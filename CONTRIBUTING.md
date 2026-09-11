# Contributing

V41 FlashLab values reproducibility over leaderboard volume. A small case with
clear provenance and a reliable grader is more useful than a large opaque set.

## Add a benchmark case

1. Add a case object to a versioned JSON or YAML suite under `benchmarks/`.
2. Give the case a stable `id`, track, prompt, and deterministic grader.
3. State the source and license when adapting third-party material.
4. Do not include personal, confidential, copyrighted, or credential-like data.
5. Run the offline tests and validate the suite before opening a pull request.

For a registered suite, update `benchmarks/registry.json` and run
`python scripts/validate_registry.py`; CI rejects metadata or sample-count drift.

Avoid cases whose answers are likely in public training corpora unless the goal
is explicitly contamination analysis. Prefer transformations of synthetic
fixtures or tasks backed by executable assertions.

## Publish a run

A publishable run must retain:

- Endpoint provider and exact model identifier.
- UTC timestamp and FlashLab commit/version.
- Sampling and reasoning settings.
- Per-case latency, token accounting, grader outcome, and error state.
- Raw model output, except when it contains data that cannot be redistributed.
- Query-free endpoint fingerprint, deployment tags, and suite SHA-256.

Never publish API keys, authorization headers, private prompts, customer data,
or provider request identifiers that can expose an account.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
python scripts/validate_registry.py
```
