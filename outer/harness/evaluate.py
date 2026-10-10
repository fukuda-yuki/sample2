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
from . import browser_review as browser_cart, browser_cleanup
from .security import child_environment

DEFAULT_EVALUATOR_DLL = 'inner/evaluator/MusicStore.Evaluator/bin/Release/net8.0/MusicStore.Evaluator.dll'
SCORING_TIMEOUT_SECONDS = 1800
SCORING_STATES = ('not_attempted', 'scored', 'evaluator_fault', 'evaluation_incomplete', 'rejected_mismatch',
                  'duplicate_sequence')


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


def read_duplicate_refusals(run_dir):
    """Duplicate-sequence refusals, kept apart from the run's own scorings.

    A duplicate sequence is an operator mistake, not a property of the run, so
    it must not displace the run's adopted scoring in `index.jsonl`.
    """
    return util.read_lines(Path(run_dir) / 'evaluations' / 'duplicate-refusals.jsonl')


def used_sequences(run_dir):
    """Sequences that already have a scoring, a work directory, or evidence logs.

    A sequence counts as used even when the index has no record for it. An
    interrupted attempt leaves a work directory or a log behind, and that trace
    is the only evidence it happened; reusing the number would overwrite it.
    """
    run_dir = Path(run_dir)
    used = {}

    def note(sequence, trace):
        if isinstance(sequence, int) and sequence > 0:
            used.setdefault(sequence, []).append(trace)

    for entry in read_index(run_dir):
        note(entry.get('sequence'), 'evaluations/index.jsonl')
    for entry in read_duplicate_refusals(run_dir):
        note(entry.get('sequence'), 'evaluations/duplicate-refusals.jsonl')
    work_root = run_dir / 'evaluation-work'
    if work_root.is_dir():
        for path in sorted(work_root.iterdir()):
            if path.is_dir() and path.name.isdigit():
                note(int(path.name), 'evaluation-work/' + path.name)
    evidence = run_dir / 'evidence'
    if evidence.is_dir():
        for path in sorted(evidence.glob('scoring-*-*.log')):
            digits = path.name.split('-')[1]
            if digits.isdigit():
                note(int(digits), 'evidence/' + path.name)
    return used


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
                       capture_output=True, env=child_environment())
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


def validate_repaired_scoring_provenance(repo, run_dir, condition, evaluator_path):
    """Bind a repaired scoring to the current prepared lock and immutable build.

    Historical build cleanliness is evidence, not current controller admission.
    An amended controller needs a fresh lock; this does not repair old Runs.
    """
    from . import profiles
    from research.repaired_runtime import validate_repaired_runtime_binding
    repo, run_dir = Path(repo).resolve(), Path(run_dir).resolve()
    if condition.get('schema_version') != 2 or condition.get('task_profile_revision') != 'evaluators-20261006':
        raise ValueError('Repaired scoring requires a frozen revised isolated condition')
    runtime_profile = condition.get('runtime') or {}
    current_runtime = profiles.read(repo, 'runtimes', runtime_profile.get('id'))
    if current_runtime != runtime_profile or util.read_json(run_dir/'profiles/runtime.json') != current_runtime:
        raise ValueError('Repaired scoring runtime profile mismatch')
    root = profiles.runtime_root(repo, condition['task_id'], current_runtime)
    lock = util.read_json(root/'lock.json')
    if condition.get('runtime_lock') != lock:
        raise ValueError('Frozen repaired lock differs from current prepared lock')
    validate_repaired_runtime_binding(repo, lock)
    task = profiles.task_profile(repo, condition['task_id'], condition['task_profile_revision'])
    if util.read_json(run_dir/'profiles/task.json') != task or condition.get('start_state') != task.get('start_state'):
        raise ValueError('Repaired scoring frozen task profile mismatch')
    evaluation = condition.get('evaluation') or {}
    expected = dict(task['evaluation'], executor='docker',
        spec_path='evaluation-assets/requirements.json', catalog_path='evaluation-assets/catalog.json',
        evaluator_sha256=lock['evaluator_sha256'], evaluator_build=lock['evaluator_build'])
    if evaluation != expected:
        raise ValueError('Repaired scoring evaluation/build differs from accepted binding')
    assets = run_dir/'evaluation-assets'
    bundle = assets/'evaluator'
    if (util.tree_hashes(bundle) != lock['evaluator_files']
            or Path(evaluator_path).resolve() != (bundle/evaluation['assembly']).resolve()
            or util.sha256_file(evaluator_path) != lock['evaluator_sha256']):
        raise ValueError('Repaired scoring copied evaluator bundle mismatch')
    expected_assets = {}
    for key, destination in [('spec_path', 'requirements.json'), ('catalog_path', 'catalog.json')]:
        expected_assets[destination] = util.sha256_file(repo/task['evaluation'][key])
    for source, destination in task['evaluation'].get('extra_assets', {}).items():
        if Path(destination).name != destination or ':' in destination or '\\' in destination:
            raise ValueError('Invalid extra evaluator asset name')
        original = (repo/source).resolve()
        if not original.is_relative_to(repo):
            raise ValueError('Extra evaluator asset escaped repository')
        expected_assets[destination] = util.sha256_file(original)
    actual_assets = {name: entry['sha256'] for name, entry in util.tree_hashes(assets).items()
                     if not name.startswith('evaluator/')}
    if actual_assets != expected_assets:
        raise ValueError('Repaired scoring specification/catalog/extra assets mismatch')
    return True


