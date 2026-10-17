"""Optional, offline-only SenseVoice adapter. Inference never downloads model files."""
import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import wave

from . import db
from .hardware import detect, rss_bytes
from .quality import ASRConfig

REPOSITORY = 'FunAudioLLM/SenseVoiceSmall'
BPE_FILE = 'chn_jpn_yue_eng_ko_spectok.bpe.model'
REQUIRED_FILES = ('config.yaml','configuration.json','model.pt',BPE_FILE,'am.mvn')
WINDOW_SECONDS = 30
_cached = None
_cached_key = None
_cached_metadata = {}


def model_directory():
    # Trusted server configuration only; HTTP clients cannot select arbitrary model paths.
    return Path(os.getenv('BILILM_SENSEVOICE_MODEL_DIR', db.DATA/'models'/'sensevoice-small')).resolve()


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(revision=None):
    directory = model_directory()
    if not all((directory/name).is_file() and (directory/name).stat().st_size for name in REQUIRED_FILES):
        raise RuntimeError('MODEL_NOT_CACHED: SenseVoiceSmall 本地快照不完整；请在批准下载后执行独立安装命令。转录不会联网下载。')
    metadata_file = directory/'bililm-snapshot.json'
    metadata = json.loads(metadata_file.read_text(encoding='utf-8')) if metadata_file.exists() else {}
    if revision and metadata.get('revision') != revision:
        raise RuntimeError('MODEL_REVISION_MISMATCH: 本地 SenseVoice 快照与指定版本不符；没有联网下载或切换版本。')
    return directory, metadata


def model(device='auto', revision=None):
    global _cached, _cached_key, _cached_metadata
    directory, metadata = snapshot(revision)
    try:
        import torch
        from funasr import AutoModel
        from omegaconf import OmegaConf
    except ImportError as exc:
        raise RuntimeError('SENSEVOICE_DEPENDENCY_MISSING: 可选 SenseVoice 依赖未安装；请先批准安装匹配的 PyTorch/torchaudio 与 requirements-sensevoice.txt。') from exc
    actual_device = ('cuda' if torch.cuda.is_available() else 'cpu') if device == 'auto' else device
    if actual_device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA_UNAVAILABLE: 当前 PyTorch 未提供可用 CUDA；请明确选择 CPU 或安装对应 GPU 运行时。')
    fingerprint = tuple((name,(directory/name).stat().st_size,(directory/name).stat().st_mtime_ns) for name in REQUIRED_FILES)
    key = (str(directory),fingerprint,actual_device,revision,metadata.get('revision'))
    if _cached_key == key:
        return _cached, actual_device, dict(_cached_metadata)
    _cached = None; _cached_key = None; gc.collect()
    loaded = OmegaConf.to_container(OmegaConf.load(directory/'config.yaml'),resolve=True)
    expected = {'model':'SenseVoiceSmall','encoder':'SenseVoiceEncoderSmall','tokenizer':'SentencepiecesTokenizer','frontend':'WavFrontend'}
    if not isinstance(loaded,dict) or any(loaded.get(name) != value for name,value in expected.items()):
        raise RuntimeError('INVALID_MODEL_CONFIG: 仅支持官方 SenseVoiceSmall 内置架构，不执行快照中的远程代码。')
    # Supplying model_conf bypasses FunASR hub resolution entirely (pinned 1.4.14).
    # Whitelist inference components instead of loading arbitrary auxiliary models/config hooks.
    settings = {name:loaded[name] for name in (*expected,'model_conf','encoder_conf','tokenizer_conf','frontend_conf')}
    settings['tokenizer_conf'] = {**settings['tokenizer_conf'],'bpemodel':str(directory/BPE_FILE)}
    settings['frontend_conf'] = {**settings['frontend_conf'],'cmvn_file':str(directory/'am.mvn')}
    _cached = AutoModel(**settings, model_path=str(directory),init_param=str(directory/'model.pt'),
                        device=actual_device,trust_remote_code=False,disable_update=True,
                        disable_pbar=True,vad_model=None,punc_model=None,spk_model=None,
                        ignore_init_mismatch=False,ncpu=max(1,min(8,(os.cpu_count() or 2)-1)),seed=0)
    _cached_metadata = {'model_repository':REPOSITORY,'resolved_model_revision':metadata.get('revision'),
                        'weights_sha256':sha256(directory/'model.pt'),
                        'model_files_sha256':{name:sha256(directory/name) for name in REQUIRED_FILES if name!='model.pt'},
                        'device':actual_device,'compute_type':'float32',
                        'versions':{name:importlib.metadata.version(name) for name in ('funasr','torch','torchaudio','numpy','sentencepiece')}}
    _cached_key = key
    return _cached, actual_device, dict(_cached_metadata)


