# 三级框架升级设计文档

> 日期：2026-07-06
> 状态：设计评审
> 范围：模板系统 (template module) 全链路升级

---

## 1. 问题定义

### 1.1 现状：一级扁平框架

当前模板系统的数据模型是**一级扁平列表**：

```
sections:
  - id: market_size        ← 只有 Level 1
    name: 市场规模与增长
  - id: competitive_landscape
    name: 竞争格局
```

这个扁平结构贯穿了整条数据管道：

| 层 | 文件 | 数据结构 | 问题 |
|---|---|---|---|
| ① 模板定义 | `config/templates/*.yaml` | `sections[]` 无嵌套 | 无法预定义子结构 |
| ② 模板加载 | `src/config/report_template.py` | `sections: Dict[str, Any]`（实际从 YAML 加载为 list） | 不识别 sub_sections，无类型化解析 |
| ③ Schema 校验 | `config/templates/template_schema.yaml` | `section_schema` 无子级定义 | 校验不覆盖嵌套 |
| ④ 框架配置 | `config/research_frameworks.yaml` | `section_weights` 扁平 key | 权重只到一级 |
| ⑤ 任务分解 | `src/core/decomposition/strategies.py` | `aspects: List[str]` 扁平 | 一个 aspect 对应一个 Agent，粒度过粗 |
| ⑥ 结果聚合 | `src/core/orchestrator/aggregation/result_aggregator.py` | 按 section_id 匹配内容 | 子结构靠 `_parse_markdown_subsections()` 从输出中启发式提取，不可靠 |
| ⑦ 报告生成 | `src/agents/fixed_agents/report_generation_agent.py` | `_integrate_body()` 只输出 `## i. Title` | 无子标题层次 |
| ⑧ 目录生成 | 同上 `_generate_toc()` | 只有 `1. [Title]` | 无子目录 |

### 1.2 运行时的"伪二级"：sections_tree

系统中存在一个**由 LLM 在对话中即兴生成的二级框架** `sections_tree`：

```python
# research_api.py:1397
sections_tree: [
  {name: "竞争格局", sub_sections: [
    {name: "市场集中度", points: ["CR4/HHI指标", "头部企业份额"]},
    {name: "竞争壁垒",  points: ["技术壁垒", "资金壁垒"]},
  ]}
]
```

**问题**：

| 编号 | 问题 | 严重度 | 说明 |
|---|---|---|---|
| P1 | YAML 模板无 sub_sections | 高 | 每次靠 LLM 即兴生成，质量不可控，且不同 session 对同一模板生成不同结构 |
| P2 | sub_sections 只影响搜索和部分分析提示 | 高 | `strategies.py:574` 将 sub_aspects 传入 data_collection prompt，`strategies.py:660` 传入 analysis prompt，但 report 阶段完全忽略，analysis 的结构约束也较弱 |
| P3 | 报告组装丢弃子结构 | 致命 | `report_generation_agent.py:521` 只输出 `## {i}. {title}`，2000-3000 字无段落划分 |
| P4 | 目录无层次 | 高 | `_generate_toc()` 只有一级目录 |
| P5 | points (第三级) 仅作 data_needs | 高 | 只传给搜索策略，分析和报告阶段完全忽略 |
| P6 | sections_tree 对齐脆弱 | 中 | `_align_section_data_specs_with_tree()` 仅做名称匹配，容易错位 |

### 1.3 质量滑坡链

```
YAML 模板扁平定义
  → LLM 即兴生成 sections_tree (P1, 不稳定)
    → 搜索提示虽有子维度，但无结构约束 (P2)
      → Agent 输出自由散漫，子维度覆盖不完整
        → 报告组装丢弃子结构 (P3, 致命)
          → 输出 3000 字大段文字，无层次 (P4, P5)
            → 研究质量大幅下滑
```

### 1.4 已存在的"线索"：模板和渲染层已支持三级

**关键发现**：以下两层已经具备三级支持能力，但从未被喂入三级数据：

1. **HTML 模板** (`config/document_templates/word_default.html`，TOC: L394-412, 正文: L420-484):
   ```html
   <!-- TOC 部分 -->
   {% for section in sections %}
     <a href="#{{ section.id }}">{{ section.title }}</a>
     {% if section.subsections %}
       {% for subsection in section.subsections %}
         <a href="#{{ subsection.id }}">{{ subsection.index }} {{ subsection.title }}</a>
         {% if subsection.points %}
           {% for pt in subsection.points %}
             {{ subsection.index }}.{{ loop.index }} {{ pt }}
           {% endfor %}
         {% endif %}
       {% endfor %}
     {% endif %}
   {% endfor %}
   
   <!-- 正文部分 -->
   {% for section in sections %}
     <h1 class="chapter-title">{{ section.title }}</h1>
     {% if section.subsections %}
       {% for subsection in section.subsections %}
         <h3 class="subsection-title">{{ subsection.title }}</h3>
         {% if subsection.points %}
           {% for pt_sec in subsection.point_sections %}
             <h4 class="sub-subsection-title">{{ pt_sec.index }} {{ pt_sec.title }}</h4>
           {% endfor %}
         {% endif %}
       {% endfor %}
     {% endif %}
   {% endfor %}
   ```

