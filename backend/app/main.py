import hashlib
import os
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from typing import Literal
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response, JSONResponse, FileResponse
from pydantic import BaseModel, Field
from . import db
from .ingestion import resolve, Bilibili
from .asr import MODELS
from .transcript import export
from .reasoning import answer
from .reasoning import OpenAICompatible
from .quality import ASRConfig, PROFILES
from .hardware import detect, warnings
from . import versions


@asynccontextmanager
async def lifespan(app):
    db.init()
    from .model_manager import recover
    recover()
    yield


app = FastAPI(title='BiliLM', lifespan=lifespan)
from .ground_truth_api import router as ground_truth_router
app.include_router(ground_truth_router)


@app.middleware('http')
async def local_only(request: Request, call_next):
    origin = request.headers.get('origin')
    allowed = {'http://127.0.0.1:3000','http://localhost:3000','http://127.0.0.1:8000','http://localhost:8000'}
    host = request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver') or (origin and origin not in allowed):
        return JSONResponse({'detail':'仅允许本地应用访问'},status_code=403)
    return await call_next(request)


class ImportRequest(ASRConfig):
    source: str = Field(min_length=1,max_length=2048)


class EditRequest(BaseModel):
    text: str = Field(max_length=2_000_000)
    revision: int


class ChatContext(BaseModel):
    role: Literal['user','assistant']
    content: str = Field(min_length=1,max_length=6000)


class Question(BaseModel):
    question: str = Field(min_length=1,max_length=2000)
    external: bool = False
    run_id: str | None = None
    history: list[ChatContext] = Field(default_factory=list,max_length=8)


class LearningRequest(BaseModel):
    kind: Literal['summary','mindmap']
    run_id: str | None = None
    external: bool = False
    refresh: bool = False


class DeepSeekSettings(BaseModel):
    api_key: str = Field(default='',max_length=500)
    model: str = Field(default='deepseek-flash',min_length=1,max_length=100,pattern=r'^[A-Za-z0-9._-]+$')


class ModelInstallRequest(BaseModel):
    authorized: bool = False


def video_or_404(key):
    video = db.get_video(key)
    if not video:
        raise HTTPException(404,'未找到视频')
    return video


@app.get('/api/health')
def health():
    import shutil
    from .llm_settings import public
    return {'status':'ok','ffmpeg':bool(shutil.which('ffmpeg')),'models':MODELS,
            'llm_configured':public()['configured']}


@app.get('/api/llm/settings')
def provider_settings():
    from .llm_settings import public
    return public()


@app.put('/api/llm/settings')
def save_provider_settings(body: DeepSeekSettings):
    from .llm_settings import save_deepseek
    try:
        return save_deepseek(body.api_key,body.model)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@app.get('/api/asr/hardware')
def hardware():
    info = detect()
    return {'hardware':info,'profiles':PROFILES,
            'warnings':{name:warnings(model,'auto',info) for name,model in PROFILES.items()},
            'default':'small','default_reason':'保留 MVP 默认；人工真值评测尚未完成'}


@app.post('/api/imports')
def import_video(body: ImportRequest):
    # ASRConfig validates backend/model pairs, including the optional cached SenseVoice backend.
    try:
        from .model_manager import ensure_ready
        ensure_ready(body.model_dump())
        bv, part = resolve(body.source)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except Exception as exc:
        raise HTTPException(502,'短链接访问失败；请粘贴完整 BV 链接。'+str(exc)[:200])
    key = f'{bv}:p{part}'
    return db.enqueue(key,f'https://www.bilibili.com/video/{bv}/?p={part}',bv,
                      {'kind':'bilibili','bv':bv,'part':part,'model':body.model,'config':body.model_dump(exclude={'source'})})


