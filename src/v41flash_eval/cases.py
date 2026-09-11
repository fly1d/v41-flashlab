from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .scoring import schema_definition_errors


class CaseFormatError(ValueError):
    """Raised when a benchmark suite does not match the supported format."""


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    messages: tuple[Mapping[str, Any], ...]
    expect: Mapping[str, Any] | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkSuite:
    name: str
    cases: tuple[BenchmarkCase, ...]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str | None = None
    version: str | None = None


def suite_sha256(path: str | Path) -> str:
    """Return a digest of the exact suite bytes used for a run."""

    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise CaseFormatError(f"cannot hash {path}: {exc}") from exc


def _read_document(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseFormatError(f"cannot read {path}: {exc}") from exc

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError as exc:
                raise CaseFormatError(
                    "YAML input requires the optional dependency: pip install 'v41-flashlab[yaml]'"
                ) from exc
            document = yaml.safe_load(text)
        else:
            document = json.loads(
                text,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-standard numeric constant {value}")
                ),
            )
        return document
    except CaseFormatError:
        raise
    except Exception as exc:
        raise CaseFormatError(f"cannot parse {path}: {exc}") from exc


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CaseFormatError(f"{location} must be an object")
    return value


def _validate_json_value(value: Any, location: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CaseFormatError(f"{location} must not contain NaN or Infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CaseFormatError(f"{location} keys must be strings")
            _validate_json_value(item, f"{location}.{key}")
        return
    raise CaseFormatError(
        f"{location} contains non-JSON value of type {type(value).__name__}"
    )


def _validate_expect(value: Any, location: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    spec = _mapping(value, location)
    scorer = spec.get("type")
    if scorer not in {"exact", "contains", "json_schema"}:
        raise CaseFormatError(
            f"{location}.type must be one of exact, contains, or json_schema"
        )
    if scorer in {"exact", "contains"} and not any(
        key in spec for key in ("value", "expected")
    ):
        raise CaseFormatError(f"{location} requires value")
    if scorer == "contains":
        expected = spec.get("value", spec.get("expected"))
        values = expected if isinstance(expected, list) else [expected]
        if not values:
            raise CaseFormatError(f"{location}.value must not be empty")
        for index, item in enumerate(values):
            text = item if isinstance(item, str) else json.dumps(item)
            if spec.get("strip", True):
                text = text.strip()
            if spec.get("collapse_whitespace", False):
                text = " ".join(text.split())
            if not text:
                raise CaseFormatError(
                    f"{location}.value[{index}] must not normalize to an empty string"
                )
        if spec.get("mode", "all") not in {"all", "any"}:
            raise CaseFormatError(f"{location}.mode must be all or any")
    if scorer == "json_schema":
        schema = spec.get("schema")
        if not isinstance(schema, dict):
            raise CaseFormatError(f"{location}.schema must be an object")
        schema_errors = schema_definition_errors(schema, f"{location}.schema")
        if schema_errors:
            raise CaseFormatError(schema_errors[0])
        if not isinstance(spec.get("allow_markdown_fence", False), bool):
            raise CaseFormatError(f"{location}.allow_markdown_fence must be a boolean")
    return spec


def load_suite(path: str | Path) -> BenchmarkSuite:
    """Load and validate a JSON suite, or YAML when PyYAML is installed."""

    suite_path = Path(path)
    raw_document = _read_document(suite_path)
    _validate_json_value(raw_document, "suite")
    document = _mapping(raw_document, "suite")
    schema_version = document.get("schema_version")
    if schema_version is not None and schema_version != "v41-flashlab.suite.v1":
        raise CaseFormatError(
            f"suite.schema_version is unsupported: {schema_version!r}"
        )
    name = document.get("name", suite_path.stem)
    if not isinstance(name, str) or not name.strip():
        raise CaseFormatError("suite.name must be a non-empty string")

    defaults = _mapping(document.get("defaults", {}), "suite.defaults")
    metadata = _mapping(document.get("metadata", {}), "suite.metadata")
    top_level_version = document.get("version")
    metadata_version = metadata.get("version")
    if (
        top_level_version is not None
        and metadata_version is not None
        and top_level_version != metadata_version
    ):
        raise CaseFormatError("suite.version must match suite.metadata.version")
    version = top_level_version if top_level_version is not None else metadata_version
    if version is not None and not (isinstance(version, str) and bool(version.strip())):
        raise CaseFormatError("suite.version must be a non-empty string")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CaseFormatError("suite.cases must be a non-empty array")

    seen: set[str] = set()
    cases: list[BenchmarkCase] = []
    for index, raw_case in enumerate(raw_cases):
        location = f"suite.cases[{index}]"
        case = _mapping(raw_case, location)
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise CaseFormatError(f"{location}.id must be a non-empty string")
        if case_id in seen:
            raise CaseFormatError(f"duplicate case id: {case_id}")
        seen.add(case_id)

        raw_messages = case.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise CaseFormatError(f"{location}.messages must be a non-empty array")
        messages: list[Mapping[str, Any]] = []
        for message_index, raw_message in enumerate(raw_messages):
            message_location = f"{location}.messages[{message_index}]"
            message = _mapping(raw_message, message_location)
            if message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise CaseFormatError(f"{message_location}.role is invalid")
            if "content" not in message:
                raise CaseFormatError(f"{message_location}.content is required")
            messages.append(message)

        expect = case.get("expect", case.get("scoring"))
        cases.append(
            BenchmarkCase(
                id=case_id,
                messages=tuple(messages),
                expect=_validate_expect(expect, f"{location}.expect"),
                parameters=_mapping(
                    case.get("parameters", {}), f"{location}.parameters"
                ),
                metadata=_mapping(case.get("metadata", {}), f"{location}.metadata"),
            )
        )

    return BenchmarkSuite(
        name=name.strip(),
        cases=tuple(cases),
        defaults=defaults,
        metadata=metadata,
        schema_version=schema_version,
        version=version.strip() if isinstance(version, str) else None,
    )
