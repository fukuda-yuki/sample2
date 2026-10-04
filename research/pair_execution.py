"""Bounded pair implementation under one OS lock, with serial postprocessing.

This API cannot authorize research or publish data. Its caller must first bind
an approved frozen plan and enforce admission. The old catalog driver remains
unchanged. No assigned dispatched identity is ever sent again, even if absent.
"""
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import uuid

from outer.harness import machine, profiles, run, runtime, util


@contextmanager
def exclusive(control, *, phase_permit=None):
    """Same byte-range dispatch.lock as the historical driver; no SciPy import."""
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    with (control / 'dispatch.lock').open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0'); stream.flush(); os.fsync(stream.fileno())
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            handoff = control / 'phase-handoff.json'
            successors = [(version, control / ('phase-handoff-v' + str(version) + '.json'))
                          for version in (2, 3)]
            if any(path.exists() for _, path in successors) and not handoff.exists():
                raise ValueError('Missing immutable predecessor handoff')
            if handoff.exists():
                marker = util.read_json(handoff)
                owner, owner_path = marker.get('phase_sha256'), marker.get('phase_path')
                parent_marker = handoff
                for version, successor in successors:
                    if not successor.exists():
                        if any(path.exists() for later, path in successors if later > version):
                            raise ValueError('Missing immutable intermediate handoff')
                        continue
                    changed = util.read_json(successor)
                    baseline, phase = changed.get('previous_handoff', {}), changed.get('new_phase', {})
                    if (changed.get('kind') != 'central_fixed_wave_successor_handoff_v' + str(version)
                            or Path(baseline.get('path', '')).resolve() != parent_marker.resolve()
                            or baseline.get('sha256') != util.sha256_file(parent_marker)
                            or changed.get('previous_phase_sha256') != owner
                            or not phase.get('path') or util.sha256_file(phase['path']) != phase.get('sha256')):
                        raise ValueError('Invalid or changed immutable successor handoff')
                    successor_phase = util.read_json(phase['path'])
                    previous = successor_phase.get('predecessor_phase', {})
                    if (successor_phase.get('kind') != 'source_info_v5_central_fixed_wave_phase_v' + str(version)
                            or previous.get('sha256') != owner
                            or not owner_path or Path(previous.get('path', '')).resolve() != Path(owner_path).resolve()
                            or successor_phase.get('original_bundle') != marker.get('original_bundle')
                            or changed.get('predecessor_journal') != successor_phase.get('predecessor_journal')
                            or changed.get('predecessor_gates') != successor_phase.get('predecessor_gates')):
                        raise ValueError('Successor does not preserve immutable ancestor chain')
                    owner, owner_path, parent_marker = phase['sha256'], phase['path'], successor
                if (marker.get('kind') != 'central_fixed_wave_handoff_v1'
                        or not owner or owner != phase_permit):
                    raise ValueError('Cohort handed off to central wave dispatcher; legacy entrypoint fenced')
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append(path, value):
    util.append_line(path, {'at': run.now(), **value})


def events(path):
    path = Path(path)
    if not path.exists(): return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Incomplete journal tail requires reconciliation')
    return [json.loads(line) for line in raw.decode('utf-8').splitlines()]


