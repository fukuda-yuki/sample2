"""Finite calibration through the ordinary isolated score_run chain; no model calls.

Cases and independent expectations are fixed in a JSON manifest before invocation.
Outputs are exclusive and historical artifacts are never reused as output paths.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--task-assets', type=Path, required=True)
    parser.add_argument('--evaluator-bundle', type=Path, required=True)
    parser.add_argument('--runtime-lock', type=Path, required=True)
    parser.add_argument('--browser-pin', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    sys.path.insert(0, str(repo/'outer'))
    from harness import aggregate, evaluate, run, util, browser_cleanup
    out.mkdir(parents=True, exist_ok=False)
    cases = util.read_json(args.cases)
    bundle = args.evaluator_bundle.resolve()
    evaluator_hash = util.sha256_file(bundle/'MusicStore.Evaluator.dll')
    pin = util.read_json(args.browser_pin)
    environment = pin['environment']
    for key, value in environment.items(): os.environ[key] = value
    node = Path(pin['node_path'])
    browser = Path(environment['SAMPLE2_BROWSER_EXECUTABLE'])
    if util.sha256_file(node) != pin['node_sha256'] or util.sha256_file(browser) != pin['browser_sha256']:
        raise RuntimeError('Current node/browser differ from declared calibration environment')
    os.environ['SAMPLE2_NODE'] = str(node)
    source_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    clean = not bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip())
    if not clean: raise RuntimeError('Commit calibration sources before freezing the executable receipt')
    lock = util.read_json(args.runtime_lock)
    runs = out/'runs'
    receipt = {'schema_version':1,'scope':'technical evaluator calibration; no research/model runs',
        'source_commit':source_commit,'evaluator_sha256':evaluator_hash,
        'evaluator_files':util.tree_hashes(bundle),'runtime_images':lock['images'],
        'browser_pin_sha256':util.sha256_file(args.browser_pin),
        'case_manifest_sha256':util.sha256_file(args.cases),
        'chain_files':{str(p.relative_to(repo)).replace('\\','/'):util.sha256_file(p) for p in
            [repo/'outer/harness/evaluate.py',repo/'outer/harness/browser_cart.py',
             repo/'outer/harness/browser_cleanup.py',repo/'outer/harness/aggregate.py',
             repo/'inner/browser/cart-review.cjs']},'human_review':'not_run','cases':[]}
    util.write_new_json(out/'predeclared-cases.json', cases)
    for index, case in enumerate(cases, 1):
        variant = case['variant']
        task = 'MS1-CONT-' + variant
        spec = repo/f'inner/spec/requirements-cont-{variant}-1.3.0.json'
        task_assets = args.task_assets.resolve()/variant
        condition = {'schema_version':2,'task_id':task,'task_title':task,
            'condition_id':'CAL','agent':None,'input_policy':{'allowlist':[],'denied':[]},
            'evaluation':{'evaluation_version':'1.3.0','assembly':'MusicStore.Evaluator.dll',
                'spec_path':'evaluation-assets/requirements.json','catalog_path':'evaluation-assets/catalog.json',
                'spec_sha256':util.sha256_file(spec),'evaluator_sha256':evaluator_hash,
                'evaluator_build':{'source_path':'inner/evaluator/MusicStore.Evaluator',
                    'source_commit':source_commit,'command':'prebuilt immutable calibration bundle',
                    'sdk_version':lock['versions']['dotnet'],'sha256_origin':str(bundle),'clean_worktree':clean}},
            'runtime_lock':copy.deepcopy(lock)}
        manifest = run.create_run(repo,runs,task,'CAL',index,{},resolved_condition=condition)
        root = runs/manifest['run_id']
        assets = root/'evaluation-assets'
        shutil.copytree(bundle,assets/'evaluator')
        shutil.copyfile(spec,assets/'requirements.json')
        for name in ('catalog.json','initial-store.sqlite','migration-oracle.json'):
            shutil.copyfile(task_assets/name,assets/name)
        util.write_new_json(root/'profiles/calibration.json',{'case':case,'model_called':False})
        util.write_new_json(root/'context.json',{'technical_case':case['name'],'model_called':False})
        shutil.copytree(Path(case['artifact_path']),root/'workspace',ignore=shutil.ignore_patterns('bin','obj','.git'))
        manifest.update(run_instance_id=uuid.uuid4().hex,profile_files=util.tree_hashes(root/'profiles'),
            assets_sha256=util.tree_hashes(assets),input_files=util.tree_hashes(root/'inputs'),
            context_sha256=util.sha256_file(root/'context.json'),synthetic=True,model_called=False,
            started_at=run.now(),ended_at=run.now(),stop_confirmed=True,
            stop_method='calibration_fixed_fixture',end_reason='completed')
        run.save_manifest(runs,manifest['run_id'],manifest)
        run.collect_run(runs,manifest['run_id'])
        fault = case.get('fault')
        original_node = os.environ['SAMPLE2_NODE']
        if fault == 'collector_unavailable': os.environ['SAMPLE2_NODE'] = str(out/'absent-node.exe')
        original_cleanup = browser_cleanup.cleanup
        if fault == 'cleanup_receipt_failure':
            def cleanup(*a,**kw):
                observed = original_cleanup(*a,**kw)
                # Actual owned cleanup happens first, then inject the declared receipt fault.
                return {**observed,'confirmed':False,'status':'injected_cleanup_receipt_failure'}
            browser_cleanup.cleanup = cleanup
        try:
            record = evaluate.score_run(repo,runs,manifest['run_id'])
        finally:
            os.environ['SAMPLE2_NODE'] = original_node
            browser_cleanup.cleanup = original_cleanup
        row = aggregate.row_for(runs,manifest['run_id'])
        output = util.read_json(root/record['directory']/'evaluation.json')
        actual = {'verdict':record.get('verdict'),'scoring_state':record['scoring_state'],
            'operation_status':record.get('operation_status'),'critical_failed':output.get('criticalFailed'),
            'failed_requirements':sorted(r['id'] for r in output.get('requirements',[]) if r['judgement']=='fail'),
            'quality':record.get('quality'),'aggregate_verdict':row.get('verdict')}
        failures = [key for key,value in case['expected'].items() if actual.get(key) != value]
        saved = {'name':case['name'],'run_id':manifest['run_id'],'variant':variant,
            'expected':case['expected'],'actual':actual,'matched':not failures,'mismatch_keys':failures,
            'artifact_sha256':run.read_snapshot(root)['artifact_sha256'],
            'spec_sha256':util.sha256_file(spec),'asset_files':util.tree_hashes(assets),
            'record':record,'aggregate':row}
        receipt['cases'].append(saved)
        util.write_new_json(out/(case['name']+'.json'),saved)
        print(case['name']+': '+json.dumps(actual)+' matched='+str(not failures),flush=True)
    receipt['matched'] = all(c['matched'] for c in receipt['cases'])
    util.write_new_json(out/'calibration-receipt.json',receipt)
    return 0 if receipt['matched'] else 1


if __name__ == '__main__': raise SystemExit(main())
