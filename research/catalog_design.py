"""No-model sample-size sensitivity calculations for the fixed catalog design."""
import argparse
import math
import platform

import numpy as np
import scipy
from scipy import stats

from research.catalog_confirmatory import DEFAULT_PLAN, read_json, sha256, write_new


def token_power(n, reduction, cv, rho):
    """Normal paired-difference approximation; means in units of expanded mean."""
    variance = cv ** 2 * ((1 - reduction) ** 2 + 1 - 2 * rho * (1 - reduction))
    cutoff = stats.t.ppf(0.975, n - 1)
    noncentrality = -reduction * math.sqrt(n / variance)
    return float(stats.nct.cdf(-cutoff, n - 1, noncentrality))


def minimum_token_n(reduction, cv, rho, power=0.8):
    lo, hi = 3, 100000
    while lo < hi:
        middle = (lo + hi) // 2
        if token_power(middle, reduction, cv, rho) >= power:
            hi = middle
        else:
            lo = middle + 1
    return lo


def cp_table(n, alpha=0.025):
    k = np.arange(n + 1)
    lo, hi = np.zeros(n + 1), np.ones(n + 1)
    lo[1:] = stats.beta.ppf(alpha / 2, k[1:], n - k[1:] + 1)
    hi[:-1] = stats.beta.ppf(1 - alpha / 2, k[:-1] + 1, n - k[:-1])
    return lo, hi


def binary_cells(pc, pe, rho):
    both = pc * pe + rho * math.sqrt(pc * (1 - pc) * pe * (1 - pe))
    cells = np.array([both, pc - both, pe - both, 1 - pc - pe + both])
    if cells.min() < -1e-12:
        raise ValueError("Impossible paired binary correlation")
    return np.maximum(cells, 0) / cells.sum()


def mc_summary(indicators):
    p = float(np.mean(indicators))
    n = len(indicators)
    # Monte Carlo error only; does not cover misspecification of the scenario.
    interval = stats.binomtest(int(sum(indicators)), n).proportion_ci(method="wilson")
    return {"estimate": p, "mc_se": math.sqrt(p * (1 - p) / n), "replicates": n,
            "mc_ci95_wilson": [float(interval.low), float(interval.high)]}


def quality_power_exact(n, pc, pe, rho):
    """Exact probability of this conservative quality rule under the scenario.

    Condition on loss count L ~ Bin(n, q_loss), then W | L is binomial.
    CP lower/upper tables determine the rejection region without simulation.
    """
    _, qw, ql, _ = binary_cells(pc, pe, rho)
    if ql == 1:
        return 0.0
    lower, upper = cp_table(n)
    losses = np.arange(n + 1)
    first_winning_count = np.searchsorted(lower, upper, side="right")
    conditional_tail = stats.binom.sf(first_winning_count - 1, n - losses, qw / (1 - ql))
    return min(1.0, max(0.0, float(np.sum(stats.binom.pmf(losses, n, ql) * conditional_tail))))


def quality_simulation(n, pc, pe, rho, repetitions, rng):
    cells = binary_cells(pc, pe, rho)
    draws = rng.multinomial(n, cells, size=repetitions)
    wins, losses = draws[:, 1], draws[:, 2]
    lo, hi = cp_table(n)
    lower, upper = lo[wins] - hi[losses], hi[wins] - lo[losses]
    true_difference = pc - pe
    return {"n": n, "p_compact": pc, "p_expanded": pe, "binary_rho": rho,
            "cell_probabilities_both_win_loss_neither": cells.tolist(),
            "support_zero_margin_quality": mc_summary(lower > 0),
            "coverage": mc_summary((lower <= true_difference) & (true_difference <= upper)),
            "mean_ci_half_width": float(np.mean((upper - lower) / 2)),
            "p90_ci_half_width": float(np.quantile((upper - lower) / 2, 0.9))}


def token_simulation(n, reduction, cv, rho, kind, repetitions, rng):
    """Parametric scenarios, never an empirical bootstrap of the four pilot Runs.

    Lognormal uses latent rho chosen to give the requested token correlation.
    Contamination is a separate stress case: independent 2% tenfold multipliers,
    mean-normalized, with an explicitly different achieved CV/correlation.
    """
    sigma2 = math.log1p(cv * cv)
    latent = math.log1p(rho * cv * cv) / sigma2
    decisions, covered, half_widths = [], [], []
    target = -reduction
    cutoff = float(stats.t.ppf(0.975, n - 1))
    for start in range(0, repetitions, 200):
        size = (min(200, repetitions - start), n)
        z1, z2 = rng.normal(size=size), rng.normal(size=size)
        e = np.exp(-sigma2 / 2 + math.sqrt(sigma2) * z1)
        c = (1 - reduction) * np.exp(-sigma2 / 2 + math.sqrt(sigma2) *
                                     (latent * z1 + math.sqrt(1 - latent ** 2) * z2))
        if kind == "contaminated":
            e *= np.where(rng.random(size) < 0.02, 10.0, 1.0) / 1.18
            c *= np.where(rng.random(size) < 0.02, 10.0, 1.0) / 1.18
        elif kind != "lognormal":
            raise ValueError("Unknown tail model")
        d = c - e
        center, radius = d.mean(axis=1), cutoff * d.std(axis=1, ddof=1) / math.sqrt(n)
        decisions.extend((center + radius < 0).tolist())
        covered.extend(((center - radius <= target) & (target <= center + radius)).tolist())
        half_widths.extend(radius.tolist())
    effective_cv = cv
    effective_rho = rho
    if kind == "contaminated":
        multiplier_second_moment = (0.98 + 0.02 * 100) / 1.18 ** 2
        effective_cv = math.sqrt((1 + cv * cv) * multiplier_second_moment - 1)
        effective_rho = rho * cv * cv / effective_cv ** 2
    return {"n": n, "reduction": reduction, "base_cv": cv, "base_token_rho": rho,
            "tail_model": kind, "effective_cv": effective_cv,
            "effective_token_rho": effective_rho,
            "reduction_support": mc_summary(decisions), "ci_coverage": mc_summary(covered),
            "mean_ci_half_width_over_expanded_mean": float(np.mean(half_widths))}


