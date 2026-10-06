"""School browser evidence cannot manufacture coverage or erase known failure."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
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

    def test_wal_committed_rows_are_read_in_one_snapshot_without_rewriting_database(self):
        path = self.root/'wal.sqlite'; writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL'); writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE Students(ID INTEGER,LastName TEXT,FirstMidName TEXT,EnrollmentDate TEXT)')
        writer.execute("INSERT INTO Students VALUES(1,'Old','Ada','2020-01-02 00:00:00.000')")
        writer.execute("INSERT INTO Students VALUES(2,'Review','Morgan','2026-02-03')")
        writer.commit()
        oracle = {'tables': {'Students': {'key':'ID','rows':[{'ID':1,'LastName':'Old','FirstMidName':'Ada','EnrollmentDate':'2020-01-02'}]}}}
        for table in ('Departments','Courses','Enrollments'): oracle['tables'][table]={'key':'ID','rows':[]}
        before = {p.name:util.sha256_file(p) for p in (path,Path(str(path)+'-wal'))}
        observed = school._database_observation(path,2,oracle,version='education-1.1.0')
        self.assertTrue(observed['original_rows_preserved']); self.assertEqual('Morgan',observed['student']['FirstMidName'])
        self.assertEqual(before,{p.name:util.sha256_file(p) for p in (path,Path(str(path)+'-wal'))})
        real_connect = sqlite3.connect
        class InterleavedReader:
            def __init__(self,*args,**kwargs): self.connection=real_connect(*args,**kwargs)
            def __enter__(self): self.connection.__enter__(); return self
            def __exit__(self,*args): return self.connection.__exit__(*args)
            @property
            def row_factory(self): return self.connection.row_factory
            @row_factory.setter
            def row_factory(self,value): self.connection.row_factory=value
            def execute(self,sql,*args):
                if sql.startswith('SELECT *'):
                    writer.execute("UPDATE Students SET LastName='Changed between reads' WHERE ID=1"); writer.commit()
                return self.connection.execute(sql,*args)
            def close(self): self.connection.close()
        with patch.object(school.sqlite3,'connect',InterleavedReader):
            snapshot = school._database_observation(path,2,oracle,version='education-1.1.0')
        self.assertTrue(snapshot['original_rows_preserved'])
        self.assertEqual('Changed between reads',writer.execute('SELECT LastName FROM Students WHERE ID=1').fetchone()[0])

    def test_duplicate_id_cannot_hide_changed_original_row(self):
        path=self.root/'duplicates.sqlite'; connection=sqlite3.connect(path)
        connection.execute('CREATE TABLE Students(ID INTEGER,LastName TEXT,FirstMidName TEXT,EnrollmentDate TEXT)')
        connection.executemany('INSERT INTO Students VALUES(?,?,?,?)',[
            (1,'Old','Ada','2020-01-02'),(1,'Lost','Ada','2020-01-02'),(2,'Review','Morgan','2026-02-03')])
        connection.commit(); connection.close()
        oracle={'tables':{'Students':{'key':'ID','rows':[{'ID':1,'LastName':'Old'}]}}}
        for table in ('Departments','Courses','Enrollments'): oracle['tables'][table]={'key':'ID','rows':[]}
        observed=school._database_observation(path,2,oracle,version='education-1.1.0')
        self.assertFalse(observed['original_rows_preserved'])
        self.assertEqual(2,observed['differences'][0]['matchedRows'])

    def test_sqlite_identifier_case_does_not_change_student_evidence_field_names(self):
        path=self.root/'lowercase.sqlite'; connection=sqlite3.connect(path)
        connection.execute('CREATE TABLE students(id INTEGER,lastname TEXT,firstmidname TEXT,enrollmentdate TEXT)')
        connection.execute("INSERT INTO students VALUES(2,'Review','Morgan','2026-02-03')")
        connection.commit(); connection.close()
        oracle={'tables':{t:{'key':'ID','rows':[]} for t in ('Students','Departments','Courses','Enrollments')}}
        observed=school._database_observation(path,2,oracle,version='education-1.1.0')
        self.assertEqual({'ID':2,'LastName':'Review','FirstMidName':'Morgan','EnrollmentDate':'2026-02-03'},observed['student'])


if __name__ == '__main__': unittest.main()
