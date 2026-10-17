import re
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from . import db, ground_truth as gt

router=APIRouter(prefix='/api/ground-truth')


def checked(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(409,str(exc))
    except FileNotFoundError:
        raise HTTPException(400,'缺少 FFmpeg/ffprobe 或原媒体文件，请检查安装与来源')
    except subprocess.TimeoutExpired:
        raise HTTPException(408,'媒体读取或裁切超时。槽位没有被替换，请缩短范围或更换本地文件后重试')
    except subprocess.CalledProcessError:
        raise HTTPException(400,'无法读取或裁切此媒体。槽位没有被替换，请检查文件是否包含可播放音轨')


class PrepareRequest(BaseModel):
    video_id: str = Field(max_length=200)
    run_id: str | None = Field(default=None,max_length=100)
    start: float = Field(ge=0)
    duration: float = Field(ge=60,le=180)
    revision: int = Field(ge=0)
    authorized: bool = False


class ReferenceSegment(BaseModel):
    start: float = Field(ge=0,le=180)
    end: float = Field(gt=0,le=180.05)
    text: str = Field(max_length=15000)


class Annotation(BaseModel):
    start: float = Field(ge=0,le=180)
    end: float = Field(gt=0,le=180.05)
    kind: Literal['cantonese_error','missing_speech','hallucinated_speech','terminology','uncertain']
    model: str = Field(default='',max_length=100)
    note: str = Field(default='',max_length=1000)


class ReferenceRequest(BaseModel):
    revision: int = Field(ge=0)
    title: str = Field(min_length=1,max_length=200)
    stratum: Literal['mandarin','cantonese','zh-en-mixed']
    category: str = Field(default='',max_length=120)
    terms: list[str] = Field(default_factory=list,max_length=100)
    reference: str = Field(default='',max_length=15000)
    reference_segments: list[ReferenceSegment] = Field(default_factory=list,max_length=200)
    notes: str = Field(default='',max_length=10000)
    annotations: list[Annotation] = Field(default_factory=list,max_length=200)


class VerifyRequest(BaseModel):
    revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1,max_length=80)
    listened: bool = False
    language_confirmed: bool = False


@router.get('/clips')
def clips():
    return gt.list_clips()


@router.get('/clips/{cid}')
def clip(cid: str):
    return checked(lambda:gt.get(cid))


@router.get('/clips/{cid}/audio')
def audio(cid: str):
    path=checked(lambda:gt.audio_path(gt.get(cid)))
    return FileResponse(path,media_type='audio/wav')


@router.get('/clips/{cid}/history')
def history(cid: str):
    return checked(lambda:gt.history(cid))


@router.post('/clips/{cid}/prepare')
def prepare(cid: str,body: PrepareRequest):
    def action():
        path,run,source=gt.source_for_video(body.video_id,body.run_id)
        return gt.prepare(cid,path,body.start,body.duration,body.revision,body.authorized,run,source)
    return checked(action)


@router.post('/clips/{cid}/upload')
async def upload(cid: str,file: UploadFile = File(...),start: float = Form(0),duration: float = Form(60),revision: int = Form(...),authorized: bool = Form(False)):
    checked(lambda:gt.get(cid))
    if not authorized:
        await file.close()
        raise HTTPException(400,'请确认此文件可用于本地评测')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.wav','.mp3','.mp4','.m4a','.flac','.ogg','.webm','.mkv','.aac'):
        await file.close()
        raise HTTPException(400,'不支持的音视频格式')
    directory=db.DATA/'ground-truth'/'sources'; directory.mkdir(parents=True,exist_ok=True)
    source=directory/(uuid4().hex+suffix); count=0
    try:
        with source.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                count+=len(chunk)
                if count>1024**3:
                    raise HTTPException(413,'文件超过 1 GB 限制')
                output.write(chunk)
        provenance={'kind':'local-file','filename':Path(file.filename or '').name,'retained_original':source.relative_to(db.DATA).as_posix()}
        return checked(lambda:gt.prepare(cid,source,start,duration,revision,authorized,None,provenance))
    except Exception:
        source.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.put('/clips/{cid}/reference')
def save(cid: str,body: ReferenceRequest):
    return checked(lambda:gt.save(cid,body.model_dump()))


@router.post('/clips/{cid}/verify')
def verify(cid: str,body: VerifyRequest):
    return checked(lambda:gt.verify(cid,body.revision,body.reviewer,body.listened,body.language_confirmed))


@router.post('/export')
def export():
    return checked(gt.export_manifest)


@router.get('/datasets/{eid}')
def dataset(eid: str):
    if not re.fullmatch(r'[a-f0-9]{32}',eid):
        raise HTTPException(404,'未找到数据集')
    path=db.DATA/'ground-truth'/('dataset-'+eid+'.json')
    if not path.is_file():
        raise HTTPException(404,'未找到数据集')
    return FileResponse(path,media_type='application/json',filename=path.name)
