import json
import unittest
from unittest.mock import Mock, patch
import test_core as core
from app import db, learning, model_manager as models
from app.reasoning import OpenAICompatible


class StudioModelsTests(unittest.TestCase):
    setUp=core.Tests.setUp
    tearDown=core.Tests.tearDown
    complete=core.Tests.complete
    enqueue=core.Tests.enqueue

    def test_citation_formats_are_normalized_without_inventing_ids(self):
        for value in (1,'1','s1','seg_1',{'id':'s1'},'[00:00:03]'):
            with self.subTest(value=value):
                self.assertEqual(learning.citation_id(value,core.ROWS),1)
        for value in (2,-1,'s999','source-does-not-exist',True,1.5):
            with self.subTest(value=value),self.assertRaises(ValueError):
                learning.citation_id(value,core.ROWS)
        items=learning.checked_items([{'text':'a','citations':['s0']*12+['s1']}],core.ROWS,6)
        self.assertEqual(items[0]['citations'],[0,1])

    def test_valid_long_reference_list_is_capped_after_validation(self):
        rows=[{'start':i,'end':i+1,'text':str(i)} for i in range(12)]
        self.assertEqual(len(learning.checked_items([{'text':'a','citations':list(range(12))}],rows,6)[0]['citations']),8)
        with self.assertRaises(ValueError):
            learning.checked_items([{'text':'a','citations':[0,99]}],rows,6)

    def test_one_bounded_repair_and_saved_result_retrieval(self):
        self.complete(); video=db.get_video(core.BV+':p1')
        invalid=json.dumps({'overview':'a','items':[{'text':'b','citations':['s900']}],'questions':['q']})
        valid=json.dumps({'overview':'a','items':[{'text':'b','citations':['s1']}],'questions':['q']})
        with patch('app.learning.llm_settings',return_value={'url':'https://mock.test','model':'mock','key':'fixture'}),patch.object(OpenAICompatible,'answer',side_effect=[invalid,valid]) as model:
            result=learning.artifact(video,'summary',external=True)
        self.assertEqual(model.call_count,2)
        self.assertTrue(model.call_args.kwargs['json_mode'])
        self.assertEqual(result['items'][0]['citations'],[1])
        saved=self.client.get(f'/api/videos/{video["id"]}/learning/artifacts').json()
        self.assertEqual(saved[0]['id'],result['id'])
        self.assertFalse(saved[0]['stale'])

    def test_failed_repair_does_not_save_or_replace_source(self):
        self.complete(); video=db.get_video(core.BV+':p1')
        with patch('app.learning.llm_settings',return_value={'url':'https://mock.test','model':'mock','key':'fixture'}),patch.object(OpenAICompatible,'answer',return_value='not-json') as model:
            with self.assertRaisesRegex(ValueError,'一次修正'):
                learning.artifact(video,'mindmap',external=True)
        self.assertEqual(model.call_count,2)
        self.assertEqual(learning.saved_artifacts(video),[])
        self.assertEqual(db.get_video(video['id'])['segments'],core.ROWS)

    def test_catalog_distinguishes_model_and_runtime_installation(self):
        with patch.object(models,'cached',side_effect=lambda name:name=='small'),patch('app.model_manager.importlib.util.find_spec',return_value=None):
            rows=self.client.get('/api/asr/models').json()
        self.assertTrue(next(row for row in rows if row['model']=='small')['usable'])
        self.assertFalse(next(row for row in rows if row['model']=='medium')['cached'])
        self.assertFalse(next(row for row in rows if row['model']=='SenseVoiceSmall')['runtime_ready'])

    def test_installation_requires_consent_and_is_deduplicated(self):
        with patch.object(models,'cached',return_value=False),patch('app.model_manager.threading.Thread') as thread:
            self.assertEqual(self.client.post('/api/asr/models/medium/install',json={}).status_code,400)
            first=self.client.post('/api/asr/models/medium/install',json={'authorized':True})
            second=self.client.post('/api/asr/models/medium/install',json={'authorized':True})
        self.assertEqual(first.json()['state'],'downloading')
        self.assertEqual(second.json()['state'],'downloading')
        thread.return_value.start.assert_called_once()
        models.recover()
        with db.connection() as con:
            self.assertEqual(con.execute("SELECT state FROM model_installations WHERE model='medium'").fetchone()[0],'failed')

    def test_uncached_large_model_rejected_before_ingestion_and_can_be_authorized(self):
        with patch.object(models,'cached',return_value=False):
            response=self.client.post('/api/imports',json={'source':core.BV,'model':'medium'})
            self.assertEqual(response.status_code,400)
            self.assertIn('尚未安装',response.json()['detail'])
            models.ensure_ready({'model':'medium','allow_model_download':True})
        with patch.object(models,'catalog',return_value=[{'model':'SenseVoiceSmall','usable':False}]):
            with self.assertRaisesRegex(ValueError,'运行依赖'):
                models.ensure_ready({'model':'SenseVoiceSmall'})

    def test_download_failure_preserves_safe_retry_state(self):
        with db.connection() as con:
            con.execute("INSERT INTO model_installations(model,state) VALUES('medium','downloading')")
        with patch('faster_whisper.utils.download_model',side_effect=RuntimeError('secret signed URL')):
            models.download('medium')
        with db.connection() as con:
            row=con.execute("SELECT * FROM model_installations WHERE model='medium'").fetchone()
        self.assertEqual(row['state'],'failed')
        self.assertNotIn('secret',row['error'])
