"""Prepare/check a new continuity cohort without sending a model request.

Execution is a separate explicit mode, bound to immutable assets, basic human
review, and an exact-bundle user start instruction. Old catalog plans are never
accepted. Preparation can retain a blocked bundle for an inspectable handoff.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys

from outer.harness import profiles, runtime, util
from outer.harness.security import child_environment
from research import next_phase_design

REPO = Path(__file__).resolve().parents[1]
PLAN = 'research/protocols/source-information-two-families-20261003-v2.json'
PREREQUISITES = ('evaluation_chain', 'selected_task_scope', 'independent_task_set',
                 'execution_evidence', 'serialized_intervention')


def now():
    return datetime.now(timezone.utc).isoformat()


def git(repo, *arguments):
    result = subprocess.run(['git', *arguments], cwd=repo, env=child_environment(),
        capture_output=True, text=True, encoding='utf-8', check=True)
    return result.stdout.strip()


def inside(repo, value, prefix=None):
    path = (Path(repo) / value).resolve()
    root = (Path(repo) / prefix).resolve() if prefix else Path(repo).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Path must stay below ' + str(root))
    return path


def validate_plan(plan):
    old = plan.get('plan_id') == 'continuity-initial-information-20261003-v1'
    tasks = ['MS1-CONT-A', 'MS1-CONT-B'] if old else ['MS1-CONT-A', 'MS1-CONT-B', 'CU1-ENR-C', 'CU1-ENR-D']
    if (plan.get('plan_id') not in ('continuity-initial-information-20261003-v1',
            'source-information-two-families-20261003-v2')
            or plan.get('task_ids') != tasks
            or plan.get('arms') != ['explore', 'preload']
            or plan.get('variant_weights') != ([0.5, 0.5] if old else [0.25] * 4)
            or plan.get('allocation', {}).get('pairs') != 64
            or plan['allocation'].get('runs') != 128
            or plan['allocation'].get('repetitions_per_variant') != (32 if old else 16)
            or plan.get('regime', {}).get('pair_concurrency') != 1
            or plan.get('quality_loss_margin') is not None
            or plan.get('research_start_authorized') is not False):
        raise ValueError('Unsupported or changed scientific protocol; create a reviewed amendment')
    return plan


def evaluation_version(plan, task):
    return plan['settings'].get('evaluator_version_by_task', {}).get(task,
        plan['settings'].get('evaluator_version'))


def assignments(plan):
    validate_plan(plan)
    rng = random.Random(plan['allocation']['randomization_seed'])
    ordered = []
    for task in plan['task_ids']:
        half = plan['allocation']['repetitions_per_variant'] // 2
        orders = [['explore', 'preload']] * half + [['preload', 'explore']] * half
        rng.shuffle(orders)
        ordered.extend((task, order) for order in orders)
    rng.shuffle(ordered)
    result = []
    for index, (task, order) in enumerate(ordered):
        attempt = plan['allocation']['attempt_start'] + index
        pair = index + 1
        cases = [{'slot': index * 2 + position, 'block': pair, 'pair': pair,
            'position': position, 'task': task, 'condition': arm, 'attempt': attempt,
            'run_id': f'{task}-{arm}-{attempt:03d}'} for position, arm in enumerate(order, 1)]
        result.append({'pair': pair, 'task': task,
            'source_family': plan.get('task_hierarchy', {}).get(task, {}).get('family'),
            'task_membership': plan.get('task_hierarchy', {}).get(task, {}).get('membership'),
            'analysis_session': index // 4 + 1, 'cases': cases})
    return result


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': util.sha256_file(path)}


def verify_reference(record):
    return util.sha256_file(record['path']) == record['sha256']


def acceptance_scopes(pins):
    """Required byte scopes; a receipt cannot choose away a changed dependency."""
    task_files = {name: digest for name, digest in pins.items() if
        name.startswith(('inner/tasks/', 'outer/profiles/tasks/MS1-CONT', 'outer/profiles/tasks/CU1-ENR', 'research/tasks/'))
        or name in ('outer/harness/migration_input.py', 'research/migration_tasks.py', 'research/verify_migration_tasks.py',
            'research/education_tasks.py', 'research/verify_education_tasks.py')}
    task_assets = {name: digest for name, digest in pins.items() if name.startswith(
        ('artifacts/migration-assets-', 'artifacts/education-assets-'))}
    evaluation = {name: digest for name, digest in pins.items() if
        name.startswith(('inner/evaluator/', 'inner/browser/'))
        or (name.startswith('inner/spec/') and ('1.3.0' in name or 'education' in name))
        or name in ('outer/harness/evaluate.py', 'outer/harness/browser_cart.py',
            'outer/harness/browser_cleanup.py', 'outer/harness/aggregate.py', 'outer/harness/education_browser.py')}
    execution = {name: digest for name, digest in pins.items() if
        name.startswith('outer/runtime/') or name in tuple('outer/harness/' + n + '.py' for n in
            ('runtime', 'run', 'usage', 'live_usage', 'gateway', 'machine', 'profiles', 'security', 'ownership', 'util'))
        or name in ('research/pair_execution.py', 'research/next_phase.py',
            'research/next_phase_execution.py', 'research/next_phase_sharing.py',
            'research/next_phase_analysis.py', 'research/catalog_delivery.py',
            'research/catalog_share.py', 'research/catalog_allocation_review.py')}
    serializer = {name: digest for name, digest in pins.items() if
        name.startswith(('outer/runtime/', 'outer/profiles/interventions/'))
        or name in ('outer/harness/profiles.py', 'outer/harness/migration_input.py',
            'outer/profiles/runtimes/deepseek-migration-v1.json',
            'outer/profiles/runtimes/deepseek-research-v2.json', 'outer/harness/gateway.py')}
    return {'evaluation_chain': {**evaluation, **task_assets,
            **{n:h for n,h in task_files.items() if n.startswith(('outer/profiles/tasks/', 'research/tasks/'))}},
        'selected_task_scope': {**task_files, **task_assets},
        'independent_task_set': {**task_files, **task_assets},
        'execution_evidence': execution, 'serialized_intervention': {**serializer, **task_files, **task_assets},
        'human_review': {**task_files, **task_assets, **{n: h for n, h in evaluation.items() if n.startswith('inner/spec/')}}}


def ledger_reasons(ledger, chain=None, scopes=None):
    reasons = []
    for key in PREREQUISITES:
        item = ledger.get(key, {})
        if item.get('status') != 'passed':
            reasons.append(key + ':' + item.get('status', 'not_run'))
        evidence = item.get('evidence', [])
        if not evidence:
            reasons.append(key + ':evidence_missing')
        for record in evidence:
            try:
                if not verify_reference(record): reasons.append(key + ':evidence_changed')
            except (OSError, KeyError, TypeError): reasons.append(key + ':evidence_unavailable')
    human = ledger.get('human_review', {})
    if human.get('status') != 'passed':
        reasons.append('human_review:' + human.get('status', 'not_run'))
    elif (human.get('actor') != 'human' or not human.get('reviewer')
            or not human.get('reviewed_at_utc') or not human.get('evidence')):
        reasons.append('human_review:unbound_or_not_human')
    else:
        for record in human['evidence']:
            try:
                if not verify_reference(record): reasons.append('human_review:evidence_changed')
            except (OSError, KeyError, TypeError): reasons.append('human_review:evidence_unavailable')
    if chain is not None:
        accepted = ledger.get('evaluation_chain', {}).get('chain', {})
        for task, lock in chain.items():
            if (accepted.get(task, {}).get('evaluator_sha256') != lock['evaluator_sha256']
                    or accepted.get(task, {}).get('evaluator_image') != lock['images']['evaluator']):
                reasons.append('evaluation_chain:runtime_artifact_not_calibrated:' + task)
    if scopes is not None:
        for key, expected in scopes.items():
            if ledger.get(key, {}).get('status') != 'passed':
                continue
            accepted = ledger[key].get('asset_hashes', {})
            if not expected or any(accepted.get(name) != digest for name, digest in expected.items()):
                reasons.append(key + ':reviewed_asset_scope_mismatch')
    return reasons


def prepare(repo, destination, ledger_path, runtime_id, browser_path=None):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if not destination.is_relative_to(repo / 'artifacts'):
        raise ValueError('Preparation must use a new local artifacts directory')
    destination.mkdir(parents=True, exist_ok=False)
    plan = validate_plan(util.read_json(repo / PLAN))
    ledger = util.read_json(ledger_path)
    pins = {}
    for name in git(repo, 'ls-files').splitlines():
        path = repo / name
        if path.is_file(): pins[name] = util.sha256_file(path)
    chain, failures = {}, []
    for task in plan['task_ids']:
        try:
            preset = profiles.read(repo, 'runtimes', runtime_id)
            root = profiles.runtime_root(repo, task, preset)
            lock = util.read_json(root / 'lock.json')
            if runtime.controller_files(repo) != lock['controller_files']:
                failures.append('runtime_controller_hash_mismatch:' + task)
            if util.tree_hashes(root / 'evaluator') != lock['evaluator_files']:
                failures.append('runtime_evaluator_inventory_mismatch:' + task)
            chain[task] = lock
            pins[(root / 'lock.json').relative_to(repo).as_posix()] = util.sha256_file(root / 'lock.json')
            for asset in (root / 'evaluator').rglob('*'):
                if asset.is_file(): pins[asset.relative_to(repo).as_posix()] = util.sha256_file(asset)
            for arm in plan['arms']:
                condition = profiles.resolve(repo, task, arm, runtime_id)
                if condition.get('task_input_adapter') == 'migration-v1':
                    from outer.harness import migration_input
                    inputs = migration_input.prepare(repo, condition)
                    task_asset_root = inputs['legacy-source'].parents[1]
                    for asset in task_asset_root.rglob('*'):
                        if asset.is_file(): pins[asset.relative_to(repo).as_posix()] = util.sha256_file(asset)
                settings = plan['settings']
                rt = condition['runtime']
                for key, target in [('model_id','model_id'), ('provider','provider'), ('endpoint','endpoint'), ('opencode_version','opencode_version'),
                        ('timeout_seconds','run_budget_seconds'), ('provider_timeout_seconds','provider_timeout_seconds'),
                        ('model_context_tokens','model_context_tokens'), ('model_output_tokens','model_output_tokens'),
                        ('compaction','compaction'), ('subagents','subagents')]:
                    if rt.get(key) != settings[target]: failures.append('runtime_setting_mismatch:' + key)
                if condition['evaluation']['evaluation_version'] != evaluation_version(plan, task):
                    failures.append('evaluation_version_mismatch:' + task)
                if condition['environment']['sdk'] != settings['dotnet_sdk']:
                    failures.append('sdk_version_mismatch:' + task)
        except (OSError, ValueError, KeyError) as exc:
            failures.append('runtime_not_prepared:' + task + ':' + type(exc).__name__)
    browser = None
    if browser_path:
        browser = {'record': util.read_json(browser_path), 'reference': reference(browser_path)}
    else:
        failures.append('browser_environment_not_bound')
    bundle = {'schema_version': 1, 'kind': 'continuity_prospective_bundle', 'prepared_at': now(),
        'source_commit': git(repo, 'rev-parse', 'HEAD'), 'source_clean': not bool(git(repo, 'status', '--porcelain')),
        'repo': str(repo), 'plan': plan, 'plan_reference': reference(repo / PLAN),
        'assignments': assignments(plan), 'runtime_id': runtime_id,
        'cohort': 'runs/source-info-v2', 'pinned_files': pins,
        'runtime_locks': chain, 'acceptance_ledger': ledger, 'acceptance_scopes': acceptance_scopes(pins),
        'acceptance_ledger_reference': reference(ledger_path), 'browser': browser,
        'python': {'path': str(Path(sys.executable).resolve()), 'sha256': util.sha256_file(sys.executable),
        'version': platform.python_version()}, 'precision': next_phase_design.calculate(
            plan['allocation']['pairs'], len(plan['task_ids']), plan['allocation']['repetitions_per_variant'],
            plan['independent_source_family_count']),
        'preparation_failures': failures, 'model_called': False, 'credential_read': False}
    util.write_new_json(destination / 'bundle.json', bundle)
    result = check(repo, destination / 'bundle.json', environment=False)
    util.write_new_json(destination / 'preparation-check.json', result)
    return result


def check(repo, bundle_path, *, environment=True):
    repo, bundle_path = Path(repo).resolve(), Path(bundle_path).resolve()
    bundle = util.read_json(bundle_path)
    validate_plan(bundle['plan'])
    reasons = list(bundle.get('preparation_failures', []))
    if bundle['plan']['plan_id'] == 'continuity-initial-information-20261003-v1':
        reasons.append('historical_one_family_candidate_not_authorized_for_acquisition')
    if bundle['runtime_id'] != bundle['plan']['settings'].get('runtime_profile', bundle['runtime_id']):
        reasons.append('research_runtime_profile_mismatch')
    if bundle.get('kind') != 'continuity_prospective_bundle': raise ValueError('Not a new study bundle')
    if bundle['assignments'] != assignments(bundle['plan']): reasons.append('assignment_identity_changed')
    if git(repo, 'rev-parse', 'HEAD') != bundle['source_commit']: reasons.append('final_source_commit_changed')
    if git(repo, 'status', '--porcelain') or not bundle['source_clean']: reasons.append('source_not_clean')
    for name, digest in bundle['pinned_files'].items():
        try:
            if util.sha256_file(inside(repo, name)) != digest: reasons.append('pinned_asset_changed:' + name)
        except (OSError, ValueError): reasons.append('pinned_asset_unavailable:' + name)
    for key in ('plan_reference', 'acceptance_ledger_reference'):
        try:
            if not verify_reference(bundle[key]): reasons.append(key + ':changed')
        except OSError: reasons.append(key + ':unavailable')
    if util.read_json(bundle['plan_reference']['path']) != bundle['plan']:
        reasons.append('embedded_plan_changed')
    scopes = acceptance_scopes(bundle['pinned_files'])
    if scopes != bundle['acceptance_scopes']: reasons.append('acceptance_scope_changed')
    reasons.extend(ledger_reasons(bundle['acceptance_ledger'], bundle['runtime_locks'], scopes))
    python = bundle['python']
    if (str(Path(sys.executable).resolve()) != python['path'] or platform.python_version() != python['version']
            or util.sha256_file(sys.executable) != python['sha256']): reasons.append('python_identity_changed')
    if environment:
        for task, lock in bundle['runtime_locks'].items():
            for target, digest in lock['images'].items():
                try:
                    if runtime.image_id(digest) != digest: reasons.append('docker_image_changed:' + task + ':' + target)
                except Exception: reasons.append('docker_image_unavailable:' + task + ':' + target)
        if bundle.get('browser'):
            try:
                from research import catalog_environment
                if not verify_reference(bundle['browser']['reference']): reasons.append('browser_reference_changed')
                catalog_environment.validate(bundle['browser']['record'], repo)
            except Exception: reasons.append('browser_environment_invalid')
    else:
        reasons.append('environment:not_checked')
    cohort = inside(repo, bundle['cohort'], 'runs')
    parent = cohort if cohort.exists() else cohort.parent
    while not parent.exists(): parent = parent.parent
    required = bundle['precision']['feasibility']['next_pair_peak_increment_scenario_bytes']
    free = shutil.disk_usage(parent).free
    if free < required: reasons.append('insufficient_next_pair_space')
    return {'kind': 'continuity_no_model_preflight', 'checked_at': now(),
        'bundle_sha256': util.sha256_file(bundle_path), 'source_commit': bundle['source_commit'],
        'model_called': False, 'credential_read': False, 'dispatches': 0,
        'scientific_and_technical_ready': not reasons, 'blocking_reasons': sorted(set(reasons)),
        'environment_checked': environment, 'free_bytes': free,
        'next_pair_peak_forecast_bytes': required,
        'separate_exact_bundle_start_instruction_required': True}


def approved(approval_path, bundle_path):
    data = util.read_json(approval_path)
    if (data.get('authorized') is not True or data.get('approved_by') != 'user'
            or data.get('bundle_sha256') != util.sha256_file(bundle_path)
            or not data.get('authorization_reference') or not data.get('approved_at_utc')):
        raise ValueError('Separate exact-bundle user research-start approval required')
    date = datetime.fromisoformat(data['approved_at_utc'].replace('Z', '+00:00'))
    if date.utcoffset().total_seconds() != 0: raise ValueError('Approval requires a UTC timestamp')
    return data


def stop(repo, bundle_path):
    bundle = util.read_json(bundle_path)
    validate_plan(bundle['plan'])
    batch = inside(repo, bundle['cohort'], 'runs')
    from research import pair_execution
    current = pair_execution.state(batch / '_control/pair-journal.jsonl')
    results = []
    digest = util.sha256_file(bundle_path)
    for rid, binding in current['dispatch'].items():
        if binding['plan_sha256'] != digest or binding['cohort'] != bundle['cohort']:
            raise ValueError('Stop target belongs to another plan/cohort')
        if binding['pair'] in current['gates']:
            continue
        root = batch / rid
        if not (root / 'manifest.json').exists():
            results.append({'run_id': rid, 'stop_confirmed': False, 'reason': 'dispatched_directory_missing'})
            continue
        manifest = util.read_json(root / 'manifest.json')
        if manifest['run_instance_id'] != binding['run_instance_id']:
            raise ValueError('Stop target instance mismatch')
        if manifest.get('stop_confirmed'):
            results.append({'run_id': rid, 'stop_confirmed': True, 'already_stopped': True})
        else:
            results.append({'run_id': rid, 'result': runtime.request_stop(root)})
    return {'model_dispatched': False, 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'check', 'execute', 'stop', 'recover', 'resume'))
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--runtime')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        if not all((args.out, args.ledger, args.runtime)): parser.error('prepare requires --out --ledger --runtime')
        result = prepare(args.repo, args.out, args.ledger, args.runtime, args.browser)
    elif not args.bundle:
        parser.error('--bundle required')
    elif args.mode == 'check':
        result = check(args.repo, args.bundle)
        if args.out: util.write_new_json(args.out, result)
    elif args.mode == 'stop':
        result = stop(args.repo, args.bundle)
    else:
        # Pair adapter is completed after the shared lifecycle owner's handoff.
        from research.next_phase_execution import execute, recover, resume
        if args.mode == 'execute': result = execute(args.repo, args.bundle, args.approval)
        elif args.mode == 'resume': result = resume(args.repo, args.bundle, args.approval)
        else: result = recover(args.repo, args.bundle)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get('scientific_and_technical_ready') is False: raise SystemExit(2)


if __name__ == '__main__':
    main()
