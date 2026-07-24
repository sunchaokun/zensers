# 取证分析模式（Forensic Analysis Mode）设计方案

> 日期：2026-07-02
> 状态：方案设计
> 前置：基于代码深度审查，所有引用标注文件路径与行号

---

## 1. 问题定义

### 1.1 场景

用户上传一份年报PDF，提出一个**开放性取证问题**：

> "为什么企业现金流大幅增长了，利润却没有增长？"

数据已在文档中，不需要"搜集"，需要的是**从已有数据中精准提取、因果归因、回答问题**。

### 1.2 现有系统的两种工作模式

| 模式 | 输入特征 | 典型场景 | 数据来源 |
|------|---------|---------|---------|
| **全景研究模式** | 指令型（"分析XX年报"） | 生成完整分析报告 | 需要搜集+已有文档 |
| **取证分析模式** | 问题型（"为什么现金流增长利润没增长？"） | 回答特定问题 | 已在文档中 |

### 1.3 当前系统的处理路径与问题

用户输入 "为什么现金流增长利润没增长" + 已上传年报，当前流程：

1. **API层**（`research_api.py:379-382`）：`question_suffixes` 检测到 `？` → `is_depth_command = False` → 问题型输入被阻止进入研究快捷通道，留在chat模式
2. **意图分析**（`semantic_intent.py:352-432`）：LLM可能将其分类为 `OPEN_ENDED` 或 `RESEARCH`，但 `IntentType` 枚举（`intent_types.py:33-41`）中没有"取证分析"类型
3. **数据需求判断**：`requires_secondary_data` 默认为 `True`（`semantic_intent.py:43`），且 `_build_result()` 解析LLM输出时也默认 `True`（`semantic_intent.py:408`: `llm_output.get("requires_secondary_data", True)`），系统假设需要搜集数据，但数据已经在年报中。取证模式需在 `_build_result()` 中识别 `data_preloaded` 字段并据此覆盖 `requires_secondary_data`
4. **任务分解**（`task_structure.py:547-591`）：基于aspect生成section，每个section是"章节"而非"假设"
5. **数据注入**（`generic_agent.py:373-405`）：按 `section_type` 粗匹配注入（含sections过滤373-386行和tables循环398-405行），无法按假设需要的精准数据项提取
6. **LLM prompt注入**（`generic_agent.py:814-834`）：document_context按section_type三级优先链匹配，假设验证agent的假设内容（如"非现金支出增加"）无法匹配section_type
7. **分析深度**：agent产出描述性摘要，缺少因果归因和假设验证

**核心矛盾：系统假设所有研究都需要"搜集数据"，但取证问题的数据已经存在。**

---

## 2. 设计目标

1. **模式识别**：系统自动识别"问题型+已有数据"输入，切换到取证分析模式
2. **假设驱动分解**：基于核心问题生成因果假设，而非章节框架
3. **精准数据提取**：按假设需要的数据项从年报中精准提取，而非按section_type粗匹配
4. **递进式验证**：假设生成→数据提取→假设验证→综合归因，而非平行章节独立分析
5. **精准回答**：输出"问题回答+证据链"，而非"完整报告"

---

## 3. 系统架构变更

### 3.1 总体架构：在现有三层分析中增加取证分支

现有架构（`intelligent_routing_adapter.py:311-365`，核心步骤在330-337）：

```
analyze():
  Step 1: _analyze_intent()      → DeepIntentResult
  Step 2: _analyze_structure()   → TaskStructure
  Step 3: _orchestrate_phases()  → ExecutionPlan
```

变更后：

```
analyze():
  Step 1: _analyze_intent()      → DeepIntentResult (增加 forensic_mode 标志)
  Step 2: if forensic_mode:
            _analyze_forensic_structure()  → TaskStructure (假设驱动)
          else:
            _analyze_structure()           → TaskStructure (章节驱动)
  Step 3: if forensic_mode:
            _orchestrate_forensic_phases() → ExecutionPlan (假设验证流水线)
          else:
            _orchestrate_phases()          → ExecutionPlan (现有流水线)
```

**设计原则：分支而非替换。现有全景研究模式的代码路径完全不变。**

### 3.2 变更清单

| # | 组件 | 变更 | 文件 |
|---|------|------|------|
| C1 | IntentType 枚举 | 增加 `FORENSIC_ANALYSIS` | `src/core/intent_types.py:33-41` |
| C2 | DeepIntentResult | 增加 `forensic_mode`、`data_preloaded` 字段 | `src/core/semantic_intent.py:31-62` |
| C3 | 意图分析prompt | 增加取证模式识别指导 | `prompts/agents/intent_analysis_system.md` |
| C4 | section_data_specs | 增加 `"preloaded"` data_source_type | `prompts/agents/intent_analysis_system.md:77-80` |
| C5 | IntelligentRoutingAdapter | 增加取证分支 | `src/core/intelligent_routing_adapter.py:311-365` |
| C6 | TaskStructureAnalyzer | 增加假设驱动的结构生成；SectionSpec增加`config`字段 | `src/core/task_structure.py` |
| C7 | SectionRole 枚举 | ~~增加 `HYPOTHESIS` 角色~~ 复用ANALYSIS（见4.2.2论证） | `src/core/task_structure.py:37-52` |
| C8 | PhaseType 枚举 | ~~增加 HYPOTHESIS_GENERATION~~ 复用现有PhaseType（见4.2.2论证） | `src/core/dynamic_orchestrator.py:16-24` |
| C9 | DynamicPhaseOrchestrator | 增加取证模式phase生成 | `src/core/dynamic_orchestrator.py:182-319` |
| C10 | AnnualReportParser | 增加精准检索API | `src/skills/analysis/annual_report_parser.py` |
| C11 | GenericAgent preloaded路径 | 增加按数据项精准提取 | `src/core/agents/generic_agent.py:365-421` |
| C12 | API question_suffixes | 取证问题允许进入研究流程 | `src/api/research_api.py:379-382` |

---

## 4. 详细设计

### 4.1 C1-C4：意图识别层

#### 4.1.1 IntentType 增加 FORENSIC_ANALYSIS

