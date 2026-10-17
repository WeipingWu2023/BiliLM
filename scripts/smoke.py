"""Live acceptance, never injects fake subtitles. Run after start.cmd."""
import argparse
import json
import time
from pathlib import Path
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('source',help='Authorized public Bilibili URL or BV ID')
parser.add_argument('--model',default='tiny')
parser.add_argument('--timeout',type=int,default=1800)
parser.add_argument('--local',action='store_true',help='Import an authorized local media file instead of a URL')
args = parser.parse_args()
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30,trust_env=False) as client:
    def submit():
        if args.local:
            source=Path(args.source)
            with source.open('rb') as file:
                return client.post('/api/uploads',files={'file':(source.name,file)},data={'model':args.model})
        return client.post('/api/imports',json={'source':args.source,'model':args.model})
    response = submit()
    response.raise_for_status(); result=response.json()
    deadline=time.monotonic()+args.timeout
    while result['job_id'] and time.monotonic()<deadline:
        response=client.get('/api/jobs'); response.raise_for_status()
        job=next(j for j in response.json() if j['id']==result['job_id'])
        print(job['status'],job['progress'],job['stage'],flush=True)
        if job['status']=='failed':
            raise SystemExit('LIVE ACCEPTANCE FAILED: '+job['error'])
        if job['status']=='completed':
            break
        time.sleep(3)
    from urllib.parse import quote
    path='/api/videos/'+quote(result['video_id'],safe='')
    response=client.get(path); response.raise_for_status(); video=response.json()
    assert video['segments'] and video['readable'],'No saved transcript (job may have timed out)'
    output=Path(__file__).resolve().parents[1]/'data'/'smoke'/video['id'].replace(':','_')
    output.mkdir(parents=True,exist_ok=True)
    for fmt in ('txt','md','srt'):
        response=client.get(path+'/export',params={'format':fmt}); response.raise_for_status()
        assert response.text.strip()
        (output/f'transcript.{fmt}').write_text(response.text,encoding='utf-8')
    response=submit(); response.raise_for_status(); cached=response.json()
    assert cached['cached'] is True
    summary={'id':video['id'],'title':video['title'],'provenance':video['provenance'],'segments':len(video['segments']),'cache_verified':True}
    (output/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
