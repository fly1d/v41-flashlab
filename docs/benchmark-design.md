# Benchmark design references

V41 FlashLab is intentionally smaller than general-purpose evaluation
frameworks. Its structure follows mature conventions where they improve audit
quality, while staying dependency-light enough to run against a newly available
endpoint on launch day.

## Patterns adopted

| Reference | Mature pattern | FlashLab implementation |
| --- | --- | --- |
| Inspect AI | Separate dataset, solver, and scorer; preserve sample-level logs | Suites define samples and scorers, the OpenAI-compatible client is the solver, and each attempt is one JSONL record |
| lm-evaluation-harness | Declarative task configuration, task discovery, provider-neutral model layer | JSON/YAML suites, `validate`/`list`, and an OpenAI-compatible endpoint adapter |
| HELM | Holistic reporting beyond accuracy and drill-down to individual requests | Pass rate, errors, latency, TTFT and token use remain separate; the report exposes raw samples |
| LiveBench | Objective ground truth, contamination awareness, versioned releases | Synthetic launch-day data, deterministic graders, explicit versions and provenance |
| LongBench | Report by context-length band and distinguish retrieval from reasoning | Generated 32K–1M suites carry requested and API-reported length metadata and require combining distant facts |
| SWE-bench | Real tasks, executable verification, isolated environments, retained logs | The roadmap reserves coding claims for repository tasks graded in disposable containers; toy code cases are labeled smoke tests |

These projects are references, not dependencies, and their names do not imply
endorsement. Third-party benchmark data is not redistributed here.

## Evaluation object model

```text
registry
  suite (versioned task configuration)
    sample (stable id + input + target + metadata)
      attempt / epoch
        request -> response -> scorer -> metrics -> error
  run manifest
    endpoint + model + parameters + timestamps + harness version
  report
    aggregate -> suite -> track -> sample drill-down
```

The separation matters. A provider timeout is not a wrong answer, a model name
is not an endpoint configuration, and a score without its sample trace is not
publishable evidence.

## Deliberate launch-day constraints

- No model judge in the default suite. It adds cost, variance, and another model
  dependency before the baseline is stable.
- No arbitrary host-side code execution. Repository tasks will use disposable
  containers when added.
- No live tool execution or multi-step Agent score. The bundled `agent` track
  is a single-turn action-intent and schema-compliance check.
- No composite leaderboard score. Workload owners must choose their own hard
  gates and weights.
- No claim of contamination-free public academic data. Initial suites are new,
  synthetic fixtures with objective answers.
- No silent retries or hidden sample deletion. Every attempt and error remains
  visible in the run artifact.

## Release rules

1. Suite ids and sample ids are stable within a release.
2. Any target, prompt, or scorer change increments the suite version.
3. Published runs include the suite hash and exact model-endpoint settings.
4. A release note states added, changed, and retired samples.
5. Public scores show numerator, denominator, epoch count, and error count.
6. Cases suspected of contamination remain available but are excluded from the
   primary view with a recorded reason.

## Upstream references

- Inspect AI: <https://inspect.aisi.org.uk/>
- lm-evaluation-harness: <https://github.com/EleutherAI/lm-evaluation-harness>
- HELM: <https://github.com/stanford-crfm/helm>
- LiveBench: <https://github.com/LiveBench/LiveBench>
- LongBench: <https://github.com/THUDM/LongBench>
- SWE-bench: <https://github.com/princeton-nlp/SWE-bench>
