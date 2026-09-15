"""Delegate scoring to the inner evaluator.

The outer harness does not decide pass or fail. It calls the evaluator, checks
that the result belongs to this run, and stores what came back unchanged.
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import run as run_mod
from . import util

DEFAULT_EVALUATOR_DLL = 'inner/evaluator/MusicStore.Evaluator/bin/Release/net8.0/MusicStore.Evaluator.dll'
SCORING_TIMEOUT_SECONDS = 1800
SCORING_STATES = ('not_attempted', 'scored', 'evaluator_fault', 'rejected_mismatch')


def evaluator_file(repo, evaluator=None):
    """The evaluator artifact this harness will invoke.

    `evaluation_version` names the *meaning* of the judgement. The build that
    produced the judgement is identified by this file's hash instead, so a
    rebuild that does not change the judgement does not need a new version.
    """
    if evaluator is None:
        path = Path(repo) / DEFAULT_EVALUATOR_DLL
    else:
        path = Path(evaluator)
    if not path.is_file():
        raise FileNotFoundError('評価器のアセンブリがありません: ' + str(path))
    return path


def evaluator_command(repo, evaluator=None):
    path = evaluator_file(repo, evaluator)
    if path.suffix == '.dll':
        return ['dotnet', str(path.resolve())]
    if path.suffix == '.py':
        return [sys.executable, str(path.resolve())]
    return [str(path.resolve())]


def read_index(run_dir):
    return util.read_lines(Path(run_dir) / 'evaluations' / 'index.jsonl')


def last_scoring(run_dir):
    entries = read_index(run_dir)
    return entries[-1] if entries else None


def _popen_kwargs():
    """Run the evaluator in its own process group.

    The evaluator starts the app under test as its own child. If the operator
    interrupts the harness, the evaluator must not be left alive without its
    child, so the harness takes the whole group down itself.
    """
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def kill_process_tree(process):
    """Kill the evaluator and every process it started."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                       capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()


def run_evaluator(command, repo, environment, out, err, timeout):
    """Run the evaluator and return (exit_code, timed_out).

    exit_code is -1 when the timeout fired, following the convention used by
    the inner evaluator for its own timeouts.
    """
    process = subprocess.Popen(command, cwd=str(repo), env=environment,
                               stdout=out, stderr=err, **_popen_kwargs())
    try:
        return process.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        kill_process_tree(process)
        return -1, True
    except BaseException:
        kill_process_tree(process)
        raise


