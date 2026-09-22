"""Offline, plan-bound analysis of saved catalog observations. Never dispatches.

The existing catalog_observations reader supplies evidence. This module only
validates that interchange, aggregates Runs, and estimates prespecified effects.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
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
HISTORICAL_PLAN = Path(__file__).parent / "protocols/ms1-catalog-confirmatory-v1.json"
DEFAULT_PLAN = Path(__file__).parent / "protocols/ms1-catalog-comparison-v2.json"
REPO = Path(__file__).resolve().parents[1]
REQUIRED_CODE = ("research/catalog_confirmatory.py", "research/catalog_observations.py",
                 "research/analyze.py", "research/requirements-confirmatory.txt")
REQUIRED_RECEIPT = ("analysis_plan_sha256", "frozen_analysis_code_hashes",
                    "pre_dispatch_verified", "checked_at_utc", "resource_capacity_confirmation",
                    "identity_and_browser_pin_checks", "dispatch_journal_path")


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


def validate_launch_receipt(plan, observations, receipt, plan_path):
    """Single validation boundary for CLI, embedded JSON and direct calls.

    This verifies shape and content binding, not the truth of a human attestation.
    The pre-dispatch journal and resource/pin evidence remain reviewable sources.
    """
    if plan.get('date_revision'):
        from research.catalog_date_revision import validate_history
        if plan_path is None or read_json(plan_path) != plan or observations.get('plan_sha256') != sha256(plan_path):
            raise ValueError('Revised observations must bind their exact saved plan')
        public = (REPO / 'MANIFEST.json').is_file()
        history = validate_history(plan_path, REPO, public=public)
        if (observations.get('date_revision_history') != history or
                receipt != read_json(REPO / plan['runs_dir'] / '_control/launch-receipt.json')):
            raise ValueError('Missing or changed original launch/amendment history')
        return
    required = set(REQUIRED_RECEIPT) | set(plan.get("launch", {}).get("receipt_required", []))
    if not isinstance(receipt, dict) or any(not receipt.get(key) for key in required):
        raise ValueError("Incomplete pre-dispatch launch receipt")
    if plan_path is None or read_json(plan_path) != plan:
        raise ValueError("Provide the saved plan file matching the analysis plan value")
    digest = sha256(plan_path)
    if (receipt.get("analysis_plan_sha256") != digest or
            observations.get("plan_sha256") != digest or
            receipt.get("pre_dispatch_verified") is not True):
        raise ValueError("Launch receipt/observations are not bound to this frozen plan")
    try:
        checked = datetime.fromisoformat(receipt["checked_at_utc"].replace("Z", "+00:00"))
        if checked.utcoffset() != timezone.utc.utcoffset(checked):
            raise ValueError("Not UTC")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Launch receipt requires a UTC checked_at_utc") from exc
    for key in ("resource_capacity_confirmation", "identity_and_browser_pin_checks"):
        evidence = receipt[key]
        if (not isinstance(evidence, dict) or evidence.get("verified") is not True or
                not isinstance(evidence.get("evidence_reference"), str) or
                not evidence["evidence_reference"].strip()):
            raise ValueError(f"Launch receipt requires verified evidence: {key}")
    if not isinstance(receipt["dispatch_journal_path"], str) or not receipt["dispatch_journal_path"].strip():
        raise ValueError("Launch receipt requires a dispatch journal path")
    hashes = receipt["frozen_analysis_code_hashes"]
    required_code = set(REQUIRED_CODE) | set(plan.get("launch", {}).get("required_code_files", []))
    if not isinstance(hashes, dict) or not required_code <= set(hashes):
        raise ValueError("Launch receipt is missing required analysis code hashes")
    for name, digest in hashes.items():
        path = (REPO / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(REPO) or not path.is_file():
            raise ValueError("Invalid analysis code path in launch receipt")
        if sha256(path) != digest:
            raise ValueError("Analysis code differs from pre-dispatch receipt")


def validate_plan(plan, require_allocation=False):
    version = plan.get("schema_version")
    if version not in (1, 2):
        raise ValueError("Unsupported plan version")
    n = plan["pairs"]
    if version == 2 and n is None:
        if (plan["maximum_runs"] is not None or plan["runs_per_condition"] is not None or plan["slots"]):
            raise ValueError("Unselected resource design cannot contain allocated Runs")
        if require_allocation:
            raise ValueError("Resource capacity and fixed allocation are not yet selected")
    elif type(n) is not int or n < 2 or plan["maximum_runs"] != 2 * n or plan["runs_per_condition"] != n:
        raise ValueError("Invalid fixed Run count")
    if version == 1 and require_allocation:
        raise ValueError("Historical v1 is design history, not an adopted execution plan")
    if plan["maximum_supplements"] != 0 or plan["quality"]["loss_margin"] != (0 if version == 1 else None):
        raise ValueError("No replacements or invented quality loss margin")
    if n is not None and plan["slots"] != allocation(n, plan["randomization_seed"], plan["attempt_start"]):
        raise ValueError("Schedule differs from the saved independent pair allocation")
    if plan["analysis"]["primary_tokens"] != "paired_arithmetic_mean_difference":
        raise ValueError("Unsupported primary estimand")
    if plan["analysis"]["confidence"] != 0.95:
        raise ValueError("Plan fixes 95% two-sided intervals")
    if plan["quality"]["rule"] != ("paired_risk_difference_lower_gt_zero" if version == 1 else "estimate_difference_superiority_additional"):
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
            "unobserved_requirements": [key for key in REQUIREMENTS if requirements.get(key) not in ("pass", "fail")],
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
            "token_integrity_issues": list(observation.get("token_audit_issues", [])),
            "quality_integrity_issues": [],
            "cleanup_confirmed": (observation.get("runtime_cleanup") or {}).get("confirmed") is True and
                                 (observation.get("browser_cleanup") or {}).get("confirmed") is True,
            "action_count": len(observation.get("actions", [])),
            "behavior_observation_present": "actions" in observation,
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
            "practical_adequacy": "not_established_no_justified_population_floor",
            "method": "Bonferroni union of two 97.5% Clopper-Pearson discordant-cell intervals"}


def classify(token_eligible, quality_eligible):
    """Availability of inference, never a research success/failure gate."""
    if token_eligible and quality_eligible:
        return "both_metrics_estimable"
    if token_eligible:
        return "tokens_estimable_quality_unresolved"
    if quality_eligible:
        return "quality_estimable_tokens_unresolved"
    return "indeterminate"


def analyze(plan, observations, purpose="confirmatory", *, launch_receipt=None, plan_path=None):
    """One row per allocated Run. Missing rows stay in the fixed denominator."""
    if purpose not in ("confirmatory", "pilot_smoke"):
        raise ValueError("Unknown analysis purpose")
    if purpose == "confirmatory":
        validate_plan(plan, require_allocation=True)
        embedded = observations.get("launch_receipt")
        if launch_receipt is not None and embedded is not None and launch_receipt != embedded:
            raise ValueError("Conflicting CLI/function and embedded launch receipts")
        validate_launch_receipt(plan, observations, launch_receipt if launch_receipt is not None else embedded, plan_path)
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
        # Known usage/behavior audit categories do not invalidate another endpoint.
        # Unrecognized provenance faults remain shared; never guess them harmless.
        shared_issues, behavior_issues = [], []
        for issue in normalized["integrity_issues"]:
            if issue in ("incomplete_request_inventory", "normalized_total_differs") or issue.startswith("usage_raw_mismatch:"):
                normalized["token_integrity_issues"].append(issue)
            elif issue == "native_provider_tool_inventory_differs" or issue.startswith("duplicate_native_tool:"):
                behavior_issues.append(issue)
            else:
                shared_issues.append(issue)
        normalized["integrity_issues"] = shared_issues
        normalized["behavior_integrity_issues"] = behavior_issues
        if purpose == "confirmatory" and slot["run_id"] in inventory:
            actual = observation.get("row", {})
            pins = plan["fixed_conditions"]
            initial = observation.get("initial_input", {})
            if plan.get('date_revision') and observation.get('row'):
                from research.catalog_identity import compare_initial
                baseline = REPO / plan['probe'] / ('MS1-001-' + slot['condition'] + '-001')
                comparison = compare_initial(REPO / plan['runs_dir'] / slot['run_id'], baseline, plan)
                if initial.get('comparison') != comparison or initial.get('semantic_match_to_mock') != bool(comparison and comparison['matches']):
                    raise ValueError('Observation comparison differs from the revised rule/raw evidence')
                normalized['initial_input_comparison'] = comparison
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
            # A known fail with partial coverage still needs the correct evaluator.
            if normalized["requirements"] or normalized["outcome"] is not None:
                scoring = actual.get("scoring", {})
                if (scoring.get("evaluator_sha256") != pins["evaluator_sha256"] or
                        scoring.get("evaluation_version") != pins["evaluation_version"]):
                    normalized["quality_integrity_issues"].append("evaluator_mismatch")
                if not normalized["artifact_present"]:
                    normalized["quality_integrity_issues"].append("artifact_not_fixed")
                if scoring.get("state") == "rejected_mismatch" or any(
                        issue.get("kind") == "mismatch" for issue in actual.get("issues", [])):
                    normalized["quality_integrity_issues"].append("evaluation_identity_mismatch")
            normalized["integrity_issues"] = [*normalized["integrity_issues"], *mismatches]
        normalized["recorded_outcome"] = normalized["outcome"]
        if normalized["integrity_issues"] or normalized["quality_integrity_issues"]:
            normalized["outcome"] = None
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
    shared_ok = all(not r["integrity_issues"] for r in rows)
    token_ok = shared_ok and all(not r["token_integrity_issues"] for r in rows)
    quality_ok = shared_ok and all(not r["quality_integrity_issues"] for r in rows)
    confirmatory = purpose == "confirmatory"
    token_reasons = ([] if confirmatory else ["pilot_descriptive_only"])
    quality_reasons = list(token_reasons)
    if not token_ok:
        token_reasons.append("token_or_shared_integrity_fault")
    if not quality_ok:
        quality_reasons.append("quality_or_shared_integrity_fault")
    if tokens is None:
        token_reasons.append("missing_usage_in_assigned_population")
    elif tokens["ci95"] is None:
        token_reasons.append("undefined_token_interval")
    if not quality["outcomes_complete"]:
        quality_reasons.append("unknown_binary_outcomes")
    token_eligible, quality_eligible = not token_reasons, not quality_reasons
    token_supported = bool(token_eligible and tokens["ci95"][1] < 0)
    quality_ci = quality["ci95_or_missingness_envelope"]
    quality_supported = bool(quality_eligible and quality_ci[0] > 0)
    quality.update(inference_eligible=quality_eligible, inference_blockers=quality_reasons,
                   relative_quality_supported=quality_supported,
                   quality_condition_status=("not_inferable" if not quality_eligible else
                       "relative_superiority_supported" if quality_supported else
                       "evidence_of_degradation" if quality_ci[1] < 0 else "difference_unresolved"))
    result = classify(token_eligible, quality_eligible)
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
    return {"schema_version": 2, "purpose": purpose, "cohort": plan["cohort"],
            **({'date_revision_history': observations['date_revision_history']}
               if plan.get('date_revision') and purpose == 'confirmatory' else {}),
            "model_called": False, "evaluator_called": False,
            "assigned_runs": len(rows), "n_pairs": len(pairs),
            "primary_tokens": tokens if token_ok else None, "quality": quality,
            "all_assigned_tokens_descriptive": tokens,
            "token_inference": {"eligible": token_eligible, "blockers": token_reasons,
                "reduction_supported": token_supported,
                "status": "not_inferable" if not token_eligible else
                          "reduction_supported" if token_supported else "reduction_not_supported"},
            "conclusions": {"token_reduction_supported": token_supported,
                "relative_quality_superiority_supported": quality_supported,
                "token_reduction_and_relative_quality_supported": token_supported and quality_supported,
                "quality_maintenance": "not_established_no_justified_margin",
                "research_success": "not_defined_by_joint_superiority",
                "intervals": "marginal_95pct_not_a_joint_95pct_confidence_region"},
            "complete_pair_tokens_secondary": complete_summary,
            "bootstrap_secondary": sensitivity,
            "order_diagnostics_secondary": {
                arm: {"pairs": sum(pair[0]["position"] == (1 if arm == COMPACT else 2) for pair in pairs),
                      "mean_difference_complete_pairs": float(np.mean([
                          pair[0]["total_tokens"] - pair[1]["total_tokens"] for pair in complete_pairs
                          if pair[0]["position"] == (1 if arm == COMPACT else 2)]))
                      if any(pair[0]["position"] == (1 if arm == COMPACT else 2) for pair in complete_pairs) else None}
                for arm in ARMS},
            "descriptive": descriptive, "integrity_ok": token_ok and quality_ok,
            "metric_integrity": {"shared": shared_ok, "tokens": token_ok, "quality": quality_ok},
            "operational": {"cleanup_complete": all(r["cleanup_confirmed"] for r in rows),
                "coverage_complete": quality["coverage_complete"],
                "behavior_complete": all(r["behavior_observation_present"] and not r["behavior_integrity_issues"] for r in rows),
                "role": "reported_separately_not_an_automatic_inference_veto"},
            "decision": result if purpose == "confirmatory" else "not_a_confirmatory_result",
            "quality_maintenance_under_equality": "not_established_no_justified_margin",
            "practical_efficiency_claim": "not_authorized_without_absolute_quality_criterion",
            "at_least_planning_target_reduction_supported": bool(token_eligible and
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
    if args.purpose == "pilot_smoke" and observations.get("plan_sha256") != sha256(args.plan):
        raise ValueError("Observation plan hash mismatch")
    receipt = read_json(args.launch_receipt) if args.launch_receipt else None
    result = analyze(plan, observations, args.purpose, launch_receipt=receipt, plan_path=args.plan)
    result["source_files"] = {"plan_sha256": sha256(args.plan),
                              "observations_sha256": sha256(args.observations)}
    write_new(args.out, result)
    print(json.dumps({"out": str(args.out), "assigned_runs": result["assigned_runs"],
                      "decision": result["decision"]}))


if __name__ == "__main__":
    main()
