import unittest

from v41flash_eval.cases import BenchmarkCase, BenchmarkSuite
from v41flash_eval.client import ChatCompletion, ClientError, Usage
from v41flash_eval.report import (
    compare_results,
    comparison_markdown,
    generate_report,
    report_markdown,
)
from v41flash_eval.runner import run_suite


class StubClient:
    model = "candidate-model"

    def complete(self, messages, *, parameters=None, stream=False):
        return ChatCompletion(
            content="yes",
            finish_reason="stop",
            usage=Usage(4, 1, 5),
            latency_ms=125.0,
            ttft_ms=25.0 if stream else None,
            response_id="stub-1",
            model=self.model,
            answer_ttft_ms=30.0 if stream else None,
        )


class ErrorClient:
    model = "broken-model"

    def complete(self, messages, *, parameters=None, stream=False):
        raise ClientError("offline", elapsed_ms=12.5)


def suite() -> BenchmarkSuite:
    return BenchmarkSuite(
        name="suite",
        defaults={"temperature": 0},
        cases=(
            BenchmarkCase(
                id="answer",
                messages=({"role": "user", "content": "Respond yes"},),
                expect={"type": "exact", "value": "yes"},
                parameters={"max_tokens": 3},
            ),
        ),
    )


def result_record(
    *,
    requested_model: str,
    served_model: str,
    endpoint_host: str,
    suite_sha256: str,
    passed: bool,
    temperature: float = 0,
    answer_ttft_ms: float = 40.0,
    case_id: str = "answer",
) -> dict:
    return {
        "suite": "suite",
        "suite_sha256": suite_sha256,
        "case_id": case_id,
        "model": requested_model,
        "endpoint_host": endpoint_host,
        "generation_parameters": {
            "model": requested_model,
            "stream": True,
            "temperature": temperature,
        },
        "response": {"model": served_model},
        "metrics": {
            "latency_ms": 100,
            "ttft_ms": 20,
            "answer_ttft_ms": answer_ttft_ms,
            "total_tokens": 5,
        },
        "score": {"passed": passed},
        "error": None,
    }


