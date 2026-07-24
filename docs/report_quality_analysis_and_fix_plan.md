# HTML报告质量分析与修复计划（v2 - 基于完整代码审计）

> 分析对象：`data/html_reports/research_aa7102b6.html`
> 分析日期：2026-07-22
> 报告主题：一线城市儿童乐园市场研究
> 代码版本：v3.0.0 (c862157)

---

## 一、问题总览

| 严重级别 | 问题类别 | 问题数量 | 影响范围 |
|---------|---------|---------|---------|
| **P0-致命** | 内容渲染错误 | 3 | 全报告 |
| **P1-严重** | 结构/排版/集成缺陷 | 5 | 多章节 |
| **P2-中等** | 图表集成问题（非图表系统本身） | 4 | 全报告 |
| **P3-轻微** | 样式/细节问题 | 5 | 局部 |

---

## 二、关键发现：图表系统已更新但集成断裂

### 图表系统现状

图表生成系统在 v2.4.0 已完成重大升级，具备以下能力：

| 能力 | 实现状态 | 代码位置 |
|------|---------|---------|
| ChartPlannerAgent (LLM语义分析) | ✅ 已实现 | `chart_planner.py` (1432行) |
| 12种图表类型 | ✅ 已实现 | `chart_generator.py` (670行) |
| 每章节最多2张图 (config) | ✅ 已实现 | `settings.py:ChartPlannerConfig.max_per_section=2` |
| 置信度过滤 (≥0.5) | ✅ 已实现 | `chart_planner.py:1277` |
| 锚点定位插入 | ✅ 已实现 | `chart_planner.py` 生成 + `content_orchestrator.py:444` 插入 |
| 语义校验 (指标-数值合理性) | ✅ 已实现 | `document_generation_agent.py:1302` |
| 主动数据获取 (akshare) | ✅ 已实现 | `chart_planner.py:968-1275` |
| 图表配色 (墨蓝+暖金) | ✅ 已实现 | `chart_generator.py:106-135` PALETTE_12 |

### 集成断裂点

**问题核心**：图表系统有3条独立的生成管线，互不协调，导致图表重复生成、caption质量参差、锚点信息丢失。

```
管线1: GenericAgent (研究阶段)
  _generate_charts_with_planner() → ChartPlannerAgent → 高质量图表(含锚点)
  结果存入: result["charts"] → research_result.sections[i].charts

管线2: DocumentGenerationAgent (HTML预览阶段)  ← 实际生效的管线
  _html_charts_from_datapoints() → ChartGenerator → 通用caption图表
  _html_charts_from_content()   → SmartChartGenerator → 通用caption图表
  结果追加到: section["charts"] (可能覆盖管线1的结果)

管线3: DocumentGenerator (DOCX/PPTX阶段)
  _generate_charts_for_sections() → SmartChartGenerator → 通用caption图表
  结果追加到: section["content"] (作为<img>标签)
```

**实际报告走的是管线2**（HTML输出），而管线2使用的是 `SmartChartGenerator`（正则提取），**没有使用已升级的 `ChartPlannerAgent`**。这就是为什么报告中图表caption都是"份额对比（10项）"这种通用格式——因为 `SmartChartGenerator._generate_caption()` 就是这么写的。

---

## 三、问题详细分析

### P0-致命：内容渲染错误

#### P0-1. Markdown语法未转换，直接以纯文本输出

**位置**：全报告多处

**现象**：
- `#### 1. 市场驱动力` → `<p>#### 1. 市场驱动力</p>`，`####` 原样输出
- `- **中低端市场**` → `<p>- **中低端市场**</p>`，`-` 列表标记原样输出
- `> **注：**` → `<p>&gt; **注：**</p>`，引用标记原样输出
- `1. **市场规模测算假设风险**` → 有序列表标记原样输出

**根因**：`_content_to_html()` (`content_orchestrator.py:1031`) 缺陷：

1. **`####` 不识别**：正则 `r'^(#{1,3})\s+(.+)$'`（第1062行）只匹配1-3个`#`
2. **列表不识别**：`- item` 和 `1. item` 无解析分支
3. **引用不识别**：`> text` 无解析分支
4. **数字编号误判**：`1. **xxx**` 被 `_parse_markdown_title()` 误判为标题

