import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy import stats

from research.catalog_confirmatory import (
    ARMS, COMPACT, DEFAULT_PLAN, REQUIREMENTS, allocation, analyze,
    clopper_pearson, paired_mean, paired_quality_interval, read_json, sha256,
    validate_plan, write_new,
)
from research.catalog_design import binary_cells, mc_summary, quality_power_exact, token_power


def fixture(n=40):
    plan = copy.deepcopy(read_json(DEFAULT_PLAN))
    plan.update(pairs=n, runs_per_condition=n, maximum_runs=2 * n,
                slots=allocation(n, plan["randomization_seed"], plan["attempt_start"]))
    plan["analysis"]["bootstrap_repetitions"] = 100
    observations = {"cohort": plan["cohort"], "launch_receipt": {"test": True}, "runs": []}
    for slot in plan["slots"]:
        total = 1000 + slot["block"] * 100
        if slot["condition"] == COMPACT:
            total //= 2
        observations["runs"].append({
            "case": slot, "run_id": slot["run_id"],
            "row": {"task_id": plan["task"], "attempt": slot["attempt"],
                    "intervention_id": slot["condition"], "run_instance_id": slot["run_id"],
                    "scoring": {"state": "scored", "research_status": "complete", "evaluation_version": "1.2.0",
                                "evaluator_sha256": plan["fixed_conditions"]["evaluator_sha256"]},
                    "verdict": "pass", "artifact": {"state": "fixed"}},
            "initial_input": {"gateway": {"verified": True, "prompt_sha256": plan["fixed_conditions"]["initial_prompt_sha256"][slot["condition"]]},
                              "semantic_match_to_mock": True, "same_files_permissions_ranges": True},
            "requirements": [{"id": key, "judgement": "pass"} for key in REQUIREMENTS],
            "usage_complete": True, "tokens": {"input_tokens": total - 10, "output_tokens": 10,
                                               "total_tokens": total, "known_total_tokens": total},
            "calls": [{"input_tokens": total - 10, "output_tokens": 10,
                       "response_models": [plan["model"]]}],
            "runtime_cleanup": {"confirmed": True}, "browser_cleanup": {"confirmed": True},
        })
    return plan, observations


def fail(observation, key="R-014"):
    observation["row"]["verdict"] = "fail"
    for requirement in observation["requirements"]:
        if requirement["id"] == key:
            requirement["judgement"] = "fail"


