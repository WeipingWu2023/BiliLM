import math
import re


def validate_segments(rows):
    result = []
    for row in rows:
        start, end = float(row['start']), float(row['end'])
        text = str(row['text']).strip()
        if not math.isfinite(start + end) or start < 0 or end <= start:
            raise ValueError('字幕时间轴无效')
        if text:
            segment = {'start': start, 'end': end, 'text': text}
            for field in ('avg_logprob','no_speech_prob','compression_ratio'):
                if field in row and math.isfinite(float(row[field])):
                    segment[field] = float(row[field])
            result.append(segment)
    result.sort(key=lambda x: x['start'])
    if not result:
        raise ValueError('未识别到有效语音或字幕')
    return result


def clean(rows):
    paragraphs, current = [], ''
    for row in rows:
        text = re.sub(r'\s+', ' ', row['text']).strip()
        if not re.search(r'[。！？.!?，,；;：:]$', text):
            text += '。'
        current += (' ' if current else '') + text
        if len(current) >= 180:
            paragraphs.append(current)
            current = ''
    if current:
        paragraphs.append(current)
    return '\n\n'.join(paragraphs)


def stamp(seconds, srt=False):
    milliseconds = round(seconds * 1000)
    h, rest = divmod(milliseconds, 3600000)
    m, rest = divmod(rest, 60000)
    s, ms = divmod(rest, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}' if srt else f'{h:02}:{m:02}:{s:02}'


def export(video, fmt):
    if fmt == 'srt':
        return '\n\n'.join(f"{i}\n{stamp(r['start'], True)} --> {stamp(r['end'], True)}\n{r['text']}" for i, r in enumerate(video['segments'], 1)) + '\n'
    if fmt == 'md':
        return f"# {video['title']}\n\n来源：{video['url']}\n\n{video['readable']}\n"
    return video['readable']
