from __future__ import annotations

import codecs
import ipaddress
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .version import __version__


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes | Iterable[bytes]


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
        stream: bool,
    ) -> TransportResponse: ...


class ClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.elapsed_ms = elapsed_ms


class UrlLibTransport:
    """urllib-based transport with no third-party runtime dependencies."""

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
        stream: bool,
    ) -> TransportResponse:
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            error_body = exc.read()
            return TransportResponse(exc.code, dict(exc.headers.items()), error_body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ClientError(f"request failed: {exc}") from exc

        status = getattr(response, "status", 200)
        response_headers = dict(response.headers.items())
        if not stream:
            try:
                response_body = response.read()
            finally:
                response.close()
            return TransportResponse(status, response_headers, response_body)

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    yield chunk
            finally:
                response.close()

        return TransportResponse(status, response_headers, chunks())


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: Any) -> Usage:
        if not isinstance(raw, dict):
            return cls()
        input_tokens = _optional_int(raw.get("prompt_tokens", raw.get("input_tokens")))
        output_tokens = _optional_int(
            raw.get("completion_tokens", raw.get("output_tokens"))
        )
        total_tokens = _optional_int(raw.get("total_tokens"))
        if (
            total_tokens is None
            and input_tokens is not None
            and output_tokens is not None
        ):
            total_tokens = input_tokens + output_tokens
        return cls(input_tokens, output_tokens, total_tokens, dict(raw))


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    finish_reason: str | None
    usage: Usage
    latency_ms: float
    ttft_ms: float | None
    response_id: str | None = None
    model: str | None = None
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    answer_ttft_ms: float | None = None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard numeric constant {constant}")


def _body_bytes(body: bytes | Iterable[bytes]) -> bytes:
    if isinstance(body, bytes):
        return body
    return b"".join(body)


