import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    from . import support
except ImportError:
    import support
from harness import evaluate, runtime, util


class SavedScoringProvenanceTests(unittest.TestCase):
    def test_original_validation_failure_is_not_bypassed(self):
        with patch.object(evaluate, 'validate_repaired_scoring_provenance', side_effect=ValueError('Frozen evaluator mismatch')), patch.object(evaluate.subprocess, 'check_output') as git:
            with self.assertRaisesRegex(ValueError, 'Frozen evaluator mismatch'):
                evaluate.saved_scoring_provenance(Path('repair'), Path('original'), Path('run'), {}, Path('dll'))
            git.assert_not_called()

    def test_uncommitted_repair_is_rejected(self):
        with patch.object(evaluate, 'validate_repaired_scoring_provenance'), patch.object(evaluate.subprocess, 'check_output', return_value=' M outer/harness/evaluate.py'):
            with self.assertRaisesRegex(ValueError, 'committed clean'):
                evaluate.saved_scoring_provenance(Path('repair'), Path('original'), Path('run'), {}, Path('dll'))

    def test_original_and_repair_are_recorded_separately_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); repair=base/'repair'; old=base/'original'; run=base/'run'
            (repair/'inner/browser').mkdir(parents=True); run.mkdir(); old.mkdir()
            (repair/'inner/browser/education-review.cjs').write_text('collector')
            (run/'condition.json').write_text('{"frozen": true}'); dll=run/'evaluator.dll'; dll.write_bytes(b'frozen evaluator')
            before=util.tree_hashes(run)
            with patch.object(evaluate, 'validate_repaired_scoring_provenance') as validate, patch.object(evaluate.subprocess, 'check_output', side_effect=['', 'a'*40]), patch.object(runtime, 'controller_files', return_value={'evaluate.py':'repair-hash'}):
                receipt=evaluate.saved_scoring_provenance(repair,old,run,{'frozen':True},dll)
            validate.assert_called_once_with(old.resolve(),run,{'frozen':True},dll)
            self.assertEqual(str(old.resolve()),receipt['original_repo'])
            self.assertEqual(str(repair.resolve()),receipt['repair_repo'])
            self.assertEqual(util.sha256_file(dll),receipt['evaluator_sha256'])
            self.assertEqual(before,util.tree_hashes(run))
            self.assertEqual(0,receipt['model_calls'])
