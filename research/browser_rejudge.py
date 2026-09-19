"""Uniform saved-corpus browser correction using the ordinary research scorer.

Only C-015/C-016 run again. An existing R-029 correction is the baseline when
present; all other checks are inherited. Originals and usage are read only.
"""
import argparse
from collections import Counter
from pathlib import Path
import shutil

from outer.harness import browser_cart, evaluate, profiles, util
from research.correction_inventory import write_new
from research.validate import read, digest, safe_path


def target(root, entry, prior_root, prior):
    run = safe_path(root, entry['root'])
    manifest = read(run/'manifest.json')
    if manifest['run_instance_id'] != entry['run_instance_id'] or digest(run/'manifest.json') != entry['manifest_sha256']:
        raise ValueError('Inventory Run identity mismatch')
    if not manifest.get('model_called'):
        return run, None, None, None
    condition = profiles.validate_run(run)
    snapshot = read(run/'snapshot.json')
    scoring = evaluate.last_scoring(run)
    if util.artifact_hash(run/'frozen') != snapshot['artifact_sha256'] or scoring['artifact_sha256_outer'] != snapshot['artifact_sha256']:
        raise ValueError('Fixed artifact identity mismatch')
    baseline = run/scoring['directory']
    if entry['run_instance_id'] in prior:
        correction = prior[entry['run_instance_id']]
        if not correction['pass'] or correction['original_evaluation_id'] != scoring['evaluation_id']:
            raise ValueError('Prior correction does not bind to this acquisition')
        baseline = prior_root/entry['run_instance_id']/'result'
    # Relocation-safe path, derived from the preserved scoring sequence.
    published = run/'evaluation-work'/f"{scoring['sequence']:03d}"/'publish'
    # Bind the runnable bytes to the original archive without re-auditing usage.
    package_file = root/entry['archive']/'packages'/entry['package']['package_id']/'package.json'
    if digest(package_file) != entry['package']['sha256']:
        raise ValueError('Archived package receipt identity mismatch')
    package = read(package_file)
    prefix = f"evaluation-work/{scoring['sequence']:03d}/publish/"
    expected = {p[len(prefix):]: {k: v[k] for k in ('sha256', 'bytes')}
                for p, v in package['files'].items() if p.startswith(prefix)}
    if not expected or util.tree_hashes(published) != expected:
        raise ValueError('Published application differs from the archived target')
    return run, condition, baseline, published


