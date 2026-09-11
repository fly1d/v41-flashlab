# V41 FlashLab

[![CI](https://github.com/fly1d/v41-flashlab/actions/workflows/ci.yml/badge.svg)](https://github.com/fly1d/v41-flashlab/actions/workflows/ci.yml)
[![Pages](https://github.com/fly1d/v41-flashlab/actions/workflows/pages.yml/badge.svg)](https://fly1d.github.io/v41-flashlab/)
[![License: MIT](https://img.shields.io/badge/License-MIT-087a50.svg)](LICENSE)

**Live migration service:** <https://fly1d.github.io/v41-flashlab/>

An independent, reproducible field lab for **DeepSeek-V4.1-Flash**. It turns
OpenAI-compatible endpoints into auditable evaluation runs, comparable result
artifacts, and a static report that can be published without a backend.

> Status: launch-day build. The model repository was created on 2026-09-10 and
> its serving ecosystem is still changing. Every claim in this project is
> labeled as official, observed, or not yet verified.

## What this gives you

- A provider-neutral benchmark CLI for OpenAI-compatible chat requests,
  including multimodal message payloads supported by the selected endpoint.
- Versioned Chinese-first cases aimed at real migration decisions.
- Raw JSONL traces, deterministic graders, and aggregate summaries.
- A no-build launch dashboard and local-only migration brief generator.
- A launch-day technical brief and a practical enterprise migration worksheet.
- A customer-facing service menu, scope confirmation template, and sales playbook.
- A public-safe GitHub intake path plus searchable and shareable site metadata.

## Commercial delivery kit

The recommended entry offer is a fixed-scope migration assessment: up to 50
authorized, anonymized business samples; one current baseline and one candidate
model-endpoint pair; raw traces, failure analysis, and a migration / routing /
hold recommendation. The standard-scope service fee shown in the local site is
CNY 9,800; seller identity, tax treatment, API costs, payment terms, and schedule
must be confirmed in writing.

- [Customer-facing service offer](docs/commercial-offer.zh-CN.md)
- [Internal sales playbook and outreach drafts](docs/sales-playbook.zh-CN.md)
- [Customer proposal / scope confirmation template](docs/customer-proposal-template.zh-CN.md)
- [Standard service terms template](docs/standard-service-terms-template.zh-CN.md)
- [Conditional data-processing addendum template](docs/data-processing-addendum-template.zh-CN.md)

No outreach, public posting, payment collection, or customer-data transfer is
performed by this repository. Fill in the actual legal entity, contact channel,
commercial terms, and data-processing agreement before using the drafts.

The repository includes a public, non-sensitive GitHub issue intake form and a
GitHub Pages workflow. Their prepared target is `fly1d/v41-flashlab`; verify the
account, repository visibility, and public seller identity before the first push.

## Quick start

The evaluator targets an OpenAI-compatible `/chat/completions` endpoint. Use a
small smoke suite before spending money on a full run.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
set -a && source .env && set +a

flashlab doctor
flashlab tasks
flashlab run --suite benchmarks/smoke.json --stream \
  --output runs/deepseek-flash-smoke.jsonl
flashlab report runs/deepseek-flash-smoke.jsonl \
  --format markdown --output runs/deepseek-flash-smoke.md
```

Secrets are read from the process environment and are never written to result
files; the CLI does not load `.env` automatically, so the shell command above
exports it. See `.env.example` for endpoint configuration. Credentials are
refused over non-loopback HTTP unless `--allow-insecure-http` is explicit.

The official DeepSeek API currently exposes this checkpoint as
`deepseek-flash`; a provider hosting the Hugging Face weights may use a
different model id. Record the exact endpoint-model pair in every comparison.

To inspect the static report locally:

```bash
python3 -m http.server 8080 -d site
```

Then open <http://localhost:8080>.

## Evidence levels

| Label | Meaning |
| --- | --- |
| `official` | Stated in DeepSeek's model repository or technical report |
| `observed` | Reproduced by a public FlashLab run with raw artifacts |
| `unverified` | A useful hypothesis that still needs endpoint access or scale |

Scores without a raw run artifact do not belong in the leaderboard. Provider,
model identifier, sampling settings, evaluator version, latency, token usage,
and failures are part of the result rather than footnotes.

## Repository map

```text
src/v41flash_eval/   Python package and CLI
benchmarks/          Versioned JSON/YAML evaluation suites and registry
tests/               Offline tests for requests and graders
site/                Static launch dashboard and migration brief generator
docs/                Research, methodology, and migration materials
schemas/             Machine-readable artifact schemas
scripts/             Registry, long-context, and checkpoint-audit utilities
runs/                Local run artifacts (ignored except examples)
```

## Suggested first public experiment

Run the 12-case Chinese business suite against V4.1-Flash and one production
model after the 3-case smoke check, then publish both raw artifacts. The first
useful answer is not "which model is best?" but "on which workload, at what
quality, latency, and cost?"

```bash
flashlab run benchmarks/cn-business-v1.json --stream \
  --deployment provider='"deepseek-api"' \
  --deployment region='"your-region"' \
  --output runs/deepseek-flash-cn-business-v1.jsonl
```

Compare only after both sides use the same suite bytes. `compare` preserves
deployment manifests, warns about model/endpoint/parameter drift, and computes
deltas as a macro-average over matched cases. A suite SHA mismatch suppresses
the delta instead of producing a misleading winner.

```bash
flashlab compare \
  --baseline runs/current-model-cn-business-v1.jsonl \
  --candidate runs/deepseek-flash-cn-business-v1.jsonl \
  --format markdown --output runs/comparison.md
```

Generate a progressive long-context suite without committing a huge fixture:

```bash
python scripts/make_long_context_suite.py \
  --tokens 32000 --cases 3 --seed 4102026 \
  --output runs/long-context-32k.json
flashlab validate runs/long-context-32k.json
```

The result record contract is published at
[`schemas/result-v1.schema.json`](schemas/result-v1.schema.json).

For the launch-day parameter-count discrepancy, reproduce the remote-header
audit without downloading the 510 GB checkpoint:

```bash
python scripts/audit_hf_weights.py \
  --revision 2bc89ac599031fa673cab993f1df02fc4a98c673
```

The pinned launch-day output is preserved in
[`evidence/hf-weight-audit-2026-09-10.json`](evidence/hf-weight-audit-2026-09-10.json).

## Sources and independence

- [Model repository](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash)
- [Official technical report](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/2bc89ac599031fa673cab993f1df02fc4a98c673/DeepSeek_V41_Tech_Report.pdf)
- [MIT model-repository license](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/2bc89ac599031fa673cab993f1df02fc4a98c673/LICENSE)
- [Official API model and pricing](https://api-docs.deepseek.com/quick_start/pricing)

V41 FlashLab is an independent community project. It is not affiliated with or
endorsed by DeepSeek. Model names and trademarks belong to their owners. This
repository's MIT license does not replace the license or terms of any model,
provider, benchmark dataset, or submitted content.

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md). New benchmark cases must state
their provenance and license, avoid private data, and include deterministic
grading whenever possible.
