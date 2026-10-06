"""Providerless watchdog regressions. Fake children are not actual model Runs."""
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from outer.harness import run, util
from research import live_pilot, pair_execution, live_pilot_launcher as subject


class Child:
    def __init__(self, code=None, pid=4321):
        self.code, self.pid, self.terminated, self.killed = code, pid, False, False
    def poll(self): return self.code
    def terminate(self): self.terminated = True; self.code = -15
    def kill(self): self.killed = True; self.code = -9
    def wait(self, timeout=None): return self.code


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'; self.repo.mkdir()
        self.batch = self.base / 'batch'; self.batch.mkdir()
        self.plan = dict(kind=live_pilot.KIND, phase_id=uuid.uuid4().hex, source_commit='a'*40,
            batch=str(self.batch), cohort='pilot', source_pins={}, bounds=dict(live_pilot.BOUNDS),
            runtime_by_task={'MS1-CONT-A':'music', 'CU1-ENR-C':'education'},
            resource_monitor={}, resource_probe={}, thresholds={}, assignments=[])
        for number, task in enumerate(('MS1-CONT-A', 'CU1-ENR-C'), 1):
            self.plan['assignments'].append(dict(pair=number, cases=[
                dict(task=task, condition=arm, pair=number, slot=slot, attempt=1,
                     run_id=run.run_id_for(task,arm,1), run_instance_id=uuid.uuid4().hex)
                for slot,arm in enumerate(('explore','preload'),1)]))
        source = self.repo / 'research/live_pilot_launcher.py'; source.parent.mkdir(); source.write_text('launcher fixture')
        self.plan['source_pins']['research/live_pilot_launcher.py'] = util.sha256_file(source)
        self.plan['launch_supervisor'] = live_pilot.reference(source)
        browser = self.base / 'browser.json'; util.write_new_json(browser, {})
        self.plan['browser_pin'] = live_pilot.reference(browser)
        self.path = self.base / 'plan.json'; util.write_new_json(self.path,self.plan)
        self.ref = live_pilot.reference(self.path)
        self.approval = self.base / 'approval.json'
        util.write_new_json(self.approval, dict(plan_sha256=self.ref['sha256'], authorized=True,
            approved_by='user',authorization_reference='finite authorized fixture'))
        util.write_new_json(self.batch/'allocation.json',dict(kind=live_pilot.KIND,plan=self.ref,phase_id=self.plan['phase_id']))
        for pair in self.plan['assignments']:
            batch = self.batch / ('pair-'+str(pair['pair'])); batch.mkdir()
            util.write_new_json(batch/'phase.json',live_pilot.observer_phase(self.plan,self.ref,pair['pair']))
        self.directory = self.batch/'_launcher'

    def preflight(self, pair=None):
        with patch.object(live_pilot,'owner_plan',return_value=self.plan), \
             patch('research.next_phase.git',side_effect=lambda repo,*args:'a'*40 if args[0]=='rev-parse' else ''), \
             patch('research.repaired_runtime._committed_files'), \
             patch('research.catalog_environment.validate'):
            return subject.preflight(self.repo,self.path,self.approval,pair)

    def rows(self, statuses=None):
        return [dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'],
                     root=str(self.batch/('pair-'+str(pair['pair']))/case['run_id']),
                     status=(statuses or {}).get(case['run_id'],'not_allocated'))
                for pair in self.plan['assignments'] for case in pair['cases']]

    def test_preflight_authorization_failure_never_spawns_or_writes(self):
        util.write_json_atomic(self.approval,dict(authorized=False))
        before=util.tree_hashes(self.base)
        with patch.object(subject,'popen') as spawn, self.assertRaises(ValueError): self.preflight()
        spawn.assert_not_called(); self.assertEqual(before,util.tree_hashes(self.base))

    def test_preflight_rejects_launcher_pin_mismatch(self):
        self.plan['source_pins']['research/live_pilot_launcher.py']='0'*64
        with self.assertRaises(ValueError): self.preflight()

    def test_preflight_rejects_resend(self):
        self.directory.mkdir()
        with self.assertRaises(FileExistsError): self.preflight()

    def test_main_preflight_requires_new100_scope_before_spawn(self):
        self.plan['kind']=live_pilot.MAIN_KIND
        before=util.tree_hashes(self.base)
        with patch.object(subject,'popen') as spawn,self.assertRaises(ValueError):self.preflight(1)
        spawn.assert_not_called();self.assertEqual(before,util.tree_hashes(self.base))

    def test_pilot_pair_option_rejected(self):
        with self.assertRaises(ValueError): subject.selected_pairs(self.plan,1)

    def test_native_short_child_sanitized_environment(self):
        with patch.dict(os.environ,{'OPENCODE_GO_API_KEY':'finite-test-sentinel'}):
            with (self.base/'native.log').open('xb') as log:
                process=subject.popen([sys.executable,'-B','-c',
                    'import os; assert "OPENCODE_GO_API_KEY" not in os.environ; print("providerless child ok")'],self.repo,log)
                self.assertEqual(process.wait(timeout=10),0)
        self.assertIn(b'providerless child ok',(self.base/'native.log').read_bytes())

    def test_stop_idempotent_preserves_first_reason_and_all_phase_markers(self):
        self.directory.mkdir()
        subject.latch_stop(self.plan,self.ref,self.directory,'first fault')
        first=util.tree_hashes(self.batch)
        subject.latch_stop(self.plan,self.ref,self.directory,'later fault')
        self.assertEqual(first,util.tree_hashes(self.batch))
        for pair in self.plan['assignments']:
            phase=live_pilot.observer_phase(self.plan,self.ref,pair['pair'])
            self.assertTrue((Path(phase['batch'])/'_control'/phase['phase_id']/'dispatch-stop.json').exists())

    def test_child_death_latches_stop_and_cannot_succeed_without_result(self):
        self.directory.mkdir()
        child=Child(7)
        with patch.object(subject,'owned_runs',return_value=self.rows()):
            result=subject.supervise(self.repo,self.plan,self.ref,self.directory,child,subject.time.monotonic())
        self.assertFalse(result['operational_complete'])
        self.assertEqual(result['reason'],'owned_controller_exit_nonzero')
        self.assertTrue((self.batch/'_control/dispatch-stop.json').exists())

    def test_zero_exit_missing_result_is_uncertain_not_success(self):
        self.directory.mkdir()
        with patch.object(subject,'owned_runs',return_value=self.rows()):
            result=subject.supervise(self.repo,self.plan,self.ref,self.directory,Child(0),subject.time.monotonic())
        self.assertEqual(result['reason'],'owned_controller_result_unconfirmed')
        self.assertFalse(result['operational_complete'])

    def test_wall_timeout_terminates_only_owned_child_after_stop(self):
        self.directory.mkdir(); child=Child()
        ticks=iter(range(10000,100000,1000))
        with patch.object(subject.time,'monotonic',side_effect=lambda:next(ticks)), \
             patch.object(subject,'owned_runs',return_value=self.rows()), patch.object(subject.time,'sleep'):
            result=subject.supervise(self.repo,self.plan,self.ref,self.directory,child,0)
        self.assertEqual(result['reason'],'whole_pilot_wall_threshold')
        self.assertTrue(child.terminated); self.assertFalse(result['operational_complete'])

    def test_foreign_runtime_never_spawned_as_stop_target(self):
        self.directory.mkdir()
        rows=self.rows(); rows[0]['status']='unknown_foreign_or_unreadable'
        with patch.object(subject,'owned_runs',return_value=rows),patch.object(subject,'popen') as spawn:
            result=subject.stop_owned(self.plan,self.ref,self.repo,self.directory,Child(3),'child death')
        spawn.assert_not_called()
        self.assertTrue(result['owned_stops'][0]['unknown'])

    def stop_process(self, command, repo, log):
        self.assertTrue((self.batch/'_control/dispatch-stop.json').exists())
        for pair in self.plan['assignments']:
            phase=live_pilot.observer_phase(self.plan,self.ref,pair['pair'])
            self.assertTrue((Path(phase['batch'])/'_control'/phase['phase_id']/'dispatch-stop.json').exists())
        instance=command[-1]
        row=next(row for row in self.rows() if row['run_instance_id']==instance)
        util.write_new_json(self.directory/'stops'/instance/'result.json',dict(run_id=row['run_id'],
            run_instance_id=instance,stop_confirmed=True,network_cleanup=dict(confirmed=True)))
        return Child(0,pid=100+len(instance))

    def test_late_allocation_after_child_exit_gets_exact_one_stop(self):
        self.directory.mkdir()
        initial=self.rows(); late=copy.deepcopy(initial);late[0]['status']='owned_allocated'
        with patch.object(subject,'owned_runs',side_effect=[initial,late]), \
             patch.object(subject,'popen',side_effect=self.stop_process) as spawn:
            result=subject.stop_owned(self.plan,self.ref,self.repo,self.directory,Child(0),'result unknown')
        self.assertEqual(spawn.call_count,1)
        self.assertTrue(result['owned_stops'][0]['stop_confirmed'])

    def test_registration_write_failure_keeps_spawned_stop_handle_for_finally(self):
        self.directory.mkdir(); rows=self.rows(); rows[0]['status']='owned_allocated'
        process=Child()
        writer=util.write_new_json
        def fail(path,value):
            if Path(path).name=='registration.json':raise OSError('finite write fault')
            return writer(path,value)
        with patch.object(subject,'owned_runs',return_value=rows), patch.object(subject,'popen',return_value=process), \
             patch.object(util,'write_new_json',side_effect=fail), patch.object(subject.time,'monotonic',side_effect=iter(range(0,100000,1000))), patch.object(subject.time,'sleep'):
            result=subject.stop_owned(self.plan,self.ref,self.repo,self.directory,Child(0),'write fault')
        self.assertTrue(process.terminated)
        self.assertTrue(result['owned_stops'][0]['unknown'])
        self.assertTrue(result['errors'])

    def test_stop_receipt_unreadable_does_not_skip_owned_child_termination(self):
        self.directory.mkdir();rows=self.rows();rows[0]['status']='owned_allocated'
        process=Child(0)
        def invalid(command,repo,log):
            target=self.directory/'stops'/command[-1]/'result.json';target.write_text('invalid JSON');return process
        with patch.object(subject,'owned_runs',return_value=rows),patch.object(subject,'popen',side_effect=invalid):
            result=subject.stop_owned(self.plan,self.ref,self.repo,self.directory,Child(0),'fault')
        self.assertTrue(result['owned_stops'][0]['unknown']);self.assertTrue(result['errors'])

    def test_main_selected_scope_excludes_historical_pair(self):
        main=copy.deepcopy(self.plan);main['kind']=live_pilot.MAIN_KIND
        self.assertEqual(subject.selected_pairs(main,2),[main['assignments'][1]])
        with self.assertRaises(ValueError):subject.selected_pairs(main)
        with self.assertRaises(ValueError):subject.selected_pairs(main,True)

    def test_main_remaining_wall_includes_previous_pair_elapsed_time(self):
        main=copy.deepcopy(self.plan);main['kind']=live_pilot.MAIN_KIND;main['bounds']['wall_seconds']=450000
        start=datetime.now(timezone.utc)-timedelta(seconds=449950)
        util.write_new_json(self.batch/'execution-start.json',dict(plan_sha256=self.ref['sha256'],started_at=start.isoformat()))
        remaining=subject.invocation_wall(main,self.ref,2)
        self.assertGreater(remaining,0);self.assertLess(remaining,51)

    def test_main_missing_origin_cannot_restart_later_pair_wall(self):
        main=copy.deepcopy(self.plan);main['kind']=live_pilot.MAIN_KIND
        with self.assertRaises(ValueError):subject.invocation_wall(main,self.ref,2)

    def test_main_future_origin_not_used_to_extend_wall(self):
        main=copy.deepcopy(self.plan);main['kind']=live_pilot.MAIN_KIND
        util.write_new_json(self.batch/'execution-start.json',dict(plan_sha256=self.ref['sha256'],
            started_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
        with self.assertRaises(ValueError):subject.invocation_wall(main,self.ref,2)

    def test_result_false_watcher_ack_cannot_pass(self):
        util.write_new_json(self.batch/'result.json',dict(kind=live_pilot.KIND,plan_sha256=self.ref['sha256'],
            pilot_operational_complete=True,fault=None,watcher_shutdown_verified=False))
        with self.assertRaises(ValueError):subject._check_result(self.plan,self.ref)

    def test_success_requires_zero_exit_and_exact_terminal_proof(self):
        self.directory.mkdir()
        util.write_new_json(self.batch/'result.json',dict(kind=live_pilot.KIND,plan_sha256=self.ref['sha256'],
            pilot_operational_complete=True,fault=None,watcher_shutdown_verified=True))
        def verifier(command,repo,log):
            self.assertIn('_verify',command)
            util.write_new_json(self.directory/'terminal-proof.json',dict(ready=True,pilot_plan=self.ref))
            return Child(0,pid=998)
        with patch.object(subject,'popen',side_effect=verifier),patch.object(subject.time,'sleep'):
            result=subject.supervise(self.repo,self.plan,self.ref,self.directory,Child(0),subject.time.monotonic())
        self.assertTrue(result['operational_complete']);self.assertFalse(result['stop_requested'])
        self.assertEqual(result['verification_child_exit_code'],0)

    def test_terminal_proof_for_foreign_plan_is_not_success(self):
        self.directory.mkdir()
        util.write_new_json(self.batch/'result.json',dict(kind=live_pilot.KIND,plan_sha256=self.ref['sha256'],
            pilot_operational_complete=True,fault=None,watcher_shutdown_verified=True))
        def verifier(command,repo,log):
            util.write_new_json(self.directory/'terminal-proof.json',dict(ready=True,pilot_plan={'foreign':True}))
            return Child(0)
        with patch.object(subject,'popen',side_effect=verifier),patch.object(subject,'owned_runs',return_value=self.rows()),patch.object(subject.time,'sleep'):
            result=subject.supervise(self.repo,self.plan,self.ref,self.directory,Child(0),subject.time.monotonic())
        self.assertFalse(result['operational_complete']);self.assertEqual(result['reason'],'terminal_proof_unconfirmed')

    def test_marker_io_failure_does_not_skip_owned_controller_termination(self):
        self.directory.mkdir();child=Child()
        with patch.object(subject,'latch_stop',side_effect=OSError('finite I/O failure')), \
             patch.object(subject,'owned_runs',return_value=self.rows()),patch.object(subject.time,'sleep'), \
             patch.object(subject.time,'monotonic',side_effect=iter(range(0,100000,1000))):
            result=subject.stop_owned(self.plan,self.ref,self.repo,self.directory,child,'marker failure')
        self.assertTrue(child.terminated)
        self.assertTrue(result['stop']['stop_marker_errors'])

    def test_raw_foreign_uuid_never_counts_as_owned(self):
        case=self.plan['assignments'][0]['cases'][0]
        root=self.batch/'pair-1'/case['run_id'];root.mkdir()
        manifest=dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'],prompt_sha256='1'*64,condition_sha256='2'*64)
        util.write_new_json(root/'manifest.json',manifest)
        util.write_new_json(root/'runtime.json',dict(run_id=case['run_id'],run_instance_id='f'*32))
        dispatch=dict(case,plan_sha256=self.ref['sha256'],input_sha256='1'*64,condition_sha256='2'*64)
        with patch.object(pair_execution,'state',return_value={'dispatch':{case['run_id']:dispatch}}):
            rows=subject.owned_runs(self.plan,self.ref)
        self.assertEqual(rows[0]['status'],'unknown_foreign_or_unreadable')

    def test_main_ownership_scan_reads_only_selected_two_paths(self):
        self.plan['kind']=live_pilot.MAIN_KIND
        with patch.object(pair_execution,'state') as state:
            rows=subject.owned_runs(self.plan,self.ref,2)
        self.assertEqual(len(rows),2);state.assert_not_called()
        self.assertEqual({r['run_instance_id'] for r in rows},{c['run_instance_id'] for c in self.plan['assignments'][1]['cases']})

    def observer_fixture(self, assignment, *, wrong_generation=False):
        phase=self.batch/('pair-'+str(assignment['pair']))/'phase.json'
        directory=self.batch/'_observers'/uuid.uuid4().hex
        identity=dict(session=directory.name,phase_sha256=util.sha256_file(phase),generation=1)
        util.write_new_json(directory/'config.json',dict(session=directory.name,directory=str(directory),phase=live_pilot.reference(phase)))
        phase_value=util.read_json(phase)
        bindings=[dict(c,phase_sha256=identity['phase_sha256'],plan_sha256=self.ref['sha256'],
            cohort=phase_value['cohort'],runtime=phase_value['runtime'],input_sha256='1'*64,condition_sha256='2'*64) for c in assignment['cases']]
        for case in assignment['cases']:
            util.write_new_json(phase.parent/case['run_id']/'manifest.json',dict(run_id=case['run_id'],
                run_instance_id=case['run_instance_id'],assignment=case,prompt_sha256='1'*64,condition_sha256='2'*64))
        util.write_new_json(directory/'scope-000001.json',dict(**identity,bindings=bindings,pairs=[assignment['pair']]))
        util.write_new_json(directory/'shutdown.json',dict(**identity,dispatched=[c['run_id'] for c in assignment['cases']]))
        ack=dict(**identity,owned_resources_resolved=True,monitor_stop_confirmed=True,fault_latched=True)
        if wrong_generation:ack['generation']=2
        util.write_new_json(directory/'shutdown-ack.json',ack)

    def test_bound_observer_ack_preserves_fault_without_killing_descendants(self):
        for assignment in self.plan['assignments']:self.observer_fixture(assignment)
        before=util.tree_hashes(self.batch)
        disposition=subject.observer_disposition(self.plan,self.ref)
        self.assertTrue(disposition['observer_shutdown_ack_confirmed'])
        self.assertFalse(disposition['manual_resolution_required'])
        self.assertTrue(all(r['fault_latched'] for r in disposition['observations']))
        self.assertFalse(disposition['observer_or_grandchild_processes_killed'])
        self.assertEqual(before,util.tree_hashes(self.batch))

    def test_wrong_generation_or_missing_observer_ack_is_unknown_manual_hold(self):
        self.observer_fixture(self.plan['assignments'][0],wrong_generation=True)
        before=util.tree_hashes(self.batch)
        disposition=subject.observer_disposition(self.plan,self.ref)
        self.assertFalse(disposition['observer_shutdown_ack_confirmed'])
        self.assertTrue(disposition['manual_resolution_required'])
        self.assertTrue(disposition['missing_selected_phase_configs'])
        self.assertEqual(before,util.tree_hashes(self.batch))

    def test_cross_pair_scope_uuid_cannot_confirm_pair1_observer_ack(self):
        self.observer_fixture(self.plan['assignments'][0])
        directory=next((self.batch/'_observers').iterdir())
        scope=util.read_json(directory/'scope-000001.json')
        foreign=self.plan['assignments'][1]['cases'][0]
        scope['bindings'][0].update(run_id=foreign['run_id'],run_instance_id=foreign['run_instance_id'])
        util.write_json_atomic(directory/'scope-000001.json',scope)
        disposition=subject.observer_disposition(self.plan,self.ref)
        self.assertFalse(disposition['observer_shutdown_ack_confirmed'])
        self.assertTrue(disposition['manual_resolution_required'])

    def test_main_empty_gateway_journals_cannot_become_operational_proof(self):
        main=copy.deepcopy(self.plan);main['kind']=live_pilot.MAIN_KIND
        batch=self.batch/'pair-1';assignment=main['assignments'][0]
        util.write_new_json(batch/'pair-result.json',dict(kind=main['kind'],plan_sha256=self.ref['sha256'],pair=1,
            pair_operational_complete=True,fault=None,watcher_shutdown_verified=True))
        util.write_new_json(batch/'observer-terminal.json',{})
        util.write_new_json(batch/'owned-terminal-proof.json',dict(plan_sha256=self.ref['sha256'],
            phase_sha256=util.sha256_file(batch/'phase.json'),runs=[]))
        journal=dict(dispatch={},results={},implementations={})
        for case in assignment['cases']:
            root=batch/case['run_id'];(root/'usage/raw').mkdir(parents=True)
            util.write_new_json(root/'snapshot.json',{'finite':True})
            util.write_new_json(root/'usage/normalized.json',dict(usage_complete=True,input_reached=True))
            journal['dispatch'][case['run_id']]=dict(case)
            journal['results'][case['run_id']]={'row':{}}
            journal['implementations'][case['run_id']]={'receipt':dict(stop_confirmed=True,raw={},snapshot_sha256=util.sha256_file(root/'snapshot.json'))}
        with patch.object(pair_execution,'state',return_value=journal),patch.object(pair_execution,'_postprocess_fault',return_value=False), \
             patch('research.acquisition_readiness.validate_observer_terminal'):
            with self.assertRaisesRegex(ValueError,'actual model request/response evidence missing'):
                subject.verify_main_terminal(self.repo,main,self.ref,1)


if __name__=='__main__': unittest.main()