**注意**：`requirements.txt` 已声明 `markdown>=3.5.0` 依赖，但代码中**未使用**。`_content_to_html()` 是手写的逐行解析器。

---

#### P0-2. JSON代码块原样输出到HTML

**位置**：section_3（客户群体画像），第672-695行

**现象**：约25行JSON结构体（含`self_check_passed`、`self_check_issues`等调试字段）被逐行渲染为`<p>`段落。

**根因**：
1. 上游Agent返回的`content`字段包含JSON代码块（Agent原始输出格式未被清洗）
2. `_content_to_html()` 不识别 ` ``` ` 围栏代码块语法
3. 无Agent输出格式校验/清洗中间层

---

#### P0-3. 章节标题显示为"章节内容"

**位置**：section_2，第597行

**现象**：`<h1 class="chapter-title">章节内容</h1>`

**根因**：上游传入的title为"章节内容"（非空但无意义），`_parse_sections()` 的空标题跳过逻辑（第759行）未触发。

---

### P1-严重：结构/排版/集成缺陷

#### P1-1. 目录页标题为空

**位置**：TOC区域，第383行

**现象**：`<h2></h2>`

**根因**：模板 `{{ labels.toc }}` 变量未在 `_prepare_template_variables()` 中设置。`variables` 字典无 `labels` 键。

**修复**：在 `variables` 中添加 `"labels": {"toc": "目 录"}`

---

#### P1-2. 章节语义重复（去重逻辑不足）

**位置**：TOC vs 正文

**现象**：12个章节中6个语义重复：
- section_0 "市场概况与规模测算" ≈ section_6 "市场规模与增长趋势" ≈ section_7 "增长趋势"
- section_2 "客单价与消费行为" ≈ section_10 "客单价与消费特征"
- section_4 "行业现存问题与风险" ≈ section_9 "存在的问题" ≈ section_11 "行业问题与痛点"

**根因**：`_dedup_sections()` (`content_orchestrator.py:883`) 仅基于标题精确匹配去重，标题略有不同即无法去重。缺少语义相似度判断。

---

#### P1-3. 数据表格双重渲染

**位置**：每个section末尾

**现象**：每个章节在正文内已有`data-table`，末尾又出现一张`Metric|Value|Unit`汇总表，内容重复。

**根因**：
1. `_content_to_html()` 将Markdown表格转为HTML `<table class="data-table">`
2. `_prepare_template_variables()` 第248-267行又将`data_points`转为`section_tables`
3. 模板第459-481行渲染`section.tables`，形成第二张表

---

#### P1-4. 图表管线2未使用ChartPlannerAgent（集成断裂）

**位置**：`document_generation_agent.py:1292-1450`

**现象**：HTML报告的图表caption为"份额对比（10项）"等通用格式，而非ChartPlannerAgent生成的语义化caption。

**根因**：`_generate_charts_for_html()` 调用的是：
- `_html_charts_from_datapoints()` → 直接用 `ChartGenerator`（无LLM规划）
- `_html_charts_from_content()` → 用 `SmartChartGenerator`（正则提取）

而 `GenericAgent._generate_charts_with_planner()` 使用的 `ChartPlannerAgent`（LLM语义分析）的结果**已被管线2覆盖或忽略**。

**具体流程**：
1. 研究阶段：`GenericAgent` 用 `ChartPlannerAgent` 生成高质量图表 → 存入 `section["charts"]`
2. HTML生成阶段：`DocumentGenerationAgent._generate_charts_for_html()` 再次调用 `_html_charts_from_datapoints()` + `_html_charts_from_content()` → **追加**到 `section["charts"]`
3. 结果：每个section可能有3-5张图表（管线1的1-2张 + 管线2的2-3张），且caption风格不一致

---

#### P1-5. 封面空作者

**位置**：封面页

**现象**：`<p class="meta"><br>2026-07-21</p>`

**根因**：`author` 变量为空，模板 `{{ author }}<br>{{ date }}` 输出空`<br>`。

---

### P2-中等：图表集成问题

#### P2-1. 图表caption通用化（SmartChartGenerator问题，非ChartPlannerAgent问题）

**根因**：`SmartChartGenerator._generate_caption()` (`smart_chart_generator.py:725-737`) 使用硬编码模板：
```python
cn_captions = {
    "market_share": "份额对比",
    "ranking": "排名对比",
    ...
}
return f"图：{base}（{len(categories)}项）"
```

而 `ChartPlannerAgent` 生成的caption是LLM语义化的。**问题在于管线2用了SmartChartGenerator而非ChartPlannerAgent**。

**修复方向**：不是修改SmartChartGenerator，而是让管线2复用管线1的ChartPlannerAgent结果。

---

#### P2-2. 图表数量超标（每section 3张而非2张）

**现象**：section_0有3张图，section_1有3张图...

**根因**：
- `ChartPlannerConfig.max_per_section=2` 只约束 `ChartPlannerAgent`
- `_html_charts_from_datapoints()` 无数量限制（生成1张）
- `_html_charts_from_content()` 硬编码 `suggestions[:2]`（最多2张）
- 两条管线叠加 → 最多3张

**修复方向**：在 `_generate_charts_for_html()` 中增加总数控制，或优先使用管线1结果。

---

#### P2-3. 图表锚点信息在管线2中丢失

**现象**：所有图表集中在章节末尾。

**根因**：
- 管线1 (`ChartPlannerAgent`) 生成的图表包含 `insertion_anchor` 和 `anchor_type`
- 管线2 (`SmartChartGenerator`) 生成的图表**不含锚点信息**
- `_html_charts_from_datapoints()` 第1399-1403行追加的图表无 `insertion_anchor`/`anchor_type`
- `_html_charts_from_content()` 第1440-1444行追加的图表也无锚点
- `_insert_charts_into_html()` 对无锚点的图表默认插入到末尾

---

#### P2-4. 图表配色已统一但PALETTE_12有重复色

**现状**：`ChartGenerator` 的 `PALETTE_12` 已使用墨蓝+暖金配色，与报告模板一致。但第11色与第1色重复（都是gold）。

**修复**：将 `PALETTE_12[11]` 改为不同颜色。

---

### P3-轻微：样式/细节问题

#### P3-1. CSS类名冲突

`<div class="section-content">` 内的 `<p class="section-content">` 类名重复。

#### P3-2. HTML实体二次转义

`客单价&lt;200元` 应显示为 `客单价<200元`。`_inline_markdown()` 对已有HTML实体二次转义。

#### P3-3. 封面Logo src为空

`logo_path` 为空时仍输出 `<img src="">`。

#### P3-4. 标题层级跳跃

章节h1后直接跳到h4，缺少h2/h3。`_content_to_html()` 的标题映射逻辑不合理。

#### P3-5. section_3内容完全缺失

只有JSON代码块，无正常分析文本。需Agent输出清洗。

---

## 四、根因汇总（按修复优先级排序）

| 编号 | 根因 | 涉及问题 | 修复位置 | 是否需要新代码 |
|------|------|---------|---------|-------------|
| **R1** | 图表管线2未复用管线1的ChartPlannerAgent结果 | P1-4, P2-1, P2-2, P2-3 | `document_generation_agent.py:1292` | 否，改集成逻辑 |
| **R2** | `_content_to_html()` Markdown解析不完整 | P0-1, P3-1, P3-4 | `content_orchestrator.py:1031` | 是，补解析分支 |
| **R3** | 不识别围栏代码块 ` ``` ` | P0-2 | `content_orchestrator.py:1031` | 是，新增分支 |
| **R4** | 上游Agent输出未校验/清洗 | P0-2, P0-3, P3-5 | 新增清洗层 | 是，新模块 |
| **R5** | 模板变量 `labels` 未设置 | P1-1 | `content_orchestrator.py:400` | 否，加一行 |
| **R6** | 章节去重仅精确标题匹配 | P1-2 | `content_orchestrator.py:883` | 是，加语义去重 |
| **R7** | 数据表格双重渲染 | P1-3 | 模板 + `content_orchestrator.py:248` | 否，改模板/逻辑 |
| **R8** | HTML实体二次转义 | P3-2 | `content_orchestrator.py:1227` | 否，改逻辑 |
| **R9** | PALETTE_12重复色 | P2-4 | `chart_generator.py:134` | 否，改一个值 |

