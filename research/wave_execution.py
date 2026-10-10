"""Existing real harness adapters for central waves; no live CLI.

Construction and execution require an explicit parent-frozen phase/approval and
health/publication callbacks. Prospective diagnostics assets are frozen from a
separately witnessed preparation view; existing Run conditions stay unchanged.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from outer.harness import profiles, run, runtime, util
from research import next_phase_execution, wave_plan

EDUCATION_SOURCE = 'inner/evaluator/Education.Evaluator/Program.cs'
DIAGNOSTICS_REVISION = 'education-1.0.0-diagnostics-1'
OLD_EDUCATION_SOURCE_SHA256 = '9476e6e60b85d927b59079b9816492bffa6ec92c86d337a0638136124fd03003'
NEW_EDUCATION_SOURCE_SHA256 = '5552b4d68e32fd91c451be2e4ec5beae4383f2f7890b16c0a7679d511568b162'


def preparation_witness(phase, original):
    view = phase.get('preparation_view', {})
    reference = view.get('witness', {})
    if not reference or util.sha256_file(reference['path']) != reference.get('sha256'):
        raise ValueError('Hash-bound prospective diagnostics witness required')
    witness = util.read_json(reference['path'])
    specs = {name: digest for name, digest in original['pinned_files'].items() if name.startswith('inner/spec/')}
    if (witness.get('kind') != 'prospective_preparation_view_diagnostics_v1'
            or witness.get('original_bundle_sha256') != phase['original_bundle']['sha256']
            or witness.get('implementation_revision') != DIAGNOSTICS_REVISION
            or witness.get('old_source_sha256') != OLD_EDUCATION_SOURCE_SHA256
            or witness.get('new_source_sha256') != NEW_EDUCATION_SOURCE_SHA256
            or original['pinned_files'].get(EDUCATION_SOURCE) != OLD_EDUCATION_SOURCE_SHA256
            or witness.get('criteria_unchanged') is not True or witness.get('criteria_pins') != specs
            or not specs or not isinstance(witness.get('new_evaluator_sha256'), str)
            or len(witness['new_evaluator_sha256']) != 64):
        raise ValueError('Only the exact diagnostics-1 revision with unchanged criteria is allowed')
    for key in ('equivalence_receipt', 'nonlive_acceptance'):
        ref = witness.get(key, {})
        if not ref or util.sha256_file(ref['path']) != ref.get('sha256'):
            raise ValueError('Diagnostics witness evidence missing or changed: ' + key)
    return witness


def validate_preparation(view, phase):
    """Offline byte checks; no Run creation, compiler, scorer, key or network."""
    view = Path(view).resolve()
    if view != Path(phase['preparation_view']['path']).resolve(): raise ValueError('Wrong preparation view')
    if util.sha256_file(phase['original_bundle']['path']) != phase['original_bundle']['sha256']:
        raise ValueError('Original bundle bytes changed')
    original = util.read_json(phase['original_bundle']['path'])
    witness = preparation_witness(phase, original)
    # Every old pinned non-runtime byte is preserved, except the one exact
    # source revision. This includes all other inner source, oracle, criteria,
    # task profiles, intervention, worker/runtime code, model-facing inputs.
    for name, digest in original['pinned_files'].items():
        if name.startswith('artifacts/runtime/'): continue
        wanted = NEW_EDUCATION_SOURCE_SHA256 if name == EDUCATION_SOURCE else digest
        if util.sha256_file(view / name) != wanted:
            raise ValueError('Preparation view changed frozen source/criteria/input: ' + name)
    tasks = original['plan']['task_ids']
    if set(witness.get('runtime_locks', {})) != set(tasks): raise ValueError('All four view runtime locks required')
    allowed = {'evaluator_files', 'evaluator_sha256', 'evaluator_build', 'build_id', 'created_at'}
    for task in tasks:
        preset = profiles.read(view, 'runtimes', phase['runtime'])
        root = profiles.runtime_root(view, task, preset)
        reference = witness['runtime_locks'][task]
        if (Path(reference['path']).resolve() != (root / 'lock.json').resolve()
                or util.sha256_file(root / 'lock.json') != reference['sha256']):
            raise ValueError('Prepared lock path/hash mismatch: ' + task)
        lock, old = util.read_json(root / 'lock.json'), original['runtime_locks'][task]
        if task.startswith('MS1-'):
            if lock != old: raise ValueError('Music evaluator/runtime lock must remain unchanged')
        else:
            if (set(lock) != set(old) or any(lock[k] != old[k] for k in old if k not in allowed)
                    or lock['evaluator_sha256'] != witness['new_evaluator_sha256']
                    or lock['evaluator_build'].get('implementation_revision') != DIAGNOSTICS_REVISION
                    or lock['evaluator_build'].get('clean_worktree') is not True):
                raise ValueError('Education runtime permits only the witnessed evaluator build change')
        if util.tree_hashes(root / 'evaluator') != lock['evaluator_files']:
            raise ValueError('Prepared evaluator tree changed: ' + task)
        dll = 'MusicStore.Evaluator.dll' if task.startswith('MS1-') else 'Education.Evaluator.dll'
        if util.sha256_file(root / 'evaluator' / dll) != lock['evaluator_sha256']:
            raise ValueError('Prepared evaluator assembly hash changed: ' + task)
    equivalence = util.read_json(witness['equivalence_receipt']['path'])
    rows = equivalence.get('eight_task_arm_prompt_and_model_input_equivalence', [])
    if (equivalence.get('original_bundle_sha256') != phase['original_bundle']['sha256']
            or equivalence.get('model_called') is not False or equivalence.get('run_created') is not False
            or equivalence.get('source_originals_changed') is not False or len(rows) != 8
            or {(r['task'], r['arm']) for r in rows} != {(t, a) for t in tasks for a in ('explore', 'preload')}):
        raise ValueError('Eight original task/arm equivalence records required')
    for row in rows:
        condition = profiles.resolve(view, row['task'], row['arm'], phase['runtime'])
        if condition.get('task_input_adapter') != 'migration-v1': raise ValueError('Unsupported input adapter')
        inputs = (view / condition['evaluation']['catalog_path']).parents[1] / 'inputs'
        prompt, _ = profiles.prepare_prompt(condition, inputs / 'legacy-source')
        actual = {name: util.tree_hashes(inputs / name) for name in ('legacy-source', 'existing-business')}
        if (row.get('public_and_hidden_profile_bytes_unchanged') is not True
                or util.sha256_bytes(prompt.encode('utf8')) != row['prompt_sha256']
                or actual != row['model_input_files']):
            raise ValueError('Original prompt/model input equivalence changed: ' + row['task'] + '/' + row['arm'])
    return witness


def preflight(repo, phase):
    original = wave_plan.validate(phase, repo=repo)
    # New code changes are explicit new-phase pins; all unchanged old assets
    # retain old byte checks. This does not call or weaken the old v5 checker.
    required = ('research/wave_plan.py', 'research/wave_dispatch.py',
                'research/wave_execution.py', 'research/pair_execution.py')
    if any(name not in phase['source_pins'] for name in required):
        raise ValueError('All new central execution modules must be frozen')
    for name, digest in original['pinned_files'].items():
        wanted = phase['source_pins'].get(name, digest)
        if util.sha256_file(Path(repo) / name) != wanted:
            raise ValueError('Frozen input/environment/code changed: ' + name)
    # An override must never silently replace a worker/runtime/task/input pin.
    allowed_changed = {'research/pair_execution.py', 'research/next_phase_execution.py',
                       'research/next_phase_sharing.py', 'research/tests/test_next_phase_sharing.py'}
    changed = {name for name, digest in original['pinned_files'].items()
               if phase['source_pins'].get(name, digest) != digest}
    witness = validate_preparation(phase['preparation_view']['path'], phase) if phase.get('preparation_view') else None
    if EDUCATION_SOURCE in changed:
        if witness is None: raise ValueError('Diagnostics source change requires a frozen prospective view')
        if phase['source_pins'].get(EDUCATION_SOURCE) != witness['new_source_sha256']:
            raise ValueError('Root diagnostics source differs from witnessed revision')
        allowed_changed.add(EDUCATION_SOURCE)
    if not changed <= allowed_changed:
        raise ValueError('New phase cannot alter original model-facing assets/runtime/evaluation criteria')
    return original


class HarnessAdapters:
    def __init__(self, repo, phase, *, postprocess=None, prepare_repo=None, validate_preparation=None):
        self.repo, self.phase = Path(repo), phase
        self.original = preflight(repo, phase)
        self.prepare_repo = Path(prepare_repo).resolve() if prepare_repo else self.repo.resolve()
        self.validate_preparation = validate_preparation
        if self.prepare_repo != self.repo.resolve():
            self.validate_preparation = self.validate_preparation or globals()['validate_preparation']
            view = phase.get('preparation_view', {})
            if Path(view.get('path', '.')).resolve() != self.prepare_repo:
                raise ValueError('Separate preparation view requires frozen equivalence witness validator')
            self.validate_preparation(self.prepare_repo, phase)
        self.batch = Path(phase['batch'])
        self.postprocess = postprocess or next_phase_execution.browser_postprocess(self.original)

    def prepare(self, binding):
        preflight(self.repo, self.phase)
        if self.validate_preparation: self.validate_preparation(self.prepare_repo, self.phase)
        return profiles.create(self.prepare_repo, self.batch, binding['task'], binding['condition'],
            binding['attempt'], self.phase['runtime'], run_instance_id=binding['run_instance_id'], assignment=binding)

    def verify(self, binding):
        preflight(self.repo, self.phase)
        if self.validate_preparation: self.validate_preparation(self.prepare_repo, self.phase)
        root = self.batch / binding['run_id']
        profiles.validate_run(root)
        manifest = util.read_json(root / 'manifest.json')
        if any(manifest.get(k) != binding.get(k) for k in ('run_id', 'run_instance_id')):
            raise ValueError('Prepared original instance changed')
        if ('input_sha256' in binding and manifest['prompt_sha256'] != binding['input_sha256']
                or 'condition_sha256' in binding and manifest['condition_sha256'] != binding['condition_sha256']):
            raise ValueError('Original model-facing input/condition bytes changed')

    def implement(self, repo, batch, run_id):
        return next_phase_execution.guarded_implementation(repo, batch, run_id)

    def fence(self, owned):
        """Initiate every gateway fence concurrently before any worker stop wait."""
        def gateway(binding):
            root = self.batch / binding['run_id']
            runtime_path = root / 'runtime.json'
            # A dispatched intent without runtime is ambiguous. Persist the
            # existing stop marker so a delayed startup cannot start the worker.
            if not (root / 'stop-request.json').exists():
                util.write_new_json(root / 'stop-request.json', {'requested_at': run.now(),
                    'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id']})
            if not runtime_path.exists():
                return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                    'confirmed': False, 'method': 'no_runtime_ambiguous_intent', 'observed_at': run.now()}
            value = util.read_json(runtime_path)
            if value['run_instance_id'] != binding['run_instance_id']:
                raise ValueError('Foreign runtime instance')
            return runtime.fence_owned(root)
        acknowledgements = []
        if owned:
            with ThreadPoolExecutor(max_workers=len(owned)) as pool:
                futures = {pool.submit(gateway, b): b for b in owned}
                for future in as_completed(futures):
                    try: acknowledgements.append(future.result())
                    except Exception as exc:
                        acknowledgements.append({'run_id': futures[future]['run_id'],
                            'run_instance_id': futures[future]['run_instance_id'],
                            'confirmed': False, 'error_type': type(exc).__name__})
        all_fenced = all(row.get('confirmed') is True for row in acknowledgements)
        effective = run.now() if all_fenced else None
        stops = []
        # All fence tasks have completed/retained uncertainty before this phase.
        def stop(binding):
            root = self.batch / binding['run_id']
            try:
                runtime.request_stop(root)
                return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                    'stop_confirmed': util.read_json(root / 'manifest.json').get('stop_confirmed', False)}
            except Exception as exc:
                return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                    'stop_confirmed': False, 'error_type': type(exc).__name__}
        if owned:
            with ThreadPoolExecutor(max_workers=len(owned)) as pool:
                stops = list(pool.map(stop, owned))
        return {'gateway_receipts': acknowledgements, 'http_fence_confirmed': all_fenced,
            'effective_stop_at': effective, 'worker_stops': stops,
            'limitation': 'Distributed ACK completion; host decision time is not an instantaneous global HTTP fence.'}

    def reconcile(self, binding):
        """Never starts a worker, never repeats a sent intent, preserves receipts."""
        root = self.batch / binding['run_id']
        manifest = util.read_json(root / 'manifest.json')
        if manifest['run_instance_id'] != binding['run_instance_id']: raise ValueError('Recovery instance mismatch')
        if not (root / 'runtime.json').exists():
            return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                'stop_confirmed': False, 'submission_fixed': False, 'ambiguous_dispatch': True}
        if not manifest.get('stop_confirmed'): runtime.request_stop(root)
        manifest = util.read_json(root / 'manifest.json')
        if not manifest.get('stop_confirmed'):
            return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                'stop_confirmed': False, 'submission_fixed': False}
        if not (root / 'snapshot.json').exists(): run.collect_run(self.batch, binding['run_id'])
        manifest = util.read_json(root / 'manifest.json')
        old = root / 'implementation-receipt.json'
        return {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
            'stop_confirmed': True, 'submission_fixed': manifest.get('submission_fixed', False),
            'manifest_sha256': util.sha256_file(root / 'manifest.json'),
            'snapshot_sha256': util.sha256_file(root / 'snapshot.json'), 'raw': util.tree_hashes(root / 'usage/raw'),
            'original_implementation_receipt': {'path': str(old), 'sha256': util.sha256_file(old)} if old.exists() else None,
            'recovered_without_send': True}
