from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

from .cases import CaseFormatError, load_suite, suite_sha256
from .client import (
    OpenAIChatClient,
    UrlLibTransport,
    completion_endpoint,
    is_loopback_host,
)
from .report import (
    ResultFormatError,
    compare_results,
    comparison_markdown,
    generate_report,
    load_jsonl,
    report_markdown,
)
from .runner import run_suite
from .version import __version__


def _json_value(raw: str) -> Any:
    try:
        return json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard numeric constant {value}")
            ),
        )
    except json.JSONDecodeError:
        return raw


def _key_values(values: Sequence[str], *, json_values: bool) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected KEY=VALUE, got {value!r}")
        key, raw = value.split("=", 1)
        if not key:
            raise ValueError("KEY cannot be empty")
        parsed[key] = _json_value(raw) if json_values else raw
    return parsed


def _api_config(
    args: argparse.Namespace,
) -> tuple[str | None, str | None, str | None]:
    cli_base_url = getattr(args, "base_url", None)
    if cli_base_url:
        base_url = cli_base_url
        base_source = "cli"
    elif os.getenv("FLASHLAB_BASE_URL"):
        base_url = os.environ["FLASHLAB_BASE_URL"]
        base_source = "flashlab"
    elif os.getenv("OPENAI_BASE_URL"):
        base_url = os.environ["OPENAI_BASE_URL"]
        base_source = "openai"
    elif os.getenv("DEEPSEEK_BASE_URL"):
        base_url = os.environ["DEEPSEEK_BASE_URL"]
        base_source = "deepseek"
    else:
        base_url = None
        base_source = "none"

    api_key = getattr(args, "api_key", None) or os.getenv("FLASHLAB_API_KEY")
    if api_key is None and base_source == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
    elif api_key is None and base_source == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
    elif api_key is None and base_source in {"cli", "flashlab"} and base_url:
        hostname = urlparse(base_url).hostname
        if hostname == "api.deepseek.com" or hostname == "api.deepseek.com.cn":
            api_key = os.getenv("DEEPSEEK_API_KEY")

    model = (
        getattr(args, "model", None)
        or os.getenv("FLASHLAB_MODEL")
        or os.getenv("V41FLASH_MODEL")
    )
    if model is None and base_source == "openai":
        model = os.getenv("OPENAI_MODEL")
    elif model is None and base_source == "deepseek":
        model = os.getenv("DEEPSEEK_MODEL")
    return base_url, api_key, model


def _discover_suite_paths(inputs: Sequence[str]) -> list[Path]:
    requested = [Path(value) for value in inputs] if inputs else [Path("benchmarks")]
    discovered: dict[str, Path] = {}
    for path in requested:
        if path.is_dir():
            for suffix in ("*.json", "*.yaml", "*.yml"):
                for candidate in path.rglob(suffix):
                    if _is_suite_catalog(candidate):
                        continue
                    discovered[str(candidate.resolve())] = candidate
        elif path.is_file():
            discovered[str(path.resolve())] = path
        else:
            raise ValueError(f"suite path does not exist: {path}")
    paths = [discovered[key] for key in sorted(discovered)]
    if not paths:
        raise ValueError("no benchmark suites found")
    return paths


def _is_suite_catalog(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(document, dict)
        and "cases" not in document
        and isinstance(document.get("suites"), list)
    )


