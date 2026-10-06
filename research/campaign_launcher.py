"""Bounded one-wave owner. No provider client, retries, or foreign PID kills.

The campaign controller prepares immutable wave specs. This supervisor retains
its own child handles, closes every selected pair on failure, and records unknown
ownership instead of treating process exit as completed cleanup.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from outer.harness import run, runtime, util
from outer.harness.security import child_environment
from research import live_pilot, live_pilot_launcher, pair_execution
from research.validation_scope import scoped_validation

KIND = 'repaired_campaign_wave_launcher_v1'
STOP_GRACE = 120
LATE_GRACE = 30
HELPER_GRACE = 45
DEFAULT_WALL = 9000
POLL = 1


def popen(command, repo, log):
    return subprocess.Popen(command, cwd=repo, env=child_environment(),
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _terminate(process):
    """Only a handle returned by this supervisor's own Popen."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            if process.poll() is None:
                raise
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return {'exit_code': None, 'exit_confirmed': False}
    return {'exit_code': process.poll(), 'exit_confirmed': process.poll() is not None}


def _selected(epoch, pairs):
    if (not isinstance(pairs, list) or not 1 <= len(pairs) <= 2
            or any(type(n) is not int or not 1 <= n <= 100 for n in pairs)
            or len(set(pairs)) != len(pairs)):
        raise ValueError('One or two distinct fixed pair numbers required')
    selected = []
    for number in pairs:
        selected.extend(live_pilot_launcher.selected_pairs(epoch, number))
    identities = [c['run_instance_id'] for p in selected for c in p['cases']]
    if len(identities) != 2 * len(pairs) or len(set(identities)) != len(identities):
        raise ValueError('Exactly two unique Run UUIDs per selected pair required')
    return selected


def _paths(campaign, wave_path):
    base = live_pilot.safe_path(campaign['batch'])
    wave_path = live_pilot.safe_path(wave_path)
    if (wave_path.name != 'spec.json' or wave_path.parent.parent != base / 'waves'
            or not wave_path.parent.name):
        raise ValueError('Immutable campaign/waves/<id>/spec.json required')
    return base, wave_path, wave_path.parent / '_launcher'


@scoped_validation
def preflight(repo, plan_path, wave_path):
    """No writes or process starts until the campaign's own validation passes."""
    from research import repaired_campaign
    repo = live_pilot.safe_path(repo)
    plan_ref = live_pilot.reference(plan_path)
    campaign = repaired_campaign.validate(repo, live_pilot.checked(plan_ref))
    base, wave_path, directory = _paths(campaign, wave_path)
    wave_ref = live_pilot.reference(wave_path)
    spec = repaired_campaign.wave_spec(repo, plan_ref['path'], wave_path)
    if repaired_campaign.validate_admission(repo, plan_ref['path'], wave_path) is not True:
        raise ValueError('Durable campaign admission was not verified')
    epoch_ref = spec['epoch_plan']
    epoch = live_pilot.owner_plan(live_pilot.checked(epoch_ref), repo)
    selected = _selected(epoch, spec['pairs'])
    if repaired_campaign.campaign_stop_pending(campaign):
        raise ValueError('Campaign STOP is latched')
    if (Path(epoch['batch']) / '_control/dispatch-stop.json').exists():
        raise ValueError('Epoch STOP is latched')
    if directory.exists() or (wave_path.parent / 'result.json').exists():
        raise FileExistsError('One-shot wave launcher cannot resend an attempt')
    for pair in selected:
        child = Path(epoch['batch']) / ('pair-' + str(pair['pair']))
        if util.read_json(child / 'phase.json') != live_pilot.observer_phase(epoch, epoch_ref, pair['pair']):
            raise ValueError('Foreign selected child phase')
        if pair_execution.events(child / '_control/pair-journal.jsonl'):
            raise ValueError('Selected pair is already reserved or dispatched')
    campaign_wall = campaign.get('bounds', {}).get('wave_wall_seconds', DEFAULT_WALL)
    wall = spec.get('wall_seconds', campaign_wall)
    if (type(campaign_wall) is not int or not 1 <= campaign_wall <= DEFAULT_WALL
            or type(wall) is not int or not 1 <= wall <= campaign_wall):
        raise ValueError('Finite wave wall of at most 9000 seconds required')
    return dict(repo=repo, campaign=campaign, base=base, plan=plan_ref,
        wave=wave_ref, wave_path=wave_path, directory=directory,
        epoch=epoch, epoch_plan=epoch_ref, pairs=spec['pairs'], wall_seconds=wall)