def score_run(repo, runs_dir, run_id, *, evaluator=None, evaluation_version=None,
              sequence=None, timeout=SCORING_TIMEOUT_SECONDS):
    repo = Path(repo).resolve()
    run_dir = run_mod.run_dir_for(runs_dir, run_id)
    manifest = run_mod.load_manifest(runs_dir, run_id)
    if not manifest.get('stop_confirmed'):
        raise RuntimeError('停止を確認していない Run は採点しません: ' + run_id)
    if not manifest.get('submission_fixed'):
        raise RuntimeError('成果物を固定していない Run は採点しません: ' + run_id)
    condition = util.read_json(run_dir / 'condition.json')
    evaluation = condition.get('evaluation') or {}
    spec = repo / (evaluation.get('spec_path') or 'inner/spec/requirements.json')
    catalog = repo / (evaluation.get('catalog_path') or 'inner/spec/catalog.json')
    frozen = run_dir / 'frozen'
    if not frozen.is_dir():
        raise FileNotFoundError(frozen)
    spec_sha256 = util.sha256_file(spec)
    if evaluation.get('spec_sha256') and spec_sha256 != evaluation['spec_sha256']:
        raise RuntimeError('台帳が条件に固定したハッシュと一致しません。採点を拒否します: '
                           + spec_sha256)
    version = evaluation_version or evaluation.get('evaluation_version')
    if not version:
        raise RuntimeError('評価版が条件にありません')
    evaluator_path = evaluator_file(repo, evaluator)
    evaluator_sha256 = util.sha256_file(evaluator_path)
    pinned_evaluator = evaluation.get('evaluator_sha256')
    pinned_build = evaluation.get('evaluator_build') or {}
    if pinned_evaluator:
        # A pinned hash without its build provenance cannot be diagnosed later,
        # so it is refused as a condition error rather than scored and rejected.
        # `clean_worktree` is the source bytes: the hash moves with the line
        # endings of the evaluator sources, and a clean worktree is what makes
        # those bytes the recorded commit's bytes.
        missing = [key for key in ('source_path', 'command', 'sdk_version', 'sha256_origin',
                                   'clean_worktree')
                   if not pinned_build.get(key)]
        if missing:
            raise RuntimeError('評価器ビルドを固定するときは出所も条件に入れてください。'
                               '欠けている項目: ' + ', '.join(missing)
                               + '（clean_worktree は、固定値が .gitattributes の eol=lf のままの'
                                 'クリーンな作業ツリーで測られ、bin obj を消して作り直しても'
                                 '同じ値になったことを示す）')
    evaluations = run_dir / 'evaluations'
    evaluations.mkdir(exist_ok=True)
    existing = read_index(run_dir)
    sequence = int(sequence) if sequence is not None else len(existing) + 1
    independent_hash = util.artifact_hash(frozen)
    command = evaluator_command(repo, evaluator) + [
        '--artifact', str(frozen), '--out', '', '--spec', str(spec),
        '--catalog', str(catalog), '--evaluation-version', str(version),
        '--sequence', str(sequence), '--work', str(run_dir / 'evaluation-work')]
    temporary = evaluations / ('.tmp-{}-{}'.format(sequence, uuid.uuid4().hex))
    temporary.mkdir(parents=True)
    command[command.index('--out') + 1] = str(temporary)
    if pinned_evaluator and evaluator_sha256 != pinned_evaluator:
        # Refuse to score, but keep the attempt so the refusal is diagnosable
        # from the record alone (both values are in the mismatch entry).
        target = evaluations / ('rejected_mismatch-{:03d}-{}'.format(sequence, uuid.uuid4().hex))
        record = _base_record(run_id, sequence, version, None, independent_hash,
                              spec_sha256, 'rejected_mismatch', None,
                              [{'check': 'evaluator_sha256', 'expected': pinned_evaluator,
                                'actual': evaluator_sha256}], command,
                              evaluator_sha256=evaluator_sha256,
                              evaluator_sha256_pinned=pinned_evaluator)
        record['reason'] = '評価器が条件に固定したビルドと一致しないため採点しません'
        temporary.rename(target)
        record['directory'] = 'evaluations/' + target.name
        _write_record(target, record)
        _append_index(run_dir, record)
        return record
    evidence = run_dir / 'evidence'
    evidence.mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment['PYTHONIOENCODING'] = 'utf-8'
    with (evidence / 'scoring-{:03d}-stdout.log'.format(sequence)).open('wb') as out, \
            (evidence / 'scoring-{:03d}-stderr.log'.format(sequence)).open('wb') as err:
        exit_code, timed_out = run_evaluator(command, repo, environment, out, err, timeout)
    produced = temporary / 'evaluation.json'
    if timed_out or not produced.is_file():
        target = evaluations / ('fault-{:03d}-{}'.format(sequence, uuid.uuid4().hex))
        record = _base_record(run_id, sequence, version, exit_code, independent_hash,
                              spec_sha256, 'evaluator_fault', None, [], command,
                              evaluator_sha256=evaluator_sha256,
                              evaluator_sha256_reported=_reported_evaluator_sha256(temporary),
                              timed_out=timed_out, timeout_seconds=timeout)
        temporary.rename(target)
        record['reason'] = ('評価器の実行が上限を超えたため停止しました'
                            if timed_out else '評価器が evaluation.json を出力しませんでした')
        _write_record(target, record)
        _append_index(run_dir, record)
        return record
    output = util.read_json(produced)
    if exit_code == 2:
        state, mismatches = 'evaluator_fault', []
    else:
        mismatches = check_mismatches(output, condition, version, frozen, independent_hash,
                                      spec, spec_sha256)
        state = 'rejected_mismatch' if mismatches else 'scored'
    record = _base_record(run_id, sequence, version, exit_code, independent_hash,
                          spec_sha256, state, output, mismatches, command,
                          evaluator_sha256=evaluator_sha256,
                          evaluator_sha256_reported=_reported_evaluator_sha256(temporary),
                          timeout_seconds=timeout)
    if state == 'scored':
        evaluation_id = output.get('evaluationId')
        if not evaluation_id:
            raise RuntimeError('評価結果に evaluationId がありません')
        target = evaluations / evaluation_id
        if target.exists():
            shutil.rmtree(temporary, ignore_errors=True)
            raise FileExistsError('同じ評価 ID を 2 つ作らない: ' + str(target))
        temporary.rename(target)
    else:
        target = evaluations / ('{}-{:03d}-{}'.format(state, sequence, uuid.uuid4().hex))
        temporary.rename(target)
    record['directory'] = 'evaluations/' + target.name
    _write_record(target, record)
    _append_index(run_dir, record)
    return record


