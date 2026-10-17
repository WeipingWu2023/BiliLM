import os
import subprocess
import wave
import time
import threading
import gc
import hashlib
import importlib.metadata
import inspect
from . import db
from .hardware import detect, rss_bytes
from .quality import ASRConfig

MODELS = ('tiny','base','small','medium','large-v3','turbo')
_cached = None
_cached_key = None
_cached_metadata = {}


def model(size, device='cpu', revision=None, allow_download=False):
    global _cached, _cached_key, _cached_metadata
    if _cached_key == (size,device,revision):
        return _cached
    _cached = None; _cached_key = None; gc.collect()
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    try:
        location = download_model(size,cache_dir=str(db.DATA/'models'),local_files_only=not allow_download,revision=revision)
    except Exception as exc:
        raise RuntimeError('MODEL_NOT_CACHED: 模型/指定版本尚未缓存。请明确允许下载后再转录；没有自动换模型。') from exc
    _cached = WhisperModel(location, device=device, compute_type='int8' if device == 'cpu' else 'float16',
                        cpu_threads=max(1, min(8, (os.cpu_count() or 2)-1)),
                        download_root=str(db.DATA / 'models'))
    from pathlib import Path
    weights = Path(location)/'model.bin'
    digest = hashlib.sha256()
    with weights.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    _cached_metadata = {'resolved_model_revision':Path(location).name,'weights_sha256':digest.hexdigest()}
    _cached_key = (size,device,revision)
    return _cached


def transcribe(source, size, progress, config=None, report=None, retain_audio=None):
    if size not in MODELS:
        raise ValueError('不支持的 Whisper 模型')
    options = ASRConfig.model_validate(config or {'model':size,'device':'cpu'})
    size = options.model
    hardware = detect()
    device = ('cuda' if hardware['cuda_devices'] else 'cpu') if options.device == 'auto' else options.device
    if device == 'cuda' and not hardware['cuda_devices']:
        raise RuntimeError('CUDA_UNAVAILABLE: 未检测到兼容 CUDA，请选择 CPU')
    wav = retain_audio or source.with_suffix('.asr.wav')
    wav.parent.mkdir(parents=True,exist_ok=True)
    began = time.perf_counter(); peak = [rss_bytes() or 0]; stop = threading.Event()
    def sample_memory():
        while not stop.wait(0.1):
            peak[0] = max(peak[0],rss_bytes() or 0)
    monitor = threading.Thread(target=sample_memory,daemon=True); monitor.start()
    progress(50, 'FFmpeg 提取音频')
    try:
        subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',str(wav)],
                       check=True, capture_output=True, timeout=1800)
        progress(55, f'加载 {size} 模型（首次需下载） · {device}')
        # FFmpeg already decoded the media. Avoid a redundant PyAV decode (API varies by version).
        import numpy as np
        with wave.open(str(wav), 'rb') as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        # Keep first-time small/tiny/base MVP downloads; large models require explicit permission.
        engine = model(size,device,options.model_revision,not options.require_cached_model and (options.allow_model_download or size in ('tiny','base','small')))
        segments, info = engine.transcribe(samples, **options.decode_options())
        result = []
        for segment in segments:
            row = {'start':segment.start,'end':segment.end,'text':segment.text}
            for field in ('avg_logprob','no_speech_prob','compression_ratio'):
                if hasattr(segment,field):
                    row[field] = getattr(segment,field)
            result.append(row)
            progress(min(94,55+int(39*segment.end/max(1,info.duration))), f'{device.upper()} 本地语音识别')
        if report is not None:
            report.update({'elapsed_seconds':time.perf_counter()-began,'peak_rss_bytes':max(peak[0],rss_bytes() or 0),
                           'duration_seconds':info.duration,'duration_after_vad':getattr(info,'duration_after_vad',None),
                           'detected_language':getattr(info,'language',None),'language_probability':getattr(info,'language_probability',None),
                           'device':device,'compute_type':'int8' if device == 'cpu' else 'float16','hardware':hardware})
            report.update(_cached_metadata)
            report['versions'] = {p:importlib.metadata.version(p) for p in ('faster-whisper','ctranslate2','numpy')}
            report['preprocessing'] = {'sample_rate':16000,'channels':1,'codec':'pcm_s16le','denoise':False,'ffmpeg_version':subprocess.run(['ffmpeg','-version'],capture_output=True,text=True,timeout=5).stdout.splitlines()[0]}
            report['decoding'] = options.decode_options()
            from faster_whisper import WhisperModel
            effective = {name:p.default for name,p in inspect.signature(WhisperModel.transcribe).parameters.items() if p.default is not inspect.Parameter.empty}
            effective.update(options.decode_options())
            report['decoding_effective'] = effective
        return result
    except FileNotFoundError as exc:
        raise RuntimeError('FFMPEG_MISSING: 请安装 FFmpeg 并加入 PATH') from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('INVALID_MEDIA: FFmpeg 无法读取此文件；请检查音视频格式') from exc
    finally:
        stop.set(); monitor.join(timeout=1)
        if not retain_audio:
            wav.unlink(missing_ok=True)