```python
# src/core/intent_types.py:33-41
class IntentType(Enum):
    RESEARCH = "research"
    IMPLEMENTATION = "implementation"
    INVESTIGATION = "investigation"
    EVALUATION = "evaluation"
    FIX = "fix"
    OPEN_ENDED = "open_ended"
    CLARIFICATION = "clarification"
    FORENSIC_ANALYSIS = "forensic_analysis"  # 新增：取证分析
```

**判定规则**：LLM在意图分析时，当输入满足以下条件时输出 `forensic_analysis`：
- 输入是问题型（包含"为什么"、"如何"、"是否"、疑问词）
- 且已有preloaded文档数据（`dynamic_fields` 中有 `annual_report_data`）
- 且问题的答案可从已有数据中推导（非事实性问题如"公司总部在哪"除外）

**为什么不用现有的 `INVESTIGATION`**：`INVESTIGATION` 的语义是"问题诊断/数据验证"，侧重于"发现问题"；`FORENSIC_ANALYSIS` 侧重于"解释现象的因果关系"，语义更精准。

**论证**：是否需要新增类型 vs 复用 INVESTIGATION？
- INVESTIGATION 的 prompt 语义是"调查问题"，触发数据验证流程
- FORENSIC_ANALYSIS 的语义是"解释因果"，触发假设验证流程
- 两者的phase编排完全不同（前者是验证→修正，后者是假设→验证→归因）
- 结论：必须新增类型，否则在后续分支中需要大量 `if investigation and has_preloaded_data` 的条件判断

#### 4.1.2 DeepIntentResult 增加字段

```python
# src/core/semantic_intent.py:31-62 (dataclass定义从第31行@dataclass开始)
@dataclass
class DeepIntentResult:
    # ... 现有字段 ...
    forensic_mode: bool = False           # 是否为取证分析模式
    data_preloaded: bool = False          # 数据是否已存在于preloaded文档中
    causal_hypotheses: List[str] = field(default_factory=list)  # 初始因果假设
```

**论证**：为什么不用 `domain_context` 字典传递？
- `forensic_mode` 和 `data_preloaded` 是控制流标志，需要类型安全和明确的访问路径
- 放在 `domain_context` 中是 `domain_context.get("forensic_mode")` — 无类型检查，易拼写错误
- 独立字段有IDE补全和类型检查支持

**`causal_hypotheses` 的必要性**：
- 意图分析阶段LLM已理解用户问题，可以同时输出初步假设
- 避免后续单独调用LLM生成假设，节省一次API调用
- 假设可以在后续phase中被修正，此处只是初始版本

**`_build_result()` 解析逻辑的配套修改**：`DeepIntentResult` 新增的 `forensic_mode`、`data_preloaded`、`causal_hypotheses` 字段需要从LLM输出JSON中解析。当前 `_build_result()`（`semantic_intent.py:352-432`）需要增加：
```python
forensic_mode=llm_output.get("forensic_mode", False),
data_preloaded=llm_output.get("data_preloaded", False),
causal_hypotheses=llm_output.get("causal_hypotheses", []),
```
同时，当 `data_preloaded=True` 时，需覆盖 `requires_secondary_data` 为 `False`：
```python
requires_secondary_data=not llm_output.get("data_preloaded", False) and llm_output.get("requires_secondary_data", True),
```
这确保取证模式下系统不会触发不必要的外部数据搜索。

#### 4.1.3 意图分析prompt增强

在 `prompts/agents/intent_analysis_system.md` 中增加取证模式识别规则：

```markdown
## Forensic Analysis Detection

When the user's input meets ALL of the following conditions, set `primary_intent` to `"forensic_analysis"`:

1. **Question-type input**: The input asks a "why", "how", or "whether" question about a specific phenomenon
2. **Preloaded data available**: Document data has been uploaded/parsed (indicated by `file_ids` or `annual_report_data` in requirement)
3. **Answerable from data**: The question can be answered by analyzing the available document data (not requiring external information)

Examples:
- "为什么现金流增长但利润没增长？" → forensic_analysis (question + annual report data + answerable from financial statements)
- "公司的竞争优势是什么？" → forensic_analysis (question + annual report data + answerable from business description)
- "行业前景如何？" → research (question but requires external data, not answerable from annual report alone)

When `primary_intent` is `forensic_analysis`, also output:
- `forensic_mode`: true
- `data_preloaded`: true
- `causal_hypotheses`: array of 3-5 initial causal hypotheses for the observed phenomenon
- `section_data_specs` with `data_source_type: "preloaded"` for data available in the document
```

**论证**：为什么在prompt中增加规则而非代码中硬编码判定？
- LLM已有语义理解能力，可以区分"可从年报回答"vs"需要外部数据"的问题
- 硬编码规则无法覆盖所有情况（如"公司转型是否成功"需要混合内外数据）
- prompt方式更灵活，可通过调整prompt优化判定准确率

#### 4.1.4 section_data_specs 增加 "preloaded" 类型

```markdown
Rules for `data_source_type`:
- **"structured"**: Numeric metrics from APIs
- **"search"**: Qualitative information from web search
- **"both"**: Both structured and search
- **"preloaded"**: Data already available in uploaded document (新增)
```

**论证**：为什么需要 "preloaded"？
- 当前只有 `"structured"` / `"search"` / `"both"` 三种类型
- 取证模式中，大部分数据来自已上传文档，标注为 `"search"` 会导致不必要的搜索
- 标注为 `"preloaded"` 后，agent可以跳过搜索，直接从文档数据中提取

---

### 4.2 C5-C9：任务分解与编排层

#### 4.2.1 IntelligentRoutingAdapter 分支逻辑

```python
# src/core/intelligent_routing_adapter.py:311-365
def analyze(self, user_request, requirement, topic=None):
    # Step 1: Semantic intent analysis (不变)
    intent_result = self._analyze_intent(user_request, requirement)

    # Step 2: Branch based on forensic mode
    if intent_result.forensic_mode:
        task_structure = self._analyze_forensic_structure(requirement, intent_result, topic)
    else:
        task_structure = self._analyze_structure(requirement, intent_result, topic)

    # Step 3: Branch based on forensic mode
    if intent_result.forensic_mode:
        execution_plan = self._orchestrate_forensic_phases(task_structure, intent_result, topic)
    else:
        execution_plan = self._orchestrate_phases(task_structure, intent_result, topic)

    # ... rest unchanged ...
```