@app.post('/api/uploads')
async def upload(file: UploadFile = File(...), model: str = Form('small'), config: str = Form('{}')):
    import json
    try:
        settings = ASRConfig.model_validate({'model':model,**json.loads(config)}).model_dump()
        model = settings['model']
        from .model_manager import ensure_ready
        ensure_ready(settings)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except Exception:
        raise HTTPException(400,'ASR 配置无效')
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ('.mp3','.mp4','.wav','.m4a','.flac','.ogg','.webm','.mkv','.aac'):
        raise HTTPException(400,'请上传受支持的音视频文件')
    directory = db.DATA / 'uploads'
    directory.mkdir(parents=True,exist_ok=True)
    target = directory / (uuid4().hex + suffix)
    digest, size = hashlib.sha256(), 0
    try:
        with target.open('wb') as output:
            while chunk := await file.read(1024*1024):
                size += len(chunk)
                if size > 1024**3:
                    raise HTTPException(413,'文件超过 1 GB 限制')
                digest.update(chunk); output.write(chunk)
        if size == 0:
            raise HTTPException(400,'文件为空')
        key = 'local:' + digest.hexdigest()
        result = db.enqueue(key,'local-file',Path(file.filename or '本地音频').name,
                            {'kind':'local','file':target.name,'title':Path(file.filename or '本地音频').name,'model':model,'config':settings})
        if result['cached']:
            target.unlink(missing_ok=True)
        else:
            with db.connection() as con:
                payload = con.execute('SELECT payload FROM jobs WHERE id=?',(result['job_id'],)).fetchone()
            import json
            if json.loads(payload['payload'])['file'] != target.name:
                target.unlink(missing_ok=True)
        return result
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get('/api/videos')
def library():
    with db.connection() as con:
        return [dict(r) for r in con.execute('''SELECT id,title,creator,thumbnail,duration,provenance,created_at,
          CASE WHEN segments IS NULL THEN 0 ELSE 1 END AS ready,
          (SELECT status FROM jobs WHERE video_id=videos.id ORDER BY created_at DESC,rowid DESC LIMIT 1) AS status
          FROM videos ORDER BY created_at DESC,rowid DESC''')]


@app.get('/api/videos/{key}')
def get_video(key: str):
    video = video_or_404(key)
    video['runs'] = versions.list_runs(key)
    return video


