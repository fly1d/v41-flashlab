import json
import unittest

from v41flash_eval.client import (
    ClientError,
    OpenAIChatClient,
    TransportResponse,
    iter_sse_data,
)


class FakeClock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class FakeTransport:
    def __init__(self, response: TransportResponse) -> None:
        self.response = response
        self.requests = []

    def request(self, method, url, headers, body, timeout, stream):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": timeout,
                "stream": stream,
            }
        )
        return self.response


class ClientTests(unittest.TestCase):
    def test_rejects_non_http_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute HTTP"):
            OpenAIChatClient(
                base_url="file:///tmp/model",
                api_key=None,
                model="test-model",
            )

    def test_rejects_endpoint_with_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "embedded credentials"):
            OpenAIChatClient(
                base_url="https://user:secret@model.example/v1",
                api_key=None,
                model="test-model",
            )

    def test_rejects_credentials_over_remote_plaintext_http(self) -> None:
        with self.assertRaisesRegex(ValueError, "remote HTTP"):
            OpenAIChatClient(
                base_url="http://model.example/v1",
                api_key="secret",
                model="test-model",
            )

    def test_allows_credentials_over_loopback_http(self) -> None:
        client = OpenAIChatClient(
            base_url="http://127.0.0.1:8000/v1",
            api_key="secret",
            model="test-model",
        )
        self.assertEqual(client.endpoint_host, "127.0.0.1")

    def test_insecure_http_requires_explicit_override(self) -> None:
        client = OpenAIChatClient(
            base_url="http://model.example/v1",
            api_key="secret",
            model="test-model",
            allow_insecure_http=True,
        )
        self.assertEqual(client.endpoint_host, "model.example")

    def test_nonstream_completion_and_usage(self) -> None:
        body = json.dumps(
            {
                "id": "completion-1",
                "model": "served-model",
                "choices": [
                    {
                        "message": {
                            "content": "323",
                            "reasoning_content": "17 times 19",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                    "prompt_cache_hit_tokens": 5,
                    "prompt_cache_miss_tokens": 2,
                    "completion_tokens_details": {"reasoning_tokens": 1},
                },
            }
        ).encode()
        transport = FakeTransport(TransportResponse(200, {}, body))
        client = OpenAIChatClient(
            base_url="http://localhost:8000/v1/",
            api_key="secret",
            model="test-model",
            transport=transport,
            clock=FakeClock(10.0, 10.25),
        )
        completion = client.complete(
            [{"role": "user", "content": "question"}], parameters={"temperature": 0}
        )

        self.assertEqual(completion.content, "323")
        self.assertEqual(completion.latency_ms, 250.0)
        self.assertIsNone(completion.ttft_ms)
        self.assertEqual(completion.reasoning_content, "17 times 19")
        self.assertEqual(completion.usage.total_tokens, 9)
        self.assertEqual(completion.usage.raw["prompt_cache_hit_tokens"], 5)
        self.assertEqual(completion.usage.raw["prompt_cache_miss_tokens"], 2)
        self.assertEqual(
            completion.usage.raw["completion_tokens_details"]["reasoning_tokens"],
            1,
        )
        request = transport.requests[0]
        self.assertEqual(request["url"], "http://localhost:8000/v1/chat/completions")
        self.assertEqual(
            client.endpoint_fingerprint,
            "http://localhost:8000/v1/chat/completions",
        )
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        payload = json.loads(request["body"])
        self.assertEqual(payload["model"], "test-model")
        self.assertFalse(payload["stream"])

    def test_streaming_completion_measures_ttft(self) -> None:
        stream = (
            b'data: {"id":"s1","model":"served","choices":[{"delta":{"content":"hel"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n'
            b"data: [DONE]\n\n"
        )
        chunks = [stream[:9], stream[9:74], stream[74:113], stream[113:]]
        transport = FakeTransport(TransportResponse(200, {}, iter(chunks)))
        client = OpenAIChatClient(
            base_url="http://localhost/v1/chat/completions",
            api_key=None,
            model="test-model",
            transport=transport,
            clock=FakeClock(1.0, 1.05, 1.2),
        )
        completion = client.complete([{"role": "user", "content": "x"}], stream=True)

        self.assertEqual(completion.content, "hello")
        self.assertAlmostEqual(completion.ttft_ms, 50.0)
        self.assertAlmostEqual(completion.answer_ttft_ms, 50.0)
        self.assertAlmostEqual(completion.latency_ms, 200.0)
        self.assertEqual(completion.usage.output_tokens, 1)
        payload = json.loads(transport.requests[0]["body"])
        self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_streaming_preserves_reasoning_and_answer_ttft(self) -> None:
        stream = (
            b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        transport = FakeTransport(TransportResponse(200, {}, stream))
        client = OpenAIChatClient(
            base_url="http://localhost/v1",
            api_key=None,
            model="test-model",
            transport=transport,
            clock=FakeClock(1.0, 1.02, 1.08, 1.1),
        )

        completion = client.complete([{"role": "user", "content": "x"}], stream=True)

        self.assertEqual(completion.reasoning_content, "think")
        self.assertEqual(completion.content, "answer")
        self.assertAlmostEqual(completion.ttft_ms, 20.0)
        self.assertAlmostEqual(completion.answer_ttft_ms, 80.0)

    def test_sse_parser_handles_split_unicode(self) -> None:
        encoded = 'data: {"text":"\u4f60"}\n\n'.encode("utf-8")
        split = encoded.index("\u4f60".encode("utf-8")) + 1
        self.assertEqual(
            list(iter_sse_data([encoded[:split], encoded[split:]])),
            ['{"text":"\u4f60"}'],
        )

    def test_http_error_preserves_status_and_elapsed_time(self) -> None:
        transport = FakeTransport(
            TransportResponse(429, {}, b'{"error":{"message":"rate limited"}}')
        )
        client = OpenAIChatClient(
            base_url="http://localhost/v1",
            api_key=None,
            model="test-model",
            transport=transport,
            clock=FakeClock(2.0, 2.01),
        )
        with self.assertRaisesRegex(ClientError, "rate limited") as raised:
            client.complete([{"role": "user", "content": "x"}])
        self.assertEqual(raised.exception.status_code, 429)
        self.assertAlmostEqual(raised.exception.elapsed_ms, 10.0)


if __name__ == "__main__":
    unittest.main()