2. **ContentOrchestrator** (`content_orchestrator.py:349-370`):
   ```python
   if section.subsections:
       for j, subsec in enumerate(section.subsections):
           subsec_dict = {
               "id": subsec.id, "title": subsec.title,
               "index": f"{i+1}.{j+1}",
               "points": subsec.points or [],
           }
           if subsec.points:
               subsec_dict["point_sections"] = [
                   {"title": pt, "content": ..., "index": f"{i+1}.{j+1}.{k+1}"}
                   for k, pt in enumerate(subsec.points)
               ]
   ```

3. **ContentOrchestrator._render_section_html** (`content_orchestrator.py:965-989`):
   ```python
   def _render_section_html(self, section: ContentSection) -> str:
       parts.append(f'<h2 class="section-title">{html.escape(section.title)}</h2>')
       if section.subsections:
           for subsec in section.subsections:
               parts.append(f'<h3 class="subsection-title">{html.escape(subsec.title)}</h3>')
               if subsec.points:
                   for pt in subsec.points:
                       parts.append(f'<h4 class="sub-subsection-title">{html.escape(pt)}</h4>')
   ```

4. **ContentOrchestrator._generate_word_html TOC** (`content_orchestrator.py:818-826`):
   ```python
   for i, section in enumerate(sections, 1):
       html_parts.append(f'<p class="toc-item">{i}. {html.escape(section.title)}</p>')
       if section.subsections:
           for j, subsec in enumerate(section.subsections, 1):
               html_parts.append(f'<p class="toc-item" style="margin-left: 20px;">{i}.{j} {html.escape(subsec.title)}</p>')
               if subsec.points:
                   for k, pt in enumerate(subsec.points, 1):
                       html_parts.append(f'<p class="toc-item" style="margin-left: 40px;">{i}.{j}.{k} {html.escape(pt)}</p>')
   ```

5. **DocumentGenerationAgent** (`document_generation_agent.py:632-644`):
   ```python
   subsections = section.get("subsections", [])
   for subsection in subsections:
       sub_title = subsection.get("title", "")
       sub_content = subsection.get("content", "")
       sub_points = subsection.get("points", []) or []
       if sub_title:
           generator.add_heading(sub_title, level=2)
       if sub_points:
           for pt in sub_points:
               generator.add_heading(pt, level=3)
   ```

6. **ContentSection** dataclass (`content_orchestrator.py:68-88`):
   ```python
   @dataclass
   class ContentSection:
       id: str
       title: str
       content: str
       order: int = 0
       type: SectionType = SectionType.BODY
       subsections: Optional[List["ContentSection"]] = None
       charts: Optional[List[Dict[str, Any]]] = None
       points: Optional[List[str]] = None
   ```

**⚠️ 关键命名不一致**：模板/对话层使用 `sub_sections`（带下划线），渲染层使用 `subsections`（无下划线）：
- `research_api.py:1866` / `orchestrator.py:3831` / `strategies.py:890` → `sub_sections`
- `content_orchestrator.py:350,769,820` / `result_aggregator.py:671` / `document_generation_agent.py:633` → `subsections`

**结论**：渲染层已经就绪（5处已实现三级渲染 + 1个支持嵌套的 ContentSection 数据类），瓶颈在于**数据源（YAML模板）和数据管道（分解/聚合）没有产生三级结构化数据**。加载层需要在读取 YAML `sub_sections` 后，输出为渲染层期望的 `subsections` 格式。

---

## 2. 目标架构

### 2.1 三级框架定义

```
Level 1: 章节 (Chapter)     → 对应一个 Agent（分析维度）
Level 2: 子章节 (Sub-section) → 对应 Agent 内的分析子维度
Level 3: 要点 (Point)         → 对应数据采集/分析的精确目标
```

示例：

```
1. 竞争格局                              ← Level 1 (chapter)
   1.1 市场集中度                          ← Level 2 (sub-section)
       1.1.1 CR4/CR8/CR10 集中度指标       ← Level 3 (point)
       1.1.2 头部企业市场份额变化趋势
   1.2 竞争壁垒分析
       1.2.1 技术壁垒与专利护城河
       1.2.2 资金壁垒与规模效应
       1.2.3 政策准入壁垒
   1.3 波特五力分析
       1.3.1 供应商议价能力
       1.3.2 买方议价能力
       1.3.3 替代品威胁
```

