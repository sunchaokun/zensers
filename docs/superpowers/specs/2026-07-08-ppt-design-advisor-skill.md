# PPT Design Advisor Skill 集成方案

> 版本：v1.2 | 日期：2026-07-09
> 目标：做成一个 **PPT 设计增强器 skill**，报告 agent 生成 PPT 前按需调用，让现有系统的输出从"能用"变成"专业"
> 约束：不复制对方代码/文件；做成独立 skill，不侵入现有管线；可独立升级维护

---

## 一、定位：增强器，不是替换件

**现状问题：** 我们的 PPT 生成管线功能完整（数据提取→slide_data→模板选择→渲染→PPTX），但设计水平停留在"能用"——

| 问题 | 根因 | 影响 |
|------|------|------|
| 所有行业报告一个配色(navy/gold) | SlideRenderer 硬编码 DESIGN 字典 | 新能源报告和AI报告看起来一样 |
| 模板选择靠启发式猜 | TemplateSelector 只看 slide_data 字段，不知道"这是什么类型的报告" | 数据页该用双栏却用了全图 |
| 没有情绪节奏 | 每页独立决策，前后页无关联 | 9页PPT视觉单调，像流水账 |
| 图表选择靠LLM猜 | SmartChartGenerator 无结构化推荐 | 时间序列数据用了饼图 |
| 不知道什么不该做 | 没有反模式约束 | 金融报告出现卡通图标 |

**ppt_design_advisor 的角色 = 设计顾问**，在报告 agent 准备生成 PPT 时被调用，回答这些问题：

- "新能源汽车报告用什么色板？" → 信任蓝 #1A56DB + 金色强调 #C9A227
- "第4页是KPI数据页，该用什么布局？" → kpi_highlight 模板 + 大号数字 + 图表
- "这页该不该打破视觉节奏？" → 是，1/3位置，切gradient背景
- "时间序列数据用什么图表？" → 折线图，不是饼图

**它不做渲染，不做生成，只做决策。** 渲染仍然由现有 SlideRenderer + HTMLToPPTConverter 完成。

---

## 二、为什么做 skill 而不是集成

| 维度 | 硬集成（改现有代码） | Skill（按需加载） |
|------|---------------------|-------------------|
| 耦合度 | 高 — 改 SlideRenderer/TemplateSelector/SlideDataBuilder | 零 — 现有代码不改一行 |
| 升级 | 改一处动全身 | skill 独立迭代，不影响主系统 |
| 维护 | 设计逻辑散落各模块 | 设计逻辑内聚在 skill 目录 |
| 加载 | 始终加载，增加启动开销 | 报告 agent 按需加载，不用不加载 |
| 测试 | 需要回归全系统 | skill 独立测试，不影响现有 317 个测试 |
| 替换 | 想换方案要大改 | 换 skill 即可，甚至可以多 skill 切换 |

**结论：做成 `ppt_design_advisor` skill，报告 agent 在生成 PPT 前调用，获得设计决策，注入 slide_data。**

---

## 三、Skill 在管线中的位置

### 3.1 Skill 内部管线（不变）

```
1. 用户上传文件 → PptInputAdapter 提取数据
2. PptRequirementExtractor 提取需求
3. ★ 调用 ppt_design_advisor.advise_deck(topic, slide_count, style_hint)
   → 返回 List[DesignContext]（每页的色板+布局+排版+情绪+图表推荐）
4. SlideDataBuilder.build_list() 时，将 DesignContext 写入 slide_data["design_context"]
5. TemplateSelector 优先读 design_context.layout_template（小改，2行代码）
6. SlideRenderer 优先读 design_context.colors（小改，3行代码）
7. 生成 PPTX
```

**Skill 只做决策，不做渲染。** 渲染仍由现有 SlideRenderer + HTMLToPPTConverter 完成。
现有管线的改动仅限：TemplateSelector 和 SlideRenderer 各加一个 `if design_context:` 分支（共 ~5 行），不是硬集成。

### 3.2 多条触发路径（v1.1 新增）

PPT 生成不是单一入口，存在至少 3 条触发路径，ppt_design_advisor 必须在每条路径中都能被调用：

#### 路径 A：研究 → PPT（先研究后制PPT）

```
用户: "帮我研究新能源汽车市场"
  → UNDERSTANDING → CLARIFYING → FRAMEWORK_CONFIRM → EXECUTING
  → 研究完成 → COMPLETED
  → 用户: "帮我做成PPT" / "生成PPT报告"
  → LLM action="generate_ppt"
  → ★ _start_ppt_generation(session_id)
      → 从 session['research_result'] 取研究数据
      → 转换为 ExtractionResult（或直接用 sections）
      → PptRequirementExtractor.extract() → PptRequirement(style_hint=...)
      → ★ ppt_design_advisor.advise_deck(topic, count, style_hint)
      → SlideDataBuilder + design_context 注入
      → PptStructureEditor.edit() → PPTX
```

**数据来源：** `session['research_result']['report']['sections']` — 研究产出的结构化内容
**style_hint 来源：** 用户在 PPT 生成请求时表达的风格偏好，或 session 中已存储的 style_hint

#### 路径 B：直接制PPT（用户提供素材）

```
用户上传文件 + "帮我做一份PPT"
  → POST /api/v1/research/start (user_input, file_ids)
  → PptInputAdapter.extract(file_ids) → ExtractionResult
  → DATA_EXTRACTED
  → LLM: "已读取3个文件...您想基于这份材料做什么？"
  → 用户: "生成PPT，要科技高级感"
  → REQUIREMENT_CONFIRM → style_hint="premium_tech" 存入 session
  → ★ _start_ppt_generation(session_id)
      → 从 session['research_context']['extraction_result'] 取提取数据
      → PptRequirementExtractor.extract() → PptRequirement(style_hint="premium_tech")
      → ★ ppt_design_advisor.advise_deck(topic, count, style_hint="premium_tech")
      → SlideDataBuilder + design_context 注入
      → PptStructureEditor.edit() → PPTX
```

**数据来源：** `session['research_context']['extraction_result']` — 用户上传文件提取的数据
**style_hint 来源：** REQUIREMENT_CONFIRM 阶段用户表达的风格偏好

#### 路径 C：Word → PPT（先生成Word再转PPT）

```
用户: "帮我研究XX" → 研究完成 → 生成 Word 报告
  → 用户: "再帮我做一份PPT版本"
  → LLM action="generate_ppt"
  → ★ _start_ppt_generation(session_id)
      → 从 session['research_result'] 取研究数据（同路径A）
      → 或从已生成的 Word 文档重新提取（如果研究数据不完整）
      → PptRequirementExtractor.extract() → PptRequirement(style_hint=...)
      → ★ ppt_design_advisor.advise_deck(topic, count, style_hint)
      → SlideDataBuilder + design_context 注入
      → PptStructureEditor.edit() → PPTX
```