def owned_rows(context):
    rows = []
    for number in context['pairs']:
        rows.extend(live_pilot_launcher.owned_runs(context['epoch'], context['epoch_plan'], number))
    return rows


def latch_stop(context, reason):
    """Attempt every durable STOP before a blocking stop operation."""
    marker = dict(kind=KIND + '_stop', plan_sha256=context['plan']['sha256'],
        wave_sha256=context['wave']['sha256'], reason=reason, requested_at=run.now())
    event_path = context['base'] / '_control/stop-events' / (context['wave_path'].parent.name + '.json')
    paths = [(event_path, marker), (context['base'] / '_control/dispatch-stop.json', marker),
        (context['directory'] / 'stop.json', marker)]
    epoch_marker = {**marker, 'plan_sha256': context['epoch_plan']['sha256'],
        'campaign_plan_sha256': context['plan']['sha256']}
    paths.append((Path(context['epoch']['batch']) / '_control/dispatch-stop.json', epoch_marker))
    for number in context['pairs']:
        phase = live_pilot.observer_phase(context['epoch'], context['epoch_plan'], number)
        paths.append((Path(phase['batch']) / '_control' / phase['phase_id'] / 'dispatch-stop.json', epoch_marker))
    written, errors = [], []
    for path, value in paths:
        try:
            path = live_pilot.safe_path(path)
            if path.exists():
                old = util.read_json(path)
                if (old.get('plan_sha256') != value['plan_sha256']
                        or (path == event_path and old.get('wave_sha256') != value['wave_sha256'])):
                    raise ValueError('Foreign existing STOP')
            else:
                util.write_new_json(path, value)
            written.append(str(path))
        except Exception as exc:
            errors.append(dict(path=str(path), error_type=type(exc).__name__))
    return dict(reason=reason, durable_stop_paths=written, errors=errors)


def _command(action, context, instance=None):
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'research.campaign_launcher',
        action, context['plan']['path'], '--repo', str(context['repo']),
        '--wave', context['wave']['path']]
    if instance is not None:
        command += ['--instance', instance]
    return command


def _spawn_helper(action, context, directory, instance=None):
    directory.mkdir(parents=True, exist_ok=False)
    log = (directory / 'child.log').open('xb')
    try:
        process = popen(_command(action, context, instance), context['repo'], log)
    except BaseException:
        log.close()
        raise
    # Return the handle before optional registration I/O: never lose an owned child.
    return process, log


