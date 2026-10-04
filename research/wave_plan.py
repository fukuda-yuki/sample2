"""Separate execution amendment; never changes the frozen v5 scientific plan.

Preparation is offline. The caller freezes this manifest, new source pins,
resource thresholds and a separate exact-phase user approval before dispatch.
"""
from collections import Counter
from pathlib import Path

from outer.harness import util
from research import next_phase, pair_execution

KIND = 'source_info_v5_central_fixed_wave_phase_v1'
V2_KIND = 'source_info_v5_central_fixed_wave_phase_v2'
V3_KIND = 'source_info_v5_central_fixed_wave_phase_v3'
V4_KIND = 'source_info_v5_central_fixed_wave_phase_v4'
V4_PROBE_SHA = '75f9bad0c64adce29527f90023ebee9f5522cad5c495f824a971c617e96a98f4'
V3_PROBE_SHA = '5efb52edd48f37713b623df46d01ebbd89e2e3321c6548fe1ac2982bd97c9354'
MONITOR_SHA = 'fcd37689e47423e5f9400ace9080ec2315ba3ad79df6a715f264547dc30f5a67'
HEALTH_FLAGS = ('host_healthy', 'resource_healthy', 'journal_healthy',
                'http_healthy', 'provider_healthy')
RESOURCE_LIMITS = ('host_memory_available_min_bytes', 'docker_memory_available_min_bytes',
                   'disk_free_min_bytes', 'cpu_percent_max', 'http_inflight_max')


def shard_mapping(assignments):
    """24/24/24/23 responsibilities with each variant count differing by <=1."""
    capacities = [24, 24, 24, 23]
    totals = [0] * 4
    variants = [Counter() for _ in capacities]
    result = {}
    # Sorting only assigns responsibility; dispatch retains the original order.
    for task in sorted({p['task'] for p in assignments}):
        for pair in (p for p in assignments if p['task'] == task):
            eligible = [i for i in range(4) if totals[i] < capacities[i]]
            owner = min(eligible, key=lambda i: (variants[i][task], totals[i], i))
            result[str(pair['pair'])] = owner + 1
            totals[owner] += 1
            variants[owner][task] += 1
    if totals != capacities or any(max(v[t] for v in variants) - min(v[t] for v in variants) > 1
                                  for t in sorted({p['task'] for p in assignments})):
        raise ValueError('Remaining assignments cannot satisfy balanced fixed responsibilities')
    return result


def build(original_bundle, old_journal, batch, *, thresholds, source_commit, source_pins, operational_policy,
          preparation_view=None):
    original = util.read_json(original_bundle)
    next_phase.validate_plan(original['plan'])
    if original['plan']['plan_id'] != next_phase.V5_ID:
        raise ValueError('Only the exact v5 global200 allocation is supported')
    remaining = original['assignments'][5:]
    phase = {'schema_version': 1, 'kind': KIND, 'phase_id': 'central-wave-pair6-100-v1',
        'original_bundle': next_phase.reference(original_bundle),
        'old_journal': next_phase.reference(old_journal), 'batch': str(Path(batch).resolve()),
        'cohort': original['cohort'], 'runtime': original['runtime_id'],
        'source_commit': source_commit, 'source_pins': source_pins,
        'completed_pairs': list(range(1, 6)), 'assignments': remaining,
        'shards': shard_mapping(remaining), 'responsibility_counts': [24, 24, 24, 23],
        'two_pair_blocks': [list(range(i, min(i + 2, 101))) for i in range(6, 101, 2)],
        'initial_pairs': 2, 'maximum_pairs': 4, 'internal_concurrency': 1,
        'no_refill': True, 'use_balance': False, 'paid_fallback': False,
        'thresholds': thresholds, 'escalation_flags': list(HEALTH_FLAGS),
        'operational_policy': next_phase.reference(operational_policy),
        'research_start_authorized': False}
    if preparation_view is not None: phase['preparation_view'] = preparation_view
    validate(phase)
    return phase


