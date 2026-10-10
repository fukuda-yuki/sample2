"""Production-shaped finite fixtures; no real acquisition, model or publication."""
import copy
from pathlib import Path
import shutil
from unittest.mock import patch

from outer.harness import profiles, util
from research import acquisition_sharing as sharing, acquisition_readiness as readiness
from research import live_pilot, next_phase, next_phase_sharing, catalog_share, catalog_delivery, pair_execution
from research.tests.test_acquisition_readiness import ReadinessFixture, ROOT


class AcquisitionSharingTests(ReadinessFixture):
    def setUp(self):
        super().setUp()
        launcher=self.repo/'research/live_pilot_launcher.py'
        if not launcher.exists():
            launcher.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'research/live_pilot_launcher.py',launcher)
            self.plan['source_pins']['research/live_pilot_launcher.py']=util.sha256_file(launcher)
        self.plan['launch_supervisor']=live_pilot.reference(launcher);self.write_plan()
        self.allocate(); self.pair=self.plan['assignments'][0]; self.number=self.pair['pair']
        self.batch=Path(self.plan['batch'])/('pair-'+str(self.number))
        self.phase_path=self.batch/'phase.json'; self.phase=util.read_json(self.phase_path)
        profile=profiles.task_profile(self.repo,self.pair['task'],readiness.REVISION)
        names=['research/__init__.py','research/catalog_allocation_review.py','research/catalog_share.py',
            'research/sql/catalog_otel_requests.sql','research/tasks/candidate-register.json',
            'research/sharing/CONTINUITY-README.md','research/sharing/THIRD-PARTY-NOTICES.md',
            'research/sharing/LICENSES/MS-PL.txt','research/sharing/LICENSES/OpenCode-MIT.txt',profile['evaluation']['spec_path']]
        for name in names:
            target=self.repo/name;target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():shutil.copyfile(ROOT/name,target)
        def prepare(binding):
            root=self.batch/binding['run_id']; root.mkdir(parents=True)
            # Production prepare COPIES its binding to add phase SHA; the
            # pair journal does not acquire that field by alias mutation.
            assignment={**binding,'phase_sha256':util.sha256_file(self.phase_path)}
            condition={'task_profile_revision':readiness.REVISION,'runtime':{'id':self.phase['runtime'],'model_id':self.plan['settings']['model_id']}}
            util.write_new_json(root/'condition.json',condition)
            prompt=b'Synthetic providerless test only\n';(root/'inputs').mkdir();(root/'inputs/prompt.txt').write_bytes(prompt)
            manifest={**binding,'assignment':assignment,'prompt_sha256':util.sha256_bytes(prompt),
                'condition_sha256':util.sha256_file(root/'condition.json'),'synthetic':True,'model_called':False}
            util.write_new_json(root/'manifest.json',manifest)
            util.write_new_json(root/'usage/normalized.json',{'run_id':binding['run_id'],'run_instance_id':binding['run_instance_id'],
                'usage_complete':False,'total_tokens':None,'fixture':True})
            (root/'frozen').mkdir();(root/'frozen/artifact.txt').write_text('Fake generated output; no model\n',encoding='utf8')
            return manifest
        def implement(repo,batch,rid):
            m=util.read_json(batch/rid/'manifest.json')
            return {'run_id':rid,'run_instance_id':m['run_instance_id'],'stop_confirmed':True,'raw':{},'fixture':True,'model_called':False}
        def postprocess(repo,batch,rid,archive):
            return {'run_id':rid,'scoring':{'state':'scored'},'verdict':'blocked','quality':None,'fixture':True}
        pair_execution.execute_pair({'plan_sha256':util.sha256_file(self.plan_path),'cohort':self.phase['cohort'],
            'runtime':self.phase['runtime'],'require_fixed_instances':True},self.pair['cases'],self.batch,repo=self.repo,
            concurrency=2,prepare=prepare,implement=implement,postprocess=postprocess)
        self.workspace=self.repo/'artifacts/continuity-sharing-v1/finite-newmain'
        self.review=self.workspace/'exact-review.json';self.remote=self.root/'synthetic-remote';self.remote.mkdir()

    def stage_review(self):
        sharing.stage(self.repo,self.plan_path,self.number,self.workspace)
        util.write_new_json(self.review,{'publication_approved':True,'reviewer':'Finite synthetic fixture; no real public acceptance',
            'reviewed_inventory':catalog_share.inventory(self.workspace/'public')})

    def transfer(self,package,tag,commit):
        self.assertEqual(tag,'source-info-repaired-v6-'+util.sha256_file(self.plan_path)[:12]+'-pair-'+f'{self.number:03d}')
        self.assertEqual(commit,self.plan['source_commit'])
        asset=catalog_delivery.verify_package(package)
        names=[p['name'] for p in asset['parts']]+['pair.manifest.json','public-review.json','scan.json']
        for name in names:shutil.copyfile(package/name,self.remote/name)
        return {n:'https://github.com/'+catalog_delivery.REPOSITORY+'/releases/download/'+tag+'/'+n for n in names}

    def injected_pipeline(self):
        self.stage_review();before={c['run_id']:catalog_share.inventory(self.batch/c['run_id']) for c in self.pair['cases']}
        with patch('research.catalog_share.known_secret',return_value=b'explicit-synthetic-canary'):
            with self.assertRaisesRegex(ValueError,'Injected transport'):
                sharing.share(self.repo,self.plan_path,self.number,self.workspace,self.review,transfer=self.transfer,
                    fetch=lambda u,t:shutil.copyfile(self.remote/u.rsplit('/',1)[-1],t))
        self.assertNotIn(self.number,pair_execution.state(self.batch/'_control/pair-journal.jsonl')['gates'])
        self.assertFalse((self.workspace/'repaired-main-gate-001.json').exists())
        for rid,inventory in before.items():self.assertEqual(inventory,catalog_share.inventory(self.batch/rid))
        return before

    def synthetic_valid_gate(self):
        """Construct semantic receipt-validator controls, NOT actual remote proof."""
        self.injected_pipeline()
        publication_path=self.workspace/'publication-receipt.json';publication=util.read_json(publication_path)
        tag='source-info-repaired-v6-'+util.sha256_file(self.plan_path)[:12]+'-pair-'+f'{self.number:03d}'
        remote_path=self.workspace/'actual-remote-readback.json'
        remote={'tag_name':tag,'release_id':123,'target_commitish':self.plan['source_commit'],'tag_commit':self.plan['source_commit'],
            'html_url':'https://github.com/'+catalog_delivery.REPOSITORY+'/releases/tag/'+tag,
            'assets':[{'id':i+1,'name':name,'size':(self.remote/name).stat().st_size,
                'digest':'sha256:'+util.sha256_file(self.remote/name),'browser_download_url':url}
                for i,(name,url) in enumerate(publication['urls'].items())]}
        util.write_new_json(remote_path,remote)
        publication.update(transport_mode='github-release-anonymous-download-v1',actual_remote_readback=live_pilot.reference(remote_path))
        util.write_json_atomic(publication_path,publication)
        final_path=self.workspace/'finalization.json';final=util.read_json(final_path)
        final['evidence_files'][str(publication_path)]=util.sha256_file(publication_path)
        final['evidence_files'][str(remote_path)]=util.sha256_file(remote_path);util.write_json_atomic(final_path,final)
        raw_path=self.workspace/'gate-001.json';raw=util.read_json(raw_path)
        raw['evidence_files'].update({str(publication_path):util.sha256_file(publication_path),str(remote_path):util.sha256_file(remote_path),
            str(final_path):util.sha256_file(final_path)})
        phase=sharing.phase_view(self.plan,self.plan_path,self.number)
        extra={'main_plan':live_pilot.reference(self.plan_path),'child_phase':live_pilot.reference(self.phase_path),
            'finalization':live_pilot.reference(final_path),'public_review':live_pilot.reference(self.review)}
        gate={**raw,**extra,'gate_kind':sharing.GATE_KIND,'quality_acceptance':False,'source_repo':str(self.repo),
            'pair_uuid':phase['pair_uuid'],'task_revision':readiness.REVISION,'source_commit':self.plan['source_commit'],
            'package_sha256':final['package_sha256'],'original_inventory':final['original_inventory'],
            'evidence_files':{**raw['evidence_files'],**{v['path']:v['sha256'] for v in extra.values()}}}
        return gate,pair_execution.state(self.batch/'_control/pair-journal.jsonl')

    def rebound(self,gate,path,value):
        """Keep all file references valid while changing the semantic control."""
        result=copy.deepcopy(gate);path=Path(path);util.write_json_atomic(path,value)
        result['evidence_files'][str(path)]=util.sha256_file(path)
        final_path=Path(result['finalization']['path']);final=util.read_json(final_path)
        if str(path) in final['evidence_files']:
            final['evidence_files'][str(path)]=util.sha256_file(path);util.write_json_atomic(final_path,final)
        result['finalization']=live_pilot.reference(final_path)
        result['evidence_files'][str(final_path)]=util.sha256_file(final_path)
        return result

    def test_production_shaped_context_revised_request_spec_readme_and_no_old_kind_mask(self):
        bundle,batch,state,pair,bindings=sharing.pair_context(self.repo,self.plan_path,self.number)
        self.assertEqual(bundle['kind'],readiness.KIND);self.assertEqual(bundle['cohort'],self.phase['cohort'])
        self.assertTrue(all('phase_sha256' not in b for b in state['dispatch'].values()))
        self.assertTrue(all(b['phase_sha256']==util.sha256_file(self.phase_path) for b in bindings))
        self.assertEqual(sharing.pair_uuid(self.plan,self.number),sharing.pair_uuid(copy.deepcopy(self.plan),self.number))
        sharing.stage(self.repo,self.plan_path,self.number,self.workspace)
        study=util.read_json(self.workspace/'public/STUDY.json');self.assertEqual(study['kind'],readiness.KIND)
        self.assertEqual(study['settings'],self.plan['settings']);self.assertEqual(study['bounds'],self.plan['bounds'])
        self.assertEqual(study['plan_role'],'administrative_baseline_design_not_execution_authority')
        ledger=profiles.task_profile(self.repo,self.pair['task'],readiness.REVISION)
        family=bundle['plan']['task_hierarchy'][self.pair['task']]['family']
        self.assertEqual((self.workspace/'public/research/tasks'/family/'public-request.txt').read_text(encoding='utf8'),ledger['migration_request'])
        self.assertEqual(util.sha256_file(self.workspace/'public'/ledger['evaluation']['spec_path']),ledger['evaluation']['spec_sha256'])
        readme=(self.workspace/'public/README.md').read_text(encoding='utf8')
        self.assertIn('source_info_repaired_v6_main',readme);self.assertIn('deepseek-v4.1-flash',readme)
        self.assertNotIn('original pairs 6',readme);catalog_share.verify_public(self.workspace/'public',exact=True)

    def test_local_real_byte_pipeline_with_injected_transport_never_creates_main_gate(self):
        self.injected_pipeline()

    def test_main_context_rejects_foreign_child_phase_revision_and_missing_stops(self):
        bundle,batch,current,pair,bindings=sharing.pair_context(self.repo,self.plan_path,self.number)
        rid=pair['cases'][0]['run_id'];condition=self.batch/rid/'condition.json';original=condition.read_bytes()
        value=util.read_json(condition);value['task_profile_revision']='foreign';util.write_json_atomic(condition,value)
        with self.assertRaises(ValueError):sharing.pair_context(self.repo,self.plan_path,self.number)
        condition.write_bytes(original)
        malformed=copy.deepcopy(current);malformed['implementations'][rid]['receipt']['stop_confirmed']=False
        with patch.object(pair_execution,'state',return_value=malformed):
            with self.assertRaises(ValueError):sharing.pair_context(self.repo,self.plan_path,self.number)
        phase=util.read_json(self.phase_path);phase['cohort']='foreign';util.write_json_atomic(self.phase_path,phase)
        with self.assertRaises(ValueError):sharing.pair_context(self.repo,self.plan_path,self.number)

    def test_saved_receipt_validator_and_new_pair_hook_positive_is_finite_fixture_only(self):
        gate,state=self.synthetic_valid_gate()
        self.assertTrue(sharing.validate_gate(gate,state,self.number))
        self.assertTrue(pair_execution._validate_gate(gate,state,self.number))
        self.assertEqual(state['gates'],{}) # Validation is pure and never adopts the synthetic control.

    def test_gate_semantic_negatives_even_when_reference_hashes_updated(self):
        gate,state=self.synthetic_valid_gate()
        for key,bad in [('pair_uuid','f'*32),('source_commit','b'*40),('task_revision','old'),('plan_sha256','f'*64),
                ('phase_sha256','f'*64),('cohort','foreign'),('quality_acceptance',True),('package_sha256','f'*64)]:
            mutant=copy.deepcopy(gate);mutant[key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):sharing.validate_gate(mutant,state,self.number)
        for field in ('run_instances','original_inventory'):
            mutant=copy.deepcopy(gate);mutant[field].pop(next(iter(mutant[field])))
            with self.subTest(key=field),self.assertRaises(ValueError):sharing.validate_gate(mutant,state,self.number)
        remote_path=Path(util.read_json(gate['publication_receipt'])['actual_remote_readback']['path']);remote=util.read_json(remote_path)
        for marker in ('commit','tag','digest','url','extra'):
            value=copy.deepcopy(remote)
            if marker=='commit':value['tag_commit']='b'*40
            elif marker=='tag':value['tag_name']='old-v5-tag'
            elif marker=='digest':value['assets'][0]['digest']='sha256:'+'f'*64
            elif marker=='url':value['assets'][0]['browser_download_url']='https://other.invalid/package.zip'
            else:value['assets'].append(copy.deepcopy(value['assets'][0]))
            mutant=self.rebound(gate,remote_path,value);pubpath=Path(gate['publication_receipt']);pub=util.read_json(pubpath)
            pub['actual_remote_readback']=live_pilot.reference(remote_path);util.write_json_atomic(pubpath,pub)
            mutant=self.rebound(mutant,pubpath,pub)
            with self.subTest(remote=marker),self.assertRaises(ValueError):sharing.validate_gate(mutant,state,self.number)
        self.assertEqual(pair_execution.state(self.batch/'_control/pair-journal.jsonl')['gates'],{})

    def test_strict_receipt_booleans_reject_truthy_values_with_all_hashes_rebound(self):
        gate,state=self.synthetic_valid_gate();final_path=Path(gate['finalization']['path']);final_bytes=final_path.read_bytes()
        for receipt_name,field in [('publication_receipt','remote_assets_verified'),('roundtrip_receipt','hashes_match'),
                ('roundtrip_receipt','extraction_sockets_blocked'),('cleanup_receipt','cleanup_completed')]:
            path=Path(gate[receipt_name]);raw=path.read_bytes();base=util.read_json(path)
            for bad in (False,1,'false'):
                value=copy.deepcopy(base);value[field]=bad;mutant=self.rebound(gate,path,value)
                with self.subTest(field=field,bad=bad),self.assertRaisesRegex(ValueError,'Strict actual'):
                    sharing.validate_gate(mutant,state,self.number)
                path.write_bytes(raw);final_path.write_bytes(final_bytes)
        self.assertTrue(sharing.validate_gate(gate,state,self.number))

    def test_restore_cleanup_review_and_original_tamper_are_rejected(self):
        gate,state=self.synthetic_valid_gate();final_path=Path(gate['finalization']['path']);final_bytes=final_path.read_bytes()
        for marker in ('foreign-restore','parts','metadata','cleanup-targets','cleanup-original','extraction','review','original'):
            mutant=copy.deepcopy(gate)
            if marker in ('foreign-restore','parts','metadata'):
                path=Path(gate['roundtrip_receipt']);raw=path.read_bytes();value=util.read_json(path)
                if marker=='foreign-restore':value['workspace']=str(self.root/'foreign')
                elif marker=='parts':value['part_hashes'][0]['sha256']='f'*64
                else:value['metadata_hashes'].pop('scan.json')
                mutant=self.rebound(gate,path,value)
            elif marker.startswith('cleanup'):
                path=Path(gate['cleanup_receipt']);raw=path.read_bytes();value=util.read_json(path)
                if marker=='cleanup-targets':value['targets']=[str(self.root/'original')]
                else:value['original_runs_deleted']=True
                mutant=self.rebound(gate,path,value)
            elif marker=='extraction':
                path=self.workspace/'before-upload-extraction.json';raw=path.read_bytes();path.write_bytes(b'changed extraction\n')
                final=util.read_json(final_path);final['evidence_files'][str(path)]=util.sha256_file(path);util.write_json_atomic(final_path,final)
                mutant['evidence_files'][str(path)]=util.sha256_file(path);mutant['finalization']=live_pilot.reference(final_path)
                mutant['evidence_files'][str(final_path)]=util.sha256_file(final_path)
            elif marker=='review':
                path=self.review;raw=path.read_bytes();value=util.read_json(path);value['publication_approved']='false'
                util.write_json_atomic(path,value);mutant['public_review']=live_pilot.reference(path);mutant['evidence_files'][str(path)]=util.sha256_file(path)
            else:
                path=self.batch/self.pair['cases'][0]['run_id']/'frozen/artifact.txt';raw=path.read_bytes();path.write_bytes(b'changed original\n')
            with self.subTest(marker=marker),self.assertRaises(ValueError):sharing.validate_gate(mutant,state,self.number)
            path.write_bytes(raw);final_path.write_bytes(final_bytes)
        self.assertTrue(sharing.validate_gate(gate,state,self.number))

    def test_unknown_legacy_kind_and_main_without_phase_rejected(self):
        bundle,batch,state,pair,bindings=sharing.pair_context(self.repo,self.plan_path,self.number)
        with self.assertRaises(ValueError):next_phase_sharing.release_prefix(self.plan_path,bundle)
        with self.assertRaises(ValueError):next_phase_sharing.release_prefix(self.plan_path,{**bundle,'kind':'unknown'})


if __name__=='__main__':
    import unittest
    unittest.main()
