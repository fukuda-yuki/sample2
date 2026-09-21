"""Consequential resource/missingness calculations, with preserved source inputs."""
import math
import unittest

from research.catalog_confirmatory import REPO, read_json
from research.catalog_resources import compare


class ResourceTests(unittest.TestCase):
    def test_reuse_preserves_v1_values_and_distinguishes_joint_power(self):
        old = read_json(REPO / "research/design-results/catalog-confirmatory-v1.json")
        inventory = {"pilot": [], "pilot_cohort_storage": {"bytes": None}}
        result = compare(old, inventory)
        row = next(r for r in result["candidates"] if r["pairs"] == 320)
        self.assertEqual(row["pilot_mean_scaled_tokens_reference_only"], 2035824640)
        self.assertAlmostEqual(row["quality_superiority_power_85_vs_80_scenario"], 0.0847769, places=7)
        self.assertLess(row["joint_support_probability_upper_bound_85_vs_80"], 0.085)
        self.assertGreater(row["token_reduction_power_scenario"]["estimate"], 0.90)
        self.assertIsNone(row["pilot_adopted_scoring_span_hours_reference_only"])
        self.assertIsNone(row["pilot_retained_cohort_scaled_gib_reference_only"])
        self.assertIsNone(result["selected_pairs"])
        self.assertEqual(result["new_simulation_repetitions"], 0)
        for item in row["missingness_scenarios"]:
            q = item["per_run_unresolved_endpoint_probability"]
            self.assertAlmostEqual(item["probability_all_endpoint_values_known"], math.exp(640 * math.log1p(-q)))

    def test_scoring_uses_adopted_spans_and_retains_whole_cohort_storage(self):
        old = read_json(REPO / "research/design-results/catalog-confirmatory-v1.json")
        inventory = {"pilot": [{"evaluations": [
            {"adopted": True, "observable_scoring_span_seconds": 30},
            {"adopted": False, "observable_scoring_span_seconds": 100}]}] * 4,
            "pilot_cohort_storage": {"bytes": 2**30}}
        result = compare(old, inventory)
        row = result["candidates"][0]
        self.assertAlmostEqual(row["pilot_adopted_scoring_span_hours_reference_only"], 80 * 30 / 3600)
        self.assertEqual(row["pilot_retained_cohort_scaled_gib_reference_only"], 20)
        low, high = row["pilot_token_mix_quota_dollar_scenario_range"]
        self.assertLess(low, high)
        self.assertFalse(row["capacity_confirmed"])