### 2.2 目标数据模型

YAML 模板中：

```yaml
sections:
  - id: competitive_landscape
    name:
      zh: 竞争格局
      en: Competitive Landscape
    required: true
    description:
      zh: 市场集中度、竞争壁垒、波特五力
      en: Market concentration, barriers, Porter's Five Forces
    sub_sections:                           # ← 新增
      - id: market_concentration
        name:
          zh: 市场集中度
          en: Market Concentration
        points:                             # ← 新增
          - zh: CR4/CR8/CR10 集中度指标
            en: CR4/CR8/CR10 concentration metrics
          - zh: 头部企业市场份额变化趋势
            en: Top players' market share trends
      - id: competitive_barriers
        name:
          zh: 竞争壁垒分析
          en: Competitive Barriers
        points:
          - zh: 技术壁垒与专利护城河
            en: Technology barriers and patent moats
          - zh: 资金壁垒与规模效应
            en: Capital barriers and economies of scale
          - zh: 政策准入壁垒
            en: Regulatory entry barriers
```

### 2.3 全链路数据流

```
① YAML 模板 (含 sub_sections + points)
  ↓ 加载
② ReportTemplate (含嵌套 SectionConfig)
  ↓ 传入
③ DecompositionPlan (每个 Agent 携带完整的 sub_sections + points)
  ↓ 执行
④ Agent 输出 (按 ### sub-section 结构化输出)
  ↓ 聚合
⑤ ResultAggregator (按模板 sub_sections 精确拆分而非启发式解析)
  ↓ 生成
⑥ ContentOrchestrator (已有三级渲染能力，直接使用)
  ↓ 输出
⑦ HTML/DOCX/PDF (三级层次完整呈现)
```

---

## 3. 逐层修改方案

### 3.1 Layer 1: YAML 模板升级

**文件**: `config/templates/*.yaml` (12 个模板文件)

**改动**：为每个 section 增加 `sub_sections` 和 `points`。

**原则**：
- 每个 section 定义 2-5 个 sub_sections
- 每个 sub_section 定义 2-4 个 points
- points 使用 i18n 格式 `{zh: ..., en: ...}` 保持双语
- 保持向后兼容：无 `sub_sections` 的 section 仍按一级处理

**示例** (`industry_report.yaml` 的 `competitive_landscape` section)：

```yaml
  - id: competitive_landscape
    name:
      zh: 竞争格局
      en: Competitive Landscape
    required: true
    description:
      zh: 市场集中度、竞争壁垒、波特五力分析、SWOT对比
      en: Market concentration, barriers, Porter Five Forces, SWOT comparison
    sub_sections:
      - id: market_concentration
        name:
          zh: 市场集中度
          en: Market Concentration
        points:
          - zh: CR4/CR8/CR10 集中度指标及变化趋势
            en: CR4/CR8/CR10 concentration metrics and trends
          - zh: 头部企业市场份额及变化
            en: Top players' market share and changes
      - id: competitive_barriers
        name:
          zh: 竞争壁垒分析
          en: Competitive Barriers
        points:
          - zh: 技术壁垒与专利护城河
            en: Technology barriers and patent moats
          - zh: 资金壁垒与规模效应
            en: Capital barriers and economies of scale
          - zh: 政策准入与牌照壁垒
            en: Regulatory entry and licensing barriers
      - id: porter_five_forces
        name:
          zh: 波特五力分析
          en: Porter's Five Forces
        points:
          - zh: 供应商议价能力
            en: Bargaining power of suppliers
          - zh: 买方议价能力
            en: Bargaining power of buyers
          - zh: 替代品威胁
            en: Threat of substitutes
```

**工作量**：12 个模板 × 平均 8 sections × 3 sub-sections = 约 288 个 sub-section 定义

**Schema 更新** (`config/templates/template_schema.yaml`)：

```yaml
section_schema:
  required_fields:
    - id
    - name
  optional_fields:
    - required
    - description
    - sub_sections          # ← 新增
  sub_section_schema:       # ← 新增
    required_fields:
      - id
      - name
    optional_fields:
      - description
      - points               # ← 新增: List of point strings or i18n dicts
```

### 3.2 Layer 2: 模板加载层

**文件**: `src/config/report_template.py`

**当前**：
```python
@dataclass
class ReportTemplate:
    sections: Dict[str, Any] = field(default_factory=dict)  # type hint 不准确，实际从 YAML 加载为 list
```
注意：`load_template()` 中 `sections=config.get('sections', {})` 默认值 `{}` 与 YAML 中的 list 不一致，这是现有 bug。

**目标**：新增嵌套数据类，统一命名

