# 检测层收敛与多语言泛化：工程 Spec

> 日期: 2026-06-27
> 状态: 设计阶段（待审批）
> 第一性需求: 提高 agent 泛化能力——无论语言、无论表达方式都能正确处理
> 关联: [原文档](./2026-06-27-semantic-layer-architecture.md)（保留作对照，本 spec 取代其方向）
> 关联: [AGENTS.md](/AGENTS.md) — Intent Detection / Prompt Injection / Guard

---

## 0. TL;DR

| | 原文档（加 SemanticDetector LLM） | 本 spec（收敛 + 主 LLM fall through） |
|---|---|---|
| 每轮新增 LLM 调用 | +1~2 | **0**（仅注入 secondary 在 regex miss 时触发，罕见） |
| 延迟 | +~1s/turn | +0 |
| 对英文 100% 基线风险 | 高（新故障面 + GATE 交 LLM） | **低**（P0 纯搬运零行为变化） |
| GATE 安全 | confirmation/transfer 交给 LLM | **确定性优先，LLM 仅 unknown 兜底** |
| 加一门语言改动 | 0（LLM 自动） | 1~2 处收敛后的 pattern |
| 泛化引擎 | 新加的 semantic LLM | **主 LLM 本身（已多语言，免费）** |

**核心反直觉点**：本系统主循环就是一个带 tool-calling 的 LLM，它已经在做意图分类。原文档要加的 `analyze()` LLM 调用与主 LLM 工作高度重叠——重复付费。真正的痛点是**正则散落**（维护性问题），不是**正则本身**（能力问题）。收敛即可，无需 LLM 化。

---

## 1. 问题重新定义

### 1.1 原文档的诊断偏差

原文档 §1 把"加语言改 6+ 文件"归因于"用正则做语义检测"。**归因错了**：
- 散落是问题 → **收敛解决**
- 正则做语义是问题 → **不成立**，主 LLM 已覆盖语义，正则只是快路径

### 1.2 正确的诊断

把当前 6 处检测按"谁该负责泛化"重新分类：

| 检测点 | 性质 | 状态依赖 | 正则是否胜任 | 泛化谁负责 |
|--------|------|---------|------------|-----------|
| 格式提取(order_id/email/item_id/zip/payment_method_id) | 数据 | 无 | ✅ 天然语言无关 | 正则（格式不变） |
| 意图分类(哪个写工具) | HINT | 无 | ⚠️ 英文够用 | **主 LLM 的 tool-call** |
| 身份-邮箱 | 数据 | 无 | ✅ 格式无关 | 正则 |
| 身份-姓名邮编 | 触发认证 | 无 | ⚠️ 英文句式 | 主 LLM 的 `find_user_id_by_name_zip` 工具（⚠️ 撞数据模型墙，见 §1.3） |
| 转人工 | **控制 GATE** | 无 | ✅ | 正则（确定性优先） |
| 确认解析 | **控制 GATE** | 无 | ✅ 已中英双语 | 正则（已精调，不动） |
| 注入检测 | **安全 GATE** | 无 | ✅ 已知模式 / ❌ 中文是缺口 | 正则 PRIMARY + LLM secondary |
| 拒绝纠正 | 编排 | **有**（查 loaded orders） | 仅其中 1 步 | **留在 AgentLoop**（有状态编排） |

### 1.3 数据模型墙（检测层翻不过）

`find_user_id_by_name_zip` 工具契约要 `first_name`/`last_name`——这是**英文名数据模型**。中文"张三"→姓张名三，塞进 first/last 就是错配。**无论正则还是 LLM 提取都救不了**，得改工具契约/schema，不在本 spec 范围。本 spec 只保证：非英文身份正则 miss 时，**优雅 fall through 到主 LLM**，由主 LLM 调工具兜底（主 LLM 天然多语言）。

### 1.4 GATE vs HINT（原文档最大的安全错误）

原文档 §5.3 把所有字段一概称"HINT，主 Loop 兜底"。逐字段看：

| 字段 | 实际作用 | 性质 | LLM 误判后果 |
|------|---------|------|------------|
| `intent` | 喂给 ActionCandidate HINT | ✅ HINT | 主 LLM 兜底 |
| `email/name/zip` | 触发幂等认证 lookup | ⚠️ 半 GATE | lookup 幂等，低危 |
| `human_transfer` | 短路并结束 turn 转人工 | ❌ **GATE** | 误转人工终止 turn，无兜底 |
| `confirmation` | 决定 pending write 执行/丢弃 | ❌ **GATE** | 误判 confirmed=执行本该取消的写；误判 denied=丢弃用户刚确认的写 |