def check_mismatches(output, condition, version, frozen, independent_hash, spec, spec_sha256):
    checks = []
    if output.get('taskId') != condition.get('task_id'):
        checks.append({'check': 'task', 'expected': condition.get('task_id'),
                       'actual': output.get('taskId')})
    fixed_spec = (condition.get('evaluation') or {}).get('spec_sha256')
    actual_spec = util.sha256_file(spec)
    if output.get('specSha256') != fixed_spec:
        checks.append({'check': 'spec', 'expected': fixed_spec, 'actual': output.get('specSha256')})
    if fixed_spec and actual_spec != fixed_spec:
        checks.append({'check': 'spec_file', 'expected': fixed_spec, 'actual': actual_spec})
    if output.get('artifactSha256') != independent_hash:
        checks.append({'check': 'artifact', 'expected': independent_hash,
                       'actual': output.get('artifactSha256')})
    if output.get('evaluationVersion') != version:
        checks.append({'check': 'evaluation_version', 'expected': version,
                       'actual': output.get('evaluationVersion')})
    reported = output.get('artifactPath')
    try:
        same_path = Path(reported or '').resolve() == Path(frozen).resolve()
    except OSError:
        same_path = False
    if not same_path:
        checks.append({'check': 'artifact_path', 'expected': str(Path(frozen).resolve()),
                       'actual': reported})
    return checks


def _reported_evaluator_sha256(directory):
    """The evaluator's own statement about which build it is, when it made one."""
    path = Path(directory) / 'evaluator-manifest.json'
    if not path.is_file():
        return None
    return util.read_json(path).get('evaluatorSha256')


def _base_record(run_id, sequence, version, exit_code, independent_hash, spec_sha256,
                 state, output, mismatches, command, *, evaluator_sha256=None,
                 evaluator_sha256_reported=None, evaluator_sha256_pinned=None,
                 timed_out=False, timeout_seconds=None):
    return {
        'schema_version': 1,
        'run_id': run_id,
        'evaluation_id': (output or {}).get('evaluationId'),
        'sequence': sequence,
        'evaluation_version': version,
        'scoring_state': state,
        'adopted': state == 'scored',
        'evaluator_exit_code': exit_code,
        'evaluator_command': command,
        'evaluator_sha256': evaluator_sha256,
        'evaluator_sha256_reported': evaluator_sha256_reported,
        'evaluator_sha256_pinned': evaluator_sha256_pinned,
        'evaluator_timed_out': timed_out,
        'timeout_seconds': timeout_seconds,
        'spec_sha256': spec_sha256,
        'artifact_sha256_outer': independent_hash,
        'artifact_sha256_reported': (output or {}).get('artifactSha256'),
        'verdict': (output or {}).get('verdict'),
        'quality': (output or {}).get('quality'),
        'requirement_count': (output or {}).get('requirementCount'),
        'passed_count': (output or {}).get('passedCount'),
        'failed_count': (output or {}).get('failedCount'),
        'blocked_count': (output or {}).get('blockedCount'),
        'error_count': (output or {}).get('errorCount'),
        'mismatches': mismatches,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'note': ('evaluation.json が評価器の出力そのもの。このファイルは外側の記録。'
                 'adopted が false の採点は verdict と quality を申告値として残すだけで、'
                 '集計には使わない。'),
    }


def _write_record(target, record):
    util.write_new_json(target / 'record.json', record)


def _append_index(run_dir, record):
    util.append_line(Path(run_dir) / 'evaluations' / 'index.jsonl',
                     {key: record[key] for key in
                      ('run_id', 'evaluation_id', 'sequence', 'evaluation_version',
                        'scoring_state', 'adopted', 'evaluator_exit_code',
                        'evaluator_sha256', 'evaluator_sha256_pinned', 'verdict',
                        'quality', 'spec_sha256', 'artifact_sha256_outer', 'mismatches',
                        'recorded_at', 'directory') if key in record})


def publish_evaluator(repo):
    """Build the evaluator once. Not a scoring step."""
    project = Path(repo) / 'inner' / 'evaluator' / 'MusicStore.Evaluator' / 'MusicStore.Evaluator.csproj'
    completed = subprocess.run(['dotnet', 'build', str(project), '-c', 'Release', '--nologo', '-v', 'q'],
                               cwd=str(repo))
    return completed.returncode
