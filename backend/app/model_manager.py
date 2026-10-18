"""Explicit local model preparation, separate from video ingestion and ASR."""
import importlib.util
import threading
from pathlib import Path
from . import db
from .asr import MODELS

SIZES={'tiny':'约 80 MB','base':'约 150 MB','small':'约 500 MB','medium':'约 1.5 GB','large-v3':'约 3 GB','turbo':'约 1.6 GB','SenseVoiceSmall':'约 936 MB（另需运行依赖）'}


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS model_installations (
        model TEXT PRIMARY KEY, state TEXT NOT NULL, error TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')


def recover():
    with db.connection() as con:
        con.execute("UPDATE model_installations SET state='failed',error='服务重启，下载中断；点击重试可复用已下载缓存' WHERE state='downloading'")


def cached(model):
    if model=='SenseVoiceSmall':
        from .sensevoice import snapshot
        try: snapshot(); return True
        except RuntimeError: return False
    from faster_whisper.utils import download_model
    try:
        directory=Path(download_model(model,cache_dir=str(db.DATA/'models'),local_files_only=True))
        return all((directory/file).is_file() and (directory/file).stat().st_size for file in ('config.json','model.bin','tokenizer.json')) and any(directory.glob('vocabulary.*'))
    except Exception:
        return False


def catalog():
    with db.connection() as con:
        installations={row['model']:dict(row) for row in con.execute('SELECT * FROM model_installations')}
    result=[]
    for name in (*MODELS,'SenseVoiceSmall'):
        ready=cached(name)
        runtime=name!='SenseVoiceSmall' or all(importlib.util.find_spec(package) for package in ('funasr','torch','torchaudio'))
        record=installations.get(name,{})
        result.append({'model':name,'backend':'sensevoice' if name=='SenseVoiceSmall' else 'faster-whisper',
                       'cached':bool(ready),'runtime_ready':bool(runtime),'usable':bool(ready and runtime),
                       'size':SIZES[name],'state':'ready' if ready and runtime else record.get('state','not_installed'),
                       'error':None if ready and runtime else record.get('error'),'note':'需安装可选运行依赖；不能将它等同于更高等级的 Whisper' if not runtime else ''})
    return result


def download(name):
    try:
        if name=='SenseVoiceSmall':
            from .sensevoice import download_snapshot
            download_snapshot('3847d57b6bdf2dd8875cb1508d2af43d80a16bf7')
        else:
            from faster_whisper.utils import download_model
            download_model(name,cache_dir=str(db.DATA/'models'),local_files_only=False)
        if not cached(name):
            raise ValueError('下载文件不完整，请重试')
        state,error='ready',None
    except Exception:
        state,error='failed','模型下载未完成，请检查网络、磁盘空间后重试；已下载文件会保留供复用'
    with db.connection() as con:
        con.execute('UPDATE model_installations SET state=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE model=?',(state,error,name))


def install(name, authorized):
    if name not in SIZES:
        raise ValueError('不支持的模型')
    if not authorized:
        raise ValueError('请明确确认下载模型文件')
    row=next(item for item in catalog() if item['model']==name)
    if not row['runtime_ready']:
        raise ValueError('SenseVoice 还需安装可选运行依赖。当前可直接安装并使用 medium、large-v3 或 turbo')
    if row['usable']:
        return {'model':name,'state':'ready'}
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        old=con.execute('SELECT state FROM model_installations WHERE model=?',(name,)).fetchone()
        if old and old['state']=='downloading':
            return {'model':name,'state':'downloading'}
        con.execute("INSERT INTO model_installations(model,state,error) VALUES(?,'downloading',NULL) ON CONFLICT(model) DO UPDATE SET state='downloading',error=NULL,updated_at=CURRENT_TIMESTAMP",(name,))
    threading.Thread(target=download,args=(name,),daemon=True).start()
    return {'model':name,'state':'downloading'}


def ensure_ready(config):
    if config.get('ai_proofread'):
        from .llm_settings import public
        if not public()['configured']:
            raise ValueError('请先在来源问答配置 DeepSeek，或取消转录后 AI 校对；仍可只做本地转录')
    name=config['model']
    if name=='SenseVoiceSmall':
        row=next(item for item in catalog() if item['model']==name)
        if not row['usable']:
            raise ValueError('SenseVoiceSmall 尚未安装完整模型和运行依赖。请在模型管理查看状态，或选择可用 Whisper 模型')
    elif name not in ('tiny','base','small') and not config.get('allow_model_download') and not cached(name):
        raise ValueError(f'{name} 尚未安装。请先点击“下载所选模型”，或明确允许首次下载后再提交转录')
