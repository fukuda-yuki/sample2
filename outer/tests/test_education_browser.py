"""School browser evidence cannot manufacture coverage or erase known failure."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
try:
    from . import support
except ImportError:
    import support
from harness import browser_review, education_browser as school, util


class SchoolEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.review = self.root/'browser-school'; self.review.mkdir()
        self.receipt = {'schemaVersion': 1, 'actor': 'agent', 'runInstanceId': 'instance',
                        'artifactSha256': 'artifact', 'specSha256': 'spec', 'action': 'create-edit-save'}
        for name in school.REFERENCES:
            (self.review/name).write_text('synthetic boundary evidence', encoding='utf-8')
            self.receipt[name] = {'path': name, 'sha256': util.sha256_file(self.review/name)}
        self.output = {'evaluationVersion': school.VERSION, 'researchStatus': 'complete',
                       'browserReviewCoverage': school.OBSERVED, 'reviewRunInstanceId': 'instance',
                       'artifactSha256': 'artifact', 'specSha256': 'spec'}
        self.write()

    def write(self):
        util.write_json_atomic(self.review/'receipt.json', self.receipt)
        self.output['browserReviewEvidenceSha256'] = util.sha256_file(self.review/'receipt.json')
        util.write_json_atomic(self.root/'evaluation.json', self.output)

    def covered(self):
        return browser_review.stored_coverage_complete(self.root, 'instance', 'artifact', 'spec')

    def test_family_dispatch_requires_full_bound_browser_and_database_evidence(self):
        self.assertTrue(self.covered())
        self.assertTrue(browser_review.required(school.VERSION))
        self.assertFalse(browser_review.coverage_complete({'evaluationVersion': school.VERSION,
                         'verdict': 'pass', 'researchStatus': 'incomplete'}))
        (self.review/'database').write_text('tampered SQL observation', encoding='utf-8')
        self.assertFalse(self.covered())

    def test_other_target_or_escaped_reference_cannot_be_adopted(self):
        self.assertFalse(school.stored_coverage_complete(self.root, 'other', 'artifact', 'spec'))
        self.receipt['after']['path'] = '../evaluation.json'; self.write()
        self.assertFalse(self.covered())

    def failure_fixture(self, known_http=False):
        baseline = self.root/'http-only'; baseline.mkdir()
        util.write_new_json(baseline/'evaluation.json', {'artifactSha256': 'artifact', 'specSha256': 'spec',
            'criticalFailed': ['EDU-R-005'] if known_http else [],
            'requirements': [{'id': 'EDU-R-005', 'judgement': 'fail' if known_http else 'pass'}]})
        (baseline/'results.jsonl').write_text('bound baseline', encoding='utf-8')
        self.output.update(researchStatus='incomplete',
            requirements=[{'id': 'EDU-R-012', 'judgement': 'fail'}], criticalFailed=[],
            baselineEvaluationSha256=util.sha256_file(baseline/'evaluation.json'),
            baselineResultsSha256=util.sha256_file(baseline/'results.jsonl'))
        self.write()

    def failure(self):
        return browser_review.stored_failure(self.root, 'instance', 'artifact', 'spec',
                                            util.sha256_file(self.root/'evaluation.json'))

    def test_unsupported_or_missing_save_evidence_cannot_invent_browser_failure(self):
        self.failure_fixture(); self.assertEqual('composed', self.failure()['source'])
        self.receipt['action'] = 'not-run-unsupported'; self.write()
        self.assertIsNone(self.failure())
        self.receipt['action'] = 'create-edit-save'; self.write(); (self.review/'after').unlink()
        self.assertIsNone(self.failure())

    def test_known_critical_http_failure_survives_observer_fault_but_requires_original_baseline(self):
        self.failure_fixture(known_http=True); (self.review/'after').unlink()
        self.assertEqual({'verdict': 'fail_critical', 'requirements': ['EDU-R-005'], 'source': 'http-only'}, self.failure())
        (self.root/'http-only/results.jsonl').write_text('changed', encoding='utf-8')
        self.assertIsNone(self.failure())

    def test_sql_observation_is_read_only_and_compares_original_rows(self):
        path = self.root/'school.sqlite'; connection = sqlite3.connect(path)
        tables = {'Students': ('ID', 'LastName'), 'Departments': ('DepartmentID', 'Budget'),
                  'Courses': ('CourseID', 'Credits'), 'Enrollments': ('EnrollmentID', 'Grade')}
        oracle = {'tables': {}}
        connection.execute('CREATE TABLE Students(ID INTEGER, LastName TEXT, FirstMidName TEXT, EnrollmentDate TEXT)')
        connection.execute("INSERT INTO Students VALUES(1,'Old','Ada','2020-01-02')")
        connection.execute("INSERT INTO Students VALUES(2,'Review','Morgan','2026-02-03')")
        oracle['tables']['Students'] = {'key': 'ID', 'rows': [{'ID': 1, 'LastName': 'Old', 'FirstMidName': 'Ada', 'EnrollmentDate': '2020-01-02'}]}
        for name, (key, value) in tables.items():
            if name == 'Students': continue
            connection.execute('CREATE TABLE '+name+'('+key+' INTEGER, '+value+' TEXT)')
            connection.execute('INSERT INTO '+name+' VALUES(1,?)', ('10.00' if value == 'Budget' else None,))
            oracle['tables'][name] = {'key': key, 'rows': [{key: 1, value: '10.0' if value == 'Budget' else None}]}
        connection.commit(); connection.close(); before = util.sha256_file(path)
        observed = school._database_observation(path, 2, oracle)
        self.assertTrue(observed['original_rows_preserved']); self.assertTrue(observed['read_only'])
        self.assertEqual('Morgan', observed['student']['FirstMidName']); self.assertEqual(before, util.sha256_file(path))
        connection = sqlite3.connect(path); connection.execute("UPDATE Students SET LastName='Lost' WHERE ID=1")
        connection.commit(); connection.close()
        self.assertFalse(school._database_observation(path, 2, oracle)['original_rows_preserved'])


if __name__ == '__main__': unittest.main()