**数据来源：** 同路径A，或从 Word 文档路径重新提取
**style_hint 来源：** 用户在 PPT 请求时表达的风格偏好

#### 路径 D：未来扩展（API 直接调用）

```
POST /api/v1/ppt/generate
  body: { topic, file_ids, style_hint, slide_count }
  → 直接走 PPT 生成管线，跳过对话
```

**预留接口，Phase 6 不实现，但架构需兼容。**

### 3.3 统一触发入口设计

4 条路径汇聚到同一个内部函数 `_start_ppt_generation(session_id)`：

```python
async def _start_ppt_generation(self, session_id: str):
    """统一 PPT 生成入口 — 所有路径汇聚于此"""
    session = session_manager.get(session_id)
    context = session.get('research_context', {})
    research_result = session.get('research_result', {})
    
    # 1. 确定数据来源（优先级：extraction_result > research_result > word文档）
    #    注意：session 持久化时 dataclass 会通过 _serialize_value() 序列化为 dict，
    #    因此从 session 读取的 extraction_result 是 dict 而非 ExtractionResult 对象，
    #    需要重建为 ExtractionResult 才能传给后续管线。
    extraction_dict = context.get('extraction_result')
    extraction = None
    if extraction_dict:
        extraction = self._rebuild_extraction(extraction_dict)
    if not extraction and research_result.get('report', {}).get('sections'):
        extraction = self._convert_research_to_extraction(research_result)
    if not extraction:
        doc_path = research_result.get('document_path', '')
        if doc_path and Path(doc_path).suffix == '.docx':
            from src.core.adjustment.ppt_input_adapter import PptInputAdapter
            extraction = PptInputAdapter().extract([doc_path])
    if not extraction:
        return {'error': 'No data available for PPT generation'}
    
    # 2. 提取需求（含 style_hint）
    style_hint = context.get('style_hint')
    extractor = PptRequirementExtractor()
    requirement = extractor.extract(extraction)
    requirement.style_hint = style_hint  # 覆盖用户偏好
    
    # 3. 调用 ppt_design_advisor
    from src.skills.ppt_design_advisor.advisor import PptDesignAdvisor
    advisor = PptDesignAdvisor(data_dir="src/skills/ppt_design_advisor/data")
    design_contexts = advisor.advise_deck(
        requirement.topic, requirement.page_count,
        style_hint=requirement.style_hint
    )
    
    # 4. 构建 slide_data + 注入 design_context
    builder = SlideDataBuilder()
    slide_data_list = builder.build_list(
        extraction.sections, add_cover=True, add_end=True,
        title=requirement.topic
    )
    for i, sd in enumerate(slide_data_list):
        if i < len(design_contexts):
            sd["design_context"] = asdict(design_contexts[i])
    
    # 5. 生成 PPTX
    editor = PptStructureEditor()
    output_path = str(Path("data/reports") / f"{session_id}.pptx")
    result = editor.edit(slide_data_list, pptx="dummy", output_path=output_path)
    
    # 6. 检查生成结果
    if not result or not result.success:
        return {'error': 'PPT generation failed', 'detail': str(result)}
    
    # 7. 更新 session + 状态机
    context['pptx_path'] = output_path
    session['research_context'] = context
    conv_machine = session.get('state_machine')
    if conv_machine and conv_machine.can_transition_to(ConversationState.PREVIEWING):
        conv_machine.transition(ConversationState.PREVIEWING)
    session['mode'] = 'chat'
    return {'status': 'completed', 'pptx_path': output_path}

def _rebuild_extraction(self, data: dict) -> ExtractionResult:
    """从序列化后的 dict 重建 ExtractionResult（session 持久化后 dataclass 变为 dict）"""
    from src.core.adjustment.extraction_types import ExtractionResult
    from src.content.content_orchestrator import ContentSection, SectionType
    sections = []
    for s in data.get('sections', []):
        try:
            st = SectionType(s.get('type', 'body'))
        except ValueError:
            st = SectionType.BODY
        sections.append(ContentSection(
            id=s.get('id', ''),
            title=s.get('title', ''),
            content=s.get('content', ''),
            order=s.get('order', 0),
            type=st,
            points=s.get('points', []),
            charts=s.get('charts'),
        ))
    return ExtractionResult(
        title=data.get('title', ''),
        sections=sections,
        tables=data.get('tables', []),
        key_topics=data.get('key_topics', []),
        metadata=data.get('metadata', {}),
    )

def _convert_research_to_extraction(self, research_result: dict) -> ExtractionResult:
    """将 research_result 的 sections 转换为 ExtractionResult（路径A/C）"""
    from src.core.adjustment.extraction_types import ExtractionResult
    from src.content.content_orchestrator import ContentSection, SectionType
    report = research_result.get('report', {})
    raw_sections = report.get('sections', [])
    sections = []
    for i, s in enumerate(raw_sections):
        if isinstance(s, ContentSection):
            sections.append(s)
        elif isinstance(s, dict):
            sections.append(ContentSection(
                id=s.get('id', f'section_{i}'),
                title=s.get('title', ''),
                content=s.get('content', ''),
                order=i,
                type=SectionType.BODY,
                points=s.get('points', []),
                charts=s.get('charts'),
            ))
    return ExtractionResult(
        title=report.get('title', ''),
        sections=sections,
        tables=[],
        key_topics=report.get('key_topics', []),
        metadata={'source': 'research_result'},
    )
```

### 3.4 Skill 加载方式

**当前 Skill 系统状态：** 迁移已完成。所有 21 个 Skill 均采用 `SKILL.md` + `skill.py` 自描述架构（含 5 个 LangChain 包装：lc_tavily_search, lc_arxiv, lc_wikipedia, lc_python_repl, llm），`register_core_skills()` 已废弃（始终返回 0）。Orchestrator 初始化时仅调用 `init_from_discovery(Path("src/skills"))`，由 `SkillDiscovery` 自动扫描所有子目录。

**ppt_design_advisor 采用相同架构：**

```
src/skills/ppt_design_advisor/
├── SKILL.md          # YAML front matter + 使用说明
├── skill.py          # 入口：导出 PptDesignAdvisorSkill 类
├── advisor.py        # 核心逻辑
├── types.py          # 数据类型
├── ...               # 其他模块
└── data/             # CSV 数据
```

**加载机制：**

