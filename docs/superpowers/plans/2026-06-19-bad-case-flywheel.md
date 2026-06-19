# Bad Case 数据飞轮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 eval failure → 归因 → 变体生成 → golden 回归的半自动闭环，使 `flywheel collect|generate|golden promote|check` CLI 成为系统持续改进的引擎。

**Architecture:** 四阶段 pipeline，每个阶段独立模块、独立可测。复用现有 `classify_failure()` / `infer_root_cause()` / `build_language_variants()` / `CuratedEvalRunner`，新增 `bad_case_store.py`（YAML I/O）、`golden_set.py`（golden 管理+回归）、`flywheel.py`（编排）、`app/cli/flywheel.py`（CLI 入口）。

**Tech Stack:** Python 3.12, dataclasses, PyYAML（新增依赖）, argparse, pytest。无 real LLM 依赖。

---

## 关键约束（探索中发现）

1. **Report JSON 不含 case 定义字段**（messages / expected_tool_names / expected_user_id / expected_intent / order_id）。`flywheel collect` 必须接受 `--subset` 参数，通过 `get_cases(subset)` 按 `case_id` 重新查找原始 case。
2. **`yaml` 不是依赖项** — Task 1 添加 `pyyaml` 到 `pyproject.toml`。
3. **变体生成仅适用于有 `variant_type` 的 case**（synthetic / generalization family）。curated hand-written case 和 tau 原始 case 的 oracle 无法自动推导，跳过变体生成。
4. **`get_cases(subset)` 必须存在 `golden` 子集** — Task 7 在 `app/eval/cases.py` 中注册 `golden` subset，从 `cases/golden.yaml` 加载。
5. **测试不走 real LLM** — golden check 的回归测试走 `CuratedEvalRunner` 但在测试中使用 mock 或仅测纯逻辑部分。

---

## File Structure

| 文件 | 责任 | 状态 |
|------|------|------|
| `pyproject.toml` | 添加 `pyyaml` 依赖 + `flywheel` script 入口 | 修改 |
| `app/eval/bad_case_store.py` | bad case YAML 序列化/反序列化 | 新建 |
| `app/eval/golden_set.py` | golden set 管理（promote / load / 差异） | 新建 |
| `app/eval/flywheel.py` | 四阶段编排（collect / generate / check） | 新建 |
| `app/eval/cases.py` | 注册 `golden` subset | 修改 |
| `app/cli/flywheel.py` | argparse CLI 入口 | 新建 |
| `cases/golden.yaml` | golden set 数据文件（初始空） | 新建 |
| `tests/test_bad_case_store.py` | bad_case_store 单元测试 | 新建 |
| `tests/test_golden_set.py` | golden_set 单元测试 | 新建 |
| `tests/test_flywheel.py` | flywheel 编排集成测试 | 新建 |
| `tests/test_flywheel_cli.py` | CLI 集成测试 | 新建 |

---

## Task 1: 添加依赖与项目入口

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 `pyyaml` 依赖与 `flywheel` script 入口**

修改 `pyproject.toml`，在 `dependencies` 中添加 `pyyaml>=6.0`，在 `[project.scripts]` 中添加 `flywheel` 入口：

```toml
dependencies = [
    "fastapi>=0.115.0",
    "langgraph>=0.2.70",
    "openai>=1.60.0",
    "pydantic>=2.10.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0",
    "uvicorn>=0.34.0",
]

[project.scripts]
phase1-chat = "app.cli.chat:chat_main"
phase2-eval = "app.cli.eval:eval_main"
flywheel = "app.cli.flywheel:flywheel_main"
workbench = "app.workbench.cli:workbench_main"
```

- [ ] **Step 2: 同步依赖**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv sync --extra dev`
Expected: `pyyaml` 安装成功，无错误

- [ ] **Step 3: 验证导入**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -c "import yaml; print(yaml.__version__)"`
Expected: 打印版本号（如 `6.0.2`）

- [ ] **Step 4: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add pyproject.toml uv.lock
git commit -m "chore: 添加 pyyaml 依赖与 flywheel CLI 入口"
```

---

## Task 2: BadCaseRecord dataclass 与 YAML 序列化

**Files:**
- Create: `app/eval/bad_case_store.py`
- Test: `tests/test_bad_case_store.py`

`BadCaseRecord` 承载单个 bad case 的完整数据：原始 EvalCase 字段 + 诊断信息。可序列化为 YAML dict 并从 YAML dict 重建。

- [ ] **Step 1: 写失败测试 — 序列化与反序列化 roundtrip**

创建 `tests/test_bad_case_store.py`：

```python
from __future__ import annotations

from app.eval.bad_case_store import BadCaseRecord


def _sample_record() -> BadCaseRecord:
    return BadCaseRecord(
        case_id="cancel_001_L1",
        source_case_id="cancel_001",
        failure_label="wrong_tool",
        failure_bucket="tool_selection",
        root_cause="prompt_gap",
        failure_source="planning",
        promoted=False,
        messages=[{"role": "user", "content": "Void my order"}],
        expected_user_id="U1001",
        expected_intent="cancel_order",
        order_id="#W1234567",
        expected_write_lock=None,
        expected_order_status="cancelled",
        expected_confirmation_status=None,
        expected_guard_block_reason=None,
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
        expected_assistant_contains=None,
        max_turns=8,
        subset="generalization",
        scenario_family="cancel",
        variant_type="cancel_success",
        language_variation_level="L1",
        seed=100,
        expected_db_assertions={"order.status": "cancelled"},
        expected_tool_sequence=[],
        diagnostics={
            "actual_tool_names": ["get_order_details"],
            "suggested_next_action": "Compare expected and actual tool calls",
        },
    )


def test_bad_case_record_to_yaml_dict_roundtrip() -> None:
    record = _sample_record()
    yaml_dict = record.to_yaml_dict()
    restored = BadCaseRecord.from_yaml_dict(yaml_dict)
    assert restored == record


