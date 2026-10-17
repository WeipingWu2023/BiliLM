"""Backend boundary: orchestration consumes timestamped segments, never engine objects."""
from typing import Protocol, Callable


class ASRBackend(Protocol):
    name: str
    def transcribe(self, source, config: dict, progress: Callable, report: dict, playback) -> list[dict]: ...


class FasterWhisperBackend:
    name = 'faster-whisper'
    def transcribe(self,source,config,progress,report,playback):
        from .asr import transcribe
        return transcribe(source,config['model'],progress,config,report,playback)


class SenseVoiceBackend:
    name = 'sensevoice'
    def transcribe(self,source,config,progress,report,playback):
        from .sensevoice import transcribe
        return transcribe(source,config,progress,report,playback)


def get_backend(name):
    if name == 'faster-whisper':
        return FasterWhisperBackend()
    if name == 'sensevoice':
        return SenseVoiceBackend()
    raise ValueError('后端未安装或未通过时间戳验证；不会自动下载模型或切换识别引擎')
