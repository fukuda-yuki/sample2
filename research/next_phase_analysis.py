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


def interval_sensitivity(differences, weights, *, binary=False):
    if any(len(values) < 2 for values in differences):
        return None
    center = sum(w * statistics.mean(values) for w, values in zip(weights, differences))
    variance = sum(w * w * statistics.variance(values) / len(values) for w, values in zip(weights, differences))
    rows = []
    for icc in (0.0, 0.1, 0.3):
        radius = 1.96 * math.sqrt(variance * (1 + 3 * icc))
        bounds = [center - radius, center + radius]
        if binary: bounds = [max(-1, bounds[0]), min(1, bounds[1])]
        rows.append({'session_icc_assumption': icc, 'session_cluster_pairs': 4,
            'estimate': center, 'normal_approximation_ci95': bounds,
            'is_missing_data_identification_bound': False})
    return rows


def summarize(plan, assignments, rows, *, bindings, plan_sha256, cohort, measurement):
    expected = {case['run_id']: case for pair in assignments for case in pair['cases']}
    if len(expected) != plan['allocation']['runs']:
        raise ValueError('Missing or duplicate assigned slot')
    for rid, binding in bindings.items():
        if rid not in expected:
            raise ValueError('Unassigned dispatch cannot enter the denominator')
        if ('run_instance_id' in expected[rid]
                and binding.get('run_instance_id') != expected[rid]['run_instance_id']):
            raise ValueError('Dispatch differs from the preassigned instance')
    by_id = {}
    for row in rows:
        rid = row.get('run_id')
        if rid not in expected or rid in by_id:
            raise ValueError('Unexpected or duplicate Run result')
        case = expected[rid]
        if row.get('task_id') != case['task'] or row.get('intervention_id') != case['condition']:
            raise ValueError('Task/intervention identity mismatch')
        binding = bindings.get(rid, {})
        if (binding.get('plan_sha256') != plan_sha256 or binding.get('cohort') != cohort
                or binding.get('run_instance_id') != row.get('run_instance_id')
                or not binding.get('run_instance_id')
                or not binding.get('condition_sha256') or not binding.get('input_sha256')
                or row.get('synthetic') is not False
                or any(binding.get(k) != case.get(k) for k in ('task', 'condition', 'run_id', 'pair', 'slot'))):
            raise ValueError('Result is not bound to this research dispatch/input instance')
        scoring = row.get('scoring', {})
        expected_version = measurement['evaluation_version']
        if isinstance(expected_version, dict): expected_version = expected_version[case['task']]
        if (scoring.get('state') == 'scored' or quality_value(row) is not None) and (scoring.get('evaluation_version') != expected_version
                or scoring.get('evaluator_sha256') != measurement['evaluator_sha256'][case['task']]):
            raise ValueError('Result uses another measurement chain')
        by_id[rid] = row
    strata = []
    token_sensitivity = []
    full_token_means = []
    secondary_pair_means = []
    quality_differences, complete_token_differences, full_quality = [], [], []
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
                'states': dict(Counter((by_id.get(c['run_id']) or {}).get('execution', {}).get('state',
                    'dispatched_no_terminal_result' if c['run_id'] in bindings else 'undispatched') for c in cases))}
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
        quality_differences.append(differences)
        complete_token_differences.append(token_diffs)
        full_quality.append(center is not None)
        radius = math.sqrt(2 * math.log(40) / len(pairs))
        stratum = {'task': task, 'variant_weight': weight, 'assigned_pairs': len(pairs),
            'arms': arm_data, 'quality_difference_identification_bounds': [statistics.mean(lower), statistics.mean(upper)],
            'all_assigned_quality_difference': center,
            'fully_observed_quality_iid_hoeffding_ci95':
                [max(-1, center - radius), min(1, center + radius)] if center is not None else None,
            'quality_difference_normal_session_sensitivity': interval_sensitivity([differences], [1.0], binary=True) if center is not None else None,
            'complete_pair_token_count_secondary': len(token_diffs),
            'complete_pair_token_difference_secondary': statistics.mean(token_diffs) if token_diffs else None,
            'complete_pair_token_normal_session_sensitivity_secondary': interval_sensitivity([token_diffs], [1.0])}
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
    quality_center = aggregate_bounds[0] if all(full_quality) else None
    quality_radius = math.sqrt(2 * math.log(40) * sum(s['variant_weight'] ** 2 / s['assigned_pairs'] for s in strata))
    tokens_identified = None not in full_token_means
    family_results = []
    hierarchy = plan.get('task_hierarchy', {})
    families = list(dict.fromkeys(hierarchy.get(task, {}).get('family') for task in plan['task_ids']))
    for family in families:
        if family is None: continue
        indexes = [i for i, task in enumerate(plan['task_ids']) if hierarchy[task]['family'] == family]
        weight = sum(plan['variant_weights'][i] for i in indexes)
        weights = [plan['variant_weights'][i] / weight for i in indexes]
        q_known = all(full_quality[i] for i in indexes)
        t_known = all(full_token_means[i] is not None for i in indexes)
        bounds = [sum(w * strata[i]['quality_difference_identification_bounds'][k]
            for w, i in zip(weights, indexes)) for k in (0, 1)]
        family_results.append({'family': family, 'fixed_family_weight': weight,
            'assigned_pairs': sum(strata[i]['assigned_pairs'] for i in indexes),
            'quality_difference_identification_bounds': bounds,
            'all_assigned_quality_difference': bounds[0] if q_known else None,
            'quality_normal_session_sensitivity': interval_sensitivity(
                [quality_differences[i] for i in indexes], weights, binary=True) if q_known else None,
            'all_assigned_token_difference': sum(w * full_token_means[i] for w, i in zip(weights, indexes)) if t_known else None,
            'token_normal_session_sensitivity': interval_sensitivity(
                [complete_token_differences[i] for i in indexes], weights) if t_known else None,
            'between_application_population_inference': False})
    return {'schema_version': 1, 'plan_id': plan['plan_id'], 'assigned_slots': len(expected),
        'plan_sha256': plan_sha256, 'cohort': cohort, 'dispatch_count': len(bindings),
        'dispatch_count_definition': 'Durable manager dispatch intents; not a count of actual gateway transmissions.',
        'execution_regime': plan.get('regime'), 'estimand': plan.get('claim'),
        'observed_results': len(by_id), 'undispatched_or_no_result': len(expected) - len(by_id),
        'strata': strata, 'fixed_family_results': family_results,
        'all_assigned_quality_difference_identification_bounds': aggregate_bounds,
        'all_assigned_quality_difference': quality_center,
        'all_assigned_quality_iid_hoeffding_ci95': [max(-1, quality_center - quality_radius), min(1, quality_center + quality_radius)] if quality_center is not None else None,
        'all_assigned_quality_normal_session_sensitivity': interval_sensitivity(quality_differences, plan['variant_weights'], binary=True) if all(full_quality) else None,
        'all_assigned_token_difference': sum(w * v for w, v in zip(plan['variant_weights'], full_token_means)) if None not in full_token_means else None,
        'all_assigned_token_contrast_identified': tokens_identified,
        'all_assigned_token_normal_session_sensitivity': interval_sensitivity(complete_token_differences, plan['variant_weights']) if tokens_identified else None,
        'all_assigned_token_uncertainty_unavailable_reason': None if tokens_identified else 'Missing complete totals; an all-assigned mean and sampling interval are not identified.',
        'equal_variant_complete_pair_token_difference_secondary': sum(w * v for w, v in zip(plan['variant_weights'], secondary_pair_means)) if None not in secondary_pair_means else None,
        'complete_pair_token_normal_session_sensitivity_secondary': interval_sensitivity(complete_token_differences, plan['variant_weights']),
        'missing_token_assumption_sensitivity': token_sensitivity,
        'quality_maintenance_claim': False, 'across_application_claim': False,
        'uncertainty_limit': 'Hoeffding intervals require independent paired observations; real day/session/provider dependence is retained and prespecified ICC sensitivity is required. Incomplete-pair identification bounds express missing-data uncertainty, not confidence coverage.'}


