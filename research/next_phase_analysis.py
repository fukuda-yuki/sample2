"""Assigned-slot accounting for the new, narrowly scoped continuity study."""
import argparse
from collections import Counter
import itertools
import json
import math
from pathlib import Path
import statistics

from outer.harness import util


def quality_value(row):
    if not row:
        return None
    if row.get('confirmed_product_failure') or row.get('verdict') in ('fail', 'fail_critical'):
        return 0
    scoring = row.get('scoring', {})
    if (row.get('verdict') == 'pass' and scoring.get('state') == 'scored'
            and scoring.get('research_status') == 'complete'
            and row.get('operation_status') == 'complete'):
        return 1
    return None


def total_value(row):
    usage = (row or {}).get('usage', {})
    value = usage.get('total_tokens')
    if usage.get('usage_complete') is True and type(value) is int and value >= 0:
        return value
    return None


def summarize(plan, assignments, rows):
    expected = {case['run_id']: case for pair in assignments for case in pair['cases']}
    if len(expected) != plan['allocation']['runs']:
        raise ValueError('Missing or duplicate assigned slot')
    by_id = {}
    for row in rows:
        rid = row.get('run_id')
        if rid not in expected or rid in by_id:
            raise ValueError('Unexpected or duplicate Run result')
        case = expected[rid]
        if row.get('task_id') != case['task'] or row.get('intervention_id') != case['condition']:
            raise ValueError('Task/intervention identity mismatch')
        by_id[rid] = row
    strata = []
    token_sensitivity = []
    full_token_means = []
    secondary_pair_means = []
    for task, weight in zip(plan['task_ids'], plan['variant_weights']):
        pairs = [p for p in assignments if p['task'] == task]
        arm_data = {}
        for arm in plan['arms']:
            cases = [c for p in pairs for c in p['cases'] if c['condition'] == arm]
            qs = [quality_value(by_id.get(c['run_id'])) for c in cases]
            ts = [total_value(by_id.get(c['run_id'])) for c in cases]
            known = [v for v in ts if v is not None]
            arm_data[arm] = {'assigned': len(cases), 'quality_pass': qs.count(1),
                'quality_failure': qs.count(0), 'quality_unknown': qs.count(None),
                'quality_pass_identification_bounds': [qs.count(1) / len(qs),
                    (qs.count(1) + qs.count(None)) / len(qs)],
                'usage_complete': len(known), 'usage_missing': ts.count(None),
                'complete_run_token_mean_secondary': statistics.mean(known) if known else None,
                'all_assigned_token_mean': statistics.mean(known) if len(known) == len(ts) else None,
                'states': dict(Counter((by_id.get(c['run_id']) or {}).get('execution', {}).get('state', 'undispatched') for c in cases))}
        differences, lower, upper, token_diffs = [], [], [], []
        for pair in pairs:
            values = {c['condition']: by_id.get(c['run_id']) for c in pair['cases']}
            e, p = quality_value(values['explore']), quality_value(values['preload'])
            lower.append((p if p is not None else 0) - (e if e is not None else 1))
            upper.append((p if p is not None else 1) - (e if e is not None else 0))
            if p is not None and e is not None:
                differences.append(p - e)
            te, tp = total_value(values['explore']), total_value(values['preload'])
            if te is not None and tp is not None:
                token_diffs.append(tp - te)
        center = statistics.mean(differences) if len(differences) == len(pairs) else None
        radius = math.sqrt(2 * math.log(40) / len(pairs))
        stratum = {'task': task, 'variant_weight': weight, 'assigned_pairs': len(pairs),
            'arms': arm_data, 'quality_difference_identification_bounds': [statistics.mean(lower), statistics.mean(upper)],
            'all_assigned_quality_difference': center,
            'fully_observed_quality_iid_hoeffding_ci95':
                [max(-1, center - radius), min(1, center + radius)] if center is not None else None,
            'complete_pair_token_count_secondary': len(token_diffs),
            'complete_pair_token_difference_secondary': statistics.mean(token_diffs) if token_diffs else None}
        strata.append(stratum)
        e_mean, p_mean = (arm_data[a]['all_assigned_token_mean'] for a in ('explore', 'preload'))
        full_token_means.append(p_mean - e_mean if e_mean is not None and p_mean is not None else None)
        secondary_pair_means.append(statistics.mean(token_diffs) if token_diffs else None)
    for e_multiplier, p_multiplier in itertools.product((0.5, 1.0, 2.0), repeat=2):
        differences = []
        for stratum in strata:
            means = []
            for arm, multiplier in (('explore', e_multiplier), ('preload', p_multiplier)):
                item = stratum['arms'][arm]
                observed = item['complete_run_token_mean_secondary']
                means.append(observed * (item['usage_complete'] + multiplier * item['usage_missing']) / item['assigned'] if observed is not None else None)
            differences.append(means[1] - means[0] if None not in means else None)
        token_sensitivity.append({'assumed_missing_explore_multiplier': e_multiplier,
            'assumed_missing_preload_multiplier': p_multiplier,
            'weighted_token_difference': sum(w * v for w, v in zip(plan['variant_weights'], differences)) if None not in differences else None,
            'is_identification_bound': False})
    aggregate_bounds = [sum(s['variant_weight'] * s['quality_difference_identification_bounds'][i] for s in strata) for i in (0, 1)]
    return {'schema_version': 1, 'plan_id': plan['plan_id'], 'assigned_slots': len(expected),
        'observed_results': len(by_id), 'undispatched_or_no_result': len(expected) - len(by_id),
        'strata': strata, 'all_assigned_quality_difference_identification_bounds': aggregate_bounds,
        'all_assigned_token_difference': sum(w * v for w, v in zip(plan['variant_weights'], full_token_means)) if None not in full_token_means else None,
        'all_assigned_token_contrast_identified': None not in full_token_means,
        'equal_variant_complete_pair_token_difference_secondary': sum(w * v for w, v in zip(plan['variant_weights'], secondary_pair_means)) if None not in secondary_pair_means else None,
        'missing_token_assumption_sensitivity': token_sensitivity,
        'quality_maintenance_claim': False, 'across_application_claim': False,
        'uncertainty_limit': 'Hoeffding intervals require independent paired observations; real day/session/provider dependence is retained and prespecified ICC sensitivity is required. Incomplete-pair identification bounds express missing-data uncertainty, not confidence coverage.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--rows', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    bundle = util.read_json(args.bundle)
    data = util.read_json(args.rows)
    rows = data.get('runs', data) if isinstance(data, dict) else data
    util.write_new_json(args.out, summarize(bundle['plan'], bundle['assignments'], rows))


if __name__ == '__main__':
    main()
