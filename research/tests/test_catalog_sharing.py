from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from research.catalog_admission import decide
from research.catalog_allocation_review import write_new, sha256
from research.catalog_share import (inventory, pack, restore, safe_member,
    scan_bytes, scan_file, public_bytes)


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        public = self.root / 'public'
        public.mkdir()
        (public / 'sample.txt').write_text('evidence', encoding='utf-8')
        write_new(public / 'MANIFEST.json', {'files': [{'path': 'sample.txt',
            'sha256': sha256(public / 'sample.txt'), 'bytes': 8}]})
        review = self.root / 'review.json'
        write_new(review, {'publication_approved': True, 'reviewed_inventory': inventory(public)})
        archive = self.root / 'sample.zip'
        pack(public, archive, review)
        return public, archive, archive.with_suffix('.manifest.json')

    def test_fresh_restore_and_tamper_rejection(self):
        public, archive, index = self.fixture()
        restored = self.root / 'restored'
        self.assertTrue(restore(archive, index, restored)['hashes_match'])
        self.assertEqual(inventory(public), inventory(restored))
        with self.assertRaises(FileExistsError):
            restore(archive, index, restored)
        archive.write_bytes(archive.read_bytes() + b'tamper')
        with self.assertRaisesRegex(ValueError, 'size/hash'):
            restore(archive, index, self.root / 'tampered')
        self.assertFalse((self.root / 'tampered').exists())

    def test_review_binds_extra_files_and_changed_bytes(self):
        public, _, _ = self.fixture()
        (public / 'unreviewed.txt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'exact public'):
            pack(public, self.root / 'second.zip', self.root / 'review.json')
        (public / 'sample.txt').write_text('changed!')
        with self.assertRaisesRegex(ValueError, 'differs'):
            pack(public, self.root / 'third.zip', self.root / 'review.json')

    def test_traversal_windows_names_and_ads_rejected(self):
        for name in ('../escape', '/absolute', 'a/../b', 'a\\b', 'C:escape', 'file:stream',
                     'a//b', 'NUL.txt', 'a/COM1', 'a. ', 'a/.'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_member(name)

    def test_scans_sqlite_blob_and_zip_without_logging_values(self):
        secret = b'synthetic-credential-for-security-test'
        db_path = self.root / 'sample.db'
        with sqlite3.connect(db_path) as db:
            db.execute('CREATE TABLE records(value BLOB)')
            db.execute('INSERT INTO records VALUES (?)', (secret,))
        db.close()
        findings = scan_file(db_path, secret)
        self.assertIn('sqlite_value:existing_provider_credential', findings)
        archive = self.root / 'trace.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('trace', secret)
        findings = scan_file(archive, secret)
        self.assertIn('zip_member:existing_provider_credential', findings)
        self.assertNotIn(secret.decode(), str(findings))

    def test_trace_redaction_preserves_original(self):
        archive = self.root / 'trace.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('trace', str(Path.home()) + '/test')
            z.writestr('picture.png', b'unchanged binary')
        before = sha256(archive)
        redacted = self.root / 'redacted.zip'
        redacted.write_bytes(public_bytes(archive))
        self.assertEqual(before, sha256(archive))
        self.assertFalse(scan_file(redacted))
        with zipfile.ZipFile(redacted) as z:
            self.assertEqual(z.read('picture.png'), b'unchanged binary')
            self.assertIn(b'<LOCAL_HOME>', z.read('trace'))

    def test_duplicate_members_refused_before_writes(self):
        archive = self.root / 'duplicate.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('A.txt', b'a')
            z.writestr('a.txt', b'b')
        index = self.root / 'index.json'
        write_new(index, {'sha256': sha256(archive), 'bytes': archive.stat().st_size,
                         'file_inventory': {'A.txt': {}, 'a.txt': {}}})
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            restore(archive, index, self.root / 'out')
        self.assertFalse((self.root / 'out').exists())


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
        self.record = {
            'account': {'checked_at_utc': self.now.isoformat(), 'http_status': 200,
                'usage': {w: {'status': 'ok', 'percent': 0,
                    'resetsAt': (self.now + timedelta(hours=5)).isoformat()}
                    for w in ('rolling','weekly','monthly')}},
            'applicable_limits': {'verified_from_account': True, 'evidence_sha256': 'a'*64,
                'usd': dict(rolling=3, weekly=7.5, monthly=15),
                'valid_until_utc': (self.now + timedelta(days=1)).isoformat()},
            'paid_overage_disabled_verified': True, 'no_other_account_consumers_verified': True,
            'pair_reservation': {'quota_usd': '2.9', 'basis_verified': True, 'runs': 2,
                'evidence_sha256': 'b'*64, 'planning_horizon_seconds': 3600},
            'storage': {'basis_verified': True, 'evidence_sha256': 'c'*64,
                'free_bytes': 700, 'checked_at_utc': self.now.isoformat(),
                **{k: 100 for k in ('next_pair_retained_bytes','generation_scratch_bytes',
                    'sqlite_finalize_bytes','public_copy_bytes','archive_bytes','download_bytes','restore_bytes')}},
            'fixed_execution_plan_verified': True, 'experiment_start_authorized': True}

    def test_capacity_requires_both_runs_and_floored_usage_margin(self):
        result = decide(self.record, self.now)
        self.assertTrue(result['may_start_pair'])
        self.assertEqual(result['windows']['rolling']['remaining_usd_lower_bound'], '2.97')
        self.record['pair_reservation']['quota_usd'] = '2.98'
        self.assertIn('rolling_insufficient_or_unknown', decide(self.record, self.now)['blocking_reasons'])

    def test_unknown_or_unverified_reservations_do_not_admit(self):
        for mutate in (
            lambda r: r['applicable_limits'].update(verified_from_account=False),
            lambda r: r['pair_reservation'].update(quota_usd=None),
            lambda r: r['pair_reservation'].update(basis_verified=False),
            lambda r: r['pair_reservation'].update(runs=1),
            lambda r: r['storage'].update(basis_verified=False),
            lambda r: r.update(paid_overage_disabled_verified=False),
            lambda r: r.update(experiment_start_authorized=False)):
            value = deepcopy(self.record)
            mutate(value)
            self.assertFalse(decide(value, self.now)['may_start_pair'])

    def test_stale_future_and_reset_crossing_rejected(self):
        self.assertFalse(decide(self.record, self.now + timedelta(minutes=6))['may_start_pair'])
        self.assertFalse(decide(self.record, self.now - timedelta(seconds=1))['may_start_pair'])
        self.record['account']['usage']['rolling']['resetsAt'] = (self.now + timedelta(minutes=20)).isoformat()
        self.assertIn('rolling_reset_before_pair_end', decide(self.record, self.now)['blocking_reasons'])

    def test_staging_download_restore_space_all_counted(self):
        self.record['storage']['free_bytes'] = 699
        result = decide(self.record, self.now)
        self.assertEqual(result['required_additional_local_bytes'], 700)
        self.assertFalse(result['may_start_pair'])

    def test_unknown_account_terms_and_timestamps_fail_closed(self):
        for section, key in (('account','checked_at_utc'), ('applicable_limits','valid_until_utc'),
                             ('storage','checked_at_utc')):
            value = deepcopy(self.record)
            value[section][key] = None
            self.assertFalse(decide(value,self.now)['may_start_pair'])
        self.record['account']['usage']['rolling']['resetsAt'] = None
        self.assertFalse(decide(self.record,self.now)['may_start_pair'])


if __name__ == '__main__':
    unittest.main()