def terminal_row(root, binding, result, implementation, current):
    """Adopt an immutable terminal row only after verifying original usage bytes."""
    row = result['row']
    if row.get('run_id') != binding['run_id'] or row.get('run_instance_id') != binding['run_instance_id']:
        raise ValueError('Terminal row belongs to another instance')
    if any(current.get(k) != v for k, v in row.items() if k not in ('archive', 'network_cleanup', 'postprocessing')):
        raise ValueError('Current aggregate differs from the immutable terminal row')
    if row.get('postprocessing'):
        timing = row['postprocessing']
        path = Path(timing['receipt']).resolve()
        if (path != (Path(root) / 'postprocess-timing.jsonl').resolve()
                or util.sha256_file(path) != timing['receipt_sha256']
                or util.read_lines(path) != timing['stages']
                or any(e.get('run_id') != binding['run_id'] or e.get('run_instance_id') != binding['run_instance_id']
                    for e in timing['stages'])):
            raise ValueError('Postprocessing clock evidence changed or belongs to another instance')
    raw = Path(root) / 'usage/raw'
    if util.tree_hashes(raw) != implementation['receipt']['raw']:
        raise ValueError('Stopped gateway originals changed after implementation receipt')
    path = Path(root) / 'usage/normalized.json'
    if path.exists():
        normalized = util.read_json(path)
        if (normalized.get('run_id') != binding['run_id'] or
                normalized.get('run_instance_id') != binding['run_instance_id']):
            raise ValueError('Normalized usage belongs to another instance')
        digest = util.sha256_file(path)
        versions = Path(root) / 'usage/derivations'
        matched = False
        for version in versions.glob('*/binding.json'):
            saved = util.read_json(version)
            if (saved.get('run_id') == binding['run_id'] and
                    saved.get('run_instance_id') == binding['run_instance_id'] and
                    saved.get('normalized_sha256') == digest and
                    util.sha256_file(version.parent / 'normalized.json') == digest and
                    saved.get('raw') == normalized.get('raw_bindings')):
                matched = True
                break
        if not matched: raise ValueError('Normalized usage has no matching immutable derivation')
    return row