`confirmation` 已是中英双语精调（`confirmation.py`，AGENTS.md 警告 `confirm<2` 守卫不能动）。塌成 LLM 一个字段 = 把写操作的执行/放弃交给模型随机性，**且无兜底层**。本 spec：GATE 字段**确定性优先**，LLM 只在正则返回 `unknown` 时兜底，绝不主导。

---

## 2. 架构：三层收敛，不加 LLM 调用

```
┌─ Layer 0  extraction.py（NEW）──────────────────────┐
│  纯格式正则，语言无关。从 parsers.py / action_candidates 收敛 │
│  extract_order_id / email / item_ids / payment_method_id / zip │
│  ★ 加语言 = 0 改动（格式不随语言变）                          │
└──────────────────────────────────────────────────────┘
┌─ Layer 1  action_candidates.py（瘦身）────────────────┐
│  保留现有 regex intent，只做 HINT。order_id/item_ids 用 Layer 0 │
│  ★ 加语言 = 给这一个模块加 pattern（intent 权威仍是主 LLM）   │
└──────────────────────────────────────────────────────┘
┌─ Layer 2  security.py（NEW）──────────────────────────┐
│  injection:  正则 PRIMARY（不变）                              │
│              + 可选 LLM secondary，仅 severity=high 且正则未    │
│                命中才采纳（防假阳误 block 合法写）              │
│  transfer:   合并 runtime.py / llm_agent.py 的重复正则为 1 个  │
│  ★ GATE 永远确定性优先，LLM 仅在 unknown 兜底                 │
└──────────────────────────────────────────────────────┘
     ConfirmationResolver（不动——已中英双语精调 GATE）
     编排逻辑（premature refusal / force_write）留在 AgentLoop
```

### 2.1 调用流（与现状拓扑一致，只是模块收敛）

```
runtime.handle_user_message
  ├ _preflight_confirmation → ConfirmationResolver（不动）
  ├ _preflight_identity     → extraction.email / 主 LLM 工具兜底
  └ _preflight_human_transfer → security.transfer（合并后）

AgentLoop.run_turn
  ├ detect_action_candidate → action_candidates（用 Layer0 + Layer1）
  ├ _record_prompt_injection_signals → security.injection
  └ _detect_premature_refusal → 留在 AgentLoop（有状态编排）
```

**无新增 LLM 调用**。注入 secondary 仅在 regex miss 时触发（罕见路径）。

---

## 3. 逐模块 API 设计

### 3.1 `app/agent/extraction.py`（NEW — Layer 0）

```python
"""纯格式提取正则。语言无关，格式不随语言变化。"""
from __future__ import annotations
import re
from app.agent.guard import _canonical_order_id

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# 订单 ID：#?(?:W)?\d{7,} → 规范化 #W\d+（复用 guard 归一化）
_ORDER_ID_RE = re.compile(r"#?(?:W)?(\d{7,})", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"\b(\d{8,10})\b")
_PAYMENT_METHOD_RE = re.compile(r"\b(gift_card_\d+|credit_card_\d+|paypal_\d+)\b")
_ZIP_RE = re.compile(r"\b(\d{5}(?:-\d{4})?)\b")
# 英文 name+zip 句式快路径；非英文 miss → fall through 主 LLM 工具
_NAME_ZIP_RE = re.compile(
    r"(?:my name is|i am|i'm)\s+([A-Za-z]+)\s+([A-Za-z]+).*?"
    r"\bzip(?:[ -]?code)? is\s+(\d{5}(?:-\d{4})?)",
    re.IGNORECASE,
)

def extract_order_id(text: str) -> str | None:
    """提取首个订单 ID 并规范化为 #W\\d+。无则 None。"""
    m = _ORDER_ID_RE.search(text)
    return _canonical_order_id(m.group(0)) if m else None

def extract_email(text: str) -> str | None: ...
def extract_item_ids(text: str) -> list[str]: ...
def extract_payment_method_id(text: str) -> str | None: ...
def extract_zip(text: str) -> str | None: ...
def extract_name_zip(text: str) -> tuple[str, str, str] | None: ...
```

**迁移来源**：`parsers.py` 的 `EMAIL_RE`/`NAME_ZIP_RE`、`action_candidates.py` 的 `_EXPLICIT_ORDER_ID_RE`/`_ORDER_CONTEXT_ID_RE`、`llm_agent.py` 的内联 `\b(\d{8,10})\b` 与 `payment_method` 正则。

