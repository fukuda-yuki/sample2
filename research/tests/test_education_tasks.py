"""Meaningful source/data oracle controls independent of reference implementation."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3

from research import education_tasks as tasks

ROOT = Path(__file__).resolve().parents[2]


class EducationTaskControls(unittest.TestCase):
    def test_input_adapter_never_returns_private_expectations(self):
        from outer.harness import migration_input
        for name in ('C', 'D'):
            inputs = migration_input.prepare(ROOT, {'task_input_adapter': 'migration-v1',
                'task_id': 'CU1-ENR-' + name, 'start_state': {'asset_variant': name}})
            self.assertEqual(set(inputs), {'legacy-source', 'existing-business'})
            self.assertFalse(any(p.name == 'migration-oracle.json' for root in inputs.values() for p in root.rglob('*')))

    def test_family_and_grade_semantics_not_independent_variants(self):
        c, d = tasks.definition(ROOT, 'C'), tasks.definition(ROOT, 'D')
        self.assertEqual([c['task_id'], d['task_id']], ['CU1-ENR-C', 'CU1-ENR-D'])
        self.assertNotEqual(c['manual_grade_expectations'], d['manual_grade_expectations'])
        self.assertEqual(c['manual_grade_expectations']['9003'], d['manual_grade_expectations']['9003'])

    def test_raw_schema_conversion_ids_and_null_grade(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            path = Path(directory) / 'raw.sqlite'
            tasks.database(ROOT, 'C', path, legacy=True)
            raw = tasks.rows(path, legacy=True)
            self.assertEqual(raw['Students']['rows'][0]['ID'], 101)
            self.assertEqual(raw['Students']['rows'][0]['FirstName'], 'Grace')
            self.assertNotIn('FirstMidName', raw['Students']['rows'][0])
            self.assertIsNone(raw['Enrollments']['rows'][2]['Grade'])

    def test_oracle_detects_lost_relationship_and_tolerates_extra_schema(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            path = Path(directory) / 'target.sqlite'
            tasks.database(ROOT, 'C', path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('ALTER TABLE Students ADD COLUMN Extra TEXT')
            self.assertEqual(tasks.compare_rows(path, tasks.expected_tables(ROOT, 'C')), [])
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('UPDATE Enrollments SET CourseID=2021 WHERE EnrollmentID=9001')
            self.assertEqual(tasks.compare_rows(path, tasks.expected_tables(ROOT, 'C'))[0]['id'], 9001)

    def test_source_parser_rejects_unhandled_explicit_enum(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            path = Path(directory) / 'Enrollment.cs'
            path.write_text('public enum Grade { A=2, B }', encoding='utf-8')
            with self.assertRaises(ValueError):
                tasks.parse_grade_enum(path)


if __name__ == '__main__':
    unittest.main()
