"""One authoritative fixed-wave manager and separate append-only phase journal.

All callbacks are explicit. No CLI, credential read, model dispatch or publication
occurs on import or plan preparation. The cohort lock remains held for the whole
session including serial heavy processing, publication and recovery.
"""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from pathlib import Path
import threading
import uuid

from outer.harness import util
from research import pair_execution as pair, wave_plan

BINDING_KEYS = ('run_id', 'run_instance_id', 'slot', 'pair', 'plan_sha256',
                'phase_sha256', 'cohort', 'runtime', 'input_sha256', 'condition_sha256')


def state(journal, phase, digest):
    """Replay strict state; incomplete tails and ambiguous sends always hold."""
    out = dict(reserved={}, dispatch={}, implementations={}, results={}, gates={}, waves=[])
    expected = {c['run_id']: c for p in phase['assignments'] for c in p['cases']}
    block_cursor = 0
    barrier = False
    for event in pair.events(journal):
        if event.get('phase_sha256') != digest: raise ValueError('Wrong phase journal')
        kind, rid = event['kind'], event.get('run_id')
        if kind == 'wave_reserved':
            if out['waves'] and any(p not in out['gates'] for p in out['waves'][-1]['pairs']):
                raise ValueError('Previous wave gates incomplete; no refill')
            blocks = phase['two_pair_blocks'][block_cursor:block_cursor + event['blocks']]
            pairs = [p for block in blocks for p in block]
            if (event['blocks'] not in (1, 2) or (not out['waves'] and event['blocks'] != 1)
                    or not blocks or event['pairs'] != pairs
                    or event['run_cap'] != 2 * len(pairs) or event['run_cap'] > 8):
                raise ValueError('Wave differs from predefined blocks or 4/8 Run cap')
            wanted = [c for p in phase['assignments'] if p['pair'] in pairs for c in p['cases']]
            if len(event['assignments']) != len(wanted): raise ValueError('Incomplete wave reservation')
            for binding, case in zip(event['assignments'], wanted):
                if (any(binding.get(k) != v for k, v in case.items())
                        or binding['run_id'] in out['reserved']
                        or binding.get('plan_sha256') != phase['original_bundle']['sha256']
                        or binding.get('phase_sha256') != digest
                        or binding.get('cohort') != phase['cohort']
                        or binding.get('runtime') != phase['runtime']
                        or not binding.get('input_sha256') or not binding.get('condition_sha256')):
                    raise ValueError('Unassigned or changed fixed identity/input')
                out['reserved'][binding['run_id']] = binding
            out['waves'].append(event); block_cursor += event['blocks']; barrier = False
        elif kind == 'dispatch':
            binding = out['reserved'].get(rid, {})
            if (rid not in expected or rid in out['dispatch'] or barrier
                    or any(event.get(k) != binding.get(k) for k in BINDING_KEYS)
                    or event['pair'] not in out['waves'][-1]['pairs']):
                raise ValueError('Duplicate, unreserved or wrong-instance dispatch')
            out['dispatch'][rid] = event
        elif kind in ('implemented', 'stop_reconciled', 'result'):
            target = out['results'] if kind == 'result' else out['implementations']
            binding = out['dispatch'].get(rid, {})
            replaces = kind == 'stop_reconciled' and rid in target and (
                target[rid]['receipt'].get('stop_confirmed') is not True
                or target[rid]['receipt'].get('submission_fixed') is not True)
            if (rid not in out['dispatch'] or (rid in target and not replaces)
                    or any(event.get(k) != binding.get(k) for k in BINDING_KEYS)):
                raise ValueError('Duplicate or wrong-instance terminal record')
            if kind == 'result' and not barrier: raise ValueError('Heavy processing before wave stop barrier')
            path = event['receipt_path']
            if util.sha256_file(path) != event['receipt_sha256']: raise ValueError('Terminal evidence changed')
            receipt = util.read_json(path)
            if any(receipt['binding'].get(k) != binding.get(k) for k in BINDING_KEYS):
                raise ValueError('Receipt binding changed')
            if receipt['receipt'] != event['receipt']: raise ValueError('Receipt bytes differ from journal')
            target[rid] = {**event, **({'row': receipt['receipt']} if kind == 'result' else {})}
        elif kind == 'barrier':
            bindings = out['waves'][-1]['assignments']
            if (barrier or any(b['run_id'] not in out['implementations']
                    or out['implementations'][b['run_id']]['receipt'].get('stop_confirmed') is not True
                    or out['implementations'][b['run_id']]['receipt'].get('submission_fixed') is not True
                    for b in bindings)):
                raise ValueError('Every wave Run must stop and originals fix before heavy processing')
            barrier = True
        elif kind == 'pair_gate':
            if not barrier or event['pair'] in out['gates']: raise ValueError('Premature or duplicate pair gate')
            if util.sha256_file(event['receipt_path']) != event['receipt_sha256']:
                raise ValueError('Pair gate evidence changed')
            gate = util.read_json(event['receipt_path'])
            pair._validate_gate(gate, out, event['pair'])
            if gate.get('phase_sha256') != digest: raise ValueError('Gate must also bind new phase')
            out['gates'][event['pair']] = event
        elif kind not in ('resource_snapshot', 'postprocess_start', 'publication_start', 'fault', 'metrics', 'resume'):
            raise ValueError('Unknown wave event')
    out.update(block_cursor=block_cursor, barrier=barrier,
        pending=[r for r in out['dispatch'] if r not in out['implementations']])
    return out


