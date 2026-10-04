"""Separate execution amendment; never changes the frozen v5 scientific plan.

Preparation is offline. The caller freezes this manifest, new source pins,
resource thresholds and a separate exact-phase user approval before dispatch.
"""
from collections import Counter
from pathlib import Path

from outer.harness import util
from research import next_phase, pair_execution

KIND = 'source_info_v5_central_fixed_wave_phase_v1'
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
