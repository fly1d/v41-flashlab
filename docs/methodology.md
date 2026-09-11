# Evaluation methodology

## Purpose

FlashLab evaluates migration fitness, not abstract intelligence. Every result
should help answer whether a model is sufficiently accurate, fast, stable, and
economical for a named workload.

## Unit of comparison

Compare model-endpoint pairs rather than model names alone. Serving engine,
quantization, hardware, queueing, prompt encoder, reasoning setting, and agent
scaffold can materially change the result.

Each run records:

- Suite and case revision.
- Provider/deployment tags, a query-free endpoint fingerprint, and requested
  plus served model identifiers.
- Temperature, output limit, seed when supported, and reasoning effort.
- Wall-clock latency, first generated token and first final-answer token latency,
  raw provider token usage, finish reason, attempts, and errors.
- Raw response and deterministic grader details.

The launch-day runner does not yet execute tools or grade multi-step agent
trajectories. Its `agent` fixture measures read-only action intent and JSON
format compliance only; full tool-use claims require a separate sandboxed
trajectory runner.

Secrets, URL user information, query strings, and fragments are excluded from
exported artifacts. The scheme, host, port, and completion path remain visible
because they are part of the deployment identity.

## Comparison protocol

- A suite SHA-256 mismatch is blocking: cross-revision deltas are suppressed.
- Added and removed cases remain visible but do not enter aggregate deltas.
- Aggregate deltas macro-average same-revision matched cases, so a case with
  more attempts cannot silently dominate the comparison.
- Quality and endpoint reliability are separate directions. A quality gain with
  a higher error rate is reported as mixed, not improved.
- Requested/served model, endpoint, generation setting, deployment, and harness
  revision differences remain allowed but appear as manifest warnings.

## Score dimensions

Report these dimensions separately:

| Dimension | Preferred measure |
| --- | --- |
| Quality | Pass rate by category and case, with raw evidence |
| Reliability | Successful responses / attempted responses |
| Latency | Median and p95 wall-clock latency |
| Efficiency | Input/output tokens and provider cost when supplied |
| Instruction fit | Structured-output and constraint pass rates |
| Long context | Accuracy plotted against actual input-token bands |

Do not combine them into a single score by default. A weighted score is only
valid after a workload owner declares the weights and hard constraints.

## Repetition and uncertainty

- Deterministic smoke tests may run once at temperature zero.
- Stochastic or agentic cases should run at least three times.
- Any public percentage must show the numerator and denominator.
- Treat fewer than 30 cases in a category as directional evidence.
- Separate endpoint failures from wrong answers.

## Long-context protocol

The configuration advertises up to one million tokens, but operational support
depends on the serving stack. Test progressively: 32K, 128K, 256K, 512K, then
1M. At each band, record request acceptance, time to first token when available,
total latency, token usage, answer accuracy, and any truncation. A successful
HTTP response is not proof that all input was attended to.

Use multiple retrieval positions and distractor densities. Include tasks that
require combining distant facts, not only retrieving a unique phrase.

## Multimodal protocol

Keep original image dimensions and hashes in local metadata. Evaluate OCR,
chart interpretation, screenshot reasoning, and cross-image synthesis
separately. Do not infer native visual capability from OCR-only success.

## Security

Treat model output as untrusted data. FlashLab graders do not execute arbitrary
generated code in the host process. Code benchmarks should use a disposable,
resource-limited container and a fixture with no secrets or network access.
API credentials require HTTPS except for loopback endpoints; remote plaintext
HTTP requires an explicit risk override.

## Claim policy

Official-paper numbers are reference points, not FlashLab results. A claim moves
from `unverified` to `observed` only when its exact run artifact and suite version
are public. Negative results receive the same preservation and visibility as
positive ones.