def saved_scoring_provenance(repo, original_repo, run_dir, condition, evaluator_path):
    """Validate frozen measurement assets at their source; separately record repair code."""
    from . import runtime
    repo, original_repo = Path(repo).resolve(), Path(original_repo).resolve()
    validate_repaired_scoring_provenance(original_repo, run_dir, condition, evaluator_path)
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True).strip():
        raise ValueError('Saved scoring recovery requires committed clean repair code')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    return dict(kind='saved_scoring_recovery_v1', original_repo=str(original_repo),
        repair_repo=str(repo), repair_commit=commit, model_calls=0,
        controller_files=runtime.controller_files(repo),
        browser_files={str(p.relative_to(repo)).replace('\\', '/'): util.sha256_file(p)
                       for p in sorted((repo/'inner/browser').glob('*.cjs'))},
        frozen_condition_sha256=util.sha256_file(Path(run_dir)/'condition.json'),
        evaluator_sha256=util.sha256_file(evaluator_path))


def finish_scoring_container(name, native_work, work_dir, out):
    """Export Linux scratch before removing its exact owned container/volume."""
    from . import runtime
    copied = None
    try:
        if native_work:
            halted = runtime.docker('stop', '--time', '10', name, check=False, timeout=25)
            if halted.returncode != 0:
                raise RuntimeError('Native scoring stop before export failed: '+name)
            copied = runtime.docker('cp', name+':/work/.', str(work_dir), check=False, timeout=180)
            util.write_new_json(Path(out)/'native-work-export.json', dict(
                container=name, storage='linux-volume', exported=copied.returncode == 0,
                destination=str(work_dir), exit_code=copied.returncode))
    finally:
        stopped = runtime.docker('rm', '-f', *(['-v'] if native_work else []), name, check=False)
        if stopped.returncode != 0:
            raise RuntimeError('Evaluator container stop could not be confirmed: '+name)
    if native_work and copied.returncode != 0:
        raise RuntimeError('Native scoring work export failed; see native-work-export.json')
    return stopped


