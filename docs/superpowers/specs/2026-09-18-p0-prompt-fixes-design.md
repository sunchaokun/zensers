# 2026-09-18-p0-prompt-fixes-design.md

## Context
当前数据分析链路有两个 P0 契约问题导致 prompt 契约分受限（当前 62.5，P0 fail 2）：
- `prompts/_shared/output_spec.md` 强制每段采用固定五段结构，限制分析灵活性。
- `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl` 禁止重写，导致证据变化后仍保留弱结论。

目标：修复这两个 P0，提高契约分至 87.5（P0 fail 1），同时保持系统通用性，不引入行业专用逻辑。

## 设计原则
- 通用性优先：不针对猪肉/手机等行业加专用规则。
- 证据驱动：分析结构服从假设验证，而非模板填充。
- 红线保留：禁止编造数据、模糊来源、不可溯源 URL。
- 可验证：通过契约审计与真实样本回放验证改善与回归。

## 修订方案

### 1) `prompts/_shared/output_spec.md`
- 删除 "Mandatory Structural Requirements" 中的 5 段强制结构。
- 保留并强化：
  - 数据一致性硬约束（HARD CONSTRAINT）。
  - 每个主要结论需包含 counter-evidence / boundary conditions。
  - 专业表达与可溯源数据引用。
- 改为“分析结构应服务于论点验证”，允许多种结构，但必须有证据与反证。

### 2) `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`
- 删除：
  - “精修≠重写”
  - “禁止从头重写”
  - “禁止删除初稿中有价值的内容”
- 改为：
  - 当证据变化或原结论不再成立时，允许重写，并明确记录变更原因与依据。
  - 保留“禁止编造数据/模糊来源”红线。
  - 保留章节结构规范但不强制五段式；允许“反证与边界条件”作为分析必要组成。

## 验证计划
- 运行 `tests/unit/skills/test_data_analysis_extraction.py`（无回归）。
- 运行 `research_analysis_prompt_opt/scripts/run_round.py --round 8`（智能手机样本）。
- 运行 `--round pork2 --cache data/ses_bd18d4b7/research_result_cache.json`（猪肉样本）。
- 预期：
  - `prompt_audit.p0_fail` 从 2 降到 1。
  - `contract_score` 从 62.5 提升到 87.5。
  - 两个样本不出现明显分数回归（例如 Agent 下降 >5 分视为回归）。

## 风险与回滚
- 风险：放宽结构后，部分产出可能变得松散。
  - 缓解：保留“每个主要结论必须含反证/边界条件”约束。
- 风险：允许重写可能引发过度改写。
  - 缓解：要求输出变更原因，并在自审中检查“是否保留核心证据链”。
- 回滚：若出现明显回归，回滚对应文件改动，并在 progress 中记录。
