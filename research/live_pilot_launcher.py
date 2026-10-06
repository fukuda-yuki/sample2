"""External one-shot pilot watchdog. No retries, model client or credentials.

9000 seconds is the observed whole-pilot wall threshold, including verification.
STOP is followed by at most 120 seconds of parallel stop grace, then bounded
termination of this launcher's own children. These are not hard provider quotas.
Launcher/host loss remains an external supervision limitation.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from outer.harness import run, runtime, util
from outer.harness.security import child_environment
from research import live_pilot, pair_execution

STOP_GRACE_SECONDS = 120
FINAL_STOP_GRACE_SECONDS = 30
TERMINATE_GRACE_SECONDS = 10
KILL_GRACE_SECONDS = 5
POLL_SECONDS = 1


def preflight(repo, plan_path, approval_path, pair=None):
    """No writes/spawns before all ordinary live pilot gates pass."""
    from research import catalog_environment, next_phase, repaired_runtime
    repo = live_pilot.safe_path(repo)
    ref = live_pilot.reference(plan_path)
    plan = live_pilot.owner_plan(live_pilot.checked(ref), repo)
    selected_pairs(plan, pair)
    approval_ref = live_pilot.reference(approval_path)
    approval = util.read_json(live_pilot.checked(approval_ref))
    if (approval.get('plan_sha256') != ref['sha256'] or approval.get('authorized') is not True
            or approval.get('approved_by') != 'user' or not approval.get('authorization_reference')
            or (plan['kind'] == live_pilot.MAIN_KIND and approval.get('scope') != 'new_100_pairs_200_runs')):
        raise ValueError('Exact pilot user authorization required before child spawn')
    if (next_phase.git(repo, 'rev-parse', 'HEAD') != plan['source_commit']
            or next_phase.git(repo, 'status', '--porcelain')):
        raise ValueError('Clean exact committed pilot source required')
    repaired_runtime._committed_files(repo, plan['source_commit'], plan['source_pins'])
    launcher = 'research/live_pilot_launcher.py'
    if plan['source_pins'].get(launcher) != util.sha256_file(repo / launcher):
        raise ValueError('Launcher source pin missing or changed')
    if live_pilot.checked(plan['launch_supervisor']) != repo / launcher:
        raise ValueError('Foreign external launcher')
    catalog_environment.validate(util.read_json(live_pilot.checked(plan['browser_pin'])), repo)
    base = live_pilot.safe_path(plan['batch'])
    if util.read_json(base / 'allocation.json') != dict(kind=plan['kind'], plan=ref, phase_id=plan['phase_id']):
        raise ValueError('Foreign pilot allocation')
    scope = scope_root(plan, pair)
    if ((base / '_control/dispatch-stop.json').exists()
            or any((scope / name).exists() for name in ('execution-intent.json', 'result.json', '_launcher', 'pair-result.json'))):
        raise FileExistsError('One-shot launcher cannot resume or resend an existing attempt')
    live_pilot.checked(ref)
    live_pilot.checked(approval_ref)
    if pair is not None:
        from research import acquisition_readiness
        acquisition_readiness.pilot_ready(repo, plan['readiness_pilot_plan'], plan['readiness_pilot_result'])
        if pair_execution.events(scope / '_control/pair-journal.jsonl'):
            raise ValueError('No main pair resend')
        if not (base / 'execution-start.json').exists() and pair != 1:
            raise ValueError('Durable main start timestamp missing')
        invocation_wall(plan, ref, pair)
    return repo, plan, ref, approval_ref


def selected_pairs(plan, pair=None):
    if plan.get('kind') == live_pilot.KIND:
        if pair is not None:
            raise ValueError('--pair is only for the main cohort')
        return plan['assignments']
    if plan.get('kind') != live_pilot.MAIN_KIND or type(pair) is not int or not 1 <= pair <= 100:
        raise ValueError('Exactly one explicit main pair required')
    matches = [value for value in plan['assignments'] if value['pair'] == pair]
    if len(matches) != 1:
        raise ValueError('Selected main pair missing or ambiguous')
    return matches


def scope_root(plan, pair=None):
    selected_pairs(plan, pair)
    base = live_pilot.safe_path(plan['batch'])
    return base if pair is None else live_pilot.safe_path(base / ('pair-' + str(pair)))


def invocation_wall(plan, ref, pair=None):
    if pair is None:
        return 9000
    origin = Path(plan['batch']) / 'execution-start.json'
    if not origin.exists():
        if pair != 1:
            raise ValueError('Main wall origin missing')
        return 9000
    beginning = util.read_json(origin)
    start = datetime.fromisoformat(beginning['started_at'])
    now = datetime.now(timezone.utc)
    if beginning.get('plan_sha256') != ref['sha256'] or start.tzinfo is None or start > now:
        raise ValueError('Foreign or uncertain main wall origin')
    remaining = plan['bounds']['wall_seconds'] - (now - start).total_seconds()
    if remaining <= 0:
        raise TimeoutError('Durable whole-main wall exhausted')
    return min(9000, remaining)


def popen(command, repo, log):
    """Caller owns this handle; never discover/kill processes by PID alone."""
    return subprocess.Popen(command, cwd=repo, env=child_environment(), stdout=log,
                            stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def owned_runs(plan, ref, pair=None):
    """Inspect exactly the four planned paths. Foreign/unreadable stays unknown."""
    rows = []
    for assignment in selected_pairs(plan, pair):
        batch = live_pilot.safe_path(Path(plan['batch']) / ('pair-' + str(assignment['pair'])))
        for case in assignment['cases']:
            row = dict(run_id=case['run_id'], run_instance_id=case['run_instance_id'], root=str(batch / case['run_id']))
            try:
                root = live_pilot.safe_path(row['root'])
                if not (root / 'runtime.json').exists():
                    row['status'] = 'not_allocated'
                else:
                    phase = util.read_json(batch / 'phase.json')
                    if phase != live_pilot.observer_phase(plan, ref, assignment['pair']):
                        raise ValueError('Foreign pair phase')
                    manifest, state = (util.read_json(root / name) for name in ('manifest.json', 'runtime.json'))
                    dispatch = pair_execution.state(batch / '_control/pair-journal.jsonl')['dispatch'].get(case['run_id'], {})
                    if (any(value.get(key) != case[key] for value in (manifest, state, dispatch)
                            for key in ('run_id', 'run_instance_id'))
                            or any(dispatch.get(key) != value for key, value in case.items())
                            or dispatch.get('plan_sha256') != ref['sha256']
                            or manifest.get('prompt_sha256') != dispatch.get('input_sha256')
                            or manifest.get('condition_sha256') != dispatch.get('condition_sha256')
                            or not dispatch.get('input_sha256') or not dispatch.get('condition_sha256')):
                        raise ValueError('Foreign/unfinished runtime identity')
                    row['status'] = 'owned_allocated'
            except Exception as exc:
                row.update(status='unknown_foreign_or_unreadable', error_type=type(exc).__name__)
            rows.append(row)
    return rows


def latch_stop(plan, ref, directory, reason, pair=None):
    marker = dict(kind='live_pilot_launcher_stop_v1', phase_id=plan['phase_id'],
                  plan_sha256=ref['sha256'], reason=reason, requested_at=run.now())
    paths = [Path(plan['batch']) / '_control/dispatch-stop.json', directory / 'stop.json']
    for assignment in selected_pairs(plan, pair):
        phase = live_pilot.observer_phase(plan, ref, assignment['pair'])
        paths.append(Path(phase['batch']) / '_control' / phase['phase_id'] / 'dispatch-stop.json')
    errors, durable = [], []
    for path in paths:
        try:
            path = live_pilot.safe_path(path)
            if path.exists():
                old = util.read_json(path)
                if old.get('plan_sha256') != ref['sha256']:
                    raise ValueError('Existing STOP belongs to another plan')
            else:
                util.write_new_json(path, marker)
            durable.append(str(path))
        except Exception as exc:
            errors.append(dict(path=str(path), error_type=type(exc).__name__))
    return dict(**marker, durable_stop_paths=durable, stop_marker_errors=errors)


def _terminate(process):
    """Only a Popen handle created here; no process-name/PID lookup."""
    outcome = dict(pid=process.pid, initial_exit_code=process.poll(), terminated=False,
                   killed=False, exit_code=process.poll(), unknown=False)
    if process.poll() is not None:
        return outcome
    try:
        process.terminate(); outcome['terminated'] = True
        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill(); outcome['killed'] = True
            process.wait(timeout=KILL_GRACE_SECONDS)
        outcome['exit_code'] = process.poll()
    except Exception as exc:
        outcome.update(unknown=True, error_type=type(exc).__name__, exit_code=process.poll())
    return outcome


def _helper_command(action, repo, ref, directory, instance=None):
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'research.live_pilot_launcher',
               action, ref['path'], '--repo', str(repo), '--directory', str(directory),
               '--plan-sha256', ref['sha256']]
    if instance is not None:
        command.extend(['--instance', instance])
    return command


def observer_disposition(plan, ref, pair=None):
    """Read-only bound ACK inventory; no process discovery/killing inference."""
    rows, expected, errors = [], {}, []
    try:
        for assignment in selected_pairs(plan, pair):
            phase_path = live_pilot.safe_path(Path(plan['batch']) / ('pair-' + str(assignment['pair'])) / 'phase.json')
            if util.read_json(phase_path) != live_pilot.observer_phase(plan, ref, assignment['pair']):
                raise ValueError('Selected observer phase changed')
            expected[str(phase_path)] = live_pilot.reference(phase_path)
        root = live_pilot.safe_path(Path(plan['batch']) / '_observers')
        for path in sorted(root.glob('*/config.json')):
            row = dict(config_path=str(path), shutdown_ack_confirmed=False, manual_resolution_required=True)
            try:
                path = live_pilot.safe_path(path)
                row['config_sha256'] = util.sha256_file(path)
                config = util.read_json(path)
                phase_path = live_pilot.safe_path(config['phase']['path'])
                if str(phase_path) not in expected:
                    row.update(status='outside_selected_phase_scope', manual_resolution_required=False)
                    rows.append(row); continue
                directory = live_pilot.safe_path(config['directory'])
                session = config['session']
                if (directory != path.parent or session != directory.name
                        or not re.fullmatch('[a-f0-9]{32}', session) or config['phase'] != expected[str(phase_path)]):
                    raise ValueError('Observer config phase/session/directory mismatch')
                row.update(session=session, phase=config['phase'])
                shutdown_path, ack_path = directory/'shutdown.json', directory/'shutdown-ack.json'
                shutdown, ack = util.read_json(shutdown_path), util.read_json(ack_path)
                generation = shutdown.get('generation')
                scope_path = directory / ('scope-' + str(generation).zfill(6) + '.json')
                scope = util.read_json(scope_path)
                identity = dict(session=session, phase_sha256=config['phase']['sha256'], generation=generation)
                bound_phase = util.read_json(phase_path)
                bound_phase['_digest'] = config['phase']['sha256']
                from research.resource_supervisor import validate_scope
                validate_scope(bound_phase, scope)
                selected = {case['run_id']: case['run_instance_id'] for assignment in bound_phase['assignments'] for case in assignment['cases']}
                bindings = scope.get('bindings', [])
                if (type(generation) is not int or generation < 1
                        or any(value.get(key) != wanted for value in (shutdown, ack, scope) for key,wanted in identity.items())
                        or not isinstance(bindings,list)
                        or any(selected.get(binding.get('run_id')) != binding.get('run_instance_id') for binding in bindings)
                        or not isinstance(shutdown.get('dispatched'),list)
                        or not set(shutdown['dispatched']) <= {binding['run_id'] for binding in bindings}
                        or ack.get('owned_resources_resolved') is not True or ack.get('monitor_stop_confirmed') is not True):
                    raise ValueError('Observer shutdown generation/owned-resource ACK mismatch')
                row.update(status='bound_shutdown_ack_confirmed', shutdown_ack_confirmed=True,
                           manual_resolution_required=False, generation=generation,
                           fault_latched=ack.get('fault_latched'),
                           evidence_sha256={name:util.sha256_file(directory/name) for name in
                               ('shutdown.json','shutdown-ack.json',scope_path.name)})
            except Exception as exc:
                row.update(status='observer_state_unknown', error_type=type(exc).__name__)
            rows.append(row)
    except Exception as exc:
        errors.append(dict(error_type=type(exc).__name__))
    bound = [row for row in rows if row.get('phase',{}).get('path') in expected]
    missing = [value for value in expected.values() if not any(row.get('phase') == value for row in bound)]
    return dict(kind='selected_observer_disposition_v1', observations=rows, missing_selected_phase_configs=missing,
                errors=errors, observer_shutdown_ack_confirmed=bool(bound) and not missing and not errors
                    and all(row['shutdown_ack_confirmed'] for row in bound),
                manual_resolution_required=bool(missing or errors or not bound or any(row['manual_resolution_required'] for row in rows)),
                observer_or_grandchild_processes_killed=False,
                limitation='Bound saved ACKs are reported; controller exit does not prove all descendant processes resolved.')


def stop_owned(plan, ref, repo, directory, child, reason, pair=None):
    """STOP first, then parallel isolated request_stop; each UUID requested once."""
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    helpers, logs, observed, scanned, errors = {}, [], {}, [], []
    try:
        stop_marker = latch_stop(plan, ref, directory, reason, pair)
    except BaseException as exc:
        stop_marker = dict(reason=reason, durable_stop_paths=[], stop_marker_errors=[dict(error_type=type(exc).__name__)])
    child_outcome, helper_outcomes = None, {}
    def admit(rows):
        for row in rows:
            instance = row['run_instance_id']
            observed[instance] = row
            if row['status'] != 'owned_allocated' or instance in helpers:
                continue
            # Mark the attempt before any I/O; an ambiguous launch is never retried.
            helpers[instance] = None
            try:
                target = directory / 'stops' / instance
                target.mkdir(parents=True, exist_ok=False)
                log = (target / 'child.log').open('xb'); logs.append(log)
                process = popen(_helper_command('_stop', repo, ref, directory, instance), repo, log)
                helpers[instance] = process
                util.write_new_json(target / 'registration.json', dict(pid=process.pid, started_at=run.now(), **row))
            except Exception as exc:
                errors.append(dict(run_instance_id=instance, error_type=type(exc).__name__))
    try:
        while True:
            scanned = owned_runs(plan, ref, pair)
            admit(scanned)
            pending = [process for process in helpers.values() if process is not None and process.poll() is None]
            # Keep the controller alive for graceful freeze/cleanup. Newly
            # allocated matching runtimes may appear during its STOP unwind.
            if (child.poll() is not None and not pending) or time.monotonic() >= deadline:
                break
            time.sleep(POLL_SECONDS)
        child_outcome = _terminate(child)
        # Once the controller is stopped, one final scan accounts for allocations
        # that raced the STOP. Never resend a previously attempted UUID.
        final = owned_runs(plan, ref, pair)
        new = [row for row in final if row['run_instance_id'] not in helpers and row['status'] == 'owned_allocated']
        admit(final)
        if new:
            final_deadline = time.monotonic() + FINAL_STOP_GRACE_SECONDS
            while any(process is not None and process.poll() is None for process in helpers.values()) and time.monotonic() < final_deadline:
                time.sleep(POLL_SECONDS)
    except BaseException as exc:
        errors.append(dict(stage='stop_or_final_scan', error_type=type(exc).__name__))
    finally:
        # Applies even to marker/registration/read failures. Handles are retained
        # immediately after spawn; foreign PIDs are never discovered or killed.
        if child_outcome is None:
            child_outcome = _terminate(child)
        for instance, process in helpers.items():
            if process is not None:
                helper_outcomes[instance] = _terminate(process)
        for log in logs:
            try:
                log.close()
            except Exception as exc:
                errors.append(dict(stage='stop_log_close', error_type=type(exc).__name__))
    results = []
    for instance, row in observed.items():
        process = helpers.get(instance)
        result_path = directory / 'stops' / instance / 'result.json'
        receipt = None
        try:
            receipt = util.read_json(result_path) if result_path.exists() else None
        except Exception as exc:
            errors.append(dict(stage='stop_receipt', run_instance_id=instance, error_type=type(exc).__name__))
        confirmed = (process is not None and process.poll() == 0 and isinstance(receipt, dict)
                     and receipt.get('run_id') == row['run_id'] and receipt.get('run_instance_id') == instance
                     and receipt.get('stop_confirmed') is True)
        cleanup = bool(confirmed and receipt.get('network_cleanup', {}).get('confirmed') is True)
        results.append(dict(**row, stop_attempted=instance in helpers, stop_confirmed=bool(confirmed),
            cleanup_confirmed=cleanup, request_stop_receipt=receipt, stop_child=helper_outcomes.get(instance),
            unknown=row['status'] != 'not_allocated' and not (confirmed and cleanup)))
    return dict(stop=stop_marker, child=child_outcome, owned_stops=results, errors=errors,
        observer_disposition=observer_disposition(plan, ref, pair),
        stop_grace_seconds=STOP_GRACE_SECONDS, final_late_allocation_grace_seconds=FINAL_STOP_GRACE_SECONDS,
        bounded_fallback_used=time.monotonic() >= deadline)


def _check_result(plan, ref, pair=None):
    path = live_pilot.safe_path(scope_root(plan, pair) / ('result.json' if pair is None else 'pair-result.json'))
    result = util.read_json(path)
    if (result.get('kind') != plan['kind'] or result.get('plan_sha256') != ref['sha256']
            or result.get('pilot_operational_complete' if pair is None else 'pair_operational_complete') is not True
            or (pair is not None and result.get('pair') != pair) or result.get('fault') is not None
            or result.get('watcher_shutdown_verified') is not True):
        raise ValueError('Child result is missing, uncertain or operationally incomplete')
    return live_pilot.reference(path)


def verify_main_terminal(repo, plan, ref, pair):
    """Actual saved two-Run proof; no historical pair participates in this gate."""
    from research import acquisition_readiness
    result_ref = _check_result(plan, ref, pair)
    assignment = selected_pairs(plan, pair)[0]
    batch = scope_root(plan, pair)
    journal = pair_execution.state(batch / '_control/pair-journal.jsonl')
    if (set(journal['dispatch']) != {case['run_id'] for case in assignment['cases']}
            or len(journal['results']) != 2):
        raise ValueError('Selected actual two-Run journal incomplete')
    acquisition_readiness.validate_observer_terminal(plan, ref, assignment, batch,
                                                     util.read_json(batch / 'observer-terminal.json'))
    saved = util.read_json(batch / 'owned-terminal-proof.json')
    if saved.get('plan_sha256') != ref['sha256'] or saved.get('phase_sha256') != util.sha256_file(batch / 'phase.json'):
        raise ValueError('Selected terminal proof identity differs')
    proofs = []
    for case in assignment['cases']:
        binding = journal['dispatch'][case['run_id']]
        if any(binding.get(key) != value for key, value in case.items()):
            raise ValueError('Selected actual UUID differs')
        root = batch / case['run_id']
        row = journal['results'][case['run_id']]['row']
        receipt = journal['implementations'][case['run_id']]['receipt']
        normalized = util.read_json(root / 'usage/normalized.json')
        if (pair_execution._postprocess_fault(row) or receipt.get('stop_confirmed') is not True
                or normalized.get('usage_complete') is not True or normalized.get('input_reached') is not True
                or receipt.get('raw') != util.tree_hashes(root / 'usage/raw')
                or receipt.get('snapshot_sha256') != util.sha256_file(root / 'snapshot.json')):
            raise ValueError('Selected usage/stop/evaluator fault')
        from research.wave_campaign import journal_health
        starts, start_errors = live_pilot.live_usage.journal(root/'usage/raw/started.jsonl')
        events, event_errors = live_pilot.live_usage.journal(root/'usage/raw/events.jsonl')
        if start_errors or event_errors or not starts or not events:
            raise ValueError('Selected actual model request/response evidence missing')
        health = journal_health(batch, [binding], plan['settings']['model_id'])
        if not all(health[key] is True for key in ('journal_healthy', 'provider_healthy', 'http_healthy')):
            raise ValueError('Selected provider evidence unhealthy')
        proofs.append(live_pilot.validate_owned_terminal(root, binding))
    if saved.get('runs') != proofs or len({item['native_session_id'] for item in proofs}) != 2:
        raise ValueError('Selected native/owned terminal proof differs')
    return dict(ready=True, plan=ref, pair=pair, result=result_ref, model_runs=2,
                new_main_authorized=False, automatic_next_pair_start=False)


def supervise(repo, plan, ref, directory, child, started, pair=None):
    """External wall includes main child and isolated terminal verification."""
    wall = invocation_wall(plan, ref, pair)
    deadline = min(started + 9000, time.monotonic() + wall)
    verifier = None
    log = None
    reason = None
    verification_exit = None
    evidence_errors = []
    try:
        while True:
            elapsed = time.monotonic() - started
            util.write_json_atomic(directory / 'heartbeat.json', dict(at=run.now(), launcher_pid=os.getpid(),
                child_pid=child.pid, child_exit_code=child.poll(), elapsed_seconds=elapsed,
                wall_seconds=wall, verification_pid=verifier.pid if verifier else None))
            if time.monotonic() >= deadline:
                reason = 'whole_pilot_wall_threshold'; break
            if child.poll() is not None:
                if child.poll() != 0:
                    reason = 'owned_controller_exit_nonzero'; break
                if verifier is None:
                    try:
                        _check_result(plan, ref, pair)
                    except Exception:
                        reason = 'owned_controller_result_unconfirmed'; break
                    log = (directory / 'verification-child.log').open('xb')
                    verifier = popen(_helper_command('_verify', repo, ref, directory), repo, log)
                    util.write_new_json(directory / 'verification-registration.json', dict(pid=verifier.pid, at=run.now()))
                if verifier.poll() is not None:
                    proof_path = directory / 'terminal-proof.json'
                    if verifier.poll() == 0 and proof_path.exists():
                        proof = util.read_json(proof_path)
                        if proof.get('ready') is True and proof.get('pilot_plan', proof.get('plan')) == ref:
                            if time.monotonic() >= deadline:
                                reason = 'whole_pilot_wall_threshold'; break
                            return dict(operational_complete=True, child_exit_code=0,
                                terminal_proof=live_pilot.reference(proof_path), elapsed_seconds=time.monotonic()-started,
                                verification_child_pid=verifier.pid, verification_child_exit_code=0,
                                watcher_shutdown_verified=True,
                                stop_requested=False, model_runs=4 if pair is None else 2, selected_pair=pair,
                                new_main_authorized=False)
                    reason = 'terminal_proof_unconfirmed'; break
            time.sleep(POLL_SECONDS)
    except BaseException as exc:
        reason = 'launcher_exception_' + type(exc).__name__
    finally:
        # Preserve the handle even if log-close/receipt I/O fails. A successful
        # return has an already exited verifier; failure always bounds it here.
        if verifier is not None:
            verification_exit = _terminate(verifier)
        if log is not None:
            try:
                log.close()
            except Exception as exc:
                evidence_errors.append(dict(stage='verification_log_close', error_type=type(exc).__name__))
    stopped = stop_owned(plan, ref, repo, directory, child, reason, pair)
    return dict(operational_complete=False, reason=reason, stop_requested=True, **stopped,
                verification_child=verification_exit, elapsed_seconds=time.monotonic()-started,
                evidence_errors=evidence_errors,
                wall_threshold_seconds=wall,
                configured_additional_cleanup_grace_seconds=STOP_GRACE_SECONDS+FINAL_STOP_GRACE_SECONDS+6*(TERMINATE_GRACE_SECONDS+KILL_GRACE_SECONDS),
                new_main_authorized=False, success_or_quality_adopted=False)


def launch(repo, plan_path, approval_path, pair=None):
    started = time.monotonic()
    started_utc = run.now()
    repo, plan, ref, approval_ref = preflight(repo, plan_path, approval_path, pair)
    if time.monotonic() - started >= invocation_wall(plan, ref, pair):
        raise TimeoutError('Whole pilot wall exhausted before spawn')
    directory = live_pilot.safe_path(scope_root(plan, pair) / '_launcher')
    directory.mkdir(exist_ok=False)
    command = [sys.executable, '-B', '-X', 'utf8', '-m', 'research.live_pilot', 'execute',
               ref['path'], '--repo', str(repo), '--approval', approval_ref['path']]
    if pair is not None:
        command = [sys.executable, '-B', '-X', 'utf8', '-m', 'research.acquisition_readiness', 'execute-pair',
                   ref['path'], '--pair', str(pair), '--repo', str(repo), '--approval', approval_ref['path']]
        origin = Path(plan['batch']) / 'execution-start.json'
        if not origin.exists():
            util.write_new_json(origin, dict(plan_sha256=ref['sha256'], started_at=started_utc))
    identity = dict(schema_version=1, kind='live_pilot_launcher_v1', launch_id=uuid.uuid4().hex,
        source_sha256=util.sha256_file(repo / 'research/live_pilot_launcher.py'),
        controller_source_commit=plan['source_commit'], parent_pid=os.getppid(), launcher_pid=os.getpid(),
        plan=ref, approval=approval_ref, phase_id=plan['phase_id'], started_at=started_utc, command=command,
        selected_pair=pair)
    util.write_new_json(directory / 'intent.json', identity)
    with (directory / 'child.log').open('xb') as log:
        try:
            child = popen(command, repo, log)
        except Exception as exc:
            marker = latch_stop(plan, ref, directory, 'child_spawn_failed', pair)
            result = dict(operational_complete=False, child_spawned=False, stop=marker, error_type=type(exc).__name__)
        else:
            try:
                util.write_new_json(directory / 'registration.json', dict(**identity, child_pid=child.pid))
                result = supervise(repo, plan, ref, directory, child, started, pair)
            except BaseException as exc:
                result = dict(operational_complete=False, first_fault=type(exc).__name__,
                              **stop_owned(plan, ref, repo, directory, child,
                                           'registration_or_supervision_' + type(exc).__name__, pair))
        result.update(kind='live_pilot_launcher_result_v1', plan=ref, approval=approval_ref,
                      source_sha256=identity['source_sha256'], controller_source_commit=plan['source_commit'],
                      launch_id=identity['launch_id'], launcher_pid=os.getpid(),
                      child_pid=child.pid if 'child' in locals() else None, selected_pair=pair)
        try:
            util.write_new_json(directory / 'result.json', result)
        except BaseException as exc:
            # Missing durable launcher result is a hold even if the pipeline
            # appeared healthy. Preserve STOP; never return apparent success.
            if 'child' in locals():
                failure = stop_owned(plan, ref, repo, directory, child, 'launcher_result_write_failure', pair)
            else:
                failure = dict(stop=latch_stop(plan, ref, directory, 'launcher_result_write_failure', pair))
            try:
                util.write_new_json(directory / 'result-write-failure.json', dict(first_fault=type(exc).__name__,
                    operational_complete=False, **failure))
            except Exception:
                pass
            raise
    return result


def internal(action, repo, plan_path, directory, digest, instance=None):
    """Only bounded launcher-owned helper children, never a model dispatch."""
    repo, directory = live_pilot.safe_path(repo), live_pilot.safe_path(directory)
    ref = dict(path=str(live_pilot.safe_path(plan_path)), sha256=digest)
    plan = util.read_json(live_pilot.checked(ref))
    # Immutable intent remains authoritative if child-PID registration I/O fails.
    registration_path = directory / 'registration.json'
    registration = util.read_json(registration_path if registration_path.exists() else directory / 'intent.json')
    pair = registration.get('selected_pair')
    if (directory != live_pilot.safe_path(scope_root(plan, pair) / '_launcher')
            or registration.get('plan') != ref or registration.get('phase_id') != plan['phase_id']
            or registration.get('source_sha256') != util.sha256_file(repo / 'research/live_pilot_launcher.py')):
        raise ValueError('Foreign launcher helper binding')
    if action == '_verify':
        from research import acquisition_readiness
        proof = (acquisition_readiness._pilot_pipeline_evidence(repo, ref, _check_result(plan, ref, pair)) if pair is None
                 else verify_main_terminal(repo, plan, ref, pair))
        util.write_new_json(directory / 'terminal-proof.json', proof)
        return proof
    stop_paths = (Path(plan['batch']) / '_control/dispatch-stop.json', directory / 'stop.json')
    matching_stop = False
    for path in stop_paths:
        try:
            matching_stop = matching_stop or util.read_json(path).get('plan_sha256') == digest
        except (OSError, ValueError):
            pass
    if not matching_stop:
        raise ValueError('Matching durable STOP required')
    row = next((row for row in owned_runs(plan, ref, pair) if row['run_instance_id'] == instance), None)
    if row is None or row['status'] != 'owned_allocated':
        raise ValueError('Cannot stop foreign/unallocated/unreadable runtime')
    receipt = runtime.request_stop(row['root'])
    receipt = dict(receipt, run_instance_id=instance)
    util.write_new_json(directory / 'stops' / instance / 'result.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('execute', '_stop', '_verify'))
    parser.add_argument('plan', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--instance')
    parser.add_argument('--pair', type=int)
    args = parser.parse_args()
    if args.action == 'execute':
        if args.approval is None:
            parser.error('execute requires --approval')
        result = launch(args.repo, args.plan, args.approval, args.pair)
        return 0 if result.get('operational_complete') is True else 2
    if args.directory is None or args.plan_sha256 is None:
        parser.error('internal action requires registration directory and plan hash')
    internal(args.action, args.repo, args.plan, args.directory, args.plan_sha256, args.instance)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
