"""Fixed catalog acquisition: durable dispatch, bounded sharing and explicit approval.

freeze/check/recover never call a model. execute requires a separate user start
approval bound to exact plan bytes. There is no alternate model or replacement.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from outer.harness import aggregate, machine, preserve, profiles, runtime, util
from outer.harness.security import child_environment
from research import catalog_admission, catalog_delivery, catalog_environment, catalog_share, catalog_observations, catalog_storage
from research.catalog_allocation_review import read, sha256, write_new
from research.catalog_confirmatory import allocation, validate_plan, REQUIRED_CODE
from research.catalog_pilot import assess

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / 'research/protocols/ms1-catalog-comparison-v2-execution-20260922.json'
STORAGE_KEYS = ('next_pair_retained_bytes', 'generation_scratch_bytes', 'sqlite_finalize_bytes',
                'public_copy_bytes', 'archive_bytes', 'download_bytes', 'restore_bytes')
CODE = ('research/catalog_execution.py', 'research/catalog_delivery.py', 'research/catalog_share.py',
        'research/catalog_storage.py',
        'research/catalog_admission.py', 'research/catalog_allocation_review.py',
        'research/catalog_pilot.py', 'research/catalog_connection_probe.py',
        'research/catalog_environment.py', 'research/catalog_return_contract.py', *REQUIRED_CODE,
        'research/sql/catalog_otel_requests.sql', 'research/sharing/PAIR-README.md',
        'research/sharing/THIRD-PARTY-NOTICES.md')


def now():
    return datetime.now(timezone.utc).isoformat()


def relative_path(repo, value, prefix):
    path = (Path(repo) / value).resolve()
    parent = (Path(repo) / prefix).resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError('Path must remain below ' + prefix)
    return path


def append(path, value):
    with Path(path).open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps({'at': now(), **value}, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def events(path):
    if not Path(path).exists():
        return []
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Incomplete journal tail; dispatch state must be reconciled')
    return [json.loads(line) for line in raw.decode('utf-8').splitlines()]


@contextmanager
def exclusive(control):
    control.mkdir(parents=True, exist_ok=True)
    lock = control / 'dispatch.lock'
    # The OS releases this lock after a crash. A durable dispatch journal still
    # prevents replay; a leftover marker file cannot deadlock future recovery.
    with lock.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def check_fixed(plan, repo=REPO):
    repo = Path(repo).resolve()
    validate_plan(plan, require_allocation=True)
    execution = plan['execution']
    if sha256(repo / execution['retention_evidence']) != execution['retention_evidence_sha256']:
        raise ValueError('Retention preparation evidence changed')
    for name, digest in {**plan['pinned_files'], **execution['code_hashes']}.items():
        path = (repo / name).resolve()
        if not path.is_relative_to(repo) or sha256(path) != digest:
            raise ValueError('Frozen file changed: ' + name)
    actual = machine.expected_conditions(repo, plan['task'], plan['runtime'], ('catalog-compact', 'catalog-expanded'))
    if actual != plan['fixed_conditions']['condition_fingerprints']:
        raise ValueError('Frozen task, model or intervention changed')
    lock_path = profiles.runtime_root(repo, plan['task'], profiles.read(repo, 'runtimes', plan['runtime'])) / 'lock.json'
    lock = read(lock_path)
    if sha256(lock_path) != execution['runtime_lock_sha256'] or runtime.controller_files(repo) != lock['controller_files']:
        raise ValueError('Runtime controller or lock changed')
    source = repo / 'artifacts/sources' / plan['fixed_conditions']['source_commit']
    source_lock = source.parent / (source.name + '.json')
    if sha256(source_lock) != execution['source_lock_sha256'] or util.tree_hashes(source) != read(source_lock)['files']:
        raise ValueError('Prepared legacy source differs from its fixed inventory')
    if util.tree_hashes(lock_path.parent / 'evaluator') != lock['evaluator_files']:
        raise ValueError('Prepared evaluator bundle changed')
    for digest in plan['fixed_conditions']['images'].values():
        if runtime.image_id(digest) != digest:
            raise ValueError('Pinned Docker image unavailable')
    browser_path = repo / plan['fixed_conditions']['browser_environment_reference']
    if sha256(browser_path) != plan['fixed_conditions']['browser_environment_sha256']:
        raise ValueError('Browser environment reference changed')
    env = catalog_environment.validate(read(browser_path), repo)
    probe = repo / plan['probe'] / 'connection-result.json'
    if sha256(probe) != execution['connection_probe_sha256'] or read(probe).get('verified') is not True:
        raise ValueError('Accepted no-model input/serialization proof changed')
    host = execution['python']
    if Path(sys.executable).resolve() != (repo / host['path']).resolve() or sha256(sys.executable) != host['sha256'] or platform.python_version() != host['version']:
        raise ValueError('Frozen Python runtime changed')
    import numpy, scipy
    if {'numpy': numpy.__version__, 'scipy': scipy.__version__} != execution['analysis_packages']:
        raise ValueError('Frozen analysis dependencies changed')
    return env


def storage_record(plan, repo=REPO):
    storage = deepcopy(plan['execution']['storage'])
    batch = relative_path(repo, plan['runs_dir'], 'runs')
    parent = batch if batch.exists() else batch.parent
    storage.update(checked_at_utc=now(), free_bytes=shutil.disk_usage(parent).free)
    return storage


def approval_for(path, plan_path):
    if path is None:
        raise ValueError('Separate user start approval is required; no dispatch')
    approval = read(path)
    if (approval.get('authorized') is not True or approval.get('approved_by') != 'user'
            or approval.get('plan_sha256') != sha256(plan_path)
            or not approval.get('authorization_reference')):
        raise ValueError('Start approval is not bound to this frozen plan')
    catalog_admission.timestamp(approval.get('approved_at_utc'))
    return approval


def freeze(source, destination, repo=REPO):
    repo = Path(repo).resolve()
    plan = deepcopy(read(source))
    plan.update(pairs=320, runs_per_condition=320, maximum_runs=640,
        slots=allocation(320, plan['randomization_seed'], plan['attempt_start']),
        status='fixed_320_pairs_prepared_awaiting_separate_start_approval')
    # Keep the frozen plan publishable byte-for-byte. Machine-specific home
    # paths belong in local environment evidence, not the hashed analysis plan.
    plan['probe'] = Path(plan['probe']).resolve().relative_to(repo).as_posix()
    plan['launch'].update(authorized=False, authorization_stored_separately=True,
        notes='Frozen plan is immutable. A separate explicit user approval bound to its SHA-256 is required by the launcher. Fresh pre-dispatch evidence is appended at execution.')
    plan['preparation'] = {'at': now(), 'source_plan_sha256': sha256(source),
        'authority': 'User instructed completion of execution, storage/sharing and 320-pair freeze preparation.',
        'model_calls': 0, 'evaluator_calls': 0, 'start_authorized': False}
    storage = read(repo / 'research/design-results/catalog-pair-admission-20260922.json')['record']['storage']
    storage = {k: v for k, v in storage.items() if k not in ('checked_at_utc', 'free_bytes')}
    names = set(CODE) | {p.relative_to(repo).as_posix() for p in (repo / 'outer/harness').glob('*.py')}
    names |= {p.relative_to(repo).as_posix() for p in (repo / 'research/sharing/LICENSES').glob('*')}
    names |= {'outer/__init__.py', 'outer/harness/__init__.py', 'research/__init__.py'}
    lock_path = profiles.runtime_root(repo, plan['task'], profiles.read(repo, 'runtimes', plan['runtime'])) / 'lock.json'
    import numpy, scipy
    plan['execution'] = {'code_hashes': {n: sha256(repo / n) for n in sorted(names)},
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
        'runtime_lock_sha256': sha256(lock_path),
        'source_lock_sha256': sha256(repo / 'artifacts/sources' / (plan['fixed_conditions']['source_commit'] + '.json')),
        'connection_probe_sha256': sha256(repo / plan['probe'] / 'connection-result.json'),
        'python': {'path': Path(sys.executable).resolve().relative_to(repo).as_posix(), 'sha256': sha256(sys.executable), 'version': platform.python_version()},
        'analysis_packages': {'numpy': numpy.__version__, 'scipy': scipy.__version__},
        'storage': storage, 'staging_root': 'artifacts/catalog-execution-sharing-20260922',
        'retention_compression': 'post_run_ntfs_lossless',
        'retention_evidence': 'research/design-results/catalog-retention-validation-20260922.json',
        'retention_evidence_sha256': sha256(repo / 'research/design-results/catalog-retention-validation-20260922.json'),
        'one_pair_at_a_time': True, 'original_retention': 'Retain all original Run files; only verified temporary public/transfer copies may be deleted.',
        'api_policy': 'User confirmed paid overage disabled. Pause on unavailable API; no dollar reservation, account rotation, model switch or Run replacement.',
        'initial_operating_days': 42, 'initial_operating_days_are_deadline': False,
        'github_target_commit': 'b005f558852bcb9263601ea18ba7ee678c8ff8fb',
        'release_policy': 'One reviewed pair per prerelease in fukuda-yuki/sample2; <=1 GiB parts, <=1000 assets per release.',
        'reproduction_limits': 'Native state/auth caches, evaluation DB/WALs and runtime binaries remain local. Public exclusions and notices are mandatory; no self-contained environment replay claimed.'}
    plan['resource_evidence']['capacity_confirmed'] = 'per-pair physical check; API exhaustion pauses; whole-study completion not guaranteed'
    plan['planning']['resource_feasibility'] = '24-hour PC allocation, full existing Go allowance, no paid overage, zero discretionary disk reserve; completed Runs use verified lossless NTFS compression outside measurement timing; bounded one-pair sharing with physical checks.'
    plan['planning']['selection_rule'] = '320 fixed pairs selected before new outcomes under the accepted allocation/resource comparison. Do not change N in response to outcomes or runtime consumption.'
    plan['budget']['reserved_disk_bytes'] = 0
    plan['forbidden_in_current_work'] = ['model dispatch before separate approval', 'repeat live pilot', 'historical product reevaluation', 'historical archive recreation']
    check_fixed(plan, repo)
    write_new(destination, plan)
    return plan


def state(plan, journal):
    dispatched, results, shared, pause = [], [], {}, None
    for event in events(journal):
        kind = event['kind']
        if kind == 'dispatch':
            if len(dispatched) != len(results) or len(dispatched) >= len(plan['slots']) or event['case'] != plan['slots'][len(dispatched)]:
                raise ValueError('Duplicate, out-of-order or uncertain dispatch journal')
            dispatched.append(event['case'])
        elif kind == 'result':
            if len(dispatched) != len(results) + 1 or event['case'] != dispatched[-1]:
                raise ValueError('Result does not match exactly one dispatch')
            results.append(event)
        elif kind == 'pause':
            pause = event
        elif kind == 'recovery':
            pause = None
        elif kind == 'pair_shared':
            if event['pair'] != len(shared) + 1 or len(results) < 2 * event['pair'] or sha256(event['receipt']) != event['receipt_sha256']:
                raise ValueError('Sharing checkpoint is missing, changed or out of sequence')
            shared[event['pair']] = event
    return {'dispatched': dispatched, 'results': results, 'shared': shared, 'pause': pause,
            'uncertain': len(dispatched) != len(results)}


def run_case(plan, case, batch, env, repo=REPO):
    args = [sys.executable, '-B', '-m', 'outer.harness.cli', '--runs-dir', str(batch), 'run',
        '--task', plan['task'], '--intervention', case['condition'], '--runtime', plan['runtime'],
        '--attempt', str(case['attempt']), '--archive', str(batch / '_archive')]
    with (batch / '_control' / (case['run_id'] + '.log')).open('xb') as output:
        process = subprocess.run(args, cwd=repo, env=child_environment(env), stdout=output, stderr=subprocess.STDOUT)
    root = batch / case['run_id']
    row = aggregate.row_for(batch, case['run_id'])
    machine.verify_conditions(root, plan['fixed_conditions']['condition_fingerprints'], case['condition'])
    stops = assess(root, {**plan, 'probe': str(Path(repo) / plan['probe'])}, row)
    reference = read(root / 'archive-reference.json')
    preserve.verify(batch / '_archive', reference['package_id'], reference['sha256'])
    if row['scoring']['state'] in ('evaluator_fault', 'rejected_mismatch', 'not_attempted'):
        stops.append('evaluation_recovery_required')
    retention = None
    if plan['execution'].get('retention_compression') == 'post_run_ntfs_lossless':
        try:
            retention = catalog_storage.retain_completed(batch, case['run_id'])
        except (ValueError, OSError, subprocess.SubprocessError):
            stops.append('retention_compression_incomplete')
    return {'cli_exit_code': process.returncode, 'stops': stops, 'row': row,
            'archive_reference': reference, 'retention': retention}


def pair_workspace(plan, pair, repo=REPO):
    root = relative_path(repo, plan['execution']['staging_root'], 'artifacts')
    return root / f'pair-{pair:03d}'


def prepare_pair(plan_path, pair, repo=REPO):
    plan = read(plan_path)
    workspace = pair_workspace(plan, pair, repo)
    decision = catalog_admission.decide({'storage': storage_record(plan, repo),
        'fixed_execution_plan_verified': True, 'experiment_start_authorized': True})
    if not decision['may_start_pair']:
        raise ValueError('Insufficient physical staging space; original pair remains retained')
    if workspace.exists():
        manifest = catalog_share.verify_public(workspace / 'public')
        if manifest.get('plan_sha256') != sha256(plan_path) or manifest.get('pair') != pair:
            raise ValueError('Existing staging attempt differs; never overwrite it')
        return workspace
    batch = relative_path(repo, plan['runs_dir'], 'runs')
    observations_path = batch / '_control' / f'observations-pair-{pair:03d}.json'
    if not observations_path.exists():
        rows = []
        for case in plan['slots'][(pair - 1) * 2:pair * 2]:
            root = batch / case['run_id']
            try:
                observed = catalog_observations.observe(root, {**plan, 'probe': str(Path(repo) / plan['probe'])})
            except (FileNotFoundError, KeyError, ValueError) as exc:
                observed = {'run_id': case['run_id'], 'state': 'incomplete_evidence', 'tokens': None,
                    'requirements': [], 'audit_issues': ['observation_unavailable:' + type(exc).__name__]}
            rows.append({'case': case, **observed})
        launch_path = batch / '_control/launch-receipt.json'
        write_new(observations_path, {'plan_sha256': sha256(plan_path), 'cohort': plan['cohort'],
            'launch_receipt': read(launch_path) if launch_path.exists() else None,
            'runs': rows, 'read_only': True, 'model_called': False, 'evaluator_called': False})
    catalog_share.stage(repo, workspace, plan_path=plan_path, pair=pair)
    write_new(workspace / 'owned-workspace.json', {'plan_sha256': sha256(plan_path), 'pair': pair,
        'path': str(workspace.resolve()), 'created_at': now()})
    return workspace


def execute(plan_path, approval_path, *, repo=REPO, dispatch=run_case, verify=check_fixed, stage_pair=prepare_pair):
    plan_path, repo = Path(plan_path).resolve(), Path(repo).resolve()
    plan = read(plan_path)
    approval = approval_for(approval_path, plan_path)  # before batch creation or dispatch
    env = verify(plan, repo)
    batch = relative_path(repo, plan['runs_dir'], 'runs')
    control = batch / '_control'
    with exclusive(control):
        journal = control / 'journal.jsonl'
        if not journal.exists():
            write_new(control / 'frozen-plan.json', plan)
            write_new(control / 'start-approval.json', approval)
            append(journal, {'kind': 'begin', 'plan_sha256': sha256(plan_path), 'assigned': len(plan['slots'])})
        if sha256(control / 'frozen-plan.json') != sha256(plan_path) or read(control / 'start-approval.json') != approval:
            raise ValueError('Plan or authorization differs from the existing batch')
        current = state(plan, journal)
        if current['uncertain']:
            return {'status': 'held', 'reason': 'uncertain_dispatch_requires_reconciliation'}
        if current['pause']:
            return {'status': 'held', 'reason': current['pause']['reason']}
        count = len(current['results'])
        if count and count % 2 == 0 and count // 2 not in current['shared']:
            workspace = stage_pair(plan_path, count // 2, repo)
            return {'status': 'held', 'reason': 'pair_publication_required', 'pair': count // 2,
                    'workspace': str(workspace)}
        if count == len(plan['slots']):
            return {'status': 'complete', 'assigned': count}
        pair = count // 2 + 1
        for case in plan['slots'][count:pair * 2]:
            env = verify(plan, repo)
            admission = catalog_admission.decide({'storage': storage_record(plan, repo),
                'fixed_execution_plan_verified': True, 'experiment_start_authorized': True,
                'api_recovery_pending': False})
            append(journal, {'kind': 'admission', 'case': case, 'decision': admission})
            if not admission['may_start_pair']:
                append(journal, {'kind': 'pause', 'reason': 'storage', 'blocking_reasons': admission['blocking_reasons']})
                return {'status': 'held', 'reason': 'storage'}
            if not (control / 'launch-receipt.json').exists():
                receipt = {'analysis_plan_sha256': sha256(plan_path), 'checked_at_utc': now(),
                    'frozen_analysis_code_hashes': {n: plan['execution']['code_hashes'][n] for n in REQUIRED_CODE},
                    'pre_dispatch_verified': True,
                    'resource_capacity_confirmation': {'verified': True, 'evidence_reference': journal.relative_to(repo).as_posix()},
                    'identity_and_browser_pin_checks': {'verified': True, 'evidence_reference': (control / 'frozen-plan.json').relative_to(repo).as_posix()},
                    'dispatch_journal_path': journal.relative_to(repo).as_posix(), 'approval_sha256': sha256(control / 'start-approval.json')}
                write_new(control / 'launch-receipt.json', receipt)
            root = batch / case['run_id']
            if root.exists():
                raise ValueError('Existing Run directory without matching dispatch: stop, never replay')
            append(journal, {'kind': 'dispatch', 'case': case, 'plan_sha256': sha256(plan_path)})
            try:
                result = dispatch(plan, case, batch, env, repo)
                seal = {'run_id': case['run_id'], 'files': catalog_share.inventory(root) if root.exists() else {},
                        'directory_present': root.exists()}
                seal_path = control / (case['run_id'] + '.seal.json')
                write_new(seal_path, seal)
                append(journal, {'kind': 'result', 'case': case, **result,
                    'seal_path': str(seal_path), 'seal_sha256': sha256(seal_path)})
            except Exception as exc:
                # A missing terminal result remains uncertain even if a Run
                # folder was never created. Never replay that identity.
                append(journal, {'kind': 'pause', 'reason': 'uncertain_dispatch', 'error_type': type(exc).__name__})
                return {'status': 'held', 'reason': 'uncertain_dispatch'}
            if result['stops']:
                append(journal, {'kind': 'pause', 'reason': 'run_fault', 'stops': result['stops']})
                return {'status': 'held', 'reason': 'run_fault', 'stops': result['stops']}
        workspace = stage_pair(plan_path, pair, repo)
        append(journal, {'kind': 'pair_staged', 'pair': pair, 'workspace': str(workspace)})
        return {'status': 'held', 'reason': 'public_review_required', 'pair': pair, 'workspace': str(workspace)}


def recover(plan_path, evidence_path, *, repo=REPO, verify=check_fixed):
    plan, evidence = read(plan_path), read(evidence_path)
    verify(plan, repo)
    control = relative_path(repo, plan['runs_dir'], 'runs') / '_control'
    with exclusive(control):
        journal = control / 'journal.jsonl'
        if (evidence.get('plan_sha256') != sha256(plan_path) or evidence.get('journal_sha256') != sha256(journal)
                or evidence.get('verified') is not True or not evidence.get('explanation')
                or evidence.get('owned_resources_reconciled') is not True):
            raise ValueError('Recovery must bind the exact pause/journal and reconciled owned resources')
        refs = evidence.get('evidence_files', {})
        if not refs or any(sha256(path) != digest for path, digest in refs.items()):
            raise ValueError('Recovery evidence is missing or changed')
        current = state(plan, journal)
        if not current['pause'] and not current['uncertain']:
            raise ValueError('No pending fault to recover')
        if current['pause'] and current['pause']['reason'] == 'run_fault' and evidence.get('api_or_environment_recovered') is not True:
            raise ValueError('API/environment recovery has not been documented')
        admission = catalog_admission.decide({'storage': storage_record(plan, repo),
            'fixed_execution_plan_verified': True, 'experiment_start_authorized': True})
        if not admission['may_start_pair']:
            raise ValueError('Physical storage remains unavailable')
        if current['results']:
            last = current['results'][-1]
            if last.get('seal_path'):
                seal = read(last['seal_path'])
                root = relative_path(repo, plan['runs_dir'], 'runs') / last['case']['run_id']
                if sha256(last['seal_path']) != last['seal_sha256'] or (catalog_share.inventory(root) if root.exists() else {}) != seal['files']:
                    raise ValueError('Preserved result changed during recovery')
        if current['uncertain']:
            if evidence.get('in_flight_processes_stopped') is not True:
                raise ValueError('Uncertain dispatch still needs process reconciliation')
            append(journal, {'kind': 'result', 'case': current['dispatched'][-1],
                'stops': ['uncertain_retained'], 'row': None, 'dispatch_certainty': 'unknown_never_replayed',
                'evidence_sha256': sha256(evidence_path)})
        append(journal, {'kind': 'recovery', 'evidence_path': str(Path(evidence_path).resolve()),
            'evidence_sha256': sha256(evidence_path), 'prior_journal_sha256': evidence['journal_sha256']})
    return {'status': 'reconciled', 'replayed_runs': 0}


def check(plan_path, repo=REPO):
    plan = read(plan_path)
    check_fixed(plan, repo)
    decision = catalog_admission.decide({'storage': storage_record(plan, repo),
        'fixed_execution_plan_verified': True, 'experiment_start_authorized': False})
    return {'kind': 'preparation_check_not_start_authorization', 'checked_at_utc': now(),
        'plan_sha256': sha256(plan_path), 'pairs': plan['pairs'], 'assigned_runs': len(plan['slots']),
        'ready_for_start_approval': decision['blocking_reasons'] == ['experiment_start_not_authorized'],
        'admission': decision, 'model_called': False, 'evaluator_called': False}


def share_pair(plan_path, pair, review_path, *, repo=REPO, transfer=catalog_delivery.publish,
               fetch=catalog_delivery.download):
    """The actual acquisition handoff; next pair waits until this receipt exists."""
    plan = read(plan_path)
    control = relative_path(repo, plan['runs_dir'], 'runs') / '_control'
    with exclusive(control):
        journal = control / 'journal.jsonl'
        current = state(plan, journal)
        if current['uncertain'] or current['pause'] or len(current['results']) != pair * 2 or pair in current['shared']:
            raise ValueError('Only the completed, unshared current pair may be published')
        workspace = pair_workspace(plan, pair, repo)
        batch = relative_path(repo, plan['runs_dir'], 'runs')
        # A crash after a successful download/restore or during cleanup must not
        # require republishing or recreating removed scratch. Finish its durable
        # checkpoint from the retained distribution receipt.
        saved_deliveries = sorted(workspace.glob('delivery-*.json'))
        if saved_deliveries:
            receipt_path = saved_deliveries[-1]
            saved = read(receipt_path)
            if saved['asset']['plan_sha256'] != sha256(plan_path) or saved['asset']['pair'] != pair:
                raise ValueError('Retained delivery belongs to another plan/pair')
            for name, original in saved['public_manifest']['original_inventory'].items():
                if (catalog_share.inventory(batch / name) if (batch / name).exists() else {}) != original:
                    raise ValueError('Original pair changed after verified delivery')
            if sha256(Path(saved['roundtrip']['workspace']) / 'extraction.json') != saved['roundtrip']['extraction_sha256']:
                raise ValueError('Retained offline extraction changed')
            cleanup = catalog_delivery.cleanup(workspace, relative_path(repo, plan['execution']['staging_root'], 'artifacts'), saved['roundtrip'])
            append(journal, {'kind': 'pair_shared', 'pair': pair, 'receipt': str(receipt_path),
                'receipt_sha256': sha256(receipt_path), 'cleanup': cleanup, 'recovered_finalization': True})
            return {'pair': pair, 'status': 'shared_restored_extracted', 'recovered_finalization': True}
        manifest = catalog_share.verify_public(workspace / 'public')
        if manifest['plan_sha256'] != sha256(plan_path) or manifest['pair'] != pair:
            raise ValueError('Staging belongs to another plan or pair')
        for name, original in manifest['original_inventory'].items():
            actual = catalog_share.inventory(batch / name) if (batch / name).exists() else {}
            if actual != original:
                raise ValueError('Original pair changed after staging')
        package_dir = workspace / 'package'
        public_bytes = sum(item['bytes'] for item in catalog_share.inventory(workspace / 'public').values())
        # Include ZIP overhead and both assembled and split copies when needed.
        zip_bound = public_bytes + public_bytes // 100 + 1024 * 1024
        needed = public_bytes + zip_bound * (2 if package_dir.exists() else 4)
        if shutil.disk_usage(workspace).free < needed:
            raise ValueError('Insufficient physical space for package/download/restore; no upload attempted')
        if not package_dir.exists():
            asset = catalog_delivery.package(workspace / 'public', package_dir, review_path)
        else:
            asset = read(package_dir / 'pair.manifest.json')
            if asset['review_sha256'] != sha256(review_path) or asset['file_inventory'] != catalog_share.inventory(workspace / 'public'):
                raise ValueError('Existing package differs from the current review')
        if not (workspace / 'before-upload-extraction.json').exists():
            catalog_delivery.offline_extract(workspace / 'public', workspace / 'before-upload-extraction.json')
        urls = transfer(package_dir, f'catalog-comparison-v2-pair-{pair:03d}', plan['execution']['github_target_commit'])
        # A fresh attempt preserves a failed/truncated previous download.
        attempt = 1
        while (workspace / f'roundtrip-{attempt:03d}').exists():
            attempt += 1
        transfer_root = workspace / f'roundtrip-{attempt:03d}'
        receipt = catalog_delivery.roundtrip(asset, urls, transfer_root, fetch=fetch)
        if receipt['extraction_sha256'] != sha256(workspace / 'before-upload-extraction.json'):
            raise ValueError('Downloaded offline extraction differs from the reviewed copy')
        for name, original in manifest['original_inventory'].items():
            if (catalog_share.inventory(batch / name) if (batch / name).exists() else {}) != original:
                raise ValueError('Original pair changed during publication')
        # Retain complete distribution manifests/review before deleting scratch.
        write_new(workspace / f'delivery-{attempt:03d}.json', {'asset': asset, 'urls': urls, 'roundtrip': receipt,
            'public_manifest': manifest, 'review': read(review_path)})
        cleanup = catalog_delivery.cleanup(workspace, relative_path(repo, plan['execution']['staging_root'], 'artifacts'), receipt)
        cleanup_path = workspace / f'cleanup-{attempt:03d}.json'
        write_new(cleanup_path, cleanup)
        append(journal, {'kind': 'pair_shared', 'pair': pair,
            'receipt': str(workspace / f'delivery-{attempt:03d}.json'),
            'receipt_sha256': sha256(workspace / f'delivery-{attempt:03d}.json'),
            'cleanup_sha256': sha256(cleanup_path)})
        return {'pair': pair, 'status': 'shared_restored_extracted', 'originals_unchanged': True,
                'extraction_sha256': receipt['extraction_sha256'], 'cleanup': cleanup}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('freeze', 'check', 'execute', 'recover', 'stage', 'share'))
    parser.add_argument('--plan', type=Path, default=DEFAULT)
    parser.add_argument('--source-plan', type=Path, default=REPO / 'research/protocols/ms1-catalog-comparison-v2.json')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--pair', type=int)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.mode == 'freeze':
        freeze(args.source_plan, args.plan)
        result = check(args.plan)
    elif args.mode == 'check':
        result = check(args.plan)
    elif args.mode == 'recover':
        result = recover(args.plan, args.evidence)
    elif args.mode == 'stage':
        result = {'workspace': str(prepare_pair(args.plan, args.pair))}
    elif args.mode == 'share':
        result = share_pair(args.plan, args.pair, args.review)
    else:
        result = execute(args.plan, args.approval)
    if args.out:
        write_new(args.out, result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