---

## 五、修复计划

### Phase 1：图表集成修复（最高优先级，影响面最大）

#### 1.1 修复 `_generate_charts_for_html()` 集成逻辑

**文件**：`src/agents/fixed_agents/document_generation_agent.py`
**方法**：`_generate_charts_for_html()` (第1292行)

**当前逻辑**：
```python
def _generate_charts_for_html(self, research_result):
    self._html_charts_from_datapoints(research_result)  # 管线2a
    self._html_charts_from_content(research_result)      # 管线2b
    return research_result
```

**修复为**：
```python
def _generate_charts_for_html(self, research_result):
    """为 HTML 报告生成图表：优先复用管线1结果，不足时补充"""
    if not research_result.get("sections"):
        return research_result

    for section in research_result["sections"]:
        existing_charts = section.get("charts", [])
        
        # 管线1 (ChartPlannerAgent) 的图表已有锚点信息，优先保留
        planner_charts = [c for c in existing_charts if c.get("insertion_anchor") or c.get("anchor_type")]
        
        if len(planner_charts) >= 2:
            # 管线1已生成足够图表，仅保留管线1结果
            section["charts"] = planner_charts[:2]
            continue
        
        # 管线1不足2张，用管线2补充（但总数不超过2）
        needed = 2 - len(planner_charts)
        
        # 先尝试从data_points生成（更可靠）
        if needed > 0:
            dp_chart = self._generate_single_datapoints_chart(section)
            if dp_chart:
                planner_charts.append(dp_chart)
                needed -= 1
        
        # 再从content文本提取
        if needed > 0:
            content_charts = self._generate_content_charts(section, max_count=needed)
            planner_charts.extend(content_charts[:needed])
        
        section["charts"] = planner_charts[:2]

    return research_result
```

