import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from v41flash_eval.cli import main
from v41flash_eval.client import TransportResponse


class FakeTransport:
    def request(self, method, url, headers, body, timeout, stream):
        response = {
            "id": "fake",
            "model": "fake-served",
            "choices": [{"message": {"content": "323"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        return TransportResponse(200, {}, json.dumps(response).encode())


class CliTests(unittest.TestCase):
    def test_run_and_report_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.jsonl"
            report_path = Path(directory) / "report.json"
            suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
            with patch(
                "v41flash_eval.cli.UrlLibTransport", return_value=FakeTransport()
            ):
                code = main(
                    [
                        "run",
                        str(suite_path),
                        "--case",
                        "arithmetic-exact",
                        "--model",
                        "fake-model",
                        "--base-url",
                        "http://localhost:8000/v1",
                        "--run-id",
                        "cli-test",
                        "--framework-revision",
                        "deadbeef",
                        "--deployment",
                        'provider="stub"',
                        "--output",
                        str(result_path),
                    ]
                )
            self.assertEqual(code, 0)
            record = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(record["run_id"], "cli-test")
            self.assertEqual(
                record["suite_sha256"],
                hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(record["endpoint_host"], "localhost")
            self.assertEqual(record["framework_version"], "0.1.0")
            self.assertEqual(record["framework_revision"], "deadbeef")
            self.assertEqual(record["deployment"], {"provider": "stub"})
            self.assertEqual(
                record["endpoint"], "http://localhost:8000/v1/chat/completions"
            )
            self.assertEqual(record["generation_parameters"]["temperature"], 0)
            self.assertTrue(record["score"]["passed"])

            code = main(["report", str(result_path), "--output", str(report_path)])
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["counts"]["records"], 1)

    def test_compare_writes_versioned_artifact(self) -> None:
        baseline_record = {
            "suite": "demo",
            "case_id": "case",
            "model": "baseline",
            "response": {"model": "baseline", "content": "no"},
            "metrics": {"latency_ms": 200, "ttft_ms": 50, "total_tokens": 10},
            "score": {"passed": False},
            "error": None,
        }
        candidate_record = {
            "suite": "demo",
            "case_id": "case",
            "model": "candidate",
            "response": {"model": "candidate", "content": "yes"},
            "metrics": {"latency_ms": 100, "ttft_ms": 25, "total_tokens": 8},
            "score": {"passed": True},
            "error": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline.jsonl"
            candidate_path = Path(directory) / "candidate.jsonl"
            output_path = Path(directory) / "comparison.json"
            baseline_path.write_text(
                json.dumps(baseline_record) + "\n", encoding="utf-8"
            )
            candidate_path.write_text(
                json.dumps(candidate_record) + "\n", encoding="utf-8"
            )
            code = main(
                [
                    "compare",
                    "--baseline",
                    str(baseline_path),
                    "--candidate",
                    str(candidate_path),
                    "--output",
                    str(output_path),
                ]
            )
            comparison = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(comparison["schema_version"], "v41-flashlab.comparison.v1")
        self.assertEqual(comparison["delta"]["pass_rate"], 1.0)

    def test_validate_example(self) -> None:
        suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
        self.assertEqual(main(["validate", str(suite_path)]), 0)

    def test_tasks_json_and_list_alias(self) -> None:
        suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["tasks", str(suite_path), "--format", "json"])
        self.assertEqual(code, 0)
        document = json.loads(stdout.getvalue())
        self.assertEqual(document["suites"][0]["name"], "v41-flashlab-smoke")
        self.assertEqual(len(document["suites"][0]["tasks"]), 3)

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["list", str(suite_path)])
        self.assertEqual(code, 0)
        self.assertIn("arithmetic-exact", stdout.getvalue())

    def test_tasks_directory_ignores_registry_catalog(self) -> None:
        benchmark_dir = Path(__file__).parents[1] / "benchmarks"
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["tasks", str(benchmark_dir), "--format", "json"])
        self.assertEqual(code, 0)
        names = {suite["name"] for suite in json.loads(stdout.getvalue())["suites"]}
        self.assertIn("v41-flashlab-smoke", names)
        self.assertNotIn(None, names)

    def test_run_accepts_suite_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "result.jsonl"
            suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
            with patch(
                "v41flash_eval.cli.UrlLibTransport", return_value=FakeTransport()
            ):
                code = main(
                    [
                        "run",
                        "--suite",
                        str(suite_path),
                        "--case",
                        "arithmetic-exact",
                        "--base-url",
                        "http://localhost:8000/v1",
                        "--model",
                        "fake-model",
                        "--output",
                        str(result_path),
                    ]
                )
        self.assertEqual(code, 0)

    def test_run_rejects_nonstandard_numeric_parameter_before_request(self) -> None:
        suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
        code = main(
            [
                "run",
                str(suite_path),
                "--base-url",
                "http://localhost:8000/v1",
                "--model",
                "fake-model",
                "--param",
                "temperature=NaN",
            ]
        )
        self.assertEqual(code, 2)

    def test_doctor_reports_configuration_without_exposing_key(self) -> None:
        suite_path = Path(__file__).parents[1] / "benchmarks" / "smoke.json"
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "doctor",
                    "--base-url",
                    "http://localhost:8000/v1",
                    "--api-key",
                    "super-secret",
                    "--model",
                    "local-model",
                    "--suite",
                    str(suite_path),
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertNotIn("super-secret", stdout.getvalue())
        document = json.loads(stdout.getvalue())
        self.assertTrue(document["ready"])
        self.assertEqual(document["configuration"]["endpoint_host"], "localhost")
        self.assertTrue(document["configuration"]["api_key_configured"])
        self.assertEqual(document["suites"][0]["tasks"], 3)

    def test_doctor_fails_for_invalid_endpoint(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "doctor",
                    "--base-url",
                    "not-a-url",
                    "--suite",
                    str(Path(__file__).parents[1] / "benchmarks" / "smoke.json"),
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["ready"])

    def test_doctor_rejects_key_over_remote_plaintext_http(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "doctor",
                    "--base-url",
                    "http://model.example/v1",
                    "--api-key",
                    "secret",
                    "--model",
                    "model",
                    "--suite",
                    str(Path(__file__).parents[1] / "benchmarks" / "smoke.json"),
                    "--format",
                    "json",
                ]
            )
        document = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        security = next(
            check
            for check in document["checks"]
            if check["name"] == "transport_security"
        )
        self.assertEqual(security["status"], "fail")

    def test_openai_key_is_not_paired_with_an_implicit_deepseek_url(self) -> None:
        stdout = StringIO()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-be-used"}, clear=True),
            redirect_stdout(stdout),
        ):
            code = main(
                [
                    "doctor",
                    "--suite",
                    str(Path(__file__).parents[1] / "benchmarks" / "smoke.json"),
                    "--format",
                    "json",
                ]
            )
        document = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertIsNone(document["configuration"]["base_url"])
        self.assertFalse(document["configuration"]["api_key_configured"])
        self.assertNotIn("must-not-be-used", stdout.getvalue())

    def test_openai_provider_environment_is_resolved_as_a_pair(self) -> None:
        stdout = StringIO()
        environment = {
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_API_KEY": "paired-secret",
            "OPENAI_MODEL": "paired-model",
        }
        with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout):
            code = main(
                [
                    "doctor",
                    "--suite",
                    str(Path(__file__).parents[1] / "benchmarks" / "smoke.json"),
                    "--format",
                    "json",
                ]
            )
        document = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(document["configuration"]["endpoint_host"], "provider.example")
        self.assertEqual(document["configuration"]["model"], "paired-model")
        self.assertTrue(document["configuration"]["api_key_configured"])
        self.assertNotIn("paired-secret", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