class RunnerAndReportTests(unittest.TestCase):
    def test_runner_emits_deterministic_structured_record(self) -> None:
        records = list(
            run_suite(
                suite(),
                StubClient(),
                stream=True,
                repeat=2,
                parameter_overrides={"seed": 1},
                run_id="fixed-run",
                suite_sha256="abc123",
                deployment_metadata={"provider": "stub", "hardware": "cpu"},
                framework_revision="deadbeef",
                timestamp=lambda: "2026-09-10T00:00:00Z",
            )
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["schema_version"], "v41-flashlab.result.v1")
        self.assertEqual(records[0]["framework_version"], "0.1.0")
        self.assertEqual(records[0]["framework_revision"], "deadbeef")
        self.assertEqual(records[0]["run_id"], "fixed-run")
        self.assertEqual(records[0]["suite_sha256"], "abc123")
        self.assertEqual(records[0]["suite_version"], None)
        self.assertIsNone(records[0]["endpoint_host"])
        self.assertIsNone(records[0]["endpoint"])
        self.assertEqual(records[0]["deployment"]["provider"], "stub")
        self.assertEqual(records[0]["finished_at"], "2026-09-10T00:00:00Z")
        self.assertEqual(
            records[0]["generation_parameters"]["model"], "candidate-model"
        )
        self.assertTrue(records[0]["generation_parameters"]["stream"])
        self.assertEqual(records[0]["request"]["parameters"]["seed"], 1)
        self.assertEqual(records[0]["metrics"]["ttft_ms"], 25.0)
        self.assertEqual(records[0]["metrics"]["answer_ttft_ms"], 30.0)
        self.assertIn("usage_details", records[0]["metrics"])
        self.assertIn("reasoning_content", records[0]["response"])
        self.assertTrue(records[0]["score"]["passed"])
        self.assertEqual(records[1]["attempt"], 2)

    def test_runner_turns_client_exception_into_a_record(self) -> None:
        record = next(
            run_suite(
                suite(),
                ErrorClient(),
                run_id="fixed-run",
                timestamp=lambda: "now",
            )
        )
        self.assertEqual(record["error"]["type"], "ClientError")
        self.assertEqual(record["metrics"]["latency_ms"], 12.5)
        self.assertIsNone(record["response"])

    def test_report_and_comparison(self) -> None:
        baseline = list(
            run_suite(suite(), ErrorClient(), run_id="base", timestamp=lambda: "now")
        )
        candidate = list(
            run_suite(
                suite(), StubClient(), run_id="candidate", timestamp=lambda: "now"
            )
        )
        report = generate_report(candidate)
        comparison = compare_results(baseline, candidate)

        self.assertEqual(report["summary"]["pass_rate"], 1.0)
        self.assertEqual(report["run_manifest"]["run_ids"], ["candidate"])
        self.assertEqual(report["summary"]["latency_ms"]["mean"], 125.0)
        self.assertEqual(report["summary"]["tokens"]["total_tokens"]["sum"], 5)
        self.assertEqual(report["tracks"]["uncategorized"]["counts"]["records"], 1)
        self.assertEqual(report["cases"]["suite/answer"]["pass_rate"], 1.0)
        self.assertEqual(comparison["delta"]["error_rate"], -1.0)
        self.assertEqual(comparison["cases"][0]["change"], "improved")
        warning_codes = {
            warning["code"] for warning in comparison["comparability"]["warnings"]
        }
        self.assertTrue(comparison["comparability"]["comparable"])
        self.assertIn("missing_suite_sha256", warning_codes)

    def test_unscored_records_do_not_dilute_pass_rate(self) -> None:
        unscored_suite = BenchmarkSuite(
            name="suite",
            cases=(
                BenchmarkCase(
                    id="observation",
                    messages=({"role": "user", "content": "say anything"},),
                ),
            ),
        )
        records = list(
            run_suite(
                unscored_suite,
                StubClient(),
                run_id="unscored",
                timestamp=lambda: "now",
            )
        )
        summary = generate_report(records)["summary"]
        self.assertEqual(summary["counts"]["scored"], 0)
        self.assertIsNone(summary["pass_rate"])

    def test_request_can_be_omitted_without_losing_generation_parameters(self) -> None:
        record = next(
            run_suite(
                suite(),
                StubClient(),
                include_request=False,
                run_id="private",
                timestamp=lambda: "now",
            )
        )
        self.assertNotIn("request", record)
        self.assertEqual(record["generation_parameters"]["temperature"], 0)
        self.assertEqual(record["generation_parameters"]["max_tokens"], 3)

    def test_comparison_preserves_manifests_and_warns_on_deployment_drift(
        self,
    ) -> None:
        baseline = [
            result_record(
                requested_model="baseline-requested",
                served_model="baseline-served",
                endpoint_host="baseline.example",
                suite_sha256="same-sha",
                passed=False,
                answer_ttft_ms=40,
            )
        ]
        candidate = [
            result_record(
                requested_model="candidate-requested",
                served_model="candidate-served",
                endpoint_host="candidate.example",
                suite_sha256="same-sha",
                passed=True,
                temperature=0.2,
                answer_ttft_ms=25,
            )
        ]

        comparison = compare_results(baseline, candidate)

        comparability = comparison["comparability"]
        self.assertTrue(comparability["comparable"])
        self.assertEqual(comparability["status"], "comparable_with_warnings")
        warning_codes = {warning["code"] for warning in comparability["warnings"]}
        self.assertEqual(
            warning_codes,
            {
                "requested_model_difference",
                "served_model_difference",
                "endpoint_host_difference",
                "generation_parameters_difference",
            },
        )
        baseline_manifest = comparability["manifests"]["baseline"]
        self.assertEqual(baseline_manifest["requested_models"], ["baseline-requested"])
        self.assertEqual(baseline_manifest["served_models"], ["baseline-served"])
        self.assertEqual(baseline_manifest["endpoint_hosts"], ["baseline.example"])
        self.assertEqual(baseline_manifest["suite_hashes"], {"suite": ["same-sha"]})
        self.assertEqual(
            baseline_manifest["generation_parameters"][0]["temperature"], 0
        )
        self.assertEqual(comparison["delta"]["pass_rate"], 1.0)
        self.assertEqual(comparison["delta"]["answer_ttft_mean_ms"], -15.0)

        markdown = comparison_markdown(comparison)
        self.assertIn("## Comparability", markdown)
        self.assertIn("`comparable_with_warnings`", markdown)
        self.assertIn("## Deployment manifests", markdown)
        self.assertIn('"baseline-requested"', markdown)

    def test_suite_revision_mismatch_suppresses_aggregate_and_unpairs_cases(
        self,
    ) -> None:
        baseline = [
            result_record(
                requested_model="model",
                served_model="model",
                endpoint_host="api.example",
                suite_sha256="old-sha",
                passed=False,
            )
        ]
        candidate = [
            result_record(
                requested_model="model",
                served_model="model",
                endpoint_host="api.example",
                suite_sha256="new-sha",
                passed=True,
            )
        ]

        comparison = compare_results(baseline, candidate)

        comparability = comparison["comparability"]
        self.assertFalse(comparability["comparable"])
        self.assertEqual(comparability["status"], "not_comparable")
        self.assertEqual(
            [issue["code"] for issue in comparability["issues"]],
            ["suite_sha256_mismatch", "no_matched_cases"],
        )
        self.assertTrue(all(value is None for value in comparison["delta"].values()))
        self.assertEqual(
            [case["change"] for case in comparison["cases"]],
            ["removed", "added"],
        )
        self.assertEqual(comparison["cases"][0]["baseline_suite_hashes"], ["old-sha"])
        self.assertEqual(comparison["cases"][1]["candidate_suite_hashes"], ["new-sha"])
        self.assertNotIn("improved", {case["change"] for case in comparison["cases"]})

    def test_answer_ttft_is_reported_separately(self) -> None:
        report = generate_report(
            [
                result_record(
                    requested_model="model",
                    served_model="model",
                    endpoint_host="api.example",
                    suite_sha256="sha",
                    passed=True,
                    answer_ttft_ms=75,
                )
            ]
        )

        self.assertEqual(report["summary"]["ttft_ms"]["mean"], 20.0)
        self.assertEqual(report["summary"]["answer_ttft_ms"]["mean"], 75.0)
        markdown = report_markdown(report)
        self.assertIn("## Run manifest", markdown)
        self.assertIn("Mean first-token TTFT", markdown)
        self.assertIn("Mean final-answer TTFT", markdown)

    def test_aggregate_delta_uses_only_matched_cases(self) -> None:
        baseline = [
            result_record(
                requested_model="model",
                served_model="model",
                endpoint_host="api.example",
                suite_sha256="sha",
                passed=False,
                case_id="shared",
            )
        ]
        candidate = [
            result_record(
                requested_model="model",
                served_model="model",
                endpoint_host="api.example",
                suite_sha256="sha",
                passed=False,
                case_id="shared",
            ),
            result_record(
                requested_model="model",
                served_model="model",
                endpoint_host="api.example",
                suite_sha256="sha",
                passed=True,
                case_id="candidate-only",
            ),
        ]

        comparison = compare_results(baseline, candidate)

        self.assertEqual(comparison["delta"]["pass_rate"], 0.0)
        self.assertEqual(
            comparison["comparability"]["delta_basis"]["matched_case_count"], 1
        )
        self.assertEqual(
            {case["case_id"]: case["change"] for case in comparison["cases"]},
            {"candidate-only": "added", "shared": "unchanged"},
        )

    def test_macro_average_prevents_repeat_count_weighting(self) -> None:
        common = {
            "requested_model": "model",
            "served_model": "model",
            "endpoint_host": "api.example",
            "suite_sha256": "sha",
        }
        baseline = [
            result_record(**common, passed=False, case_id="a"),
            *[result_record(**common, passed=True, case_id="b") for _ in range(9)],
        ]
        candidate = [
            result_record(**common, passed=True, case_id="a"),
            result_record(**common, passed=False, case_id="b"),
        ]

        comparison = compare_results(baseline, candidate)

        self.assertEqual(comparison["delta"]["pass_rate"], 0.0)
        warning_codes = {
            warning["code"] for warning in comparison["comparability"]["warnings"]
        }
        self.assertIn("attempt_count_difference", warning_codes)

    def test_quality_gain_with_reliability_loss_is_mixed(self) -> None:
        common = {
            "requested_model": "model",
            "served_model": "model",
            "endpoint_host": "api.example",
            "suite_sha256": "sha",
            "case_id": "answer",
        }
        baseline = [result_record(**common, passed=False)]
        candidate = [result_record(**common, passed=True)]
        for _ in range(9):
            failed = result_record(**common, passed=False)
            failed["response"] = None
            failed["score"] = None
            failed["error"] = {"type": "TimeoutError", "message": "timeout"}
            candidate.append(failed)

        comparison = compare_results(baseline, candidate)
        case = comparison["cases"][0]

        self.assertEqual(case["quality_change"], "improved")
        self.assertEqual(case["reliability_change"], "regressed")
        self.assertEqual(case["change"], "mixed")


if __name__ == "__main__":
    unittest.main()
