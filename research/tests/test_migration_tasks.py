"""Independent task arithmetic and preserved-data acceptance controls."""
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from research import migration_tasks as tasks

REPO = Path(__file__).resolve().parents[2]


class MigrationTasksTests(unittest.TestCase):
    def test_shared_public_contract_and_nested_variants(self):
        a = tasks.read_json(REPO / 'outer/profiles/tasks/MS1-CONT-A.json')
        b = tasks.read_json(REPO / 'outer/profiles/tasks/MS1-CONT-B.json')
        request = (tasks.asset_dir(REPO) / 'public-request.txt').read_text(encoding='utf-8')
        self.assertEqual(a['migration_request'], b['migration_request'])
        self.assertEqual(a['migration_request'], request)
        self.assertEqual(a['family_id'], b['family_id'])
        self.assertFalse(a['held_out'])
        self.assertFalse(b['held_out'])
        for amount in ('26.90', '20.40', '7.25', '8.96', '0.90'):
            self.assertNotIn(amount, request)

    def test_manual_values_are_independently_recomputed(self):
        result = tasks.semantic_necessity(REPO)
        self.assertEqual(result['A']['checkout']['total'], '26.90')
        self.assertEqual(result['B']['checkout']['total'], '20.40')
        self.assertTrue(result['A_fixed_answer_passes_A'])
        self.assertFalse(result['A_fixed_answer_passes_B'])
        self.assertEqual(result['family_count'], 1)
        self.assertEqual(result['human_review'], 'not_run')

    def test_existing_history_identifiers_and_relations_cannot_be_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'initial.sqlite'
            tasks.create_initial_database(REPO, 'B', database)
            oracle = {'tables': tasks.snapshot_tables(database)}
            self.assertFalse(tasks.compare_existing(database, oracle))
            self.assertEqual(oracle['tables']['Orders']['rows'][0]['Total'], '25.15')
            self.assertEqual(oracle['tables']['OrderDetails']['rows'][1]['UnitPrice'], '5.25')
            with closing(sqlite3.connect(database)) as connection, connection:
                self.assertFalse(connection.execute('PRAGMA foreign_key_check').fetchall())
                connection.execute('UPDATE Orders SET Total=? WHERE OrderId=7001', ('20.40',))
            problems = tasks.compare_existing(database, oracle)
            self.assertEqual([(p['table'], p['id']) for p in problems], [('Orders', 7001)])

    def test_allowed_extra_schema_and_equivalent_money_are_not_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'initial.sqlite'
            tasks.create_initial_database(REPO, 'A', database)
            oracle = {'tables': tasks.snapshot_tables(database)}
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('ALTER TABLE Orders ADD COLUMN OptionalNote TEXT')
                connection.execute('UPDATE Orders SET OptionalNote=?', ('extra data is permitted',))
                connection.execute('UPDATE Albums SET Price=? WHERE AlbumId=1', ('7.2500',))
            self.assertFalse(tasks.compare_existing(database, oracle))


if __name__ == '__main__':
    unittest.main()
