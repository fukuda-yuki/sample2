"""A saved correction must still refer to the independently selected artifact."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outer.harness import browser_cart, util
from research import browser_rejudge


class SavedBrowserIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root/'run'
        (self.run/'frozen').mkdir(parents=True)
        (self.run/'frozen/app.cs').write_text('saved generated source')
        (self.run/'evaluation-assets').mkdir()
        (self.run/'evaluation-assets/requirements.json').write_text('saved public contract')
        for path in ('inner/browser/cart-review.cjs', 'outer/harness/browser_cart.py', 'bundle/MusicStore.Evaluator.dll'):
            file = self.root/path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('synthetic guard test')
        self.baseline = self.root/'baseline'; self.baseline.mkdir()
        util.write_new_json(self.baseline/'evaluation.json', {
            'quality': 100, 'verdict': 'pass', 'requirements': [], 'evaluationId': 'baseline'})
        prior = self.root/'prior'; prior.mkdir()
        util.write_new_json(prior/'summary.json', {'corrections': []})
        util.write_new_json(self.root/'inventory.json', {'runs': [{
            'run_instance_id': 'instance', 'run_id': 'sample', 'cohort': 'pilot', 'root': 'run'}]})
        util.write_new_json(self.root/'quality.json', {'human_review_selection': [], 'rows': [{
            'run_instance_id': 'instance', 'run_id': 'sample', 'cohort': 'pilot', 'condition': 'explore',
            'calls': 1, 'usage_complete': True, 'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 15,
            'original_quality': 100, 'original_verdict': 'pass', 'corrected_quality': 100, 'corrected_verdict': 'pass'}]})

    def resume(self, artifact=None, spec=None):
        result = self.root/'out/instance/result'; result.mkdir(parents=True)
        review = result/'browser-cart'; review.mkdir()
        artifact = artifact or util.artifact_hash(self.run/'frozen')
        spec = spec or util.sha256_file(self.run/'evaluation-assets/requirements.json')
        removals = []
        for check in ('C-015', 'C-016'):
            row = {'checkId': check}
            for kind in ('before', 'after', 'beforeScreenshot', 'afterScreenshot'):
                name = check + '-' + kind
                (review/name).write_text('synthetic evidence completeness test')
                row[kind] = {'path': name, 'sha256': util.sha256_file(review/name)}
            removals.append(row)
        util.write_new_json(review/'receipt.json', {'actor': 'agent', 'runInstanceId': 'instance',
            'artifactSha256': artifact, 'specSha256': spec, 'removals': removals})
        util.write_new_json(result/'evaluation.json', {'quality': 100, 'verdict': 'pass', 'requirements': [],
            'evaluationId': 'correction', 'artifactSha256': artifact, 'specSha256': spec,
            'researchStatus': 'complete', 'browserCartCoverage': browser_cart.OBSERVED,
            'reviewRunInstanceId': 'instance', 'browserCartEvidenceSha256': util.sha256_file(review/'receipt.json')})
        with patch.object(browser_rejudge, 'target', return_value=(self.run, {}, self.baseline, None)):
            return browser_rejudge.run_batch(self.root, self.root/'inventory.json', self.root/'prior',
                self.root/'quality.json', self.root/'bundle', self.root/'out')['rows'][0]

    def test_bound_saved_evidence_remains_complete(self):
        row = self.resume()
        self.assertEqual('complete', row['browser_state'])
        self.assertEqual('pass', row['verdict'])

    def test_internally_consistent_other_artifact_is_incomplete(self):
        row = self.resume(artifact='another-artifact')
        self.assertEqual('evaluation_incomplete', row['browser_state'])
        self.assertIsNone(row['quality'])
        self.assertIsNone(row['verdict'])

    def test_internally_consistent_other_spec_is_incomplete(self):
        row = self.resume(spec='another-public-contract')
        self.assertEqual('evaluation_incomplete', row['browser_state'])
        self.assertIsNone(row['quality'])
        self.assertIsNone(row['verdict'])

    def test_pending_cleanup_stops_resumed_batch_without_observing_again(self):
        self.resume()
        result = self.root/'out/instance/result'
        util.write_new_json(result/'browser-resources.json', {'owner': 'test owner'})
        util.write_new_json(result/'browser-cleanup.json', {'confirmed': False, 'status': 'cleanup_failed'})
        with patch.object(browser_rejudge, 'target', return_value=(self.run, {}, self.baseline, None)), \
                patch.object(browser_cart, 'complete_evaluation') as observe:
            with self.assertRaisesRegex(RuntimeError, 'still need cleanup'):
                browser_rejudge.run_batch(self.root, self.root/'inventory.json', self.root/'prior',
                    self.root/'quality.json', self.root/'bundle', self.root/'out')
        observe.assert_not_called()


if __name__ == '__main__': unittest.main()