@app.post('/api/videos/{key}/retranscribe')
def retranscribe(key: str, body: ASRConfig):
    import json
    video = video_or_404(key)
    from .model_manager import ensure_ready
    try:
        ensure_ready(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    with db.connection() as con:
        old = con.execute("SELECT payload FROM jobs WHERE video_id=? AND json_extract(payload,'$.kind') IN ('bilibili','local') ORDER BY created_at DESC,rowid DESC LIMIT 1",(key,)).fetchone()
    if not old:
        raise HTTPException(409,'没有可恢复的来源，请重新导入原文件')
    payload = json.loads(old['payload'])
    payload.update({'model':body.model,'config':body.model_dump(),'retranscribe':True})
    try:
        return db.enqueue(key,video['url'],video['title'],payload)
    except ValueError as exc:
        raise HTTPException(409,str(exc))


def run_or_404(rid):
    result = versions.get(rid)
    if not result:
        raise HTTPException(404,'未找到转录版本')
    return result


@app.get('/api/runs/{rid}')
def run(rid: str):
    return run_or_404(rid)


class VersionEdit(BaseModel):
    texts: list[str] = Field(max_length=100000)
    revision: int


@app.put('/api/runs/{rid}/{version}')
def edit_version(rid: str, version: str, body: VersionEdit):
    run_or_404(rid)
    try:
        revision = versions.edit(rid,version,body.texts,body.revision)
        return {'revision':revision}
    except ValueError as exc:
        raise HTTPException(409,str(exc))


@app.post('/api/runs/{rid}/proofread')
def proofread(rid: str):
    current = run_or_404(rid)
    try:
        proposals = OpenAICompatible().proofread(current['proofread'],current['config'].get('topic',''),current['config'].get('glossary',''))
        count = versions.propose(rid,proposals,current['proof_revision'])
        return {'proposals':count,'audio_verified':False,'requires_review':True}
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except Exception:
        raise HTTPException(502,'文本校对提供方失败，原文未改变')


class ReviewRequest(BaseModel):
    accept: bool


class ProofreadPipelineRequest(BaseModel):
    proof_revision: int
    readable_revision: int
    use_search: bool = False
    topic: str = Field(default='',max_length=300)
    glossary: str = Field(default='',max_length=2000)


@app.post('/api/runs/{rid}/proofread/pipeline')
def proofread_pipeline(rid: str, body: ProofreadPipelineRequest):
    current=run_or_404(rid)
    if current['proof_revision']!=body.proof_revision or current['readable_revision']!=body.readable_revision:
        raise HTTPException(409,'文稿版本已变化，请重新加载')
    from . import proofreading
    try:
        from .llm_settings import public
        if not public()['configured']: raise ValueError('请先配置 DeepSeek，再运行 AI 校对')
        return {'job_id':proofreading.enqueue(rid,body.model_dump())}
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except Exception:
        raise HTTPException(502,'AI 语境校对失败，原稿和已有文稿未改变；请检查服务配置后重试')


@app.post('/api/runs/{rid}/proofread/undo')
def undo_proofread(rid: str):
    run_or_404(rid)
    from .proofreading import undo
    try:
        undo(rid)
        return {'ok':True}
    except ValueError as exc:
        raise HTTPException(409,str(exc))


@app.post('/api/runs/{rid}/corrections/{cid}/review')
def review(rid: str,cid: str,body: ReviewRequest):
    run_or_404(rid)
    try:
        versions.review(rid,cid,body.accept)
        return {'ok':True}
    except ValueError as exc:
        raise HTTPException(409,str(exc))


class FormatRequest(BaseModel):
    revision: int
    remove_filler: bool = False


@app.post('/api/runs/{rid}/readable/format')
def format_version(rid: str,body: FormatRequest):
    run_or_404(rid)
    try:
        versions.format_readable(rid,body.revision,body.remove_filler)
        return {'ok':True}
    except ValueError as exc:
        raise HTTPException(409,str(exc))


@app.get('/api/runs/{rid}/audio')
def audio(rid: str, original: bool = False):
    current = run_or_404(rid)
    relative = current['audio'] if original else current['playback']
    if not relative:
        raise HTTPException(404,'此历史版本未保留音频；可重新转录以获取可访问音轨')
    path = (db.DATA / relative).resolve()
    if not path.is_relative_to(db.DATA) or not path.is_file():
        raise HTTPException(404,'音频文件不可用')
    return FileResponse(path,media_type='audio/wav' if not original else None,filename=path.name if original else None)


@app.get('/api/runs/{rid}/compare/{other}')
def compare(rid: str,other: str):
    from .evaluation import disagreements
    first=run_or_404(rid); second=run_or_404(other)
    if first['video_id']!=second['video_id']:
        raise HTTPException(400,'只能比较同一视频的转录')
    try:
        return disagreements(first,second)
    except ValueError as exc:
        raise HTTPException(409,str(exc))


@app.get('/api/runs/{rid}/export')
def export_version(rid: str, version: str = 'raw', format: str = 'txt'):
    import json
    current = run_or_404(rid)
    if version not in ('raw','proofread','readable') or format not in ('txt','srt','md','json'):
        raise HTTPException(400,'不支持的版本或格式')
    rows = current['raw'] if version=='raw' else current['proofread'] if version=='proofread' else current['readable_segments']
    if format=='srt' and version=='readable' and not current['mapped']:
        raise HTTPException(409,'历史自由编辑稿没有可靠片段映射；请逐段编辑后再导出 SRT')
    video = video_or_404(current['video_id'])
    data = {'title':video['title'],'url':video['url'],'provenance':current['provenance']+' / '+version,
            'segments':rows,'readable':current['readable'] if version=='readable' else '\n'.join(r['text'] for r in rows)}
    content = json.dumps(current,ensure_ascii=False,indent=2) if format=='json' else export(data,format)
    return Response(content,media_type='application/json' if format=='json' else 'text/plain; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename="bililm-{version}.{format}"'})


@app.get('/api/videos/{key}/thumbnail')
def thumbnail(key: str):
    video = video_or_404(key)
    if not video['thumbnail']:
        raise HTTPException(404,'暂无封面')
    directory = db.DATA / 'thumbnails'
    directory.mkdir(parents=True,exist_ok=True)
    target = directory / (hashlib.sha256(key.encode()).hexdigest() + '.image')
    if target.exists():
        return FileResponse(target,media_type='image/jpeg')
    adapter = Bilibili()
    try:
        url = video['thumbnail']
        if url.startswith('http://'):
            url = 'https://' + url[7:]
        url = adapter.check_cdn(url)
        with adapter.client.stream('GET',url) as response:
            response.raise_for_status()
            content_type = response.headers.get('content-type','').split(';')[0]
            if content_type not in ('image/jpeg','image/png','image/webp'):
                raise ValueError('无效图片类型')
            chunks, count = [], 0
            for chunk in response.iter_bytes():
                count += len(chunk)
                if count > 5*1024*1024:
                    raise ValueError('封面超过大小限制')
                chunks.append(chunk)
            data = b''.join(chunks)
            temporary = target.with_suffix('.'+uuid4().hex+'.tmp')
            try:
                temporary.write_bytes(data); temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return Response(data,media_type=content_type)
    except Exception:
        raise HTTPException(502,'封面暂时无法读取')
    finally:
        adapter.close()


