"""Operator's ordinary end-to-end workflow. Failed attempts remain in the ledger."""
from pathlib import Path
import json
import time
import uuid

from . import aggregate, evaluate, preserve, profiles, run, runtime, util


def fingerprint(value):
    return util.sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def timed_stage(receipt, stage, operation, *, binding):
    """Clock an owned local stage; persist identities and exception type only.

    Callers retain the usual ownership lock. Duration includes the durable
    start receipt and the operation, excludes writing the terminal receipt,
    and is independent of a Run's implementation budget. Sharing callers can
    use the same clock with their plan/cohort/pair/instance binding.
    """
    identity = {**binding, 'stage': stage, 'stage_instance': uuid.uuid4().hex}
    started = time.perf_counter()
    util.append_line(receipt, {**identity, 'event': 'stage_started', 'at': run.now()})
    try:
        result = operation()
    except BaseException as exc:
        util.append_line(receipt, {**identity, 'event': 'stage_failed', 'at': run.now(),
            'duration_seconds': time.perf_counter() - started, 'error_type': type(exc).__name__})
        raise
    util.append_line(receipt, {**identity, 'event': 'stage_completed', 'at': run.now(),
        'duration_seconds': time.perf_counter() - started})
    return result


def expected_conditions(repo, task, runtime_id, interventions):
    return {'task': fingerprint(profiles.read(repo, 'tasks', task)),
            'runtime': fingerprint(profiles.read(repo, 'runtimes', runtime_id)),
            'runtime_lock': fingerprint(util.read_json(profiles.runtime_root(
                repo, task, profiles.read(repo, 'runtimes', runtime_id)) / 'lock.json')),
            'interventions': {i:fingerprint(profiles.read(repo, 'interventions', i)) for i in interventions}}


def verify_conditions(root, expected, intervention):
    actual = {k:fingerprint(util.read_json(root/'profiles'/(k+'.json'))) for k in ('task','runtime')}
    actual['runtime_lock'] = fingerprint(util.read_json(root/'condition.json')['runtime_lock'])
    if any(actual[k] != expected[k] for k in actual) or (
        fingerprint(util.read_json(root/'profiles/intervention.json')) != expected['interventions'][intervention]):
        raise ValueError('Acceptance conditions changed after the batch plan; no model dispatched')


def implement(repo, runs_dir, run_id):
    """Implement and fix stopped originals now; no scorer/importer/archive here."""
    root = Path(runs_dir) / run_id
    try:
        runtime.start(repo, runs_dir, run_id)
    finally:
        manifest = run.load_manifest(runs_dir, run_id)
        collection_error = None
        try:
            if manifest.get('stop_confirmed') and not (root / 'snapshot.json').exists():
                run.collect_run(runs_dir, run_id)
        except BaseException as exc:
            collection_error = type(exc).__name__
            raise
        finally:
            manifest = run.load_manifest(runs_dir, run_id)
            receipt = {'run_id': run_id, 'run_instance_id': manifest['run_instance_id'],
                'stop_confirmed': manifest.get('stop_confirmed'), 'at': run.now(),
                'submission_fixed': manifest.get('submission_fixed', False),
                'collection_status': 'collection_fault' if collection_error else
                    ('fixed' if manifest.get('submission_fixed') else 'not_fixed'),
                'collection_error_type': collection_error,
                'manifest_sha256': util.sha256_file(root / 'manifest.json'),
                'raw': util.tree_hashes(root / 'usage/raw'),
                'snapshot_sha256': util.sha256_file(root / 'snapshot.json') if (root / 'snapshot.json').exists() else None}
            util.write_new_json(root / 'implementation-receipt.json', receipt)
    return receipt


def postprocess(repo, runs_dir, run_id, archive):
    """Idempotent serial continuation. Existing scoring/import/archive stays put."""
    root = Path(runs_dir) / run_id
    manifest = run.load_manifest(runs_dir, run_id)
    if not manifest.get('stop_confirmed'):
        raise RuntimeError('Unconfirmed stop blocks heavy postprocessing')
    implementation = root / 'implementation-receipt.json'
    if implementation.exists():
        saved = util.read_json(implementation)
        if saved.get('collection_status') == 'collection_fault' or saved.get('collection_error_type'):
            raise RuntimeError('Recorded collection fault blocks heavy postprocessing')
    timing = root / 'postprocess-timing.jsonl'
    binding = {**(manifest.get('assignment') or {}), 'run_id': run_id,
               'run_instance_id': manifest['run_instance_id']}
    scoring = evaluate.last_scoring(root)
    if scoring is None:
        # A started/incomplete scoring directory is uncertain, never rescore it
        # automatically after a crash.
        if evaluate.used_sequences(root):
            raise RuntimeError('Interrupted scoring requires explicit reconciliation')
        timed_stage(timing, 'scoring', lambda: evaluate.score_run(repo, runs_dir, run_id), binding=binding)
    else:
        util.append_line(timing, {**binding, 'stage': 'scoring', 'event': 'stage_reused',
            'at': run.now(), 'duration_seconds': None, 'reason': 'existing_scoring_retained'})
    from . import monitor
    timed_stage(timing, 'monitor_import_including_build', lambda: monitor.link(repo, root), binding=binding)
    reference_path = root / 'archive-reference.json'
    if reference_path.exists():
        reference = util.read_json(reference_path)
        timed_stage(timing, 'archive_verify',
            lambda: preserve.verify(archive, reference['package_id'], reference['sha256']), binding=binding)
    else:
        reference = timed_stage(timing, 'archive_pack_including_compression',
            lambda: preserve.pack_run(archive, root, include=['evidence', 'workspace']), binding=binding)
        util.write_new_json(reference_path, reference)
    row = aggregate.row_for(runs_dir, run_id)
    row['network_cleanup'] = manifest.get('network_cleanup')
    row['archive'] = reference
    row['postprocessing'] = {'receipt': str(timing.resolve()), 'receipt_sha256': util.sha256_file(timing),
                            'stages': util.read_lines(timing)}
    return row


