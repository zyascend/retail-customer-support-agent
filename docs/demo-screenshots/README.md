# Phase 6 Demo Screenshots

These screenshots need to be captured manually from the running Workbench at `http://localhost:5173`.

## How to Capture

```bash
# Terminal 1: Start backend
uv run phase4-workbench

# Terminal 2: Start frontend
cd workbench && npm run dev

# Open http://localhost:5173 in browser
```

## Screenshot List

### 1. workbench-overview.png
- **State**: Select "取消待处理订单", click "运行全部"
- **Capture**: Full Workbench window showing all 6 panels
- **Key evidence**: Grouped case selector (top-left), BusinessState with user/order/intent, Timeline with primary/secondary events, Inspector with selected event detail

### 2. guard-block.png
- **State**: Select "阻止访问他人订单", click "运行全部", click a blocked event in Timeline
- **Capture**: Timeline + Inspector panels side by side
- **Key evidence**: Guard block reason in Inspector, blocked status badge in Timeline

### 3. write-audit.png
- **State**: Select "取消待处理订单", click "运行全部", click write_audit event in Timeline
- **Capture**: Timeline + Inspector panels side by side
- **Key evidence**: DB hash before/after, idempotency key in Inspector

### 4. confirmation-pending.png
- **State**: Select "取消待处理订单", click "单步执行" until pending action appears
- **Capture**: BusinessState panel
- **Key evidence**: Orange pending action banner "⏳ 需要用户确认才能执行", action name, confirm/deny/change buttons

### 5. eval-passing.png
- **State**: Terminal
- **Capture**: Terminal output of eval command
- **Command**: `uv run phase2-eval --subset generalized_mvp --trials 1`
- **Key evidence**: 30/30 PASS results, pass_1 and pass_k metrics
