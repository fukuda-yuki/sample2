"""Immutable administrative succession of one fixed logical-100 campaign.

No acquisition, evaluation, cleanup, STOP removal, or publication occurs here.
Creation is explicit and requires a committed controller, closed old waves and
exclusive old ownership. Failed creation keeps all new evidence and retirement.
"""
from contextlib import ExitStack
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from outer.harness import run, runtime, util
from outer.harness.security import child_environment
from research import live_pilot, pair_execution, repaired_runtime
from research import repaired_campaign as campaign

KIND = 'repaired_campaign_successor_v1'
PIN = 'research/campaign_transition.py'
PRESERVED = ('campaign_id', 'slots', 'settings', 'bounds', 'policy', 'base_plan',
             'storage_policy', 'readiness_source_repo')


def _ref(path):
    return live_pilot.reference(path)


def _read(ref):
    return util.read_json(live_pilot.checked(ref))


def _digest(value):
    return util.sha256_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def _history(ref, seen=None):
    seen = set() if seen is None else seen
    path = live_pilot.checked(ref)
    if str(path) in seen:
        raise ValueError('Cyclic campaign history')
    seen.add(str(path))
    history = util.read_json(path)
    if history.get('kind') != KIND+'_history' or history.get('schema_version') != 1:
        raise ValueError('Wrong immutable predecessor history')
    old = _read(history['campaign'])
    original = live_pilot.checked(history['original_ledger'])
    snapshot = live_pilot.checked(history['ledger_snapshot'])
    if (original != live_pilot.safe_path(Path(old['batch'])/'attempts.jsonl')
            or snapshot != path.parent/'attempts.jsonl'
            or snapshot.read_bytes() != original.read_bytes()
            or history['original_ledger']['sha256'] != history['ledger_snapshot']['sha256']):
        raise ValueError('History is not the exact immutable old ledger')
    inherited = history.get('inherited_history')
    expected = (old.get('predecessor') or {}).get('history')
    if inherited != expected:
        raise ValueError('Inherited campaign history dropped or substituted')
    events = _history(inherited, seen)[1] if inherited else []
    events = events + pair_execution.events(snapshot)
    if history.get('event_count') != len(events) or history.get('accepted_slots') != _accepted(events):
        raise ValueError('Historical attempt/adoption denominator changed')
    return history, events


def history_events(plan):
    """Exact prior events, including failures and earlier administrative roots."""
    predecessor = plan.get('predecessor')
    return _history(predecessor['history'])[1] if predecessor else []


def reserved_instance_ids(plan):
    """All predecessor epoch UUIDs, including never-dispatched reservations."""
    identities, seen = set(), set()
    reference = (plan.get('predecessor') or {}).get('history')
    while reference:
        history, _ = _history(reference)
        if reference['sha256'] in seen:
            raise ValueError('Cyclic epoch inheritance')
        seen.add(reference['sha256'])
        for epoch_ref in history['epoch_plans']:
            epoch = _read(epoch_ref)
            cases = [case for pair in epoch['assignments'] for case in pair['cases']]
            ids = [case['run_instance_id'] for case in cases]
            if len(ids) != 200 or len(set(ids)) != 200 or any(not re.fullmatch('[a-f0-9]{32}', value) for value in ids):
                raise ValueError('Exact 200 fixed epoch UUIDs required')
            if identities.intersection(ids):
                raise ValueError('Predecessor epochs reused a reserved Run UUID')
            identities.update(ids)
        reference = history.get('inherited_history')
    return identities


def _accepted(events):
    accepted = [e['slot'] for e in events if e.get('kind') == 'pair_accepted']
    if len(accepted) != len(set(accepted)) or any(type(n) is not int or not 1 <= n <= 100 for n in accepted):
        raise ValueError('Duplicate or invalid accepted logical slot')
    return sorted(accepted)


