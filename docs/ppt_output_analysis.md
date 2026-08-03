# PPT输出模块问题分析报告

## 一、问题概述

当前PPT输出模块生成的PPT与Word文档几乎相同——全是文字，没有内容精简，没有图形化呈现。具体表现为：

1. **内容未精简**：长段落原样搬入PPT，未提炼为要点/关键词
2. **缺乏图形**：无图表、无KPI卡片、无可视化数据呈现
3. **版式单一**：所有内容页都是"标题+大段文字"的Word式排版
4. **无视觉层次**：没有利用PPT特有的分栏、图文混排、数据可视化等能力

---

## 二、根因分析：6个关键断裂点

### 断裂点1：PPTXStrategy 策略已定义但从未接入

**位置**：`src/content/format_strategy.py:135-199`

`PPTXStrategy` 已经完整定义了PPT应有的写作规范：

| 配置项 | PPTX策略值 | 实际效果 |
|--------|-----------|---------|
| `content_style` | `"bullet_points"` | ❌ 实际输出长段落 |
| `bullet_max_chars` | `25` | ❌ 未执行 |
| `section_structure` | `"slide_based"` | ❌ 实际按Word章节结构 |
| `data_presentation` | `"visual"` | ❌ 实际为纯文本 |
| `max_slide_text_chars` | `300` | ❌ 未执行 |
| `min_chart_count_per_section` | `1` | ❌ 未执行 |
| `require_visual_balance` | `True` | ❌ 未执行 |

`get_chapter_writer_prompt_suffix()` 方法返回了精心设计的PPT精简提示词（要求每要点不超过25字、每页聚焦一个核心观点、明确指出配图位置），但**该方法从未被任何代码调用**。

**根因**：`ChapterWriter` 的prompt系统与 `FormatStrategy` 系统是**两套独立体系，从未对接**。`ChapterWriter.write()` 通过 `PromptManager.get("chapter_write")` 加载固定模板 `chapter_write.tmpl`，该模板是Word风格的详细论述指令，与FormatStrategy完全无关。无论输出格式是Word还是PPT，ChapterWriter始终使用同一套详细论述模板。

---

### 断裂点2：ContentOrchestrator 只做机械分割，不做内容精简

**位置**：`src/content/content_orchestrator.py:1491-1519`

`_split_content_for_slides()` 方法是PPT内容处理的唯一环节，其逻辑为：

```python
# 按\n分割段落 → 按500字符阈值合并 → 输出chunks
paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
for para in paragraphs:
    if len(current_chunk) + len(para) < 500:
        current_chunk += para + "\n"
    else:
        chunks.append(current_chunk.strip())
        current_chunk = para + "\n"
```

**问题**：
- 这是**机械字符计数分割**，不是语义精简
- 2000字的段落 → 变成4页各500字的PPT，内容完全相同
- 没有将长段落提炼为要点/关键词
- 没有提取数据标签（如"950万辆"、"+37.5%"）
- 没有生成图表建议

**对比**：Word路径的 `_render_section_html()` 和PPT路径的 `_render_section_slides()` 使用完全相同的 `_content_to_html()` 方法，没有任何格式差异化处理。

---

### 断裂点3：HTML中间格式丢失了PPT所需的语义结构

**位置**：`src/content/content_orchestrator.py:1460-1467`

`_render_section_slides()` 生成的HTML结构：

```html
<section class="slide" data-type="content" data-page="3">
    <div class="slide-content">
        <div class="slide-body">
            <p>{_inline_markdown(chunk)}</p>  <!-- 大段文字直接塞入<p> -->
            {chart_imgs}  <!-- 仅当上游已生成图表时才有 -->
        </div>
    </div>
</section>
```

**问题**：
- 内容被包裹在单个 `<p>` 标签中，`SlideElementParser` 会将其归入 `content` 字段（纯文本），而非 `items` 字段（要点列表）
- 没有生成 `<ul><li>` 结构，导致PPT渲染时无法显示为要点列表
- content页**没有 `<h2>` 标题**（section-title页和content页是分开渲染的），导致解析后 `title` 字段为空
- 没有 `data-type="findings"` / `data-type="data"` 等语义分类
- 没有嵌入KPI数据标签、对比数据等PPT特有结构