1. **Orchestrator 初始化时**，`init_from_discovery(Path("src/skills"))` 扫描到 `ppt_design_advisor/SKILL.md`
2. `SkillDiscovery._parse_skill_md()` 解析 YAML front matter → `SkillManifest`
3. 发现 `skill.py` → `discovery.load_skill_class(manifest)` 找到 `PptDesignAdvisorSkill` 子类
4. `register_factory("ppt_design_advisor", PptDesignAdvisorSkill)` **懒加载**（首次 `get()` 时实例化）
5. 同时注册 aliases（如 `ppt_design`、`design_advisor`）→ 同样懒加载
6. `ManifestStrategyBuilder(skill_registry.all_manifests())` 注入到分解策略，使 GenericAgent 可通过 capability 发现此 skill

**调用方式（两种并存）：**

```python
# 方式1：直接 import（推荐，用于 _start_ppt_generation 内部）
from src.skills.ppt_design_advisor.advisor import PptDesignAdvisor
advisor = PptDesignAdvisor(data_dir="src/skills/ppt_design_advisor/data")
design_contexts = advisor.advise_deck(topic, count, style_hint)

# 方式2：通过 Skill Registry（用于 GenericAgent action 路由）
skill = registry.get("ppt_design_advisor")
result = await skill.execute(action="advise_deck", topic=topic, slide_count=count, style_hint=hint)
```

**为什么方式1更合适：** `_start_ppt_generation` 是同步管线内部调用，不需要 async 函数，直接 import 避免了 registry 查找开销和 async 包装层。方式2 保留给未来 GenericAgent 通过 `generate_pptx` action 触发的场景。

**关于 `pptx_skill`：** 当前 `GenericAgent._build_action_to_skill_map()` 中 `generate_pptx` 硬编码映射到 `"pptx_skill"`，但该 skill 尚未注册（`registry.get("pptx_skill")` 返回 None）。实现 Phase 6 时需创建 `src/skills/pptx/SKILL.md` + `skill.py`，或在 ppt_design_advisor 的 capabilities 中增加 `generate_pptx` 并更新 SKILL.md 的 `action_param_map`。

**GenericAgent action→skill 映射机制（当前实际逻辑）：**
1. 从所有 manifest 的 `capabilities` 反向构建映射：`capability → skill_name`
2. 硬编码覆盖（如 `generate_docx → docx_skill`）
3. 因此 ppt_design_advisor 的 SKILL.md 中声明的 `capabilities: [advise_deck, advise_slide, classify_product, recommend_chart]` 会自动注册为 action→skill 映射

**SKILL.md YAML front matter 设计：**

```yaml
---
name: ppt_design_advisor
description: "PPT设计决策引擎 — 产品主题识别、情绪弧线规划、语义色板、布局决策、图表推荐"
version: "1.0"
categories:
  - design
  - ppt-generation
  - report-enhancement
priority: structured_db
keywords:
  - PPT
  - 幻灯片
  - 演示
  - 配色
  - 色板
  - 布局
  - 图表推荐
  - 设计
  - style
  - design
  - color
  - layout
  - chart
aliases:
  - ppt_design
  - design_advisor
capabilities:
  - advise_deck
  - advise_slide
  - classify_product
  - recommend_chart
data_types:
  zh:
    - PPT设计
    - 配色方案
    - 布局推荐
    - 图表选择
data_source_keywords:
  - PPT
  - 演示
  - 幻灯片
  - 设计
  - 配色
action_rules:
  - pattern: ".*"
    aspect_keywords: [PPT, 演示, 幻灯片, 设计, 配色, layout, design]
    actions: [advise_deck]
action_param_map:
  advise_deck: {topic: topic, slide_count: slide_count, style_hint: style_hint}
  advise_slide: {product: product, goal: goal, emotion: emotion}
  classify_product: {topic: topic}
  recommend_chart: {data_type: data_type, category_count: category_count}
supports_topic_fallback: true
topic_fallback_pattern: "[\\u4e00-\\u9fff]+"
is_intrinsic: false
skill_type: standard
aspect_coverage:
  - PPT Design
  - PPT设计
  - Visual Design
  - 视觉设计
  - Data Visualization
  - 数据可视化
---
```

### 3.5 LLM action 触发机制

**新增 action 映射：**

```python
# research_api.py _resolve_transition()
if llm_action == 'generate_ppt':
    return ConversationState.PREVIEWING  # PPT生成完成可直接预览

# research_api.py _handle_chat_mode() 中新增分支
if llm_action == 'generate_ppt':
    # 先提取 style_hint（如果 LLM 一并返回了）
    if conv_result.get('style_hint'):
        context = session.get('research_context', {})
        context['style_hint'] = conv_result['style_hint']
        session['research_context'] = context
    return await self._start_ppt_generation(session_id)
```

**状态转换选择说明：** 
- 不能用 `EXECUTING`——它会触发 `research_executor`（研究执行器），而非 PPT 生成
- 不能从 `COMPLETED`（终态）转换到任何非终态
- `PREVIEWING` 合适：PPT 生成后用户可预览，且 `COMPLETED → PREVIEWING` 是有效转换
- `DATA_EXTRACTED → PREVIEWING` 不是有效转换，需在 `VALID_TRANSITIONS` 中添加 `DATA_EXTRACTED → PREVIEWING`
- 同理 `REQUIREMENT_CONFIRM → PREVIEWING` 也需添加

**需要新增的状态转换：**

```python
# state_machine.py VALID_TRANSITIONS 中新增
ConversationState.DATA_EXTRACTED: [
    ...,  # 已有
    ConversationState.PREVIEWING,       # 新增：直接生成PPT后预览
],
ConversationState.REQUIREMENT_CONFIRM: [
    ...,  # 已有
    ConversationState.PREVIEWING,       # 新增：确认需求后直接生成PPT预览
],
ConversationState.COMPLETED: [
    ConversationState.COMPLETED,
    ConversationState.PREVIEWING,       # 新增：研究完成后生成PPT预览
],
```

**LLM 对话引导（写入 `_build_dialogue_context`）：**

在 `COMPLETED` 状态的引导文本中追加：
```
- If user asks to generate PPT/幻灯片/演示文稿, use action="generate_ppt".
- If user specifies style preference (高级感/极简/奢华/活力 etc.), include style_hint field.
```

在 `DATA_EXTRACTED` 状态的引导文本中追加：
```
- If user wants to generate PPT directly from uploaded data, use action="generate_ppt".
- Ask about style preference if not specified.
```

### 3.6 关键技术细节

**1. 色板注入机制**

`SlideRenderer.__init__(self, design: Dict)` 接收一个颜色名→hex的映射字典，`_resolve_color()` 先查 `self.design` 再 fallback 到原始 hex 值。模板 JSON 中使用颜色名（如 `"color": "navy"`），经 `_resolve_color("navy")` → `self.design["navy"]` → `"1A2744"`。