def test_bad_case_record_from_eval_case_and_diagnostics_builds_full_record() -> None:
    from app.eval.cases import EvalCase

    case = EvalCase(
        case_id="cancel_001_L1",
        category="cancel",
        messages=[{"role": "user", "content": "Void my order"}],
        expected_user_id="U1001",
        expected_intent="cancel_order",
        order_id="#W1234567",
        expected_order_status="cancelled",
        expected_tool_names=["cancel_pending_order"],
        subset="generalization",
        scenario_family="cancel",
        variant_type="cancel_success",
        language_variation_level="L1",
        seed=100,
        expected_db_assertions={"order.status": "cancelled"},
    )
    record = BadCaseRecord.from_eval_case(
        case=case,
        source_case_id="cancel_001",
        failure_label="wrong_tool",
        failure_bucket="tool_selection",
        root_cause="prompt_gap",
        failure_source="planning",
        diagnostics={"actual_tool_names": ["get_order_details"]},
    )
    assert record.case_id == "cancel_001_L1"
    assert record.expected_user_id == "U1001"
    assert record.seed == 100
    assert record.diagnostics["actual_tool_names"] == ["get_order_details"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_bad_case_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.bad_case_store'`

- [ ] **Step 3: 实现 `BadCaseRecord`**

创建 `app/eval/bad_case_store.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.eval.cases import EvalCase

# EvalCase 字段名 → BadCaseRecord 字段名的统一映射
_EVAL_CASE_FIELDS = (
    "messages",
    "expected_user_id",
    "expected_intent",
    "order_id",
    "expected_write_lock",
    "expected_order_status",
    "expected_confirmation_status",
    "expected_guard_block_reason",
    "expected_no_write",
    "expected_tool_names",
    "expected_assistant_contains",
    "max_turns",
    "subset",
    "scenario_family",
    "variant_type",
    "language_variation_level",
    "seed",
    "expected_db_assertions",
    "expected_tool_sequence",
)


@dataclass
class BadCaseRecord:
    """单个 bad case 的完整记录：原始 EvalCase 字段 + 归因 + 诊断。"""

    case_id: str
    source_case_id: str
    failure_label: Optional[str]
    failure_bucket: Optional[str]
    root_cause: Optional[str]
    failure_source: Optional[str]
    promoted: bool
    messages: List[Dict[str, str]]
    expected_user_id: str
    expected_intent: str
    order_id: Optional[str]
    expected_write_lock: Optional[str]
    expected_order_status: Optional[str]
    expected_confirmation_status: Optional[str]
    expected_guard_block_reason: Optional[str]
    expected_no_write: bool
    expected_tool_names: List[str]
    expected_assistant_contains: Optional[str]
    max_turns: int
    subset: str
    scenario_family: Optional[str]
    variant_type: Optional[str]
    language_variation_level: Optional[str]
    seed: Optional[int]
    expected_db_assertions: Dict[str, Any]
    expected_tool_sequence: List[str]
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_eval_case(
        cls,
        *,
        case: EvalCase,
        source_case_id: str,
        failure_label: Optional[str],
        failure_bucket: Optional[str],
        root_cause: Optional[str],
        failure_source: Optional[str],
        diagnostics: Dict[str, Any],
    ) -> "BadCaseRecord":
        """从 EvalCase + 归因信息构造 BadCaseRecord。"""
        return cls(
            case_id=case.case_id,
            source_case_id=source_case_id,
            failure_label=failure_label,
            failure_bucket=failure_bucket,
            root_cause=root_cause,
            failure_source=failure_source,
            promoted=False,
            messages=list(case.messages),
            expected_user_id=case.expected_user_id,
            expected_intent=case.expected_intent,
            order_id=case.order_id,
            expected_write_lock=case.expected_write_lock,
            expected_order_status=case.expected_order_status,
            expected_confirmation_status=case.expected_confirmation_status,
            expected_guard_block_reason=case.expected_guard_block_reason,
            expected_no_write=case.expected_no_write,
            expected_tool_names=list(case.expected_tool_names),
            expected_assistant_contains=case.expected_assistant_contains,
            max_turns=case.max_turns,
            subset=case.subset,
            scenario_family=case.scenario_family,
            variant_type=case.variant_type,
            language_variation_level=case.language_variation_level,
            seed=case.seed,
            expected_db_assertions=dict(case.expected_db_assertions),
            expected_tool_sequence=list(case.expected_tool_sequence),
            diagnostics=dict(diagnostics),
        )

    def to_eval_case(self, *, subset_override: Optional[str] = None) -> EvalCase:
        """重建为 EvalCase，用于 golden check 执行。"""
        return EvalCase(
            case_id=self.case_id,
            category=self.scenario_family or self.expected_intent,
            messages=list(self.messages),
            expected_user_id=self.expected_user_id,
            expected_intent=self.expected_intent,
            order_id=self.order_id,
            expected_write_lock=self.expected_write_lock,
            expected_order_status=self.expected_order_status,
            expected_confirmation_status=self.expected_confirmation_status,
            expected_guard_block_reason=self.expected_guard_block_reason,
            expected_no_write=self.expected_no_write,
            expected_tool_names=list(self.expected_tool_names),
            expected_assistant_contains=self.expected_assistant_contains,
            max_turns=self.max_turns,
            subset=subset_override or self.subset,
            scenario_family=self.scenario_family,
            variant_type=self.variant_type,
            language_variation_level=self.language_variation_level,
            seed=self.seed,
            expected_db_assertions=dict(self.expected_db_assertions),
            expected_tool_sequence=list(self.expected_tool_sequence),
        )

    def to_yaml_dict(self) -> Dict[str, Any]:
        """序列化为 YAML-safe dict。"""
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "failure_label": self.failure_label,
            "failure_bucket": self.failure_bucket,
            "root_cause": self.root_cause,
            "failure_source": self.failure_source,
            "promoted": self.promoted,
            "messages": list(self.messages),
            "expected_user_id": self.expected_user_id,
            "expected_intent": self.expected_intent,
            "order_id": self.order_id,
            "expected_write_lock": self.expected_write_lock,
            "expected_order_status": self.expected_order_status,
            "expected_confirmation_status": self.expected_confirmation_status,
            "expected_guard_block_reason": self.expected_guard_block_reason,
            "expected_no_write": self.expected_no_write,
            "expected_tool_names": list(self.expected_tool_names),
            "expected_assistant_contains": self.expected_assistant_contains,
            "max_turns": self.max_turns,
            "subset": self.subset,
            "scenario_family": self.scenario_family,
            "variant_type": self.variant_type,
            "language_variation_level": self.language_variation_level,
            "seed": self.seed,
            "expected_db_assertions": dict(self.expected_db_assertions),
            "expected_tool_sequence": list(self.expected_tool_sequence),
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "BadCaseRecord":
        """从 YAML dict 重建 BadCaseRecord。"""
        return cls(
            case_id=data["case_id"],
            source_case_id=data.get("source_case_id", data["case_id"]),
            failure_label=data.get("failure_label"),
            failure_bucket=data.get("failure_bucket"),
            root_cause=data.get("root_cause"),
            failure_source=data.get("failure_source"),
            promoted=data.get("promoted", False),
            messages=list(data.get("messages", [])),
            expected_user_id=data["expected_user_id"],
            expected_intent=data["expected_intent"],
            order_id=data.get("order_id"),
            expected_write_lock=data.get("expected_write_lock"),
            expected_order_status=data.get("expected_order_status"),
            expected_confirmation_status=data.get("expected_confirmation_status"),
            expected_guard_block_reason=data.get("expected_guard_block_reason"),
            expected_no_write=data.get("expected_no_write", False),
            expected_tool_names=list(data.get("expected_tool_names", [])),
            expected_assistant_contains=data.get("expected_assistant_contains"),
            max_turns=data.get("max_turns", 8),
            subset=data.get("subset", "curated_mvp"),
            scenario_family=data.get("scenario_family"),
            variant_type=data.get("variant_type"),
            language_variation_level=data.get("language_variation_level"),
            seed=data.get("seed"),
            expected_db_assertions=dict(data.get("expected_db_assertions", {})),
            expected_tool_sequence=list(data.get("expected_tool_sequence", [])),
            diagnostics=dict(data.get("diagnostics", {})),
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_bad_case_store.py -v`
Expected: PASS（2 个测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/bad_case_store.py tests/test_bad_case_store.py
git commit -m "feat: BadCaseRecord dataclass 与 YAML 序列化"
```

---

## Task 3: BadCaseStore — YAML 文件 I/O

**Files:**
- Modify: `app/eval/bad_case_store.py`
- Test: `tests/test_bad_case_store.py`

`BadCaseStore` 读写 `cases/bad_cases/<date>.yaml` 文件，支持去重合并（同 case_id 只保留最新）。

- [ ] **Step 1: 追加失败测试 — 写入与读取文件**

在 `tests/test_bad_case_store.py` 末尾追加：

```python
def test_bad_case_store_write_and_read_roundtrip(tmp_path) -> None:
    from app.eval.bad_case_store import BadCaseStore

    store = BadCaseStore(root=tmp_path)
    record = _sample_record()
    file_path = store.write_records([record], date_str="2026-06-19")

    assert file_path.exists()
    assert file_path.name == "2026-06-19.yaml"
    assert file_path.parent.name == "bad_cases"

    loaded = store.read_records(date_str="2026-06-19")
    assert len(loaded) == 1
    assert loaded[0].case_id == "cancel_001_L1"
    assert loaded[0].failure_label == "wrong_tool"


def test_bad_case_store_dedupes_by_case_id_on_repeated_write(tmp_path) -> None:
    from app.eval.bad_case_store import BadCaseStore

    store = BadCaseStore(root=tmp_path)
    record1 = _sample_record()
    record1.diagnostics = {"actual_tool_names": ["old"]}
    store.write_records([record1], date_str="2026-06-19")

    record2 = _sample_record()
    record2.diagnostics = {"actual_tool_names": ["new"]}
    store.write_records([record2], date_str="2026-06-19")

    loaded = store.read_records(date_str="2026-06-19")
    assert len(loaded) == 1
    assert loaded[0].diagnostics["actual_tool_names"] == ["new"]


def test_bad_case_store_find_by_case_id_searches_all_files(tmp_path) -> None:
    from app.eval.bad_case_store import BadCaseStore

    store = BadCaseStore(root=tmp_path)
    record_a = _sample_record()
    store.write_records([record_a], date_str="2026-06-19")

    record_b = BadCaseRecord(
        case_id="other_case",
        source_case_id="other_case",
        failure_label="guard_blocked",
        failure_bucket="guard_behavior",
        root_cause="guard_policy_gap",
        failure_source="guard",
        promoted=False,
        messages=[{"role": "user", "content": "cancel"}],
        expected_user_id="U1002",
        expected_intent="cancel_order",
        order_id=None,
        expected_write_lock=None,
        expected_order_status=None,
        expected_confirmation_status=None,
        expected_guard_block_reason="order_status_not_pending",
        expected_no_write=True,
        expected_tool_names=[],
        expected_assistant_contains=None,
        max_turns=8,
        subset="curated_mvp",
        scenario_family=None,
        variant_type=None,
        language_variation_level=None,
        seed=None,
        expected_db_assertions={},
        expected_tool_sequence=[],
        diagnostics={},
    )
    store.write_records([record_b], date_str="2026-06-20")

    found = store.find_by_case_id("other_case")
    assert found is not None
    assert found.case_id == "other_case"
    assert found.expected_guard_block_reason == "order_status_not_pending"

    not_found = store.find_by_case_id("nonexistent")
    assert not_found is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_bad_case_store.py -v`
Expected: 3 个新测试 FAIL（`BadCaseStore` 未定义）

- [ ] **Step 3: 实现 `BadCaseStore`**

在 `app/eval/bad_case_store.py` 末尾追加：

```python
import yaml


class BadCaseStore:
    """bad case YAML 文件 I/O，按日期组织，同 case_id 去重。"""

    def __init__(self, *, root: Path) -> None:
        self._root = root

    @property
    def bad_cases_dir(self) -> Path:
        return self._root / "bad_cases"

    def write_records(
        self, records: List[BadCaseRecord], *, date_str: str
    ) -> Path:
        """写入当日 bad_cases 文件。若已存在，按 case_id 去重合并（新覆盖旧）。"""
        self.bad_cases_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.bad_cases_dir / f"{date_str}.yaml"

        existing: Dict[str, BadCaseRecord] = {}
        if file_path.exists():
            for record in self._read_file(file_path):
                existing[record.case_id] = record

        for record in records:
            existing[record.case_id] = record

        payload = {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "bad_cases": [r.to_yaml_dict() for r in existing.values()],
        }
        file_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return file_path

    def read_records(self, *, date_str: str) -> List[BadCaseRecord]:
        """读取指定日期的 bad case 记录。"""
        file_path = self.bad_cases_dir / f"{date_str}.yaml"
        if not file_path.exists():
            return []
        return self._read_file(file_path)

    def find_by_case_id(self, case_id: str) -> Optional[BadCaseRecord]:
        """跨所有日期文件查找 case_id。"""
        if not self.bad_cases_dir.exists():
            return None
        for yaml_file in sorted(self.bad_cases_dir.glob("*.yaml")):
            for record in self._read_file(yaml_file):
                if record.case_id == case_id:
                    return record
        return None

    def list_all_records(self) -> List[BadCaseRecord]:
        """读取所有日期文件的全部记录，按文件名排序。"""
        all_records: List[BadCaseRecord] = []
        if not self.bad_cases_dir.exists():
            return all_records
        for yaml_file in sorted(self.bad_cases_dir.glob("*.yaml")):
            all_records.extend(self._read_file(yaml_file))
        return all_records

    def _read_file(self, file_path: Path) -> List[BadCaseRecord]:
        if not file_path.exists():
            return []
        data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        bad_cases = data.get("bad_cases", []) if isinstance(data, dict) else []
        return [BadCaseRecord.from_yaml_dict(item) for item in bad_cases]
```

同时在文件顶部 import 区追加：

```python
from datetime import datetime, timezone
from pathlib import Path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_bad_case_store.py -v`
Expected: PASS（5 个测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/bad_case_store.py tests/test_bad_case_store.py
git commit -m "feat: BadCaseStore YAML 文件 I/O 与去重合并"
```

---

## Task 4: GoldenEntry dataclass 与 GoldenSet 管理

**Files:**
- Create: `app/eval/golden_set.py`
- Test: `tests/test_golden_set.py`

`GoldenEntry` 承载已合入 golden 的 case，`GoldenSet` 管理 `cases/golden.yaml` 的读写、promote、回归结果对比。

- [ ] **Step 1: 写失败测试 — GoldenSet 序列化与 promote**

创建 `tests/test_golden_set.py`：

```python
from __future__ import annotations

from app.eval.bad_case_store import BadCaseRecord
from app.eval.golden_set import GoldenEntry, GoldenSet, RegressionOutcome


def _sample_bad_case_record() -> BadCaseRecord:
    return BadCaseRecord(
        case_id="cancel_001_L1",
        source_case_id="cancel_001",
        failure_label="wrong_tool",
        failure_bucket="tool_selection",
        root_cause="prompt_gap",
        failure_source="planning",
        promoted=False,
        messages=[{"role": "user", "content": "Void my order"}],
        expected_user_id="U1001",
        expected_intent="cancel_order",
        order_id="#W1234567",
        expected_write_lock=None,
        expected_order_status="cancelled",
        expected_confirmation_status=None,
        expected_guard_block_reason=None,
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
        expected_assistant_contains=None,
        max_turns=8,
        subset="generalization",
        scenario_family="cancel",
        variant_type="cancel_success",
        language_variation_level="L1",
        seed=100,
        expected_db_assertions={},
        expected_tool_sequence=[],
        diagnostics={},
    )


def test_golden_entry_from_bad_case_record_promotes_with_expected_pass_true() -> None:
    record = _sample_bad_case_record()
    entry = GoldenEntry.from_bad_case_record(
        record=record, promoted_from="bad_cases/2026-06-19.yaml"
    )
    assert entry.case_id == "cancel_001_L1"
    assert entry.expected_pass is True
    assert entry.failure_label == "wrong_tool"
    assert entry.promoted_from == "bad_cases/2026-06-19.yaml"
    assert entry.expected_user_id == "U1001"


def test_golden_set_promote_and_save_and_load_roundtrip(tmp_path) -> None:
    golden_path = tmp_path / "golden.yaml"
    golden = GoldenSet(path=golden_path)
    record = _sample_bad_case_record()
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")
    golden.save()

    assert golden_path.exists()
    loaded = GoldenSet(path=golden_path)
    loaded.load()
    assert len(loaded.entries) == 1
    assert loaded.entries[0].case_id == "cancel_001_L1"
    assert loaded.entries[0].expected_pass is True


def test_golden_set_promote_is_idempotent(tmp_path) -> None:
    golden = GoldenSet(path=tmp_path / "golden.yaml")
    record = _sample_bad_case_record()
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")
    assert len(golden.entries) == 1


def test_golden_set_compare_results_detects_regression() -> None:
    golden = GoldenSet(path=tmp_path / "golden.yaml")
    record = _sample_bad_case_record()
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")

    # 模拟 eval 结果：case 应该 pass 但实际 fail → 回归
    eval_results = {
        "cancel_001_L1": {"passed": False, "failure_label": "wrong_tool"}
    }
    outcomes = golden.compare_results(eval_results)
    assert len(outcomes) == 1
    assert outcomes[0].status == "regression"
    assert outcomes[0].case_id == "cancel_001_L1"


def test_golden_set_compare_results_pass_when_expected_pass_and_passed() -> None:
    golden = GoldenSet(path=tmp_path / "golden.yaml")
    record = _sample_bad_case_record()
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")

    eval_results = {
        "cancel_001_L1": {"passed": True, "failure_label": None}
    }
    outcomes = golden.compare_results(eval_results)
    assert outcomes[0].status == "pass"


def test_golden_set_compare_results_unexpected_pass_when_expected_fail() -> None:
    golden = GoldenSet(path=tmp_path / "golden.yaml")
    record = _sample_bad_case_record()
    golden.promote(record, promoted_from="bad_cases/2026-06-19.yaml")
    # 手动改为 expected_pass=False（模拟 known-bad case）
    golden.entries[0].expected_pass = False

    eval_results = {
        "cancel_001_L1": {"passed": True, "failure_label": None}
    }
    outcomes = golden.compare_results(eval_results)
    assert outcomes[0].status == "unexpected_pass"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_golden_set.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.golden_set'`

- [ ] **Step 3: 实现 `GoldenEntry`、`GoldenSet`、`RegressionOutcome`**

创建 `app/eval/golden_set.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.eval.bad_case_store import BadCaseRecord


@dataclass
class GoldenEntry:
    """已合入 golden set 的 case，用于回归断言。"""

    case_id: str
    added_at: str
    promoted_from: str
    failure_label: Optional[str]
    root_cause: Optional[str]
    expected_pass: bool
    messages: List[Dict[str, str]]
    expected_user_id: str
    expected_intent: str
    order_id: Optional[str]
    expected_write_lock: Optional[str]
    expected_order_status: Optional[str]
    expected_confirmation_status: Optional[str]
    expected_guard_block_reason: Optional[str]
    expected_no_write: bool
    expected_tool_names: List[str]
    expected_assistant_contains: Optional[str]
    max_turns: int
    subset: str
    scenario_family: Optional[str]
    variant_type: Optional[str]
    language_variation_level: Optional[str]
    seed: Optional[int]
    expected_db_assertions: Dict[str, Any]
    expected_tool_sequence: List[str]

    @classmethod
    def from_bad_case_record(
        cls, *, record: BadCaseRecord, promoted_from: str
    ) -> "GoldenEntry":
        """从 BadCaseRecord 构造 GoldenEntry，默认 expected_pass=True。"""
        return cls(
            case_id=record.case_id,
            added_at=datetime.now(timezone.utc).isoformat(),
            promoted_from=promoted_from,
            failure_label=record.failure_label,
            root_cause=record.root_cause,
            expected_pass=True,
            messages=list(record.messages),
            expected_user_id=record.expected_user_id,
            expected_intent=record.expected_intent,
            order_id=record.order_id,
            expected_write_lock=record.expected_write_lock,
            expected_order_status=record.expected_order_status,
            expected_confirmation_status=record.expected_confirmation_status,
            expected_guard_block_reason=record.expected_guard_block_reason,
            expected_no_write=record.expected_no_write,
            expected_tool_names=list(record.expected_tool_names),
            expected_assistant_contains=record.expected_assistant_contains,
            max_turns=record.max_turns,
            subset="golden",
            scenario_family=record.scenario_family,
            variant_type=record.variant_type,
            language_variation_level=record.language_variation_level,
            seed=record.seed,
            expected_db_assertions=dict(record.expected_db_assertions),
            expected_tool_sequence=list(record.expected_tool_sequence),
        )

    def to_yaml_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "added_at": self.added_at,
            "promoted_from": self.promoted_from,
            "failure_label": self.failure_label,
            "root_cause": self.root_cause,
            "expected_pass": self.expected_pass,
            "messages": list(self.messages),
            "expected_user_id": self.expected_user_id,
            "expected_intent": self.expected_intent,
            "order_id": self.order_id,
            "expected_write_lock": self.expected_write_lock,
            "expected_order_status": self.expected_order_status,
            "expected_confirmation_status": self.expected_confirmation_status,
            "expected_guard_block_reason": self.expected_guard_block_reason,
            "expected_no_write": self.expected_no_write,
            "expected_tool_names": list(self.expected_tool_names),
            "expected_assistant_contains": self.expected_assistant_contains,
            "max_turns": self.max_turns,
            "subset": self.subset,
            "scenario_family": self.scenario_family,
            "variant_type": self.variant_type,
            "language_variation_level": self.language_variation_level,
            "seed": self.seed,
            "expected_db_assertions": dict(self.expected_db_assertions),
            "expected_tool_sequence": list(self.expected_tool_sequence),
        }

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "GoldenEntry":
        return cls(
            case_id=data["case_id"],
            added_at=data.get(
                "added_at", datetime.now(timezone.utc).isoformat()
            ),
            promoted_from=data.get("promoted_from", "(unknown)"),
            failure_label=data.get("failure_label"),
            root_cause=data.get("root_cause"),
            expected_pass=data.get("expected_pass", True),
            messages=list(data.get("messages", [])),
            expected_user_id=data["expected_user_id"],
            expected_intent=data["expected_intent"],
            order_id=data.get("order_id"),
            expected_write_lock=data.get("expected_write_lock"),
            expected_order_status=data.get("expected_order_status"),
            expected_confirmation_status=data.get("expected_confirmation_status"),
            expected_guard_block_reason=data.get("expected_guard_block_reason"),
            expected_no_write=data.get("expected_no_write", False),
            expected_tool_names=list(data.get("expected_tool_names", [])),
            expected_assistant_contains=data.get("expected_assistant_contains"),
            max_turns=data.get("max_turns", 8),
            subset=data.get("subset", "golden"),
            scenario_family=data.get("scenario_family"),
            variant_type=data.get("variant_type"),
            language_variation_level=data.get("language_variation_level"),
            seed=data.get("seed"),
            expected_db_assertions=dict(data.get("expected_db_assertions", {})),
            expected_tool_sequence=list(data.get("expected_tool_sequence", [])),
        )

    def to_eval_case(self) -> "EvalCase":  # type: ignore[name-defined]
        """重建为 EvalCase，用于 golden check 执行。"""
        from app.eval.cases import EvalCase

        return EvalCase(
            case_id=self.case_id,
            category=self.scenario_family or self.expected_intent,
            messages=list(self.messages),
            expected_user_id=self.expected_user_id,
            expected_intent=self.expected_intent,
            order_id=self.order_id,
            expected_write_lock=self.expected_write_lock,
            expected_order_status=self.expected_order_status,
            expected_confirmation_status=self.expected_confirmation_status,
            expected_guard_block_reason=self.expected_guard_block_reason,
            expected_no_write=self.expected_no_write,
            expected_tool_names=list(self.expected_tool_names),
            expected_assistant_contains=self.expected_assistant_contains,
            max_turns=self.max_turns,
            subset=self.subset,
            scenario_family=self.scenario_family,
            variant_type=self.variant_type,
            language_variation_level=self.language_variation_level,
            seed=self.seed,
            expected_db_assertions=dict(self.expected_db_assertions),
            expected_tool_sequence=list(self.expected_tool_sequence),
        )


@dataclass
class RegressionOutcome:
    """单个 golden case 的回归对比结果。"""

    case_id: str
    status: str  # "pass" | "regression" | "unexpected_pass" | "missing"
    expected_pass: bool
    actual_passed: Optional[bool]
    failure_label: Optional[str]


class GoldenSet:
    """golden.yaml 的读写、promote、回归对比。"""

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self.entries: List[GoldenEntry] = []

    def load(self) -> None:
        """从文件加载。文件不存在时初始化为空。"""
        self.entries = []
        if not self._path.exists():
            return
        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        for item in data.get("entries", []):
            self.entries.append(GoldenEntry.from_yaml_dict(item))

    def save(self) -> None:
        """写入文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": [entry.to_yaml_dict() for entry in self.entries],
        }
        self._path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def promote(
        self, record: BadCaseRecord, *, promoted_from: str
    ) -> GoldenEntry:
        """将 bad case 合入 golden set。同 case_id 幂等（覆盖）。"""
        existing_idx = None
        for idx, entry in enumerate(self.entries):
            if entry.case_id == record.case_id:
                existing_idx = idx
                break
        entry = GoldenEntry.from_bad_case_record(
            record=record, promoted_from=promoted_from
        )
        if existing_idx is not None:
            self.entries[existing_idx] = entry
        else:
            self.entries.append(entry)
        return entry

    def remove(self, case_id: str) -> bool:
        """从 golden set 移除 case。返回是否实际移除。"""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.case_id != case_id]
        return len(self.entries) < before

    def find(self, case_id: str) -> Optional[GoldenEntry]:
        for entry in self.entries:
            if entry.case_id == case_id:
                return entry
        return None

    def compare_results(
        self, eval_results: Dict[str, Dict[str, Any]]
    ) -> List[RegressionOutcome]:
        """对比 golden 期望与实际 eval 结果。

        eval_results: {case_id: {"passed": bool, "failure_label": str|None}}
        """
        outcomes: List[RegressionOutcome] = []
        for entry in self.entries:
            result = eval_results.get(entry.case_id)
            if result is None:
                outcomes.append(
                    RegressionOutcome(
                        case_id=entry.case_id,
                        status="missing",
                        expected_pass=entry.expected_pass,
                        actual_passed=None,
                        failure_label=None,
                    )
                )
                continue
            actual_passed = bool(result.get("passed"))
            actual_label = result.get("failure_label")
            if entry.expected_pass and actual_passed:
                status = "pass"
            elif entry.expected_pass and not actual_passed:
                status = "regression"
            elif not entry.expected_pass and actual_passed:
                status = "unexpected_pass"
            else:
                # expected_pass=False 且 not actual_passed → 仍为 known-bad，非回归
                status = "pass"
            outcomes.append(
                RegressionOutcome(
                    case_id=entry.case_id,
                    status=status,
                    expected_pass=entry.expected_pass,
                    actual_passed=actual_passed,
                    failure_label=actual_label,
                )
            )
        return outcomes

    def has_regression(self, eval_results: Dict[str, Dict[str, Any]]) -> bool:
        return any(
            outcome.status == "regression"
            for outcome in self.compare_results(eval_results)
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_golden_set.py -v`
Expected: PASS（6 个测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/golden_set.py tests/test_golden_set.py
git commit -m "feat: GoldenEntry 与 GoldenSet 管理 promote 与回归对比"
```

---

## Task 5: Flywheel 编排 — collect 阶段

**Files:**
- Create: `app/eval/flywheel.py`
- Test: `tests/test_flywheel.py`

`Flywheel.collect()` 读取 eval report + 通过 `get_cases(subset)` 重查原始 case，调用现有归因函数，导出 bad case。

- [ ] **Step 1: 写失败测试 — collect 从 report 生成 bad case 记录**

创建 `tests/test_flywheel.py`：

```python
from __future__ import annotations

import json

from app.eval.flywheel import Flywheel


def _report_with_failure(*, case_id: str, subset: str, failure_label: str) -> dict:
    """构造一个含失败 case 的 eval report dict。"""
    return {
        "eval_run_id": "eval-test001",
        "subset": subset,
        "results": [
            {
                "case_id": case_id,
                "passed": False,
                "trial": 0,
                "failure_label": failure_label,
                "failure_category": "tool_selection",
                "trace_artifact_path": "artifacts/phase2/traces/eval-test/case.json",
                "expected_actual_diff": {
                    "expected_tool_names": ["cancel_pending_order"],
                    "actual_tool_names": ["get_order_details"],
                    "missing_tools": ["cancel_pending_order"],
                },
                "actual_guard_block_reasons": [],
                "db_assertion_failures": [],
                "tool_protocol_violations": 0,
                "tool_errors": 0,
                "failed_tool_calls": 0,
                "guard_blocks": 0,
                "blocked_tool_calls": 0,
            }
        ],
    }


def test_collect_extracts_failed_case_to_bad_case_store(tmp_path) -> None:
    """collect 应从 report 提取失败 case 并写入 BadCaseStore。"""
    # 使用 curated_mvp 的真实 case_id（lookup_pending_order 不在失败列表，
    # 这里用 monkeypatch 注入一个会失败的 case）
    report = _report_with_failure(
        case_id="lookup_pending_order",
        subset="curated_mvp",
        failure_label="response_mismatch",
    )

    flywheel = Flywheel(cases_root=tmp_path)
    records = flywheel.collect(
        report=report,
        subset="curated_mvp",
        date_str="2026-06-19",
    )

    assert len(records) == 1
    record = records[0]
    assert record.case_id == "lookup_pending_order"
    assert record.failure_label == "response_mismatch"
    assert record.root_cause == "model_reasoning_gap"
    assert record.failure_source == "response"
    # 从 EvalCase 重查的字段
    assert record.expected_user_id  # curated case 有 user_id
    assert record.messages  # curated case 有 messages


def test_collect_skips_passed_cases(tmp_path) -> None:
    report = {
        "eval_run_id": "eval-test002",
        "subset": "curated_mvp",
        "results": [
            {
                "case_id": "lookup_pending_order",
                "passed": True,
                "trial": 0,
                "failure_label": None,
            }
        ],
    }
    flywheel = Flywheel(cases_root=tmp_path)
    records = flywheel.collect(
        report=report, subset="curated_mvp", date_str="2026-06-19"
    )
    assert records == []


def test_collect_unknown_case_id_skipped_with_warning(tmp_path) -> None:
    """report 中 case_id 在 get_cases(subset) 中找不到时，跳过并记录。"""
    report = _report_with_failure(
        case_id="nonexistent_case_xyz",
        subset="curated_mvp",
        failure_label="response_mismatch",
    )
    flywheel = Flywheel(cases_root=tmp_path)
    records = flywheel.collect(
        report=report, subset="curated_mvp", date_str="2026-06-19"
    )
    assert records == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.flywheel'`

- [ ] **Step 3: 实现 `Flywheel.collect()`**

创建 `app/eval/flywheel.py`：

```python
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app.eval.bad_case_store import BadCaseRecord, BadCaseStore
from app.eval.cases import EvalCase, get_cases
from app.eval.golden_set import GoldenSet, RegressionOutcome
from app.eval.live_triage import classify_failure, infer_root_cause

logger = logging.getLogger(__name__)

# failure_label → failure_source 映射（从 metrics.py 同步）
_FAILURE_LABEL_TO_SOURCE = {
    "wrong_intent": "parsing",
    "auth_failure": "parsing",
    "wrong_tool": "planning",
    "wrong_tool_sequence": "planning",
    "llm_json_failure": "planning",
    "expected_guard_block_missing": "guard",
    "guard_blocked": "guard",
    "confirmation_status_mismatch": "response",
    "confirmation_failure": "response",
    "response_mismatch": "response",
    "tool_exception": "tool_mutation",
    "unexpected_mutation": "tool_mutation",
    "mutation_missing": "tool_mutation",
    "db_state_mismatch": "tool_mutation",
    "db_assertion_mismatch": "tool_mutation",
}


def _failure_source_for(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    return _FAILURE_LABEL_TO_SOURCE.get(label, "unknown")


class Flywheel:
    """四阶段飞轮编排：collect → generate → promote → check。"""

    def __init__(
        self,
        *,
        cases_root: Path,
        golden_path: Optional[Path] = None,
    ) -> None:
        self._cases_root = cases_root
        self._store = BadCaseStore(root=cases_root)
        self._golden_path = golden_path or (cases_root.parent / "golden.yaml")

    @property
    def bad_case_store(self) -> BadCaseStore:
        return self._store

    @property
    def golden_set(self) -> GoldenSet:
        golden = GoldenSet(path=self._golden_path)
        golden.load()
        return golden

    # ── Stage 1: collect ──

    def collect(
        self,
        *,
        report: Mapping[str, Any],
        subset: str,
        date_str: str,
    ) -> List[BadCaseRecord]:
        """从 eval report 提取失败 case，归因后写入 BadCaseStore。

        需要 subset 参数以通过 get_cases(subset) 重查原始 case 定义
        （report JSON 不含 messages/expected_tool_names 等字段）。
        """
        case_index = self._build_case_index(subset)
        failed_results = self._extract_failed_results(report)
        records: List[BadCaseRecord] = []
        for result in failed_results:
            case_id = result.get("case_id")
            case = case_index.get(case_id) if case_id else None
            if case is None:
                logger.warning(
                    "collect: case_id=%r not found in subset=%r, skipping",
                    case_id,
                    subset,
                )
                continue
            record = self._build_record(case=case, result=result)
            records.append(record)

        if records:
            self._store.write_records(records, date_str=date_str)
        return records

    def _build_case_index(self, subset: str) -> Dict[str, EvalCase]:
        return {case.case_id: case for case in get_cases(subset)}

    def _extract_failed_results(
        self, report: Mapping[str, Any]
    ) -> List[Mapping[str, Any]]:
        results = report.get("results", [])
        return [
            result
            for result in results
            if isinstance(result, Mapping) and result.get("passed") is not True
        ]

    def _build_record(
        self, *, case: EvalCase, result: Mapping[str, Any]
    ) -> BadCaseRecord:
        failure_label = result.get("failure_label")
        failure_bucket = classify_failure(result)
        root_cause = infer_root_cause(result)
        failure_source = _failure_source_for(failure_label)
        diagnostics = self._build_diagnostics(result)
        return BadCaseRecord.from_eval_case(
            case=case,
            source_case_id=case.case_id,
            failure_label=failure_label,
            failure_bucket=failure_bucket,
            root_cause=root_cause,
            failure_source=failure_source,
            diagnostics=diagnostics,
        )

    def _build_diagnostics(self, result: Mapping[str, Any]) -> Dict[str, Any]:
        diff = result.get("expected_actual_diff") or {}
        return {
            "actual_tool_names": list(diff.get("actual_tool_names", [])),
            "missing_tools": list(diff.get("missing_tools", [])),
            "unexpected_tools": list(diff.get("unexpected_tools", [])),
            "actual_guard_block_reasons": list(
                result.get("actual_guard_block_reasons", [])
            ),
            "trace_artifact_path": result.get("trace_artifact_path"),
            "suggested_next_action": self._next_action_for_bucket(
                classify_failure(result)
            ),
        }

    def _next_action_for_bucket(self, bucket: str) -> str:
        from app.eval.live_triage import _NEXT_ACTIONS

        return _NEXT_ACTIONS.get(bucket, "Inspect the trace manually.")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py -v`
Expected: PASS（3 个测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/flywheel.py tests/test_flywheel.py
git commit -m "feat: Flywheel collect 阶段 — eval failure → bad case 归因"
```

---

## Task 6: Flywheel 编排 — generate 阶段

**Files:**
- Modify: `app/eval/flywheel.py`
- Test: `tests/test_flywheel.py`

`Flywheel.generate()` 对有 `variant_type` 的 bad case 调用 `build_language_variants()` 生成 L1/L2 变体。

- [ ] **Step 1: 追加失败测试 — generate 为 variant case 生成语言变体**

在 `tests/test_flywheel.py` 末尾追加：

```python
def test_generate_creates_language_variants_for_variant_case(tmp_path) -> None:
    """对有 variant_type 的 bad case，generate 应生成 L1/L2 变体。"""
    from app.eval.bad_case_store import BadCaseRecord

    record = BadCaseRecord(
        case_id="cancel_success_s100",
        source_case_id="cancel_success_s100",
        failure_label="response_mismatch",
        failure_bucket="response_oracle",
        root_cause="model_reasoning_gap",
        failure_source="response",
        promoted=False,
        messages=[{"role": "user", "content": "My email is a@b.com. Cancel order #W1111111 because no longer needed."}, {"role": "user", "content": "yes"}],
        expected_user_id="amanda_wexler",
        expected_intent="cancel_order",
        order_id="#W1111111",
        expected_write_lock=None,
        expected_order_status="cancelled",
        expected_confirmation_status=None,
        expected_guard_block_reason=None,
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
        expected_assistant_contains=None,
        max_turns=8,
        subset="generalization",
        scenario_family="cancel",
        variant_type="cancel_success",
        language_variation_level="base",
        seed=100,
        expected_db_assertions={},
        expected_tool_sequence=[],
        diagnostics={},
    )

    flywheel = Flywheel(cases_root=tmp_path)
    variants = flywheel.generate(records=[record])

    # base + L1 + L2（L3 gate=False 不生成）
    levels = {v.language_variation_level for v in variants}
    assert "L1" in levels
    assert "L2" in levels
    for v in variants:
        assert v.variant_type == "cancel_success"
        assert v.seed == 100
        assert v.source_case_id == "cancel_success_s100"


def test_generate_skips_case_without_variant_type(tmp_path) -> None:
    """curated hand-written case（无 variant_type）不生成变体。"""
    from app.eval.bad_case_store import BadCaseRecord

    record = BadCaseRecord(
        case_id="curated_lookup_001",
        source_case_id="curated_lookup_001",
        failure_label="response_mismatch",
        failure_bucket="response_oracle",
        root_cause="model_reasoning_gap",
        failure_source="response",
        promoted=False,
        messages=[{"role": "user", "content": "where is my order"}],
        expected_user_id="U1001",
        expected_intent="lookup_order",
        order_id=None,
        expected_write_lock=None,
        expected_order_status=None,
        expected_confirmation_status=None,
        expected_guard_block_reason=None,
        expected_no_write=False,
        expected_tool_names=[],
        expected_assistant_contains=None,
        max_turns=8,
        subset="curated_mvp",
        scenario_family=None,
        variant_type=None,
        language_variation_level=None,
        seed=None,
        expected_db_assertions={},
        expected_tool_sequence=[],
        diagnostics={},
    )

    flywheel = Flywheel(cases_root=tmp_path)
    variants = flywheel.generate(records=[record])
    assert variants == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py::test_generate_creates_language_variants_for_variant_case tests/test_flywheel.py::test_generate_skips_case_without_variant_type -v`
Expected: FAIL（`Flywheel.generate` 未定义）

- [ ] **Step 3: 实现 `Flywheel.generate()`**

在 `app/eval/flywheel.py` 的 `Flywheel` 类中追加：

```python
    # ── Stage 2: generate ──

    def generate(
        self,
        *,
        records: List[BadCaseRecord],
        levels: Optional[tuple] = None,
    ) -> List[BadCaseRecord]:
        """对有 variant_type 的 bad case 生成 L1/L2 语言变体。

        curated/tau hand-written case（无 variant_type）跳过，因 oracle 无法推导。
        """
        from app.synthetic.generator import SyntheticDBGenerator
        from app.synthetic.language_variation import build_language_variants

        gate_levels = levels or ("base", "L1", "L2")
        variants: List[BadCaseRecord] = []
        for record in records:
            if not record.variant_type:
                logger.info(
                    "generate: case_id=%r has no variant_type, skipping",
                    record.case_id,
                )
                continue
            entities = self._rebuild_entities(record)
            language_variants = build_language_variants(
                record.messages, record.variant_type, entities
            )
            for lang_var in language_variants:
                if lang_var.level not in gate_levels:
                    continue
                variant_record = self._build_variant_record(
                    base=record, lang_var=lang_var
                )
                variants.append(variant_record)
        return variants

    def _rebuild_entities(self, record: BadCaseRecord) -> dict:
        """从 seed 重建 synthetic world，选出对应 entities。"""
        from app.synthetic.generator import SyntheticDBGenerator
        from app.synthetic.oracle import select_entity_for_variant

        if record.seed is None:
            # 无 seed 的 variant case（理论上不应发生，但防御）
            return {"user": {"email": "(unknown)"}, "order": None}
        world = SyntheticDBGenerator.from_seed(record.seed)
        return select_entity_for_variant(world, record.variant_type)

    def _build_variant_record(
        self, *, base: BadCaseRecord, lang_var
    ) -> BadCaseRecord:
        """基于 language variant 构造新的 BadCaseRecord。"""
        return BadCaseRecord(
            case_id=f"{base.source_case_id}_{lang_var.level}",
            source_case_id=base.source_case_id,
            failure_label=base.failure_label,
            failure_bucket=base.failure_bucket,
            root_cause=base.root_cause,
            failure_source=base.failure_source,
            promoted=False,
            messages=list(lang_var.messages),
            expected_user_id=base.expected_user_id,
            expected_intent=base.expected_intent,
            order_id=base.order_id,
            expected_write_lock=base.expected_write_lock,
            expected_order_status=base.expected_order_status,
            expected_confirmation_status=base.expected_confirmation_status,
            expected_guard_block_reason=base.expected_guard_block_reason,
            expected_no_write=base.expected_no_write,
            expected_tool_names=list(base.expected_tool_names),
            expected_assistant_contains=base.expected_assistant_contains,
            max_turns=base.max_turns,
            subset=base.subset,
            scenario_family=base.scenario_family,
            variant_type=base.variant_type,
            language_variation_level=lang_var.level,
            seed=base.seed,
            expected_db_assertions=dict(base.expected_db_assertions),
            expected_tool_sequence=list(base.expected_tool_sequence),
            diagnostics={"generated_from": base.case_id},
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py -v`
Expected: PASS（5 个测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/flywheel.py tests/test_flywheel.py
git commit -m "feat: Flywheel generate 阶段 — bad case → 语言变体"
```

---

## Task 7: 注册 golden subset 到 cases.py

**Files:**
- Modify: `app/eval/cases.py:983-1037`

让 `get_cases("golden")` 从 `cases/golden.yaml` 加载，作为 `flywheel check` 的执行入口。

- [ ] **Step 1: 写失败测试 — get_cases("golden") 从 YAML 加载**

在 `tests/test_flywheel.py` 末尾追加：

```python
def test_get_cases_golden_loads_from_yaml(tmp_path) -> None:
    """get_cases('golden') 应从 golden.yaml 加载 EvalCase 列表。"""
    import os

    from app.eval.golden_set import GoldenSet

    # 构造一个 golden.yaml
    golden_path = tmp_path / "golden.yaml"
    golden = GoldenSet(path=golden_path)
    record = _record_for_golden()
    golden.promote(record, promoted_from="bad_cases/test.yaml")
    golden.save()

    # monkeypatch GOLDEN_YAML_PATH
    import app.eval.cases as cases_module

    original = cases_module.GOLDEN_YAML_PATH
    cases_module.GOLDEN_YAML_PATH = golden_path
    try:
        cases = cases_module.get_cases("golden")
    finally:
        cases_module.GOLDEN_YAML_PATH = original

    assert len(cases) == 1
    assert cases[0].case_id == "cancel_001_L1"
    assert cases[0].subset == "golden"


def _record_for_golden():
    from app.eval.bad_case_store import BadCaseRecord

    return BadCaseRecord(
        case_id="cancel_001_L1",
        source_case_id="cancel_001",
        failure_label="wrong_tool",
        failure_bucket="tool_selection",
        root_cause="prompt_gap",
        failure_source="planning",
        promoted=False,
        messages=[{"role": "user", "content": "Void my order"}],
        expected_user_id="U1001",
        expected_intent="cancel_order",
        order_id="#W1234567",
        expected_write_lock=None,
        expected_order_status="cancelled",
        expected_confirmation_status=None,
        expected_guard_block_reason=None,
        expected_no_write=False,
        expected_tool_names=["cancel_pending_order"],
        expected_assistant_contains=None,
        max_turns=8,
        subset="generalization",
        scenario_family="cancel",
        variant_type="cancel_success",
        language_variation_level="L1",
        seed=100,
        expected_db_assertions={},
        expected_tool_sequence=[],
        diagnostics={},
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py::test_get_cases_golden_loads_from_yaml -v`
Expected: FAIL（`get_cases("golden")` 抛 `ValueError: unsupported subset: golden` 或 `GOLDEN_YAML_PATH` 未定义）

- [ ] **Step 3: 注册 `golden` subset**

在 `app/eval/cases.py` 顶部（import 区之后）添加模块级常量：

```python
from pathlib import Path

GOLDEN_YAML_PATH = Path(__file__).parent.parent.parent / "cases" / "golden.yaml"
```

在 `get_cases()` 函数中（`raise ValueError` 之前）添加：

```python
    if subset == "golden":
        return _load_golden_cases()
```

在 `get_cases()` 函数之后添加：

```python
def _load_golden_cases() -> List[EvalCase]:
    """从 cases/golden.yaml 加载 golden EvalCase 列表。"""
    from app.eval.golden_set import GoldenSet

    if not GOLDEN_YAML_PATH.exists():
        return []
    golden = GoldenSet(path=GOLDEN_YAML_PATH)
    golden.load()
    return [entry.to_eval_case() for entry in golden.entries]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py::test_get_cases_golden_loads_from_yaml -v`
Expected: PASS

- [ ] **Step 5: 验证不破坏现有 subset**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -c "from app.eval.cases import get_cases; print(len(get_cases('curated_mvp'))); print(len(get_cases('golden')))"`
Expected: 打印 `11` 和 `0`（golden.yaml 尚不存在）

- [ ] **Step 6: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/cases.py tests/test_flywheel.py
git commit -m "feat: 注册 golden subset 从 golden.yaml 加载"
```

---

## Task 8: Flywheel 编排 — check 阶段（回归校验）

**Files:**
- Modify: `app/eval/flywheel.py`
- Test: `tests/test_flywheel.py`

`Flywheel.check()` 调用 `CuratedEvalRunner` 跑 golden subset，对比结果输出回归报告。

- [ ] **Step 1: 追加失败测试 — check 调用 runner 并对比结果**

在 `tests/test_flywheel.py` 末尾追加：

```python
def test_check_compares_golden_against_eval_results_and_detects_regression(
    tmp_path,
    monkeypatch,
) -> None:
    """check 应调用 runner 跑 golden subset 并对比结果。

    用 mock runner 避免真实 LLM 调用。
    """
    from app.eval.bad_case_store import BadCaseRecord
    from app.eval.golden_set import GoldenSet

    # 构造 golden set
    golden_path = tmp_path / "golden.yaml"
    golden = GoldenSet(path=golden_path)
    record = _record_for_golden()
    golden.promote(record, promoted_from="bad_cases/test.yaml")
    golden.save()

    flywheel = Flywheel(cases_root=tmp_path, golden_path=golden_path)

    # mock runner：返回模拟结果（case fail → 回归）
    captured = {}

    def fake_run_summary(*, cases, runner=None):
        captured["cases"] = cases
        return {
            record.case_id: {
                "passed": False,
                "failure_label": "wrong_tool",
            }
        }

    monkeypatch.setattr(flywheel, "_run_golden_cases", fake_run_summary)

    result = flywheel.check()
    assert result.has_regression is True
    assert len(result.outcomes) == 1
    assert result.outcomes[0].status == "regression"


def test_check_reports_no_regression_when_all_pass(tmp_path, monkeypatch) -> None:
    from app.eval.golden_set import GoldenSet

    golden_path = tmp_path / "golden.yaml"
    golden = GoldenSet(path=golden_path)
    record = _record_for_golden()
    golden.promote(record, promoted_from="bad_cases/test.yaml")
    golden.save()

    flywheel = Flywheel(cases_root=tmp_path, golden_path=golden_path)
    monkeypatch.setattr(
        flywheel,
        "_run_golden_cases",
        lambda **kw: {record.case_id: {"passed": True, "failure_label": None}},
    )

    result = flywheel.check()
    assert result.has_regression is False
    assert result.outcomes[0].status == "pass"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py::test_check_compares_golden_against_eval_results_and_detects_regression tests/test_flywheel.py::test_check_reports_no_regression_when_all_pass -v`
Expected: FAIL（`Flywheel.check` / `_run_golden_cases` 未定义）

- [ ] **Step 3: 实现 `Flywheel.check()` 与 `GoldenCheckResult`**

在 `app/eval/flywheel.py` 顶部 import 区追加：

```python
from dataclasses import dataclass, field
```

在 `Flywheel` 类之前添加 dataclass：

```python
@dataclass
class GoldenCheckResult:
    """flywheel check 的回归报告。"""

    outcomes: List[RegressionOutcome]
    has_regression: bool
    pass_count: int
    regression_count: int
    unexpected_pass_count: int
    missing_count: int

    @classmethod
    def from_outcomes(
        cls, outcomes: List[RegressionOutcome]
    ) -> "GoldenCheckResult":
        from collections import Counter

        status_counts = Counter(o.status for o in outcomes)
        return cls(
            outcomes=outcomes,
            has_regression=status_counts.get("regression", 0) > 0,
            pass_count=status_counts.get("pass", 0),
            regression_count=status_counts.get("regression", 0),
            unexpected_pass_count=status_counts.get("unexpected_pass", 0),
            missing_count=status_counts.get("missing", 0),
        )
```

在 `Flywheel` 类中追加：

```python
    # ── Stage 4: check ──

    def check(
        self,
        *,
        live: bool = True,
        config: Optional["AppConfig"] = None,  # type: ignore[name-defined]
    ) -> GoldenCheckResult:
        """跑 golden subset，对比结果输出回归报告。

        调用 CuratedEvalRunner 执行 golden subset。
        """
        cases = get_cases("golden")
        eval_results = self._run_golden_cases(
            cases=cases, live=live, config=config
        )
        golden = self.golden_set
        outcomes = golden.compare_results(eval_results)
        return GoldenCheckResult.from_outcomes(outcomes)

    def _run_golden_cases(
        self,
        *,
        cases: List[EvalCase],
        live: bool = True,
        config: Optional["AppConfig"] = None,  # type: ignore[name-defined]
    ) -> Dict[str, Dict[str, Any]]:
        """执行 golden cases，返回 {case_id: {"passed": bool, "failure_label": str|None}}。

        默认走 CuratedEvalRunner；测试中可 monkeypatch 此方法避免真实 LLM。
        """
        from app.config import resolve_config
        from app.eval.runner import CuratedEvalRunner

        resolved_config = config or resolve_config()
        runner = CuratedEvalRunner(
            config=resolved_config,
            artifact_dir=resolved_config.artifact_dir,
            live=live,
        )
        summary = runner.run(subset="golden")
        return {
            result.case_id: {
                "passed": result.passed,
                "failure_label": result.failure_label,
            }
            for result in summary.results
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel.py -v`
Expected: PASS（全部测试，含 mock 的 check 测试）

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/eval/flywheel.py tests/test_flywheel.py
git commit -m "feat: Flywheel check 阶段 — golden 回归校验"
```

---

## Task 9: CLI 入口 — flywheel collect/generate/golden/check

**Files:**
- Create: `app/cli/flywheel.py`
- Test: `tests/test_flywheel_cli.py`

argparse CLI，串联四阶段。

- [ ] **Step 1: 写失败测试 — CLI 子命令解析**

创建 `tests/test_flywheel_cli.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

from app.cli.flywheel import flywheel_main


def test_flywheel_cli_collect_reads_report_and_writes_bad_case(
    tmp_path, monkeypatch
) -> None:
    """CLI collect 子命令应读取 report 并写入 bad case。"""
    report = {
        "eval_run_id": "eval-cli001",
        "subset": "curated_mvp",
        "results": [
            {
                "case_id": "lookup_pending_order",
                "passed": False,
                "trial": 0,
                "failure_label": "response_mismatch",
                "failure_category": "response_oracle",
                "expected_actual_diff": {},
                "actual_guard_block_reasons": [],
                "db_assertion_failures": [],
                "tool_protocol_violations": 0,
                "tool_errors": 0,
                "failed_tool_calls": 0,
                "guard_blocks": 0,
                "blocked_tool_calls": 0,
            }
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    cases_root = tmp_path / "cases"
    exit_code = flywheel_main(
        [
            "collect",
            "--report",
            str(report_path),
            "--subset",
            "curated_mvp",
            "--cases-root",
            str(cases_root),
            "--date",
            "2026-06-19",
        ]
    )
    assert exit_code == 0
    bad_case_file = cases_root / "bad_cases" / "2026-06-19.yaml"
    assert bad_case_file.exists()


def test_flywheel_cli_check_returns_nonzero_on_regression(
    tmp_path, monkeypatch
) -> None:
    """有回归时 check 应返回退出码 1。"""
    cases_root = tmp_path / "cases"
    golden_path = tmp_path / "golden.yaml"

    # 构造 golden set
    from app.eval.bad_case_store import BadCaseRecord
    from app.eval.golden_set import GoldenSet

    golden = GoldenSet(path=golden_path)
    golden.promote(
        BadCaseRecord(
            case_id="cancel_001_L1",
            source_case_id="cancel_001",
            failure_label="wrong_tool",
            failure_bucket="tool_selection",
            root_cause="prompt_gap",
            failure_source="planning",
            promoted=False,
            messages=[{"role": "user", "content": "Void my order"}],
            expected_user_id="U1001",
            expected_intent="cancel_order",
            order_id="#W1234567",
            expected_write_lock=None,
            expected_order_status="cancelled",
            expected_confirmation_status=None,
            expected_guard_block_reason=None,
            expected_no_write=False,
            expected_tool_names=["cancel_pending_order"],
            expected_assistant_contains=None,
            max_turns=8,
            subset="generalization",
            scenario_family="cancel",
            variant_type="cancel_success",
            language_variation_level="L1",
            seed=100,
            expected_db_assertions={},
            expected_tool_sequence=[],
            diagnostics={},
        ),
        promoted_from="bad_cases/test.yaml",
    )
    golden.save()

    # mock check 避免真实 LLM
    from app.eval.flywheel import GoldenCheckResult
    from app.eval.golden_set import RegressionOutcome

    import app.cli.flywheel as cli_module

    original_factory = cli_module._build_flywheel

    class FakeFlywheel:
        def check(self, **kw):
            return GoldenCheckResult.from_outcomes(
                [
                    RegressionOutcome(
                        case_id="cancel_001_L1",
                        status="regression",
                        expected_pass=True,
                        actual_passed=False,
                        failure_label="wrong_tool",
                    )
                ]
            )

    def fake_factory(*, cases_root, golden_path):
        return FakeFlywheel()

    monkeypatch.setattr(cli_module, "_build_flywheel", fake_factory)

    exit_code = flywheel_main(
        ["check", "--cases-root", str(cases_root), "--golden-path", str(golden_path)]
    )
    assert exit_code == 1


def test_flywheel_cli_status_shows_counts(tmp_path) -> None:
    """status 子命令应输出 bad case 和 golden 数量。"""
    cases_root = tmp_path / "cases"
    golden_path = tmp_path / "golden.yaml"
    golden_path.write_text("version: 1\nentries: []\n", encoding="utf-8")

    exit_code = flywheel_main(
        [
            "status",
            "--cases-root",
            str(cases_root),
            "--golden-path",
            str(golden_path),
        ]
    )
    assert exit_code == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cli.flywheel'`

- [ ] **Step 3: 实现 CLI**

创建 `app/cli/flywheel.py`：

```python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.eval.flywheel import Flywheel


def flywheel_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bad Case 数据飞轮 — collect/generate/golden/check"
    )
    argv = list(argv) if argv is not None else sys.argv[1:]
    subparsers = parser.add_subparsers(dest="command", required=True)

    # collect
    collect_p = subparsers.add_parser("collect", help="从 eval report 收集 bad case")
    collect_p.add_argument("--report", required=True, help="eval report JSON 路径")
    collect_p.add_argument(
        "--subset", required=True, help="report 对应的 subset（用于重查 case 定义）"
    )
    collect_p.add_argument("--cases-root", default="cases")
    collect_p.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="bad case 文件日期（YYYY-MM-DD）",
    )

    # generate
    gen_p = subparsers.add_parser("generate", help="为 bad case 生成语言变体")
    gen_p.add_argument("--input", help="输入 bad_cases YAML（默认最新）")
    gen_p.add_argument("--output", help="输出变体 YAML 路径")
    gen_p.add_argument("--cases-root", default="cases")

    # golden promote
    promote_p = subparsers.add_parser(
        "golden", help="管理 golden set"
    )
    golden_sub = promote_p.add_subparsers(dest="golden_command", required=True)

    promote_single = golden_sub.add_parser("promote", help="合入 golden set")
    promote_single.add_argument("case_id", help="要合入的 case_id")
    promote_single.add_argument("--batch", help="批量从 bad_cases YAML 合入")
    promote_single.add_argument("--yes", action="store_true", help="跳过确认")
    promote_single.add_argument("--cases-root", default="cases")
    promote_single.add_argument("--golden-path", default="cases/golden.yaml")

    golden_sub.add_parser("list", help="列出 golden set").add_argument(
        "--golden-path", default="cases/golden.yaml"
    )

    golden_sub.add_parser("remove", help="从 golden 移除").add_argument("case_id")

    # check
    check_p = subparsers.add_parser("check", help="golden 回归校验")
    check_p.add_argument("--live", action="store_true", help="使用真实 LLM")
    check_p.add_argument("--cases-root", default="cases")
    check_p.add_argument("--golden-path", default="cases/golden.yaml")

    # status
    status_p = subparsers.add_parser("status", help="显示飞轮统计")
    status_p.add_argument("--cases-root", default="cases")
    status_p.add_argument("--golden-path", default="cases/golden.yaml")

    args = parser.parse_args(argv)

    if args.command == "collect":
        return _cmd_collect(args)
    if args.command == "generate":
        return _cmd_generate(args)
    if args.command == "golden":
        return _cmd_golden(args)
    if args.command == "check":
        return _cmd_check(args)
    if args.command == "status":
        return _cmd_status(args)
    return 1


def _build_flywheel(*, cases_root: Path, golden_path: Path) -> Flywheel:
    return Flywheel(cases_root=cases_root, golden_path=golden_path)


def _cmd_collect(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    flywheel = _build_flywheel(
        cases_root=Path(args.cases_root), golden_path=Path("cases/golden.yaml")
    )
    records = flywheel.collect(
        report=report, subset=args.subset, date_str=args.date
    )
    print(f"collected {len(records)} bad case(s) to cases/bad_cases/{args.date}.yaml")
    for record in records:
        print(
            f"  - {record.case_id}: {record.failure_label} "
            f"({record.root_cause} / {record.failure_source})"
        )
    return 0


def _cmd_generate(args) -> int:
    flywheel = _build_flywheel(
        cases_root=Path(args.cases_root), golden_path=Path("cases/golden.yaml")
    )
    if args.input:
        from app.eval.bad_case_store import BadCaseStore

        store = flywheel.bad_case_store
        records = store._read_file(Path(args.input))
    else:
        records = flywheel.bad_case_store.list_all_records()
    variants = flywheel.generate(records=records)
    print(f"generated {len(variants)} variant(s) from {len(records)} bad case(s)")
    for v in variants:
        print(f"  - {v.case_id} ({v.language_variation_level})")
    if variants:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        flywheel.bad_case_store.write_records(variants, date_str=f"{date_str}_variants")
    return 0


def _cmd_golden(args) -> int:
    if args.golden_command == "promote":
        return _cmd_golden_promote(args)
    if args.golden_command == "list":
        return _cmd_golden_list(args)
    if args.golden_command == "remove":
        return _cmd_golden_remove(args)
    return 1


def _cmd_golden_promote(args) -> int:
    flywheel = _build_flywheel(
        cases_root=Path(args.cases_root), golden_path=Path(args.golden_path)
    )
    golden = flywheel.golden_set

    if args.batch:
        from app.eval.bad_case_store import BadCaseStore

        records = flywheel.bad_case_store._read_file(Path(args.batch))
        promoted = 0
        for record in records:
            if not args.yes:
                print(f"\n--- {record.case_id} ---")
                print(f"  failure_label: {record.failure_label}")
                print(f"  root_cause: {record.root_cause}")
                print(f"  suggested: {record.diagnostics.get('suggested_next_action')}")
                answer = input("promote? [y/N/q] ").strip().lower()
                if answer == "q":
                    break
                if answer != "y":
                    continue
            golden.promote(record, promoted_from=str(args.batch))
            promoted += 1
        golden.save()
        print(f"promoted {promoted} case(s) to {args.golden_path}")
        return 0

    record = flywheel.bad_case_store.find_by_case_id(args.case_id)
    if record is None:
        print(f"case_id not found: {args.case_id}", file=sys.stderr)
        return 1
    if not args.yes:
        print(f"--- {record.case_id} ---")
        print(f"  failure_label: {record.failure_label}")
        print(f"  root_cause: {record.root_cause}")
        print(f"  suggested: {record.diagnostics.get('suggested_next_action')}")
        answer = input("promote? [y/N] ").strip().lower()
        if answer != "y":
            print("aborted")
            return 0
    golden.promote(record, promoted_from=f"bad_cases/{args.case_id}")
    golden.save()
    print(f"promoted {args.case_id} to {args.golden_path}")
    return 0


def _cmd_golden_list(args) -> int:
    from app.eval.golden_set import GoldenSet

    golden = GoldenSet(path=Path(args.golden_path))
    golden.load()
    print(f"golden set: {len(golden.entries)} case(s)")
    for entry in golden.entries:
        status = "expected_pass" if entry.expected_pass else "known_bad"
        print(
            f"  - {entry.case_id} [{status}] "
            f"(was {entry.failure_label}, from {entry.promoted_from})"
        )
    return 0


def _cmd_golden_remove(args) -> int:
    from app.eval.golden_set import GoldenSet

    golden = GoldenSet(path=Path(args.golden_path))
    golden.load()
    if golden.remove(args.case_id):
        golden.save()
        print(f"removed {args.case_id} from golden set")
        return 0
    print(f"case_id not in golden set: {args.case_id}", file=sys.stderr)
    return 1


def _cmd_check(args) -> int:
    flywheel = _build_flywheel(
        cases_root=Path(args.cases_root), golden_path=Path(args.golden_path)
    )
    result = flywheel.check(live=args.live)
    print(f"golden check: {result.pass_count} pass, {result.regression_count} regression, "
          f"{result.unexpected_pass_count} unexpected_pass, {result.missing_count} missing")
    for outcome in result.outcomes:
        if outcome.status != "pass":
            print(
                f"  [{outcome.status}] {outcome.case_id} "
                f"(expected_pass={outcome.expected_pass}, actual={outcome.actual_passed})"
            )
    return 1 if result.has_regression else 0


def _cmd_status(args) -> int:
    from app.eval.golden_set import GoldenSet

    flywheel = _build_flywheel(
        cases_root=Path(args.cases_root), golden_path=Path(args.golden_path)
    )
    bad_cases = flywheel.bad_case_store.list_all_records()
    golden = GoldenSet(path=Path(args.golden_path))
    golden.load()
    unpromoted = [r for r in bad_cases if not r.promoted]

    print("Bad Case Flywheel Status")
    print(f"  bad cases (total):    {len(bad_cases)}")
    print(f"  bad cases (unpromoted): {len(unpromoted)}")
    print(f"  golden set:           {len(golden.entries)}")

    from collections import Counter

    source_counts = Counter(r.failure_source for r in bad_cases if r.failure_source)
    if source_counts:
        print("  failure sources:")
        for source, count in source_counts.most_common():
            print(f"    {source}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(flywheel_main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/test_flywheel_cli.py -v`
Expected: PASS（3 个测试）

- [ ] **Step 5: 验证 CLI 可执行**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run flywheel --help`
Expected: 打印 help，含 collect/generate/golden/check/status 子命令

- [ ] **Step 6: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add app/cli/flywheel.py tests/test_flywheel_cli.py
git commit -m "feat: flywheel CLI 入口 — collect/generate/golden/check/status"
```

---

## Task 10: 初始化 golden.yaml 与端到端验证

**Files:**
- Create: `cases/golden.yaml`
- Create: `cases/bad_cases/.gitkeep`

- [ ] **Step 1: 创建初始 golden.yaml**

创建 `cases/golden.yaml`：

```yaml
# Bad Case 数据飞轮 — Golden Regression Set
# 由 `uv run flywheel golden promote <case_id>` 合入，不要手动添加
version: 1
entries: []
```

创建 `cases/bad_cases/.gitkeep`（空文件，确保目录 git-tracked）。

- [ ] **Step 2: 更新 .gitignore（如需）**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && cat .gitignore 2>/dev/null | head -20`
检查 `cases/` 是否被 ignore。若被 ignore，添加例外：

```
!cases/golden.yaml
!cases/bad_cases/
```

- [ ] **Step 3: 端到端 smoke test**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run flywheel status --golden-path cases/golden.yaml`
Expected: 打印 `golden set: 0`，无错误

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run flywheel golden list --golden-path cases/golden.yaml`
Expected: 打印 `golden set: 0 case(s)`，无错误

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -c "from app.eval.cases import get_cases; print(len(get_cases('golden')))"`
Expected: 打印 `0`

- [ ] **Step 4: 运行全量测试确保无回归**

Run: `cd /Users/theyang/Documents/ai/retail-customer-support-agent && uv run python -m pytest tests/ -v 2>&1 | tail -20`
Expected: 全部测试 PASS，无新增 FAIL

- [ ] **Step 5: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add cases/golden.yaml cases/bad_cases/.gitkeep .gitignore
git commit -m "chore: 初始化 golden.yaml 与 bad_cases 目录"
```

---

## Task 11: 文档更新

**Files:**
- Modify: `AGENTS.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: 更新 AGENTS.md Architecture 段**

在 `## Architecture` 的架构图中追加飞轮组件：

```
user msg → AgentRuntime → AgentLoop ──LLM──→ DeepSeek
                │              │
                ▼              ▼
         preflight        ToolGateway ──→ WriteActionGuard (7层)
         (身份/确认)         │
                            ▼
                       RetailAdapter (tau2-bench / local db.json)

eval report ──→ Flywheel ──→ cases/bad_cases/ ──→ golden.yaml ──→ 回归
                  (collect/generate/promote/check)
```

在文件列表中追加：

```
- `app/eval/flywheel.py` — Bad Case 数据飞轮四阶段编排
- `app/eval/bad_case_store.py` — bad case YAML I/O
- `app/eval/golden_set.py` — golden set 管理与回归对比
- `app/cli/flywheel.py` — `flywheel` CLI 入口
```

- [ ] **Step 2: 更新 AGENTS.md Quick start 段**

在 Quick start 追加飞轮命令示例：

```bash
uv run flywheel collect --report <report.json> --subset <subset>  # 收集 bad case
uv run flywheel generate                                          # 生成变体
uv run flywheel golden promote <case_id>                          # 合入 golden
uv run flywheel check --live                                      # 回归校验
uv run flywheel status                                            # 飞轮统计
```

- [ ] **Step 3: 更新 HANDOFF.md**

在 Recent 段追加本次改动摘要：

```markdown
## Recent
- **Bad Case 数据飞轮 (Q30)** — 新增 `flywheel` CLI（collect/generate/golden/check/status）
  - `app/eval/flywheel.py` 四阶段编排，复用 classify_failure / build_language_variants / CuratedEvalRunner
  - `cases/bad_cases/` 自动收集失败 case，`cases/golden.yaml` 回归 golden set
  - 半自动：收集/变体/回归自动化，修复与合入需人工确认
```

- [ ] **Step 4: Commit**

```bash
cd /Users/theyang/Documents/ai/retail-customer-support-agent
git add AGENTS.md HANDOFF.md
git commit -m "docs: 更新 AGENTS/HANDOFF — Bad Case 数据飞轮"
```

---

## 完成标准

- [ ] `uv run python -m pytest tests/ -v` 全绿
- [ ] `uv run flywheel --help` 显示 5 个子命令
- [ ] `uv run flywheel status` 正常输出
- [ ] `get_cases("golden")` 返回空列表（初始状态）
- [ ] spec 中四个阶段（collect/generate/promote/check）均有实现与测试覆盖