---

### 断裂点4：高级渲染管线默认关闭

**位置**：`src/converters/html_to_ppt.py:440-441, 595-662`

系统存在两条渲染管线：

| 管线 | 触发条件 | 功能 |
|------|---------|------|
| **Template Renderer** | `USE_TEMPLATE_RENDERER=1` | TemplateSelector + LayoutEngine + SlideRenderer + ImageProvider + SmartChartGenerator |
| **Built-in Renderer** | 默认 | 简单的5种slide_type处理 |

**问题**：
- 高级管线（含图表自动生成、KPI卡片、对比布局、图文混排）**默认关闭**，需手动设置环境变量
- 默认管线的 `_create_content_slide()` 只是把 `content` 字段原样放入文本框
- 即使开启高级管线，如果 `content` 字段是长段落（而非 `items` 列表），TemplateSelector 也会退回到 `content_text_only` 模板

---

### 断裂点5：图表生成是被动响应，不是主动规划

**位置**：`src/converters/html_to_ppt.py:443-501` 和 `src/services/smart_chart_generator.py`

图表生成流程：

```
SlideData → LayoutEngine.can_accommodate_chart() → _auto_generate_charts()
    → SmartChartGenerator.analyze_content() → 正则提取数据 → 生成图表
```

**问题**：
- 仅在Template Renderer管线中触发，默认管线无图表生成
- `SmartChartGenerator` 使用正则匹配提取数据，对中文长段落提取率低
- `ChartPlannerAgent`（LLM驱动的智能图表规划）是独立服务，从未在主流程中调用；且其为异步服务（`async def plan()`），而 `HTMLToPPTConverter._create_pptx_document()` 是同步方法，存在**同步/异步不兼容**的集成障碍
- 图表生成依赖 `layout_engine.can_accommodate_chart()` 判断，但该判断基于已有 `items`/`images` 数量——如果内容全是长段落（无items），判断结果可能不准确
- `ImageProvider` 需要API密钥（Unsplash/Pexels/DALL-E），未配置时只能生成占位图

---

### 断裂点6：chapter_write.tmpl 模板指令与PPT精简需求方向相反

**位置**：`src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`

`chapter_write.tmpl` 是ChapterWriter的核心prompt模板，其中明确要求：

```
核心原则：只做提升，绝不降级
- 逐段对照初稿 — 初稿每段的核心论点和数据引用必须保留，不得丢失或替换
- 精修≠重写 — 你是在初稿基础上做增量提升，不是另起炉灶
- 禁止删除初稿中有价值的内容 — 初稿是专业成果，你只能增补和优化，不能删减核心论点
```

**问题**：
- 这些指令与PPT需要的**精简提炼**方向完全相反——PPT要求"每要点不超过25字"、"每页聚焦一个核心观点"，而模板要求"保留原文"、"不能删减"
- 即使将 `PPTXStrategy.get_chapter_writer_prompt_suffix()` 追加到模板末尾，也会与模板中的"禁止删除"指令产生**语义冲突**，LLM会优先遵循模板中的"保留"指令
- 需要为PPT输出提供**独立的chapter_write模板**，而非在Word模板上追加补丁

---

## 三、数据流全景图

```
Research Result (dict)
    │
    ▼
ChapterWriter Agent ── 使用DOCXStrategy（详细论述）── ❌ 应使用PPTXStrategy
    │
    ▼
ContentSection {title, content(长段落), points=[]}
    │
    ▼
ContentOrchestrator._render_section_slides()
    │  ├── _split_content_for_slides() → 500字符机械分割 ❌
    │  └── 输出 <p>{长段落}</p> ❌ 应输出 <ul><li>要点</li></ul>
    │
    ▼
HTML string (<section class="slide" data-type="content">)
    │
    ▼
SlideElementParser.feed()
    │  └── content字段=长段落, items字段=[] ❌
    │
    ▼
HTMLToPPTConverter._create_pptx_document()
    │
    ├── [默认] Built-in Renderer
    │   └── _create_content_slide() → 文本框直接放content ❌
    │
    └── [USE_TEMPLATE_RENDERER=1] Template Renderer
        ├── TemplateSelector → 退回content_text_only ❌
        ├── LayoutEngine → 无图表空间
        ├── SmartChartGenerator → 正则提取失败
        └── ImageProvider → 无API密钥 → 占位图
    │
    ▼
.pptx = Word式纯文字PPT ❌
```