def validate(phase, *, repo=None):
    if phase.get('kind') == V4_KIND:
        return validate_v4(phase, repo=repo)
    if phase.get('kind') == V3_KIND:
        return validate_v3(phase, repo=repo)
    if phase.get('kind') == V2_KIND:
        return validate_v2(phase, repo=repo)
    if (phase.get('kind') != KIND or phase.get('schema_version') != 1
            or phase.get('phase_id') != 'central-wave-pair6-100-v1'
            or phase.get('completed_pairs') != list(range(1, 6))
            or phase.get('responsibility_counts') != [24, 24, 24, 23]
            or phase.get('initial_pairs') != 2 or phase.get('maximum_pairs') != 4
            or phase.get('internal_concurrency') != 1 or phase.get('no_refill') is not True
            or phase.get('use_balance') is not False or phase.get('paid_fallback') is not False
            or phase.get('research_start_authorized') is not False
            or phase.get('escalation_flags') != list(HEALTH_FLAGS)):
        raise ValueError('Unsupported wave amendment')
    for field in ('original_bundle', 'old_journal', 'operational_policy'):
        if not next_phase.verify_reference(phase[field]):
            raise ValueError('Immutable transition reference changed: ' + field)
    original = util.read_json(phase['original_bundle']['path'])
    if phase.get('preparation_view'):
        view = phase['preparation_view']
        if (not Path(view['path']).is_absolute() or not next_phase.verify_reference(view['witness'])
                or util.read_json(view['witness']['path']).get('original_bundle_sha256') != phase['original_bundle']['sha256']):
            raise ValueError('Prospective preparation view lacks original-bundle-bound witness')
    next_phase.validate_plan(original['plan'])
    if (original['plan']['plan_id'] != next_phase.V5_ID
            or original['assignments'] != next_phase.assignments(original['plan'])
            or phase['assignments'] != original['assignments'][5:]
            or phase['cohort'] != original['cohort'] or phase['runtime'] != original['runtime_id']):
        raise ValueError('Original global slot/instance/input/priority assignment changed')
    if phase['shards'] != shard_mapping(phase['assignments']):
        raise ValueError('Fixed balanced responsibilities changed')
    if phase['two_pair_blocks'] != [list(range(i, min(i + 2, 101))) for i in range(6, 101, 2)]:
        raise ValueError('Fixed wave blocks changed')
    if (set(phase['thresholds']) != set(RESOURCE_LIMITS)
            or any(type(v) not in (int, float) or v <= 0 for v in phase['thresholds'].values())
            or phase['thresholds']['cpu_percent_max'] > 100
            or not phase.get('source_commit') or not phase.get('source_pins')):
        raise ValueError('Predeclared objective thresholds and new source pins required')
    if repo is not None:
        root = Path(repo).resolve()
        if (root / phase['cohort']).resolve() != Path(phase['batch']).resolve():
            raise ValueError('Canonical shared registry must be this cohort batch')
        for name, digest in phase['source_pins'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or util.sha256_file(path) != digest:
                raise ValueError('New phase code/environment pin changed: ' + name)
    old = pair_execution.state(phase['old_journal']['path'])
    expected = {c['run_id']: c for p in original['assignments'][:5] for c in p['cases']}
    if (set(old['dispatch']) != set(expected) or set(old['reserved']) != set(expected)
            or set(old['gates']) != set(range(1, 6)) or old['pending']
            or set(old['results']) != set(expected)
            or any(d['run_instance_id'] != expected[r]['run_instance_id']
                   or d['slot'] != expected[r]['slot']
                   or d['plan_sha256'] != phase['original_bundle']['sha256']
                   or old['implementations'][r]['receipt'].get('stop_confirmed') is not True
                   for r, d in old['dispatch'].items())):
        raise ValueError('Exactly old10 once-only dispatches and five completed gates required')
    return original


def _fixed_originals(batch, current):
    """Verify original raw/snapshot bytes; mutable manifests are not rehashed."""
    batch = Path(batch)
    for rid, binding in current['dispatch'].items():
        receipt = current['implementations'].get(rid, {}).get('receipt', {})
        root = batch / rid
        if (receipt.get('stop_confirmed') is not True or receipt.get('submission_fixed') is not True
                or receipt.get('collection_status') == 'collection_fault' or receipt.get('collection_error_type')
                or not receipt.get('raw') or not receipt.get('snapshot_sha256')
                or util.tree_hashes(root / 'usage/raw') != receipt['raw']
                or util.sha256_file(root / 'snapshot.json') != receipt['snapshot_sha256']):
            raise ValueError('Predecessor stop/fixed original raw/snapshot proof missing or changed: ' + rid)
        manifest = util.read_json(root / 'manifest.json')
        if (manifest.get('run_id') != rid or manifest.get('run_instance_id') != binding['run_instance_id']
                or manifest.get('stop_confirmed') is not True or manifest.get('submission_fixed') is not True):
            raise ValueError('Predecessor original instance/stop/fix changed: ' + rid)


def predecessor_state(phase):
    """Read frozen history without applying a new HEAD to old source pins."""
    from research import wave_dispatch
    ref, journal = phase['predecessor_phase'], phase['predecessor_journal']
    if not next_phase.verify_reference(ref) or not next_phase.verify_reference(journal):
        raise ValueError('Predecessor phase/journal bytes changed')
    previous = util.read_json(ref['path'])
    expected_kind = {V4_KIND: V3_KIND, V3_KIND: V2_KIND}.get(phase.get('kind'), KIND)
    if previous.get('kind') != expected_kind: raise ValueError('Successor must retain the exact preceding phase version')
    original = validate(previous)
    for key in ('resource_monitor', 'resource_probe', 'resource_collector_acceptance'):
        if not next_phase.verify_reference(previous[key]): raise ValueError('Historical collector proof changed: ' + key)
    expected_journal = Path(previous['batch']) / '_control' / previous['phase_id'] / 'wave-journal.jsonl'
    if Path(journal['path']).resolve() != expected_journal.resolve(): raise ValueError('Wrong predecessor journal location')
    current = wave_dispatch.state(journal['path'], previous, ref['sha256'])
    prior_pairs = {V3_KIND: range(14, 18), V2_KIND: range(12, 14)}.get(expected_kind, range(6, 12))
    expected = {c['run_id']: c for p in original['assignments'] if p['pair'] in prior_pairs for c in p['cases']}
    if (current['pending'] or set(current['dispatch']) != set(expected) or set(current['reserved']) != set(expected)
            or set(current['implementations']) != set(expected) or set(current['results']) != set(expected)
            or set(current['gates']) != set(prior_pairs)
            or any(current['dispatch'][rid]['run_instance_id'] != c['run_instance_id'] for rid, c in expected.items())):
        raise ValueError('All and only predecessor boundary pairs must be stopped/fixed/scored/gated before transition')
    gates = {str(n): {'path': gate['receipt_path'], 'sha256': gate['receipt_sha256']} for n, gate in current['gates'].items()}
    if phase['predecessor_gates'] != gates: raise ValueError('Exact predecessor gate references changed')
    old = pair_execution.state(previous['old_journal']['path'])
    _fixed_originals(previous['batch'], old)
    _fixed_originals(previous['batch'], current)
    return previous, original, current


def build_v2(predecessor_phase, predecessor_journal, *, source_commit, source_pins,
             resource_monitor, resource_probe, resource_collector_acceptance):
    """Offline builder rejects an active predecessor's cohort lease."""
    previous = util.read_json(predecessor_phase)
    with pair_execution.exclusive(Path(previous['batch']) / '_control', phase_permit=util.sha256_file(predecessor_phase)):
        return _build_v2(predecessor_phase, predecessor_journal, source_commit=source_commit,
            source_pins=source_pins, resource_monitor=resource_monitor, resource_probe=resource_probe,
            resource_collector_acceptance=resource_collector_acceptance)


def _build_v2(predecessor_phase, predecessor_journal, *, source_commit, source_pins,
              resource_monitor, resource_probe, resource_collector_acceptance):
    from research import wave_dispatch
    previous = util.read_json(predecessor_phase)
    current = wave_dispatch.state(predecessor_journal, previous, util.sha256_file(predecessor_phase))
    phase = {**previous, 'schema_version': 2, 'kind': V2_KIND, 'phase_id': 'central-wave-pair12-100-v2',
        'source_commit': source_commit, 'source_pins': source_pins,
        'completed_pairs': list(range(1, 12)), 'assignments': previous['assignments'][6:],
        'shards': {k: v for k, v in previous['shards'].items() if int(k) >= 12},
        'responsibility_counts': [sum(v == owner for k, v in previous['shards'].items() if int(k) >= 12) for owner in range(1, 5)],
        'two_pair_blocks': [list(range(i, min(i + 2, 101))) for i in range(12, 101, 2)],
        'maximum_pairs': 2, 'escalation_allowed': False,
        'predecessor_phase': next_phase.reference(predecessor_phase),
        'predecessor_journal': next_phase.reference(predecessor_journal),
        'predecessor_gates': {str(n): {'path': g['receipt_path'], 'sha256': g['receipt_sha256']} for n, g in current['gates'].items()},
        'resource_monitor': resource_monitor, 'resource_probe': resource_probe,
        'resource_collector_acceptance': resource_collector_acceptance}
    validate_v2(phase)
    return phase


def validate_v2(phase, *, repo=None):
    previous, original, _ = predecessor_state(phase)
    if (phase.get('schema_version') != 2 or phase.get('phase_id') != 'central-wave-pair12-100-v2'
            or phase.get('completed_pairs') != list(range(1, 12))
            or phase.get('assignments') != original['assignments'][11:]
            or phase.get('two_pair_blocks') != [list(range(i, min(i + 2, 101))) for i in range(12, 101, 2)]
            or phase.get('initial_pairs') != 2 or phase.get('maximum_pairs') != 2
            or phase.get('escalation_allowed') is not False or not phase.get('source_commit') or not phase.get('source_pins')):
        raise ValueError('Unsupported v2 future-only178-slot conservative4-Run amendment')
    mutable = {'schema_version', 'kind', 'phase_id', 'source_commit', 'source_pins', 'completed_pairs',
        'assignments', 'shards', 'responsibility_counts', 'two_pair_blocks', 'maximum_pairs',
        'resource_monitor', 'resource_probe', 'resource_collector_acceptance'}
    if any(phase.get(k) != v for k, v in previous.items() if k not in mutable):
        raise ValueError('V2 cannot change original model/input/criteria/budgets/operational policy thresholds')
    inherited = {k: v for k, v in previous['shards'].items() if int(k) >= 12}
    if (phase.get('shards') != inherited or phase.get('responsibility_counts') !=
            [sum(v == owner for v in inherited.values()) for owner in range(1, 5)]):
        raise ValueError('V2 responsibilities must inherit the frozen mapping without reassignment')
    for key in ('resource_monitor', 'resource_probe', 'resource_collector_acceptance'):
        if not next_phase.verify_reference(phase[key]): raise ValueError('New collector reference changed: ' + key)
    if phase['resource_monitor']['sha256'] != previous['resource_monitor']['sha256']:
        raise ValueError('Resource monitor rules cannot change in a probe-only amendment')
    acceptance = util.read_json(phase['resource_collector_acceptance']['path'])
    required = {'kind': 'resource_probe_only_v2_nonlive_acceptance',
        'previous_probe_sha256': previous['resource_probe']['sha256'],
        'resource_probe_sha256': phase['resource_probe']['sha256'],
        'resource_monitor_sha256': phase['resource_monitor']['sha256'],
        'operational_policy_sha256': previous['operational_policy']['sha256'],
        'fail_closed_unchanged': True, 'model_called': False, 'run_created': False}
    if any(acceptance.get(k) != v for k, v in required.items()):
        raise ValueError('Nonlive acceptance must bind exact old/new probe, unchanged monitor/policy and fail-closed rules')
    monitor, probe = Path(phase['resource_monitor']['path']).resolve(), Path(phase['resource_probe']['path']).resolve()
    if probe != monitor.with_name('wave_resource_probe.py'): raise ValueError('New private probe must accompany its monitor')
    if (probe == Path(previous['resource_probe']['path']).resolve()
            or monitor == Path(previous['resource_monitor']['path']).resolve()):
        raise ValueError('New collector cannot overwrite predecessor helper originals')
    if repo is not None:
        root = Path(repo).resolve()
        if (root / phase['cohort']).resolve() != Path(phase['batch']).resolve(): raise ValueError('Wrong canonical cohort')
        for name, digest in phase['source_pins'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or util.sha256_file(path) != digest: raise ValueError('New v2 source pin changed: ' + name)
    return original



def _checked_json(phase, key):
    reference = phase.get(key)
    if not isinstance(reference, dict) or not next_phase.verify_reference(reference):
        raise ValueError('Required final v3 acceptance reference missing or changed: ' + key)
    return util.read_json(reference['path'])


def _utc_timestamp(value):
    from datetime import datetime, timezone
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None: raise ValueError('Evidence timestamp must retain timezone')
    return stamp.astimezone(timezone.utc)



def _verify_bound_leaf(reference, checked):
    """Check one declared leaf, deduplicating only within this validation call."""
    if not isinstance(reference, dict) or not {'path', 'sha256'} <= reference.keys():
        raise ValueError('Complete immutable acceptance leaf reference required')
    key = (str(Path(reference['path']).resolve()), reference['sha256'])
    if key not in checked:
        if not next_phase.verify_reference(reference):
            raise ValueError('Listed acceptance evidence leaf changed: ' + reference['path'])
        checked.add(key)


def _verify_soak_observations(soak, result, checked):
    observations = soak.get('observations')
    if not isinstance(observations, list) or len(observations) != 183:
        raise ValueError('Exactly183 sequential soak observations required')
    seen, session = set(), None
    for number, observation in enumerate(observations, 1):
        label = ('scheduled' if number <= 180 else
                 ('controlled-worker-stop', 'controlled-gateway-stop', 'controlled-all-stop')[number - 181])
        raw, monitor = observation.get('raw'), observation.get('monitor')
        if (observation.get('sequence') != number or not isinstance(raw, dict)
                or not isinstance(monitor, dict) or len(monitor) != 1):
            raise ValueError('Soak observations must retain sequential unique raw/monitor bindings')
        raw_path, monitor_path = Path(raw['path']).resolve(), Path(next(iter(monitor))).resolve()
        if (raw_path in seen or monitor_path in seen or raw_path == monitor_path
                or raw_path.name != f'{number:06d}-' + label + '.json'
                or not monitor_path.name.endswith(f'-{number:06d}.json')):
            raise ValueError('Swapped/duplicate/mislabelled soak observation evidence')
        seen.update((raw_path, monitor_path))
        _verify_bound_leaf(raw, checked)
        _verify_bound_leaf({'path': str(monitor_path), 'sha256': next(iter(monitor.values()))}, checked)
        sample, record = util.read_json(raw_path), util.read_json(monitor_path)
        if (record.get('sequence') != number or record.get('expected_runs') != 4
                or record.get('schema') != 'prospective-wave-resource-observation-v1'
                or record.get('sample') != sample or sample.get('ok') is not True or record.get('faults') != []):
            raise ValueError('Raw/monitor observation sequence or exact sample binding changed')
        if number == 1: session = record.get('monitor_session')
        if not session or record.get('monitor_session') != session:
            raise ValueError('Soak observations must belong to one monitor session')
        if number > 180:
            transition = result['transition_observations'][number - 181]
            if transition.get('raw') != raw or transition.get('monitor') != monitor:
                raise ValueError('Controlled stop-stage references differ from exact final183 observations')

def _validate_v3_acceptance(phase, previous):
    """Technical success alone cannot close the retained formal-dispatch hold."""
    finite = _checked_json(phase, 'finite_acceptance')
    soak = _checked_json(phase, 'actual_soak_verification')
    review = _checked_json(phase, 'post_soak_independent_review')
    boundary = _checked_json(phase, 'post_v2_boundary')
    hold_boundary = _checked_json(phase, 'hold_boundary')
    _checked_json(phase, 'revised_hold_instruction')
    decision = _checked_json(phase, 'resource_collector_acceptance')
    checked = set()
    # The existing finite receipt lists original source/fixture references directly.
    for reference in finite.values():
        if isinstance(reference, dict) and {'path', 'sha256'} <= reference.keys():
            _verify_bound_leaf(reference, checked)
    inputs = review.get('input_references')
    if not isinstance(inputs, list) or not inputs or any(not isinstance(r, dict) or 'path' not in r or 'sha256' not in r for r in inputs):
        raise ValueError('Independent review must retain all listed immutable input references')
    for reference in inputs: _verify_bound_leaf(reference, checked)
    probe, monitor = phase['resource_probe']['sha256'], phase['resource_monitor']['sha256']
    if (finite.get('candidate', {}).get('sha256') != probe
            or finite.get('unchanged_monitor', {}).get('sha256') != monitor
            or finite.get('all_native_expected_decisions_passed') is not True):
        raise ValueError('Exact candidate finite acceptance required')
    for reference in (finite['candidate'], finite['unchanged_monitor']):
        if not next_phase.verify_reference(reference): raise ValueError('Finite candidate bytes changed')
    if (boundary.get('kind') != 'quiescent_pre_v3_boundary'
            or boundary.get('phase') != phase['predecessor_phase']
            or boundary.get('journal') != phase['predecessor_journal']
            or boundary.get('gates') != phase['predecessor_gates']
            or boundary.get('actual_sent') != 26 or boundary.get('all_stopped_fixed') is not True
            or boundary.get('active_run_containers_at_final_recovery_sample') != 0
            or boundary.get('recovery_controller_exit_code') != 0):
        raise ValueError('Exact quiescent26-instance/13-gate boundary required')
    _utc_timestamp(boundary['at'])
    if (hold_boundary.get('kind') != 'quiescent_post_v2_recurrence_boundary'
            or hold_boundary.get('phase') != phase['predecessor_phase']
            or hold_boundary.get('journal') != phase['predecessor_journal']
            or hold_boundary.get('gates') != phase['predecessor_gates']
            or hold_boundary.get('total_actual_sent') != 26 or hold_boundary.get('remaining_original_unsent') != 174
            or hold_boundary.get('all26_stopped_fixed') is not True or hold_boundary.get('all13_gates_complete') is not True
            or hold_boundary.get('new_research_dispatch_held') is not True):
        raise ValueError('Original immutable post-v2 hold boundary required')
    hold_at = _utc_timestamp(hold_boundary['at'])
    if (soak.get('kind') != 'actual_nonmodel_soak_bounded_evidence_verification'
            or soak.get('scheduled_samples') != 180 or soak.get('controlled_stop_observations') != 3
            or soak.get('owned_fixtures_created_started_stopped_removed') != 8
            or soak.get('all_original_references_checked_unchanged') is not True
            or soak.get('original_research_sent_runs') != 26 or soak.get('remaining_original_unsent') != 174
            or soak.get('formal_research_resume_authorized') is not False
            or soak.get('historical_cause_resolved') is not False or soak.get('model_called') is not False):
        raise ValueError('Completed independently verified actual180+3 nonmodel soak required')
    for field in ('result', 'protocol', 'attempt', 'ownership', 'command_ledger'):
        if not next_phase.verify_reference(soak[field]): raise ValueError('Actual soak evidence changed')
    result, protocol = util.read_json(soak['result']['path']), util.read_json(soak['protocol']['path'])
    if (result.get('status') != 'passed' or result.get('completed_scheduled_samples') != 180
            or len(result.get('transition_observations', [])) != 3 or result.get('cleanup_errors') != []
            or result.get('model_called') is not False or result.get('research_dispatched') is not False
            or result.get('protocol_sha256') != soak['protocol']['sha256']
            or protocol.get('probe', {}).get('sha256') != probe or protocol.get('monitor', {}).get('sha256') != monitor
            or protocol.get('original_bundle') != phase['original_bundle']
            or protocol.get('source', {}).get('commit') != soak.get('source_commit')
            or not soak.get('source_commit')
            or protocol.get('scheduled_samples') != 180 or protocol.get('cadence_seconds') != 10):
        raise ValueError('Actual soak result/protocol does not bind exact reviewed candidate')
    _verify_soak_observations(soak, result, checked)
    if (review.get('kind') != 'actual_nonmodel_soak_independent_evidence_review_v3'
            or review.get('operational_soak_verified') is not True
            or review.get('historical_cause_resolved') is not False
            or review.get('formal_174_hold_remains') is not True
            or review.get('actual_verification') != phase['actual_soak_verification']
            or review.get('protocol') != soak['protocol'] or review.get('result') != soak['result']):
        raise ValueError('Exact advisory post-soak review must preserve unresolved historical cause and174 hold')
    bindings = {'source_commit': phase['source_commit'], 'original_bundle_sha256': phase['original_bundle']['sha256'],
        'post_v2_boundary': phase['post_v2_boundary'], 'hold_boundary': phase['hold_boundary'],
        'revised_hold_instruction': phase['revised_hold_instruction'], 'predecessor_journal_sha256': phase['predecessor_journal']['sha256'],
        'resource_probe_sha256': probe, 'resource_monitor_sha256': monitor,
        'operational_policy_sha256': previous['operational_policy']['sha256'],
        'finite_acceptance': phase['finite_acceptance'], 'actual_soak_verification': phase['actual_soak_verification'],
        'post_soak_independent_review': phase['post_soak_independent_review']}
    if (decision.get('kind') != 'prospective_resource_fault_recovery_decision_v3'
            or decision.get('formal_remaining_dispatch_authorized') is not True
            or decision.get('cause_condition_satisfied') is not True
            or type(decision.get('historical_cause_resolved')) is not bool
            or any(decision.get(k) != v for k, v in bindings.items())):
        raise ValueError('Explicit exact-source cause-condition recovery decision required; soak alone cannot authorize')
    mode = decision.get('acceptance_mode')
    if mode not in ('verified_mechanism_resolution', 'parent_explicit_revised_condition'):
        raise ValueError('Unsupported cause-condition acceptance mode')
    if mode == 'verified_mechanism_resolution' or decision['historical_cause_resolved']:
        evidence = decision.get('mechanism_resolution')
        if not decision['historical_cause_resolved'] or not evidence or not next_phase.verify_reference(evidence):
            raise ValueError('Historical mechanism resolution must have exact affirmative evidence')
        proof = util.read_json(evidence['path'])
        if (proof.get('kind') != 'verified_resource_transport_mechanism_resolution'
                or proof.get('historical_cause_resolved') is not True
                or proof.get('predecessor_journal_sha256') != phase['predecessor_journal']['sha256']
                or proof.get('resource_probe_sha256') != probe):
            raise ValueError('Mechanism evidence does not resolve this retained historical failure')
        evidence, independent = proof.get('causal_evidence'), proof.get('independent_review')
        if not evidence or not independent or not next_phase.verify_reference(evidence) or not next_phase.verify_reference(independent):
            raise ValueError('Separate genuine affirmative independent mechanism evidence required')
        checked = util.read_json(independent['path'])
        if (checked.get('kind') != 'verified_resource_transport_mechanism_independent_review'
                or checked.get('status') != 'passed' or checked.get('historical_cause_resolved') is not True
                or checked.get('causal_evidence') != evidence
                or checked.get('predecessor_journal_sha256') != phase['predecessor_journal']['sha256']
                or checked.get('resource_probe_sha256') != probe):
            raise ValueError('Advisory false post-soak facts cannot substitute for affirmative mechanism review')
    if mode == 'parent_explicit_revised_condition':
        instruction_ref = decision.get('parent_instruction')
        if not instruction_ref or not next_phase.verify_reference(instruction_ref):
            raise ValueError('New exact parent instruction required; existing hold is not permission')
        instruction = util.read_json(instruction_ref['path'])
        if (instruction.get('kind') != 'parent_explicit_revised_resource_fault_condition_instruction'
                or instruction.get('authority') != 'parent' or instruction.get('received_after_hold_boundary') is not True
                or instruction.get('hold_boundary') != phase['hold_boundary']
                or instruction.get('revised_hold_instruction') != phase['revised_hold_instruction']
                or instruction_ref == phase['revised_hold_instruction']
                or instruction.get('revises_existing_hold') is not True
                or instruction.get('formal_remaining_instances') != 174
                or instruction.get('original_bundle_sha256') != phase['original_bundle']['sha256']
                or instruction.get('predecessor_journal_sha256') != phase['predecessor_journal']['sha256']
                or type(instruction.get('message')) is not str or not instruction['message']
                or instruction['message'] != decision.get('parent_instruction_verbatim')
                or _utc_timestamp(instruction['received_at']) <= hold_at):
            raise ValueError('Received parent authority/new timestamp/verbatim revised-condition provenance required')
    return decision


def build_v3(predecessor_phase, predecessor_journal, *, source_commit, source_pins,
             resource_monitor, resource_probe, finite_acceptance, actual_soak_verification,
             post_soak_independent_review, post_v2_boundary, hold_boundary, revised_hold_instruction, recovery_decision):
    """Future-only builder; never supplies a missing cause-condition decision."""
    previous = util.read_json(predecessor_phase)
    if previous.get('kind') != V2_KIND: raise ValueError('Exact v2 predecessor required')
    with pair_execution.exclusive(Path(previous['batch']) / '_control', phase_permit=util.sha256_file(predecessor_phase)):
        from research import wave_dispatch
        current = wave_dispatch.state(predecessor_journal, previous, util.sha256_file(predecessor_phase))
        phase = {**previous, 'schema_version': 3, 'kind': V3_KIND, 'phase_id': 'central-wave-pair14-100-v3',
            'source_commit': source_commit, 'source_pins': source_pins,
            'completed_pairs': list(range(1, 14)), 'assignments': previous['assignments'][2:],
            'shards': {k: v for k, v in previous['shards'].items() if int(k) >= 14},
            'responsibility_counts': [21, 22, 22, 22],
            'two_pair_blocks': [list(range(i, min(i + 2, 101))) for i in range(14, 101, 2)],
            'predecessor_phase': next_phase.reference(predecessor_phase),
            'predecessor_journal': next_phase.reference(predecessor_journal),
            'predecessor_gates': {str(n): {'path': g['receipt_path'], 'sha256': g['receipt_sha256']} for n, g in current['gates'].items()},
            'resource_monitor': resource_monitor, 'resource_probe': resource_probe,
            'finite_acceptance': finite_acceptance, 'actual_soak_verification': actual_soak_verification,
            'post_soak_independent_review': post_soak_independent_review, 'post_v2_boundary': post_v2_boundary,
            'hold_boundary': hold_boundary, 'revised_hold_instruction': revised_hold_instruction,
            'resource_collector_acceptance': recovery_decision}
        validate_v3(phase)
        return phase


def validate_v3(phase, *, repo=None):
    previous, original, _ = predecessor_state(phase)
    if (phase.get('schema_version') != 3 or phase.get('phase_id') != 'central-wave-pair14-100-v3'
            or phase.get('completed_pairs') != list(range(1, 14))
            or phase.get('assignments') != original['assignments'][13:]
            or phase.get('responsibility_counts') != [21, 22, 22, 22]
            or phase.get('two_pair_blocks') != [list(range(i, min(i + 2, 101))) for i in range(14, 101, 2)]
            or not phase.get('source_commit') or not phase.get('source_pins')):
        raise ValueError('Unsupported v3 future-only174-instance amendment')
    mutable = {'schema_version', 'kind', 'phase_id', 'source_commit', 'source_pins', 'completed_pairs',
        'assignments', 'shards', 'responsibility_counts', 'two_pair_blocks', 'predecessor_phase',
        'predecessor_journal', 'predecessor_gates', 'resource_monitor', 'resource_probe', 'resource_collector_acceptance'}
    if any(phase.get(k) != v for k, v in previous.items() if k not in mutable):
        raise ValueError('V3 cannot alter model/input/criteria/budgets/policy or four-Run cap')
    inherited = {k: v for k, v in previous['shards'].items() if int(k) >= 14}
    if phase.get('shards') != inherited: raise ValueError('Original responsibility owners changed')
    for key in ('resource_monitor', 'resource_probe'):
        if not next_phase.verify_reference(phase[key]): raise ValueError('New collector reference changed: ' + key)
    if (phase['resource_monitor']['sha256'] != previous['resource_monitor']['sha256']
            or phase['resource_monitor']['sha256'] != MONITOR_SHA or phase['resource_probe']['sha256'] != V3_PROBE_SHA):
        raise ValueError('V3 admits only exact reviewed5efb probe and unchanged monitor')
    monitor, probe = Path(phase['resource_monitor']['path']).resolve(), Path(phase['resource_probe']['path']).resolve()
    if (probe != monitor.with_name('wave_resource_probe.py')
            or monitor == Path(previous['resource_monitor']['path']).resolve()
            or probe == Path(previous['resource_probe']['path']).resolve()):
        raise ValueError('Prospective helper paths cannot replace predecessor originals')
    _validate_v3_acceptance(phase, previous)
    if repo is not None:
        root = Path(repo).resolve()
        if (root / phase['cohort']).resolve() != Path(phase['batch']).resolve(): raise ValueError('Wrong canonical cohort')
        for name, digest in phase['source_pins'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or util.sha256_file(path) != digest: raise ValueError('New v3 source pin changed: ' + name)
    return original


def build_v4(predecessor_phase, predecessor_journal, *, source_commit, source_pins,
             resource_monitor, resource_probe, resource_collector_acceptance):
    """Offline, future-only successor for the observed pre-write busy acquisition."""
    previous = util.read_json(predecessor_phase)
    if previous.get('kind') != V3_KIND: raise ValueError('Exact v3 predecessor required')
    with pair_execution.exclusive(Path(previous['batch']) / '_control', phase_permit=util.sha256_file(predecessor_phase)):
        from research import wave_dispatch
        current = wave_dispatch.state(predecessor_journal, previous, util.sha256_file(predecessor_phase))
        inherited = {k: v for k, v in previous['shards'].items() if int(k) >= 18}
        phase = {**previous, 'schema_version': 4, 'kind': V4_KIND, 'phase_id': 'central-wave-pair18-100-v4',
            'source_commit': source_commit, 'source_pins': source_pins,
            'completed_pairs': list(range(1, 18)), 'assignments': previous['assignments'][4:],
            'shards': inherited, 'responsibility_counts': [sum(v == n for v in inherited.values()) for n in range(1, 5)],
            'two_pair_blocks': [list(range(i, min(i + 2, 101))) for i in range(18, 101, 2)],
            'predecessor_phase': next_phase.reference(predecessor_phase),
            'predecessor_journal': next_phase.reference(predecessor_journal),
            'predecessor_gates': {str(n): {'path': g['receipt_path'], 'sha256': g['receipt_sha256']} for n, g in current['gates'].items()},
            'resource_monitor': resource_monitor, 'resource_probe': resource_probe,
            'resource_collector_acceptance': resource_collector_acceptance}
        validate_v4(phase)
        return phase


def _validate_v4_acceptance(phase, previous, current):
    acceptance = _checked_json(phase, 'resource_collector_acceptance')
    required = {'kind': 'resource_probe_prewrite_pipe_busy_v4_acceptance',
        'previous_probe_sha256': previous['resource_probe']['sha256'],
        'resource_probe_sha256': phase['resource_probe']['sha256'],
        'resource_monitor_sha256': phase['resource_monitor']['sha256'],
        'operational_policy_sha256': phase['operational_policy']['sha256'],
        'source_commit': phase['source_commit'], 'original_bundle_sha256': phase['original_bundle']['sha256'],
        'predecessor_journal_sha256': phase['predecessor_journal']['sha256'],
        'prewrite_only': True, 'postwrite_retry': False, 'whole_probe_deadline_seconds': 10,
        'fail_closed_unchanged': True, 'historical_cause_resolved': False,
        'remaining_original_instances': 166, 'maximum_runs': 4, 'model_called': False, 'run_created': False}
    if any(acceptance.get(k) != v for k, v in required.items()):
        raise ValueError('V4 acceptance must bind exact prewrite repair, frozen policy and retained historical uncertainty')
    checked, documents = set(), {}
    for key in ('finite_acceptance', 'independent_acceptance', 'observed_resource_fault',
                'stop_acknowledgements', 'post_v3_boundary', 'standing_completion_authority',
                'parent_revised_recovery_authority'):
        reference = acceptance.get(key)
        _verify_bound_leaf(reference, checked)
        documents[key] = util.read_json(reference['path'])
    finite, review = documents['finite_acceptance'], documents['independent_acceptance']
    if (finite.get('schema') != 'prospective-pipe-busy-acquire-finite-v1'
            or finite.get('old_probe', {}).get('sha256') != previous['resource_probe']['sha256']
            or finite.get('candidate', {}).get('sha256') != phase['resource_probe']['sha256']
            or finite.get('unchanged_monitor', {}).get('sha256') != phase['resource_monitor']['sha256']
            or finite.get('observed_failure') != acceptance['observed_resource_fault']
            or type(finite.get('finite_passed')) is not int or finite['finite_passed'] != 13
            or type(finite.get('old_cpu_identity_cases_passed')) is not int or finite['old_cpu_identity_cases_passed'] != 31
            or finite.get('all_ast_outside_native_constructor_unchanged') is not True
            or finite.get('deadline_checks') != {'10_seconds': True, 'shorter_outer_deadline_preserved': True, 'above_10_rejected': True}
            or review.get('kind') != 'prospective_pipe_busy_v4_independent_acceptance'
            or review.get('status') != 'passed' or review.get('finite_acceptance') != acceptance['finite_acceptance']
            or review.get('resource_probe_sha256') != phase['resource_probe']['sha256']
            or review.get('historical_cause_resolved') is not False or review.get('operationally_acceptable') is not True):
        raise ValueError('Exact finite and independent prewrite repair acceptance required')
    for reference in finite.values():
        if isinstance(reference, dict) and {'path', 'sha256'} <= reference.keys():
            _verify_bound_leaf(reference, checked)
    inputs = review.get('input_references')
    if not isinstance(inputs, list) or not inputs:
        raise ValueError('Independent v4 review must retain its listed immutable input references')
    for reference in inputs: _verify_bound_leaf(reference, checked)
    sample = documents['observed_resource_fault'].get('sample', {})
    diagnostic = sample.get('transport_diagnostic', {})
    if (sample.get('ok') is not False or sample.get('timeout_seconds') != 10
            or any(diagnostic.get(k) != v for k, v in {'substage': 'pipe_open', 'errno': 22,
                'winerror': 231, 'bytes_written': 0, 'body_bytes_returned': 0}.items())):
        raise ValueError('Observed original failure must be exact zero-write pipe-open231')
    boundary = documents['post_v3_boundary']
    if (boundary.get('kind') != 'quiescent_post_v3_pipe_busy_boundary'
            or boundary.get('phase') != phase['predecessor_phase'] or boundary.get('journal') != phase['predecessor_journal']
            or boundary.get('gates') != phase['predecessor_gates'] or boundary.get('actual_sent') != 34
            or boundary.get('all_stopped_fixed') is not True
            or boundary.get('all17_gates_complete') is not True
            or boundary.get('active_run_containers_at_final_recovery_sample') != 0
            or boundary.get('recovery_controller_exit_code') != 0):
        raise ValueError('All34 stopped/fixed and17 gates with quiescent predecessor required')
    _utc_timestamp(boundary['at'])
    fence = documents['stop_acknowledgements']; receipt = fence.get('receipt', {})
    expected = {r: b['run_instance_id'] for r, b in current['dispatch'].items() if b['pair'] in (16, 17)}
    if (fence.get('phase_sha256') != phase['predecessor_phase']['sha256'] or fence.get('evidence_errors') != []
            or receipt.get('http_fence_confirmed') is not True or not receipt.get('effective_stop_at')
            or len(fence.get('owned', [])) != 4
            or {b['run_id']: b['run_instance_id'] for b in fence.get('owned', [])} != expected):
        raise ValueError('Exact owned fault-wave stop ACK proof required')
    for key, confirmed in (('gateway_receipts', 'confirmed'), ('worker_stops', 'stop_confirmed')):
        rows = receipt.get(key, [])
        if (len(rows) != 4 or {b['run_id']: b['run_instance_id'] for b in rows} != expected
                or any(b.get(confirmed) is not True for b in rows)):
            raise ValueError('All four owned gateway ACKs and worker stops required')
        if key == 'gateway_receipts' and any(b.get('acknowledgement', {}).get('run_id') != b['run_id']
                or b['acknowledgement'].get('session_id') != b['run_instance_id']
                or b['acknowledgement'].get('admission_closed') is not True for b in rows):
            raise ValueError('Gateway acknowledgement identities must match the exact owned instances')
    # Root retains the received limited repair instruction, not a new human reply.
    authority = documents['parent_revised_recovery_authority']
    if (authority.get('kind') != 'parent_explicit_pipe_busy_recovery_condition_instruction_v4'
            or authority.get('authority') != 'parent' or not isinstance(authority.get('message'), str)
            or not authority['message'] or authority.get('message') != acceptance.get('parent_instruction_verbatim')
            or authority.get('formal_remaining_instances') != 166 or authority.get('maximum_concurrent_runs') != 4
            or authority.get('original_bundle_sha256') != phase['original_bundle']['sha256']
            or authority.get('predecessor_phase') != phase['predecessor_phase']
            or authority.get('observed_resource_fault') != acceptance['observed_resource_fault']
            or authority.get('received_after_observed_fault') is not True
            or authority.get('model_request_retry_authorized') is not False
            or authority.get('hold_until_known_prewrite_acquisition_handling_verified') is not True
            or authority.get('not_a_new_human_reply') is not True):
        raise ValueError('Exact received limited pipe-only recovery instruction required')
    standing = documents['standing_completion_authority']
    if (standing.get('kind') != 'standing_delegated_completion_with_parent_revised_recovery_condition'
            or standing.get('approved_by') != 'user' or standing.get('not_a_new_human_reply') is not True
            or standing.get('parent_revised_instruction') != util.read_json(previous['resource_collector_acceptance']['path']).get('parent_instruction')
            or standing.get('recovery_decision') != previous['resource_collector_acceptance']):
        raise ValueError('Remaining166 must be a subset of the standing original174 completion authority')
    _verify_bound_leaf({'path': standing['original_instruction_path'],
                        'sha256': standing['original_instruction_sha256']}, checked)


def validate_v4(phase, *, repo=None):
    previous, original, current = predecessor_state(phase)
    if (phase.get('schema_version') != 4 or phase.get('phase_id') != 'central-wave-pair18-100-v4'
            or phase.get('completed_pairs') != list(range(1, 18)) or phase.get('assignments') != original['assignments'][17:]
            or phase.get('two_pair_blocks') != [list(range(i, min(i + 2, 101))) for i in range(18, 101, 2)]
            or not phase.get('source_commit') or not phase.get('source_pins')):
        raise ValueError('Unsupported v4 future-only166-instance amendment')
    mutable = {'schema_version', 'kind', 'phase_id', 'source_commit', 'source_pins', 'completed_pairs',
        'assignments', 'shards', 'responsibility_counts', 'two_pair_blocks', 'predecessor_phase',
        'predecessor_journal', 'predecessor_gates', 'resource_monitor', 'resource_probe', 'resource_collector_acceptance'}
    if any(phase.get(k) != v for k, v in previous.items() if k not in mutable):
        raise ValueError('V4 cannot alter model/input/criteria/budgets/policy or four-Run cap')
    inherited = {k: v for k, v in previous['shards'].items() if int(k) >= 18}
    if (phase.get('shards') != inherited or phase.get('responsibility_counts') !=
            [sum(v == n for v in inherited.values()) for n in range(1, 5)]):
        raise ValueError('V4 must inherit original responsibility mapping')
    for key in ('resource_monitor', 'resource_probe'):
        if not next_phase.verify_reference(phase[key]): raise ValueError('New collector reference changed: ' + key)
    if (phase['resource_monitor']['sha256'] != previous['resource_monitor']['sha256']
            or phase['resource_monitor']['sha256'] != MONITOR_SHA or phase['resource_probe']['sha256'] != V4_PROBE_SHA):
        raise ValueError('V4 admits only exact reviewed prewrite231 repair and unchanged monitor')
    monitor, probe = Path(phase['resource_monitor']['path']).resolve(), Path(phase['resource_probe']['path']).resolve()
    if (probe != monitor.with_name('wave_resource_probe.py') or monitor == Path(previous['resource_monitor']['path']).resolve()
            or probe == Path(previous['resource_probe']['path']).resolve()):
        raise ValueError('Prospective helper paths cannot replace predecessor originals')
    _validate_v4_acceptance(phase, previous, current)
    if repo is not None:
        root = Path(repo).resolve()
        if (root / phase['cohort']).resolve() != Path(phase['batch']).resolve(): raise ValueError('Wrong canonical cohort')
        for name, digest in phase['source_pins'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or util.sha256_file(path) != digest: raise ValueError('New v4 source pin changed: ' + name)
    return original


def ancestor_references(phase):
    result = []
    while phase.get('predecessor_phase'):
        reference = phase['predecessor_phase']
        result.append(reference)
        phase = util.read_json(reference['path'])
    return list(reversed(result))

def healthy(snapshot, thresholds):
    """Allowlist only operational inputs. Quality/arm/token outcomes cannot enter."""
    required = set(HEALTH_FLAGS) | set(RESOURCE_LIMITS) | {'sampled_at', 'evidence_files', 'escalation_healthy'}
    if set(snapshot) != required or any(snapshot[k] is not True for k in HEALTH_FLAGS):
        return False
    if type(snapshot['escalation_healthy']) is not bool: return False
    refs = snapshot['evidence_files']
    if (not snapshot['sampled_at'] or not refs
            or any(util.sha256_file(p) != h for p, h in refs.items())):
        return False
    for name in RESOURCE_LIMITS:
        value = snapshot[name]
        if type(value) not in (int, float): return False
        if name.endswith('_min_bytes') and value < thresholds[name]: return False
        if name.endswith('_max') and value > thresholds[name]: return False
    return True