**论证**：为什么在 `IntelligentRoutingAdapter` 分支而非在更上层？
- `IntelligentRoutingAdapter` 是三层分析的编排器，是唯一能同时访问intent、structure、plan的组件
- 在更上层（`_research_with_routing`）分支会导致重复三层调用逻辑
- 在更下层（`TaskStructureAnalyzer`）分支会导致该组件承担不属于它的职责（模式判断）

#### 4.2.2 取证模式的任务结构生成：`_analyze_forensic_structure()`

```python
def _analyze_forensic_structure(self, requirement, intent, topic):
    """Generate hypothesis-driven task structure for forensic analysis."""
    hypotheses = intent.causal_hypotheses
    if not hypotheses:
        hypotheses = self._generate_hypotheses_with_llm(intent.core_question, requirement)

    sections = []

    # 先提取所有假设的数据需求（后续假设section和提取section都需要）
    data_needs = self._extract_data_needs_from_hypotheses(hypotheses, requirement)

    # Section 0: Core question statement
    sections.append(SectionSpec(
        section_id="section_0_core_question",
        section_name=intent.core_question,
        section_role=SectionRole.SYNTHESIS,  # 最终综合
        content_dependency=[],
    ))

    # Section 1-N: Each hypothesis is an ANALYSIS section
    for i, hypothesis in enumerate(hypotheses):
        hypothesis_data_needs = self._extract_data_needs_for_hypothesis(hypothesis, data_needs)
        sections.append(SectionSpec(
            section_id=f"section_{i+1}_hypothesis",
            section_name=hypothesis,
            section_role=SectionRole.ANALYSIS,
            content_dependency=[],
            config={  # 新增字段，见4.2.2论证
                "forensic_mode": True,
                "is_hypothesis": True,
                "hypothesis_data_needs": hypothesis_data_needs,
            },
        ))

    # Section N+1: Data extraction (DATA_COLLECTION role)
    sections.append(SectionSpec(
        section_id="section_data_extraction",
        section_name="精准数据提取",
        section_role=SectionRole.DATA_COLLECTION,
        content_dependency=[],
        skill_requirements=["annual_report_parser"],
    ))

    # Core question depends on all hypothesis sections
    for s in sections[1:-1]:
        if s.section_role == SectionRole.ANALYSIS:
            sections[0].content_dependency.append(s.section_id)

    # Hypothesis sections depend on data extraction
    for s in sections[1:-1]:
        if s.section_role == SectionRole.ANALYSIS:
            s.content_dependency.append("section_data_extraction")

    return TaskStructure(
        task_id=requirement.get("task_id", "forensic_unknown"),
        topic=topic or intent.core_question,
        sections=sections,
        dependencies=self._build_forensic_dependencies(sections),
        execution_graph={},
        parallel_groups=self._compute_forensic_parallel_groups(sections),
    )
```

**关键设计决策**：

1. **假设即Section**：每个假设是一个 `SectionSpec`，角色为 `ANALYSIS`。这样复用了现有的section→agent映射机制，无需修改下游代码。

2. **数据提取是一个独立的DATA_COLLECTION section**：所有假设共享同一个数据提取section，避免重复提取。假设验证agent依赖数据提取agent的输出（通过 `aggregated_data_points`），不直接调用 `AnnualReportParserSkill`。

3. **核心问题是一个SYNTHESIS section**：最终综合agent汇总所有假设验证结果，回答核心问题。

**论证：为什么假设是ANALYSIS角色而非新增HYPOTHESIS角色？**

方案A：新增 `SectionRole.HYPOTHESIS` 角色
- 优点：语义更精确
- 缺点：需要在 `dynamic_orchestrator.py` 的 `to_decomposition_plan()` 中增加HYPOTHESIS→category映射，在 `generic_agent.py` 中增加HYPOTHESIS category处理，在engine.py中增加HYPOTHESIS agent的task构建。改动面大，回归风险高。

方案B：复用 `SectionRole.ANALYSIS` 角色
- 优点：复用现有ANALYSIS→DEEP_ANALYSIS→"analysis" category的完整路径，改动最小
- 缺点：语义稍弱，假设验证和普通分析混用同一角色

**选择方案B**。原因：
1. ANALYSIS角色的agent行为（接收上游数据→深度分析→输出结论）与假设验证的agent行为完全一致
2. 区别仅在agent的prompt中（"验证假设X" vs "分析章节Y"），而非在角色分类中
3. `core_question` 字段已能区分：假设验证agent的 `core_question` 是假设陈述，普通分析agent的是章节名
4. 如果将来需要差异化处理，可通过 `config` 字段传递 `is_hypothesis: True` 标志

**注意**：当前 `SectionSpec`（`task_structure.py:56-87`）没有 `config` 字段。取证模式需要为假设验证section传递 `hypothesis_data_needs` 等元数据。有两种方案：

方案A：给 SectionSpec 增加 `config: Dict[str, Any] = field(default_factory=dict)` 字段
- 优点：数据随section流转，下游可通过 `spec.config` 访问
- 缺点：修改 SectionSpec 定义，需同步更新 `to_dict()` 方法

方案B：在 `_create_agents_from_plan()` 中从 `intent_result` 获取假设数据需求，而非从 `spec.context`
- 优点：不修改 SectionSpec，利用已有的 `intent_result` 参数
- 缺点：需要在 `_create_agents_from_plan()` 中按 `spec.agent_id` 匹配到对应假设

**选择方案A**。原因：`config` 字段是通用的扩展机制，未来其他模式也可能需要传递section级元数据；且 `AgentSpec` 已有 `config` 字段（`dynamic_orchestrator.py:49`），SectionSpec 增加同名字段保持一致性。实现时需同步修改 `to_dict()` 方法。

#### 4.2.3 取证模式的Phase编排：`_orchestrate_forensic_phases()`

