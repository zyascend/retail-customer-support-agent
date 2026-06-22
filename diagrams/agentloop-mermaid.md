# AgentLoop Mermaid 图解

> 本文件包含 AgentLoop 完整流程的 Mermaid 图表，可直接在 GitHub、GitLab 或任意支持 Mermaid 的 Markdown 预览中渲染。

---

## 1. 整体架构概览

```mermaid
flowchart TB
    subgraph 用户["👤 用户层"]
        UserMsg["用户消息"]
        UserConfirm["用户确认/拒绝"]
    end

    subgraph 运行时["⚙️ AgentRuntime"]
        Preflight["Pre-flight 预处理"]
        Confirmation["ConfirmationResolver\n关键词确认解析"]
        Identity["身份快速提取\n(email / 姓名+邮编)"]
    end

    subgraph 循环["🔄 AgentLoop 核心循环"]
        direction TB
        LLM["LLM.chat_with_tools()\nDeepSeek + tool schemas"]
        Parse["解析 tool_calls"]
        HasTools{"有 tool calls?"}
        PrematureRefusal{"Premature Refusal\n安全网检测?"}
        ForceWrite["强制注入 write tool 调用\n绕过 LLM 过早拒绝"]
        Finalize["_step_finalize()\n后处理修正 ×5"]
        Execute["ToolGateway.execute()"]
    end

    subgraph 安全层["🛡️ WriteActionGuard 7层守卫"]
        Guard1["1. Known Action"]
        Guard2["2. Authentication"]
        Guard3["3. Ownership"]
        Guard4["4. Read-before-Write"]
        Guard5["5. User Confirmation"]
        Guard6["6. Policy Validation"]
        Guard7["7. Resource Locking"]
    end

    subgraph 工具层["🔧 Tool 执行"]
        ReadTools["Read Tools\nget_order_details 等"]
        WriteTools["Write Tools\ncancel/return/exchange 等"]
        AutoLoad["Auto-Load\nread-before-write 自动补齐"]
    end

    subgraph 数据层["📦 数据"]
        DB["tau3-bench DB\ndb.json"]
        Context["SessionState\nloaded_context"]
        Trace["TraceWriter\n全链路审计"]
    end

    UserMsg --> Preflight
    Preflight --> Confirmation
    Confirmation -->|confirmed| Execute
    Confirmation -->|denied/changed| UserMsg
    Preflight --> Identity
    Identity --> Execute
    
    Preflight --> LLM
    LLM --> Parse
    Parse --> HasTools
    
    HasTools -->|无 tool calls| PrematureRefusal
    PrematureRefusal -->|是| ForceWrite
    PrematureRefusal -->|否| Finalize
    ForceWrite --> LLM
    
    HasTools -->|有 tool calls| Execute
    
    Execute -->|write| Guard1
    Guard1 --> Guard2 --> Guard3 --> Guard4 --> Guard5 --> Guard6 --> Guard7
    Guard7 -->|通过| WriteTools
    Guard5 -->|需要确认| UserConfirm
    
    WriteTools --> Context
    ReadTools --> Context
    ReadTools --> DB
    WriteTools --> DB
    
    Execute -->|read| ReadTools
    
    Execute -->|read-before-write 屏蔽| AutoLoad
    AutoLoad --> ReadTools
    AutoLoad --> Execute
    
    Execute --> Trace
    
    Execute -->|blocked / success / error| LLM
    
    Finalize -->|返回结果| 用户

    linkStyle default stroke:#666,stroke-width:1.5px
```

---

## 2. AgentLoop 内循环状态机 (核心)

