from pathlib import Path
import tempfile
import unittest
from tools.init_local_profile import PROFILES, initialize

class LocalProfileTests(unittest.TestCase):
    def test_existing_personal_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            templates = root / 'templates/local-profile'
            templates.mkdir(parents=True)
            for name in PROFILES.values():
                (templates / name).write_text('Safe placeholder', encoding='utf-8')
            (root / 'CLAUDE.md').write_text('Private local profile', encoding='utf-8')
            created = initialize(root)
            self.assertNotIn('CLAUDE.md', created)
            self.assertEqual((root / 'CLAUDE.md').read_text(), 'Private local profile')
            self.assertEqual(len(created), len(PROFILES) - 1)
            self.assertEqual(initialize(root), [])
