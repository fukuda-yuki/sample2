"""Providerless campaign supervisor ownership and failure-boundary checks."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid
import research

from outer.harness import run, util
from research import campaign_launcher as subject, live_pilot


class Child:
    def __init__(self, code=None, pid=4321):
        self.code, self.pid, self.terminated = code, pid, False
    def poll(self): return self.code
    def terminate(self): self.terminated = True; self.code = -15
    def kill(self): self.code = -9
    def wait(self, timeout=None): return self.code


class CampaignLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'; self.repo.mkdir()
        self.batch = self.base / 'campaign'; self.batch.mkdir()
        self.campaign = {'batch': str(self.batch)}
        self.plan = self.base / 'plan.json'; util.write_new_json(self.plan, self.campaign)
        self.epoch = dict(kind=live_pilot.MAIN_KIND, phase_id=uuid.uuid4().hex,
            batch=str(self.base / 'epoch'), cohort='epoch', assignments=[],
            runtime_by_task={'MS1-CONT-A':'music'}, source_pins={},
            resource_monitor={}, resource_probe={}, thresholds={})
        for number in (1, 2):
            self.epoch['assignments'].append(dict(pair=number, cases=[
                dict(task='MS1-CONT-A', condition=arm, pair=number, slot=slot, attempt=6000+number,
                    run_id=run.run_id_for('MS1-CONT-A',arm,6000+number), run_instance_id=uuid.uuid4().hex)
                for slot, arm in enumerate(('explore','preload'), 1)]))
        self.epoch_path = self.base / 'epoch-plan.json'; util.write_new_json(self.epoch_path,self.epoch)
        self.epoch_ref = live_pilot.reference(self.epoch_path)
        for number in (1,2):
            phase = live_pilot.observer_phase(self.epoch, self.epoch_ref, number)
            util.write_new_json(Path(phase['batch'])/'phase.json',phase)
        self.wave = self.batch/'waves/wave-001/spec.json'
        self.spec = {'epoch_plan':self.epoch_ref,'pairs':[1,2],'wall_seconds':300}
        util.write_new_json(self.wave,self.spec)
        self.module = types.ModuleType('research.repaired_campaign')
        self.module.validate = lambda repo, path: self.campaign
        self.module.wave_spec = lambda repo, path, wave: self.spec
        self.module.validate_admission = lambda repo, path, wave: True
        self.module.campaign_stop_pending = lambda campaign: (Path(campaign['batch'])/'_control/dispatch-stop.json').exists()

    def context(self):
        with patch.dict(sys.modules, {'research.repaired_campaign':self.module}), \
             patch.object(research,'repaired_campaign',self.module,create=True), \
             patch.object(live_pilot,'owner_plan',return_value=self.epoch):
            return subject.preflight(self.repo,self.plan,self.wave)

    def retained(self):
        ctx = self.context(); ctx['directory'].mkdir()
        util.write_new_json(ctx['directory']/'intent.json',dict(kind=subject.KIND,
            plan=ctx['plan'],wave=ctx['wave'],epoch_plan=ctx['epoch_plan'],pairs=ctx['pairs'],source_repo=str(self.repo)))
        return ctx

    def rows(self, status='not_allocated'):
        return [dict(run_id=c['run_id'],run_instance_id=c['run_instance_id'],
            root=str(Path(self.epoch['batch'])/('pair-'+str(p['pair']))/c['run_id']),status=status)
            for p in self.epoch['assignments'] for c in p['cases']]

    def test_preflight_rejects_more_than_two_pairs_without_writes(self):
        self.spec['pairs']=[1,2,3]
        before=util.tree_hashes(self.base)
        with self.assertRaises(ValueError): self.context()
        self.assertEqual(before,util.tree_hashes(self.base))

    def test_preflight_requires_exact_durable_admission(self):
        self.module.validate_admission=lambda repo,path,wave:False
        with self.assertRaises(ValueError):self.context()

    def test_competing_launcher_cannot_stop_or_spawn_under_existing_owner_lock(self):
        with patch.dict(sys.modules,{'research.repaired_campaign':self.module}), \
             patch.object(research,'repaired_campaign',self.module,create=True), \
             subject.pair_execution.exclusive(self.batch/'_launcher-owner'), \
             patch.object(subject,'_launch_owned') as launch, \
             patch.object(subject,'latch_stop') as stop, self.assertRaises(OSError):
            subject.launch(self.repo,self.plan,self.wave)
        launch.assert_not_called();stop.assert_not_called()

    def test_supervisor_lock_remains_held_through_closure(self):
        def owned(repo,path,wave):
            with self.assertRaises(OSError):
                with subject.pair_execution.exclusive(self.batch/'_launcher-owner'):pass
            return {'operational_complete':False,'closure_retained':True}
        with patch.dict(sys.modules,{'research.repaired_campaign':self.module}), \
             patch.object(research,'repaired_campaign',self.module,create=True), \
             patch.object(subject,'_launch_owned',side_effect=owned):
            result=subject.launch(self.repo,self.plan,self.wave)
        self.assertTrue(result['closure_retained'])
        with subject.pair_execution.exclusive(self.batch/'_launcher-owner'):pass

    def test_wave_wall_cannot_exceed_campaign_bound(self):
        self.campaign['bounds']={'wave_wall_seconds':120}
        with self.assertRaises(ValueError):self.context()
        del self.spec['wall_seconds']
        self.assertEqual(self.context()['wall_seconds'],120)

    def test_preflight_rejects_outside_wave_scope(self):
        self.wave=self.base/'foreign/spec.json';util.write_new_json(self.wave,self.spec)
        with self.assertRaises(ValueError): self.context()

    def test_preflight_rejects_reserved_pair_and_existing_launcher(self):
        ctx=self.context();ctx['directory'].mkdir()
        with self.assertRaises(FileExistsError):self.context()

    def test_stop_latches_campaign_epoch_and_both_pairs(self):
        ctx=self.retained(); result=subject.latch_stop(ctx,'fixture')
        self.assertEqual(len(result['durable_stop_paths']),6)
        self.assertEqual(result['errors'],[])
        for path in result['durable_stop_paths']:
            self.assertTrue(Path(path).is_file())
        with self.assertRaises(ValueError):self.context()

    def test_foreign_existing_stop_not_overwritten(self):
        ctx=self.retained()
        marker=self.batch/'_control/dispatch-stop.json'
        util.write_new_json(marker,{'plan_sha256':'foreign'})
        result=subject.latch_stop(ctx,'fixture')
        self.assertEqual(util.read_json(marker),{'plan_sha256':'foreign'})
        self.assertEqual(len(result['errors']),1)
        self.assertEqual(len(result['durable_stop_paths']),5)

    def test_cleared_old_stop_preserved_and_new_wave_event_becomes_pending(self):
        root_stop=self.batch/'_control/dispatch-stop.json'
        old_marker=dict(plan_sha256=live_pilot.reference(self.plan)['sha256'],wave_sha256='a'*64,reason='old')
        util.write_new_json(root_stop,old_marker)
        old_event=self.batch/'_control/stop-events/old-wave.json'
        util.write_new_json(old_event,old_marker)
        cleared={str(old_event)}
        self.module.campaign_stop_pending=lambda campaign:any(str(p) not in cleared for p in
            (Path(campaign['batch'])/'_control/stop-events').glob('*.json'))
        ctx=self.retained()  # Cleared original root STOP alone does not block admission.
        result=subject.latch_stop(ctx,'new fault')
        event=self.batch/'_control/stop-events/wave-001.json'
        saved=util.read_json(event)
        self.assertEqual(saved['plan_sha256'],ctx['plan']['sha256'])
        self.assertEqual(saved['wave_sha256'],ctx['wave']['sha256'])
        self.assertEqual(util.read_json(root_stop),old_marker)
        self.assertEqual(util.read_json(old_event),old_marker)
        self.assertFalse(result['errors'])
        with self.assertRaisesRegex(ValueError,'Campaign STOP'):self.context()

    def test_epoch_stop_remains_hard_after_campaign_clearance(self):
        ctx=self.retained();subject.latch_stop(ctx,'fixture')
        self.module.campaign_stop_pending=lambda campaign:False
        with self.assertRaisesRegex(ValueError,'Epoch STOP'):self.context()

    def test_supervisor_uses_recovery_predicate_not_old_root_marker(self):
        ctx=self.retained()
        util.write_new_json(self.batch/'_control/dispatch-stop.json',{'plan_sha256':ctx['plan']['sha256']})
        self.module.campaign_stop_pending=lambda campaign:False
        with patch.object(research,'repaired_campaign',self.module,create=True), \
             patch.object(subject,'_bounded_helper',return_value={'confirmed':True}), \
             patch.object(subject,'close_owned') as stop:
            result=subject.supervise(ctx,Child(0),subject.time.monotonic())
        self.assertTrue(result['operational_complete']);stop.assert_not_called()

    def test_supervisor_stops_when_new_event_becomes_pending(self):
        ctx=self.retained();self.module.campaign_stop_pending=lambda campaign:True
        with patch.object(research,'repaired_campaign',self.module,create=True), \
             patch.object(subject,'close_owned',return_value={'owned_closure_confirmed':False}) as stop:
            result=subject.supervise(ctx,Child(),subject.time.monotonic())
        self.assertFalse(result['operational_complete'])
        self.assertEqual(result['reason'],'campaign_stop');stop.assert_called_once()

    def test_existing_event_with_foreign_wave_hash_is_not_overwritten(self):
        ctx=self.retained();event=self.batch/'_control/stop-events/wave-001.json'
        foreign={'plan_sha256':ctx['plan']['sha256'],'wave_sha256':'b'*64}
        util.write_new_json(event,foreign)
        result=subject.latch_stop(ctx,'fixture')
        self.assertEqual(util.read_json(event),foreign)
        self.assertEqual(len(result['errors']),1)

    def test_internal_stop_rejects_foreign_uuid_before_runtime(self):
        ctx=self.retained();subject.latch_stop(ctx,'fixture')
        with patch.object(subject,'owned_rows',return_value=self.rows('owned_allocated')), \
             patch.object(subject.runtime,'request_stop') as stop, self.assertRaises(ValueError):
            subject.internal('_stop',self.repo,self.plan,self.wave,'f'*32)
        stop.assert_not_called()

    def test_internal_stop_calls_only_bound_root_and_retains_identity(self):
        ctx=self.retained();subject.latch_stop(ctx,'fixture');rows=self.rows('owned_allocated')
        with patch.object(subject,'owned_rows',return_value=rows), \
             patch.object(subject.runtime,'request_stop',return_value={'run_id':rows[0]['run_id'],'stop_confirmed':True}) as stop:
            result=subject.internal('_stop',self.repo,self.plan,self.wave,rows[0]['run_instance_id'])
        stop.assert_called_once_with(rows[0]['root'])
        self.assertEqual(result['run_instance_id'],rows[0]['run_instance_id'])

    def test_changed_spec_cannot_expand_retained_stop_scope(self):
        ctx=self.retained();subject.latch_stop(ctx,'fixture')
        util.write_json_atomic(self.wave,{**self.spec,'pairs':[2]})
        with self.assertRaises(ValueError):subject._retained_context(self.repo,self.plan,self.wave)

    def test_unknown_identity_is_never_stopped_or_counted_closed(self):
        ctx=self.retained()
        with patch.object(subject,'owned_rows',return_value=self.rows('unknown_foreign_or_unreadable')), \
             patch.object(subject,'_spawn_helper') as spawn, \
             patch.object(subject,'_bounded_helper',return_value={'confirmed':True}):
            result=subject.close_owned(ctx,Child(0),'fixture')
        spawn.assert_not_called()
        self.assertFalse(result['owned_closure_confirmed'])
        self.assertTrue(all(r['unknown'] for r in result['owned_runs']))

    def test_missing_child_handle_is_not_proof_of_no_child(self):
        ctx=self.retained()
        with patch.object(subject,'owned_rows',return_value=self.rows()), \
             patch.object(subject,'_bounded_helper',return_value={'confirmed':True}):
            result=subject.close_owned(ctx,None,'spawn_outcome_unknown')
        self.assertFalse(result['owned_closure_confirmed'])
        self.assertTrue(result['child']['child_handle_unavailable'])

    def test_helper_launch_ambiguity_is_attempted_once_after_all_stop_markers(self):
        ctx=self.retained(); calls=[]
        def fail(action, context, directory, instance=None):
            self.assertTrue((context['base']/'_control/dispatch-stop.json').exists())
            for number in (1,2):
                phase=live_pilot.observer_phase(self.epoch,self.epoch_ref,number)
                self.assertTrue((Path(phase['batch'])/'_control'/phase['phase_id']/'dispatch-stop.json').exists())
            calls.append(instance);raise OSError('fixture ambiguous spawn')
        with patch.object(subject,'owned_rows',return_value=self.rows('owned_allocated')), \
             patch.object(subject,'_spawn_helper',side_effect=fail), \
             patch.object(subject,'_bounded_helper',return_value={'confirmed':True}):
            result=subject.close_owned(ctx,Child(0),'fixture')
        self.assertEqual(len(calls),4);self.assertEqual(len(set(calls)),4)
        self.assertFalse(result['owned_closure_confirmed'])

    def test_failed_worker_result_cannot_be_verified(self):
        ctx=self.retained()
        util.write_new_json(self.wave.parent/'result.json',dict(plan_sha256=ctx['plan']['sha256'],
            wave_sha256=ctx['wave']['sha256'],operational_complete=False,watcher_shutdown_verified=True))
        with patch.object(subject.live_pilot_launcher,'verify_pair_terminal') as verify, self.assertRaises(ValueError):
            subject.internal('_verify',self.repo,self.plan,self.wave)
        verify.assert_not_called()

    def test_success_requires_independent_pair_verification(self):
        ctx=self.retained()
        util.write_new_json(self.wave.parent/'result.json',dict(plan_sha256=ctx['plan']['sha256'],
            wave_sha256=ctx['wave']['sha256'],operational_complete=True,watcher_shutdown_verified=True))
        with patch.object(subject.live_pilot_launcher,'verify_pair_terminal',return_value={'ready':True}) as verify:
            result=subject.internal('_verify',self.repo,self.plan,self.wave)
        self.assertTrue(result['confirmed']);self.assertEqual(verify.call_count,2)

    def test_missing_observer_cannot_close_allocated_runs(self):
        ctx=self.retained()
        with patch.object(subject.live_pilot_launcher,'owned_runs',return_value=self.rows('owned_allocated')):
            result=subject.close_observers(ctx)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['missing_allocated_pair_observers'],[1,2])

    def test_native_failed_worker_closes_without_model_or_docker(self):
        self.repo=Path(subject.__file__).resolve().parents[1]
        ctx=self.retained()
        with (self.base/'failed-child.log').open('xb') as log:
            child=subject.popen([sys.executable,'-B','-c','raise SystemExit(2)'],self.repo,log)
            child.wait(timeout=10)
            result=subject.supervise(ctx,child,subject.time.monotonic())
        self.assertFalse(result['operational_complete'])
        self.assertTrue(result['owned_closure_confirmed'])
        self.assertTrue(result['observer_closure']['confirmed'])
        self.assertEqual(len(result['owned_runs']),4)
        self.assertTrue(all(row['status']=='not_allocated' for row in result['owned_runs']))

    def test_native_child_environment_does_not_receive_provider_key(self):
        with patch.dict(os.environ,{'OPENCODE_GO_API_KEY':'fixture-no-provider'}):
            with (self.base/'native.log').open('xb') as log:
                child=subject.popen([sys.executable,'-B','-c',
                    'import os; assert "OPENCODE_GO_API_KEY" not in os.environ; print("ok")'],self.repo,log)
                self.assertEqual(child.wait(timeout=10),0)

    @unittest.skipUnless(os.name=='nt','Windows native process-handle proof')
    def test_readonly_observer_exit_wait_never_terminates_live_process(self):
        self.assertFalse(subject.observer_exited(os.getpid(),timeout=0))
        with (self.base/'exit-child.log').open('xb') as log:
            child=subject.popen([sys.executable,'-B','-c','import time; time.sleep(.2)'],self.repo,log)
            try:
                self.assertTrue(subject.observer_exited(child.pid,timeout=3))
                self.assertEqual(child.wait(timeout=3),0)
            finally:
                if child.poll() is None:subject._terminate(child)

    @unittest.skipUnless(os.name=='nt','Windows native owner-handle proof')
    def test_campaign_watch_detects_native_owner_exit_before_admission(self):
        from research.repaired_campaign import CampaignWatch
        with (self.base/'owner.log').open('xb') as log:
            owner=subject.popen([sys.executable,'-B','-c','import time; time.sleep(.3)'],self.repo,log)
            watch=None
            try:
                watch=CampaignWatch(self.epoch,'a'*64,{}, {},run.now(),owner.pid,self.wave.parent)
                owner.wait(timeout=5)
                with self.assertRaisesRegex(RuntimeError,'supervisor ownership lost'):watch.check()
            finally:
                if watch is not None:watch.finish()
                if owner.poll() is None:subject._terminate(owner)


if __name__=='__main__':unittest.main()