```mermaid
stateDiagram-v2
    [*] --> LLMReason: loop 开始 (max 14 轮)
    
    LLMReason --> ParseToolCalls: LLM 返回
    
    ParseToolCalls --> NoToolCalls: 无 tool_calls
    ParseToolCalls --> HasToolCalls: 有 tool_calls
    
    NoToolCalls --> PrematureRefusalCheck: 检查是否过早拒绝
    PrematureRefusalCheck --> ForceWriteInject: 检测到拒绝模式\n(ownership/status-based)
    PrematureRefusalCheck --> NormalFinalize: 无拒绝\n→ 后处理修正
    ForceWriteInject --> LLMReason: 注入强制 write 调用后重试
    
    NormalFinalize --> [*]: 返回最终回复
    
    HasToolCalls --> NormalizeArgs: 归一化参数\n(order_id → #W格式)
    NormalizeArgs --> EnrichBatch: 同订单商品批量增强
    EnrichBatch --> ToolExecutePerCall: 逐 call 执行
    
    ToolExecutePerCall --> GuardBlock: write 被 guard 拦截
    ToolExecutePerCall --> GuardAllow: write 通过 guard
    ToolExecutePerCall --> ReadExecute: read 操作
    
    GuardBlock --> PendingConfirmation: explicit_confirmation_required
    GuardBlock --> OtherBlock: 其他 guard 错误\n→ 返回 LLM
    PendingConfirmation --> [*]: 等待用户确认
    
    GuardAllow --> EnrichObservation: 预计算财务字段注入\n(最贵商品/退款金额/差价等)
    EnrichObservation --> LLMReason: 继续下一轮
    
    ReadExecute --> AutoUpdateContext: gateway 自动更新 loaded_context
    AutoUpdateContext --> LLMReason: 继续下一轮
    
    OtherBlock --> LLMReason: 继续下一轮
    
    state NormalFinalize {
        [*] --> CorrectGiftCard
        CorrectGiftCard --> CorrectCredit
        CorrectCredit --> CorrectOriginalPrice
        CorrectOriginalPrice --> CorrectCancelItem
        CorrectCancelItem --> CorrectReturnSummary
        CorrectReturnSummary --> [*]
    }
    
    note right of ForceWriteInject: 只触发一次/每轮\n检查 _forcedWriteInjected + _anyWriteAttempted
    note right of EnrichObservation: 自动注入 _precomputed 字段\nLLM 不需要自行计算
    note right of AutoUpdateContext: _MAX_AUTO_LOAD_RETRIES=1\n递归自动执行
```

---

## 3. 7层 Guard 守卫流程

```mermaid
flowchart LR
    subgraph 入口["Tool Call"]
        Call["Gateway.execute()"]
    end

    subgraph 守卫链["WriteActionGuard.check()"]
        direction TB
        L1["① Known Action\n是 write 操作吗?"]
        L1D{{"拒绝 → unknown_write_action\nunsupported_in_mvp"}}
        
        L2["② Authentication\n用户已登录?"]
        L2D{{"拒绝 → authentication_required"}}
        
        L3["③ Ownership\n订单属于该用户?"]
        L3D{{"拒绝 → ownership_violation\norder_not_found"}}
        
        L4["④ Read-before-Write\n订单已加载?"]
        L4D{{"拒绝 → read_before_write_required\ntrigger Auto-Load"}}
        
        L5["⑤ User Confirmation\n用户已确认?"]
        L5D{{"拒绝 → explicit_confirmation_required\n暂停循环"}}
        
        L6["⑥ Policy Validation\n业务规则校验"]
        L6D{{"拒绝 → 具体策略错误\n(cancel 需 pending 等)"}}
        
        L7["⑦ Resource Locking\n幂等 + 冲突检测"]
        L7D{{"拒绝 → duplicate_write_lock\norder_already_cancelled 等"}}
    end

    subgraph 执行["执行"]
        ExecOK["执行 tool function\n更新 locks/audit/context"]
    end

    Call --> L1
    L1 -->|is write| L2
    L1 -->|not write| L1D
    
    L2 -->|已登录| L3
    L2 -->|未登录| L2D
    
    L3 -->|属于用户| L4
    L3 -->|不属于| L3D
    
    L4 -->|已加载| L5
    L4 -->|未加载| L4D
    
    L5 -->|已确认| L6
    L5 -->|未确认| L5D
    
    L6 -->|通过| L7
    L6 -->|不通过| L6D
    
    L7 -->|无冲突| ExecOK
    L7 -->|有冲突| L7D

    style Call fill:#e3f2fd,stroke:#1565c0
    style L1 fill:#c8e6c9,stroke:#2e7d32
    style L2 fill:#c8e6c9,stroke:#2e7d32
    style L3 fill:#c8e6c9,stroke:#2e7d32
    style L4 fill:#c8e6c9,stroke:#2e7d32
    style L5 fill:#c8e6c9,stroke:#2e7d32
    style L6 fill:#c8e6c9,stroke:#2e7d32
    style L7 fill:#c8e6c9,stroke:#2e7d32
    style ExecOK fill:#bbdefb,stroke:#1565c0
```

