import json
import os
import unittest
from unittest.mock import patch
import httpx
import test_core as core
from app import db, versions, learning, llm_settings
from app.quality import ASRConfig
from app.reasoning import OpenAICompatible


class LearningTests(unittest.TestCase):
    setUp=core.Tests.setUp
    tearDown=core.Tests.tearDown
    complete=core.Tests.complete
    enqueue=core.Tests.enqueue
    key=core.BV+':p1'

    def make_source(self):
        self.complete()
        versions.create('learning-run',self.key,core.ROWS,'test-asr',ASRConfig().model_dump(),{})
        return db.get_video(self.key)

    def test_readable_exports_do_not_append_timestamps_or_duplicate_raw(self):
        self.make_source()
        for path in (f'/api/videos/{self.key}/export?format=md','/api/runs/learning-run/export?version=readable&format=md'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('原始时间轴',response.text)
            self.assertNotIn('[00:',response.text)
            self.assertEqual(response.text.count('学习 Python'),1)
        self.assertIn('-->',self.client.get('/api/runs/learning-run/export?version=raw&format=srt').text)

    def test_local_summary_and_map_are_extracts_not_ai(self):
        video=self.make_source()
        with patch.object(OpenAICompatible,'answer',side_effect=AssertionError('offline must not call provider')):
            summary=learning.artifact(video,'summary')
            tree=learning.artifact(video,'mindmap')
        self.assertEqual(summary['mode'],'extractive')
        self.assertFalse(summary['audio_verified'])
        self.assertEqual(summary['items'][0]['text'],core.ROWS[0]['text'])
        self.assertTrue(tree['branches'][0]['children'])
        self.assertFalse(summary['cached'])
        self.assertTrue(learning.artifact(video,'summary')['cached'])
        self.assertEqual(versions.get('learning-run')['raw'],core.ROWS)

    def test_cache_changes_when_source_is_manually_corrected(self):
        video=self.make_source(); old=learning.artifact(video,'summary')
        run=versions.get('learning-run')
        versions.edit('learning-run','proofread',['你好世界','学习 API。'],run['proof_revision'])
        new=learning.artifact(video,'summary')
        self.assertNotEqual(old['source_hash'],new['source_hash'])
        self.assertEqual(new['items'][-1]['text'],'学习 API。')
        self.assertEqual(versions.get('learning-run')['raw'],core.ROWS)

    def test_ai_summary_is_validated_and_cached_without_mutating_source(self):
        video=self.make_source()
        value={'overview':'关于学习的概括。','items':[{'text':'提到 Python。','citations':[1]}],'questions':['学习了什么？']}
        with patch.dict(os.environ,{'BILILM_LLM_URL':'https://example.test/v1'}),patch.object(OpenAICompatible,'answer',return_value=json.dumps(value)) as model:
            result=learning.artifact(video,'summary',external=True)
            self.assertTrue(learning.artifact(video,'summary',external=True)['cached'])
            model.assert_called_once()
        self.assertEqual(result['mode'],'llm')
        self.assertEqual(result['items'][0]['citations'],[1])
        self.assertEqual(versions.get('learning-run')['raw'],core.ROWS)

    def test_ai_malformed_output_and_invalid_source_ids_are_not_saved(self):
        video=self.make_source()
        for value in ('not-json',json.dumps({'overview':'a','items':[{'text':'b','citations':[999]}],'questions':['q']})):
            with patch.dict(os.environ,{'BILILM_LLM_URL':'https://example.test/v1'}),patch.object(OpenAICompatible,'answer',return_value=value),self.assertRaises(ValueError):
                learning.artifact(video,'summary',external=True)
        with db.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM learning_artifacts').fetchone()[0],0)

    def test_ai_mindmap_hierarchy_carries_valid_source_ids(self):
        video=self.make_source()
        value={'branches':[{'text':'学习','citations':[1],'children':[{'text':'Python','citations':[1]}]}]}
        with patch.dict(os.environ,{'BILILM_LLM_URL':'https://example.test/v1'}),patch.object(OpenAICompatible,'answer',return_value=json.dumps(value)):
            result=learning.artifact(video,'mindmap',external=True)
        self.assertEqual(result['branches'][0]['children'][0]['citations'],[1])

    def test_mismatched_run_unavailable_source_and_unconfigured_ai(self):
        self.make_source()
        self.assertEqual(self.client.post(f'/api/videos/{self.key}/learning',json={'kind':'summary','run_id':'unknown'}).status_code,400)
        with patch.dict(os.environ,{'BILILM_LLM_URL':''}):
            self.assertEqual(self.client.post(f'/api/videos/{self.key}/learning',json={'kind':'summary','external':True}).status_code,400)
        self.assertEqual(self.client.post(f'/api/videos/{self.key}/learning',json={'kind':'unsupported'}).status_code,422)

    def test_deepseek_settings_are_local_and_never_return_secret(self):
        key='fixture-key-not-real'
        response=self.client.put('/api/llm/settings',json={'api_key':key,'model':'deepseek-flash'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn(key,response.text)
        self.assertNotIn(key,self.client.get('/api/llm/settings').text)
        self.assertTrue(self.client.get('/api/health').json()['llm_configured'])
        self.client.put('/api/llm/settings',json={'api_key':'','model':'deepseek-v4-pro'})
        self.assertEqual(llm_settings.load()['key'],key)
        self.assertEqual(llm_settings.load()['model'],'deepseek-v4-pro')
        self.assertEqual(self.client.put('/api/llm/settings',json={'api_key':'bad\nkey'}).status_code,400)

    def test_deepseek_request_uses_verified_endpoint_and_non_thinking_mode(self):
        llm_settings.save_deepseek('fixture-only','deepseek-flash')
        captured=[]
        def respond(request):
            captured.append(request)
            return httpx.Response(200,json={'choices':[{'message':{'content':'依据来源 [00:00:03]。'}}]})
        client=httpx.Client(transport=httpx.MockTransport(respond))
        with patch('app.reasoning.httpx.Client',return_value=client):
            self.assertIn('依据来源',OpenAICompatible().answer('问题','来源内容',json_mode=True))
        body=json.loads(captured[0].content)
        self.assertEqual(str(captured[0].url),'https://api.deepseek.com/chat/completions')
        self.assertEqual(body['thinking'],{'type':'disabled'})
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertEqual(captured[0].headers['authorization'],'Bearer fixture-only')

    def test_provider_errors_are_actionable_without_secret_urls(self):
        self.make_source(); llm_settings.save_deepseek('fixture-only','deepseek-flash')
        request=httpx.Request('POST','https://api.deepseek.com/chat/completions')
        error=httpx.HTTPStatusError('secret debug must not leak',request=request,response=httpx.Response(401,request=request))
        with patch.object(OpenAICompatible,'answer',side_effect=error):
            r=self.client.post(f'/api/videos/{self.key}/learning',json={'kind':'summary','external':True})
        self.assertEqual(r.status_code,502)
        self.assertIn('API Key',r.json()['detail'])
        self.assertNotIn('secret debug',r.text)

    def test_generic_source_question_works_without_exact_keyword(self):
        self.make_source()
        response=self.client.post(f'/api/videos/{self.key}/ask',json={'question':'这份来源主要讲了什么？'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['mode'],'local-search')
        self.assertTrue(response.json()['citations'])

    def test_ai_followup_history_and_only_linked_timestamp_citations(self):
        self.make_source(); llm_settings.save_deepseek('fixture-only','deepseek-flash')
        history=[{'role':'user','content':'前一个问题'},{'role':'assistant','content':'前一个回答'}]
        with patch.object(OpenAICompatible,'answer',return_value='来源提到 Python [00:00:03]，未知标签 [99:99:99]。') as model:
            response=self.client.post(f'/api/videos/{self.key}/ask',json={'question':'进一步解释','external':True,'history':history})
        self.assertEqual(response.status_code,200)
        self.assertEqual(model.call_args.args[2],history)
        self.assertEqual(response.json()['citations'],[core.ROWS[1]])
        self.assertEqual(self.client.post(f'/api/videos/{self.key}/ask',json={'question':'x','history':[{'role':'system','content':'invalid'}]}).status_code,422)

    def test_oversized_source_is_not_silently_cut_or_sent(self):
        video=self.make_source()
        with patch.dict(os.environ,{'BILILM_LLM_URL':'https://example.test/v1'}),patch.object(learning,'source',return_value=([{'start':0,'end':1,'text':'原文'*30000}],'test')),patch.object(OpenAICompatible,'answer') as model:
            with self.assertRaisesRegex(ValueError,'未截断'):
                learning.artifact(video,'summary',external=True)
            model.assert_not_called()
