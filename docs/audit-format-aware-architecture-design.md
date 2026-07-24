# 格式感知架构设计文档 审计报告

> 审计日期：2026-07-06
> 审计对象：`2026-07-06-format-aware-architecture-design.md` v1.1
> 审计方法：逐项对照源代码验证所有代码引用、行号、方法签名、数据模型、架构主张
> 审计范围：全部10个章节 + 3个附录，涉及19个源文件
> 审计状态：**已全部修正** → 文档已更新至 v2.0

---

## 审计结论

文档共发现 **14处缺陷**（2 CRITICAL / 5 HIGH / 5 MEDIUM / 2 LOW），其中v1.1已修正的6处缺陷中**3处修正不完整或引入新问题**。

### 严重度分布

| 严重度 | 数量 | 说明 |
|--------|------|------|
| CRITICAL | 2 | 会导致实现完全失败 |
| HIGH | 5 | 会导致功能错误或运行时异常 |
| MEDIUM | 5 | 会导致行为偏差或遗漏 |
| LOW | 2 | 信息不准确但不影响实现 |

---

## 缺陷清单

### DEF-01 [CRITICAL] 模板语法体系错误 — Jinja2 vs string.Template

**位置**：第4.2节"配套改动：`prompts/chapter_write.tmpl` 模板文件末尾新增"

**文档描述**：
```
{% if format_directive %}

## 格式输出要求
{{format_directive}}
{% endif %}
```

**实际代码**：`PromptManager`（`prompt_manager.py:2,17-20`）使用 Python 标准库 `string.Template`，语法为 `${variable}` 替换，**不支持条件逻辑**（无 `{% if %}`、无 `{{variable}}`）。

**影响**：
- Jinja2 语法写入 `.tmpl` 文件后，`Template.substitute()` 会将 `{% if format_directive %}` 当作纯文本输出
- `{{format_directive}}` 不会被替换，会原样输出到 prompt 中
- 条件判断完全失效，`format_directive` 为空时也会输出标题

**修正方案**：
- 方案A：将 `PromptManager` 改为 Jinja2（`jinja2.Template`），支持条件逻辑 — 改动较大
- 方案B：保持 `string.Template`，在 Python 层面控制是否拼接格式指令，模板只加 `${format_directive}` 占位符，为空时传空字符串
- **推荐方案B**，改动最小且与现有体系一致：
  ```python
  # chapter_writer.py 中
  format_directive_text = ""
  if format_directive:
      format_directive_text = f"\n\n## 格式输出要求\n{format_directive}"
  
  prompt = self._prompts.get(
      "chapter_write",
      ...,
      format_directive=format_directive_text,
  )
  ```
  模板中只需在末尾加：`${format_directive}`

---

### DEF-02 [CRITICAL] `supported_formats` 字段在 ReportTemplate 中不存在

**位置**：第3.1.1节 `select_output_format()` 方法中 `template.supported_formats`

**文档描述**：
```python
template = self._templates.get(selected_template)
supported = [f.value for f in template.supported_formats]
```

**实际代码**：`ReportTemplate` dataclass（`report_template.py:114-139`）的8个字段为：`meta`, `report`, `styles`, `charts`, `tables`, `sections`, `validation`, `output`。**没有 `supported_formats` 字段**。

**影响**：
- `template.supported_formats` 会抛出 `AttributeError`
- 格式选择步骤完全无法工作
- 模板约束校验（第7.2节）同样依赖此字段，也无法工作

**修正方案**：
1. 在 `ReportTemplate` dataclass 中新增 `supported_formats` 字段：
   ```python
   supported_formats: List[OutputFormat] = field(default_factory=lambda: [OutputFormat.DOCX, OutputFormat.PPTX, OutputFormat.PDF, OutputFormat.HTML])
   ```
2. 对应的 YAML 模板文件中增加 `supported_formats` 配置项
3. 模板加载逻辑需解析此字段

---