---

## 4. Pre-flight + 确认解析流程

```mermaid
flowchart TB
    Start(["收到用户消息"]) --> CheckPending{"session.pending_action\n存在?"}
    
    CheckPending -->|是 → 确认/拒绝/变更| ConfirmResolve["ConfirmationResolver.resolve()"]
    
    ConfirmResolve -->|confirmed| ExecPending["Gateway.execute(confirmed=True)\n→ Guard 跳过第5层确认"]
    ExecPending --> ContinueAction["_continue_after_confirmed_action()\n发送 continuation prompt"]
    ContinueAction --> DedupCheck{"_is_repeated_confirmed_action?\n防止重复执行"}
    DedupCheck -->|是 → 去重| ReturnResult["返回结果"]
    DedupCheck -->|否| MiniLoop["小循环 LLM 处理\n剩余部分"]
    MiniLoop --> ReturnResult
    
    ConfirmResolve -->|denied| ClearDeny["清除 pending_action\n'No changes were made.'"]
    ClearDeny --> ReturnResult
    
    ConfirmResolve -->|changed| ClearChange["清除 pending_action\n'Discarded previous request.\nPlease provide updated details.'"]
    ClearChange --> ReturnResult
    
    ConfirmResolve -->|unknown| Fallback["交给 LLM 正常处理"]
    Fallback --> LLMFlow

    CheckPending -->|否| CheckIdentity{"已认证\n(authenticated_user_id)?"}
    
    CheckIdentity -->|是| LLMFlow["AgentLoop.run_turn()"]
    
    CheckIdentity -->|否| ExtractsIdentity{"消息中含\nemail 或 姓名+邮编?"}
    ExtractsIdentity -->|匹配| FindUser["Gateway.execute(find_user...)\n→ 获取用户详情"]
    FindUser --> PopulateContext["填充 session.loaded_context.users"]
    PopulateContext --> LLMFlow
    
    ExtractsIdentity -->|不匹配| LLMFlow

    LLMFlow --> ReturnResult

    subgraph 关键词权重系统[ConfirmationResolver 内部]
        KW["
        ■ 确认关键词 (权重1-3):
          yes, confirm, proceed, go ahead
          是的, 确认, 好的, 继续
        
        ■ 拒绝关键词 (权重2-3):
          no, nope, cancel, deny
          不, 不要, 取消, 拒绝
        
        ■ 变更关键词 (权重2-3):
          change, instead, different, replace
          改, 换个, 换, 变更
        
        ■ 规则:
          negated_change → immediately denied
          deny > confirm+change & deny≥2 → denied
          change > confirm & change≥2 & confirm<2 → changed
          confirm > deny & confirm≥2 → confirmed
          其他 → unknown
        "]
    end

    linkStyle default stroke:#666,stroke-width:1.5px
```

---

## 5. 完整时序交互