def score_run(repo, runs_dir, run_id, *, evaluator=None, evaluation_version=None,
              sequence=None, timeout=SCORING_TIMEOUT_SECONDS, native_work=False, recovery_source_repo=None):
    repo = Path(repo).resolve()
    run_dir = run_mod.run_dir_for(runs_dir, run_id)
    manifest = run_mod.load_manifest(runs_dir, run_id)
    if not manifest.get('stop_confirmed'):
        raise RuntimeError('停止を確認していない Run は採点しません: ' + run_id)
    if not manifest.get('submission_fixed'):
        raise RuntimeError('成果物を固定していない Run は採点しません: ' + run_id)
    condition = util.read_json(run_dir / 'condition.json')
    isolated = condition.get('schema_version') == 2
    if isolated:
        from . import profiles
        profiles.validate_run(run_dir)
        if evaluator is not None:
            raise ValueError('Isolated Runs must use their frozen evaluator bundle')
        if evaluation_version is not None and evaluation_version != condition['evaluation']['evaluation_version']:
            raise ValueError('Isolated Runs must use their frozen evaluation version')
    evaluation = condition.get('evaluation') or {}
    asset_root = run_dir if isolated else repo
    spec = asset_root / (evaluation.get('spec_path') or 'inner/spec/requirements.json')
    catalog = asset_root / (evaluation.get('catalog_path') or 'inner/spec/catalog.json')
    if isolated:
        evaluator = run_dir / 'evaluation-assets/evaluator' / evaluation['assembly']
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
    recovery_provenance = None
    if (condition.get('task_profile_revision') == 'evaluators-20261006'
            or (condition.get('runtime') or {}).get('id') in ('deepseek-music-repaired-v1', 'deepseek-education-repaired-v1')
            or 'repaired_runtime_binding' in (condition.get('runtime_lock') or {})
            or pinned_build.get('binding_kind') == 'accepted_bundle_reuse_v1'):
        if recovery_source_repo is None:
            validate_repaired_scoring_provenance(repo, run_dir, condition, evaluator_path)
        else:
            recovery_provenance = saved_scoring_provenance(
                repo, recovery_source_repo, run_dir, condition, evaluator_path)
    elif pinned_evaluator:
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
    if recovery_source_repo is not None and recovery_provenance is None:
        raise ValueError('Saved recovery requires a frozen repaired measurement')
    evaluations = run_dir / 'evaluations'
    evaluations.mkdir(exist_ok=True)
    used = used_sequences(run_dir)
    if sequence is None:
        # 使用済みの最大の次を使う。件数で数えると、中断された試行が残した
        # 作業領域や証跡と衝突する（docs/outer-harness.md §6.6）。
        sequence = max(used) + 1 if used else 1
    else:
        sequence = int(sequence)
        if sequence in used:
            # 作業領域の削除・作成、既存ログのオープン、評価器の起動より前に拒否する。
            # 以前の採点の DB・ログ・記録はその採点の証跡であり、書き換えない。
            return _refuse_duplicate_sequence(
                run_dir, evaluations, sequence, used[sequence],
                run_id=run_id, version=version, independent_hash=util.artifact_hash(frozen),
                spec_sha256=spec_sha256,
                command=evaluator_command(repo, evaluator) + [
                    '--artifact', str(frozen), '--out', '', '--spec', str(spec),
                    '--catalog', str(catalog), '--evaluation-version', str(version),
                    '--sequence', str(sequence),
                    '--work', str(run_dir / 'evaluation-work' / '{:03d}'.format(sequence))],
                evaluator_sha256=evaluator_sha256)
    independent_hash = util.artifact_hash(frozen)
    # 採点ごとに空の作業ディレクトリを使う。前の採点の SQLite ファイルや生成物を
    # 引き継ぐと「毎回空のデータベースから始める」という初期条件を満たさない
    # （docs/quality-spec.md §4.1）。
    work_dir = run_dir / 'evaluation-work' / '{:03d}'.format(sequence)
    command = evaluator_command(repo, evaluator) + [
        '--artifact', str(frozen), '--out', '', '--spec', str(spec),
        '--catalog', str(catalog), '--evaluation-version', str(version),
        '--sequence', str(sequence), '--work', str(work_dir)]
    frozen_hash = run_mod.read_snapshot(run_dir).get('artifact_sha256')
    if frozen_hash != independent_hash:
        # 回収の時点で固定した成果物と frozen/ が違う。固定後の書き換えを採点して
        # 採用すると、固定した成果物に対する判定ではなくなる（docs/outer-harness.md §6.5）。
        return _refuse_scoring(
            run_dir, evaluations, sequence,
            [{'check': 'artifact_sha256', 'expected': frozen_hash, 'actual': independent_hash}],
            '回収時に固定した成果物と frozen/ の内容が一致しないため採点しません',
            run_id=run_id, version=version, independent_hash=independent_hash,
            spec_sha256=spec_sha256, command=command,
            evaluator_sha256=evaluator_sha256, artifact_sha256_frozen=frozen_hash)
    if pinned_evaluator and evaluator_sha256 != pinned_evaluator:
        # Refuse to score, but keep the attempt so the refusal is diagnosable
        # from the record alone (both values are in the mismatch entry).
        return _refuse_scoring(
            run_dir, evaluations, sequence,
            [{'check': 'evaluator_sha256', 'expected': pinned_evaluator,
              'actual': evaluator_sha256}],
            '評価器が条件に固定したビルドと一致しないため採点しません',
            run_id=run_id, version=version, independent_hash=independent_hash,
            spec_sha256=spec_sha256, command=command,
            evaluator_sha256=evaluator_sha256, evaluator_sha256_pinned=pinned_evaluator)
    # 使用済み連番は上で拒否しているので、既存の作業領域を消すことはない。
    # 消さずに残すのは、中断された試行の資材を保全するためである。
    work_dir.mkdir(parents=True)
    browser_required = browser_cart.required(str(version))
    temporary = evaluations / (('{}-{}-{}'.format('attempt' if browser_required else '.tmp', sequence, uuid.uuid4().hex)))
    temporary.mkdir(parents=True)
    if recovery_provenance is not None:
        util.write_new_json(temporary/'scoring-recovery-provenance.json', recovery_provenance)
    http_out = temporary / 'http-only' if browser_required else temporary
    http_out.mkdir(exist_ok=True)
    command[command.index('--out') + 1] = str(http_out)
    container_name = None
    if isolated:
        from . import runtime
        container_name, command = runtime.scoring_command(condition, frozen, http_out, work_dir,
            run_dir / 'evaluation-assets', str(version), sequence, native_work=native_work)
    evidence = run_dir / 'evidence'
    evidence.mkdir(exist_ok=True)
    environment = child_environment()
    # The repository's explicit non-model test double accepts three control inputs.
    # These are not inherited by real evaluators or isolated submissions.
    if evaluator_path.resolve() == (Path(__file__).resolve().parents[1] / 'tests/stub_evaluator.py'):
        environment.update({k: os.environ[k] for k in
            ('HARNESS_STUB_MODE', 'HARNESS_STUB_INVOCATIONS', 'HARNESS_STUB_MARKER') if k in os.environ})
    environment['PYTHONIOENCODING'] = 'utf-8'
    # 'xb' は既存のログを切り詰めない。使用済み連番は上で拒否しているので、
    # ここで既存のログを開くことはない。
    with (evidence / 'scoring-{:03d}-stdout.log'.format(sequence)).open('xb') as out, \
            (evidence / 'scoring-{:03d}-stderr.log'.format(sequence)).open('xb') as err:
        try:
            execution_command = (runtime.prepare_native_container(command, '/work', http_out/'native-work-init.json')
                                 if isolated and native_work else command)
            exit_code, timed_out = run_evaluator(execution_command, repo, environment, out, err, timeout)
        finally:
            if container_name:
                stopped = finish_scoring_container(container_name, native_work, work_dir, http_out)
    if browser_required and browser_cart.http_phase_eligible(condition,http_out,
            exit_code=exit_code,timed_out=timed_out,
            cleanup_confirmed=container_name is None or stopped.returncode==0,
            stopped=(run_dir/'STOP').exists(),frozen=frozen,artifact_hash=independent_hash,
            spec=spec,spec_hash=spec_sha256,evaluator_hash=evaluator_sha256):
        if isolated:
            exit_code = browser_cart.complete_evaluation(repo, condition, frozen, http_out, work_dir / 'publish',
                run_dir / 'evaluation-assets', temporary, manifest.get('run_instance_id'), sequence,
                **({'native_state': True} if native_work and str(version).startswith('education-') else {}))
        else:
            # The research browser runner requires the frozen isolated runtime.
            # Keep legacy HTTP output as evidence, never adopt it as research quality.
            exit_code = 2
    produced = temporary / 'evaluation.json'
    if (browser_required and not produced.is_file() and (timed_out or exit_code != 0)
            and (http_out / 'evaluation.json').is_file() and (http_out / 'results.jsonl').is_file()):
        baseline = util.read_json(http_out / 'evaluation.json')
        if (not check_mismatches(baseline, condition, version, frozen, independent_hash, spec, spec_sha256)
                and _reported_evaluator_sha256(http_out) == evaluator_sha256):
            # An observer failure before browser collection must retain already
            # confirmed, bound product failures; it never creates numeric quality.
            fallback = {**baseline, 'quality': None, 'researchStatus': 'incomplete',
                        'browserReviewCoverage': 'not_run_evaluator_fault',
                        'browserCartCoverage': 'not_run_evaluator_fault',
                        'reviewRunInstanceId': manifest.get('run_instance_id'),
                        'baselineEvaluationSha256': util.sha256_file(http_out / 'evaluation.json'),
                        'baselineResultsSha256': util.sha256_file(http_out / 'results.jsonl'),
                        'evaluatorFaults': baseline.get('evaluatorFaults') or ['HTTP evaluator exited before browser collection']}
            util.write_new_json(produced, fallback)
            shutil.copyfile(http_out / 'evaluator-manifest.json', temporary / 'evaluator-manifest.json')
            util.write_new_json(browser_cleanup._local_path(temporary) / 'browser-cleanup.json', {
                'confirmed': True, 'status': 'no_browser_resources_created', 'resources': [],
                'run_instance_id': manifest.get('run_instance_id'), 'artifact_sha256': independent_hash,
                'spec_sha256': spec_sha256, 'model_called': False, 'browser_observed': False,
                'evaluator_container': container_name,
                'evaluator_container_removed': container_name is None or stopped.returncode == 0,
                'scope': 'HTTP observer failed before browser launch; no browser resource intent or creation occurred'})
    if (timed_out and not browser_required) or not produced.is_file():
        target = evaluations / ('fault-{:03d}-{}'.format(sequence, uuid.uuid4().hex))
        record = _base_record(run_id, sequence, version, exit_code, independent_hash,
                              spec_sha256, 'evaluator_fault', None, [], command,
                              evaluator_sha256=evaluator_sha256,
                              evaluator_sha256_reported=_reported_evaluator_sha256(temporary),
                              timed_out=timed_out, timeout_seconds=timeout,
                              work_dir=str(work_dir), artifact_sha256_frozen=frozen_hash)
        temporary.rename(target)
        record['reason'] = ('評価器の実行が上限を超えたため停止しました'
                            if timed_out else '評価器が evaluation.json を出力しませんでした')
        _write_record(target, record)
        _append_index(run_dir, record)
        return record
    output = util.read_json(produced)
    mismatches = check_mismatches(output, condition, version, frozen, independent_hash, spec, spec_sha256)
    if mismatches:
        state = 'rejected_mismatch'
    elif browser_required and not browser_cart.coverage_complete(output):
        state = 'evaluator_fault' if output.get('evaluatorFaults') or (temporary/'browser-fault.json').exists() else 'evaluation_incomplete'
    else:
        state = 'scored' if exit_code == 0 or browser_required and exit_code == 3 else 'evaluator_fault'
    record = _base_record(run_id, sequence, version, exit_code, independent_hash,
                          spec_sha256, state, output, mismatches, command,
                          evaluator_sha256=evaluator_sha256,
                          evaluator_sha256_reported=_reported_evaluator_sha256(temporary),
                          timed_out=timed_out, timeout_seconds=timeout, work_dir=str(work_dir),
                          artifact_sha256_frozen=frozen_hash)
    record['evaluation_sha256'] = util.sha256_file(produced)
    record['operation_status'] = ('cleanup_failed' if browser_required
        and not browser_cleanup.latest(temporary)['confirmed'] else 'complete' if state == 'scored' else 'evaluation_incomplete')
    if record['operation_status'] == 'cleanup_failed':
        # A remaining Docker bind mount can prevent renaming this directory on
        # Windows. Its durable name is already known to the cleanup manifest.
        # Keep the quality and index here so cleanup-only recovery is possible.
        target = temporary
    elif state == 'scored':
        evaluation_id = output.get('evaluationId')
        # Evaluator-controlled IDs are labels, never authority over paths.
        valid_id = (isinstance(evaluation_id, str) and bool(evaluation_id)
                    and len(evaluation_id) <= 128 and evaluation_id not in ('.', '..')
                    and all(c.isascii() and (c.isalnum() or c in '-_.') for c in evaluation_id))
        target = evaluations / evaluation_id if valid_id else temporary
        if not valid_id or target.exists():
            record.update(scoring_state='rejected_mismatch', adopted=False, quality=None,
                          operation_status='evaluation_incomplete',
                          reason='evaluation_id_collision' if valid_id else 'unsafe_evaluation_id')
            record['mismatches'].append({'check': record['reason']})
            # Keep stdout, raw output, browser ownership and work evidence at
            # the already owned unique directory, including on interrupted retry.
            target = temporary
        else:
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
        same_path = (reported == '/artifact' if condition.get('schema_version') == 2 else
                     Path(reported or '').resolve() == Path(frozen).resolve())
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
                 timed_out=False, timeout_seconds=None, work_dir=None,
                 artifact_sha256_frozen=None):
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
        'artifact_sha256_frozen': artifact_sha256_frozen,
        'work_dir': work_dir,
        'verdict': (output or {}).get('verdict'),
        'browser_cart_coverage': (output or {}).get('browserCartCoverage', 'not_run_http_only'),
        'browser_cart_evidence_sha256': (output or {}).get('browserCartEvidenceSha256'),
        'browser_review_coverage': (output or {}).get('browserReviewCoverage'),
        'browser_review_evidence_sha256': (output or {}).get('browserReviewEvidenceSha256'),
        'research_status': (output or {}).get('researchStatus', 'incomplete'),
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