def _wave_inventory(repo, path, plan):
    root = Path(plan['batch'])
    rows = []
    for wave_path in sorted((root/'waves').glob('*/spec.json')):
        closure_path = wave_path.parent/'closure.json'
        campaign.verify_closure(repo, path, wave_path, closure_path)
        wave = campaign.wave_spec(repo, path, wave_path)
        from research import campaign_recovery
        ctx = campaign_recovery._context(repo, path, wave_path)
        launcher = campaign_recovery._owned_closure(ctx)
        rows.append(dict(wave=_ref(wave_path), closure=_ref(closure_path), launcher=launcher,
                         epoch_plan=wave['epoch_plan']))
    reserved = [e for e in pair_execution.events(root/'attempts.jsonl') if e['kind'] == 'pair_attempt_reserved']
    known = {row['wave']['sha256'] for row in rows}
    if {event['wave']['sha256'] for event in reserved} != known:
        raise ValueError('Every old reserved wave requires its actual closed wave')
    for event in reserved:
        wave = _read(event['wave'])
        if (event['slot'] not in wave['pairs'] or event['epoch_plan'] != wave['epoch_plan']
                or wave['campaign'] != _ref(path)):
            raise ValueError('Old reservation does not bind its retained wave')
    return rows


def _owned_idle(repo, path, plan, waves):
    """Read-only actual owned-resource checks; no resource is removed or signaled."""
    from research import campaign_launcher, live_pilot_launcher, saved_reassessment
    containers = runtime.docker('ps', '-a', '--no-trunc', '--format', '{{json .}}', timeout=30)
    listing = [json.loads(line) for line in containers.stdout.splitlines() if line.strip()]
    networks = runtime.docker('network', 'ls', '--no-trunc', '--format', '{{json .}}', timeout=30)
    net_listing = [json.loads(line) for line in networks.stdout.splitlines() if line.strip()]
    if any(row.get('Names', '').startswith('s2-score-') for row in listing):
        raise ValueError('Unresolved scoring resource prevents retirement')
    evidence = []
    for row in waves:
        wave, epoch = _read(row['wave']), _read(row['epoch_plan'])
        for number in wave['pairs']:
            for owned in live_pilot_launcher.owned_runs(epoch, row['epoch_plan'], number):
                if owned['status'] == 'not_allocated':
                    evidence.append(owned)
                    continue
                if owned['status'] != 'owned_allocated':
                    raise ValueError('Unknown old Run ownership prevents retirement')
                root = live_pilot.safe_path(owned['root'])
                state, manifest = (util.read_json(root/name) for name in ('runtime.json', 'manifest.json'))
                if any(v.get('stop_confirmed') is not True for v in (state, manifest)):
                    raise ValueError('Old acquisition stop is unconfirmed')
                for role in ('worker', 'gateway'):
                    present = [item for item in listing if item.get('Names') == state[role]]
                    if present:
                        actual = runtime._owned_container(state, role)
                        if actual is None or any(actual['State'].get(k) for k in ('Running', 'Paused', 'Restarting')):
                            raise ValueError('Old worker/gateway still active or foreign')
                if any(item.get('Name') == state['network'] or item.get('ID') == state['network_id'] for item in net_listing):
                    raise ValueError('Old owned network still exists')
                for resource_file in root.rglob('browser-resources.json'):
                    if not saved_reassessment._saved_cleanup_bound(resource_file.parent, owned['run_instance_id']):
                        raise ValueError('Old browser/scoring cleanup not confirmed')
                    resources = util.read_json(resource_file)['resources']
                    for resource in resources:
                        table, key = (listing, 'Names') if resource['kind'] == 'container' else (net_listing, 'Name')
                        if any(item.get(key) == resource['name'] or resource.get('id') and item.get('ID') == resource['id'] for item in table):
                            raise ValueError('Old assessment resource still exists')
                evidence.append(dict(owned, runtime=_ref(root/'runtime.json'), manifest=_ref(root/'manifest.json'),
                    resources_confirmed_inactive=True))
        # Bound old observer PIDs may conservatively hold retirement after PID
        # reuse, but they can never authorize signaling an unrelated process.
        for startup in (Path(epoch['batch'])/'_observers').glob('*/startup-ready.json'):
            value = util.read_json(startup)
            if not campaign_launcher.observer_exited(value.get('observer_pid'), timeout=0):
                raise ValueError('Old observer process exit remains unconfirmed')
    return evidence