```mermaid
sequenceDiagram
    participant U as 👤 用户
    participant RT as ⚙️ AgentRuntime
    participant AL as 🔄 AgentLoop
    participant LLM as 🧠 DeepSeek
    participant GW as 🚪 ToolGateway
    participant GD as 🛡️ Guard
    participant SK as 📋 Skill 注入
    
    U->>RT: 用户消息
    
    rect rgb(240, 248, 255)
        Note over RT: Pre-flight 阶段
        RT->>RT: 检查 pending_action
        alt 有待确认操作
            RT->>RT: ConfirmationResolver.resolve()
            RT->>GW: execute(confirmed=True)
            GW->>GD: Guard.check()
            GD-->>GW: allowed
            GW->>GW: 执行 write tool
            GW-->>RT: success
            RT->>AL: 续调 (continuation)
        end
        
        alt 未认证
            RT->>RT: 提取 email/姓名+邮编
            RT->>GW: find_user_by_email/name_zip
            GW->>GW: 查询用户
            GW-->>RT: 填充 session
        end
    end
    
    RT->>AL: run_turn(session, message)
    
    loop max 14 次迭代
        AL->>AL: ContextBuilder.build() → state_summary
        AL->>SK: build_skill_guidance_for_prompt()
        SK-->>AL: skill_guidance + few-shot
        
        AL->>LLM: chat_with_tools(messages, schemas)
        Note over AL,LLM: {tool_catalog} + {skill_guidance} + {state_summary}
        LLM-->>AL: response (含 tool_calls 或文本)
        
        alt 无 tool_calls
            AL->>AL: Premature refusal 检测
            alt 检测到过早拒绝
                AL->>GW: 强制注入 write 调用
                GW->>GD: Guard.check()
                GD-->>GW: blocked
                GW-->>AL: 返回 guard 结果
                AL->>LLM: 重新处理
            else 正常
                AL->>AL: 5种数值后处理修正
                AL-->>RT: 返回最终回复
            end
        else 有 tool_calls
            AL->>AL: 归一化 order_id / 批量增强 / 去重
            loop 对每个 tool_call
                AL->>GW: execute()
                GW->>GD: check() [write 操作]
                alt Guard blocked (确认)
                    GD-->>GW: explicit_confirmation_required
                    GW-->>AL: blocked
                    AL-->>U: "Can you confirm?"
                else Guard blocked (其他)
                    GD-->>GW: 策略/所有权错误
                    GW-->>AL: blocked
                    AL->>LLM: 继续
                else Guard allowed
                    GW->>GW: 执行 tool function
                    GW->>GW: 更新 locks/audit/context
                    GW->>AL: 预计算财务字段
                    AL->>LLM: 继续
                end
            end
            
            alt consecutive_failures ≥ 3
                AL-->>RT: 转人工
            end
        end
    end
    
    AL-->>U: 最终回复
```

---

## 6. 关键数据流总结

```
用户消息
    │
    ├─ agent/runtime.py ── preflight
    │   ├─ pending_action → ConfirmationResolver → 确认/拒绝/变更 → 直接执行
    │   └─ 未认证 → regex 提取 → find_user → 填充 loaded_context
    │
    └─ agent/llm_agent.py ── AgentLoop.run_turn()
           │
           │  System Prompt = llm_agent_system_v001.md
           │    + {tool_catalog}   ← tools/registry.py
           │    + {policy}         ← config
           │    + {state_summary}  ← context_builder.py (每轮动态)
           │    + {skill_guidance} ← skills/registry.py (8 skills)
           │
           └── loop (max 14):
                  ├─ LLM → tool_calls?
                  │   ├─ 无 → Premature Refusal 检测
                  │   │   ├─ 是 → 强制注入 write → 重试
                  │   │   └─ 否 → 5种数值修正 → 返回
                  │   └─ 有 → ToolGateway.execute() → Guard (7层)
                  │       ├─ write 通过 → 执行 → 财务字段预计算
                  │       ├─ write 被拦截 → 确认/策略/所有权错误
                  │       └─ read 通过 → 自动更新 loaded_context
                  │
                  └── 终止条件:
                       ├─ LLM 无 tool_calls + 无拒绝检测 → 正常返回
                       ├─ Guard 要求确认 → 暂停等待用户
                       ├─ 14 轮满 → 转人工
                       └─ 连续 3 次失败 → 转人工
```
