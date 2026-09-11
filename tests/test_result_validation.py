import json
import tempfile
import unittest
from pathlib import Path

from v41flash_eval.report import ResultFormatError, load_jsonl


class ResultValidationTests(unittest.TestCase):
    def write_line(self, value: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "result.jsonl"
        path.write_text(value + "\n", encoding="utf-8")
        return path

    def test_rejects_truncated_record_instead_of_counting_it_complete(self) -> None:
        path = self.write_line(json.dumps({"case_id": "one", "model": "model"}))
        with self.assertRaisesRegex(ResultFormatError, "record is missing"):
            load_jsonl([path])

    def test_rejects_nonstandard_json_number(self) -> None:
        path = self.write_line(
            '{"suite":"s","case_id":"c","model":"m","metrics":'
            '{"latency_ms":NaN},"response":{},"score":null,"error":null}'
        )
        with self.assertRaisesRegex(ResultFormatError, "non-standard numeric"):
            load_jsonl([path])

    def test_rejects_unknown_declared_schema_version(self) -> None:
        path = self.write_line(
            json.dumps(
                {
                    "schema_version": "v41-flashlab.result.v999",
                    "suite": "s",
                    "case_id": "c",
                    "model": "m",
                    "metrics": {},
                    "response": {},
                    "score": None,
                    "error": None,
                }
            )
        )
        with self.assertRaisesRegex(ResultFormatError, "unsupported"):
            load_jsonl([path])

    def test_rejects_contradictory_error_record(self) -> None:
        path = self.write_line(
            json.dumps(
                {
                    "suite": "s",
                    "case_id": "c",
                    "model": "m",
                    "metrics": {"latency_ms": 2},
                    "response": {"content": "partial"},
                    "score": None,
                    "error": {"type": "TimeoutError", "message": "timeout"},
                }
            )
        )
        with self.assertRaisesRegex(ResultFormatError, "null response and score"):
            load_jsonl([path])

    def test_rejects_fractional_token_count(self) -> None:
        path = self.write_line(
            json.dumps(
                {
                    "suite": "s",
                    "case_id": "c",
                    "model": "m",
                    "metrics": {"total_tokens": 3.5},
                    "response": {},
                    "score": None,
                    "error": None,
                }
            )
        )
        with self.assertRaisesRegex(ResultFormatError, "non-negative integer"):
            load_jsonl([path])

    def test_accepts_well_formed_legacy_record(self) -> None:
        record = {
            "suite": "s",
            "case_id": "c",
            "model": "m",
            "metrics": {"latency_ms": 2, "total_tokens": 3},
            "response": {"content": "yes", "model": "served"},
            "score": {"passed": True, "score": 1.0},
            "error": None,
        }
        path = self.write_line(json.dumps(record))
        self.assertEqual(load_jsonl([path]), [record])


if __name__ == "__main__":
    unittest.main()