def state(journal):
    dispatch, implementations, results, gates, reserved = {}, {}, {}, {}, {}
    for event in events(journal):
        kind, rid = event['kind'], event.get('run_id')
        if kind == 'pair_reserved':
            for binding in event['assignments']:
                if binding['run_id'] in reserved:
                    raise ValueError('Duplicate reserved identity')
                reserved[binding['run_id']] = binding
        elif kind == 'dispatch':
            if rid in dispatch or not event.get('run_instance_id'):
                raise ValueError('Duplicate dispatch or absent instance')
            if rid not in reserved or any(event.get(k) != reserved[rid].get(k) for k in
                    ('plan_sha256','cohort','runtime','run_instance_id','pair','slot','condition_sha256','input_sha256')):
                raise ValueError('Dispatch differs from reserved identity')
            pending = [e for key, e in dispatch.items() if key not in implementations]
            if pending and (len(pending) >= 2 or pending[0]['pair'] != event['pair']):
                raise ValueError('Only two implementations from one pair may overlap')
            if any(e['pair'] < event['pair'] and e['pair'] not in gates for e in dispatch.values()):
                raise ValueError('Previous pair publication/restore/cleanup gate is pending')
            dispatch[rid] = event
        elif kind in ('implemented', 'stop_reconciled', 'result'):
            target = implementations if kind != 'result' else results
            replacing_unconfirmed = (kind == 'stop_reconciled' and rid in target
                and target[rid]['receipt'].get('stop_confirmed') is not True)
            if rid not in dispatch or (rid in target and not replacing_unconfirmed) or any(event.get(k) != dispatch[rid].get(k)
                    for k in ('run_instance_id', 'pair', 'slot', 'plan_sha256')):
                raise ValueError('Duplicate, unassigned or wrong-instance result')
            target[rid] = event
            receipt_path = event.get('receipt_path') if kind != 'result' else event.get('receipt')
            if not receipt_path or util.sha256_file(receipt_path) != event.get('receipt_sha256'):
                raise ValueError('Terminal receipt missing or changed')
            receipt = util.read_json(receipt_path)
            if kind == 'result':
                if receipt.get('row') != event.get('row') or any(receipt.get(k) != dispatch[rid].get(k)
                        for k in ('run_id','run_instance_id','pair','slot','plan_sha256','cohort','runtime')):
                    raise ValueError('Result row/binding differs from durable receipt')
            elif receipt.get('receipt') != event.get('receipt') or any(receipt.get('binding',{}).get(k) != dispatch[rid].get(k)
                    for k in ('run_id','run_instance_id','pair','slot','plan_sha256','cohort','runtime')):
                raise ValueError('Implementation receipt binding changed')
            baseline = (receipt.get('receipt') or {}).get('reconciles_implementation_receipt')
            if baseline and (not Path(baseline['path']).is_file()
                    or util.sha256_file(baseline['path']) != baseline['sha256']):
                raise ValueError('Stop reconciliation original receipt changed')
        elif kind == 'pair_gate':
            pair = event['pair']
            assigned = [r for r, d in dispatch.items() if d['pair'] == pair]
            if len(assigned) != 2 or not all(r in results for r in assigned) or pair in gates:
                raise ValueError('Pair gate without exactly two terminal results')
            path = Path(event['receipt'])
            if not path.is_file() or util.sha256_file(path) != event['receipt_sha256']:
                raise ValueError('Changed pair gate evidence')
            gates[pair] = event
    current = {'dispatch': dispatch, 'implementations': implementations, 'results': results,
            'reserved': reserved,
            'gates': gates, 'pending': [r for r in dispatch if r not in implementations]}
    for number, gate in gates.items():
        _validate_gate(util.read_json(gate['receipt']), current, number)
    return current


def _verify_plan(plan, current):
    if any(any(d.get(k) != plan.get(k) for k in ('plan_sha256','cohort','runtime'))
           for d in current['reserved'].values()):
        raise ValueError('Caller plan/cohort/runtime differs from durable assignments')


def _record_implementation(journal, binding, receipt, batch, kind='implemented'):
    path = batch / '_control' / ('implementation-' + binding['run_id'] + '-' + uuid.uuid4().hex + '.json')
    util.write_new_json(path, {'binding': binding, 'receipt': receipt})
    append(journal, {'kind': kind, **binding, 'receipt': receipt,
        'receipt_path': str(path), 'receipt_sha256': util.sha256_file(path)})


def _stop_active(futures, batch, stop):
    for future, binding in futures.items():
        if not future.done():
            try:
                stop(batch / binding['run_id'])
            except Exception as exc:
                util.write_new_json(batch / '_control' / ('peer-stop-' + uuid.uuid4().hex + '.json'),
                    {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                     'error_type': type(exc).__name__, 'stop_confirmed': False})