def _compress(root):
    if os.name != 'nt':
        raise ValueError('This campaign requires Windows NTFS storage')
    subprocess.run(['compact.exe', '/C', str(root)], env=child_environment(), stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=True, timeout=30)
    if not root.stat().st_file_attributes & 0x800:
        raise ValueError('New successor compression unconfirmed')


def _clock(path, plan_ref):
    value = _read(_ref(path))
    stamp = value.get('started_at')
    if (value.get('plan_sha256') != plan_ref['sha256'] or not isinstance(stamp, str)
            or datetime.fromisoformat(stamp).tzinfo is None):
        raise ValueError('Original finite campaign clock missing or unbound')
    return value


def create_successor(*, repo, path, batch, predecessor_plan, predecessor_repo, authorization):
    """Explicit administrative transition only; invoke after committing new code."""
    repo, path, batch, old_repo, old_path = map(live_pilot.safe_path,
        (repo, path, batch, predecessor_repo, predecessor_plan))
    if path.exists() or batch.exists():
        raise FileExistsError('Successor path/root already exists; never overwrite or retry blindly')
    old_ref = _ref(old_path)
    old = campaign.validate(old_repo, old_path)
    old_root = live_pilot.safe_path(old['batch'])
    if repo == old_repo:
        raise ValueError('Successor requires a separate committed source checkout')
    for target in (path, batch):
        for protected in (repo, old_repo, old_root, *map(live_pilot.safe_path, old['protected_roots'])):
            if target == protected or target.is_relative_to(protected) or protected.is_relative_to(target):
                raise ValueError('New successor overlaps protected source/evidence')
    from research import next_phase
    if next_phase.git(repo, 'status', '--porcelain'):
        raise ValueError('Successor requires a clean committed checkout')
    commit = next_phase.git(repo, 'rev-parse', 'HEAD')
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Full successor commit identity required')
    names = set(old['source_pins']) | set(campaign.EXTRA_PINS) | {PIN}
    pins = {name: util.sha256_file(repo/name) for name in sorted(names)}
    repaired_runtime._committed_files(repo, commit, pins)
    with ExitStack() as stack:
        for control in ('_launcher-owner', '_control', '_allocation'):
            stack.enter_context(pair_execution.exclusive(old_root/control))
        old = campaign.validate(old_repo, live_pilot.checked(old_ref))
        old_stops = {_ref(p)['path']: util.sha256_file(p) for p in campaign.stop_markers(old)}
        if not old_stops:
            raise ValueError('Explicit stopped predecessor required')
        if any(util.read_json(p).get('kind') == KIND+'_retirement' for p in campaign.stop_markers(old)):
            raise ValueError('Predecessor is already permanently retired')
        waves = _wave_inventory(old_repo, old_path, old)
        ownership = _owned_idle(old_repo, old_path, old, waves)
        events = campaign.ledger(old)
        start_path = old_root/'execution-start.json'
        start = _clock(start_path, old_ref)
        usage = campaign.observed_usage(old)
        if usage['usage_journal_errors'] or usage['missing_duration_runs']:
            raise ValueError('Prior usage must be reconciled before succession')
        old_ledger = _ref(old_root/'attempts.jsonl')
        epochs = [_ref(p) for p in sorted((old_root/'epochs').glob('*/plan.json'))]
        if not epochs or any(row['epoch_plan'] not in epochs for row in waves):
            raise ValueError('Every old wave must bind a retained complete epoch')
        batch.mkdir(parents=True, exist_ok=False)
        _compress(batch)
        history_dir = batch/'history'; history_dir.mkdir()
        snapshot = history_dir/'attempts.jsonl'
        shutil.copyfile(live_pilot.checked(old_ledger), snapshot)
        if _ref(snapshot)['sha256'] != old_ledger['sha256']:
            raise ValueError('Ledger copy differs; retained successor is unusable')
        transition = uuid.uuid4().hex
        history = dict(schema_version=1, kind=KIND+'_history', transition_id=transition,
            campaign=old_ref, original_ledger=old_ledger, ledger_snapshot=_ref(snapshot),
            inherited_history=(old.get('predecessor') or {}).get('history'), event_count=len(events),
            accepted_slots=_accepted(events), epoch_plans=epochs, waves=waves,
            original_execution_start=_ref(start_path), observed_usage=usage,
            existing_stop_hashes=old_stops, owned_resources_at_retirement=ownership)
        history_path = history_dir/'predecessor.json'
        util.write_new_json(history_path, history)
        new = copy.deepcopy(old)
        new.update(source_commit=commit, source_pins=pins, batch=str(batch),
            protected_roots=list(dict.fromkeys(old['protected_roots']+[str(old_root), str(old_repo)])),
            authorization_reference=authorization, created_at=run.now())
        # The old executable already treats this explicit STOP as uncleared.
        # No existing STOP or clearance is changed. A failed subsequent write
        # therefore leaves the old campaign safely and permanently fenced.
        retirement_path = old_root/'_control/stop-events'/('retirement-'+transition+'.json')
        retirement = dict(schema_version=1, kind=KIND+'_retirement', transition_id=transition,
            reason='explicit_stop', permanent=True, plan_sha256=old_ref['sha256'], campaign=old_ref,
            history=_ref(history_path), successor=dict(path=str(path), batch=str(batch),
                campaign_id=old['campaign_id'], source_commit=commit, source_pins_sha256=_digest(pins)),
            requested_at=run.now(), scope='administrative retirement; never eligible for STOP clearance')
        # Check mutable old boundaries once more before the permanent fence.
        live_pilot.checked(old_ledger)
        if any(util.sha256_file(p) != sha for p, sha in old_stops.items()):
            raise ValueError('Predecessor STOP evidence changed during transition')
        util.write_new_json(retirement_path, retirement)
        new['predecessor'] = dict(plan=old_ref, source_repo=str(old_repo), history=_ref(history_path),
                                  retirement=_ref(retirement_path))
        util.write_new_json(path, new)
        new_ref = _ref(path)
        util.write_new_json(batch/'allocation.json', dict(campaign=new_ref, slots=100, actual_model_dispatches=0,
            inherited_pair_attempts=sum(e['kind'] == 'pair_attempt_reserved' for e in events),
            inherited_accepted_slots=history['accepted_slots'], history=new['predecessor']['history']))
        util.write_new_json(batch/'authorization.json', dict(authorized=True, approved_by='user',
            authorization_reference=authorization, plan_sha256=new_ref['sha256'],
            scope='continue_same_100_logical_slots_and_finite_accumulated_budget',
            predecessor=old_ref, source='delegated user instruction; no per-pair reconfirmation'))
        util.write_new_json(batch/'execution-start.json', dict(start, plan_sha256=new_ref['sha256'],
            inherited_from=_ref(start_path)))
        validate_predecessor(repo, new)
        campaign.validate(repo, path)
        return new


