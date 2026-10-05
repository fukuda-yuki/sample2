"""Saved-data finite boundaries; no browser, scoring, provider or Run writes."""
from pathlib import Path
import copy, tempfile, unittest
from unittest.mock import patch
from outer.harness import util
from research import app_failure_preservation as app, wave_dispatch, next_phase, pair_execution

ROOT=Path(__file__).resolve().parents[2].parent/'v5-go30m'
MUSIC=ROOT/'runs/source-info-v5-100p2/MS1-CONT-B-preload-5067'
SCHOOL=ROOT/'runs/source-info-v5-100p2/CU1-ENR-D-preload-5053'


class AppFailureTests(unittest.TestCase):
    def setUp(self):
        if not MUSIC.is_dir(): self.skipTest('Actual private saved67 evidence required')
        self.directory=MUSIC/util.read_lines(MUSIC/'evaluations/index.jsonl')[0]['directory']

    def test_actual67_and_saved_school_evidence_no_gate_adoption(self):
        self.assertEqual(app.app_exception_evidence(MUSIC)['category'],'music_generated_cart_db_constraint')
        self.assertEqual(app.app_exception_evidence(SCHOOL)['category'],'school_generated_missing_view')

    def test_http500_without_app_exception_or_source_or_request_rejected(self):
        log=self.directory/'browser-server.log';old=Path.read_text
        for needle in ('UNIQUE constraint failed: Carts.RecordId','ShoppingCartController.AddToCart(Int32 id)',
                       'GET http://127.0.0.1:62420/ShoppingCart/AddToCart/1 - 500'):
            def read(p,*args,**kwargs):
                text=old(p,*args,**kwargs)
                return text.replace(needle,'unclassified') if p==log else text
            with self.subTest(needle=needle),patch.object(Path,'read_text',read):
                with self.assertRaises(ValueError): app.app_exception_evidence(MUSIC)

    def test_music_mixed_exception_and_interleaved_request_rejected(self):
        log=self.directory/'browser-server.log';old=Path.read_text
        def mixed(s):return s.replace('Microsoft.EntityFrameworkCore.DbUpdateException:', 'System.IO.IOException: unknown infrastructure fault\nMicrosoft.EntityFrameworkCore.DbUpdateException:')
        def crossed(s):return s.replace('Request starting HTTP/1.1 GET http://127.0.0.1:62420/ShoppingCart/AddToCart/1 - - -',
            'Request starting HTTP/1.1 GET http://127.0.0.1:62420/ShoppingCart/AddToCart/1 - - -\nRequest starting HTTP/1.1 GET http://127.0.0.1:62420/foreign - - -')
        for change in (mixed,crossed):
            self.assertNotEqual(change(old(log,encoding='utf8')),old(log,encoding='utf8'))
            with self.subTest(change=change.__name__),patch.object(Path,'read_text',lambda p,*a,**kw:change(old(p,*a,**kw)) if p==log else old(p,*a,**kw)):
                with self.assertRaises(ValueError):app.app_exception_evidence(MUSIC)

    def test_wrong_owned_identity_endpoint_and_cleanup_rejected(self):
        path=self.directory/'browser-intent.json';baseline=util.read_json(path);old=util.read_json
        for field,value in (('run_instance_id','foreign'),('artifact_sha256','0'*64),
                            ('base_url','http://127.0.0.1:1'),('launch_command',[])):
            changed=copy.deepcopy(baseline);changed[field]=value
            with self.subTest(field=field),patch.object(util,'read_json',side_effect=lambda p:changed if Path(p)==path else old(p)):
                with self.assertRaises(ValueError):app.app_exception_evidence(MUSIC)

    def test_changed_first_attempt_or_original_result_rejected(self):
        path=MUSIC/'evaluations/index.jsonl';baseline=util.read_lines(path);old=util.read_lines
        for field,value in (('sequence',2),('adopted',True),('quality',100),('scoring_state','scored')):
            changed=copy.deepcopy(baseline);changed[0][field]=value
            with self.subTest(field=field),patch.object(util,'read_lines',side_effect=lambda p:changed if Path(p)==path else old(p)):
                with self.assertRaises(ValueError):app.app_exception_evidence(MUSIC)

    def test_no_policy_or_other_fault_never_exempted(self):
        d=wave_dispatch.Dispatcher.__new__(wave_dispatch.Dispatcher);d.app_failure_policy=None
        self.assertFalse(d.retained_fault({'run_id':MUSIC.name},{'scoring':{'state':'evaluator_fault'}}))
        d.app_failure_policy={'path':'does-not-exist','sha256':'0'*64}
        self.assertFalse(d.retained_fault({'run_id':MUSIC.name},{'scoring':{'state':'rejected_mismatch'}}))
        self.assertFalse(d.retained_fault({'run_id':MUSIC.name},{'operation_status':'cleanup_failed'}))

    def test_school_mixed_fault_spec_other_view_or_foreign_attempt_rejected(self):
        directory=SCHOOL/util.read_lines(SCHOOL/'evaluations/index.jsonl')[0]['directory']
        old=util.read_json
        for filename,field,value in [('browser-school/request.json','specSha256','foreign'),
                ('browser-school/collector-receipt.json','specSha256','foreign'),
                ('browser-intent.json','collector_command',[])]:
            path=directory/filename; changed=copy.deepcopy(old(path));changed[field]=value
            with self.subTest(filename=filename),patch.object(util,'read_json',side_effect=lambda p:changed if Path(p)==path else old(p)):
                with self.assertRaises(ValueError):app.app_exception_evidence(SCHOOL)
        old_text=Path.read_text
        for path,change in [(directory/'browser-server.log',lambda s:s+'\nSystem.IO.IOException: unknown host fault\n'),
                (SCHOOL/'frozen/Controllers/StudentController.cs',lambda s:s.replace('View(new StudentFormViewModel())','View("Other")'))]:
            with self.subTest(path=str(path)),patch.object(Path,'read_text',lambda p,*a,**kw:change(old_text(p,*a,**kw)) if p==path else old_text(p,*a,**kw)):
                with self.assertRaises(ValueError):app.app_exception_evidence(SCHOOL)

    def test_contract_fault_set_handler_and_typed_gate_boundaries(self):
        # Isolation tests mock policy acceptance only. Saved67 bytes are read;
        # temporary contracts are never published or adopted as actual gates.
        proof=app.app_exception_evidence(MUSIC)
        bundle=next_phase.reference(ROOT/'artifacts/main-go30m-current-fixed-20261004/bundle.json')
        phase_ref=next_phase.reference(ROOT/'artifacts/main-central-wave-v9-fixed-20261005/phase.json')
        phase=util.read_json(phase_ref['path']);assignment=next(a for a in util.read_json(bundle['path'])['assignments'] if a['pair']==67)
        instances={c['run_id']:c['run_instance_id'] for c in assignment['cases']}
        policy={'batch':str(MUSIC.parent),'original_bundle':bundle,'source_commit':'unit-fixture',
            'source_tree':'unit-tree','allowed_instances':instances,'source_pins':{n:'fixture-pin' for n in app.CORE}}
        current={'results':{rid:{'row':proof['row'] if rid==MUSIC.name else {'scoring':{'state':'scored'}}} for rid in instances}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'validate_policy',return_value=policy):
            tmp=Path(tmp);policy_ref={'path':str(tmp/'policy.json'),'sha256':'fixture-reference'}
            handler={'kind':'actual_imported_app_preservation_handler','policy':policy_ref,'source_commit':policy['source_commit'],
                'source_tree':policy['source_tree'],'sole_cohort_lease_held':True,'original_bundle':bundle,
                'phase':phase_ref,'phase_id':phase['phase_id'],'model_called':False,'evaluator_called':False,
                'actual_imported_modules':{n:{'sha256':'fixture-pin'} for n in app.CORE}}
            util.write_json_atomic(tmp/'handler.json',handler)
            contract={'kind':app.CONTRACT_KIND,'quality_acceptance':False,'policy':policy_ref,'pair':67,
                'original_bundle':bundle,'run_instances':instances,'phase_sha256':phase_ref['sha256'],
                'handler_execution':next_phase.reference(tmp/'handler.json'),'faults':[proof]}
            def check(value):
                util.write_json_atomic(tmp/'contract.json',value)
                return app.validate_contract(next_phase.reference(tmp/'contract.json'),current=current)
            self.assertEqual(check(contract)['pair'],67)
            for field,value in [('pair',66),('faults',[proof,proof]),('phase_sha256','0'*64),('quality_acceptance',True)]:
                changed=copy.deepcopy(contract);changed[field]=value
                with self.subTest(field=field),self.assertRaises((ValueError,KeyError)):check(changed)
            foreign=copy.deepcopy(contract);foreign['faults'][0]['run_id']='foreign'
            with self.assertRaises(ValueError):check(foreign)
            changed_current=copy.deepcopy(current);peer=next(r for r in instances if r!=MUSIC.name)
            changed_current['results'][peer]['row']={'scoring':{'state':'evaluator_fault'}}
            util.write_json_atomic(tmp/'contract.json',contract);ref=next_phase.reference(tmp/'contract.json')
            with self.assertRaises(ValueError):app.validate_contract(ref,current=changed_current)
            gate={'gate_kind':app.KIND,'preservation_contract':ref,'phase_sha256':phase_ref['sha256'],
                'run_instances':instances,'quality_acceptance':False,'retained_scoring_state':'evaluator_fault',
                'recovery_source_commit':'unit-fixture','evidence_files':{ref['path']:ref['sha256']}}
            with patch.object(pair_execution,'_validate_gate_common') as common:
                app.validate_gate(gate,current,67);common.assert_called_once()
                for field,value in [('gate_kind','ordinary'),('quality_acceptance',True),('phase_sha256','0'*64),
                        ('recovery_source_commit','foreign'),('evidence_files',{})]:
                    changed=copy.deepcopy(gate);changed[field]=value
                    with self.subTest(gate_field=field),self.assertRaises(ValueError):app.validate_gate(changed,current,67)


if __name__=='__main__':unittest.main()

