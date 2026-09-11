#!/usr/bin/env python3
"""Audit logical parameter counts from remote safetensors headers only.

This downloads the small index file and byte-range headers, never model tensor
payloads. DeepSeek-V4.1-Flash stores two FP4 expert values in each I8 element,
so a naive safetensors element count understates its logical parameter count.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

DEFAULT_REPO = "deepseek-ai/DeepSeek-V4.1-Flash"


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "v41-flashlab/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError(f"expected an object from {url}")
    return value


def _range(url: str, start: int, end: int, *, timeout: float) -> bytes:
    if start < 0 or end < start:
        raise ValueError(f"invalid byte range: {start}-{end}")
    expected = end - start + 1
    request = urllib.request.Request(
        url,
        headers={
            "Range": f"bytes={start}-{end}",
            "User-Agent": "v41-flashlab/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = response.getcode()
        if status != 206:
            raise ValueError(
                f"server returned HTTP {status} for a byte-range request; "
                "refusing to download tensor payloads"
            )
        content_range = response.headers.get("Content-Range")
        range_match = (
            re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range.strip())
            if isinstance(content_range, str)
            else None
        )
        if (
            range_match is None
            or int(range_match.group(1)) != start
            or int(range_match.group(2)) != end
            or (range_match.group(3) != "*" and int(range_match.group(3)) <= end)
        ):
            raise ValueError(
                f"server returned invalid Content-Range {content_range!r}; "
                "refusing to download tensor payloads"
            )
        data = response.read(expected + 1)
    if len(data) != expected:
        raise ValueError(
            f"server returned {len(data):,} bytes for a {expected:,}-byte range; "
            "refusing to download tensor payloads"
        )
    return data


def _header(url: str, *, timeout: float) -> dict[str, Any]:
    length = struct.unpack("<Q", _range(url, 0, 7, timeout=timeout))[0]
    if length <= 0 or length > 100_000_000:
        raise ValueError(f"implausible safetensors header length: {length:,}")
    return json.loads(_range(url, 8, 8 + length - 1, timeout=timeout))


def _component(name: str) -> str:
    if name.startswith("mtp."):
        return "dspark"
    if ".engram." in name:
        return "engram"
    return "backbone"


def audit(repo: str, revision: str, timeout: float, workers: int) -> dict[str, Any]:
    quoted_repo = urllib.parse.quote(repo, safe="/")
    quoted_revision = urllib.parse.quote(revision, safe="")
    base = f"https://huggingface.co/{quoted_repo}/resolve/{quoted_revision}"
    index = _get_json(f"{base}/model.safetensors.index.json", timeout=timeout)
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        raise ValueError("weight index has no weight_map")
    shards = sorted({str(value) for value in weight_map.values()})

    def fetch(shard: str) -> tuple[str, dict[str, Any]]:
        return shard, _header(f"{base}/{urllib.parse.quote(shard)}", timeout=timeout)

    headers: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for shard, header in pool.map(fetch, shards):
            headers[shard] = header

    physical_by_dtype: Counter[str] = Counter()
    logical_by_component: Counter[str] = Counter()
    scale_elements = 0
    tensor_count = 0
    for shard in shards:
        for name, metadata in headers[shard].items():
            if name == "__metadata__":
                continue
            tensor_count += 1
            shape = metadata.get("shape")
            dtype = str(metadata.get("dtype", "unknown"))
            if not isinstance(shape, list) or not all(
                isinstance(size, int) and size >= 0 for size in shape
            ):
                raise ValueError(f"invalid shape for {name}")
            elements = math.prod(shape)
            physical_by_dtype[dtype] += elements
            if name.endswith(".scale"):
                scale_elements += elements
                continue
            # The repository config declares expert_dtype=fp4. Safetensors has
            # no native FP4 dtype, so two values are packed in each I8 element.
            logical_elements = elements * 2 if dtype == "I8" else elements
            logical_by_component[_component(name)] += logical_elements

    metadata = index.get("metadata", {})
    total_size = metadata.get("total_size") if isinstance(metadata, dict) else None
    return {
        "schema_version": "v41-flashlab.weight-audit.v1",
        "repository": repo,
        "revision": revision,
        "shards": len(shards),
        "tensors": tensor_count,
        "index_total_bytes": total_size,
        "index_total_gb": round(total_size / 1_000_000_000, 3)
        if isinstance(total_size, int)
        else None,
        "index_total_gib": round(total_size / (1024**3), 3)
        if isinstance(total_size, int)
        else None,
        "physical_elements_by_dtype": dict(sorted(physical_by_dtype.items())),
        "physical_elements_total": sum(physical_by_dtype.values()),
        "quantization_scale_elements_excluded": scale_elements,
        "logical_parameters_by_component": dict(sorted(logical_by_component.items())),
        "logical_parameters_total": sum(logical_by_component.values()),
        "assumptions": [
            "Tensor names ending in .scale are quantization metadata, not model parameters.",
            "Each I8 tensor element stores two logical FP4 expert parameters, per repository config.",
            "Components with prefix mtp. are reported as DSpark; tensors containing .engram. as Engram.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")
    print(
        json.dumps(
            audit(args.repo, args.revision, args.timeout, args.workers),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
