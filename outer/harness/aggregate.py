"""Aggregate saved materials into one table.

Aggregation reads what was already saved. It does not re-evaluate artifacts and
it does not drop failed, unscored or incomplete runs.
"""
from datetime import datetime, timezone
from pathlib import Path

from . import evaluate
from . import run as run_mod
from . import util


def build(runs_dir):
    runs_dir = Path(runs_dir)
    rows = []
    for manifest_path in sorted(runs_dir.glob('*/manifest.json')):
        rows.append(row_for(runs_dir, manifest_path.parent.name))
    return {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'runs_dir': str(runs_dir),
        'source': '保存済み資材のみから作成した。成果物の再評価はしていない。',
        'run_count': len(rows),
        'columns_note': ('quality と total_tokens は別の列である。未採点は 0 ではなく null。'
                         'blocked は分母から落とさない。scoring.evaluation_version は判定の'
                         '意味の版、scoring.evaluator_sha256 は採点した評価器ビルドの同一性。'
                         '後者はソースの版ではなくビルドした場所と SDK を含むため、別環境での'
                         '一致を前提にしない。scoring.evaluator_sha256_pinned は条件が固定した'
                         '値で、固定していなければ null である。'),
        'runs': rows,
    }


def row_for(runs_dir, run_id):
    run_dir = run_mod.run_dir_for(runs_dir, run_id)
    manifest = run_mod.load_manifest(runs_dir, run_id)
    snapshot = run_mod.read_snapshot(run_dir)
    usage = run_mod.read_usage(run_dir)
    if usage.get('error') == 'usage_not_collected':
        usage['observed_tokens'] = None
    scoring = evaluate.last_scoring(run_dir)
    execution = run_mod.execution_state(manifest)
    artifact_state = snapshot.get('artifact_state')
    if artifact_state is None:
        artifact_state = 'fixed' if manifest.get('submission_fixed') else 'not_fixed'
    scoring_state = scoring['scoring_state'] if scoring else 'not_attempted'
    if scoring and 'adopted' in scoring:
        scored = bool(scoring['adopted'])
    else:
        scored = scoring_state == 'scored'
    issues = []

    if execution != 'completed':
        issues.append({'kind': 'execution', 'detail': execution})
    if not manifest.get('stop_confirmed'):
        issues.append({'kind': 'stop_unconfirmed',
                       'detail': manifest.get('stop_evidence') or '停止を確認していない'})
    if artifact_state != 'fixed':
        issues.append({'kind': 'artifact', 'detail': artifact_state})
    if scoring_state == 'evaluator_fault':
        issues.append({'kind': 'evaluator_fault',
                       'detail': (scoring.get('reason') or '評価側の障害。実行の失敗ではない')})
    elif scoring_state == 'rejected_mismatch':
        issues.append({'kind': 'mismatch', 'detail': scoring.get('mismatches')})
    elif scoring_state == 'not_attempted':
        issues.append({'kind': 'not_scored', 'detail': '採点していない'})
    if scored and scoring.get('verdict') in ('fail', 'fail_critical'):
        issues.append({'kind': 'quality', 'detail': scoring['verdict']})
    if scored and scoring.get('verdict') == 'blocked':
        issues.append({'kind': 'quality_blocked', 'detail': 'blocked を含む（分母から落とさない）'})
    if usage.get('state') != 'complete':
        issues.append({'kind': 'usage', 'detail': usage.get('error') or usage.get('missing')})
    if manifest.get('synthetic'):
        issues.append({'kind': 'synthetic',
                       'detail': 'ダミー実行器。実モデル実行の記録ではない'})

    return {
        'run_id': run_id,
        'run_instance_id': manifest.get('run_instance_id'),
        'task_id': manifest.get('task_id'),
        'condition_id': manifest.get('condition_id'),
        'intervention_id': manifest.get('intervention_id'),
        'attempt': manifest.get('attempt'),
        'runner': (manifest.get('runner') or {}).get('id'),
        'synthetic': manifest.get('synthetic'),
        'model_called': manifest.get('model_called'),
        'execution': {'state': execution, 'end_reason': manifest.get('end_reason'),
                      'exit_code': manifest.get('exit_code'),
                      'duration_seconds': manifest.get('duration_seconds')},
        'artifact': {'state': artifact_state,
                     'artifact_sha256': snapshot.get('artifact_sha256'),
                     'artifact_sha256_collected': snapshot.get('artifact_sha256_collected')},
        'scoring': {'state': scoring_state,
                    'evaluation_id': (scoring or {}).get('evaluation_id'),
                    'sequence': (scoring or {}).get('sequence'),
                    'evaluation_version': (scoring or {}).get('evaluation_version'),
                    'evaluator_sha256': (scoring or {}).get('evaluator_sha256'),
                    'evaluator_sha256_pinned': (scoring or {}).get('evaluator_sha256_pinned')},
        'quality': scoring.get('quality') if scored else None,
        'verdict': scoring.get('verdict') if scored else None,
        'usage': {'state': usage.get('state'),
                  'usage_complete': usage.get('usage_complete'),
                  'input_reached': usage.get('input_reached'),
                  'input_tokens': usage.get('input_tokens'),
                  'output_tokens': usage.get('output_tokens'),
                  'cache_read_tokens': usage.get('cache_read_tokens'),
                  'cache_write_tokens': usage.get('cache_write_tokens'),
                  'reasoning_tokens': usage.get('reasoning_tokens'),
                  'total_tokens': usage.get('total_tokens'),
                  'observed_tokens': usage.get('observed_tokens'),
                  'observed_request_count': usage.get('observed_request_count')},
        'issues': issues,
    }


def compare(runs_dir):
    """Descriptive comparisons only; never pool changed tasks or runtimes."""
    import json
    groups = {}
    for row in build(runs_dir)['runs']:
        manifest = run_mod.load_manifest(runs_dir, row['run_id'])
        profile_files = manifest.get('profile_files', {})
        identity = {'task': row['task_id'], 'intervention': row['condition_id'],
                    'condition_sha256': manifest.get('condition_sha256'),
                    'profiles': {k: v['sha256'] for k, v in profile_files.items()},
                    'evaluator_sha256': row['scoring'].get('evaluator_sha256')}
        key = json.dumps(identity, sort_keys=True)
        group = groups.setdefault(key, {'identity': identity, 'run_ids': [], 'quality': [],
            'verdicts': [], 'usage': [], 'execution_states': [], 'measured_count': 0})
        group['run_ids'].append(row['run_id'])
        group['quality'].append(row['quality'])
        group['verdicts'].append(row['verdict'])
        group['usage'].append(row['usage'])
        group['execution_states'].append(row['execution']['state'])
        if row['usage'].get('usage_complete'):
            group['measured_count'] += 1
    return {'source': 'saved Runs only; no model or evaluator was invoked',
            'groups': list(groups.values()),
            'note': 'Unscored quality and missing usage remain null. These small samples do not establish intervention effects.'}
