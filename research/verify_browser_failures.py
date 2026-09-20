"""No-model regression through real score CLI, Chromium, composition and aggregate.

Mutations below create explicitly synthetic, disposable fixtures from a copied
saved artifact. Original Runs and uniform-v3 are never writable test targets.
Only infrastructure failures are injected into the harness; real app HTTP,
browser navigation/clicks, DOM captures and evaluator decisions are exercised.
"""
import argparse
from contextlib import redirect_stdout
import os
from pathlib import Path
import shutil
from unittest.mock import patch
import uuid

from outer.harness import aggregate, browser_cart, browser_cleanup, cli, evaluate, runtime, util

NORMAL = '94fe01fe7837446b9ae44a067b2a3512'
CASES = {
    'normal': (NORMAL, 'pass', 'scored'),
    'inert': (NORMAL, 'fail', 'scored'),
    'missing': (NORMAL, 'fail', 'scored'),
    'disabled': (NORMAL, 'fail', 'scored'),
    'quantity': (NORMAL, 'fail_critical', 'evaluation_incomplete'),
    'unsupported': (NORMAL, None, 'evaluation_incomplete'),
    'launch-failure': (NORMAL, None, 'evaluator_fault'),
    'missing-evidence': (NORMAL, None, 'evaluator_fault'),
    'http-fail-launch-failure': ('758bb8cbfdf04d3a98233f8e97f0fea6', 'fail', 'evaluator_fault'),
    'container-cleanup': (NORMAL, 'pass', 'scored'),
    'network-cleanup': (NORMAL, 'pass', 'scored'),
    'stale-total': (None, 'fail', 'scored'),
    'inert-saved': (None, 'fail', 'scored'),
}


def prepare(root, entry, bundle, runs, case):
    source = root/entry['root']
    dest = runs/entry['run_id']; dest.mkdir(parents=True)
    for name in ('frozen', 'inputs', 'profiles'):
        shutil.copytree(source/name, dest/name)
    for name in ('context.json', 'snapshot.json'):
        shutil.copy2(source/name, dest/name)
    assets = dest/'evaluation-assets'; assets.mkdir()
    for name in ('requirements.json', 'catalog.json'):
        shutil.copy2(source/'evaluation-assets'/name, assets/name)
    shutil.copytree(bundle, assets/'evaluator')
    condition, manifest = util.read_json(source/'condition.json'), util.read_json(source/'manifest.json')
    condition['evaluation']['evaluator_sha256'] = None
    condition['runtime_lock']['evaluator_files'] = util.tree_hashes(bundle)
    condition['runtime_lock']['evaluator_sha256'] = util.sha256_file(bundle/'MusicStore.Evaluator.dll')
    util.write_new_json(dest/'condition.json', condition)
    manifest.update(condition_sha256=util.sha256_file(dest/'condition.json'), assets_sha256=util.tree_hashes(assets),
                    synthetic=True, model_called=False, verification_only=True, run_instance_id=uuid.uuid4().hex)
    util.write_new_json(dest/'manifest.json', manifest)
    view = dest/'frozen/Views/ShoppingCart/Index.cshtml'
    if case in ('inert', 'missing', 'disabled', 'unsupported'):
        original = view.read_text(encoding='utf-8')
        link = '<a href="#" class="RemoveLink" data-id="@item.RecordId">Remove from cart</a>'
        replacement = {'missing': '', 'disabled': '<button disabled>Remove from cart</button>',
                       'unsupported': '<button class="MinusOne" data-id="@item.RecordId">Decrease quantity</button>'}.get(case, link)
        assert original.count(link) == 1
        value = original.replace(link, replacement)
        if case == 'inert':
            value = value[:value.index('<script type="text/javascript">')]
        if case == 'unsupported':
            value = value.replace("querySelectorAll('.RemoveLink')", "querySelectorAll('.MinusOne')")
        view.write_text(value, encoding='utf-8')
    if case == 'quantity':
        service = dest/'frozen/Services/CartService.cs'
        value = service.read_text(encoding='utf-8')
        assert value.count('existing.Count++;') == 1
        service.write_text(value.replace('existing.Count++;', 'existing.Count += 2;'), encoding='utf-8')
    snap = util.read_json(dest/'snapshot.json')
    snap.update(artifact_sha256=util.artifact_hash(dest/'frozen'), regression_fixture=case)
    util.write_json_atomic(dest/'snapshot.json', snap)
    util.write_new_json(dest/'regression-provenance.json', {
        'case': case, 'source': entry['root'], 'source_instance': entry['run_instance_id'],
        'source_artifact_sha256': util.artifact_hash(source/'frozen'), 'fixture_sha256': snap['artifact_sha256'],
        'model_called': False, 'human_review': 'not_run', 'synthetic_mutation': case in ('inert','missing','disabled','quantity','unsupported')})
    return dest