def _refuse_scoring(run_dir, evaluations, sequence, mismatches, reason, *, run_id,
                    version, independent_hash, spec_sha256, command,
                    evaluator_sha256=None, evaluator_sha256_pinned=None,
                    artifact_sha256_frozen=None):
    """Record a refused scoring attempt without invoking the evaluator.

    The attempt is kept so the refusal is diagnosable from the record alone:
    both the expected and the actual value are in the mismatch entry.
    """
    target = evaluations / ('rejected_mismatch-{:03d}-{}'.format(sequence, uuid.uuid4().hex))
    target.mkdir(parents=True)
    record = _base_record(run_id, sequence, version, None, independent_hash,
                          spec_sha256, 'rejected_mismatch', None, mismatches, command,
                          evaluator_sha256=evaluator_sha256,
                          evaluator_sha256_pinned=evaluator_sha256_pinned,
                          artifact_sha256_frozen=artifact_sha256_frozen)
    record['reason'] = reason
    record['directory'] = 'evaluations/' + target.name
    _write_record(target, record)
    _append_index(run_dir, record)
    return record


def _refuse_duplicate_sequence(run_dir, evaluations, sequence, traces, *, run_id, version,
                               independent_hash, spec_sha256, command,
                               evaluator_sha256=None):
    """Record a refused duplicate sequence without touching the earlier scoring.

    The earlier scoring's work directory, database, logs and records are the
    evidence for that scoring. Reusing the number would overwrite them, so the
    refusal is written to its own directory and its own log, and the run's
    adopted scoring in `index.jsonl` is left alone.
    """
    target = evaluations / ('duplicate_sequence-{:03d}-{}'.format(sequence, uuid.uuid4().hex))
    target.mkdir(parents=True)
    record = _base_record(run_id, sequence, version, None, independent_hash,
                          spec_sha256, 'duplicate_sequence', None, [], command,
                          evaluator_sha256=evaluator_sha256)
    record['reason'] = ('連番 {} は使用済みのため採点しません。既存の採点の作業領域・DB・'
                        'ログ・記録を書き換えないよう、評価器を起動する前に拒否しました。'
                        '同じ Run を採点し直すときは新しい連番を使ってください。'
                        .format(sequence))
    record['sequence_traces'] = traces
    record['directory'] = 'evaluations/' + target.name
    _write_record(target, record)
    _append_duplicate_index(run_dir, record)
    return record