def close_owned(context, child, reason):
    stop = latch_stop(context, reason)
    helpers, logs, attempted, errors = {}, [], set(), []
    child_result = None

    def scan():
        rows = owned_rows(context)
        for row in rows:
            instance = row['run_instance_id']
            if row['status'] != 'owned_allocated' or instance in attempted:
                continue
            attempted.add(instance)  # Ambiguous launches are never retried.
            try:
                target = context['directory'] / 'stops' / instance
                process, log = _spawn_helper('_stop', context, target, instance)
                helpers[instance] = process
                logs.append(log)
                util.write_new_json(target / 'registration.json', dict(pid=process.pid, **row))
            except Exception as exc:
                errors.append(dict(run_instance_id=instance, error_type=type(exc).__name__))
        return rows

    try:
        deadline = time.monotonic() + STOP_GRACE
        while True:
            scan()
            if child is None or (child.poll() is not None and all(p.poll() is not None for p in helpers.values())):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(POLL)
        child_result = _terminate(child) if child is not None else {'child_handle_unavailable': True, 'exit_confirmed': False}
        scan()  # Account for allocations racing the durable STOP.
        deadline = time.monotonic() + LATE_GRACE
        while any(p.poll() is None for p in helpers.values()) and time.monotonic() < deadline:
            time.sleep(POLL)
    except BaseException as exc:
        errors.append(dict(stage='owned_stop_scan', error_type=type(exc).__name__))
    finally:
        if child_result is None:
            try:
                child_result = _terminate(child) if child is not None else {'child_handle_unavailable': True, 'exit_confirmed': False}
            except Exception as exc:
                child_result = {'exit_confirmed': False, 'error_type': type(exc).__name__}
        helper_results = {}
        for instance, process in helpers.items():
            try:
                helper_results[instance] = _terminate(process)
            except Exception as exc:
                helper_results[instance] = {'exit_confirmed': False, 'error_type': type(exc).__name__}
        for log in logs:
            try:
                log.close()
            except Exception as exc:
                errors.append(dict(stage='helper_log_close', error_type=type(exc).__name__))
    rows = []
    try:
        for row in owned_rows(context):
            instance = row['run_instance_id']
            receipt_path = context['directory'] / 'stops' / instance / 'result.json'
            receipt = util.read_json(receipt_path) if receipt_path.exists() else {}
            confirmed = (helpers.get(instance) is not None and helpers[instance].poll() == 0
                and receipt.get('run_id') == row['run_id'] and receipt.get('run_instance_id') == instance
                and receipt.get('stop_confirmed') is True
                and receipt.get('network_cleanup', {}).get('confirmed') is True)
            rows.append(dict(**row, stop_attempted=instance in attempted, closure_confirmed=confirmed,
                unknown=row['status'] != 'not_allocated' and not confirmed,
                stop_receipt=receipt, helper=helper_results.get(instance)))
    except Exception as exc:
        errors.append(dict(stage='stop_receipt_verification', error_type=type(exc).__name__))
    observer = _bounded_helper('_observers', context, context['directory'] / 'observer-close', HELPER_GRACE)
    return dict(stop=stop, child=child_result, owned_runs=rows, errors=errors,
        observer_closure=observer, owned_closure_confirmed=bool(rows)
        and not errors and not stop['errors'] and not any(r['unknown'] for r in rows)
        and child_result.get('exit_confirmed') is True and observer.get('confirmed') is True)


def _bounded_helper(action, context, directory, seconds):
    process = log = None
    outcome = {'confirmed': False}
    try:
        process, log = _spawn_helper(action, context, directory)
        util.write_new_json(directory / 'registration.json', dict(pid=process.pid, started_at=run.now()))
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            code = None
        path = directory / 'result.json'
        value = util.read_json(path) if path.exists() else None
        outcome = dict(confirmed=code == 0 and isinstance(value, dict) and value.get('confirmed') is True,
            exit_code=code, evidence=live_pilot.reference(path) if path.exists() else None)
    except Exception as exc:
        outcome['error_type'] = type(exc).__name__
    finally:
        if process is not None:
            try:
                outcome['child'] = _terminate(process)
            except Exception as exc:
                outcome.update(confirmed=False, child={'exit_confirmed':False, 'error_type':type(exc).__name__})
        if log is not None:
            try:
                log.close()
            except Exception as exc:
                outcome.update(confirmed=False, log_close_error=type(exc).__name__)
    return outcome