```python
@dataclass
class PointConfig:
    zh: str = ""
    en: str = ""
    @property
    def text(self) -> str:
        return self.zh or self.en

@dataclass
class SubSectionConfig:
    id: str = ""
    name: Dict[str, str] = field(default_factory=dict)  # ← YAML 用 sub_sections（带下划线）
    description: Dict[str, str] = field(default_factory=dict)
    points: List[PointConfig] = field(default_factory=list)
    
    @property
    def display_name(self) -> str:
        if isinstance(self.name, dict):
            return self.name.get("zh", self.name.get("en", self.id))
        return str(self.name) or self.id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "points": [{"zh": pt.zh, "en": pt.en} for pt in self.points],
        }

@dataclass
class SectionConfig:
    id: str = ""
    name: Dict[str, str] = field(default_factory=dict)
    required: bool = False
    description: Dict[str, str] = field(default_factory=dict)
    sub_sections: List[SubSectionConfig] = field(default_factory=list)  # ← 保留 YAML 命名 sub_sections
    
    @property
    def display_name(self) -> str:
        if isinstance(self.name, dict):
            return self.name.get("zh", self.name.get("en", self.id))
        return str(self.name) or self.id
    
    def to_subsections_list(self) -> List[Dict]:
        """将模板 sub_sections 转换为渲染层期望的 subsections 格式（无下划线）
        
        解决命名不一致：YAML/模板层用 sub_sections，渲染层用 subsections
        """
        return [
            {
                "id": sub.id,
                "title": sub.display_name,
                "name": sub.name,
                "points": [pt.text for pt in sub.points],
            }
            for sub in self.sub_sections
        ]
    
    def get(self, key: str, default: Any = None) -> Any:
        """兼容 dict 式访问，使 smart_clarifier.py 等现有代码无需修改"""
        mapping = {
            "id": self.id,
            "name": self.name,
            "required": self.required,
            "description": self.description,
            "sub_sections": [sub.to_dict() for sub in self.sub_sections],
        }
        return mapping.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        """兼容 dict 式访问: section["id"]"""
        return self.get(key)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，供 I18n.localize_sections() 等函数使用"""
        return {
            "id": self.id,
            "name": self.name,
            "required": self.required,
            "description": self.description,
            "sub_sections": [sub.to_dict() for sub in self.sub_sections],
        }

@dataclass
class ReportTemplate:
    meta: Dict[str, Any] = field(default_factory=dict)
    sections: List[SectionConfig] = field(default_factory=list)  # ← 改为 List[SectionConfig]
    # ... 其余字段不变
```

**加载逻辑** (`load_template`)：
```python
# 新增 _parse_sections 方法
def _parse_sections(raw_sections: list) -> List[SectionConfig]:
    result = []
    for s in raw_sections:
        sub_sections = []
        for sub in s.get("sub_sections", []):
            points = []
            for pt in sub.get("points", []):
                if isinstance(pt, dict):
                    points.append(PointConfig(zh=pt.get("zh", ""), en=pt.get("en", "")))
                elif isinstance(pt, str):
                    points.append(PointConfig(zh=pt, en=pt))
            sub_sections.append(SubSectionConfig(
                id=sub.get("id", ""),
                name=sub.get("name", {}),
                description=sub.get("description", {}),
                points=points,
            ))
        result.append(SectionConfig(
            id=s.get("id", ""),
            name=s.get("name", {}),
            required=s.get("required", False),
            description=s.get("description", {}),
            sub_sections=sub_sections,
        ))
    return result
```

同时修复 `load_template()` 现有 bug：
```python
# 当前 (有 bug):
sections=config.get('sections', {})

# 修正:
sections=_parse_sections(config.get('sections', []))
```

### 3.3 Layer 3: 任务分解层

**文件**: `src/core/decomposition/strategies.py`

**当前问题**：
- `aspects: List[str]` 是扁平字符串列表
- `SubSectionSpec` 是运行时从 `section_data_specs` 或 `sections_tree` 生成的
- 当模板有预定义 sub_sections 时，应**优先使用模板定义**而非 LLM 生成

**改动**：

1. **从模板加载 sub_sections 到 AgentSpec**

```python
# IndustryResearchStrategy.decompose() 中
for seq_idx, (i, aspect) in enumerate(normal_aspects):
    # 优先从模板 section_details 获取 sub_sections
    template_sub_sections = []
    if section_details:
        for sd in section_details:
            sd_name = sd.get("name", {}) if isinstance(sd.get("name"), dict) else sd.get("name", "")
            # 匹配当前 aspect
            if _name_matches(sd, aspect):  # 注: _name_matches 为新增辅助函数，需在实施时定义
                template_sub_sections = sd.get("sub_sections", [])
                break
    
    # 构建 sub_aspects
    if template_sub_sections:
        sub_aspects = [sub.get("name", {}) for sub in template_sub_sections]
        sub_points = []
        for sub in template_sub_sections:
            sub_points.extend(sub.get("points", []))
    else:
        # 回退: 从 section_data_specs 获取
        matched_spec = section_spec_by_id.get(section_id) or section_spec_by_name.get(aspect)
        sub_aspects = [sub.name for sub in matched_spec.sub_sections] if matched_spec else []
```