def execute_pair(plan, cases, batch, *, repo, concurrency=1, prepare=None,
                 implement=machine.implement, postprocess=machine.postprocess, stop=runtime.request_stop,
                 admit=None):
    """cases: two {run_id, task, condition, attempt, pair, slot} assignments.

    plan: {plan_sha256, cohort, runtime}. Caller checks plan/approval/resources.
    Existing completed receipt recovery is explicit via recover_pair; never
    automatically replay a dispatch or an uncertain postprocessing stage.
    """
    if concurrency not in (1, 2) or len(cases) != 2 or concurrency != plan.get('pair_concurrency', concurrency):
        raise ValueError('Exactly one pair and concurrency 1 or 2 required')
    if len({c['pair'] for c in cases}) != 1 or len({c['run_id'] for c in cases}) != 2:
        raise ValueError('Pair identity or Run identity mismatch')
    if len({c['slot'] for c in cases}) != 2:
        raise ValueError('Duplicate slot')
    fixed = [c.get('run_instance_id') for c in cases]
    if plan.get('require_fixed_instances') or any(value is not None for value in fixed):
        if (len(set(fixed)) != 2 or any(not isinstance(value, str) or len(value) != 32
                or any(ch not in '0123456789abcdef' for ch in value) for value in fixed)):
            raise ValueError('Two distinct preassigned instances required')
    batch = Path(batch)
    control = batch / '_control'
    with exclusive(control):
        journal = control / 'pair-journal.jsonl'
        current = state(journal)
        _verify_plan(plan, current)
        pair = cases[0]['pair']
        if any(e['pair'] < pair and e['pair'] not in current['gates'] for e in current['dispatch'].values()):
            return {'status': 'held', 'reason': 'previous_pair_gate'}
        if any(c['run_id'] in current['dispatch'] for c in cases):
            return {'status': 'held', 'reason': 'dispatched_identity_never_replayed'}
        if current['pending']:
            return {'status': 'held', 'reason': 'uncertain_implementation'}
        assignments = []
        # All identities and immutable inputs are allocated before either starts.
        for case in cases:
            if (batch / case['run_id']).exists():
                raise ValueError('Existing unassigned directory; never overwrite')
            binding = {**case, 'cohort': plan['cohort'], 'plan_sha256': plan['plan_sha256'],
                       'runtime': plan['runtime'],
                       'run_instance_id': case.get('run_instance_id') or uuid.uuid4().hex}
            if prepare:
                manifest = prepare(binding)
            else:
                manifest = profiles.create(repo, batch, case['task'], case['condition'], case['attempt'],
                    plan['runtime'], run_instance_id=binding['run_instance_id'], assignment=binding)
            if manifest['run_id'] != case['run_id'] or manifest['run_instance_id'] != binding['run_instance_id']:
                raise ValueError('Prepared Run identity differs from assignment')
            binding['input_sha256'] = manifest.get('prompt_sha256')
            binding['condition_sha256'] = manifest.get('condition_sha256')
            assignments.append(binding)
        append(journal, {'kind': 'pair_reserved', 'pair': pair, 'concurrency': concurrency,
                         'assignments': assignments})
        fault = False
        # Journal mutation stays on this one manager thread. A child writes its
        # implementation-receipt before returning; manager loss cannot lose it.
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {}
            try:
                for binding in assignments:
                    for future in list(futures):
                        if future.done():
                            prior = futures.pop(future)
                            receipt, failed = _implementation_result(future, prior, batch)
                            _record_implementation(journal, prior, receipt, batch)
                            fault = fault or failed
                    if fault:
                        _stop_active(futures, batch, stop)
                        break
                    # Admission and submission share the caller's stop-latch lock.
                    # A durable campaign stop therefore precedes or follows a
                    # dispatch unambiguously, including the serial second peer.
                    with admit(binding) if admit else nullcontext():
                        append(journal, {'kind': 'dispatch', **binding})
                        futures[pool.submit(implement, repo, batch, binding['run_id'])] = binding
                    if concurrency == 1:
                        future = next(iter(futures))
                        receipt, failed = _implementation_result(future, binding, batch)
                        _record_implementation(journal, binding, receipt, batch)
                        fault = fault or failed
                        futures.clear()
                        if fault: break
                for future in as_completed(futures):
                    binding = futures[future]
                    receipt, failed = _implementation_result(future, binding, batch)
                    _record_implementation(journal, binding, receipt, batch)
                    fault = fault or failed
                    if failed: _stop_active(futures, batch, stop)
            except BaseException:
                _stop_active(futures, batch, stop)
                raise
        current = state(journal)
        _verify_plan(plan, current)
        if fault or not all(c['run_id'] in current['implementations'] for c in cases):
            append(journal, {'kind': 'pause', 'pair': pair, 'reason': 'implementation_fault'})
            return {'status': 'held', 'reason': 'implementation_fault'}
        return _postprocess(plan, assignments, batch, repo, journal, postprocess)


