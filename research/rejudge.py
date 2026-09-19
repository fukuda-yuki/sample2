"""Compare R-029 on frozen artifacts and save isolated correction evaluations.

No Run manifest, original evaluation, condition, or frozen bundle is rewritten.
Only changed judgements receive a full 29-requirement correction evaluation.
"""
import argparse
import json
from pathlib import Path
import shutil

from outer.harness import evaluate, profiles, runtime, util, preserve
from research.correction_inventory import write_new
from research.validate import digest, read, safe_path


def scan(tool, artifact, assembly, image=None):
    if image:
        result = runtime.docker('run','--rm','--network','none',*runtime.sandbox_args(),
            *runtime.mount(Path(tool).parent,'/scan',True),*runtime.mount(artifact,'/artifact',True),
            *runtime.mount(Path(assembly).parent,'/assembly',True),image,'dotnet','/scan/'+Path(tool).name,
            '--scan','/artifact','--assembly','/assembly/'+Path(assembly).name)
    else:
        result = runtime.command(['dotnet', str(tool), '--scan', str(artifact), '--assembly', str(assembly)])
    value = json.loads(result.stdout)
    value['judgement'] = 'error' if value['unresolved'] else 'fail' if value['references'] else 'pass'
    return value


def rejudge(root, entry, bundle, lock, out):
    run_root = safe_path(root, entry['root'])
    condition = profiles.validate_run(preserve.native_path(run_root))
    snapshot = read(run_root/'snapshot.json')
    original = evaluate.last_scoring(preserve.native_path(run_root))
    frozen = run_root/'frozen'
    artifact_hash = util.artifact_hash(preserve.native_path(frozen))
    if artifact_hash != snapshot['artifact_sha256'] or artifact_hash != original['artifact_sha256_outer']:
        raise ValueError('Frozen artifact hash mismatch')
    if util.tree_hashes(preserve.native_path(bundle)) != lock['evaluator_files']:
        raise ValueError('Correction evaluator bundle differs from pinned build')
    out.mkdir(parents=True)
    assets = out/'assets'; assets.mkdir()
    shutil.copytree(bundle, assets/'evaluator')
    for name in ('requirements.json','catalog.json'):
        shutil.copy2(run_root/'evaluation-assets'/name, assets/name)
    spec_hash = digest(assets/'requirements.json')
    if spec_hash != condition['evaluation']['spec_sha256'] or spec_hash != original['spec_sha256']:
        raise ValueError('Correction must use the original requirements')
    sequence = max(evaluate.used_sequences(run_root), default=0) + 1
    work, result_dir = out/'work', out/'result'
    work.mkdir(); result_dir.mkdir()
    # Keep the original image/SDK/package cache. The corrected executable is an
    # explicit read-only mounted bundle; the ordinary rescore guard stays intact.
    container, command = runtime.scoring_command(condition, frozen, result_dir, work, assets,
        condition['evaluation']['evaluation_version'], sequence)
    intent = {'run_id': entry['run_id'], 'run_instance_id': entry['run_instance_id'], 'cohort':entry['cohort'],
        'original_evaluation_id':original['evaluation_id'], 'original_evaluation_directory':original['directory'],
        'original_evaluator_sha256':original['evaluator_sha256'], 'corrected_evaluator_sha256':lock['evaluator_sha256'],
        'corrected_evaluator_build':lock['evaluator_build'], 'artifact_sha256':artifact_hash,
        'spec_sha256':spec_hash, 'evaluation_version':condition['evaluation']['evaluation_version'],
        'sequence':sequence, 'original_runtime_image':condition['runtime_lock']['images']['evaluator'],
        'reason':'R-029 solution project references replace filename-only rejection',
        'model_called':False, 'originals_modified':False, 'command':command}
    write_new(out/'intent.json', intent)
    try:
        process = runtime.command(command, timeout=evaluate.SCORING_TIMEOUT_SECONDS, check=False)
        (out/'stdout.log').write_text(process.stdout, encoding='utf-8')
        (out/'stderr.log').write_text(process.stderr, encoding='utf-8')
    finally:
        runtime.docker('rm','-f',container,check=False)
    output = read(result_dir/'evaluation.json')
    mismatches = evaluate.check_mismatches(output, condition, intent['evaluation_version'], frozen,
        artifact_hash, assets/'requirements.json', spec_hash)
    reported = read(result_dir/'evaluator-manifest.json')['evaluatorSha256']
    if reported != lock['evaluator_sha256']: mismatches.append({'check':'corrected_evaluator_sha256'})
    if util.artifact_hash(preserve.native_path(frozen)) != artifact_hash: mismatches.append({'check':'artifact_changed_during_correction'})
    original_output = read(run_root/original['directory']/'evaluation.json')
    def failed(value): return [r['id'] for r in value['requirements'] if r['judgement']=='fail']
    receipt = {**intent, 'pass':not mismatches and process.returncode==0, 'mismatches':mismatches,
        'exit_code':process.returncode, 'corrected_evaluation_id':output['evaluationId'],
        'original_quality':original['quality'], 'corrected_quality':output['quality'],
        'original_verdict':original['verdict'], 'corrected_verdict':output['verdict'],
        'original_failed_requirements':failed(original_output), 'corrected_failed_requirements':failed(output)}
    write_new(out/'correction.json', receipt)
    if not receipt['pass']: raise RuntimeError('Correction evaluation failed; inspect retained receipt')
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--runtime-lock',type=Path,required=True)
    p.add_argument('--scan-tool',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--scan-only',action='store_true')
    p.add_argument('--scan-in-docker',action='store_true',help='Use the saved evaluator image; no host .NET runtime needed')
    a=p.parse_args()
    a.root=a.root.resolve();a.out=a.out.resolve()
    if a.out.exists(): raise SystemExit('Correction output already exists')
    a.out.mkdir(parents=True)
    inv, lock = read(a.inventory), read(a.runtime_lock)
    if util.tree_hashes(preserve.native_path(a.bundle)) != lock['evaluator_files']: raise ValueError('Unpinned corrected bundle')
    rows, corrections = [], []
    for entry in inv['runs']:
        run_root=safe_path(a.root,entry['root'])
        if read(run_root/'manifest.json').get('model_called') is not True: continue
        original = evaluate.last_scoring(preserve.native_path(run_root))
        scan_image = read(run_root/'condition.json')['runtime_lock']['images']['evaluator'] if a.scan_in_docker else None
        old = scan(a.scan_tool,run_root/'frozen',run_root/'evaluation-assets/evaluator/MusicStore.Evaluator.dll',scan_image)
        new = scan(a.scan_tool,run_root/'frozen',a.bundle/'MusicStore.Evaluator.dll',scan_image)
        row = {'run_id':entry['run_id'],'run_instance_id':entry['run_instance_id'],'cohort':entry['cohort'],
            'old':old,'new':new,'changed':old['judgement']!=new['judgement'],'original_evaluation_id':original['evaluation_id']}
        rows.append(row)
        print(entry['run_instance_id'] + ': ' + old['judgement'] + ' -> ' + new['judgement'],flush=True)
        if row['changed'] and not a.scan_only:
            corrections.append(rejudge(a.root,entry,a.bundle,lock,a.out/entry['run_instance_id']))
    write_new(a.out/'summary.json', {'scanned_artifacts':len(rows), 'changed_artifacts':sum(r['changed'] for r in rows),
        'scan_tool_sha256':digest(a.scan_tool),'rows':rows,'corrections':corrections,
        'scan_only':a.scan_only,'scan_in_docker':a.scan_in_docker,'model_called':False,'originals_modified':False})


if __name__=='__main__':
    main()
