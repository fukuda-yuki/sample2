"""The scorer gives submitted apps only the declared public import file."""
from pathlib import Path
import tempfile
import unittest

import support
from harness import runtime


class ScoringImportInputTests(unittest.TestCase):
    def test_declared_public_raw_file_is_readonly_and_private_oracle_is_not_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('initial-store.sqlite', 'legacy-school.sqlite', 'migration-oracle.json'):
                (root / name).write_bytes(b'fixture')
            base = {'runtime_lock': {'images': {'evaluator': 'fixture-image'}},
                    'evaluation': {'assembly': 'Education.Evaluator.dll'}}
            for declared, expected in ((None, 'initial-store.sqlite'),
                                       ('legacy-school.sqlite', 'legacy-school.sqlite')):
                migration = {'initial_database': 'initial-store.sqlite'}
                if declared: migration['import_input'] = declared
                condition = {**base, 'evaluation': {**base['evaluation'], 'migration_contract': migration}}
                _, cmd = runtime.scoring_command(condition, root/'artifact', root/'out', root/'work',
                                                 root, 'fixture-version', 1)
                input_mounts = [part for part in cmd if 'target=/inputs/' in part]
                self.assertEqual(len(input_mounts), 1)
                self.assertIn('target=/inputs/existing-business/' + expected, input_mounts[0])
                self.assertIn('readonly', input_mounts[0])
                self.assertNotIn('migration-oracle', input_mounts[0])
                if declared: self.assertNotIn('initial-store.sqlite', input_mounts[0])
            for name in ('migration-oracle.json', '../initial-store.sqlite', 'missing.sqlite'):
                condition = {**base, 'evaluation': {**base['evaluation'], 'migration_contract': {'import_input': name}}}
                with self.assertRaises(ValueError):
                    runtime.scoring_command(condition, root/'artifact', root/'out', root/'work',
                                            root, 'fixture-version', 1)
            (root / 'legacy-school.sqlite').unlink()
            condition = {**base, 'evaluation': {**base['evaluation'], 'migration_contract': {'import_input': 'legacy-school.sqlite'}}}
            with self.assertRaisesRegex(ValueError, 'requires its frozen'):
                runtime.scoring_command(condition, root/'artifact', root/'out', root/'work',
                                        root, 'fixture-version', 1)


if __name__ == '__main__': unittest.main()
