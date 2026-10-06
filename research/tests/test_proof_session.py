"""Non-model proof invalidation, ownership and reuse regressions."""
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from research import proof_session as proof


@unittest.skipUnless(os.name == 'nt', 'Windows byte-sharing guards')
class ProofSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root/'evidence.txt'
        self.payload.write_text('original')

    def validate(self):
        if self.payload.read_text() != 'original':
            raise ValueError('changed evidence')
        return {'verified':True}

    def test_baseline_replays_then_session_reuses_across_operations(self):
        validate=Mock(side_effect=self.validate)
        for _ in range(4):proof.use('closed',{'id':1},validate)
        self.assertEqual(validate.call_count,4)
        validate.reset_mock()
        with proof.local_session() as session:
            for _ in range(4):proof.use('closed',{'id':1},validate)
            self.assertEqual(validate.call_count,1)
            self.assertEqual(session.stats,{'full_validations':1,'hits':3})

    def test_same_size_timestamp_preserving_tamper_is_denied(self):
        stamp=self.payload.stat()
        with proof.local_session():
            proof.use('closed',{},self.validate)
            with self.assertRaises(OSError):
                with self.payload.open('r+b') as stream:stream.write(b'tampered')
            self.assertEqual(self.payload.read_text(),'original')
        self.payload.write_text('tampered')
        os.utime(self.payload,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with proof.local_session():
            with self.assertRaisesRegex(ValueError,'changed evidence'):
                proof.use('closed',{},self.validate)

    def test_replacement_and_delete_are_denied_until_session_close(self):
        with proof.local_session():
            proof.use('closed',{},self.validate)
            with self.assertRaises(OSError):self.payload.unlink()
            with self.assertRaises(OSError):self.payload.rename(self.root/'renamed')
        self.payload.rename(self.root/'renamed')

    def test_added_member_invalidates_before_a_hit(self):
        validate=Mock(side_effect=lambda: sorted(x.name for x in self.root.iterdir()))
        with proof.local_session():
            proof.use('tree',{},validate)
            (self.root/'unexpected').write_text('new')
            with self.assertRaises(proof.ProofInvalid):proof.use('tree',{},validate)
            self.assertEqual(validate.call_count,1)

    def test_failure_is_not_cached(self):
        validate=Mock(side_effect=[ValueError('incomplete'),True])
        with proof.local_session():
            with self.assertRaises(ValueError):proof.use('new-wave',{},validate)
            self.assertTrue(proof.use('new-wave',{},validate))
            self.assertEqual(validate.call_count,2)

    def test_false_or_missing_proof_is_not_cached(self):
        with proof.local_session() as session:
            for value in (False,None):
                with self.assertRaises(proof.ProofInvalid):proof.use('negative',{},lambda:value)
            self.assertEqual(session.stats['full_validations'],0)

    def test_absent_cleanup_target_is_guarded(self):
        target=self.root/'restored'
        def validate():
            proof.watch_absence(target)
            if target.exists():raise ValueError('cleanup incomplete')
            return True
        with proof.local_session():
            self.assertTrue(proof.use('cleanup',{},validate))
            target.mkdir()
            with self.assertRaises(proof.ProofInvalid):proof.use('cleanup',{},validate)

    def test_unverified_new_wave_cannot_inherit_other_wave_success(self):
        with proof.local_session():
            self.assertTrue(proof.use('gate',{'wave':1},lambda:True))
            with self.assertRaisesRegex(ValueError,'missing gate'):
                proof.use('gate',{'wave':2},lambda:(_ for _ in ()).throw(ValueError('missing gate')))

    def test_owner_loss_and_expiry_release_guards_and_never_reuse(self):
        for failure in ('owner','expiry'):
            alive=[True]
            with proof.local_session(owner_alive=lambda:alive[0]) as session:
                proof.use('closed',{},self.validate)
                if failure=='owner':alive[0]=False
                else:session.deadline=time.monotonic()-1
                with self.assertRaises(proof.ProofInvalid):proof.use('closed',{},self.validate)
            self.payload.write_text('original')

    def test_restart_rechecks_and_returned_result_cannot_poison_cache(self):
        validate=Mock(side_effect=self.validate)
        with proof.local_session():
            result=proof.use('closed',{},validate);result['verified']=False
            self.assertTrue(proof.use('closed',{},validate)['verified'])
        with proof.local_session():proof.use('closed',{},validate)
        self.assertEqual(validate.call_count,2)

    def test_live_stop_owner_lease_uuid_dispatch_usage_remain_fresh(self):
        state={k:False for k in ('stop','owner_lost','lease_lost','uuid_changed','ambiguous_dispatch','usage_exhausted')}
        validate=Mock(side_effect=self.validate)
        def admit():
            proof.use('closed',{},validate)
            if any(state.values()):raise ValueError('live guard')
            return True
        with proof.local_session():
            for key in state:
                self.assertTrue(admit());state[key]=True
                with self.assertRaisesRegex(ValueError,'live guard'):admit()
                state[key]=False
            self.assertEqual(validate.call_count,1)

    def test_mutating_subprocess_and_filesystem_write_are_rejected(self):
        with proof.local_session():
            with self.assertRaises(proof.ProofInvalid):
                proof.use('bad-write',{},lambda:self.payload.write_text('bad'))
            import subprocess
            with self.assertRaises(proof.ProofInvalid):
                proof.use('bad-command',{},lambda:subprocess.run(['git','push','origin','show']))

    def test_external_read_probe_is_fresh_and_change_invalidates(self):
        import subprocess
        actual=Mock(return_value=subprocess.CompletedProcess(['git','status'],0,b'clean',b''))
        with patch.object(proof,'_ORIGINAL_RUN',actual),proof.local_session():
            def validate():return subprocess.run(['git','status'],capture_output=True).stdout.decode()
            self.assertEqual(proof.use('probe',{},validate),'clean')
            self.assertEqual(proof.use('probe',{},validate),'clean')
            self.assertEqual(actual.call_count,2)
            actual.return_value=subprocess.CompletedProcess(['git','status'],0,b'dirty',b'')
            with self.assertRaises(proof.ProofInvalid):proof.use('probe',{},validate)


if __name__=='__main__':unittest.main()
