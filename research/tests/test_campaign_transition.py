"""Synthetic successor evidence only; no Docker, models or real campaign writes."""
from contextlib import ExitStack
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import campaign_transition as transition
from research import campaign_recovery
from research.validation_scope import validation_scope


class CampaignTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.old_repo, self.repo = self.base/'old-source', self.base/'new-source'
        for repo in (self.old_repo, self.repo):
            (repo/'research').mkdir(parents=True)
            (repo/'controller.py').write_bytes(b'old controller' if repo == self.old_repo else b'new controller')
        (self.repo/transition.PIN).write_bytes(Path(transition.__file__).read_bytes())
        from research import validation_scope
        (self.repo/transition.SCOPE_PIN).write_bytes(Path(validation_scope.__file__).read_bytes())
        from research import proof_session
        (self.repo/'research/proof_session.py').write_bytes(Path(proof_session.__file__).read_bytes())
        self.old_root, self.new_root = self.base/'p26', self.base/'p27'
        self.old_root.mkdir()
        self.old_path, self.path = self.base/'old-plan.json', self.base/'new-plan.json'
        self.old = dict(schema_version=1,kind=transition.campaign.KIND,campaign_id='a'*32,
            source_commit='1'*40,source_pins={'controller.py':util.sha256_file(self.old_repo/'controller.py')},
            batch=str(self.old_root),slots=[{'pair':n,'task':'fixed'} for n in range(1,101)],
            settings={'provider':'opencode-go','model_id':'deepseek-v4.1-flash','use_balance':False,'paid_fallback':False},
            bounds=copy.deepcopy(transition.campaign.BOUNDS),policy=transition.campaign.policy(),
            base_plan={'path':'fixed-baseline','sha256':'b'*64},
            storage_policy='new_campaign_ntfs_compression_originals_retained',
            readiness_source_repo=str(self.base/'readiness-source'),protected_roots=[],
            authorization_reference='original authorization',created_at='2026-10-06T13:00:00+00:00')
        util.write_new_json(self.old_path,self.old)
        self.old_ref=transition._ref(self.old_path)
        epoch_path=self.old_root/'epochs/001/plan.json'
        epoch=dict(assignments=[dict(pair=n,cases=[dict(run_instance_id=f'{2*n-1:032x}'),
                    dict(run_instance_id=f'{2*n:032x}')]) for n in range(1,101)])
        util.write_new_json(epoch_path,epoch)
        self.epoch_ref=transition._ref(epoch_path)
        self.wave_path=self.old_root/'waves/wave-1/spec.json'
        self.wave=dict(campaign=self.old_ref,epoch_plan=self.epoch_ref,pairs=[1,2])
        util.write_new_json(self.wave_path,self.wave)
        self.wave_ref=transition._ref(self.wave_path)
        util.write_new_json(self.wave_path.parent/'closure.json',dict(closed=True,wave=self.wave_ref))
        util.write_new_json(self.wave_path.parent/'_launcher/result.json',dict(owned_closure_confirmed=True))
        for n in (1,2):
            transition.pair_execution.append(self.old_root/'attempts.jsonl',dict(kind='pair_attempt_reserved',
                slot=n,pair_attempt=1,wave=self.wave_ref,epoch_plan=self.epoch_ref))
            transition.pair_execution.append(self.old_root/'attempts.jsonl',dict(kind='pair_accepted',slot=n,
                pair_attempt=1,wave=self.wave_ref,epoch_plan=self.epoch_ref,quality_complete=True))
        self.events=transition.pair_execution.events(self.old_root/'attempts.jsonl')
        self.old_ledger_bytes=(self.old_root/'attempts.jsonl').read_bytes()
        self.stop=self.old_root/'_control/stop-events/wave-1.json'
        util.write_new_json(self.stop,dict(reason='RuntimeError',plan_sha256=self.old_ref['sha256']))
        self.stop_bytes=self.stop.read_bytes()
        self.start=dict(plan_sha256=self.old_ref['sha256'],started_at='2026-10-06T13:55:43.123456+00:00')
        util.write_new_json(self.old_root/'execution-start.json',self.start)
        self.usage=dict(requests=27,observed_tokens=801,accumulated_run_seconds=1234.5,
            dispatched_runs=4,usage_journal_errors=[],missing_duration_runs=[])
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(transition.campaign,'EXTRA_PINS',('controller.py',)))
        self.validation=self.stack.enter_context(patch.object(transition.campaign,'validate',
            side_effect=lambda repo,path:util.read_json(path)))
        self.wave_check=self.stack.enter_context(patch.object(transition.campaign,'verify_closure',
            side_effect=self.verify_closure))
        self.stack.enter_context(patch.object(transition.campaign,'wave_spec',side_effect=lambda repo,path,wave:util.read_json(wave)))
        self.stack.enter_context(patch.object(transition.campaign,'observed_usage',return_value=self.usage))
        self.stack.enter_context(patch.object(campaign_recovery,'_context',return_value={'synthetic':True}))
        self.owned_closure=self.stack.enter_context(patch.object(campaign_recovery,'_owned_closure',
            return_value=transition._ref(self.wave_path.parent/'_launcher/result.json')))
        self.owned=self.stack.enter_context(patch.object(transition,'_owned_idle',return_value=[{'confirmed':True}]))
        self.compressed=self.stack.enter_context(patch.object(transition,'_compress'))
        from research import next_phase
        self.git=self.stack.enter_context(patch.object(next_phase,'git',
            side_effect=lambda repo,*args:'2'*40 if args==('rev-parse','HEAD') else ''))
        self.committed=self.stack.enter_context(patch.object(transition.repaired_runtime,'_committed_files'))
        self.docker=self.stack.enter_context(patch.object(transition.runtime,'docker',
            side_effect=AssertionError('Actual Docker is forbidden in synthetic tests')))

    def verify_closure(self,repo,path,wave,closure):
        value=util.read_json(closure)
        if value.get('closed') is not True or value.get('wave')!=transition._ref(wave):
            raise ValueError('Unclosed wave')
        return True

    def create(self):
        return transition.create_successor(repo=self.repo,path=self.path,batch=self.new_root,
            predecessor_plan=self.old_path,predecessor_repo=self.old_repo,authorization='continue same 100')

    def test_same_slots_history_usage_and_elapsed_clock_are_preserved(self):
        p=self.create()
        self.assertEqual({k:p[k] for k in transition.PRESERVED},{k:self.old[k] for k in transition.PRESERVED})
        self.assertEqual(transition.history_events(p),self.events)
        h=transition._read(p['predecessor']['history'])
        self.assertEqual(Path(h['ledger_snapshot']['path']).read_bytes(),self.old_ledger_bytes)
        self.assertEqual(h['observed_usage'],self.usage)
        self.assertEqual(h['accepted_slots'],[1,2])
        self.assertEqual(transition.reserved_instance_ids(p),{f'{n:032x}' for n in range(1,201)})
        clock=util.read_json(self.new_root/'execution-start.json')
        self.assertEqual(clock['started_at'],self.start['started_at'])
        self.assertEqual(clock['plan_sha256'],transition._ref(self.path)['sha256'])
        self.assertEqual(clock['inherited_from'],transition._ref(self.old_root/'execution-start.json'))
        self.assertEqual(util.read_json(self.new_root/'allocation.json')['inherited_pair_attempts'],2)
        self.assertIn(transition.SCOPE_PIN,p['source_pins'])
        self.compressed.assert_called_once_with(self.new_root)
        self.assertTrue(transition.validate_predecessor(self.repo,p))
        self.docker.assert_not_called()

    def test_new_permanent_stop_fences_old_without_changing_existing_evidence(self):
        p=self.create()
        marker=transition._read(p['predecessor']['retirement'])
        self.assertEqual(marker['reason'],'explicit_stop')
        self.assertTrue(marker['permanent'])
        self.assertEqual(marker['history'],p['predecessor']['history'])
        self.assertEqual(self.stop.read_bytes(),self.stop_bytes)
        self.assertEqual((self.old_root/'attempts.jsonl').read_bytes(),self.old_ledger_bytes)
        self.assertEqual(util.read_json(self.old_path),self.old)
        self.assertTrue(transition.campaign.campaign_stop_pending(self.old))

    def test_active_old_launcher_prevents_allocation(self):
        with transition.pair_execution.exclusive(self.old_root/'_launcher-owner'):
            with self.assertRaises((OSError,RuntimeError,ValueError)):
                self.create()
        self.assertFalse(self.new_root.exists())
        self.assertFalse(self.path.exists())

    def test_ownership_verified_while_all_three_old_locks_are_held(self):
        def verify(*args):
            for name in ('_launcher-owner','_control','_allocation'):
                with self.assertRaises((OSError,RuntimeError,ValueError)):
                    with transition.pair_execution.exclusive(self.old_root/name):
                        pass
            return []
        self.owned.side_effect=verify
        self.create()

    def test_missing_wave_closure_blocks_before_any_new_root(self):
        (self.wave_path.parent/'closure.json').unlink()
        with self.assertRaises((OSError,ValueError)):
            self.create()
        self.assertFalse(self.new_root.exists())

    def test_unknown_resources_or_usage_cannot_retire(self):
        self.owned.side_effect=ValueError('Unknown owned resources')
        with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.new_root.exists())
        self.owned.side_effect=None
        self.usage['missing_duration_runs']=['unknown-instance']
        with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.new_root.exists())

    def test_dirty_source_is_rejected_without_old_stop_write(self):
        self.git.side_effect=lambda *args:'dirty'
        with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.new_root.exists())
        self.assertEqual(len(transition.campaign.stop_markers(self.old)),1)

    def test_plan_identity_budget_or_clock_changes_are_refused(self):
        p=self.create()
        for field,change in [('campaign_id','f'*32),('bounds',{}),('policy',{}),('slots',[]),('settings',{})]:
            with self.subTest(field=field):
                altered=copy.deepcopy(p);altered[field]=change
                with self.assertRaises(ValueError):transition.validate_predecessor(self.repo,altered)
        clock=util.read_json(self.new_root/'execution-start.json');clock['started_at']='2026-10-07T00:00:00+00:00'
        util.write_json_atomic(self.new_root/'execution-start.json',clock)
        with self.assertRaisesRegex(ValueError,'clock'):
            transition.validate_predecessor(self.repo,p)

    def test_old_ledger_append_or_snapshot_change_invalidates_history(self):
        p=self.create()
        transition.pair_execution.append(self.old_root/'attempts.jsonl',dict(kind='late_mutation'))
        with self.assertRaises(ValueError):transition.history_events(p)

    def test_retirement_removal_or_clearance_is_refused(self):
        p=self.create()
        marker=p['predecessor']['retirement']
        util.write_new_json(self.old_root/'_control/clearances/illegal.json',{'stops':{marker['path']:marker['sha256']}})
        with self.assertRaisesRegex(ValueError,'never receive a clearance'):
            transition.validate_predecessor(self.repo,p)
        Path(marker['path']).unlink()
        with self.assertRaises((OSError,ValueError)):
            transition.validate_predecessor(self.repo,p)

    def test_all_unsent_epoch_identities_are_excluded(self):
        p=self.create()
        ids=transition.reserved_instance_ids(p)
        self.assertIn(f'{199:032x}',ids)
        self.assertIn(f'{200:032x}',ids)
        self.assertEqual(len(ids),200)
        self.assertEqual(transition.reserved_instance_ids({'batch':'old'}),set())
        self.assertEqual(transition.history_events({'batch':'old'}),[])

    def test_failed_write_after_retirement_leaves_old_fenced(self):
        real=util.write_new_json
        def fail(path,value):
            if Path(path)==self.path:raise OSError('Synthetic interrupted write')
            return real(path,value)
        with patch.object(util,'write_new_json',side_effect=fail):
            with self.assertRaises(OSError):self.create()
        markers=[util.read_json(p) for p in transition.campaign.stop_markers(self.old)]
        self.assertTrue(any(p.get('permanent') is True for p in markers))
        self.assertTrue(transition.campaign.campaign_stop_pending(self.old))
        self.assertFalse(self.path.exists())
        self.assertTrue((self.new_root/'history/attempts.jsonl').exists())

    def test_existing_successor_not_overwritten_or_replayed(self):
        p=self.create();before=transition._ref(self.path)
        with self.assertRaises(FileExistsError):self.create()
        self.assertEqual(transition._ref(self.path),before)
        self.assertEqual(len(transition.campaign.stop_markers(self.old)),2)

    def test_reset_allocation_or_authorization_is_rejected(self):
        p=self.create()
        allocation=self.new_root/'allocation.json'
        original=util.read_json(allocation)
        changed=dict(original,inherited_pair_attempts=0)
        util.write_json_atomic(allocation,changed)
        with self.assertRaisesRegex(ValueError,'allocation/authorization'):
            transition.validate_predecessor(self.repo,p)
        util.write_json_atomic(allocation,original)
        authorization=self.new_root/'authorization.json'
        changed=util.read_json(authorization);changed['authorized']=False
        util.write_json_atomic(authorization,changed)
        with self.assertRaisesRegex(ValueError,'allocation/authorization'):
            transition.validate_predecessor(self.repo,p)

    def test_inherited_and_new_local_attempts_share_one_budget_ledger(self):
        p=self.create()
        transition.pair_execution.append(self.new_root/'attempts.jsonl',dict(kind='pair_attempt_reserved',
            slot=3,pair_attempt=1,wave={'new':'wave'},epoch_plan={'new':'epoch'}))
        events=transition.campaign.ledger(p)
        self.assertEqual(events[:len(self.events)],self.events)
        self.assertEqual(sum(e['kind']=='pair_attempt_reserved' for e in events),3)
        self.assertEqual([e['slot'] for e in events if e['kind']=='pair_accepted'],[1,2])

    def test_retired_ownership_checked_once_per_operation_and_again_on_next(self):
        with validation_scope():
            p=self.create()
            self.assertTrue(transition.validate_predecessor(self.repo,p))
            checked=self.owned_closure.call_count
            self.assertTrue(transition.validate_predecessor(self.repo,p))
            self.assertEqual(self.owned_closure.call_count,checked)
            self.assertEqual(self.wave_check.call_count,1)
        self.owned_closure.side_effect=ValueError('Owned closure changed')
        with validation_scope(), self.assertRaisesRegex(ValueError,'Owned closure changed'):
            transition.validate_predecessor(self.repo,p)

    def test_retired_usage_and_permanent_stop_rechecked_each_operation(self):
        p=self.create();self.wave_check.reset_mock()
        with validation_scope():
            self.assertTrue(transition.validate_predecessor(self.repo,p))
        self.usage['requests']+=1
        with validation_scope(), self.assertRaisesRegex(ValueError,'Retained predecessor evidence changed'):
            transition.validate_predecessor(self.repo,p)
        self.usage['requests']-=1
        with validation_scope(), patch.object(transition.campaign,'campaign_stop_pending',return_value=False):
            with self.assertRaisesRegex(ValueError,'not permanently fenced'):
                transition.validate_predecessor(self.repo,p)
        self.stop.write_bytes(b'changed original STOP')
        with validation_scope(), self.assertRaisesRegex(ValueError,'Original STOP bytes changed'):
            transition.validate_predecessor(self.repo,p)

    def test_next_operation_rechecks_deep_file_even_when_closure_ref_is_unchanged(self):
        p=self.create();self.wave_check.reset_mock()
        dependency=self.old_root/'immutable-payload.bin';dependency.write_bytes(b'original')
        def verify(*args):
            self.verify_closure(*args)
            if dependency.read_bytes()!=b'original':raise ValueError('Deep historical bytes changed')
            return True
        self.wave_check.side_effect=verify
        with validation_scope():
            transition.validate_predecessor(self.repo,p)
            transition.validate_predecessor(self.repo,p)
        self.assertEqual(self.wave_check.call_count,1)
        dependency.write_bytes(b'tampered')
        with validation_scope():
            with self.assertRaisesRegex(ValueError,'Deep historical bytes changed'):
                transition.validate_predecessor(self.repo,p)
        self.assertEqual(self.wave_check.call_count,2)

    def test_changed_retired_closure_is_revalidated_on_next_operation(self):
        p=self.create();self.wave_check.reset_mock()
        with validation_scope():
            transition.validate_predecessor(self.repo,p)
        closure=self.wave_path.parent/'closure.json'
        util.write_json_atomic(closure,dict(closed=False,wave=self.wave_ref))
        with validation_scope():
            with self.assertRaisesRegex(ValueError,'Unclosed wave'):
                transition.validate_predecessor(self.repo,p)
        self.assertEqual(self.wave_check.call_count,2)


if __name__=='__main__':unittest.main()



class LegacyPolicyPredecessorTests(CampaignTransitionTests):
    """A historical publication-gated predecessor may hand over to the owned policy."""
    def setUp(self):
        legacy=transition.campaign.legacy_policy()
        with patch.object(transition.campaign,'policy',return_value=legacy):
            super().setUp()

    def test_only_next_wave_rule_moves_to_owned_policy(self):
        p=self.create()
        self.assertEqual(self.old['policy'],transition.campaign.legacy_policy())
        self.assertEqual(p['policy'],transition.campaign.policy())
        self.assertTrue(transition.validate_predecessor(self.repo,p))
        for key,value in [('paid_fallback',True),('balance',True),('low_quality_replacement',True),
                          ('initial_denominator',99),('next_wave_requires','anything_else')]:
            with self.subTest(key=key):
                altered=copy.deepcopy(p);altered['policy']=dict(p['policy'],**{key:value})
                with self.assertRaises(ValueError):transition.validate_predecessor(self.repo,altered)