def verify(root, inventory, bundle, out, cases):
    root, bundle, out = map(lambda p: Path(p).resolve(), (root, bundle, out))
    if out.exists(): raise FileExistsError(out)
    out.mkdir(parents=True)
    entries = {r['run_instance_id']: r for r in util.read_json(inventory)['runs']}
    reports = []
    for case in cases:
        instance, verdict, state = CASES[case]
        # Locate saved known defects by inventory identity, not by evaluator logic.
        if case in ('stale-total', 'inert-saved'):
            suffix = 'preload-003' if case == 'stale-total' else 'explained-004'
            instance = next(i for i, e in entries.items() if e['run_id'].endswith(suffix))
        entry = entries[instance]
        source_hash = util.artifact_hash(root/entry['root']/'frozen')
        # Keep disposable Windows paths short; the copied legacy source itself
        # contains long filenames. The full case name lives in the receipts.
        runs = out/f'{list(CASES).index(case) + 1:02d}'
        dest = prepare(root, entry, bundle, runs, case)
        real_docker, real_compose = runtime.docker, browser_cart.compose_evaluation
        calls, injected = [], []

        def docker(*args, **kwargs):
            calls.append(list(args))
            fail = False
            if case == 'network-cleanup' and args[:2] == ('network', 'rm'):
                fail = True
            if case == 'container-cleanup' and args[:2] == ('rm', '-f'):
                info = real_docker('inspect', args[2], check=False)
                fail = info.returncode == 0 and 's2-browser-' in info.stdout
            if fail and not injected:
                injected.append(list(args))
                raise RuntimeError('Injected Docker removal failure: ' + case)
            return real_docker(*args, **kwargs)

        def compose(*args, **kwargs):
            if case == 'missing-evidence' and not injected:
                screenshot = Path(args[4])/'browser-cart/C-015-after.png'
                screenshot.rename(screenshot.with_suffix('.withheld-for-regression'))
                injected.append('missing screenshot')
            return real_compose(*args, **kwargs)

        env = {'SAMPLE2_BROWSER_EXECUTABLE': str(out/'deliberately-absent-browser.exe')} if 'launch-failure' in case else {}
        with patch.dict(os.environ, env), patch.object(runtime, 'docker', docker), patch.object(browser_cart, 'compose_evaluation', compose):
            with (runs/'score-cli.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                exit_code = cli.main(['--repo', str(root), '--runs-dir', str(runs), 'score', '--run', dest.name])
        record = evaluate.last_scoring(dest)
        result = dest/record['directory']
        output = util.read_json(result/'evaluation.json')
        row = aggregate.row_for(runs, dest.name)
        report = {'case': case, 'exit_code': exit_code, 'state': row['scoring']['state'], 'verdict': row['verdict'],
                  'quality': row['quality'], 'research_status': row['scoring']['research_status'],
                  'browser_cases': output.get('browserCartCases'), 'operation_status': row['operation_status'],
                  'injected': injected, 'directory': str(result), 'model_called': False}
        if (result/'browser-cart/receipt.json').exists():
            receipt = util.read_json(result/'browser-cart/receipt.json')
            report['actions'] = {r['checkId']: r['action'] for r in receipt['removals']}
            for removal in receipt['removals']:
                events = util.read_json(result/'browser-cart'/(removal['checkId'] + '-events.json'))
                clicks = sum(e['kind'] == 'ui-click-remove' for e in events)
                assert clicks == (1 if removal['action'] == 'click-remove' else 0)
                assert ('clickedAt' in removal) == (removal['action'] == 'click-remove')
            report['action_attribution_verified'] = True
        expected_exit = 1 if state != 'scored' or 'cleanup' in case else 0
        report['pass'] = row['verdict'] == verdict and row['scoring']['state'] == state and exit_code == expected_exit
        if 'cleanup' in case:
            assert injected and row['operation_status'] == 'cleanup_failed'
            before = {'evaluation': util.sha256_file(result/'evaluation.json'), 'browser': util.tree_hashes(result/'browser-cart'),
                      'frozen': util.tree_hashes(dest/'frozen')}
            retry_calls = []
            def retry_docker(*args, **kwargs):
                retry_calls.append(list(args))
                return real_docker(*args, **kwargs)
            with patch.object(runtime, 'docker', retry_docker), patch.object(evaluate, 'run_evaluator', side_effect=AssertionError('Observation retry forbidden')):
                with (runs/'cleanup-cli.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                    retry_code = cli.main(['cleanup-browser', '--directory', str(result)])
            after = {'evaluation': util.sha256_file(result/'evaluation.json'), 'browser': util.tree_hashes(result/'browser-cart'),
                     'frozen': util.tree_hashes(dest/'frozen')}
            report['retry'] = {'exit_code': retry_code, 'commands': retry_calls, 'unchanged': before == after,
                               'confirmed': browser_cleanup.latest(result)['confirmed']}
            report['pass'] &= retry_code == 0 and before == after and report['retry']['confirmed']
        report['source_unchanged'] = source_hash == util.artifact_hash(root/entry['root']/'frozen')
        report['pass'] &= report['source_unchanged']
        util.write_new_json(runs/'aggregate.json', row)
        util.write_new_json(runs/'verification.json', report)
        reports.append(report)
        print(report, flush=True)
    summary = {'cases': reports, 'pass': all(r['pass'] for r in reports), 'model_called': False,
               'human_review': 'not_run', 'scope': 'Disposable fixtures; no research cohort or token changes'}
    util.write_new_json(out/'summary.json', summary)
    return 0 if summary['pass'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.')
    p.add_argument('--inventory', required=True)
    p.add_argument('--bundle', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--case', action='append', choices=CASES)
    a = p.parse_args()
    raise SystemExit(verify(a.root, a.inventory, a.bundle, a.out, a.case or list(CASES)))
