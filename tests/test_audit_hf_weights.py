import unittest
from unittest.mock import patch

from scripts.audit_hf_weights import _range


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: bytes,
        content_range: str | None = "bytes 5-7/100",
    ) -> None:
        self.status = status
        self.payload = payload
        self.read_sizes: list[int] = []
        self.headers = (
            {"Content-Range": content_range} if content_range is not None else {}
        )

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.payload[:size]


class RangeRequestTests(unittest.TestCase):
    @patch("scripts.audit_hf_weights.urllib.request.urlopen")
    def test_reads_at_most_one_byte_past_expected_range(self, urlopen: object) -> None:
        response = FakeResponse(206, b"abc")
        urlopen.return_value = response  # type: ignore[attr-defined]

        self.assertEqual(_range("https://example.test/shard", 5, 7, timeout=1), b"abc")
        self.assertEqual(response.read_sizes, [4])

    @patch("scripts.audit_hf_weights.urllib.request.urlopen")
    def test_rejects_ignored_range_before_reading(self, urlopen: object) -> None:
        response = FakeResponse(200, b"entire tensor payload", "bytes 0-7/100")
        urlopen.return_value = response  # type: ignore[attr-defined]

        with self.assertRaisesRegex(ValueError, "HTTP 200"):
            _range("https://example.test/shard", 0, 7, timeout=1)

        self.assertEqual(response.read_sizes, [])

    @patch("scripts.audit_hf_weights.urllib.request.urlopen")
    def test_rejects_oversized_partial_response(self, urlopen: object) -> None:
        response = FakeResponse(206, b"abcd")
        urlopen.return_value = response  # type: ignore[attr-defined]

        with self.assertRaisesRegex(ValueError, "returned 4 bytes"):
            _range("https://example.test/shard", 5, 7, timeout=1)

    @patch("scripts.audit_hf_weights.urllib.request.urlopen")
    def test_rejects_wrong_content_range_before_reading(self, urlopen: object) -> None:
        response = FakeResponse(206, b"abc", "bytes 0-2/100")
        urlopen.return_value = response  # type: ignore[attr-defined]

        with self.assertRaisesRegex(ValueError, "invalid Content-Range"):
            _range("https://example.test/shard", 5, 7, timeout=1)

        self.assertEqual(response.read_sizes, [])


if __name__ == "__main__":
    unittest.main()