**注入方式：** 当 `slide_data` 包含 `design_context.colors` 时，用语义色板覆盖 `self.design` 的对应键。例如新能源汽车主题：
```python
# 原 design
{"navy": "1A2744", "gold": "C9A227", ...}
# 覆盖后
{"navy": "1A56DB", "gold": "C9A227", ...}  # navy 换成信任蓝，gold 保留
```

**注意：** 仅覆盖模板渲染器路径（`USE_TEMPLATE_RENDERER=1`）。Fallback 渲染器直接引用 `self.DESIGN` 硬编码，不走 `self.design`，无法动态替换——但这不影响，因为生产环境始终使用模板渲染器。

**2. 模板选择注入点**

`TemplateSelector.select_and_enhance()` 在 `_select()` 之前执行，返回模板名。注入点在 `_select()` 开头加 2 行优先返回：
```python
def _select(self, slide_data, ...):
    dc = slide_data.get("design_context")
    if dc and dc.get("layout_template"):
        return dc["layout_template"]
    # ... 原有启发式逻辑
```

**3. 情绪弧线与 slide_structure 的对齐**

`advise_deck()` 返回的 `List[DesignContext]` 长度可能不等于 `slide_data_list` 长度（因为策略的 slide_structure 是固定的，而实际 slide_data 由内容决定）。处理方式：
- 若 `design_contexts` 更长：截断到 `len(slide_data_list)`
- 若 `design_contexts` 更短：不足的页用最后一个 DesignContext（通常都是 end 页）
- 在 `SlideDataBuilder.build_list_with_design()` 中处理此对齐逻辑

---

## 四、Skill 目录结构

```
src/skills/ppt_design_advisor/
├── SKILL.md                          # 自描述元数据（YAML front matter + 使用说明）
├── skill.py                          # 入口：导出 PptDesignAdvisorSkill 类
├── advisor.py                        # PptDesignAdvisor 核心逻辑（~350行）
├── types.py                          # DesignContext, SemanticColorPalette, TypographySpec
├── product_classifier.py             # 产品类型识别（jieba + CSV 关键词匹配，~80行）
├── emotion_arc.py                    # 情绪弧线规划（策略选择 + goal 序列，~100行）
├── layout_decider.py                 # 布局决策（goal+emotion→layout+typography+color，~120行）
├── chart_recommender.py              # 图表推荐（data_type→chart_type，~60行）
└── data/
    ├── ppt_product_styles.csv        # 30条：产品→风格+色板
    ├── ppt_style_presets.csv         # 8条：风格偏好覆盖（高级感/极简/奢华...）
    ├── ppt_slide_strategies.csv      # 10条：演示策略+情绪弧线
    ├── ppt_layout_logic.csv          # 15条：goal→布局+排版+色彩
    ├── ppt_chart_recommendations.csv # 15条：图表类型推荐
    └── ppt_reasoning_rules.csv       # 10条：推理决策规则
```

**总代码量：~710行 Python + 6个CSV（~88条数据）**

---

## 五、数据层设计（6 个自建 CSV）

### 5.1 `ppt_product_styles.csv` — 产品→风格+色板

**设计思想来源：** UI/UX Pro Max 的 products.csv + colors.csv（192条×18列），精简为 PPT 场景

| 列 | 说明 | 示例 | 映射到 DESIGN 键 |
|----|------|------|-----------------|
| `product_type` | 产品/行业类型 | "新能源汽车" | - |
| `keywords` | 匹配关键词(逗号分隔) | "新能源,电动车,BEV,NEV,充电" | - |
| `style_name` | 设计风格名 | "数据驱动专业" | - |
| `color_primary` | 主色 hex | "#1A56DB" | navy |
| `color_secondary` | 辅色 hex | "#0F172A" | navy_dark |
| `color_accent` | 强调色 hex | "#C9A227" | gold |
| `color_bg_light` | 浅背景 hex | "#FFFFFF" | white |
| `color_bg_dark` | 深背景 hex | "#F5F5F5" | off_white |
| `color_text` | 正文色 hex | "#1E293B" | text_dark |
| `color_text_muted` | 弱化色 hex | "#94A3B8" | text_mid |
| `color_success` | 正向色 hex | "#16A34A" | 新增键 |
| `color_danger` | 负向色 hex | "#DC2626" | 新增键 |
| `heading_font` | 标题字体 | "Microsoft YaHei" | - |
| `body_font` | 正文字体 | "Microsoft YaHei" | - |
| `density` | 信息密度 | "high" / "medium" / "low" | - |
| `anti_patterns` | 反模式 | "过度动画,卡通图标" | - |

**30条覆盖：** 新能源汽车, 半导体, AI/大模型, SaaS, 金融/银行, 医疗健康, 教育, 消费品, 房地产, 能源/电力, 制造业, 物流, 农业, 政府/公共, 电商, 游戏, 文娱, 旅游, 环保, 零售, 餐饮, 保险, 证券, 基金, 区块链, 航空航天, 国防, 电信, 钢铁/化工, 通用

### 5.1b `ppt_style_presets.csv` — 风格偏好覆盖

**解决用户问题：** "我想要互联网高级感"——产品类型决定基础色板，风格偏好在此基础上覆盖色板和排版。

| 列 | 说明 | 示例 |
|----|------|------|
| `preset_id` | 风格标识 | "premium_tech" |
| `preset_name` | 风格中文名 | "科技高级感" |
| `keywords` | 匹配关键词 | "高级感,科技,互联网,premium,high-end,精致" |
| `color_primary_override` | 主色覆盖(空=不覆盖) | "#6366F1" |
| `color_accent_override` | 强调色覆盖 | "#06B6D4" |
| `color_bg_override` | 背景色覆盖(空=不覆盖) | "#0F172A" |
| `color_text_override` | 文字色覆盖 | "#E2E8F0" |
| `bg_treatment_default` | 默认背景处理 | "gradient" |
| `density` | 信息密度 | "medium" |
| `typography_scale` | 排版缩放因子 | "1.1" |

**匹配优先级：** `style_hint` > `product_type`。用户说了"高级感"，即使产品是"新能源汽车"（默认信任蓝），色板也会被高级感预设覆盖为深色+科技紫+青色强调。

**~8条预设：** 科技高级感(premium_tech), 极简商务(minimal_corp), 奢华品牌(luxury_brand), 活力创新(vibrant_innovate), 学术严谨(academic_rigor), 政务稳重(gov_formal), 数据极客(data_geek), 自然清新(nature_fresh)

