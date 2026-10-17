"""Offline benchmark reporting; scores require a reviewed, hash-matched audio reference."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path

from .evaluation import score

STRATA = {'mandarin':'普通话', 'cantonese':'粤语', 'zh-en-mixed':'中英混合'}
DEFAULT_MODELS = ['small', 'SenseVoiceSmall']


def backend_for(model):
    return 'sensevoice' if model == 'SenseVoiceSmall' else 'faster-whisper'


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verified_clips(manifest, directory):
    accepted, rejected, seen = [], [], set()
    for clip in manifest.get('clips', []):
        clip_id = clip.get('id')
        reason = None
        if not clip_id or clip_id in seen:
            reason = '缺少或重复 clip id'
        elif clip.get('stratum') not in STRATA:
            reason = '未知语言类别'
        elif clip.get('human_verified') is not True or not str(clip.get('reviewer') or '').strip() or not str(clip.get('reference') or '').strip():
            reason = '需要人工逐字核对、reviewer 与非空真值；机器草稿不能计分'
        seen.add(clip_id)
        audio = (Path(directory) / str(clip.get('audio') or '')).resolve()
        if not reason and not audio.is_file():
            reason = '真实音频不存在'
        digest = file_sha256(audio) if not reason else None
        if not reason and digest != clip.get('audio_sha256'):
            reason = '音频 SHA256 与已审核真值不匹配'
        if reason:
            rejected.append({'id':clip_id, 'stratum':clip.get('stratum'), 'reason':reason})
        else:
            accepted.append((clip, audio, digest))
    return accepted, rejected


def _identity(config, execution, provenance, clip_id):
    # Preserve every requested setting; include the resolved execution settings that affect accuracy.
    effective = {key:execution.get(key) for key in (
        'device', 'compute_type', 'resolved_model_revision', 'weights_sha256', 'model_files_sha256',
        'versions', 'preprocessing', 'decoding', 'decoding_effective', 'timestamp_quality',
        'window_seconds', 'window_overlap_seconds')}
    identity = {'config':config, 'effective':effective, 'provenance':provenance}
    if not config or not config.get('backend') or not config.get('model'):
        # Unknown configurations cannot silently combine unrelated external experiments.
        identity['unknown_configuration_clip'] = clip_id
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12], identity


def _segments(rows):
    if not isinstance(rows, list):
        raise ValueError('segments 必须为数组')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('text'), str):
            raise ValueError('每段需要原始文本')
        start, end = row.get('start'), row.get('end')
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError('每段需要有效的起止秒数')
    return rows


def build_report(manifest, directory, predictions=None, models=None):
    models = models or DEFAULT_MODELS
    verified, rejected = verified_clips(manifest, directory)
    results, groups, missing = [], {}, []
    supplied = predictions or {}
    for clip, _, digest in verified:
        entries = supplied.get(clip['id'], [])
        entries = [entries] if isinstance(entries, dict) else entries
        if not isinstance(entries, list):
            entries = [{'status':'rejected', 'error':'prediction 必须为对象或数组'}]
        completed = set()
        for predicted in entries:
            base = {'clip':clip['id'], 'stratum':clip['stratum'], 'reference_revision':clip.get('revision'),
                    'reference':clip['reference'], 'reference_segments':clip.get('reference_segments', []),
                    'source_audio_sha256':digest, 'category':clip.get('category', '')}
            if not isinstance(predicted, dict):
                results.append({**base, 'status':'rejected', 'error':'prediction 不是对象'})
                continue
            config = predicted.get('config') or {}
            execution = predicted.get('metrics') or {}
            if not isinstance(config, dict) or not isinstance(execution, dict):
                results.append({**base, 'status':'rejected', 'error':'config/metrics 必须为对象'})
                continue
            base.update({'config':config, 'execution':execution, 'provenance':predicted.get('provenance', 'unknown')})
            if predicted.get('status') in ('unavailable', 'rejected'):
                results.append({**base, 'status':predicted['status'], 'error':predicted.get('error', '')})
                continue
            if predicted.get('source_audio_sha256') != digest:
                results.append({**base, 'status':'rejected', 'error':'prediction source audio hash 缺少或不匹配'})
                continue
            try:
                segments = _segments(predicted.get('segments'))
                coarse = execution.get('timestamp_quality') == 'input-window-only'
                scores = score(clip['reference'], segments, clip.get('terms', []),
                               [] if coarse else clip.get('reference_segments', []),
                               [] if coarse else clip.get('silence_intervals', []))
            except (ValueError, TypeError, KeyError) as exc:
                results.append({**base, 'status':'rejected', 'error':str(exc)})
                continue
            if coarse:
                for field in ('timestamp_errors', 'timestamp_mae_seconds', 'missing_reference_segments', 'speech_in_verified_silence_candidates'):
                    scores[field] = None
                scores['timestamp_policy'] = '输入窗口边界不是语音对齐；时间准确率、缺段覆盖与静音输出未测'
            identity, settings = _identity(config, execution, base['provenance'], clip['id'])
            group_id = clip['stratum'] + '/' + identity
            scoped = [item for item in clip.get('annotations', []) if isinstance(item, dict) and item.get('model') == config.get('model')]
            review = predicted.get('human_audio_review') or {}
            if not isinstance(review, dict) or review.get('audio_verified') is not True or not str(review.get('reviewer') or '').strip():
                review = None
            result = {**base, 'status':'scored', 'cohort':group_id, 'segments':segments,
                      'prediction':' '.join(row['text'] for row in segments), 'scores':scores,
                      'human_annotations':scoped, 'human_audio_review':review,
                      'reference_has_silence_intervals':bool(clip.get('silence_intervals'))}
            results.append(result)
            completed.add((config.get('backend'), config.get('model')))
            group = groups.setdefault(group_id, {'stratum':clip['stratum'], 'settings':settings, 'clip_ids':[]})
            group['clip_ids'].append(clip['id'])
        for model in models:
            if (backend_for(model), model) not in completed:
                missing.append({'clip':clip['id'], 'stratum':clip['stratum'], 'backend':backend_for(model), 'model':model,
                                'reason':'没有可计分、同音频 hash 的预测（未运行/失败/被拒绝）'})
    for group_id, group in groups.items():
        rows = [row for row in results if row.get('cohort') == group_id]
        group['summary'] = summarize(rows)
        group['duplicate_clip_predictions'] = sorted(key for key, count in Counter(group['clip_ids']).items() if count > 1)
        if group['duplicate_clip_predictions']:
            # Repeated trials must become separate explicit configurations/trial IDs, not overweight one clip.
            group['summary'] = None
        group['clip_ids'] = sorted(set(group['clip_ids']))
    paired = []
    for (a_id, a), (b_id, b) in itertools.combinations(groups.items(), 2):
        if a['stratum'] != b['stratum']:
            continue
        common = sorted(set(a['clip_ids']) & set(b['clip_ids']))
        paired.append({'stratum':a['stratum'], 'cohorts':[a_id, b_id], 'common_clips':common,
                       'unpaired_clips':sorted(set(a['clip_ids']) ^ set(b['clip_ids'])),
                       'summaries':{key:summarize([row for row in results if row.get('cohort') == key and row['clip'] in common])
                                    for key in (a_id, b_id)} if common and a['summary'] is not None and b['summary'] is not None else None})
    return {'schema_version':2, 'generated_at':datetime.now(timezone.utc).isoformat(),
            'manifest':manifest, 'verified_clips':len(verified), 'rejected_clips':rejected,
            'requested_models':models, 'results':results, 'groups':groups, 'paired_coverage':paired,
            'missing_predictions':missing, 'default_recommendation':None,
            'normalization':'CER: NFKC、小写、去空格和标点，保留简繁差异；WER: 仅英文/数字 token，不猜中文分词。',
            'note':'未自动推荐模型；ASR、平台字幕和文字校对按 provenance 与完整配置分组，候选诊断不是人工确认错误。'}


def summarize(rows):
    cer = [row['scores']['cer'] for row in rows]
    wer = [row['scores']['english_wer'] for row in rows if row['scores']['english_wer']]
    terms = [term for row in rows for term in row['scores']['terms']]
    characters = sum(item['reference_units'] for item in cer)
    words = sum(item['reference_units'] for item in wer)
    wanted = sum(item['reference_count'] for item in terms)
    predicted = sum(item['prediction_count'] for item in terms)
    matched = sum(item['matched_count'] for item in terms)
    elapsed = [row['execution']['elapsed_seconds'] for row in rows if isinstance(row['execution'].get('elapsed_seconds'), (int, float))]
    rss = [row['execution']['peak_rss_bytes'] for row in rows if isinstance(row['execution'].get('peak_rss_bytes'), (int, float))]
    boundaries = [boundary for row in rows for boundary in row['scores']['timestamp_errors'] or []]
    annotations = Counter(item.get('kind') for row in rows for item in row['human_annotations'])
    aligned = [row for row in rows if row['reference_segments'] and row['scores']['missing_reference_segments'] is not None]
    silence = [row for row in rows if row['reference_has_silence_intervals'] and row['scores']['speech_in_verified_silence_candidates'] is not None]
    return {'clips':len(rows), 'character_errors':sum(item['distance'] for item in cer), 'reference_characters':characters,
            'micro_cer':sum(item['distance'] for item in cer) / characters if characters else None,
            'english_word_errors':sum(item['distance'] for item in wer), 'reference_english_words':words,
            'micro_english_wer':sum(item['distance'] for item in wer) / words if words else None,
            'term_reference_count':wanted, 'term_prediction_count':predicted, 'term_matched_count':matched,
            'term_recall':matched / wanted if wanted else None, 'term_precision':matched / predicted if predicted else None,
            'elapsed_seconds_total':sum(elapsed) if elapsed else None, 'timed_clips':len(elapsed),
            'peak_rss_bytes':max(rss) if rss else None, 'memory_measured_clips':len(rss),
            'timestamp_mae_seconds':sum(item['start_error_seconds'] + item['end_error_seconds'] for item in boundaries) / (2 * len(boundaries)) if boundaries else None,
            'missing_coverage_candidates':sum(len(row['scores']['missing_reference_segments']) for row in aligned) if aligned else None,
            'speech_in_verified_silence_candidates':sum(len(row['scores']['speech_in_verified_silence_candidates']) for row in silence) if silence else None,
            'adjacent_duplicate_candidates':sum(len(row['scores']['adjacent_duplicate_candidates']) for row in rows),
            'overlap_candidates':sum(len(row['scores']['overlap_candidates']) for row in rows),
            'human_annotation_counts':dict(annotations)}


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def _rate(value):
    return '未测' if value is None else f'{value:.2%}'


def render_markdown(report):
    verified = report['verified_clips']
    lines = ['# BiliLM Phase 2：真实 ASR 准确率比较', '',
             f"人工验证样本 **{verified}** 条；清单共 {len(report['manifest'].get('clips', []))} 条。未审核、缺少音频或 hash 不符的样本不计分。", '',
             '当前没有模型准确率排名，也没有修改默认模型。' if not verified else '以下指标仅适用于列明的已审核片段；没有自动选择默认模型。', '',
             '## 各语言与实验配置', '',
             '| 语言 | 后端 / 模型 / 配置 | 可计分片段 | CER | 英文 WER | 术语召回 / 精确 | 转录总秒数 | 最大 RSS MiB | 时间 MAE 秒 |',
             '|---|---|---:|---:|---:|---|---:|---:|---:|']
    for stratum, label in STRATA.items():
        groups = [(key, group) for key, group in report['groups'].items() if group['stratum'] == stratum]
        for key, group in groups:
            config = group['settings']['config']
            summary = group['summary']
            title = f"{config.get('backend', 'unknown')} / {config.get('model', 'external')} / {group['settings']['provenance']} / {key.split('/')[-1]}"
            if summary is None:
                lines.append(f'| {label} | {_cell(title)}（重复预测，拒绝聚合） | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 |')
                continue
            elapsed = '未测' if summary['elapsed_seconds_total'] is None else f"{summary['elapsed_seconds_total']:.2f}（{summary['timed_clips']} 段）"
            rss = '未测' if summary['peak_rss_bytes'] is None else f"{summary['peak_rss_bytes'] / 2**20:.1f}（{summary['memory_measured_clips']} 段）"
            timing = '未测' if summary['timestamp_mae_seconds'] is None else f"{summary['timestamp_mae_seconds']:.3f}"
            lines.append(f"| {label} | {_cell(title)} | {summary['clips']} | {_rate(summary['micro_cer'])} | {_rate(summary['micro_english_wer'])} | {_rate(summary['term_recall'])} / {_rate(summary['term_precision'])} | {elapsed} | {rss} | {timing} |")
        for model in report['requested_models']:
            if not any(group['settings']['config'].get('model') == model and group['settings']['config'].get('backend') == backend_for(model) for _, group in groups):
                lines.append(f'| {label} | {backend_for(model)} / {model} | 0 | 未测 | 未测 | 未测 | 未测 | 未测 | 未测 |')
    lines += ['', 'CER/英文 WER 使用总编辑距离 ÷ 总参考单位，未平均片段百分比。术语按人工真值中实际出现次数计数；词表提示不等于正确识别。', '',
              '## 配对覆盖与可复现信息', '',
              f"可计分预测 {sum(row['status'] == 'scored' for row in report['results'])} 项；缺少请求模型预测 {len(report['missing_predictions'])} 项。"]
    for pair in report['paired_coverage']:
        lines.append(f"- {STRATA[pair['stratum']]}：{' ↔ '.join(pair['cohorts'])}，共同片段 {len(pair['common_clips'])}，未配对 {len(pair['unpaired_clips'])}。")
        if pair['summaries']:
            lines += ['', '| 仅共同片段的配置 | 片段 | CER | 英文 WER | 术语召回 / 精确 |', '|---|---:|---:|---:|---|']
            for key, summary in pair['summaries'].items():
                lines.append(f"| {key} | {summary['clips']} | {_rate(summary['micro_cer'])} | {_rate(summary['micro_english_wer'])} | {_rate(summary['term_recall'])} / {_rate(summary['term_precision'])} |")
            lines.append('')
    if not report['paired_coverage']:
        lines.append('尚无两个可比较实验的共同音频，不能得出模型优劣结论。')
    for key, group in report['groups'].items():
        lines += ['', f'配置 `{key}`（不得与其他配置混合；原始文本、完整指标和配置保存在 JSON）：', '',
                  '```json', json.dumps(group['settings'], ensure_ascii=False, indent=2), '```']
    lines += ['', '## 错误示例与人工审听', '',
              '以下为原始文本摘录；文字差异、CER 插入/删除、重复、重叠及缺段覆盖均是候选诊断。幻觉、省略、粤语词法/方言错误必须重听确认。未注明模型的人工注释不归因到某个模型。']
    if report['groups']:
        lines += ['', '| 配置 | 缺参考窗候选 | 相邻重复候选 | 重叠候选 | 静音内输出候选 | 人工模型注释（不是错误率） |', '|---|---:|---:|---:|---:|---|']
        for key, group in report['groups'].items():
            summary = group['summary']
            if summary is None:
                continue
            missing = summary['missing_coverage_candidates']
            silence = summary['speech_in_verified_silence_candidates']
            annotations = summary['human_annotation_counts']
            human = '未做系统人工错误审查' if not annotations else '；'.join(f'{kind}: {count}' for kind, count in annotations.items())
            lines.append(f"| {key} | {'未测' if missing is None else missing} | {summary['adjacent_duplicate_candidates']} | {summary['overlap_candidates']} | {'未测' if silence is None else silence} | {_cell(human)} |")
    scored = [row for row in report['results'] if row['status'] == 'scored']
    if not scored:
        lines.append('未测：当前没有可展示的已验证识别错误，不使用虚构示例。')
    for row in scored[:9]:
        scores = row['scores']
        lines += ['', f"- `{row['clip']}` / `{row['cohort']}`：参考（最多 180 字）“{_cell(row['reference'][:180])}”；识别（最多 180 字）“{_cell(row['prediction'][:180])}”。",
                  f"  字符替换/删除/插入：{scores['cer']['substitutions']} / {scores['cer']['deletions']} / {scores['cer']['insertions']}；人工模型注释 {len(row['human_annotations'])} 条。"]
        for item in row['human_annotations']:
            lines.append(f"  - 人工 `{_cell(item.get('kind', ''))}` [{item.get('start', '?')}–{item.get('end', '?')} 秒]：{_cell(item.get('note', ''))}")
    failed = [row for row in report['results'] if row['status'] != 'scored']
    if failed:
        lines += ['', '运行失败/拒绝的预测（未计入准确率）：']
        lines += [f"- `{row['clip']}`：{_cell(row.get('error', row['status']))}" for row in failed]
    lines += ['', '## 局限与下一次实验', '',
              '- 首批目标为普通话、粤语、中英混合各 3 段，每段约 1–3 分钟；9 段不足以代表平台、口音、噪声与课程类型，不报告泛化准确率或显著性。',
              '- '+report['normalization'],
              '- SenseVoiceSmall 当前仅提供输入窗口时间，不把窗口边缘作为语音对齐；其时间准确率、静音输出与覆盖缺段指标标为未测。',
              '- 每个模型、每个片段在独立进程内运行；耗时包含本次后端模型加载、预处理与转录，另存进程总时长。RSS 为 100ms 采样的进程驻留内存，可能漏掉瞬时峰值，包含运行时且不是 GPU 显存。',
              '- 先由人工完成逐字真值与术语核对，再以相同音频 SHA256 比较 Whisper small 与 SenseVoiceSmall；配置、权重 hash、版本和原始输出留档。模型提示/VAD/切窗不同属于后端基线差异，不能单独归因为模型权重。',
              '- 在同一语言层、相同片段集合审听省略/幻觉/粤语差异，之后才固定单一因素做 beam、语言、术语或切窗消融。文字校对与平台字幕需独立 provenance，不能算作原始 ASR 提升。',
              '- 无人工参考、缺少配对预测或模型尚未获准下载时，继续显示“未测”；不会替换默认 small，也不会自动开始下载或长任务。', '']
    return '\n'.join(lines)