def _implementation_result(future, binding, batch):
    try:
        receipt = future.result()
    except Exception as exc:
        path = batch / binding['run_id'] / 'implementation-receipt.json'
        receipt = util.read_json(path) if path.exists() else {'stop_confirmed': False}
        receipt = {**receipt, 'error_type': type(exc).__name__}
    failed = (receipt.get('run_id') != binding['run_id']
        or receipt.get('run_instance_id') != binding['run_instance_id']
        or receipt.get('stop_confirmed') is not True or bool(receipt.get('error_type')))
    root = batch / binding['run_id']
    if (root / 'manifest.json').exists():
        manifest = util.read_json(root / 'manifest.json')
        failed = failed or manifest.get('end_reason') in ('environment_failure', 'provider_failure', 'stop_unconfirmed')
        if manifest.get('schema_version') == 2:
            normalized = root / 'usage/normalized.json'
            failed = failed or not normalized.exists() or not util.read_json(normalized).get('usage_complete')
            failed = failed or not (manifest.get('network_cleanup') or {}).get('confirmed')
    return receipt, failed


def _postprocess_fault(row):
    return ((row.get('scoring') or {}).get('state') in
            ('evaluator_fault', 'rejected_mismatch', 'not_attempted')
            or row.get('operation_status') == 'cleanup_failed')


def _collection_hold(current, assignments):
    for binding in assignments:
        receipt = current['implementations'].get(binding['run_id'], {}).get('receipt', {})
        if receipt.get('collection_status') == 'collection_fault' or receipt.get('collection_error_type'):
            return {'status': 'held', 'reason': 'collection_fault', 'run_id': binding['run_id'],
                'stop_confirmed': receipt.get('stop_confirmed'),
                'submission_fixed': receipt.get('submission_fixed', False)}


def _postprocess(plan, assignments, batch, repo, journal, postprocess):
    current = state(journal)
    _verify_plan(plan, current)
    held = _collection_hold(current, assignments)
    if held: return held
    for binding in assignments:
        previous = current['results'].get(binding['run_id'])
        if previous and _postprocess_fault(previous['row']):
            return {'status': 'held', 'reason': 'postprocess_fault',
                    'run_id': binding['run_id'],
                    'scoring_state': (previous['row'].get('scoring') or {}).get('state')}
    for binding in assignments:
        rid = binding['run_id']
        implementation = current['implementations'].get(rid)
        if not implementation or implementation['receipt'].get('stop_confirmed') is not True:
            return {'status': 'held', 'reason': 'stop_barrier_unconfirmed'}
    append(journal, {'kind': 'barrier', 'pair': assignments[0]['pair'], 'both_stopped': True})
    for binding in assignments:
        if binding['run_id'] in current['results']:
            continue
        rid = binding['run_id']
        stage = batch / rid / 'postprocess-intent.json'
        if stage.exists():
            return {'status': 'held', 'reason': 'uncertain_postprocess_requires_reconciliation'}
        util.write_new_json(stage, binding)
        append(journal, {'kind': 'postprocess_start', **binding})
        try:
            row = postprocess(repo, batch, rid, batch / '_archive')
            receipt_path = batch / rid / 'postprocess-receipt.json'
            util.write_new_json(receipt_path, {**binding, 'row': row})
            append(journal, {'kind': 'result', **binding, 'row': row,
                'receipt': str(receipt_path), 'receipt_sha256': util.sha256_file(receipt_path)})
            scoring_state = (row.get('scoring') or {}).get('state')
            if _postprocess_fault(row):
                append(journal, {'kind': 'pause', **binding, 'reason': 'postprocess_fault',
                    'scoring_state': scoring_state, 'operation_status': row.get('operation_status')})
                return {'status': 'held', 'reason': 'postprocess_fault', 'run_id': rid,
                        'scoring_state': scoring_state}
        except Exception as exc:
            append(journal, {'kind': 'pause', 'pair': binding['pair'], 'reason': 'postprocess_fault',
                             'error_type': type(exc).__name__})
            return {'status': 'held', 'reason': 'postprocess_fault'}
    return {'status': 'held', 'reason': 'pair_publication_restore_cleanup_required',
            'pair': assignments[0]['pair'], 'runs': [b['run_id'] for b in assignments]}