def supervise(context, child, started):
    from research import repaired_campaign
    deadline = started + context['wall_seconds']
    reason = None
    try:
        while time.monotonic() < deadline:
            util.write_json_atomic(context['directory'] / 'heartbeat.json', dict(kind=KIND,
                plan=context['plan'], wave=context['wave'], launcher_pid=os.getpid(),
                child_pid=child.pid, child_exit_code=child.poll(), at=run.now(),
                elapsed_seconds=time.monotonic() - started))
            if repaired_campaign.campaign_stop_pending(context['campaign']):
                reason = 'campaign_stop'; break
            if child.poll() is not None:
                if child.poll() != 0:
                    reason = 'controller_nonzero'; break
                remaining = max(0, deadline - time.monotonic())
                proof = _bounded_helper('_verify', context, context['directory'] / 'verification', remaining)
                if proof.get('confirmed') is True and time.monotonic() < deadline:
                    return dict(operational_complete=True, child_exit_code=0,
                        verification=proof, owned_closure_confirmed=True, stop_requested=False)
                reason = 'terminal_verification_unconfirmed'; break
            time.sleep(POLL)
        if reason is None:
            reason = 'wave_wall_exhausted'
    except BaseException as exc:
        reason = 'supervision_' + type(exc).__name__
    return dict(operational_complete=False, stop_requested=True, reason=reason,
        **close_owned(context, child, reason))


@scoped_validation
def launch(repo, plan_path, wave_path):
    """One campaign-level supervisor owns preflight through final closure."""
    from research import repaired_campaign
    campaign = repaired_campaign.validate(repo, plan_path)
    base = live_pilot.safe_path(campaign['batch'])
    # Failure to acquire this lock must never STOP the legitimate owner.
    with pair_execution.exclusive(base / '_launcher-owner'):
        return _launch_owned(repo, plan_path, wave_path)


def _launch_owned(repo, plan_path, wave_path):
    context = preflight(repo, plan_path, wave_path)
    context['directory'].mkdir(exist_ok=False)
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'research.repaired_campaign',
        '_wave', context['plan']['path'], '--repo', str(context['repo']),
        '--wave', context['wave']['path'], '--owner-pid', str(os.getpid())]
    intent = dict(kind=KIND, launch_id=uuid.uuid4().hex, launcher_pid=os.getpid(),
        parent_pid=os.getppid(), plan=context['plan'], wave=context['wave'],
        epoch_plan=context['epoch_plan'], pairs=context['pairs'], source_repo=str(context['repo']),
        command=command, wall_seconds=context['wall_seconds'], started_at=run.now())
    util.write_new_json(context['directory'] / 'intent.json', intent)
    child = None
    started = time.monotonic()
    with (context['directory'] / 'child.log').open('xb') as log:
        try:
            child = popen(command, context['repo'], log)
            util.write_new_json(context['directory'] / 'registration.json', dict(**intent, child_pid=child.pid))
            result = supervise(context, child, started)
        except BaseException as exc:
            reason = 'launch_' + type(exc).__name__
            result = dict(operational_complete=False, stop_requested=True, reason=reason,
                **close_owned(context, child, reason))
        result.update(kind=KIND + '_result', plan=context['plan'], wave=context['wave'],
            epoch_plan=context['epoch_plan'], pairs=context['pairs'], launch_id=intent['launch_id'],
            launcher_pid=os.getpid(), child_pid=child.pid if child is not None else None,
            elapsed_seconds=time.monotonic() - started, finished_at=run.now())
        try:
            util.write_new_json(context['directory'] / 'result.json', result)
        except BaseException:
            close_owned(context, child, 'launcher_result_write_failure')
            raise
    return result


def _retained_context(repo, plan_path, wave_path):
    """Stop helpers use retained immutable scope even when fresh preflight fails."""
    repo = live_pilot.safe_path(repo)
    plan_ref = live_pilot.reference(plan_path)
    campaign = util.read_json(live_pilot.checked(plan_ref))
    base, wave_path, directory = _paths(campaign, wave_path)
    wave_ref = live_pilot.reference(wave_path)
    intent = util.read_json(directory / 'intent.json')
    if (intent.get('kind') != KIND or intent.get('plan') != plan_ref or intent.get('wave') != wave_ref
            or intent.get('source_repo') != str(repo)):
        raise ValueError('Foreign retained launcher identity')
    spec = util.read_json(wave_path)
    if intent.get('epoch_plan') != spec.get('epoch_plan') or intent.get('pairs') != spec.get('pairs'):
        raise ValueError('Retained scope differs from immutable wave spec')
    epoch = util.read_json(live_pilot.checked(intent['epoch_plan']))
    _selected(epoch, intent['pairs'])
    return dict(repo=repo, campaign=campaign, base=base, plan=plan_ref, wave=wave_ref,
        wave_path=wave_path, directory=directory, epoch=epoch,
        epoch_plan=intent['epoch_plan'], pairs=intent['pairs'])