### DEF-03 [HIGH] "500字硬切" 描述不准确 — 实为段落感知的软限制分块

**位置**：第0.2节格式传递链路、第0.1节D2缺陷描述、第4.5节

**文档描述**：多处称 PPT 内容为"500字硬切"

**实际代码**：`_split_content_for_slides()`（`content_orchestrator.py:1295-1323`）按段落分割，以500字符为软上限累加段落，不会在段落中间截断。超长段落整体作为一个 chunk。

**影响**：
- 问题定性偏差：文档将问题定性为"硬切"，但实际是"软限制但不够智能"
- 改造方案中的"替代500字硬切"定位不够精确，真正的问题是：段落内容本身是长文本（ChapterWriter格式无关的输出），即使段落感知地分块，每个chunk仍是密集长段落而非精炼要点

**修正方案**：将所有"500字硬切"描述修正为"500字符段落感知分块，但因源头内容格式无关，分块结果仍是密集段落而非精炼要点"

---

### DEF-04 [HIGH] `ChartConfig.height` 类型标注与默认值矛盾

**位置**：第5.1节"⚠️ 真实代码约束"

**文档描述**："`ChartConfig` 的 `width`/`height` 字段是 `int` 类型（英寸，line 71-72）"

**实际代码**：
- `width: int = 9` — 类型 `int`，默认值 `9` ✅
- `height: int = 5.5` — 类型标注 `int`，但默认值 `5.5` 是 `float` ❌

**影响**：
- 文档说"英寸"单位是正确的（`plt.subplots(figsize=(config.width, config.height))`）
- 但 `height: int = 5.5` 是代码中的已有 bug（类型不匹配），文档未指出此问题
- 设计文档第5.1节 `generate_with_format_config()` 中 `config.width = int(format_style.figsize[0])` 使用 `int()` 转换，对 width 无影响，但对 height 会截断小数（如 4.5→4）

**修正方案**：
1. 在文档中标注 `height: int = 5.5` 的类型bug
2. `generate_with_format_config()` 中应使用 `float` 而非 `int` 转换，或将 `ChartConfig` 的 `width`/`height` 类型改为 `float`

---

### DEF-05 [HIGH] `config.dpi` 被完全忽略，设计文档的 `_default_dpi` 方案基于错误前提

**位置**：第5.1节 `generate_with_format_config()` 方法

**文档描述**：修改 `self._default_dpi` 来适配格式

**实际代码**：
- `ChartConfig.dpi`（line 73）定义但从未被使用
- `_save_figure()`（line 228）硬编码 `dpi=150`
- `ChartGenerator` 无 `_default_dpi` 属性

**影响**：
- `generate_with_format_config()` 中 `self._default_dpi = format_style.dpi` 无效，因为 `_save_figure()` 不读取任何实例属性
- PPTStrategy 配置 `dpi=200` 不会生效

**修正方案**：应修改 `_save_figure()` 使用 `config.dpi` 而非硬编码，或新增实例属性并在 `_save_figure()` 中引用：
```python
def _save_figure(self, fig, name, config=None):
    dpi = config.dpi if config and hasattr(config, 'dpi') else 150
    fig.savefig(image_path, dpi=dpi, ...)
```

---

### DEF-06 [HIGH] `select_output_type()` 行号引用错误

**位置**：第3.1.1节改动点1

**文档描述**："`select_output_type()` 方法（line 565-586）"

**实际代码**：`select_output_type()` 位于 **line 588-604**，line 565-586 是 `start()` 方法

**影响**：开发者按行号定位会找到错误的方法

**修正方案**：修正为 line 588-604

---

### DEF-07 [HIGH] `ResearchRequirement` 和 `UserChoice` 行号引用不精确

**位置**：第3.1.1节改动点3-4

**文档描述**：
- `ResearchRequirement` dataclass（line 124）
- `UserChoice` dataclass（line 165）

