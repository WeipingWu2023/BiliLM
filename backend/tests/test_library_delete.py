import unittest
from app import db,versions,learning
from app.quality import ASRConfig
import test_core as core


class LibraryDeleteTests(unittest.TestCase):
    setUp=core.Tests.setUp
    tearDown=core.Tests.tearDown
    key=core.BV+':p1'

    def enqueue(self):
        return db.enqueue(self.key,'local-file','可恢复的学习笔记',{'kind':'local','model':'small','file':'fixture.wav'})

    def complete(self):
        self.enqueue();job=db.claim()
        versions.commit_job(job,{'title':'可恢复的学习笔记'},core.ROWS,'fixture',ASRConfig().model_dump(),{})
        return job

    def test_delete_hides_source_runs_jobs_but_restore_preserves_transcript_and_artifacts(self):
        job=self.complete();original=versions.get(job['id'])
        artifact=learning.artifact(db.get_video(self.key),'summary')
        self.assertEqual(self.client.delete('/api/videos/'+self.key).status_code,200)
        self.assertEqual(self.client.get('/api/videos').json(),[])
        self.assertEqual(self.client.get('/api/jobs').json(),[])
        self.assertEqual(self.client.get('/api/videos?trash=true').json()[0]['id'],self.key)
        for endpoint in ('/api/videos/'+self.key,'/api/runs/'+job['id'],'/api/runs/'+job['id']+'/export','/api/videos/'+self.key+'/final/export'):
            self.assertEqual(self.client.get(endpoint).status_code,404)
        self.assertEqual(self.client.post('/api/videos/'+self.key+'/restore').status_code,200)
        self.assertEqual(self.client.get('/api/videos?trash=true').json(),[])
        self.assertEqual(versions.get(job['id'])['raw'],original['raw'])
        self.assertEqual(learning.artifact(db.get_video(self.key),'summary')['id'],artifact['id'])

    def test_active_job_cancelled_and_old_lease_cannot_commit_after_restore(self):
        self.enqueue();old=db.claim()
        self.client.delete('/api/videos/'+self.key)
        with db.connection() as con:
            self.assertEqual(con.execute('SELECT status FROM jobs WHERE id=?',(old['id'],)).fetchone()[0],'cancelled')
        with self.assertRaises(db.LeaseLost):db.update_job(old['id'],_lease_token=old['lease_token'],status='completed')
        self.client.post('/api/videos/'+self.key+'/restore')
        new=db.claim();self.assertEqual(new['id'],old['id']);self.assertNotEqual(new['lease_token'],old['lease_token'])
        with self.assertRaises(db.LeaseLost):versions.commit_job(old,{'title':'stale'},core.ROWS,'fixture',{}, {})
        self.assertIsNone(versions.get(old['id']))

    def test_queued_source_restores_one_task_and_claim_ignores_deleted_sources(self):
        self.enqueue();self.client.delete('/api/videos/'+self.key)
        self.assertIsNone(db.claim())
        with db.connection() as con:con.execute("UPDATE jobs SET status='queued' WHERE video_id=?",(self.key,))
        self.assertIsNone(db.claim())
        with db.connection() as con:con.execute("UPDATE jobs SET status='cancelled' WHERE video_id=?",(self.key,))
        self.client.post('/api/videos/'+self.key+'/restore')
        self.assertIsNotNone(db.claim());self.assertIsNone(db.claim())

    def test_failed_hidden_job_cannot_be_retried_via_old_url(self):
        jid=self.enqueue()['job_id']
        with db.connection() as con:con.execute("UPDATE jobs SET status='failed' WHERE id=?",(jid,))
        self.client.delete('/api/videos/'+self.key)
        self.assertEqual(self.client.post('/api/jobs/'+jid+'/retry').status_code,404)

    def test_reimport_restores_cached_source_without_retranscription(self):
        job=self.complete();self.client.delete('/api/videos/'+self.key)
        result=self.enqueue();self.assertTrue(result['cached'])
        self.assertEqual(db.get_video(self.key)['title'],'可恢复的学习笔记')
        self.assertEqual(len(versions.list_runs(self.key)),1);self.assertIsNone(db.claim())
        self.assertEqual(versions.get(job['id'])['raw'],core.ROWS)

    def test_idempotent_delete_restore_and_missing_note(self):
        self.complete()
        for _ in range(2):self.assertEqual(self.client.delete('/api/videos/'+self.key).status_code,200)
        for _ in range(2):self.assertEqual(self.client.post('/api/videos/'+self.key+'/restore').status_code,200)
        self.assertEqual(self.client.delete('/api/videos/missing').status_code,404)
        self.assertEqual(self.client.post('/api/videos/missing/restore').status_code,404)

    def test_restart_keeps_deleted_state_and_immutable_data(self):
        job=self.complete();self.client.delete('/api/videos/'+self.key)
        db.init();db.init()
        self.assertIsNone(db.get_video(self.key));self.assertEqual(versions.get(job['id'])['raw'],core.ROWS)
        self.assertEqual(len(self.client.get('/api/videos?trash=true').json()),1)