### 5.2 `ppt_slide_strategies.csv` — 演示策略+情绪弧线

**设计思想来源：** UI/UX Pro Max 的 slide-strategies.csv（15条），针对研究报告定制

| 列 | 说明 | 示例 |
|----|------|------|
| `strategy_id` | 策略标识 | "industry_report" |
| `strategy_name` | 策略名 | "行业深度研究报告" |
| `keywords` | 匹配关键词 | "行业,研究,深度,报告,产业" |
| `slide_structure` | 页面结构序列 | "cover,toc,overview,kpi,data,competition,tech,investment,end" |
| `emotion_arc` | 情绪序列 | "curiosity,interest,confidence,trust,evaluation,clarity,hope,urgency,warmth" |
| `audience` | 目标受众 | "投资机构,企业战略部" |
| `tone` | 语调 | "专业,数据驱动,客观" |

**10条覆盖：** 行业深度研究报告, 融资BP, 季度经营复盘, 竞争分析简报, 产品发布, 技术白皮书, 投资尽调, 政策解读, 市场快报, 通用

### 5.3 `ppt_layout_logic.csv` — goal→布局+排版+色彩决策

**设计思想来源：** UI/UX Pro Max 的 slide-layout-logic.csv + slide-typography.csv + slide-color-logic.csv 三表合一

| 列 | 说明 | 示例 |
|----|------|------|
| `goal` | 页面目标 | "overview" |
| `emotion` | 情绪 | "curiosity" |
| `layout_template` | 对应模板名 | "content_left_right" |
| `visual_weight` | 视觉权重 | "balanced" |
| `title_size_pt` | 标题字号 | 32 |
| `body_size_pt` | 正文字号 | 14 |
| `accent_size_pt` | 辅助字号 | 11 |
| `bg_treatment` | 背景处理 | "solid" / "gradient" / "full_bleed" |
| `accent_usage` | 强调色用法 | "kpi_cards" / "title_underline" / "side_bar" |
| `break_pattern` | 是否打破节奏 | "false" |

**15条覆盖：** overview, kpi, data_analysis, comparison, competition, technology, investment, risk, conclusion, cta, timeline, quote, feature_grid, section_divider, end

### 5.4 `ppt_chart_recommendations.csv` — 图表推荐

**设计思想来源：** UI/UX Pro Max 的 slide-charts.csv（25条），精简为 PPT 实用场景

| 列 | 说明 | 示例 |
|----|------|------|
| `data_type` | 数据结构类型 | "time_series" |
| `recommended_chart` | 推荐图表 | "line_chart" |
| `alt_chart` | 备选图表 | "area_chart" |
| `best_for` | 最佳场景 | "趋势变化,时间序列" |
| `max_categories` | 最大分类数 | 12 |
| `ppt_implementation` | PPT实现 | "python-pptx XL_CHART_TYPE.LINE" |

**15条覆盖：** time_series, categorical_comparison, composition, kpi_progress, ranking, correlation, funnel, distribution, multi_series, proportion, trend_with_range, geographic, flow, comparison_over_time, single_value

### 5.5 `ppt_reasoning_rules.csv` — 推理决策规则

**设计思想来源：** UI/UX Pro Max 的 ui-reasoning.csv（161条），精简为 PPT 场景

| 列 | 说明 | 示例 |
|----|------|------|
| `product_category` | 产品类别 | "数据密集型" |
| `style_priority` | 风格优先级 | "数据驱动 > 极简 > 专业" |
| `color_mood` | 色彩情绪 | "信任蓝 + 数据强调" |
| `key_effects` | 关键效果 | "KPI卡片, 渐变标题, 表格+图表双栏" |
| `anti_patterns` | 反模式 | "过度动画, 卡通风格, 霓虹色" |
| `decision_rules` | 条件决策(JSON) | '{"if_data_heavy":"use_table_chart_split"}' |

**10条覆盖：** 数据密集型, 品牌展示型, 说服转化型, 教育解释型, 技术前瞻型, 政策合规型, 竞争分析型, 投资决策型, 运营复盘型, 通用型

---

## 六、核心类设计

### 6.1 `types.py` — 数据类型

```python
# DESIGN 键名 → 语义色板字段的映射
# 模板 JSON 使用 "navy"/"gold" 等键名，SlideRenderer._resolve_color() 从 self.design 查找
# 色板注入时，用 CSV 的 hex 值覆盖对应键名
COLOR_KEY_MAP = {
    "navy":       "color_primary",     # 主色
    "navy_dark":  "color_secondary",   # 辅色
    "navy_light": "color_secondary",   # 辅色变体（梯度用）
    "gold":       "color_accent",      # 强调色
    "gold_light": "color_accent",      # 强调色变体
    "white":      "color_bg_light",    # 浅背景
    "off_white":  "color_bg_dark",     # 深背景
    "text_dark":  "color_text",        # 正文色
    "text_mid":   "color_text_muted",  # 弱化色
    "text_light": "color_text_muted",  # 弱化色变体
}

@dataclass
class SemanticColorPalette:
    color_primary: str      # "#1A56DB"  → 映射到 navy
    color_secondary: str    # "#0F172A"  → 映射到 navy_dark/navy_light
    color_accent: str       # "#C9A227"  → 映射到 gold/gold_light
    color_bg_light: str     # "#FFFFFF"  → 映射到 white
    color_bg_dark: str      # "#F5F5F5"  → 映射到 off_white
    color_text: str         # "#1E293B"  → 映射到 text_dark
    color_text_muted: str   # "#94A3B8"  → 映射到 text_mid/text_light
    color_success: str      # "#16A34A"  → 新增键
    color_danger: str       # "#DC2626"  → 新增键

    def to_design_dict(self) -> Dict[str, str]:
        """转换为 SlideRenderer.design 格式（颜色名→hex值）"""
        d = {}
        for design_key, palette_field in COLOR_KEY_MAP.items():
            d[design_key] = getattr(self, palette_field).lstrip("#")
        d["success"] = self.color_success.lstrip("#")
        d["danger"] = self.color_danger.lstrip("#")
        return d

@dataclass
class TypographySpec:
    heading_font: str   # "Microsoft YaHei"
    body_font: str      # "Microsoft YaHei"
    title_size: int     # 32
    body_size: int      # 14
    accent_size: int    # 11

@dataclass
class DesignContext:
    """每页的设计决策 — skill 的核心输出"""
    product_type: str
    style_name: str
    colors: SemanticColorPalette
    typography: TypographySpec
    layout_template: str
    bg_treatment: str
    accent_usage: str
    emotion: str
    break_pattern: bool
    chart_recommendation: Optional[str] = None
```

