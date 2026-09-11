from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .version import __version__


class ResultFormatError(ValueError):
    pass


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard numeric constant {constant}")


def _finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_result_record(record: Mapping[str, Any], location: str) -> None:
    try:
        json.dumps(record, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ResultFormatError(
            f"{location}: record is not strict JSON: {exc}"
        ) from exc

    core_fields = ("suite", "case_id", "model", "response", "metrics", "score", "error")
    missing_core = [field for field in core_fields if field not in record]
    if missing_core:
        raise ResultFormatError(
            f"{location}: record is missing {', '.join(missing_core)}"
        )
    for field in ("suite", "case_id", "model"):
        if not _nonempty_text(record.get(field)):
            raise ResultFormatError(f"{location}.{field} must be a non-empty string")

    schema_version = record.get("schema_version")
    if schema_version is not None and schema_version != "v41-flashlab.result.v1":
        raise ResultFormatError(
            f"{location}.schema_version is unsupported: {schema_version!r}"
        )
    if schema_version == "v41-flashlab.result.v1":
        required_v1 = (
            "framework_version",
            "framework_revision",
            "run_id",
            "started_at",
            "finished_at",
            "suite_version",
            "suite_sha256",
            "attempt",
            "endpoint_host",
            "endpoint",
            "deployment",
            "stream",
            "generation_parameters",
            "metadata",
        )
        missing_v1 = [field for field in required_v1 if field not in record]
        if missing_v1:
            raise ResultFormatError(
                f"{location}: v1 record is missing {', '.join(missing_v1)}"
            )
        for field in ("framework_version", "run_id", "started_at", "finished_at"):
            if not _nonempty_text(record.get(field)):
                raise ResultFormatError(
                    f"{location}.{field} must be a non-empty string"
                )
        attempt = record.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ResultFormatError(f"{location}.attempt must be a positive integer")
        if not isinstance(record.get("stream"), bool):
            raise ResultFormatError(f"{location}.stream must be a boolean")
        for field in ("generation_parameters", "metadata", "deployment"):
            if not isinstance(record.get(field), dict):
                raise ResultFormatError(f"{location}.{field} must be an object")
        for field in (
            "framework_revision",
            "suite_version",
            "suite_sha256",
            "endpoint_host",
            "endpoint",
        ):
            value = record.get(field)
            if value is not None and not _nonempty_text(value):
                raise ResultFormatError(
                    f"{location}.{field} must be null or a non-empty string"
                )

    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        raise ResultFormatError(f"{location}.metrics must be an object")
    if schema_version == "v41-flashlab.result.v1":
        required_metrics = (
            "latency_ms",
            "ttft_ms",
            "answer_ttft_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "usage_details",
        )
        missing_metrics = [field for field in required_metrics if field not in metrics]
        if missing_metrics:
            raise ResultFormatError(
                f"{location}.metrics is missing {', '.join(missing_metrics)}"
            )
        if not isinstance(metrics.get("usage_details"), dict):
            raise ResultFormatError(
                f"{location}.metrics.usage_details must be an object"
            )
    for field in ("latency_ms", "ttft_ms", "answer_ttft_ms"):
        value = metrics.get(field)
        if value is not None and (not _finite_number(value) or value < 0):
            raise ResultFormatError(
                f"{location}.metrics.{field} must be null or a finite non-negative number"
            )
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        value = metrics.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ResultFormatError(
                f"{location}.metrics.{field} must be null or a non-negative integer"
            )

    response = record.get("response")
    score = record.get("score")
    error = record.get("error")
    if error is None:
        if not isinstance(response, dict):
            raise ResultFormatError(
                f"{location}.response must be an object when error is null"
            )
    else:
        if not isinstance(error, dict) or not _nonempty_text(error.get("type")):
            raise ResultFormatError(f"{location}.error must name an error type")
        if response is not None or score is not None:
            raise ResultFormatError(
                f"{location}: failed records must have null response and score"
            )

    if score is not None:
        if not isinstance(score, dict):
            raise ResultFormatError(f"{location}.score must be an object or null")
        passed = score.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise ResultFormatError(f"{location}.score.passed must be boolean or null")
        value = score.get("score")
        if value is not None and (
            not _finite_number(value) or not 0 <= float(value) <= 1
        ):
            raise ResultFormatError(
                f"{location}.score.score must be null or a finite number from 0 to 1"
            )


def _validate_records(records: Sequence[Mapping[str, Any]], side: str) -> None:
    for index, record in enumerate(records):
        _validate_result_record(record, f"{side}[{index}]")


def load_jsonl(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ResultFormatError(f"cannot read {path}: {exc}") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, parse_constant=_reject_json_constant)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ResultFormatError(
                    f"{path}:{line_number}: invalid JSON: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ResultFormatError(
                    f"{path}:{line_number}: record must be an object"
                )
            _validate_result_record(record, f"{path}:{line_number}")
            records.append(record)
    if not records:
        raise ResultFormatError("no result records found")
    return records


def _numbers(records: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        metrics = record.get("metrics")
        value = metrics.get(field) if isinstance(metrics, dict) else None
        if _finite_number(value):
            values.append(float(value))
    return values


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _distribution(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "min": None, "max": None}
    return {
        "mean": round(statistics.fmean(values), 3),
        "p50": round(_percentile(values, 0.5) or 0.0, 3),
        "p95": round(_percentile(values, 0.95) or 0.0, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    errors = sum(record.get("error") is not None for record in records)
    scored_records = [
        record
        for record in records
        if isinstance(record.get("score"), dict)
        and isinstance(record["score"].get("passed"), bool)
    ]
    passed = sum(record["score"].get("passed") is True for record in scored_records)
    failed = sum(record["score"].get("passed") is False for record in scored_records)
    token_fields = ("input_tokens", "output_tokens", "total_tokens")
    tokens: dict[str, Any] = {}
    for field in token_fields:
        values = _numbers(records, field)
        tokens[field] = {
            "sum": int(sum(values)) if values else None,
            "mean": round(statistics.fmean(values), 3) if values else None,
        }
    return {
        "counts": {
            "records": len(records),
            "completed": len(records) - errors,
            "errors": errors,
            "scored": len(scored_records),
            "passed": passed,
            "failed": failed,
        },
        "pass_rate": round(passed / len(scored_records), 6) if scored_records else None,
        "error_rate": round(errors / len(records), 6) if records else None,
        "latency_ms": _distribution(_numbers(records, "latency_ms")),
        "ttft_ms": _distribution(_numbers(records, "ttft_ms")),
        "answer_ttft_ms": _distribution(_numbers(records, "answer_ttft_ms")),
        "tokens": tokens,
    }


def generate_report(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    _validate_records(records, "records")
    by_model: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_suite: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_track: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        model = str(record.get("model", "unknown"))
        suite = str(record.get("suite", "unknown"))
        case_id = str(record.get("case_id", "unknown"))
        metadata = record.get("metadata")
        track = (
            str(metadata.get("track", metadata.get("category", "uncategorized")))
            if isinstance(metadata, dict)
            else "uncategorized"
        )
        by_model[model].append(record)
        by_suite[suite].append(record)
        by_track[track].append(record)
        by_case[f"{suite}/{case_id}"].append(record)
    return {
        "schema_version": "v41-flashlab.report.v1",
        "framework_version": __version__,
        "run_manifest": _deployment_manifest(records),
        "summary": summarize(records),
        "models": {name: summarize(by_model[name]) for name in sorted(by_model)},
        "suites": {name: summarize(by_suite[name]) for name in sorted(by_suite)},
        "tracks": {name: summarize(by_track[name]) for name in sorted(by_track)},
        "cases": {name: summarize(by_case[name]) for name in sorted(by_case)},
    }


def _metric(summary: Mapping[str, Any], *path: str) -> float | None:
    value: Any = summary
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round(candidate - baseline, 6)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _deployment_manifest(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    requested_models: set[str] = set()
    served_models: set[str] = set()
    endpoint_hosts: set[str] = set()
    endpoints: set[str] = set()
    run_ids: set[str] = set()
    framework_versions: set[str] = set()
    framework_revisions: set[str] = set()
    suite_hashes: dict[str, set[str]] = defaultdict(set)
    suite_versions: dict[str, set[str]] = defaultdict(set)
    missing_suite_hashes: dict[str, int] = defaultdict(int)
    generation_parameters: dict[str, dict[str, Any]] = {}
    deployment_metadata: dict[str, dict[str, Any]] = {}
    started_at: list[str] = []
    finished_at: list[str] = []
    missing = {
        "requested_model": 0,
        "served_model": 0,
        "endpoint_host": 0,
        "suite_sha256": 0,
        "generation_parameters": 0,
    }

    for record in records:
        suite = _text(record.get("suite")) or "unknown"
        if value := _text(record.get("run_id")):
            run_ids.add(value)
        if value := _text(record.get("framework_version")):
            framework_versions.add(value)
        if value := _text(record.get("framework_revision")):
            framework_revisions.add(value)
        if value := _text(record.get("started_at")):
            started_at.append(value)
        if value := _text(record.get("finished_at")):
            finished_at.append(value)
        if value := _text(record.get("suite_version")):
            suite_versions[suite].add(value)
        requested_model = _text(record.get("model"))
        if requested_model is None:
            missing["requested_model"] += 1
        else:
            requested_models.add(requested_model)

        response = record.get("response")
        served_model = (
            _text(response.get("model")) if isinstance(response, Mapping) else None
        )
        if served_model is None:
            missing["served_model"] += 1
        else:
            served_models.add(served_model)

        endpoint_host = _text(record.get("endpoint_host"))
        if endpoint_host is None:
            missing["endpoint_host"] += 1
        else:
            endpoint_hosts.add(endpoint_host)
        if endpoint := _text(record.get("endpoint")):
            endpoints.add(endpoint)

        suite_sha256 = _text(record.get("suite_sha256"))
        if suite_sha256 is None:
            missing["suite_sha256"] += 1
            missing_suite_hashes[suite] += 1
        else:
            suite_hashes[suite].add(suite_sha256)

        parameters = record.get("generation_parameters")
        if not isinstance(parameters, Mapping):
            missing["generation_parameters"] += 1
        else:
            copied = dict(parameters)
            generation_parameters[_canonical_json(copied)] = copied

        deployment = record.get("deployment")
        if isinstance(deployment, Mapping):
            copied_deployment = dict(deployment)
            deployment_metadata[_canonical_json(copied_deployment)] = copied_deployment

    suites = sorted(set(suite_hashes) | set(missing_suite_hashes))
    return {
        "record_count": len(records),
        "requested_models": sorted(requested_models),
        "served_models": sorted(served_models),
        "endpoint_hosts": sorted(endpoint_hosts),
        "endpoints": sorted(endpoints),
        "run_ids": sorted(run_ids),
        "framework_versions": sorted(framework_versions),
        "framework_revisions": sorted(framework_revisions),
        "run_window": {
            "started_at": min(started_at) if started_at else None,
            "finished_at": max(finished_at) if finished_at else None,
        },
        "suite_hashes": {
            suite: sorted(suite_hashes.get(suite, set())) for suite in suites
        },
        "suite_versions": {
            suite: sorted(suite_versions.get(suite, set()))
            for suite in sorted(set(suites) | set(suite_versions))
        },
        "missing_suite_hash_records": {
            suite: missing_suite_hashes.get(suite, 0) for suite in suites
        },
        "generation_parameters": [
            generation_parameters[key] for key in sorted(generation_parameters)
        ],
        "deployment_metadata": [
            deployment_metadata[key] for key in sorted(deployment_metadata)
        ],
        "missing_metadata_records": missing,
    }


def _parameter_signatures(manifest: Mapping[str, Any]) -> set[str]:
    signatures: set[str] = set()
    parameters = manifest.get("generation_parameters")
    if not isinstance(parameters, list):
        return signatures
    for value in parameters:
        if not isinstance(value, Mapping):
            continue
        normalized = dict(value)
        # The requested model is compared independently as deployment metadata.
        normalized.pop("model", None)
        signatures.add(_canonical_json(normalized))
    return signatures


def _paired_macro_delta(
    baseline_cases: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    candidate_cases: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    case_keys: Iterable[tuple[str, str]],
    *path: str,
) -> float | None:
    paired: list[tuple[float, float]] = []
    for key in case_keys:
        baseline_value = _metric(summarize(baseline_cases[key]), *path)
        candidate_value = _metric(summarize(candidate_cases[key]), *path)
        if baseline_value is not None and candidate_value is not None:
            paired.append((baseline_value, candidate_value))
    if not paired:
        return None
    baseline_mean = statistics.fmean(value[0] for value in paired)
    candidate_mean = statistics.fmean(value[1] for value in paired)
    return _delta(candidate_mean, baseline_mean)


def _finding(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _comparability(
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], set[str]]:
    baseline_manifest = _deployment_manifest(baseline)
    candidate_manifest = _deployment_manifest(candidate)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    blocked_suites: set[str] = set()

    baseline_hashes = baseline_manifest["suite_hashes"]
    candidate_hashes = candidate_manifest["suite_hashes"]
    shared_suites = set(baseline_hashes) & set(candidate_hashes)
    for suite in sorted(shared_suites):
        base = baseline_hashes[suite]
        cand = candidate_hashes[suite]
        if len(base) > 1 or len(cand) > 1:
            blocked_suites.add(suite)
            issues.append(
                _finding(
                    "mixed_suite_revisions",
                    f"Suite {suite!r} contains multiple revisions in one comparison side.",
                    suite=suite,
                    baseline=base,
                    candidate=cand,
                )
            )
        if base and cand and base != cand:
            blocked_suites.add(suite)
            issues.append(
                _finding(
                    "suite_sha256_mismatch",
                    f"Suite {suite!r} has different SHA-256 revisions.",
                    suite=suite,
                    baseline=base,
                    candidate=cand,
                )
            )

    baseline_suites = set(baseline_hashes)
    candidate_suites = set(candidate_hashes)
    if baseline_suites != candidate_suites:
        warnings.append(
            _finding(
                "suite_set_difference",
                "The baseline and candidate contain different suite sets; unmatched cases "
                "are reported as added or removed.",
                baseline_only=sorted(baseline_suites - candidate_suites),
                candidate_only=sorted(candidate_suites - baseline_suites),
            )
        )

    missing_labels = {
        "requested_model": "requested model",
        "served_model": "served model",
        "endpoint_host": "endpoint host",
        "suite_sha256": "suite SHA-256",
        "generation_parameters": "generation parameters",
    }
    for side, manifest in (
        ("baseline", baseline_manifest),
        ("candidate", candidate_manifest),
    ):
        missing = manifest["missing_metadata_records"]
        for field, label in missing_labels.items():
            count = missing[field]
            if count:
                warnings.append(
                    _finding(
                        f"missing_{field}",
                        f"{side.title()} lacks {label} metadata for {count} record(s); "
                        "legacy comparisons remain enabled but cannot verify this dimension.",
                        side=side,
                        records=count,
                    )
                )

    dimensions = (
        ("requested_models", "requested_model_difference", "requested models"),
        ("served_models", "served_model_difference", "served models"),
    )
    for field, code, label in dimensions:
        base = baseline_manifest[field]
        cand = candidate_manifest[field]
        if base and cand and base != cand:
            warnings.append(
                _finding(
                    code,
                    f"Baseline and candidate use different {label}.",
                    baseline=base,
                    candidate=cand,
                )
            )

    base_endpoints = baseline_manifest["endpoints"]
    candidate_endpoints = candidate_manifest["endpoints"]
    if base_endpoints and candidate_endpoints:
        if base_endpoints != candidate_endpoints:
            warnings.append(
                _finding(
                    "endpoint_difference",
                    "Baseline and candidate use different endpoint fingerprints.",
                    baseline=base_endpoints,
                    candidate=candidate_endpoints,
                )
            )
    else:
        base_hosts = baseline_manifest["endpoint_hosts"]
        candidate_hosts = candidate_manifest["endpoint_hosts"]
        if base_hosts and candidate_hosts and base_hosts != candidate_hosts:
            warnings.append(
                _finding(
                    "endpoint_host_difference",
                    "Baseline and candidate use different endpoint hosts.",
                    baseline=base_hosts,
                    candidate=candidate_hosts,
                )
            )

    for field, code, message in (
        (
            "deployment_metadata",
            "deployment_metadata_difference",
            "Baseline and candidate use different deployment metadata.",
        ),
        (
            "framework_versions",
            "framework_version_difference",
            "Baseline and candidate use different FlashLab versions.",
        ),
        (
            "framework_revisions",
            "framework_revision_difference",
            "Baseline and candidate use different FlashLab source revisions.",
        ),
    ):
        base_values = baseline_manifest[field]
        candidate_values = candidate_manifest[field]
        if base_values and candidate_values and base_values != candidate_values:
            warnings.append(_finding(code, message))

    base_parameters = _parameter_signatures(baseline_manifest)
    candidate_parameters = _parameter_signatures(candidate_manifest)
    if (
        base_parameters
        and candidate_parameters
        and base_parameters != candidate_parameters
    ):
        warnings.append(
            _finding(
                "generation_parameters_difference",
                "Baseline and candidate use different generation parameters.",
            )
        )

    comparable = not issues
    status = (
        "not_comparable"
        if not comparable
        else "comparable_with_warnings"
        if warnings
        else "comparable"
    )
    return (
        {
            "status": status,
            "comparable": comparable,
            "issues": issues,
            "warnings": warnings,
            "manifests": {
                "baseline": baseline_manifest,
                "candidate": candidate_manifest,
            },
        },
        blocked_suites,
    )


def compare_results(
    baseline: Sequence[Mapping[str, Any]], candidate: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    _validate_records(baseline, "baseline")
    _validate_records(candidate, "candidate")
    baseline_cases: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    candidate_cases: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in baseline:
        baseline_cases[
            (str(record.get("suite", "unknown")), str(record["case_id"]))
        ].append(record)
    for record in candidate:
        candidate_cases[
            (str(record.get("suite", "unknown")), str(record["case_id"]))
        ].append(record)

    baseline_summary = summarize(baseline)
    candidate_summary = summarize(candidate)
    comparability, blocked_suites = _comparability(baseline, candidate)
    matched_case_keys = {
        key
        for key in baseline_cases.keys() & candidate_cases.keys()
        if key[0] not in blocked_suites
    }
    baseline_only = {
        key
        for key in baseline_cases.keys() - candidate_cases.keys()
        if key[0] not in blocked_suites
    }
    candidate_only = {
        key
        for key in candidate_cases.keys() - baseline_cases.keys()
        if key[0] not in blocked_suites
    }
    if baseline_only or candidate_only:
        comparability["warnings"].append(
            _finding(
                "case_set_difference",
                "Only matched cases contribute to aggregate deltas; unmatched cases "
                "remain visible as added or removed.",
                baseline_only=[
                    f"{suite}/{case}" for suite, case in sorted(baseline_only)
                ],
                candidate_only=[
                    f"{suite}/{case}" for suite, case in sorted(candidate_only)
                ],
            )
        )

    attempt_differences = [
        {
            "suite": suite,
            "case_id": case_id,
            "baseline": len(baseline_cases[(suite, case_id)]),
            "candidate": len(candidate_cases[(suite, case_id)]),
        }
        for suite, case_id in sorted(matched_case_keys)
        if len(baseline_cases[(suite, case_id)])
        != len(candidate_cases[(suite, case_id)])
    ]
    if attempt_differences:
        comparability["warnings"].append(
            _finding(
                "attempt_count_difference",
                "Matched cases have different attempt counts; per-case rates are "
                "macro-averaged so heavily repeated cases do not dominate.",
                cases=attempt_differences,
            )
        )
    if not matched_case_keys:
        comparability["issues"].append(
            _finding(
                "no_matched_cases",
                "No same-revision case is present on both comparison sides.",
            )
        )

    comparability["comparable"] = not comparability["issues"]
    comparability["status"] = (
        "not_comparable"
        if not comparability["comparable"]
        else "comparable_with_warnings"
        if comparability["warnings"]
        else "comparable"
    )
    comparability["delta_basis"] = {
        "method": "macro_average_over_matched_cases",
        "matched_case_count": len(matched_case_keys),
        "baseline_only_case_count": len(baseline_only),
        "candidate_only_case_count": len(candidate_only),
    }

    metric_paths = {
        "pass_rate": ("pass_rate",),
        "error_rate": ("error_rate",),
        "latency_mean_ms": ("latency_ms", "mean"),
        "ttft_mean_ms": ("ttft_ms", "mean"),
        "answer_ttft_mean_ms": ("answer_ttft_ms", "mean"),
        "total_tokens_mean": ("tokens", "total_tokens", "mean"),
    }
    delta = {
        name: _paired_macro_delta(
            baseline_cases,
            candidate_cases,
            matched_case_keys,
            *path,
        )
        for name, path in metric_paths.items()
    }
    if not comparability["comparable"]:
        # Side summaries remain available, but cross-revision deltas do not.
        delta = dict.fromkeys(delta)

    cases: list[dict[str, Any]] = []
    for suite, case_id in sorted(baseline_cases.keys() | candidate_cases.keys()):
        base_records = baseline_cases.get((suite, case_id), [])
        cand_records = candidate_cases.get((suite, case_id), [])
        if suite in blocked_suites:
            if base_records:
                cases.append(
                    _comparison_case(suite, case_id, base_records, [], "removed")
                )
            if cand_records:
                cases.append(
                    _comparison_case(suite, case_id, [], cand_records, "added")
                )
            continue
        cases.append(_comparison_case(suite, case_id, base_records, cand_records))

    return {
        "schema_version": "v41-flashlab.comparison.v1",
        "framework_version": __version__,
        "comparability": comparability,
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "delta": delta,
        "cases": cases,
    }


def _record_suite_hashes(records: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            value
            for record in records
            if (value := _text(record.get("suite_sha256"))) is not None
        }
    )


def _comparison_case(
    suite: str,
    case_id: str,
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    forced_change: str | None = None,
) -> dict[str, Any]:
    base = summarize(baseline) if baseline else None
    cand = summarize(candidate) if candidate else None
    base_rate = _metric(base or {}, "pass_rate")
    cand_rate = _metric(cand or {}, "pass_rate")
    base_error_rate = _metric(base or {}, "error_rate")
    cand_error_rate = _metric(cand or {}, "error_rate")
    if forced_change is not None:
        quality_change = forced_change
        reliability_change = forced_change
    elif base is None:
        quality_change = "added"
        reliability_change = "added"
    elif cand is None:
        quality_change = "removed"
        reliability_change = "removed"
    else:
        quality_change = _direction(cand_rate, base_rate)
        reliability_change = _direction(
            cand_error_rate, base_error_rate, lower_is_better=True
        )
    active_changes = {
        value
        for value in (quality_change, reliability_change)
        if value not in {"unchanged", "not_available"}
    }
    change = (
        "mixed"
        if {"improved", "regressed"} <= active_changes
        else next(iter(active_changes))
        if active_changes
        else "unchanged"
    )
    return {
        "suite": suite,
        "case_id": case_id,
        "change": change,
        "quality_change": quality_change,
        "reliability_change": reliability_change,
        "baseline_suite_hashes": _record_suite_hashes(baseline),
        "candidate_suite_hashes": _record_suite_hashes(candidate),
        "baseline_pass_rate": base_rate,
        "candidate_pass_rate": cand_rate,
        "pass_rate_delta": _delta(cand_rate, base_rate),
        "baseline_error_rate": base_error_rate,
        "candidate_error_rate": cand_error_rate,
        "error_rate_delta": _delta(cand_error_rate, base_error_rate),
        "baseline_latency_mean_ms": _metric(base or {}, "latency_ms", "mean"),
        "candidate_latency_mean_ms": _metric(cand or {}, "latency_ms", "mean"),
    }


def _direction(
    candidate: float | None,
    baseline: float | None,
    *,
    lower_is_better: bool = False,
) -> str:
    if candidate is None or baseline is None:
        return "not_available"
    if candidate == baseline:
        return "unchanged"
    improved = candidate < baseline if lower_is_better else candidate > baseline
    return "improved" if improved else "regressed"


def report_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    counts = summary["counts"]
    latency = summary["latency_ms"]
    ttft = summary["ttft_ms"]
    answer_ttft = summary.get("answer_ttft_ms", {})
    pass_rate = summary["pass_rate"]
    pass_text = "n/a" if pass_rate is None else f"{pass_rate * 100:.1f}%"
    lines = [
        "# Benchmark report",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Records | {counts['records']} |",
        f"| Passed | {counts['passed']} / {counts['scored']} |",
        f"| Pass rate | {pass_text} |",
        f"| Errors | {counts['errors']} |",
        f"| Mean latency | {_format_ms(latency['mean'])} |",
        f"| P95 latency | {_format_ms(latency['p95'])} |",
        f"| Mean first-token TTFT | {_format_ms(ttft['mean'])} |",
        f"| Mean final-answer TTFT | {_format_ms(_metric(answer_ttft, 'mean'))} |",
        "",
    ]
    manifest = report.get("run_manifest")
    if isinstance(manifest, Mapping):
        lines.extend(
            [
                "## Run manifest",
                "",
                "```json",
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ),
                "```",
                "",
            ]
        )
    tracks = report.get("tracks", {})
    if isinstance(tracks, dict) and tracks:
        lines.extend(
            [
                "## Track breakdown",
                "",
                "| Track | Passed | Pass rate | Errors | P95 latency |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for name, track in tracks.items():
            if not isinstance(track, dict):
                continue
            track_counts = track.get("counts", {})
            track_latency = track.get("latency_ms", {})
            lines.append(
                f"| {name} | {track_counts.get('passed', 0)} / "
                f"{track_counts.get('scored', 0)} | "
                f"{_format_rate(_metric(track, 'pass_rate'))} | "
                f"{track_counts.get('errors', 0)} | "
                f"{_format_ms(_metric(track_latency, 'p95'))} |"
            )
        lines.append("")
    return "\n".join(lines)


def comparison_markdown(comparison: Mapping[str, Any]) -> str:
    delta = comparison["delta"]
    comparability = comparison.get("comparability")
    if not isinstance(comparability, Mapping):
        comparability = {
            "status": "unknown",
            "comparable": True,
            "issues": [],
            "warnings": [
                {
                    "code": "missing_comparability_metadata",
                    "message": "This legacy comparison has no comparability metadata.",
                }
            ],
            "manifests": {},
        }
    lines = [
        "# Benchmark comparison",
        "",
        "## Comparability",
        "",
        f"**Status:** `{comparability.get('status', 'unknown')}`",
        "",
    ]
    issues = comparability.get("issues", [])
    if isinstance(issues, list) and issues:
        lines.extend(["### Blocking issues", ""])
        lines.extend(f"- {_format_finding(issue)}" for issue in issues)
        lines.append("")
    warnings = comparability.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(["### Warnings", ""])
        lines.extend(f"- {_format_finding(warning)}" for warning in warnings)
        lines.append("")

    manifests = comparability.get("manifests", {})
    if isinstance(manifests, Mapping) and manifests:
        lines.extend(["## Deployment manifests", ""])
        for side in ("baseline", "candidate"):
            manifest = manifests.get(side)
            if not isinstance(manifest, Mapping):
                continue
            lines.extend(
                [
                    f"### {side.title()}",
                    "",
                    "```json",
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )

    aggregate_note = (
        "Aggregate deltas are omitted because the benchmark revisions are not "
        "comparable."
        if comparability.get("comparable") is False
        else "Deltas are macro-averaged over matched cases. Positive pass-rate "
        "delta favors the candidate; negative latency delta is faster."
    )
    lines.extend(
        [
            "## Aggregate delta",
            "",
            aggregate_note,
            "",
            "| Metric | Delta |",
            "| --- | ---: |",
            f"| Pass rate | {_format_rate_delta(delta['pass_rate'])} |",
            f"| Error rate | {_format_rate_delta(delta['error_rate'])} |",
            f"| Mean latency | {_format_delta(delta['latency_mean_ms'], ' ms')} |",
            (
                f"| Mean first-token TTFT | "
                f"{_format_delta(delta['ttft_mean_ms'], ' ms')} |"
            ),
            (
                f"| Mean final-answer TTFT | "
                f"{_format_delta(delta.get('answer_ttft_mean_ms'), ' ms')} |"
            ),
            f"| Mean total tokens | {_format_delta(delta['total_tokens_mean'], '')} |",
            "",
            "## Case changes",
            "",
            (
                "| Suite / case | Revisions (baseline -> candidate) | Overall | "
                "Quality | Reliability | Baseline | Candidate |"
            ),
            "| --- | --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for case in comparison["cases"]:
        lines.append(
            f"| {case['suite']} / {case['case_id']} | "
            f"{_format_revisions(case)} | {case['change']} | "
            f"{case.get('quality_change', 'n/a')} | "
            f"{case.get('reliability_change', 'n/a')} | "
            f"{_format_rate(case['baseline_pass_rate'])} | "
            f"{_format_rate(case['candidate_pass_rate'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_finding(finding: Any) -> str:
    if not isinstance(finding, Mapping):
        return str(finding).replace("\n", " ")
    code = str(finding.get("code", "unspecified")).replace("`", "'")
    message = str(finding.get("message", "")).replace("\n", " ")
    return f"`{code}`: {message}"


def _format_revisions(case: Mapping[str, Any]) -> str:
    def compact(values: Any) -> str:
        if not isinstance(values, list) or not values:
            return "unknown"
        return ", ".join(str(value)[:12] for value in values)

    return (
        f"{compact(case.get('baseline_suite_hashes'))} -> "
        f"{compact(case.get('candidate_suite_hashes'))}"
    )


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _format_rate_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f} pp"


def _format_delta(value: float | None, suffix: str) -> str:
    return "n/a" if value is None else f"{value:+.1f}{suffix}"
