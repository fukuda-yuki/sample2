"""Mocked future158 dispatch and immutable race-proof handoff; no live I/O."""
from pathlib import Path
import unittest
from unittest.mock import patch
from outer.harness import util
from research import pair_execution,wave_dispatch,wave_plan,wave_sharing
from research.tests import test_wave_v4 as fixtures


class V5Tests(unittest.TestCase):
    prepare=fixtures.V4Tests.prepare
    implement=fixtures.V4Tests.implement
    verify=fixtures.V4Tests.verify
    postprocess=fixtures.V4Tests.postprocess
    publish=fixtures.V4Tests.publish
    dispatcher=fixtures.V4Tests.dispatcher
    reference=fixtures.V4Tests.reference

    def setUp(self):
        fixtures.V4Tests.setUp(self)
        fixtures.V4Tests.handoff(self)
        d=self.dispatcher()
        with d.session(): d.execute_next(); d.execute_next()
        self.v4path,self.v4digest,self.v4phase,self.v4journal=self.path,self.digest,self.phase,d.journal
        self.marker_bytes={p:p.read_bytes() for p in (d.control/'phase-handoff.json',
            *[d.control/('phase-handoff-v'+str(n)+'.json') for n in (2,3,4)])}
        current=wave_dispatch.state(d.journal,self.phase,self.digest)
        collector=self.repo/'v5-collector'; collector.mkdir()
        def save(name,value):
            path=collector/(name+'.json'); util.write_new_json(path,value); return self.reference(path)
        monitor=collector/'wave_resource_monitor.py'; monitor.write_bytes(Path(self.v4monitor['path']).read_bytes())
        probe=collector/'wave_resource_probe.py'; probe.write_bytes(b'finite bounded prewrite race fixture')
        self.v5monitor,self.v5probe=self.reference(monitor),self.reference(probe)
        patch.object(wave_plan,'V5_PROBE_SHA',self.v5probe['sha256']).start()
        self.fault5=save('fault',{'sample':{'ok':False,'timeout_seconds':10,'transport_diagnostic':
            {'substage':'pipe_open','errno':22,'winerror':231,'bytes_written':0,'body_bytes_returned':0,
             'pipe_open_attempts':2,'pipe_busy_wait_calls':1,'pipe_wait_winerror':None}}})
        owned=[b for b in current['dispatch'].values() if b['pair'] in (20,21)]
        self.acks5=save('acks',{'phase_sha256':self.v4digest,'owned':owned,'evidence_errors':[],
            'receipt':{'http_fence_confirmed':True,'effective_stop_at':'2026-10-04T14:09:03+00:00',
                'gateway_receipts':[{'run_id':b['run_id'],'run_instance_id':b['run_instance_id'],'confirmed':True,
                    'acknowledgement':{'run_id':b['run_id'],'session_id':b['run_instance_id'],'admission_closed':True}} for b in owned],
                'worker_stops':[{'run_id':b['run_id'],'run_instance_id':b['run_instance_id'],'stop_confirmed':True} for b in owned]}})
        self.boundary5=save('boundary',{'kind':'quiescent_post_v4_pipe_busy_race_boundary','at':'2026-10-04T14:22:00+00:00',
            'phase':self.reference(self.v4path),'journal':self.reference(self.v4journal),
            'gates':{str(n):{'path':g['receipt_path'],'sha256':g['receipt_sha256']} for n,g in current['gates'].items()},
            'actual_sent':42,'all_stopped_fixed':True,'all21_gates_complete':True,
            'active_run_containers_at_final_recovery_sample':0,'recovery_controller_exit_code':0})
        fixture=save('native-fixture',{'mocked_fixture_not_actual_native_proof':True})
        runner=save('native-runner',{'mocked_runner':True})
        plan=save('repeat-plan',{'schema':'predeclared-native-race-repetitions-v1','candidate':self.v5probe,'fixture':fixture,
            'fixed_matrix':[{'case':'repeated_race','count':30,'expected_GET':1,'expected_races':2},
                {'case':'perpetual_race','count':10,'expected_GET':0,'expected_attempts':8},
                {'case':'permanent','count':3,'expected_GET':0,'expected_winerror':121}]})
        leaves=[]
        for case,count in (('repeated_race',30),('perpetual_race',10),('permanent',3)):
            for repeat in range(count):
                leaves.append(save(case+'-'+str(repeat),{'case':case,'repeat':repeat,
                    'all_expected_checks_passed':True,'candidate_endpoint_identity_checked':True,
                    'server_stopped':True,'server_errors':[],'owned_clients_remaining':0,'child_exit_code':0,
                    'request_count':1 if case=='repeated_race' else 0,'transport':{'bytes_written':87 if case=='repeated_race' else 0}}))
        self.repeat_leaf=leaves[0]
        self.native5=save('repeat-receipt',{'schema':'repeated-native-race-verification-v1','plan':plan,
            'candidate':self.v5probe,'fixture':fixture,'runner':runner,'per_case_receipts':leaves,
            'executions':43,'repeated_race_successes':30,'attempt_exhaustions':10,'aggregate_timeouts':3,'passed':43,'failures':[]})
        self.finite5=save('finite',{'schema':'prospective-pipe-busy-acquire-loop-finite-v1',
            'old_probe':self.v4probe,'candidate':self.v5probe,'unchanged_monitor':self.v5monitor,'observed_failure':self.fault5,
            'finite_passed':16,'old_cpu_identity_cases_passed':31,'repeated_native_passed':43,
            'repeated_native_counts':{'repeated_race_success':30,'attempt_exhaustion':10,'permanent_busy_timeout':3},
            'repeated_native_race_fixture_verified':True,'repeated_native_receipt':self.native5,
            'all_ast_outside_native_constructor_unchanged':True,'deadline_checks':{'10_seconds':True,
                'shorter_outer_deadline_preserved':True,'above_10_rejected':True,'aggregate_1second_before_open':True,
                'backoff_inside_budget':True,'at_most_8_opens':True}})
        self.review5=save('review',{'kind':'prospective_pipe_busy_v5_independent_acceptance','status':'passed',
            'finite_acceptance':self.finite5,'resource_probe_sha256':self.v5probe['sha256'],
            'historical_cause_resolved':False,'operationally_acceptable':True,'repeated_native_race_fixture_verified':True,
            'input_references':[self.native5]})
        authority=save('parent-hold',{'kind':'parent_explicit_prewrite_race_verification_hold_instruction_v5',
            'authority':'parent','message':'Finite fixture hold only, never actual permission.',
            'formal_remaining_instances':158,'maximum_concurrent_runs':4,'original_bundle_sha256':self.phase['original_bundle']['sha256'],
            'predecessor_phase':self.reference(self.v4path),'observed_resource_fault':self.fault5,
            'previous_revised_condition':self.authority4,'model_request_retry_authorized':False,'not_a_new_human_reply':True,
            'hold_until_preservation_gates_and_repeated_native_race_verification_and_result_sharing':True,
            'formal_acquisition_as_repair_test_prohibited':True,'monitor_deadline_and_threshold_changes_authorized':False})
        self.shared5=save('results-shared',{'kind':'prewrite_race_verification_results_shared_v5',
            'results_shared':True,'not_a_new_human_reply':True,'finite_acceptance':self.finite5,
            'independent_acceptance':self.review5,'post_v4_boundary':self.boundary5,
            'formal_remaining_instances':158,'maximum_concurrent_runs':4})
        self.acceptance_value5={'kind':'resource_probe_prewrite_pipe_busy_v5_acceptance',
            'previous_probe_sha256':self.v4probe['sha256'],'resource_probe_sha256':self.v5probe['sha256'],
            'resource_monitor_sha256':self.v5monitor['sha256'],'operational_policy_sha256':self.phase['operational_policy']['sha256'],
            'source_commit':'v5 fixture source','original_bundle_sha256':self.phase['original_bundle']['sha256'],
            'predecessor_journal_sha256':self.reference(self.v4journal)['sha256'],'prewrite_only':True,
            'postwrite_retry':False,'whole_probe_deadline_seconds':10,'fail_closed_unchanged':True,'historical_cause_resolved':False,
            'remaining_original_instances':158,'maximum_runs':4,'model_called':False,'run_created':False,
            'repeated_native_race_fixture_verified':True,'finite_acceptance':self.finite5,'independent_acceptance':self.review5,
            'observed_resource_fault':self.fault5,'stop_acknowledgements':self.acks5,'post_v4_boundary':self.boundary5,
            'standing_completion_authority':self.standing,'parent_revised_recovery_authority':authority,
            'parent_instruction_verbatim':util.read_json(authority['path'])['message'],'verification_results_shared':self.shared5}
        self.acceptance5=save('acceptance',self.acceptance_value5)
        self.phase=self.build(); self.path=self.repo/'phase-v5.json'; util.write_new_json(self.path,self.phase)
        self.digest=util.sha256_file(self.path); self.approval={**self.approval,'phase_sha256':self.digest}
        self.sent.clear(); self.heavy.clear(); self.peak=0

    def build(self,**changes):
        values={'source_commit':'v5 fixture source','source_pins':self.v4phase['source_pins'],
            'resource_monitor':self.v5monitor,'resource_probe':self.v5probe,'resource_collector_acceptance':self.acceptance5}
        return wave_plan.build_v5(self.v4path,self.v4journal,**{**values,**changes})

    def handoff(self): return wave_dispatch.handoff_v5(self.repo,self.path,self.approval)

    def test_all79_pairs158_ids_max4_and_historical_metadata(self):
        self.assertEqual(self.phase['assignments'],self.original['assignments'][21:])
        self.assertEqual(len({c['run_instance_id'] for p in self.phase['assignments'] for c in p['cases']}),158)
        self.handoff(); d=self.dispatcher()
        with d.session():
            result=d.execute_next(escalate=True); metadata=wave_sharing.Publisher(d).metadata(22)
            self.assertEqual(metadata['configured_wave_run_cap'],4)
            self.assertEqual(metadata['cause_condition_acceptance_sha256'],self.v3phase['resource_collector_acceptance']['sha256'])
            self.assertIn('does not authorize current v5',metadata['soak_binding'])
            while result['status']!='complete': result=d.execute_next(escalate=True)
            self.assertEqual(set(d.current()['gates']),set(range(22,101)))
            self.assertEqual(len(set(self.sent)),158); self.assertEqual(self.peak,4)
            self.assertEqual(d.current()['waves'][-1]['pairs'],[100])

    def test_missing_shared_proof_inner_native_leaf_and_bounds_rejected(self):
        for path in (self.shared5['path'],self.repeat_leaf['path'],self.v4journal,
                     self.phase['predecessor_gates']['21']['path']):
            path=Path(path); old=path.read_bytes(); path.write_bytes(old+b'changed')
            with self.subTest(path=path),self.assertRaises(ValueError): self.build()
            path.write_bytes(old)
        for key in ('repeated_native_race_fixture_verified','postwrite_retry','whole_probe_deadline_seconds'):
            util.write_json_atomic(self.acceptance5['path'],{**self.acceptance_value5,key:'invalid'})
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.build(resource_collector_acceptance=self.reference(self.acceptance5['path']))
        util.write_json_atomic(self.acceptance5['path'],self.acceptance_value5)
        for changes in ({'maximum_pairs':4},{'escalation_allowed':True},{'assignments':self.v4phase['assignments']}):
            with self.assertRaises(ValueError): wave_plan.validate({**self.phase,**changes})

    def test_append_only_v5_fences_all_ancestor_permits_and_active_lease(self):
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.v4digest):
            with self.assertRaises(OSError): self.build()
        self.handoff(); self.handoff()
        for path,raw in self.marker_bytes.items(): self.assertEqual(path.read_bytes(),raw)
        for permit in (None,self.previous_digest,self.v2digest,self.v3digest,self.v4digest):
            with self.assertRaises(ValueError):
                with pair_execution.exclusive(self.batch/'_control',phase_permit=permit): pass
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.digest): pass


if __name__=='__main__': unittest.main()