**关键改动**：
1. 检测管线1已有图表（含`insertion_anchor`/`anchor_type`的为管线1产物）
2. 管线1图表优先保留（有锚点、caption语义化）
3. 管线2仅补充不足部分，总数硬限2张
4. 不再无条件追加，避免3-5张图表

#### 1.2 为管线2图表补充锚点信息

**文件**：`src/agents/fixed_agents/document_generation_agent.py`

**`_html_charts_from_datapoints()`** 第1399-1403行，追加图表时增加锚点：
```python
existing.append({
    "path": result.image_path,
    "caption": f"{section.get('title', '')} - 关键数据",
    "section_title": section.get("title", ""),
    "insertion_anchor": "",  # 新增
    "anchor_type": "section_end",  # 新增
})
```

**`_html_charts_from_content()`** 第1440-1444行，同样补充：
```python
existing.append({
    "path": chart_path,
    "caption": suggestion.caption or title,
    "section_title": title,
    "insertion_anchor": "",  # 新增
    "anchor_type": "section_end",  # 新增
})
```

#### 1.3 修复PALETTE_12重复色

**文件**：`src/services/chart_generator.py` 第134行

```python
# 修改前：
(201/255, 162/255, 39/255),   # gold variant (DUPLICATE)

# 修改后：
(107/255, 142/255, 158/255),  # steel teal
```

---

### Phase 2：Markdown解析修复

#### 2.1 完善 `_content_to_html()`

**文件**：`src/content/content_orchestrator.py`
**方法**：`_content_to_html()` (第1031行起)

**新增解析分支**（在现有heading检测之后、Normal paragraph之前插入）：

```python
# === 新增：围栏代码块 ===
if stripped.startswith('```'):
    lang = stripped[3:].strip()
    code_lines = []
    i += 1
    while i < len(lines):
        if lines[i].strip().startswith('```'):
            i += 1
            break
        code_lines.append(lines[i])
        i += 1
    # JSON代码块：尝试提取content字段
    if lang == 'json':
        try:
            import json
            data = json.loads('\n'.join(code_lines))
            if isinstance(data, dict) and 'content' in data:
                result.append(self._content_to_html(data['content']))
                continue
        except Exception:
            pass
    result.append(f'<pre class="code-block"><code>{html.escape(chr(10).join(code_lines))}</code></pre>')
    continue