def run_batch(root, inventory_path, prior_root, summary_path, bundle, out, only=None, observations=None):
    root, prior_root, bundle, out = map(lambda p: Path(p).resolve(), (root, prior_root, bundle, out))
    inventory, quality = read(inventory_path), read(summary_path)
    prior = {c['run_instance_id']: c for c in read(prior_root/'summary.json')['corrections']}
    quality_rows = {r['run_instance_id']: r for r in quality['rows']}
    entries = [e for e in inventory['runs'] if not only or e['run_instance_id'] in only]
    out.mkdir(parents=True, exist_ok=True)
    run_lock = {'inventory_sha256': digest(inventory_path), 'prior_correction_summary_sha256': digest(prior_root/'summary.json'),
                'prior_quality_summary_sha256': digest(summary_path), 'evaluator_files': util.tree_hashes(bundle),
                'collector_sha256': digest(root/'inner/browser/cart-review.cjs'),
                'runner_sha256': digest(root/'outer/harness/browser_cart.py'), 'selected_instances': [e['run_instance_id'] for e in entries]}
    if observations:
        observations = Path(observations).resolve()
        run_lock['observation_batch_lock_sha256'] = digest(observations/'lock.json')
    if (out/'lock.json').exists():
        if read(out/'lock.json') != run_lock: raise ValueError('Batch inputs changed; use a new output directory')
    else: write_new(out/'lock.json', run_lock)
    rows = []
    for entry in entries:
        instance = entry['run_instance_id']
        run, condition, baseline, published = target(root, entry, prior_root, prior)
        saved = quality_rows[instance]
        row = {k: saved[k] for k in ('cohort', 'condition', 'run_id', 'run_instance_id', 'calls', 'usage_complete',
                                     'input_tokens', 'output_tokens', 'total_tokens', 'original_quality', 'original_verdict')}
        row.update(root=entry['root'], r029_quality=saved['corrected_quality'], r029_verdict=saved['corrected_verdict'])
        if condition is None:
            row.update(browser_state='not_applicable_no_artifact', quality=None, verdict=None, changed_requirements=[],
                       evidence=None, scope='pre-model technical failure retained; no generated artifact')
            rows.append(row)
            continue
        dest = out/instance
        if not (dest/'result/evaluation.json').exists():
            if dest.exists(): raise ValueError('Incomplete attempt retained; inspect before using a new directory: ' + str(dest))
            dest.mkdir()
            assets = dest/'assets'; assets.mkdir()
            shutil.copytree(bundle, assets/'evaluator')
            for name in ('requirements.json', 'catalog.json'): shutil.copy2(run/'evaluation-assets'/name, assets/name)
            evidence_files = [run/'manifest.json', run/'snapshot.json', run/'condition.json', run/'usage/normalized.json',
                              baseline/'evaluation.json', baseline/'results.jsonl', run/'evaluations/index.jsonl']
            before = {str(p.relative_to(root)).replace('\\','/'): digest(p) for p in evidence_files if p.is_file()}
            frozen_before = util.tree_hashes(run/'frozen')
            write_new(dest/'preservation-before.json', {'files': before, 'frozen': frozen_before,
                       'raw_usage_access': 'not parsed; not mounted writable; existing archive and token records retained'})
            if observations:
                previous = observations/instance/'result'
                observed_intent = read(previous/'browser-intent.json')
                if (observed_intent['run_instance_id'] != instance
                        or observed_intent['artifact_sha256'] != util.artifact_hash(run/'frozen')
                        or observed_intent['spec_sha256'] != digest(assets/'requirements.json')
                        or observed_intent['published_files'] != util.tree_hashes(published)
                        or observed_intent['baseline_evaluation_sha256'] != digest(baseline/'evaluation.json')
                        or observed_intent['baseline_results_sha256'] != digest(baseline/'results.jsonl')):
                    raise ValueError('Reused browser observations are bound to another target or baseline')
                result = dest/'result'; result.mkdir()
                shutil.copytree(previous/'browser-cart', result/'browser-cart')
                write_new(result/'observation-source.json', {'directory': str(previous.relative_to(root)).replace('\\','/'),
                          'intent_sha256': digest(previous/'browser-intent.json'),
                          'receipt_sha256': digest(previous/'browser-cart/receipt.json'),
                          'reason': 'Same-origin application navigation is an observed outcome, not an identity fault'})
                code = browser_cart.compose_evaluation(condition, run/'frozen', baseline, assets, result, instance, 1002)
            else:
                code = browser_cart.complete_evaluation(root, condition, run/'frozen', baseline, published, assets, dest/'result', instance, 1001)
            after = {p: digest(root/p) for p in before}
            preservation = {'pass': before == after and frozen_before == util.tree_hashes(run/'frozen'),
                            'files_after': after, 'fixed_files': len(frozen_before), 'exit_code': code}
            write_new(dest/'preservation-after.json', preservation)
            if not preservation['pass']: raise ValueError('Preservation check failed')
        result_dir = dest/'result'
        output, base = read(result_dir/'evaluation.json'), read(baseline/'evaluation.json')
        if saved['corrected_quality'] != base['quality'] or saved['corrected_verdict'] != base['verdict']:
            raise ValueError('Prior quality summary disagrees with chosen baseline')
        complete = browser_cart.stored_coverage_complete(result_dir, instance,
            util.artifact_hash(run/'frozen'), digest(run/'evaluation-assets/requirements.json'))
        base_requirements = {r['id']: r['judgement'] for r in base['requirements']}
        changed = [r['id'] for r in output.get('requirements', []) if base_requirements.get(r['id']) != r['judgement']]
        if complete and not set(changed).issubset({'R-014','R-015'}): raise ValueError('Unrelated requirement changed')
        checks = {r['checkId']: r['judgement'] for r in util.read_lines(result_dir/'results.jsonl') if r['checkId'] in ('C-015','C-016')}
        row.update(browser_state='complete' if complete else 'evaluation_incomplete', quality=output['quality'] if complete else None,
                   verdict=output['verdict'] if complete else None, changed_requirements=changed, checks=checks,
                   evidence=str(result_dir.relative_to(root)).replace('\\','/'),
                   baseline=str(baseline.relative_to(root)).replace('\\','/'), baseline_evaluation_id=base['evaluationId'],
                   browser_evaluation_id=output['evaluationId'], evaluator_sha256=run_lock['evaluator_files']['MusicStore.Evaluator.dll']['sha256'],
                   artifact_sha256=output['artifactSha256'], spec_sha256=output['specSha256'])
        rows.append(row)
        print(f"{entry['cohort']}/{entry['run_id']}: {row['r029_quality']} {row['r029_verdict']} -> {row['quality']} {row['verdict']} {row['checks']}", flush=True)
    groups = []
    for cohort, condition in sorted({(r['cohort'], r['condition']) for r in rows}):
        rr = [r for r in rows if (r['cohort'], r['condition']) == (cohort, condition)]
        groups.append({'cohort': cohort, 'condition': condition, 'attempts': len(rr),
                       'artifacts': sum(r['browser_state'] != 'not_applicable_no_artifact' for r in rr),
                       'observed': sum(r['browser_state'] == 'complete' for r in rr),
                       'incomplete': sum(r['browser_state'] == 'evaluation_incomplete' for r in rr),
                       'no_artifact': sum(r['browser_state'] == 'not_applicable_no_artifact' for r in rr),
                       'acquisition_verdicts': dict(Counter(str(r['original_verdict']) for r in rr)),
                       'r029_verdicts': dict(Counter(str(r['r029_verdict']) for r in rr)),
                       'browser_verdicts': dict(Counter(str(r['verdict']) for r in rr)),
                       'pass_over_artifacts': sum(r['verdict']=='pass' for r in rr) / sum(r['browser_state']!='not_applicable_no_artifact' for r in rr)
                           if all(r['browser_state']!='evaluation_incomplete' for r in rr) else None})
    report = {'rows': rows, 'groups': groups, 'model_called': False, 'human_review': 'not_run',
              'scope': 'Only C-015/C-016 repeated; HTTP baseline and other 27 requirements inherited including R-029 correction',
              'review_selection_retained': quality['human_review_selection'], 'representatives_reselected': False,
              'artifacts_observed': sum(r['browser_state']=='complete' for r in rows),
              'incomplete': sum(r['browser_state']=='evaluation_incomplete' for r in rows),
              'no_artifact': sum(r['browser_state']=='not_applicable_no_artifact' for r in rows)}
    if not (out/'summary.json').exists(): write_new(out/'summary.json', report)
    elif read(out/'summary.json') != report: raise ValueError('Existing batch summary changed')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--prior-corrections', type=Path, required=True)
    p.add_argument('--prior-quality', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--only-instance', action='append')
    p.add_argument('--observations', type=Path, help='Reuse bound real captures for an evaluator-only correction; no new clicks')
    a = p.parse_args()
    run_batch(a.root, a.inventory, a.prior_corrections, a.prior_quality, a.bundle, a.out, a.only_instance, a.observations)


if __name__ == '__main__': main()