def execute(repo, runs_dir, task, intervention, attempt, runtime_id, archive, *, expected=None):
    manifest = profiles.create(repo, runs_dir, task, intervention, attempt, runtime_id)
    rid = manifest['run_id']
    root = Path(runs_dir) / rid
    print('Running ' + rid, flush=True)
    try:
        if expected is not None:
            verify_conditions(root, expected, intervention)
        manifest = runtime.start(repo, runs_dir, rid)
        if manifest['stop_confirmed']:
            run.collect_run(runs_dir, rid)
            evaluate.score_run(repo, runs_dir, rid)
            from . import monitor
            monitor.link(repo, root)
    except Exception as exc:
        util.write_new_json(root / ('pipeline-error-' + uuid.uuid4().hex + '.json'),
                            {'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        # Also preserve interrupted, unscored and missing-usage attempts.
        reference = preserve.pack_run(archive, root, include=['evidence', 'workspace'])
        util.write_new_json(root / 'archive-reference.json', reference)
    row = aggregate.row_for(runs_dir, rid)
    row['network_cleanup'] = run.load_manifest(runs_dir, rid).get('network_cleanup')
    row['archive'] = reference
    print(rid + ': ' + str(row['execution']['state']) + ', quality=' + str(row['quality']), flush=True)
    return row


def acceptance(repo, runs_dir, task, runtime_id):
    root = Path(runs_dir) / ('acceptance-' + uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    cases = [{'intervention': i, 'attempt': a} for a in (1, 2)
             for i in ('explore', 'preload', 'explained')]
    expected = expected_conditions(repo, task, runtime_id, ('explore','preload','explained'))
    util.write_new_json(root / 'acceptance-plan.json', {'task': task, 'runtime': runtime_id,
        'cases': cases, 'condition_fingerprints': expected,
        'criteria': ['uniform_frozen_conditions', 'completed', 'usage_complete', 'input_reached',
                                   'scored', 'monitor_readback', 'restored_rescore']})
    results = []
    for case in cases:
        try:
            row = execute(repo, root, task, case['intervention'], case['attempt'], runtime_id, root / '_archive',
                          expected=expected)
        except Exception as exc:
            util.write_new_json(root / 'acceptance-failure.json', {'case':case, 'completed_runs':results,
                'complete':False, 'error_type':type(exc).__name__, 'message':str(exc)})
            raise
        rid = row['run_id']
        usage = run.read_usage(root / rid)
        telemetry = util.read_json(root / rid / 'telemetry-link.json')
        healthy = (row['execution']['state'] == 'completed' and row['scoring']['state'] == 'scored'
                   and usage.get('usage_complete') and usage.get('input_reached')
                   and telemetry.get('verified') and (row.get('network_cleanup') or {}).get('confirmed')
                   and row.get('operation_status') != 'cleanup_failed')
        results.append({'run_id': rid, 'healthy': bool(healthy), 'row': row})
        util.write_json_atomic(root / 'acceptance-progress.json', {'runs': results, 'complete': False})
        if not healthy:
            raise RuntimeError('Acceptance paused for repair: ' + rid + '; retained ' + str(root))
    # Restore a completed original to a different location, then invoke the same CLI scorer.
    first = results[0]['row']
    restored = root / '_restored' / first['run_id']
    preserve.restore(root / '_archive', first['archive'], restored)
    original = evaluate.last_scoring(root / first['run_id'])
    again = evaluate.score_run(repo, restored.parent, restored.name)
    restored_ok = all(original.get(k) == again.get(k) for k in ('quality', 'verdict', 'artifact_sha256_outer'))
    def judgments(base, scoring):
        data = util.read_json(base / scoring['directory'] / 'evaluation.json')
        return sorted((r['id'], r['judgement'], sorted(r.get('failedChecks', []))) for r in data['requirements'])
    restored_ok = restored_ok and judgments(root / first['run_id'], original) == judgments(restored, again)
    restored_row = aggregate.row_for(restored.parent, restored.name)
    if restored_row.get('operation_status') == 'cleanup_failed':
        raise RuntimeError('Restored evaluation cleanup failed; quality retained at ' + str(restored))
    restored_ok = restored_ok and all(first[k] == restored_row[k] for k in ('quality', 'verdict', 'usage', 'artifact'))
    if not restored_ok:
        raise RuntimeError('Restored scoring differs')
    table = aggregate.build(root)
    util.write_new_json(root / 'aggregate.json', table)
    util.write_new_json(root / 'comparison.json', aggregate.compare(root))
    result = {'runs': results, 'restored_rescore': restored_ok,
              'at_least_one_application_pass': any(r['row']['verdict'] == 'pass' for r in results),
              'complete': bool(restored_ok and any(r['row']['verdict'] == 'pass' for r in results)),
              'directory': str(root)}
    util.write_new_json(root / 'acceptance-result.json', result)
    return result
