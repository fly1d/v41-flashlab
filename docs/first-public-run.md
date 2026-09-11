## Goal

Publish the first independently reproducible DeepSeek V4.1 Flash endpoint comparison without turning provider claims into FlashLab results.

## Required evidence

- [ ] Record the exact provider, endpoint region, model id, and model or serving revision.
- [ ] Run the 3-case `smoke` suite before any larger spend.
- [ ] Run `cn-business-v1` against the candidate and one production baseline with identical suite bytes.
- [ ] Use one locked parameter profile per endpoint and at least two attempts per case.
- [ ] Preserve raw JSONL, errors, timeouts, latency, TTFT, token usage, and suite SHA-256.
- [ ] Publish the deployment manifests and a FlashLab-generated comparison report.
- [ ] Include at least one failure or limitation; do not publish only favorable examples.
- [ ] Scrub all secrets, private hostnames, customer data, and non-public prompts before upload.

## Long-context follow-up

After the business suite is reproducible, generate progressive 32K / 128K / 256K cases with `scripts/make_long_context_suite.py`. A 512K-1M result belongs here only after the selected endpoint actually accepts that input and the raw artifact records the effective setup. RULER and graph-walk coverage are not implemented yet.

## Current blocker

A legal DeepSeek V4.1 Flash endpoint, a selected baseline, and an approved API budget are required. No score should be inferred from this issue while those inputs are missing.

Contributions can use the **Submit reproducible benchmark result** issue form.
