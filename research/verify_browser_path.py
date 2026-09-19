"""Exercise score_run -> real browser -> aggregate on disposable saved-artifact copies.

This does not dispatch any implementation/model Run. Explicit instance IDs and
expected verdicts are validation inputs, never branches in the evaluator.
"""
import argparse
from pathlib import Path
import shutil

from outer.harness import aggregate, evaluate, util
from research.validate import read


def verify(root, inventory, bundle, out, cases):
    root, bundle, out = map(lambda p: Path(p).resolve(), (root, bundle, out))
    if out.exists(): raise FileExistsError(out)
    out.mkdir(parents=True)
    entries = {r['run_instance_id']: r for r in read(inventory)['runs']}
    reports = []
    for instance, expected in cases:
        entry = entries[instance]; source = root/entry['root']
        runs = out/instance; runs.mkdir()
        dest = runs/entry['run_id']; dest.mkdir()
        for name in ('frozen', 'inputs', 'profiles'):
            shutil.copytree(source/name, dest/name)
        for name in ('context.json', 'snapshot.json'):
            shutil.copy2(source/name, dest/name)
        assets = dest/'evaluation-assets'; assets.mkdir()
        for name in ('requirements.json', 'catalog.json'):
            shutil.copy2(source/'evaluation-assets'/name, assets/name)
        shutil.copytree(bundle, assets/'evaluator')
        condition, manifest = read(source/'condition.json'), read(source/'manifest.json')
        condition['evaluation']['evaluator_sha256'] = None  # development build, provenance below; no false clean-worktree claim
        condition['runtime_lock']['evaluator_files'] = util.tree_hashes(bundle)
        condition['runtime_lock']['evaluator_sha256'] = util.sha256_file(bundle/'MusicStore.Evaluator.dll')
        util.write_new_json(dest/'condition.json', condition)
        manifest.update(condition_sha256=util.sha256_file(dest/'condition.json'), assets_sha256=util.tree_hashes(assets),
                        synthetic=True, model_called=False, verification_only=True)
        util.write_new_json(dest/'manifest.json', manifest)
        util.write_new_json(dest/'verification-provenance.json', {'source_run': entry['root'], 'run_instance_id': instance,
                            'model_called': False, 'purpose': 'ordinary evaluator integration on a disposable copy',
                            'source_artifact_sha256': util.artifact_hash(source/'frozen'),
                            'evaluator_sha256': util.sha256_file(bundle/'MusicStore.Evaluator.dll')})
        record = evaluate.score_run(root, runs, entry['run_id'])
        row = aggregate.row_for(runs, entry['run_id'])
        report = {'instance': instance, 'run_id': entry['run_id'], 'expected_verdict': expected,
                  'actual_verdict': row['verdict'], 'quality': row['quality'], 'scoring_state': record['scoring_state'],
                  'adopted': record['adopted'], 'research_status': row['scoring']['research_status'],
                  'directory': str(dest/record['directory']), 'pass': record['adopted'] and row['verdict'] == expected,
                  'source_unchanged': util.artifact_hash(source/'frozen') == util.artifact_hash(dest/'frozen')}
        if expected == 'incomplete':
            report['pass'] = not record['adopted'] and row['quality'] is None and row['verdict'] is None
        report['complete_expectation'] = 'evaluator_fault' if expected == 'incomplete' else 'scored'
        report['pass'] = report['pass'] and record['scoring_state'] == report['complete_expectation']
        reports.append(report)
        util.write_new_json(runs/'verification.json', report)
        print(report, flush=True)
    util.write_new_json(out/'summary.json', {'cases': reports, 'pass': all(r['pass'] and r['source_unchanged'] for r in reports),
                        'model_called': False, 'human_review': 'not_run'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--case', action='append', required=True, help='Run instance ID:expected verdict')
    a = p.parse_args()
    verify(a.root, a.inventory, a.bundle, a.out, [s.split(':') for s in a.case])


if __name__ == '__main__': main()
