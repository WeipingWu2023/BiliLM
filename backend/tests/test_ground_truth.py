"""Workflow safety tests use temporary synthetic fixtures, never production truth."""
import json
import shutil
import sqlite3
import subprocess
import wave
from pathlib import Path
from unittest.mock import patch
import unittest
import test_core as core
from app import db, versions, ground_truth as gt
from app.benchmark_report import verified_clips


class GroundTruthTests(unittest.TestCase):
    setUp = core.Tests.setUp
    tearDown = core.Tests.tearDown
    cid = 'mandarin-01'

    def prepare(self, cid=None, run=None, revision=0):
        source = db.DATA / 'fixture-source.wav'
        source.write_bytes(b'original authorized fixture; no real speech')

        def extract(command, **_):
            duration = float(command[command.index('-t') + 1])
            with wave.open(command[-1], 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\0\0' * int(16000 * duration))

        with patch.object(gt, '_duration', return_value=240), patch.object(gt.subprocess, 'run', side_effect=extract):
            return gt.prepare(cid or self.cid, source, 10, 60, revision, True, run,
                              {'kind':'test-fixture', 'filename':source.name})

    def draft(self, clip=None, **changes):
        clip = clip or self.prepare()
        body = {key:clip[key] for key in ('revision', 'title', 'stratum', 'category', 'terms',
                                         'reference', 'reference_segments', 'notes', 'annotations')}
        body.update({'reference':'你好，Python。\n这个片段仅用于自动测试。', 'category':'测试夹具', 'terms':['Python']})
        body.update(changes)
        return gt.save(clip['id'], body)

    def verified(self):
        clip = self.draft()
        return gt.verify(self.cid, clip['revision'], 'fixture-only-reviewer', True, True)

    def test_nine_slots_are_empty_and_idempotent(self):
        db.init()
        rows = self.client.get('/api/ground-truth/clips').json()
        self.assertEqual(len(rows), 9)
        self.assertEqual({stratum:sum(row['stratum'] == stratum for row in rows) for stratum in gt.STRATA},
                         dict.fromkeys(gt.STRATA, 3))
        self.assertTrue(all(row['state'] == 'empty' and row['reference'] == '' and not row['human_verified']
                            and row['machine'] == [] and row['audio'] is None for row in rows))
        self.assertEqual(self.client.post('/api/ground-truth/export').status_code, 409)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg integration requires installed binaries')
    def test_real_ffmpeg_crop_and_http_range_without_inference(self):
        # Silence is media plumbing evidence only; it is never verified or scored as ground truth.
        source=db.DATA/'media-plumbing-only.wav'
        with wave.open(str(source),'wb') as audio:
            audio.setparams((1,2,16000,0,'NONE','not compressed'))
            audio.writeframes(b'\0\0'*(61*16000))
        digest=gt._hash(source)
        clip=gt.prepare(self.cid,source,1,60,0,True,provenance={'kind':'synthetic-test-fixture-not-ground-truth'})
        self.assertAlmostEqual(clip['duration'],60,places=2)
        self.assertEqual(gt._hash(source),digest)
        self.assertEqual(clip['reference'],'')
        self.assertFalse(clip['human_verified'])
        response=self.client.get(f'/api/ground-truth/clips/{self.cid}/audio',headers={'range':'bytes=0-43'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(response.content[:4],b'RIFF')
        self.assertEqual(len(response.content),44)
        self.assertEqual(self.client.post('/api/ground-truth/export').status_code,409)

    def test_prepare_projects_machine_but_leaves_reference_empty(self):
        run = {'raw':[{'start':5, 'end':12, 'text':'边界机器稿'},
                      {'start':12, 'end':18, 'text':'Python 机器稿'},
                      {'start':75, 'end':80, 'text':'范围外'}], 'provenance':'test-asr'}
        clip = self.prepare(run=run)
        self.assertEqual(clip['reference'], '')
        self.assertFalse(clip['human_verified'])
        self.assertEqual(clip['machine'], [
            {'start':0, 'end':2, 'text':'边界机器稿', 'boundary_truncated':True},
            {'start':2, 'end':8, 'text':'Python 机器稿', 'boundary_truncated':False}])
        self.assertEqual(clip['source']['machine_kind'], 'projected_source_run_display_only')
        self.assertEqual(clip['source']['preprocessing'],
                         {'sample_rate':16000, 'channels':1, 'codec':'pcm_s16le', 'denoise':False})
        self.assertEqual(clip['source']['source_start'], 10)
        self.assertEqual((db.DATA / 'fixture-source.wav').read_bytes(), b'original authorized fixture; no real speech')

    def test_preparation_requires_authorization_and_valid_short_range(self):
        with patch.object(gt.subprocess, 'run') as run:
            for start, duration, authorized in [(0,60,False), (0,59,True), (0,181,True),
                                                (-1,60,True), (float('nan'),60,True)]:
                with self.subTest(start=start, duration=duration, authorized=authorized), self.assertRaises(ValueError):
                    gt.prepare(self.cid, db.DATA / 'source.wav', start, duration, 0, authorized)
            run.assert_not_called()
        self.assertEqual(gt.get(self.cid)['state'], 'empty')
        with patch.object(gt, '_duration', return_value=30), self.assertRaisesRegex(ValueError, '超过'):
            gt.prepare(self.cid, db.DATA / 'source.wav', 0, 60, 0, True)

    def test_stale_save_and_prepare_cannot_overwrite(self):
        clip = self.prepare()
        saved = self.draft(clip)
        with self.assertRaisesRegex(ValueError, '变化'):
            self.draft(clip, reference='过期编辑')
        with self.assertRaisesRegex(ValueError, '变化'):
            self.prepare(revision=clip['revision'])
        self.assertEqual(gt.get(self.cid)['reference'], saved['reference'])
        self.assertEqual(gt.get(self.cid)['audio'], saved['audio'])

    def test_verification_is_explicit_and_rejects_uncertainty(self):
        clip = self.draft(annotations=[{'start':1, 'end':2, 'kind':'uncertain', 'note':'尚未听清'}])
        for reviewer, listened, language in [('',True,True), ('reviewer',False,True), ('reviewer',True,False)]:
            with self.subTest(reviewer=reviewer, listened=listened, language=language), self.assertRaises(ValueError):
                gt.verify(self.cid, clip['revision'], reviewer, listened, language)
        with self.assertRaisesRegex(ValueError, '不确定'):
            gt.verify(self.cid, clip['revision'], 'reviewer', True, True)
        clip = self.draft(clip, annotations=[])
        verified = gt.verify(self.cid, clip['revision'], ' fixture-only-reviewer ', True, True)
        self.assertTrue(verified['human_verified'])
        self.assertEqual(verified['reviewer'], 'fixture-only-reviewer')
        self.assertTrue(verified['verified_at'])

    def test_verified_edits_invalidate_review_and_keep_history(self):
        verified = self.verified()
        edited = self.draft(verified, reference='人工修改后的参考稿')
        self.assertFalse(edited['human_verified'])
        self.assertEqual(edited['state'], 'draft')
        self.assertEqual(edited['reviewer'], '')
        self.assertIsNone(edited['verified_at'])
        snapshots = [json.loads(row['snapshot']) for row in gt.history(self.cid)]
        self.assertEqual(snapshots[-1]['reference'], verified['reference'])
        self.assertTrue(snapshots[-1]['human_verified'])
        with self.assertRaises(sqlite3.IntegrityError), db.connection() as con:
            con.execute('UPDATE benchmark_history SET event=?', ('tampered',))
        with self.assertRaises(sqlite3.IntegrityError), db.connection() as con:
            con.execute('DELETE FROM benchmark_history')

    def test_reprepare_retains_old_clip_and_resets_verification(self):
        verified = self.verified()
        old = gt.audio_path(verified)
        replacement = self.prepare(revision=verified['revision'])
        self.assertNotEqual(verified['audio'], replacement['audio'])
        self.assertTrue(old.exists())
        self.assertEqual(replacement['reference'], '')
        self.assertEqual(replacement['reviewer'], '')
        self.assertFalse(replacement['human_verified'])
        self.assertEqual(json.loads(gt.history(self.cid)[-1]['snapshot'])['audio'], verified['audio'])

    def test_audio_tampering_blocks_verify_and_export(self):
        clip = self.draft()
        path = gt.audio_path(clip)
        original = path.read_bytes()
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, '音频内容已变化'):
            gt.verify(self.cid, clip['revision'], 'reviewer', True, True)
        path.write_bytes(original)
        verified = gt.verify(self.cid, clip['revision'], 'reviewer', True, True)
        gt.audio_path(verified).write_bytes(b'changed after review')
        with self.assertRaisesRegex(ValueError, '拒绝导出'):
            gt.export_manifest()

    def test_manifest_is_hash_matched_and_compatible_with_existing_benchmark(self):
        verified = self.verified()
        exported = gt.export_manifest()
        manifest = json.loads(Path(exported['manifest_path']).read_text(encoding='utf-8'))
        accepted, rejected = verified_clips(manifest, Path(exported['manifest_path']).parent)
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        clip, audio, digest = accepted[0]
        self.assertEqual(audio, gt.audio_path(verified))
        self.assertEqual(clip['reference'], verified['reference'])
        self.assertEqual(digest, verified['audio_sha256'])
        self.assertEqual(clip['terms'], ['Python'])
        self.assertEqual(clip['source']['kind'], 'test-fixture')
        response = self.client.get('/api/ground-truth/datasets/' + exported['dataset_id'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), manifest)

    def test_timestamp_mapping_and_annotation_bounds_are_validated(self):
        clip = self.prepare()
        for changes in [
            {'reference_segments':[{'start':0, 'end':5, 'text':'伪造文字'}]},
            {'reference_segments':[{'start':0, 'end':61, 'text':'你好，Python。这个片段仅用于自动测试。'}]},
            {'annotations':[{'start':2, 'end':1, 'kind':'missing_speech'}]},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.draft(clip, **changes)
        saved = self.draft(clip, reference_segments=[
            {'start':0, 'end':5, 'text':'你好 Python'},
            {'start':6, 'end':20, 'text':'这个片段仅用于自动测试'}])
        self.assertEqual(saved['reference'], '你好，Python。\n这个片段仅用于自动测试。')
        self.assertEqual(len(saved['reference_segments']), 2)

    def test_api_import_boundaries_do_not_start_processing(self):
        with patch.object(gt.subprocess, 'run') as ffmpeg:
            response = self.client.post('/api/ground-truth/clips/mandarin-01/upload',
                files={'file':('authorized.wav',b'fixture')}, data={'revision':0,'authorized':'false'})
            self.assertEqual(response.status_code, 400)
            response = self.client.post('/api/ground-truth/clips/mandarin-01/upload',
                files={'file':('untrusted.exe',b'fixture')}, data={'revision':0,'authorized':'true'})
            self.assertEqual(response.status_code, 400)
            ffmpeg.assert_not_called()
        self.assertEqual(self.client.get('/api/ground-truth/datasets/invalid').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_explicit_run_must_belong_to_selected_local_source(self):
        uploads = db.DATA / 'uploads'
        uploads.mkdir()
        (uploads / 'retained.wav').write_bytes(b'original local fixture')
        key = 'local:fixture'
        db.enqueue(key, 'local-file', 'Local fixture', {'kind':'local', 'file':'retained.wav'})
        versions.create('unrelated-run', 'other-video', core.ROWS, 'test-asr', {}, {})
        for rid in ('unrelated-run', 'unknown-run'):
            with self.subTest(rid=rid), self.assertRaises(ValueError):
                gt.source_for_video(key, rid)
        path, run, _ = gt.source_for_video(key)
        self.assertEqual(path, uploads / 'retained.wav')
        self.assertIsNone(run)

    def test_invalid_media_returns_actionable_client_error(self):
        with patch.object(gt, 'source_for_video', return_value=(db.DATA / 'bad.wav', None, {})), \
             patch.object(gt, 'prepare', side_effect=subprocess.CalledProcessError(1, ['ffmpeg'], stderr=b'invalid media')):
            response = self.client.post('/api/ground-truth/clips/mandarin-01/prepare', json={
                'video_id':'local:fixture', 'start':0, 'duration':60, 'revision':0, 'authorized':True})
        self.assertIn(response.status_code, (400, 409))
        self.assertTrue(response.json().get('detail'))


if __name__ == '__main__':
    unittest.main()
