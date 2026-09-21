"""Offline resource references and read-only pilot OTLP/SQLite inspection.

Does not acquire, evaluate, import telemetry, build archives, upload or delete.
The cache-mix cost is a rate scenario using saved usage, never a bill or a cap.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3


REPO = Path(__file__).resolve().parents[1]
PILOT = "runs/catalog-technical-pilot-20260920"
PILOT_PLAN = "research/protocols/ms1-catalog-technical-pilot-20260920.json"
COMPARISON = "research/design-results/catalog-comparison-v2.json"
RATE_SOURCE = "https://opencode.ai/docs/ja/go/#利用制限"
RATES_OFF_PEAK = {"input": "0.15", "output": "0.60", "cache_read": "0.003"}
FIELDS = {"input_tokens": "gen_ai.usage.input_tokens",
          "output_tokens": "gen_ai.usage.output_tokens",
          "cache_read_tokens": "sample2.cache_read_tokens"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def quota_reference(input_tokens, output_tokens, cache_read_tokens):
    """Cached reads are a subset of total input; do not charge them twice."""
    for value in (input_tokens, output_tokens, cache_read_tokens):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Usage must be nonnegative integers or unknown")
    if input_tokens is not None and cache_read_tokens is not None and cache_read_tokens > input_tokens:
        raise ValueError("Cache reads exceed total input")
    if None in (input_tokens, output_tokens, cache_read_tokens):
        return None
    off_peak = ((input_tokens - cache_read_tokens) * Decimal(RATES_OFF_PEAK["input"])
                + output_tokens * Decimal(RATES_OFF_PEAK["output"])
                + cache_read_tokens * Decimal(RATES_OFF_PEAK["cache_read"])) / 1000000
    return {"off_peak": float(off_peak), "peak": float(off_peak * 2)}


def attributes(items):
    values = {}
    for item in items:
        name, value = item["key"], item["value"]
        if name in values:
            raise ValueError("Duplicate OTLP attribute")
        values[name] = int(value["intValue"]) if "intValue" in value else value.get("stringValue")
    return values


def inspect_run(root):
    root = Path(root).resolve()
    paths = [root / name for name in ("manifest.json", "usage/normalized.json",
             "telemetry/gateway.otlp.json", "telemetry/monitor.db", "telemetry-link.json")]
    before = {p.relative_to(root).as_posix(): sha256(p) for p in paths}
    manifest, usage, otlp, receipt = (read(root / name) for name in
        ("manifest.json", "usage/normalized.json", "telemetry/gateway.otlp.json", "telemetry-link.json"))
    if usage.get("run_id") != root.name or receipt.get("verified") is not True:
        raise ValueError("Pilot usage or telemetry identity is not verified")
    database = root / "telemetry/monitor.db"
    # Sealed pilot DBs must be self-contained; never checkpoint an original DB.
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("SQLite sidecar present; a separate consistent snapshot is required")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        records = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM raw_records ORDER BY id")]
    if integrity != ["ok"] or records != [otlp]:
        raise ValueError("SQLite integrity or exact saved OTLP readback failed")
    spans = []
    for resource in otlp["resourceSpans"]:
        identity = attributes(resource["resource"]["attributes"])
        if (identity.get("run.id") != root.name or not manifest.get("run_instance_id")
                or identity.get("sample2.run_instance_id") != manifest["run_instance_id"]):
            raise ValueError("OTLP Run identity differs from the manifest")
        for scope in resource["scopeSpans"]:
            spans.extend(scope["spans"])
    values = [attributes(s["attributes"]) for s in spans]
    ids = [v.get("sample2.request.id") for v in values]
    if not ids or any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate OTLP request identity")
    if len(ids) != usage["observed_call_count"] or len(ids) != receipt["request_count"]:
        raise ValueError("OTLP request count differs from saved usage/receipt")
    totals = {}
    for field, key in FIELDS.items():
        reported = [v.get(key) for v in values]
        if any(v is not None and (type(v) is not int or v < 0) for v in reported):
            raise ValueError("Invalid OTLP usage value")
        observed = sum(v for v in reported if v is not None) if any(v is not None for v in reported) else None
        total = observed if all(v is not None for v in reported) and usage["usage_complete"] else None
        if total != usage.get(field) or observed != usage.get("observed_" + field):
            raise ValueError("OTLP usage differs from saved normalization")
        totals[field] = total
    scenario = quota_reference(**totals)
    after = {p.relative_to(root).as_posix(): sha256(p) for p in paths}
    if before != after:
        raise ValueError("Source changed during read-only inspection")
    return {"run_id": root.name, "source_hashes": before, "source_unchanged": True,
            "sqlite_integrity": "ok", "exact_otlp_readback": True, "raw_records": len(records),
            "request_spans": len(spans), "database_bytes": database.stat().st_size,
            "span_events_present": any(s.get("events") for s in spans),
            "span_attribute_keys": sorted({k for v in values for k in v}),
            "usage_complete": usage["usage_complete"], **totals,
            "cache_write_tokens": usage.get("cache_write_tokens"),
            "runtime_seconds": manifest["duration_seconds"], "quota_dollars_reference": scenario}


def review(repo):
    repo = Path(repo).resolve()
    plan = read(repo / PILOT_PLAN)
    expected = [slot["run_id"] for slot in plan["slots"]]
    if len(expected) != 4 or len(set(expected)) != 4:
        raise ValueError("Expected the accepted four-Run technical pilot")
    runs = [inspect_run(repo / PILOT / name) for name in expected]
    totals = {key: sum(r[key] for r in runs) if all(r[key] is not None for r in runs) else None
              for key in FIELDS}
    cost = quota_reference(**totals)
    comparison = read(repo / COMPARISON)
    disk = shutil.disk_usage(repo)
    rows = []
    for candidate in comparison["candidates"]:
        scale = candidate["runs"] / len(runs)
        reference = ({k: v * scale for k, v in cost.items()} if cost else None)
        rows.append({"pairs": candidate["pairs"], "runs": candidate["runs"],
            "pilot_cache_mix_quota_dollars_reference": reference,
            "pilot_runtime_hours_reference": candidate["pilot_mean_scaled_runtime_hours_reference_only"],
            "pilot_adopted_scoring_hours_reference": candidate["pilot_adopted_scoring_span_hours_reference_only"],
            "runtime_budget_hours": candidate["maximum_runtime_budget_hours"],
            "retained_gib_reference": candidate["pilot_retained_cohort_scaled_gib_reference_only"],
            "sqlite_mib_reference": sum(r["database_bytes"] for r in runs) * scale / 2**20,
            "token_reduction_support_probability_scenario": candidate["token_reduction_power_scenario"]["estimate"],
            "quality_interval_mean_half_width_pp_scenario": candidate["quality_mean_half_width_pp_scenario"],
            "capacity_confirmed": False})
    return {"schema_version": 1, "kind": "allocation_and_sharing_review_not_acquisition",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_called": False, "evaluator_called": False, "archives_created": False,
        "telemetry_imported": False, "uploaded": False,
        "source_hashes": {p: sha256(repo / p) for p in (PILOT_PLAN, COMPARISON)},
        "pilot_root": PILOT, "runs": runs, "totals": totals,
        "cache_read_fraction_of_input": totals["cache_read_tokens"] / totals["input_tokens"]
            if totals["input_tokens"] and totals["cache_read_tokens"] is not None else None,
        "quota_dollars_four_run_reference": cost,
        "pricing": {"source": RATE_SOURCE, "rate_snapshot_date": "2026-09-21",
            "off_peak_per_million": RATES_OFF_PEAK, "peak_multiplier": 2,
            "interpretation": "Saved normalized cache mix with the reviewed rates; not actual billed cost, future capacity, a spending cap or a confidence interval. Missing optional cache-write usage remains unknown. Primary scientific tokens remain unweighted input plus output."},
        "verification_scope": "SQLite integrity, exact saved gateway OTLP payload, identities/counts, and token reconciliation against saved normalization. No reparse of original provider requests/SSE; no evaluation or quality rejudgment.",
        "telemetry_scope": "Gateway request spans in SQLite; prompt/response bodies, tool actions, products and evaluation evidence remain separate originals. No native OpenCode OTLP or span event coverage claimed.",
        "current_disk_free_bytes": disk.free, "candidates": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    write_new(args.out, review(args.repo))


if __name__ == "__main__":
    main()