def _append_duplicate_index(run_dir, record):
    util.append_line(Path(run_dir) / 'evaluations' / 'duplicate-refusals.jsonl',
                     {key: record[key] for key in
                      ('run_id', 'sequence', 'evaluation_version', 'scoring_state',
                        'adopted', 'evaluator_sha256', 'spec_sha256',
                        'artifact_sha256_outer', 'sequence_traces', 'reason',
                        'recorded_at', 'directory') if key in record})


def _append_index(run_dir, record):
    util.append_line(Path(run_dir) / 'evaluations' / 'index.jsonl',
                     {key: record[key] for key in
                      ('run_id', 'evaluation_id', 'sequence', 'evaluation_version',
                        'scoring_state', 'adopted', 'evaluator_exit_code',
                        'evaluator_sha256', 'evaluator_sha256_pinned', 'verdict',
                        'quality', 'spec_sha256', 'artifact_sha256_outer', 'mismatches',
                        'browser_cart_coverage', 'browser_cart_evidence_sha256', 'browser_review_coverage',
                        'browser_review_evidence_sha256', 'research_status',
                        'evaluation_sha256', 'operation_status',
                        'work_dir', 'recorded_at', 'directory') if key in record})


def publish_evaluator(repo):
    """Build the evaluator once. Not a scoring step."""
    project = Path(repo) / 'inner' / 'evaluator' / 'MusicStore.Evaluator' / 'MusicStore.Evaluator.csproj'
    completed = subprocess.run(['dotnet', 'build', str(project), '-c', 'Release', '--nologo', '-v', 'q'],
                               cwd=str(repo), env=child_environment())
    return completed.returncode
