import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from v41flash_eval.cases import CaseFormatError, load_suite


class LoadSuiteTests(unittest.TestCase):
    def write_suite(self, document: object) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "suite.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_loads_defaults_and_scoring_alias(self) -> None:
        path = self.write_suite(
            {
                "name": "demo",
                "defaults": {"temperature": 0},
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "Hi"}],
                        "scoring": {"type": "exact", "value": "Hello"},
                    }
                ],
            }
        )
        suite = load_suite(path)
        self.assertEqual(suite.name, "demo")
        self.assertEqual(suite.defaults["temperature"], 0)
        self.assertEqual(suite.cases[0].expect["type"], "exact")

    def test_loads_and_checks_declared_suite_version(self) -> None:
        path = self.write_suite(
            {
                "schema_version": "v41-flashlab.suite.v1",
                "version": "1.2.3",
                "metadata": {"version": "1.2.3"},
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                    }
                ],
            }
        )
        suite = load_suite(path)
        self.assertEqual(suite.version, "1.2.3")
        self.assertEqual(suite.schema_version, "v41-flashlab.suite.v1")

    def test_rejects_conflicting_suite_versions(self) -> None:
        path = self.write_suite(
            {
                "version": "1.0.0",
                "metadata": {"version": "2.0.0"},
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "must match"):
            load_suite(path)

    def test_rejects_duplicate_ids(self) -> None:
        case = {"id": "same", "messages": [{"role": "user", "content": "x"}]}
        path = self.write_suite({"name": "demo", "cases": [case, case]})
        with self.assertRaisesRegex(CaseFormatError, "duplicate case id"):
            load_suite(path)

    def test_rejects_invalid_scorer(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {"type": "regex", "value": "x"},
                    }
                ]
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "exact, contains, or json_schema"):
            load_suite(path)

    def test_rejects_empty_contains_expectation(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {"type": "contains", "value": []},
                    }
                ]
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "must not be empty"):
            load_suite(path)

    def test_rejects_contains_needle_that_normalizes_empty(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {"type": "contains", "value": ["  "]},
                    }
                ]
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "normalize to an empty"):
            load_suite(path)

    def test_rejects_unsupported_json_schema_keyword(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {
                            "type": "json_schema",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "value": {
                                        "type": "string",
                                        "oneOf": [{"const": "x"}],
                                    }
                                },
                            },
                        },
                    }
                ]
            }
        )
        with self.assertRaisesRegex(
            CaseFormatError, "unsupported JSON Schema keyword 'oneOf'"
        ):
            load_suite(path)

    def test_rejects_non_boolean_allow_markdown_fence(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {
                            "type": "json_schema",
                            "schema": {},
                            "allow_markdown_fence": "yes",
                        },
                    }
                ]
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "must be a boolean"):
            load_suite(path)

    def test_rejects_invalid_supported_schema_keyword_value(self) -> None:
        path = self.write_suite(
            {
                "cases": [
                    {
                        "id": "one",
                        "messages": [{"role": "user", "content": "x"}],
                        "expect": {
                            "type": "json_schema",
                            "schema": {"type": "object", "required": "value"},
                        },
                    }
                ]
            }
        )
        with self.assertRaisesRegex(CaseFormatError, "unique strings"):
            load_suite(path)

    def test_rejects_non_json_yaml_values_before_running(self) -> None:
        path = self.write_suite({"name": "placeholder", "cases": []})
        with (
            patch(
                "v41flash_eval.cases._read_document",
                return_value={
                    "name": "demo",
                    "metadata": {"date": date(2026, 9, 10)},
                    "cases": [
                        {
                            "id": "one",
                            "messages": [{"role": "user", "content": "x"}],
                        }
                    ],
                },
            ),
            self.assertRaisesRegex(CaseFormatError, "non-JSON value"),
        ):
            # Validate values returned by both JSON and YAML parsers.
            load_suite(path)

    def test_rejects_yaml_implicit_date(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML is not installed in this interpreter")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "suite.yaml"
        path.write_text(
            """\
name: demo
metadata:
  release_date: 2026-09-10
cases:
  - id: one
    messages:
      - role: user
        content: x
""",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CaseFormatError, "non-JSON value"):
            load_suite(path)

    def test_repository_smoke_suite_is_valid(self) -> None:
        suite = load_suite(Path(__file__).parents[1] / "benchmarks" / "smoke.json")
        self.assertEqual(len(suite.cases), 3)


if __name__ == "__main__":
    unittest.main()
