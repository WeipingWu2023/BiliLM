from typing import Literal
from pydantic import BaseModel, Field, model_validator

PROFILES = {'fast':'small','balanced':'medium','accuracy':'large-v3','turbo':'turbo'}


class ASRConfig(BaseModel):
    backend: Literal['faster-whisper','sensevoice'] = 'faster-whisper'
    model: Literal['tiny','base','small','medium','large-v3','turbo','SenseVoiceSmall'] = 'small'
    profile: Literal['fast','balanced','accuracy','turbo'] | None = None
    device: Literal['auto','cpu','cuda'] = 'auto'
    language: Literal['auto','zh','yue','en'] = 'auto'
    model_revision: str | None = Field(default=None,max_length=100,pattern=r'^[A-Za-z0-9._-]+$')
    allow_model_download: bool = False
    require_cached_model: bool = False
    multilingual: bool = False
    beam_size: Literal[5,8] = 5
    topic: str = Field(default='',max_length=300)
    glossary: str = Field(default='',max_length=2000)
    ai_proofread: bool = False
    auto_finalize: bool = False
    proofread_search: bool = False
    vad_filter: bool = True
    vad_threshold: float = Field(default=0.5,ge=0.1,le=0.9)
    speech_pad_ms: int = Field(default=400,ge=0,le=2000)
    min_silence_duration_ms: int = Field(default=2000,ge=100,le=5000)

    @model_validator(mode='after')
    def select_profile(self):
        if self.proofread_search and not self.ai_proofread:
            raise ValueError('联网核对专名需要先启用 AI 校对')
        if self.backend == 'sensevoice' and self.profile:
            raise ValueError('Whisper 质量档位不能用于 SenseVoice；请直接选择 SenseVoiceSmall')
        if self.profile:
            self.model = PROFILES[self.profile]
        if (self.backend == 'sensevoice') != (self.model == 'SenseVoiceSmall'):
            raise ValueError('SenseVoice 后端必须配对 SenseVoiceSmall；Whisper 模型必须使用 faster-whisper 后端')
        if self.language != 'auto' and self.multilingual:
            raise ValueError('逐段多语言检测需要 language=auto')
        return self

    def decode_options(self):
        if self.backend == 'sensevoice':
            # Built-in SenseVoice uses CTC greedy decoding; Whisper prompts/beam/VAD do not apply.
            return {'language':self.language,'use_itn':False,'output_timestamp':False,'batch_size':1}
        prompt = '\n'.join(part for part in (
            ('主题：'+self.topic.strip()) if self.topic.strip() else '',
            ('参考术语（仅在实际听到时使用）：'+self.glossary.strip()) if self.glossary.strip() else '') if part)
        return {'language':None if self.language == 'auto' else self.language,
                'multilingual':self.multilingual,'beam_size':self.beam_size,
                'initial_prompt':prompt or None,'hotwords':self.glossary.strip() or None,
                'vad_filter':self.vad_filter,
                'vad_parameters':{'threshold':self.vad_threshold,'speech_pad_ms':self.speech_pad_ms,'min_silence_duration_ms':self.min_silence_duration_ms}}