2. **分析 prompt 强化结构约束**

当模板定义了 sub_sections 时，在 `_build_analysis_prompt` 中追加：

```python
if template_sub_sections:
    structure_constraint = "\n\n## 输出结构要求（必须严格遵守）\n"
    structure_constraint += "请按以下结构输出分析内容，每个子章节使用 ### 标题：\n"
    for sub in template_sub_sections:
        sub_name = sub.get("name", {}) if isinstance(sub.get("name"), dict) else sub.get("name", "")
        if isinstance(sub_name, dict):
            sub_name = sub_name.get("zh", sub_name.get("en", ""))
        structure_constraint += f"### {sub_name}\n"
        for pt in sub.get("points", []):
            if isinstance(pt, dict):
                pt_text = pt.get("zh", pt.get("en", ""))
            else:
                pt_text = pt
            structure_constraint += f"- {pt_text}\n"
    sub_aspects_section = structure_constraint
```

**关键**：这是质量提升的核心。当前 Agent 输出自由散漫，因为 prompt 只说"请分析 X"。加上结构约束后，Agent 必须按预定义的子维度输出，确保覆盖完整。

### 3.4 Layer 4: 结果聚合层

**文件**: `src/core/orchestrator/aggregation/result_aggregator.py`

**当前问题**：
- `_parse_markdown_subsections()` 是启发式的，从 Agent 输出中猜测子章节
- 当模板定义了 sub_sections 时，应该**按模板定义拆分**而非启发式解析

**改动**：

```python
# 在 ResultAggregator.aggregate() 中，遍历 self.section_details 生成 section dict 时
# (位于 result_aggregator.py:518 循环体中，约 L665)
# self.section_details 中的 section 字典来自 _build_section_details_from_tree()
# 其键名为 "sub_sections"（带下划线，见 research_api.py:1871）

# 当前:
subsections = _parse_markdown_subsections(content)

# 改为:
template_sub_sections = section.get("sub_sections", [])  # 注意: section_details 用 sub_sections
if template_sub_sections:
    # 按模板定义拆分
    subsections = _split_content_by_template_subsections(
        content, template_sub_sections
    )
else:
    # 回退: 启发式解析
    subsections = _parse_markdown_subsections(content)
```

**新增函数** `_split_content_by_template_subsections`：

```python
def _split_content_by_template_subsections(
    content: str,
    template_sub_sections: List[Dict],
) -> List[Dict]:
    """按模板定义的 sub_sections 拆分 Agent 输出内容
    
    策略:
    1. 在 content 中查找 ### 子标题
    2. 按模板 sub_section name 匹配
    3. ### 标题行保留在内容中（渲染层需要）
    4. 未匹配的内容归入前一个 sub_section
    
    输出格式: 与 _parse_markdown_subsections() 一致，使用 "subsections"（无下划线）
    """
    if not content or not template_sub_sections:
        return _parse_markdown_subsections(content)
    
    # 构建 heading → sub_section 映射
    sub_names = []
    for sub in template_sub_sections:
        name = sub.get("name", "")
        if isinstance(name, dict):
            name = name.get("zh", name.get("en", ""))
        sub_names.append(name)
    
    # 在 content 中按 ### 标题拆分
    lines = content.split('\n')
    sections_content = {name: [] for name in sub_names}
    current_sub = None
    
    for line in lines:
        stripped = line.strip()
        # 检查是否是 ### 子标题
        matched_sub = None
        if stripped.startswith('### '):
            heading = stripped[4:].strip()
            for name in sub_names:
                if name in heading or heading in name:
                    matched_sub = name
                    break
        
        if matched_sub:
            current_sub = matched_sub
            # 注意: 保留 ### 标题行在内容中（渲染层需要从内容中提取标题）
            sections_content[current_sub].append(line)
            continue
        
        if current_sub:
            sections_content[current_sub].append(line)
        else:
            # 未归属的内容，归入第一个 sub_section
            if sub_names:
                sections_content[sub_names[0]].append(line)
    
    # 组装结果 (使用 "subsections" 格式，与渲染层一致)
    result = []
    for i, sub in enumerate(template_sub_sections):
        name = sub.get("name", "")
        if isinstance(name, dict):
            name = name.get("zh", name.get("en", ""))
        sub_id = sub.get("id", f"sub_{i}")
        sub_content = '\n'.join(sections_content.get(name, [])).strip()
        
        # 提取 points
        points = []
        for pt in sub.get("points", []):
            if isinstance(pt, dict):
                points.append(pt.get("zh", pt.get("en", "")))
            else:
                points.append(pt)
        
        result.append({
            "id": sub_id,
            "title": name,
            "content": sub_content or f"> ⚠️ 子章节 {name} 数据不足",
            "points": points,
        })
    
    return result
```

