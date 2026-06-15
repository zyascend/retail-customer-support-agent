# 数据流文档

> 从用户输入到最终响应的完整数据流，覆盖所有安全层和逻辑分支。

```mermaid
flowchart TD
    %% ─── 入口层 ───
    subgraph Entry[入口层 Entry Points]
        direction LR
        CLI[phase1-chat CLI]
        EVAL[phase2-eval CLI]
        WB[Workbench API]
        TEST[测试用例]
    end

    %% ─── AgentRuntime ───
    subgraph RT[AgentRuntime.handle_user_message]
        direction TB
        RECV[接收用户消息]
        RECV --> P1{有 PendingAction?}
        
        P1 -- 是 --> PRE_CONF[ConfirmationResolver 解析]
        P1 -- 否 --> P2{已认证?}
        
        PRE_CONF --> RES_CONF{解析结果}
        RES_CONF -- confirmed --> EXEC_WRITE[Gateway.execute confirmed=True]
        RES_CONF -- denied --> DROP_ACT["丢弃 PendingAction<br/>返回 'No changes'"]
        RES_CONF -- changed --> DROP_ACT
        RES_CONF -- unknown --> P2
        
        EXEC_WRITE --> CHECK_PASS{成功?}
        CHECK_PASS -- 是 --> CONTINUE_CB[继续原始请求的剩余部分]
        CHECK_PASS -- 否 --> MAP_ERR[映射错误为用户消息]
        
        P2 -- 未认证 --> PRE_ID[预身份认证]
        PRE_ID --> EMAIL{Email 匹配?}
        EMAIL -- 是 --> LD_EMAIL[find_user_id_by_email]
        EMAIL -- 否 --> NZ{Name+Zip 匹配?}
        NZ -- 是 --> LD_NZ[find_user_id_by_name_zip]
        NZ -- 否 --> P3
        LD_EMAIL --> P3
        LD_NZ --> P3
        
        P3[进入 AgentLoop]
    end

    %% ─── AgentLoop (LLM Tool-Calling Loop) ───
    subgraph LOOP[AgentLoop.run_turn]
        direction TB
        
        BUILD_MSG[构建消息：系统提示 + 状态摘要 + 对话历史]
        BUILD_MSG --> LLM_CALL[LLM Provider.chat_with_tools]
        LLM_CALL --> LLM_RSP{返回 Tool Calls?}
        
        LLM_RSP -- 无 --> REF_DETECT{检测到过早拒绝?}
        REF_DETECT -- 是 --> FORCE_INJECT[强制注入 write tool call<br/>触发 guard 层]
        REF_DETECT -- 否 --> FINALIZE[最终化阶段<br/>修正金额/退款等响应]
        
        FORCE_INJECT --> LOOP_BACK[继续循环]
        LOOP_BACK --> LLM_CALL
        
        LLM_RSP -- 有 --> EXEC_TOOLS[执行每个 Tool Call]
        
        EXEC_TOOLS --> T_PREP[参数预处理<br/>- 标准化 order_id<br/>- 批量增强 item_ids<br/>- 抑制冗余 payment]
        T_PREP --> GATEWAY_CALL[ToolGateway.execute]
        
        GATEWAY_CALL --> GW_RSP{执行结果}
        
        GW_RSP -- blocked: confirmation_required --> PENDING_SET[设置 PendingAction<br/>返回确认请求]
        GW_RSP -- blocked: read_before_write --> AUTO_LOAD[自动加载缺失上下文<br/>get_order_details / get_user_details]
        GW_RSP -- blocked: 其他 --> OBS_ERR[构造 ToolExecutionError<br/>返回给 LLM 重试]
        GW_RSP -- success --> OBS_OK[格式化观察结果<br/>更新 loaded_context]
        GW_RSP -- error --> OBS_ERR
        
        AUTO_LOAD --> RETRY{加载成功?}
        RETRY -- 是 --> GATEWAY_CALL
        RETRY -- 否 --> OBS_ERR
        
        OBS_OK --> CHK_ALL{全部失败?}
        OBS_ERR --> CHK_ALL
        CHK_ALL -- 是 --> FAIL_CNT[连续失败数 +1]
        CHK_ALL -- 否 --> FAIL_RST[连续失败数归零]
        
        FAIL_CNT --> CHK_LIM{达到上限?}
        FAIL_RST --> LOOP_BACK
        
        CHK_LIM -- 是 --> TERM_FAIL[终止: 连续失败<br/>转人工]
        CHK_LIM -- 否 --> LOOP_BACK
        
        LLM_CALL --> TIMEOUT{超时?}
        TIMEOUT -- 是 --> TERM_TO[终止: 超时]
        
        LLM_CALL --> ITER_LIM{达到最大迭代?}
        ITER_LIM -- 是 --> TERM_ITER[终止: 最大迭代]
    end

    %% ─── ToolGateway & Guard ───
    subgraph GW[ToolGateway.execute]
        direction TB
        GW_START[接收 tool_name + arguments]
        GW_START --> CHK_KIND{工具类型}
        CHK_KIND -- read/generic --> EXEC_DIRECT[直接执行工具函数]
        CHK_KIND -- write --> GUARD_L1[WriteActionGuard.check]
        
        GUARD_L1 --> L1{Auth: 已认证?}
        L1 -- 否 --> BLK_AUTH[block: authentication_required]
        
        L1 -- 是 --> L2{Confirmation: 已确认?}
        L2 -- 否 --> BLK_CONF[block: explicit_confirmation_required<br/>设置 pending]
        
        L2 -- 是 --> L3{Ownership: 属于该用户?}
        L3 -- 否 --> BLK_OWN[block: ownership_violation]
        
        L3 -- 是 --> L4{Read-before-write: 已加载?}
        L4 -- 否 --> BLK_READ[block: read_before_write_required]
        
        L4 -- 是 --> L5{Policy: 状态/商品/支付合法?}
        L5 -- 否 --> BLK_POL[block: 具体策略错误码]
        
        L5 -- 是 --> L6{Resource Lock: 无冲突?}
        L6 -- 否 --> BLK_LOCK[block: duplicate/lock 冲突]
        
        L6 -- 是 --> L7[Idempotency Key 生成]
        L7 --> EXEC_DIRECT
        
        EXEC_DIRECT --> CAPTURE[捕获 before_db_hash]
        CAPTURE --> RUN_FUNC[运行工具函数]
        RUN_FUNC --> LOG_AFTER[捕获 after_db_hash / 异常]
        LOG_AFTER --> WRITE_TRACE[记录 ToolCallRecord]
        
        BLK_AUTH --> WRITE_TRACE
        BLK_CONF --> WRITE_TRACE
        BLK_OWN --> WRITE_TRACE
        BLK_READ --> WRITE_TRACE
        BLK_POL --> WRITE_TRACE
        BLK_LOCK --> WRITE_TRACE
    end

    %% ─── Confirmation Parser ───
    subgraph CONF[ConfirmationResolver]
        CONF_START[用户确认文本]
        CONF_START --> NEG{否定+变更检测?}
        NEG -- "don't change" --> DENY_RES[denied]
        NEG -- 正常 --> SCORE[加权关键词打分]
        SCORE --> COMP[比较 confirm/deny/change 分数]
        COMP -- deny > confirm+change --> DENY_RES
        COMP -- change > confirm --> CHG_RES[changed]
        COMP -- confirm > deny --> CFM_RES[confirmed]
        COMP -- 其他 --> UNK_RES[unknown]
    end

    %% ─── 上下文构建 ───
    subgraph CTX[ContextBuilder]
        CTX_START[从 SessionState 提取]
        CTX_START --> USR_LINE[用户身份行]
        CTX_START --> ORD_LINE[已加载订单摘要]
        CTX_START --> PAY_LINE[支付方式列表]
        CTX_START --> PEN_LINE[待确认 action]
        CTX_START --> LOCK_LINE[写锁列表]
        CTX_START --> WRITE_HIST[近期成功写入]
        CTX_START --> BLOCK_HIST[近期 guard block]
        CTX_START --> ERR_HIST[近期工具错误]
    end

    %% ─── 数据存储 ───
    subgraph DATA[数据存储]
        DB[(SQLite 数据库 / tau2-bench)]
        TRACE[(Trace 产物 JSON)]
    end

    %% ─── 连接 ───
    Entry --> RT
    
    RT --> LOOP
    RT --> CONF
    
    LOOP --> GW
    
    GW --> DATA
    LOOP --> CTX
    CTX --> LOOP
    
    LOOP --> FINALIZE --> RESPONSE[返回 assistant_message 给用户]
    
    PRE_CONF --> CONF
    PRE_CONF --> EXEC_WRITE --> GW
```

