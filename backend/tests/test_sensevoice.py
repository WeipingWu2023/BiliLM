import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from app import sensevoice
from app.backends import get_backend
from app.quality import ASRConfig


class SenseVoiceTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'data'/'tests'
        root.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.directory = Path(self.temp.name)/'model'
        self.location = patch.object(sensevoice,'model_directory',return_value=self.directory)
        self.location.start()
        sensevoice._cached = None; sensevoice._cached_key = None

    def tearDown(self):
        self.location.stop(); self.temp.cleanup()
        sensevoice._cached = None; sensevoice._cached_key = None

    def fake_snapshot(self):
        self.directory.mkdir()
        for name in sensevoice.REQUIRED_FILES:
            (self.directory/name).write_bytes(b'offline-test-fixture')

    def test_backend_config_pairing_and_existing_default(self):
        self.assertEqual(ASRConfig().backend,'faster-whisper')
        self.assertEqual(ASRConfig().model,'small')
        config=ASRConfig(backend='sensevoice',model='SenseVoiceSmall',language='yue')
        self.assertEqual(config.decode_options(),{'language':'yue','use_itn':False,'output_timestamp':False,'batch_size':1})
        self.assertEqual(get_backend('sensevoice').name,'sensevoice')
        for invalid in ({'backend':'sensevoice','model':'small'}, {'model':'SenseVoiceSmall'},
                        {'backend':'sensevoice','model':'SenseVoiceSmall','profile':'fast'}):
            with self.assertRaises(ValueError): ASRConfig(**invalid)

    def test_missing_snapshot_fails_before_runtime_or_ffmpeg_even_with_download_flag(self):
        with patch.dict(sys.modules,{'funasr':None}), patch.object(sensevoice.subprocess,'run') as command:
            with self.assertRaisesRegex(RuntimeError,'MODEL_NOT_CACHED'):
                sensevoice.transcribe(Path(self.temp.name)/'source.wav',
                    {'backend':'sensevoice','model':'SenseVoiceSmall','allow_model_download':True},lambda *_:None)
            command.assert_not_called()

    def test_revision_must_match_cached_snapshot_and_download_requires_commit(self):
        self.fake_snapshot()
        with self.assertRaisesRegex(RuntimeError,'MODEL_REVISION_MISMATCH'): sensevoice.snapshot('wrong')
        (self.directory/'bililm-snapshot.json').write_text(json.dumps({'revision':'a'*40}),encoding='utf-8')
        self.assertEqual(sensevoice.snapshot('a'*40)[1]['revision'],'a'*40)
        with self.assertRaises(ValueError): sensevoice.download_snapshot('main')
        with self.assertRaisesRegex(RuntimeError,'模型目录非空'): sensevoice.download_snapshot('a'*40)

    def test_loader_uses_builtin_config_without_hub_or_remote_code(self):
        self.fake_snapshot()
        config={'model':'SenseVoiceSmall','model_conf':{},'encoder':'SenseVoiceEncoderSmall','encoder_conf':{},
                'tokenizer':'SentencepiecesTokenizer','tokenizer_conf':{},'frontend':'WavFrontend','frontend_conf':{},
                'vad_model':'must-not-load','remote_code':'https://must-not-load','punc_model':'must-not-load'}
        auto=Mock(return_value=object())
        omega=SimpleNamespace(load=lambda _:config,to_container=lambda config,resolve:config)
        modules={'torch':SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False)),
                 'funasr':SimpleNamespace(AutoModel=auto),'omegaconf':SimpleNamespace(OmegaConf=omega)}
        with patch.dict(sys.modules,modules),patch.object(sensevoice.importlib.metadata,'version',return_value='test'):
            first,device,report=sensevoice.model('auto')
            self.assertIs(first,sensevoice.model('cpu')[0]); auto.assert_called_once()
            self.assertEqual(device,'cpu'); self.assertEqual(len(report['weights_sha256']),64)
            kwargs=auto.call_args.kwargs
            self.assertIn('model_conf',kwargs); self.assertFalse(kwargs['trust_remote_code'])
            self.assertTrue(kwargs['disable_update']); self.assertIsNone(kwargs['vad_model'])
            self.assertNotIn('remote_code',kwargs)
            self.assertEqual(kwargs['init_param'],str(self.directory/'model.pt'))
            with self.assertRaisesRegex(RuntimeError,'CUDA_UNAVAILABLE'): sensevoice.model('cuda')

    def test_bounded_windows_preserve_tagged_output_audio_and_coarse_timestamps(self):
        self.fake_snapshot()
        source=Path(self.temp.name)/'source.wav'; source.write_bytes(b'original remains unchanged')
        playback=Path(self.temp.name)/'playback.wav'
        def command(args,**kwargs):
            if args[1]=='-version': return SimpleNamespace(stdout='ffmpeg test\n')
            with wave.open(str(playback),'wb') as audio:
                audio.setparams((1,2,16000,0,'NONE','not compressed')); audio.writeframes(b'\0\0'*(31*16000))
            return subprocess.CompletedProcess(args,0)
        engine=SimpleNamespace(generate=Mock(side_effect=[
            [{'text':'<|yue|><|NEUTRAL|><|Speech|><|woitn|>呢个 API'}],
            [{'text':'<|en|><|NEUTRAL|><|Speech|><|woitn|>API'}]]))
        config={'backend':'sensevoice','model':'SenseVoiceSmall','device':'cpu','glossary':'must never be inserted'}
        report={}
        with patch.object(sensevoice.subprocess,'run',side_effect=command),patch.object(sensevoice,'model',return_value=(engine,'cpu',{})),patch.object(sensevoice,'detect',return_value={}):
            rows=sensevoice.transcribe(source,config,lambda *_:None,report,playback)
        self.assertEqual(rows,[{'start':0,'end':30,'text':'呢个 API'},{'start':30,'end':31,'text':'API'}])
        self.assertEqual(source.read_bytes(),b'original remains unchanged'); self.assertTrue(playback.exists())
        self.assertEqual(report['timestamp_quality'],'input-window-only')
        self.assertTrue(report['raw_model_outputs'][0]['model_text'].startswith('<|yue|>'))
        self.assertNotIn('hotword',engine.generate.call_args.kwargs)
        self.assertEqual([len(call.kwargs['input']) for call in engine.generate.call_args_list],[30*16000,16000])
        self.assertFalse(report['decoding']['use_itn']); self.assertFalse(report['preprocessing']['vad'])


if __name__=='__main__': unittest.main()
