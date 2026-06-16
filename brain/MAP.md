# MAP — 项目地图

> **这份文件回答**："项目长什么样？想找某个信息应该去哪？"
>
> **特性**：随项目结构演进。只到**模块级粒度**，不涉及具体函数 / 文件细节。
> 细节属于 `brain/topics/` 下的专题文档。
>
> **谁该读**：**每次新会话第一个读的**。

---

## 1. 快速开始

> 给新会话醒来后最快的接入路径。只放"让项目跑起来"的最小指令，不做详细说明。
> 完整运维细节在 `brain/topics/operations/`。

**启动项目**：
```bash
# 安装依赖
uv sync --extra dev

# 启动 Workbench（需 DEEPSEEK_API_KEY）
uv run workbench &                    # Python API → :8765
cd workbench && npm install && npm run dev  # React 界面 → :5173
```

**关键入口 / 端口**：
- Workbench 前端：`http://localhost:5173`
- Workbench API：`http://localhost:8765`
- 需要 `DEEPSEEK_API_KEY` 环境变量（在 `.env` 中配置）

**状态验证 / 健康检查**：
```bash
# 跑全量测试（无需 API key）
uv run python -m pytest tests/ -v

# Lint 检查
uv run ruff check .
```

## 2. 模块清单

> 当前项目有哪些模块、各自职责、当前状态。模块级，不下钻到文件。

| 模块 | 职责 | 状态 | 主要位置 |
|---|---|---|---|
| Agent Core | AgentLoop 运行时、LangGraph 状态机、LLM Provider、Prompt 管理、确认解析、写护栏 | 稳定 | `app/agent/` |
| Tool Layer | 工具注册表、ToolGateway 护栏门控、RetailAdapter（tau2/local fallback） | 稳定 | `app/tools/` |
| Eval | curated/generalized 案例、eval runner、失败分类、live triage、baseline 对比 | 稳定 | `app/eval/` |
| Workbench | FastAPI 后端 + React 前端，交互式案例体验 + AgentOps 可视化 | 稳定 | `app/workbench/` + `workbench/` |
| Ops | TraceWriter 追踪、序列化（stable_hash） | 稳定 | `app/ops/` |
| Synthetic | LLM 生成的多样化 eval 案例、语言变体 | 稳定 | `app/synthetic/` |
| Analysis | tau task 空间分析 | 稳定 | `app/analysis/` |
| CLI | phase1-chat、phase2-eval 命令行入口 | 稳定 | `app/cli/` |
| Config | AppConfig 配置加载（.env + 默认值） | 稳定 | `app/config.py` |
| Prompts | LLM agent 系统提示词（版本化 Markdown） | 稳定 | `prompts/` |
| Tests | 20 个测试文件覆盖 agent core、eval、workbench、tools | 稳定 | `tests/` |
| Docs | 设计文档、架构参考、实施计划、审计报告 | 演进中 | `docs/` |

## 3. 模块依赖关系

```
CLI (chat/eval) → AgentRuntime → LangGraph StateGraph (12 nodes)
                                    ├── LLMProvider (DeepSeek)
                                    ├── PromptManager
                                    ├── ConfirmationResolver
                                    ├── WriteActionGuard
                                    └── ToolGateway → ToolRegistry → RetailAdapter
                                                                      ├── tau2-bench runtime
                                                                      └── LocalRetailTools (fallback)

EvalRunner → AgentRuntime (per case) → TraceWriter → artifacts/

Workbench API → AgentRuntime → TraceWriter
Workbench UI → Workbench API (REST)
```

关键数据流：`user message → pre-flight → AgentLoop → ToolGateway/Guard → tool → observation → response → trace`

## 4. 接续层 5 份核心（`brain/` 直接子文件）

> 新会话先读 MAP 和 STATUS，存在 HANDOFF 也读，其余按需。

