# ChartPlannerAgent 设计文档

> Version: v2.1  
> Date: 2026-07-04  
> Status: Design Proposal (Audit Complete)  
> Supersedes: `docs/_archive/design/CHART_GENERATION_SKILL_DESIGN.md` (v1.0)

---

## 目录

1. [问题诊断](#1-问题诊断)
2. [设计目标](#2-设计目标)
3. [架构设计](#3-架构设计)
4. [ChartPlannerAgent 详细设计](#4-chartplanneragent-详细设计)
5. [图表插入位置系统](#5-图表插入位置系统)
6. [数据结构定义](#6-数据结构定义)
7. [LLM Prompt 设计](#7-llm-prompt-设计)
8. [集成方案](#8-集成方案)
9. [降级与容错](#9-降级与容错)
10. [修改清单](#10-修改清单)
11. [测试方案](#11-测试方案)

---

## 1. 问题诊断

### 1.1 当前系统行为

当前图表生成流程（`generic_agent.py:5952-6096`）：

```
GenericAgent 生成章节内容
    → 正则提取 Markdown 表格 (r'\|(.+)\|\n\|[-\s|:]+\|\n...')
    → 对每个表格的第一列数值列，提取数值 (re.sub(r'[^\d.]', '', ...))
    → 生成 ChartType.BAR 柱状图
    → 标题为 "{aspect} - {headers[col_idx]}"[:50]
    → 图注为 "份额对比（N项）" 或 "排名对比（N项）"
```

### 1.2 六大问题

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| P1 | **图表标题无语义** | 标题由 `aspect + 列名` 拼接，图注由通用模板生成 | 读者无法理解图表含义 |
| P2 | **数据量纲混乱** | `re.sub(r'[^\d.]', '', ...)` 剥离单位，百分比4.05与绝对值8040同图 | 图表无意义，无法对比 |
| P3 | **只生成柱状图** | 硬编码 `ChartType.BAR`，忽略 ChartGenerator 支持的10种类型 | 图表类型与数据特征不匹配 |
| P4 | **无关数据生成图表** | 无数据源相关性检查，B站/船舶/4399数据也生成图表 | 报告可信度受损 |
| P5 | **图表堆叠在章节末尾** | 模板统一在 `section.charts` 循环渲染，位于所有子章节之后 | 图表与正文脱节 |
| P6 | **文本列解析为数值0** | 非数值列经正则提取后变为0，混入图表 | 图表包含无意义数据 |

### 1.3 根因总结

图表渲染层（`ChartGenerator`）本身专业，问题出在**数据提取与图表规划层**——用正则表达式机械地从 LLM 输出的 Markdown 表格中提取数据，缺乏：

1. **语义理解**：哪些数据应该可视化，哪些不应该
2. **量纲一致性检查**：同图数据是否可比较
3. **图表类型选择**：数据特征 → 图表类型映射
4. **主题相关性判断**：数据源是否与章节主题匹配
5. **插入位置规划**：图表应出现在正文中的哪个位置

---

## 2. 设计目标

### 2.1 核心目标

**引入 ChartPlannerAgent，通过 LLM 语义分析，替代正则提取，实现专业图表规划与精准插入。**

### 2.2 量化指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 图表标题语义明确率 | ~10% | >90% |
| 图表量纲一致性 | ~20% | 100% |
| 图表类型多样性 | 1种(bar) | 5种+ |
| 无关数据生成图表率 | ~60% | 0% |
| 图表与正文位置匹配率 | 0%(全堆末尾) | >80% |
| 每章节平均图表数 | 2-3 | 0-2(精选) |

### 2.3 约束

- 每章节最多2张图表，宁缺毋滥
- 数据源与章节主题不匹配时，拒绝生成图表
- 不修改 `ChartGenerator`（渲染层无需改动）
- 对下游 `content_orchestrator` 的接口保持兼容

---

## 3. 架构设计

### 3.1 整体数据流

```
GenericAgent 输出 (content, topic, section_title)
    │
    ▼
┌─────────────────────────────────────────────┐
│ ChartPlannerAgent.plan()                    │
│                                             │
│  1. 预过滤 (规则引擎，无LLM调用)             │
│     - 表格数值有效性检查                     │
│     - 主题相关性初筛（标记）                  │
│                                             │
│  2. LLM 语义分析 (1次LLM调用, call_llm)     │
│     - 输入：章节内容摘要 + 表格数据 + 主题   │
│     - 输出：ChartPlan[] JSON                │
│                                             │
│  3. 方案校验 (规则引擎，无LLM调用)           │
│     - 量纲一致性                             │
│     - 图表类型与数据匹配                     │
│     - 数值范围合理性                         │
│                                             │
│  返回 ChartPlan[] (不含 image_path)          │
└─────────────────────────────────────────────┘
    │
    ▼
GenericAgent 调用 ChartGenerator.generate(config) → PNG
(规划与渲染分离，ChartPlannerAgent 不负责渲染)
    │
    ▼
ContentOrchestrator._insert_charts_into_html()
    → 根据 insertion_anchor 在 Markdown 阶段定位
    → 转换后按行号在 HTML 对应位置插入 <figure>
```

### 3.2 与现有系统的关系

```
改动前:
  GenericAgent._generate_charts_from_content()  [正则提取，6大问题]
      → ChartGenerator.generate()
      → content_orchestrator (模板末尾循环渲染)

改动后:
  GenericAgent._generate_charts_from_content()
      → ChartPlannerAgent.plan()                [新增：LLM语义分析，返回ChartPlan[]]
      → ChartGenerator.generate(config)         [不变，由GenericAgent调用]
      → content_orchestrator._insert_charts_into_html()  [新增：锚点插入]
```

---

## 4. ChartPlannerAgent 详细设计

### 4.1 类定义

```python
# src/services/chart_planner.py

class ChartPlannerAgent:
    """
    图表规划Agent
    
    通过LLM语义分析，从章节内容中规划专业图表方案。
    职责：决定"要不要图"、"用什么图"、"图放哪里"、"数据怎么组织"。
    不负责渲染（由ChartGenerator执行）。
    """
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
    
    async def plan(
        self,
        content: str,
        topic: str,
        section_title: str,
    ) -> List[ChartPlan]:
        """
        规划图表方案
        
        Args:
            content: 章节完整内容（含Markdown表格）
            topic: 研究主题（如"比亚迪财务分析"）
            section_title: 章节标题（如"Competitive Landscape"）
            
        Returns:
            ChartPlan列表，0-2个（不含image_path，渲染由调用方负责）
        """
        # Step 1: 预过滤
        tables = self._extract_tables(content)
        filtered = self._prefilter_tables(tables, topic, section_title)
        
        if not filtered:
            logger.info(f"No valid tables for chart in '{section_title}'")
            return []
        
        # Step 2: LLM语义分析
        plans = await self._llm_plan(content, filtered, topic, section_title)
        
        # Step 3: 方案校验
        validated = self._validate_plans(plans)
        
        return validated
    
    async def _llm_plan(self, content, filtered, topic, section_title):
        """
        调用LLM进行图表规划
        
        使用 call_llm 全局函数（与GenericAgent一致），
        而非传入 llm_client 对象。
        """
        from src.core.llm_client import call_llm
        from src.config.llm_profiles import RoutingHint
        
        content_summary, tables_json = self._prepare_llm_input(content, filtered)
        
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(topic, section_title, content_summary, tables_json)
        
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=1000,
            temperature=0.3,
            routing_hint=RoutingHint(agent_type="generic", action="chart_planning"),
        )
        
        if not result.get("success"):
            logger.warning(f"ChartPlanner LLM call failed: {result.get('error')}")
            return []
        
        return self._parse_llm_response(result.get("content", ""))
```

### 4.2 预过滤规则

预过滤在LLM调用之前执行，用规则引擎快速剔除明显无意义的表格，节省LLM调用成本。

```python
def _prefilter_tables(
    self,
    tables: List[ExtractedTable],
    topic: str,
    section_title: str,
) -> List[ExtractedTable]:
    """
    规则引擎预过滤，返回适合生成图表的表格
    
    过滤规则：
    1. 数值列占比 < 30% → 剔除（纯文本表格）
    2. 所有数值为0或空 → 剔除
    3. 同一数值列内，量纲不一致 → 标记（由LLM进一步判断）
    4. 表格行数 < 2 → 剔除
    5. 主题相关性初筛 → 标记可疑表格（见下方实现）
    """
        results = []
        for table in tables:
            # 规则4: 行数检查
            if len(table.rows) < 2:
                continue
            
            # 规则1: 数值列占比
            numeric_cols = self._count_numeric_columns(table)
            total_cols = len(table.headers)
            if numeric_cols / total_cols < 0.3:
                continue
            
            # 规则2: 数值有效性
            has_valid_values = False
            for col_idx in range(1, total_cols):
                values = self._extract_numeric_values(table, col_idx)
                if any(v != 0 for v in values):
                    has_valid_values = True
                    break
            if not has_valid_values:
                continue
            
            # 规则5: 主题相关性初筛（标记，不直接过滤）
            # 从表格header和前两行提取关键词，与topic做重叠度检查
            table_keywords = set()
            for h in table.headers:
                table_keywords.update(re.findall(r'[\u4e00-\u9fff]{2,}', h))
            for row in table.rows[:2]:
                for cell in row:
                    table_keywords.update(re.findall(r'[\u4e00-\u9fff]{2,}', cell))
            
            topic_keywords = set(re.findall(r'[\u4e00-\u9fff]{2,}', topic + section_title))
            overlap = len(table_keywords & topic_keywords)
            
            # 标记可疑表格（传给LLM时附加标记，由LLM最终决定）
            table.topic_relevance = "high" if overlap >= 2 else "low" if overlap == 0 else "medium"
            
            results.append(table)
        
        return results
```

### 4.3 LLM 语义分析

核心方法，通过LLM理解数据语义，输出结构化图表方案。

详见 [第7节 LLM Prompt 设计](#7-llm-prompt-设计)。

### 4.4 方案校验规则

对LLM输出的ChartPlan做结构校验，防止幻觉。

```python
def _validate_plans(self, plans: List[ChartPlan]) -> List[ChartPlan]:
    """
    校验规则：
    1. 量纲一致性：同一图表的values必须量纲统一
       - 百分比列（0-100）不能与绝对值列（万元）同图
       - LLM输出的data中已含unit字段，校验是否一致
    2. 图表类型与数据匹配：
       - 饼图：values必须全部非负，且总和有意义
       - 折线图：categories必须是时间序列或有序序列
       - 雷达图：维度数3-8个
       - 柱状图：categories <= 12
    3. 数值范围合理性：
       - 百分比值应在0-100范围
       - 不应出现极端异常值（如1e10）
    4. 置信度过滤：confidence < 0.5 的方案剔除
    5. 数量限制：每章节最多2张图表，取confidence最高的
    """
    validated = []
    for plan in plans:
        # 规则4: 置信度
        if plan.confidence < 0.5:
            continue
        
        # 规则1: 量纲一致性
        if not self._check_unit_consistency(plan):
            continue
        
        # 规则2: 图表类型匹配
        if not self._check_chart_type_match(plan):
            continue
        
        # 规则3: 数值范围
        if not self._check_value_range(plan):
            continue
        
        validated.append(plan)
    
    # 规则5: 数量限制
    validated.sort(key=lambda p: p.confidence, reverse=True)
    return validated[:2]
```

---

## 5. 图表插入位置系统

### 5.1 当前问题

模板 `word_default.html:452-457` 中，图表统一追加在章节末尾：

```
章节标题 → 正文内容 → 子章节们 → 【所有图表堆在这里】 → 表格
```

导致：
1. 图表与正文脱节——读者读到关键数据时，图表在数屏之后
2. 图表堆叠——多张图表连续排列，缺乏上下文关联
3. 图表和表格倒挂——表格（数据源）在图表后面

### 5.2 锚点定位插入方案

ChartPlannerAgent在规划图表时，同时输出**插入锚点**，指定图表应出现在正文中的哪个位置。

#### 锚点类型

| anchor_type | 含义 | 插入位置 | 示例 |
|-------------|------|----------|------|
| `after_paragraph` | 图表是对某段分析的可视化 | 该段落`<p>`标签之后 | 锚点"利润率持续承压" → 插在该段后 |
| `after_table` | 图表是对表格数据的可视化 | 紧跟数据源表格之后 | 锚点"比亚迪关键财务指标" → 插在表格后 |
| `section_start` | 图表是章节总览/概要 | 章节标题之后、正文之前 | 适用于总览型图表 |
| `section_end` | 图表是章节总结 | 章节末尾（现有逻辑） | 适用于汇总型图表 |

#### ChartPlan 新增字段

```python
@dataclass
class ChartPlan:
    # ... 原有字段 ...
    insertion_anchor: str      # 锚点文本：图表应紧跟的内容关键词
    anchor_type: str           # "after_paragraph" | "after_table" | "section_start" | "section_end"
```

### 5.3 渲染层改动

> **关键设计决策**：锚点匹配在 Markdown → HTML 转换**之前**执行，在原始内容中定位锚点文本，标记插入行号，转换后按行号定位插入。

#### 5.3.1 整体流程（修正版）

```
原始 Markdown 内容 + ChartPlan[]
    │
    ▼
Step 1: 在 Markdown 中定位锚点文本 → 记录行号
Step 2: Markdown → HTML 转换（现有 _content_to_html 逻辑）
Step 3: 按 行号 → HTML 位置 的映射，在对应位置插入 <figure>
Step 4: section_end 类型的图表追加到 HTML 末尾
```

**为什么不在 HTML 中做锚点匹配？**

HTML 经过 `_inline_markdown` 处理后存在三个问题：
1. `html.escape()` 会转义特殊字符（`&` → `&amp;`）
2. `<strong>`/`<em>` 等行内标签会打断文本，正则 `[^<]*` 匹配断裂
3. 表格可能被渲染为 HTML `<table>` 而非 Markdown 原文，caption 结构不同

在 Markdown 中定位更可靠，因为文本未经转义和标签嵌套。

#### 5.3.2 content_orchestrator.py 改动

`_content_to_html` 保持 `@staticmethod` 签名不变，锚点插入作为独立的后处理步骤：

```python
# 新增方法（非 staticmethod）
def _insert_charts_into_html(self, html: str, charts: List[Dict], original_content: str) -> str:
    """
    在 HTML 中插入图表（锚点定位）
    
    Args:
        html: 已转换的 HTML 内容
        charts: 图表信息列表（含 insertion_anchor, anchor_type, path, caption）
        original_content: 原始 Markdown 内容（用于锚点定位）
    """
    if not charts:
        return html
    
    # Step 1: 在 Markdown 中定位锚点行号
    md_lines = original_content.split('\n')
    anchor_line_map = {}  # chart_index → md_line_number
    
    for idx, chart in enumerate(charts):
        anchor = chart.get("insertion_anchor", "")
        anchor_type = chart.get("anchor_type", "section_end")
        
        if anchor_type == "section_end" or not anchor:
            anchor_line_map[idx] = None  # 追加到末尾
            continue
        
        if anchor_type == "section_start":
            anchor_line_map[idx] = 0  # 插入到开头
            continue
        
        # 在 Markdown 中搜索锚点文本
        best_line = None
        for line_no, line in enumerate(md_lines):
            if anchor in line:
                best_line = line_no
                break
        
        if best_line is None:
            # 模糊匹配：锚点关键词
            core_words = self._extract_core_words(anchor)
            for word in core_words[:3]:
                for line_no, line in enumerate(md_lines):
                    if word in line:
                        best_line = line_no
                        break
                if best_line is not None:
                    break
        
        anchor_line_map[idx] = best_line  # None 表示匹配失败
    
    # Step 2: 将 Markdown 行号映射到 HTML 块位置
    # 策略：_content_to_html 按行处理，每个非空行生成一个 HTML 块
    # 通过行号计数器建立对应关系
    html_blocks = html.split('\n')
    
    # 建立 Markdown 行号 → HTML 块索引的映射
    # _content_to_html 跳过空行，非空行各生成一个 HTML 元素
    md_to_html_idx = {}
    html_block_idx = 0
    for md_line_no, md_line in enumerate(md_lines):
        if md_line.strip():
            md_to_html_idx[md_line_no] = html_block_idx
            # 一个 Markdown 行可能生成多行 HTML（如表格）
            # 简化处理：每个非空行对应 html_blocks 中的一个块
            html_block_idx += 1
    
    # Step 3: 按 Markdown 行号在 HTML 中插入图表
    # 从后往前插入（避免索引偏移）
    insertions = []  # [(html_insert_position, chart_html)]
    
    for idx, chart in enumerate(charts):
        chart_html = self._render_chart_figure(chart)
        md_line = anchor_line_map.get(idx)
        
        if md_line is None:
            # 匹配失败或 section_end，追加到末尾
            insertions.append((len(html_blocks), chart_html))
        elif md_line == 0:
            # section_start，插入到开头
            insertions.append((0, chart_html))
        else:
            # 找到锚点行，在其后插入
            # 需要找到该 Markdown 行对应的 HTML 块结束位置
            html_idx = md_to_html_idx.get(md_line)
            if html_idx is not None:
                # 插入到该 HTML 块之后
                insertions.append((html_idx + 1, chart_html))
            else:
                insertions.append((len(html_blocks), chart_html))
    
    # 从后往前执行插入
    for pos, chart_html in sorted(insertions, key=lambda x: x[0], reverse=True):
        html_blocks.insert(pos, chart_html)
    
    return '\n'.join(html_blocks)
```

#### 5.3.3 _prepare_template_variables 中的调用

```python
# _prepare_template_variables 改动：
section_dict = {
    "id": section.id,
    "title": section.title,
    # 先转为 HTML，再插入图表
    "content": self._insert_charts_into_html(
        self._content_to_html(section.content) if section.content else "",
        charts_data,
        section.content or ""
    ),
    # ...
    "charts": [],  # HTML: 图表已嵌入content，模板不循环渲染
}
```

#### 5.3.4 多格式输出策略

不同输出格式的图表插入策略不同：

| 输出格式 | 图表插入方式 | 说明 |
|----------|-------------|------|
| **HTML** | `_insert_charts_into_html` 锚点插入 | 完整支持 |
| **DOCX** | 保持模板循环渲染 `section.charts` | 锚点暂不实现，图表仍在章节末尾 |
| **PPTX** | 保持模板循环渲染 | 同DOCX |

具体实现：

```python
# _prepare_template_variables 中：
if output_format == "html":
    section_dict["content"] = self._insert_charts_into_html(
        self._content_to_html(section.content) if section.content else "",
        charts_data,
        section.content or ""
    )
    section_dict["charts"] = []  # 已嵌入content
else:
    # DOCX/PPTX: 图表由模板渲染，不嵌入content
    section_dict["content"] = self._content_to_html(section.content) if section.content else ""
    section_dict["charts"] = charts_data  # 保留给模板循环渲染
```

#### 5.3.5 模板改动

**仅 HTML 模板**移除图表循环渲染（DOCX模板保持不变）：

```html
<!-- word_default.html：保留 section.charts 循环渲染（DOCX需要） -->
<!-- HTML输出时 section.charts 为空列表，循环不执行，图表已嵌入content -->
{% for chart in section.charts %}
<figure class="chart-container">
  <img src="{{ chart.path }}" alt="{{ chart.caption }}" style="max-width:100%">
  <figcaption class="figure-caption">{{ chart.caption }}</figcaption>
</figure>
{% endfor %}
```

---

## 6. 数据结构定义

### 6.1 ExtractedTable

预过滤阶段的中间数据结构：

```python
@dataclass
class ExtractedTable:
    headers: List[str]           # 表头
    rows: List[List[str]]        # 原始行数据（含文本、单位）
    numeric_columns: List[int]   # 数值列索引
    raw_text: str                # 原始Markdown文本
```

### 6.2 ChartPlan

核心输出结构，LLM输出的图表方案：

```python
@dataclass
class ChartPlan:
    chart_type: ChartType        # 图表类型 (bar/hbar/line/pie/radar/waterfall/...)
    title: str                   # 图表标题（具体语义，如"比亚迪2025年盈利能力指标"）
    subtitle: str                # 副标题（数据来源说明，如"数据来源：2025年年报"）
    data: Dict[str, Any]         # 标准化数据（已统一量纲，见6.3）
    caption: str                 # 图注（解释图表含义，如"图1：比亚迪净利润率远低于同行"）
    xlabel: str                  # X轴标签
    ylabel: str                  # Y轴标签（含单位，如"净利润率（%）"）
    confidence: float            # LLM对该图表的信心度 0-1
    reason: str                  # LLM选择该图表类型的理由
    insertion_anchor: str        # 锚点：图表应紧跟哪段内容之后
    anchor_type: str             # "after_paragraph" | "after_table" | "section_start" | "section_end"
    unit: str                    # 数据单位（如"亿元"、"%"、"万辆"）
```

### 6.3 data 字段标准化格式

不同图表类型的 `data` 字段必须遵循以下格式：

#### 柱状图 / 水平柱状图 (bar / hbar)

```python
{
    "categories": ["营收", "净利润", "研发投入"],    # 类别标签
    "values": [8040, 326, 580],                    # 数值（已统一量纲）
    "unit": "亿元"                                  # 单位
}
```

#### 分组柱状图（多系列对比）

```python
{
    "categories": ["2024", "2025", "2026E"],
    "series": [
        {"name": "比亚迪", "values": [17.0, 17.23, 16.5], "unit": "%"},
        {"name": "特斯拉", "values": [25.0, 23.0, 22.0], "unit": "%"},
    ]
}
```

#### 折线图 (line)

```python
{
    "years": ["2022", "2023", "2024", "2025"],     # 必须是有序序列
    "scenarios": {
        "实际值": [180, 300, 460, 460],            # 单位统一
        "目标值": [200, 350, 500, 700],
    },
    "unit": "万辆"
}
```

#### 饼图 (pie)

```python
{
    "labels": ["比亚迪", "特斯拉", "吉利", "其他"],
    "values": [38, 12, 8, 42],                     # 百分比或绝对值
    "unit": "%"
}
```

#### 雷达图 (radar)

```python
{
    "categories": ["成本控制", "技术领先", "品牌力", "渠道覆盖", "海外扩张"],
    "values": [90, 85, 70, 80, 60],                # 0-100评分
    "unit": "分"
}
```

#### 瀑布图 (waterfall)

```python
{
    "factors": [
        {"label": "2024年净利润", "value": 290, "is_total": True},
        {"label": "销量增长", "value": 80},
        {"label": "价格下降", "value": -30},
        {"label": "研发投入增加", "value": -14},
        {"label": "2025年净利润", "value": 326, "is_total": True},
    ],
    "unit": "亿元"
}
```

### 6.4 LLM 输出 JSON Schema

LLM 输出必须严格遵循以下 JSON Schema：

```json
{
    "charts": [
        {
            "chart_type": "bar",
            "title": "比亚迪2025年盈利能力指标",
            "subtitle": "数据来源：2025年年报",
            "data": {
                "categories": ["营收", "净利润", "研发投入"],
                "values": [8040, 326, 580],
                "unit": "亿元"
            },
            "caption": "图1：比亚迪净利润率仅4.1%，远低于行业平均水平",
            "xlabel": "指标",
            "ylabel": "金额（亿元）",
            "confidence": 0.9,
            "reason": "三组绝对值数据量纲统一（亿元），适合柱状图对比",
            "insertion_anchor": "净利润326.0亿元",
            "anchor_type": "after_paragraph",
            "unit": "亿元"
        }
    ],
    "skip_reason": null
}
```

当 LLM 判断无法生成有效图表时：

```json
{
    "charts": [],
    "skip_reason": "数据源与章节主题不匹配，无法生成有效图表"
}
```

---

## 7. LLM Prompt 设计

### 7.1 System Prompt

```
你是一个专业的数据可视化规划师。你的任务是分析研究报告的章节内容，判断哪些数据适合可视化，并规划图表方案。

## 核心原则

1. **宁缺毋滥**：每章节最多2张图表。如果数据不适合可视化，输出空列表。
2. **语义优先**：图表标题必须传达具体洞察，如"比亚迪净利润率远低于同行"，而非"份额对比"。
3. **量纲一致**：同一图表中的数值必须量纲统一。百分比(%)与绝对值(亿元)不能同图。
4. **主题相关**：如果数据与章节主题无关（如比亚迪报告出现B站/船舶数据），拒绝生成图表。
5. **类型匹配**：根据数据特征选择图表类型，而非一律柱状图。

## 图表类型选择规则

| 数据特征 | 推荐图表类型 | 条件 |
|----------|-------------|------|
| 不同类别的数值对比 | bar | 类别数 ≤ 12，量纲一致 |
| 排名/排行对比 | hbar | 适合展示排名 |
| 时间序列趋势 | line | categories必须是有序时间序列 |
| 构成/占比分布 | pie | 类别数 ≤ 6，值非负 |
| 多维度评估 | radar | 维度数 3-8，值0-100 |
| 增减拆解 | waterfall | 有正有负的累计变化 |
| 多组对比 | bar (分组) | 2-3组系列，量纲一致 |

## 插入位置规则

| 场景 | anchor_type | insertion_anchor |
|------|-------------|-----------------|
| 图表是对某段分析的可视化 | after_paragraph | 该段的关键短语(10-20字) |
| 图表是对表格数据的可视化 | after_table | 表格的caption或标题关键词 |
| 图表是章节总览/概要 | section_start | 章节标题 |
| 图表是章节总结 | section_end | 章节标题 |

## 输出格式

严格输出JSON，不要输出其他内容：
{schema}
```

### 7.2 User Prompt

```
## 研究主题
{topic}

## 当前章节
{section_title}

## 章节内容
{content_summary}

## 可用表格数据
{filtered_tables_json}

---

请分析上述内容，规划图表方案。注意：
1. 只使用与"{topic}"主题相关的数据
2. 如果数据源与主题无关，输出空列表并说明原因
3. 每张图表的标题必须传达具体的分析洞察
4. 量纲不一致的数据不能放在同一张图表中
5. 图表的insertion_anchor应选择正文中实际存在的关键短语
```

### 7.3 内容摘要策略

为控制LLM输入token量，章节内容需要摘要：

- **表格数据**：完整保留，因为这是图表的数据来源
- **正文内容**：截取前2000字 + 提取所有包含数值的句子 + **每个段落的首句**（作为锚点候选）
- **总输入控制**：不超过4000 tokens

**为什么需要段落首句？** LLM输出的 `insertion_anchor` 必须引用正文中实际存在的文本。如果摘要只取前2000字，LLM无法感知后续段落的存在，输出的锚点可能指向它没见过的文本，导致匹配失败。段落首句让LLM知道每个段落的主题和关键词，从而选择合理的锚点。

```python
def _prepare_llm_input(self, content: str, tables: List[ExtractedTable]) -> Tuple[str, str]:
    """
    准备LLM输入，控制token量
    
    策略：
    1. 正文：取前2000字 + 含数值的句子 + 段落首句（锚点候选）
    2. 表格：完整保留（序列化为JSON）
    """
    # 提取含数值的句子
    numeric_sentences = []
    for line in content.split('\n'):
        if re.search(r'\d+\.?\d*[万亿%％]?', line):
            numeric_sentences.append(line.strip())
    
    # 提取段落首句（锚点候选）
    # 段落定义：非空行，且前一行是空行或文件开头
    paragraph_first_sentences = []
    prev_empty = True
    for line in content.split('\n'):
        if line.strip() and prev_empty:
            # 取第一个句号前的内容（首句）
            first_sentence = re.split(r'[。！？；]', line.strip())[0]
            if len(first_sentence) > 5:  # 过滤太短的
                paragraph_first_sentences.append(first_sentence[:50])
        prev_empty = not line.strip()
    
    # 正文摘要
    content_summary = content[:2000]
    if numeric_sentences:
        content_summary += '\n\n关键数据句：\n' + '\n'.join(numeric_sentences[:20])
    if paragraph_first_sentences:
        content_summary += '\n\n段落首句（可选锚点位置）：\n' + '\n'.join(paragraph_first_sentences[:30])
    
    # 表格数据
    tables_json = json.dumps(
        [{"headers": t.headers, "rows": t.rows, "topic_relevance": getattr(t, 'topic_relevance', 'unknown')} for t in tables],
        ensure_ascii=False, indent=2
    )
    
    return content_summary, tables_json
```

---

## 8. 集成方案

### 8.1 改动点1：GenericAgent

在 `generic_agent.py` 中，将 `_generate_charts_from_content` 方法的实现替换为调用 ChartPlannerAgent，并在外部完成渲染：

```python
# src/core/agents/generic_agent.py

# 改动前 (line 1288-1296):
charts = await self._generate_charts_from_content(
    content, search_topic, aspect
)
if charts:
    result["charts"] = charts

# 改动后:
from src.services.chart_planner import ChartPlannerAgent
from src.services.chart_generator import ChartGenerator, ChartConfig, ChartType

chart_planner = ChartPlannerAgent(output_dir=str(Path("output/charts")))
chart_plans = await chart_planner.plan(
    content=result.get("content", ""),
    topic=topic,
    section_title=aspect,
)

# 渲染图表（规划与渲染分离）
charts = []
if chart_plans:
    chart_generator = ChartGenerator(output_dir=str(Path("output/charts")))
    for plan in chart_plans:
        try:
            config = ChartConfig(
                chart_type=plan.chart_type,
                title=plan.title,
                data=plan.data,
                xlabel=plan.xlabel,
                ylabel=plan.ylabel,
                caption=plan.caption,
            )
            render_result = chart_generator.generate(config)
            if render_result.success and render_result.image_path:
                charts.append({
                    "chart_type": plan.chart_type.value,
                    "title": plan.title,
                    "path": render_result.image_path,
                    "caption": plan.caption,
                    "aspect": aspect,
                    "insertion_anchor": plan.insertion_anchor,
                    "anchor_type": plan.anchor_type,
                })
        except Exception:
            logger.exception(f"Chart rendering failed for plan: {plan.title}")

if charts:
    result["charts"] = charts
```

### 8.2 改动点2：ContentOrchestrator

在 `content_orchestrator.py` 中，新增 `_insert_charts_into_html` 方法，并在 `_prepare_template_variables` 中根据输出格式选择插入策略：

```python
# src/content/content_orchestrator.py

# _prepare_template_variables 改动：
# 根据输出格式决定图表插入方式
if output_format == "html":
    # HTML: 锚点插入到content中
    section_dict = {
        "id": section.id,
        "title": section.title,
        "content": self._insert_charts_into_html(
            self._content_to_html(section.content) if section.content else "",
            charts_data,
            section.content or "",
        ),
        "charts": [],  # 已嵌入content，模板不循环渲染
    }
else:
    # DOCX/PPTX: 图表由模板渲染，不嵌入content
    section_dict = {
        "id": section.id,
        "title": section.title,
        "content": self._content_to_html(section.content) if section.content else "",
        "charts": charts_data,  # 保留给模板循环渲染
    }
```

> **注意**：`_content_to_html` 保持 `@staticmethod` 不变。`_insert_charts_into_html` 是新增的实例方法，调用 `_content_to_html` 的输出作为输入。

### 8.3 改动点3：模板文件

**模板文件不做修改。** 模板中的 `section.charts` 循环渲染保留：

- HTML输出时：`section.charts` 传入空列表，循环不执行，图表已通过 `_insert_charts_into_html` 嵌入content
- DOCX/PPTX输出时：`section.charts` 传入完整图表列表，模板循环渲染在章节末尾（锚点插入暂不实现）

### 8.4 改动点4：Feature Flag

通过配置控制是否启用新的图表规划系统：

```python
# src/config/settings.py

CHART_PLANNER_ENABLED: bool = True    # 是否启用ChartPlannerAgent
CHART_PLANNER_MAX_PER_SECTION: int = 2  # 每章节最大图表数
CHART_PLANNER_MIN_CONFIDENCE: float = 0.5  # 最低置信度
```

当 `CHART_PLANNER_ENABLED = False` 时，降级回原有正则提取逻辑。

---

## 9. 降级与容错

### 9.1 降级链

```
ChartPlannerAgent (LLM语义分析)
    ↓ LLM调用失败
规则引擎降级 (无LLM，基于表格结构判断)
    ↓ 规则引擎也无法生成
无图表 (返回空列表，不生成无意义图表)
```

**关键原则：宁可没有图表，也不要生成无意义的图表。**

### 9.2 具体降级策略

| 故障场景 | 降级行为 |
|----------|---------|
| LLM调用超时/失败 | 规则引擎降级：检查表格结构，只生成量纲一致的简单柱状图 |
| LLM输出JSON解析失败 | 重试1次，仍失败则跳过图表 |
| LLM输出的chart_type不存在 | 降级为bar |
| 锚点匹配失败 | 降级为section_end（章节末尾） |
| 数值列提取失败 | 跳过该图表 |
| ChartPlan校验不通过 | 跳过该图表 |

### 9.3 日志与监控

```python
logger.info(f"ChartPlanner: section='{section_title}', "
            f"tables_found={len(tables)}, "
            f"tables_after_filter={len(filtered)}, "
            f"plans_generated={len(plans)}, "
            f"plans_after_validation={len(validated)}")
```

---

## 10. 修改清单

### 10.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `src/services/chart_planner.py` | ChartPlannerAgent 实现 |

### 10.2 修改文件

| 文件路径 | 修改内容 |
|----------|---------|
| `src/core/agents/generic_agent.py` | `_generate_charts_from_content` 替换为调用 ChartPlannerAgent + ChartGenerator 渲染 |
| `src/content/content_orchestrator.py` | 新增 `_insert_charts_into_html` 方法；`_prepare_template_variables` 按输出格式分流图表数据 |
| `src/config/settings.py` | 新增 CHART_PLANNER_* 配置项 |

### 10.3 不修改文件

| 文件路径 | 原因 |
|----------|------|
| `src/services/chart_generator.py` | 渲染层无需改动，仅被调用方变更 |
| `src/core/orchestrator/aggregation/result_aggregator.py` | charts数据流不变 |
| `src/core/orchestrator/orchestrator.py` | 不涉及 |

---

## 11. 测试方案

### 11.1 单元测试

| 测试类 | 测试用例 | 验证点 |
|--------|---------|--------|
| TestPrefilter | test_pure_text_table_filtered | 纯文本表格被过滤 |
| TestPrefilter | test_all_zero_values_filtered | 全零值表格被过滤 |
| TestPrefilter | test_mixed_table_passes | 数值列占比>30%的表格通过 |
| TestValidate | test_unit_inconsistency_rejected | 百分比+绝对值同图被拒绝 |
| TestValidate | test_pie_negative_values_rejected | 饼图含负值被拒绝 |
| TestValidate | test_confidence_threshold | confidence<0.5被过滤 |
| TestValidate | test_max_charts_per_section | 最多2张图表 |
| TestAnchorInsert | test_after_paragraph_insertion | 锚点匹配后正确插入 |
| TestAnchorInsert | test_after_table_insertion | 表格后正确插入 |
| TestAnchorInsert | test_anchor_fallback_to_end | 匹配失败降级到末尾 |
| TestAnchorInsert | test_section_start_insertion | 章节开头插入 |

### 11.2 集成测试

| 测试场景 | 输入 | 预期输出 |
|----------|------|---------|
| 正常财务数据章节 | 比亚迪财务表格 | 生成1-2张图表，标题语义明确，量纲一致 |
| 无关数据章节 | B站/船舶数据 | 0张图表，skip_reason不为空 |
| 混合数据章节 | 比亚迪+B站数据混合 | 仅生成比亚迪相关图表 |
| 纯文本章节 | 无表格的分析文字 | 0张图表 |
| 多量纲表格 | 营收(亿元)+利润率(%) | 分成两张图表，量纲各自一致 |

### 11.3 端到端验收标准

| 验收项 | 标准 |
|--------|------|
| 图表标题语义 | >90%的图表标题能传达具体分析洞察 |
| 图表量纲一致性 | 100%的图表内数据量纲统一 |
| 图表类型多样性 | 报告中至少出现3种不同图表类型 |
| 无关数据零图表 | 与主题无关的章节不生成图表 |
| 锚点插入成功率 | >80%的图表成功插入到正文对应位置 |
| 无降级回归 | CHART_PLANNER_ENABLED=False时，行为与改动前一致 |

---

## 附录

### A. 与v1.0设计的关系

本设计（v2.0）与 `docs/_archive/design/CHART_GENERATION_SKILL_DESIGN.md`（v1.0）的关系：

| 维度 | v1.0 | v2.0 |
|------|------|------|
| 核心思路 | 在Agent执行阶段集成ChartGenerationSkill | 后处理阶段引入ChartPlannerAgent |
| 语义理解 | 规则引擎判断图表类型 | LLM语义分析+规则引擎校验 |
| 插入位置 | 未设计 | 锚点定位插入 |
| 数据来源 | 依赖data_points字段 | 从内容中LLM分析提取 |
| 改动范围 | 修改strategies/result_aggregator/多个模块 | 仅改generic_agent/content_orchestrator/模板 |

v2.0选择后处理方案的原因：
1. 对现有系统侵入最小（不需要改strategies/result_aggregator等核心模块）
2. LLM语义理解远强于规则引擎
3. 可独立开关，降级简单

### B. 修订历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-30 | 初始设计（ChartGenerationSkill） |
| v2.0 | 2026-07-04 | 重新设计：ChartPlannerAgent + 锚点插入 |
| v2.1 | 2026-07-04 | 深度审查修正：8项关键问题修复（LLM接口、锚点匹配阶段、staticmethod兼容、DOCX多格式、规划渲染分离、摘要策略、主题相关性初筛、模板逻辑） |
