"""Extract an authorized clip and create an explicitly UNVERIFIED review manifest."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('audio')
parser.add_argument('--stratum',required=True,choices=['mandarin','cantonese','zh-en-mixed'])
parser.add_argument('--id',required=True)
parser.add_argument('--start',type=float,default=0)
parser.add_argument('--duration',type=float,default=15)
parser.add_argument('--output',default='data/benchmark-candidates')
args=parser.parse_args()
if not 0<args.duration<=60 or args.start<0 or not args.id.replace('-','').replace('_','').isalnum():
    raise SystemExit('Use a safe clip ID, start >= 0 and 0 < duration <= 60 seconds')
source=Path(args.audio).resolve(); output=Path(args.output).resolve(); output.mkdir(parents=True,exist_ok=True)
clip=output/(args.id+'.wav')
if clip.exists(): raise SystemExit('Clip already exists; choose a new ID to preserve reviewed audio')
subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(source),'-ss',str(args.start),'-t',str(args.duration),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(clip)],check=True,timeout=120)
data={'schema_version':1,'status':'pending_human_review_not_an_accuracy_dataset','clips':[{'id':args.id,'stratum':args.stratum,'audio':clip.name,
      'audio_sha256':hashlib.sha256(clip.read_bytes()).hexdigest(),'language':'zh' if args.stratum=='mandarin' else 'auto',
      'source':str(source),'source_start':args.start,'reference':'','reference_segments':[],'terms':[],'silence_intervals':[],
      'human_verified':False,'reviewer':'','reviewed_at':None}]}
manifest=output/(args.id+'.pending.json'); manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared for human listening review only:',manifest)