def validate_predecessor(repo, plan):
    """Read-only original-byte, closure, permanent-fence and clock validation."""
    predecessor = plan.get('predecessor')
    if not predecessor:
        return True
    if set(predecessor) != {'plan', 'source_repo', 'history', 'retirement'}:
        raise ValueError('Complete typed predecessor binding required')
    repo = live_pilot.safe_path(repo)
    if plan.get('source_pins', {}).get(PIN) != util.sha256_file(repo/PIN):
        raise ValueError('Successor transition implementation must be pinned')
    old_repo = live_pilot.safe_path(predecessor['source_repo'])
    old_path = live_pilot.checked(predecessor['plan'])
    old = campaign.validate(old_repo, old_path)
    repaired_runtime._committed_files(old_repo, old['source_commit'], old['source_pins'])
    if repo == old_repo or any(plan.get(k) != old.get(k) for k in PRESERVED):
        raise ValueError('Successor changed original campaign identity/design/budget')
    root, old_root = live_pilot.safe_path(plan['batch']), live_pilot.safe_path(old['batch'])
    if root == old_root or root.is_relative_to(old_root) or old_root.is_relative_to(root):
        raise ValueError('Successor must have a separate storage root')
    history, events = _history(predecessor['history'])
    if (history['campaign'] != predecessor['plan']
            or live_pilot.checked(predecessor['history']) != root/'history/predecessor.json'
            or history['waves'] != _wave_inventory(old_repo, old_path, old)
            or history['epoch_plans'] != [_ref(p) for p in sorted((old_root/'epochs').glob('*/plan.json'))]
            or history['observed_usage'] != campaign.observed_usage(old)):
        raise ValueError('Retained predecessor evidence changed or was omitted')
    retirement_path = live_pilot.checked(predecessor['retirement'])
    retirement = util.read_json(retirement_path)
    if (retirement_path.parent != old_root/'_control/stop-events'
            or retirement.get('kind') != KIND+'_retirement' or retirement.get('reason') != 'explicit_stop'
            or retirement.get('permanent') is not True or retirement.get('plan_sha256') != predecessor['plan']['sha256']
            or retirement.get('campaign') != predecessor['plan'] or retirement.get('history') != predecessor['history']
            or retirement.get('transition_id') != history['transition_id']
            or retirement.get('successor') != dict(path=str(_successor_path(root)), batch=str(root),
                campaign_id=plan['campaign_id'], source_commit=plan['source_commit'],
                source_pins_sha256=_digest(plan['source_pins']))):
        raise ValueError('Permanent predecessor retirement is missing or foreign')
    if any(util.sha256_file(path) != digest for path, digest in history['existing_stop_hashes'].items()):
        raise ValueError('Original STOP bytes changed')
    for clearance in (old_root/'_control/clearances').glob('*.json'):
        if str(retirement_path) in util.read_json(clearance).get('stops', {}):
            raise ValueError('Permanent retirement must never receive a clearance')
    if campaign.campaign_stop_pending(old) is not True:
        raise ValueError('Old campaign is not permanently fenced')
    start_ref = history['original_execution_start']
    if live_pilot.checked(start_ref) != old_root/'execution-start.json':
        raise ValueError('Foreign predecessor clock')
    original = _clock(start_ref['path'], predecessor['plan'])
    new_start = util.read_json(root/'execution-start.json')
    new_ref = _ref(_successor_path(root))
    expected_allocation = dict(campaign=new_ref, slots=100, actual_model_dispatches=0,
        inherited_pair_attempts=sum(e['kind'] == 'pair_attempt_reserved' for e in events),
        inherited_accepted_slots=history['accepted_slots'], history=predecessor['history'])
    expected_authorization = dict(authorized=True, approved_by='user',
        authorization_reference=plan['authorization_reference'], plan_sha256=new_ref['sha256'],
        scope='continue_same_100_logical_slots_and_finite_accumulated_budget', predecessor=predecessor['plan'],
        source='delegated user instruction; no per-pair reconfirmation')
    if (new_start != dict(original, plan_sha256=new_ref['sha256'], inherited_from=start_ref)
            or util.read_json(root/'allocation.json') != expected_allocation
            or util.read_json(root/'authorization.json') != expected_authorization):
        raise ValueError('Successor allocation/authorization/elapsed clock was reset or unbound')
    reserved_instance_ids(plan)
    return True


def _successor_path(root):
    allocation = util.read_json(root/'allocation.json')
    return live_pilot.checked(allocation['campaign'])
