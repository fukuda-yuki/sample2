"""Save an HTTP control and browser-evidence correction for the three PMO targets.

No model calls, new research Runs, original evaluations or frozen inputs change.
Consumes independently captured UI observations; this is not a browser runner.
Invoke with python -m research.pmo_scenario_correction.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
from outer.harness import evaluate, runtime
from research.pmo_scenario_evidence import REPO, IMAGE, read, save, sha, inventory, aggregate


def receipt(out, target):
    folder = out / target['condition']
    pairs = [('S2-01-quantity-two', 'S2-02-quantity-one'),
             ('S2-02-quantity-one', 'S2-03-quantity-zero')]
    if target['condition'] == 'preload':
        pairs[1] = ('S2-07-followup-one-before', 'S2-08-followup-zero-stale')
    elif target['condition'] == 'explained':
        pairs[1] = ('S2-08-B-quantity-one-before-click', 'S2-09-B-quantity-one-click-no-effect')
    removals = []
    def ref(label, suffix):
        name = label + suffix
        return {'path': name, 'sha256': sha(folder / name)}
    for check, (before, after) in zip(('C-015', 'C-016'), pairs):
        removals.append({'checkId': check, 'action': 'click-remove',
            'before': ref(before, '.browser.json'), 'after': ref(after, '.browser.json'),
            'beforeScreenshot': ref(before, '.png'), 'afterScreenshot': ref(after, '.png')})
    path = folder / 'browser-cart-receipt.json'
    save(path, {'schemaVersion': 1, 'actor': 'agent', 'runInstanceId': target['run_instance_id'],
        'artifactSha256': target['artifact_sha256'], 'specSha256': target['spec_sha256'], 'removals': removals})
    return path


def score(out, bundle, target, mode, sequence, browser_receipt):
    original = REPO / 'runs/exploration-20260919-ms1' / target['run_id']
    frozen = REPO / 'work/relocated-ms1-correction-v3' / original.relative_to(REPO) / 'frozen'
    condition = read(original / 'condition.json')
    assert condition['runtime_lock']['images']['evaluator'] == IMAGE
    assert aggregate(inventory(frozen)) == target['artifact_sha256']
    dest = out / 'correction' / target['condition'] / mode
    assets, work, result_dir = dest / 'assets', dest / 'work', dest / 'result'
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copytree(bundle, assets / 'evaluator')
    for name in ('requirements.json', 'catalog.json'):
        shutil.copy2(original / 'evaluation-assets' / name, assets / name)
    assert sha(assets / 'requirements.json') == target['spec_sha256']
    work.mkdir(); result_dir.mkdir()
    container, command = runtime.scoring_command(condition, frozen, result_dir, work, assets, '1.2.0', sequence)
    if mode == 'browser-corrected':
        index = command.index(IMAGE)
        command[index:index] = runtime.mount(browser_receipt.parent, '/browser', True)
        command += ['--browser-cart-evidence', '/browser/' + browser_receipt.name,
                    '--review-run-instance-id', target['run_instance_id']]
    intent = {'at': datetime.now(timezone.utc).isoformat(), 'run_id': target['run_id'],
        'run_instance_id': target['run_instance_id'], 'original_evaluation_id': target['evaluation_id'],
        'mode': mode, 'sequence': sequence, 'artifact_sha256': target['artifact_sha256'],
        'spec_sha256': target['spec_sha256'], 'evaluator_sha256': sha(bundle / 'MusicStore.Evaluator.dll'),
        'image': IMAGE, 'model_called': False, 'command': command, 'container': container,
        'bundle_files': inventory(bundle), 'browser_receipt_sha256': sha(browser_receipt)}
    save(dest / 'intent.json', intent)
    try:
        result = runtime.command(command, timeout=evaluate.SCORING_TIMEOUT_SECONDS, check=False)
        (dest / 'stdout.log').write_text(result.stdout, encoding='utf-8')
        (dest / 'stderr.log').write_text(result.stderr, encoding='utf-8')
        save(dest / 'container.json', runtime.inspect_container(container))
    finally:
        # Only this helper's fresh, uniquely named evaluator container is removed.
        runtime.docker('rm', '-f', container, check=False)
    value = read(result_dir / 'evaluation.json')
    mismatches = evaluate.check_mismatches(value, condition, '1.2.0', frozen,
        target['artifact_sha256'], assets / 'requirements.json', target['spec_sha256'])
    assert read(result_dir / 'evaluator-manifest.json')['evaluatorSha256'] == intent['evaluator_sha256']
    assert aggregate(inventory(frozen)) == target['artifact_sha256']
    expected_fails = [] if mode == 'http-control' or target['condition'] == 'explore' else ['R-014', 'R-015']
    failed = [r['id'] for r in value['requirements'] if r['judgement'] == 'fail']
    row = {'condition': target['condition'], 'run_instance_id': target['run_instance_id'], 'mode': mode,
        'evaluation_id': value['evaluationId'], 'quality': value['quality'], 'verdict': value['verdict'],
        'failed_requirements': failed, 'browser_cart_coverage': value['browserCartCoverage'],
        'exit_code': result.returncode, 'mismatches': mismatches,
        'impact_as_expected': failed == expected_fails and value['errorCount'] == 0 and value['blockedCount'] == 0,
        'path': str(dest.relative_to(out)).replace('\\', '/')}
    save(dest / 'comparison.json', row)
    if result.returncode or mismatches or not row['impact_as_expected']:
        raise RuntimeError('Correction/control failed; retained ' + str(dest))
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    a = p.parse_args()
    out, bundle = a.out.resolve(), a.bundle.resolve()
    lock = read(bundle.parent / 'result.json')
    assert lock['exit_code'] == 0 and inventory(bundle) == lock['bundle_files']
    rows = []
    for target in read(out / 'targets.json'):
        browser_receipt = receipt(out, target)
        for mode, sequence in [('http-control', 901), ('browser-corrected', 902)]:
            row = score(out, bundle, target, mode, sequence, browser_receipt)
            rows.append(row)
            print(row, flush=True)
    save(out / 'correction/summary.json', {'rows': rows, 'model_called': False,
        'human_review': 'not_run', 'agent_scenario_review': 'fail',
        'note': '901/902 are separate correction evaluation sequences, not new research Runs.'})


if __name__ == '__main__':
    main()