### 3.5 Layer 5: 报告生成层

**文件**: `src/agents/fixed_agents/report_generation_agent.py`

**当前问题**：
- `_integrate_body()` 只输出 `## {i}. {title}`，无子标题
- `_generate_toc()` 只有一级目录

**改动**：

#### 3.5.1 `_integrate_body()` 升级

```python
def _integrate_body(self, sections: List[Dict], style_guide: Dict, lang: Language) -> str:
    sections = self._apply_content_quality(sections)
    body_parts = []
    
    for i, section in enumerate(sections, start=1):
        title = section.get("title", f"{_t('chapter', lang)} {i}")
        content = section.get("content", "")
        subsections = section.get("subsections", [])  # ← 新增
        
        # Level 1: 章节标题
        body_parts.append(f"## {i}. {title}\n")
        
        if subsections:
            # 三级模式: 按 sub-sections 渲染
            for j, subsec in enumerate(subsections, 1):
                sub_title = subsec.get("title", "")
                sub_content = subsec.get("content", "")
                sub_points = subsec.get("points", [])
                
                # Level 2: 子章节标题
                body_parts.append(f"### {i}.{j} {sub_title}\n")
                body_parts.append(sub_content)
                
                # Level 3: 要点 (如果有 point_sections)
                point_sections = subsec.get("point_sections", [])
                if point_sections:
                    for k, pt_sec in enumerate(point_sections, 1):
                        pt_title = pt_sec.get("title", "")
                        pt_content = pt_sec.get("content", "")
                        if pt_content:
                            body_parts.append(f"#### {i}.{j}.{k} {pt_title}\n")
                            body_parts.append(pt_content)
        else:
            # 一级模式: 向后兼容
            body_parts.append(content)
        
        if section.get("include_summary", False):
            summary = self._generate_section_summary(content)
            body_parts.append(f"\n> **{_t('chapter_summary', lang)}**：{summary}\n")
        
        body_parts.append("\n---\n")
    
    return "\n".join(body_parts)
```

#### 3.5.2 `_generate_toc()` 升级

```python
def _generate_toc(self, sections, has_exec_summary=True, has_conclusion=False, lang=Language.ZH):
    toc_lines = [f"## {_t('toc', lang)}\n"]
    chapter_num = 1
    
    if has_exec_summary:
        exec_label = _t("exec_summary", lang)
        toc_lines.append(f"{chapter_num}. [{exec_label}](#{self._generate_anchor(exec_label)})")
        chapter_num += 1
    
    for section in sections:
        title = section.get("title", f"{_t('chapter', lang)}{chapter_num}")
        anchor = self._generate_anchor(title)
        toc_lines.append(f"{chapter_num}. [{title}](#{anchor})")
        
        # Level 2: 子章节
        subsections = section.get("subsections", [])
        for j, subsec in enumerate(subsections, 1):
            sub_title = subsec.get("title", "")
            sub_anchor = self._generate_anchor(sub_title)
            toc_lines.append(f"   {chapter_num}.{j} [{sub_title}](#{sub_anchor})")
        
        chapter_num += 1
    
    if has_conclusion:
        conclusion_label = _t("conclusion", lang)
        toc_lines.append(f"{chapter_num}. [{conclusion_label}](#{self._generate_anchor(conclusion_label)})")
        chapter_num += 1
    
    appendix_label = _t("appendix", lang)
    toc_lines.append(f"{chapter_num}. [{appendix_label}](#{self._generate_anchor(appendix_label)})")
    toc_lines.append("\n---\n")
    return "\n".join(toc_lines)
```

**注意**：`document_generation_agent.py` 已有三级渲染逻辑（L632-644），使用 `section.get("subsections", [])` 和 `subsection.get("points", [])`。只要 `result_aggregator` 输出的 `subsections` 结构正确（含 `title`, `content`, `points`），该文件无需修改。

### 3.6 Layer 6: 框架对话层

**文件**: `src/api/research_api.py` 和 `src/core/orchestrator/orchestrator.py`

两个文件都有 `_build_section_details_from_tree()` 方法（`research_api.py:1859`、`orchestrator.py:3824`），需要同步添加 `_build_section_details_from_template()`。

**当前问题**：
- `_build_section_details_from_tree()` 从 LLM 生成的 `sections_tree` 构建
- 当使用模板启动时，应从**模板预定义**的 sub_sections 构建

**改动**：