def completion_endpoint(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def iter_sse_data(body: bytes | Iterable[bytes]) -> Iterator[str]:
    """Yield SSE data fields, tolerating arbitrary byte chunk boundaries."""

    chunks: Iterable[bytes] = (body,) if isinstance(body, bytes) else body
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    data_lines: list[str] = []

    def process_line(line: str) -> str | None:
        nonlocal data_lines
        line = line.rstrip("\r")
        if not line:
            if not data_lines:
                return None
            event = "\n".join(data_lines)
            data_lines = []
            return event
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
        elif line.startswith("{"):
            data_lines.append(line)
        return None

    for chunk in chunks:
        if not isinstance(chunk, (bytes, bytearray)):
            raise ClientError("stream transport yielded a non-bytes chunk")
        buffer += decoder.decode(bytes(chunk))
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            event = process_line(line)
            if event is not None:
                yield event

    buffer += decoder.decode(b"", final=True)
    if buffer:
        event = process_line(buffer)
        if event is not None:
            yield event
    if data_lines:
        yield "\n".join(data_lines)


class OpenAIChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 120.0,
        headers: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.perf_counter,
        allow_insecure_http: bool = False,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.transport = transport or UrlLibTransport()
        self.clock = clock
        self.completion_url = completion_endpoint(base_url)
        parsed_endpoint = urllib.parse.urlparse(self.completion_url)
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or not parsed_endpoint.hostname
        ):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed_endpoint.username is not None or parsed_endpoint.password is not None:
            raise ValueError("base_url must not contain embedded credentials")
        try:
            endpoint_port = parsed_endpoint.port
        except ValueError as exc:
            raise ValueError(f"base_url has an invalid port: {exc}") from exc
        sensitive_headers = {
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "api-key",
        }
        has_credentials = bool(api_key) or any(
            name.casefold() in sensitive_headers for name in self.headers
        )
        if (
            parsed_endpoint.scheme == "http"
            and not is_loopback_host(parsed_endpoint.hostname)
            and has_credentials
            and not allow_insecure_http
        ):
            raise ValueError(
                "refusing to send credentials over remote HTTP; use HTTPS or "
                "--allow-insecure-http for a trusted network"
            )
        self.endpoint_host = parsed_endpoint.hostname
        endpoint_host = parsed_endpoint.hostname
        if ":" in endpoint_host:
            endpoint_host = f"[{endpoint_host}]"
        endpoint_netloc = (
            f"{endpoint_host}:{endpoint_port}" if endpoint_port else endpoint_host
        )
        self.endpoint_fingerprint = urllib.parse.urlunsplit(
            (
                parsed_endpoint.scheme,
                endpoint_netloc,
                parsed_endpoint.path,
                "",
                "",
            )
        )

    def complete(
        self,
        messages: Iterable[Mapping[str, Any]],
        *,
        parameters: Mapping[str, Any] | None = None,
        stream: bool = False,
    ) -> ChatCompletion:
        payload = dict(parameters or {})
        payload.update(
            {
                "model": self.model,
                "messages": list(messages),
                "stream": stream,
            }
        )
        if stream:
            stream_options = payload.get("stream_options")
            if stream_options is None:
                payload["stream_options"] = {"include_usage": True}

        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"v41-flashlab/{__version__}",
            **self.headers,
        }
        if self.api_key:
            headers.setdefault("Authorization", f"Bearer {self.api_key}")

        started = self.clock()
        try:
            response = self.transport.request(
                "POST",
                self.completion_url,
                headers,
                json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                    "utf-8"
                ),
                self.timeout,
                stream,
            )
        except ClientError as exc:
            if exc.elapsed_ms is None:
                exc.elapsed_ms = (self.clock() - started) * 1000
            raise
        except Exception as exc:
            raise ClientError(
                f"request failed: {exc}", elapsed_ms=(self.clock() - started) * 1000
            ) from exc

        if not 200 <= response.status_code < 300:
            raw_body = _body_bytes(response.body).decode("utf-8", errors="replace")
            message = f"API returned HTTP {response.status_code}"
            try:
                error_document = json.loads(raw_body)
                api_message = error_document.get("error", {}).get("message")
                if isinstance(api_message, str):
                    message = f"{message}: {api_message}"
            except (json.JSONDecodeError, AttributeError):
                pass
            raise ClientError(
                message,
                status_code=response.status_code,
                body=raw_body,
                elapsed_ms=(self.clock() - started) * 1000,
            )

        if stream:
            return self._consume_stream(response.body, started)
        return self._consume_json(response.body, started)

    def _consume_json(
        self, body: bytes | Iterable[bytes], started: float
    ) -> ChatCompletion:
        raw_body = _body_bytes(body)
        try:
            document = json.loads(raw_body, parse_constant=_reject_json_constant)
            choice = document["choices"][0]
            message = choice["message"]
            content = _content_text(message.get("content"))
            reasoning_content = _content_text(message.get("reasoning_content")) or None
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            raise ClientError(
                f"invalid chat completion response: {exc}",
                body=raw_body.decode("utf-8", errors="replace"),
                elapsed_ms=(self.clock() - started) * 1000,
            ) from exc
        return ChatCompletion(
            content=content,
            finish_reason=choice.get("finish_reason"),
            usage=Usage.from_api(document.get("usage")),
            latency_ms=(self.clock() - started) * 1000,
            ttft_ms=None,
            response_id=document.get("id")
            if isinstance(document.get("id"), str)
            else None,
            model=document.get("model")
            if isinstance(document.get("model"), str)
            else None,
            reasoning_content=reasoning_content,
        )

    def _consume_stream(
        self, body: bytes | Iterable[bytes], started: float
    ) -> ChatCompletion:
        parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason: str | None = None
        usage = Usage()
        ttft_ms: float | None = None
        answer_ttft_ms: float | None = None
        response_id: str | None = None
        response_model: str | None = None
        event_count = 0

        try:
            for data in iter_sse_data(body):
                if data.strip() == "[DONE]":
                    break
                event_count += 1
                document = json.loads(data, parse_constant=_reject_json_constant)
                if isinstance(document.get("error"), dict):
                    raise ClientError(
                        f"stream error: {document['error'].get('message', document['error'])}"
                    )
                if isinstance(document.get("id"), str):
                    response_id = document["id"]
                if isinstance(document.get("model"), str):
                    response_model = document["model"]
                if "usage" in document:
                    usage = Usage.from_api(document.get("usage"))
                choices = document.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                text = (
                    _content_text(delta.get("content"))
                    if isinstance(delta, dict)
                    else ""
                )
                reasoning_text = (
                    _content_text(delta.get("reasoning_content"))
                    if isinstance(delta, dict)
                    else ""
                )
                event_elapsed_ms: float | None = None
                if (reasoning_text or text) and (
                    ttft_ms is None or (text and answer_ttft_ms is None)
                ):
                    # Sample once per SSE event so first-token metrics from the
                    # same chunk share an identical timestamp.
                    event_elapsed_ms = (self.clock() - started) * 1000
                if reasoning_text:
                    if ttft_ms is None:
                        ttft_ms = event_elapsed_ms
                    reasoning_parts.append(reasoning_text)
                if text:
                    if ttft_ms is None:
                        ttft_ms = event_elapsed_ms
                    if answer_ttft_ms is None:
                        answer_ttft_ms = event_elapsed_ms
                    parts.append(text)
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
        except ClientError as exc:
            if exc.elapsed_ms is None:
                exc.elapsed_ms = (self.clock() - started) * 1000
            raise
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            raise ClientError(
                f"invalid streaming chat completion response: {exc}",
                elapsed_ms=(self.clock() - started) * 1000,
            ) from exc
        except Exception as exc:
            raise ClientError(
                f"stream read failed: {exc}",
                elapsed_ms=(self.clock() - started) * 1000,
            ) from exc

        if event_count == 0:
            raise ClientError(
                "stream ended without any events",
                elapsed_ms=(self.clock() - started) * 1000,
            )
        return ChatCompletion(
            content="".join(parts),
            finish_reason=finish_reason,
            usage=usage,
            latency_ms=(self.clock() - started) * 1000,
            ttft_ms=ttft_ms,
            response_id=response_id,
            model=response_model,
            reasoning_content="".join(reasoning_parts) or None,
            answer_ttft_ms=answer_ttft_ms,
        )