### 3.2 `app/agent/action_candidates.py`（MODIFY — Layer 1，瘦身）

- 保留 `_CANCEL_RE` 等 intent 正则（瘦身但保留，作 HINT）。
- `_extract_order_id` → 调 `extraction.extract_order_id`。
- `_selected_item_ids` 的价格比较逻辑**保留**（数据层面，语义无关）。
- `_allows_loaded_order_fallback` 的内联正则保留或迁 Layer 0（按需）。
- **加中文 pattern**（P2）：如 `_CANCEL_RE` 加 `取消.*订单`、`_RETURN_RE` 加 `退货`。集中在此一处。

> ⚠️ intent 权威仍是主 LLM 的 tool-call。正则 HINT 只在命中时给主 LLM 一个 nudge（见 `llm_agent.py:1761-1780`），miss 时主 LLM 自行决策——这就是泛化兜底。

### 3.3 `app/agent/security.py`（NEW — Layer 2）

```python
"""安全与控制 GATE 检测。确定性优先，LLM 仅在 regex unknown 时兜底。"""
from __future__ import annotations
from typing import Any
from app.agent.providers import LLMProvider

# ── 注入：正则 PRIMARY（从 llm_agent.py 迁移，不变） ──
INJECTION_PATTERNS: list[tuple[str, str, re.Pattern]] = [...]  # 原 _PROMPT_INJECTION_PATTERNS

# ── 转人工：合并 runtime.py / llm_agent.py 两个逐字符相同的正则 ──
HUMAN_TRANSFER_RE: re.Pattern = re.compile(...)  # 原 _HUMAN_TRANSFER_RE（单份）

HIGH_RISK_PATTERN_IDS = {
    "instruction_override", "system_prompt_exfiltration",
    "role_rebinding", "tool_bypass_or_forcing", "secret_request",
}

def detect_injection_signals(
    text: str,
    *,
    source: str,
    provider: LLMProvider | None = None,
) -> list[dict[str, Any]]:
    """注入检测：正则 PRIMARY + 可选 LLM secondary。

    LLM secondary 仅在 (a) provider 可用 且 (b) 正则未命中 high-risk
    时才采纳，且只采纳 severity=high 的判定——防止 LLM 把正常客服话
    误判 injection 进而误 block 合法写操作（英文 100% eval 退步风险）。
    """
    signals = _regex_injection_signals(text, source=source)
    if provider is not None and not any(
        s["severity"] == "high" for s in signals
    ):
        # 仅在正则未命中 high-risk 时调 LLM（罕见路径）
        llm_result = _llm_injection_secondary(text, provider)  # 带超时
        if llm_result and llm_result.get("is_injection") and llm_result.get("severity") == "high":
            signals.append({
                "source": source,
                "pattern_id": "llm_secondary",
                "severity": "high",
                "matched_text": llm_result.get("reason", "")[:120],
            })
    return signals

def is_explicit_human_transfer(text: str) -> bool:
    """转人工 GATE。正则确定性判断，不交给 LLM。"""
    return bool(HUMAN_TRANSFER_RE.search(text))
```

### 3.4 `ConfirmationResolver`（不动）

已是中英双语精调 GATE。本 spec **一行不动**。`confirm<2` 守卫（`confirmation.py:147-151`）受 AGENTS.md 警告保护。

### 3.5 编排逻辑（留在 AgentLoop，不提取）

`_detect_premature_refusal`（`llm_agent.py:1910-1951`）是**三阶段有状态编排**：
1. refusal 正则匹配（这步是"检测"）
2. `plausible_refusal`：遍历 `session.loaded_context.orders` 校验 ownership/终态（**依赖 session 状态**）
3. `_WRITE_INTENT_MAP` 反查 user 消息意图 → 映射 tool_name

`_force_write_tool_call`（`llm_agent.py:1953-2124`）按工具逐个正则提取参数。二者**都不是无状态检测**，留在 AgentLoop。仅第 1 步的 refusal 正则可迁 `security.py` 复用，但编排整体不动。

### 3.6 `app/agent/parsers.py`（瘦身）

`EMAIL_RE`/`NAME_ZIP_RE` 迁出后，`parsers.py` 仅留 `clean_llm_scalar`/`clean_llm_list`。保持文件作为纯函数工具，或并入 `extraction.py`（按实现偏好，spec 不强求）。

