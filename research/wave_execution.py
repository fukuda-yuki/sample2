"""Existing real harness adapters for central waves; no live CLI.

Construction and execution require an explicit parent-frozen phase/approval and
health/publication callbacks. Evaluator overrides belong to a separately pinned
postprocessor, supplied by the research lead; original condition bytes stay put.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from outer.harness import machine, profiles, run, runtime, util
from research import next_phase_execution, wave_plan


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
                       'research/next_phase_sharing.py'}
    changed = {name for name, digest in original['pinned_files'].items()
               if phase['source_pins'].get(name, digest) != digest}
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
            view = phase.get('preparation_view', {})
            if Path(view.get('path', '.')).resolve() != self.prepare_repo or not validate_preparation:
                raise ValueError('Separate preparation view requires frozen equivalence witness validator')
            validate_preparation(self.prepare_repo, phase)
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
