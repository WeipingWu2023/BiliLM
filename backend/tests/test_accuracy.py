import inspect
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import test_core as core
from test_core import ROWS, BV
from app import db, versions
from app.quality import ASRConfig
from app.evaluation import score, distance, disagreements


class AccuracyTests(unittest.TestCase):
    setUp=core.Tests.setUp
    tearDown=core.Tests.tearDown
    enqueue=core.Tests.enqueue
    complete=core.Tests.complete
    def make_run(self,rid='run1',key=None):
        self.complete()
        with db.connection() as con:
            con.execute("UPDATE jobs SET status='completed' WHERE video_id=?",(BV+':p1',))
        versions.create(rid,key or BV+':p1',ROWS,'test-asr',ASRConfig().model_dump(),{'source_audio_sha256':'samehash'})
        return versions.get(rid)

    def test_profiles_and_supported_decoding_only(self):
        from faster_whisper import WhisperModel
        config=ASRConfig(profile='accuracy',language='zh',beam_size=8,topic='网络',glossary='TCP/IP, GPU')
        self.assertEqual(config.model,'large-v3')
        self.assertEqual(config.decode_options()['hotwords'],'TCP/IP, GPU')
        self.assertTrue(set(config.decode_options())<=set(inspect.signature(WhisperModel.transcribe).parameters))
        self.assertFalse(config.allow_model_download)
        self.assertIsNone(ASRConfig().decode_options()['initial_prompt'])

    def test_independent_runs_and_immutable_raw(self):
        one=self.make_run(); versions.create('run2',BV+':p1',ROWS,'test-medium',ASRConfig(model='medium').model_dump(),{})
        self.assertEqual(len(versions.list_runs(BV+':p1')),2)
        versions.edit('run1','proofread',['你好，世界',ROWS[1]['text']],0)
        self.assertEqual(versions.get('run1')['raw'],one['raw'])
        self.assertEqual(versions.get('run2')['proofread'],ROWS)
        with self.assertRaises(sqlite3.IntegrityError),db.connection() as con:
            con.execute('UPDATE runs SET raw=? WHERE id=?',('[]','run1'))
        with self.assertRaises(sqlite3.IntegrityError),db.connection() as con:
            con.execute('UPDATE runs SET config=? WHERE id=?',('{}','run1'))

    def test_text_proposals_pending_then_explicit_review(self):
        self.make_run()
        count=versions.propose('run1',[{'index':0,'text':'你好，世界','reason':'补标点','uncertain':False}],0)
        run=versions.get('run1'); self.assertEqual(count,1); self.assertEqual(run['proofread'],ROWS)
        p=run['corrections'][0]; self.assertEqual(p['uncertain'],1); self.assertEqual(p['source'],'text-only-llm')
        versions.review('run1',p['id'],True)
        updated=versions.get('run1'); self.assertEqual(updated['proofread'][0]['text'],'你好，世界')
        self.assertEqual(updated['proofread'][0]['start'],ROWS[0]['start'])
        self.assertEqual(updated['raw'],ROWS)
        with self.assertRaises(ValueError): versions.review('run1',p['id'],True)

    def test_unsafe_proposals_and_stale_edits_rejected(self):
        self.make_run()
        with self.assertRaises(ValueError): versions.propose('run1',[{'index':0,'text':'添加完全没有说过的理论与新事实','reason':'猜测'}])
        self.assertEqual(versions.get('run1')['corrections'],[])
        versions.edit('run1','proofread',['你好，世界',ROWS[1]['text']],0)
        with self.assertRaises(ValueError): versions.propose('run1',[],0)
        with self.assertRaises(ValueError): versions.edit('run1','proofread',['x','y'],0)
        with self.assertRaises(ValueError): versions.edit('run1','readable',['missing index'],0)

    def test_each_version_exports_and_mapping_preserved(self):
        self.make_run()
        for version in ('raw','proofread','readable'):
            for fmt in ('txt','srt','md','json'):
                response=self.client.get(f'/api/runs/run1/export?version={version}&format={fmt}')
                self.assertEqual(response.status_code,200); self.assertTrue(response.content)
        versions.format_readable('run1',0,False)
        self.assertEqual(versions.get('run1')['readable_segments'][0]['start'],ROWS[0]['start'])
        self.assertEqual(self.client.put('/api/runs/run1/raw',json={'texts':['bad','bad'],'revision':0}).status_code,409)

    def test_retranscribe_keeps_original_cache_and_history(self):
        self.make_run()
        with patch('app.model_manager.cached',return_value=True):
            response=self.client.post(f'/api/videos/{BV}:p1/retranscribe',json={'profile':'balanced','language':'auto'})
        self.assertEqual(response.status_code,200); self.assertFalse(response.json()['cached'])
        with db.connection() as con:
            config=json.loads(con.execute('SELECT payload FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone()['payload'])
        self.assertEqual(config['model'],'medium')
        self.assertEqual(db.get_video(BV+':p1')['segments'],ROWS)
        self.assertTrue(self.enqueue()['cached'])

    def test_concurrent_worker_claims_and_fencing(self):
        for i in range(8): db.enqueue('key'+str(i),'url','video',{'model':'small','config':{'device':'auto'}})
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed=list(pool.map(lambda i:db.claim('worker'+str(i)),range(8)))
        self.assertEqual(len({j['id'] for j in claimed}),8)
        first=claimed[0]; db.recover()
        self.assertIsNone(db.claim()) # Live leases must not be stolen.
        with db.connection() as con: con.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(first['id'],))
        replacement=db.claim('new-worker'); self.assertEqual(replacement['id'],first['id'])
        with self.assertRaises(db.LeaseLost): db.update_job(first['id'],_lease_token=first['lease_token'],status='completed')
        with self.assertRaises(db.LeaseLost): db.heartbeat(first['id'],first['lease_token'])
        db.heartbeat(replacement['id'],replacement['lease_token'])
        db.update_job(replacement['id'],_lease_token=replacement['lease_token'],status='completed')

    def test_device_capability_is_independent_of_model(self):
        gpu=db.enqueue('gpu','url','GPU',{'model':'large-v3','config':{'device':'cuda'}})
        cpu=db.enqueue('cpu','url','CPU',{'model':'large-v3','config':{'device':'cpu'}})
        self.assertEqual(db.claim('cpu-worker',('cpu',))['id'],cpu['job_id'])
        self.assertEqual(db.claim('gpu-worker',('cuda',))['id'],gpu['job_id'])

    def test_metrics_known_errors_and_timestamps(self):
        result=distance('abc','adcX'); self.assertEqual(result['distance'],2)
        scored=score('你好 Python API',[{'start':0.2,'end':2.5,'text':'你好 Python API API'}],['API'],[{'start':0,'end':2,'text':'你好 Python API'}])
        self.assertEqual(scored['terms'][0]['extra_count'],1)
        self.assertEqual(scored['term_recall'],1)
        self.assertEqual(scored['term_precision'],0.5)
        self.assertAlmostEqual(scored['timestamp_errors'][0]['start_error_seconds'],0.2)
        self.assertEqual(scored['english_wer']['insertions'],1)
        self.assertIsNone(score('你好',ROWS)['english_wer'])

    def test_comparison_requires_same_audio(self):
        first=self.make_run(); second={**first,'raw':[dict(r) for r in ROWS]}
        second['raw'][0]['text']='你好，世界'
        self.assertEqual(disagreements(first,second)['differences'],[])
        second['metrics']={'source_audio_sha256':'different'}
        with self.assertRaises(ValueError): disagreements(first,second)

    def test_missing_audio_and_download_is_not_automatic(self):
        self.make_run(); self.assertEqual(self.client.get('/api/runs/run1/audio').status_code,404)
        from app.asr import model
        with patch('faster_whisper.utils.download_model',side_effect=RuntimeError('not cached')) as download:
            with self.assertRaisesRegex(RuntimeError,'MODEL_NOT_CACHED'): model('large-v3','cpu')
            self.assertTrue(download.call_args.kwargs['local_files_only'])

    def test_legacy_migration_preserves_free_text_and_backs_up(self):
        directory=db.DATA/'legacy'; directory.mkdir()
        with sqlite3.connect(directory/'bililm.sqlite3') as con:
            con.executescript("CREATE TABLE videos(id TEXT PRIMARY KEY,url TEXT,title TEXT,creator TEXT DEFAULT '',thumbnail TEXT DEFAULT '',duration REAL DEFAULT 0,segments TEXT,readable TEXT,provenance TEXT,revision INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            con.execute('INSERT INTO videos(id,url,title,segments,readable,provenance) VALUES(?,?,?,?,?,?)',('legacy','url','old',json.dumps(ROWS),'原来人工编辑的独立段落','original'))
        con.close()
        with patch.object(db,'DATA',directory):
            db.init(); run=versions.get(versions.list_runs('legacy')[0]['id'])
            self.assertEqual(run['raw'],ROWS); self.assertEqual(run['readable'],'原来人工编辑的独立段落'); self.assertEqual(run['mapped'],0)
            self.assertTrue(list((directory/'backups').glob('*.sqlite3')))

    def test_result_commit_is_atomic_and_recoverable(self):
        self.enqueue(); job=db.claim('one')
        with db.connection() as con:
            con.execute("CREATE TRIGGER test_failure BEFORE UPDATE OF status ON jobs WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT,'simulated commit failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            versions.commit_job(job,{'title':'Course'},ROWS,'test',{}, {})
        self.assertIsNone(versions.get(job['id']))
        self.assertEqual(db.get_video(BV+':p1')['segments'],[])
        with db.connection() as con:
            con.execute('DROP TRIGGER test_failure')
        versions.commit_job(job,{'title':'Course'},ROWS,'test',{}, {})
        self.assertEqual(versions.get(job['id'])['raw'],ROWS)

    def test_offline_retranscribe_uses_retained_audio_and_private_playback(self):
        from app.worker import process
        self.make_run()
        source=db.DATA/'saved.m4a'; source.write_bytes(b'original-audio')
        versions.create('with-audio',BV+':p1',ROWS,'test',ASRConfig().model_dump(),{},'saved.m4a')
        response=self.client.post(f'/api/videos/{BV}:p1/retranscribe',json={'model':'small'})
        self.assertEqual(response.status_code,200)
        job=db.claim('offline-worker')
        def recognize(source,config,progress,report,playback):
            self.assertIn(job['lease_token'],playback.name)
            playback.parent.mkdir(exist_ok=True); playback.write_bytes(b'pcm-for-this-lease')
            return ROWS
        with patch('app.worker.Bilibili',side_effect=AssertionError('must not contact platform')),patch('app.backends.FasterWhisperBackend.transcribe',side_effect=recognize):
            process(job)
        run=versions.get(job['id']); self.assertEqual(run['raw'],ROWS)
        self.assertIn(job['lease_token'],run['playback'])
