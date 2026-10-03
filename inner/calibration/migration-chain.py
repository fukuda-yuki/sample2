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
    parser.add_argument('--runtime-lock-dir', type=Path,
                        help='Select and bind the exact <task>/lock.json image for each case')
    parser.add_argument('--browser-pin', type=Path, required=True)
    parser.add_argument('--contract-root', type=Path,
                        help='Task owner checkout with public request/profiles for upstream authority binding')
    parser.add_argument('--education', action='store_true', help='Run the independent education-1.0.0 contract')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    sys.path.insert(0, str(repo/'outer'))
    from harness import aggregate, evaluate, run, util, browser_cleanup
    out.mkdir(parents=True, exist_ok=False)
    cases = util.read_json(args.cases)
    bundle = args.evaluator_bundle.resolve()
    assembly = 'Education.Evaluator.dll' if args.education else 'MusicStore.Evaluator.dll'
    evaluation_version = 'education-1.0.0' if args.education else '1.3.0'
    evaluator_hash = util.sha256_file(bundle/assembly)
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
    task_locks = {}
    if args.runtime_lock_dir:
        for variant in sorted({case['variant'] for case in cases}):
            task = ('CU1-ENR-' if args.education else 'MS1-CONT-') + variant
            path = args.runtime_lock_dir.resolve()/task/'lock.json'
            selected = util.read_json(path)
            if (selected['evaluator_files'] != util.tree_hashes(bundle)
                    or selected['evaluator_files'] != util.tree_hashes(path.parent/'evaluator')
                    or selected['evaluator_sha256'] != evaluator_hash):
                raise RuntimeError('Per-task runtime evaluator bundle differs: '+task)
            current = {p.name:util.sha256_file(p) for p in (repo/'outer/harness').glob('*.py')}
            if selected['controller_files'] != current:
                raise RuntimeError('Per-task runtime controller differs from calibration checkout: '+task)
            task_locks[task] = (path, selected)
    runs = out/'runs'
    receipt = {'schema_version':1,'scope':'technical evaluator calibration; no research/model runs',
        'source_commit':source_commit,'evaluator_sha256':evaluator_hash,
        'evaluator_files':util.tree_hashes(bundle),'runtime_images':lock['images'],
        'browser_pin_sha256':util.sha256_file(args.browser_pin),
        'case_manifest_sha256':util.sha256_file(args.cases),
        'scheduled_case_count':len(cases),
        'stop_rule':'Stop remaining cases on an unexpected evaluator or cleanup infrastructure fault; retain all receipts.',
        'chain_files':{str(p.relative_to(repo)).replace('\\','/'):util.sha256_file(p) for p in
            [repo/'outer/harness/evaluate.py',repo/'outer/harness/browser_cart.py',
             repo/'outer/harness/browser_cleanup.py',repo/'outer/harness/aggregate.py',
             repo/'inner/browser/cart-review.cjs']},'human_review':'not_run','cases':[]}
    receipt['evaluator_source_files'] = {p.relative_to(repo).as_posix():util.sha256_file(p)
        for p in (repo/('inner/evaluator/Education.Evaluator' if args.education else 'inner/evaluator/MusicStore.Evaluator')).glob('*')
        if p.suffix in ('.cs','.csproj')}
    receipt['controller_files'] = {p.relative_to(repo).as_posix():util.sha256_file(p)
        for p in (repo/'outer/harness').glob('*.py')}
    receipt['runtime_lock_sha256'] = util.sha256_file(args.runtime_lock)
    receipt['task_runtimes'] = {task:{'lock_sha256':util.sha256_file(path),
        'images':selected['images'], 'evaluator_sha256':selected['evaluator_sha256'],
        'evaluator_files':selected['evaluator_files'], 'evaluator_build':selected['evaluator_build']}
        for task,(path,selected) in task_locks.items()}
    receipt['calibration_driver_sha256'] = util.sha256_file(Path(__file__))
    for p in [repo/'outer/harness/browser_review.py',repo/'outer/harness/education_browser.py',
              repo/'inner/browser/education-review.cjs']:
        if p.is_file(): receipt['chain_files'][p.relative_to(repo).as_posix()] = util.sha256_file(p)
    shutil.copyfile(args.runtime_lock, out/'runtime-lock.json')
    for task,(path,selected) in task_locks.items():
        target = out/'task-runtime-locks'/task; target.mkdir(parents=True)
        shutil.copyfile(path,target/'lock.json')
    receipt['linked_contract_files'] = {}
    receipt['linked_contract_scope'] = 'Upstream authority/input binding; model serialization is separately validated by Issue #23.'
    if args.contract_root:
        contract_root = args.contract_root.resolve()
        relatives = ['research/tasks/music-store-continuity/public-request.txt',
            'research/tasks/music-store-continuity/variants.json',
            'research/tasks/candidate-register.json',
            'research/migration_tasks.py',
            'outer/profiles/tasks/MS1-CONT-A.json','outer/profiles/tasks/MS1-CONT-B.json']
        if args.education:
            relatives = ['research/tasks/contoso-enrollment/public-request.txt',
                'research/tasks/contoso-enrollment/source-pin.json', 'research/tasks/contoso-enrollment/variants.json',
                'research/tasks/candidate-register.json', 'research/education_tasks.py',
                'outer/profiles/tasks/CU1-ENR-C.json', 'outer/profiles/tasks/CU1-ENR-D.json']
        for relative in relatives:
            source = contract_root/relative
            if source.is_file():
                target = out/'linked-contract'/relative; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,target)
                receipt['linked_contract_files'][relative] = util.sha256_file(target)
    util.write_new_json(out/'calibration-intent.json',receipt)
    util.write_new_json(out/'predeclared-cases.json', cases)
    for index, case in enumerate(cases, 1):
        variant = case['variant']
        task = ('CU1-ENR-' if args.education else 'MS1-CONT-') + variant
        selected_lock_path, selected_lock = task_locks.get(task, (args.runtime_lock, lock))
        spec = repo/(f'inner/spec/requirements-cu-{variant}-education-1.0.0.json' if args.education else f'inner/spec/requirements-cont-{variant}-1.3.0.json')
        task_assets = args.task_assets.resolve()/variant
        condition = {'schema_version':2,'task_id':task,'task_title':task,
            'condition_id':'CAL','agent':None,'input_policy':{'allowlist':[],'denied':[]},
            'evaluation':{'evaluation_version':evaluation_version,'assembly':assembly,
                'migration_contract':{'initial_database':'initial-store.sqlite','oracle':'migration-oracle.json',
                                     **({'import_input':'legacy-school.sqlite'} if args.education else {})},
                'spec_path':'evaluation-assets/requirements.json','catalog_path':'evaluation-assets/catalog.json',
                'spec_sha256':util.sha256_file(spec),'evaluator_sha256':evaluator_hash,
                'evaluator_build':{'source_path':'inner/evaluator/'+assembly.removesuffix('.dll'),
                    'source_commit':source_commit,'command':'prebuilt immutable calibration bundle',
                    'sdk_version':selected_lock['versions']['dotnet'],'sha256_origin':str(bundle),'clean_worktree':clean}},
            'runtime_lock':copy.deepcopy(selected_lock)}
        if task_locks:
            condition['evaluation']['evaluator_build'] = copy.deepcopy(selected_lock['evaluator_build'])
        manifest = run.create_run(repo,runs,task,'CAL',index,{},resolved_condition=condition)
        root = runs/manifest['run_id']
        assets = root/'evaluation-assets'
        shutil.copytree(bundle,assets/'evaluator')
        shutil.copyfile(spec,assets/'requirements.json')
        for name in ('catalog.json','initial-store.sqlite','migration-oracle.json', *(['legacy-school.sqlite'] if args.education else [])):
            shutil.copyfile(task_assets/name,assets/name)
        util.write_new_json(root/'profiles/calibration.json',{'case':case,'model_called':False})
        util.write_new_json(root/'context.json',{'technical_case':case['name'],'model_called':False,
                                               'method':'explore','blocks':[]})
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
                injected = {**observed,'confirmed':False,'status':'injected_cleanup_receipt_failure',
                            'fault_injection':True,'actual_owned_cleanup_confirmed':observed['confirmed']}
                target = browser_cleanup._local_path(a[0])/'browser-cleanup-attempts'
                util.write_new_json(target/('injected-'+uuid.uuid4().hex+'-result.json'),injected)
                util.append_line(target/'index.jsonl',injected)
                return injected
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
            'runtime_lock_sha256':util.sha256_file(selected_lock_path), 'runtime_images':selected_lock['images'],
            'record':record,'aggregate':row}
        receipt['cases'].append(saved)
        util.write_new_json(out/(case['name']+'.json'),saved)
        print(case['name']+': '+json.dumps(actual)+' matched='+str(not failures),flush=True)
        if not fault and (record['scoring_state'] == 'evaluator_fault'
                          or record.get('operation_status') == 'cleanup_failed'):
            receipt['stop_reason'] = 'Unexpected infrastructure fault in ' + case['name']
            break
    receipt['matched'] = len(receipt['cases']) == len(cases) and all(c['matched'] for c in receipt['cases'])
    util.write_new_json(out/'calibration-receipt.json',receipt)
    return 0 if receipt['matched'] else 1


if __name__ == '__main__': raise SystemExit(main())