def recover_pair(plan, batch, *, repo, stop=runtime.request_stop, postprocess=machine.postprocess):
    """Reconcile every dispatched Run; never start a worker or repeat send."""
    batch = Path(batch)
    with exclusive(batch / '_control'):
        journal = batch / '_control/pair-journal.jsonl'
        current = state(journal)
        _verify_plan(plan, current)
        assignments = [{k:v for k,v in d.items() if k not in ('at','kind')}
                       for d in current['dispatch'].values()]
        if not assignments:
            return {'status': 'held', 'reason': 'no_dispatch'}
        pair = max(b['pair'] for b in assignments)
        assignments = [b for b in assignments if b['pair'] == pair]
        for binding in assignments:
            rid = binding['run_id']
            root = batch / rid
            if not root.is_dir():
                return {'status': 'held', 'reason': 'dispatched_directory_missing', 'run_id': rid}
            manifest = util.read_json(root / 'manifest.json')
            if manifest['run_instance_id'] != binding['run_instance_id']:
                raise ValueError('Recovery instance mismatch')
            previous = current['implementations'].get(rid)
            saved_path = root / 'implementation-receipt.json'
            if not previous and saved_path.exists():
                saved_hash = util.sha256_file(saved_path)
                saved = util.read_json(saved_path)
                if saved.get('run_id') != rid or saved.get('run_instance_id') != binding['run_instance_id']:
                    raise ValueError('Saved implementation receipt instance mismatch')
                if saved.get('stop_confirmed') is True and (saved.get('collection_status') == 'collection_fault'
                        or saved.get('collection_error_type')):
                    snapshot = root / 'snapshot.json'
                    snapshot_hash = util.sha256_file(snapshot) if snapshot.exists() else None
                    if (saved.get('manifest_sha256') != util.sha256_file(root / 'manifest.json')
                            or saved.get('raw') != util.tree_hashes(root / 'usage/raw')
                            or saved.get('snapshot_sha256') != snapshot_hash
                            or util.sha256_file(saved_path) != saved_hash):
                        raise ValueError('Saved stopped collection receipt hashes changed')
                    recovered = {**saved, 'recovered': True,
                        'reconciles_implementation_receipt': {'path': str(saved_path.resolve()), 'sha256': saved_hash}}
                    _record_implementation(journal, binding, recovered, batch)
                    previous = state(journal)['implementations'][rid]
            if not previous or previous['receipt'].get('stop_confirmed') is not True:
                if not (root / 'runtime.json').exists() and not manifest.get('started_at'):
                    # runtime.json is durably written before container allocation.
                    # A dispatched identity is terminal here, never reissued.
                    manifest.update(stop_confirmed=True, ended_at=run.now(),
                        end_reason='controller_lost_before_start', model_called=False,
                        stop_evidence={'known_no_send':True,'runtime_never_allocated':True})
                    util.write_json_atomic(root / 'manifest.json',manifest)
                else:
                    stop(root)
                manifest = util.read_json(root / 'manifest.json')
                if not manifest.get('stop_confirmed'):
                    return {'status': 'held', 'reason': 'stop_unconfirmed'}
                if not (root / 'snapshot.json').exists():
                    run.collect_run(batch, rid)
                receipt_path = root / 'implementation-receipt.json'
                if not receipt_path.exists():
                    util.write_new_json(receipt_path, {'run_id': rid,
                        'run_instance_id': binding['run_instance_id'], 'stop_confirmed': True,
                        'recovered': True, 'raw': util.tree_hashes(root / 'usage/raw')})
                receipt = util.read_json(receipt_path)
                if not receipt.get('stop_confirmed'):
                    receipt = {**receipt, 'stop_confirmed': True, 'recovered': True,
                        'manifest_sha256': util.sha256_file(root / 'manifest.json'),
                        'raw': util.tree_hashes(root / 'usage/raw'),
                        'snapshot_sha256': util.sha256_file(root / 'snapshot.json'),
                        'reconciles_implementation_receipt': {'path': str(receipt_path.resolve()),
                            'sha256': util.sha256_file(receipt_path)}}
                    util.write_new_json(root / ('stop-reconciliation-' + uuid.uuid4().hex + '.json'), receipt)
                _record_implementation(journal, binding, receipt, batch, 'stop_reconciled' if previous else 'implemented')
            if rid not in current['results'] and (root / 'postprocess-receipt.json').exists():
                path = root / 'postprocess-receipt.json'
                receipt = util.read_json(path)
                if any(receipt.get(k) != binding.get(k) for k in ('run_instance_id', 'slot', 'plan_sha256')):
                    raise ValueError('Postprocess receipt identity mismatch')
                append(journal, {'kind': 'result', **binding, 'row': receipt['row'],
                    'receipt': str(path), 'receipt_sha256': util.sha256_file(path)})
        held = _collection_hold(state(journal), assignments)
        if held: return held
        if len(assignments) != 2:
            return {'status': 'held', 'reason': 'pair_incomplete_unsent_slot_not_dispatched'}
        return _postprocess(plan, assignments, batch, repo, journal, postprocess)