---

## 4. Provider 能力前置（仅注入 secondary 需要）

注入 LLM secondary 需要 per-call 短超时，否则降级路径形同虚设。**当前 `DeepSeekProvider` 不支持 per-call timeout/max_tokens**（`providers.py:222-232` 单 client 级 30s timeout，`json()/chat()` 无形参）。

### 4.1 改动（P1，最小）

```python
# providers.py — LLMProvider 协议加可选形参
class LLMProvider(Protocol):
    def json(
        self, messages, schema, *, timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]: ...
    def chat(
        self, messages, *, timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...
```

`DeepSeekProvider` 实现透传 OpenAI SDK 的 per-request `timeout=`。`max_tokens` 透传到 `chat.completions.create`。

> 注：本 spec **不**需要原文档 §4 那种全局短超时（因为没有每轮 analyze 调用）。只有注入 secondary 这一个罕见路径需要 3s 短超时保护。

---

## 5. 多语言策略

| 检测点 | 多语言方案 | 改动量 |
|--------|-----------|--------|
| 格式提取 | 格式无关，0 改动 | 0 |
| 意图 HINT | Layer 1 加中文 pattern；miss → 主 LLM 兜底 | 1 模块 |
| 身份-邮箱 | 格式无关 | 0 |
| 身份-姓名邮编 | 英文正则快路径；非英文 miss → 主 LLM 调 `find_user_id_by_name_zip`（撞数据模型墙见 §1.3） | 0（+ 改工具契约，另案） |
| 转人工 | Layer 2 合并正则加中文 pattern | 1 处 |
| 确认 | 已中英双语 | 0 |
| 注入 | 正则加中文 pattern（如 `忽略|无视`）+ LLM secondary 自动覆盖 | 1 处 + LLM 自动 |

**加一门语言总改动：2~3 处 pattern**（集中在 Layer 1 + Layer 2），意图泛化靠主 LLM 零改动。对比原文档"0 改动但每轮 +1 LLM"——本 spec 用少量 pattern 换 0 额外 LLM 调用。

---

## 6. 分阶段交付

### P0 — 纯收敛重构（零行为变化，保护英文 100% 基线）

| 文件 | 操作 | 变更 |
|------|------|------|
| `app/agent/extraction.py` | **NEW** | Layer 0 格式正则收敛 |
| `app/agent/security.py` | **NEW** | 注入正则 + 合并转人工正则（无 LLM secondary） |
| `app/agent/parsers.py` | MODIFY | EMAIL_RE/NAME_ZIP_RE 迁出 |
| `app/agent/action_candidates.py` | MODIFY | order_id 提调 Layer 0；intent 正则保留 |
| `app/agent/llm_agent.py` | MODIFY | 删 `_PROMPT_INJECTION_PATTERNS`/`_EXPLICIT_HUMAN_TRANSFER_RE`/`_WRITE_KEYWORD_PATTERNS`（死代码）；注入检测调 `security`；refusal 正则可迁 `security` 复用，编排留原处 |
| `app/agent/runtime.py` | MODIFY | 删 `_HUMAN_TRANSFER_RE`，调 `security.is_explicit_human_transfer` |

**验收**：`uv run phase2-eval --subset generalized_mvp --live` 保持 100%；`uv run python -m pytest tests/ -v` 全绿。零新增 LLM 调用。

### P1 — 注入 LLM secondary（堵中文安全洞）

| 文件 | 操作 | 变更 |
|------|------|------|
| `app/agent/providers.py` | MODIFY | `json()/chat()` 加 `timeout`/`max_tokens` 形参 |
| `app/agent/security.py` | MODIFY | `detect_injection_signals` 加 LLM secondary，带假阳守卫（§3.3） |
| `app/config.py` | MODIFY | `injection_llm_secondary: bool = False`、`injection_llm_timeout: float = 3.0` |

**go/no-go 门槛**：先造中文注入 eval case（§7），验证 LLM secondary 在中文注入上命中、在英文正常写上不假阳，再默认开启。默认 `False` 保持英文基线不变。

### P2 — 多语言 pattern + 中文 eval subset

| 文件 | 操作 | 变更 |
|------|------|------|
| `app/agent/action_candidates.py` | MODIFY | intent 正则加中文等价 pattern |
| `app/agent/security.py` | MODIFY | 注入正则加中文 pattern（如 `忽略\|无视`） |
| `app/eval/` | NEW | 中文 eval subset（复用 `app/synthetic/generator.py` 语言变体） |