# === 新增：无序列表 ===
if stripped.startswith('- ') or stripped.startswith('* '):
    list_items = []
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('- ') or line.startswith('* '):
            item_text = line[2:].strip()
            list_items.append(f'<li>{ContentOrchestrator._inline_markdown(item_text)}</li>')
            i += 1
        elif line.startswith('  ') and not line.startswith('    '):
            # 嵌套列表项暂不处理，归入当前项
            i += 1
        else:
            break
    result.append(f'<ul>{chr(10).join(list_items)}</ul>')
    continue

# === 新增：有序列表 ===
ol_match = re.match(r'^(\d+)[\.、]\s+(.+)$', stripped)
if ol_match and not re.match(r'^\d+[\.、，．]\s*[（(]?[一二三四五六七八九十百千]+', stripped):
    # 排除中文编号标题（已在上面处理）
    list_items = []
    while i < len(lines):
        line = lines[i].strip()
        ol_m = re.match(r'^(\d+)[\.、]\s+(.+)$', line)
        if ol_m and not re.match(r'^\d+[\.、，．]\s*[（(]?[一二三四五六七八九十百千]+', line):
            list_items.append(f'<li>{ContentOrchestrator._inline_markdown(ol_m.group(2))}</li>')
            i += 1
        else:
            break
    result.append(f'<ol>{chr(10).join(list_items)}</ol>')
    continue

# === 新增：引用块 ===
if stripped.startswith('> '):
    quote_lines = []
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('> '):
            quote_lines.append(line[2:])
            i += 1
        else:
            break
    quote_text = ContentOrchestrator._inline_markdown(' '.join(quote_lines))
    result.append(f'<blockquote class="quote-block">{quote_text}</blockquote>')
    continue
```

**修改标题正则**（第1062行）：
```python
# 修改前：
hm = re.match(r'^(#{1,3})\s+(.+)$', stripped)

# 修改后：支持1-6级标题
hm = re.match(r'^(#{1,6})\s+(.+)$', stripped)
```

**修改标题层级映射**（第1070行）：
```python
# 修改前：
tag = f'h{min(level + 1, 4)}'
result.append(f'<{tag} class="subsection-title">{text}</{tag}>')

# 修改后：合理映射层级和CSS类
tag = f'h{min(level + 1, 6)}'
class_map = {
    2: 'section-title',      # # → h2
    3: 'subsection-title',   # ## → h3
    4: 'sub-subsection-title', # ### → h4
}
css_class = class_map.get(min(level + 1, 4), '')
class_attr = f' class="{css_class}"' if css_class else ''
result.append(f'<{tag}{class_attr}>{text}</{tag}>')
```

#### 2.2 修复标题解析误判

**文件**：`src/content/content_orchestrator.py`
**方法**：`_parse_markdown_title()` (第700行起)

```python
# 数字编号匹配中，排除以 ** 开头的内容（有序列表项而非标题）
num_match = re.match(r'^\d+[\.、，．]\s*(.*)$', stripped)
if num_match:
    raw_title = num_match.group(1).strip()
    # 新增：以 ** 或 * 开头的是列表项，不是标题
    if raw_title.startswith('**') or raw_title.startswith('*'):
        break  # 不提取标题，保留原始内容
    extracted_title = raw_title if raw_title else stripped
    body_start = i + 1
    break
