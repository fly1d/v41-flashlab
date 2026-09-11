from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_JSON_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "const",
        "enum",
        "required",
        "properties",
        "additionalProperties",
        "minItems",
        "maxItems",
        "items",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
)
JSON_SCHEMA_TYPES = frozenset(
    {"null", "boolean", "integer", "number", "string", "array", "object"}
)


@dataclass(frozen=True)
class ScoreResult:
    type: str
    passed: bool | None
    score: float | None
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "passed": self.passed,
            "score": self.score,
            "details": dict(self.details),
        }


def _normalized(value: Any, spec: Mapping[str, Any]) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if spec.get("strip", True):
        text = text.strip()
    if spec.get("collapse_whitespace", False):
        text = " ".join(text.split())
    if not spec.get("case_sensitive", True):
        text = text.casefold()
    return text


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard numeric constant {constant}")


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        or isinstance(value, float)
        and math.isfinite(value)
    )


def _json_content(content: str, *, allow_markdown_fence: bool = False) -> Any:
    text = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        if not allow_markdown_fence:
            raise ValueError("Markdown code fences are not allowed")
        text = match.group(1)
    return json.loads(text, parse_constant=_reject_json_constant)


def schema_definition_errors(schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Validate definitions for the recursively implemented schema subset."""

    errors = [
        f"{path}: unsupported JSON Schema keyword {keyword!r}"
        for keyword in schema
        if keyword not in SUPPORTED_JSON_SCHEMA_KEYWORDS
    ]

    declared_type = schema.get("type")
    if declared_type is not None:
        declared_types = (
            declared_type if isinstance(declared_type, list) else [declared_type]
        )
        if (
            not declared_types
            or not all(
                isinstance(item, str) and item in JSON_SCHEMA_TYPES
                for item in declared_types
            )
            or len(set(declared_types)) != len(declared_types)
        ):
            errors.append(f"{path}.type must contain unique supported type names")

    enum = schema.get("enum")
    if "enum" in schema and (not isinstance(enum, list) or not enum):
        errors.append(f"{path}.enum must be a non-empty array")

    required = schema.get("required")
    if "required" in schema and (
        not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or len(set(required)) != len(required)
    ):
        errors.append(f"{path}.required must contain unique strings")

    additional = schema.get("additionalProperties")
    if "additionalProperties" in schema and not isinstance(additional, bool):
        errors.append(f"{path}.additionalProperties must be a boolean")

    for keyword in ("minItems", "maxItems", "minLength", "maxLength"):
        value = schema.get(keyword)
        if keyword in schema and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            errors.append(f"{path}.{keyword} must be a non-negative integer")

    for minimum, maximum in (("minItems", "maxItems"), ("minLength", "maxLength")):
        low = schema.get(minimum)
        high = schema.get(maximum)
        if (
            isinstance(low, int)
            and not isinstance(low, bool)
            and isinstance(high, int)
            and not isinstance(high, bool)
            and low > high
        ):
            errors.append(f"{path}.{minimum} must not exceed {maximum}")

    for keyword in ("minimum", "maximum"):
        value = schema.get(keyword)
        if keyword in schema and (not _is_finite_number(value)):
            errors.append(f"{path}.{keyword} must be a finite number")
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if _is_finite_number(minimum) and _is_finite_number(maximum) and minimum > maximum:
        errors.append(f"{path}.minimum must not exceed maximum")

    pattern = schema.get("pattern")
    if "pattern" in schema:
        if not isinstance(pattern, str):
            errors.append(f"{path}.pattern must be a string")
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"{path}.pattern is invalid: {exc}")

    properties = schema.get("properties")
    if "properties" in schema and not isinstance(properties, dict):
        errors.append(f"{path}.properties must be an object")
    elif isinstance(properties, dict):
        for name, child_schema in properties.items():
            if isinstance(child_schema, dict):
                errors.extend(
                    schema_definition_errors(
                        child_schema, f"{path}.properties[{name!r}]"
                    )
                )
            else:
                errors.append(f"{path}.properties[{name!r}] must be an object")

    item_schema = schema.get("items")
    if "items" in schema and not isinstance(item_schema, dict):
        errors.append(f"{path}.items must be an object")
    elif isinstance(item_schema, dict):
        errors.extend(schema_definition_errors(item_schema, f"{path}.items"))

    return errors


def _type_matches(value: Any, expected: str) -> bool:
    checks = {
        "null": lambda item: item is None,
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "string": lambda item: isinstance(item, str),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
    }
    return expected in checks and checks[expected](value)


def validate_schema(
    value: Any, schema: Mapping[str, Any], path: str = "$"
) -> list[str]:
    """Validate the practical JSON Schema subset used by benchmark fixtures."""

    errors: list[str] = []
    declared_type = schema.get("type")
    if declared_type is not None:
        allowed_types = (
            declared_type if isinstance(declared_type, list) else [declared_type]
        )
        if not all(isinstance(item, str) for item in allowed_types):
            return [f"{path}: schema type must be a string or array of strings"]
        if not any(_type_matches(value, item) for item in allowed_types):
            return [f"{path}: expected type {' or '.join(allowed_types)}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: value does not equal const")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            errors.append(f"{path}: value is not in enum")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    errors.append(f"{path}: missing required property {key!r}")
        else:
            errors.append(f"{path}: required must be an array")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, dict):
                    errors.extend(
                        validate_schema(value[key], child_schema, f"{path}.{key}")
                    )
        else:
            errors.append(f"{path}: properties must be an object")
        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            for key in value.keys() - properties.keys():
                errors.append(f"{path}: unexpected property {key!r}")

    if isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            errors.append(f"{path}: has fewer than minItems")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            errors.append(f"{path}: has more than maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        if (
            isinstance(schema.get("minLength"), int)
            and len(value) < schema["minLength"]
        ):
            errors.append(f"{path}: shorter than minLength")
        if (
            isinstance(schema.get("maxLength"), int)
            and len(value) > schema["maxLength"]
        ):
            errors.append(f"{path}: longer than maxLength")
        if isinstance(schema.get("pattern"), str):
            try:
                if re.search(schema["pattern"], value) is None:
                    errors.append(f"{path}: does not match pattern")
            except re.error as exc:
                errors.append(f"{path}: invalid schema pattern: {exc}")

    if _is_finite_number(value):
        if (
            isinstance(schema.get("minimum"), (int, float))
            and value < schema["minimum"]
        ):
            errors.append(f"{path}: below minimum")
        if (
            isinstance(schema.get("maximum"), (int, float))
            and value > schema["maximum"]
        ):
            errors.append(f"{path}: above maximum")

    return errors


def score_response(content: str, spec: Mapping[str, Any] | None) -> ScoreResult:
    if spec is None:
        return ScoreResult("none", None, None, {})

    scorer = spec.get("type")
    if scorer == "exact":
        expected = spec.get("value", spec.get("expected"))
        actual_text = _normalized(content, spec)
        expected_text = _normalized(expected, spec)
        passed = actual_text == expected_text
        return ScoreResult(
            "exact",
            passed,
            float(passed),
            {"expected": expected_text, "actual": actual_text},
        )

    if scorer == "contains":
        expected = spec.get("value", spec.get("expected"))
        values = expected if isinstance(expected, list) else [expected]
        actual_text = _normalized(content, spec)
        needles = [_normalized(value, spec) for value in values]
        matches = [needle in actual_text for needle in needles]
        mode = spec.get("mode", "all")
        passed = any(matches) if mode == "any" else all(matches)
        matched = [value for value, found in zip(needles, matches) if found]
        missing = [value for value, found in zip(needles, matches) if not found]
        return ScoreResult(
            "contains",
            passed,
            float(passed),
            {"mode": mode, "matched": matched, "missing": missing},
        )

    if scorer == "json_schema":
        try:
            value = _json_content(
                content,
                allow_markdown_fence=spec.get("allow_markdown_fence", False) is True,
            )
        except json.JSONDecodeError as exc:
            return ScoreResult(
                "json_schema",
                False,
                0.0,
                {"errors": [f"invalid JSON: {exc.msg} at character {exc.pos}"]},
            )
        except ValueError as exc:
            return ScoreResult(
                "json_schema",
                False,
                0.0,
                {"errors": [f"invalid JSON: {exc}"]},
            )
        schema = spec.get("schema", {})
        errors = validate_schema(value, schema)
        passed = not errors
        return ScoreResult(
            "json_schema",
            passed,
            float(passed),
            {"errors": errors, "value": value},
        )

    raise ValueError(f"unsupported scorer type: {scorer!r}")