**go/no-go 门槛**：出现多语言需求或 ≥1 个中文失败 case 时开启。P2 必须有中文 eval subset 才能验证不回归。

---

## 7. eval 与验证（任何方案的前置）

### 7.1 前置归因（验证瓶颈在正则层）

拉 `synthetic_seeded_v1` 那 43% 失败 case（AGENTS.md 基线 57%）归因：
- 正则预检 miss → 本 spec P0/P2 修
- 主 LLM 调错工具/错误拒绝 → 改 prompt/schema/模型，非检测层
- 工具 schema 硬伤 → 改工具契约

**这是验证本 spec 匹配真实瓶颈的最后一块证据。**

### 7.2 中文 eval subset 构造

复用 `app/synthetic/generator.py` 的语言变体能力生成中文 golden。无此 subset，多语言收益不可度量，P1/P2 不得默认开启。

### 7.3 测试矩阵

| 测试对象 | 方法 | 覆盖 |
|---------|------|------|
| `extraction.py` | 参数化，格式提取中英文 case | 10+ |
| `security.detect_injection_signals` regex | 原 `INJECTION_PATTERNS` case 回归 | 6 |
| `security.is_explicit_human_transfer` | 合并后中英文 case | 8 |
| `security` LLM secondary | mock provider，验证假阳守卫（正常写不 block） | 5 |
| `action_candidates` | 原 case 回归 + 中文 intent | 10+ |
| E2E | `generalized_mvp` live eval 保持 100% | 现有 |
| Flywheel golden | 中英文 case 回归 | 需 §7.2 |

---

## 8. 故障模式矩阵

| 故障模式 | 表现 | 用户感知 | 影响范围 |
|---------|------|---------|---------|
| 注入 LLM secondary 超时 | → 仅正则结果 | 无（正则已跑） | `detect_injection_signals` |
| 注入 LLM secondary 假阳 | **被假阳守卫拦**（仅 high+regex未命中采纳） | 无 | `detect_injection_signals` |
| 注入 LLM secondary 误判 non-high | 不采纳 | 无 | `detect_injection_signals` |
| 主 LLM 超时 (30s) | 现有 TimeoutError 处理 | 同当前 | AgentLoop |
| 中文意图正则 miss | → 主 LLM tool-call 兜底 | 正常处理，丢 HINT nudge | action_candidates |
| 中文身份正则 miss | → 主 LLM 调 `find_user_id_by_name_zip` | 正常（撞墙见 §1.3） | runtime 预检 |
| confirmation 误判 | **不发生**（确定性正则，未 LLM 化） | — | — |
| transfer 误判 | **不发生**（确定性正则） | — | — |

对比原文档：本 spec **没有** "LLM analyze 超时降级"/"LLM 返回非法 JSON"/"LLM 误判 confirmed 执行写" 这些故障模式——因为不引入它们。

---

## 9. 待决策

- [ ] P0 是否立即开工（纯重构零风险，建议立即）
- [ ] P1 LLM secondary 用哪个 provider：与主 LLM 共用，或配小模型（如 Ollama qwen3.5:2b，~200-500ms）
- [ ] 中文姓名邮编的数据模型墙是否另案修工具契约（`find_user_id_by_name_zip` 加 `full_name` 可选参数？）
- [ ] P2 中文 eval subset 规模与覆盖范围

---

## 10. 与原文档的取舍说明

原文档（`2026-06-27-semantic-layer-architecture.md`）保留作对照。本 spec 取代其方向，原因：

1. **泛化引擎重复付费**：原文档 `analyze()` LLM 与主 LLM 的 tool-call 意图分类重叠
2. **GATE 安全错误**：原文档 §5.3 把 confirmation/transfer 也当 HINT 交 LLM，无兜底层
3. **Provider 前置悬空**：原文档 §4/§5 依赖 per-call 3s timeout + max_tokens 300，当前 provider 不支持
4. **有状态编排误当无状态检测**：原文档把 `_detect_premature_refusal`/`_force_write_tool_call` 当检测塞进 SemanticDetector
5. **延迟成本无对应收益**：英文 100% 基线上 +1s/turn，换不被现有 eval 度量的多语言能力

本 spec 承接原文档的正确部分（注入的 regex PRIMARY + LLM secondary、正则收敛降维护成本），丢弃错误部分（每轮 analyze LLM、GATE 交 LLM）。
