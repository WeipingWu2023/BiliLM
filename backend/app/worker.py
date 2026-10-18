import hashlib
import json
import logging
import socket
import threading
import time
from uuid import uuid4
import httpx
from . import db, versions
from .backends import get_backend
from .hardware import detect
from .ingestion import Bilibili, IngestionError
from .quality import ASRConfig
from .transcript import validate_segments


def process(job):
    payload = json.loads(job['payload'])
    key, jid = job['video_id'], job['id']
    token = job.get('lease_token')
    stopped = threading.Event()
    def renew():
        while not stopped.wait(20):
            try:
                db.heartbeat(jid,token)
            except db.LeaseLost:
                stopped.set()
    renewal = threading.Thread(target=renew,daemon=True)
    if token:
        renewal.start()
    def progress(value, stage):
        db.update_job(jid,_lease_token=token,progress=value,stage=stage)
    adapter = None
    try:
        if payload['kind']=='proofread':
            from . import proofreading
            current=versions.get(payload['rid']); options=payload['options']
            if not current or current['proof_revision']!=options['proof_revision'] or current['readable_revision']!=options['readable_revision']:
                raise ValueError('文稿版本已变化，未发出校对请求；请重新提交')
            result=proofreading.prepare(current['proofread'],db.get_video(key)['title'],
                       options.get('topic') or current['config'].get('topic',''),options.get('glossary') or current['config'].get('glossary',''),
                       options.get('use_search',False),progress,current['metrics'].get('detected_language') or current['config'].get('language','auto'))
            proofreading.apply(payload['rid'],result,options['proof_revision'],options['readable_revision'],job)
            return
        if versions.get(jid):
            db.update_job(jid,_lease_token=token,status='completed',progress=100,stage='已从缓存恢复')
            return
        progress(5,'读取来源信息')
        config = ASRConfig.model_validate(payload.get('config',{'model':payload['model'],'device':'cpu'})).model_dump()
        backend = get_backend(config['backend'])
        metrics = {}; source = None
        # Stale leases cannot write another attempt's committed media.
        attempt = jid+'-'+(token or uuid4().hex)
        playback = db.DATA/'audio'/(attempt+'.wav')
        if payload['kind']=='local':
            source = db.DATA/'uploads'/payload['file']
            metadata = {'title':payload['title']}
            rows = backend.transcribe(source,config,progress,metrics,playback)
            provenance = 'local-asr:'+config['model']
        else:
            for previous in versions.list_runs(key):
                saved = versions.get(previous['id'])
                if saved['audio'] and (db.DATA/saved['audio']).is_file():
                    source = db.DATA/saved['audio']; break
            if source:
                metadata = db.get_video(key)
                rows,language=[], ''
            else:
                adapter = Bilibili()
                metadata = adapter.metadata(payload['bv'],payload['part'])
                db.save_metadata(key,metadata,jid,token)
                progress(15,'检测已有字幕')
                rows,language = [], ''
                if not payload.get('retranscribe'):
                    try:
                        rows,language = adapter.subtitles(payload['bv'],metadata['cid'])
                        # Invalid platform subtitles must not block a valid audio fallback.
                        if rows:
                            rows = validate_segments(rows)
                    except (httpx.HTTPError, IngestionError, ValueError, KeyError) as exc:
                        metrics['subtitle_lookup'] = {'status':'failed','error_type':type(exc).__name__}
                        rows,language = [], ''
                        progress(18,'字幕读取失败，尝试平台正常提供的音轨')
            provenance = 'bilibili-subtitle:'+language
            subtitle_meta = getattr(adapter,'subtitle_provenance',None) if adapter else None
            if rows and isinstance(subtitle_meta,dict):
                metrics['subtitle_provenance']=subtitle_meta
            if not rows:
                source = source or db.DATA/'audio'/(attempt+'.m4a')
                source.parent.mkdir(parents=True,exist_ok=True)
                if not source.exists():
                    partial=source.with_suffix('.partial')
                    try:
                        adapter.audio(payload['bv'],metadata['cid'],partial,progress)
                        partial.replace(source)
                    finally:
                        partial.unlink(missing_ok=True)
                rows=backend.transcribe(source,config,progress,metrics,playback)
                provenance='bilibili-asr:'+config['model']
        rows=validate_segments(rows)
        proofreading = None
        if config.get('ai_proofread'):
            try:
                from .proofreading import prepare
                proofreading=prepare(rows,metadata['title'],config.get('topic',''),config.get('glossary',''),
                                     config.get('proofread_search',False),progress,metrics.get('detected_language') or config.get('language','auto'))
                metrics['ai_proofreading']=proofreading['summary']
            except Exception:
                # External text correction must never discard a successful ASR result.
                metrics['ai_proofreading']={'status':'failed','audio_verified':False,'notice':'AI 校对失败；原始转录已保存，请稍后在校对稿重试'}
                logging.warning('AI proofreading failed for job %s; preserving ASR output',jid)
        progress(97,'保存独立原稿、校对稿与可读稿')
        if source and source.exists():
            digest=hashlib.sha256()
            with source.open('rb') as file:
                for chunk in iter(lambda:file.read(1024*1024),b''):
                    digest.update(chunk)
            metrics['source_audio_sha256']=digest.hexdigest()
        versions.commit_job(job,metadata,rows,provenance,config,metrics,
                            source.relative_to(db.DATA).as_posix() if source and source.exists() else None,
                            playback.relative_to(db.DATA).as_posix() if playback.exists() else None,proofreading)
    except db.LeaseLost:
        logging.warning('Lease lost for job %s; result not committed',jid)
    except Exception as exc:
        logging.exception('Job %s failed',jid)
        try:
            db.update_job(jid,_lease_token=token,status='failed',stage='处理失败，可重试或导入本地文件',error=str(exc)[:1000])
        except db.LeaseLost:
            pass
    finally:
        if adapter:
            adapter.close()
        stopped.set()
        if token:
            renewal.join(timeout=1)


def main():
    db.init()
    worker_id=socket.gethostname()+'-'+uuid4().hex
    capabilities=('cpu','cuda') if detect()['cuda_devices'] else ('cpu',)
    db.recover()
    while True:
        job=db.claim(worker_id,capabilities)
        if job:
            process(job)
        else:
            time.sleep(1)


if __name__=='__main__':
    main()