```
Phase A: DATA_COLLECTION — 精准数据提取
  1个agent：根据所有假设的数据需求，从年报中精准提取
  输出：按假设分组的data_points

Phase B: DEEP_ANALYSIS — 假设验证
  N个agent（每个假设1个）：验证/反驳/量化假设
  依赖：Phase A
  输出：假设成立/不成立 + 量化贡献度 + 证据引用

Phase C: SYNTHESIS — 因果归因
  1个agent：汇总所有假设验证结果，构建因果链，回答核心问题
  依赖：Phase B 所有agent
  输出：核心问题回答 + 归因桥接图 + 投资启示

Phase D: CALIBRATION — 数据口径校准（复用现有）
  依赖：Phase C

Phase E: REPORT — 报告生成（复用现有）
  依赖：Phase D
```

**与现有编排的对比**：

| | 全景研究模式 | 取证分析模式 |
|---|---|---|
| Phase A | DATA_COLLECTION（每个章节一个agent，并行搜集） | DATA_COLLECTION（1个agent，精准提取） |
| Phase B | DEEP_ANALYSIS（每个章节一个agent，独立分析） | DEEP_ANALYSIS（每个假设一个agent，依赖Phase A数据） |
| Phase C | SYNTHESIS（summary/conclusion等） | SYNTHESIS（因果归因，回答核心问题） |
| Phase D | CALIBRATION | CALIBRATION（复用） |
| Phase E | REPORT | REPORT（复用） |

**论证：为什么不需要新增 `HYPOTHESIS_GENERATION` phase？**

初始设计中考虑过将"假设生成"作为独立phase。分析后认为不必要：

1. 假设在意图分析阶段已由LLM生成（`causal_hypotheses` 字段）
2. 如果 `causal_hypotheses` 为空，在 `_analyze_forensic_structure()` 中调用LLM补充生成
3. 这发生在编排阶段之前，是结构生成的一部分，不需要单独的agent执行
4. 新增phase会增加编排复杂度，且假设生成本身是一次性LLM调用，不值得一个独立phase

**重要：`_orchestrate_forensic_phases()` 必须是独立方法，不能复用 `_generate_phases()`**。现有 `_generate_phases()`（`dynamic_orchestrator.py:182-319`）包含M1拆分逻辑（第202-241行），会自动将每个ANALYSIS section拆分为DC+Analysis双phase。取证模式的数据提取是独立的DATA_COLLECTION section（非M1拆分产生），假设验证agent依赖此section而非各自产生DC agent。如果复用 `_generate_phases()`，假设验证section会被M1拆分为额外的DC agent，导致每个假设都有一个独立搜索agent——这与取证模式的"共享数据提取"设计矛盾。

**论证：为什么数据提取是1个agent而非N个？**

方案A：每个假设一个数据提取agent
- 优点：并行提取
- 缺点：同一份年报被N个agent重复提取，浪费API调用和token

方案B：1个共享数据提取agent
- 优点：一次提取，去重后按假设分组传递给验证agent
- 缺点：数据提取agent需要理解所有假设的需求

**选择方案B**。原因：
1. 年报数据已经在SharedMemory中（preloaded），提取是内存操作，不是网络调用，并行无速度优势
2. 去重效率高：同一份"应收账款变动"数据，5个假设中3个需要，只需提取一次
3. 数据一致性：单一提取agent确保所有验证agent看到相同的底层数据

#### 4.2.4 取证模式的数据传递链

年报解析数据通过**两条并行路径**到达agent，取证模式必须确保两条路径都正确工作：

**路径A：document_context注入（LLM分析上下文）**

```
requirement.dynamic_fields["annual_report_data"]
  → _create_agents_from_plan() 中推导出 document_context 字符串
  → agent._context["document_context"]
  → execution/engine.py:2371-2380 复制到 task["document_context"]
  → generic_agent.py:814-834 注入LLM prompt
```

取证模式下此路径的变更：假设验证agent的`document_context`不应按`section_type`匹配（4.2.2论证中假设是ANALYSIS角色，但假设内容如"非现金支出增加"无法匹配section_type），而应按假设的`data_needs`关键词从年报中精准提取。这意味着`_create_agents_from_plan()`中对取证模式agent需要新的`document_context`推导逻辑。

具体设计：在`_create_agents_from_plan()`的annual report注入段（`src/core/orchestrator/orchestrator.py:3994-4096`）中，当`intent_result.forensic_mode=True`时，对假设验证agent使用`extract_for_hypothesis()`生成`document_context`，而非走现有的三级优先链（aspect→section_type→全局摘要）。

```python
# src/core/orchestrator/orchestrator.py _create_agents_from_plan() 取证分支
if intent_result.forensic_mode and spec.agent_type == "analysis":
    from src.skills.analysis.annual_report_parser import AnnualReportParserSkill
    parser = AnnualReportParserSkill()
    hypothesis_name = spec.agent_id  # 或从context中获取
    # 注意：此处spec是strategies.py的AgentSpec，字段名为context而非config
    # SectionSpec.config中的数据经to_decomposition_plan()转换后，会通过spec.context传递
    # （to_decomposition_plan()未显式复制config字段，需在转换时补充，见下方说明）
    data_needs = spec.context.get("hypothesis_data_needs", [])
    extracted = parser.extract_for_hypothesis(annual_report_data, hypothesis_name, data_needs)
    if extracted["relevant_sections"] or extracted["relevant_line_items"]:
        parts = []
        for sec in extracted["relevant_sections"]:
            parts.append(f"### {sec['title']}\n{sec.get('content', '')[:4000]}")
        for item in extracted["relevant_line_items"]:
            parts.append(f"### {item['table_type']} - {item['row'].get('科目', '')}\n{item['row']}")
        document_context = f"[年报相关数据（假设验证）]\n\n" + "\n\n".join(parts)
```

**`hypothesis_data_needs` 的数据传递链**：SectionSpec.config → to_decomposition_plan() → OriginalAgentSpec.context → _create_agents_from_plan() → spec.context。当前 `to_decomposition_plan()`（`dynamic_orchestrator.py:109-133`）未将 `AgentSpec.config` 中的 `hypothesis_data_needs` 等自定义字段复制到 `OriginalAgentSpec.context`。实现时需在 `to_decomposition_plan()` 中补充：`orig.context.update(spec.config)` 或显式传递 `hypothesis_data_needs`。

