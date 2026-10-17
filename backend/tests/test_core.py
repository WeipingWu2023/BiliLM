import json
import sqlite3
import tempfile
import unittest
import wave
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app import db
from app.ingestion import parse_input, resolve, Bilibili, IngestionError
from app.transcript import validate_segments, clean, export, stamp
from app.worker import process
from app.main import app

BV = 'BV1xx411c7mD'
ROWS = [{'start':0.123,'end':2.5,'text':'你好世界'},{'start':3,'end':5,'text':'学习 Python。'}]


class Tests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'data'/'tests'
        root.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        assert Path(self.temp.name).resolve().is_relative_to(root.resolve())
        self.patch = patch.object(db,'DATA',Path(self.temp.name)); self.patch.start()
        db.init(); self.client = TestClient(app)

    def tearDown(self):
        self.client.close(); self.patch.stop(); self.temp.cleanup()

    def enqueue(self):
        return db.enqueue(BV+':p1','https://www.bilibili.com/video/'+BV,BV,{'kind':'bilibili','bv':BV,'part':1,'model':'tiny'})

    def complete(self):
        self.enqueue(); db.save(BV+':p1',{'title':'测试课程'},ROWS,clean(ROWS),'bilibili-subtitle:zh')

    def test_url_variants_and_parts(self):
        self.assertEqual(parse_input(BV),(BV,1))
        self.assertEqual(parse_input(f'https://www.bilibili.com/video/{BV}/?p=2&share=1'),(BV,2))
        self.assertEqual(parse_input(f'http://m.bilibili.com/video/{BV}'),(BV,1))
        self.assertIsNone(parse_input('https://b23.tv/abcdef')[0])

    def test_reject_untrusted_urls(self):
        for value in ['https://evil.com/video/'+BV,'https://bilibili.com.evil.com/video/'+BV,'file:///video/'+BV,
                      'https://user@b23.tv/abc','https://b23.tv:999/abc','https://b23.tv/abc/def',
                      f'https://www.bilibili.com/video/{BV}?p=0',f'https://www.bilibili.com/video/{BV}?p=-2','BV123']:
            with self.subTest(value=value), self.assertRaises(ValueError): parse_input(value)

    def test_short_redirect_validates_before_fetch(self):
        transport=httpx.MockTransport(lambda request:httpx.Response(302,headers={'location':'http://127.0.0.1/private'}))
        client=httpx.Client(transport=transport)
        with patch('app.ingestion.httpx.Client',return_value=client),self.assertRaises(ValueError): resolve('https://b23.tv/abc')

    def test_short_redirect_success(self):
        client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(302,headers={'location':f'https://www.bilibili.com/video/{BV}?p=2'})))
        with patch('app.ingestion.httpx.Client',return_value=client): self.assertEqual(resolve('https://b23.tv/abc'),(BV,2))

    def test_timestamps_and_validation(self):
        self.assertEqual(validate_segments(ROWS[::-1]),ROWS)
        self.assertEqual(stamp(59.9996,True),'00:01:00,000')
        for rows in [[],[{'start':0,'end':float('nan'),'text':'x'}],[{'start':-1,'end':2,'text':'x'}]]:
            with self.assertRaises(ValueError): validate_segments(rows)
        self.assertEqual(ROWS[0]['text'],'你好世界')
        self.assertIn('你好世界。',clean(ROWS))

    def test_cache_and_part_isolation(self):
        first=self.enqueue(); second=self.enqueue()
        self.assertEqual(first['job_id'],second['job_id'])
        self.complete(); self.assertTrue(self.enqueue()['cached'])
        self.assertFalse(db.enqueue(BV+':p2','url','P2',{})['cached'])

    def test_concurrent_imports_are_deduplicated(self):
        with ThreadPoolExecutor(max_workers=5) as executor:
            results=list(executor.map(lambda _:self.enqueue(),range(10)))
        self.assertEqual(len({r['job_id'] for r in results}),1)

    def test_original_immutable_and_edit_conflict(self):
        self.complete(); key=BV+':p1'
        response=self.client.put(f'/api/videos/{key}/readable',json={'text':'人工修改','revision':0})
        self.assertEqual(response.status_code,200)
        self.assertEqual(db.get_video(key)['segments'],ROWS)
        self.assertEqual(self.client.put(f'/api/videos/{key}/readable',json={'text':'旧修改','revision':0}).status_code,409)
        with self.assertRaises(sqlite3.IntegrityError),db.connection() as con:
            con.execute('UPDATE videos SET segments=? WHERE id=?',('[]',key))

    def test_exports(self):
        self.complete(); video=db.get_video(BV+':p1')
        self.assertIn('00:00:00,123 --> 00:00:02,500',export(video,'srt'))
        self.assertNotIn('## 原始时间轴',export(video,'md'))
        self.assertNotIn('[00:',export(video,'md'))
        self.assertIn(video['readable'],export(video,'md'))
        self.assertEqual(export(video,'txt'),video['readable'])
        self.assertEqual(self.client.get(f'/api/videos/{video["id"]}/export?format=srt').status_code,200)

    def test_restart_recovers_job(self):
        result=self.enqueue(); self.assertIsNotNone(db.claim()); self.assertIsNone(db.claim())
        with db.connection() as con:
            con.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(result['job_id'],))
        db.recover(); self.assertEqual(db.claim()['id'],result['job_id'])

    def test_failure_and_retry_recovery(self):
        result=self.enqueue(); job=db.claim()
        with patch('app.worker.Bilibili') as adapter, self.assertLogs(level='ERROR'):
            adapter.return_value.metadata.side_effect=IngestionError('ACCESS_412: restricted')
            process(job)
        tasks=self.client.get('/api/jobs').json()
        self.assertEqual(tasks[0]['status'],'failed'); self.assertIn('ACCESS_412',tasks[0]['error'])
        self.assertEqual(self.client.post('/api/jobs/'+result['job_id']+'/retry').status_code,200)
        with patch('app.worker.Bilibili') as adapter:
            adapter.return_value.metadata.return_value={'title':'Recovered','cid':1}
            adapter.return_value.subtitles.return_value=(ROWS,'zh')
            process(db.claim())
        self.assertTrue(self.enqueue()['cached'])
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'],'completed')

    def test_asr_fallback_pipeline(self):
        self.enqueue()
        with patch('app.worker.Bilibili') as adapter,patch('app.backends.FasterWhisperBackend.transcribe',return_value=ROWS) as asr:
            adapter.return_value.metadata.return_value={'title':'ASR','cid':1}
            adapter.return_value.subtitles.return_value=([],'')
            def audio(bv,cid,target,progress):
                target.write_bytes(b'test media'); return target
            adapter.return_value.audio.side_effect=audio
            process(db.claim()); asr.assert_called_once()
        self.assertEqual(db.get_video(BV+':p1')['provenance'],'bilibili-asr:tiny')

    def test_subtitle_failure_falls_back_to_permitted_audio(self):
        from app import versions
        for part,error in enumerate((httpx.ReadError('network'), IngestionError('ACCESS_403: subtitle unavailable'), ValueError('invalid subtitle')),1):
            with self.subTest(error=type(error).__name__):
                key=f'{BV}:p{part}'
                db.enqueue(key,'https://www.bilibili.com/video/'+BV,BV,{'kind':'bilibili','bv':BV,'part':part,'model':'tiny'})
                job=db.claim()
                with patch('app.worker.Bilibili') as adapter,patch('app.backends.FasterWhisperBackend.transcribe',return_value=ROWS) as asr:
                    adapter.return_value.metadata.return_value={'title':'Fallback','cid':1}
                    adapter.return_value.subtitles.side_effect=error
                    adapter.return_value.audio.side_effect=lambda bv,cid,target,progress: target.write_bytes(b'permitted audio')
                    process(job)
                    asr.assert_called_once()
                self.assertEqual(db.get_video(key)['provenance'],'bilibili-asr:tiny')
                run=versions.get(job['id'])
                self.assertEqual(run['metrics']['subtitle_lookup']['error_type'],type(error).__name__)

    def test_subtitle_failure_does_not_bypass_audio_restriction(self):
        self.enqueue()
        with patch('app.worker.Bilibili') as adapter,patch('app.backends.FasterWhisperBackend.transcribe') as asr,self.assertLogs(level='ERROR'):
            adapter.return_value.metadata.return_value={'title':'Restricted','cid':1}
            adapter.return_value.subtitles.side_effect=IngestionError('ACCESS_403: subtitles')
            adapter.return_value.audio.side_effect=IngestionError('ACCESS_403: audio restricted')
            process(db.claim())
            asr.assert_not_called()
        tasks=self.client.get('/api/jobs').json()
        self.assertEqual(tasks[0]['status'],'failed')
        self.assertIn('audio restricted',tasks[0]['error'])

    def test_asr_passes_normalized_pcm_without_pyav_decode(self):
        from app.asr import transcribe
        import numpy as np
        from numpy.testing import assert_array_equal
        source=db.DATA/'speech.mp3'
        def ffmpeg_run(*args,**kwargs):
            with wave.open(str(source.with_suffix('.asr.wav')),'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(np.array([0,16384,-16384],dtype=np.int16).tobytes())
        def recognize(samples,**kw):
            assert_array_equal(samples,np.array([0,0.5,-0.5],dtype=np.float32))
            return iter([SimpleNamespace(start=0,end=1,text='Hello')]),SimpleNamespace(duration=1)
        engine=SimpleNamespace(transcribe=recognize)
        with patch('app.asr.subprocess.run',side_effect=ffmpeg_run),patch('app.asr.model',return_value=engine):
            result=transcribe(source,'tiny',lambda *_:None)
        self.assertEqual(result[0]['text'],'Hello')
        self.assertFalse(source.with_suffix('.asr.wav').exists())

    def test_local_upload_deduplication_and_retry(self):
        first=self.client.post('/api/uploads',files={'file':('sample.wav',b'RIFF fake for pipeline test','audio/wav')},data={'model':'tiny'})
        self.assertEqual(first.status_code,200)
        second=self.client.post('/api/uploads',files={'file':('same.wav',b'RIFF fake for pipeline test','audio/wav')})
        self.assertEqual(first.json()['video_id'],second.json()['video_id'])
        self.assertEqual(len(list((db.DATA/'uploads').iterdir())),1)
        with patch('app.backends.FasterWhisperBackend.transcribe',return_value=ROWS): process(db.claim())
        self.assertTrue(db.get_video(first.json()['video_id'])['segments'])
        self.assertEqual(self.client.post('/api/uploads',files={'file':('bad.exe',b'x')}).status_code,400)

    def test_benchmark_cached_only_disables_legacy_small_download(self):
        from app.asr import transcribe
        import wave
        source=db.DATA/'strict-cache.wav'
        def ffmpeg(*args,**kwargs):
            with wave.open(str(source.with_suffix('.asr.wav')),'wb') as audio:
                audio.setparams((1,2,16000,0,'NONE','not compressed'))
                audio.writeframes(b'\0\0'*160)
        with patch('app.asr.subprocess.run',side_effect=ffmpeg),patch('app.asr.model',side_effect=RuntimeError('not cached')) as load:
            with self.assertRaisesRegex(RuntimeError,'not cached'):
                transcribe(source,'small',lambda *_:None,{'model':'small','device':'cpu','require_cached_model':True,'allow_model_download':True})
            self.assertIs(load.call_args.args[3],False)

    def test_api_boundaries_and_assistant(self):
        self.assertIn(self.client.post('/api/imports',json={'source':BV,'model':'unsupported'}).status_code,(400,422))
        self.assertEqual(self.client.post('/api/imports',json={'source':BV},headers={'origin':'https://evil.com'}).status_code,403)
        self.assertEqual(self.client.get('/api/health',headers={'host':'evil.com'}).status_code,403)
        self.complete()
        result=self.client.post(f'/api/videos/{BV}:p1/ask',json={'question':'Python'}).json()
        self.assertEqual(result['mode'],'local-search'); self.assertEqual(result['citations'][0]['start'],3)

    def test_cdn_and_restricted_response(self):
        for url in ['https://127.0.0.1/media','https://hdslb.com.evil.com/media','http://foo.hdslb.com/media']:
            with self.assertRaises(IngestionError): Bilibili.check_cdn(url)
        self.assertEqual(Bilibili.check_cdn('//a.hdslb.com/file'),'https://a.hdslb.com/file')
        adapter=Bilibili(); adapter.client.close()
        adapter.client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(412)))
        with self.assertRaisesRegex(IngestionError,'ACCESS_412'): adapter.metadata(BV,1)
        adapter.close()

    def test_thumbnail_cache(self):
        self.enqueue(); db.save_metadata(BV+':p1',{'title':'Cover','thumbnail':'http://i0.hdslb.com/cover.jpg'})
        adapter=Bilibili(); adapter.client.close()
        adapter.client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'image/jpeg'},content=b'jpeg-test')))
        with patch('app.main.Bilibili',return_value=adapter):
            first=self.client.get(f'/api/videos/{BV}:p1/thumbnail')
        self.assertEqual(first.status_code,200)
        with patch('app.main.Bilibili',side_effect=AssertionError('cache should not fetch')):
            cached=self.client.get(f'/api/videos/{BV}:p1/thumbnail')
        self.assertEqual(cached.content,first.content)

    def test_audio_uses_validated_backup_when_primary_port_is_unsupported(self):
        adapter=Bilibili(); adapter.client.close()
        requests=[]
        def response(request):
            requests.append(str(request.url))
            return httpx.Response(200,content=b'authorized-audio')
        adapter.client=httpx.Client(transport=httpx.MockTransport(response),follow_redirects=False)
        target=db.DATA/'download.partial'
        data={'dash':{'audio':[{'bandwidth':64000,
            'baseUrl':'https://peer.mcdn.bilivideo.cn:8082/audio',
            'backupUrl':['https://127.0.0.1/private','https://evil.com/audio',
                         'https://upos.bilivideo.com/audio']}]}}
        with patch.object(adapter,'api',return_value=data):
            self.assertEqual(adapter.audio(BV,1,target,lambda *_:None),target)
        self.assertEqual(requests,['https://upos.bilivideo.com/audio'])
        self.assertEqual(target.read_bytes(),b'authorized-audio'); adapter.close()

    def test_audio_fallback_does_not_follow_redirects_and_replaces_partial_bytes(self):
        adapter=Bilibili(); adapter.client.close()
        requests=[]
        class Interrupted(httpx.SyncByteStream):
            def __iter__(self):
                yield b'bad-partial'
                raise httpx.ReadError('interrupted')
        def response(request):
            requests.append(request.url.host)
            if request.url.host=='first.bilivideo.com': return httpx.Response(200,stream=Interrupted())
            if request.url.host=='redirect.bilivideo.com': return httpx.Response(302,headers={'location':'https://127.0.0.1/private'})
            return httpx.Response(200,content=b'complete-backup')
        adapter.client=httpx.Client(transport=httpx.MockTransport(response),follow_redirects=False)
        data={'dash':{'audio':[{'base_url':'https://first.bilivideo.com/audio',
            'backup_url':['https://redirect.bilivideo.com/audio','https://last.bilivideo.com/audio']}]}}
        target=db.DATA/'download.partial'
        with patch.object(adapter,'api',return_value=data): adapter.audio(BV,1,target,lambda *_:None)
        self.assertEqual(target.read_bytes(),b'complete-backup')
        self.assertEqual(requests,['first.bilivideo.com','redirect.bilivideo.com','last.bilivideo.com'])
        adapter.close()


if __name__=='__main__': unittest.main()