```python
def _build_section_details_from_template(self, template_sections: List[Dict]) -> List[Dict]:
    """从模板的预定义 sections (含 sub_sections) 构建 section_details"""
    details = []
    for section in template_sections:
        name = section.get("name", "")
        if isinstance(name, dict):
            name = name.get("zh", name.get("en", ""))
        
        sub_sections_data = []
        for sub in section.get("sub_sections", []):
            sub_name = sub.get("name", "")
            if isinstance(sub_name, dict):
                sub_name = sub_name.get("zh", sub_name.get("en", ""))
            points = []
            for pt in sub.get("points", []):
                if isinstance(pt, dict):
                    points.append(pt.get("zh", pt.get("en", "")))
                else:
                    points.append(pt)
            sub_sections_data.append({"name": sub_name, "points": points})
        
        detail = {
            "id": section.get("id", name.lower().replace(" ", "_")),
            "name": name,
            "content": name,
            "sub_sections": sub_sections_data,
        }
        details.append(detail)
    return details
```

### 3.7 Layer 7: 框架配置层 (可选)

**文件**: `config/research_frameworks.yaml`

**当前**: `section_weights` 只到一级

```yaml
section_weights:
  competitive_landscape: 2.0
```

**目标**: 支持二级权重（可选，一期可不实现）

```yaml
section_weights:
  competitive_landscape: 2.0
  competitive_landscape.market_concentration: 2.5  # 子章节权重
```

**一期策略**：不改动，子章节权重继承父章节权重。

---

## 4. 向后兼容性分析

### 4.1 无 sub_sections 的模板

所有现有模板在添加 `sub_sections` 之前，行为完全不变：

| 代码路径 | 兼容逻辑 |
|---|---|
| `report_template.py` | `sub_sections` 默认空列表 `[]` |
| `strategies.py` | `if template_sub_sections: ... else: 回退` |
| `result_aggregator.py` | `if section.get("sub_sections"): ... else: _parse_markdown_subsections()` |
| `report_generation_agent.py` | `if subsections: 三级模式 else: 一级模式` |
| `document_generation_agent.py` | 已有 `section.get("subsections", [])` 三级逻辑，无需改动 |
| `content_orchestrator.py` | 已有 `if section.subsections:` 判断，无需改动 |

**⚠️ 类型变更影响**：将 `sections: Dict[str, Any]` 改为 `List[SectionConfig]` 会影响以下现有消费者
（它们使用 dict 式访问 `s["id"]`、`s.get("required", False)`）：

| 文件 | 行号 | 当前用法 | 需要适配 |
|---|---|---|---|
| `smart_clarifier.py` | L849 | `s["id"] for s in template.sections` | 改为 `s.id` |
| `smart_clarifier.py` | L849 | `s.get("required", False)` | 改为 `s.required` |
| `smart_clarifier.py` | L858 | `"sections": template.sections` | 调用序列化方法 |
| `smart_clarifier.py` | L615 | `base_template.sections` | 遍历方式不变（list→list） |
| `smart_clarifier.py` | L310,338 | `I18n.localize_sections(template.sections, ...)` | 需适配函数签名 |
| `orchestrator.py` | L3982 | `return template.sections` | 返回类型变更，需检查调用方 |

**解决方案**：为 `SectionConfig` 添加 `to_dict()` 方法和兼容性方法 `get()` / `__getitem__`：
```python
@dataclass
class SectionConfig:
    # ... existing fields ...
    
    def get(self, key: str, default: Any = None) -> Any:
        """兼容 dict 式访问"""
        mapping = {
            "id": self.id,
            "name": self.name,
            "required": self.required,
            "description": self.description,
            "sub_sections": [sub.to_dict() for sub in self.sub_sections],
        }
        return mapping.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        return self.get(key)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "required": self.required,
            "description": self.description,
            "sub_sections": [sub.to_dict() for sub in self.sub_sections],
        }
```

这样 `smart_clarifier.py` 等现有代码无需修改即可正常工作。

### 4.2 旧模板 YAML 格式

`name` 字段同时支持字符串和 `{zh: ..., en: ...}` 字典：

```yaml
# 旧格式 (仍有效)
- id: summary
  name: Investment Summary

# 新格式
- id: summary
  name:
    zh: 投资摘要
    en: Investment Summary
```

### 4.3 命名规范：sub_sections vs subsections

系统中存在命名不一致，升级方案保留两套命名：

| 上下文 | 键名 | 说明 |
|---|---|---|
| YAML 模板 | `sub_sections` | 带下划线，符合 YAML 键命名惯例 |
| `sections_tree` / `section_details` | `sub_sections` | 对话层/框架层，与 YAML 一致 |
| `SectionConfig` 属性 | `sub_sections` | 模板加载层，与 YAML 一致 |
| `ContentSection` 属性 | `subsections` | 无下划线，Python 属性命名惯例 |
| `result_aggregator` 输出 | `subsections` | 与 ContentSection 一致 |
| HTML 模板变量 | `subsections` | 与 ContentOrchestrator 一致 |
| `document_generation_agent` | `subsections` | 与 result_aggregator 一致 |

