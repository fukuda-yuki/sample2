"""Finite v5 technical comparison, one gated pair per invocation.

Preparation is read-only except new owned artifacts. Execute is an explicit
model operation, never replay/resume. Publication uses next_phase_sharing with
exact-byte review. The second pair is blocked until the first real gate.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import threading
import time
import uuid

from outer.harness import live_usage, machine, profiles, runtime, util
from research import catalog_environment, next_phase, pair_execution, paired_acceptance
from research.next_phase_execution import browser_postprocess, guarded_implementation

LIMITS = {'maximum_dispatches': 4, 'run_seconds': 1800,
    'provider_timeout_seconds': 600, 'maximum_accumulated_run_seconds': 7200,
    'gateway_started_calls_stop': 600, 'reported_observed_tokens_stop': 20_000_000,
    'no_retries_or_replacements': True, 'order': [1, 2]}


class StopLatch:
    """Stop admission first; notify every owned root before waiting for stops."""
    def __init__(self, batch, cases, stop=runtime.request_stop):
        self.batch, self.cases, self.stop = Path(batch), cases, stop
        self.event, self.lock = threading.Event(), threading.RLock()
        self.path = self.batch / '_control/safety-stop.json'

    def stopped(self):
        return self.event.is_set() or self.path.exists()

    @contextmanager
    def admit(self, binding):
        with self.lock:
            if self.stopped(): raise RuntimeError('Technical campaign admission stopped')
            yield

    def latch(self, reason, **details):
        with self.lock:
            self.event.set()
            try:
                if not self.path.exists():
                    util.write_new_json(self.path, {'at': next_phase.now(), 'reason': reason, **details})
            except OSError:
                # The missing normal-completion receipt also bars the next block
                # after process loss if storage cannot retain this stop record.
                pass
        roots = []
        for case in self.cases:
            root = self.batch / case['run_id']
            if not (root / 'manifest.json').exists(): continue
            try:
                if util.read_json(root/'manifest.json').get('stop_confirmed') is True: continue
            except (OSError,ValueError):
                # A damaged current manifest cannot prevent notification of the
                # other owned root. Confirmation itself remains ownership-aware.
                pass
            try:
                util.write_json_atomic(root / 'stop-request.json', {'requested_at': next_phase.now(),
                    'source': 'finite_v5_technical_comparison', 'reason': reason})
            except OSError: pass
            if (root / 'runtime.json').exists(): roots.append(root)
        def confirm(root):
            try: return self.stop(root)
            except Exception: return {'stop_confirmed': False}
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(confirm, roots))


class PreparedRuns:
    """Observe only identities explicitly registered after complete preparation.

    profiles.create publishes an intermediate manifest before adding its fixed
    instance and frozen profile receipts. Directory existence is not readiness.
    Once registered, missing or changed identity remains a hard monitor fault.
    """
    def __init__(self, batch):
        self.batch, self.lock, self.ready = Path(batch), threading.Lock(), {}

    def register(self, case):
        manifest = util.read_json(self.batch / case['run_id'] / 'manifest.json')
        if (manifest['run_id'] != case['run_id']
                or manifest['run_instance_id'] != case['run_instance_id']):
            raise ValueError('Prepared monitoring identity mismatch')
        with self.lock:
            self.ready[case['run_id']] = dict(case)

    def manifests(self):
        with self.lock:
            cases = list(self.ready.values())
        for case in cases:
            root = self.batch / case['run_id']
            manifest = util.read_json(root / 'manifest.json')
            if (manifest['run_id'] != case['run_id']
                    or manifest['run_instance_id'] != case['run_instance_id']):
                raise ValueError('Registered monitoring identity mismatch')
            yield root, case, manifest


def resource_owners(batch, active):
    owners = []
    for root, case in active:
        if not (root / 'runtime.json').exists(): continue
        state = util.read_json(root / 'runtime.json')
        if state['run_instance_id'] != case['run_instance_id']:
            raise ValueError('Stats owner mismatch')
        # started_at precedes allocation. Stats cannot observe a worker until
        # Docker has created it; worker_started_at is recorded after create.
        if state.get('worker_started_at') and not state.get('stop_confirmed'):
            owners.append({'name': state['worker'], 'run_instance_id': case['run_instance_id']})
    return owners


def serializer_applicability(repo, record, plan):
    """Rebind preserved originals only if every serializer dependency is equal."""
    prior = paired_acceptance.read_reference(record['prior_bundle'])
    witness = paired_acceptance.read_reference(record['ordinary_worker_witness'])
    accepted = prior['acceptance_ledger']['serialized_intervention']
    if (record.get('kind') != 'v5_preserved_serializer_applicability'
            or accepted.get('status') != 'passed'
            or record['ordinary_worker_witness'] not in accepted['evidence']
            or record.get('asset_hashes') != accepted['asset_hashes']
            or record.get('asset_hashes') != next_phase.acceptance_scopes(prior['pinned_files'],prior['plan'])['serialized_intervention']):
        raise ValueError('Preserved serializer scope is not bound to its accepted originals')
    for ref in accepted['evidence']:
        paired_acceptance.read_reference(ref)
    for name, digest in record['asset_hashes'].items():
        if util.sha256_file(next_phase.inside(repo,name)) != digest:
            raise ValueError('Preserved serializer dependency changed: ' + name)
    if (witness.get('kind') != 'final_v3_public_prompt_actual_worker_acceptance'
            or witness.get('passed') is not True or witness.get('real_model_calls') != 0
            or witness.get('user_credential_reads') != 0 or witness.get('fixed_actual_worker_runs') != 2
            or witness.get('worker_retries_or_replacements') != 0
            or witness.get('collection_policy') != plan['settings']['collection_policy']
            or witness.get('run_budget_seconds') != 1800 or witness.get('provider_timeout_seconds') != 600
            or not witness.get('serialization_comparison')
            or not all(v is True for v in witness['serialization_comparison'].values())):
        raise ValueError('Bound ordinary-worker serializer acceptance required')
    scope = paired_acceptance.read_reference(witness['scope_at_dispatch'])
    inputs = paired_acceptance.read_reference(witness['eight_prepared_input_dependency_witness'])
    actual = paired_acceptance.read_reference(witness['new_ordinary_worker_result'])
    if (scope['task'] != 'MS1-CONT-A' or scope['runtime'] != plan['settings']['runtime_profile']
            or scope['controller_files'] != runtime.controller_files(repo)
            or actual.get('passed') is not True or len(actual['results']) != 2
            or inputs.get('passed') is not True or len(inputs['cases']) != 8):
        raise ValueError('Preserved serializer execution or eight-input coverage differs')
    expected = { (task,arm) for task in plan['task_ids'] for arm in plan['arms'] }
    covered=set()
    for case in inputs['cases']:
        covered.add((case['task'],case['arm']))
        if not case['checks'] or not all(v is True for v in case['checks'].values()):
            raise ValueError('Preserved input applicability was not established')
        lock = profiles.runtime_root(repo,case['task'],profiles.read(repo,'runtimes',plan['settings']['runtime_profile']))/'lock.json'
        if util.sha256_file(lock) != case['final_lock_sha256']:
            raise ValueError('Current runtime lock differs from preserved input acceptance')
    if covered != expected: raise ValueError('All eight fixed task/arm inputs required')
    originals={row['case']:row for row in witness['owned_stop_and_stopped_originals']}
    if set(originals) != {'actual-explore','actual-preload'}: raise ValueError('Both serializer arms required')
    for row in actual['results']:
        arm=row['case'].removeprefix('actual-'); root=Path(row['root']); original=originals[row['case']]
        condition=profiles.resolve(repo,'MS1-CONT-A',arm,plan['settings']['runtime_profile'])
        _settings_match(condition,plan)
        if (row.get('passed') is not True or row.get('ordinary_opencode_worker') is not True
                or row.get('real_model_calls') != 0 or row['runtime'] != condition['runtime']
                or row['run_instance_id'] != original['run_instance_id']
                or util.sha256_file(root/'manifest.json') != original['manifest_sha256']
                or util.tree_hashes(root/'usage/raw') != original['raw_sha256']
                or not util.read_json(root/'manifest.json').get('stop_confirmed')
                or original['actual_source_packets'].get('verified') is not True
                or original['actual_source_packets']['packet_count'] != (0 if arm=='explore' else 7)):
            raise ValueError('Original ordinary-worker serializer identity/raw/settings differ')
    return record


def rebind_serializer(repo, prior_bundle, witness, output):
    prior=util.read_json(prior_bundle)
    record={'kind':'v5_preserved_serializer_applicability','at':next_phase.now(),
        'prior_bundle':next_phase.reference(prior_bundle),
        'ordinary_worker_witness':next_phase.reference(witness),
        'asset_hashes':prior['acceptance_ledger']['serialized_intervention']['asset_hashes'],
        'no_new_worker_or_model_calls':True,'old_originals_unchanged':True}
    serializer_applicability(Path(repo).resolve(),record,next_phase.validate_plan(util.read_json(Path(repo)/next_phase.V5_PLAN)))
    util.write_new_json(output,record)
    return {'bound':True,'receipt':next_phase.reference(output),'model_called':False,'credential_read':False}


def prepare(repo, destination, browser_pin, serializer_witness, authorization):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if not destination.is_relative_to(repo / 'artifacts') or destination.exists():
        raise ValueError('Use a new owned technical preparation directory')
    if next_phase.git(repo, 'status', '--porcelain'):
        raise ValueError('Commit final code before freezing the technical comparison')
    plan = next_phase.validate_plan(util.read_json(repo / next_phase.V5_PLAN))
    browser = util.read_json(browser_pin)
    catalog_environment.validate(browser, repo)
    serializer_applicability(repo,util.read_json(serializer_witness),plan)
    if not Path(authorization).is_file():
        raise ValueError('Current user authorization source must be preserved')
    task, runtime_id = 'MS1-CONT-A', plan['settings']['runtime_profile']
    conditions = machine.expected_conditions(repo, task, runtime_id, plan['arms'])
    lock = util.read_json(profiles.runtime_root(repo, task,
        profiles.read(repo, 'runtimes', runtime_id)) / 'lock.json')
    if lock['controller_files'] != runtime.controller_files(repo):
        raise ValueError('Runtime controller changed')
    for arm in plan['arms']:
        condition = profiles.resolve(repo, task, arm, runtime_id)
        _settings_match(condition, plan)
    pins = {name: util.sha256_file(repo / name) for name in next_phase.git(repo, 'ls-files').splitlines()
        if (repo / name).is_file()}
    generated_roots = [profiles.runtime_root(repo, task, profiles.read(repo, 'runtimes', runtime_id))]
    from outer.harness import migration_input
    generated_roots.append(migration_input.prepare(repo, condition)['legacy-source'].parents[1])
    for generated_root in generated_roots:
        for asset in generated_root.rglob('*'):
            if asset.is_file(): pins[asset.relative_to(repo).as_posix()] = util.sha256_file(asset)
    assignments = []
    for pair, attempt in ((1, 90051), (2, 90052)):
        cases = [{'pair': pair, 'block': pair, 'slot': (pair - 1) * 2 + pos,
            'position': pos, 'task': task, 'condition': arm, 'attempt': attempt,
            'run_id': f'{task}-{arm}-{attempt}',
            'run_instance_id': uuid.uuid5(uuid.NAMESPACE_URL,
                next_phase.V5_SCIENTIFIC_SHA256 + f'/technical/{pair}/{arm}').hex}
            for pos, arm in enumerate(plan['arms'], 1)]
        assignments.append({'pair': pair, 'task': task, 'cases': cases})
    cohort = 'runs/_technical-sharing-v5-100p2-20261003'
    if (repo / cohort).exists():
        raise ValueError('Technical cohort already exists; no replay or replacement')
    destination.mkdir(parents=True)
    fixed = {**LIMITS, 'kind': 'finite_v5_technical_comparison_plan', 'created_at': next_phase.now(),
        'plan_reference': next_phase.reference(repo / next_phase.V5_PLAN),
        'source_commit': next_phase.git(repo, 'rev-parse', 'HEAD'), 'settings': plan['settings'],
        'conditions': conditions, 'assignments': assignments, 'cohort': cohort,
        'serializer_witness': next_phase.reference(serializer_witness),
        'authorization': next_phase.reference(authorization),
        'execution_asset_hashes': next_phase.acceptance_scopes(pins, plan)['execution_evidence'],
        'python': {'path':sys.executable,'version':sys.version,'sha256':util.sha256_file(sys.executable)},
        'minimum_next_pair_free_bytes':8_000_000_000,
        'total_time_boundary': 'execute-start through actual public/restore/cleanup pair-gate timestamp',
        'adoption': 'No control/original/usage/load defects; actual different-Run HTTP overlap; paired total time strictly less than serial; no quality/distribution-equivalence requirement.'}
    util.write_new_json(destination / 'fixed-comparison-plan.json', fixed)
    bundle = {'kind': 'continuity_sharing_technical_fixture', 'source_commit': fixed['source_commit'],
        'plan': plan, 'plan_reference': fixed['plan_reference'], 'assignments': assignments,
        'cohort': cohort, 'runtime_id': runtime_id, 'browser': {'record': browser,
            'reference': next_phase.reference(browser_pin)}, 'pinned_files': pins,
        'technical_plan': next_phase.reference(destination / 'fixed-comparison-plan.json')}
    util.write_new_json(destination / 'technical-bundle.json', bundle)
    return {'prepared': True, 'technical_bundle': next_phase.reference(destination / 'technical-bundle.json'),
        'model_called': False, 'credential_read': False, 'maximum_dispatches': 4}


def _settings_match(condition, plan):
    settings = plan['settings']
    for actual, expected in [('provider','provider'),('model_id','model_id'),('endpoint','endpoint'),
            ('timeout_seconds','run_budget_seconds'),('provider_timeout_seconds','provider_timeout_seconds'),
            ('opencode_version','opencode_version'),('model_context_tokens','model_context_tokens'),
            ('model_output_tokens','model_output_tokens'),('compaction','compaction'),('subagents','subagents')]:
        if condition['runtime'].get(actual) != settings[expected]:
            raise ValueError('Technical setting mismatch: ' + actual)
    if condition['runtime']['concurrency'] != 1 or condition['collection_policy'] != settings['collection_policy']:
        raise ValueError('Technical internal concurrency/collection policy mismatch')


def check(repo, bundle_path, *, environment=True):
    repo, bundle_path = Path(repo).resolve(), Path(bundle_path).resolve()
    bundle = util.read_json(bundle_path)
    next_phase.validate_plan(bundle['plan'])
    fixed = paired_acceptance.read_reference(bundle['technical_plan'])
    if (fixed.get('python') != {'path':sys.executable,'version':sys.version,'sha256':util.sha256_file(sys.executable)}
            or fixed.get('minimum_next_pair_free_bytes') != 8_000_000_000
            or shutil.disk_usage(repo).free < fixed['minimum_next_pair_free_bytes']):
        raise ValueError('Technical Python identity or next-pair storage admission failed')
    if (bundle.get('kind') != 'continuity_sharing_technical_fixture'
            or bundle.get('cohort') != 'runs/_technical-sharing-v5-100p2-20261003'
            or fixed.get('kind') != 'finite_v5_technical_comparison_plan'
            or any(fixed.get(k)!=v for k,v in LIMITS.items())
            or paired_acceptance.read_reference(bundle['plan_reference']) != bundle['plan']
            or paired_acceptance.read_reference(bundle['browser']['reference']) != bundle['browser']['record']):
        raise ValueError('Technical bundle format, fixed limits, or embedded references differ')
    cases=[c for pair in fixed['assignments'] for c in pair['cases']]
    if ([(p['pair'],p['task']) for p in fixed['assignments']] != [(1,'MS1-CONT-A'),(2,'MS1-CONT-A')]
            or len(cases)!=4 or [c['slot'] for c in cases]!=[1,2,3,4]
            or len({c['run_id'] for c in cases})!=4 or len({c['run_instance_id'] for c in cases})!=4
            or [c['condition'] for c in cases]!=bundle['plan']['arms']*2):
        raise ValueError('Fixed four technical slots/order/instances differ')
    serializer_applicability(repo,paired_acceptance.read_reference(fixed['serializer_witness']),bundle['plan'])
    if (next_phase.git(repo, 'rev-parse', 'HEAD') != bundle['source_commit']
            or next_phase.git(repo, 'status', '--porcelain')
            or fixed['source_commit'] != bundle['source_commit']
            or fixed['assignments'] != bundle['assignments'] or fixed['settings'] != bundle['plan']['settings']
            or fixed['cohort'] != bundle['cohort']):
        raise ValueError('Frozen technical source/assignments/settings changed')
    for name, digest in bundle['pinned_files'].items():
        if util.sha256_file(next_phase.inside(repo, name)) != digest:
            raise ValueError('Pinned technical asset changed: ' + name)
    for ref in (fixed['plan_reference'],fixed['serializer_witness'],fixed['authorization'],bundle['browser']['reference']):
        if not next_phase.verify_reference(ref): raise ValueError('Technical evidence changed')
    if environment:
        catalog_environment.validate(bundle['browser']['record'], repo)
    for arm in bundle['plan']['arms']:
        condition = profiles.resolve(repo, fixed['assignments'][0]['task'], arm, bundle['runtime_id'])
        _settings_match(condition,bundle['plan'])
        lock = util.read_json(profiles.runtime_root(repo,condition['task_id'],condition['runtime'])/'lock.json')
        if lock['controller_files'] != runtime.controller_files(repo):
            raise ValueError('Prepared technical controller changed')
        if environment:
            for image in lock['images'].values():
                if runtime.image_id(image) != image: raise ValueError('Pinned image unavailable')
    return bundle, fixed


def next_block(bundle, current):
    for selected in bundle['assignments']:
        number = selected['pair']
        if number in current['gates']: continue
        if any(c['run_id'] in current['reserved'] for c in selected['cases']):
            return None, 'explicit_recovery_or_publication_required'
        if number > 1 and number - 1 not in current['gates']:
            return None, 'previous_pair_gate'
        return selected, None
    return None, 'all_technical_pair_gates_complete'


def execute(repo, bundle_path):
    repo = Path(repo).resolve()
    bundle, fixed = check(repo,bundle_path)
    batch = next_phase.inside(repo,bundle['cohort'],'runs')
    current = pair_execution.state(batch / '_control/pair-journal.jsonl')
    selected, reason = next_block(bundle,current)
    if selected is None: return {'status':'held','reason':reason,'model_dispatched':False}
    number = selected['pair']
    batch.mkdir(parents=True,exist_ok=True)
    control = batch / '_control'
    control.mkdir(exist_ok=True)
    if (control / 'safety-stop.json').exists():
        return {'status':'held','reason':'technical_safety_stop','model_dispatched':False}
    if number > 1 and not (control / f'comparison-block-completed-{number-1}.json').exists():
        return {'status':'held','reason':'previous_technical_block_not_normally_completed','model_dispatched':False}
    start_path = control / f'execute-start-{number}.json'
    if start_path.exists():
        return {'status':'held','reason':'technical_start_uncertain_never_replayed','model_dispatched':False}
    util.write_new_json(start_path,{'at':next_phase.now(),'pair':number,
        'bundle_sha256':util.sha256_file(bundle_path),'technical_plan_sha256':bundle['technical_plan']['sha256']})
    done = threading.Event()
    latch = StopLatch(batch, selected['cases'])
    prepared = PreparedRuns(batch)
    # Previous gated blocks still contribute to the fixed cumulative limits.
    for previous in bundle['assignments']:
        if previous['pair'] not in current['gates']: continue
        for case in previous['cases']:
            profiles.validate_run(batch / case['run_id'])
            machine.verify_conditions(batch / case['run_id'], fixed['conditions'], case['condition'])
            prepared.register(case)
    resource_path = control / f'resource-samples-{number}.jsonl'
    def watch():
        next_sample = 0
        while not done.wait(1):
            active, total_tokens, count, seconds = [], 0, 0, 0
            fault = None
            for root, case, manifest in prepared.manifests():
                starts,se = live_usage.journal(root / 'usage/raw/started.jsonl')
                ends,ee = live_usage.journal(root / 'usage/raw/events.jsonl')
                count += len(starts)
                if se or ee: fault='damaged_usage_journal'
                for event in ends:
                    amounts=[(event.get('usage') or {}).get(k) for k in ('input_tokens','output_tokens')]
                    total_tokens += sum(v for v in amounts if type(v) is int and v >= 0)
                    if (any(type(v) is not int or v < 0 for v in amounts) or event.get('status') != 'completed'
                            or event.get('session_id') != case['run_instance_id']): fault='provider_or_missing_usage'
                if (root / 'usage/raw/failure.jsonl').exists(): fault='provider_fault'
                if manifest.get('duration_seconds') is not None: seconds += manifest['duration_seconds']
                elif manifest.get('started_at'):
                    seconds += (datetime.now(timezone.utc)-datetime.fromisoformat(manifest['started_at'])).total_seconds()
                if manifest.get('started_at') and not manifest.get('stop_confirmed'): active.append((root,case))
            if count >= fixed['gateway_started_calls_stop']: fault='call_safety_limit'
            if total_tokens >= fixed['reported_observed_tokens_stop']: fault='token_safety_limit'
            if seconds >= fixed['maximum_accumulated_run_seconds']: fault='run_time_safety_limit'
            if fault:
                latch.latch(fault, calls=count, observed_tokens=total_tokens, accumulated_run_seconds=seconds)
                return
            if active and time.monotonic() >= next_sample:
                next_sample = time.monotonic()+10
                owners=resource_owners(batch,active)
                if owners:
                    sampled_at=next_phase.now()
                    stats=runtime.docker('stats','--no-stream','--format','{{json .}}',
                        *[o['name'] for o in owners],timeout=20,check=False)
                    util.append_line(resource_path,{'at':sampled_at,'ended_at':next_phase.now(),'pair':number,
                        'bundle_sha256':util.sha256_file(bundle_path),'owners':owners,
                        'exit_code':stats.returncode,'samples':[json.loads(line) for line in stats.stdout.splitlines()
                            if line.strip()],'error_present':bool(stats.stderr.strip())})
                    if stats.returncode or stats.stderr.strip():
                        # A shutdown race is retained as a coverage gap. It
                        # still prevents adoption; do not confuse it with an
                        # active-worker monitoring fault requiring a stop.
                        if not resource_owners(batch,active): continue
                        raise RuntimeError('Resource monitor failed')
    def safe_watch():
        try: watch()
        except BaseException as exc:
            latch.latch('safety_monitor_fault', error_type=type(exc).__name__)
    watcher=threading.Thread(target=safe_watch,daemon=True)
    watcher.start()
    descriptor={'plan_sha256':util.sha256_file(bundle_path),'cohort':bundle['cohort'],
        'runtime':bundle['runtime_id'],'pair_concurrency':number,'require_fixed_instances':True}
    def prepare_run(binding):
        with latch.admit(binding):
            pass
        manifest=profiles.create(repo,batch,binding['task'],binding['condition'],binding['attempt'],
            bundle['runtime_id'],run_instance_id=binding['run_instance_id'],assignment=binding)
        machine.verify_conditions(batch/binding['run_id'],fixed['conditions'],binding['condition'])
        # Stop admission and registration share the stop lock: a preparation
        # finishing after a safety stop can never become dispatch-eligible.
        with latch.admit(binding):
            prepared.register(binding)
        return manifest
    def implement(repo, batch, rid):
        with latch.admit({'run_id':rid}):
            pass
        return guarded_implementation(repo,batch,rid)
    result = None
    try:
        result = pair_execution.execute_pair(descriptor,selected['cases'],batch,repo=repo,
            concurrency=number,prepare=prepare_run,implement=implement,
            postprocess=browser_postprocess(bundle),admit=latch.admit)
        if result.get('reason') != 'pair_publication_restore_cleanup_required':
            latch.latch('technical_block_fault', result_reason=result.get('reason'))
    except BaseException as exc:
        latch.latch('technical_block_exception', error_type=type(exc).__name__)
        raise
    finally:
        done.set()
        watcher.join(timeout=30)
        if watcher.is_alive():
            latch.latch('safety_monitor_stop_unconfirmed')
    if not latch.stopped():
        util.write_new_json(control / f'comparison-block-completed-{number}.json',
            {'at': next_phase.now(), 'pair':number, 'bundle_sha256':util.sha256_file(bundle_path),
             'technical_plan_sha256':bundle['technical_plan']['sha256'], 'result':result})
    return result


def adopt(repo,bundle_path,output):
    repo=Path(repo).resolve()
    bundle,fixed=check(repo,bundle_path,environment=False)
    batch=next_phase.inside(repo,bundle['cohort'],'runs')
    journal=batch/'_control/pair-journal.jsonl'
    if (batch/'_control/safety-stop.json').exists(): raise ValueError('Stopped technical campaign cannot be adopted')
    current=pair_execution.state(journal)
    blocks=[]
    for selected in bundle['assignments']:
        number=selected['pair']
        if number not in current['gates']: raise ValueError('Both actual technical gates required')
        start=batch/f'_control/execute-start-{number}.json'
        timing=util.read_json(start)
        end=current['gates'][number]['at']
        duration=(datetime.fromisoformat(end)-datetime.fromisoformat(timing['at'])).total_seconds()
        blocks.append({'concurrency':number,'pair':number,'technical_bundle':next_phase.reference(bundle_path),
            'journal':next_phase.reference(journal),'execute_start':next_phase.reference(start),
            'resource_samples':next_phase.reference(batch/f'_control/resource-samples-{number}.jsonl'),
            'normal_completion':next_phase.reference(batch/f'_control/comparison-block-completed-{number}.json'),
            'total_elapsed_seconds':duration})
    scopes=next_phase.acceptance_scopes(bundle['pinned_files'],bundle['plan'])
    receipt={'kind':'paired_execution_acceptance_v5','plan_sha256':fixed['plan_reference']['sha256'],
        'execution_asset_hashes':scopes['execution_evidence'],'maximum_dispatches':4,
        'research_runs_included':False,'fixed_comparison_plan':bundle['technical_plan'],'blocks':blocks}
    accepted=paired_acceptance.validate(receipt,bundle['plan'],scopes)
    util.write_new_json(output,{**receipt,'acceptance':accepted,'at':next_phase.now()})
    return accepted


def recover(repo,bundle_path):
    """Preservation of the original dispatched identities; never sends a model."""
    repo=Path(repo).resolve()
    bundle,_=check(repo,bundle_path,environment=False)
    batch=next_phase.inside(repo,bundle['cohort'],'runs')
    current=pair_execution.state(batch/'_control/pair-journal.jsonl')
    pending=[b for rid,b in current['dispatch'].items() if rid not in current['results']]
    if not pending: return {'status':'held','reason':'no_original_recovery_needed','model_dispatched':False}
    number=min(b['pair'] for b in pending)
    descriptor={'plan_sha256':util.sha256_file(bundle_path),'cohort':bundle['cohort'],
        'runtime':bundle['runtime_id'],'pair_concurrency':number,'require_fixed_instances':True}
    return pair_execution.recover_pair(descriptor,batch,repo=repo,postprocess=browser_postprocess(bundle))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('rebind-serializer','prepare','check','execute','recover','adopt'))
    parser.add_argument('--repo',type=Path,default=next_phase.REPO)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--browser',type=Path)
    parser.add_argument('--serializer-witness',type=Path)
    parser.add_argument('--authorization',type=Path)
    parser.add_argument('--prior-bundle',type=Path)
    args=parser.parse_args()
    if args.mode=='rebind-serializer':
        if not all((args.out,args.prior_bundle,args.serializer_witness)):
            parser.error('rebind-serializer requires --out --prior-bundle --serializer-witness')
        result=rebind_serializer(args.repo,args.prior_bundle,args.serializer_witness,args.out)
    elif args.mode=='prepare':
        if not all((args.out,args.browser,args.serializer_witness,args.authorization)):
            parser.error('prepare requires --out --browser --serializer-witness --authorization')
        result=prepare(args.repo,args.out,args.browser,args.serializer_witness,args.authorization)
    else:
        if not args.bundle: parser.error('--bundle required')
        if args.mode=='execute': result=execute(args.repo,args.bundle)
        elif args.mode=='recover': result=recover(args.repo,args.bundle)
        elif args.mode=='adopt':
            if not args.out: parser.error('adopt requires --out')
            result=adopt(args.repo,args.bundle,args.out)
        else:
            check(args.repo,args.bundle)
            result={'checked':True,'model_called':False,'credential_read':False}
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