**路径B：SharedMemory精准提取（DC agent数据交付）**

```
orchestrator._shared_memory.write("annual_report_data", parse_data)  # 同一实例
  → agent._shared_memory (factory.py:381 注入同一对象)
  → generic_agent.py:365-413 preloaded路径读取
```

此路径无需变更。SharedMemory是同一实例（`orchestrator/orchestrator.py:265`创建 → `orchestrator/orchestrator.py:311`传给ExecutionEngine → `execution/engine.py:234`存储 → `factory.py:381`注入agent → `agent._shared_memory`），取证模式agent通过`self._context.get("forensic_mode")`进入精准提取分支（4.3.2节已设计）。

**两条路径的协同**：
- 路径A（document_context）为analysis agent的LLM分析提供上下文——LLM知道"年报里有哪些相关数据"
- 路径B（SharedMemory精准提取）为DC agent的结构化数据交付提供数据源——DC agent按data_needs精准提取
- 两者互补：analysis agent的prompt中同时包含document_context（路径A注入）和aggregated_data_points（来自DC agent通过路径B提取的结果）

**数据传递完整性验证**：
- SharedMemory实例：同一对象，无丢失风险
- `forensic_mode`和`hypothesis_data_needs`通过`agent._context`传递，`_create_agents_from_plan()`中注入
- engine.py已实现`document_context`从`agent._context`到`task`的复制（`execution/engine.py:2371-2380`）
- 年报解析结果无持久化——SharedMemory纯内存，进程重启丢失；session JSON只保存file_ids引用不保存parse_data。当前同一任务内无问题，跨session/重启需重新解析（可接受，20秒）

---

### 4.3 C10：年报数据精准检索API

#### 4.3.1 设计

在 `AnnualReportParserSkill` 中增加三个方法：

```python
def search_sections(self, parse_data: dict, keywords: List[str]) -> List[dict]:
    """在年报sections中按关键词搜索相关段落"""
    results = []
    for section in parse_data.get("sections", []):
        content = section.get("content", "")
        for kw in keywords:
            if kw in content or kw in section.get("title", ""):
                results.append(section)
                break
    return results

def find_line_items(self, parse_data: dict, metric_keywords: List[str]) -> List[dict]:
    """在financial_tables中按科目关键词查找行项目"""
    results = []
    for table_type, rows in parse_data.get("financial_tables", {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            subject = row.get("科目", "")
            for kw in metric_keywords:
                if kw in subject:
                    results.append({"table_type": table_type, "row": row})
                    break
    return results

def extract_for_hypothesis(self, parse_data: dict, hypothesis: str, data_needs: List[str]) -> dict:
    """为假设验证提取所有相关数据"""
    sections = self.search_sections(parse_data, data_needs)
    line_items = self.find_line_items(parse_data, data_needs)
    return {
        "hypothesis": hypothesis,
        "relevant_sections": sections,
        "relevant_line_items": line_items,
        "section_count": len(sections),
        "line_item_count": len(line_items),
    }
```

**论证：为什么放在parser中而非新建模块？**

1. parser已有完整的sections和financial_tables数据结构知识
2. 搜索是数据访问操作，属于parser的职责
3. 避免循环依赖：如果新建模块，需要import parser的数据结构

**论证：关键词搜索 vs 语义搜索？**

当前选择关键词搜索（`kw in content`），原因：
1. 年报数据是结构化+半结构化文本，关键词匹配的精确度高
2. 语义搜索需要embedding模型，增加系统复杂度
3. `data_needs` 由LLM生成，已经是精准的科目名（如"应收账款"、"折旧"），关键词足够
4. 如果将来需要语义搜索，可作为增强层叠加，不影响当前设计

#### 4.3.2 在GenericAgent中的使用

修改 `generic_agent.py:365-421` 的preloaded路径，当 `forensic_mode=True` 时使用精准提取：

```python
# generic_agent.py preloaded路径增加
if self._context.get("forensic_mode") and self._context.get("hypothesis_data_needs"):
    from src.skills.analysis.annual_report_parser import AnnualReportParserSkill
    parser = AnnualReportParserSkill()
    data_needs = self._context.get("hypothesis_data_needs", [])
    hypothesis = self._context.get("core_question", "")
    extracted = parser.extract_for_hypothesis(annual_report_data, hypothesis, data_needs)
    # 构建精准的data_points
    data_points = []
    for sec in extracted["relevant_sections"]:
        data_points.append({
            "title": sec.get("title", ""),
            "content": sec.get("content", "")[:4000],
            "source": "annual_report_pdf",
            "type": sec.get("section_type", "document"),
            "relevance": "hypothesis_match",
        })
    for item in extracted["relevant_line_items"]:
        data_points.append({
            "title": f"{item['table_type']} - {item['row'].get('科目', '')}",
            "content": str(item["row"]),
            "source": "annual_report_pdf_table",
            "type": "structured_data",
            "relevance": "hypothesis_match",
        })
else:
    # 现有逻辑：按section_type匹配
    ...
```

**论证：为什么不在现有preloaded路径中直接修改，而是增加分支？**

1. 现有路径按 `section_type` 匹配，适用于全景研究模式，不应破坏
2. 取证模式的精准提取逻辑（按data_needs关键词）与section_type匹配逻辑完全不同
3. 分支判断基于 `forensic_mode` 标志，两种模式互不干扰

---

### 4.4 C12：API层变更

#### 4.4.1 question_suffixes 修复

当前代码（`research_api.py:379-382`）：

```python
is_depth_command = any(kw in input_lower for kw in depth_keywords) and not any(input_lower.endswith(s) for s in question_suffixes)
```

问题：问题型输入被阻止进入研究快捷通道。

修复：当已有preloaded文档数据时，问题型输入应允许进入研究流程：

```python
has_preloaded = bool(session.get("custom_params", {}).get("file_ids"))
is_depth_command = any(kw in input_lower for kw in depth_keywords) and (not any(input_lower.endswith(s) for s in question_suffixes) or has_preloaded)
```

**论证**：为什么不是直接去掉 `question_suffixes` 检查？
- 对于没有preloaded数据的问题（如"比亚迪行业前景如何？"），保持在chat模式是合理的——chat模式会调用搜索回答
- 只有"已有数据+问题型输入"才应进入研究流程
- `has_preloaded` 标志精准识别了这个场景