```

---

### Phase 3：Agent输出清洗与结构修复

#### 3.1 新增内容清洗层

**文件**：新建 `src/content/content_cleaner.py`

```python
class ContentCleaner:
    """清洗上游Agent输出，确保格式合规"""
    
    # 无意义标题黑名单
    TITLE_BLACKLIST = {"章节内容", "Section Content", "内容", "正文", "Content"}
    
    @classmethod
    def clean_section(cls, section_data: Dict) -> Dict:
        """清洗单个section数据"""
        # 1. 清洗标题
        title = section_data.get("title", "").strip()
        if title in cls.TITLE_BLACKLIST:
            section_data["title"] = ""
        
        # 2. 清洗content中的JSON代码块
        content = section_data.get("content", "")
        content = cls._extract_json_content(content)
        section_data["content"] = content
        
        # 3. 移除内部调试字段
        # (如果content是JSON且含self_check_*字段，已在_extract_json_content中处理)
        
        return section_data
    
    @classmethod
    def _extract_json_content(cls, content: str) -> str:
        """从JSON代码块中提取实际内容"""
        stripped = content.strip()
        if not stripped.startswith('```json'):
            return content
        
        import json
        lines = stripped.split('\n')
        # 找到代码块边界
        code_start = 1
        code_end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip().startswith('```'):
                code_end = i
                break
        
        json_str = '\n'.join(lines[code_start:code_end])
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and 'content' in data:
                return data['content']
        except Exception:
            pass
        
        return content
```

**调用位置**：`_parse_sections() 中，在调用 `_parse_markdown_title()` 之前：
```python
# 在 _parse_sections() 的循环中，第750行前插入：
from src.content.content_cleaner import ContentCleaner
data = ContentCleaner.clean_section(data)
```

#### 3.2 修复模板变量缺失

**文件**：`src/content/content_orchestrator.py`
**方法**：`_prepare_template_variables()` 第400行

在 `variables` 字典中添加：
```python
"labels": {
    "toc": "目 录",
    "findings": "关键发现",
    "data": "核心数据",
},
```

#### 3.3 修复数据表格双重渲染

**方案**：在 `_prepare_template_variables()` 中，当 `section.content` 已包含 `<table` 时，不生成 `section_tables`：

```python
# 第248行附近，修改条件：
section_content_html = section_dict.get("content", "")
if raw_section.get("tables") and "<table" not in section_content_html:
    section_tables = raw_section["tables"]
elif raw_section.get("data_points") and "<table" not in section_content_html:
    ...
else:
    section_tables = []
```

#### 3.4 增强章节去重

**文件**：`src/content/content_orchestrator.py`
**方法**：`_dedup_sections()` (第883行)

在精确匹配去重后，增加一轮关键词Jaccard相似度去重：

```python
# 精确去重后，对结果再做模糊去重
def _extract_keywords(title: str) -> set:
    stop_words = {'的', '与', '和', '及', '等', '中', '在', '对', '分析', '研究', '问题', '市场', '行业'}
    words = set(re.findall(r'[\u4e00-\u9fff]{2,}', title))
    return words - stop_words

def _jaccard(s1: set, s2: set) -> float:
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)

# 对result列表做O(n²)比较
to_remove = set()
for i in range(len(result)):
    if i in to_remove:
        continue
    kw_i = _extract_keywords(result[i].title)
    for j in range(i + 1, len(result)):
        if j in to_remove:
            continue
        kw_j = _extract_keywords(result[j].title)
        sim = _jaccard(kw_i, kw_j)
        if sim > 0.6:
            # 保留内容更长的
            if len(result[j].content or "") > len(result[i].content or ""):
                to_remove.add(i)
            else:
                to_remove.add(j)

result = [r for idx, r in enumerate(result) if idx not in to_remove]
```

#### 3.5 修复HTML实体二次转义

**文件**：`src/content/content_orchestrator.py`
**方法**：`_inline_markdown()` (第1227行)

在 `html.escape()` 之前保护已有HTML实体：
```python
# 在 tag_placeholders 保护逻辑之后、html.escape() 之前插入：
entity_placeholders = {}
def protect_entity(m):
    idx = len(entity_placeholders)
    placeholder = f'__HTMLENTITY_{idx}__'
    entity_placeholders[placeholder] = m.group(0)
    return placeholder

text = re.sub(r'&[a-zA-Z]+;|&#\d+;', protect_entity, text)
text = html.escape(text)
for placeholder, entity in entity_placeholders.items():
    text = text.replace(placeholder, entity)
```

#### 3.6 修复封面和Logo

**文件**：`config/document_templates/word_default.html`

```html
<!-- 修改前 -->
<p class="meta">{{ author }}<br>{{ date }}</p>
<img class="logo" src="{{ logo_path }}" alt="" onerror="this.style.display='none'">

<!-- 修改后 -->
<p class="meta">{% if author %}{{ author }}<br>{% endif %}{{ date }}</p>
{% if logo_path %}
<img class="logo" src="{{ logo_path }}" alt="Logo">
{% endif %}
```