### 6.2 `advisor.py` — PptDesignAdvisor

**注意：** `PptDesignAdvisor` 是纯同步类（只读 CSV + 关键词匹配，无 I/O、无 LLM 调用），可在线程中直接调用。`skill.py` 的 `execute()` 是 async（满足 Skill ABC 接口），内部同步调用 advisor。

```python
class PptDesignAdvisor:
    def __init__(self, data_dir: str):
        self._product_classifier = ProductClassifier(data_dir)
        self._emotion_arc = EmotionArcPlanner(data_dir)
        self._layout_decider = LayoutDecider(data_dir)
        self._chart_recommender = ChartRecommender(data_dir)
        self._style_presets = self._load_style_presets(data_dir)

    def advise_deck(self, topic: str, slide_count: int,
                    style_hint: Optional[str] = None) -> List[DesignContext]:
        """为整份报告生成设计决策序列

        Args:
            topic: 报告主题，如"新能源汽车产业深度研究"
            slide_count: 预期页数
            style_hint: 风格偏好，如"高级感"/"极简"/"luxury"/"premium_tech"
                         支持中英文关键词，匹配 ppt_style_presets.csv
        """
        product = self._product_classifier.classify(topic)
        strategy = self._emotion_arc.select_strategy(topic, slide_count)

        # 风格偏好覆盖：style_hint > product_type
        style_preset = None
        if style_hint:
            style_preset = self._match_style_preset(style_hint)

        contexts = []
        for i, (goal, emotion) in enumerate(zip(strategy.goals, strategy.emotions)):
            ctx = self._layout_decider.resolve(product, goal, emotion, i, len(strategy.goals), contexts)
            # 应用风格偏好覆盖
            if style_preset:
                ctx = self._apply_style_preset(ctx, style_preset)
            contexts.append(ctx)
        return contexts

    def advise_slide(self, product: str, goal: str, emotion: str,
                     position: int, total: int,
                     previous: Optional[DesignContext] = None) -> DesignContext:
        """为单页生成设计决策"""
        return self._layout_decider.resolve(product, goal, emotion, position, total, [previous] if previous else [])

    def classify_product(self, topic: str) -> str:
        return self._product_classifier.classify(topic)

    def recommend_chart(self, data_type: str, category_count: int = 0) -> str:
        return self._chart_recommender.recommend(data_type, category_count)
```

### 6.3 `skill.py` — Skill 入口

```python
class PptDesignAdvisorSkill(Skill):
    @property
    def name(self) -> str:
        return "ppt_design_advisor"

    @property
    def description(self) -> str:
        return "PPT设计决策引擎 — 产品主题、情绪弧线、语义色板、布局决策、图表推荐"

    def __init__(self, config=None):
        super().__init__(config)
        # skill.py 被 load_skill_class() 加载时，manifest.skill_dir 尚未传入
        # 使用相对于 skill.py 的固定路径
        from pathlib import Path
        self._data_dir = str(Path(__file__).parent / "data")

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "advise_deck")
        advisor = PptDesignAdvisor(data_dir=self._data_dir)

        if action == "advise_deck":
            contexts = advisor.advise_deck(
                kwargs["topic"],
                kwargs.get("slide_count", 10),
                style_hint=kwargs.get("style_hint"),
            )
            return self._success({"design_contexts": [asdict(c) for c in contexts]})

        elif action == "advise_slide":
            ctx = advisor.advise_slide(kwargs["product"], kwargs["goal"],
                                       kwargs.get("emotion", "clarity"),
                                       kwargs.get("position", 0),
                                       kwargs.get("total", 10))
            return self._success({"design_context": asdict(ctx)})

        elif action == "classify_product":
            product = advisor.classify_product(kwargs["topic"])
            return self._success({"product_type": product})

        elif action == "recommend_chart":
            chart = advisor.recommend_chart(kwargs["data_type"], kwargs.get("category_count", 0))
            return self._success({"chart_type": chart})

        return self._failure(f"Unknown action: {action}")
```

---

## 七、调用方式

### 7.1 报告 Agent 调用（推荐）

```python
from src.skills.ppt_design_advisor.advisor import PptDesignAdvisor

advisor = PptDesignAdvisor(data_dir="src/skills/ppt_design_advisor/data")

# 方式1：自动识别产品类型，用默认色板
design_contexts = advisor.advise_deck("新能源汽车产业深度研究", slide_count=9)

# 方式2：用户指定风格偏好 — "互联网高级感"
design_contexts = advisor.advise_deck("新能源汽车产业深度研究", slide_count=9,
                                      style_hint="高级感")

# 方式3：用户直接指定预设ID
design_contexts = advisor.advise_deck("新能源汽车产业深度研究", slide_count=9,
                                      style_hint="premium_tech")

# 注入到 slide_data
for i, sd in enumerate(slide_data_list):
    if i < len(design_contexts):
        sd["design_context"] = asdict(design_contexts[i])
```

### 7.2 通过 Skill Registry 调用

```python
skill = registry.get("ppt_design_advisor")

# 自动识别
result = await skill.execute(action="advise_deck", topic="新能源汽车", slide_count=9)

# 指定风格偏好
result = await skill.execute(action="advise_deck", topic="新能源汽车", slide_count=9,
                              style_hint="高级感")
design_contexts = result["design_contexts"]
```

### 7.3 现有管线的最小适配（共 ~5 行）

**TemplateSelector.select_and_enhance()** — 加 2 行：
```python
dc = slide_data.get("design_context")
if dc and dc.get("layout_template"):
    return dc["layout_template"]
```

**SlideRenderer 色板覆盖** — 在 `html_to_ppt.py` 的模板渲染器路径中：
```python
# 当前代码 (line 610):
renderer = SlideRenderer(self.DESIGN, image_provider=image_provider)

# 改为：检查第一页的 design_context，构建覆盖色板
design = dict(self.DESIGN)
if slides and slides[0].get("design_context", {}).get("colors"):
    colors = slides[0]["design_context"]["colors"]
    for design_key, palette_field in COLOR_KEY_MAP.items():
        if palette_field in colors:
            design[design_key] = colors[palette_field].lstrip("#")
renderer = SlideRenderer(design, image_provider=image_provider)
```

这两处改动是**可选注入**，design_context 不存在时走原逻辑，零影响。

> **安全保证：不调用 skill = 零差异。** `slide_data` 没有 `design_context` 字段 → 所有 `if dc:` 分支跳过 → 完全走现有代码路径，一行不变。不存在"不调用就走样"的可能。