def collect(bundle, bundle_path, repo):
    """Read normal dispatch/original/derived records; no unbound row import."""
    from outer.harness import aggregate, profiles
    from research import pair_execution
    from research.next_phase import inside, evaluation_version
    batch = inside(repo, bundle['cohort'], 'runs')
    state = pair_execution.state(batch / '_control/pair-journal.jsonl')
    digest = util.sha256_file(bundle_path)
    rows = []
    for rid, binding in state['dispatch'].items():
        if binding['plan_sha256'] != digest or binding['cohort'] != bundle['cohort']:
            raise ValueError('Another plan/cohort is present in the dispatch journal')
        root = batch / rid
        if not (root / 'manifest.json').exists():
            continue  # assigned uncertainty remains in the denominator
        manifest = util.read_json(root / 'manifest.json')
        condition = profiles.validate_run(root)
        if (manifest['run_instance_id'] != binding['run_instance_id']
                or manifest.get('assignment', {}).get('plan_sha256') != digest
                or manifest['condition_sha256'] != binding['condition_sha256']
                or manifest['prompt_sha256'] != binding['input_sha256']
                or condition['evaluation']['evaluation_version'] != evaluation_version(bundle['plan'], binding['task'])
                or condition['evaluation']['evaluator_sha256'] != bundle['runtime_locks'][binding['task']]['evaluator_sha256']):
            raise ValueError('Frozen input/evaluator/instance identity mismatch')
        for kind, name in [('task', binding['task']), ('runtime', bundle['runtime_id']), ('intervention', binding['condition'])]:
            profile_path = 'outer/profiles/' + {'task': 'tasks', 'runtime': 'runtimes', 'intervention': 'interventions'}[kind] + '/' + name + '.json'
            if (util.sha256_file(Path(repo) / profile_path) != bundle['pinned_files'][profile_path]
                    or util.read_json(root / 'profiles' / (kind + '.json')) != util.read_json(Path(repo) / profile_path)):
                raise ValueError('Run profile differs from the frozen bundle')
        # A dispatched slot without a terminal receipt remains in the assigned
        # denominator as unknown. Mutable compatibility aggregates cannot replace
        # the row committed by the single pair manager.
        if rid in state['results']:
            rows.append(terminal_row(root, binding, state['results'][rid],
                state['implementations'][rid], aggregate.row_for(batch, rid)))
    measurement = {'evaluation_version': {task: evaluation_version(bundle['plan'], task) for task in bundle['plan']['task_ids']},
        'evaluator_sha256': {task: lock['evaluator_sha256'] for task, lock in bundle['runtime_locks'].items()}}
    summary=summarize(bundle['plan'], bundle['assignments'], rows, bindings=state['dispatch'],
        plan_sha256=digest, cohort=bundle['cohort'], measurement=measurement)
    summary['acquisition_facts']=slot_facts(bundle,bundle_path,repo,state,rows)
    return summary