**实际代码**：
- `ResearchRequirement` 类定义从 **line 114** 开始，`output_format` 字段在 line 124
- `UserChoice` 类定义从 **line 161** 开始，`output_format` 字段在 line 165

**影响**：开发者按行号定位 `ResearchRequirement` 会落到字段定义而非类定义

**修正方案**：
- 修正为"`ResearchRequirement` dataclass（line 114，`output_format` 字段在 line 124）"
- 修正为"`UserChoice` dataclass（line 161，`output_format` 字段在 line 165）"

---

### DEF-08 [HIGH] SmartClarifier 步骤数描述错误

**位置**：第3.1节

**文档描述**："当前流程：选类型 → 选框架 → 选章节 → 设参数 → 确认（5步，无格式选择）"

**实际代码**：SmartClarifier 实际有 **7步**：选类型 → 选框架 → 选章节 → 设参数 → 确认研究 → 配置调研 → 最终确认

前端 `useResearch.ts` 也有6个步骤（Step 0-5 + running/completed 状态）

**影响**：改造后流程说"6步"，但实际应为7→8步

**修正方案**：核对实际步骤数，修正流程描述

---

### DEF-09 [MEDIUM] `to_ppt_styles()` 返回值描述不完整

**位置**：第5.4节

**文档描述**：`to_ppt_styles()` 方法（line 83-93）扩展提取颜色和装饰信息

**实际代码**：`to_ppt_styles()`（line 83-93）当前返回7个键：`title_font`, `body_font`, `title_size`, `subtitle_size`, `body_size`, `slide_width`, `slide_height`。**不包含任何颜色信息**。

文档提出的扩展方案新增 `primary_color`, `accent_color` 等颜色键，这是正确的改进方向。但文档未说明 `ExtractedStyles` dataclass 中**不存在** `accent_color`、`bg_gradient_start` 等字段，`_extract_color()` 方法不存在（实际是 `_parse_color()`，且它是 `CSSStyleExtractor` 的方法，不是 `ExtractedStyles` 的方法）。

**影响**：扩展方案缺少对 `ExtractedStyles` dataclass 字段的修改，以及从 `CSSStyleExtractor._parse_color()` 到 `ExtractedStyles` 的数据传递链路

**修正方案**：
1. 在 `ExtractedStyles` dataclass 中新增颜色字段
2. 在 `CSSStyleExtractor._extract_key_styles()` 中填充这些字段
3. `to_ppt_styles()` 中引用新增字段

---

### DEF-10 [MEDIUM] PPT图表流程缺少 `_generate_chart_image()` 的实现细节

**位置**：第4.6节

**文档描述**：
```python
chart_path = self._generate_chart_image(chart, strategy.get_chart_style())
```

**实际代码**：`ContentOrchestrator` 中**不存在** `_generate_chart_image()` 方法。此方法为设计文档提出的新增方法，但文档未给出实现细节。

`chart` 参数的类型是什么？它来自 `charts_data`（原始图表数据字典），但 `ChartGenerator.generate()` 需要 `ChartConfig` 对象。从原始数据字典到 `ChartConfig` 的转换逻辑未说明。

**影响**：实现时缺少关键环节

**修正方案**：明确 `_generate_chart_image()` 的实现：
1. 从 `charts_data` 字典构建 `ChartConfig`
2. 调用 `ChartGenerator.generate_with_format_config(config, format_style)`
3. 返回生成的 PNG 文件路径

---

### DEF-11 [MEDIUM] 文档API路径与实际API架构不匹配

**位置**：第3.1.2节

**文档描述**：新增 `@router.post("/research/{session_id}/select-format")` 在 `research_api.py` 中

**实际代码**：
- 不存在独立的 `research_api.py` 文件
- API 全部在 `src/api/main.py` 中定义
- 交互式步骤通过统一的 `POST /api/v1/research/interact` 端点处理，而非每个步骤独立端点
- SmartClarifier 的步骤选择通过 `interact` 端点的 `action` 字段路由