class ConfirmatoryTests(unittest.TestCase):
    def test_plan_and_pins_match_accepted_implementation(self):
        plan = read_json(DEFAULT_PLAN)
        validate_plan(plan)
        root = Path(__file__).resolve().parents[2]
        for name, digest in plan["pinned_files"].items():
            self.assertEqual(sha256(root / name), digest, name)
        self.assertEqual(plan["runs_per_condition"], plan["pairs"])

    def test_schedule_is_reproducible_both_orders_and_no_duplicate_slots(self):
        plan = read_json(DEFAULT_PLAN)
        schedule = allocation(plan["pairs"], plan["randomization_seed"], plan["attempt_start"])
        self.assertEqual(schedule, plan["slots"])
        self.assertEqual(len({s["run_id"] for s in schedule}), 640)
        self.assertEqual({s["condition"] for s in schedule if s["position"] == 1}, set(ARMS))

    def test_mean_interval_matches_independent_scipy_api(self):
        c, e = [100, 200, 140, 350, 190], [140, 280, 150, 500, 150]
        result = paired_mean(c, e)
        oracle = stats.ttest_rel(c, e)
        ci = oracle.confidence_interval()
        np.testing.assert_allclose(result["ci95"], [ci.low, ci.high], atol=1e-10)
        self.assertAlmostEqual(result["one_sided_p_reduction"], stats.ttest_rel(c, e, alternative="less").pvalue)

    def test_exact_binomial_matches_independent_scipy_binomtest_api(self):
        for n in (2, 40, 320):
            for k in (0, n // 2, n):
                expected = stats.binomtest(k, n).proportion_ci(confidence_level=0.975, method="exact")
                np.testing.assert_allclose(clopper_pearson(k, n, 0.025), [expected.low, expected.high], atol=1e-10)

    def test_all_pass_and_all_fail_have_nonzero_quality_uncertainty(self):
        for n in (2, 40, 320):
            ci = paired_quality_interval(0, 0, n)
            expected_radius = 1 - 0.0125 ** (1 / n)
            self.assertAlmostEqual(ci[1], expected_radius)
            self.assertLess(ci[0], 0)
            self.assertGreater(ci[1], 0)
        plan, data = fixture()
        result = analyze(plan, data)
        self.assertFalse(result["quality"]["relative_quality_supported"])
        self.assertEqual(result["decision"], "token_reduction_quality_not_supported_or_unresolved")

    def test_low_tokens_failed_quality_is_never_joint_support(self):
        plan, data = fixture()
        for obs in data["runs"]:
            if obs["case"]["condition"] == COMPACT:
                fail(obs)
        result = analyze(plan, data)
        self.assertEqual(result["quality"]["arms"][COMPACT]["confirmed_fail"], 40)
        self.assertEqual(result["descriptive"][COMPACT]["success_only_n_secondary"], 0)
        self.assertEqual(result["decision"], "token_reduction_quality_not_supported_or_unresolved")
        self.assertEqual(result["primary_tokens"]["n_pairs"], 40)

    def test_joint_support_is_relative_only_no_practical_quality_claim(self):
        plan, data = fixture()
        for obs in data["runs"]:
            if obs["case"]["condition"] != COMPACT:
                fail(obs)
        result = analyze(plan, data)
        self.assertEqual(result["decision"], "token_reduction_and_relative_quality_supported")
        self.assertIn("not_authorized", result["practical_efficiency_claim"])

    def test_low_quality_in_both_arms_never_implies_practical_adequacy(self):
        plan, data = fixture()
        for obs in data["runs"]:
            fail(obs)
        result = analyze(plan, data)
        self.assertEqual(result["decision"], "token_reduction_quality_not_supported_or_unresolved")
        self.assertIn("not_established", result["quality"]["practical_adequacy"])

    def test_token_increase_does_not_support_reduction(self):
        plan, data = fixture()
        for obs in data["runs"]:
            if obs["case"]["condition"] == COMPACT:
                total = obs["tokens"]["total_tokens"] * 4
                obs["tokens"].update(input_tokens=total-10, total_tokens=total, known_total_tokens=total)
                obs["calls"][0]["input_tokens"] = total-10
        self.assertEqual(analyze(plan, data)["decision"], "token_reduction_not_supported")

    def test_analysis_has_no_network_or_subprocess_activity(self):
        plan, data = fixture()
        with patch("subprocess.run", side_effect=AssertionError("No subprocess allowed")), \
                patch("socket.socket.connect", side_effect=AssertionError("No network allowed")):
            self.assertEqual(analyze(plan, data)["assigned_runs"], 80)

    def test_nonadopted_evaluation_cannot_pass_from_requirement_rows_alone(self):
        plan, data = fixture()
        data["runs"][0]["row"]["scoring"]["state"] = "evaluator_fault"
        result = analyze(plan, data)
        self.assertEqual(result["decision"], "indeterminate")

    def test_no_fixed_artifact_cannot_pass_from_requirement_rows_alone(self):
        plan, data = fixture()
        data["runs"][0]["row"]["artifact"]["state"] = "not_fixed"
        result = analyze(plan, data)
        self.assertEqual(result["decision"], "indeterminate")
        self.assertIsNone(result["rows"][0]["outcome"])

    def test_auxiliary_partial_reads_are_not_full_source_claims(self):
        plan, data = fixture()
        data["runs"][0]["actions"] = [{"tool": "bash", "inputs": {"command": "head -c 2000 /inputs/catalog-derived/raw-first.txt"},
            "labels": ["file_access_candidate_review_command"], "first_returned_utf8_bytes": 2000,
            "later_exact_retentions": 2, "later_changed_retentions": 1, "returned_bytes_exposure_sum": 6500}]
        aux = analyze(plan, data)["rows"][0]["auxiliary"]
        self.assertEqual(aux["file_access_evidence"][0]["first_returned_utf8_bytes"], 2000)
        self.assertNotIn("catalog_source_return", aux["source_access_labels"])
        self.assertEqual(aux["later_exact_tool_output_retentions"], 2)

    def test_missing_usage_not_zero_and_no_complete_case_primary(self):
        plan, data = fixture()
        data["runs"][0]["tokens"]["total_tokens"] = None
        data["runs"][0]["usage_complete"] = False
        result = analyze(plan, data)
        self.assertIsNone(result["primary_tokens"])
        self.assertEqual(result["complete_pair_tokens_secondary"]["n_pairs"], 39)
        self.assertEqual(result["assigned_runs"], 80)
        self.assertEqual(result["decision"], "indeterminate")

    def test_missing_scheduled_run_stays_in_denominator(self):
        plan, data = fixture()
        data["runs"].pop()
        result = analyze(plan, data)
        self.assertEqual(result["assigned_runs"], 80)
        self.assertIsNone(result["primary_tokens"])
        self.assertEqual(sum(a["unknown_outcome"] for a in result["quality"]["arms"].values()), 1)

    def test_failed_product_with_incomplete_coverage_preserves_both(self):
        plan, data = fixture()
        obs = data["runs"][0]
        fail(obs)
        obs["requirements"].pop()
        obs["row"]["scoring"]["research_status"] = "incomplete"
        result = analyze(plan, data)
        arm = result["quality"]["arms"][obs["case"]["condition"]]
        self.assertEqual(arm["confirmed_fail"], 1)
        self.assertEqual(arm["coverage_incomplete"], 1)
        self.assertEqual(arm["unknown_outcome"], 0)
        self.assertEqual(result["decision"], "indeterminate")

    def test_unknown_quality_envelope_contains_all_possible_completions(self):
        plan, data = fixture(4)
        data["runs"][0]["requirements"] = []
        data["runs"][0]["row"]["scoring"]["research_status"] = "incomplete"
        result = analyze(plan, data)
        interval = result["quality"]["ci95_or_missingness_envelope"]
        for wins, losses in ((0, 0), (0, 1), (1, 0)):
            # Only check the two feasible outcomes for the assigned arm.
            if (data["runs"][0]["case"]["condition"] == COMPACT and wins) or (data["runs"][0]["case"]["condition"] != COMPACT and losses):
                continue
            ci = paired_quality_interval(wins, losses, 4)
            self.assertLessEqual(interval[0], ci[0])
            self.assertGreaterEqual(interval[1], ci[1])

    def test_calls_are_not_runs_and_usage_formats_are_not_exclusions(self):
        plan, data = fixture(2)
        for obs, count in zip(data["runs"], (38, 43, 50, 87)):
            original = obs["calls"][0]
            obs["calls"] = [original] + [{"input_tokens": 0, "output_tokens": 0,
                "response_models": [plan["model"]], "usage_shape": "changed"} for _ in range(count - 1)]
        result = analyze(plan, data)
        self.assertEqual(result["assigned_runs"], 4)
        self.assertEqual(result["n_pairs"], 2)
        self.assertEqual(sum(a["observed_calls"] for a in result["descriptive"].values()), 218)

    def test_budget_stop_with_observed_usage_is_retained(self):
        plan, data = fixture()
        data["runs"][0]["row"]["execution"] = {"state": "budget_exhausted"}
        fail(data["runs"][0])
        self.assertEqual(analyze(plan, data)["primary_tokens"]["n_pairs"], 40)

    def test_unknown_zero_dispatch_is_not_measured_zero(self):
        plan, data = fixture()
        obs = data["runs"][0]
        obs["calls"] = []
        obs["tokens"] = dict(input_tokens=0, output_tokens=0, total_tokens=0)
        self.assertIsNone(analyze(plan, data)["primary_tokens"])
        obs["verified_zero_dispatch"] = True
        self.assertIsNotNone(analyze(plan, data)["primary_tokens"])

    def test_historical_cohort_and_duplicate_run_are_rejected(self):
        plan, data = fixture()
        data["cohort"] = "catalog-technical-pilot-20260920"
        with self.assertRaisesRegex(ValueError, "cohort"):
            analyze(plan, data)
        data["cohort"] = plan["cohort"]
        data["runs"].append(data["runs"][0])
        with self.assertRaisesRegex(ValueError, "duplicate Run"):
            analyze(plan, data)

    def test_identity_fault_retains_attempt_and_blocks_inference(self):
        plan, data = fixture()
        data["runs"][0]["calls"][0]["response_models"] = ["wrong-model"]
        result = analyze(plan, data)
        self.assertEqual(result["assigned_runs"], 80)
        self.assertEqual(result["decision"], "indeterminate")

    def test_cleanup_fault_does_not_erase_quality(self):
        plan, data = fixture()
        data["runs"][0]["browser_cleanup"]["confirmed"] = False
        result = analyze(plan, data)
        self.assertEqual(result["quality"]["arms"][COMPACT]["pass"], 40)
        self.assertEqual(result["decision"], "indeterminate")

    def test_success_only_selection_cannot_replace_all_run_tokens(self):
        plan, data = fixture()
        failed = next(obs for obs in data["runs"] if obs["case"]["condition"] == COMPACT)
        fail(failed)
        failed["tokens"].update(input_tokens=1000000, output_tokens=10, total_tokens=1000010, known_total_tokens=1000010)
        failed["calls"][0].update(input_tokens=1000000, output_tokens=10)
        result = analyze(plan, data)
        self.assertGreater(result["primary_tokens"]["mean_compact"], result["descriptive"][COMPACT]["success_only_mean_total_secondary"])
        self.assertEqual(result["primary_tokens"]["n_pairs"], 40)

    def test_degenerate_token_variance_does_not_make_exact_claim(self):
        self.assertIsNone(paired_mean([1, 2, 3], [2, 3, 4])["ci95"])

    def test_scenario_power_and_probability_validation(self):
        self.assertAlmostEqual(token_power(320, 0, 1, 0), 0.025, places=8)
        self.assertGreater(token_power(320, 0.2, 1, 0.25), 0.8)
        self.assertAlmostEqual(sum(binary_cells(0.8, 0.8, 0.5)), 1)
        with self.assertRaises(ValueError):
            binary_cells(0.1, 0.9, 1)

    def test_exact_quality_power_matches_independent_multinomial_enumeration(self):
        n, pc, pe, rho = 10, 0.95, 0.6, 0
        _, qw, ql, _ = binary_cells(pc, pe, rho)
        expected = 0.0
        for wins in range(n + 1):
            for losses in range(n + 1 - wins):
                if paired_quality_interval(wins, losses, n)[0] > 0:
                    expected += stats.multinomial.pmf([wins, losses, n - wins - losses], n, [qw, ql, 1 - qw - ql])
        self.assertAlmostEqual(quality_power_exact(n, pc, pe, rho), expected, places=12)

    def test_monte_carlo_zero_events_do_not_imply_zero_uncertainty(self):
        self.assertGreater(mc_summary([False] * 100)["mc_ci95_wilson"][1], 0)
        self.assertLess(mc_summary([True] * 100)["mc_ci95_wilson"][0], 1)

    def test_outputs_do_not_overwrite_prior_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            write_new(path, {"x": None})
            with self.assertRaises(FileExistsError):
                write_new(path, {"x": 0})


if __name__ == "__main__":
    unittest.main()
