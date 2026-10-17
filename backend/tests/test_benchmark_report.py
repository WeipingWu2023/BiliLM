import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.benchmark_report import build_report, render_markdown


class BenchmarkReportTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'data' / 'tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.directory = Path(self.temporary.name)
        self.audio = self.directory / 'clip.wav'
        self.audio.write_bytes(b'fixed-authorized-test-audio')
        self.digest = hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.clip = {'id':'mandarin-01', 'stratum':'mandarin', 'audio':'clip.wav', 'audio_sha256':self.digest,
                     'reference':'你好 Python API', 'reference_segments':[{'start':0, 'end':2, 'text':'你好 Python API'}],
                     'terms':['API'], 'human_verified':True, 'reviewer':'test listener', 'revision':2, 'category':'编程'}
        self.prediction = {'source_audio_sha256':self.digest, 'segments':[{'start':0, 'end':2, 'text':'你好 Python API API'}],
                           'config':{'backend':'faster-whisper', 'model':'small', 'beam_size':5, 'device':'cpu'},
                           'metrics':{'elapsed_seconds':3, 'peak_rss_bytes':1024, 'weights_sha256':'fixed',
                                      'decoding_effective':{'beam_size':5}, 'compute_type':'int8'}, 'provenance':'raw-asr'}

    def tearDown(self):
        self.temporary.cleanup()

    def report(self, predictions):
        return build_report({'clips':[self.clip]}, self.directory, {'mandarin-01':predictions})

    def test_unverified_and_audio_mismatch_never_score(self):
        self.clip['human_verified'] = False
        report = self.report(self.prediction)
        self.assertEqual(report['verified_clips'], 0)
        self.assertFalse(report['groups'])
        markdown = render_markdown(report)
        self.assertIn('普通话', markdown)
        self.assertIn('粤语', markdown)
        self.assertIn('中英混合', markdown)
        self.assertIn('未测', markdown)
        self.assertNotIn('0.00%', markdown)
        self.clip['human_verified'] = True
        self.audio.write_bytes(b'changed since review')
        self.assertIn('SHA256', self.report(self.prediction)['rejected_clips'][0]['reason'])

    def test_raw_text_and_complete_metrics_are_retained(self):
        report = self.report(self.prediction)
        row = report['results'][0]
        self.assertEqual(row['reference'], self.clip['reference'])
        self.assertEqual(row['reference_revision'], 2)
        self.assertEqual(row['segments'], self.prediction['segments'])
        self.assertEqual(row['execution'], self.prediction['metrics'])
        self.assertEqual(row['scores']['terms'][0]['extra_count'], 1)
        self.assertIsNone(report['default_recommendation'])
        self.assertEqual(report['missing_predictions'][0]['model'], 'SenseVoiceSmall')

    def test_config_and_resolved_settings_do_not_blend(self):
        beam = copy.deepcopy(self.prediction)
        beam['config']['beam_size'] = 8
        device = copy.deepcopy(self.prediction)
        device['config']['device'] = 'cuda'
        weights = copy.deepcopy(self.prediction)
        weights['metrics']['weights_sha256'] = 'different revision'
        proofread = copy.deepcopy(self.prediction)
        proofread['provenance'] = 'text-only-proofread'
        report = self.report([self.prediction, beam, device, weights, proofread])
        self.assertEqual(len(report['groups']), 5)
        self.assertTrue(all(len(group['clip_ids']) == 1 for group in report['groups'].values()))

    def test_coarse_timestamps_and_annotation_attribution_are_not_verified_alignment(self):
        prediction = copy.deepcopy(self.prediction)
        prediction['config'] = {'backend':'sensevoice', 'model':'SenseVoiceSmall', 'device':'cpu'}
        prediction['metrics']['timestamp_quality'] = 'input-window-only'
        prediction['metrics']['raw_model_outputs'] = [{'model_text':'<|zh|>你好'}]
        self.clip['annotations'] = [
            {'kind':'cantonese_error', 'model':'SenseVoiceSmall', 'note':'人工听音注释'},
            {'kind':'hallucinated_speech', 'note':'未说明模型，不计入模型统计'},
            {'kind':'missing_speech', 'model':'small', 'note':'另一模型'}]
        report = self.report(prediction)
        row = report['results'][0]
        self.assertIsNone(row['scores']['timestamp_mae_seconds'])
        self.assertIsNone(row['scores']['missing_reference_segments'])
        self.assertIsNone(row['scores']['speech_in_verified_silence_candidates'])
        self.assertEqual(len(row['human_annotations']), 1)
        self.assertIn('raw_model_outputs', row['execution'])

    def test_missing_bad_predictions_and_repeated_trials_are_explicit(self):
        invalid = copy.deepcopy(self.prediction)
        invalid['source_audio_sha256'] = 'wrong'
        failed = {'config':{'backend':'sensevoice', 'model':'SenseVoiceSmall'}, 'status':'unavailable', 'error':'not installed'}
        report = self.report([invalid, failed])
        self.assertEqual(len(report['missing_predictions']), 2)
        self.assertEqual([row['status'] for row in report['results']], ['rejected', 'unavailable'])
        repeated = self.report([self.prediction, self.prediction])
        group = next(iter(repeated['groups'].values()))
        self.assertIsNone(group['summary'])
        self.assertEqual(group['duplicate_clip_predictions'], ['mandarin-01'])

    def test_paired_scores_use_only_the_identical_common_clips(self):
        other = copy.deepcopy(self.clip)
        other['id'] = 'mandarin-02'
        voice = copy.deepcopy(self.prediction)
        voice['config'] = {'backend':'sensevoice', 'model':'SenseVoiceSmall', 'device':'cpu'}
        report = build_report({'clips':[self.clip, other]}, self.directory,
                              {self.clip['id']:[self.prediction, voice], other['id']:[self.prediction]})
        pair = report['paired_coverage'][0]
        self.assertEqual(pair['common_clips'], ['mandarin-01'])
        self.assertEqual(pair['unpaired_clips'], ['mandarin-02'])
        self.assertTrue(all(summary['clips'] == 1 for summary in pair['summaries'].values()))

    def test_cli_is_dry_by_default_even_with_verified_audio(self):
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'benchmark.py'
        spec = importlib.util.spec_from_file_location('benchmark_cli_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest = self.directory / 'manifest.json'
        output = self.directory / 'report.json'
        manifest.write_text(json.dumps({'clips':[self.clip]}), encoding='utf-8')
        with patch.object(module, 'run_prediction', side_effect=AssertionError('inference must remain explicit')):
            module.main([str(manifest), '--output', str(output)])
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['verified_clips'], 1)
        self.assertEqual(report['results'], [])
        self.assertTrue(output.with_suffix('.md').is_file())


if __name__ == '__main__':
    unittest.main()
