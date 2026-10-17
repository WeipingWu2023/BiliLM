import re
from urllib.parse import urlsplit, parse_qs
import httpx
import hashlib
from datetime import datetime, timezone


class IngestionError(Exception):
    pass


def parse_input(value):
    value = value.strip()
    if re.fullmatch(r'BV[0-9A-Za-z]{10}', value):
        return value, 1
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError('请输入 BV 号或标准 B 站视频链接')
    if parsed.hostname in ('b23.tv', 'bili2233.cn'):
        if not re.fullmatch(r'/[A-Za-z0-9]+/?', parsed.path):
            raise ValueError('短链接格式无效')
        return None, value
    if parsed.hostname not in ('bilibili.com', 'www.bilibili.com', 'm.bilibili.com'):
        raise ValueError('仅支持 bilibili.com 视频链接和 b23.tv / bili2233.cn 短链接')
    match = re.fullmatch(r'/video/(BV[0-9A-Za-z]{10})/?', parsed.path)
    if not match:
        raise ValueError('链接中未找到有效 BV 号')
    part = parse_qs(parsed.query).get('p', ['1'])[0]
    if not part.isdigit() or not 1 <= int(part) <= 10000:
        raise ValueError('分 P 参数无效')
    return match[1], int(part)


def resolve(value):
    bv, part = parse_input(value)
    if bv:
        return bv, part
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        current = part
        for _ in range(5):
            candidate, selected = parse_input(current)
            if candidate:
                return candidate, selected
            response = client.get(current)
            if response.status_code not in (301,302,303,307,308):
                response.raise_for_status()
            location = response.headers.get('location')
            if not location:
                break
            # Validate next target before making any request (no arbitrary redirects).
            parse_input(location)
            current = location
    raise IngestionError('SHORT_LINK: 短链接未能解析，请使用完整视频链接')


class Bilibili:
    def __init__(self):
        self.subtitle_provenance = None
        self.client = httpx.Client(timeout=30, follow_redirects=False, trust_env=False,
                                  headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'})

    def close(self):
        self.client.close()

    def api(self, path, **params):
        response = self.client.get('https://api.bilibili.com' + path, params=params)
        if response.status_code in (401,403,412,429):
            raise IngestionError(f'ACCESS_{response.status_code}: 平台限制访问；请导入已授权的本地文件')
        response.raise_for_status()
        body = response.json()
        if body.get('code') != 0:
            raise IngestionError(f"PLATFORM_{body.get('code')}: {body.get('message','无法访问此视频')}；可尝试本地导入")
        return body['data']

    def metadata(self, bv, part):
        data = self.api('/x/web-interface/view', bvid=bv)
        if part > len(data['pages']):
            raise IngestionError('PART_NOT_FOUND: 视频不存在指定分 P')
        page = data['pages'][part-1]
        return {'title': data['title'] + (f" · P{part} {page['part']}" if len(data['pages']) > 1 else ''),
                'creator': data['owner']['name'], 'thumbnail': data['pic'], 'duration': page['duration'], 'cid': page['cid']}

    @staticmethod
    def check_cdn(url):
        if url.startswith('//'):
            url = 'https:' + url
        parsed = urlsplit(url)
        hosts = ('hdslb.com','bilivideo.com','bilivideo.cn','bilibili.com')
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443) or not any(parsed.hostname == h or (parsed.hostname or '').endswith('.'+h) for h in hosts):
            raise IngestionError('UNSAFE_MEDIA: 不支持的媒体地址')
        return url

    def subtitles(self, bv, cid):
        data = self.api('/x/player/v2', bvid=bv, cid=cid)
        tracks = data.get('subtitle',{}).get('subtitles',[])
        tracks.sort(key=lambda t: 0 if 'zh' in t.get('lan','') else 1)
        for track in tracks:
            response = self.client.get(self.check_cdn(track['subtitle_url']))
            response.raise_for_status()
            rows = response.json().get('body',[])
            if rows:
                self.subtitle_provenance = {'platform':'bilibili','track_id':track.get('id'),'language':track.get('lan'),
                    'automatic_label':track.get('lan','').startswith('ai-'),'audio_verified':False,
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),'subtitle_url_sha256':hashlib.sha256(track['subtitle_url'].encode()).hexdigest()}
                return [{'start': r['from'], 'end': r['to'], 'text': r['content']} for r in rows], track.get('lan','unknown')
        return [], ''

    def audio(self, bv, cid, target, progress):
        data = self.api('/x/player/playurl', bvid=bv, cid=cid, fnval=16, qn=16, fourk=0)
        streams = data.get('dash',{}).get('audio',[])
        if not streams:
            raise IngestionError('AUDIO_UNAVAILABLE: 无可访问音轨；请导入已授权的本地音视频')
        stream = min(streams, key=lambda s:s.get('bandwidth',0))
        candidates = []
        for field in ('baseUrl','base_url','backupUrl','backup_url'):
            values = stream.get(field) or []
            candidates.extend([values] if isinstance(values,str) else values)
        attempted = False
        for candidate in dict.fromkeys(candidates):
            try:
                url = self.check_cdn(candidate)
            except (IngestionError,ValueError):
                continue
            attempted = True
            try:
                with self.client.stream('GET', url) as response:
                    response.raise_for_status()
                    total, count = int(response.headers.get('content-length',0)), 0
                    with target.open('wb') as file:
                        for chunk in response.iter_bytes(65536):
                            count += len(chunk)
                            if count > 1024**3:
                                raise IngestionError('MEDIA_TOO_LARGE: 音轨超过 1 GB 限制')
                            file.write(chunk)
                            if total:
                                progress(min(49, 20 + int(29*count/total)), '下载可访问音轨')
                    return target
            except httpx.HTTPError:
                # Signed platform URLs may have multiple CDN endpoints. Validate every
                # fallback independently and never follow arbitrary HTTP redirects.
                target.unlink(missing_ok=True)
        if not attempted:
            raise IngestionError('UNSAFE_MEDIA: 平台返回的音轨均不符合支持的 HTTPS 地址规则；请导入已授权的本地文件')
        raise IngestionError('AUDIO_DOWNLOAD_FAILED: 可访问音轨地址均下载失败；请重试或导入已授权的本地文件')
