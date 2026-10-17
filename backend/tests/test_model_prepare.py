import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import test_core as core

spec = importlib.util.spec_from_file_location('prepare_models', Path(__file__).resolve().parents[2] / 'scripts' / 'prepare_models.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PreparationTests(unittest.TestCase):
    setUp = core.Tests.setUp
    tearDown = core.Tests.tearDown

    def test_cached_models_are_reused_without_network_or_inference(self):
        with patch('sys.argv', ['prepare_models.py', '--models', 'medium', 'turbo', '--sensevoice']), patch.object(prepare.model_manager, 'cached', return_value=True), patch.object(prepare.model_manager, 'download') as download, patch.object(prepare.sensevoice, 'download_snapshot') as sense:
            prepare.main()
            download.assert_not_called()
            sense.assert_not_called()

    def test_failed_download_is_not_reported_as_ready(self):
        with patch('sys.argv', ['prepare_models.py', '--models', 'turbo']), patch.object(prepare.model_manager, 'cached', return_value=False), patch.object(prepare.model_manager, 'download') as download:
            with self.assertRaisesRegex(RuntimeError, 'not complete'):
                prepare.main()
            download.assert_called_once_with('turbo')
