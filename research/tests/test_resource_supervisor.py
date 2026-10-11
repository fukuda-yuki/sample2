"""Finite local safety boundary tests; no provider, credential or Docker mutation."""
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from outer.harness import util
from research import resource_supervisor as supervisor


class SupervisorTests(unittest.TestCase):
    def test_probe_timeout_retries_once_within_original_deadline_and_retains_failure(self):
        failed = {'ok': False, 'error': 'TimeoutExpired', 'probe_elapsed_seconds': 4.4}
        good = {'ok': True, 'containers': [], 'probe_elapsed_seconds': .5}
        probe = Mock(side_effect=[failed, good])
        with patch.object(supervisor.time, 'monotonic', side_effect=[100, 104.4, 104.9]):
            result = supervisor.bounded_probe(probe, ['owned-root'])
        self.assertTrue(result['ok'])
        self.assertEqual(probe.call_count, 2)
        self.assertAlmostEqual(probe.call_args_list[1].kwargs['timeout_seconds'], 5.6)
        self.assertEqual(result['retry_evidence'], [failed])
        self.assertAlmostEqual(result['probe_elapsed_seconds'], 4.9)

    def test_probe_repeated_timeout_stays_failed(self):
        failed = {'ok': False, 'error': 'TimeoutExpired'}
        probe = Mock(side_effect=[failed, dict(failed)])
        with patch.object(supervisor.time, 'monotonic', side_effect=[100, 104, 108]):
            result = supervisor.bounded_probe(probe, [])
        self.assertFalse(result['ok'])
        self.assertEqual(result['retry_evidence'], [failed])
        self.assertEqual(probe.call_count, 2)

    def test_probe_identity_fault_and_exhausted_deadline_never_retry(self):
        for error, elapsed in [('container_label_identity_mismatch', 1), ('probe_timeout', 10)]:
            failed = {'ok': False, 'error': error}
            probe = Mock(return_value=failed)
            with patch.object(supervisor.time, 'monotonic', side_effect=[100, 100+elapsed]):
                self.assertEqual(supervisor.bounded_probe(probe, []), failed)
            self.assertEqual(probe.call_count, 1)

    def test_late_retry_success_is_not_healthy(self):
        probe = Mock(side_effect=[{'ok': False, 'error': 'TimeoutExpired'}, {'ok': True}])
        with patch.object(supervisor.time, 'monotonic', side_effect=[100, 104, 110.1]):
            result = supervisor.bounded_probe(probe, [])
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'probe_deadline_exceeded')
        self.assertTrue(result['late_collector_result']['ok'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.batch = self.root / 'batch'
        self.bindings = []
        cases = []
        for i in range(2):
            case = {'run_id': 'fixture-' + str(i), 'run_instance_id': str(i)*32, 'pair':9001, 'slot':i}
            cases.append(case)
            binding = {**case,'phase_sha256':'a'*64,'plan_sha256':'b'*64,
                'cohort':'fixture','runtime':'fixture','input_sha256':'c'*64,'condition_sha256':'d'*64}
            self.bindings.append(binding)
            util.write_new_json(self.batch / case['run_id'] / 'manifest.json',
                {**case,'assignment':case,'prompt_sha256':'c'*64,'condition_sha256':'d'*64})
        self.phase = {'_digest':'a'*64,'assignments':[{'pair':9001,'cases':cases}],
            'two_pair_blocks':[[9001]],'batch':str(self.batch),'original_bundle':{'sha256':'b'*64},
            'cohort':'fixture','runtime':'fixture'}
        self.request = {'phase_sha256':'a'*64,'session':'fixture','generation':1,
            'pairs':[9001],'bindings':self.bindings}

    def bare(self):
        value = object.__new__(supervisor.Supervisor)
        value.directory = self.root / 'supervisor';value.directory.mkdir(exist_ok=True)
        value.session = 'fixture';value.phase = self.phase
        value.bindings = self.bindings;value.generation = 1
        value.fault = {'reason':'synthetic_deadline'}
        value.futures = {};value.confirmed = {};value.next_fence = {}
        from concurrent.futures import ThreadPoolExecutor
        value.pool = ThreadPoolExecutor(2);self.addCleanup(value.pool.shutdown)
        return value

    def test_full_preassigned_scope_and_input_identity_required(self):
        self.assertEqual(supervisor.validate_scope(self.phase,self.request),self.bindings)
        bad = {**self.request,'bindings':[self.bindings[0]]*2}
        with self.assertRaises(ValueError):supervisor.validate_scope(self.phase,bad)
        bad = {**self.request,'pairs':[9002]}
        with self.assertRaises(ValueError):supervisor.validate_scope(self.phase,bad)
        manifest = self.batch/'fixture-0/manifest.json'
        v=util.read_json(manifest);v['run_instance_id']='foreign';util.write_json_atomic(manifest,v)
        with self.assertRaises(ValueError):supervisor.validate_scope(self.phase,self.request)

    def test_environment_never_inherits_provider_credentials(self):
        with patch.dict(supervisor.os.environ,{'OPENCODE_GO_API_KEY':'synthetic-canary','OTHER_SECRET':'synthetic'},clear=False):
            env=supervisor.safe_environment()
        self.assertNotIn('OPENCODE_GO_API_KEY',env);self.assertNotIn('OTHER_SECRET',env)

    def test_single_assignment_observer_requires_complete_explicit_scope(self):
        self.phase['assignments'][0]['cases'] = self.phase['assignments'][0]['cases'][:1]
        self.request['bindings'] = self.bindings[:1]
        with self.assertRaises(ValueError): supervisor.validate_scope(self.phase, self.request)
        self.phase['cases_per_assignment'] = 1
        self.assertEqual(supervisor.validate_scope(self.phase, self.request), self.bindings[:1])
        with self.assertRaises(ValueError):
            supervisor.validate_scope(self.phase, dict(self.request, bindings=self.bindings))

    def runtime(self,binding):
        state={k:binding[k] for k in ('run_id','run_instance_id')}
        state.update(worker='worker-'+binding['run_id'],gateway='gateway-'+binding['run_id'])
        util.write_new_json(self.batch/binding['run_id']/'runtime.json',state)
        return state

    def test_docker_outage_cannot_ack_owned_absence(self):
        value=self.bare();self.runtime(self.bindings[0])
        manifest=self.batch/'fixture-0/manifest.json';v=util.read_json(manifest);v['stop_confirmed']=True;util.write_json_atomic(manifest,v)
        with patch.object(supervisor.runtime,'docker',return_value=CompletedProcess([],1,'','synthetic failure')):
            with self.assertRaises(RuntimeError):value.owned_resolved(['fixture-0'])

    def test_missing_runtime_dispatched_is_unresolved(self):
        self.assertFalse(self.bare().owned_resolved(['fixture-0']))

    def test_missing_runtime_unsent_has_no_started_manifest(self):
        self.assertTrue(self.bare().owned_resolved([]))
        path=self.batch/'fixture-0/manifest.json';v=util.read_json(path);v['started_at']='synthetic';util.write_json_atomic(path,v)
        self.assertFalse(self.bare().owned_resolved([]))

    def test_unresolved_prior_scope_cannot_be_replaced(self):
        value=self.bare();value.fault=None
        util.write_new_json(value.directory/'scope-000002.json',{**self.request,'generation':2})
        value.monitor=Mock()
        with patch.object(value,'owned_resolved',return_value=False):
            with self.assertRaises(ValueError):value.enroll()
        value.monitor.set_wave.assert_not_called()

    def test_missing_gateway_confirmation_does_not_exclude_late_allocation(self):
        value=self.bare()
        value.fence();self.assertEqual(value.futures,{})
        self.runtime(self.bindings[0])
        called=[]
        with patch.object(supervisor.runtime,'fence_owned',side_effect=lambda path:called.append(path.name) or {'confirmed':True,'method':'gateway_stop'}):
            value.fence()
            for future in value.futures.values():future.result(2)
            value.fence();value.next_fence.clear();value.fence()
            for future in value.futures.values():future.result(2)
        self.assertEqual(called,['fixture-0','fixture-0'])

    def test_evidence_write_failure_does_not_skip_all_physical_fences(self):
        value=self.bare()
        for binding in self.bindings:self.runtime(binding)
        called=[]
        with patch.object(supervisor.util,'write_new_json',side_effect=OSError('synthetic')),\
             patch.object(supervisor.runtime,'fence_owned',side_effect=lambda path:called.append(path.name) or {'confirmed':True}):
            value.fence()
            for future in value.futures.values():future.result(2)
            value.fence()
        self.assertEqual(set(called),{'fixture-0','fixture-1'})

    def test_old_generation_snapshot_cannot_be_relabeled_healthy(self):
        value=self.bare();value.fault=None
        value.latest=(0,{'sampled_at':'old','resource_healthy':True,'host_healthy':True},{})
        value.scope={'generation':1};value.status_sequence=0;value.published_token=None
        value.publish()
        record=util.read_json(supervisor.checked(util.read_json(value.directory/'status.json')))
        self.assertFalse(record['snapshot']['resource_healthy'])
        self.assertFalse(record['snapshot']['host_healthy'])

    def test_status_envelope_is_immutable_evidence(self):
        value=self.bare();value.fault=None
        value.latest=(1,{'sampled_at':'a','resource_healthy':True,'host_healthy':True},{})
        value.scope={'generation':1};value.status_sequence=0;value.published_token=None
        value.publish();reference=util.read_json(value.directory/'status.json')
        value.latest=(1,{**value.latest[1],'sampled_at':'b'},{});value.publish()
        self.assertEqual(util.sha256_file(reference['path']),reference['sha256'])

    def test_monitor_lock_held_enrollment_does_not_delay_stale_fencing(self):
        value=self.bare();value.fault=None;value.phase_control=self.root/'control'
        value.bindings=[];value.generation=0;value.scope={'bindings':[],'generation':0}
        value.monitor=Mock(last_tick=time.monotonic()-31,faults=set())
        value.started_tick=time.monotonic()
        lock=threading.Lock();entered=threading.Event();errors=[]
        def set_wave(*_):
            entered.set()
            with lock:pass
        value.monitor.set_wave=set_wave
        util.write_new_json(value.directory/'scope-000001.json',self.request)
        def enroll():
            try:value.enroll()
            except Exception as exc:errors.append(exc)
        with lock,patch.object(value,'fence') as fence:
            thread=threading.Thread(target=enroll);thread.start()
            self.assertTrue(entered.wait(2))
            self.assertTrue(thread.is_alive())
            began=time.monotonic();value.safety_tick()
            self.assertLess(time.monotonic()-began,1)
            self.assertEqual(value.fault['reason'],'resource_sample_stale')
            fence.assert_called_once()
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
