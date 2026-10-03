"""Two predeclared identity negatives beside a new static-SQLite positive."""
import argparse
import copy
from pathlib import Path
import shutil
import sys
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--positive',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); repo=args.repo.resolve(); out=args.out.resolve()
    sys.path.insert(0,str(repo/'outer'))
    from harness import aggregate, browser_cart, browser_cleanup, evaluate, run, util
    positive=util.read_json(args.positive)
    assert positive['matched'] and len(positive['cases'])==1
    case=positive['cases'][0]
    source_root=args.positive.resolve().parent/'runs'/case['run_id']
    condition=util.read_json(source_root/'condition.json')
    assert condition['collection_policy']=='workspace-static-db-v2'
    protected=util.tree_hashes(browser_cleanup._local_path(source_root))
    fixture_hashes=util.tree_hashes(args.fixture.resolve())
    out.mkdir(parents=True,exist_ok=False)
    expected={'database_byte_change':{'state':'rejected_mismatch','evaluator_exit_code':None,'adopted':False},
              'baseline_spec_mismatch':{'exit_code':2,'quality':None,'identity_fault':True}}
    receipt={'scope':'Two fixed new independent-fixture identity controls; no model, historical Run or repair',
             'model_calls':0,'human_review':'not_run','expected':expected,
             'positive_receipt_sha256':util.sha256_file(args.positive),
             'fixture_files':fixture_hashes,'cases':[]}
    util.write_new_json(out/'intent.json',receipt)
    runs=out/'runs'
    control_condition=copy.deepcopy(condition)
    control_condition['condition_id']='IDNEG'
    manifest=run.create_run(repo,runs,condition['task_id'],'IDNEG',1,{},resolved_condition=control_condition)
    root=runs/manifest['run_id']
    shutil.copytree(source_root/'evaluation-assets',root/'evaluation-assets')
    shutil.copytree(args.fixture.resolve(),root/'workspace')
    util.write_new_json(root/'profiles/control.json',{'scope':'Static database byte alteration after independent collection','model_called':False})
    util.write_new_json(root/'context.json',{'technical_control':True,'model_called':False})
    manifest.update(run_instance_id=uuid.uuid4().hex,profile_files=util.tree_hashes(root/'profiles'),
        assets_sha256=util.tree_hashes(root/'evaluation-assets'),input_files=util.tree_hashes(root/'inputs'),
        context_sha256=util.sha256_file(root/'context.json'),synthetic=True,model_called=False,
        started_at=run.now(),ended_at=run.now(),stop_confirmed=True,
        stop_method='fixed_independent_identity_control',end_reason='completed')
    run.save_manifest(runs,manifest['run_id'],manifest)
    run.collect_run(runs,manifest['run_id'])
    snapshot=run.read_snapshot(root)
    target=root/'frozen/MusicStore.Continuity/Data/initial-store.sqlite'
    assert target.is_file() and util.sha256_file(target)==util.sha256_file(args.fixture/'MusicStore.Continuity/Data/initial-store.sqlite')
    before=util.sha256_file(target)
    data=bytearray(target.read_bytes()); data[100]^=1; target.write_bytes(data)
    changed=util.sha256_file(target)
    assert changed!=before and util.artifact_hash(root/'frozen')!=snapshot['artifact_sha256']
    record=evaluate.score_run(repo,runs,manifest['run_id'])
    actual={'state':record['scoring_state'],'evaluator_exit_code':record['evaluator_exit_code'],'adopted':record['adopted']}
    assert actual==expected['database_byte_change'] and any(m['check']=='artifact_sha256' for m in record['mismatches'])
    receipt['cases'].append({'name':'static-database-byte-alteration','expected':expected['database_byte_change'],
        'actual':actual,'matched':True,'record':record,'snapshot_sha256':util.sha256_file(root/'snapshot.json'),
        'static_database_original_sha256':before,'static_database_changed_sha256':changed})

    # A new copied calibration baseline is the deliberate fault control. The
    # original positive baseline, frozen submission and browser evidence stay intact.
    positive_directory=source_root/case['record']['directory']
    baseline=out/'spec-mismatch-baseline'
    shutil.copytree(browser_cleanup._local_path(positive_directory/'http-only'),baseline)
    value=util.read_json(baseline/'evaluation.json'); value['specSha256']='0'*64
    util.write_json_atomic(baseline/'evaluation.json',value)
    composed=out/'spec-mismatch-composition'; composed.mkdir()
    code=browser_cart.compose_evaluation(condition,source_root/'frozen',baseline,
         source_root/'evaluation-assets',composed,case['record']['run_id']+'-spec-negative',1)
    output=util.read_json(composed/'evaluation.json')
    identity_fault=any('Baseline identity' in str(f) for f in output.get('evaluatorFaults',[]))
    actual={'exit_code':code,'quality':output.get('quality'),'identity_fault':identity_fault}
    assert actual==expected['baseline_spec_mismatch']
    # The historical SDK rejects this baseline before normal manifest emission.
    # Bind the actually dispatched DLL through the composition intent instead;
    # absence of a success manifest cannot be treated as an observed pass.
    intent=util.read_json(composed/'composition-intent.json')
    assert intent['evaluator_sha256']==condition['evaluation']['evaluator_sha256']
    assert output['artifactSha256']==case['artifact_sha256']
    assert browser_cleanup.latest(composed)['confirmed']
    receipt['cases'].append({'name':'bound-static-baseline-spec-mismatch','expected':expected['baseline_spec_mismatch'],
        'actual':actual,'matched':True,'output_sha256':util.sha256_file(composed/'evaluation.json'),
        'composition_intent_sha256':util.sha256_file(composed/'composition-intent.json'),
        'success_manifest_emitted':(composed/'evaluator-manifest.json').is_file(),
        'evaluator_sha256':intent['evaluator_sha256'],'artifact_sha256':output['artifactSha256'],
        'baseline_sha256':util.sha256_file(baseline/'evaluation.json'),'cleanup':browser_cleanup.latest(composed)})
    receipt['positive_originals_unchanged']=util.tree_hashes(browser_cleanup._local_path(source_root))==protected
    receipt['fixture_unchanged']=util.tree_hashes(args.fixture.resolve())==fixture_hashes
    receipt['matched']=all(c['matched'] for c in receipt['cases']) and receipt['positive_originals_unchanged'] and receipt['fixture_unchanged']
    util.write_new_json(out/'controls-receipt.json',receipt)
    print(str(out/'controls-receipt.json')+' matched='+str(receipt['matched']))
    return 0 if receipt['matched'] else 1


if __name__=='__main__':raise SystemExit(main())
