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


## Code Layout

Core implementation is organized by product capability rather than iteration phase:

```text
app/agent/   guarded workflow runtime, prompts, providers, state models
app/tools/   retail adapter, registry, gateway
app/eval/    curated cases, eval runner, failure labels
app/ops/     trace and serialization helpers
app/cli/     chat and eval command entrypoints
prompts/     file-versioned LLM prompts with hash metadata
```

Phase-named CLI commands are kept for roadmap clarity, but the implementation
lives in the capability packages above.

## Phase 1: Guarded Workflow Agent

Phase 1 adds a CLI-first guarded agent runtime. It authenticates the user,
loads retail context, creates pending write actions, requires explicit
confirmation, executes retail tools through a gateway, and writes a replayable
trace artifact.

Run a scripted smoke conversation:

```bash
uv run phase1-chat --script examples/chat/cancel_order.json
```

Configure DeepSeek for the LLM-backed path in local `.env`:

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEFAULT_AGENT_MODEL=deepseek-v4-flash
AGENT_LLM_TIMEOUT_SECONDS=30
AGENT_LLM_MAX_RETRIES=2
```

Then run:

```bash
uv run phase1-chat --script examples/chat/cancel_order.json --require-llm
```

Without `DEEPSEEK_API_KEY`, Phase 1 falls back to deterministic rules so local
tests and guard checks remain offline and repeatable.

Run an interactive session:

```bash
uv run phase1-chat --interactive
```

Trace artifacts are written to:

```text
artifacts/phase1/runs/<run_id>.json
```

## Phase 2: Curated Eval Runner

Run the curated MVP eval subset. It covers lookup, writes, confirmation flows,
guard-blocked policy violations, wrong-user access, and human transfer:

```bash
uv run phase2-eval --subset curated_mvp --trials 1
```

Force the LLM-backed path:

```bash
uv run phase2-eval --subset curated_mvp --trials 1 --require-llm
```

Eval progress is printed to stderr by default so long LLM-backed runs show the
active case and per-case duration without corrupting `--json` stdout. Use
`--no-progress` for quiet machine-driven runs.

Eval summaries are written to:

```text
artifacts/phase2/eval_runs/<eval_run_id>.json
```

Each eval result records dataset paths, code commit, model settings, prompt file
hashes, trace path, initial/final DB hashes, expected guard-block reasons, and
failure labels.
