import json
import unittest
from unittest.mock import patch
import httpx
import test_core as core
from app import db, versions, proofreading as proof, learning
from app.worker import process
from app.quality import ASRConfig

ROWS=[{'start':0,'end':4,'text':'乒乓球运动员返振东今天归队。'},{'start':4,'end':8,'text':'比赛中需要保持冷静。'}]
TITLE='乒乓球：樊振东与王励勤'
CHANGE={'index':0,'before':'返振东','after':'樊振东','kind':'name','reason':'乒乓球语境、同音且标题提供规范姓名','uncertain':False}


class ProofreadingTests(unittest.TestCase):
    def setUp(self):
        core.Tests.setUp(self)
        self.provider=patch('app.proofreading.load',return_value={'url':'https://api.deepseek.com','model':'fixture','key':'fixture'})
        self.provider.start()

    def tearDown(self):
        self.provider.stop(); core.Tests.tearDown(self)

    def result(self,changes=None,**kwargs):
        with patch('app.reasoning.OpenAICompatible.answer',return_value=json.dumps({'corrections':changes if changes is not None else [CHANGE]},ensure_ascii=False)):
            return proof.prepare(ROWS,**{'title':TITLE,**kwargs})

    def make_run(self):
        db.enqueue(core.BV+':p1','https://www.bilibili.com/video/'+core.BV,TITLE,{'kind':'bilibili','bv':core.BV,'part':1,'model':'small'})
        job=db.claim(); versions.commit_job(job,{'title':TITLE},ROWS,'fixture',ASRConfig().model_dump(),{})
        return job['id']

    def test_homophone_spelling_supported_by_title_corrects_without_touching_input(self):
        result=self.result()
        self.assertIn('樊振东',result['rows'][0]['text'])
        self.assertIn('返振东',ROWS[0]['text'])
        self.assertEqual(result['rows'][0]['start'],0)
        self.assertEqual(result['summary']['automatic_segments'],1)
        self.assertFalse(result['summary']['audio_verified'])

    def test_missing_evidence_uncertainty_and_cantonese_stay_pending(self):
        for kwargs,change in [({'title':'赛事'},CHANGE),({}, {**CHANGE,'uncertain':True}),({'language':'yue'},CHANGE),({}, {**CHANGE,'after':'马龙'})]:
            with self.subTest(kwargs=kwargs,change=change):
                result=self.result([change],**kwargs)
                self.assertEqual(result['rows'],ROWS)
                self.assertEqual(result['summary']['pending_segments'],1)

    def test_web_support_is_bounded_and_authority_required(self):
        source={'url':'https://example.org/player','title':'樊振东','snippet':'乒乓球运动员','authority':3}
        with patch.object(proof,'search_spelling',return_value=[source]) as search:
            result=self.result(title='赛事',use_search=True)
        search.assert_called_once(); self.assertEqual(result['summary']['automatic_segments'],1)
        with patch.object(proof,'search_spelling',return_value=[{**source,'authority':0}]):
            self.assertEqual(self.result(title='赛事',use_search=True)['summary']['automatic_segments'],0)
        with patch.object(proof,'search_spelling',side_effect=httpx.ReadError('offline')):
            result=self.result(title='赛事',use_search=True)
            self.assertTrue(result['summary']['warnings']); self.assertEqual(result['summary']['search_queries'],0)

    def test_invalid_index_and_long_source_never_partially_apply(self):
        with self.assertRaises(ValueError): self.result([{**CHANGE,'index':100}])
        with patch('app.reasoning.OpenAICompatible.answer') as model,self.assertRaises(ValueError):
            proof.prepare([{'start':0,'end':1,'text':'字'*6001}],TITLE)
        model.assert_not_called()
        result=self.result([{**CHANGE,'before':'源文根本没有这个词'}])
        self.assertEqual(result['rows'],ROWS); self.assertEqual(len(result['summary']['rejected']),1)

    def test_search_budget_prioritizes_names_not_already_in_title(self):
        changes=[CHANGE,{**CHANGE,'after':'何智丽'},{**CHANGE,'after':'这是一整句不适合检索的长话'},{**CHANGE,'after':'邓亚萍','uncertain':True}]
        with patch.object(proof,'search_spelling',return_value=[]) as search:
            self.result(changes,use_search=True)
        self.assertEqual([c.args[0] for c in search.call_args_list],['何智丽'])

    def test_single_nasal_confusion_requires_title_name_and_not_cantonese(self):
        rows=[{'start':0,'end':1,'text':'樊正东今天归队'}]
        change={**CHANGE,'before':'樊正东'}
        with patch('app.reasoning.OpenAICompatible.answer',return_value=json.dumps({'corrections':[change]})):
            self.assertEqual(proof.prepare(rows,TITLE)['summary']['automatic_segments'],1)
            self.assertEqual(proof.prepare(rows,'赛事')['summary']['automatic_segments'],0)
            self.assertEqual(proof.prepare(rows,TITLE,language='yue')['summary']['automatic_segments'],0)
            self.assertEqual(proof.prepare(rows,TITLE)['rows'][0]['start'],0)

    def test_numeric_changes_never_automatically_applied(self):
        change={'index':0,'before':'归队','after':'12','kind':'term','reason':'模型猜测','uncertain':False}
        result=self.result([change],glossary='12')
        self.assertEqual(result['rows'],ROWS); self.assertEqual(result['summary']['pending_segments'],1)

    def test_apply_updates_readable_and_learning_then_undo_restores_all_versions(self):
        rid=self.make_run(); original=versions.get(rid)
        proof.apply(rid,self.result(),0,0)
        current=versions.get(rid)
        self.assertEqual(current['raw'],ROWS)
        self.assertIn('樊振东',current['readable'])
        self.assertEqual(current['corrections'][0]['state'],'auto-applied')
        self.assertIn('樊振东',learning.source(db.get_video(core.BV+':p1'),rid)[0][0]['text'])
        proof.undo(rid); restored=versions.get(rid)
        for field in ('raw','proofread','readable','readable_segments'):self.assertEqual(restored[field],original[field])
        self.assertEqual(restored['corrections'][0]['state'],'reverted')

    def test_concurrent_edit_blocks_apply_and_undo(self):
        rid=self.make_run(); result=self.result()
        versions.edit(rid,'proofread',['人工编辑',ROWS[1]['text']],0)
        with self.assertRaises(ValueError): proof.apply(rid,result,0,0)
        proof.apply(rid,{'rows':versions.get(rid)['proofread'],'changes':[],'readable':'人工编辑。','summary':{}},1,0)
        versions.edit(rid,'readable',['另外编辑','比赛'],1)
        with self.assertRaises(ValueError):proof.undo(rid)

    def test_rerun_supersedes_old_pending_and_undo_restores_them(self):
        rid=self.make_run(); pending=self.result([{**CHANGE,'uncertain':True}])
        proof.apply(rid,pending,0,0)
        old=versions.get(rid)['corrections'][0]['id']
        proof.apply(rid,pending,1,1)
        self.assertEqual(sum(c['state']=='pending' for c in versions.get(rid)['corrections']),1)
        proof.undo(rid)
        self.assertEqual(next(c for c in versions.get(rid)['corrections'] if c['id']==old)['state'],'pending')

    def test_manual_queue_deduplicates_and_worker_finishes_without_asr(self):
        rid=self.make_run(); options={'proof_revision':0,'readable_revision':0,'use_search':False,'topic':'','glossary':''}
        jid=proof.enqueue(rid,options)
        self.assertEqual(jid,proof.enqueue(rid,options))
        with patch.object(proof,'prepare',return_value=self.result()),patch('app.backends.FasterWhisperBackend.transcribe') as asr:
            process(db.claim()); asr.assert_not_called()
        self.assertEqual(versions.get(rid)['raw'],ROWS)
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'],'completed')

    def test_auto_asr_pipeline_failure_still_saves_raw_and_success_creates_corrected_version(self):
        config=ASRConfig(ai_proofread=True).model_dump()
        payload={'kind':'bilibili','bv':core.BV,'part':1,'model':'small','config':config}
        db.enqueue(core.BV+':p1','url',TITLE,payload)
        with patch('app.worker.Bilibili') as adapter,patch.object(proof,'prepare',side_effect=ValueError('provider unavailable')):
            adapter.return_value.metadata.return_value={'title':TITLE,'cid':1}; adapter.return_value.subtitles.return_value=(ROWS,'zh')
            process(db.claim())
        job=self.client.get('/api/jobs').json()[0]
        self.assertEqual(job['status'],'completed'); self.assertEqual(versions.get(job['id'])['raw'],ROWS)
        self.assertEqual(versions.get(job['id'])['metrics']['ai_proofreading']['status'],'failed')
        db.enqueue(core.BV+':p2','url',TITLE,{**payload,'part':2})
        with patch('app.worker.Bilibili') as adapter,patch.object(proof,'prepare',return_value=self.result()):
            adapter.return_value.metadata.return_value={'title':TITLE,'cid':2}; adapter.return_value.subtitles.return_value=(ROWS,'zh')
            process(db.claim())
        job=self.client.get('/api/jobs').json()[0]
        self.assertIn('樊振东',versions.get(job['id'])['readable'])
        self.assertEqual(versions.get(job['id'])['raw'],ROWS)

    def test_search_uses_official_endpoint_and_only_short_candidate_query(self):
        def response(request):
            self.assertEqual(str(request.url),'https://api.deepseek.com/v1/tools/search')
            data=json.loads(request.content); self.assertEqual(data['count'],3); self.assertFalse(data['need_content'])
            self.assertLessEqual(len(data['query']),128)
            return httpx.Response(200,json={'results':[{'url':'https://example.org','title':'樊振东','snippet':'规范姓名','authority':3}]})
        client=httpx.Client(transport=httpx.MockTransport(response))
        with patch('app.proofreading.httpx.Client',return_value=client):
            self.assertEqual(len(proof.search_spelling('樊振东',TITLE,'乒乓球')),1)

    def test_pipeline_api_returns_persistent_job_and_rejects_stale_revision(self):
        rid=self.make_run(); body={'proof_revision':0,'readable_revision':0,'use_search':False}
        with patch('app.llm_settings.public',return_value={'configured':True}):
            first=self.client.post(f'/api/runs/{rid}/proofread/pipeline',json=body)
            again=self.client.post(f'/api/runs/{rid}/proofread/pipeline',json=body)
        self.assertEqual(first.status_code,200); self.assertEqual(first.json(),again.json())
        self.assertEqual(self.client.post(f'/api/runs/{rid}/proofread/pipeline',json={**body,'proof_revision':99}).status_code,409)

    def test_lost_manual_job_lease_cannot_modify_transcript(self):
        rid=self.make_run(); proof.enqueue(rid,{'proof_revision':0,'readable_revision':0,'use_search':False})
        job=db.claim()
        with db.connection() as con:con.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(job['id'],))
        with patch.object(proof,'prepare',return_value=self.result()),self.assertLogs(level='WARNING'):
            process(job)
        self.assertEqual(versions.get(rid)['proofread'],ROWS)