def observer_exited(pid, timeout=3):
    """Read-only wait on a receipt-bound PID; never signal/kill a process.

    PID reuse can only make this check conservative: a later live process yields
    unknown, while an absent/exited PID proves the original is no longer alive.
    """
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87  # No such process; access denied stays unknown.
        try:
            return kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    # This campaign runs on Windows. Other hosts cannot claim this proof.
    return False


def close_observers(context):
    """Request shutdown using the exact acknowledged scope; never kill a PID."""
    from research.resource_supervisor import validate_scope, validate_startup_ready
    expected = {}
    for number in context['pairs']:
        path = Path(context['epoch']['batch']) / ('pair-' + str(number)) / 'phase.json'
        expected[str(live_pilot.safe_path(path))] = live_pilot.reference(path)
    rows, seen = [], set()
    for config_path in (Path(context['epoch']['batch']) / '_observers').glob('*/config.json'):
        try:
            config_path = live_pilot.safe_path(config_path)
            config = util.read_json(config_path)
            phase_ref = config['phase']
            key = str(live_pilot.safe_path(phase_ref['path']))
            if key not in expected:
                continue
            seen.add(key)
            if phase_ref != expected[key]:
                raise ValueError('Observer phase hash differs')
            directory = live_pilot.safe_path(config['directory'])
            if directory != config_path.parent or config['session'] != directory.name:
                raise ValueError('Foreign observer directory/session')
            phase = util.read_json(live_pilot.checked(phase_ref))
            phase['_digest'] = phase_ref['sha256']
            startup = util.read_json(directory / 'startup-ready.json')
            pid = startup.get('observer_pid')
            validate_startup_ready(config, phase, pid, startup)
            requests = [p for p in directory.glob('scope-*.json')
                if p.stem.removeprefix('scope-').isdigit()]
            if not requests:
                raise ValueError('Observer has no bound scope')
            request_path = max(requests, key=lambda p: int(p.stem.removeprefix('scope-')))
            request = util.read_json(request_path)
            validate_scope(phase, request)
            ack = util.read_json(directory / ('scope-ack-' + str(request['generation']).zfill(6) + '.json'))
            if (ack.get('accepted') is not True or ack.get('session') != config['session']
                    or ack.get('generation') != request['generation']
                    or ack.get('scope_sha256') != util.sha256_file(request_path)):
                raise ValueError('Latest observer scope was not acknowledged')
            state = pair_execution.state(Path(phase['batch']) / '_control/pair-journal.jsonl')
            dispatched = sorted(state['dispatch'])
            if not set(dispatched) <= {b['run_id'] for b in request['bindings']}:
                raise ValueError('Observer final scope misses a dispatched Run')
            shutdown = dict(session=config['session'], phase_sha256=phase_ref['sha256'],
                generation=request['generation'], dispatched=dispatched)
            target = directory / 'shutdown.json'
            if target.exists():
                if util.read_json(target) != shutdown:
                    raise ValueError('Existing observer shutdown scope differs')
            else:
                util.write_new_json(target, shutdown)
            rows.append(dict(directory=str(directory), shutdown=shutdown, observer_pid=pid,
                confirmed=False, shutdown_ack_confirmed=False, process_exit_verified=False))
        except Exception as exc:
            rows.append(dict(config=str(config_path), confirmed=False, error_type=type(exc).__name__))
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        for row in rows:
            if row['confirmed'] or 'shutdown' not in row:
                continue
            path = Path(row['directory']) / 'shutdown-ack.json'
            if not path.exists():
                continue
            value = util.read_json(path)
            row['shutdown_ack_confirmed'] = (all(value.get(k) == row['shutdown'][k]
                for k in ('session', 'phase_sha256', 'generation'))
                and value.get('owned_resources_resolved') is True
                and value.get('monitor_stop_confirmed') is True)
            if row['shutdown_ack_confirmed']:
                row['process_exit_verified'] = observer_exited(row['observer_pid'])
                row['confirmed'] = row['process_exit_verified']
        if all(row['confirmed'] or 'shutdown' not in row for row in rows):
            break
        time.sleep(.1)
    # An allocated Run needs an observer, even if its config is missing.
    missing = []
    for number in context['pairs']:
        allocated = any(row['status'] != 'not_allocated' for row in
            live_pilot_launcher.owned_runs(context['epoch'], context['epoch_plan'], number))
        phase_path = live_pilot.safe_path(Path(context['epoch']['batch']) / ('pair-' + str(number)) / 'phase.json')
        if allocated and str(phase_path) not in seen:
            missing.append(number)
    confirmed = all(row['confirmed'] for row in rows) and not missing
    return dict(confirmed=confirmed, observers=rows, observer_or_foreign_processes_killed=False,
        missing_allocated_pair_observers=missing,
        proof_kind='bound_observer_shutdown_ack_and_native_exit', process_exit_inferred_from_ack=False)