## 逻辑流程概述

### 1. 用户输入进入 `AgentRuntime.handle_user_message()`

这是所有入口（CLI、Workbench API、测试）的统一入口点。

### 2. 预检查（Pre-flight）

| 步骤 | 逻辑 | 路由 |
|------|------|------|
| **PendingAction 检查** | 如果 `session.pending_action` 存在，调用 `ConfirmationResolver` 解析用户回复 | 确认→直接执行；拒绝/变更→丢弃；未知→继续 LLM |
| **身份认证** | 如果未认证，尝试从消息中提取 email 或 name+zip 自动认证 | 成功→加载用户上下文；失败→LLM 会提示用户提供信息 |

### 3. AgentLoop：LLM 工具调用循环

系统提示由三部分组成：`核心契约 + 具体任务提示 + 动态状态摘要`。LLM 收到工具 Schema 后决定调用哪些工具。

**关键设计模式**：LLM 负责调用写工具——Guard 层负责决策是否允许。即使 LLM 觉得操作会失败，也必须调用写工具。

**安全网**：如果 LLM 过早拒绝（不调用写工具直接回复文本），`_detect_premature_refusal` 会检测并强制注入一个写工具调用。

### 4. ToolGateway：执行与 Guard 检查

| 层 | 检查项 | 阻断时 |
|----|--------|--------|
| 1. 认证 | `authenticated_user_id` 是否设置 | "authentication_required" |
| 2. 显式确认 | `confirmed=True` 标志 | "explicit_confirmation_required" → 设置 PendingAction |
| 3. 所有权 | 订单/资源的 owner 是否匹配 | "ownership_violation" |
| 4. 读前写 | 订单/用户是否已在 loaded_context | "read_before_write_required" → 自动加载重试 |
| 5. 策略 | 订单状态、商品可用性、支付方式、余额 | 具体错误码（如 "non_pending_order_cannot_be_cancelled"） |
| 6. 资源锁 | 同资源是否有冲突写操作 | "duplicate_write_lock" |
| 7. 幂等性 | 基于 session+tool+args+lock 的哈希 | 内部使用，防止重复执行 |

### 5. 确认流程（用户侧的交互）

```
LLM 调用 write tool → Guard 要求确认 → 设置 PendingAction → 
Assistant 返回 "Can you confirm?" → 用户回复 →
ConfirmationResolver 解析 → 确认则执行, 拒绝则丢弃
```

### 6. 响应生成

- 如果无工具调用且无过早拒绝→最终化阶段
- 如果写操作成功确认→可选的"继续剩余请求"的二次 LLM 调用
- 如果全部失败→终止策略（连续失败限制、最大迭代限制）

### 7. 追踪与评估

每次运行的完整记录（状态变化、工具调用、LLM 响应、Guard 阻断）保存为 Trace 产物，用于后续评估和 Workbench AgentOps 可视化。
