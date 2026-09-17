"""Operator's ordinary end-to-end workflow. Failed attempts remain in the ledger."""
from pathlib import Path
import uuid

from . import aggregate, evaluate, preserve, profiles, run, runtime, util


def execute(repo, runs_dir, task, intervention, attempt, runtime_id, archive):
    manifest = profiles.create(repo, runs_dir, task, intervention, attempt, runtime_id)
    rid = manifest['run_id']
    root = Path(runs_dir) / rid
    print('Running ' + rid, flush=True)
    try:
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
        reference = preserve.pack_run(archive, root, include=['evidence'])
        util.write_new_json(root / 'archive-reference.json', reference)
    row = aggregate.row_for(runs_dir, rid)
    row['archive'] = reference
    print(rid + ': ' + str(row['execution']['state']) + ', quality=' + str(row['quality']), flush=True)
    return row


def acceptance(repo, runs_dir, task, runtime_id):
    root = Path(runs_dir) / ('acceptance-' + uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    cases = [{'intervention': i, 'attempt': a} for a in (1, 2)
             for i in ('explore', 'preload', 'explained')]
    util.write_new_json(root / 'acceptance-plan.json', {'task': task, 'runtime': runtime_id,
        'cases': cases, 'criteria': ['completed', 'usage_complete', 'input_reached',
                                   'scored', 'monitor_readback', 'restored_rescore']})
    results = []
    for case in cases:
        try:
            row = execute(repo, root, task, case['intervention'], case['attempt'], runtime_id, root / '_archive')
        except Exception as exc:
            util.write_new_json(root / 'acceptance-failure.json', {'case':case, 'completed_runs':results,
                'complete':False, 'error_type':type(exc).__name__, 'message':str(exc)})
            raise
        rid = row['run_id']
        usage = run.read_usage(root / rid)
        telemetry = util.read_json(root / rid / 'telemetry-link.json')
        healthy = (row['execution']['state'] == 'completed' and row['scoring']['state'] == 'scored'
                   and usage.get('usage_complete') and usage.get('input_reached')
                   and telemetry.get('verified'))
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