---

## 四、问题影响矩阵

| 问题 | 严重度 | 影响范围 | 修复难度 |
|------|--------|---------|---------|
| PPTXStrategy未接入ChapterWriter | **P0** | 所有PPT输出 | 中 |
| _split_content_for_slides只做机械分割 | **P0** | 所有PPT内容页 | 中 |
| HTML中间格式缺少PPT语义结构 | **P0** | 所有PPT渲染 | 中 |
| chapter_write.tmpl指令与PPT精简方向相反 | **P0** | 内容生成源头 | 中 |
| 高级渲染管线默认关闭 | **P1** | 图表/布局/视觉 | 低 |
| 图表生成被动且脆弱 | **P1** | 数据可视化 | 高 |
| ImageProvider依赖外部API | **P2** | 配图丰富度 | 低 |

---

## 五、修复方案概要

### 方案A：源头修复（推荐）—— 在内容生成阶段就区分PPT/Word

1. **接入PPTXStrategy**：在ChapterWriter调用时，根据output_format选择对应Strategy的prompt_suffix
2. **新增PPT专用chapter_write模板**：创建 `chapter_write_pptx.tmpl`，替换"保留原文"指令为"精简提炼"指令，避免与Word模板的语义冲突
3. **新增ContentCondenser**：在ContentOrchestrator中，对PPT格式的内容调用LLM进行精简（长段落→要点列表）
3. **改造_render_section_slides**：输出 `<ul><li>` 结构而非 `<p>` 标签；自动识别KPI数据生成 `data-type="findings"` 页

### 方案B：中间层修复 —— 在HTML→PPT转换阶段增强

1. **开启Template Renderer为默认**：将 `USE_TEMPLATE_RENDERER` 默认值改为1
2. **新增ContentToItemsConverter**：在SlideElementParser中，将长 `content` 文本自动拆分为 `items` 列表（按句号分割、提取关键句）
3. **集成ChartPlannerAgent**：在Template Renderer管线中主动调用LLM图表规划

### 方案C：双管齐下（最彻底）

同时实施方案A和方案B，确保从内容生成到最终渲染的每个环节都有PPT差异化处理。

---

## 六、关键代码位置索引

| 文件 | 行号 | 说明 |
|------|------|------|
| `src/content/format_strategy.py` | 135-199 | PPTXStrategy定义（未接入） |
| `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl` | 全文 | Word风格写作模板（与PPT精简方向相反） |
| `src/agents/fixed_agents/report_upgrade/chapter_writer.py` | 20-39 | ChapterWriter.write()（不使用FormatStrategy） |
| `src/agents/fixed_agents/report_upgrade/prompt_manager.py` | 17-23 | PromptManager.get()（加载固定模板） |
| `src/content/content_orchestrator.py` | 1491-1519 | _split_content_for_slides（机械分割） |
| `src/content/content_orchestrator.py` | 1419-1489 | _render_section_slides（输出<p>非<li>，content页无标题） |
| `src/content/content_orchestrator.py` | 1092-1200 | _content_to_html（无PPT差异化） |
| `src/converters/html_to_ppt.py` | 440-441 | USE_TEMPLATE_RENDERER开关 |
| `src/converters/html_to_ppt.py` | 595-662 | Template Renderer管线 |
| `src/converters/html_to_ppt.py` | 663-684 | Built-in Renderer管线（默认） |
| `src/converters/html_to_ppt.py` | 967-1046 | _create_content_slide（纯文字渲染） |
| `src/converters/base_parser.py` | 466-562 | _build_slide_dict（<p>→content, <li>→items） |
| `src/converters/base_parser.py` | 564-633 | _split_dense_slides（仅分割items，不处理content） |
| `src/converters/template_selector.py` | 200-248 | _select()（无items时退回content_text_only） |
| `src/services/smart_chart_generator.py` | - | 正则图表生成（脆弱） |
| `src/services/chart_planner.py` | - | LLM图表规划（未集成，异步接口不兼容同步管线） |
| `src/services/image_provider.py` | - | 图片提供（需API密钥） |
