import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('release_check', Path(__file__).resolve().parents[2] / 'scripts' / 'check_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_private_paths_and_credentials_are_rejected_without_echoing_values(self):
        for path in ('data/llm-settings.json', 'frontend/node_modules/x.js', '.env.local', 'backup.sqlite3'):
            self.assertTrue(release.problems(path, b'{}'))
        key = b'sk-' + b'x' * 32
        result = release.problems('settings.py', key)
        self.assertTrue(result)
        self.assertNotIn(key.decode(), str(result))
        self.assertEqual(release.problems('backend/app/main.py', b'key = os.getenv("API_KEY")'), [])