**为什么模板 JSON 不用改？** 现有 12 个模板 JSON 使用颜色名而非 hex 值（如 `"color": "navy"` 而非 `"color": "1A2744"`）。`SlideRenderer._resolve_color("navy")` 从 `self.design` 字典查 hex 值。我们只需替换 `self.design` 字典的值，模板无需任何修改。

---

## 八、用户风格偏好机制

### 8.0 用户介入点设计

**问题：** spec 定义了 `style_hint` 参数，但未设计用户如何表达风格偏好——API 无参数、对话无引导、session 无存储。

**最佳介入点 = `REQUIREMENT_CONFIRM` 状态**，理由：
- 用户刚回答了"想做什么"（PPT/报告/分析），意图明确
- LLM 此时可以自然追问风格偏好
- 还没进入框架确认/执行，修改成本为零
- 与现有对话流程无缝衔接

**用户交互流程：**

```
用户上传文件 → DATA_EXTRACTED
  ↓
LLM: "已读取3个文件《新能源汽车报告》，共5章节/2表。您想基于这份材料做什么？"
用户: "生成PPT"
  ↓
REQUIREMENT_CONFIRM
  ↓
LLM: "好的，将为您生成PPT。您偏好什么风格？可选：科技高级感/极简商务/奢华品牌/活力创新/学术严谨/政务稳重/数据极客/自然清新，或直接说'默认'。"
用户: "高级感"  ← style_hint 介入点
  ↓
style_hint="premium_tech" 存入 session context
  ↓
FRAMEWORK_CONFIRM → EXECUTING → 调用 ppt_design_advisor.advise_deck(topic, count, style_hint="premium_tech")
```

**用户也可以跳过：** 回答"默认"/"都行"/直接说"开始" → `style_hint=None` → 纯产品类型自动匹配。

**3 处改动：**

| 改动 | 位置 | 内容 |
|------|------|------|
| **1. 对话引导** | `research_api.py` `_build_dialogue_context()` | 给 `REQUIREMENT_CONFIRM` 和 `DATA_EXTRACTED` 状态加引导文本：询问风格偏好，用户确认后用 action `generate_ppt` |
| **2. LLM action** | `research_api.py` `_resolve_transition()` | 新增 `generate_ppt` action → `ConversationState.PREVIEWING`（含 style_hint 提取） |
| **3. API 参数** | `research_api.py` `start_research()` | 可选参数 `style_hint`，直接存入 session context（适用于前端直接传风格偏好，跳过对话询问） |

**注意：** 不再使用单独的 `confirm_style` action。风格偏好通过 `generate_ppt` action 的 `style_hint` 字段一并发送，简化流程。用户说 "生成PPT，科技高级感" → LLM 返回 `action="generate_ppt", style_hint="premium_tech"` → 一步到位。

**对话引导文本（写入 `_build_dialogue_context` 的 `state_guidance` 字典）：**

```python
ConversationState.REQUIREMENT_CONFIRM: (
    '## Current Dialogue Phase: PPT Requirement Confirmation\n'
    'The user wants to generate a PPT from their uploaded data.\n'
    '- Ask about style preference: offer 8 presets (科技高级感/极简商务/奢华品牌/活力创新/学术严谨/政务稳重/数据极客/自然清新).\n'
    '- If user specifies a style, use action="generate_ppt" with style_hint field.\n'
    '- If user says "默认"/"都行"/skips, use action="generate_ppt" with style_hint=null.\n'
    '- Do NOT use confirm_requirements or enter_framework for PPT generation.\n'
)
```

**`_resolve_transition` 新增：**

```python
if llm_action == 'generate_ppt':
    return ConversationState.PREVIEWING
```

**`_handle_chat_mode` 中处理 generate_ppt：**

```python
if llm_action == 'generate_ppt':
    # 提取 style_hint（LLM 可能在同一回复中指定风格偏好）
    style_hint = conv_result.get('style_hint')
    if style_hint:
        context = session.get('research_context', {})
        context['style_hint'] = style_hint
        session['research_context'] = context
    return await self._start_ppt_generation(session_id)
```

**`PptRequirement` 扩展：**

```python
@dataclass
class PptRequirement:
    topic: str
    audience: str = "business_professional"
    focus: List[str] = field(default_factory=list)
    page_count: Optional[int] = None
    style: str = "professional"
    style_hint: Optional[str] = None   # 新增：用户风格偏好，如"高级感"/"premium_tech"
    confirmed: bool = False
```

**style_hint 传递链：**

```
用户输入 → LLM提取style_hint → session['research_context']['style_hint']
  → PptRequirementExtractor.extract() 写入 PptRequirement.style_hint
  → ppt_design_advisor.advise_deck(topic, count, style_hint=requirement.style_hint)
  → DesignContext 注入 slide_data
```

### 8.1 三层决策优先级

```
用户 style_hint（最高） → 风格预设覆盖色板
产品 product_type（其次） → 基础色板
默认（兜底）             → 现有 navy/gold 硬编码
```

**用户说"高级感"时：** 即使主题是"新能源汽车"（默认信任蓝），风格预设 `premium_tech` 会覆盖为深色背景+科技紫+青色强调。

**用户不说风格偏好时：** 纯靠产品类型自动匹配，走默认色板。

### 8.2 style_hint 支持的输入

| 输入方式 | 示例 | 匹配逻辑 |
|---------|------|---------|
| 中文关键词 | "高级感"、"极简"、"奢华"、"活力" | jieba分词 + ppt_style_presets.csv keywords 匹配 |
| 英文关键词 | "premium"、"minimal"、"luxury"、"vibrant" | 同上 |
| 预设ID | "premium_tech"、"minimal_corp" | 精确匹配 preset_id |
| 空值 | None / "" | 不覆盖，用产品默认色板 |

### 8.3 风格预设覆盖逻辑

```python
def _apply_style_preset(self, ctx: DesignContext, preset: dict) -> DesignContext:
    """风格预设覆盖 DesignContext 的色板和排版"""
    colors = ctx.colors
    if preset.get("color_primary_override"):
        colors = dataclasses.replace(colors, color_primary=preset["color_primary_override"])
    if preset.get("color_accent_override"):
        colors = dataclasses.replace(colors, color_accent=preset["color_accent_override"])
    if preset.get("color_bg_override"):
        colors = dataclasses.replace(colors, color_bg_light=preset["color_bg_override"])
    if preset.get("color_text_override"):
        colors = dataclasses.replace(colors, color_text=preset["color_text_override"])
    return dataclasses.replace(ctx, colors=colors, style_name=preset["preset_name"])
```

### 8.4 8个风格预设效果预览