---

## 5. 完整数据流

### 5.1 取证分析模式的端到端流程

```
用户输入: "为什么现金流增长利润没增长？" + 已上传年报PDF
    │
    ▼
API层 (research_api.py)
    │ has_preloaded=True → 允许进入研究流程
    ▼
研究入口 (orchestrator._research_with_routing)
    │ Phase 1: _parse_requirement() → 提取topic, file_ids等
    │ Phase 1.5: 解析年报 → annual_report_data 写入 SharedMemory + requirement.dynamic_fields
    │ Phase 2: 构建requirement_dict，注入document_metadata（年报数据目录）
    ▼
IntelligentRoutingAdapter.analyze()
    │
    ├─ Step 1: _analyze_intent()
    │   │ LLM看到：用户问题 + document_metadata（有cashflow/balance/income表）
    │   │ → 判断：问题可从文档回答
    │   │ → primary_intent=FORENSIC_ANALYSIS
    │   │ → 输出: core_question, causal_hypotheses=[H1,H2,H3,H4],
    │   │       forensic_mode=True, data_preloaded=True
    │   │
    ├─ Step 2: _analyze_forensic_structure()
    │   │ 生成SectionSpec:
    │   │   section_0: "为什么现金流增长利润没增长" (SYNTHESIS)
    │   │   section_1: H1: "非现金支出增加" (ANALYSIS)
    │   │   section_2: H2: "营运资本改善" (ANALYSIS)
    │   │   section_3: H3: "非经常性损失压低利润" (ANALYSIS)
    │   │   section_4: H4: "会计政策变更影响" (ANALYSIS)
    │   │   section_data: "精准数据提取" (DATA_COLLECTION)
    │   │ 依赖: section_1-4 依赖 section_data; section_0 依赖 section_1-4
    │   │
    └─ Step 3: _orchestrate_forensic_phases()
        │ Phase A: 1个数据提取agent（路径B: SharedMemory精准提取）
        │   → 从年报精准提取: 折旧摊销明细、应收/存货变动、
        │     非经常性损益、会计政策变更
        │ Phase B: 4个假设验证agent (并行，依赖Phase A)
        │   路径A: document_context按data_needs精准生成（非section_type匹配）
        │   路径B: aggregated_data_points来自Phase A的提取结果
        │   → H1: 折旧+8.2亿(成立,贡献35%)
        │   → H2: 应收回收+5.1亿(成立,贡献22%)
        │   → H3: 减值计提+3.7亿(成立,贡献16%)
        │   → H4: 资本化率无显著变化(不成立)
        │ Phase C: 1个因果归因agent
        │   → 综合回答: 现金流增长中约35%来自非现金支出(中性)，
        │     22%来自营运资本改善(正面)，16%来自减值计提(负面信号)
        │ Phase D: CALIBRATION
        │ Phase E: REPORT
```

### 5.2 与全景研究模式的数据流对比

| 步骤 | 全景研究模式 | 取证分析模式 |
|------|-------------|-------------|
| 年报解析 | 相同 | 相同 |
| 意图分析 | `primary_intent=RESEARCH` | `primary_intent=FORENSIC_ANALYSIS` |
| 数据需求 | `requires_secondary_data=True` | `requires_secondary_data=False`（`_build_result()`中`data_preloaded`覆盖）, `data_preloaded=True` |
| 结构生成 | 9个章节section | N个假设section + 1个数据提取 + 1个综合 |
| Phase A | N个DC agent（每章节搜集） | 1个提取agent（精准提取） |
| Phase B | N个分析agent（独立分析） | N个验证agent（假设验证） |
| Phase C | summary/conclusion | 因果归因 |
| 搜索 | 需要 | 跳过（数据已有） |
| 报告 | 完整9章 | 问题回答+证据链 |

---

## 6. 回归风险论证

### 6.1 全景研究模式是否受影响？

**不受影响。** 所有变更都在 `if forensic_mode:` 分支中，现有代码路径完全不变。

具体论证：
- C1 `FORENSIC_ANALYSIS` 枚举值：新增值不影响现有枚举的使用
- C2 `forensic_mode` 字段：默认 `False`，现有代码路径行为不变
- C4 `_build_result()` 新增字段解析：`llm_output.get("forensic_mode", False)` 默认False，不影响现有LLM输出；`data_preloaded`覆盖`requires_secondary_data`仅在`data_preloaded=True`时生效
- C5 分支逻辑：`if intent_result.forensic_mode:` 为 `False` 时走原路径
- C6 `_analyze_forensic_structure()`：新方法，不修改 `_analyze_structure()`；SectionSpec新增`config`字段有默认值`field(default_factory=dict)`，不影响现有构造
- C9 `_orchestrate_forensic_phases()`：新方法，不修改 `_orchestrate_phases()`，不走M1拆分逻辑
- C10 parser新增方法：不影响现有 `execute()` 方法
- C11 GenericAgent：`if self._context.get("forensic_mode"):` 为 `False` 时走现有preloaded路径
- C12 API：只在 `has_preloaded=True` 时放宽限制，不影响无文档的chat
- `to_decomposition_plan()` config→context传播：仅当spec.config非空时`orig.context.update(spec.config)`，现有spec.config为空字典，不影响

### 6.2 边界条件

| 边界条件 | 处理方式 |
|---------|---------|
| 用户问问题但没上传文档 | `data_preloaded=False` → 走全景研究模式（需要搜集数据） |
| 用户上传文档但输入是指令 | `primary_intent=RESEARCH` → 走全景研究模式 |
| 问题部分可从文档回答、部分需外部数据 | 混合模式：取证为主，SYNTHESIS agent可调用搜索补充 |
| LLM生成的假设为空 | `_analyze_forensic_structure()` 中调用LLM补充生成 |
| 假设验证全部不成立 | SYNTHESIS agent输出"初步假设均不成立，可能原因..."，建议进一步调查 |
| 年报中无相关数据 | 数据提取agent输出空结果，假设验证agent标记"数据不足无法验证" |
| PDF解析失败 | `document_metadata`不会被注入，意图分析不知道有文档数据 → 降级为全景研究模式（走搜索补充路径）。`requirement.dynamic_fields`中无`annual_report_data`，`forensic_mode`不会被设为True |