**影响**：新增独立端点的方案与现有API架构不一致

**修正方案**：格式选择应通过 `POST /api/v1/research/interact` 端点实现，新增 `action: "select_format"` 类型，而非创建独立端点

---

### DEF-12 [MEDIUM] PDF转换器完全忽略图片/图表，文档未提及

**位置**：第0.2节格式传递链路、第5.5节PPT图表流程

**文档描述**：链路中 `HTMLToPDFConverter → .pdf`，暗示PDF路径正常

**实际代码**：`html_to_pdf.py` 的 `_create_reportlab_document()` 方法**完全没有 `image` 元素类型的处理**。图表和图片在PDF中完全丢失。

**影响**：
- 第0.1节D3缺陷描述为"PPT图表传递链断裂"，但PDF图表也断裂
- PDFStrategy 的 `ChartStyleConfig` 设置（如 `dpi=200`, `theme_name="print_optimized"`）在PDF路径下不会生效

**修正方案**：
1. 在第0.1节增加D4缺陷："PDF图表丢失"
2. 在改造项中补充 `html_to_pdf.py` 的图片渲染修复（使用 `reportlab.platypus.Image`）

---

### DEF-13 [MEDIUM] `document_api.py` 的 `exportDocument` 实际硬编码为DOCX

**位置**：第3.2节

**文档描述**："`OutputFormat` 枚举已包含四种格式，`exportDocument` API 已接受 format 参数，无需改动"

**实际代码**：虽然 `ExportDocumentRequest` 接受 `format` 参数且验证格式合法性，但 `_export_document()` 的实现（`document_api.py:497-620`）**始终使用 `HTMLToWordConverter` 生成 DOCX**，完全忽略传入的 `format` 参数。即使传入 `"pptx"` 或 `"pdf"`，输出的仍是 `.docx` 文件。

**影响**：前端格式选择器即使实现，后端也不会真正转换格式

**修正方案**：将此问题列为P0修复项，`_export_document()` 需根据 `format` 参数路由到不同的转换器

---

### DEF-14 [MEDIUM] v1→v1.1 修正#5 不完整 — `ChartConfig` 的 `figsize` 属性不存在

**位置**：第5.1节 `_create_figure()` 改造、附录C修正#5

**文档描述**：v1.1修正将 `config.figsize` 改为 `config.width`/`config.height`，但在 `_create_figure()` 改造代码中仍出现 `config.figsize`：

```python
fig, ax = plt.subplots(
    figsize=config.figsize or style.figsize,
    dpi=style.dpi,
)
```

**实际代码**：`ChartConfig` 只有 `width` 和 `height` 字段，没有 `figsize` 属性。

**影响**：此代码会抛出 `AttributeError: 'ChartConfig' object has no attribute 'figsize'`

**修正方案**：
```python
fig, ax = plt.subplots(
    figsize=(config.width, config.height),
    dpi=style.dpi,
)
```

---

### DEF-15 [LOW] `chapter_write.tmpl` 模板路径描述不精确

**位置**：第4.2节"配套改动"

**文档描述**："`prompts/chapter_write.tmpl` 模板文件末尾新增"

**实际代码**：模板文件位于 `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`，项目根目录下的 `prompts/` 目录是另一套模板体系（agents/phases/tasks）

**影响**：路径不精确可能导致开发者修改错误的文件

**修正方案**：明确写完整路径 `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl`

---

### DEF-16 [LOW] `_check_consistency` 方法签名与文档描述不一致

**位置**：第6.1节

**文档描述**：质检调用代码隐含 `_check_consistency(report_data)` 只接收一个参数

**实际代码**：`_check_consistency(self, report: Dict)` 确实只接收 `report`（line 634），而 `_check_completeness`、`_check_accuracy`、`_check_format` 都接收 `(report, standards)` 两个参数