| 预设 | 色板特征 | 适用场景 |
|------|---------|---------|
| 科技高级感 premium_tech | 深色背景#0F172A + 科技紫#6366F1 + 青色强调#06B6D4 | 互联网/AI/SaaS |
| 极简商务 minimal_corp | 白底#FFFFFF + 深灰文字#1E293B + 蓝强调#2563EB | 咨询/法律/审计 |
| 奢华品牌 luxury_brand | 深色#1C1917 + 金色#D4AF37 + 米白文字#FAFAF9 | 奢侈品/地产/金融 |
| 活力创新 vibrant_innovate | 亮白底 + 活力橙#EA580C + 翠绿#059669 | 消费品/电商/教育 |
| 学术严谨 academic_rigor | 浅灰底#F8FAFC + 深蓝#1E40AF + 黑文字#0F172A | 论文/白皮书/学术 |
| 政务稳重 gov_formal | 红色#DC2626 + 深蓝#1E3A5F + 金点缀#B8860B | 政府/国企/公共 |
| 数据极客 data_geek | 暗色#111827 + 绿数据#22C55E + 红警示#EF4444 | 金融终端/量化/监控 |
| 自然清新 nature_fresh | 浅绿底#F0FDF4 + 森林绿#15803D + 棕点缀#92400E | 环保/农业/健康 |

---

## 九、与 UI/UX Pro Max 的重合度

| 维度 | UI/UX Pro Max | 本 Skill | 重合度 |
|------|---------------|----------|--------|
| CSV 数据 | 15个CSV, 5100+条, 18+列 | 6个CSV, ~88条, 7-15列 | **低** — 数据量1.7%，列结构重设计 |
| 搜索引擎 | BM25 (core.py 274行) | jieba分词+关键词匹配 | **零** — 完全不同实现 |
| 设计系统生成 | design_system.py 1329行 | advisor.py ~300行 | **低** — 功能子集，逻辑自研 |
| 幻灯片生成 | generate-slide.py 770行(HTML) | 不使用 | **零** |
| 上下文决策 | slide_search_core.py 453行 | layout_decider.py ~120行 | **低** — 思想借鉴，代码自研 |
| 推理规则 | ui-reasoning.csv 161条 | ppt_reasoning_rules.csv 10条 | **低** |
| 模板/平台配置 | 18平台JSON | 不使用 | **零** |
| 持久化 | Master+Overrides | 不使用 | **零** |

**综合重合度 < 10%**

---

## 十、实施计划

| 阶段 | 任务 | 产出 | 天数 |
|------|------|------|------|
| **Phase 1** | 创建 6 个 CSV + types.py + SKILL.md | 数据层+类型定义 | 1 |
| **Phase 2** | ProductClassifier + StylePresetMatcher | 产品识别+风格偏好匹配 | 1.5 |
| **Phase 3** | EmotionArcPlanner + LayoutDecider | 情绪弧线+布局决策 | 1.5 |
| **Phase 4** | ChartRecommender + PptDesignAdvisor + skill.py | 图表推荐+核心引擎+Skill入口 | 1.5 |
| **Phase 5** | 单元测试(35+) + 集成验证 | 测试覆盖 | 1.5 |
| **Phase 6** | 多路径触发：`_start_ppt_generation()` + LLM action `generate_ppt` + 对话引导 + PptRequirement扩展 + style_hint传递链 | 3条触发路径打通 | 1 |
| **Phase 7** | TemplateSelector/SlideRenderer 最小适配 | 管线接入(~5行) | 0.5 |
| **Phase 8** | 生成3种行业PPT × 2种风格偏好对比验证 | 视觉验证 | 1 |
| | | **合计** | **9.5天** |

---

## 十一、预期效果

| 指标 | 当前 | 集成后 |
|------|------|--------|
| 色板 | 1种固定(navy/gold) | 30种产品主题自适应 |
| 布局决策 | 启发式(~60%准确) | 情绪弧线驱动(~90%) |
| 图表推荐 | LLM猜测(慢/不稳定) | CSV查表(快/确定) |
| 视觉多样性 | 所有报告同风格 | 产品类型自适应 |
| 升级维护 | 改一处动全身 | skill独立迭代 |

**示例效果（无风格偏好，纯产品识别）：**
- 新能源汽车报告 → 信任蓝+数据密集风格，KPI卡片+表格图表双栏
- AI行业报告 → 科技紫+前瞻风格，渐变背景+全出血图
- 融资BP → 专业深色+转化风格，CTA强调+情绪弧线
- 教育/培训 → 温暖色+清晰风格，大字号+步骤化布局

**示例效果（用户指定风格偏好）：**
- 新能源汽车 + "高级感" → 深色背景+科技紫#6366F1+青色强调（覆盖默认信任蓝）
- 金融报告 + "极简" → 白底+深灰文字+蓝强调（覆盖默认深色终端风）
- 消费品 + "奢华" → 深色#1C1917+金色#D4AF37+米白文字

---

## 十二、风险与缓解

| 风险 | 缓解 |
|------|------|
| CSV数据不足，色板/布局不准 | 先用30条核心产品验证，逐步扩展 |
| 情绪弧线与内容不匹配 | DesignContext可选注入，缺失走原逻辑 |
| jieba对英文主题不准 | 中英文双语关键词匹配 |
| skill加载失败 | 不影响主系统，fallback到原硬编码色板 |
| UI/UX Pro Max 升级后数据过时 | 本skill数据自建，独立演进，不依赖对方 |
| 色板覆盖仅对模板渲染器生效 | fallback渲染器(`USE_TEMPLATE_RENDERER=0`)直接引用`self.DESIGN`硬编码，无法动态替换；但生产环境始终`USE_TEMPLATE_RENDERER=1`，不影响 |
| 用户跳过风格询问直接开始 | `style_hint=None` → 纯产品类型自动匹配，无差异 |
| LLM未正确提取style_hint | `generate_ppt` action 的 style_hint 字段为空时仍正常生成PPT（纯产品类型自动匹配） |
| 状态转换不合法（DATA_EXTRACTED/REQUIREMENT_CONFIRM/COMPLETED → PREVIEWING） | 需在 state_machine.py VALID_TRANSITIONS 中新增3条转换规则 |
| 路径A研究数据格式与PPT管线不兼容 | `_convert_research_to_extraction()` 做格式转换，同时处理 dict 和 ContentSection 对象 |
| 路径C Word文档提取失败 | 优先用 research_result 内存数据，Word 提取仅作 fallback |
| 多路径触发导致重复生成 | session 中加 `pptx_path` 标记，已生成则提示用户而非重新生成 |
| Skill系统迁移已完成 | ppt_design_advisor 采用与现有 16 个 Skill 相同的 SKILL.md + skill.py 架构，`register_core_skills()` 已废弃，全部走 `init_from_discovery()` |
