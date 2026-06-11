# Retail Customer Support Agent

Transaction-oriented retail customer support Agent based on tau3-bench retail data.

## Start Here

- [Technical Architecture](./TECHNICAL_ARCHITECTURE.md)

## Phase 0: Baseline Reproduction

Phase 0 is offline-first. It validates the local tau2-bench retail data and
summarizes existing retail benchmark results before any project-specific agent
workflow is built.

### Prerequisites

- Install `uv`: https://docs.astral.sh/uv/getting-started/installation/
- Keep the local tau2-bench checkout available at:

```text
/Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench
```

If your checkout lives elsewhere, copy `.env.example` to `.env` and override
`TAU2_BENCH_ROOT` and `TAU2_DATA_DIR`.

### Offline Checks

Validate the local source and retail data:

```bash
uv run phase0-check
```

Summarize the historical retail baseline result:

```bash
uv run phase0-report \
  --result /Users/theyang/Documents/ai/AgentProject/data_sources/raw/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json
```

Reports are written to `artifacts/phase0/`, which is intentionally ignored by
git.

### Optional Live Smoke Test

Live smoke testing is optional for Phase 0 because it requires provider API
keys and tau2 runtime dependencies. Configure a provider key and model names in
your environment or `.env`, then run:

```bash
uv run phase0-smoke --domain retail --num-tasks 1 --num-trials 1
```

Without an API key, `phase0-smoke` exits successfully with a skipped message.

### Local Unit Tests

```bash
python3 -m unittest discover -s tests
```