class Dispatcher:
    def __init__(self, repo, phase_path, approval, *, prepare, verify, implement,
                 postprocess, publish, reconcile, fence, snapshot, supervise, publication_ready):
        self.repo, self.phase_path = Path(repo).resolve(), Path(phase_path).resolve()
        self.phase = util.read_json(phase_path); self.digest = util.sha256_file(phase_path)
        wave_plan.validate(self.phase, repo=self.repo)
        if (approval.get('approved_by') != 'user' or approval.get('authorized') is not True
                or approval.get('phase_sha256') != self.digest
                or not approval.get('authorization_reference')):
            raise ValueError('Separate exact-new-phase user authorization required')
        self.approval = approval
        self.batch = Path(self.phase['batch']); self.control = self.batch / '_control'
        self.phase_control = self.control / self.phase['phase_id']
        self.journal = self.phase_control / 'wave-journal.jsonl'
        self.stop_path = self.phase_control / 'dispatch-stop.json'
        self.prepare, self.verify, self.implement = prepare, verify, implement
        self.postprocess, self.publish, self.reconcile = postprocess, publish, reconcile
        self.fence, self.snapshot, self.supervise = fence, snapshot, supervise
        self.publication_ready = publication_ready
        self.admission = threading.RLock(); self.journal_lock = threading.RLock(); self.entered = False
        self.closed = threading.Event(); self.owned_active = {}

    @contextmanager
    def session(self):
        if self.entered: raise ValueError('Nested dispatcher session')
        with pair.exclusive(self.control, phase_permit=self.digest):
            wave_plan.validate(self.phase, repo=self.repo)
            marker = {'kind': 'central_fixed_wave_handoff_v1', 'phase_sha256': self.digest,
                'phase_path': str(self.phase_path), 'old_journal': self.phase['old_journal'],
                'original_bundle': self.phase['original_bundle'], 'approval': self.approval}
            handoff = self.control / 'phase-handoff.json'
            if handoff.exists():
                if util.read_json(handoff) != marker: raise ValueError('Different durable phase owner')
            else: util.write_new_json(handoff, marker)
            self.entered = True
            try: yield self
            finally: self.entered = False

    def current(self):
        if not self.entered: raise ValueError('Central cohort session lock required')
        wave_plan.validate(self.phase, repo=self.repo)
        with self.journal_lock:
            return state(self.journal, self.phase, self.digest)

    def record(self, kind, **value):
        with self.journal_lock:
            pair.append(self.journal, {'kind': kind, 'phase_sha256': self.digest, **value})

    def terminal(self, kind, binding, receipt):
        path = self.phase_control / (kind + '-' + binding['run_id'] + '-' + uuid.uuid4().hex + '.json')
        util.write_new_json(path, {'binding': binding, 'receipt': receipt})
        self.record(kind, **binding, receipt=receipt, receipt_path=str(path), receipt_sha256=util.sha256_file(path))
        if kind in ('implemented', 'stop_reconciled') and receipt.get('stop_confirmed') is True:
            self.owned_active.pop(binding['run_id'], None)

    def fault(self, reason):
        """Decision closes dispatch durably; distributed gateway ACK time is separate."""
        with self.admission:
            self.closed.set()
            evidence_errors = []
            try:
                if not self.stop_path.exists():
                    util.write_new_json(self.stop_path, {'reason': reason, 'phase_sha256': self.digest,
                        'decision_at': pair.run.now(), 'http_fence_confirmed': False})
            except OSError as exc: evidence_errors.append(type(exc).__name__)
            try:
                current = self.current()
                owned = [binding for rid, binding in current['dispatch'].items()
                    if rid not in current['implementations']
                    or current['implementations'][rid]['receipt'].get('stop_confirmed') is not True]
            except (OSError, ValueError) as exc:
                evidence_errors.append(type(exc).__name__)
                owned = list(self.owned_active.values())
            try: self.record('fault', reason=reason, stop_reference=str(self.stop_path))
            except OSError as exc: evidence_errors.append(type(exc).__name__)
        # Caller closes ALL gateways concurrently before waiting for worker stops.
        # Callback must return every owned binding, ACK and stop uncertainty.
        try: receipt = self.fence(owned)
        except Exception as exc: receipt = {'confirmed': False, 'error_type': type(exc).__name__}
        path = self.phase_control / ('distributed-fence-' + uuid.uuid4().hex + '.json')
        try:
            util.write_new_json(path, {'phase_sha256': self.digest, 'owned': owned, 'receipt': receipt,
                'evidence_errors': evidence_errors})
            reference = str(path)
        except OSError as exc:
            evidence_errors.append(type(exc).__name__); reference = None
        return {'status': 'held', 'reason': reason, 'fence_receipt': reference,
            'evidence_errors': evidence_errors}

    def execute_next(self, *, escalate=False):
        current = self.current()
        if self.closed.is_set() or self.stop_path.exists(): return {'status': 'held', 'reason': 'durable_dispatch_stop'}
        if current['waves'] and any(p not in current['gates'] for p in current['waves'][-1]['pairs']):
            return {'status': 'held', 'reason': 'previous_wave_gates_or_explicit_recovery'}
        if current['block_cursor'] == len(self.phase['two_pair_blocks']):
            return {'status': 'complete', 'phase_pairs': 95, 'global_pairs': 100}
        resource = self.snapshot()
        self.record('resource_snapshot', snapshot=resource)
        if not wave_plan.healthy(resource, self.phase['thresholds']): return self.fault('objective_health_hold')
        # At least one complete 4-Run wave is required before an 8-Run wave.
        blocks = 2 if escalate and current['waves'] and resource['escalation_healthy'] else 1
        selected = self.phase['two_pair_blocks'][current['block_cursor']:current['block_cursor'] + blocks]
        numbers = [n for block in selected for n in block]
        bindings = []
        for p in self.phase['assignments']:
            if p['pair'] not in numbers: continue
            for case in p['cases']:
                binding = {**case, 'cohort': self.phase['cohort'], 'runtime': self.phase['runtime'],
                    'plan_sha256': self.phase['original_bundle']['sha256'], 'phase_sha256': self.digest,
                    'responsibility': self.phase['shards'][str(p['pair'])]}
                root = self.batch / binding['run_id']
                if root.exists():
                    # Manager loss during preparation cannot authorize a new
                    # identity or overwrite any bytes. Reuse only a complete,
                    # demonstrably unstarted original same-phase preparation.
                    manifest = util.read_json(root / 'manifest.json')
                    assigned = manifest.get('assignment', manifest)
                    if (manifest.get('started_at') or (root / 'runtime.json').exists()
                            or any(assigned.get(k) != v for k, v in binding.items())):
                        raise ValueError('Unassigned or ambiguous directory; preserve and reconcile')
                else:
                    manifest = self.prepare(binding)
                if any(manifest.get(k) != binding[k] for k in ('run_id', 'run_instance_id')):
                    raise ValueError('Prepared identity changed')
                binding.update(input_sha256=manifest['prompt_sha256'], condition_sha256=manifest['condition_sha256'])
                self.verify(binding)
                bindings.append(binding)
        self.record('wave_reserved', pairs=numbers, blocks=len(selected), run_cap=len(bindings), assignments=bindings)
        return self._implement(bindings)

    def _implement(self, bindings):
        failed = False
        with ThreadPoolExecutor(max_workers=len(bindings)) as pool:
            futures = {}
            processed = set()
            try:
                for binding in bindings:
                    for future in list(futures):
                        if future.done() and future not in processed:
                            prior = futures[future]
                            receipt, bad = pair._implementation_result(future, prior, self.batch)
                            self.terminal('implemented', prior, receipt); processed.add(future)
                            if bad or receipt.get('submission_fixed') is not True:
                                if not failed: self.fault('implementation_or_collection_fault')
                                failed = True
                    with self.admission:
                        if self.closed.is_set() or self.stop_path.exists(): break
                        # Durable intent precedes pool submission. A crash here is
                        # ambiguous dispatch; neither recovery nor resume replays it.
                        self.owned_active[binding['run_id']] = binding
                        self.record('dispatch', **binding)
                        futures[pool.submit(self.implement, self.repo, self.batch, binding['run_id'])] = binding
                pending = set(futures) - processed
                while pending:
                    completed, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    for future in completed:
                        binding = futures[future]
                        receipt, bad = pair._implementation_result(future, binding, self.batch)
                        self.terminal('implemented', binding, receipt)
                        if bad or receipt.get('submission_fixed') is not True:
                            if not failed: self.fault('implementation_or_collection_fault')
                            failed = True
                    if pending and not failed:
                        reason = self.supervise([futures[f] for f in pending])
                        if reason:
                            self.fault(str(reason)); failed = True
            except BaseException:
                self.fault('controller_fault')
                raise
        rows = pair.events(self.journal)
        selected = {b['run_id'] for b in bindings}
        active, peak = set(), 0
        for event in rows:
            if event.get('run_id') not in selected: continue
            if event['kind'] == 'dispatch': active.add(event['run_id']); peak = max(peak, len(active))
            elif event['kind'] in ('implemented', 'stop_reconciled') and event['receipt'].get('stop_confirmed'):
                active.discard(event['run_id'])
        self.record('metrics', dispatched_runs=len(futures), configured_run_cap=len(bindings),
            dispatch_to_confirmed_stop_peak=peak, unresolved_dispatches=sorted(active),
            accounting='Journal dispatch-to-confirmed-stop interval; not actual HTTP overlap')
        if failed or len(futures) != len(bindings): return {'status': 'held', 'reason': 'implementation_fault'}
        return self.finish_wave()

    def finish_wave(self, *, recovering=False):
        current = self.current()
        for binding in current['waves'][-1]['assignments'] if current['waves'] else []:
            previous = current['implementations'].get(binding['run_id'])
            if previous and (previous['receipt'].get('collection_status') == 'collection_fault'
                    or previous['receipt'].get('collection_error_type')):
                return {'status': 'held', 'reason': 'recorded_collection_fault', 'run_id': binding['run_id']}
        if not current['waves']: return {'status': 'held', 'reason': 'no_wave'}
        bindings = current['waves'][-1]['assignments']
        if any(b['run_id'] not in current['implementations'] for b in bindings):
            return {'status': 'held', 'reason': 'wave_incomplete_unsent_or_uncertain'}
        if any(current['implementations'][b['run_id']]['receipt'].get('stop_confirmed') is not True
                or current['implementations'][b['run_id']]['receipt'].get('submission_fixed') is not True for b in bindings):
            return {'status': 'held', 'reason': 'stop_or_original_fix_unconfirmed'}
        if any(pair._postprocess_fault(result['row']) for result in current['results'].values()):
            return {'status': 'held', 'reason': 'recorded_postprocess_fault'}
        if not current['barrier']:
            self.record('barrier', pairs=current['waves'][-1]['pairs'])
            current = self.current()
        for binding in bindings:
            rid = binding['run_id']
            if rid in current['results']: continue
            intent = self.phase_control / ('postprocess-intent-' + rid + '.json')
            durable = self.batch / rid / 'postprocess-receipt.json'
            if intent.exists():
                if not recovering or not durable.exists():
                    return {'status': 'held', 'reason': 'uncertain_postprocess_requires_reconciliation', 'run_id': rid}
                saved = util.read_json(durable)
                if any(saved.get(k) != binding.get(k) for k in BINDING_KEYS): raise ValueError('Wrong-instance recovered result')
                row = saved['row']
            else:
                util.write_new_json(intent, binding)
                self.record('postprocess_start', **binding)
                try: row = self.postprocess(self.repo, self.batch, rid, self.batch / '_archive')
                except Exception: return self.fault('postprocess_fault')
                util.write_new_json(durable, {**binding, 'row': row})
            self.terminal('result', binding, row)
            if pair._postprocess_fault(row): return self.fault('postprocess_fault')
        current = self.current()
        for number in current['waves'][-1]['pairs']:
            if number in current['gates']: continue
            # This callback may stage a public copy and report that exact review
            # is pending. No remote intent or operational fault is recorded.
            if not self.publication_ready(number, current):
                return {'status': 'held', 'reason': 'publication_review_pending', 'pair': number,
                    'wave_implementations_stopped': True, 'model_dispatched': False}
            intent = self.phase_control / ('publication-intent-' + str(number) + '.json')
            if intent.exists() and not recovering:
                return {'status': 'held', 'reason': 'uncertain_publication_requires_reconciliation'}
            if not intent.exists():
                util.write_new_json(intent, {'pair': number, 'phase_sha256': self.digest})
                self.record('publication_start', pair=number)
            # Adapter reconciles exact existing remote bytes/finalization on
            # recovery. It must not recursively acquire the cohort lock or write
            # an old-v5 pair journal gate. Remote operations remain serial here.
            try: path = self.publish(number, current, recovering)
            except Exception: return self.fault('publication_fault')
            value = util.read_json(path)
            pair._validate_gate(value, current, number)
            if value.get('phase_sha256') != self.digest: raise ValueError('Publication gate phase mismatch')
            self.record('pair_gate', pair=number, receipt_path=str(Path(path).resolve()), receipt_sha256=util.sha256_file(path))
            current = self.current()
        return {'status': 'wave_gated', 'pairs': current['waves'][-1]['pairs'], 'next_wave_dispatched': False}

    def recover(self):
        current = self.current()
        # The durable stop stays set until an explicit same-phase health-bound
        # resume authorization. Every sent identity is reconciled, never sent.
        self.fault('explicit_recovery')
        uncertain = [rid for rid in current['dispatch'] if rid not in current['implementations']
            or current['implementations'][rid]['receipt'].get('stop_confirmed') is not True
            or current['implementations'][rid]['receipt'].get('submission_fixed') is not True]
        unresolved = []
        for rid in uncertain:
            binding = current['dispatch'][rid]
            try: receipt = self.reconcile(binding)
            except Exception as exc:
                unresolved.append({'run_id': rid, 'error_type': type(exc).__name__}); continue
            if (receipt.get('run_id') != rid or receipt.get('run_instance_id') != binding['run_instance_id']
                    or receipt.get('stop_confirmed') is not True or receipt.get('submission_fixed') is not True):
                unresolved.append({'run_id': rid, 'stop_confirmed': receipt.get('stop_confirmed'),
                    'submission_fixed': receipt.get('submission_fixed')}); continue
            self.terminal('stop_reconciled' if rid in current['implementations'] else 'implemented', binding, receipt)
        if unresolved: return {'status': 'held', 'reason': 'stop_or_original_fix_unconfirmed', 'unresolved': unresolved}
        return self.finish_wave(recovering=True)

    def clear_reconciled_stop(self, authorization):
        """Health-bound explicit continuation after every wave gate has completed.

        Uses the still-valid user phase authorization plus an operator recovery
        decision; never grants a new plan, identity, budget or concurrency cap.
        """
        current = self.current()
        if not self.stop_path.exists(): return {'status': 'ready', 'stop_already_clear': True}
        if (current['pending'] or current['waves'] and any(
                p not in current['gates'] for p in current['waves'][-1]['pairs'])):
            return {'status': 'held', 'reason': 'recovery_and_all_wave_gates_required'}
        if (authorization.get('approved_by') != 'user' or authorization.get('authorized') is not True
                or authorization.get('phase_sha256') != self.digest
                or authorization.get('authorization_reference') != self.approval['authorization_reference']
                or not authorization.get('recovery_decision_reference')
                or authorization.get('journal_sha256') != util.sha256_file(self.journal)
                or authorization.get('stop_sha256') != util.sha256_file(self.stop_path)
                or not wave_plan.healthy(self.snapshot(), self.phase['thresholds'])):
            raise ValueError('Bound recovery decision and objective health required before new dispatch')
        self.record('resume', authorization=authorization, unsent_slots=0, all_prior_wave_gates_complete=True)
        self.stop_path.rename(self.phase_control / ('retained-stop-' + uuid.uuid4().hex + '.json'))
        self.closed.clear()
        return {'status': 'ready', 'model_dispatched': False}

    def resume_unsent(self, authorization):
        current = self.current()
        bindings = current['waves'][-1]['assignments'] if current['waves'] else []
        unsent = [b for b in bindings if b['run_id'] not in current['dispatch']]
        if not unsent or current['pending']: return {'status': 'held', 'reason': 'no_reconciled_unsent_slot'}
        if (authorization.get('approved_by') != 'user' or authorization.get('authorized') is not True
                or not authorization.get('authorization_reference')
                or authorization.get('phase_sha256') != self.digest
                or authorization.get('journal_sha256') != util.sha256_file(self.journal)
                or authorization.get('run_instances') != {b['run_id']: b['run_instance_id'] for b in unsent}
                or not wave_plan.healthy(self.snapshot(), self.phase['thresholds'])):
            raise ValueError('Explicit exact-journal same-instance healthy unsent-only resume required')
        for binding in unsent:
            root = self.batch / binding['run_id']; manifest = util.read_json(root / 'manifest.json')
            if manifest.get('started_at') or (root / 'runtime.json').exists(): raise ValueError('Ambiguous slot never replayed')
            self.verify(binding)
        # Preserve each stop original, rather than replacing/deleting a fence.
        self.record('resume', authorization=authorization, unsent_slots=len(unsent))
        if self.stop_path.exists():
            self.stop_path.rename(self.phase_control / ('retained-stop-' + uuid.uuid4().hex + '.json'))
        self.closed.clear()
        return self._implement(unsent)