---

## 六、修复优先级与排期

| 阶段 | 修复内容 | 涉及问题 | 预估工时 | 优先级 |
|------|---------|---------|---------|--------|
| **Phase 1** | 图表集成修复（管线复用） | P1-4, P2-1, P2-2, P2-3 | 3h | **立即** |
| **Phase 1** | PALETTE_12重复色 | P2-4 | 0.5h | **立即** |
| **Phase 2** | Markdown解析完善 | P0-1 | 4h | **立即** |
| **Phase 2** | 围栏代码块识别 | P0-2 | 2h | **立即** |
| **Phase 2** | 标题解析修复 | P0-3 | 1h | **立即** |
| **Phase 3** | Agent输出清洗层 | P0-2, P0-3, P3-5 | 3h | 高 |
| **Phase 3** | 模板变量修复 | P1-1 | 0.5h | 高 |
| **Phase 3** | 表格双重渲染 | P1-3 | 1h | 高 |
| **Phase 3** | 语义去重 | P1-2 | 2h | 高 |
| **Phase 3** | HTML实体修复 | P3-2 | 1h | 中 |
| **Phase 3** | 封面/Logo修复 | P1-4, P3-3 | 0.5h | 中 |
| **Phase 3** | CSS类名/标题层级 | P3-1, P3-4 | 1h | 低 |

**总计预估**：约20小时

---

## 七、不需要修复的项目（已确认图表系统已实现）

| 原计划修复项 | 现状 | 结论 |
|------------|------|------|
| 图表caption语义化 | ChartPlannerAgent已实现LLM语义caption | ✅ 不需修改，只需集成 |
| 图表数量控制 | ChartPlannerConfig.max_per_section=2已实现 | ✅ 不需修改，只需集成 |
| 图表配色统一 | PALETTE_12已使用墨蓝+暖金 | ✅ 已实现，仅修重复色 |
| 图表锚点定位 | ChartPlannerAgent已生成锚点 | ✅ 不需修改，只需集成 |
| 图表类型选择规则 | 12种类型+LLM驱动已实现 | ✅ 不需修改 |
| 图表数据校验 | 置信度+语义+单位一致性已实现 | ✅ 不需修改 |
| 新建图表去重模块 | 问题本质是管线重复生成 | ❌ 不需新模块，修集成即可 |

---

## 八、验证方案

### 8.1 图表集成验证

1. 在 `_generate_charts_for_html()` 中添加日志，记录管线1已有图表数量
2. 确认管线2仅补充不足部分
3. 验证最终每section图表数≤2
4. 验证caption包含语义化描述（非"份额对比（10项）"）

### 8.2 Markdown解析验证

为 `_content_to_html()` 新增测试用例：

```python
test_cases = [
    ("```json\n{\"content\": \"实际内容\"}\n```", "不含```json"),
    ("- item1\n- item2", "<ul>"),
    ("1. item1\n2. item2", "<ol>"),
    ("> 引用文本", "<blockquote"),
    ("#### 四级标题", "<h5"),
    ("1. **风险**：描述", "<ol>"),  # 不应被识别为标题
]
```

### 8.3 回归测试

使用同一份研究数据重新生成报告，检查：
1. 图表数量合理（每section≤2）
2. 图表caption语义化
3. Markdown标记正确转换
4. JSON代码块被正确处理
5. 目录标题显示
6. 表格只出现一次
7. HTML实体正确显示

---

## 九、长期优化建议

1. **统一图表生成入口**：将3条管线合并为1条，由 `DocumentGenerationAgent` 统一调度 `ChartPlannerAgent`，消除 `SmartChartGenerator` 的并行调用
2. **利用已声明的markdown库**：`requirements.txt` 已声明 `markdown>=3.5.0`，考虑用其替代手写解析器，减少边界情况
3. **Agent输出Schema校验**：在研究Agent输出环节增加JSON Schema校验，确保content为Markdown格式
4. **端到端测试流水线**：建立"研究数据→HTML报告→视觉diff"的自动化测试
