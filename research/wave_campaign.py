"""Single leased controller for the explicitly approved remaining fixed waves.

Import is inert. Credentials remain in the existing gateway-only bootstrap.
Public-copy review is an ordinary wait inside the central session, not a fault.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import time
import uuid

from outer.harness import live_usage, runtime, util
from research import next_phase, wave_dispatch, wave_execution, wave_plan


def load_monitor(phase):
    reference = phase['resource_monitor']
    if not next_phase.verify_reference(reference):
        raise ValueError('Frozen private resource monitor changed')
    path = Path(reference['path']).resolve()
    probe = phase['resource_probe']
    if (Path(probe['path']).resolve() != path.with_name('wave_resource_probe.py')
            or not next_phase.verify_reference(probe)):
        raise ValueError('Frozen private resource probe dependency changed')
    spec = importlib.util.spec_from_file_location('sample2_frozen_wave_resource_monitor', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.ResourceMonitor


def preflight(repo, phase):
    """Verify amended source plus unchanged model/runtime/environment identities."""
    original = wave_execution.preflight(repo, phase)
    for name in ('research/wave_campaign.py', 'research/wave_sharing.py'):
        if phase['source_pins'].get(name) != util.sha256_file(Path(repo) / name):
            raise ValueError('Central controller/publication module must be frozen: ' + name)
    if next_phase.git(repo, 'rev-parse', 'HEAD') != phase['source_commit']:
        raise ValueError('Final wave source commit changed')
    if next_phase.git(repo, 'status', '--porcelain'):
        raise ValueError('Wave source is not clean')
    python = original['python']
    if (str(Path(sys.executable).resolve()) != python['path']
            or platform.python_version() != python['version']
            or util.sha256_file(sys.executable) != python['sha256']):
        raise ValueError('Original Python identity changed')
    for lock in original['runtime_locks'].values():
        for digest in lock['images'].values():
            if runtime.image_id(digest) != digest:
                raise ValueError('Original runtime image changed')
    from research import catalog_environment
    browser = original['browser']
    if not next_phase.verify_reference(browser['reference']):
        raise ValueError('Original browser reference changed')
    catalog_environment.validate(browser['record'], repo)
    return original


def journal_health(batch, bindings, model):
    """Only operational metadata; never reads prompts, response text or keys."""
    flags = dict(journal_healthy=True, http_healthy=True, provider_healthy=True)
    inflight = 0
    inventory = {}
    for binding in bindings:
        root = Path(batch) / binding['run_id']
        paths = {name: root / 'usage/raw' / (name + '.jsonl')
                 for name in ('started', 'events', 'transmission', 'failure')}
        rows = {}
        for name, path in paths.items():
            values, errors = live_usage.journal(path)
            rows[name] = values
            if errors: flags['journal_healthy'] = False
            if path.exists(): inventory[str(path.resolve())] = util.sha256_file(path)
            for row in values:
                if row.get('run_id') != binding['run_id']:
                    flags['journal_healthy'] = False
                if name != 'failure' and row.get('session_id') != binding['run_instance_id']:
                    flags['journal_healthy'] = False
        starts = [r.get('request_id') for r in rows['started']]
        ends = [r.get('request_id') for r in rows['events']]
        if (None in starts or None in ends or len(set(starts)) != len(starts)
                or len(set(ends)) != len(ends) or not set(ends) <= set(starts)):
            flags['journal_healthy'] = False
        # A durable started request includes connecting/queued/unknown-send work.
        # Count it conservatively until the terminal event is present.
        inflight += len(set(starts) - set(ends))
        if rows['failure']: flags['provider_healthy'] = False
        for row in rows['events']:
            if (row.get('model_id') != model or row.get('response_model_id') not in (None, model)
                    or row.get('status') != 'completed' or row.get('usage_complete') is not True
                    or row.get('send_evidence') != 'observed_send' or row.get('http_status') != 200):
                flags['provider_healthy'] = False
            usage = row.get('usage') or {}
            if any(type(usage.get(k)) is not int or usage[k] < 0
                   for k in ('input_tokens', 'output_tokens')):
                flags['provider_healthy'] = False
        if any(r.get('request_id') not in starts for r in rows['transmission']):
            flags['http_healthy'] = False
        manifest_path = root / 'manifest.json'
        if not manifest_path.exists():
            flags['journal_healthy'] = False
        else:
            manifest = util.read_json(manifest_path)
            if (manifest.get('run_id') != binding['run_id']
                    or manifest.get('run_instance_id') != binding['run_instance_id']):
                flags['journal_healthy'] = False
            if manifest.get('stop_confirmed') and set(starts) != set(ends):
                flags['http_healthy'] = False
    return {**flags, 'http_inflight_max': inflight, 'journal_files': inventory}


class Health:
    def __init__(self, dispatcher, monitor, *, escalate=False):
        self.dispatcher, self.monitor = dispatcher, monitor
        self.escalate = escalate
        self.wave = None
        self.http_peak = 0
        self.costs = {}

    def disk_forecast(self, current, resource):
        d = self.dispatcher
        policy = util.read_json(d.phase['operational_policy']['path'])['disk']
        cost = policy['initial_retained_bytes_per_remaining_pair']
        from outer.harness.preserve import native_path
        def size(path):
            path = native_path(path)
            return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        # Only retained bytes affect this capacity forecast; never model outcomes.
        for wave in current['waves']:
            key = tuple(wave['pairs'])
            if key in self.costs or any(p not in current['gates'] for p in key): continue
            total = 0
            packages = set()
            for binding in wave['assignments']:
                root = d.batch / binding['run_id']
                total += size(root)
                reference = util.read_json(root / 'archive-reference.json')
                package = (d.batch / '_archive/packages' / reference['package_id']).resolve()
                if not package.is_relative_to((d.batch / '_archive/packages').resolve()):
                    raise ValueError('Foreign archive capacity path')
                packages.add(package)
            total += sum(size(p) for p in packages)
            self.costs[key] = math.ceil(total / len(key))
        cost = max([cost, *self.costs.values()])
        pending = current['waves'] and any(p not in current['gates'] for p in current['waves'][-1]['pairs'])
        remaining = len(d.phase['assignments']) - len(current['gates'])
        if pending:
            wave = current['waves'][-1]
            unfixed = {b['pair'] for b in wave['assignments']
                       if not current['implementations'].get(b['run_id'], {}).get('receipt', {}).get('submission_fixed')}
            pairs, retained = len(unfixed), 0
        else:
            blocks = 2 if (d.phase.get('maximum_pairs', 4) >= 4 and self.escalate
                           and current['waves'] and resource['escalation_healthy']) else 1
            pairs = sum(len(b) for b in d.phase['two_pair_blocks'][current['block_cursor']:current['block_cursor'] + blocks])
            retained = remaining * cost
        required = (retained + pairs * policy['scratch_bytes_per_next_or_unfixed_wave_pair']
                    + policy['hard_free_floor_bytes'])
        return {'remaining_pairs': remaining, 'retained_cost_per_pair_bytes': cost,
                'scratch_pairs': pairs, 'required_free_bytes': required,
                'available_free_bytes': resource['disk_free_min_bytes'],
                'healthy': resource['disk_free_min_bytes'] >= required,
                'mode': 'active_preservation' if pending else 'next_wave_admission'}

    def roots(self):
        current = self.dispatcher.current()
        if not current['waves']: return []
        wave = current['waves'][-1]
        self.monitor.set_wave('wave-' + '-'.join(map(str, wave['pairs'])), len(wave['assignments']))
        roots = []
        for binding in wave['assignments']:
            if binding['run_id'] not in current['dispatch']: continue
            root = self.dispatcher.batch / binding['run_id']
            if not (root / 'runtime.json').exists(): continue
            state = util.read_json(root / 'runtime.json')
            if any(state.get(k) != binding[k] for k in ('run_id', 'run_instance_id')):
                raise ValueError('Foreign runtime in resource scope')
            manifest = util.read_json(root / 'manifest.json')
            # Runtime identity is allocated before Docker creates containers.
            # This durable milestone follows successful worker creation; it is
            # not a timed grace period or proof that missing metrics are zero.
            if state.get('worker_started_at') or manifest.get('stop_confirmed'):
                roots.append(root)
        return roots

    def snapshot(self, bindings=None):
        d = self.dispatcher
        current = d.current()  # strict journal replay is itself the identity gate
        wave = tuple(current['waves'][-1]['pairs']) if current['waves'] else ()
        if wave != self.wave:
            self.wave, self.http_peak = wave, 0
            self.monitor.set_wave('wave-' + '-'.join(map(str, wave)) if wave else 'initial-admission',
                                  len(current['waves'][-1]['assignments']) if wave else 0)
        if bindings is None:
            bindings = [b for b in current['waves'][-1]['assignments']
                        if b['run_id'] in current['dispatch']] if (current['waves'] and
                        any(p not in current['gates'] for p in wave)) else []
        model = util.read_json(d.phase['original_bundle']['path'])['plan']['settings']['model_id']
        health = journal_health(d.batch, bindings, model)
        self.http_peak = max(self.http_peak, health['http_inflight_max'])
        record = {'at': datetime.now(timezone.utc).isoformat(), 'phase_sha256': d.digest,
                  'wave_pairs': list(wave), **health, 'http_inflight_peak': self.http_peak}
        resource = dict(self.monitor.snapshot())
        record['disk_forecast'] = self.disk_forecast(current, resource)
        if not record['disk_forecast']['healthy']: resource['resource_healthy'] = False
        evidence = d.phase_control / 'supervision' / (uuid.uuid4().hex + '.json')
        util.write_new_json(evidence, record)
        resource.update({k: health[k] for k in ('journal_healthy', 'http_healthy', 'provider_healthy')})
        resource['http_inflight_max'] = self.http_peak
        resource['evidence_files'] = {**resource['evidence_files'], str(evidence.resolve()): util.sha256_file(evidence)}
        return resource

    def supervise(self, bindings):
        try:
            sample = self.snapshot(bindings)
            self.dispatcher.record('resource_snapshot', snapshot=sample)
            if not wave_plan.healthy(sample, self.dispatcher.phase['thresholds']):
                return 'runtime_resource_journal_http_or_provider_fault'
        except Exception:
            return 'runtime_supervision_fault'
        return None

    def decide_escalation(self):
        """One prospective operational decision; never use outcomes or tokens."""
        d = self.dispatcher
        if d.phase.get('maximum_pairs', 4) <= 2:
            self.escalate = False
            return False
        path = d.phase_control / 'escalation-decision.json'
        if path.exists():
            saved = util.read_json(path)
            if saved.get('phase_sha256') != d.digest: raise ValueError('Foreign escalation decision')
            self.escalate = self.escalate and saved['eligible'] is True
            return saved['eligible'] is True
        current = d.current()
        if not {6, 7} <= set(current['gates']): return False
        sample = self.snapshot()
        first = current['waves'][0]
        boundaries = []
        for binding in first['assignments']:
            events, errors = live_usage.journal(d.batch / binding['run_id'] / 'usage/raw/events.jsonl')
            if errors: raise ValueError('HTTP qualification journal damaged')
            for event in events:
                if event.get('send_evidence') == 'observed_send' and event.get('transmitted_at') and event.get('ended_at'):
                    start, end = datetime.fromisoformat(event['transmitted_at']), datetime.fromisoformat(event['ended_at'])
                    if start < end:
                        boundaries.extend([(start, 1, binding['pair']), (end, -1, binding['pair'])])
        active, peak = {}, 0
        for _, direction, rid in sorted(boundaries):
            active[rid] = active.get(rid, 0) + direction
            peak = max(peak, sum(n > 0 for n in active.values()))
        # Lost process history is deliberately not reconstructed as successful
        # qualification: a fresh monitor has no first-four active samples.
        model = util.read_json(d.phase['original_bundle']['path'])['plan']['settings']['model_id']
        provider = journal_health(d.batch, first['assignments'], model)
        eligible = (len(current['waves']) == 1 and sample['escalation_healthy'] is True
                    and wave_plan.healthy(sample, d.phase['thresholds']) and peak >= 2
                    and all(provider[k] is True for k in ('journal_healthy', 'http_healthy', 'provider_healthy')))
        util.write_new_json(path, {'phase_sha256': d.digest, 'at': next_phase.now(),
            'eligible': eligible, 'first_wave_pairs': first['pairs'], 'actual_distinct_pair_http_peak': peak,
            'snapshot': sample, 'journal_sha256': util.sha256_file(d.journal),
            'basis': 'Single operational decision after first four formal Runs and both public gates; no quality/token input.'})
        self.escalate = self.escalate and eligible
        return eligible


def warmup(health, thresholds, *, seconds=30, sleep=time.sleep, clock=time.monotonic):
    """Finite pre-dispatch sampling; no reservation, fault or remote intent."""
    deadline, consecutive, previous = clock() + seconds, 0, None
    while clock() < deadline:
        try:
            sample = health.snapshot()
            healthy = wave_plan.healthy(sample, thresholds)
            stamp = sample['sampled_at']
        except (OSError, ValueError, KeyError, TypeError): healthy, stamp = False, None
        if not healthy: consecutive = 0
        elif stamp != previous: consecutive += 1
        previous = stamp
        if consecutive >= 2: return True
        sleep(1)
    return False


def drive(dispatcher, *, mode='run', recovery_approval=None, one_wave=False,
          escalate=False, poll_seconds=5, sleep=time.sleep, report=None, escalation_decision=None):
    """Caller holds the sole session; review polling never drops that lease."""
    if mode == 'recover': result = dispatcher.recover()
    elif mode == 'resume-unsent': result = dispatcher.resume_unsent(recovery_approval)
    elif mode == 'continue':
        result = dispatcher.clear_reconciled_stop(recovery_approval)
        if result.get('status') == 'ready': result = dispatcher.execute_next(escalate=escalate)
    elif mode == 'finish': result = dispatcher.finish_wave()
    else:
        current = dispatcher.current()
        pending_wave = current['waves'] and any(p not in current['gates'] for p in current['waves'][-1]['pairs'])
        result = dispatcher.finish_wave() if pending_wave else dispatcher.execute_next(escalate=escalate)
    while True:
        if report: report(result)
        if result.get('reason') == 'publication_review_pending':
            sleep(poll_seconds)
            result = dispatcher.finish_wave(recovering=mode == 'recover')
            continue
        if result.get('status') == 'wave_gated' and escalation_decision:
            eligible = escalation_decision()
            escalate = escalate and eligible
        if result.get('status') != 'wave_gated' or one_wave or mode in ('finish', 'recover'):
            return result
        result = dispatcher.execute_next(escalate=escalate)


def run_campaign(repo, phase_path, approval_path, *, mode='run', recovery_approval_path=None,
                 one_wave=False, escalate=False, poll_seconds=5):
    repo = Path(repo).resolve()
    phase = util.read_json(phase_path)
    approval = util.read_json(approval_path)
    # No environment access or helper imports until exact-phase approval passes.
    if (approval.get('approved_by') != 'user' or approval.get('authorized') is not True
            or approval.get('phase_sha256') != util.sha256_file(phase_path)
            or not next_phase.verify_reference(approval['authorization_reference'])):
        raise ValueError('Verified exact-phase user authorization required')
    preflight(repo, phase)
    if phase.get('kind') in (wave_plan.V2_KIND, wave_plan.V3_KIND, wave_plan.V4_KIND, wave_plan.V5_KIND):
        escalate = False
        handoff = {wave_plan.V2_KIND: wave_dispatch.handoff_v2, wave_plan.V3_KIND: wave_dispatch.handoff_v3,
                   wave_plan.V4_KIND: wave_dispatch.handoff_v4, wave_plan.V5_KIND: wave_dispatch.handoff_v5}[phase['kind']]
        handoff(repo, phase_path, approval)
    Monitor = load_monitor(phase)
    preparation = phase.get('preparation_view')
    adapters = wave_execution.HarnessAdapters(repo, phase,
        prepare_repo=preparation['path'] if preparation else None,
        validate_preparation=getattr(wave_execution, 'validate_preparation', None) if preparation else None)
    delegates = {}
    dispatcher = wave_dispatch.Dispatcher(repo, phase_path, approval,
        prepare=adapters.prepare, verify=adapters.verify, implement=adapters.implement,
        postprocess=adapters.postprocess, reconcile=adapters.reconcile, fence=adapters.fence,
        snapshot=lambda: delegates['health'].snapshot(),
        supervise=lambda bindings: delegates['health'].supervise(bindings),
        publication_ready=lambda number, current: delegates['publisher'].ready(number, current),
        publish=lambda number, current, recovering: delegates['publisher'].publish(number, current, recovering))
    from research.wave_sharing import Publisher
    delegates['publisher'] = Publisher(dispatcher)
    recovery = util.read_json(recovery_approval_path) if recovery_approval_path else None
    if mode in ('resume-unsent', 'continue') and not recovery:
        raise ValueError('Explicit same-phase recovery approval required')
    with dispatcher.session():
        monitor = Monitor(dispatcher.phase_control / 'resources', lambda: delegates['health'].roots())
        delegates['health'] = Health(dispatcher, monitor, escalate=escalate)
        try:
            monitor.start()
            if mode in ('run', 'resume-unsent', 'continue') and not warmup(delegates['health'], phase['thresholds']):
                return {'status': 'held', 'reason': 'resource_warmup_not_healthy', 'model_dispatched': False}
            return drive(dispatcher, mode=mode, recovery_approval=recovery, one_wave=one_wave,
                escalate=escalate, poll_seconds=poll_seconds,
                escalation_decision=delegates['health'].decide_escalation,
                report=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
        except BaseException:
            dispatcher.fault('central_campaign_controller_exception')
            raise
        finally:
            if monitor.stop() is False:
                dispatcher.fault('resource_monitor_stop_unconfirmed')
                raise RuntimeError('Resource monitor stop unconfirmed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--phase', type=Path, required=True)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--mode', choices=('run', 'finish', 'recover', 'resume-unsent', 'continue'), default='run')
    parser.add_argument('--recovery-approval', type=Path)
    parser.add_argument('--one-wave', action='store_true')
    parser.add_argument('--escalate', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.poll_seconds <= 60: parser.error('poll-seconds must be between 1 and 60')
    try:
        result = run_campaign(args.repo, args.phase, args.approval, mode=args.mode,
            recovery_approval_path=args.recovery_approval, one_wave=args.one_wave,
            escalate=args.escalate, poll_seconds=args.poll_seconds)
    except Exception as exc:
        # Exception messages may contain runtime/provider context; only classify.
        print(json.dumps({'status': 'held', 'error_type': type(exc).__name__}), flush=True)
        return 1
    return 0 if result.get('status') in ('complete', 'wave_gated') else 2


if __name__ == '__main__':
    raise SystemExit(main())
