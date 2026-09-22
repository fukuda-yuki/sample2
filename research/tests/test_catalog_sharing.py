from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
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
            'api_recovery_pending': False,
            'storage': {'basis_verified': True, 'evidence_sha256': 'c'*64,
                'free_bytes': 700, 'checked_at_utc': self.now.isoformat(),
                **{k: 100 for k in ('next_pair_retained_bytes','generation_scratch_bytes',
                    'sqlite_finalize_bytes','public_copy_bytes','archive_bytes','download_bytes','restore_bytes')}},
            'fixed_execution_plan_verified': True, 'experiment_start_authorized': True}

    def test_dollar_evidence_and_reset_horizon_are_not_required(self):
        result = decide(self.record, self.now)
        self.assertTrue(result['may_start_pair'])
        self.assertFalse(result['monetary_gate_applied'])
        # Historical records may retain unverified financial fields. None can
        # override the user's policy or introduce a fresh usage-GET prerequisite.
        self.record.update(
            applicable_limits={'verified_from_account': False, 'usd': None,
                'valid_until_utc': None},
            paid_overage_disabled_verified=False,
            no_other_account_consumers_verified=False,
            pair_reservation={'quota_usd': None, 'basis_verified': False,
                'planning_horizon_seconds': None})
        for checked_at in (None, (self.now - timedelta(days=1)).isoformat(),
                           (self.now + timedelta(days=1)).isoformat()):
            for reset in (None, (self.now + timedelta(seconds=1)).isoformat()):
                with self.subTest(checked_at=checked_at, reset=reset):
                    self.record['account'] = {'checked_at_utc': checked_at,
                        'http_status': None, 'usage': {'rolling': {
                            'percent': 100, 'status': 'ok', 'resetsAt': reset}}}
                    self.assertTrue(decide(self.record, self.now)['may_start_pair'])

    def test_storage_and_execution_authorization_still_required(self):
        for mutate in (
            lambda r: r['storage'].update(basis_verified=False),
            lambda r: r['storage'].update(evidence_sha256=None),
            lambda r: r['storage'].update(public_copy_bytes=None),
            lambda r: r.update(fixed_execution_plan_verified=False),
            lambda r: r.update(experiment_start_authorized=False)):
            value = deepcopy(self.record)
            mutate(value)
            self.assertFalse(decide(value, self.now)['may_start_pair'])

    def test_stale_future_and_missing_disk_readback_rejected(self):
        self.assertFalse(decide(self.record, self.now + timedelta(minutes=6))['may_start_pair'])
        self.assertFalse(decide(self.record, self.now - timedelta(seconds=1))['may_start_pair'])
        self.record['storage']['checked_at_utc'] = None
        self.assertIn('storage_component_unknown', decide(self.record, self.now)['blocking_reasons'])

    def test_staging_download_restore_space_all_counted(self):
        self.record['storage']['free_bytes'] = 699
        result = decide(self.record, self.now)
        self.assertEqual(result['required_additional_local_bytes'], 700)
        self.assertFalse(result['may_start_pair'])

    def test_api_failure_pauses_until_recovery_not_a_predicted_reset(self):
        self.record['api_recovery_pending'] = True
        self.record['account'] = {'usage': {'rolling': {'status': 'ok',
            'resetsAt': (self.now - timedelta(seconds=1)).isoformat()}}}
        result = decide(self.record, self.now)
        self.assertFalse(result['may_start_pair'])
        self.assertEqual(result['blocking_reasons'], ['api_recovery_pending'])
        self.record['api_recovery_pending'] = False
        self.assertTrue(decide(self.record, self.now)['may_start_pair'])

    def test_cli_saved_record_exits_nonzero_when_launch_is_held(self):
        self.record['experiment_start_authorized'] = False
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'record.json', Path(folder)/'decision.json'
            write_new(source, {'record':self.record, 'decision':{'historical':True}})
            result = subprocess.run([sys.executable,'-B','-m','research.catalog_admission',
                '--record',str(source),'--out',str(output)],capture_output=True,text=True,
                cwd=Path(__file__).resolve().parents[2])
            self.assertEqual(result.returncode,2,result.stderr)
            import json
            decision = json.loads(output.read_text(encoding='utf-8'))
            self.assertFalse(decision['may_start_pair'])
            self.assertIn('experiment_start_not_authorized',decision['blocking_reasons'])
            self.assertFalse(decision['monetary_gate_applied'])


if __name__ == '__main__':
    unittest.main()
