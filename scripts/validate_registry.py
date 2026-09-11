#!/usr/bin/env python3
"""Validate benchmark registry metadata against its suite files."""

from __future__ import annotations

import argparse
import json

from v41flash_eval.registry import RegistryFormatError, validate_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", default="benchmarks/registry.json")
    args = parser.parse_args()
    try:
        result = validate_registry(args.registry)
    except RegistryFormatError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
