# P0 Prompt Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove two P0 hard constraints (output_spec five-segment mandatory structure; chapter_write rewrite ban) to raise contract score from 62.5 to 87.5 while preserving quality and generalization.

**Architecture:** Make two prompt/template files more flexible, add a lightweight contract test to lock the fix, then validate with unit tests and two real-sample replays (smartphone + pork).

**Tech Stack:** Markdown prompts, Jinja-like template, Python tests, existing replay script.

---

### Task 1: Add prompt contract tests

**Files:**
- Create: `tests/prompts/test_p0_prompt_constraints.py`
- Modify: none

- [ ] **Step 1: Create test file to assert P0 constraints**

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def test_output_spec_does_not_enforce_five_segment():
    text = read_text(ROOT / "prompts" / "_shared" / "output_spec.md")
    assert not re.search(r"Every analysis section MUST follow this structure", text, re.I)

def test_output_spec_keeps_data_consistency_hard_constraint():
    text = read_text(ROOT / "prompts" / "_shared" / "output_spec.md")
    assert re.search(r"Data Consistency \(HARD CONSTRAINT\)", text, re.I)

def test_chapter_write_allows_rewrite():
    text = read_text(ROOT / "src" / "agents" / "fixed_agents" / "report_upgrade" / "prompts" / "chapter_write.tmpl")
    assert "禁止从头重写" not in text
    assert "精修≠重写" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/prompts/test_p0_prompt_constraints.py -v`
Expected: FAIL due to currently present phrases.

- [ ] **Step 3: Commit test skeleton**

```bash
git add tests/prompts/test_p0_prompt_constraints.py
git commit -m "test: add p0 prompt constraint tests"
```

### Task 2: Fix output_spec (remove five-segment mandatory structure)

**Files:**
- Modify: `prompts/_shared/output_spec.md`

- [ ] **Step 1: Replace mandatory structure section with flexible analysis requirement**

Replace section `## Mandatory Structural Requirements ... 5. **Implication** ...` with:

```markdown
## Analysis Structure (Flexible)

- Structure your analysis to best test the claims and hypotheses.
- Every major conclusion must include supporting evidence and counter-evidence/boundary conditions.
- You may use different section layouts depending on the problem; do not force a fixed template.
```

Keep all other constraints unchanged (content requirements, data consistency, prohibited content).

- [ ] **Step 2: Run contract test**

Run: `pytest tests/prompts/test_p0_prompt_constraints.py -v`
Expected: PASS for output_spec checks.

- [ ] **Step 3: Commit**

```bash
git add prompts/_shared/output_spec.md
git commit -m "fix: relax output_spec mandatory five-segment structure"
```

### Task 3: Fix chapter_write (allow rewrite when evidence changes)

**Files:**
- Modify: `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`

- [ ] **Step 1: Remove rewrite ban and allow evidence-driven rewrite**

In section `### 精修操作规程（严格遵循）`, replace line "3. **精修≠重写** — 你是在初稿基础上做增量提升，不是另起炉灶" with:

```markdown
3. **允许重写** — 当证据变化或原结论不再成立时，可以重写相关段落或章节；必须记录变更原因与依据，保留数据来源可溯源。
```

In section `### 绝对禁止`, remove these two items:

- "1. **禁止删除初稿中有价值的内容** — 初稿是专业成果，你只能增补和优化，不能删减核心论点"
- "2. **禁止从头重写** — 必须基于初稿进行精修，不得抛弃初稿另起炉灶"

Keep红线: 禁止编造数据，禁止模糊来源，禁止无据断言。

- [ ] **Step 2: Run contract test**

Run: `pytest tests/prompts/test_p0_prompt_constraints.py -v`
Expected: PASS for chapter_write checks.

- [ ] **Step 3: Commit**

```bash
git add src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl
git commit -m "fix: allow rewrite in chapter_write when evidence changes"
```

### Task 4: Run unit and contract tests

**Files:** none

- [ ] **Step 1: Run all related tests**

Run: `pytest tests/unit/skills/test_data_analysis_extraction.py tests/prompts/test_p0_prompt_constraints.py -v`
Expected: ALL PASS

- [ ] **Step 2: Commit (if needed)**

No commit unless you changed files to fix failing tests.

### Task 5: Validate with smartphone sample replay

**Files:**
- Outputs: `research_analysis_prompt_opt/results/round8_*`

- [ ] **Step 1: Run replay**

Run: `venv\Scripts\python.exe research_analysis_prompt_opt/scripts/run_round.py --round 8`

- [ ] **Step 2: Check results**

Open `research_analysis_prompt_opt/results/round8_baseline.json` and confirm:
- `prompt_audit.p0_fail` == 1
- `contract_score` == 87.5

- [ ] **Step 3: Log results to progress**

Append Round 8 row to `research_analysis_prompt_opt/progress.md` test table.

### Task 6: Validate with pork sample replay

**Files:**
- Outputs: `research_analysis_prompt_opt/results/roundpork2_*`

- [ ] **Step 1: Run replay**

Run: `venv\Scripts\python.exe research_analysis_prompt_opt/scripts/run_round.py --round pork2 --cache data/ses_bd18d4b7/research_result_cache.json`

- [ ] **Step 2: Check results**

Open `research_analysis_prompt_opt/results/roundpork2_baseline.json` and confirm:
- `prompt_audit.p0_fail` == 1
- `contract_score` == 87.5

- [ ] **Step 3: Compare with previous pork run**

Ensure no major regression (e.g., Agent score drop >5 vs Round pork1).

- [ ] **Step 4: Log results to progress**

Append Round pork2 row to `research_analysis_prompt_opt/progress.md` test table.

### Task 7: Update documentation

**Files:**
- Modify: `research_analysis_prompt_opt/progress.md`
- Modify: `research_analysis_prompt_opt/task_plan.md`

- [ ] **Step 1: Add Phase 11 entry and test records**

Add a new Phase for P0 fixes and record Round 8 and Round pork2 results.

- [ ] **Step 2: Commit**

```bash
git add research_analysis_prompt_opt/progress.md research_analysis_prompt_opt/task_plan.md
git commit -m "docs: record p0 fix results for smartphone and pork samples"
```

### Task 8: Final sanity check

**Files:** none

- [ ] **Step 1: Run all tests once more**

Run: `pytest tests/unit/skills/test_data_analysis_extraction.py tests/prompts/test_p0_prompt_constraints.py -q`
Expected: ALL PASS
