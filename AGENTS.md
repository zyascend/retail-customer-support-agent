# AGENTS.md

> Read by ZCode, Claude Code, and other AI coding agents on session start.

## On session start

1. Read `HANDOFF.md` — latest session progress, eval baselines, next steps
2. Skim this file for conventions and commands

## Conventions

- **文档语言**: 中文，API 名称/代码标识符/命令保留英文
- **Commit**: `<type>: 中文描述` — type: feat/fix/chore/docs/refactor/test
- **分支**: `git checkout -b <branch>`，合并后删除

## Commands

```bash
uv sync --extra dev                    # 安装依赖
uv run python -m pytest tests/ -v      # 全量测试
uv run ruff check .                    # lint
uv run phase1-chat                     # CLI 对话
uv run phase2-eval --subset generalized_mvp --live --max-workers 50  # 跑 eval
```

## Architecture (概览)

```
user message → AgentRuntime → AgentLoop → ToolGateway / WriteActionGuard
→ tool observation → assistant response → trace artifact
```

- **入口**: `app/agent/runtime.py` — `AgentRuntime.handle_user_message()`
- **Agent loop**: `app/agent/llm_agent.py` — `AgentLoop.run_turn()`
- **7 层写安全 Guard**: `app/agent/guard.py` — `WriteActionGuard.check()`
- **工具注册**: `app/tools/registry.py`
- **Prompt**: `prompts/llm_agent_system_v001.md`
- **Eval**: `app/eval/runner.py` — 151 cases across 4 subsets
- **配置**: `app/config.py` — `AppConfig` from `.env`

## Update protocol

HANDOFF.md is auto-updated by `/pr` and `/prm`. No manual edits needed.
