# Dataset card

## Summary

The bundled suites are launch-day validation fixtures for V41 FlashLab. They
are designed to verify an endpoint, the logging pipeline, and a small set of
objective Chinese business behaviors before running larger third-party or
customer-owned evaluations.

They are not a comprehensive intelligence benchmark and must not be presented
as one.

## Releases

| Suite | Release | Samples | Language | Intended use |
| --- | --- | ---: | --- | --- |
| `smoke` | 1.0.0 | 3 | English | Endpoint, scorer, and structured-output checks |
| `cn-business-v1` | 1.0.0 | 12 | Simplified Chinese | Directional enterprise-migration pilot |
| generated long context | per invocation | 3 per length by default | English | Progressive context acceptance and retrieval stress |

The machine-readable catalog is in `benchmarks/registry.json`.

## Creation

All bundled prompts and ground truths were written specifically for this
repository on 2026-09-10. No customer data, scraped text, private documents, or
third-party benchmark samples are included. The long-context generator uses a
recorded seed to vary labels, numeric targets, and three answer-bearing fact
positions per sample while remaining exactly reproducible.

## Tasks and annotations

Each sample contains:

- A stable case id.
- One or more chat messages.
- Request defaults and optional per-case parameters.
- An objective scorer specification (`exact`, `contains`, or `json_schema`).
- Metadata such as track, difficulty, provenance, language, and release.

Targets were checked by hand. JSON extraction targets constrain both values and
additional fields. Exact-match prompts explicitly request a canonical output.

## Personal and sensitive information

The bundled data contains no information about real people or organizations.
Names, order numbers, businesses, and transactions are fictional. Contributors
must not submit prompts containing personal data, secrets, customer text, or
confidential source code.

## Known limitations

- Twelve Chinese cases are far too few for a capability claim.
- Deterministic graders reward canonical outputs but do not capture all valid
  free-form answers.
- Synthetic business tasks are cleaner than production inputs.
- Single-turn tasks do not measure long-horizon agent behavior.
- The generated long-context suite reserves prompt/output headroom but still
  estimates size; only tokenizer or API-reported input tokens establish actual
  length.
- Public prompts may eventually enter training data. Releases should add fresh
  held-out questions before comparative publication.

## Recommended evaluation practice

Use the smoke suite once at temperature zero. For stochastic tasks, run at least
three epochs and report pass@1 with uncertainty. Compare model-endpoint pairs
under identical prompts and budgets. Preserve errors rather than dropping them.
Treat the business suite as a pipeline demonstration until it is supplemented
with a documented, blinded, domain-representative set.

## Maintenance

Prompt or target changes require a version increment. Retired cases remain in
release history with a reason. Suspected contamination, ambiguous targets, or
grader faults should be filed as issues and excluded from the primary aggregate
until resolved.

## License

Bundled synthetic fixtures are available under this repository's MIT license.
That license does not apply to third-party suites or customer-owned evaluation
data loaded by users.