def _validate_gate(value, current, pair):
    assigned = [d for d in current['dispatch'].values() if d['pair'] == pair]
    if len(assigned) != 2 or not all(d['run_id'] in current['results'] for d in assigned):
        raise ValueError('Exactly two terminal results required before the gate')
    if _collection_hold(current, assigned):
        raise ValueError('Recorded collection fault blocks publication gate')
    if any(_postprocess_fault(current['results'][d['run_id']]['row']) for d in assigned):
        raise ValueError('Recorded postprocess fault blocks publication gate')
    expected = {d['run_id']: d['run_instance_id'] for d in assigned}
    if (value.get('pair') != pair or value.get('plan_sha256') != assigned[0]['plan_sha256']
            or value.get('cohort') != assigned[0]['cohort'] or value.get('run_instances') != expected):
        raise ValueError('Publication gate plan/cohort/instance binding mismatch')
    refs = value.get('evidence_files', {})
    if not refs or any(not Path(p).is_file() or util.sha256_file(p) != h for p, h in refs.items()):
        raise ValueError('Publication gate original evidence missing or changed')
    records = {key: util.read_json(value[key]) for key in ('publication_receipt', 'roundtrip_receipt', 'cleanup_receipt')
               if value.get(key) in refs}
    if len(records) != 3:
        raise ValueError('Three original gate receipts required')
    publication, restored, cleaned = (records[k] for k in
        ('publication_receipt', 'roundtrip_receipt', 'cleanup_receipt'))
    if (not publication.get('remote_assets_verified') or not publication.get('urls')
            or not restored.get('hashes_match') or not restored.get('extraction_sockets_blocked')
            or not cleaned.get('cleanup_completed') or cleaned.get('original_runs_deleted') is not False):
        raise ValueError('Publication/independent restore/owned cleanup not verified')
    digest = publication.get('package_sha256')
    if (not isinstance(digest, str) or len(digest) != 64
            or restored.get('package_sha256') != digest or cleaned.get('package_sha256') != digest):
        raise ValueError('Package receipt hashes differ')


def record_pair_gate(batch, pair, receipt):
    """Only a hash-bound publication, independent restore and owned cleanup proof."""
    value = util.read_json(receipt)
    batch = Path(batch)
    with exclusive(batch / '_control'):
        journal = batch / '_control/pair-journal.jsonl'
        current = state(journal)
        _validate_gate(value, current, pair)
        append(journal, {'kind': 'pair_gate', 'pair': pair, 'receipt': str(Path(receipt).resolve()),
                         'receipt_sha256': util.sha256_file(receipt)})
        state(journal)


