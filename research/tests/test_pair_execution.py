"""One manager, real durable receipts, bounded injected implementation workers."""
from concurrent.futures import Future
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from outer.harness import machine, util
from research import pair_execution as pair


class PairExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.batch=self.root/'runs'
        self.plan={'cohort':'technical-fixture','plan_sha256':'a'*64,'runtime':'fixture'}
        self.cases=[{'run_id':r,'pair':1,'slot':i,'task':'fixture','condition':'arm'+str(i),'attempt':1}
                    for i,r in enumerate(('A','B'),1)]
        self.active=0; self.peak=0; self.lock=threading.Lock(); self.stopped=[]; self.heavy=[]

    def prepare(self,binding):
        m={**binding,'stop_confirmed':False,'prompt_sha256':'b'*64}
        util.write_new_json(self.batch/binding['run_id']/'manifest.json',m)
        return m

    def implement(self,repo,batch,rid):
        with self.lock: self.active+=1; self.peak=max(self.peak,self.active)
        time.sleep(.06 if rid=='A' else .01)
        with self.lock: self.active-=1; self.stopped.append(rid)
        m=util.read_json(batch/rid/'manifest.json'); m['stop_confirmed']=True
        util.write_json_atomic(batch/rid/'manifest.json',m)
        receipt={'run_id':rid,'run_instance_id':m['run_instance_id'],'stop_confirmed':True}
        util.write_new_json(batch/rid/'implementation-receipt.json',receipt)
        return receipt

    def postprocess(self,repo,batch,rid,archive):
        self.assertEqual(self.active,0); self.assertEqual(set(self.stopped),{'A','B'})
        self.assertTrue(all((batch/r/'implementation-receipt.json').exists() for r in ('A','B')))
        self.heavy.append(rid); return {'run_id':rid,'verdict':'fail'}

    def execute(self,concurrency=2,**kw):
        return pair.execute_pair(self.plan,self.cases,self.batch,repo=self.root,concurrency=concurrency,
            prepare=self.prepare,implement=kw.pop('implement',self.implement),postprocess=self.postprocess,**kw)

    def test_reverse_completion_barrier_identity_and_no_redispatch(self):
        result=self.execute()
        self.assertEqual(self.peak,2); self.assertEqual(self.stopped,['B','A']); self.assertEqual(self.heavy,['A','B'])
        self.assertEqual(result['reason'],'pair_publication_restore_cleanup_required')
        before=(self.batch/'_control/pair-journal.jsonl').read_bytes()
        self.assertEqual(self.execute()['reason'],'dispatched_identity_never_replayed')
        self.assertEqual(before,(self.batch/'_control/pair-journal.jsonl').read_bytes())
        for c in self.cases: (self.batch/c['run_id']/'manifest.json').unlink()
        self.assertEqual(self.execute()['reason'],'dispatched_identity_never_replayed')

    def test_serial_regression(self):
        self.execute(concurrency=1); self.assertEqual(self.peak,1); self.assertEqual(self.stopped,['A','B'])

    def test_collection_sidecar_hold_preserves_confirmed_raw_and_blocks_recovery_resume(self):
        import sqlite3
        from contextlib import closing
        sends=[]
        originals={}
        def prepare(binding):
            manifest=self.prepare(binding)
            root=self.batch/binding['run_id']
            util.write_new_json(root/'condition.json',{'collection_policy':util.STATIC_DB_COLLECTION_POLICY})
            manifest.update(collection_policy=util.STATIC_DB_COLLECTION_POLICY,submission_fixed=False,
                condition_sha256=util.sha256_file(root/'condition.json'))
            util.write_json_atomic(root/'manifest.json',manifest)
            data=root/'workspace/Data'; data.mkdir(parents=True)
            dbfile=data/'seed.sqlite'
            with closing(sqlite3.connect(dbfile)) as db:
                db.execute('CREATE TABLE Facts(Id INTEGER)'); db.commit()
            if binding['run_id']=='A': Path(str(dbfile)+'-wal').write_bytes(b'unresolved-sidecar')
            originals[binding['run_id']]=util.tree_hashes(root/'workspace')
            return manifest
        def stopped_runtime(repo,batch,rid):
            sends.append(rid)
            root=batch/rid
            raw=root/'usage/raw'; raw.mkdir(parents=True)
            (raw/'fixture.response.sse').write_bytes(b'data: synthetic-no-provider-fixture\n\n')
            manifest=util.read_json(root/'manifest.json'); manifest['stop_confirmed']=True
            util.write_json_atomic(root/'manifest.json',manifest)
            return manifest
        with patch.object(machine.runtime,'start',side_effect=stopped_runtime):
            result=pair.execute_pair(self.plan,self.cases,self.batch,repo=self.root,concurrency=1,
                prepare=prepare,implement=machine.implement,postprocess=self.postprocess)
        self.assertEqual('implementation_fault',result['reason'])
        self.assertEqual(['A'],sends)
        self.assertEqual([],self.heavy)
        root=self.batch/'A'; receipt_path=root/'implementation-receipt.json'
        receipt=util.read_json(receipt_path); original_hash=util.sha256_file(receipt_path)
        self.assertTrue(receipt['stop_confirmed'])
        self.assertFalse(receipt['submission_fixed'])
        self.assertEqual('collection_fault',receipt['collection_status'])
        self.assertEqual('ValueError',receipt['collection_error_type'])
        self.assertIsNone(receipt['snapshot_sha256'])
        self.assertEqual(util.tree_hashes(root/'usage/raw'),receipt['raw'])
        self.assertEqual(originals['A'],util.tree_hashes(root/'workspace'))
        self.assertFalse((root/'frozen').exists())
        with patch.object(machine.evaluate,'score_run',side_effect=lambda *a:self.fail('No ordinary scorer after collection fault')):
            with self.assertRaisesRegex(RuntimeError,'collection fault blocks'):
                machine.postprocess(self.root,self.batch,'A',self.root/'archive')
        self.assertFalse((root/'postprocess-timing.jsonl').exists())
        recovered=pair.recover_pair(self.plan,self.batch,repo=self.root,
            stop=lambda *a:self.fail('Already stopped raw must not be re-stopped'),
            postprocess=lambda *a:self.fail('Collection fault must block all heavy stages'))
        self.assertEqual('collection_fault',recovered['reason'])
        self.assertTrue(recovered['stop_confirmed'])
        self.assertFalse(recovered['submission_fixed'])
        journal=self.batch/'_control/pair-journal.jsonl'; current=pair.state(journal)
        auth={'authorized':True,'approved_by':'user','authorization_reference':'fixture-only',
            'plan_sha256':self.plan['plan_sha256'],'journal_sha256':util.sha256_file(journal),
            'run_instances':{'B':current['reserved']['B']['run_instance_id']}}
        resumed=pair.resume_pair(self.plan,self.batch,auth,repo=self.root,
            verify=lambda *a:self.fail('Held collection must not authorize further dispatch'),
            implement=lambda *a:self.fail('No unsent peer model/worker start'),postprocess=self.postprocess)
        self.assertEqual('collection_fault',resumed['reason'])
        self.assertEqual(original_hash,util.sha256_file(receipt_path))
        self.assertEqual([],self.heavy)

    def test_unconfirmed_one_side_blocks_all_heavy_work(self):
        def implement(repo,batch,rid):
            r=self.implement(repo,batch,rid)
            if rid=='A': r['stop_confirmed']=False
            return r
        self.assertEqual(self.execute(implement=implement)['reason'],'implementation_fault')
        self.assertEqual(self.heavy,[])

    def test_second_manager_and_third_run_rejected(self):
        with pair.exclusive(self.batch/'_control'):
            with self.assertRaises(OSError): self.execute()
        with self.assertRaises(ValueError):
            pair.execute_pair(self.plan,self.cases+[self.cases[0]],self.batch,repo=self.root)

    def test_wrong_instance_result_and_changed_gate_rejected(self):
        self.execute()
        journal=self.batch/'_control/pair-journal.jsonl'
        pair.append(journal,{'kind':'result',**self.cases[0],'run_instance_id':'wrong','plan_sha256':'a'*64})
        with self.assertRaises(ValueError): pair.state(journal)

    def test_next_pair_waits_for_real_receipt_and_boolean_gate_fails(self):
        self.execute()
        next_cases=[{**c,'pair':2,'run_id':c['run_id']+'2','slot':c['slot']+2} for c in self.cases]
        result=pair.execute_pair(self.plan,next_cases,self.batch,repo=self.root,prepare=self.prepare)
        self.assertEqual(result['reason'],'previous_pair_gate')
        proof=self.root/'fake-gate.json'; util.write_new_json(proof,{'pair':1,
            'publication_verified':True,'independent_restore_verified':True,'owned_cleanup_verified':True})
        with self.assertRaises(ValueError): pair.record_pair_gate(self.batch,1,proof)

    def test_caller_plan_and_result_receipt_changes_rejected(self):
        self.execute()
        for field in ('plan_sha256','cohort','runtime'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                pair.recover_pair({**self.plan,field:'wrong'},self.batch,repo=self.root)
        receipt=self.batch/'A/postprocess-receipt.json'
        value=util.read_json(receipt); value['row']['verdict']='pass'
        util.write_json_atomic(receipt,value)
        with self.assertRaises(ValueError): pair.state(self.batch/'_control/pair-journal.jsonl')

    def test_serial_fault_explicit_resume_only_same_unsent_instance(self):
        def broken(repo,batch,rid):
            receipt=self.implement(repo,batch,rid)
            return {**receipt,'error_type':'SyntheticProviderFault'}
        self.assertEqual(self.execute(concurrency=1,implement=broken)['reason'],'implementation_fault')
        journal=self.batch/'_control/pair-journal.jsonl'
        current=pair.state(journal); instance=current['reserved']['B']['run_instance_id']
        auth={'authorized':True,'approved_by':'user','authorization_reference':'test-only explicit resume',
            'plan_sha256':self.plan['plan_sha256'],'journal_sha256':util.sha256_file(journal),
            'run_instances':{'B':instance}}
        result=pair.resume_pair(self.plan,self.batch,auth,repo=self.root,verify=lambda *a:None,
            implement=self.implement,postprocess=self.postprocess)
        self.assertEqual(result['reason'],'pair_publication_restore_cleanup_required')
        current=pair.state(journal)
        self.assertEqual(current['dispatch']['B']['run_instance_id'],instance)
        self.assertEqual(self.stopped,['A','B'])

    def test_child_completion_before_manager_result_recovers_without_send(self):
        self.execute()
        journal=self.batch/'_control/pair-journal.jsonl'
        rows=pair.events(journal)
        rows=[r for r in rows if not (r['kind']=='result' and r['run_id']=='B')]
        journal.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        result=pair.recover_pair(self.plan,self.batch,repo=self.root,stop=lambda r: self.fail('unexpected stop'),
            postprocess=lambda *a:self.fail('unexpected repeated heavy work'))
        self.assertEqual(result['reason'],'pair_publication_restore_cleanup_required')
        self.assertEqual(len(pair.state(journal)['results']),2)

    def test_shared_fault_requests_owned_peer_stop(self):
        entered,stopped=threading.Event(),threading.Event()
        requests=[]
        def implement(repo,batch,rid):
            if rid=='A':
                self.assertTrue(entered.wait(2))
                receipt=self.implement(repo,batch,rid)
                return {**receipt,'error_type':'SyntheticStorageFault'}
            entered.set(); self.assertTrue(stopped.wait(2))
            return self.implement(repo,batch,rid)
        def stop(root): requests.append(root.name); stopped.set()
        self.assertEqual(self.execute(implement=implement,stop=stop)['reason'],'implementation_fault')
        self.assertEqual(requests,['B']); self.assertFalse(self.heavy)

    def test_known_first_fault_stops_second_dispatch(self):
        class ImmediatePool:
            def __init__(self,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def submit(self,fn,*args):
                f=Future(); f.set_result(fn(*args)); return f
        def broken(repo,batch,rid):
            return {**self.implement(repo,batch,rid),'error_type':'KnownProviderFault'}
        with patch.object(pair,'ThreadPoolExecutor',ImmediatePool): self.execute(implement=broken)
        self.assertEqual(set(pair.state(self.batch/'_control/pair-journal.jsonl')['dispatch']),{'A'})

    def test_inner_gate_receipt_changes_rejected_on_reader(self):
        self.execute(); journal=self.batch/'_control/pair-journal.jsonl'
        current=pair.state(journal)
        values={'publication_receipt':{'remote_assets_verified':True,'urls':{'zip':'mock://asset'},'package_sha256':'c'*64},
            'roundtrip_receipt':{'hashes_match':True,'extraction_sockets_blocked':True,'package_sha256':'c'*64},
            'cleanup_receipt':{'cleanup_completed':True,'original_runs_deleted':False,'package_sha256':'c'*64}}
        refs={}; paths={}
        for key,value in values.items():
            path=self.root/(key+'.json'); util.write_new_json(path,value)
            refs[str(path)]=util.sha256_file(path); paths[key]=str(path)
        gate={'pair':1,'plan_sha256':self.plan['plan_sha256'],'cohort':self.plan['cohort'],
            'run_instances':{rid:d['run_instance_id'] for rid,d in current['dispatch'].items()},
            'evidence_files':refs,**paths}
        path=self.root/'gate.json'; util.write_new_json(path,gate)
        pair.record_pair_gate(self.batch,1,path)
        util.write_json_atomic(paths['publication_receipt'],{**values['publication_receipt'],'urls':{}})
        with self.assertRaises(ValueError): pair.state(journal)

    def test_scoring_infrastructure_fault_retains_row_and_blocks_next_processing(self):
        calls=[]
        def postprocess(repo,batch,rid,archive):
            calls.append(rid)
            return {'run_id':rid,'verdict':None,'scoring':{'state':'evaluator_fault'}}
        result=pair.execute_pair(self.plan,self.cases,self.batch,repo=self.root,concurrency=2,
            prepare=self.prepare,implement=self.implement,postprocess=postprocess)
        self.assertEqual(result['reason'],'postprocess_fault')
        self.assertEqual(calls,['A'])
        current=pair.state(self.batch/'_control/pair-journal.jsonl')
        self.assertEqual(current['results']['A']['row']['scoring']['state'],'evaluator_fault')
        recovered=pair.recover_pair(self.plan,self.batch,repo=self.root,postprocess=postprocess)
        self.assertEqual(recovered['reason'],'postprocess_fault')
        self.assertEqual(calls,['A'])

    def test_second_recorded_scoring_fault_rejects_publication_gate(self):
        def postprocess(repo,batch,rid,archive):
            return {'run_id':rid,'verdict':'fail','scoring':{'state':'completed' if rid=='A' else 'evaluator_fault'}}
        result=pair.execute_pair(self.plan,self.cases,self.batch,repo=self.root,concurrency=2,
            prepare=self.prepare,implement=self.implement,postprocess=postprocess)
        self.assertEqual(result['reason'],'postprocess_fault')
        proof=self.root/'gate.json'; util.write_new_json(proof,{})
        with self.assertRaisesRegex(ValueError,'Recorded postprocess fault'):
            pair.record_pair_gate(self.batch,1,proof)

    def test_stop_reconciliation_binds_final_raw_and_retains_original_receipt(self):
        def implement(repo,batch,rid):
            receipt=self.implement(repo,batch,rid)
            if rid=='A':
                raw=batch/rid/'usage/raw'; raw.mkdir(parents=True)
                (raw/'response.sse').write_bytes(b'partial')
                receipt.update(stop_confirmed=False,raw=util.tree_hashes(raw))
                util.write_json_atomic(batch/rid/'implementation-receipt.json',receipt)
                m=util.read_json(batch/rid/'manifest.json'); m['stop_confirmed']=False
                util.write_json_atomic(batch/rid/'manifest.json',m)
            return receipt
        self.assertEqual(self.execute(implement=implement)['reason'],'implementation_fault')
        original=self.batch/'A/implementation-receipt.json'; original_hash=util.sha256_file(original)
        def stop(root):
            (root/'usage/raw/response.sse').write_bytes(b'final stopped stream')
            m=util.read_json(root/'manifest.json'); m['stop_confirmed']=True
            util.write_json_atomic(root/'manifest.json',m)
        def collect(batch,rid): util.write_new_json(batch/rid/'snapshot.json',{'artifact_state':'fixed'})
        with patch.object(pair.run,'collect_run',collect):
            result=pair.recover_pair(self.plan,self.batch,repo=self.root,stop=stop,postprocess=self.postprocess)
        self.assertEqual(result['reason'],'pair_publication_restore_cleanup_required')
        current=pair.state(self.batch/'_control/pair-journal.jsonl')
        receipt=current['implementations']['A']['receipt']
        self.assertEqual(receipt['raw'],util.tree_hashes(self.batch/'A/usage/raw'))
        self.assertEqual(receipt['manifest_sha256'],util.sha256_file(self.batch/'A/manifest.json'))
        self.assertEqual(receipt['snapshot_sha256'],util.sha256_file(self.batch/'A/snapshot.json'))
        self.assertEqual(receipt['reconciles_implementation_receipt']['sha256'],original_hash)
        self.assertEqual(util.sha256_file(original),original_hash)
        self.assertFalse(util.read_json(original)['stop_confirmed'])
        util.write_json_atomic(original,{**util.read_json(original),'stop_confirmed':True})
        with self.assertRaisesRegex(ValueError,'original receipt changed'):
            pair.state(self.batch/'_control/pair-journal.jsonl')


if __name__ == '__main__': unittest.main()