**映射规则**：`SectionConfig.to_subsections_list()` 方法在模板加载层完成 `sub_sections` → `subsections` 的转换。此后整个渲染管道统一使用 `subsections`。

### 4.4 sections_tree vs 模板 sub_sections

优先级：
1. 模板预定义 `sub_sections` (最高，从 YAML 模板加载)
2. LLM 对话生成的 `sections_tree` (次之，当模板无定义时使用)
3. 启发式 `_parse_markdown_subsections()` (兜底)

---

## 5. 分期实施计划

### Phase 1: 数据源 + 模板加载 (核心)

| # | 任务 | 文件 | 行数估计 |
|---|---|---|---|
| 1 | 为 `industry_report.yaml` 添加 sub_sections | `config/templates/industry_report.yaml` | ~80 行 |
| 2 | 为 `company_research.yaml` 添加 sub_sections | `config/templates/company_research.yaml` | ~60 行 |
| 3 | 为 `annual_analysis.yaml` 添加 sub_sections | `config/templates/annual_analysis.yaml` | ~60 行 |
| 4 | 更新 `template_schema.yaml` | `config/templates/template_schema.yaml` | ~15 行 |
| 5 | 新增 `SectionConfig` / `SubSectionConfig` / `PointConfig` + 兼容性方法 | `src/config/report_template.py` | ~110 行 |
| 6 | 更新 `load_template()` 解析逻辑 | `src/config/report_template.py` | ~40 行 |

**交付标准**：`load_template("industry_report")` 返回含 `sub_sections` 的 `ReportTemplate`

### Phase 2: 数据管道 (分解 + 聚合)

| # | 任务 | 文件 | 行数估计 |
|---|---|---|---|
| 7 | `strategies.py`: 从模板加载 sub_sections 到 AgentSpec | `src/core/decomposition/strategies.py` | ~30 行 |
| 8 | `strategies.py`: 分析 prompt 追加结构约束 | `src/core/decomposition/strategies.py` | ~25 行 |
| 9 | `result_aggregator.py`: `_split_content_by_template_subsections()` | `src/core/orchestrator/aggregation/result_aggregator.py` | ~80 行 |
| 10 | `result_aggregator.py`: 优先使用模板拆分 | 同上 | ~10 行 |
| 11 | `research_api.py` + `orchestrator.py`: `_build_section_details_from_template()` | `src/api/research_api.py`, `src/core/orchestrator/orchestrator.py` | ~30 行 |

**交付标准**：Agent 输出按模板 sub_sections 结构化拆分

### Phase 3: 报告渲染

| # | 任务 | 文件 | 行数估计 |
|---|---|---|---|
| 12 | `_integrate_body()` 三级渲染 | `src/agents/fixed_agents/report_generation_agent.py` | ~35 行 |
| 13 | `_generate_toc()` 三级目录 | 同上 | ~15 行 |
| 14 | 确认 `document_generation_agent.py` 三级逻辑兼容 | `src/agents/fixed_agents/document_generation_agent.py` | 0（已有实现，仅需验证） |

**交付标准**：最终报告含 `## → ### → ####` 三级标题

### Phase 4: 批量模板 + 测试

| # | 任务 | 文件 | 行数估计 |
|---|---|---|---|
| 15 | 其余 9 个模板添加 sub_sections | `config/templates/*.yaml` | ~400 行 |
| 16 | 单元测试 | `tests/unit/` | ~150 行 |
| 17 | 端到端验证 | 手动 | - |

---

## 6. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Agent 不遵循 ### 结构约束 | 中 | 中 | prompt 强约束 + 后处理拆分兜底 |
| 模板 sub_sections 与 LLM 输出不匹配 | 中 | 低 | `_split_content_by_template_subsections` 有模糊匹配 + 兜底 |
| 旧数据/session 不兼容 | 低 | 低 | `sub_sections=[]` 作为默认值，完全向后兼容 |
| 子章节拆分后内容过短 | 低 | 低 | 设置子章节最小字数阈值，不足时合并 |
| points 作为 data_needs 过于精确导致搜索结果少 | 中 | 中 | points 同时用于搜索关键词和宽泛查询 |

---

## 7. 验收标准

1. `load_template("industry_report").sections[0].sub_sections` 非空
2. 生成的研究报告 TOC 含二级条目 (`1.1`, `1.2`...)
3. 生成的研究报告正文含 `### 1.1 xxx` 子标题
4. 无 sub_sections 的模板行为不变（向后兼容）
5. 模板预定义优先于 LLM 即兴生成
