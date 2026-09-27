# Prompt 与 Skill 对报告研究深度影响的系统审查报告

**审查日期：** 2026-09-16  
**审查范围：** \`prompts/\`、\`src/skills/\`、\`src/core/quality/\`、\`src/agents/fixed_agents/report_upgrade/\`  
**审查目的：** 判断现有 Prompt、Skill、阶段衔接和质量反馈机制，是否存在导致报告研究深度不足的设计缺陷，并确定达到“中等以上、高级分析师方向”的优先优化路径。

## 一、执行结论

当前系统并不是缺少研究阶段、数据补充能力或报告生成能力。系统已经具备数据采集、验证、深度分析、综合、报告生成、数据防御和 L1-L5 微循环等完整能力。

本次审查发现，报告深度不足主要来自四类问题：

1. **Prompt 把模型约束成“格式合规的报告撰写者”，而不是有取舍的高级分析师。**
2. **深度研究要求停留在分析维度清单，没有转化为可执行的研究动作。**
3. **部分 Skill 的实际证据输入不完整，导致数据分析退化为标题和常识推理。**
4. **质量反馈主要检查完整性、结构和表面可信度，尚未稳定识别主因判断、替代解释和结论强度。**

因此，首要任务不是再增加研究 Agent，也不是立即建立复杂的外部 benchmark，而是重新定义一套“高级分析师行为契约”，并检查该契约是否贯穿每个阶段、每个 Skill 和每一轮反馈。

## 二、审查判断框架

本次审查没有把优秀行业报告作为简单分数基准，而是从高级分析师的工作行为反推系统要求：

| 检查维度 | 高级分析师应完成的动作 | 当前系统的主要状态 |
|---|---|---|
| 研究问题 | 明确最重要的问题和判断对象 | 有章节主题，但主问题不总是被显式锁定 |
| 假设与因果 | 提出竞争性假设，识别主因、次因和表象 | 有驱动因素/因果链要求，但缺少验证和排序协议 |
| 证据 | 证据带数值、口径、时间、来源和适用范围 | 注册和证据池能力存在，但部分 Skill 只接收标题或文本 |
| 分析方法 | 根据问题选择少量有解释力的方法 | 部分 Skill 默认堆叠多个框架和指标 |
| 结论强度 | 区分事实、推断、预测和待验证判断 | 有 confidence 字段，但缺少稳定证据绑定 |
| 决策价值 | 给出有优先级、边界和前提的行动含义 | 有 implication/recommendation 要求，但常被模板化 |

## 三、核心问题与证据

### P0-1：全局输出规范挤压了真正的分析空间

文件：[prompts/_shared/output_spec.md](../../prompts/_shared/output_spec.md)

当前输出规范要求大量章节采用固定的五段式结构：核心判断、逻辑推导、数据支持、反证/边界、含义，并要求每段以判断开头、使用 HTML 表格、遵守统一的内容组织方式。

这些约束有助于防止空泛描述，但作为全局规则会产生反作用：

- 每个段落都必须“产出判断”，导致事实陈述被人为改写成判断；
- 反证和边界可能变成固定句式，而不是对结论有实质影响的证据；
- 所有章节被迫使用同一种推理结构，市场规模、政策、技术、风险和估值失去方法差异；
- 模型把主要精力放在满足格式，而不是判断哪些因素最重要；
- 报告变得结构完整，但主线和重点不突出。

高级分析师不会要求每一段都完整展示同样的五个步骤，而是根据问题决定推理结构。当前规则应从“段落级硬约束”调整为“研究结论级检查项”。

### P0-2：报告阶段的“精修”定位抑制了重新分析

文件：[src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl](../../src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl)

章节写作 Prompt 强调“精修不是重写”、保留核心论点和既有内容。这适合保护已有成果，但不适合作为高级分析阶段的主要行为约束。

如果初步分析已经存在以下问题：

- 研究问题本身选错；
- 结论由弱证据支撑；
- 主因与次因没有区分；
- 章节之间存在重复或矛盾；
- 新证据已经改变原判断；

那么报告阶段必须允许模型重排论证、合并内容、降低结论强度，甚至推翻原始结论。否则后续的数据补充和 L1-L5 反馈只能修补表达，不能完成研究重构。

应将“保留原结论”改为“保留已被证据支持的结论；若证据发生变化，必须说明并更新结论”。

### P0-3：深度分析要求是清单，不是研究协议

文件：[prompts/tasks/deep_analysis.md](../../prompts/tasks/deep_analysis.md)、[prompts/phases/deep_analysis.md](../../prompts/phases/deep_analysis.md)

当前 Prompt 已包含框架选择、驱动因素、风险、前瞻性、量化判断和置信度等要求，但缺少高级分析师必须执行的顺序和决策规则：

1. 先确定本节唯一的核心问题；
2. 提出两个或多个相互竞争的解释；
3. 列出验证每个解释所需的证据；
4. 根据证据判断主因、次因和未知因素；
5. 进行反事实或情景比较；
6. 给出结论强度和失效条件；
7. 只把经过筛选的内容交给报告阶段。

目前更像是在要求模型“覆盖很多分析点”，而不是要求模型“完成一次可审计的研究判断”。这很容易产生框架齐全、逻辑顺滑、但没有真正洞察的内容。

### P0-4：部分 Skill 的证据没有真正进入 LLM 推理上下文

重点文件：

- [src/skills/analysis/risk_analysis.py](../../src/skills/analysis/risk_analysis.py)
- [src/skills/analysis/policy_analysis.py](../../src/skills/analysis/policy_analysis.py)
- [src/skills/analysis/tech_trend.py](../../src/skills/analysis/tech_trend.py)

这些 Skill 接收的数据点对象本身包含更丰富的信息，但在构建分析 Prompt 时主要使用标题等简化字段。来源、原文摘录、数值、时间、范围和证据 ID 没有稳定传入最终推理上下文，甚至存在参数接收后未充分使用的情况。

直接后果是：

- 风险分析容易变成行业常识罗列；
- 政策分析容易变成政策名称加影响判断；
- 技术趋势分析容易变成趋势描述加预测；
- 结论看似与数据相关，实际无法逐条回溯。

这属于“能力已实现但上下文装配失败”，优先级高于增加新的 Skill。

### P0-5：计算型 Skill 的文本正则提取会破坏数据可比性

重点文件：

- [src/skills/analysis/data_analysis.py](../../src/skills/analysis/data_analysis.py)
- [src/skills/analysis/market_analysis.py](../../src/skills/analysis/market_analysis.py)

当前实现通过正则从文本中提取数字，再计算趋势、CAGR、市场份额、CR3/CR5 和 HHI。主要风险是没有在计算前强制确认以下字段一致：

- metric；
- unit；
- period；
- geography；
- population/statistical object；
- source and evidence scope。

如果不同口径的数字被放入同一序列，模型最终可能得到“数学过程正确、研究含义错误”的结论。高级分析师水平的基础不是指标越多越好，而是知道哪些数字可以比较、哪些数字绝对不能放在一起比较。

### P1-1：数据验证没有形成硬性处置状态

文件：[prompts/phases/data_validation.md](../../prompts/phases/data_validation.md)

当前数据验证主要输出完整性、一致性、时效性、质量评分和改进建议，但没有统一的决策状态，例如：

- accepted：可直接支撑结论；
- conditional：只能在限定范围内使用；
- needs_research：必须补充证据；
- rejected：不得进入报告。

没有硬性状态，后续阶段仍可能把“有问题但有一定参考价值”的数据当作普通证据使用，最终形成过强结论。

### P1-2：中间结果缺少稳定的证据—结论关系

文件：[prompts/phases/deep_analysis.md](../../prompts/phases/deep_analysis.md)

当前输出虽然包含 insights、evidence、implication 和 confidence，但证据多以字符串表达，缺少稳定的：

- claim ID；
- hypothesis ID；
- evidence ID；
- derived metric ID；
- supports/refutes/qualifies 关系；
- unresolved gap；
- next research action。

因此 synthesis 和 report generation 更容易消费已经写好的文本，而不是重新消费结构化研究成果。文本接力会逐步丢失证据边界和推理前提。

### P1-3：共享 Prompt 之间存在目标冲突

典型冲突包括：

- [data_canonical.md](../../prompts/_shared/data_canonical.md)要求数据带来源和口径；
- [output_spec.md](../../prompts/_shared/output_spec.md)限制正文中的来源表达；
- [report_generation.md](../../prompts/phases/report_generation.md)要求来源标注和报告一致性；
- synthesis 类 Prompt 又倾向于基于章节内容生成，不直接处理原始证据。

当多个规则冲突时，模型通常优先满足最近、最具体或最容易检查的格式要求，导致来源、口径和结论强度被牺牲。

### P1-4：现有质量评分能发现“浅层完整”，不一定能发现“浅层正确性”

重点文件：

- [prompts/_shared/quality_rubric.md](../../prompts/_shared/quality_rubric.md)
- [src/core/quality/layer3_depth.py](../../src/core/quality/layer3_depth.py)
- [src/core/quality/semantic_scorer.py](../../src/core/quality/semantic_scorer.py)

系统已经存在深度评分，说明“缺少深度评估”不是准确判断。真正的问题是评分尚未充分回答：

- 本章是否识别了最主要的解释变量；
- 主要判断是否由最强证据支撑；
- 是否认真比较了替代解释；
- 反证是否真正改变了结论强度；
- 预测是否说明了前提和失效条件；
- 建议是否来自分析，而不是从结论段落顺手生成。

目前评分容易奖励“有框架、有数据、有反证、有建议”的表面完整性，而不是奖励“取舍准确、因果解释有力、结论克制且可行动”。

### P2-1：Skill 描述层和 Skill 执行层不一致

例如：

- [src/skills/data_analysis/SKILL.md](../../src/skills/data_analysis/SKILL.md)主要描述可计算 CAGR、CR3、HHI 和趋势；
- [src/skills/market_analysis/SKILL.md](../../src/skills/market_analysis/SKILL.md)主要描述市场规模、竞争格局和框架；
- [src/skills/registry.py](../../src/skills/registry.py)主要承担 Skill 路由和组合。

这些描述更接近“能力标签”或“功能目录”，不是可重复执行的研究方法。没有规定何时使用、何时拒绝使用、需要哪些输入、如何处理证据冲突、如何返回推理链和数据缺口。

因此系统可能“调用了正确名称的 Skill”，但没有获得资深分析师式的研究行为。

### P2-2：缺少浅层输出的反例和高级输出的正例

当前 Prompt 有大量规范性语言，但缺少成对示例：

- 什么是“数据罗列”；
- 什么是“真正的驱动因素解释”；
- 什么是“伪因果”；
- 什么是“无效反证”；
- 什么是“高级分析师的结论强度表达”。

对于复杂研究任务，抽象要求往往不足。少量高质量正例和典型反例，通常比继续增加规则更能稳定模型行为。

## 四、问题优先级

| 优先级 | 问题 | 影响 | 是否需要先改架构 |
|---|---|---|---|
| P0 | 格式约束压过分析判断 | 产生模板化、平均化报告 | 否 |
| P0 | 报告阶段不允许充分重构 | 新证据无法改变原判断 | 否 |
| P0 | 深度分析缺少假设验证和主因排序 | 有分析维度但无研究取舍 | 否 |
| P0 | Skill 传入 LLM 的证据不完整 | 数据分析退化为常识推理 | 否，先修上下文装配 |
| P0 | 计算前缺少口径一致性校验 | 产生不可比数据和伪量化 | 否，先修 Skill 契约 |
| P1 | 中间结果缺少 Claim/Evidence 关系 | 阶段交接时丢失研究链条 | 否 |
| P1 | 数据验证无 accepted/rejected 状态 | 不可靠数据可能继续流转 | 否 |
| P1 | 质量评分偏完整性 | 微循环可能越修越模板化 | 否 |
| P1 | 共享 Prompt 规则冲突 | 模型选择错误优化目标 | 否 |
| P2 | Skill 文档偏能力标签 | 方法执行不稳定 | 否 |
| P2 | 缺少正反例 | 高级行为难以稳定复现 | 否 |

## 五、建议形成的“高级分析师行为契约”

后续 Prompt 重构不应首先增加更多章节要求，而应统一要求每个重要研究单元产出以下内部对象：

~~~text
ResearchQuestion
  ├─ core_question
  ├─ decision_context
  ├─ competing_hypotheses
  ├─ prioritized_drivers
  ├─ evidence_map
  │    ├─ supports
  │    ├─ refutes
  │    └─ qualifies
  ├─ derived_metrics_and_formula
  ├─ alternative_explanations
  ├─ uncertainty_and_failure_conditions
  ├─ conclusion_strength
  └─ decision_implications
~~~

其中最重要的不是字段数量，而是要求模型完成以下动作：

1. 只选择对当前问题有解释力的方法；
2. 对驱动因素进行排序，而不是并列罗列；
3. 对关键假设寻找支持证据和反证；
4. 对每个关键结论标明证据边界；
5. 区分事实、推断、预测和建议；
6. 允许新证据推翻旧结论；
7. 将研究缺口转化为下一轮明确的数据任务。

## 六、推荐实施顺序

### 第一阶段：只修 Prompt 契约

重点修改：

- \`prompts/_shared/output_spec.md\`；
- \`prompts/tasks/deep_analysis.md\`；
- \`prompts/phases/deep_analysis.md\`；
- \`src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl\`。

目标是把“固定格式要求”降级为输出检查项，把“核心问题—假设—证据—取舍—结论强度”提升为主流程。

### 第二阶段：修 Skill 的输入输出契约

每个分析 Skill 至少应接收并使用完整证据对象：数值、单位、时间、地域、对象、口径、原文、来源、证据 ID 和可信度。

每个 Skill 至少应返回：计算过程、使用的数据 ID、适用条件、冲突数据、结论、结论强度和待补充证据。

### 第三阶段：修 L1-L5 微循环目标

将反馈类型明确区分为：

- rewrite：表达问题；
- reframe：研究问题或论证主线问题；
- research：证据不足；
- recalculate：计算或口径问题；
- downgrade_claim：结论强度过高；
- resolve_conflict：证据冲突。

这样微循环才不会把所有问题都归结为“补数据”或“改写文字”。

### 第四阶段：再建立轻量级内部基准

不需要一开始对标顶级券商或咨询报告，也不应立即用一个总分判断研究深度。建议选取固定主题，比较以下中间产物：

- 核心研究问题是否清晰；
- 驱动因素排序是否合理；
- 关键结论的证据绑定率；
- 替代解释覆盖情况；
- 不确定性和失效条件是否明确；
- 建议是否由分析结论推出。

这类基准用于判断系统是否从“资料汇编”提升到“中等分析”，之后再用于高级水平升级。

## 七、暂不建议的方向

现阶段不建议优先进行以下工作：

- 引入新的多 Agent 架构；
- 继续堆叠更多行业框架；
- 仅增加 Prompt 长度；
- 先建立复杂的总分 benchmark；
- 仅优化 HTML、表格和排版；
- 让报告阶段继续无条件保留所有初步结论。

这些工作不能直接解决当前的主要矛盾：模型没有持续执行高级分析师的取舍、证据辨别、因果排序和结论校准。

## 八、最终判断

我们的系统具备达到中等以上研究报告水平的基础，当前短板不是“不会搜集数据”或“不会写报告”，而是：

> 研究能力没有被统一编码成稳定、可传递、可审查的高级分析师行为。

本轮已完成 P0 主链路和大部分 P1 修复：Prompt 契约已从固定模板转向研究协议，Skill 已接收完整证据上下文并限制不可比计算，验证结果已引入处置状态，分析阶段已输出可供报告升级使用的结构化研究发现，L3 深度评分已接入研究上下文。仍需后续专项推进的事项是：将 L2 方法论评分从关键词覆盖进一步升级为“方法是否改变了结论”的判断；为深度门槛增加确定性硬门；补充端到端样例和质量回归集。完成这些后，再用优秀行业报告做中等水平基准校准，避免过早追求高级水平。
