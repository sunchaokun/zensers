# 报告深度优化执行计划 v2

## 核心思路

**不改架构，用 prompt 引导 LLM 像资深分析师一样思考。**

资深分析师的工作方式：
1. 通读全部数据 → 判断模型合理性
2. 评估各章数据充足性 → 确定写作优先级
3. 先写数据充足章节（基础层）→ 再写分析章节（分析层）→ 最后综合（综合层）
4. 数据不足时统一补充
5. 所有内容打磨完成后 → L1-L5 终审

当前系统已有 `read_json` 工具让 LLM 读取全量数据，只需在 prompt 中引导它按此顺序思考。

## 当前状态

| 指标 | 值 |
|---|---|
| 质量分 | **81.5** (rubric_v2) |
| 契约分 | **100.0** |
| P0 fail | **0/6** |
| 最佳历史 | 83.8 (Round 2b) → **81.5 (R15, 当前锁定)** |

## 优化总结

### 成功的优化（R13-R15）
| Round | 改动 | 效果 | 关键发现 |
|---|---|---|---|
| R13 | 规划阶段+框架评估输出 | +5.2 (75.0→80.2) | LLM成功检测框架不匹配 |
| R15 | 前瞻性分析要求 | +1.3 (80.2→81.5) | 适度分析要求有效提升质量 |

### 失败的优化（R14, R16-R19）
| Round | 改动 | 效果 | 失败原因 |
|---|---|---|---|
| R14 | 分析深度要求 | -9.2 (80.2→71.0) | 过度约束导致LLM输出退化 |
| R16 | chapter_review分析深度维度 | -7.5 (81.5→74.0) | 审查维度增加导致退化 |
| R17 | global_review深度+截断修复 | -7.0 (81.5→74.5) | 全局审查增强导致退化 |
| R18 | exec_summary综合质量 | -6.0 (81.5→75.5) | 摘要增强导致退化 |
| R19 | 修改现有结构要求 | -24.0 (81.5→57.5) | 结构要求修改导致严重退化 |

### 关键经验
1. **适度的prompt引导有效**：R13（规划阶段）和R15（前瞻性分析）通过适度引导LLM思考流程提升了质量
2. **过度约束导致退化**：R14（分析深度要求）、R16（审查维度）、R17（全局审查）、R18（摘要增强）都因为过度约束导致LLM输出质量下降
3. **审查维度增加适得其反**：在review阶段增加分析深度维度反而降低了报告质量
4. **截断放宽无显著效果**：global_reviewer的截断从400→1200没有带来质量提升
5. **修改现有要求也可能退化**：R19尝试修改现有结构要求使其更具体，但导致严重退化（-24.0），说明现有要求已经是LLM理解的最佳状态

### 当前锁定状态
- **R13锁定**：规划阶段+框架评估输出（80.2/100）
- **R15锁定**：前瞻性分析要求（81.5/100）
- **R14/R16/R17/R18已revert**：保持R15锁定分81.5/100

## 评分维度 vs 当前覆盖

| 维度 | 权重 | 当前状态 | 本轮目标 |
|---|---|---|---|
| 证据锚定 | 25% | ✅ 已充分 | 维持 |
| 逻辑完整性 | 20% | ⚠️ 部分覆盖 | 微调 |
| 数据使用 | 20% | ✅ 已充分 | 维持 |
| **洞察深度** | **15%** | ❌ **空白** | **R13重点** |
| 结构合规 | 10% | ✅ 已充分 | 维持 |
| **前瞻价值** | **10%** | ❌ **空白** | **R14重点** |

---

## 执行计划（逐项评估，找到局部最优）

### R13: 报告规划阶段 + 框架评估输出 ✅ COMPLETED

**结果**: 80.2/100 (+5.2), contract 100.0, P0 fail 0/6
**改动**: 
- chapter_write.tmpl: 添加5步规划指令（通读数据→模型合理性判断→数据充足性评估→撰写优先级排序→本章定位）
- chapter_write.tmpl: 添加 planning_assessment JSON输出字段
- models.py: ChapterWriteOutput 新增 planning_assessment 字段
- chapter_writer.py: _parse_output 提取 planning_assessment
- orchestrator.py: 添加 planning_assessment 日志（含 severity 警告）
**关键发现**: LLM 成功检测到 section_3 (供应链与补链影响) 的 critical 框架不匹配（研究数据是智能手机市场，但章节要求供应链分析）
**经验**: 规划阶段指令有效提升报告质量，planning_assessment 为后续流程提供决策信号

