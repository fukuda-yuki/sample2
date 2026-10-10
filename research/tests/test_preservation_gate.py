"""Finite model-free checks: exact scope, unchanged faults, replay/finalization."""
import copy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase, next_phase_sharing, pair_execution, preservation_gate as pg, wave_dispatch, wave_plan


def historical_v7_fixture_source():
    """Prospective fixture predates the immutable accepted-history verifier.

    Load the exact local Git blob, without replacing any executing module or
    altering the current saved-history acceptance/hash guards.
    """
    commit = '7b81e5709f5cfa2557476dd4486d459af4cd9c69'
    digest = '820bb8fe4513cb99a62464c1b2b61890d8b0bdf39ebbe83126c55e4afa0e7fc0'
    repo = Path(__file__).resolve().parents[2]
    blob = subprocess.run(['git', '-c', 'safe.directory=' + str(repo), 'cat-file', 'blob',
        commit + ':research/wave_plan.py'], cwd=repo, capture_output=True, check=True, timeout=10).stdout
    if hashlib.sha256(blob).hexdigest() != digest:
        raise AssertionError('Historical V7 fixture source bytes changed')
    module = types.ModuleType('historical_v7_prospective_fixture')
    module.__file__ = str(repo / 'research/wave_plan.py')
    exec(compile(blob, '<historical-v7:' + commit + '>', 'exec'), module.__dict__)
    return module


class PreservationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = 'a'*64
        self.current = {'dispatch':{},'implementations':{},'results':{}}
        for pos,(rid,instance) in enumerate(pg.PAIR_INSTANCES.items(),1):
            binding = {'run_id':rid,'run_instance_id':instance,'pair':53,'slot':104+pos,
                'plan_sha256':self.plan,'phase_sha256':pg.PHASE,'cohort':'runs/fixture',
                'runtime':'fixture','input_sha256':'b'*64,'condition_sha256':'c'*64}
            self.current['dispatch'][rid]=binding
            self.current['implementations'][rid]={'receipt':{'stop_confirmed':True,'submission_fixed':True}}
            self.current['results'][rid]={'row':{'run_id':rid,'run_instance_id':instance,
                'scoring':{'state':'evaluator_fault' if rid==pg.RUN else 'evaluation_incomplete'},'quality':None}}
        contract = self.root/'contract.json'; util.write_new_json(contract,{'fixture_only':True})
        self.reference = next_phase.reference(contract)
        digest='d'*64
        receipts = {
            'publication_receipt':{'remote_assets_verified':True,'urls':['fixture'],'package_sha256':digest},
            'roundtrip_receipt':{'hashes_match':True,'extraction_sockets_blocked':True,'package_sha256':digest},
            'cleanup_receipt':{'cleanup_completed':True,'original_runs_deleted':False,'package_sha256':digest,'targets':[]}}
        refs={self.reference['path']:self.reference['sha256']}
        self.gate={'pair':53,'plan_sha256':self.plan,'phase_sha256':pg.PHASE,'cohort':'runs/fixture',
            'run_instances':pg.PAIR_INSTANCES,'gate_kind':pg.KIND,'preservation_contract':self.reference,
            'quality_acceptance':False,'retained_scoring_state':'evaluator_fault','recovery_source_commit':'fixture'}
        for key,value in receipts.items():
            p=self.root/(key+'.json');util.write_new_json(p,value)
            self.gate[key]=str(p);refs[str(p)]=util.sha256_file(p)
        self.gate['evidence_files']=refs

    def validate_fixture(self, gate=None, current=None):
        # Only substitute the synthetic evidence leaf, leaving the current
        # exact gate identity, retained fault, and common receipt guards active.
        with patch.object(pg,'_validate_contract',side_effect=self.fixture_contract):
            return pair_execution._validate_gate(gate or self.gate,current or self.current,53)

    def fixture_contract(self, reference, *, current=None, history=None):
        if (reference != self.reference or history is not None
                or util.read_json(pg.checked(reference)) != {'fixture_only': True}):
            raise ValueError('Only this explicit synthetic contract fixture is covered')
        return {'source_commit': 'fixture'}

    def test_normal_fault_guard_and_exact_fixture_preservation(self):
        original=copy.deepcopy(self.current)
        self.assertTrue(pair_execution._postprocess_fault(self.current['results'][pg.RUN]['row']))
        ordinary={k:v for k,v in self.gate.items() if k not in
            ('gate_kind','preservation_contract','quality_acceptance','retained_scoring_state','recovery_source_commit')}
        with self.assertRaises(ValueError):pair_execution._validate_gate(ordinary,self.current,53)
        self.validate_fixture()
        self.assertEqual(self.current,original)
        self.assertIsNone(self.current['results'][pg.RUN]['row']['quality'])

    def test_wrong_scope_identity_and_quality_claims_rejected(self):
        changes=[('pair',54),('gate_kind','generic-http500'),('phase_sha256','e'*64),
            ('quality_acceptance',True),('retained_scoring_state','scored'),
            ('recovery_source_commit','different'),('run_instances',{pg.RUN:'different'})]
        for key,value in changes:
            with self.subTest(key=key):
                gate=copy.deepcopy(self.gate);gate[key]=value
                with self.assertRaises(ValueError):self.validate_fixture(gate)

    def test_exception_does_not_extend_to_peer_or_collection_fault(self):
        current=copy.deepcopy(self.current)
        peer=next(r for r in pg.PAIR_INSTANCES if r!=pg.RUN)
        current['results'][peer]['row']['scoring']['state']='evaluator_fault'
        with self.assertRaises(ValueError):self.validate_fixture(current=current)
        current=copy.deepcopy(self.current)
        current['implementations'][pg.RUN]['receipt']['collection_status']='collection_fault'
        with self.assertRaises(ValueError):self.validate_fixture(current=current)

    def test_normal_remote_restore_cleanup_and_contract_evidence_required(self):
        for key,field,value in [('publication_receipt','remote_assets_verified',False),
                ('roundtrip_receipt','hashes_match',False),('cleanup_receipt','cleanup_completed',False),
                ('cleanup_receipt','original_runs_deleted',True),('roundtrip_receipt','package_sha256','z'*64)]:
            with self.subTest(field=field):
                gate=copy.deepcopy(self.gate);p=Path(gate[key]);old=p.read_bytes()
                data=util.read_json(p);data[field]=value;util.write_json_atomic(p,data)
                gate['evidence_files'][str(p)]=util.sha256_file(p)
                with self.assertRaises(ValueError):self.validate_fixture(gate)
                p.write_bytes(old)
        gate=copy.deepcopy(self.gate);del gate['evidence_files'][self.reference['path']]
        with self.assertRaises(ValueError):self.validate_fixture(gate)

    def test_contract_without_real_evidence_or_authority_is_not_accepted(self):
        with self.assertRaises(ValueError):pg.validate_contract(self.reference)
        with self.assertRaises(ValueError):pg.validate_contract({'path':str(self.root/'absent'),'sha256':'0'*64})

    def journal_fixture(self, kind):
        journal=self.root/(kind+'.jsonl')
        assignments=list(self.current['dispatch'].values())
        phase={'assignments':[{'pair':53,'cases':assignments}], 'two_pair_blocks':[[53]],
            'maximum_pairs':2,'original_bundle':{'sha256':self.plan},'cohort':'runs/fixture','runtime':'fixture'}
        def append(kind,**fields):pair_execution.append(journal,{'kind':kind,'phase_sha256':pg.PHASE,**fields})
        append('wave_reserved',pairs=[53],blocks=1,run_cap=2,assignments=assignments)
        for b in assignments:
            append('dispatch',**{k:v for k,v in b.items() if k!='phase_sha256'})
            receipt=self.current['implementations'][b['run_id']]['receipt']
            p=self.root/(kind+'-implementation-'+b['run_id']+'.json')
            util.write_new_json(p,{'binding':b,'receipt':receipt})
            append('implemented',**{k:v for k,v in b.items() if k!='phase_sha256'},
                receipt=receipt,receipt_path=str(p),receipt_sha256=util.sha256_file(p))
        append('barrier',pairs=[53])
        for b in assignments:
            row=self.current['results'][b['run_id']]['row']
            p=self.root/(kind+'-result-'+b['run_id']+'.json');util.write_new_json(p,{'binding':b,'receipt':row})
            append('result',**{k:v for k,v in b.items() if k!='phase_sha256'},
                receipt=row,receipt_path=str(p),receipt_sha256=util.sha256_file(p))
        path=self.root/(kind+'-gate.json');util.write_new_json(path,self.gate)
        append(kind,pair=53,receipt_path=str(path),receipt_sha256=util.sha256_file(path))
        return journal,phase

    def test_strict_replay_requires_explicit_preservation_event(self):
        journal,phase=self.journal_fixture('pair_preservation_gate')
        with patch.object(pg,'_validate_contract',side_effect=self.fixture_contract):
            state=wave_dispatch.state(journal,phase,pg.PHASE)
        self.assertEqual(set(state['gates']),{53})
        self.assertEqual(state['results'][pg.RUN]['row']['scoring']['state'],'evaluator_fault')
        journal,phase=self.journal_fixture('pair_gate')
        with self.assertRaises(ValueError):wave_dispatch.state(journal,phase,pg.PHASE)

    def test_finalization_requires_same_private_contract_before_cleanup(self):
        batch=self.root/'batch';workspace=self.root/'workspace';workspace.mkdir()
        names=list(pg.PAIR_INSTANCES)
        for rid in names:(batch/rid).mkdir(parents=True)
        bundle_path=self.root/'bundle.json';bundle={'cohort':'runs/fixture'};util.write_new_json(bundle_path,bundle)
        review=workspace/'review.json';util.write_new_json(review,{'fixture_only':True})
        disclosure={'fixture_only':True};phase={'phase_sha256':pg.PHASE,'preservation_disposition':disclosure}
        fields={'gate_kind':pg.KIND,'preservation_contract':self.reference,'quality_acceptance':False,
                'retained_scoring_state':'evaluator_fault','recovery_source_commit':'fixture'}
        finalization=workspace/'finalization.json'
        util.write_new_json(finalization,{'pair':53,'plan_sha256':util.sha256_file(bundle_path),
            'cohort':'runs/fixture','review_sha256':util.sha256_file(review),'run_instances':pg.PAIR_INSTANCES,
            'phase_sha256':pg.PHASE,'evidence_files':{},**fields})
        def context(*args):return bundle,batch,self.current,{},list(self.current['dispatch'].values())
        with self.assertRaises(ValueError):
            next_phase_sharing.finish(self.root,bundle_path,53,workspace,review,finalization,
                context=context,phase=phase,record_gate=lambda *args:None)
        changed={**fields,'recovery_source_commit':'different'}
        with patch.object(pg,'gate_fields',return_value=changed),patch.object(pg,'public_disclosure',return_value=disclosure):
            with self.assertRaises(ValueError):
                next_phase_sharing.finish(self.root,bundle_path,53,workspace,review,finalization,
                    context=context,phase=phase,record_gate=lambda *args:None,preservation_contract=self.reference)

    def test_v7_only_original94_and_unchanged_policy_with_explicit_acceptance(self):
        assignments=[{'pair':n,'cases':[{'run_instance_id':str(2*n-1)},{'run_instance_id':str(2*n)}]}
                     for n in range(1,101)]
        original={'assignments':assignments}
        previous={'schema_version':6,'kind':wave_plan.V6_KIND,'phase_id':'central-wave-pair50-100-v6',
            'source_commit':'old','source_pins':{},'completed_pairs':list(range(1,50)),
            'assignments':assignments[49:],'shards':{str(n):(n%4)+1 for n in range(50,101)},
            'responsibility_counts':[],'two_pair_blocks':[], 'predecessor_phase':{},
            'predecessor_journal':{},'predecessor_gates':{},'maximum_pairs':2,'internal_concurrency':1,
            'no_refill':True,'thresholds':{'unchanged':1},'resource_probe':{'unchanged':True},
            'model_id':'deepseek-v4.1-flash'}
        pins={'research/preservation_gate.py':'a'*64}
        def saved(name,data):
            p=self.root/(name+'.json');util.write_new_json(p,data);return next_phase.reference(p)
        contract=saved('v7-contract',{'fixture_only':True})
        gate=saved('v7-gate',{'preservation_contract':contract})
        review=saved('v7-review',{'status':'passed','reviewed_commit':'handler','reviewed_source_sha256':pins})
        checks=saved('v7-checks',{'passed':True,'model_called':False})
        boundary=saved('v7-boundary',{'gated_pairs':53,'sent_stopped_fixed_archived':106,
            'remaining_original_UUID_count':94,'original_evaluator_fault_retained':True,
            'pair52_usage_missingness_retained':True})
        shared=saved('v7-shared',{'ordinary_push_and_no_ff_integration_completed':True,'source_commit':'integration'})
        acceptance=saved('v7-acceptance',{'kind':'exact_pair53_preservation_and_v7_future94_acceptance',
            'passed':True,'source_commit':'integration','remaining_original_UUID_count':94,
            'model_called':False,'evaluator_called':False,'contract':contract,'preservation_gate':gate,
            'source_review':review,'nonmodel_acceptance':checks,'preserved_boundary':boundary,'source_sharing':shared})
        shards={k:v for k,v in previous['shards'].items() if int(k)>=54}
        phase={**previous,'schema_version':7,'kind':wave_plan.V7_KIND,'phase_id':'central-wave-pair54-100-v7',
            'source_commit':'integration','source_pins':pins,'completed_pairs':list(range(1,54)),
            'assignments':assignments[53:],'shards':shards,
            'responsibility_counts':[sum(v==n for v in shards.values()) for n in range(1,5)],
            'two_pair_blocks':[list(range(i,min(i+2,101))) for i in range(54,101,2)],
            'predecessor_gates':{'53':gate},'preservation_acceptance':acceptance}
        # This prospective fixture is not the real immutable accepted history.
        # Current code must reject it; never patch the saved hash constants or
        # its loader/gate/contract verifier to make synthetic history accepted.
        untouched = Path(acceptance['path']).read_bytes()
        with patch.object(wave_plan,'predecessor_state',return_value=(previous,original,{})):
            with self.assertRaisesRegex(ValueError, 'Wrong immutable historical phase/gate'):
                wave_plan.validate_v7(phase)
        self.assertEqual(Path(acceptance['path']).read_bytes(), untouched)
        historical = historical_v7_fixture_source()
        with patch.object(historical,'predecessor_state',return_value=(previous,original,{})),\
                patch.object(pg,'validate_gate'),patch.object(pg,'validate_contract',return_value={
                    'source_commit':'handler','evidence':{'source_review':review,'nonmodel_acceptance':checks}}):
            self.assertEqual(historical.validate_v7(phase),original)
            self.assertEqual(sum(len(p['cases']) for p in phase['assignments']),94)
            for field,value in [('assignments',assignments[52:]),('maximum_pairs',4),
                    ('resource_probe',{'different':True}),('thresholds',{'relaxed':0}),
                    ('model_id','different'),('internal_concurrency',2)]:
                changed=copy.deepcopy(phase);changed[field]=value
                with self.subTest(field=field),self.assertRaises(ValueError):historical.validate_v7(changed)
            changed=copy.deepcopy(phase);changed.pop('preservation_acceptance')
            with self.assertRaises(ValueError):historical.validate_v7(changed)
            for key,reference in [('source_review',saved('other-review',util.read_json(review['path']))),
                                  ('nonmodel_acceptance',saved('other-checks',util.read_json(checks['path'])))]:
                alternate=util.read_json(acceptance['path']);alternate[key]=reference
                changed=copy.deepcopy(phase);changed['preservation_acceptance']=saved('other-acceptance-'+key,alternate)
                with self.subTest(key=key),self.assertRaises(ValueError):historical.validate_v7(changed)


if __name__=='__main__':unittest.main()