**影响**：文档第6.1节示例代码中 `self._check_consistency(report_data)` 的调用方式正确，但 `_check_format(report_data, quality_standard)` 中的 `quality_standard` 参数来自 `strategy.get_quality_standard()`，而现有 `_check_format` 签名为 `(self, report, standards)`，需确认 `QualityStandard` 对象与 `standards: Dict` 的兼容性

**修正方案**：明确 `QualityStandard` 如何转换为 `standards: Dict`，或让 `_check_format` 也接受 `QualityStandard` 对象

---

## v1.1 已修正缺陷的复审

| # | v1.1修正项 | 修正是否完整 | 遗留问题 |
|---|-----------|-------------|---------|
| 1 | `_assemble_final_report` 是 `@staticmethod`，改为参数传入 | ✅ 正确 | 无 |
| 2 | ChapterWriter 使用 PromptManager 模板系统 | ❌ 不完整 | 修正了注入方式，但模板语法用了 Jinja2 而非 string.Template（见 DEF-01） |
| 3 | `charts: []` 硬编码为空 | ✅ 正确 | 无 |
| 4 | PPT图表流程缺少 ChartPlannerAgent 步骤 | ✅ 正确 | `ChartPlannerAgent` 确实存在（`src/services/chart_planner.py`） |
| 5 | `ChartConfig` 尺寸字段是 width/height | ❌ 不完整 | `_create_figure()` 改造代码仍引用不存在的 `config.figsize`（见 DEF-14） |
| 6 | python-pptx 渐变背景降级处理 | ✅ 正确 | 无 |

---

## 架构逻辑审查

### 1. 数据流完整性

改造后PPTX数据流（附录B.2）中，以下环节缺少实现细节：

| 环节 | 缺失细节 |
|------|---------|
| ChapterWriter → 结构化slides输出 | LLM输出JSON解析失败的降级策略未定义 |
| chart_suggestion → ChartConfig | `_generate_chart_image()` 实现未给出（见 DEF-10） |
| ChartPlannerAgent 集成点 | 在哪个阶段调用、输入输出如何衔接未明确 |
| HTML → SlideElementParser → chart_placeholder | 解析器不支持 `data-chart-*` 属性，需扩展 |

### 2. 格式约束一致性

- `OutputFormat` 枚举三处不一致（smart_clarifier 有 MD，其他两处无），文档已识别但统一方案未说明 MD 的处理策略
- `FormatStrategy` 新增 `HTML = "html"` 值，但 `HTMLStrategy` 实现类未给出

### 3. 向后兼容性

- `ChapterWriteInput` 新字段有默认值 ✅
- `generate_report()` 新参数有默认值 ✅
- `_assemble_final_report()` 新参数有默认值 ✅
- 但 `document_api.py` 的 `_export_document()` 硬编码DOCX（见 DEF-13），即使前端不选格式也会受影响

### 4. 遗漏的改造项

| 遗漏 | 影响 | 建议优先级 |
|------|------|-----------|
| `html_to_pdf.py` 图片渲染缺失 | PDF输出无图表 | P1 |
| `document_api.py._export_document()` 硬编码DOCX | 格式选择不生效 | P0 |
| `SlideElementParser` 不支持 chart_placeholder | PPT图表解析失败 | P1 |
| `HTMLStrategy` 实现 | HTML格式无策略 | P2 |
| `ExtractedStyles` 新增颜色字段 | PPT视觉配置无法传递 | P2 |

---

## 修正优先级建议

| 优先级 | 缺陷 | 理由 |
|--------|------|------|
| **立即修正** | DEF-01, DEF-14 | 代码无法运行 |
| **设计定稿前修正** | DEF-02, DEF-05, DEF-13 | 核心功能无法实现 |
| **实现前修正** | DEF-03, DEF-06, DEF-07, DEF-08, DEF-10, DEF-11 | 实现时会造成困惑或错误 |
| **实现时注意** | DEF-04, DEF-09, DEF-12, DEF-15, DEF-16 | 影响较小但需记录 |
