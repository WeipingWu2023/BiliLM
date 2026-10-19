import json
import unittest
from unittest.mock import patch
import test_core as core
from app import db,versions,proofreading as proof,learning
from app.worker import process
from app.quality import ASRConfig

ROWS=[{'start':0,'end':3,'text':'何志力打乒乓球。'},{'start':3,'end':6,'text':'今天有12个人。'}]
CORRECTION={'index':0,'before':'何志力','after':'何智丽','kind':'name','reason':'乒乓球上下文支持这位运动员的姓名','uncertain':False}


class FinalWorkflowTests(unittest.TestCase):
    setUp=core.Tests.setUp
    tearDown=core.Tests.tearDown
    key=core.BV+':p1'

    def make_run(self):
        db.enqueue(self.key,'local-file','乒乓球示例',{'kind':'local','file':'fixture.wav','model':'small'})
        job=db.claim();versions.commit_job(job,{'title':'乒乓球示例'},ROWS,'fixture',ASRConfig().model_dump(),{})
        return job['id']

    def result(self,change=None,approved=None):
        replies=[json.dumps({'corrections':[change or CORRECTION]},ensure_ascii=False),json.dumps({'approved':[0] if approved is None else approved})]
        with patch.object(proof,'load',return_value={'url':'https://api.deepseek.com','key':'fixture','model':'fixture'}),patch('app.reasoning.OpenAICompatible.answer',side_effect=replies):
            return proof.prepare(ROWS,policy=proof.FINAL_POLICY)

    def test_second_review_applies_context_supported_name_without_manual_queue(self):
        result=self.result();self.assertEqual(result['rows'][0]['text'],'何智丽打乒乓球。')
        self.assertEqual(result['summary']['policy'],proof.FINAL_POLICY)
        rid=self.make_run();proof.apply(rid,result,0,0)
        self.assertEqual(proof.final_state(self.key)['status'],'ready')
        self.assertEqual(versions.get(rid)['raw'],ROWS)

    def test_reviewer_rejection_uncertainty_and_number_changes_keep_original(self):
        self.assertEqual(self.result(approved=[])['rows'],ROWS)
        uncertain={**CORRECTION,'uncertain':True}
        with patch.object(proof,'load',return_value={'url':'fixture','model':'fixture'}),patch('app.reasoning.OpenAICompatible.answer',return_value=json.dumps({'corrections':[uncertain]})) as model:
            result=proof.prepare(ROWS,policy=proof.FINAL_POLICY)
        self.assertEqual(model.call_count,1);self.assertEqual(result['rows'],ROWS)
        rid=self.make_run();proof.apply(rid,result,0,0)
        self.assertEqual(versions.get(rid)['corrections'][0]['state'],'retained')
        self.assertEqual(self.result({**CORRECTION,'index':1,'before':'12','after':'21'})['rows'],ROWS)

    def test_bad_second_review_never_produces_final(self):
        with self.assertRaises(ValueError):self.result(approved=[99])

    def test_no_key_has_no_raw_text_and_no_charge(self):
        self.make_run()
        with patch.object(proof,'load',return_value={'url':''}),patch.object(proof,'enqueue') as enqueue:
            response=self.client.post(f'/api/videos/{self.key}/finalize',json={})
        self.assertEqual(response.json()['status'],'needs_configuration')
        self.assertNotIn('segments',response.json());enqueue.assert_not_called()
        self.assertEqual(self.client.get(f'/api/videos/{self.key}/final/export').status_code,409)

    def test_polling_is_deduplicated_failure_does_not_loop_paid_calls(self):
        self.make_run()
        with patch.object(proof,'load',return_value={'url':'fixture'}):
            first=proof.final_state(self.key,schedule=True);again=proof.final_state(self.key,schedule=True)
            self.assertEqual(first['job_id'],again['job_id'])
            with patch.object(proof,'prepare',side_effect=ValueError('provider unavailable')),self.assertLogs(level='ERROR'):process(db.claim())
            self.assertEqual(proof.final_state(self.key,schedule=True)['status'],'failed')
            with db.connection() as con:self.assertEqual(con.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0],0)
            self.assertIsNotNone(proof.final_state(self.key,schedule=True,retry=True)['job_id'])

    def test_existing_run_auto_finalizes_without_asr_then_exports_only_final(self):
        rid=self.make_run();result=self.result()
        with patch.object(proof,'load',return_value={'url':'fixture'}):
            self.client.post(f'/api/videos/{self.key}/finalize',json={})
            with patch.object(proof,'prepare',return_value=result),patch('app.worker.get_backend',side_effect=AssertionError('must not run ASR')):process(db.claim())
        state=proof.final_state(self.key);self.assertEqual(state['status'],'ready')
        for fmt in ('md','txt','srt'):
            response=self.client.get(f'/api/videos/{self.key}/final/export?format={fmt}')
            self.assertEqual(response.status_code,200);self.assertIn('何智丽',response.text);self.assertNotIn('何志力',response.text)
        with patch.object(proof,'enqueue') as enqueue:
            self.client.post(f'/api/videos/{self.key}/finalize',json={});enqueue.assert_not_called()
        self.assertEqual(versions.get(rid)['raw'],ROWS)

    def test_final_edit_is_shared_by_reading_export_and_learning(self):
        rid=self.make_run();proof.apply(rid,self.result(),0,0)
        texts=['何智丽参加比赛。',ROWS[1]['text']]
        self.assertEqual(self.client.put(f'/api/videos/{self.key}/final',json={'texts':texts,'revision':1,'run_id':'another-run'}).status_code,409)
        response=self.client.put(f'/api/videos/{self.key}/final',json={'texts':texts,'revision':1,'run_id':rid})
        self.assertEqual(response.status_code,200)
        self.assertIn(texts[0],response.json()['readable'])
        self.assertEqual(learning.source(db.get_video(self.key))[0][0]['text'],texts[0])
        self.assertIn(texts[0],self.client.get(f'/api/videos/{self.key}/final/export').text)
        self.assertEqual(self.client.put(f'/api/videos/{self.key}/final',json={'texts':texts,'revision':1,'run_id':rid}).status_code,409)
        self.assertEqual(versions.get(rid)['raw'],ROWS)

    def test_final_learning_is_blocked_until_ready(self):
        self.make_run()
        with patch('app.reasoning.OpenAICompatible.answer',side_effect=AssertionError('must wait for final')):
            self.assertEqual(self.client.post(f'/api/videos/{self.key}/learning',json={'kind':'summary','final':True,'external':True}).status_code,409)
            self.assertEqual(self.client.post(f'/api/videos/{self.key}/ask',json={'question':'总结','final':True,'external':True}).status_code,409)

    def test_import_automatically_enables_finalization_even_with_old_client_flags(self):
        with patch.object(proof,'load',return_value={'url':'fixture'}),patch('app.model_manager.ensure_ready'):
            response=self.client.post('/api/imports',json={'source':core.BV,'ai_proofread':False,'proofread_search':False})
        self.assertEqual(response.status_code,200)
        with db.connection() as con:config=json.loads(con.execute('SELECT payload FROM jobs WHERE id=?',(response.json()['job_id'],)).fetchone()[0])['config']
        self.assertTrue(config['ai_proofread']);self.assertTrue(config['proofread_search']);self.assertTrue(config['auto_finalize'])

    def test_failed_retranscription_does_not_masquerade_as_previous_final(self):
        rid=self.make_run();proof.apply(rid,self.result(),0,0)
        new=db.enqueue(self.key,'local-file','示例',{'kind':'local','file':'fixture.wav','model':'medium','retranscribe':True})
        with db.connection() as con:con.execute("UPDATE jobs SET status='failed' WHERE id=?",(new['job_id'],))
        self.assertEqual(proof.final_state(self.key)['status'],'failed')
        self.assertEqual(self.client.get(f'/api/videos/{self.key}/final/export').status_code,409)
        self.assertEqual(proof.final_state(self.key,schedule=True,retry=True)['job_id'],new['job_id'])