def internal(action, repo, plan_path, wave_path, instance=None):
    context = _retained_context(repo, plan_path, wave_path)
    if action == '_verify':
        result_path = context['wave_path'].parent / 'result.json'
        result = util.read_json(result_path)
        if (result.get('plan_sha256') != context['plan']['sha256']
                or result.get('wave_sha256') != context['wave']['sha256']
                or result.get('operational_complete') is not True
                or result.get('watcher_shutdown_verified') is not True):
            raise ValueError('Worker wave completion is unconfirmed')
        proofs = [live_pilot_launcher.verify_pair_terminal(context['repo'], context['epoch'],
            context['epoch_plan'], number, live_pilot.reference(result_path)) for number in context['pairs']]
        value = dict(confirmed=True, plan=context['plan'], wave=context['wave'], pair_proofs=proofs)
        target = context['directory'] / 'verification/result.json'
    else:
        marker = util.read_json(context['directory'] / 'stop.json')
        if marker.get('plan_sha256') != context['plan']['sha256'] or marker.get('wave_sha256') != context['wave']['sha256']:
            raise ValueError('Matching campaign wave STOP required')
        if action == '_stop':
            rows = [row for row in owned_rows(context) if row['run_instance_id'] == instance]
            if len(rows) != 1 or rows[0]['status'] != 'owned_allocated':
                raise ValueError('Only an exact allocated wave UUID may be stopped')
            value = runtime.request_stop(rows[0]['root'])
            value = dict(value, run_instance_id=instance)
            target = context['directory'] / 'stops' / instance / 'result.json'
        elif action == '_observers':
            value = close_observers(context)
            target = context['directory'] / 'observer-close/result.json'
        else:
            raise ValueError('Unknown internal action')
    util.write_new_json(target, value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('launch', '_stop', '_verify', '_observers'))
    parser.add_argument('plan', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--wave', type=Path, required=True)
    parser.add_argument('--instance')
    args = parser.parse_args()
    result = (launch(args.repo, args.plan, args.wave) if args.action == 'launch'
        else internal(args.action, args.repo, args.plan, args.wave, args.instance))
    if args.action == 'launch':
        return 0 if result.get('operational_complete') is True else 2
    if args.action in ('_verify', '_observers'):
        return 0 if result.get('confirmed') is True else 2
    return 0 if result.get('stop_confirmed') is True else 2


if __name__ == '__main__':
    raise SystemExit(main())
