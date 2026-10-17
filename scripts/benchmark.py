"""Dry by default. No unverified samples contribute accuracy numbers."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.benchmark_report import backend_for, build_report, render_markdown, verified_clips


def worker(request, output):
    """One model/clip per process: another resident model cannot contaminate peak RSS."""
    from app.backends import get_backend
    from app.quality import ASRConfig
    config = ASRConfig.model_validate(request['config'])
    predicted = {'config':config.model_dump(), 'source_audio_sha256':request['source_audio_sha256'],
                 'provenance':'raw-asr', 'metrics':{}}
    began = time.perf_counter()
    try:
        if config.backend == 'faster-whisper' and not config.allow_model_download:
            from app import db
            from faster_whisper.utils import download_model
            # Explicit cache check also protects legacy small-model loading behavior.
            download_model(config.model, cache_dir=str(db.DATA / 'models'), local_files_only=True,
                           revision=config.model_revision)
        predicted['segments'] = get_backend(config.backend).transcribe(
            Path(request['audio']), config.model_dump(), lambda *_:None, predicted['metrics'], None)
    except Exception as exc:
        predicted.update({'status':'unavailable', 'error':str(exc)})
    predicted['metrics']['worker_wall_seconds'] = time.perf_counter() - began
    predicted['metrics']['process_isolation'] = 'fresh process per clip/model'
    predicted['metrics'].setdefault('memory_measurement', 'process RSS sampled every 100ms; includes runtime/model; not GPU VRAM')
    Path(output).write_text(json.dumps(predicted, ensure_ascii=False, indent=2), encoding='utf-8')


def run_prediction(audio, digest, config):
    with tempfile.TemporaryDirectory(prefix='bililm-benchmark-') as temporary:
        request = Path(temporary) / 'request.json'
        response = Path(temporary) / 'response.json'
        request.write_text(json.dumps({'audio':str(audio), 'source_audio_sha256':digest, 'config':config}, ensure_ascii=False), encoding='utf-8')
        environment = os.environ.copy()
        if not config['allow_model_download']:
            environment['HF_HUB_OFFLINE'] = '1'
        command = [sys.executable, str(Path(__file__).resolve()), '--worker-request', str(request), '--output', str(response)]
        began = time.perf_counter()
        process = subprocess.run(command, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if process.returncode or not response.is_file():
            return {'config':config, 'status':'unavailable', 'error':(process.stderr or process.stdout)[-4000:] or 'benchmark worker failed'}
        result = json.loads(response.read_text(encoding='utf-8'))
        result['metrics']['process_wall_seconds'] = time.perf_counter() - began
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='人工真值优先的可复现 ASR 比较；默认不下载、不推理')
    parser.add_argument('manifest', nargs='?')
    parser.add_argument('--predictions', help='JSON: clip id -> predictions；必须含 source_audio_sha256、segments、config、metrics、provenance')
    parser.add_argument('--run', action='store_true', help='明确执行已人工审核的片段；可能长时间占用 CPU/GPU，运行前需获用户批准')
    parser.add_argument('--models', nargs='+', default=['small', 'SenseVoiceSmall'],
                        choices=['tiny', 'base', 'small', 'medium', 'large-v3', 'turbo', 'SenseVoiceSmall'])
    parser.add_argument('--device', default='auto', choices=['auto', 'cpu', 'cuda'])
    parser.add_argument('--beam', type=int, default=5, choices=[5, 8])
    parser.add_argument('--language', choices=['auto', 'zh', 'yue', 'en'], help='未指定时使用每个片段的语言设置')
    parser.add_argument('--topic', default='')
    parser.add_argument('--no-glossary', action='store_true', help='停用词表提示以做独立对照')
    parser.add_argument('--no-vad', action='store_true', help='停用 Whisper VAD 以做独立对照')
    parser.add_argument('--model-revision', help='固定模型版本；两种后端版本不同，应分别运行并合并 predictions')
    parser.add_argument('--allow-model-download', action='store_true', help='额外下载授权；SenseVoice 仍只加载独立安装的本地快照')
    parser.add_argument('--output', default='data/benchmark-report.json')
    parser.add_argument('--markdown', help='中文报告路径，默认与 JSON 同名 .md')
    parser.add_argument('--worker-request', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_request:
        worker(json.loads(Path(args.worker_request).read_text(encoding='utf-8')), args.output)
        return
    if not args.manifest:
        parser.error('需要 manifest 路径')
    if args.allow_model_download and not args.run:
        parser.error('--allow-model-download 只能与经批准的 --run 一起使用')
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    supplied = json.loads(Path(args.predictions).read_text(encoding='utf-8')) if args.predictions else {}
    if not isinstance(supplied, dict):
        parser.error('--predictions 顶层必须为 clip id 字典')
    if args.run:
        from app.quality import ASRConfig
        verified, _ = verified_clips(manifest, manifest_path.parent)
        for clip, audio, digest in verified:
            predictions = supplied.setdefault(clip['id'], [])
            if isinstance(predictions, dict):
                predictions = supplied[clip['id']] = [predictions]
            if not isinstance(predictions, list):
                parser.error('每个 clip predictions 必须为对象或数组')
            for model in args.models:
                config = ASRConfig(backend=backend_for(model), model=model, device=args.device, beam_size=args.beam,
                                   allow_model_download=args.allow_model_download, require_cached_model=not args.allow_model_download,
                                   model_revision=args.model_revision, language=args.language or clip.get('language', 'auto'),
                                   topic=args.topic, glossary='' if args.no_glossary else ', '.join(clip.get('terms', [])),
                                   vad_filter=not args.no_vad)
                print(f"Transcribing {clip['id']} / {config.backend} / {model} (approved --run)", flush=True)
                predictions.append(run_prediction(audio, digest, config.model_dump()))
    report = build_report(manifest, manifest_path.parent, supplied, args.models)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    markdown = Path(args.markdown) if args.markdown else output.with_suffix('.md')
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_markdown(report), encoding='utf-8')
    print(json.dumps({'verified_clips':report['verified_clips'], 'rejected_clips':len(report['rejected_clips']),
                      'scored':sum(row['status'] == 'scored' for row in report['results']),
                      'report':str(output), 'markdown':str(markdown), 'inference_started':bool(args.run and report['verified_clips'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
