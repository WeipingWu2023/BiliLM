"""Nine review slots, immutable clip audio, explicit human verification. No inference."""
import hashlib
import json
import math
import subprocess
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from . import db, versions

STRATA = {'mandarin':'普通话','cantonese':'粤语','zh-en-mixed':'中英混合'}


def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS benchmark_clips (
      id TEXT PRIMARY KEY, stratum TEXT NOT NULL, title TEXT NOT NULL, category TEXT DEFAULT '',
      terms TEXT DEFAULT '[]', audio TEXT, audio_sha256 TEXT, duration REAL, source TEXT DEFAULT '{}',
      machine TEXT DEFAULT '[]', reference TEXT DEFAULT '', reference_segments TEXT DEFAULT '[]',
      notes TEXT DEFAULT '', annotations TEXT DEFAULT '[]', revision INTEGER DEFAULT 0,
      state TEXT DEFAULT 'empty', reviewer TEXT DEFAULT '', verified_at TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS benchmark_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT, clip_id TEXT NOT NULL, event TEXT NOT NULL,
      snapshot TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TRIGGER IF NOT EXISTS immutable_benchmark_history_update BEFORE UPDATE ON benchmark_history
      BEGIN SELECT RAISE(ABORT,'benchmark history is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS immutable_benchmark_history_delete BEFORE DELETE ON benchmark_history
      BEGIN SELECT RAISE(ABORT,'benchmark history is append-only'); END;
    ''')
    for language,label in STRATA.items():
        for number in range(1,4):
            con.execute('INSERT OR IGNORE INTO benchmark_clips(id,stratum,title) VALUES(?,?,?)',
                        (f'{language}-{number:02}',language,f'{label} {number:02}'))


def decode(row):
    clip=dict(row)
    for field in ('terms','source','machine','reference_segments','annotations'):
        clip[field]=json.loads(clip[field])
    clip['human_verified']=clip['state']=='verified'
    return clip


def list_clips():
    with db.connection() as con:
        return [decode(row) for row in con.execute('SELECT * FROM benchmark_clips ORDER BY id')]


def get(cid):
    with db.connection() as con:
        row=con.execute('SELECT * FROM benchmark_clips WHERE id=?',(cid,)).fetchone()
    if not row:
        raise ValueError('未找到评测槽位')
    return decode(row)


def _log(con,clip,event):
    con.execute('INSERT INTO benchmark_history(clip_id,event,snapshot) VALUES(?,?,?)',
                (clip['id'],event,json.dumps(clip,ensure_ascii=False)))


def history(cid):
    get(cid)
    with db.connection() as con:
        return [dict(row) for row in con.execute('SELECT * FROM benchmark_history WHERE clip_id=? ORDER BY id',(cid,))]


def audio_path(clip):
    if not clip['audio']:
        raise ValueError('此槽位尚未准备音频')
    path=(db.DATA/clip['audio']).resolve()
    if not path.is_relative_to(db.DATA) or not path.is_file():
        raise ValueError('评测音频不可用')
    return path


def _hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def _duration(path):
    result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],check=True,capture_output=True,text=True,timeout=30)
    value=float(result.stdout.strip())
    if not math.isfinite(value) or value<=0:
        raise ValueError('无法确定音频时长')
    return value


def source_for_video(key,rid=None):
    video=db.get_video(key)
    if not video:
        raise ValueError('未找到已有 BiliLM 来源，请先导入或上传已授权的本地文件')
    candidates=[versions.get(rid)] if rid else [versions.get(row['id']) for row in versions.list_runs(key)]
    if rid and (not candidates[0] or candidates[0]['video_id']!=key):
        raise ValueError('指定转录记录不属于此来源')
    for run in candidates:
        if not run or run['video_id']!=key:
            continue
        for field in ('audio','playback'):
            if run[field]:
                path=(db.DATA/run[field]).resolve()
                if path.is_relative_to(db.DATA) and path.is_file():
                    return path,run,{'kind':'bililm','video_id':key,'run_id':run['id'],'title':video['title'],
                                    'url':video['url'],'source_audio_kind':field}
    # Older runs did not keep audio. Do not silently fetch or transcribe anything here.
    if key.startswith('local:'):
        with db.connection() as con:
            jobs=con.execute('SELECT payload FROM jobs WHERE video_id=? ORDER BY created_at DESC,rowid DESC',(key,)).fetchall()
        for job in jobs:
            payload=json.loads(job['payload'])
            if payload.get('kind')=='local':
                path=(db.DATA/'uploads'/payload['file']).resolve()
                if path.is_relative_to(db.DATA) and path.is_file():
                    return path,candidates[0] if candidates else None,{'kind':'bililm','video_id':key,'title':video['title'],'url':video['url']}
    raise ValueError('此历史来源没有保留音轨。请使用已授权本地文件，或在原笔记重新转录并保留音频后再选择；本步骤不会自动联网获取。')


def prepare(cid,source,start,duration,revision,authorized,run=None,provenance=None):
    clip=get(cid)
    if not authorized:
        raise ValueError('请明确确认此音频可用于本地评测')
    if clip['revision']!=revision:
        raise ValueError('槽位已变化，请重新加载')
    if not math.isfinite(start+duration) or start<0 or not 60<=duration<=180:
        raise ValueError('首批片段长度应为 60–180 秒，开始时间不能为负')
    source=Path(source).resolve()
    if start+duration>_duration(source)+0.05:
        raise ValueError('选取范围超过原媒体时长；请缩短或选择其他来源')
    directory=db.DATA/'ground-truth'; directory.mkdir(parents=True,exist_ok=True)
    target=directory/(uuid4().hex+'.wav')
    try:
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(source),'-t',str(duration),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(target)],check=True,capture_output=True,timeout=120)
        with wave.open(str(target),'rb') as audio:
            actual=audio.getnframes()/audio.getframerate()
        if actual<59.9 or abs(actual-duration)>0.1:
            raise ValueError('实际裁切时长与请求不符，没有替换原槽位')
        machine=[]
        if run:
            for row in run['raw']:
                if row['end']>start and row['start']<start+actual:
                    machine.append({'start':max(0,row['start']-start),'end':min(actual,row['end']-start),
                                    'text':row['text'],'boundary_truncated':row['start']<start or row['end']>start+actual})
        origin={**(provenance or {}),'source_start':start,'source_duration':actual,'source_sha256':_hash(source),
                'authorized':True,'machine_kind':'projected_source_run_display_only' if run else 'not_generated',
                'machine_provenance':run['provenance'] if run else None,
                'preprocessing':{'sample_rate':16000,'channels':1,'codec':'pcm_s16le','denoise':False}}
        with db.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            row=con.execute('SELECT * FROM benchmark_clips WHERE id=?',(cid,)).fetchone()
            if row['revision']!=revision:
                raise ValueError('裁切期间槽位已变化，没有覆盖现有内容')
            _log(con,decode(row),'before_prepare')
            con.execute("UPDATE benchmark_clips SET audio=?,audio_sha256=?,duration=?,source=?,machine=?,reference='',reference_segments='[]',annotations='[]',notes='',revision=revision+1,state='draft',reviewer='',verified_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (target.relative_to(db.DATA).as_posix(),_hash(target),actual,json.dumps(origin,ensure_ascii=False),json.dumps(machine,ensure_ascii=False),cid))
        return get(cid)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def save(cid,body):
    if body['stratum'] not in STRATA:
        raise ValueError('不支持的语言类别')
    clip=get(cid); duration=clip['duration'] or 0
    if any(len(term)>128 for term in body['terms']):
        raise ValueError('单个术语最多 128 个字符')
    if body.get('reference_segments'):
        from .evaluation import normalize
        if normalize(''.join(r['text'] for r in body['reference_segments']))!=normalize(body['reference']):
            raise ValueError('人工时间段文字必须与参考稿一致，不能伪造时间映射')
    for row in body.get('reference_segments',[]):
        if not math.isfinite(row['start']+row['end']) or not 0<=row['start']<row['end']<=duration+0.05:
            raise ValueError('人工时间段超出音频范围')
    for row in body.get('annotations',[]):
        if not 0<=row['start']<row['end']<=duration+0.05:
            raise ValueError('错误标注时间范围无效')
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM benchmark_clips WHERE id=?',(cid,)).fetchone()
        if not row or row['revision']!=body['revision']:
            raise ValueError('草稿已变化，请重新加载后保存')
        _log(con,decode(row),'before_save')
        con.execute("UPDATE benchmark_clips SET title=?,stratum=?,category=?,terms=?,reference=?,reference_segments=?,notes=?,annotations=?,revision=revision+1,state=?,reviewer='',verified_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (body['title'],body['stratum'],body['category'],json.dumps(body['terms'],ensure_ascii=False),body['reference'],
                     json.dumps(body.get('reference_segments',[]),ensure_ascii=False),body['notes'],json.dumps(body.get('annotations',[]),ensure_ascii=False),'draft' if row['audio'] else 'empty',cid))
    return get(cid)


def verify(cid,revision,reviewer,listened,language_confirmed):
    clip=get(cid)
    if not listened or not language_confirmed or not reviewer.strip():
        raise ValueError('需要核对人姓名、逐句听音确认和实际语言确认')
    if not clip['reference'].strip() or not clip['category'].strip():
        raise ValueError('请先保存非空人工参考稿和视频类别')
    if not clip['source'].get('authorized'):
        raise ValueError('此音频尚未确认使用授权')
    if any(row.get('kind')=='uncertain' for row in clip['annotations']):
        raise ValueError('仍有不确定片段，请核对并移除不确定标注后再确认真值')
    if _hash(audio_path(clip))!=clip['audio_sha256']:
        raise ValueError('音频内容已变化，不能验证旧参考稿')
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM benchmark_clips WHERE id=?',(cid,)).fetchone()
        if row['revision']!=revision:
            raise ValueError('参考稿已变化，请重新加载后核对')
        _log(con,decode(row),'before_verify')
        con.execute("UPDATE benchmark_clips SET state='verified',reviewer=?,verified_at=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reviewer.strip(),datetime.now(timezone.utc).isoformat(),cid))
    return get(cid)


def export_manifest():
    clips=[]
    for clip in list_clips():
        if not clip['human_verified']:
            continue
        path=audio_path(clip)
        if _hash(path)!=clip['audio_sha256']:
            raise ValueError('音频已变化，拒绝导出真值清单')
        clips.append({'id':clip['id'],'stratum':clip['stratum'],'category':clip['category'],'audio':path.name,
                      'audio_sha256':clip['audio_sha256'],'reference':clip['reference'],'reference_sha256':hashlib.sha256(clip['reference'].encode()).hexdigest(),
                      'reference_segments':clip['reference_segments'],'terms':clip['terms'],'human_verified':True,
                      'reviewer':clip['reviewer'],'reviewed_at':clip['verified_at'],'revision':clip['revision'],
                      'language':'zh' if clip['stratum']=='mandarin' else 'auto','annotations':clip['annotations'],'source':clip['source']})
    if not clips:
        raise ValueError('当前没有人工核对完成的样本；不会生成可计分真值')
    directory=db.DATA/'ground-truth'; eid=uuid4().hex
    manifest={'schema_version':1,'dataset_id':eid,'clips':clips,'normalization':'app.evaluation.normalize','created_at':datetime.now(timezone.utc).isoformat()}
    path=directory/('dataset-'+eid+'.json')
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'dataset_id':eid,'manifest_path':str(path),'verified_clips':len(clips),'manifest':manifest}