def resume_pair(plan, batch, authorization, *, repo, verify, implement=machine.implement,
                postprocess=machine.postprocess, concurrency=1, stop=runtime.request_stop, admit=None):
    """Explicitly authorized unsent-only continuation of an existing reservation.

    verify(plan, binding) must recheck frozen inputs/environment/admission.
    Authorization binds current journal bytes and exact reserved instances.
    A dispatched identity is never sent again; recovery of it must finish first.
    """
    if concurrency not in (1, 2) or concurrency != plan.get('pair_concurrency', concurrency):
        raise ValueError('Resume must retain frozen pair concurrency 1 or 2')
    batch = Path(batch)
    with exclusive(batch / '_control'):
        journal = batch / '_control/pair-journal.jsonl'
        current = state(journal)
        _verify_plan(plan, current)
        unsent = [d for rid, d in current['reserved'].items() if rid not in current['dispatch']]
        if not unsent or current['pending']:
            return {'status':'held','reason':'no_reconciled_unsent_slot'}
        pair = unsent[0]['pair']
        if any(d['pair'] != pair for d in unsent):
            raise ValueError('Unsent reservations span different pairs')
        assignments = [d for d in current['reserved'].values() if d['pair'] == pair]
        held = _collection_hold(current, assignments)
        if held: return held
        if (authorization.get('authorized') is not True or authorization.get('approved_by') != 'user'
                or not authorization.get('authorization_reference')
                or authorization.get('plan_sha256') != plan['plan_sha256']
                or authorization.get('journal_sha256') != util.sha256_file(journal)
                or authorization.get('run_instances') != {d['run_id']:d['run_instance_id'] for d in unsent}):
            raise ValueError('Explicit resume authorization must bind exact unsent instances and journal')
        for d in assignments:
            previous = current['implementations'].get(d['run_id'])
            if d['run_id'] in current['dispatch'] and (not previous or previous['receipt'].get('stop_confirmed') is not True):
                raise ValueError('Dispatched peer has not been reconciled to a confirmed stop')
        for binding in unsent:
            root = batch / binding['run_id']
            manifest = util.read_json(root / 'manifest.json')
            if (manifest.get('started_at') or manifest.get('run_instance_id') != binding['run_instance_id']
                    or (root / 'runtime.json').exists()):
                raise ValueError('Reserved slot is not demonstrably unstarted')
            verify(plan,binding)
        # Validate every unsent input before dispatching either peer. A one-slot
        # continuation is explicit; no stopped/dispatched peer is recreated.
        append(journal, {'kind': 'resume_regime', 'pair': pair,
            'frozen_concurrency': concurrency, 'unsent_slots': len(unsent),
            'stopped_peer_not_replayed': len(unsent) == 1})
        if concurrency == 2 and len(unsent) == 2:
            fault = False
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {}
                try:
                    for binding in unsent:
                        for future in list(futures):
                            if future.done():
                                prior = futures.pop(future)
                                receipt, failed = _implementation_result(future, prior, batch)
                                _record_implementation(journal, prior, receipt, batch)
                                fault = fault or failed
                        if fault:
                            _stop_active(futures, batch, stop)
                            break
                        with admit(binding) if admit else nullcontext():
                            append(journal, {'kind': 'resume_authorized', **binding, 'authorization': authorization})
                            append(journal, {'kind': 'dispatch', **binding})
                            futures[pool.submit(implement, repo, batch, binding['run_id'])] = binding
                    for future in as_completed(futures):
                        binding = futures[future]
                        receipt, failed = _implementation_result(future, binding, batch)
                        _record_implementation(journal, binding, receipt, batch)
                        fault = fault or failed
                        if failed: _stop_active(futures, batch, stop)
                except BaseException:
                    _stop_active(futures, batch, stop)
                    raise
            if fault:
                return {'status': 'held', 'reason': 'implementation_fault'}
            return _postprocess(plan, assignments, batch, repo, journal, postprocess)
        for binding in unsent:
            future=Future()
            with admit(binding) if admit else nullcontext():
                append(journal, {'kind':'resume_authorized', **binding,'authorization':authorization})
                append(journal, {'kind':'dispatch', **binding})
            try: future.set_result(implement(repo,batch,binding['run_id']))
            except Exception as exc: future.set_exception(exc)
            receipt,failed=_implementation_result(future,binding,batch)
            _record_implementation(journal,binding,receipt,batch)
            if failed: return {'status':'held','reason':'implementation_fault'}
        return _postprocess(plan,assignments,batch,repo,journal,postprocess)
