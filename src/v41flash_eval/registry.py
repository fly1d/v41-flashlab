from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cases import CaseFormatError, load_suite


class RegistryFormatError(ValueError):
    pass


def _strings(value: Any, location: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise RegistryFormatError(f"{location} must be a non-empty string array")
    return [item.strip() for item in value]


def validate_registry(path: str | Path) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryFormatError(
            f"cannot read registry {registry_path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise RegistryFormatError("registry must be an object")
    if document.get("schema_version") != "v41flash.registry.v1":
        raise RegistryFormatError(
            "registry.schema_version must be v41flash.registry.v1"
        )
    entries = document.get("suites")
    if not isinstance(entries, list) or not entries:
        raise RegistryFormatError("registry.suites must be a non-empty array")

    repository_root = registry_path.parent.parent.resolve()
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, value in enumerate(entries):
        location = f"registry.suites[{index}]"
        if not isinstance(value, dict):
            raise RegistryFormatError(f"{location} must be an object")
        suite_id = value.get("id")
        if not isinstance(suite_id, str) or not suite_id.strip():
            raise RegistryFormatError(f"{location}.id must be a non-empty string")
        if suite_id in seen_ids:
            raise RegistryFormatError(f"duplicate registry suite id: {suite_id}")
        seen_ids.add(suite_id)

        relative_path = value.get("path")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise RegistryFormatError(f"{location}.path must be a non-empty string")
        suite_path = (repository_root / relative_path).resolve()
        if not suite_path.is_relative_to(repository_root):
            raise RegistryFormatError(f"{location}.path escapes the repository")
        try:
            suite = load_suite(suite_path)
        except CaseFormatError as exc:
            raise RegistryFormatError(f"{location}: {exc}") from exc
        if suite.schema_version != "v41-flashlab.suite.v1":
            raise RegistryFormatError(
                f"{location}: managed suite must declare v41-flashlab.suite.v1"
            )

        expected_version = value.get("version")
        if expected_version != suite.version:
            raise RegistryFormatError(
                f"{location}.version {expected_version!r} does not match "
                f"suite version {suite.version!r}"
            )
        expected_count = value.get("sample_count")
        if expected_count != len(suite.cases):
            raise RegistryFormatError(
                f"{location}.sample_count {expected_count!r} does not match "
                f"{len(suite.cases)} cases"
            )

        expected_tracks = sorted(_strings(value.get("tracks"), f"{location}.tracks"))
        actual_tracks = sorted(
            {
                str(case.metadata["track"])
                for case in suite.cases
                if isinstance(case.metadata.get("track"), str)
            }
        )
        if expected_tracks != actual_tracks:
            raise RegistryFormatError(
                f"{location}.tracks does not match suite tracks: {actual_tracks}"
            )

        expected_languages = sorted(
            _strings(value.get("languages"), f"{location}.languages")
        )
        raw_language = suite.metadata.get("language")
        actual_languages = sorted(
            [raw_language]
            if isinstance(raw_language, str)
            else _strings(raw_language, "suite.metadata.language")
            if isinstance(raw_language, list)
            else []
        )
        if expected_languages != actual_languages:
            raise RegistryFormatError(
                f"{location}.languages does not match suite languages: "
                f"{actual_languages}"
            )

        for field in ("provenance", "license"):
            if value.get(field) != suite.metadata.get(field):
                raise RegistryFormatError(
                    f"{location}.{field} does not match suite metadata"
                )
        default_epochs = value.get("default_epochs")
        if (
            not isinstance(default_epochs, int)
            or isinstance(default_epochs, bool)
            or default_epochs < 1
        ):
            raise RegistryFormatError(
                f"{location}.default_epochs must be a positive integer"
            )

        validated.append(
            {
                "id": suite_id,
                "path": relative_path,
                "version": suite.version,
                "samples": len(suite.cases),
            }
        )

    return {
        "schema_version": document["schema_version"],
        "registry": str(registry_path),
        "suite_count": len(validated),
        "suites": validated,
    }
