"""Meaningful source/data oracle controls independent of reference implementation."""
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil

from research import education_tasks as tasks

ROOT = Path(__file__).resolve().parents[2]


class EducationTaskControls(unittest.TestCase):
    def test_input_adapter_never_returns_private_expectations(self):
        from outer.harness import migration_input
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            repo = fixture / 'repo'
            contract = repo / 'research/tasks' / tasks.FAMILY
            contract.mkdir(parents=True)
            for name in ('variants.json', 'public-request.txt', 'source-pin.json'):
                shutil.copyfile(ROOT / 'research/tasks' / tasks.FAMILY / name, contract / name)
            source = fixture / 'upstream'
            grade = source / 'src/ContosoUniversity/Models/Enrollment.cs'
            grade.parent.mkdir(parents=True)
            grade.write_text('public enum Grade { A, B, C, D, F }\n', encoding='utf-8')
            # Only substitute the external pinned upstream boundary. Exercise
            # real asset preparation and input selection in the isolated repo.
            with patch.object(tasks, 'source_root', return_value=source):
                for name in ('C', 'D'):
                    inputs = migration_input.prepare(repo, {'task_input_adapter': 'migration-v1',
                        'task_id': 'CU1-ENR-' + name, 'start_state': {'asset_variant': name}})
                    self.assertEqual(set(inputs), {'legacy-source', 'existing-business'})
                    prepared = repo / 'artifacts' / tasks.ASSET_NAMESPACE / ('CU1-ENR-' + name)
                    private = prepared / 'evaluation'
                    oracle = tasks.common.read_json(private / 'migration-oracle.json')
                    self.assertTrue(oracle['workflow'])
                    self.assertTrue(oracle['grade_map'])
                    self.assertTrue((private / 'catalog.json').is_file())
                    self.assertTrue((private / 'initial-store.sqlite').is_file())
                    self.assertEqual(inputs, {key: prepared / 'inputs' / key for key in inputs})
                    self.assertFalse(any(p.name == 'migration-oracle.json' for root in inputs.values() for p in root.rglob('*')))
                    self.assertFalse(any(p.name == 'catalog.json' for root in inputs.values() for p in root.rglob('*')))
                    self.assertFalse(any(p.name == 'initial-store.sqlite' for root in inputs.values() for p in root.rglob('*')))

    def test_family_and_grade_semantics_not_independent_variants(self):
        c, d = tasks.definition(ROOT, 'C'), tasks.definition(ROOT, 'D')
        self.assertEqual([c['task_id'], d['task_id']], ['CU1-ENR-C', 'CU1-ENR-D'])
        self.assertNotEqual(c['manual_grade_expectations'], d['manual_grade_expectations'])
        self.assertEqual(c['manual_grade_expectations']['9003'], d['manual_grade_expectations']['9003'])

    def test_raw_schema_conversion_ids_and_null_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'raw.sqlite'
            tasks.database(ROOT, 'C', path, legacy=True)
            raw = tasks.rows(path, legacy=True)
            self.assertEqual(raw['Students']['rows'][0]['ID'], 101)
            self.assertEqual(raw['Students']['rows'][0]['FirstName'], 'Grace')
            self.assertNotIn('FirstMidName', raw['Students']['rows'][0])
            self.assertIsNone(raw['Enrollments']['rows'][2]['Grade'])

    def test_oracle_detects_lost_relationship_and_tolerates_extra_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'target.sqlite'
            tasks.database(ROOT, 'C', path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('ALTER TABLE Students ADD COLUMN Extra TEXT')
            self.assertEqual(tasks.compare_rows(path, tasks.expected_tables(ROOT, 'C')), [])
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('UPDATE Enrollments SET CourseID=2021 WHERE EnrollmentID=9001')
            self.assertEqual(tasks.compare_rows(path, tasks.expected_tables(ROOT, 'C'))[0]['id'], 9001)

    def test_source_parser_rejects_unhandled_explicit_enum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Enrollment.cs'
            path.write_text('public enum Grade { A=2, B }', encoding='utf-8')
            with self.assertRaises(ValueError):
                tasks.parse_grade_enum(path)


if __name__ == '__main__':
    unittest.main()
