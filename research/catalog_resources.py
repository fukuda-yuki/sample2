"""Read-only resource inventory and small deterministic reuse of v1 calculations.

Never starts a model, evaluator, browser, Docker job or new simulation. Inventory
uses file sizes and saved timestamps, not product re-evaluation. Outputs are new.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from research.catalog_confirmatory import read_json, sha256, write_new


def tree_size(path):
    path = Path(path).resolve()
    native = "\\\\?\\" + str(path) if os.name == "nt" else str(path)
    total = count = 0
    errors = []
    if not path.exists():
        return {"bytes": None, "files": None, "errors": ["missing_directory"]}
    def failed(error):
        errors.append(type(error).__name__)
    for directory, _, files in os.walk(native, onerror=failed, followlinks=False):
        for name in files:
            try:
                entry = Path(directory) / name
                if entry.is_symlink():
                    errors.append("symlink_not_counted")
                    continue
                total += entry.stat().st_size
                count += 1
            except OSError as exc:
                failed(exc)
    return {"bytes": total if not errors else None, "known_bytes": total,
            "files": count, "errors": errors}


def inventory(repo):
    repo = Path(repo).resolve()
    cohort = repo / "runs/catalog-technical-pilot-20260920"
    pilot = []
    for directory in sorted(cohort.glob("MS1-*")):
        manifest = directory / "manifest.json"
        index = directory / "evaluations/index.jsonl"
        m = read_json(manifest)
        evaluations = []
        for line in index.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            saved = directory / record["directory"]
            starts = []
            references = {}
            for relative in ("evaluation.json", "http-only/evaluation.json"):
                path = saved / relative
                if path.is_file():
                    e = read_json(path)
                    if e.get("startedAt"):
                        starts.append(datetime.fromisoformat(e["startedAt"]))
                    references[path.relative_to(repo).as_posix()] = sha256(path)
            end = datetime.fromisoformat(record["recorded_at"])
            evaluations.append({"sequence": record["sequence"], "adopted": record["adopted"],
                "state": record["scoring_state"], "sources": references,
                "observable_scoring_span_seconds": (end - min(starts)).total_seconds() if starts else None})
        pilot.append({"run_id": directory.name, "storage": tree_size(directory),
            "runtime_seconds": m["duration_seconds"], "evaluations": evaluations,
            "manifest_sha256": sha256(manifest), "evaluation_index_sha256": sha256(index)})
    disk = shutil.disk_usage(repo)
    return {"schema_version": 1, "kind": "read_only_resource_snapshot",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_called": False, "evaluator_called": False,
        "disk": {"volume": repo.anchor, "total_bytes": disk.total,
                 "used_bytes": disk.used, "free_bytes": disk.free},
        "storage": {name: tree_size(repo / name) for name in ("runs", "artifacts")},
        "pilot_cohort_storage": tree_size(cohort), "pilot": pilot,
        "storage_definition": "Logical bytes of currently retained regular files; not allocated disk blocks; cohort includes saved archives and recovery copies. No cleanup.",
        "scoring_time_definition": "Earliest saved HTTP/composed evaluator startedAt through evaluations/index.jsonl recorded_at, per attempt. Includes observed browser/cleanup span; excludes earlier preparation and later archival. Recovery wait between attempts is excluded.",
        "available_execution_hours": None, "reserved_disk_bytes": None,
        "account_remaining_usage": None, "account_window_reset_times": None,
        "model_run_capacity": None}


def compare(design, resources, account_usage=None):
    """Only select saved rows and apply algebra; no sampling or power rerun."""
    result = []
    pilot = resources["pilot"]
    adopted = [e["observable_scoring_span_seconds"] for p in pilot for e in p["evaluations"] if e["adopted"]]
    measured = bool(adopted) and all(v is not None for v in adopted)
    storage = resources["pilot_cohort_storage"]["bytes"]
    for old in design["resources"]:
        n, runs = old["pairs"], old["runs"]
        token = next(t for t in design["token_parametric_simulations"] if
            t["n"] == n and t["reduction"] == 0.2 and t["base_cv"] == 1 and
            t["base_token_rho"] == 0.25 and t["tail_model"] == "lognormal")
        quality = next(q for q in design["quality_multinomial_simulations"] if
            q["n"] == n and q["p_compact"] == q["p_expanded"] == 0.8 and q["binary_rho"] == 0)
        power = next(q for q in design["quality_superiority_size_grid"] if
            q["p_compact"] == 0.85 and q["p_expanded"] == 0.8 and q["binary_rho"] == 0)["exact_power_by_n"][str(n)]
        result.append({**old, "token_reduction_power_scenario": token["reduction_support"],
            "token_mean_interval_half_width_reference_tokens": token["mean_ci_half_width_over_expanded_mean"] * 3000000,
            "quality_mean_half_width_pp_scenario": quality["mean_ci_half_width"] * 100,
            "quality_p90_half_width_pp_scenario": quality["p90_ci_half_width"] * 100,
            "quality_superiority_power_85_vs_80_scenario": power,
            "joint_support_probability_upper_bound_85_vs_80": power,
            "joint_support_upper_bound_reason": "Joint support is a subset of quality superiority; no token-quality independence assumption.",
            "missingness_scenarios": [{"per_run_unresolved_endpoint_probability": q,
                "probability_all_endpoint_values_known": (1 - q) ** runs,
                "expected_unresolved_endpoint_values": runs * q} for q in (0, 0.001, 0.005)],
            "pilot_retained_cohort_scaled_gib_reference_only": runs * storage / len(pilot) / 2**30 if storage is not None and pilot else None,
            "pilot_adopted_scoring_span_hours_reference_only": runs * sum(adopted) / len(adopted) / 3600 if measured else None,
            "pilot_token_mix_quota_dollar_scenario_range": [
                runs / 4 * (12555186 * 0.003 + 168718 * 0.60) / 1000000,
                runs / 4 * (12555186 * 0.30 + 168718 * 1.20) / 1000000],
            "capacity_confirmed": False})
    return {"schema_version": 2, "kind": "resource_and_information_comparison_not_acquisition",
        "new_simulation_repetitions": 0, "model_called": False, "evaluator_called": False,
        "selected_pairs": None, "recommendation": "Resource-bounded fixed paired estimation; defer allocation until model-specific feasible capacity, storage reserve and available hours are documented. Do not adopt 320 by default.",
        "account_usage_readback": account_usage,
        "quota_scenario_definition": "Scale the saved four-Run input/output totals. Low endpoint assumes all input cache hits at off-peak rates; high endpoint assumes no cache hits at peak rates. Rate snapshot: https://opencode.ai/docs/go/ on 2026-09-21. These are quota-dollar scenarios, not actual charges, observed cache costs, spending caps or an account-percent-to-Run conversion. No overage enabled.",
        "missingness_interpretation": "Independent per-Run residual unknown ENDPOINT values, after recovery: hypothetical, not observed failure rates. An incomplete inspection with a verified failure is not an unknown all-29 outcome. No multiplication of availability and power without assumptions about their dependence.",
        "candidates": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inventory", "compare"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--design", type=Path, default=Path(__file__).parent / "design-results/catalog-confirmatory-v1.json")
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--usage", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "inventory":
        result = inventory(args.repo)
    else:
        if args.resources is None:
            parser.error("compare requires --resources")
        result = compare(read_json(args.design), read_json(args.resources), read_json(args.usage) if args.usage else None)
        result["source_hashes"] = {str(args.design): sha256(args.design), str(args.resources): sha256(args.resources)}
        if args.usage:
            result["source_hashes"][str(args.usage)] = sha256(args.usage)
    write_new(args.out, result)


if __name__ == "__main__":
    main()
