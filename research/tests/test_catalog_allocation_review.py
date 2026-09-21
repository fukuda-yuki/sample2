"""Resource arithmetic and SQLite evidence must not invent capacity or missing data."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from research.catalog_allocation_review import REPO, inspect_run, quota_reference, sha256, write_new
from outer.harness.monitor import payload


class AllocationReviewTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / "RUN-A"
        (root / "usage").mkdir(parents=True)
        (root / "telemetry").mkdir()
        manifest = {"run_instance_id": "instance-A", "duration_seconds": 12}
        event = {"request_id": "request-A", "model_id": "test-model", "status": "completed",
            "started_at": "2026-09-21T00:00:00+00:00", "ended_at": "2026-09-21T00:00:01+00:00",
            "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 80}}
        otlp = payload([event], root.name, manifest)
        usage = {"run_id": root.name, "usage_complete": True, "observed_call_count": 1}
        for key, value in event["usage"].items():
            usage[key] = usage["observed_" + key] = value
        write_new(root / "manifest.json", manifest)
        write_new(root / "usage/normalized.json", usage)
        write_new(root / "telemetry/gateway.otlp.json", otlp)
        write_new(root / "telemetry-link.json", {"verified": True, "request_count": 1})
        with closing(sqlite3.connect(root / "telemetry/monitor.db")) as db, db:
            db.execute("CREATE TABLE raw_records (id INTEGER, payload_json TEXT)")
            db.execute("INSERT INTO raw_records VALUES (1, ?)", (json.dumps(otlp),))
        return root, usage, otlp

    def test_cache_is_subtracted_from_total_input(self):
        # 1M input with 0.8M hits costs 0.03 + 0.0024; 0.1M output costs 0.06.
        result = quota_reference(1000000, 100000, 800000)
        self.assertAlmostEqual(result["off_peak"], 0.0924)
        self.assertAlmostEqual(result["peak"], 0.1848)

    def test_unknown_usage_never_becomes_zero_cost(self):
        for values in ((100, 20, None), (None, 20, 0), (100, None, 0)):
            self.assertIsNone(quota_reference(*values))

    def test_impossible_usage_is_rejected(self):
        for values in ((100, 20, 101), (-1, 20, 0), (True, 20, 0), (100, 2.5, 0)):
            with self.assertRaises(ValueError):
                quota_reference(*values)

    def test_sqlite_readback_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = self.fixture(tmp)
            before = sha256(root / "telemetry/monitor.db")
            result = inspect_run(root)
            self.assertTrue(result["exact_otlp_readback"])
            self.assertEqual(result["request_spans"], 1)
            self.assertEqual(result["cache_read_tokens"], 80)
            self.assertEqual(before, sha256(root / "telemetry/monitor.db"))
            self.assertFalse(result["span_events_present"])

    def test_changed_database_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = self.fixture(tmp)
            with closing(sqlite3.connect(root / "telemetry/monitor.db")) as db, db:
                db.execute("UPDATE raw_records SET payload_json = '{}' WHERE id = 1")
            with self.assertRaisesRegex(ValueError, "readback"):
                inspect_run(root)

    def test_unknown_cache_remains_unknown_after_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, usage, otlp = self.fixture(tmp)
            usage["cache_read_tokens"] = usage["observed_cache_read_tokens"] = None
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            spans[0]["attributes"] = [a for a in spans[0]["attributes"] if a["key"] != "sample2.cache_read_tokens"]
            (root / "usage/normalized.json").write_text(json.dumps(usage), encoding="utf-8")
            (root / "telemetry/gateway.otlp.json").write_text(json.dumps(otlp), encoding="utf-8")
            with closing(sqlite3.connect(root / "telemetry/monitor.db")) as db, db:
                db.execute("UPDATE raw_records SET payload_json = ?", (json.dumps(otlp),))
            result = inspect_run(root)
            self.assertIsNone(result["quota_dollars_reference"])

    def test_duplicate_request_spans_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, otlp = self.fixture(tmp)
            spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
            spans.append(spans[0])
            (root / "telemetry/gateway.otlp.json").write_text(json.dumps(otlp), encoding="utf-8")
            with closing(sqlite3.connect(root / "telemetry/monitor.db")) as db, db:
                db.execute("UPDATE raw_records SET payload_json = ?", (json.dumps(otlp),))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                inspect_run(root)

    def test_uncheckpointed_database_is_not_opened_or_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = self.fixture(tmp)
            sidecar = root / "telemetry/monitor.db-wal"
            sidecar.write_bytes(b"uncheckpointed fixture")
            with self.assertRaisesRegex(ValueError, "sidecar"):
                inspect_run(root)
            self.assertEqual(sidecar.read_bytes(), b"uncheckpointed fixture")

    def test_existing_evidence_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            write_new(out, {"original": True})
            before = out.read_bytes()
            with self.assertRaises(FileExistsError):
                write_new(out, {"original": False})
            self.assertEqual(out.read_bytes(), before)

    def test_sql_projects_identity_usage_and_retains_raw_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, otlp = self.fixture(tmp)
            sql = (REPO / "research/sql/catalog_otel_requests.sql").read_text(encoding="utf-8")
            with closing(sqlite3.connect((root / "telemetry/monitor.db").as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                db.row_factory = sqlite3.Row
                rows = [dict(r) for r in db.execute(sql)]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual((row["run_id"], row["run_instance_id"], row["request_id"]),
                             ("RUN-A", "instance-A", "request-A"))
            self.assertEqual((row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]), (100, 20, 80))
            self.assertIsNone(row["cache_write_tokens"])
            self.assertEqual(json.loads(row["span_json"]), otlp["resourceSpans"][0]["scopeSpans"][0]["spans"][0])


if __name__ == "__main__":
    unittest.main()