---

### R14: 分析深度要求（因果链+定量推理+多因素交互）

**目标**: 在 chapter_write.tmpl 中添加前瞻性分析规范

**修改文件**: `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`

**修改位置**: 紧接 R13 分析深度要求之后

**新增内容**:
```markdown
## 前瞻性分析（每章至少1段）

### 必须包含
- 基于当前数据趋势，给出未来12-24个月的合理预期
- 明确标注假设前提和边界条件
- 提供至少一个可量化的预测或场景

### 决策导向
- 回答"So what"：这个趋势对利益相关方意味着什么
- 回答"Now what"：应该采取什么行动
```

**验证**: 运行 `run_report_round.py --round 14`
**通过标准**: 质量 ≥ R13锁定分
**回退条件**: 质量 < R13锁定分 - 3.0

---

### R15: 前瞻性分析 ✅ COMPLETED

**结果**: 81.5/100 (+1.3), contract 100.0, P0 fail 0/6
**改动**: 
- chapter_write.tmpl: 添加前瞻性分析要求（每章至少1段，12-24个月预测+决策导向）
**关键发现**: 前瞻性分析要求有效提升报告的前瞻价值维度
**经验**: 适度的分析要求（如前瞻性分析）可以提升质量，但过度约束（如R14的分析深度要求）会导致退化

---

### R16: chapter_review 添加分析深度审查维度（HIGH）

**目标**: 在 chapter_review.tmpl 中添加分析深度维度（15%权重），让质量审查能检测浅层分析

**修改文件**: `src/agents/fixed_agents/report_upgrade/prompts/chapter_review.tmpl`

**修改内容**:
1. 在现有8个维度后新增第9维度"分析深度"（权重15%）
2. 调整其他维度权重归一化
3. 新增反模式检测规则

**权重调整**:
- 数据锚定: 30% → 23%
- 认知标签: 15% → 14%
- 数据支撑: 15% → 14%
- 逻辑清晰: 12% → 9%
- 结构合规: 8% → 7%
- 内容完整: 10% → 9%
- 校准替代: 5% → 5%
- 决策相关: 5% → 5%
- **分析深度: 0% → 15%**

**验证**: 运行 `run_report_round.py --round 16`
**通过标准**: 质量 ≥ R15锁定分
**回退条件**: 质量 < R15锁定分 - 3.0

---

### R17: global_review 分析深度维度 + 截断放宽（HIGH）

**目标**: 全局审查能检测跨章节分析深度问题

**修改文件**:
1. `src/agents/fixed_agents/report_upgrade/prompts/global_review.tmpl` — 新增分析深度维度
2. `src/agents/fixed_agents/report_upgrade/global_reviewer.py` — 截断长度 400→1200

**修改内容**:
- global_review.tmpl: 新增第8维度"分析深度"（HIGH级别）
- global_reviewer.py L144-145: `content[:400]` → `content[:1200]`

**验证**: 运行 `run_report_round.py --round 17`
**通过标准**: 质量 ≥ R15锁定分
**回退条件**: 质量 < R15锁定分 - 3.0

---

### R18: exec_summary 综合质量增强（MEDIUM）

**目标**: 摘要更像人类专家的综合判断，而非简单拼接

**修改文件**: `src/agents/fixed_agents/report_upgrade/prompts/exec_summary.tmpl`

**修改内容**: 在摘要结构中新增交叉主题识别、矛盾处理、行动建议、前瞻展望

**验证**: 运行 `run_report_round.py --round 17`
**通过标准**: 质量 ≥ R16锁定分
**回退条件**: 质量 < R16锁定分 - 3.0

---

## 依赖关系

```
R13 (规划+depth) → R15 (forward) → R17 (global:depth) → R18 (summary)
```

每个 Round 独立评估，找到局部最优后锁定再进入下一个。

## 验证工具

```bash
# 运行回放（自动评分）
python research_report_prompt_opt/scripts/run_report_round.py --round <N> --prompt-note "描述"

# 仅审计（不调用LLM）
python research_report_prompt_opt/scripts/run_report_round.py --round <N> --skip-llm

# 对比结果
python -c "import json; r=json.load(open('research_report_prompt_opt/results/round<N>.json')); print(f'Quality: {r[\"quality_score\"]}, Contract: {r[\"contract_score\"]}')"
```
