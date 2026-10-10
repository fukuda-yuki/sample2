"""Prospective sensitivity calculations; no historical outcomes or model calls."""
import argparse
import json
import math
from pathlib import Path


def calculate(pairs=64, variants=2, repetitions=32, families=1, pair_concurrency=1):
    if pairs != variants * repetitions or min(pairs, variants, repetitions) <= 0:
        raise ValueError('Pair count must equal variants times repetitions')
    if pair_concurrency not in (1,2): raise ValueError('Pair concurrency must be 1 or 2')
    rows = []
    for missing in (0.0, 0.1, 0.25):
        observed = max(1, math.floor(pairs * (1 - missing)))
        for discordance in (0.2, 0.5, 1.0):
            # D = quality(preload) - quality(explore), in {-1,0,+1}.
            # Var(D) = discordance - E(D)^2; zero difference is conservative
            # for a specified discordance, but dependence can increase uncertainty.
            for session_icc in (0.0, 0.1, 0.3):
                deff = 1 + (4 - 1) * session_icc
                rows.append({'missing_pair_fraction': missing, 'observed_pairs': observed,
                    'discordance': discordance, 'session_cluster_size': 4,
                    'session_icc': session_icc, 'design_effect': deff,
                    'quality_difference_ci95_half_width_normal':
                        1.96 * math.sqrt(discordance * deff / observed)})
    token_rows = []
    for missing in (0.0, 0.1, 0.25):
        observed = max(1, math.floor(pairs * (1 - missing)))
        for cv in (0.5, 1.0, 1.5):
            for rho in (0.0, 0.5):
                for session_icc in (0.0, 0.3):
                    deff = 1 + 3 * session_icc
                    token_rows.append({'missing_pair_fraction': missing,
                        'observed_pairs': observed, 'equal_arm_cv': cv,
                        'within_pair_token_correlation': rho, 'session_icc': session_icc,
                        'ci95_half_width_in_units_of_arm_mean_normal':
                            1.96 * cv * math.sqrt(2 * (1 - rho) * deff / observed)})
    return {'schema_version': 1, 'model_called': False, 'historical_outcomes_used': False,
        'selected_pairs': pairs, 'source_families': families, 'semantic_variants': variants,
        'repetitions_per_variant': repetitions, 'assigned_runs': 2 * pairs,
        'quality_precision_scenarios': rows, 'token_precision_scenarios': token_rows,
        'quality_distribution_free_iid_hoeffding_half_width': math.sqrt(2 * math.log(40) / pairs),
        'new_family_effect_variance_identifiable': False,
        'notes': ['Normal approximations describe assumed precision, not power or a guarantee.',
            'Missingness reduces the complete-pair sample and can cause selection bias; these rows do not identify the all-assigned token contrast.',
            'Session ICC is a sensitivity assumption; four-pair sessions are an operational analysis grouping, not four new independent applications.',
            'The selected fixed families and nested variants do not justify population inference across unselected applications.',
            'There is no noninferiority/equivalence margin or maintenance claim.'],
        'feasibility': {'implementation_wall_clock_cap_hours_serial': 2 * pairs * 1800 / 3600,
            'pair_concurrency': pair_concurrency,
            'implementation_wall_clock_cap_hours_frozen_regime': 2 * pairs * 1800 / 3600 / pair_concurrency,
            'historical_twelve_minute_reference_hours_serial': 2 * pairs * 12 / 60,
            'retained_bytes_scenario_per_run_including_archive': 600_000_000,
            'retained_bytes_scenario_all_assigned': 2 * pairs * 600_000_000,
            'next_pair_peak_increment_scenario_bytes': 8_000_000_000,
            'postprocessing_and_public_gate_hours': None,
            'provider_quota_completion_time': None,
            'reference_is_not_new_task_runtime_or_storage_bound': True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(calculate(), stream, indent=2, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    main()
