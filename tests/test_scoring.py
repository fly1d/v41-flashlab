import unittest

from v41flash_eval.scoring import score_response, validate_schema


class ScoringTests(unittest.TestCase):
    def test_exact_normalization(self) -> None:
        result = score_response(
            "  HELLO\n", {"type": "exact", "value": "hello", "case_sensitive": False}
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_contains_all_and_any(self) -> None:
        all_result = score_response(
            "red and blue", {"type": "contains", "value": ["red", "green"]}
        )
        any_result = score_response(
            "red and blue",
            {"type": "contains", "value": ["red", "green"], "mode": "any"},
        )
        self.assertFalse(all_result.passed)
        self.assertTrue(any_result.passed)
        self.assertEqual(all_result.details["missing"], ["green"])

    def test_json_schema_rejects_fenced_json_by_default(self) -> None:
        result = score_response(
            '```json\n{"name":"water","formula":"H2O"}\n```',
            {"type": "json_schema", "schema": {"type": "object"}},
        )
        self.assertFalse(result.passed)
        self.assertIn("code fences are not allowed", result.details["errors"][0])

    def test_json_schema_accepts_fenced_json_when_enabled(self) -> None:
        result = score_response(
            '```json\n{"name":"water","formula":"H2O"}\n```',
            {
                "type": "json_schema",
                "allow_markdown_fence": True,
                "schema": {
                    "type": "object",
                    "required": ["name", "formula"],
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "formula": {"const": "H2O"},
                    },
                    "additionalProperties": False,
                },
            },
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.details["value"]["formula"], "H2O")

    def test_json_schema_rejects_nonstandard_numeric_constants(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                result = score_response(
                    f'{{"value": {constant}}}',
                    {"type": "json_schema", "schema": {"type": "object"}},
                )
                self.assertFalse(result.passed)
                self.assertIn(
                    "non-standard numeric constant", result.details["errors"][0]
                )

    def test_json_schema_reports_nested_errors(self) -> None:
        errors = validate_schema(
            {"items": [{"count": 0}], "extra": True},
            {
                "type": "object",
                "required": ["items", "name"],
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"count": {"type": "integer", "minimum": 1}},
                        },
                    }
                },
                "additionalProperties": False,
            },
        )
        self.assertTrue(any("missing required" in error for error in errors))
        self.assertTrue(any("below minimum" in error for error in errors))
        self.assertTrue(any("unexpected property" in error for error in errors))

    def test_invalid_json_is_a_failed_score(self) -> None:
        result = score_response("not-json", {"type": "json_schema", "schema": {}})
        self.assertFalse(result.passed)
        self.assertIn("invalid JSON", result.details["errors"][0])


if __name__ == "__main__":
    unittest.main()
