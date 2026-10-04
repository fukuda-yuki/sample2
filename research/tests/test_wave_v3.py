"""Future-only v3 fixtures; no real Docker, model or formal-state operations."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from outer.harness import util
from research import pair_execution, wave_plan, wave_dispatch, wave_sharing
from research.tests import test_wave_v2 as fixtures


class V3Tests(unittest.TestCase):
    prepare = fixtures.V2Tests.prepare
    implement = fixtures.V2Tests.implement
    verify = fixtures.V2Tests.verify
    postprocess = fixtures.V2Tests.postprocess
    publish = fixtures.V2Tests.publish
    dispatcher = fixtures.V2Tests.dispatcher

    def reference(self, path): return {'path': str(Path(path).resolve()), 'sha256': util.sha256_file(path)}

    def setUp(self):
        fixtures.V2Tests.setUp(self)
        fixtures.V2Tests.handoff(self)
        d = self.dispatcher()
        with d.session(): d.execute_next()
        self.v2path, self.v2digest, self.v2phase, self.v2journal = self.path, self.digest, self.phase, d.journal
        self.marker_bytes = {p: p.read_bytes() for p in (d.control/'phase-handoff.json', d.control/'phase-handoff-v2.json')}
        current = wave_dispatch.state(d.journal, self.phase, self.digest)
        new = self.repo/'v3-collector';new.mkdir()
        monitor = new/'wave_resource_monitor.py';monitor.write_bytes(Path(self.phase['resource_monitor']['path']).read_bytes())
        probe = new/'wave_resource_probe.py';probe.write_bytes(b'reviewed v3 fixture')
        self.addCleanup(patch.stopall)
        patch.object(wave_plan,'MONITOR_SHA',util.sha256_file(monitor)).start()
        patch.object(wave_plan,'V3_PROBE_SHA',util.sha256_file(probe)).start()
        self.monitor, self.probe = self.reference(monitor), self.reference(probe)
        def save(name, value):
            path=new/(name+'.json');util.write_new_json(path,value);return self.reference(path)
        self.finite_leaf=save('retained-finite-source',{'finite_fixture':True})
        self.finite = save('finite',{'frozen_source':self.finite_leaf,'candidate':self.probe,'unchanged_monitor':self.monitor,'all_native_expected_decisions_passed':True})
        self.boundary = save('boundary',{'kind':'quiescent_pre_v3_boundary','at':'2026-10-04T11:50:00+00:00',
            'phase':self.reference(self.v2path),'journal':self.reference(self.v2journal),
            'gates':{str(n):{'path':g['receipt_path'],'sha256':g['receipt_sha256']} for n,g in current['gates'].items()},
            'actual_sent':26,'all_stopped_fixed':True,'active_run_containers_at_final_recovery_sample':0,'recovery_controller_exit_code':0})
        self.hold_boundary = save('hold-boundary',{'kind':'quiescent_post_v2_recurrence_boundary','at':'2026-10-04T10:45:00+00:00',
            'phase':self.reference(self.v2path),'journal':self.reference(self.v2journal),
            'gates':util.read_json(self.boundary['path'])['gates'],'total_actual_sent':26,'remaining_original_unsent':174,
            'all26_stopped_fixed':True,'all13_gates_complete':True,'new_research_dispatch_held':True})
        self.hold_instruction=save('original-hold',{'kind':'original_parent_hold_instruction','message':'Finite fixture hold until cause condition closed.'})
        protocol = save('protocol',{'probe':self.probe,'monitor':self.monitor,'original_bundle':self.phase['original_bundle'],
            'scheduled_samples':180,'cadence_seconds':10,'source':{'commit':'soak base fixture'}})
        observations=[]
        rawdir=new/'raw';rawdir.mkdir();mondir=new/'monitor';mondir.mkdir()
        for sequence in range(1,184):
            label='scheduled' if sequence<=180 else ('controlled-worker-stop','controlled-gateway-stop','controlled-all-stop')[sequence-181]
            rawpath=rawdir/(f'{sequence:06d}-'+label+'.json');sample={'ok':True,'finite_sequence':sequence};util.write_new_json(rawpath,sample)
            monpath=mondir/(f'finite-session-{sequence:06d}.json');util.write_new_json(monpath,{'schema':'prospective-wave-resource-observation-v1',
                'sequence':sequence,'expected_runs':4,'monitor_session':'finite-session','sample':sample,'faults':[]})
            observations.append({'sequence':sequence,'raw':self.reference(rawpath),'monitor':{str(monpath):util.sha256_file(monpath)}})
        self.observations=observations
        transitions=[{'raw':o['raw'],'monitor':o['monitor']} for o in observations[180:]]
        result = save('result',{'status':'passed','completed_scheduled_samples':180,'transition_observations':transitions,
            'cleanup_errors':[],'model_called':False,'research_dispatched':False,'protocol_sha256':protocol['sha256']})
        self.soak = save('soak',{'kind':'actual_nonmodel_soak_bounded_evidence_verification',
            'scheduled_samples':180,'controlled_stop_observations':3,'owned_fixtures_created_started_stopped_removed':8,
            'all_original_references_checked_unchanged':True,'original_research_sent_runs':26,'remaining_original_unsent':174,
            'formal_research_resume_authorized':False,'historical_cause_resolved':False,'model_called':False,
            'source_commit':'soak base fixture','result':result,'protocol':protocol,'observations':observations,
            'attempt':save('attempt',{'no_retry':True}),'ownership':save('ownership',{'errors':[]}),
            'command_ledger':save('commands',{'synthetic_finite_commands':True})})
        self.review = save('review',{'kind':'actual_nonmodel_soak_independent_evidence_review_v3',
            'operational_soak_verified':True,'historical_cause_resolved':False,'formal_174_hold_remains':True,
            'actual_verification':self.soak,'protocol':protocol,'result':result,
            'input_references':[self.reference(new/'raw/000001-scheduled.json'),self.finite_leaf]})
        evidence=save('causal-evidence',{'finite_fixture_mechanism':'No actual historical claim or permission'})
        affirmative=save('mechanism-independent',{'kind':'verified_resource_transport_mechanism_independent_review',
            'status':'passed','historical_cause_resolved':True,'causal_evidence':evidence,
            'predecessor_journal_sha256':self.reference(self.v2journal)['sha256'],'resource_probe_sha256':self.probe['sha256']})
        mechanism = save('mechanism',{'kind':'verified_resource_transport_mechanism_resolution','historical_cause_resolved':True,
            'predecessor_journal_sha256':self.reference(self.v2journal)['sha256'],'resource_probe_sha256':self.probe['sha256'],
            'causal_evidence':evidence,'independent_review':affirmative})
        self.decision_value = {'kind':'prospective_resource_fault_recovery_decision_v3','formal_remaining_dispatch_authorized':True,
            'cause_condition_satisfied':True,'acceptance_mode':'verified_mechanism_resolution','historical_cause_resolved':True,
            'source_commit':'v3 fixture source','original_bundle_sha256':self.phase['original_bundle']['sha256'],
            'post_v2_boundary':self.boundary,'hold_boundary':self.hold_boundary,'revised_hold_instruction':self.hold_instruction,'predecessor_journal_sha256':self.reference(self.v2journal)['sha256'],
            'resource_probe_sha256':self.probe['sha256'],'resource_monitor_sha256':self.monitor['sha256'],
            'operational_policy_sha256':self.phase['operational_policy']['sha256'],'finite_acceptance':self.finite,
            'actual_soak_verification':self.soak,'post_soak_independent_review':self.review,'mechanism_resolution':mechanism}
        self.decision = save('decision',self.decision_value)
        self.phase = self.build()
        self.path = self.repo/'phase-v3.json';util.write_new_json(self.path,self.phase);self.digest=util.sha256_file(self.path)
        self.approval={**self.approval,'phase_sha256':self.digest};self.sent.clear();self.heavy.clear();self.peak=0

    def build(self, **changed):
        values = dict(source_commit='v3 fixture source',source_pins=self.v2phase['source_pins'],resource_monitor=self.monitor,
            resource_probe=self.probe,finite_acceptance=self.finite,actual_soak_verification=self.soak,
            post_soak_independent_review=self.review,post_v2_boundary=self.boundary,hold_boundary=self.hold_boundary,
            revised_hold_instruction=self.hold_instruction,recovery_decision=self.decision)
        return wave_plan.build_v3(self.v2path,self.v2journal,**{**values,**changed})

    def handoff(self): return wave_dispatch.handoff_v3(self.repo,self.path,self.approval)

    def test_original174_ids_mapping_and_all13_historical_gates(self):
        self.assertEqual(self.phase['assignments'],self.original['assignments'][13:])
        self.assertEqual(len({c['run_instance_id'] for p in self.phase['assignments'] for c in p['cases']}),174)
        self.assertEqual(self.phase['responsibility_counts'],[21,22,22,22])
        self.assertEqual(self.phase['shards'],{k:v for k,v in self.v2phase['shards'].items() if int(k)>=14})
        for changed in ({'maximum_pairs':4},{'escalation_allowed':True},{'runtime':'different model runtime'}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):wave_plan.validate({**self.phase,**changed})
        self.assertEqual([r['sha256'] for r in wave_plan.ancestor_references(self.phase)],[self.previous_digest,self.v2digest])

    def test_missing_decision_or_final_soak_is_not_permission(self):
        absent={'path':str(self.repo/'not-received-decision.json'),'sha256':'0'*64}
        for key in ('recovery_decision','actual_soak_verification','post_soak_independent_review'):
            with self.subTest(key=key),self.assertRaises((ValueError,OSError)):self.build(**{key:absent})
        changed={**self.decision_value,'cause_condition_satisfied':False};util.write_json_atomic(self.decision['path'],changed)
        with self.assertRaises(ValueError):self.build(recovery_decision=self.reference(self.decision['path']))

    def test_soak_success_cannot_claim_historical_cause_resolved(self):
        mechanism_path=self.decision_value['mechanism_resolution']['path'];proof=util.read_json(mechanism_path)
        missing={k:v for k,v in proof.items() if k!='independent_review'};util.write_json_atomic(mechanism_path,missing)
        modified={**self.decision_value,'mechanism_resolution':self.reference(mechanism_path)};util.write_json_atomic(self.decision['path'],modified)
        with self.assertRaisesRegex(ValueError,'affirmative independent'):self.build(recovery_decision=self.reference(self.decision['path']))
        util.write_json_atomic(mechanism_path,proof)
        bad={**self.decision_value,'historical_cause_resolved':False}
        review=util.read_json(self.review['path']);review['historical_cause_resolved']=False;util.write_json_atomic(self.review['path'],review)
        self.review=self.reference(self.review['path']);bad['post_soak_independent_review']=self.review
        util.write_json_atomic(self.decision['path'],bad)
        with self.assertRaisesRegex(ValueError,'Historical mechanism'):self.build(recovery_decision=self.reference(self.decision['path']))

    def revised_decision(self,**changed):
        instruction={'kind':'parent_explicit_revised_resource_fault_condition_instruction','authority':'parent',
            'received_after_hold_boundary':True,'hold_boundary':self.hold_boundary,'revised_hold_instruction':self.hold_instruction,'revises_existing_hold':True,'formal_remaining_instances':174,
            'original_bundle_sha256':self.phase['original_bundle']['sha256'],'predecessor_journal_sha256':self.phase['predecessor_journal']['sha256'],
            'received_at':'2026-10-04T11:00:00+00:00','message':'Finite fixture new parent condition, never an actual authorization.',**changed}
        path=self.repo/'new-parent-instruction.json';util.write_json_atomic(path,instruction)
        review=util.read_json(self.review['path']);review['historical_cause_resolved']=False;util.write_json_atomic(self.review['path'],review);self.review=self.reference(self.review['path'])
        decision={**self.decision_value,'historical_cause_resolved':False,'acceptance_mode':'parent_explicit_revised_condition',
            'post_soak_independent_review':self.review,'parent_instruction':self.reference(path),'parent_instruction_verbatim':instruction['message']}
        util.write_json_atomic(self.decision['path'],decision);return self.reference(self.decision['path'])

    def test_explicit_new_parent_condition_preserves_unknown_history(self):
        p=self.build(recovery_decision=self.revised_decision())
        self.assertFalse(util.read_json(p['resource_collector_acceptance']['path'])['historical_cause_resolved'])
        for changed in ({'received_at':'2026-10-04T10:45:00+00:00'},{'kind':'original_standing_instruction'},
                        {'authority':'human'},{'revises_existing_hold':False},{'message':{'inferred':'permission'}}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):self.build(recovery_decision=self.revised_decision(**changed))
        reference=self.revised_decision();value=util.read_json(reference['path']);value['parent_instruction_verbatim']='inferred permission';util.write_json_atomic(reference['path'],value)
        with self.assertRaises(ValueError):self.build(recovery_decision=self.reference(reference['path']))

    def test_forged_ancestor_or_changed_history_rejected(self):
        with self.assertRaises(ValueError):wave_plan.validate({**self.phase,'predecessor_phase':self.phase['original_bundle']})
        raw_v2=self.batch/self.v2phase['assignments'][0]['cases'][0]['run_id']/'usage/raw/fixed'
        for path in (self.previous_journal,self.previous_path,Path(self.phase['predecessor_gates']['13']['path']),raw_v2,raw_v2.parents[2]/'snapshot.json'):
            with self.subTest(path=path):
                raw=path.read_bytes();path.write_bytes(raw+b'changed')
                with self.assertRaises((ValueError,OSError)):wave_plan.validate(self.phase)
                path.write_bytes(raw)
        bad=deepcopy(self.phase);bad['assignments'][0]=self.v2phase['assignments'][0]
        with self.assertRaises(ValueError):wave_plan.validate(bad)

    def test_open_predecessor_or_active_lease_rejects_builder(self):
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.v2digest):
            with self.assertRaises(OSError):self.build()
            with self.assertRaises(OSError):self.handoff()
        raw=self.v2journal.read_bytes();lines=raw.decode().splitlines()
        self.v2journal.write_text('\n'.join(line for line in lines if not ('"kind": "pair_gate"' in line and '"pair": 13' in line))+'\n',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'boundary pairs'):self.build()
        self.v2journal.write_bytes(raw)

    def test_immutable_handoff_chain_fences_all_ancestors(self):
        self.handoff();self.handoff()
        for path,raw in self.marker_bytes.items():self.assertEqual(path.read_bytes(),raw)
        for permit in (None,self.previous_digest,self.v2digest):
            with self.assertRaises(ValueError):
                with pair_execution.exclusive(self.batch/'_control',phase_permit=permit):pass
        with pair_execution.exclusive(self.batch/'_control',phase_permit=self.digest):pass
        middle=self.batch/'_control/phase-handoff-v2.json';raw=middle.read_bytes();middle.unlink()
        with self.assertRaisesRegex(ValueError,'Missing immutable intermediate'):
            with pair_execution.exclusive(self.batch/'_control',phase_permit=self.digest):pass
        middle.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'cannot be overwritten'):
            wave_dispatch.handoff_v3(self.repo,self.path,{**self.approval,'authorization_reference':'different'})

    def test_forged_successor_ancestry_rejected_by_shared_guard(self):
        self.handoff();path=self.batch/'_control/phase-handoff-v3.json';saved=util.read_json(path)
        forged={**saved,'previous_handoff':self.reference(self.batch/'_control/phase-handoff.json')};util.write_json_atomic(path,forged)
        with self.assertRaises(ValueError):
            with pair_execution.exclusive(self.batch/'_control',phase_permit=self.digest):pass

    def test_future_only_wave_and_publication_barrier_no_refence_old_stops(self):
        self.handoff();d=self.dispatcher(publication_ready=lambda number,current:False)
        with d.session():
            self.assertEqual(d.execute_next(escalate=True)['reason'],'publication_review_pending')
            self.assertEqual(len(self.sent),4);self.assertEqual(self.peak,4)
            self.assertEqual(d.current()['waves'][0]['pairs'],[14,15])
            self.assertEqual(d.execute_next(escalate=True)['reason'],'previous_wave_gates_or_explicit_recovery')
            metadata=wave_sharing.Publisher(d).metadata(14)
            self.assertEqual(metadata['ancestor_phase_sha256s'],[self.previous_digest,self.v2digest])
            self.assertEqual(metadata['configured_wave_run_cap'],4)
            self.assertEqual(d.fault('finite_fault')['status'],'held');self.assertEqual(self.fenced[-1],[])

    def test_inner_raw_monitor_and_listed_review_inputs_tamper_rejected(self):
        paths = [Path(self.observations[0]['raw']['path']), Path(next(iter(self.observations[0]['monitor']))),
                 Path(self.finite_leaf['path'])]
        for path in paths:
            with self.subTest(path=path):
                original=path.read_bytes();path.write_bytes(original+b'changed')
                with self.assertRaises((ValueError,OSError)):wave_plan.validate(self.phase)
                path.write_bytes(original)
        # An additional listed review input is not covered by the observation table.
        leaf=self.repo/'independent-input.json';util.write_new_json(leaf,{'input':True})
        review=util.read_json(self.review['path']);review['input_references'].append(self.reference(leaf))
        util.write_json_atomic(self.review['path'],review);self.review=self.reference(self.review['path'])
        decision={**self.decision_value,'post_soak_independent_review':self.review}
        util.write_json_atomic(self.decision['path'],decision);self.decision=self.reference(self.decision['path'])
        candidate=self.build();leaf.write_bytes(b'changed')
        with self.assertRaises(ValueError):wave_plan.validate(candidate)

    def test_swapped_duplicate_missing_or_mislabelled183_observations_rejected(self):
        original=util.read_json(self.soak['path'])
        for mutation in ('swap','duplicate','missing','label','transition'):
            with self.subTest(mutation=mutation):
                value=deepcopy(original)
                if mutation=='swap':value['observations'][0],value['observations'][1]=value['observations'][1],value['observations'][0]
                elif mutation=='duplicate':value['observations'][1]['raw']=value['observations'][0]['raw']
                elif mutation=='missing':value['observations'].pop()
                elif mutation=='label':value['observations'][0]['raw']=value['observations'][180]['raw']
                else:
                    resultpath=value['result']['path'];result=util.read_json(resultpath);saved=Path(resultpath).read_bytes()
                    result['transition_observations'][0]['raw']=value['observations'][0]['raw'];util.write_json_atomic(resultpath,result)
                    value['result']=self.reference(resultpath)
                util.write_json_atomic(self.soak['path'],value);self.soak=self.reference(self.soak['path'])
                review=util.read_json(self.review['path']);review['actual_verification']=self.soak
                if mutation=='transition':review['result']=value['result']
                util.write_json_atomic(self.review['path'],review);self.review=self.reference(self.review['path'])
                decision={**self.decision_value,'actual_soak_verification':self.soak,'post_soak_independent_review':self.review}
                util.write_json_atomic(self.decision['path'],decision)
                with self.assertRaises(ValueError):self.build(recovery_decision=self.reference(self.decision['path']))
                if mutation=='transition':Path(resultpath).write_bytes(saved)
                util.write_json_atomic(self.soak['path'],original)

    def test_all87_future_pairs174_mocked_sends_and_gates_max4(self):
        self.handoff();d=self.dispatcher()
        with d.session():
            result=d.execute_next(escalate=True)
            while result['status']!='complete':result=d.execute_next(escalate=True)
            current=d.current()
            self.assertEqual(set(current['gates']),set(range(14,101)))
            self.assertEqual(len(current['dispatch']),174);self.assertEqual(len(set(self.sent)),174)
            self.assertEqual(self.peak,4);self.assertEqual(current['waves'][-1]['pairs'],[100])
            self.assertEqual(result['phase_pairs'],87)


if __name__=='__main__':unittest.main()
