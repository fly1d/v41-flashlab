from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any

from .cases import BenchmarkCase, BenchmarkSuite
from .client import ClientError, OpenAIChatClient
from .scoring import score_response
from .version import __version__

RESULT_SCHEMA_VERSION = "v41-flashlab.result.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_suite(
    suite: BenchmarkSuite,
    client: OpenAIChatClient,
    *,
    stream: bool = False,
    repeat: int = 1,
    case_ids: Iterable[str] | None = None,
    parameter_overrides: Mapping[str, Any] | None = None,
    include_request: bool = True,
    run_id: str | None = None,
    suite_sha256: str | None = None,
    deployment_metadata: Mapping[str, Any] | None = None,
    framework_revision: str | None = None,
    timestamp: Callable[[], str] = _utc_now,
) -> Iterator[dict[str, Any]]:
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    selected = set(case_ids or ())
    known = {case.id for case in suite.cases}
    unknown = selected - known
    if unknown:
        raise ValueError(f"unknown case id(s): {', '.join(sorted(unknown))}")

    invocation_id = run_id or str(uuid.uuid4())
    for case in suite.cases:
        if selected and case.id not in selected:
            continue
        for attempt in range(1, repeat + 1):
            yield run_case(
                suite,
                case,
                client,
                stream=stream,
                attempt=attempt,
                parameter_overrides=parameter_overrides,
                include_request=include_request,
                run_id=invocation_id,
                suite_sha256=suite_sha256,
                deployment_metadata=deployment_metadata,
                framework_revision=framework_revision,
                started_at=timestamp(),
                timestamp=timestamp,
            )


def run_case(
    suite: BenchmarkSuite,
    case: BenchmarkCase,
    client: OpenAIChatClient,
    *,
    stream: bool,
    attempt: int,
    parameter_overrides: Mapping[str, Any] | None,
    include_request: bool,
    run_id: str,
    suite_sha256: str | None,
    deployment_metadata: Mapping[str, Any] | None,
    framework_revision: str | None,
    started_at: str,
    timestamp: Callable[[], str],
) -> dict[str, Any]:
    parameters = dict(suite.defaults)
    parameters.update(case.parameters)
    parameters.update(parameter_overrides or {})
    record: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "framework_version": __version__,
        "framework_revision": framework_revision,
        "run_id": run_id,
        "started_at": started_at,
        "suite": suite.name,
        "suite_version": suite.version,
        "suite_sha256": suite_sha256,
        "case_id": case.id,
        "attempt": attempt,
        "model": client.model,
        "endpoint_host": getattr(client, "endpoint_host", None),
        "endpoint": getattr(client, "endpoint_fingerprint", None),
        "deployment": dict(deployment_metadata or {}),
        "stream": stream,
        "generation_parameters": {
            **parameters,
            "model": client.model,
            "stream": stream,
        },
        "metadata": {**suite.metadata, **case.metadata},
    }
    if include_request:
        record["request"] = {
            "messages": [dict(message) for message in case.messages],
            "parameters": parameters,
        }

    try:
        completion = client.complete(
            case.messages, parameters=parameters, stream=stream
        )
        score = score_response(completion.content, case.expect)
        record.update(
            {
                "response": {
                    "id": completion.response_id,
                    "model": completion.model,
                    "content": completion.content,
                    "reasoning_content": completion.reasoning_content,
                    "finish_reason": completion.finish_reason,
                },
                "metrics": {
                    "latency_ms": round(completion.latency_ms, 3),
                    "ttft_ms": (
                        round(completion.ttft_ms, 3)
                        if completion.ttft_ms is not None
                        else None
                    ),
                    "answer_ttft_ms": (
                        round(completion.answer_ttft_ms, 3)
                        if completion.answer_ttft_ms is not None
                        else None
                    ),
                    "input_tokens": completion.usage.input_tokens,
                    "output_tokens": completion.usage.output_tokens,
                    "total_tokens": completion.usage.total_tokens,
                    "usage_details": dict(completion.usage.raw),
                },
                "score": score.as_dict(),
                "error": None,
            }
        )
    # Every attempted case must remain representable as a JSONL result record.
    except Exception as exc:  # noqa: BLE001
        error: dict[str, Any] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        elapsed_ms: float | None = None
        if isinstance(exc, ClientError):
            error["status_code"] = exc.status_code
            elapsed_ms = exc.elapsed_ms
        record.update(
            {
                "response": None,
                "metrics": {
                    "latency_ms": round(elapsed_ms, 3)
                    if elapsed_ms is not None
                    else None,
                    "ttft_ms": None,
                    "answer_ttft_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "usage_details": {},
                },
                "score": None,
                "error": error,
            }
        )
    record["finished_at"] = timestamp()
    return record