### 6.3 关键假设与验证方式

| 假设 | 验证方式 |
|------|---------|
| LLM能正确区分问题型vs指令型输入 | A/B测试：50个输入样本，检查 `primary_intent` 准确率 |
| LLM能生成合理的因果假设 | 人工评估：3个年报×5个问题，评估假设的合理性和覆盖度 |
| 关键词搜索能从年报中找到相关数据 | 精度测试：20组data_needs，检查搜索召回率和精确率 |
| 假设验证agent能正确使用提取的数据 | E2E测试：运行完整取证流程，检查agent输出质量 |

---

## 7. 实现优先级

| 优先级 | 变更 | 依赖 | 预估工作量 |
|--------|------|------|-----------|
| P0 | C1-C4 意图识别层 + `_build_result()`解析逻辑 | 无 | 2.5h |
| P0 | C12 API question_suffixes修复 | 无 | 0.5h |
| P1 | C5-C6 分支逻辑+取证结构生成+SectionSpec.config | C1-C4 | 4.5h |
| P1 | C9 取证Phase编排（独立方法，不走M1拆分） | C5-C6 | 3h |
| P1 | `to_decomposition_plan()` config→context传播 | C6 | 0.5h |
| P2 | C10 年报精准检索API | 无 | 2h |
| P2 | C11 GenericAgent精准提取 | C10 | 2h |
| P2 | 解析数据磁盘缓存 | 无 | 1h |
| P3 | C7 SectionRole.HYPOTHESIS | 不需要（复用ANALYSIS） | 取消 |
| P3 | C8 PhaseType新增 | 不需要（复用现有PhaseType） | 取消 |

**注**：C7和C8在4.2.2的论证中决定暂不实施——复用现有ANALYSIS角色和PhaseType，通过 `core_question` 和新增的 `SectionSpec.config.forensic_mode` 区分行为。这大幅减少了改动面。

---

## 8. 关键架构决策：先提取数据还是先确认需求？

### 8.1 问题描述

用户提交了PDF文件和初步需求（如"为什么现金流增长利润没增长？"），系统应该：

- **方案A**：先解析PDF提取数据 → 再基于数据理解需求 → 生成研究框架
- **方案B**：先理解需求 → 再解析PDF → 按需提取数据
- **方案C**：先轻量解析PDF（元数据+摘要）→ 理解需求 → 再深度解析PDF → 精准提取

### 8.2 当前系统的顺序

当前流程（`src/core/orchestrator/orchestrator.py:1728-1844`）：

```
Phase 1: _parse_requirement()         ← 先理解需求（第1758行调用）
Phase 1.5: Annual report pre-parsing  ← 再解析PDF（第1766行）
Phase 2: routing_adapter.analyze()    ← 意图分析（第1840行）
```

即**先需求→再解析PDF→再意图分析**。

这个顺序的问题：
1. `_parse_requirement()` 在第1758行构建requirement时，不知道PDF里有什么数据
2. 意图分析在第1840行，此时PDF已解析但 `DeepIntentResult` 的生成没有使用解析结果
3. 结果：意图分析无法判断"这个问题能否从已有数据回答"

### 8.3 信息依赖分析

需求理解和数据可用性之间存在**双向依赖**：

```
需求理解 ←──依赖──→ 数据可用性

需求理解需要知道：
  - 文档中有哪些数据？（决定问题是否可从文档回答）
  - 数据的粒度如何？（决定分析深度）
  - 数据的时间范围？（决定时间约束）

数据提取需要知道：
  - 用户关心什么？（决定提取哪些section和科目）
  - 分析的精度要求？（决定提取深度）
```

这不是简单的先后问题，而是**协同问题**。

### 8.4 方案论证

#### 方案A：先提取数据 → 再理解需求

```
PDF → 全量解析(174 sections, 680 tables) → 基于数据理解需求 → 生成框架
```

**优点**：
- 需求理解有完整数据上下文，判断精准
- 可以知道"年报里有没有现金流调节表"，从而判断问题是否可回答

**缺点**：
- 全量解析耗时（当前实测约20秒），用户等待时间长
- 大部分数据与用户问题无关，浪费计算
- 全量解析不依赖需求，无法做精准提取

**论证**：全量解析是当前已有能力（`annual_report_parser.execute(action="parse")`），且只需做一次。20秒的等待在研究任务（通常5-20分钟）中可接受。**但全量解析的结果应该反馈给意图分析，当前缺少这一步。**

#### 方案B：先理解需求 → 再解析PDF

```
用户问题 → 意图分析 → 按需解析PDF(只提取相关部分) → 分析
```

**优点**：
- 只提取需要的数据，效率高
- 用户等待时间短

**缺点**：
- 意图分析不知道文档里有什么，可能判断错误
  - 例：用户问"为什么现金流增长"，意图分析不知道年报里有没有间接法现金流量表
  - 可能误判为"需要搜索外部数据"，走全景研究模式
- PDF解析器当前不支持"只提取相关部分"——需要先解析TOC才能知道有哪些section
- 部分解析的实现复杂度高（需要选择性页面提取）

**论证**：意图分析在不知道数据可用性的情况下，无法做出"问题可从文档回答"的判断。这是致命缺陷。

#### 方案C：轻量解析 → 理解需求 → 深度提取（两阶段解析）

```
PDF → 轻量解析(TOC+元数据+section摘要) → 意图分析(有数据目录) → 按需深度提取 → 分析
```

**优点**：
- 轻量解析快速（1-2秒），提供数据目录
- 意图分析知道文档里有什么section和数据类型
- 深度提取只针对假设需要的数据项，精准高效

**缺点**：
- 需要实现两阶段解析器（当前只有一次性全量解析）
- 轻量解析和深度解析的接口设计需要仔细考虑
- 增加了系统复杂度

**论证**：这是理论最优解，但实现成本高。当前解析器不支持两阶段解析。

### 8.5 决策：方案A（先提取数据），但修复信息断裂

**选择方案A**，原因：

