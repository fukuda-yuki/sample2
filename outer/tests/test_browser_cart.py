"""Evidence completeness is a prerequisite for research aggregation."""
import tempfile
import unittest
from pathlib import Path

try:
    from . import support
except ImportError:
    import support
from harness import browser_cart, util


class BrowserCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.review = self.root/'browser-cart'; self.review.mkdir()
        removals = []
        for check in ('C-015', 'C-016'):
            row = {'checkId': check}
            for kind in ('before', 'after', 'beforeScreenshot', 'afterScreenshot'):
                name = check + '-' + kind
                (self.review/name).write_text('synthetic coverage test only')
                row[kind] = {'path': name, 'sha256': util.sha256_file(self.review/name)}
            removals.append(row)
        util.write_new_json(self.review/'receipt.json', {'actor': 'agent', 'runInstanceId': 'instance',
            'artifactSha256': 'artifact', 'specSha256': 'spec', 'removals': removals})
        self.output = {'researchStatus': 'complete', 'browserCartCoverage': browser_cart.OBSERVED,
            'reviewRunInstanceId': 'instance', 'artifactSha256': 'artifact', 'specSha256': 'spec',
            'browserCartEvidenceSha256': util.sha256_file(self.review/'receipt.json')}
        util.write_new_json(self.root/'evaluation.json', self.output)

    def covered(self, instance='instance', artifact='artifact', spec='spec'):
        return browser_cart.stored_coverage_complete(self.root, instance, artifact, spec)

    def test_bound_complete_evidence(self):
        self.assertTrue(self.covered())

    def test_http_pass_without_browser_is_not_complete(self):
        self.assertFalse(browser_cart.coverage_complete({'verdict': 'pass', 'quality': 100,
            'browserCartCoverage': 'not_run_http_only'}))

    def test_missing_screenshot_vetoes_index_pass(self):
        (self.review/'C-016-afterScreenshot').unlink()
        self.assertFalse(self.covered())

    def test_changed_dom_vetoes_index_pass(self):
        (self.review/'C-015-after').write_text('tampered')
        self.assertFalse(self.covered())

    def test_different_target_vetoes_index_pass(self):
        self.assertFalse(self.covered(instance='other'))
        self.assertFalse(self.covered(artifact='other'))
        self.assertFalse(self.covered(spec='other'))

    def test_missing_receipt_vetoes_index_pass(self):
        (self.review/'receipt.json').unlink()
        self.assertFalse(self.covered())

    def test_comparisons_distinguish_browser_execution_conditions(self):
        receipt = util.read_json(self.review/'receipt.json')
        receipt['conditions'] = {'collectorSha256': 'one', 'browserVersion': '149', 'updateTimeoutMs': 10000}
        util.write_json_atomic(self.review/'receipt.json', receipt)
        before = browser_cart.execution_identity(self.root)
        receipt['conditions']['collectorSha256'] = 'two'
        util.write_json_atomic(self.review/'receipt.json', receipt)
        self.assertNotEqual(before, browser_cart.execution_identity(self.root))

    def test_receipt_outside_evidence_root_is_not_coverage(self):
        receipt = util.read_json(self.review/'receipt.json')
        receipt['removals'][0]['before']['path'] = '../evaluation.json'
        util.write_json_atomic(self.review/'receipt.json', receipt)
        self.output['browserCartEvidenceSha256'] = util.sha256_file(self.review/'receipt.json')
        util.write_json_atomic(self.root/'evaluation.json', self.output)
        self.assertFalse(self.covered())

    def failure_fixture(self, http_fail=False):
        baseline = self.root/'http-only'; baseline.mkdir()
        util.write_new_json(baseline/'evaluation.json', {
            'artifactSha256': 'artifact', 'specSha256': 'spec', 'criticalFailed': [],
            'requirements': [{'id': 'R-010', 'judgement': 'fail' if http_fail else 'pass'}]})
        (baseline/'results.jsonl').write_text('bound HTTP test results')
        self.output.update(researchStatus='incomplete', browserCartCoverage='partial', verdict='fail', quality=None,
            requirements=[{'id': 'R-010' if http_fail else 'R-014', 'judgement': 'fail'}],
            baselineEvaluationSha256=util.sha256_file(baseline/'evaluation.json'),
            baselineResultsSha256=util.sha256_file(baseline/'results.jsonl'))
        util.write_json_atomic(self.root/'evaluation.json', self.output)
        self.evaluation_hash = util.sha256_file(self.root/'evaluation.json')

    def failure(self):
        return browser_cart.stored_failure(self.root, 'instance', 'artifact', 'spec', self.evaluation_hash)

    def test_http_failure_survives_missing_browser_evidence(self):
        self.failure_fixture(http_fail=True)
        (self.review/'C-016-afterScreenshot').unlink()
        failure = self.failure()
        self.assertEqual('fail', failure['verdict'])
        self.assertEqual(['R-010'], failure['requirements'])
        self.assertEqual('http-only', failure['source'])

    def test_partial_browser_failure_requires_its_evidence(self):
        self.failure_fixture()
        self.assertEqual('fail', self.failure()['verdict'])
        (self.review/'C-016-afterScreenshot').unlink()
        self.assertIsNone(self.failure())

    def test_modified_evaluation_cannot_invent_partial_failure(self):
        self.failure_fixture()
        self.output['requirements'][0]['id'] = 'R-001'
        util.write_json_atomic(self.root/'evaluation.json', self.output)
        self.assertIsNone(self.failure())

    def test_partial_http_failure_requires_bound_baseline(self):
        self.failure_fixture(http_fail=True)
        (self.root/'http-only/results.jsonl').write_text('changed')
        self.assertIsNone(self.failure())


if __name__ == '__main__': unittest.main()