@app.put('/api/videos/{key}/readable')
def edit(key: str, body: EditRequest):
    video = video_or_404(key)
    if not video['segments']:
        raise HTTPException(409,'转录尚未完成')
    with db.connection() as con:
        changed = con.execute('UPDATE videos SET readable=?,revision=revision+1 WHERE id=? AND revision=?',
                              (body.text,key,body.revision)).rowcount
        if not changed:
            raise HTTPException(409,'可读稿已在其他窗口修改；请重新打开后保存')
    return {'revision':body.revision+1}


@app.get('/api/videos/{key}/export')
def download(key: str, format: str = 'txt'):
    if format not in ('txt','srt','md'):
        raise HTTPException(400,'不支持的导出格式')
    video = video_or_404(key)
    if not video['segments']:
        raise HTTPException(409,'转录尚未完成')
    return Response(export(video,format),media_type='text/plain; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename="bililm.{format}"'})


@app.get('/api/jobs')
def jobs():
    with db.connection() as con:
        return [dict(r) for r in con.execute('SELECT id,video_id,status,progress,stage,error,attempts,created_at FROM jobs ORDER BY created_at DESC,rowid DESC LIMIT 100')]


@app.post('/api/jobs/{jid}/retry')
def retry(jid: str):
    with db.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        job = con.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not job:
            raise HTTPException(404,'未找到任务')
        if job['status'] != 'failed':
            raise HTTPException(409,'仅失败任务可重试')
        if con.execute("SELECT 1 FROM jobs WHERE video_id=? AND status IN ('queued','running')",(job['video_id'],)).fetchone():
            raise HTTPException(409,'该视频已有任务正在处理')
        con.execute("UPDATE jobs SET status='queued',error=NULL,progress=0,stage='等待重试' WHERE id=?",(jid,))
    return {'job_id':jid}


@app.post('/api/videos/{key}/ask')
def ask(key: str, body: Question):
    video = video_or_404(key)
    try:
        from .learning import source
        video['segments'],_=source(video,body.run_id)
        return answer(video,body.question,body.external,[entry.model_dump() for entry in body.history])
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except httpx.HTTPStatusError as exc:
        raise provider_failure(exc)
    except Exception:
        raise HTTPException(502,'AI 服务访问失败，请检查 DeepSeek 设置或网络后重试')


@app.post('/api/videos/{key}/learning')
def learning_artifact(key: str, body: LearningRequest):
    video=video_or_404(key)
    try:
        from .learning import artifact
        return artifact(video,body.kind,body.run_id,body.external,body.refresh)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except httpx.HTTPStatusError as exc:
        raise provider_failure(exc)
    except Exception:
        raise HTTPException(502,'学习材料生成失败，请检查 AI 服务连接后重试；原始文稿未改变')


@app.get('/api/videos/{key}/learning/artifacts')
def learning_saved(key: str, run_id: str | None = None):
    from .learning import saved_artifacts
    try:
        return saved_artifacts(video_or_404(key),run_id)
    except ValueError as exc:
        raise HTTPException(400,str(exc))


def provider_failure(exc):
    messages={401:'API Key 无效，请检查 DeepSeek 设置',402:'DeepSeek 账户余额不足，请检查账户',
              429:'AI 服务请求频率受限，请稍后重试',400:'AI 请求被拒绝，请检查模型名称及服务支持的参数'}
    return HTTPException(502,messages.get(exc.response.status_code,'AI 服务暂时不可用，请稍后重试'))


@app.get('/api/asr/models')
def asr_models():
    from .model_manager import catalog
    return catalog()


@app.post('/api/asr/models/{name}/install')
def install_asr_model(name: str, body: ModelInstallRequest):
    from .model_manager import install
    try:
        return install(name,body.authorized)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