1. **当前已有全量解析能力**，无需新增解析器
2. **20秒解析时间在研究任务中可接受**（整个任务5-20分钟）
3. **关键不是顺序问题，而是信息传递问题**：当前流程先解析PDF再意图分析，但意图分析没有使用解析结果。修复这个信息断裂即可。

**具体修复**：将PDF解析结果传入意图分析，让LLM在判断意图时知道数据可用性。

当前代码（`src/core/orchestrator/orchestrator.py:1840`）：

```python
routing_result = self._routing_adapter.analyze(
    user_request=requirement.topic,
    requirement=requirement_dict,      # ← 不含annual_report_data
    topic=requirement.topic,
)
```

修复后：

```python
# 将年报元数据注入requirement_dict，供意图分析使用
if requirement.dynamic_fields.get("annual_report_data"):
    ar_data = requirement.dynamic_fields["annual_report_data"]
    requirement_dict["document_metadata"] = {
        "has_annual_report": True,
        "section_types": list(set(s.get("section_type", "") for s in ar_data.get("sections", []))),
        "section_count": len(ar_data.get("sections", [])),
        "table_types": list(ar_data.get("financial_tables", {}).keys()),
        "table_row_count": {k: len(v) for k, v in ar_data.get("financial_tables", {}).items() if isinstance(v, list)},
        "year": ar_data.get("meta", {}).get("year"),
    }

routing_result = self._routing_adapter.analyze(
    user_request=requirement.topic,
    requirement=requirement_dict,      # ← 现在含document_metadata
    topic=requirement.topic,
)
```

意图分析prompt中增加：

```markdown
## Document Data Availability

If `requirement.document_metadata` is present, consider what data is already available:

- `section_types`: list of section categories in the document (e.g., ["financial", "cashflow", "risk"])
- `table_types`: list of financial table types (e.g., ["income", "balance", "cashflow"])
- `table_row_count`: number of rows per table type

When the user's question can be answered from the available document data:
- Set `primary_intent` to `"forensic_analysis"` (not `"research"`)
- Set `data_preloaded` to `true`
- Use `data_source_type: "preloaded"` in section_data_specs
```

**`document_metadata` 传递链验证**：`requirement_dict` 注入 `document_metadata` 后，传递路径为：`requirement_dict` → `_analyze_intent(user_request, requirement)` → `_format_intent_prompt(template, user_request, requirement)` → `template.format(..., requirement_json=json.dumps(requirement, ...))` → LLM prompt。由于 `requirement` 被整体序列化为JSON填入prompt模板的 `{requirement_json}` 占位符（见 `_format_intent_prompt()` 定义 `semantic_intent.py:268-270`），`document_metadata` 会被自动包含在LLM可见的输入中，无需额外修改传递逻辑。

### 8.6 完整流程（修复后）

```
用户输入: "为什么现金流增长利润没增长？" + PDF
    │
    ▼
Phase 1: _parse_requirement()
    │ 提取topic, aspects, file_ids等
    ▼
Phase 1.5: Annual report pre-parsing (全量解析)
    │ 解析PDF → 174 sections, 680 tables
    │ 写入SharedMemory + requirement.dynamic_fields
    ▼
Phase 2: routing_adapter.analyze()
    │ requirement_dict 包含 document_metadata（年报数据目录）
    │ ↓
    │ _analyze_intent():
    │   LLM看到：用户问题 + 文档中有cashflow/balance/income表
    │   → 判断：问题可从文档回答
    │   → primary_intent = FORENSIC_ANALYSIS
    │   → forensic_mode = True
    │   → causal_hypotheses = [H1, H2, H3, H4]
    │ ↓
    │ _analyze_forensic_structure():
    │   基于假设生成section结构
    │ ↓
    │ _orchestrate_forensic_phases():
    │   生成假设验证流水线
    ▼
Phase 3: Agent创建 + 执行
    │ 数据提取agent → 假设验证agent → 因果归因agent
    ▼
Phase 4: 报告生成
```

### 8.7 为什么不需要两阶段解析（方案C）

方案C的核心优势是"按需深度提取"，但当前场景下：

1. **年报PDF的全量解析已经很快**（20秒），且只需做一次
2. **"按需提取"在agent执行阶段自然发生**——数据提取agent根据假设的data_needs从已解析的数据中精准检索，不需要重新解析PDF
3. **两阶段解析的实现成本**：需要修改parser支持"只解析TOC"和"按section深度解析"两种模式，涉及PDF页面选择、表格区域定位等底层改动

**结论**：全量解析一次 + agent阶段精准检索，比两阶段解析更简单且效果相同。

---

## 9. 开放问题

1. **混合模式处理**：当问题部分可从文档回答、部分需外部数据时，如何处理？当前设计在SYNTHESIS阶段允许搜索补充，但这可能导致SYNTHESIS agent过度依赖搜索。需要更精确的"数据缺口检测"机制。

2. **假设质量评估**：LLM生成的假设可能遗漏关键因素。是否需要"反证agent"主动寻找与假设矛盾的证据？这与现有 `causal_hypotheses` 机制（`generic_agent.py:761-793`，从A2.1因果假设生成到LLM调用+解析）的交叉验证功能有关，可复用。

3. **多次追问**：用户看完取证结果后可能追问（"那减值计提的具体构成是什么？"），需要支持在同一session中增量分析。当前session机制已支持对话历史，但需要确保追问时能复用之前提取的数据。

4. **取证模式报告模板**：当前report generation使用通用模板。取证模式需要专门的报告模板（核心结论→归因分析→证据链→启示）。这涉及 `report_generation_agent` 的模板选择逻辑。

5. **解析数据持久化**：年报解析结果存储在SharedMemory（纯内存字典`_data: Dict[str, Any]`）和`requirement.dynamic_fields`中，但session JSON只保存file_ids引用不保存parse_data。进程重启后数据丢失，同一PDF需重新解析（~20秒）。当前同一任务内无问题，但跨session追问（如"那减值计提的具体构成是什么？"）需要确保复用已有解析结果，而非重新解析。可选方案：(a) 将parse_data缓存到磁盘`data/cache/{file_id}.json`；(b) 在session JSON中保存parse_data摘要。方案(a)更优，按file_id去重，跨session复用。
