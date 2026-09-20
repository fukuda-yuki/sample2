"""Offline, plan-bound analysis of saved catalog observations. Never dispatches.

The existing catalog_observations reader supplies evidence. This module only
validates that interchange, aggregates Runs, and estimates prespecified effects.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np
from scipy import stats


COMPACT = "catalog-compact"
EXPANDED = "catalog-expanded"
ARMS = (COMPACT, EXPANDED)
REQUIREMENTS = tuple(f"R-{i:03d}" for i in range(1, 30))
DEFAULT_PLAN = Path(__file__).parent / "protocols/ms1-catalog-confirmatory-v1.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def allocation(n, seed, attempt_start=1001):
    """Independent fair order per pair; save once, never search for a nice seed."""
    rng = random.Random(seed)
    result = []
    for block in range(1, n + 1):
        order = ARMS if rng.getrandbits(1) == 0 else ARMS[::-1]
        for position, arm in enumerate(order, 1):
            attempt = attempt_start + block - 1
            result.append({"slot": len(result) + 1, "block": block,
                           "position": position, "condition": arm, "attempt": attempt,
                           "run_id": f"MS1-001-{arm}-{attempt:03d}"})
    return result


def validate_plan(plan):
    n = plan["pairs"]
    if type(n) is not int or n < 2 or plan["maximum_runs"] != 2 * n:
        raise ValueError("Invalid fixed Run count")
    if plan["maximum_supplements"] != 0 or plan["quality"]["loss_margin"] != 0:
        raise ValueError("No replacements or positive quality loss margin in v1")
    expected = allocation(n, plan["randomization_seed"], plan["attempt_start"])
    if plan["slots"] != expected:
        raise ValueError("Schedule differs from the saved independent pair allocation")
    if plan["analysis"]["primary_tokens"] != "paired_arithmetic_mean_difference":
        raise ValueError("Unsupported primary estimand")
    if plan["analysis"]["confidence"] != 0.95:
        raise ValueError("v1 fixes 95% two-sided intervals")
    if plan["quality"]["rule"] != "paired_risk_difference_lower_gt_zero":
        raise ValueError("Unsupported quality rule")


def clopper_pearson(k, n, alpha=0.05):
    """Exact equal-tail interval, including non-degenerate 0/n and n/n cases."""
    if n < 1 or not 0 <= k <= n:
        raise ValueError("Invalid binomial counts")
    lo = 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(1 - alpha / 2, k + 1, n - k))
    return [lo, hi]


def paired_quality_interval(wins, losses, n, alpha=0.05):
    """95% conservative paired risk-difference interval by a union bound.

    Each discordant cell probability receives a 97.5% CP interval; with at
    least 95% simultaneous coverage their difference lies in [Lw-Ul, Uw-Ll].
    Does not assume independence of the two discordant cell counts.
    """
    if wins < 0 or losses < 0 or wins + losses > n:
        raise ValueError("Invalid paired cells")
    w = clopper_pearson(wins, n, alpha / 2)
    l = clopper_pearson(losses, n, alpha / 2)
    return [max(-1.0, w[0] - l[1]), min(1.0, w[1] - l[0])]


def paired_mean(compact, expanded, alpha=0.05):
    c, e = np.asarray(compact, dtype=float), np.asarray(expanded, dtype=float)
    if c.shape != e.shape or c.ndim != 1 or len(c) < 2:
        raise ValueError("At least two complete pairs required")
    if not np.isfinite(c).all() or not np.isfinite(e).all():
        raise ValueError("Missing/nonfinite values are not zeros")
    d = c - e
    mean = float(d.mean())
    se = float(d.std(ddof=1) / math.sqrt(len(d)))
    # Identical observed differences do not justify a zero uncertainty interval
    # for a stochastic, unbounded Run population. Keep the estimate, defer inference.
    if se == 0:
        interval, p = None, None
    else:
        radius = float(stats.t.ppf(1 - alpha / 2, len(d) - 1) * se)
        interval = [mean - radius, mean + radius]
        p = float(stats.t.cdf(mean / se, len(d) - 1))
    return {"n_pairs": len(d), "mean_compact": float(c.mean()),
            "mean_expanded": float(e.mean()), "difference": mean,
            "ci95": interval, "one_sided_p_reduction": p,
            "mean_ratio": float(c.mean() / e.mean()) if e.mean() > 0 else None,
            "standard_error": se, "degenerate_variance": se == 0}


def pair_bootstrap(compact, expanded, seed, repetitions):
    """Secondary fixed pair bootstrap; never substitutes for the t interval."""
    c, e = np.asarray(compact, dtype=float), np.asarray(expanded, dtype=float)
    rng = np.random.default_rng(seed)
    differences, ratios = [], []
    for start in range(0, repetitions, 500):
        ix = rng.integers(0, len(c), size=(min(500, repetitions - start), len(c)))
        cm, em = c[ix].mean(axis=1), e[ix].mean(axis=1)
        differences.extend((cm - em).tolist())
        ratios.extend(np.divide(cm, em, out=np.full_like(cm, np.nan), where=em > 0).tolist())
    diff = np.quantile(differences, [0.025, 0.975]).tolist()
    ratio = np.quantile(ratios, [0.025, 0.975]).tolist() if np.isfinite(ratios).all() else None
    return {"repetitions": repetitions, "seed": seed,
            "difference_ci95": diff if np.ptp(differences) > 0 else None,
            "mean_ratio_ci95": ratio if ratio and ratio[0] != ratio[1] else None,
            "role": "sensitivity_only_no_metric_switch"}


def _count(value, name):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"Invalid nonnegative integer: {name}")
    return value


def auxiliary(observation):
    """Reuse the existing action classifier; heuristics never change quality."""
    from research.analyze import classify as classify_action
    actions = observation.get("actions", [])
    labels, phases, written, sequence = Counter(), Counter(), set(), []
    for action in actions:
        labels.update(action.get("labels", []))
        codes, _ = classify_action(action.get("tool", ""), action.get("inputs", {}), "", written)
        phases.update(codes)
        path = action.get("inputs", {}).get("filePath")
        if path and action.get("tool") in ("write", "edit", "apply_patch"):
            written.add(path)
        phase = "implementation" if any(k in codes for k in ("implementation", "revision")) else (
            "verification" if any(k in codes for k in ("build", "validation")) else None)
        if phase and (not sequence or sequence[-1] != phase):
            sequence.append(phase)
    calls = observation.get("calls", [])
    lengths = [c.get("input_tokens") for c in calls]
    all_input_known = bool(lengths) and all(type(v) is int and v >= 0 for v in lengths)
    return {"per_call_input_mean": float(np.mean(lengths)) if all_input_known else None,
            "per_call_input_max": max(lengths) if all_input_known else None,
            "source_access_labels": dict(labels), "action_labels_overlapping": dict(phases),
            "implementation_verification_phase_switches": max(0, len(sequence) - 1),
            "later_exact_tool_output_retentions": sum(a.get("later_exact_retentions", 0) for a in actions),
            "later_changed_tool_output_retentions": sum(a.get("later_changed_retentions", 0) for a in actions),
            "returned_bytes_exposure_sum": sum(a.get("returned_bytes_exposure_sum", 0) for a in actions),
            "initial_packet_retained_calls": sum(c.get("initial_packet_retained") is True for c in calls),
            "file_access_evidence": [{k: a.get(k) for k in (
                "tool_call_id", "native_ref", "labels", "visible_numbered_lines",
                "first_returned_utf8_bytes", "truncation_notice_observed", "request_exposures")}
                for a in actions if a.get("labels")],
            "usage_format_analysis": "Review saved raw usage shapes separately; never exclusion or causal explanation by itself",
            "limits": "Bash access candidates require command/range review; no automatic claim of full-source reacquisition. Bytes are not tokens."}


def normalize_observation(observation, slot):
    """Preserve known failures AND incomplete coverage as independent facts."""
    if observation.get("case") != slot or observation.get("run_id") != slot["run_id"]:
        raise ValueError("Run identity/allocation mismatch")
    row = observation.get("row", {})
    if row and row.get("intervention_id") != slot["condition"]:
        raise ValueError("Observed condition differs from assignment")
    requirements = {}
    for item in observation.get("requirements", []):
        key, judgement = item["id"], item["judgement"]
        if key not in REQUIREMENTS or key in requirements:
            raise ValueError("Duplicate or unexpected requirement")
        if judgement not in ("pass", "fail", "blocked", "unknown"):
            raise ValueError("Unknown requirement judgement")
        requirements[key] = judgement
    known_failed = set((row.get("confirmed_product_failure") or {}).get("requirements", []))
    if not known_failed <= set(REQUIREMENTS):
        raise ValueError("Unexpected confirmed failure requirement")
    for key in known_failed:
        requirements[key] = "fail"
    scope = observation.get("evaluation_scope", {})
    complete = (len(requirements) == 29 and
                all(v in ("pass", "fail") for v in requirements.values()) and
                row.get("artifact", {}).get("state") == "fixed" and
                row.get("scoring", {}).get("state") == "scored" and
                row.get("scoring", {}).get("research_status") == "complete" and
                not scope.get("evaluatorFaults"))
    failed = "fail" in requirements.values() or row.get("verdict") in ("fail", "fail_critical")
    outcome = 0 if failed else 1 if complete and row.get("verdict") == "pass" and all(v == "pass" for v in requirements.values()) else None
    if row.get("verdict") == "pass" and failed:
        raise ValueError("Contradictory pass and confirmed failure")
    token = observation.get("tokens") or {}
    inputs = _count(token.get("input_tokens"), "input_tokens")
    outputs = _count(token.get("output_tokens"), "output_tokens")
    total = _count(token.get("total_tokens"), "total_tokens")
    calls = observation.get("calls", [])
    token_complete = (observation.get("usage_complete") is True and
                      not observation.get("token_audit_issues") and
                      inputs is not None and outputs is not None and total is not None)
    if token_complete:
        if total != inputs + outputs:
            raise ValueError("Total is not input plus output")
        for field, expected in (("input_tokens", inputs), ("output_tokens", outputs)):
            values = [_count(call.get(field), field) for call in calls]
            if any(v is None for v in values) or sum(values) != expected:
                raise ValueError("Run total does not reconcile with all saved calls")
        if not calls and total != 0:
            raise ValueError("Nonzero tokens without calls")
        if not calls and observation.get("verified_zero_dispatch") is not True:
            token_complete = False
    known = _count(token.get("known_total_tokens"), "known_total_tokens")
    return {**slot, "outcome": outcome, "confirmed_failure": failed,
            "coverage_complete": complete, "requirements": requirements,
            "total_tokens": total if token_complete else None,
            "input_tokens": inputs if token_complete else None,
            "output_tokens": outputs if token_complete else None,
            "known_total_tokens": known, "calls": len(calls),
            "call_input_tokens": [call.get("input_tokens") for call in calls],
            "token_complete": token_complete,
            "execution": row.get("execution", {"state": observation.get("state", "unknown")}),
            "artifact_present": row.get("artifact", {}).get("state") == "fixed",
            "run_instance_id": row.get("run_instance_id"),
            "integrity_issues": observation.get("audit_issues", []),
            "cleanup_confirmed": (observation.get("runtime_cleanup") or {}).get("confirmed") is True and
                                 (observation.get("browser_cleanup") or {}).get("confirmed") is True,
            "action_count": len(observation.get("actions", [])),
            "auxiliary": auxiliary(observation),
            "human_review": observation.get("human_review", "not_run")}


def quality_summary(pairs):
    n = len(pairs)
    arms = {}
    for index, arm in enumerate(ARMS):
        rows = [pair[index] for pair in pairs]
        counts = Counter(row["outcome"] for row in rows)
        passes, fails, unknown = counts[1], counts[0], counts[None]
        arms[arm] = {"assigned": n, "pass": passes, "confirmed_fail": fails,
                     "unknown_outcome": unknown,
                     "coverage_incomplete": sum(not r["coverage_complete"] for r in rows),
                     "artifacts": sum(r["artifact_present"] for r in rows),
                     "pass_fraction_artifacts": passes / sum(r["artifact_present"] for r in rows)
                        if any(r["artifact_present"] for r in rows) else None,
                     "pass_fraction_assigned": passes / n,
                     "sample_pass_rate_bounds": [passes / n, (passes + unknown) / n],
                     "pass_rate_ci95_envelope": [clopper_pearson(passes, n)[0],
                                                 clopper_pearson(passes + unknown, n)[1]],
                     "requirements": {key: {value: sum(r["requirements"].get(key, "unknown") == value for r in rows)
                                             for value in ("pass", "fail", "blocked", "unknown")}
                                      for key in REQUIREMENTS}}
    wins = losses = worst_wins = worst_losses = best_wins = best_losses = 0
    complete_outcomes = True
    for c, e in pairs:
        yc, ye = c["outcome"], e["outcome"]
        complete_outcomes &= yc is not None and ye is not None
        wins += yc == 1 and ye == 0
        losses += yc == 0 and ye == 1
        wc, we = (0 if yc is None else yc), (1 if ye is None else ye)
        bc, be = (1 if yc is None else yc), (0 if ye is None else ye)
        worst_wins += wc == 1 and we == 0
        worst_losses += wc == 0 and we == 1
        best_wins += bc == 1 and be == 0
        best_losses += bc == 0 and be == 1
    ci = [paired_quality_interval(worst_wins, worst_losses, n)[0],
          paired_quality_interval(best_wins, best_losses, n)[1]]
    return {"arms": arms, "n_pairs": n, "wins": wins, "losses": losses,
            "difference": (wins - losses) / n if complete_outcomes else None,
            "sample_difference_bounds": [(worst_wins - worst_losses) / n,
                                         (best_wins - best_losses) / n],
            "ci95_or_missingness_envelope": ci,
            "outcomes_complete": complete_outcomes,
            "coverage_complete": all(r["coverage_complete"] for pair in pairs for r in pair),
            "relative_quality_supported": complete_outcomes and ci[0] > 0,
            "quality_condition_status": ("supported" if complete_outcomes and ci[0] > 0 else
                                         "evidence_of_degradation" if complete_outcomes and ci[1] < 0 else "unresolved"),
            "practical_adequacy": "not_established_no_justified_population_floor",
            "method": "Bonferroni union of two 97.5% Clopper-Pearson discordant-cell intervals"}


def classify(tokens, quality, integrity_ok):
    if (not integrity_ok or tokens is None or tokens["ci95"] is None or
            not quality["outcomes_complete"] or not quality["coverage_complete"]):
        return "indeterminate"
    if tokens["ci95"][1] >= 0:
        return "token_reduction_not_supported"
    if quality["relative_quality_supported"]:
        return "token_reduction_and_relative_quality_supported"
    return "token_reduction_quality_not_supported_or_unresolved"


def analyze(plan, observations, purpose="confirmatory"):
    """One row per allocated Run. Missing rows stay in the fixed denominator."""
    if purpose == "confirmatory":
        validate_plan(plan)
        if not observations.get("launch_receipt"):
            raise ValueError("Confirmatory data require a pre-dispatch launch receipt")
    if observations["cohort"] != plan["cohort"]:
        raise ValueError("Historical/pilot cohort cannot enter confirmatory analysis")
    inventory = {}
    expected = {slot["run_id"] for slot in plan["slots"]}
    for observation in observations["runs"]:
        run_id = observation["run_id"]
        if run_id not in expected or run_id in inventory:
            raise ValueError("Unexpected or duplicate Run; model calls are not samples")
        inventory[run_id] = observation
    rows = []
    for slot in plan["slots"]:
        observation = inventory.get(slot["run_id"], {"case": slot, "run_id": slot["run_id"], "state": "not_started"})
        normalized = normalize_observation(observation, slot)
        if purpose == "confirmatory" and observation.get("row"):
            actual = observation["row"]
            pins = plan["fixed_conditions"]
            initial = observation.get("initial_input", {})
            mismatches = []
            if actual.get("task_id") != plan["task"] or actual.get("attempt") != slot["attempt"]:
                mismatches.append("task_or_attempt_mismatch")
            if actual.get("synthetic") or not actual.get("run_instance_id"):
                mismatches.append("synthetic_or_missing_instance")
            if (initial.get("gateway") or {}).get("prompt_sha256") != pins["initial_prompt_sha256"][slot["condition"]]:
                mismatches.append("initial_prompt_mismatch")
            if not ((initial.get("gateway") or {}).get("verified") and
                    initial.get("semantic_match_to_mock") and initial.get("same_files_permissions_ranges")):
                mismatches.append("unverified_input_or_common_access")
            if any(call.get("response_models") != [plan["model"]] for call in observation.get("calls", [])):
                mismatches.append("model_mismatch")
            if normalized["coverage_complete"] and (
                    actual["scoring"].get("evaluator_sha256") != pins["evaluator_sha256"] or
                    actual["scoring"].get("evaluation_version") != pins["evaluation_version"]):
                mismatches.append("evaluator_mismatch")
            normalized["integrity_issues"] = [*normalized["integrity_issues"], *mismatches]
        rows.append(normalized)
    instances = [r["run_instance_id"] for r in rows if r["run_instance_id"]]
    if len(instances) != len(set(instances)):
        raise ValueError("Repeated model Run instance")
    blocks = {}
    for row in rows:
        block = blocks.setdefault(row["block"], {})
        if row["condition"] in block:
            raise ValueError("Duplicated condition within pair")
        block[row["condition"]] = row
    if any(set(block) != set(ARMS) for block in blocks.values()):
        raise ValueError("Every allocation block must contain both conditions")
    pairs = [tuple(block[arm] for arm in ARMS) for _, block in sorted(blocks.items())]
    quality = quality_summary(pairs)
    complete_pairs = [pair for pair in pairs if all(r["token_complete"] for r in pair)]
    complete_summary = None
    sensitivity = None
    if len(complete_pairs) >= 2:
        c, e = ([pair[i]["total_tokens"] for pair in complete_pairs] for i in (0, 1))
        complete_summary = paired_mean(c, e)
        analysis = plan.get("analysis", {})
        sensitivity = pair_bootstrap(c, e, analysis.get("bootstrap_seed", 20260921),
                                     analysis.get("bootstrap_repetitions", 20000))
    tokens = complete_summary if len(complete_pairs) == len(pairs) else None
    integrity_ok = all(not r["integrity_issues"] and r["cleanup_confirmed"] for r in rows)
    result = classify(tokens, quality, integrity_ok)
    descriptive = {}
    for arm in ARMS:
        selected = [r for r in rows if r["condition"] == arm]
        measured = [r for r in selected if r["token_complete"]]
        success = [r for r in measured if r["outcome"] == 1]
        descriptive[arm] = {"assigned_runs": len(selected), "complete_usage_runs": len(measured),
                            "missing_usage_runs": len(selected) - len(measured),
                            "observed_calls": sum(r["calls"] for r in selected),
                            "all_assigned_total_tokens": sum(r["total_tokens"] for r in measured) if len(measured) == len(selected) else None,
                            "known_partial_tokens": sum(r["known_total_tokens"] for r in selected if r["known_total_tokens"] is not None) if any(r["known_total_tokens"] is not None for r in selected) else None,
                            "mean_input_tokens": float(np.mean([r["input_tokens"] for r in measured])) if len(measured) == len(selected) else None,
                            "mean_output_tokens": float(np.mean([r["output_tokens"] for r in measured])) if len(measured) == len(selected) else None,
                            "success_only_mean_total_secondary": float(np.mean([r["total_tokens"] for r in success])) if success else None,
                            "success_only_n_secondary": len(success)}
    return {"schema_version": 1, "purpose": purpose, "cohort": plan["cohort"],
            "model_called": False, "evaluator_called": False,
            "assigned_runs": len(rows), "n_pairs": len(pairs),
            "primary_tokens": tokens, "quality": quality,
            "complete_pair_tokens_secondary": complete_summary,
            "bootstrap_secondary": sensitivity,
            "order_diagnostics_secondary": {
                arm: {"pairs": sum(pair[0]["position"] == (1 if arm == COMPACT else 2) for pair in pairs),
                      "mean_difference_complete_pairs": float(np.mean([
                          pair[0]["total_tokens"] - pair[1]["total_tokens"] for pair in complete_pairs
                          if pair[0]["position"] == (1 if arm == COMPACT else 2)]))
                      if any(pair[0]["position"] == (1 if arm == COMPACT else 2) for pair in complete_pairs) else None}
                for arm in ARMS},
            "descriptive": descriptive, "integrity_ok": integrity_ok,
            "decision": result if purpose == "confirmatory" else "not_a_confirmatory_result",
            "quality_maintenance_under_equality": "not_established_by_this_zero_margin_design",
            "practical_efficiency_claim": "not_authorized_without_absolute_quality_criterion",
            "at_least_planning_target_reduction_supported": bool(tokens and tokens["ci95"] and
                 tokens["ci95"][1] < -plan.get("planning", {}).get("token_difference_target", math.inf)),
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--purpose", choices=("confirmatory", "pilot_smoke"), default="confirmatory")
    parser.add_argument("--launch-receipt", type=Path)
    args = parser.parse_args()
    plan, observations = read_json(args.plan), read_json(args.observations)
    if observations.get("plan_sha256") != sha256(args.plan):
        raise ValueError("Observation plan hash mismatch")
    if args.launch_receipt:
        receipt = read_json(args.launch_receipt)
        required = plan.get("launch", {}).get("receipt_required", [])
        if any(not receipt.get(key) for key in required):
            raise ValueError("Incomplete pre-dispatch launch receipt")
        if receipt.get("analysis_plan_sha256") != sha256(args.plan) or not receipt.get("pre_dispatch_verified"):
            raise ValueError("Launch receipt is not bound to this frozen plan")
        for name, digest in receipt.get("frozen_analysis_code_hashes", {}).items():
            if sha256(Path(__file__).resolve().parents[1] / name) != digest:
                raise ValueError("Analysis code differs from pre-dispatch receipt")
        observations["launch_receipt"] = receipt
    result = analyze(plan, observations, args.purpose)
    result["source_files"] = {"plan_sha256": sha256(args.plan),
                              "observations_sha256": sha256(args.observations)}
    write_new(args.out, result)
    print(json.dumps({"out": str(args.out), "assigned_runs": result["assigned_runs"],
                      "decision": result["decision"]}))


if __name__ == "__main__":
    main()
