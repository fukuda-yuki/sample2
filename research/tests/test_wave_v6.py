"""Model-free mocked dispatcher tests; native acceptance remains separate."""
from pathlib import Path
from copy import deepcopy
import unittest
from unittest.mock import patch
from outer.harness import util
from research import pair_execution, wave_dispatch, wave_plan, wave_sharing
from research.tests import test_wave_v5 as fixtures


class V6Tests(fixtures.V5Tests):
    def setUp(self):
        fixtures.V5Tests.setUp(self)
        fixtures.V5Tests.handoff(self)
        d=self.dispatcher()
        with d.session():
            for _ in range(14): d.execute_next()
        self.v5path,self.v5digest,self.v5phase,self.v5journal=self.path,self.digest,self.phase,d.journal
        current=wave_dispatch.state(d.journal,self.phase,self.digest)
        self.marker_bytes={p:p.read_bytes() for p in (d.control/'phase-handoff.json',
            *[d.control/('phase-handoff-v'+str(n)+'.json') for n in (2,3,4,5)])}
        collector=self.repo/'v6-collector'; collector.mkdir()
        def save(name,value):
            p=collector/(name+'.json'); util.write_new_json(p,value); return self.reference(p)
        monitor=collector/'wave_resource_monitor.py'; monitor.write_bytes(Path(self.v5monitor['path']).read_bytes())
        probe=collector/'wave_resource_probe.py'; probe.write_bytes(b'mocked paced acquire probe')
        self.v6monitor,self.v6probe=self.reference(monitor),self.reference(probe)
        patch.object(wave_plan,'V6_PROBE_SHA',self.v6probe['sha256']).start()
        fault=save('fault',{'sample':{'ok':False,'timeout_seconds':10,'transport_diagnostic':None,'diagnostic':{'transport':
            {'substage':'pipe_open','winerror':231,'errno':22,'bytes_written':0,'body_bytes_returned':0,
             'pipe_open_attempts':8,'pipe_busy_wait_calls':7,'pipe_acquire_exhaustion':'attempt_limit',
             'pipe_acquire_elapsed_seconds':.065}}}})
        originals=self.original['assignments'][:49]
        rows=[]
        for p in originals:
            for c in p['cases']:
                rows.append({'pair':p['pair'],'run_id':c['run_id'],'run_instance_id':c['run_instance_id'],
                    'end_reason':'operator_stop' if p['pair'] in (48,49) and not(p['pair']==48 and c['condition']=='explore') else 'completed',
                    'actual_send_observed':True,'stop_confirmed':True,'submission_fixed':True,
                    'manifest_reference':self.reference(self.batch/c['run_id']/'manifest.json')})
        owned=[b for b in current['dispatch'].values() if any(r['run_id']==b['run_id'] and r['end_reason']=='operator_stop' for r in rows)]
        acks=save('acks',{'phase_sha256':self.v5digest,'owned':owned,'evidence_errors':[],
            'receipt':{'http_fence_confirmed':True,'effective_stop_at':'2026-10-04T22:43:03+00:00',
                'gateway_receipts':[{'run_id':b['run_id'],'run_instance_id':b['run_instance_id'],'confirmed':True,
                    'acknowledgement':{'run_id':b['run_id'],'session_id':b['run_instance_id'],'admission_closed':True}} for b in owned],
                'worker_stops':[{'run_id':b['run_id'],'run_instance_id':b['run_instance_id'],'stop_confirmed':True} for b in owned]}})
        gates=[]
        for n in range(1,50):
            if n in current['gates']:
                g=current['gates'][n]; gates.append({'path':g['receipt_path'],'sha256':g['receipt_sha256']})
            else: gates.append(save('historical-gate-'+str(n),{'mocked_historical_gate':n}))
        boundary=save('boundary',{'kind':'post_v5_attempt_limit_stop_preserved_boundary',
            'phase_reference':self.reference(self.v5path),'closed_current_journal_reference':self.reference(self.v5journal),
            'fault_reference':fault,'actual_fence_reference':acks,
            'counts':{'full_gated_pairs':49,'actually_sent':98,'stopped_fixed_postprocessed':98,'unknown_or_unfixed_sent_runs':0,'undispatched':102},
            'controllers':{'finish_only_66858_exit':0,'new_wave_dispatched':False},
            'ledger':{'requests_started':98,'requests_ended':98},'all_98_saved_run_facts':rows,'gate_references':gates,
            **{k:save(k,{'mocked':True}) for k in ('stop_reference','fault_summary_reference','busy_observations_reference')}})
        finite=save('finite',{'kind':'paced_acquire_finite_safety_v6','passed':16,'candidate_sha256':self.v6probe['sha256'],
            'outer_10_seconds_unchanged':True,'postwrite_reopen_forbidden':True,'events_bounded':21,'model_called':False,
            'cases':[{'passed':True} for _ in range(16)],'legacy_fixture_reference':save('legacy',{'mocked':True})})
        fixture=save('fixture',{'mocked':True}); runner=save('runner',{'mocked':True})
        matrix=[('immediate','new',3,True),('busy_available','new',3,True),('fast_perpetual','old',3,False),
            ('fast_perpetual','new',5,False),('window_250ms','old',3,False),('window_250ms','new',5,True),
            ('window_600ms','old',3,False),('window_600ms','new',5,True),('permanent','new',3,False),('absent','new',2,False)]
        plan=save('plan',{'kind':'predeclared_native_paced_acquire_v6','candidate':self.v6probe,'fixture':fixture,
            'previous_probe':self.v5probe,'finite_script':runner,'acquire_budget_seconds':1,'attempt_cap':8,
            'outer_deadline_seconds':10,'total_executions':35,
            'matrix':[{'case':c,'variant':v,'count':n,'expected_success':ok,'expected_GET':int(ok)} for c,v,n,ok in matrix]})
        leaves=[]
        for c,v,n,ok in matrix:
            for i in range(n):
                leaves.append(save(c+'-'+v+'-'+str(i),{'case':c,'variant':v,'repetition':i,'ok':ok,
                    'request_count':int(ok),'all_expected_checks_passed':True,'candidate_endpoint_identity_checked':True,
                    'server_stopped':True,'server_errors':[],'owned_clients_remaining':0,'child_exit_code':0,
                    'transport':{'pipe_open_attempts':1,'bytes_written':87 if ok else 0,'body_bytes_returned':18 if ok else 0,
                        'pipe_acquire_events':[{'operation':'open','begin_seconds':0}]}}))
        self.v6leaf=leaves[0]
        native=save('native',{'kind':'actual_native_paced_acquire_acceptance_v6','planned':35,'executed':35,'passed':35,
            'failures':[],'candidate':self.v6probe,'plan':plan,'fixture':fixture,'runner':runner,
            'native_returns_not_injected':True,'model_called':False,'Docker_called':False,
            'historical_per_call_timing_reconstructed':False,'per_case_receipts':leaves})
        review=save('review',{'kind':'independent_v6_paced_acquire_acceptance','status':'passed_with_scope_limits',
            'candidate':self.v6probe,'plan':plan,'parent_native_receipt':native,'outside_constructor_ast_identical':True,
            'old_probe_and_monitor_hash_unchanged':True,'parent_native_leaf_hashes_and_timelines_verified':35,
            'finite_cases_independently_reexecuted':16,'trace_allowlist_and_max21_verified':True,
            'source_inputs_unchanged':True,'independent_native_cases':[{'mocked':True}]*4,'input_references':[finite,native]})
        authority=save('authority',{'kind':'parent_explicit_bounded_acquisition_pacing_recovery_instruction_v6',
            'authority':'parent','message':'Mocked limited recovery instruction, never live authorization.',
            'original_bundle_sha256':self.phase['original_bundle']['sha256'],'predecessor_phase':self.reference(self.v5path),
            'preserved_boundary':boundary,'remaining_original_instances':102,'maximum_concurrent_runs':4,
            'received_after_hold_boundary':True,'not_a_new_human_reply':True,'model_request_retry_authorized':False,
            'formal_acquisition_as_repair_test_prohibited':True,'threshold_or_deadline_changes_authorized':False,
            'new_cost_or_permission_changes_authorized':False})
        shared=save('shared',{'kind':'paced_acquire_v6_verification_results_shared','results_shared':True,
            'finite_acceptance':finite,'native_acceptance':native,'independent_acceptance':review,'preserved_boundary':boundary,
            'remaining_original_instances':102,'maximum_runs':4})
        self.v6value={'kind':'resource_probe_paced_acquire_v6_acceptance','previous_probe_sha256':self.v5probe['sha256'],
            'resource_probe_sha256':self.v6probe['sha256'],'resource_monitor_sha256':self.v6monitor['sha256'],
            'operational_policy_sha256':self.phase['operational_policy']['sha256'],'source_commit':'v6 fixture source',
            'original_bundle_sha256':self.phase['original_bundle']['sha256'],'predecessor_journal_sha256':self.reference(self.v5journal)['sha256'],
            'prewrite_only':True,'postwrite_retry':False,'whole_probe_deadline_seconds':10,'acquire_deadline_seconds':1,
            'open_attempt_cap':8,'fail_closed_unchanged':True,'historical_cause_resolved':False,
            'remaining_original_instances':102,'maximum_runs':4,'model_called':False,'run_created':False,
            'finite_acceptance':finite,'native_acceptance':native,'independent_acceptance':review,
            'observed_resource_fault':fault,'stop_acknowledgements':acks,'preserved_boundary':boundary,
            'standing_completion_authority':self.standing,'parent_revised_recovery_authority':authority,
            'parent_instruction_verbatim':util.read_json(authority['path'])['message'],'verification_results_shared':shared}
        self.v6acceptance=save('acceptance',self.v6value)
        self.phase=self.build(); self.path=self.repo/'phase-v6.json';util.write_new_json(self.path,self.phase)
        self.digest=util.sha256_file(self.path);self.approval={**self.approval,'phase_sha256':self.digest}
        self.sent.clear(); self.heavy.clear(); self.peak=0

    def build(self,**changes):
        if not hasattr(self,'v6acceptance'): return fixtures.V5Tests.build(self,**changes)
        values={'source_commit':'v6 fixture source','source_pins':self.v5phase['source_pins'],
            'resource_monitor':self.v6monitor,'resource_probe':self.v6probe,'resource_collector_acceptance':self.v6acceptance}
        return wave_plan.build_v6(self.v5path,self.v5journal,**{**values,**changes})

    def handoff(self):
        return wave_dispatch.handoff_v6(self.repo,self.path,self.approval)

    # Override inherited tests: their158-slot assertions belong to V5, run separately.
    def test_all79_pairs158_ids_max4_and_historical_metadata(self):
        self.assertEqual(self.phase['assignments'],self.original['assignments'][49:])
        self.assertEqual(len({c['run_instance_id'] for p in self.phase['assignments'] for c in p['cases']}),102)
        self.handoff();d=self.dispatcher()
        with d.session():
            result=d.execute_next(escalate=True);meta=wave_sharing.Publisher(d).metadata(50)
            self.assertEqual(meta['configured_wave_run_cap'],4)
            self.assertEqual(meta['cause_condition_acceptance_sha256'],self.v3phase['resource_collector_acceptance']['sha256'])
            self.assertIn('does not authorize current v6',meta['soak_binding'])
            while result['status']!='complete':result=d.execute_next(escalate=True)
            self.assertEqual(set(d.current()['gates']),set(range(50,101)))
            self.assertEqual(len(set(self.sent)),102);self.assertEqual(self.peak,4)
            self.assertEqual(d.current()['waves'][-1]['pairs'],[100])

    def test_missing_shared_proof_inner_native_leaf_and_bounds_rejected(self):
        for key in ('verification_results_shared','preserved_boundary','independent_acceptance'):
            p=Path(self.v6value[key]['path']);raw=p.read_bytes();p.write_bytes(raw+b'changed')
            with self.subTest(key=key),self.assertRaises(ValueError):self.build()
            p.write_bytes(raw)
        p=Path(self.v6leaf['path']);raw=p.read_bytes();p.write_bytes(raw+b'changed')
        with self.assertRaises(ValueError):self.build()
        p.write_bytes(raw)
        for key in ('postwrite_retry','open_attempt_cap','acquire_deadline_seconds','remaining_original_instances'):
            util.write_json_atomic(self.v6acceptance['path'],{**self.v6value,key:'invalid'})
            with self.subTest(key=key),self.assertRaises(ValueError):self.build(resource_collector_acceptance=self.reference(self.v6acceptance['path']))
        util.write_json_atomic(self.v6acceptance['path'],self.v6value)
        for change in ({'maximum_pairs':4},{'escalation_allowed':True},{'assignments':self.v5phase['assignments']}):
            with self.assertRaises(ValueError):wave_plan.validate({**self.phase,**change})
        boundary_path=self.v6value['preserved_boundary']['path']
        read_json=util.read_json
        for wrong in ('boolean_zero_count','missing_request_counts'):
            def altered(path):
                value=read_json(path)
                if Path(path)==Path(boundary_path):
                    value=deepcopy(value)
                    if wrong=='boolean_zero_count':value['counts']['unknown_or_unfixed_sent_runs']=False
                    else:value['ledger']={}
                return value
            with self.subTest(wrong=wrong),patch.object(util,'read_json',side_effect=altered),self.assertRaises(ValueError):
                self.build()

    def test_append_only_v5_fences_all_ancestor_permits_and_active_lease(self):
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.v5digest):
            with self.assertRaises(OSError):self.build()
        self.handoff();self.handoff()
        for p,raw in self.marker_bytes.items():self.assertEqual(p.read_bytes(),raw)
        for permit in (None,self.previous_digest,self.v2digest,self.v3digest,self.v4digest,self.v5digest):
            with self.assertRaises(ValueError):
                with pair_execution.exclusive(self.batch/'_control',phase_permit=permit):pass
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.digest):pass


if __name__=='__main__':unittest.main()
