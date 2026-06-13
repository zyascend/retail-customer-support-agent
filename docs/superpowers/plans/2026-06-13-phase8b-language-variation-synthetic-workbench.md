# Phase 8b Language Variation 与 Synthetic Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 8a generated scenarios 上增加可复现 L1/L2 language variation gate、L3 exploratory cases，并让 Workbench 能展示和 replay generated scenario。

**Architecture:** 新增 `app/synthetic/language_variation.py` 负责 deterministic message rewrite；扩展 `EvalCase` metadata、family case builder、runner/report aggregation 和 Workbench catalog/session runtime。L1/L2 进入 `generalization` gate，L3 进入 `generalization_exploratory` 非阻塞集合。

**Tech Stack:** Python 3.12, dataclasses, pytest/unittest, FastAPI TestClient, React/TypeScript for metadata consumption.

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `app/synthetic/language_variation.py` | 新建 | Deterministic L1/L2/L3 language variant generation |
| `app/synthetic/families.py` | 修改 | 为每个 family variant 生成 base/L1/L2 gate cases 和 L3 exploratory cases |
| `app/eval/cases.py` | 修改 | `EvalCase` 增加 scenario/language metadata，`get_cases()` 支持 exploratory subset |
| `app/eval/runner.py` | 修改 | result 写入 metadata，synthetic runtime 支持 generated subsets |
| `app/eval/metrics.py` | 修改 | failure analysis 增加 language level 聚合 |
| `app/workbench/cases.py` | 修改 | catalog 暴露 generated scenario metadata |
| `app/workbench/session.py` | 修改 | selected generated case 使用自身 seed 创建 synthetic runtime |
| `workbench/src/types.ts` | 修改 | WorkbenchCase 增加 generated metadata 类型 |
| `tests/test_generalization.py` | 修改 | language variation 和 case builder 测试 |
| `tests/test_workbench_api.py` | 修改 | config 返回 generated metadata 测试 |
| `tests/test_workbench_session.py` | 修改 | generated case replay 使用 synthetic seed 测试 |

## Task 1: Language Variation 模块

