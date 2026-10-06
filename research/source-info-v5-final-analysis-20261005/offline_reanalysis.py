"""Offline full-cohort calculations. No provider/evaluator/network access.

Preparatory source; a final public dataset may be analyzed only after all original
100 preservation/publication gates and 200 stopped/fixed slots are verified.
Raw verdicts are not classified here. full_pass and critical_failure must come
from an explicit evidence-linked derivation, preserving the original evaluation.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics as st

ARMS = ('explore', 'preload')
METRICS = ('input_tokens', 'output_tokens', 'total_tokens')


def avg(xs):
    return st.mean(xs) if xs else None


def weighted(values, weights):
    return sum(v * w for v, w in zip(values, weights)) if all(v is not None for v in values) else None


def valid_binary(value):
    return value is None or type(value) is int and value in (0, 1)


def validate(dataset):
    plan, rows = dataset['plan'], dataset['runs']
    tasks, weights = plan['task_ids'], plan['variant_weights']
    if len(tasks) != 4 or len(set(tasks)) != 4 or weights != [0.25] * 4:
        raise ValueError('Exactly four equally weighted fixed variants are required')
    hierarchy = plan['task_hierarchy']
    if set(hierarchy) != set(tasks) or sorted(Counter(hierarchy[t]['family'] for t in tasks).values()) != [2, 2]:
        raise ValueError('Fixed task hierarchy must contain exactly two families with two variants each')
    if len(rows) != 200 or len({r['run_id'] for r in rows}) != 200 or len({r['run_instance_id'] for r in rows}) != 200:
        raise ValueError('Exactly 200 distinct original Run identities are required')
    expected = {r['run_id']: r for r in dataset['original_assignments']}
    if len(expected) != 200 or len(dataset['original_assignments']) != 200 or set(expected) != {r['run_id'] for r in rows}:
        raise ValueError('Exact original assignment registry is required')
    pairs = defaultdict(list)
    for r in rows:
        if any(r[k] != expected[r['run_id']][k] for k in ('run_instance_id', 'pair', 'task', 'arm', 'slot', 'position')):
            raise ValueError('Run does not match its original fixed assignment')
        if r['source_family'] != hierarchy[r['task']]['family']:
            raise ValueError('Run family differs from the frozen task hierarchy')
        start, end = [datetime.fromisoformat(r[k].replace('Z', '+00:00')) for k in ('started_at', 'ended_at')]
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError('Implementation intervals require timezone-aware timestamps and end at or after start')
        if r['start_date_utc'] != start.astimezone(timezone.utc).date().isoformat():
            raise ValueError('UTC start-date stratum must agree with the original timestamp')
        if r['task'] not in tasks or r['arm'] not in ARMS or not valid_binary(r['full_pass']) or not valid_binary(r['critical_failure']):
            raise ValueError('Invalid task, arm or derived binary value')
        if r['full_pass'] == 1 and r['critical_failure'] != 0:
            raise ValueError('Complete pass cannot coexist with critical failure or unknown critical coverage')
        if r['critical_failure'] == 1 and r['full_pass'] != 0:
            raise ValueError('Confirmed critical failure must refute full pass')
        if any(r[k] is not True for k in ('actual_send_observed', 'stop_confirmed', 'submission_fixed', 'pair_gate_verified')):
            raise ValueError('Analysis is restricted to all completed acquisition slots and gates')
        if not r.get('quality_derivation_rule') or not r.get('quality_evidence_references'):
            raise ValueError('Derived quality must retain its rule and evidence references, including uncertainty reasons')
        usage = r['usage']
        if type(usage['complete']) is not bool:
            raise ValueError('Usage complete flag must be explicit')
        for k in METRICS:
            v = usage.get(k)
            if usage['complete']:
                if type(v) is not int or v < 0:
                    raise ValueError('Complete usage requires nonnegative integer totals')
            elif v is not None:
                raise ValueError('Incomplete whole-Run totals must stay null; use observed_partial fields')
        if usage['complete'] and usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']:
            raise ValueError('Input plus output must be counted exactly once')
        for k in METRICS:
            lb = usage.get('verified_lower_bounds', {}).get(k)
            if lb is not None and (not usage.get('lower_bound_receipt') or type(lb) is not int or lb < 0):
                raise ValueError('Formal lower bound requires an explicit semantic/reconciliation receipt')
            if lb is not None and usage['complete'] and lb > usage[k]:
                raise ValueError('Verified lower bound exceeds the complete whole-Run total')
        pairs[r['pair']].append(r)
    if set(pairs) != set(range(1, 101)):
        raise ValueError('All original pair numbers 1..100 are required')
    for pair, members in pairs.items():
        if len(members) != 2 or {r['arm'] for r in members} != set(ARMS) or len({r['task'] for r in members}) != 1:
            raise ValueError('Each pair must contain its exact two original arms of one task')
        if any(r['analysis_session'] != (pair - 1) // 4 + 1 for r in members):
            raise ValueError('Original consecutive-four-pair sessions must be retained')
    if any(sum(r['task'] == t and r['arm'] == a for r in rows) != 25 for t in tasks for a in ARMS):
        raise ValueError('Every task/arm must retain 25 original assignments')
    return pairs


def binary_arm(rows, key):
    values = [r[key] for r in rows]
    n = len(values)
    if not n:
        return {'assigned': 0, 'zero': 0, 'one': 0, 'unknown': 0, 'identification_bounds': None, 'all_assigned_mean': None}
    return {'assigned': n, 'zero': values.count(0), 'one': values.count(1), 'unknown': values.count(None),
            'identification_bounds': [values.count(1) / n, (values.count(1) + values.count(None)) / n],
            'all_assigned_mean': avg(values) if None not in values else None}


def paired_binary(pairs, key):
    bounds, diffs = [], []
    table = Counter()
    for e, p in pairs:
        x, y = e[key], p[key]
        table[f'explore={x},preload={y}'] += 1
        bounds.append(((y if y is not None else 0) - (x if x is not None else 1),
                       (y if y is not None else 1) - (x if x is not None else 0)))
        if x is not None and y is not None:
            diffs.append(y - x)
    return {'assigned_pairs': len(pairs), 'known_pairs': len(diffs),
            'identification_bounds': [avg([b[k] for b in bounds]) for k in (0, 1)] if bounds else None,
            'all_assigned_difference': avg(diffs) if len(diffs) == len(pairs) and pairs else None,
            'known_pair_difference_secondary': avg(diffs), 'paired_status_table': dict(sorted(table.items()))}


def location(xs):
    if not xs:
        return {'n': 0, 'mean': None, 'median': None, 'min': None, 'max': None, 'sample_sd': None, 'q25': None, 'q75': None}
    ordered = sorted(xs)
    def quantile(p):
        i = (len(ordered) - 1) * p
        lo, hi = math.floor(i), math.ceil(i)
        return ordered[lo] * (hi - i) + ordered[hi] * (i - lo) if lo != hi else ordered[lo]
    return {'n': len(xs), 'mean': avg(xs), 'median': st.median(xs), 'min': min(xs), 'max': max(xs),
            'sample_sd': st.stdev(xs) if len(xs) > 1 else None, 'q25': quantile(.25), 'q75': quantile(.75)}


def iid_hoeffding(center, weights, sizes):
    if center is None or any(n == 0 for n in sizes):
        return None
    radius = math.sqrt(2 * math.log(40) * sum(w * w / n for w, n in zip(weights, sizes)))
    return {'confidence_level': .95, 'interval': [max(-1, center - radius), min(1, center + radius)],
            'assumption': 'Independent paired observations within/across fixed variants; bounded paired binary differences in [-1,1]. Actual session/day/provider dependence can invalidate this nominal coverage.',
            'not_missing_data_identification_bound': True}


def normal_icc_sensitivity(series, weights, binary=False):
    if any(len(xs) < 2 for xs in series):
        return {'available': False, 'reason': 'At least two paired differences per retained variant are needed'}
    center = weighted([avg(xs) for xs in series], weights)
    variance = sum(w * w * st.variance(xs) / len(xs) for w, xs in zip(weights, series))
    rows = []
    for rho in (0, .1, .3):
        radius = 1.96 * math.sqrt(variance * (1 + 3 * rho))
        interval = [center - radius, center + radius]
        if binary:
            interval = [max(-1, interval[0]), min(1, interval[1])]
        rows.append({'icc_assumption': rho, 'assumed_session_size': 4, 'estimate': center, 'normal_ci95': interval})
    return {'available': True, 'scenarios': rows,
            'assumption': 'Prespecified 1+3*rho design-effect sensitivity for consecutive-four-pair sessions, not measured ICC or an actual cluster covariance estimator. Normal approximation and selection/dependence limitations remain.',
            'uses_actual_session_memberships_for_covariance': False}


def ordered_pairs(rows):
    groups = defaultdict(dict)
    for r in rows:
        groups[r['pair']][r['arm']] = r
    return [(g['explore'], g['preload']) for _, g in sorted(groups.items()) if set(g) == set(ARMS)]


def token_diffs(pairs, metric, selector='complete'):
    return [p['usage'][metric] - e['usage'][metric] for e, p in pairs
            if e['usage']['complete'] and p['usage']['complete']
            and (selector != 'full_pass' or e['full_pass'] == p['full_pass'] == 1)]


def arm_summary(rows):
    out = {'assigned': len(rows), 'full_pass': binary_arm(rows, 'full_pass'),
           'critical_failure': binary_arm(rows, 'critical_failure'),
           'execution': dict(sorted(Counter(r['execution_state'] for r in rows).items())),
           'raw_scoring': dict(sorted(Counter(r['scoring_state'] for r in rows).items())),
           'raw_verdict': dict(sorted(Counter(str(r['raw_verdict']) for r in rows).items())),
           'research_coverage': dict(sorted(Counter(str(r['research_status']) for r in rows).items())),
           'usage_complete': sum(r['usage']['complete'] for r in rows),
           'usage_missing': sum(not r['usage']['complete'] for r in rows),
           'quality_usage_execution_joint': dict(sorted(Counter(f"full_pass={r['full_pass']};usage_complete={r['usage']['complete']};execution={r['execution_state']}" for r in rows).items()))}
    out['tokens'] = {}
    for metric in METRICS:
        known = [r['usage'][metric] for r in rows if r['usage']['complete']]
        partial = [r['usage'].get('observed_partial', {}).get(metric) for r in rows if not r['usage']['complete']]
        out['tokens'][metric] = {'complete_run_distribution_secondary': location(known),
            'all_assigned_mean': avg(known) if len(known) == len(rows) and rows else None,
            'sum_complete_runs': sum(known),
            'observed_partial_count': sum(v is not None for v in partial),
            'sum_reported_observed_partial': sum(v for v in partial if v is not None),
            'partial_sum_is_whole_run_total_or_verified_lower_bound': False}
    return out


def compare_subset(rows):
    pairs = ordered_pairs(rows)
    return {'assigned_runs': len(rows), 'paired_runs_available': len(pairs) * 2,
            'arms': {a: arm_summary([r for r in rows if r['arm'] == a]) for a in ARMS},
            'full_pass': paired_binary(pairs, 'full_pass'), 'critical_failure': paired_binary(pairs, 'critical_failure'),
            'complete_pair_token_secondary': {m: location(token_diffs(pairs, m)) for m in METRICS},
            'both_full_pass_pair_token_secondary': {m: location(token_diffs(pairs, m, 'full_pass')) for m in METRICS},
            'quality_usage_paired_joint': dict(sorted(Counter(f"explore={e['full_pass']}/{e['usage']['complete']},preload={p['full_pass']}/{p['usage']['complete']}" for e, p in pairs).items())),
            'interpretation': 'Subset comparisons are descriptive. Complete/success-only estimates condition on post-assignment selection and change the population; no phase/concurrency causal effect is identified.'}


def missing_scenarios(rows, tasks, weights):
    outputs = []
    for metric in METRICS:
        for em, pm in product((.5, 1., 2.), repeat=2):
            strata, diffs, inconsistent = [], [], []
            for task in tasks:
                means, arms = [], {}
                for a, mult in zip(ARMS, (em, pm)):
                    subset = [r for r in rows if r['task'] == task and r['arm'] == a]
                    known = [r['usage'][metric] for r in subset if r['usage']['complete']]
                    missing = [r for r in subset if not r['usage']['complete']]
                    reference = avg(known)
                    imputed = reference * mult if reference is not None else None
                    conflict = [r['run_id'] for r in missing if imputed is not None
                                and r['usage'].get('verified_lower_bounds', {}).get(metric) is not None
                                and imputed < r['usage']['verified_lower_bounds'][metric]]
                    inconsistent.extend(conflict)
                    mean = (sum(known) + len(missing) * imputed) / len(subset) if imputed is not None else None
                    means.append(mean)
                    arms[a] = {'assigned': len(subset), 'observed_complete': len(known), 'missing': len(missing),
                               'reference_complete_mean': reference, 'imputed_missing_total': imputed,
                               'scenario_all_assigned_mean': mean, 'below_verified_lower_bound_runs': conflict}
                difference = means[1] - means[0] if all(v is not None for v in means) else None
                diffs.append(difference)
                strata.append({'task': task, 'arms': arms, 'difference': difference})
            outputs.append({'metric': metric, 'missing_explore_multiplier': em, 'missing_preload_multiplier': pm,
                            'equal_variant_difference': weighted(diffs, weights), 'variant_results': strata,
                            'inconsistent_with_verified_lower_bound_runs': inconsistent,
                            'identified_from_data': False, 'lower_bound_clamping_applied': False,
                            'interpretation': 'Prespecified crossed assumptions, not recovered missing truth, a confidence interval, or a finite identification bound.'})
    return outputs


def overlap_chronology(rows):
    def time(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    intervals = {r['run_id']: (time(r['started_at']), time(r['ended_at'])) for r in rows}
    events = sorted({t for interval in intervals.values() for t in interval})
    counts = []
    for start, end in zip(events, events[1:]):
        active = [r for r in rows if intervals[r['run_id']][0] <= start < intervals[r['run_id']][1]]
        if active:
            counts.append({'start': start.isoformat(), 'end': end.isoformat(), 'active_implementations': len(active),
                           'active_pairs': len({r['pair'] for r in active}), 'run_ids': [r['run_id'] for r in active]})
    by_run = {}
    for r in rows:
        segments = [s for s in counts if r['run_id'] in s['run_ids']]
        by_run[r['run_id']] = {'max_simultaneous_implementation_intervals': max((s['active_implementations'] for s in segments), default=0),
                              'overlapping_other_pair_observed': any(s['active_pairs'] > 1 for s in segments)}
    return {'basis': 'Manifest implementation start/end intervals, not proof of instantaneous simultaneous model requests or container CPU activity.',
            'segments': counts, 'by_run': by_run}


def fixed_family_summary(rows, tasks, variants, family):
    members = [t for t in tasks if any(r['task'] == t and r['source_family'] == family for r in rows)]
    weights = [1 / len(members)] * len(members)
    out = {'family': family, 'variants': members, 'weights_within_fixed_family': dict(zip(members, weights)),
           'assigned_pairs': sum(variants[t]['full_pass']['assigned_pairs'] for t in members),
           'fixed_family_population_inference': False,
           'arms': {a: arm_summary([r for r in rows if r['source_family'] == family and r['arm'] == a]) for a in ARMS}}
    for key in ('full_pass', 'critical_failure'):
        items = [variants[t][key] for t in members]
        center = weighted([v['all_assigned_difference'] for v in items], weights)
        series = [[p[key] - e[key] for e, p in ordered_pairs([r for r in rows if r['task'] == t])
                   if e[key] is not None and p[key] is not None] for t in members]
        out[key] = {'identification_bounds': [weighted([v['identification_bounds'][k] for v in items], weights) for k in (0, 1)],
                    'all_assigned_difference': center,
                    'iid_hoeffding_ci95': iid_hoeffding(center, weights, [25] * len(members)),
                    'prespecified_session_icc_sensitivity': normal_icc_sensitivity(series, weights, binary=True) if center is not None else None}
    out['tokens'] = {}
    for metric in METRICS:
        full_means = []
        for t in members:
            e, p = [variants[t]['arms'][a]['tokens'][metric]['all_assigned_mean'] for a in ARMS]
            full_means.append(p - e if e is not None and p is not None else None)
        series = [token_diffs(ordered_pairs([r for r in rows if r['task'] == t]), metric) for t in members]
        successful = [token_diffs(ordered_pairs([r for r in rows if r['task'] == t]), metric, 'full_pass') for t in members]
        center = weighted(full_means, weights)
        out['tokens'][metric] = {'all_assigned_difference': center, 'identified': center is not None,
            'all_assigned_prespecified_normal_icc_sensitivity': normal_icc_sensitivity(series, weights) if center is not None else None,
            'equal_variant_complete_pair_difference_secondary': weighted([avg(s) for s in series], weights),
            'complete_pair_counts_by_variant': dict(zip(members, [len(s) for s in series])),
            'complete_pair_prespecified_normal_icc_sensitivity_secondary': normal_icc_sensitivity(series, weights),
            'equal_variant_both_full_pass_pair_difference_secondary': weighted([avg(s) for s in successful], weights),
            'both_full_pass_pair_counts_by_variant': dict(zip(members, [len(s) for s in successful]))}
    return out


def analyze(dataset):
    pairs = validate(dataset)
    rows = dataset['runs']
    tasks, weights = dataset['plan']['task_ids'], dataset['plan']['variant_weights']
    variants = {t: compare_subset([r for r in rows if r['task'] == t]) for t in tasks}
    overall = {'all_assigned_count': len(rows), 'assigned_pairs': len(pairs), 'contrast': 'preload minus explore',
               'variant_weights': dict(zip(tasks, weights)), 'arms': {a: arm_summary([r for r in rows if r['arm'] == a]) for a in ARMS}}
    for key in ('full_pass', 'critical_failure'):
        items = [variants[t][key] for t in tasks]
        bounds = [weighted([v['identification_bounds'][k] for v in items], weights) for k in (0, 1)]
        center = weighted([v['all_assigned_difference'] for v in items], weights)
        series = [[p[key] - e[key] for e, p in ordered_pairs([r for r in rows if r['task'] == t])
                   if e[key] is not None and p[key] is not None] for t in tasks]
        overall[key] = {'identification_bounds': bounds, 'all_assigned_difference': center,
                        'iid_hoeffding_ci95': iid_hoeffding(center, weights, [25] * 4),
                        'prespecified_session_icc_sensitivity': normal_icc_sensitivity(series, weights, binary=True) if center is not None else None}
        for i, task in enumerate(tasks):
            variants[task][key]['iid_hoeffding_ci95'] = iid_hoeffding(items[i]['all_assigned_difference'], [1.], [25])
            variants[task][key]['prespecified_session_icc_sensitivity'] = normal_icc_sensitivity([series[i]], [1.], binary=True) if items[i]['all_assigned_difference'] is not None else None
    overall['tokens'] = {}
    for metric in METRICS:
        means = []
        for t in tasks:
            arm_items = variants[t]['arms']
            e, p = [arm_items[a]['tokens'][metric]['all_assigned_mean'] for a in ARMS]
            means.append(p - e if e is not None and p is not None else None)
        series = [token_diffs(ordered_pairs([r for r in rows if r['task'] == t]), metric) for t in tasks]
        successful = [token_diffs(ordered_pairs([r for r in rows if r['task'] == t]), metric, 'full_pass') for t in tasks]
        center = weighted(means, weights)
        overall['tokens'][metric] = {'all_assigned_difference': center, 'identified': center is not None,
            'unavailable_reason': 'Missing complete whole-Run totals with no externally justified finite upper bound' if center is None else None,
            'all_assigned_prespecified_normal_icc_sensitivity': normal_icc_sensitivity(series, weights) if center is not None else None,
            'equal_variant_complete_pair_difference_secondary': weighted([avg(s) for s in series], weights),
            'complete_pair_counts_by_variant': dict(zip(tasks, [len(s) for s in series])),
            'complete_pair_prespecified_normal_icc_sensitivity_secondary': normal_icc_sensitivity(series, weights),
            'equal_variant_both_full_pass_pair_difference_secondary': weighted([avg(s) for s in successful], weights),
            'both_full_pass_pair_counts_by_variant': dict(zip(tasks, [len(s) for s in successful]))}
    groups = {}
    for axis in ('acquisition_phase', 'run_concurrency_cap', 'analysis_session', 'assigned_order_quartile', 'start_date_utc'):
        values = sorted({str(r[axis]) for r in rows})
        groups[axis] = {value: compare_subset([r for r in rows if str(r[axis]) == value]) for value in values}
    families = {f: fixed_family_summary(rows, tasks, variants, f) for f in sorted({r['source_family'] for r in rows})}
    return {'kind': 'offline_all200_analysis', 'primary': overall, 'variants': variants, 'fixed_family_results': families,
            'prespecified_missing_token_scenarios': missing_scenarios(rows, tasks, weights),
            'added_descriptive_strata': groups, 'added_actual_overlap_chronology': overlap_chronology(rows),
            'all_assigned_quality_usage_paired_table': compare_subset(rows)['quality_usage_paired_joint'],
            'no_joint_success_flag': True, 'quality_maintenance_or_universal_claim': False,
            'limitations': ['Identification bounds, hypothetical missingness scenarios and confidence intervals express different uncertainties.',
                            'Two fixed families and nested variants do not represent an independent application population.',
                            'Repeated paired observations share provider/date/session/wave conditions; nominal independent-pair intervals may understate uncertainty.',
                            'Mixed acquisition phases and overlapping-pair regimes limit original-regime and causal phase/concurrency claims.',
                            'Success-only/complete-case token contrasts are conditional on post-assignment selection; early failure is not efficiency improvement.',
                            'Saved evaluated contract coverage does not establish universal product quality or a mechanism.',
                            'Public exclusion ledger limits full evaluator replay even when statistical results are reproducible.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    raw = a.data.read_bytes()
    dataset = json.loads(raw)
    if dataset.get('kind') != 'public_verified_all200_reanalysis_dataset_v1':
        raise ValueError('A verified final full-cohort public dataset is required')
    results = analyze(dataset)
    results['input_sha256'] = hashlib.sha256(raw).hexdigest()
    results['analysis_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    a.out.mkdir(parents=True, exist_ok=False)
    for name, value in [('analysis-results.json', results), ('primary.json', results['primary']),
                        ('variant-results.json', results['variants']), ('fixed-family-results.json', results['fixed_family_results']), ('missing-token-scenarios.json', results['prespecified_missing_token_scenarios']),
                        ('descriptive-strata.json', results['added_descriptive_strata']), ('actual-overlap-chronology.json', results['added_actual_overlap_chronology'])]:
        with (a.out / name).open('x', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
    print(json.dumps({'assigned_pairs': results['primary']['assigned_pairs'], 'assigned_runs': results['primary']['all_assigned_count'],
                      'output': str(a.out), 'input_sha256': results['input_sha256'], 'model_called': False, 'evaluator_called': False}))


if __name__ == '__main__':
    main()
