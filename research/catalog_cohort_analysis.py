"""Offline cohort analysis of an immutable catalog snapshot (never dispatches).

Usage: python catalog_cohort_analysis.py --root SNAPSHOT --out ANALYSES
Requires numpy and scipy. The selected snapshot is the complete report scope.
Reference intervals concern comparable repeated executions under independent,
stable pair distributions; they do not impute missing usage or require further
collection. Complete-usage subsets never replace all selected executions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import scipy
from scipy import stats


ARMS = ("compact", "expanded")
LABELS = {"compact": "初期ソース抜粋なし", "expanded": "初期ソース抜粋あり"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def table(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def distribution(values):
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if not len(v):
        return {"n": 0, "mean": None, "median": None, "ci95": None}
    mean = float(v.mean())
    sd = float(v.std(ddof=1)) if len(v) > 1 else None
    half = float(stats.t.ppf(.975, len(v)-1) * sd / np.sqrt(len(v))) if sd else None
    return {"n": len(v), "sum": float(v.sum()), "mean": mean,
            "median": float(np.median(v)), "sd": sd, "min": float(v.min()), "max": float(v.max()),
            "q25": float(np.quantile(v, .25)), "q75": float(np.quantile(v, .75)),
            "ci95": [mean-half, mean+half] if half is not None else None}


def cp(k, n, alpha=.05):
    return [0. if k == 0 else float(stats.beta.ppf(alpha/2, k, n-k+1)),
            1. if k == n else float(stats.beta.ppf(1-alpha/2, k+1, n-k))]


def quality(pairs):
    n = len(pairs)
    cells = Counter((p["compact_all_pass"], p["expanded_all_pass"]) for p in pairs)
    known = all(a is not None and b is not None for a, b in cells)
    wins, losses = cells[(1, 0)], cells[(0, 1)]
    worst_wins = sum((p["compact_all_pass"] or 0) == 1 and (1 if p["expanded_all_pass"] is None else p["expanded_all_pass"]) == 0 for p in pairs)
    worst_losses = sum((p["compact_all_pass"] or 0) == 0 and (1 if p["expanded_all_pass"] is None else p["expanded_all_pass"]) == 1 for p in pairs)
    best_wins = sum((1 if p["compact_all_pass"] is None else p["compact_all_pass"]) == 1 and (p["expanded_all_pass"] or 0) == 0 for p in pairs)
    best_losses = sum((1 if p["compact_all_pass"] is None else p["compact_all_pass"]) == 0 and (p["expanded_all_pass"] or 0) == 1 for p in pairs)
    low = cp(worst_wins, n, .025)[0] - cp(worst_losses, n, .025)[1]
    high = cp(best_wins, n, .025)[1] - cp(best_losses, n, .025)[0]
    return {"n_pairs": n, "outcomes_complete": known, "both_pass": cells[(1, 1)],
            "known_outcome_pairs": sum(p["compact_all_pass"] is not None and p["expanded_all_pass"] is not None for p in pairs),
            "unknown_outcome_pairs": [p["pair"] for p in pairs if p["compact_all_pass"] is None or p["expanded_all_pass"] is None],
            "compact_only": wins, "expanded_only": losses, "both_fail": cells[(0, 0)],
            "difference": (wins-losses)/n if known else None,
            "sample_difference_bounds": [(worst_wins-worst_losses)/n, (best_wins-best_losses)/n],
            "conservative_ci95": [low, high],
            "method": "Difference of two 97.5% Clopper-Pearson discordant-cell intervals; reference inference for independent pairs with stable outcome probabilities, not uncertainty in the recorded cohort proportion",
            "equivalence_or_noninferiority": "not_established_no_margin"}


def paired_tokens(pairs, bootstrap=False):
    pp = [p for p in pairs if p["compact_total_tokens"] is not None and p["expanded_total_tokens"] is not None]
    if not pp:
        return {"n_pairs": 0}
    c = np.array([p["compact_total_tokens"] for p in pp], dtype=float)
    e = np.array([p["expanded_total_tokens"] for p in pp], dtype=float)
    d = c-e
    result = {"n_pairs": len(pp), "pairs": [p["pair"] for p in pp],
              "compact": distribution(c), "expanded": distribution(e), "difference": distribution(d),
              "ratio_of_means": float(c.mean()/e.mean()), "relative_change": float(c.mean()/e.mean()-1),
              "compact_lower_pairs": int((d < 0).sum()),
              "role": "complete_usage_subset_description_not_all_acquired"}
    if bootstrap:
        ix = np.random.default_rng(2026092101).integers(0, len(pp), (20000, len(pp)))
        result["bootstrap"] = {"seed": 2026092101, "repetitions": 20000, "unit": "pair",
            "difference_ci95": np.quantile(d[ix].mean(axis=1), [.025, .975]).tolist(),
            "ratio_ci95": np.quantile(c[ix].mean(axis=1)/e[ix].mean(axis=1), [.025, .975]).tolist()}
    return result


def temporal_comparison(runrows, pairs):
    """Disjoint descriptions of acquisition order, never independent old-vs-full tests."""
    last = max(p["pair"] for p in pairs)
    partitions = {
        "first_33_and_subsequent": [(1, min(33, last)), (34, last)],
        "successive_groups_of_25": [(start, min(start+24, last)) for start in range(1, last+1, 25)],
    }
    result = {"role": "Post hoc disjoint acquisition-order descriptions of the same task; time, order, provider, failure and selection mechanisms can differ. No old-subset-versus-containing-full-cohort independence test.",
              "partitions": {}}
    for name, spans in partitions.items():
        groups = []
        for start, end in spans:
            if start > end:
                continue
            pp = [p for p in pairs if start <= p["pair"] <= end]
            rr = [r for r in runrows if start <= r["pair"] <= end]
            group = {"first_pair": start, "last_pair": end, "n_pairs": len(pp), "n_runs": len(rr),
                "quality": quality(pp), "complete_usage": paired_tokens(pp),
                "duration_difference": distribution(p["difference_duration_seconds"] for p in pp), "arms": {}}
            for arm in ARMS:
                aa = [r for r in rr if r["arm"] == arm]
                group["arms"][arm] = {"n": len(aa), "pass": sum(r["all_pass"] == 1 for r in aa),
                    "fail": sum(r["all_pass"] == 0 for r in aa), "unknown": sum(r["all_pass"] is None for r in aa),
                    "complete_usage_n": sum(r["token_complete"] for r in aa),
                    "missing_usage_runs": [r["run_id"] for r in aa if not r["token_complete"]],
                    "missing_duration_runs": [r["run_id"] for r in aa if r["duration_seconds"] is None],
                    "execution_states": dict(Counter(r["execution_state"] for r in aa)),
                    "duration_seconds": distribution(r["duration_seconds"] for r in aa),
                    "tokens_complete_only": distribution(r["total_tokens"] for r in aa)}
            groups.append(group)
        result["partitions"][name] = groups
    return result


def compare_extracted(extracted, out, snapshot_sha256):
    """Independently produced stdlib raw-evidence tables versus observation metrics."""
    def csv_rows(name):
        with (extracted/(name+".csv")).open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def value(text, reference):
        if text == "":
            return None
        if isinstance(reference, (bool, int, float, list, dict)):
            return json.loads(text)
        return text

    checked, issues = Counter(), []
    source_runs = {r["run_id"]: r for r in csv_rows("runs")}
    calculated = read(out/"runs.json")
    if set(source_runs) != {r["run_id"] for r in calculated}:
        issues.append("run_inventory")
    mapping = {"pair": "block", "position": "position", "started_at": "started_at", "ended_at": "ended_at",
        "duration_seconds": "duration_seconds", "execution_state": "execution_state", "token_complete": "usage_complete",
        "calls": "request_count", "total_tokens": "total_tokens", "known_total_tokens": "observed_tokens",
        "input_tokens": "input_tokens", "output_tokens": "output_tokens", "cache_read_tokens": "cache_read_tokens",
        "reasoning_tokens": "reasoning_tokens", "coverage_complete": "evaluation_complete", "quality_score": "quality",
        "all_pass": "all_requirements_pass", "failed_requirements": "known_failed_requirements", "human_review": "human_review"}
    for row in calculated:
        raw = source_runs[row["run_id"]]
        if raw["condition"] != "catalog-"+row["arm"]:
            issues.append(row["run_id"]+":condition")
        for dest, source in mapping.items():
            checked["run_field"] += 1
            extracted_value = value(raw[source], row[dest])
            if dest == "token_complete":
                # Source null is retained in extraction. This derived indicator
                # asks only whether completeness is established as true.
                extracted_value = extracted_value is True
            if extracted_value != row[dest]:
                issues.append(row["run_id"]+":"+dest)
    source_requirements = {(r["run_id"], r["requirement_id"]): r for r in csv_rows("requirements")}
    calculated_requirements = read(out/"requirements.json")
    if set(source_requirements) != {(r["run_id"], r["id"]) for r in calculated_requirements}:
        issues.append("requirement_inventory")
    for row in calculated_requirements:
        key = (row["run_id"], row["id"])
        checked["requirement_judgement"] += 1
        if source_requirements.get(key, {}).get("judgement") != row["judgement"]:
            issues.append(":".join(key))
    source_calls = {(r["run_id"], r["request_id"]): r for r in csv_rows("calls")}
    calculated_calls = read(out/"calls.json")
    if set(source_calls) != {(r["run_id"], r["request_id"]) for r in calculated_calls}:
        issues.append("call_inventory")
    for row in calculated_calls:
        key = (row["run_id"], row["request_id"])
        raw = source_calls.get(key, {})
        for name in ("call_index", "input_tokens", "output_tokens", "status", "http_status", "stream_done", "response_models", "request_sha256", "response_sha256"):
            checked["call_field"] += 1
            if value(raw.get(name, ""), row[name]) != row[name]:
                issues.append(":".join(key)+":"+name)
    raw_verify = read(extracted/"verify.json")
    raw_errors = raw_verify.get("errors", [])
    # These exact discrepancies were diagnosed against the sealed cancelled SSE
    # response: it contains partial usage that the saved event/normalizer omitted.
    # They remain errors in the raw verifier, never become zero or a complete Run.
    discrepancy_run = "MS1-001-catalog-expanded-1085"
    discrepancy_request = "e257b6cf018a4e8f9496e569a1fe28d2"
    recognized_errors = {(discrepancy_run, name, discrepancy_request) for name in
                         ("sse_native_usage", "sse_normalized_event_usage", "otlp_request_usage")}
    recognized_errors.update((discrepancy_run, name, None) for name in
                             ("raw_to_normalized_input_tokens", "raw_to_normalized_output_tokens", "raw_to_normalized_reasoning_tokens", "observed_total"))
    for error in raw_errors:
        if (error.get("run_id"), error.get("check"), error.get("detail")) not in recognized_errors:
            issues.append("unclassified_raw_extractor_error:"+json.dumps(error, sort_keys=True))
    if raw_errors:
        rr = next((r for r in calculated if r["run_id"] == discrepancy_run), None)
        cc = next((c for c in calculated_calls if c["run_id"] == discrepancy_run and c["request_id"] == discrepancy_request), None)
        if not (rr and cc and rr["token_complete"] is False and rr["total_tokens"] is None
                and rr["known_total_tokens"] == 3049684 and rr["normalized_known_total_tokens"] == 2952025
                and cc["status"] == "cancelled" and cc["stream_done"] is False
                and cc["input_tokens"] == 97652 and cc["output_tokens"] == 7
                and cc["response_sha256"] == "039d7d62251b44508020c51e2ba1a4198e09aa5e592b44cdbd22cce15bf4e0c4"):
            issues.append("diagnosed_raw_discrepancy_evidence_mismatch")
    if raw_verify.get("verified") is not (not raw_errors):
        issues.append("raw_extractor_verdict_inconsistent")
    if raw_verify.get("snapshot_sha256") != snapshot_sha256:
        issues.append("raw_extractor_snapshot_hash_mismatch")
    write(out/"analysis-extracted-crosscheck.json", {"verified": not issues, "check_count": sum(checked.values()),
        "checks": dict(checked), "issues": issues,
        "raw_original_consistency_verified": raw_verify.get("verified"),
        "retained_raw_original_errors": raw_errors,
        "verification_meaning": "Table values reconcile and raw-original discrepancies are explicitly classified. This does not assert inconsistent source records agree; retained raw verifier errors remain unresolved original-record discrepancies.",
        "sources": {name: sha(extracted/name) for name in ("runs.csv", "requirements.csv", "calls.csv", "verify.json")},
        "snapshot_sha256": snapshot_sha256,
        "scope": "Independent stdlib raw SSE/evaluation/SQLite extraction versus saved observation analysis. No model or evaluator run."})
    if issues:
        raise ValueError("Independent extraction disagreement: " + repr(issues[:12]))


def analyze(root, out, extracted=None):
    root, out = root.resolve(), out.resolve()
    if root == out or root in out.parents:
        raise ValueError("Output must be outside the immutable snapshot")
    marker = root/"SNAPSHOT.json"
    if not marker.exists():
        marker = root.parent/"SNAPSHOT.json"
    if not marker.exists():
        raise ValueError("Snapshot completion marker SNAPSHOT.json is required")
    snapshot = read(marker)
    stopped = {r["run_id"]: r for r in snapshot.get("unsealed_stopped_runs", [])}
    base = root/"runs/catalog-comparison-v2"
    ctl = base/"_control"
    if not ctl.exists():
        ctl = root/"control"
    plan_path = root/"research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json"
    if not plan_path.exists():
        plan_path = ctl/"frozen-plan.json"
    plan = read(plan_path)
    slots = {s["run_id"]: s for s in plan["slots"]}
    sources = {str(marker.relative_to(root.parent)): sha(marker), str(plan_path.relative_to(root)): sha(plan_path)}
    checks = Counter()

    def check(condition, name, detail):
        checks[name] += 1
        if not condition:
            raise ValueError(f"{name}: {detail}")

    observations = []
    for p in sorted(ctl.glob("observations-pair-*.json")):
        doc = read(p)
        sources[p.relative_to(root).as_posix()] = sha(p)
        check(doc["plan_sha256"] == sha(plan_path), "plan_identity", p.name)
        observations.extend(doc["runs"])
    check(bool(observations) and len(observations) % 2 == 0, "nonempty_complete_pair_inventory", len(observations))
    check(len({r["run_id"] for r in observations}) == len(observations), "unique_run_ids", len(observations))
    check(set(snapshot["selected_runs"]) == {r["run_id"] for r in observations}, "snapshot_selected_runs", len(observations))
    check(snapshot["plan_sha256"] == sha(plan_path), "snapshot_plan_hash", snapshot["plan_sha256"])
    runrows, callrows, reqrows, behaviorrows = [], [], [], []
    retained_limitations, record_discrepancies = [], []
    diagnosed_audit_issues = {
        "MS1-001-catalog-expanded-1048": {"native_provider_tool_inventory_differs"},
        "MS1-001-catalog-expanded-1085": {"usage_raw_mismatch:44:input_tokens", "usage_raw_mismatch:44:output_tokens"},
        "MS1-001-catalog-expanded-1094": {"native_provider_tool_inventory_differs"},
    }
    for obs in sorted(observations, key=lambda r: r["case"]["slot"]):
        rid, row, case = obs["run_id"], obs["row"], obs["case"]
        rp = base/rid
        check(case == slots[rid], "allocation", rid)
        # Preserve diagnosed measurement limitations without discarding unrelated
        # outcomes. New audit issue types still stop analysis for review.
        audit_issues = obs["audit_issues"] or []
        token_audit_issues = obs["token_audit_issues"] or []
        check(set(audit_issues + token_audit_issues) <= diagnosed_audit_issues.get(rid, set()), "saved_audit_issues_classified", rid)
        check(not token_audit_issues or obs["usage_complete"] is not True, "token_audit_incomplete_usage", rid)
        if audit_issues or token_audit_issues:
            retained_limitations.append({"run_id": rid, "audit_issues": audit_issues, "token_audit_issues": token_audit_issues,
                "handling": "Raw partial usage remains descriptive; token audit discrepancies preclude complete totals. Tool inventory discrepancies limit behavior coverage, not independently verified usage or evaluation."})
        check(obs["initial_input"]["semantic_match_to_mock"] and obs["initial_input"]["same_files_permissions_ranges"], "input_contract", rid)
        manifest = read(rp/"manifest.json")
        usage_path = rp/"usage/normalized.json"
        evaluation_index_path = rp/"evaluations/index.jsonl"
        if rid in stopped:
            exception = stopped[rid]
            check(exception.get("historical_seal_verified") is False and exception.get("capture_time_stability_verified") is True,
                  "declared_stopped_capture", rid)
            check(manifest["end_reason"] == row["execution"]["state"] == "operator_stop"
                  and manifest["submission_fixed"] is False and row["artifact"]["state"] == "not_fixed"
                  and row["scoring"]["state"] == "not_attempted" and row["scoring"]["evaluation_id"] is None
                  and not obs["requirements"] and row.get("quality") is None and row["verdict"] is None,
                  "unsealed_stopped_state", rid)
            check(not usage_path.exists() and not evaluation_index_path.exists(), "unsealed_stopped_missing_records", rid)
            usage = {}
            source_paths = (rp/"manifest.json",)
            retained_limitations.append({"run_id": rid, "audit_issues": ["unsealed_stopped_run"],
                "handling": "Capture stability does not establish historical sealing. Keep raw calls and partial tokens; usage total, quality, evaluation and saved duration remain unknown."})
        else:
            usage = read(usage_path)
            evaluation_index = [json.loads(line) for line in evaluation_index_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            adopted = [entry for entry in evaluation_index if entry["evaluation_id"] == row["scoring"]["evaluation_id"]]
            check(len(adopted) == 1, "adopted_evaluation_index", rid)
            evaluation_path = rp/adopted[0]["directory"]/"evaluation.json"
            evaluation = read(evaluation_path)
            check(sha(evaluation_path) == adopted[0]["evaluation_sha256"], "selected_evaluation_hash", rid)
            check(evaluation["requirements"] == obs["requirements"], "adopted_requirements", rid)
            check(row["scoring"]["evaluator_sha256"] == plan["fixed_conditions"]["evaluator_sha256"], "evaluator_identity", rid)
            source_paths = (rp/"manifest.json", usage_path, evaluation_index_path, evaluation_path)
        for p in source_paths:
            sources[p.relative_to(root).as_posix()] = sha(p)
        arm = case["condition"].split("-")[-1]
        requirements = obs["requirements"]
        if rid not in stopped:
            check(len(requirements) == 29 and len({r["id"] for r in requirements}) == 29, "29_requirements", rid)
        failures = [r["id"] for r in requirements if r["judgement"] == "fail"]
        blocked = [r["id"] for r in requirements if r["judgement"] not in ("pass", "fail")]
        scope = obs["evaluation_scope"]
        coverage = len(requirements) == 29 and not blocked and row["artifact"]["state"] == "fixed" and row["scoring"]["state"] == "scored" and row["scoring"].get("research_status") == "complete" and not scope.get("evaluatorFaults")
        outcome = 0 if failures else 1 if coverage and row["verdict"] == "pass" else None
        token = obs["tokens"]
        complete = obs["usage_complete"] is True and all(token.get(k) is not None for k in ("input_tokens", "output_tokens", "total_tokens"))
        if complete:
            check(token["total_tokens"] == token["input_tokens"] + token["output_tokens"] == usage["total_tokens"], "complete_total_reconciliation", rid)
            for key in ("input_tokens", "output_tokens"):
                check(all(c.get(key) is not None for c in obs["calls"]) and sum(c[key] for c in obs["calls"]) == token[key], "call_total_reconciliation", rid+":"+key)
        check((usage.get("usage_complete") is True) == complete, "usage_completeness", rid)
        for key in ("input_tokens", "output_tokens"):
            check(sum(c[key] for c in obs["calls"] if c.get(key) is not None) == token["known_"+key], "known_call_sum_reconciliation", rid+":"+key)
        check(token["known_total_tokens"] == token["known_input_tokens"] + token["known_output_tokens"], "known_total_reconciliation", rid)
        if usage.get("observed_tokens") is not None and usage["observed_tokens"] != token["known_total_tokens"]:
            check(bool(token_audit_issues), "known_usage_difference_has_saved_audit", rid)
            record_discrepancies.append({"run_id": rid, "field": "known_token_subtotal", "raw_observation": token["known_total_tokens"],
                "normalized_observed": usage["observed_tokens"], "difference": token["known_total_tokens"]-usage["observed_tokens"],
                "handling": "Use raw observation partial sum; retain normalized partial sum and do not claim complete usage."})
        if manifest.get("model_called") is False and obs["calls"]:
            check(rid in stopped, "declared_model_called_discrepancy", rid)
            record_discrepancies.append({"run_id": rid, "field": "model_called", "manifest": False,
                "saved_row": row.get("model_called"), "observed_request_records": len(obs["calls"]),
                "handling": "Do not use the false flag to remove observed requests or classify this as an uncalled execution."})
        actions = obs["actions"]
        labels, tools = Counter(), Counter()
        for action in actions:
            labels.update(action.get("labels", [])); tools[action["tool"]] += 1
        rr = {"run_id": rid, "pair": case["block"], "slot": case["slot"], "arm": arm,
              "condition_label": LABELS[arm], "position": case["position"],
              "started_at": manifest["started_at"], "ended_at": manifest["ended_at"],
              "date_utc": manifest["started_at"][:10], "execution_state": row["execution"]["state"],
              "total_tokens": token["total_tokens"] if complete else None,
              "known_total_tokens": token["known_total_tokens"], "token_complete": complete,
              "input_tokens": token["input_tokens"] if complete else None,
              "output_tokens": token["output_tokens"] if complete else None,
              "cache_read_tokens": usage.get("cache_read_tokens") if complete else None,
              "reasoning_tokens": usage.get("reasoning_tokens") if complete else None,
              "uncached_input_tokens": token["input_tokens"]-usage["cache_read_tokens"] if complete and usage.get("cache_read_tokens") is not None else None,
              "duration_seconds": row["execution"]["duration_seconds"], "all_pass": outcome,
              "quality_score": row.get("quality"), "coverage_complete": coverage,
              "evaluation_available": rid not in stopped, "unsealed_stopped_run": rid in stopped,
              "saved_model_called": manifest.get("model_called"),
              "normalized_known_total_tokens": usage.get("observed_tokens"),
              "audit_issues": audit_issues, "token_audit_issues": token_audit_issues,
              "behavior_inventory_complete": "native_provider_tool_inventory_differs" not in audit_issues,
              "failed_requirements": failures, "unobserved_requirements": blocked,
              "evaluation_state": row["scoring"]["state"], "browser_coverage": scope.get("browserCartCoverage"),
              "human_review": obs.get("human_review", "not_run"), "calls": len(obs["calls"]),
              "first_input_tokens": obs["calls"][0].get("input_tokens") if obs["calls"] else None,
              "mean_input_per_call": token["input_tokens"]/len(obs["calls"]) if complete and obs["calls"] else None,
              "initial_packet_retained_calls": sum(c["initial_packet_retained"] for c in obs["calls"]),
              "initial_packet_retained_after_first": sum(c["initial_packet_retained"] for c in obs["calls"][1:]),
              "catalog_source_reads": labels["catalog_source_return"], "derived_catalog_reads": labels["derived_catalog_return"],
              "catalog_packet_reads": labels["catalog_packet_return"], "bash_access_candidates": labels["file_access_candidate_review_command"],
              "tool_actions": len(actions), "tool_errors": sum(a["status"] != "completed" for a in actions),
              "large_outputs": len(obs["large_outputs"]),
              "returned_bytes_exposure_sum": sum(a["returned_bytes_exposure_sum"] for a in actions),
              "exact_tool_output_retentions": sum(a["later_exact_retentions"] for a in actions),
              "changed_tool_output_retentions": sum(a["later_changed_retentions"] for a in actions),
              "request_utf8_bytes_sum": sum(c["request_utf8_bytes"] for c in obs["calls"])}
        runrows.append(rr)
        for c in obs["calls"]:
            callrows.append({"run_id": rid, "pair": case["block"], "arm": arm, **c})
        for q in requirements:
            reqrows.append({"run_id": rid, "pair": case["block"], "arm": arm, **q})
        behaviorrows.append({"run_id": rid, "arm": arm, "source_access_labels": dict(labels), "tool_counts": dict(tools)})

    pairs = []
    pair_ids = sorted({r["pair"] for r in runrows})
    check(pair_ids == list(range(1, len(pair_ids)+1)), "contiguous_acquired_prefix", pair_ids)
    pair_fields = ["total_tokens", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens", "uncached_input_tokens", "first_input_tokens", "duration_seconds", "calls", "tool_actions", "all_pass"]
    for number in pair_ids:
        group = {r["arm"]: r for r in runrows if r["pair"] == number}
        check(set(group) == set(ARMS), "both_assigned_conditions", number)
        p = {"pair": number, "compact_position": group["compact"]["position"]}
        for k in pair_fields:
            c, e = group["compact"][k], group["expanded"][k]
            p["compact_"+k], p["expanded_"+k] = c, e
            p["difference_"+k] = c-e if c is not None and e is not None else None
        pairs.append(p)
    metrics = [k for k, v in runrows[0].items() if (type(v) in (int, float) or v is None) and k not in ("pair", "slot", "position", "all_pass", "known_total_tokens")]
    arm_summary = {}
    for arm in ARMS:
        rr = [r for r in runrows if r["arm"] == arm]
        complete_rows = [r for r in rr if r["token_complete"]]
        passes = sum(r["all_pass"] == 1 for r in rr)
        unknown = sum(r["all_pass"] is None for r in rr)
        arm_summary[arm] = {"label": LABELS[arm], "n": len(rr), "passes": sum(r["all_pass"] == 1 for r in rr),
            "confirmed_failures": sum(r["all_pass"] == 0 for r in rr), "unknown_outcomes": sum(r["all_pass"] is None for r in rr),
            "quality_pass_rate": passes/len(rr) if not unknown else None,
            "sample_pass_rate_bounds": [passes/len(rr), (passes+unknown)/len(rr)],
            "pass_rate_ci95": cp(passes, len(rr)) if not unknown else None,
            "pass_rate_ci95_unknown_outcome_envelope": [cp(passes, len(rr))[0], cp(passes+unknown, len(rr))[1]],
            "complete_usage_runs": len(complete_rows), "incomplete_inspections": sum(not r["coverage_complete"] for r in rr),
            "known_token_subtotal": sum(r["known_total_tokens"] or 0 for r in rr),
            "execution_states": dict(Counter(r["execution_state"] for r in rr)),
            "failure_combinations": dict(Counter(",".join(r["failed_requirements"]) or ("unknown_outcome" if r["all_pass"] is None else "none") for r in rr)),
            "metrics": {k: distribution(r[k] for r in rr) for k in metrics},
            "cache_share_complete_usage": sum(r["cache_read_tokens"] for r in complete_rows)/sum(r["input_tokens"] for r in complete_rows)}
    req_summary = []
    for key in sorted({q["id"] for q in reqrows}):
        for arm in ARMS:
            qq = [q for q in reqrows if q["id"] == key and q["arm"] == arm]
            counts = Counter(q["judgement"] for q in qq)
            req_summary.append({"requirement_id": key, "arm": arm, "n": arm_summary[arm]["n"],
                                "observed_judgements": len(qq), "missing_evaluation": arm_summary[arm]["n"]-len(qq),
                                **{k: counts[k] for k in ("pass", "fail", "blocked", "unknown")}})
    full = [p for p in pairs if p["difference_total_tokens"] is not None]
    sensitivities = {}
    subsets = {
        "compact_first": [p for p in full if p["compact_position"] == 1],
        "expanded_first": [p for p in full if p["compact_position"] == 2],
        "first_half_by_saved_pair_order": [p for p in full if p["pair"] <= len(pairs)//2],
        "second_half_by_saved_pair_order": [p for p in full if p["pair"] > len(pairs)//2],
        "exclude_first_r2_pair": [p for p in full if p["pair"] != 1],
        "exclude_two_largest_absolute_differences": sorted(full, key=lambda p: abs(p["difference_total_tokens"]))[:-2],
        "both_pass_only_post_outcome_selection": [p for p in full if p["compact_all_pass"] == 1 and p["expanded_all_pass"] == 1],
    }
    for name, sub in subsets.items():
        if sub:
            sensitivities[name] = paired_tokens(sub)
            sensitivities[name]["duration_difference"] = distribution(p["difference_duration_seconds"] for p in sub)
    by_date = []
    for date in sorted({r["date_utc"] for r in runrows}):
        for arm in ARMS:
            rr = [r for r in runrows if r["date_utc"] == date and r["arm"] == arm]
            if rr:
                by_date.append({"date_utc": date, "arm": arm, "n": len(rr),
                    "pass": sum(r["all_pass"] == 1 for r in rr), "token_complete_n": sum(r["token_complete"] for r in rr),
                    "tokens_complete_only": distribution(r["total_tokens"] for r in rr), "duration_seconds": distribution(r["duration_seconds"] for r in rr)})
    correlations = {}
    for arm in ARMS:
        rr = [r for r in runrows if r["arm"] == arm and r["token_complete"]]
        correlations[arm] = {}
        for key in ("calls", "duration_seconds", "tool_actions", "large_outputs", "returned_bytes_exposure_sum"):
            coefficient = float(stats.spearmanr([r["total_tokens"] for r in rr], [r[key] for r in rr]).statistic)
            correlations[arm][key] = coefficient if np.isfinite(coefficient) else None
    outcome_profiles = []
    for arm in ARMS:
        for outcome in (0, 1, None):
            rr = [r for r in runrows if r["arm"] == arm and r["all_pass"] == outcome]
            if rr:
                outcome_profiles.append({"arm": arm, "all_pass": outcome, "n": len(rr),
                    "complete_usage_n": sum(r["token_complete"] for r in rr),
                    "tokens_complete_only": distribution(r["total_tokens"] for r in rr),
                    "duration_seconds": distribution(r["duration_seconds"] for r in rr),
                    "role": "post_outcome_description_not_causal_adjustment"})
    duration_known_sums = {arm: sum(r["duration_seconds"] for r in runrows if r["arm"] == arm and r["duration_seconds"] is not None) for arm in ARMS}
    duration_missing_counts = {arm: sum(r["duration_seconds"] is None for r in runrows if r["arm"] == arm) for arm in ARMS}
    duration_known_difference = duration_known_sums["compact"]-duration_known_sums["expanded"]
    summary = {
        "schema_version": 2, "classification": "fixed_observed_cohort_analysis",
        "condition_labels": LABELS,
        "snapshot_captured_at_utc": snapshot["captured_at_utc"],
        "report_scope": "All selected executions in SNAPSHOT.json; subsequent acquisition is outside this report. The historical allocation file is retained for identity and order verification, not as a completion target.",
        "metrics_population": "Each metric distribution excludes its own nulls and reports n. Complete token and quality-score distributions describe their observed subsets, not all selected executions. Known partial-token subtotals have no inference interval.",
        "inference_scope": "Observed counts, rates and complete-data differences describe this fixed cohort. Reference intervals concern comparable repeated executions under independent, stable pair distributions; these assumptions do not follow from repeated use of one task or randomized order alone. Intervals do not quantify missing-token amounts or uncertainty in recorded cohort counts.",
        "acquired_pairs": len(pairs), "acquired_runs": len(runrows),
        "complete_usage_pairs": len(full), "unknown_usage_runs": [r["run_id"] for r in runrows if not r["token_complete"]],
        "unknown_quality_runs": [r["run_id"] for r in runrows if r["all_pass"] is None],
        "unknown_duration_runs": [r["run_id"] for r in runrows if r["duration_seconds"] is None],
        "retained_measurement_limitations": retained_limitations, "record_discrepancies": record_discrepancies,
        "all_acquired_token_difference": None if len(full) != len(pairs) else paired_tokens(pairs),
        "missingness_formula": {"known_compact_minus_expanded": arm_summary["compact"]["known_token_subtotal"]-arm_summary["expanded"]["known_token_subtotal"],
            "denominator_pairs": len(pairs), "formula": "(known_compact_minus_expanded + unknown_compact_additional - unknown_expanded_additional) / denominator_pairs", "unknown_additional_upper_bound": None},
        "arms": arm_summary, "quality": quality(pairs), "secondary_complete_usage": paired_tokens(full, bootstrap=True),
        "duration_all_acquired": {"difference": distribution(p["difference_duration_seconds"] for p in pairs),
            "role": "Observed paired durations only; missing durations are not imputed and this contrast is not the all-selected mean difference when any are absent",
            "fixed_cohort_missingness_bounds": {
                "assumption": "Every missing duration has the same measurement definition as saved durations and is nonnegative; no missing value is imputed",
                "known_sums_seconds": duration_known_sums, "missing_counts": duration_missing_counts,
                "known_compact_minus_expanded_seconds": duration_known_difference,
                "denominator_pairs": len(pairs),
                "formula": "(known_compact_minus_expanded_seconds + unknown_compact_seconds - unknown_expanded_seconds) / denominator_pairs",
                "mean_difference_lower_bound": duration_known_difference/len(pairs) if not duration_missing_counts["expanded"] else None,
                "mean_difference_upper_bound": duration_known_difference/len(pairs) if not duration_missing_counts["compact"] else None,
                "bound_meaning": "Logical bounds for this fixed cohort under nonnegative missing durations; null bound is unbounded. Not a repeated-execution confidence interval."},
            "measurement": "Runtime network/container setup through request drain and process stop; excludes evaluation, later cleanup, archive, sharing and quota waits"},
        "paired_metric_distributions": {k: distribution(p["difference_"+k] for p in pairs) for k in pair_fields if k != "all_pass"},
        "sensitivity_posthoc": sensitivities,
        "leave_one_complete_pair_out": [{"omitted_pair": p["pair"], "mean_difference": float(np.mean([x["difference_total_tokens"] for x in full if x["pair"] != p["pair"]]))} for p in full],
        "by_utc_date_descriptive": by_date, "spearman_descriptive": correlations,
        "outcome_profiles_posthoc": outcome_profiles,
        "tool_counts_by_arm": {arm: dict(sum((Counter(r["tool_counts"]) for r in behaviorrows if r["arm"] == arm), Counter())) for arm in ARMS},
        "failure_judgements": sum(len(r["failed_requirements"]) for r in runrows),
        "failed_products": sum(r["all_pass"] == 0 for r in runrows),
        "calls": len(callrows), "requirement_rows": len(reqrows), "human_review": dict(Counter(r["human_review"] for r in runrows)),
        "observation_window_utc": [min(r["started_at"] for r in runrows), max(r["ended_at"] for r in runrows)],
        "warnings": ["Reference intervals assume independent, stable pair distributions and are not adjusted for repeated inspection or data-dependent selection. No future sample count is a prerequisite for this cohort description.",
            "Calls and requirements are nested within Runs, not independent experimental samples.",
            "Missing totals are not zero; complete-pair token results describe a subset and cannot identify the all-selected token contrast. More executions do not recover existing missing usage.",
            "Quality equality of observed rates does not establish equivalence or maintenance.",
            "Unknown quality remains unknown: fixed-cohort bounds enumerate its possible binary outcomes; reference confidence envelopes also include repeated-execution uncertainty.",
            "Known raw-token subtotals can differ from normalized partial subtotals; discrepancies are retained. Complete totals require complete reconciled usage.",
            "Stopped unsealed executions retain observed calls, but capture stability is not historical sealing or evidence of complete usage, evaluation or duration.",
            "Cache tokens are part of input and reasoning tokens part of output; no double counting or billing inference.",
            "Read labels are descriptive; bash candidates require command review. Byte exposure is not tokens.",
            "Success-only, time splits, order splits and leave-one-out are post hoc diagnostics; selection on outcomes changes the compared population."]}
    out.mkdir(parents=True, exist_ok=True)
    write(out/"summary.json", summary)
    write(out/"temporal-comparison.json", temporal_comparison(runrows, pairs))
    for name, rows in (("runs", runrows), ("pairs", pairs), ("requirements", reqrows), ("requirements-summary", req_summary), ("calls", callrows), ("behavior", behaviorrows)):
        write(out/(name+".json"), rows)
        table(out/(name+".csv"), rows)
    write(out/"analysis-audit.json", {"checks": dict(checks), "check_count": sum(checks.values()), "issues": [],
          "retained_measurement_limitations": retained_limitations, "record_discrepancies": record_discrepancies,
          "scope": "Read-only saved observation to manifest, normalized usage and adopted evaluation reconciliation; raw SSE verification belongs to the separate extractor",
          "source_hashes": sources, "script_sha256": sha(Path(__file__)),
          "versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}})
    if extracted is not None:
        compare_extracted(extracted.resolve(), out, sha(marker))
    print(json.dumps({"runs": len(runrows), "pairs": len(pairs), "complete_usage_pairs": len(full),
          "quality_difference": summary["quality"]["difference"], "secondary_token_difference": summary["secondary_complete_usage"]["difference"],
          "checks": sum(checks.values()), "output": str(out)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compare-extracted", type=Path, help="Optional independent standard-library extraction directory")
    args = parser.parse_args()
    analyze(args.root, args.out, args.compare_extracted)


if __name__ == "__main__":
    main()