| 文件 | 回答什么 | 何时读 |
|---|---|---|
| `PROJECT.md` | 初衷、非目标 | 首次接触、范围模糊时 |
| `MAP.md` | 模块结构、文档索引 | 每次会话 |
| `STATUS.md` | 当下状态、下一步 | 每次会话 |
| `HANDOFF.md` | 上个会话切窗口的最新交接 | 每次会话（如果存在） |
| `DECISIONS.md` | 历史决策 | 追溯某个设计原因时 |

`handoffs/` —— 历史 HANDOFF 归档目录。

## 5. 专题文档（`brain/topics/`）

> 按类别分组。"**何时读**"列是关键 —— 告诉未来的读者触发条件，不需要每次都全部读。
> 不维护"最后更新"列 —— 协议保证文件最新；如果真的要查，用 `git log -1 --format=%ad <path>`。

### systems/（系统设计专题）
| 文件 | 是什么 | 何时读 |
|---|---|---|
| 写护栏 7 层设计 | `WriteActionGuard` 的完整护栏链：认证→确认→所有权→先读后写→策略→锁→幂等 | 修改 guard.py、新增写操作、护栏行为异常时 |
| AgentLoop 运行时 | AgentRuntime + LangGraph 12 节点 pipeline 的完整流程 | 修改 graph.py/runtime.py、调试 Agent 流程时 |
| ToolGateway 调用链 | 工具注册→查找→参数校验→护栏→执行→审计的 14 步链路 | 修改 gateway.py、新增工具类型时 |
| Eval 体系 | curated_mvp/generalized_mvp、失败分类 14 标签、指标定义 | 新增 eval case、调试 eval 失败时 |

### operations/（运维 / 流程类）
| 文件 | 是什么 | 何时读 |
|---|---|---|
| 环境配置 | .env、API key、tau2-bench 路径、模型选择 | 首次 setup、切换环境时 |
| 发版流程 | commit 规范、分支策略、PR 流程 | 准备提交、发 PR 时 |
| 常用调试命令 | pytest 筛选、单 case 调试、trace 查看 | 遇到测试失败需要定位时 |

### planning/（计划 / 路线图）
| 文件 | 是什么 | 何时读 |
|---|---|---|
| 长期优化路线 | 项目长期优化路径的 topic 摘要（源文档：docs/long-term-optimization-path.md） | 规划下阶段工作、评估优先级时 |
| 架构演进记录 | Phase 0-12 各阶段的架构决策和变更 | 理解"为什么现在长这样"时 |

### feedback/（反馈 / 追踪）
| 文件 | 是什么 | 何时读 |
|---|---|---|
| Eval 结果趋势 | 各阶段 eval pass rate、failure 分布变化 | 回顾项目进展、准备展示时 |
| 已知问题 | 当前未解决但非阻塞的 bug / 设计缺陷 | 评估"能不能修"时 |

---

## 6. 工作流清单（v2.1，仅多工作流项目填）

> **本节只在多工作流项目里填** —— 单工作流项目这一节可保留为空或删除。

本项目当前为**单工作流**模式，暂无并行工作流。

---

## 7. MAP 自我校准

> MAP 最大的敌人是陈旧。这份文件必须有主动维护机制。

**触发更新的场景**：
- 模块新增 / 删除 / 状态变化 → 更新第 2 节（模块清单）
- 模块**大的结构变化**（重构、引入新子系统）→ 更新第 2、3 节
- 新文档加入 / 删除 / 大改 → 更新第 5 节
- 启动命令变化 → 更新第 1 节（快速开始）

**MAP 校准扫描**（不自动跑，由用户触发或 AI 主动提议）：
- 扫描 `brain/topics/`：发现文件存在但 MAP 第 5 节里未登记 → 报告"未登记文件"
- 扫描 MAP 登记项：发现登记了但文件不存在 → 报告"失效条目"
- 发现 MAP 条目描述和实际内容明显不符 → 报告"条目漂移"
- **触发时机**：
  - 用户说"MAP 校准 / 整理项目记忆"时
  - 完成某个大的模块改动之后（AI 主动提议跑校准）