def slot_facts(bundle,bundle_path,repo,state,rows):
    """All-assigned factual index; send evidence and manager intent stay distinct."""
    from outer.harness import live_usage
    from research import next_phase
    batch=next_phase.inside(repo,bundle['cohort'],'runs')
    digest=util.sha256_file(bundle_path); by_id={r['run_id']:r for r in rows}; facts=[]
    expected={c['run_id']:c for p in bundle['assignments'] for c in p['cases']}
    if len(expected)!=bundle['plan']['allocation']['runs'] or set(state['dispatch'])-set(expected):
        raise ValueError('All assigned facts require exact slots without extra dispatches')
    for pair in bundle['assignments']:
        for case in pair['cases']:
            rid=case['run_id']; root=batch/rid; binding=state['dispatch'].get(rid); row=by_id.get(rid,{})
            if binding and (binding['plan_sha256']!=digest or binding['cohort']!=bundle['cohort']
                    or case.get('run_instance_id',binding['run_instance_id'])!=binding['run_instance_id']):
                raise ValueError('Slot fact belongs to another bundle or instance')
            manifest_path=root/'manifest.json'
            manifest=util.read_json(manifest_path) if manifest_path.exists() else {}
            if manifest and (manifest['run_id']!=rid or case.get('run_instance_id',manifest['run_instance_id'])!=manifest['run_instance_id']):
                raise ValueError('Manifest fact belongs to another assigned identity')
            evidence=live_usage.execution_evidence(root) if manifest else {'send_evidence':'unknown' if binding else 'known_no_send','issues':[]}
            if not binding and evidence['send_evidence']!='known_no_send':
                raise ValueError('Unmanaged transmission or uncertain assigned original')
            terminal=bool(manifest.get('ended_at') and manifest.get('stop_confirmed') is True)
            observed=evidence['send_evidence']=='observed_send'
            acquisition=('normal' if terminal and observed and manifest.get('end_reason')=='completed' else
                'failed' if terminal and observed else 'incomplete' if binding else 'undispatched')
            gate=state['gates'].get(case['pair'])
            facts.append({**case,'source_family':pair.get('source_family'),'task_membership':pair.get('task_membership'),
                'original_location':str(root),'original_sha256':util.tree_hashes(root) if root.exists() else {},
                'manager_dispatch_recorded':bool(binding),'gateway_execution_evidence':evidence,
                'actual_gateway_send_observed':evidence['send_evidence']=='observed_send',
                'acquisition_state':acquisition,'end_reason':manifest.get('end_reason'),
                'stop_confirmed':manifest.get('stop_confirmed'),'evaluation':row.get('scoring'),
                'quality':row.get('quality'),'usage':row.get('usage'),
                'pair_gate':gate if gate else {'state':'pending'}})
    counts=Counter(f['acquisition_state'] for f in facts)
    return {'kind':'all_assigned_acquisition_fact_index','bundle_reference':next_phase.reference(bundle_path),
        'assigned_pairs':len(bundle['assignments']),'assigned_slots':len(facts),
        'actual_gateway_sent_runs':sum(f['actual_gateway_send_observed'] for f in facts),
        'unknown_send_runs':sum(f['gateway_execution_evidence']['send_evidence']=='unknown' for f in facts),
        'manager_dispatch_count':len(state['dispatch']),'normal_runs':counts['normal'],'failed_runs':counts['failed'],
        'incomplete_runs':counts['incomplete'],'undispatched_runs':counts['undispatched'],
        'completed_pair_gates':len(state['gates']),'rows':facts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    bundle = util.read_json(args.bundle)
    util.write_new_json(args.out, collect(bundle, args.bundle, args.repo))


if __name__ == '__main__':
    main()