**Files:**
- Create: `app/synthetic/language_variation.py`
- Modify: `tests/test_generalization.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `build_language_variants()` and assert:

```python
def test_language_variants_include_reproducible_base_l1_l2_and_l3():
    from app.synthetic.language_variation import build_language_variants
    from app.synthetic.oracle import select_entity_for_variant

    world = SyntheticDBGenerator.from_seed(100)
    entities = select_entity_for_variant(world, "cancel_success")
    base_messages = [
        {
            "role": "user",
            "content": (
                f"My email is {entities['user']['email']}. Cancel order "
                f"{entities['order']['order_id']} because no longer needed."
            ),
        },
        {"role": "user", "content": "yes"},
    ]

    first = build_language_variants(base_messages, "cancel_success", entities)
    second = build_language_variants(base_messages, "cancel_success", entities)

    assert first == second
    assert [variant.level for variant in first] == ["base", "L1", "L2", "L3"]
    assert first[0].gate is True
    assert first[1].gate is True
    assert first[2].gate is True
    assert first[3].gate is False
    assert "Cancel order" not in first[1].messages[0]["content"]
    assert entities["user"]["email"] in first[2].messages[0]["content"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m pytest tests/test_generalization.py::test_language_variants_include_reproducible_base_l1_l2_and_l3 -v
```

Expected: FAIL because `app.synthetic.language_variation` does not exist.

- [ ] **Step 3: Implement minimal module**

Create `app/synthetic/language_variation.py` with a frozen `LanguageVariant` dataclass and deterministic rewrite helpers. Keep rules explicit per variant family; unknown variants return base plus generic copies with stable suffixes.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_generalization.py::test_language_variants_include_reproducible_base_l1_l2_and_l3 -v
```

Expected: PASS.

## Task 2: EvalCase Metadata And Builders

**Files:**
- Modify: `app/eval/cases.py`
- Modify: `app/synthetic/families.py`
- Modify: `tests/test_generalization.py`

- [ ] **Step 1: Write failing builder tests**

Add tests that assert:

```python
def test_generalization_cases_include_base_l1_l2_gate_variants():
    from app.eval.cases import get_cases

    cases = get_cases("generalization")
    levels = {case.language_variation_level for case in cases}

    assert len(cases) == 45
    assert levels == {"base", "L1", "L2"}
    assert all(case.scenario_family for case in cases)
    assert all(case.variant_type for case in cases)
    assert all(case.seed is not None for case in cases)


def test_l3_variants_are_exploratory_only():
    from app.eval.cases import get_cases

    gate_ids = {case.case_id for case in get_cases("generalization")}
    exploratory = get_cases("generalization_exploratory")

    assert exploratory
    assert {case.language_variation_level for case in exploratory} == {"L3"}
    assert all(case.subset == "generalization_exploratory" for case in exploratory)
    assert not gate_ids.intersection({case.case_id for case in exploratory})
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m pytest tests/test_generalization.py::test_generalization_cases_include_base_l1_l2_gate_variants tests/test_generalization.py::test_l3_variants_are_exploratory_only -v
```

Expected: FAIL because `EvalCase` lacks language metadata and builders still return 15 cases.

- [ ] **Step 3: Implement metadata and builders**

Add fields to `EvalCase`, preserve them in `_case_for_subset()`, update `FamilyVariant.to_eval_case()` to accept a `LanguageVariant`, and add `build_generalization_exploratory_cases()`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_generalization.py -v
```

Expected: PASS.

## Task 3: Runner And Report Language Aggregation

**Files:**
- Modify: `app/eval/runner.py`
- Modify: `app/eval/metrics.py`
- Modify: `tests/test_eval_runner.py` or `tests/test_generalization.py`

- [ ] **Step 1: Write failing metadata/report tests**

Add a focused test that runs or constructs results and asserts `language_variation_level` appears on results and in failure analysis aggregation.

- [ ] **Step 2: Verify RED**

Run the focused test. Expected: FAIL because result metadata or aggregation is missing.

- [ ] **Step 3: Implement runner/report metadata**

Add `language_variation_level` to `EvalCaseResult`, populate `scenario_family`, `variant_type`, `seed`, and `language_variation_level` from `EvalCase`, and add `by_language_variation_level` to `build_failure_analysis()`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_generalization.py tests/test_eval_runner.py -v
```

Expected: PASS.

## Task 4: Workbench Generated Scenario Catalog

**Files:**
- Modify: `app/workbench/cases.py`
- Modify: `app/workbench/session.py`
- Modify: `tests/test_workbench_api.py`
- Modify: `tests/test_workbench_session.py`

- [ ] **Step 1: Write failing Workbench tests**

Add API/session tests that assert:

```python
def test_config_includes_generated_scenario_metadata(self):
    ...
    generated = [
        case for case in payload["case_catalog"]["all_cases"]
        if case["subset"] == "generalization"
    ]
    self.assertTrue(generated)
    self.assertIn("seed", generated[0])
    self.assertIn("language_variation_level", generated[0])
    self.assertIn("expected_oracle", generated[0])
```

and:

```python
def test_generated_generalization_case_replays_with_seeded_runtime(self):
    ...
    session = manager.create_session(
        mode="deterministic",
        case_id="cancel_success_s100_l1",
    )
    snapshot = session.run_all()
    self.assertEqual(snapshot["selected_case_id"], "cancel_success_s100_l1")
    self.assertEqual(snapshot["business"]["confirmation_status"], "confirmed")
    self.assertTrue(Path(snapshot["trace_artifact_path"]).exists())
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run python -m pytest tests/test_workbench_api.py::WorkbenchAPITests::test_config_includes_generated_scenario_metadata tests/test_workbench_session.py::WorkbenchSessionTests::test_generated_generalization_case_replays_with_seeded_runtime -v
```

Expected: FAIL because catalog/session do not support generated case metadata/runtime.

- [ ] **Step 3: Implement Workbench support**

Include `generalization` cases in catalog, add a generated group, serialize seed/family/variant/language/oracle metadata, update `get_case_by_id()` fallback subsets, and use `SyntheticRetailAdapter(seed=selected_case.seed or 42)` for generated subsets.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run python -m pytest tests/test_workbench_api.py tests/test_workbench_session.py -v
```

Expected: PASS.

## Task 5: Frontend Types And Final Verification

**Files:**
- Modify: `workbench/src/types.ts`
- Optional Modify: `workbench/src/components/RunControl.tsx` if generated metadata needs visible grouping labels.

- [ ] **Step 1: Update TypeScript metadata types**

Add optional fields to `WorkbenchCase`: `subset`, `capability`, `policy_area`, `seed`, `scenario_family`, `variant_type`, `language_variation_level`, `expected_oracle`.

- [ ] **Step 2: Run backend verification**

Run:

```bash
uv run python -m pytest tests/ -v
uv run ruff check .
```

Expected: all tests pass and ruff reports no issues.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd workbench && npm run build
```

Expected: TypeScript build succeeds.

- [ ] **Step 4: Run generalization gate smoke**

Run:

```bash
uv run phase2-eval --subset generalization --trials 1
```

Expected: command completes and writes eval/report artifacts. Passing all cases is the target; any failure must be investigated with systematic debugging before code changes.

## Self-Review

- Spec coverage: L1/L2 gate, L3 exploratory, metadata/reporting, Workbench display/replay are covered by Tasks 1-5.
- Placeholder scan: no `TBD` or unspecified code paths remain; each task names exact files and verification commands.
- Type consistency: metadata names are consistent across `EvalCase`, `EvalCaseResult`, Workbench JSON, and TypeScript.
