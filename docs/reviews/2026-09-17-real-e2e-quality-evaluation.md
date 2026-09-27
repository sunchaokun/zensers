# 真实 E2E 报告质量评估

日期：2026-09-17  
运行 ID：`e2e_smartphone6_56e991bf`  
主题：中国新能源汽车市场（实际章节内容为中国智能手机行业相关分析）

## 1. E2E 执行结果

使用已有研究缓存和检查点，执行真实报告生成阶段，实际调用 LLM 完成：

- 检查点恢复
- 6 章节报告生成/修订
- 全局审查
- 问题验证
- 证据补充搜索
- 章节 `patch_data` / `rewrite`
- HTML 预览生成
- DOCX 文档生成

测试命令：

```text
python -m pytest -q tests/integration/test_real_report_generation_resume_e2e.py --disable-warnings --maxfail=1 -vv
```

结果：

- pytest：`1 passed`
- 总耗时：2196.29 秒（约 36 分 36 秒）
- 章节数：6
- 生成的报告缓存：`data/e2e_smartphone6_56e991bf/real_report_e2e/research_result_cache.json`
- HTML：`data/e2e_smartphone6_56e991bf/real_report_e2e/report_preview.html`
- DOCX：`data/e2e_smartphone6_56e991bf/real_report_e2e/final_report.docx`

## 2. 系统质量结果

虽然文档产物生成测试通过，但质量闸门没有通过：

| 指标 | 实际结果 | 判断 |
|---|---:|---|
| `formal_complete` | `false` | 不可正式交付 |
| `quality_gate_status` | `degraded` | 降级状态 |
| `quality_report.overall_score` | `0.0` | 未形成有效质量收敛结果 |
| `convergence_rounds` | `0` | 质量收敛循环未建立有效评分 |
| `defense_audit.formal_status` | `failed` | 防御审计失败 |
| 防御审计问题数 | 49 | 严重 |
| 来源数 | 30 | 有原始来源池 |
| 全局 claims 数 | 23 | 有一定结构化分析产物 |
| key findings 数 | 4 | 有摘要性结论 |

章节级检查显示，6 个章节均存在以下异常：

- `data_points_used = 0`
- `research_findings = 0`
- 正文长度约 1228–2100 字符
- 每章虽然有 3–5 个 `key_conclusions`，但结论没有对应的结构化证据链

49 个防御问题主要由以下类型组成：

- `unverified_evidence`：25 个
- `missing_source_url`：19 个
- `scope_collision`：4 个
- `unbound_numeric_claim`：1 个

## 3. 独立 LLM 质量评估

使用独立的资深行业研究总监评估 Prompt，对真实生成的 6 章节正文进行盲评，要求按证据锚定、因果解释、驱动排序、替代解释、结论校准和决策价值评分。

LLM 评估结果：

- 总分：`40/100`
- 水平：不及格，未达到中等行业分析师水平
- 证据锚定：约 `30`
- 因果解释：约 `45`
- 驱动排序：约 `40`
- 替代解释：约 `35`
- 结论校准：约 `25`
- 决策价值：约 `40`

LLM 识别出的主要问题：

1. 报告存在章节主题与内容错配，部分章节的标题、数据和论证对象不一致。
2. 关键数据缺乏可核查来源，很多数字无法从正文追溯到可靠证据。
3. 驱动因素主要是并列罗列，没有明确的主因排序和传导机制。
4. 替代解释、反面假设和证伪条件不足。
5. 预测和建议的前提条件、置信度、失效条件没有充分表达。
6. 不同章节存在口径混用和内容重复，影响专业可信度。

## 4. 最关键的系统缺陷

### P0：报告升级阶段丢失结构化证据

当前真实结果同时出现：

- 来源池有 30 条来源；
- 全局 claims 有 23 条；
- 但 6 个最终章节的 `data_points_used` 和 `research_findings` 全部为 0。

这说明研究数据并非完全没有搜集，而是在“分析结果 → 报告章节”的交接过程中没有进入章节对象。后续 L3 防御审计只能看到正文中的数字，无法关联到结构化证据，因此批量产生 `missing_source_url` 和 `unverified_evidence`。

这是当前最优先修复点，优先级高于继续增加 Prompt 长度或增加新的分析框架。

### P0：章节主题/数据对象出现错配

运行主题记录为“中国新能源汽车市场”，但章节标题和内容出现中国智能手机行业相关对象。即使单次测试断言只检查“6 章存在”，这种对象漂移也足以使报告失去研究价值。

应在报告生成前增加主题实体一致性硬门：章节主题、证据对象、数据指标和正文实体必须属于同一研究对象，否则禁止进入正式报告。

### P1：质量收敛循环没有形成有效收敛

最终 `quality_report.overall_score = 0` 且 `convergence_rounds = 0`，但报告经历了大量 LLM 修订。这说明“进行了修订”不等于“完成了质量收敛”，当前循环缺少可观测的前后评分、问题关闭率和证据绑定改善率。

### P1：当前修订循环过于昂贵

一次真实报告 E2E 约 36 分钟，且大量时间消耗在章节逐条修订。应优先修复数据交接和主题错配，否则后续重复运行只会高成本地修订同一类系统性缺陷。

## 5. 下一步修复顺序

1. 在章节生成前后增加结构化契约断言：每个章节必须携带 `data_points_used`、`research_findings` 和证据 ID 集合。
2. 对 `aggregated_result → ChapterWriteInput → ChapterWriteOutput → final report` 做逐节点快照审计。
3. 增加主题实体一致性检查，阻止新能源汽车任务生成手机行业章节。
4. 将 `missing_source_url`、`unverified_evidence` 和 `unbound_numeric_claim` 按证据 ID 聚合，避免对同一根因重复修订。
5. 将质量收敛指标改为可观测指标：章节平均分、证据绑定率、问题关闭率、主题一致性和未验证数字数。
6. 修复后重新执行本 E2E，并用本报告的 40 分结果作为当前基线；只有达到至少 70 分且 `formal_complete=true`，才进入更高级的行业分析师水平升级。

## 结论

本次真实 E2E 证明：系统已经具备完整执行和文档产出能力，但当前报告质量仍明显低于中等水平。核心瓶颈是结构化研究证据没有进入最终章节，以及主题对象发生漂移；继续优化 Prompt 的收益会低于先修复这两个数据链路问题。