def calculate(plan):
    planning = plan["planning"]
    candidates = planning["candidate_pairs"]
    repetitions = planning["simulation_repetitions"]
    rng = np.random.default_rng(planning["simulation_seed"])
    token_analytic = []
    for reduction in (0.1, 0.2, 0.3):
        for cv in (0.5, 1.0, 1.5):
            for rho in (-0.25, 0.0, 0.25, 0.5):
                token_analytic.append({"reduction": reduction, "cv": cv, "token_rho": rho,
                    "n_for_80pct_normal_approximation": minimum_token_n(reduction, cv, rho),
                    "candidate_power": {str(n): token_power(n, reduction, cv, rho) for n in candidates}})
    token_scenarios = [("lognormal", 0.5, 0.5), ("lognormal", 1.0, 0.25),
                       ("lognormal", 1.5, 0.0), ("contaminated", 0.75, 0.25),
                       ("lognormal", 1.0, -0.25)]
    token_simulations = [token_simulation(n, reduction, cv, rho, kind, repetitions, rng)
                         for n in candidates for kind, cv, rho in token_scenarios
                         for reduction in (0.0, 0.1, 0.2)]
    quality_scenarios = [(0.5, 0.5, 0.0), (0.8, 0.8, 0.0), (0.8, 0.8, 0.5),
                         (0.8, 0.8, -0.2),
                         (0.95, 0.95, 0.0), (1.0, 1.0, 0.0),
                         (0.75, 0.8, 0.0), (0.85, 0.8, 0.0),
                         (0.95, 0.9, 0.5), (1.0, 0.95, 0.0)]
    quality_simulations = [quality_simulation(n, pc, pe, rho, repetitions, rng)
                           for n in candidates for pc, pe, rho in quality_scenarios]
    resources = []
    for n in candidates:
        resources.append({"pairs": n, "runs": 2 * n,
            "provider_token_envelopes": {str(mean): int(2 * n * mean) for mean in (2000000, 3200000, 6000000)},
            "pilot_mean_scaled_tokens_reference_only": int(2 * n * 12723904 / 4),
            "pilot_mean_scaled_runtime_hours_reference_only": 2 * n * (525.071 + 305.956 + 665.185 + 1484.920) / 4 / 3600,
            "maximum_runtime_budget_hours": 2 * n * 1800 / 3600,
            "extra_evaluation_storage_hours_scenarios": {str(seconds): 2 * n * seconds / 3600 for seconds in (60, 300)},
            "disk_gib_scenarios": {str(gib): 2 * n * gib for gib in (0.1, 0.5, 1.0)}})
    extremes = []
    for n in candidates:
        lo, hi = cp_table(n)
        # All-concordant (all pass OR all fail) still leaves discordance uncertain.
        extremes.append({"pairs": n, "all_concordant_ci95": [-float(hi[0]), float(hi[0])],
                         "worst_discordance_expected_half_width": float(hi[n // 2] - lo[n // 2])})
    quality_size_grid = []
    for pc, pe, rho in ((0.85, 0.8, 0.0), (0.95, 0.9, 0.5), (1.0, 0.95, 0.0)):
        grid = {str(n): quality_power_exact(n, pc, pe, rho)
                for n in (40, 80, 160, 320, 640, 1280, 2560, 5120)}
        first = next((int(n) for n, power in grid.items() if power >= 0.8), None)
        quality_size_grid.append({"p_compact": pc, "p_expanded": pe, "binary_rho": rho,
                                  "exact_power_by_n": grid,
                                  "first_evaluated_size_at_least_80pct": first})
    return {"schema_version": 1, "kind": "design_calculation_not_experimental_results",
            "model_called": False, "recommended_pairs": plan["pairs"],
            "assumptions_are_not_pilot_estimates": True,
            "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "simulation_seed": planning["simulation_seed"], "simulation_repetitions": repetitions,
            "token_normal_approximation": token_analytic,
            "token_parametric_simulations": token_simulations,
            "quality_multinomial_simulations": quality_simulations,
            "quality_superiority_size_grid": quality_size_grid,
            "boundary_intervals": extremes, "resources": resources,
            "equal_quality_80pct_power_sample_size": None,
            "equal_quality_reason": "Zero margin tests superiority: equality cannot have 80% rejection probability at any n.",
            "cost_currency": None, "resource_authorization": "not_requested_not_granted"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=str, default=str(DEFAULT_PLAN))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = calculate(read_json(args.plan))
    result["plan_sha256"] = sha256(args.plan)
    write_new(args.out, result)
    print(f"Saved offline design calculations: {args.out}")


if __name__ == "__main__":
    main()