def transcribe(source, config, progress, report=None, playback=None):
    options = ASRConfig.model_validate(config)
    if options.backend != 'sensevoice':
        raise ValueError('SenseVoice 需要 backend=sensevoice 与 model=SenseVoiceSmall')
    # Fail before FFmpeg/importing optional runtimes when unapproved files are absent.
    snapshot(options.model_revision)
    source = Path(source)
    if playback is None:
        (db.DATA/'tmp').mkdir(parents=True,exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix='bililm-sensevoice-',dir=db.DATA/'tmp') if playback is None else None
    wav = Path(temporary.name)/'audio.wav' if temporary else Path(playback)
    if wav.resolve() == source.resolve():
        if temporary: temporary.cleanup()
        raise ValueError('输出播放音频不能覆盖原始来源音频')
    wav.parent.mkdir(parents=True,exist_ok=True)
    began = time.perf_counter(); peak = [rss_bytes() or 0]; stop = threading.Event()
    def sample_memory():
        while not stop.wait(0.1):
            peak[0] = max(peak[0],rss_bytes() or 0)
    monitor = threading.Thread(target=sample_memory,daemon=True); monitor.start()
    try:
        progress(50,'FFmpeg 提取音频 · 保留来源文件')
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],
                       check=True,capture_output=True,timeout=1800)
        progress(55,'加载本地 SenseVoiceSmall · 无网络下载')
        engine,device,metadata = model(options.device,options.model_revision)
        import numpy as np
        rows,outputs = [],[]
        decoding = options.decode_options()
        with wave.open(str(wav),'rb') as audio:
            if audio.getframerate()!=16000 or audio.getnchannels()!=1 or audio.getsampwidth()!=2:
                raise ValueError('INVALID_PCM: SenseVoice 输入应为 16kHz 单声道 PCM16')
            frames = audio.getnframes(); duration=frames/16000
            for offset in range(0,frames,WINDOW_SECONDS*16000):
                data = audio.readframes(WINDOW_SECONDS*16000)
                samples = np.frombuffer(data,dtype='<i2').astype(np.float32)/32768.0
                start,end = offset/16000,(offset+len(samples))/16000
                result = engine.generate(input=samples,cache={},**decoding)
                if not isinstance(result,list) or len(result)!=1 or not isinstance(result[0].get('text'),str):
                    raise RuntimeError('INVALID_ASR_OUTPUT: SenseVoice 未返回对应输入窗的文本；没有静默丢弃窗口。')
                tagged = result[0]['text']
                # Strip control tags only; no emoji insertion, ITN, glossary rewrite or deduplication.
                text = re.sub(r'<\|[^<>]*\|>','',tagged).strip()
                outputs.append({'start':start,'end':end,'model_text':tagged,'text':text})
                if text:
                    rows.append({'start':start,'end':end,'text':text})
                progress(min(94,55+int(39*end/max(duration,0.001))),f'{device.upper()} SenseVoice · 输入窗时间（非逐词对齐）')
        if report is not None:
            report.update(metadata)
            report.update({'elapsed_seconds':time.perf_counter()-began,'peak_rss_bytes':max(peak[0],rss_bytes() or 0),
                           'memory_measurement':'process RSS sampled every 100ms; includes runtime/model; not GPU VRAM',
                           'duration_seconds':duration,'hardware':detect(),'decoding':decoding,'decoding_effective':decoding,
                           'timestamp_quality':'input-window-only','window_seconds':WINDOW_SECONDS,'window_overlap_seconds':0,
                           'raw_model_outputs':outputs,
                           'preprocessing':{'sample_rate':16000,'channels':1,'codec':'pcm_s16le','denoise':False,'vad':False,
                                            'ffmpeg_version':subprocess.run(['ffmpeg','-version'],capture_output=True,text=True,timeout=5).stdout.splitlines()[0]},
                           'warnings':['SenseVoice 时间戳仅表示最多 30 秒输入窗口，不表示逐词/语音边界；固定切窗可能切断词语。',
                                       'Whisper beam、VAD、topic/glossary 提示与 multilingual 参数不用于此后端；原配置仅保留供追溯。',
                                       '未添加外部 VAD、标点、热词替换或对齐模型；控制标签原文保存在 raw_model_outputs。']})
        return rows
    except FileNotFoundError as exc:
        raise RuntimeError('FFMPEG_MISSING: 请安装 FFmpeg 并加入 PATH') from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('INVALID_MEDIA: FFmpeg 无法读取来源文件') from exc
    finally:
        stop.set(); monitor.join(timeout=1)
        if temporary: temporary.cleanup()


def download_snapshot(revision):
    """Explicit model preparation only. Never called during transcription."""
    if not re.fullmatch(r'[0-9a-f]{40}',revision):
        raise ValueError('下载必须指定 Hugging Face 模型的完整 40 位 commit，不能使用可变 main/tag')
    directory = model_directory()
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError('模型目录非空；拒绝覆盖已有快照。请由管理员选择新的 BILILM_SENSEVOICE_MODEL_DIR。')
    from huggingface_hub import snapshot_download
    # Incomplete transfers stay in a revision-specific staging directory, so retry
    # can resume safely without ever modifying an active model snapshot.
    staging = directory.with_name(directory.name+'.download-'+revision)
    snapshot_download(REPOSITORY,revision=revision,local_dir=str(staging),allow_patterns=list(REQUIRED_FILES))
    missing = [name for name in REQUIRED_FILES if not (staging/name).is_file() or not (staging/name).stat().st_size]
    if missing: raise RuntimeError('下载快照不完整：'+', '.join(missing))
    (staging/'bililm-snapshot.json').write_text(json.dumps({'repository':REPOSITORY,'revision':revision,
        'files_sha256':{name:sha256(staging/name) for name in REQUIRED_FILES}},ensure_ascii=False,indent=2),encoding='utf-8')
    if directory.exists():
        directory.rmdir()  # Empty destinations only; never delete a model recursively.
    staging.replace(directory)
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SenseVoice 可选模型维护命令（不会启动转录）')
    parser.add_argument('--download',action='store_true',help='明确执行一次获批准的下载')
    parser.add_argument('--revision',help='已批准的官方模型 40 位 commit')
    args = parser.parse_args()
    if not args.download or not args.revision:
        parser.error('仅在用户批准后使用 --download --revision <完整 commit>')
    print(download_snapshot(args.revision))