def _write_document(
    document: Mapping[str, Any], output: str, *, markdown: str | None = None
) -> None:
    text = (
        markdown
        if markdown is not None
        else json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    if output == "-":
        sys.stdout.write(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(args: argparse.Namespace) -> int:
    if args.suite and args.suite_option:
        raise ValueError(
            "provide the suite either positionally or with --suite, not both"
        )
    suite_path = args.suite_option or args.suite
    if not suite_path:
        raise ValueError("a benchmark suite is required")
    suite = load_suite(suite_path)
    headers = _key_values(args.header, json_values=False)
    parameters = _key_values(args.param, json_values=True)
    deployment = _key_values(args.deployment, json_values=True)
    base_url, api_key, model = _api_config(args)
    if not base_url:
        raise ValueError(
            "base URL is required; use --base-url, FLASHLAB_BASE_URL, "
            "OPENAI_BASE_URL, or DEEPSEEK_BASE_URL"
        )
    if not model:
        raise ValueError(
            "model is required; use --model, FLASHLAB_MODEL, or a matched provider model variable"
        )
    client = OpenAIChatClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=args.timeout,
        headers=headers,
        transport=UrlLibTransport(),
        allow_insecure_http=args.allow_insecure_http,
    )

    output: TextIO
    close_output = False
    if args.output == "-":
        output = sys.stdout
    else:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        output = path.open("a" if args.append else "w", encoding="utf-8")
        close_output = True

    records: list[dict[str, Any]] = []
    try:
        for record in run_suite(
            suite,
            client,
            stream=args.stream,
            repeat=args.repeat,
            case_ids=args.case,
            parameter_overrides=parameters,
            include_request=not args.no_request,
            run_id=args.run_id,
            suite_sha256=suite_sha256(suite_path),
            deployment_metadata=deployment,
            framework_revision=args.framework_revision
            or os.getenv("FLASHLAB_REVISION"),
        ):
            records.append(record)
            output.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
            output.flush()
    finally:
        if close_output:
            output.close()

    errors = sum(record["error"] is not None for record in records)
    failures = sum(
        isinstance(record.get("score"), dict) and record["score"].get("passed") is False
        for record in records
    )
    print(
        f"completed {len(records)} result(s): {failures} scoring failure(s), {errors} error(s)",
        file=sys.stderr,
    )
    return 0 if args.allow_failures or (errors == 0 and failures == 0) else 1


def _report(args: argparse.Namespace) -> int:
    report = generate_report(load_jsonl(args.inputs))
    markdown = report_markdown(report) if args.format == "markdown" else None
    _write_document(report, args.output, markdown=markdown)
    return 0


def _compare(args: argparse.Namespace) -> int:
    comparison = compare_results(load_jsonl(args.baseline), load_jsonl(args.candidate))
    markdown = comparison_markdown(comparison) if args.format == "markdown" else None
    _write_document(comparison, args.output, markdown=markdown)
    return 0


def _validate(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    print(f"valid suite {suite.name!r}: {len(suite.cases)} case(s)")
    return 0


def _tasks(args: argparse.Namespace) -> int:
    suites: list[dict[str, Any]] = []
    for path in _discover_suite_paths(args.paths):
        suite = load_suite(path)
        suites.append(
            {
                "name": suite.name,
                "version": suite.version,
                "path": str(path),
                "sha256": suite_sha256(path),
                "tasks": [
                    {
                        "id": case.id,
                        "scorer": case.expect.get("type") if case.expect else None,
                        "metadata": dict(case.metadata),
                    }
                    for case in suite.cases
                ],
            }
        )
    document = {
        "schema_version": "v41-flashlab.tasks.v1",
        "framework_version": __version__,
        "suites": suites,
    }
    if args.format == "json":
        _write_document(document, "-")
    else:
        for suite in suites:
            print(f"{suite['name']}  {suite['path']}  ({len(suite['tasks'])} tasks)")
            for task in suite["tasks"]:
                print(f"  {task['id']}  scorer={task['scorer'] or 'none'}")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    base_url, api_key, model = _api_config(args)
    endpoint_url = completion_endpoint(base_url) if base_url else None
    parsed = urlparse(endpoint_url or "")
    checks: list[dict[str, str]] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append(
        {
            "name": "python",
            "status": "pass" if python_ok else "fail",
            "detail": platform.python_version(),
        }
    )
    endpoint_ok = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    checks.append(
        {
            "name": "endpoint",
            "status": "pass" if endpoint_ok else "fail",
            "detail": endpoint_url or "not configured",
        }
    )
    checks.append(
        {
            "name": "model",
            "status": "pass" if model and model.strip() else "fail",
            "detail": model or "not configured",
        }
    )
    checks.append(
        {
            "name": "api_key",
            "status": "pass"
            if api_key
            else ("fail" if args.require_api_key else "warn"),
            "detail": "configured"
            if api_key
            else "not configured (local endpoints may not need one)",
        }
    )
    remote_plaintext = parsed.scheme == "http" and not is_loopback_host(parsed.hostname)
    insecure_credentials = remote_plaintext and bool(api_key)
    checks.append(
        {
            "name": "transport_security",
            "status": (
                "pass"
                if not remote_plaintext
                else (
                    "warn"
                    if args.allow_insecure_http or not insecure_credentials
                    else "fail"
                )
            ),
            "detail": (
                "HTTPS or loopback HTTP"
                if not remote_plaintext
                else (
                    "remote plaintext HTTP explicitly allowed"
                    if args.allow_insecure_http
                    else (
                        "credentials would be sent over remote plaintext HTTP"
                        if insecure_credentials
                        else "remote plaintext HTTP (no API key configured)"
                    )
                )
            ),
        }
    )

    suite_paths: list[Path] = []
    suite_details: list[dict[str, Any]] = []
    requested_suites = args.suite
    if requested_suites or Path("benchmarks").is_dir():
        try:
            suite_paths = _discover_suite_paths(requested_suites)
            for path in suite_paths:
                suite = load_suite(path)
                suite_details.append(
                    {
                        "name": suite.name,
                        "version": suite.version,
                        "path": str(path),
                        "tasks": len(suite.cases),
                        "sha256": suite_sha256(path),
                    }
                )
            checks.append(
                {
                    "name": "suites",
                    "status": "pass",
                    "detail": f"{len(suite_details)} valid suite(s)",
                }
            )
        except (CaseFormatError, ValueError) as exc:
            checks.append({"name": "suites", "status": "fail", "detail": str(exc)})
    else:
        checks.append(
            {
                "name": "suites",
                "status": "warn",
                "detail": "no suite supplied and ./benchmarks was not found",
            }
        )

    ready = all(check["status"] != "fail" for check in checks)
    document = {
        "schema_version": "v41-flashlab.doctor.v1",
        "framework_version": __version__,
        "ready": ready,
        "configuration": {
            "base_url": base_url,
            "endpoint_host": parsed.hostname,
            "model": model,
            "api_key_configured": bool(api_key),
        },
        "suites": suite_details,
        "checks": checks,
    }
    if args.format == "json":
        _write_document(document, "-")
    else:
        print(f"V41 FlashLab {__version__}  {'ready' if ready else 'not ready'}")
        for check in checks:
            print(f"{check['status'].upper():4}  {check['name']}: {check['detail']}")
        for suite in suite_details:
            print(f"SUITE {suite['name']}: {suite['tasks']} task(s) at {suite['path']}")
    return 0 if ready else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flashlab",
        description="Run reproducible benchmarks against an OpenAI-compatible chat API.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run a benchmark suite and emit JSONL")
    run.add_argument(
        "suite", nargs="?", help="benchmark suite (.json, or .yaml with PyYAML)"
    )
    run.add_argument("--suite", dest="suite_option", help="benchmark suite path")
    run.add_argument("--output", "-o", default="-", help="JSONL path, or - for stdout")
    run.add_argument(
        "--append", action="store_true", help="append instead of replacing output"
    )
    run.add_argument(
        "--base-url", help="API base URL (or a FLASHLAB/provider base URL variable)"
    )
    run.add_argument(
        "--api-key",
        help="API key (or a key paired with the selected provider base URL)",
    )
    run.add_argument("--model", help="API model name (or FLASHLAB_MODEL)")
    run.add_argument(
        "--timeout", type=float, default=120.0, help="request timeout in seconds"
    )
    run.add_argument(
        "--stream", action="store_true", help="stream responses and measure TTFT"
    )
    run.add_argument("--repeat", type=int, default=1, help="attempts per case")
    run.add_argument(
        "--case", action="append", default=[], help="run only this case id; repeatable"
    )
    run.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=JSON",
        help="override request parameter",
    )
    run.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="add HTTP header",
    )
    run.add_argument(
        "--deployment",
        action="append",
        default=[],
        metavar="KEY=JSON",
        help="record provider, engine, hardware, revision, or quantization metadata",
    )
    run.add_argument(
        "--framework-revision",
        help="record the FlashLab source revision (or FLASHLAB_REVISION)",
    )
    run.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="allow credentials over non-loopback HTTP on a trusted network",
    )
    run.add_argument("--run-id", help="stable run id for reproducible fixtures")
    run.add_argument(
        "--no-request", action="store_true", help="omit prompts from result records"
    )
    run.add_argument(
        "--allow-failures",
        action="store_true",
        help="exit zero when requests or scores fail",
    )
    run.set_defaults(handler=_run)

    report = subparsers.add_parser(
        "report", help="aggregate one or more JSONL result files"
    )
    report.add_argument("inputs", nargs="+", help="JSONL result paths")
    report.add_argument(
        "--output", "-o", default="-", help="output path, or - for stdout"
    )
    report.add_argument("--format", choices=("json", "markdown"), default="json")
    report.set_defaults(handler=_report)

    compare = subparsers.add_parser(
        "compare", help="compare baseline and candidate JSONL results"
    )
    compare.add_argument(
        "--baseline", nargs="+", required=True, help="baseline JSONL path(s)"
    )
    compare.add_argument(
        "--candidate", nargs="+", required=True, help="candidate JSONL path(s)"
    )
    compare.add_argument(
        "--output", "-o", default="-", help="output path, or - for stdout"
    )
    compare.add_argument("--format", choices=("json", "markdown"), default="json")
    compare.set_defaults(handler=_compare)

    validate = subparsers.add_parser(
        "validate", help="validate a benchmark suite without calling an API"
    )
    validate.add_argument("suite")
    validate.set_defaults(handler=_validate)

    tasks = subparsers.add_parser(
        "tasks",
        aliases=["list"],
        help="list benchmark suites and tasks",
    )
    tasks.add_argument(
        "paths", nargs="*", help="suite files or directories (default: benchmarks)"
    )
    tasks.add_argument("--format", choices=("table", "json"), default="table")
    tasks.set_defaults(handler=_tasks)

    doctor = subparsers.add_parser(
        "doctor", help="check API configuration and benchmark suites"
    )
    doctor.add_argument(
        "--base-url", help="API base URL (or a FLASHLAB/provider base URL variable)"
    )
    doctor.add_argument(
        "--api-key",
        help="API key (or a key paired with the selected provider base URL)",
    )
    doctor.add_argument("--model", help="API model name (or FLASHLAB_MODEL)")
    doctor.add_argument(
        "--suite",
        action="append",
        default=[],
        help="suite file or directory; repeatable",
    )
    doctor.add_argument("--require-api-key", action="store_true")
    doctor.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="accept remote plaintext HTTP as an explicit trusted-network risk",
    )
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    doctor.set_defaults(handler=_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (CaseFormatError, ResultFormatError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
