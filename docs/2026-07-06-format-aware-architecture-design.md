# 格式感知架构设计：多输出格式的端到端改造方案

> 日期：2026-07-06
> 状态：设计方案 v2.1（经三次代码审查修正21处缺陷）
> 关联问题：报告输出格式选择缺失 + PPT图表传递链断裂 + PDF图表丢失 + 格式无关的内容生成 + 导出API硬编码DOCX
> 影响范围：SmartClarifier → ChapterWriter → ContentOrchestrator → HTMLToPPTConverter → HTMLToPDFConverter → QualityCheckAgent → DocumentAPI → 前端UI
> 审计历史：v1经逐行代码对照审查发现6处缺陷（1 CRITICAL / 3 HIGH / 2 MEDIUM）；v1.1修正后复审发现2处修正不完整+10处新缺陷；v2.0全部修正（2 CRITICAL / 5 HIGH / 5 MEDIUM / 2 LOW → 0）；v2.1修正5处新发现缺陷（2 HIGH / 3 MEDIUM → 0）

---

## 0. 问题全景

### 0.1 三大核心缺陷

| # | 缺陷 | 影响 | 严重度 |
|---|------|------|--------|
| D1 | **用户无法选择输出格式** | 交互流程无格式选择步骤，导出按钮硬编码DOCX | HIGH |
| D2 | **内容生成格式无关** | ChapterWriter统一写长段落，PPT只能500字符段落感知分块，结果仍是密集段落而非精炼要点 | CRITICAL |
| D3 | **PPT图表传递链断裂** | ChartGenerator产出PNG → ContentOrchestrator跳过 → HTMLToPPTConverter忽略图片 | CRITICAL |
| D4 | **PDF图表丢失** | HTMLToPDFConverter无`image`元素处理，图表在PDF中完全丢失 | HIGH |

### 0.2 当前格式传递链路

```
ResearchRequirement.output_format = DOCX (默认，不可选)
        ↓
  研究Agent（格式无关）—— 产出相同的结构化数据
        ↓
  ChapterWriter.write()（格式无关）—— 统一写长段落
        ↓
  ContentOrchestrator.transform_to_html(output_format=...)
      ├── PPTX → _generate_ppt_html() → 500字符段落感知分块，charts字段跳过
      └── DOCX/PDF → _generate_word_html() → 段落式，charts正常嵌入
        ↓
  转换器
      ├── HTMLToWordConverter → .docx（图表5"宽嵌入）
      ├── HTMLToPPTConverter → .pptx（无add_picture，图表丢失；SlideElementParser输出格式与_create_pptx_document不匹配）
      └── HTMLToPDFConverter → .pdf（无image元素处理，图表丢失）
        ↓
  QualityCheckAgent（格式无关）—— 统一质检标准
        ↓
  DocumentAPI._export_document() → 始终使用HTMLToWordConverter（format参数被忽略）
        ↓
  前端 FinalizeToolbar → "Convert to DOCX"（硬编码）
```

### 0.3 格式感知现状

| 阶段 | 感知格式? | 代码证据 |
|------|----------|---------|
| 数据收集 | ✅ 可访问 | `ResearchRequirement.output_format`，但未传递给Agent |
| 数据分析 | ⚠️ 可访问但未使用 | `output_format`在编排器上下文中，未传给分析Agent |
| 报告生成（ChapterWriter） | ❌ 不感知 | `ChapterWriteInput`无`output_format`字段 |
| 报告生成（ContentOrchestrator） | ✅ 感知 | 选择模板、分叉HTML生成路径 |
| PPT内容适配 | ⚠️ 机械适配 | 500字符段落感知分块（非硬切），但因源头内容格式无关，分块结果仍是密集段落 |
| 图表传递（HTML路径） | ✅ 正常 | `_insert_charts_into_html()`锚点定位 |
| 图表传递（PPTX路径） | ❌ 断裂 | `content_orchestrator.py:347` "template skips" |
| PPT图表渲染 | ❌ 缺失 | `html_to_ppt.py`无`add_picture()`调用；`SlideElementParser.get_slides()`返回`List[List[Dict]]`元素列表，但`_create_pptx_document`期望`List[Dict]`带slide_type/title/content键，格式不匹配 |
| PDF图表渲染 | ❌ 缺失 | `html_to_pdf.py`无`image`元素处理，图表完全丢失 |
| PPT视觉设计 | ❌ 丢失 | 模板CSS定义了渐变/配色，转换器全部丢弃 |
| 质检 | ❌ 不感知 | `QualityCheckAgent`无格式参数 |
| 导出 | ❌ 硬编码 | `DocumentPreview.tsx:425`写死`'docx'`；`document_api.py:497-620`的`_export_document()`始终使用HTMLToWordConverter |

---

## 1. 设计目标

### 1.1 功能目标

1. **用户可选格式**：在任务配置阶段和导出阶段均可选择输出格式
2. **内容因格式而异**：同一份数据，DOCX产出详细论述，PPT产出精炼要点+图表建议
3. **PPT图文并茂**：图表正确传递到PPT幻灯片，支持图文混排布局
4. **格式适配质检**：DOCX查论述完整性，PPT查要点精炼度和图表覆盖率

### 1.2 非功能目标

1. **向后兼容**：默认格式仍为DOCX，现有流程不受影响
2. **增量改造**：分优先级逐步实现，P0修复断裂即可产出可用PPT
3. **模板约束**：格式选项受模板`supported_formats`约束（如`pitch_deck`仅支持PPTX）。⚠️ **前提条件**：`ReportTemplate` dataclass 当前没有 `supported_formats` 字段，需先新增此字段及对应的 YAML 模板配置（见第7.2节）。

### 1.3 设计原则

1. **源头感知优于下游补救**：ChapterWriter知道格式后直接写要点，比ContentOrchestrator段落感知分块更优
2. **策略模式优于条件分支**：格式差异通过Strategy封装，不在业务代码中堆叠if/else
3. **传递链完整性**：图表从生成到渲染的每一步都不可断裂

---

## 2. 架构设计：三层格式感知体系

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    格式策略层 (FormatStrategy)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ DOCXStrategy │  │ PPTXStrategy │  │ PDFStrategy  │          │
│  │ - 写作指令    │  │ - 写作指令    │  │ - 写作指令    │          │
│  │ - 图表策略    │  │ - 图表策略    │  │ - 图表策略    │          │
│  │ - 质检标准    │  │ - 质检标准    │  │ - 质检标准    │          │
│  │ - 布局偏好    │  │ - 布局偏好    │  │ - 布局偏好    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└────────────┬──────────────────┬──────────────────┬──────────────┘
             │                  │                  │
    ┌────────▼────────┐ ┌──────▼──────────┐ ┌────▼────────────┐
    │ 报告生成阶段     │ │ 质检阶段        │ │ 报告优化阶段    │
    │                 │ │                 │ │                 │
    │ ChapterWriter   │ │ QualityCheck    │ │ ChapterWriter   │
    │  ← FormatStrat  │ │ Agent           │ │ .rewrite()      │
    │                 │ │  ← FormatStrat  │ │  ← FormatStrat  │
    │ ContentOrchestr │ │                 │ │                 │
    │ ator            │ │                 │ │                 │
    │  ← FormatStrat  │ │                 │ │                 │
    └────────┬────────┘ └─────────────────┘ └─────────────────┘
             │
    ┌────────▼──────────────────────────────────────────────────┐
    │                    文档渲染阶段                             │
    │                                                           │
    │  PPTX路径:                                                │
    │  ChartGenerator(FormatAware) → PPTLayoutEngine →          │
    │    PPTTheme → HTMLToPPTConverter(支持add_picture)          │
    │                                                           │
    │  DOCX/PDF路径:                                            │
    │  ChartGenerator(FormatAware) → HTMLToWordConverter        │
    └───────────────────────────────────────────────────────────┘
```

### 2.2 FormatStrategy 接口设计

**新增文件**: `src/content/format_strategy.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class OutputFormat(Enum):
    DOCX = "docx"
    PPTX = "pptx"
    PDF = "pdf"
    HTML = "html"


@dataclass
class ChartStyleConfig:
    """图表格式适配配置"""
    figsize: tuple = (5.0, 3.5)
    dpi: int = 150
    title_fontsize: int = 12
    label_fontsize: int = 10
    tick_fontsize: int = 9
    transparent_bg: bool = False
    theme_name: str = "default"
    annotation_fontsize: int = 7


@dataclass
class WritingDirective:
    """写作指令配置"""
    content_style: str = "detailed"
    paragraph_max_chars: int = 0
    bullet_max_chars: int = 0
    require_chart_suggestion: bool = False
    require_data_annotation: bool = False
    section_structure: str = "hierarchical"
    data_presentation: str = "embedded"


@dataclass
class QualityStandard:
    """格式相关的质检标准"""
    max_paragraph_chars: int = 0
    min_chart_count_per_section: int = 0
    max_slide_text_chars: int = 0
    require_visual_balance: bool = False
    check_items: List[str] = field(default_factory=list)


@dataclass
class LayoutPreference:
    """布局偏好配置"""
    slide_layouts: List[str] = field(default_factory=lambda: ["bullet_points"])
    prefer_split_layout: bool = False
    chart_position: str = "embedded"
    table_style: str = "full"


class FormatStrategy(ABC):
    """格式策略抽象基类"""

    @property
    @abstractmethod
    def format_name(self) -> str:
        pass

    @abstractmethod
    def get_writing_directive(self, section_type: str = "body") -> WritingDirective:
        pass

    @abstractmethod
    def get_chart_style(self) -> ChartStyleConfig:
        pass

    @abstractmethod
    def get_quality_standard(self) -> QualityStandard:
        pass

    @abstractmethod
    def get_layout_preference(self) -> LayoutPreference:
        pass

    @abstractmethod
    def get_chapter_writer_prompt_suffix(self, section_type: str = "body") -> str:
        pass


class DOCXStrategy(FormatStrategy):

    @property
    def format_name(self) -> str:
        return "docx"

    def get_writing_directive(self, section_type: str = "body") -> WritingDirective:
        return WritingDirective(
            content_style="detailed",
            paragraph_max_chars=0,
            require_chart_suggestion=False,
            require_data_annotation=True,
            section_structure="hierarchical",
            data_presentation="embedded",
        )

    def get_chart_style(self) -> ChartStyleConfig:
        return ChartStyleConfig(
            figsize=(5.0, 3.5),
            dpi=150,
            title_fontsize=12,
            label_fontsize=10,
            tick_fontsize=9,
            transparent_bg=False,
            theme_name="default",
        )

    def get_quality_standard(self) -> QualityStandard:
        return QualityStandard(
            check_items=[
                "paragraph_completeness",
                "argument_logic",
                "data_citation_accuracy",
                "heading_hierarchy",
                "cross_section_consistency",
            ],
        )

    def get_layout_preference(self) -> LayoutPreference:
        return LayoutPreference(
            slide_layouts=["bullet_points"],
            chart_position="embedded",
            table_style="full",
        )

    def get_chapter_writer_prompt_suffix(self, section_type: str = "body") -> str:
        return (
            "请撰写详细的分析论述，将数据自然融入论证逻辑中。"
            "每段应包含：观点陈述 → 数据支撑 → 逻辑推导 → 结论。"
            "段落之间保持逻辑连贯，形成完整的论证链条。"
        )


class PPTXStrategy(FormatStrategy):

    @property
    def format_name(self) -> str:
        return "pptx"

    def get_writing_directive(self, section_type: str = "body") -> WritingDirective:
        return WritingDirective(
            content_style="bullet_points",
            paragraph_max_chars=0,
            bullet_max_chars=25,
            require_chart_suggestion=True,
            require_data_annotation=True,
            section_structure="slide_based",
            data_presentation="visual",
        )

    def get_chart_style(self) -> ChartStyleConfig:
        return ChartStyleConfig(
            figsize=(7.5, 4.5),
            dpi=200,
            title_fontsize=16,
            label_fontsize=14,
            tick_fontsize=12,
            transparent_bg=True,
            theme_name="ppt_navy_gold",
        )

    def get_quality_standard(self) -> QualityStandard:
        return QualityStandard(
            max_slide_text_chars=300,
            min_chart_count_per_section=1,
            require_visual_balance=True,
            check_items=[
                "bullet_conciseness",
                "chart_coverage",
                "visual_density",
                "slide_focus",
                "data_label_readability",
            ],
        )

    def get_layout_preference(self) -> LayoutPreference:
        return LayoutPreference(
            slide_layouts=["chart_full", "chart_split", "bullet_points", "kpi_highlight", "data_table"],
            prefer_split_layout=True,
            chart_position="right",
            table_style="compact",
        )

    def get_chapter_writer_prompt_suffix(self, section_type: str = "body") -> str:
        return (
            "请为每张幻灯片提炼内容，使用以下格式：\n"
            "## 幻灯片: [标题]\n"
            "- 要点1: [不超过25字]\n"
            "- 要点2: [不超过25字]\n"
            "- 要点3: [不超过25字]\n"
            "[图表建议: 图表类型 - 展示内容描述]\n"
            "[数据标签: 关键数值及单位]\n\n"
            "要求：\n"
            "1. 每张幻灯片聚焦一个核心观点\n"
            "2. 要点精炼，适合远距离阅读\n"
            "3. 明确指出哪里适合配图、配什么图\n"
            "4. 数据以标签形式呈现，而非嵌入段落\n"
        )


class PDFStrategy(FormatStrategy):

    @property
    def format_name(self) -> str:
        return "pdf"

    def get_writing_directive(self, section_type: str = "body") -> WritingDirective:
        return WritingDirective(
            content_style="detailed",
            paragraph_max_chars=0,
            require_chart_suggestion=False,
            require_data_annotation=True,
            section_structure="hierarchical",
            data_presentation="embedded",
        )

    def get_chart_style(self) -> ChartStyleConfig:
        return ChartStyleConfig(
            figsize=(5.0, 3.5),
            dpi=200,
            title_fontsize=12,
            label_fontsize=10,
            tick_fontsize=9,
            transparent_bg=False,
            theme_name="print_optimized",
        )

    def get_quality_standard(self) -> QualityStandard:
        return QualityStandard(
            check_items=[
                "paragraph_completeness",
                "argument_logic",
                "data_citation_accuracy",
                "print_readability",
                "page_break_quality",
            ],
        )

    def get_layout_preference(self) -> LayoutPreference:
        return LayoutPreference(
            chart_position="embedded",
            table_style="full",
        )

    def get_chapter_writer_prompt_suffix(self, section_type: str = "body") -> str:
        return (
            "请撰写详细的分析论述，适合打印阅读。"
            "注意页面可读性，避免过长段落。"
            "图表应有清晰标题和数据来源标注。"
        )


STRATEGY_REGISTRY: Dict[str, FormatStrategy] = {
    "docx": DOCXStrategy(),
    "pptx": PPTXStrategy(),
    "pdf": PDFStrategy(),
}


def get_format_strategy(output_format: str) -> FormatStrategy:
    if output_format not in STRATEGY_REGISTRY:
        output_format = "docx"
    return STRATEGY_REGISTRY[output_format]
```

---

## 3. 改造项一：用户格式选择

### 3.1 任务配置阶段（SmartClarifier流程）

**当前流程**：选类型 → 选框架 → 选章节 → 设参数 → 确认研究 → 配置调研 → 最终确认（7步，无格式选择）

**改造后流程**：选类型 → 选框架 → **选格式** → 选章节 → 设参数 → 确认研究 → 配置调研 → 最终确认（8步）

#### 3.1.1 后端：SmartClarifier 增加格式选择步骤

**修改文件**: `src/core/orchestrator/smart_clarifier.py`

**改动点**:

1. `select_output_type()` 方法（line 588-604）返回结果中增加 `supported_formats` 字段

2. 新增 `select_output_format()` 方法，在 Step 2（选框架）之后插入：

```python
async def select_output_format(
    self,
    session_id: str,
    output_type: str,
    selected_template: str,
) -> Dict[str, Any]:
    template = self._templates.get(selected_template)
    if not template:
        return {"format_options": ["docx"], "default": "docx"}

    # SmartClarifier 的 Template dataclass（smart_clarifier.py:146-157）已有 supported_formats 字段，
    # 由 TemplateLoader._load_template_from_yaml()（smart_clarifier.py:233-268）从 YAML 解析填充。
    # 所有 YAML 模板文件（config/templates/*.yaml）均已配置 supported_formats。
    # 注意：部分 YAML 模板的 supported_formats 为空列表（如 commercial_plan、conference_call），
    # TemplateLoader 解析后降级为 [DOCX]（line 256-257），这些模板需补全 YAML 配置。
    supported = [f.value for f in template.supported_formats]

    if len(supported) == 1:
        return {
            "format_options": supported,
            "default": supported[0],
            "auto_selected": True,
        }

    return {
        "format_options": supported,
        "default": "docx",
        "descriptions": {
            "docx": "Word文档 - 适合详细论述和长篇报告",
            "pptx": "PPT演示 - 适合汇报演示和图文展示",
            "pdf":  "PDF文档 - 适合正式发布和打印阅读",
        },
    }
```

3. `ResearchRequirement` dataclass（line 114，`output_format` 字段在 line 124）的 `output_format` 字段将从前端选择中赋值，而非默认DOCX

4. `UserChoice` dataclass（line 161，`output_format` 字段在 line 165）的 `output_format` 字段在格式选择步骤中被设置

#### 3.1.2 API层：新增格式选择接口

> **⚠️ 真实代码约束**：交互式步骤通过 `POST /api/v1/research/interact` 统一端点处理，
> 由 `step` 整数参数路由（`research_api.py:1988-2107`），而非 `action` 字段。
> 现有路由：step 0=用户消息, step 1=选类型, step 2=选框架, step 3=确认章节, step 4=设参数, step 5=确认启动。
> 格式选择应插入为 step 2.5（在选框架之后、确认章节之前），即新增 step 编号。

**修改文件**: `src/api/research_api.py`（`handle_interact` 方法）

在 `handle_interact` 的 step 分发逻辑中新增格式选择步骤：

```python
# research_api.py handle_interact() 中新增 step 分支
# 格式选择插入在 step 2（选框架）之后，后续 step 编号需顺延
elif step == FORMAT_SELECT_STEP:
    format_choice = response_dict.get("format_choice", "docx")
    session = session_store.get(session_id)
    template_name = session.get("selected_template")

    clarifier = SmartClarifier()
    result = await clarifier.select_output_format(
        session_id=session_id,
        output_type=session.get("output_type"),
        selected_template=template_name,
    )

    session["format_options"] = result.get("format_options", ["docx"])
    session["output_format"] = format_choice

    return {"success": True, "data": result, "next_step": CONFIRM_SECTIONS_STEP}
```

#### 3.1.3 前端：格式选择UI组件

**修改文件**: `web/src/hooks/useResearch.ts`

在 `selectTemplate()` 之后、`selectSections()` 之前插入格式选择步骤：

```typescript
const selectOutputFormat = async (formatChoice: string) => {
  const response = await api.post(
    `/api/v1/research/interact`,
    { session_id: sessionId, step: FORMAT_SELECT_STEP, response: JSON.stringify({ format_choice: formatChoice }) }
  );

  setResearchState(prev => ({
    ...prev,
    currentStep: 'select_sections',
    outputFormat: formatChoice,
    formatOptions: response.data.format_options,
  }));
};
```

**新增组件**: `web/src/components/chat/FormatSelector.tsx`

```tsx
interface FormatSelectorProps {
  formatOptions: string[];
  defaultFormat: string;
  descriptions: Record<string, string>;
  onSelect: (format: string) => void;
}

const FormatSelector: React.FC<FormatSelectorProps> = ({
  formatOptions,
  defaultFormat,
  descriptions,
  onSelect,
}) => {
  if (formatOptions.length === 1) {
    return <FormatAutoSelect format={formatOptions[0]} />;
  }

  return (
    <div className="format-selector">
      <h3>选择输出格式</h3>
      <div className="format-options">
        {formatOptions.map(format => (
          <FormatCard
            key={format}
            format={format}
            description={descriptions[format]}
            isDefault={format === defaultFormat}
            onClick={() => onSelect(format)}
          />
        ))}
      </div>
    </div>
  );
};
```

### 3.2 文档导出阶段（FinalizeToolbar）

**修改文件**: `web/src/components/preview/DocumentPreview.tsx`

**当前**（line 425）：
```typescript
api.exportDocument(taskId, 'latest', 'docx')  // 硬编码
```

**改造后**：

```tsx
const [exportFormat, setExportFormat] = useState<string>('docx');

const handleExport = () => {
  api.exportDocument(taskId, 'latest', exportFormat);
};

<Select value={exportFormat} onChange={setExportFormat}>
  <Option value="docx">Word (.docx)</Option>
  <Option value="pptx">PowerPoint (.pptx)</Option>
  <Option value="pdf">PDF (.pdf)</Option>
  <Option value="html">HTML (.html)</Option>
</Select>
<Button onClick={handleExport}>导出</Button>
```

**修改文件**: `src/api/document_api.py`（line 82-87）

> **⚠️ 真实代码约束**：`OutputFormat` 枚举已包含四种格式，`ExportDocumentRequest` 已接受 `format` 参数。
> 但 `_export_document()` 实现（line 497-620）**始终使用 `HTMLToWordConverter` 生成 DOCX**，完全忽略传入的 `format` 参数。
> 即使传入 `"pptx"` 或 `"pdf"`，输出的仍是 `.docx` 文件。此为 **P0 修复项**。

**改造后**：`_export_document()` 需根据 `format` 参数路由到不同转换器：

```python
# _export_document() 中的格式路由改造
if output_format == "pptx":
    converter = HTMLToPPTConverter()
    result = converter.convert(html_content, output_path)
elif output_format == "pdf":
    converter = HTMLToPDFConverter()
    result = converter.convert(html_content, output_path)
else:
    converter = HTMLToWordConverter()
    result = converter.convert(html_content, output_path)
```

### 3.3 格式约束传递

**修改文件**: `src/core/orchestrator/orchestrator.py`

`research()` 和 `_research_with_routing()` 中，`output_format` 需从 `ResearchRequirement` 一路传递到 `ReportOrchestrator.generate_report()`：

```python
# orchestrator.py 改造点
report_result = await report_orchestrator.generate_report(
    task_structure=task_structure,
    framework_config=framework_config,
    aggregated_result=aggregation_result,
    output_format=requirement.output_format,  # 新增参数
)
```

---

## 4. 改造项二：报告生成阶段格式感知

### 4.1 ChapterWriteInput 扩展

**修改文件**: `src/agents/fixed_agents/report_upgrade/models.py`

```python
@dataclass
class ChapterWriteInput:
    framework_config: Dict[str, Any]
    task_structure: Dict[str, Any]
    chapter_spec: Dict[str, Any]
    chapter_data: Dict[str, Any]
    raw_data_summary: str = ""
    preceding_summary: str = ""
    used_metrics_summary: str = ""
    base_content: str = ""
    upstream_data_points: Optional[List[Dict]] = None
    output_format: str = "docx"                    # 新增
    format_directive: Optional[str] = None          # 新增：格式写作指令
```

### 4.2 ChapterWriter 格式感知

**修改文件**: `src/agents/fixed_agents/report_upgrade/chapter_writer.py`

**核心改动**：`write()` 方法中，根据 `output_format` 注入格式指令到PromptManager模板变量

> **⚠️ 真实代码约束**：ChapterWriter使用 `PromptManager` 模板系统（`self._prompts.get("chapter_write", ...)`），
> 而非直接字符串拼接。格式指令应通过**新增模板变量**注入，而非拼接prompt。

```python
class ChapterWriter:

    async def write(self, input_data: ChapterWriteInput) -> ChapterWriteOutput:
        strategy = get_format_strategy(input_data.output_format)
        format_directive = input_data.format_directive
        if not format_directive:
            format_directive = strategy.get_chapter_writer_prompt_suffix()

        # PPT格式额外要求：输出结构化幻灯片内容
        if input_data.output_format == "pptx":
            format_directive += (
                "\n\n输出格式要求：\n"
                "请按以下JSON结构输出：\n"
                "{\n"
                '  "title": "章节标题",\n'
                '  "slides": [\n'
                '    {\n'
                '      "slide_title": "幻灯片标题",\n'
                '      "bullets": ["要点1", "要点2", "要点3"],\n'
                '      "chart_suggestion": {"type": "bar", "description": "展示内容"},\n'
                '      "data_labels": [{"value": "1200万辆", "context": "2024年销量"}]\n'
                '    }\n'
                '  ],\n'
                '  "data_points_used": [...],\n'
                '  "key_conclusions": [...]\n'
                "}\n"
            )

        # 通过PromptManager模板变量注入格式指令
        # ⚠️ PromptManager 使用 string.Template（${variable}语法），不支持条件逻辑
        # 因此在Python层面控制格式指令内容，模板只加 ${format_directive} 占位符
        format_directive_text = ""
        if format_directive:
            format_directive_text = f"\n\n## 格式输出要求\n{format_directive}"

        prompt = self._prompts.get(
            "chapter_write",
            topic=input_data.task_structure.get('topic', ''),
            framework_name=input_data.framework_config.get('name', '通用研究报告'),
            section_name=chapter_spec.get('section_name', ''),
            section_id=chapter_spec.get('section_id', ''),
            section_role=str(chapter_spec.get('section_role', '')),
            preceding_summary=input_data.preceding_summary,
            used_metrics_summary=input_data.used_metrics_summary,
            chapter_data=json.dumps(input_data.chapter_data, ensure_ascii=False, indent=2)
                         if input_data.chapter_data else '无可用数据',
            raw_data_summary=input_data.raw_data_summary if input_data.raw_data_summary else '无原始数据摘要',
            base_content=input_data.base_content if input_data.base_content else '无分析初稿，请基于数据从头撰写',
            upstream_data_points_json=json.dumps(input_data.upstream_data_points, ensure_ascii=False, indent=2)
                                      if input_data.upstream_data_points else '无可用数据',
            format_directive=format_directive_text,  # 新增模板变量（string.Template语法）
            output_format=input_data.output_format,  # 新增模板变量
        )

        raw_output = await self._call_llm(prompt)

        if input_data.output_format == "pptx":
            return self._parse_ppt_output(raw_output, chapter_spec)
        else:
            return self._parse_output(raw_output, chapter_spec)  # 保持原有逻辑
```

**配套改动**：`src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl` 模板文件末尾新增：

> **⚠️ 真实代码约束**：`PromptManager`（`prompt_manager.py:2,17-20`）使用 Python 标准库 `string.Template`，
> 语法为 `${variable}` 替换，**不支持条件逻辑**（无 `{% if %}`、无 `{{variable}}`）。
> 因此条件判断在 Python 层完成（见上方 `format_directive_text` 拼接逻辑），模板只加占位符。

```
${format_directive}
```

### 4.3 ChapterWriteOutput 扩展

**修改文件**: `src/agents/fixed_agents/report_upgrade/models.py`

```python
@dataclass
class SlideContent:
    slide_title: str
    bullets: List[str]
    chart_suggestion: Optional[Dict[str, str]] = None
    data_labels: Optional[List[Dict[str, str]]] = None

@dataclass
class ChapterWriteOutput:
    chapter_id: str
    title: str
    content: str                              # DOCX: Markdown长段落; PPTX: 兼容格式
    data_points_used: List[DataPoint]
    key_conclusions: List[str]
    self_check_passed: bool
    self_check_issues: List[str]
    slides: Optional[List[SlideContent]] = None    # 新增：PPT专用
    chart_suggestions: Optional[List[Dict]] = None  # 新增：图表建议
```

### 4.4 ReportOrchestrator 格式传递

**修改文件**: `src/agents/fixed_agents/report_upgrade/orchestrator.py`

**改动点**:

1. `generate_report()` 方法签名增加 `output_format` 参数：

```python
async def generate_report(
    self,
    task_structure: Dict[str, Any],
    framework_config: Dict[str, Any],
    aggregated_result: Any,
    topic: str = "",
    task_id: Optional[str] = None,
    output_format: str = "docx",  # 新增，默认值保证向后兼容
) -> Dict[str, Any]:
```

2. 将 `output_format` 存为实例属性供逐章处理和组装使用：

```python
self._output_format = output_format
```

3. 逐章处理循环中，将 `output_format` 传入 `ChapterWriteInput`：

```python
strategy = get_format_strategy(self._output_format)

chapter_input = ChapterWriteInput(
    framework_config=self._framework_config,
    task_structure=self._task_structure_dict,
    chapter_spec=chapter_spec,
    chapter_data=chapter_data,
    raw_data_summary=raw_summary,
    preceding_summary=prev_summary,
    used_metrics_summary=used_metrics,
    base_content=base_content,
    upstream_data_points=upstream_dp,
    output_format=self._output_format,        # 新增
    format_directive=strategy.get_chapter_writer_prompt_suffix(),  # 新增
)
```

4. `_assemble_final_report()` 中，PPT格式时将 `slides` 和 `chart_suggestions` 写入section：

> **⚠️ 真实代码约束**：`_assemble_final_report()` 是 `@staticmethod`（`report_upgrade/orchestrator.py:1409`），
> 无法访问 `self._output_format`。需要将 `output_format` 作为参数传入。

```python
# 方法签名增加 output_format 参数
@staticmethod
def _assemble_final_report(
    chapters: List[ChapterWriteOutput],
    exec_summary: str,
    review: ReviewOutput,
    topic: str,
    original_sources: List[Dict[str, Any]] = None,
    quality_report: QualityReport = None,
    llm_trace: List[Dict[str, Any]] = None,
    output_format: str = "docx",  # 新增参数
) -> Dict[str, Any]:
```

```python
# PPT格式时组装slides和chart_suggestions
sections.append({
    "id": ch.chapter_id,
    "title": ch.title,
    "content": ch.content,
    "subsections": [],
    "charts": ch.chart_suggestions or [],  # 修正：原硬编码 charts: [] 为空
    "data_points": grounded_dp,
    "sources": chapter_sources,
    "key_conclusions": ch.key_conclusions,
})

# PPT格式额外写入结构化slides数据
if output_format == "pptx" and ch.slides:
    sections[-1]["slides"] = [
        {
            "slide_title": s.slide_title,
            "bullets": s.bullets,
            "chart_suggestion": s.chart_suggestion,
            "data_labels": s.data_labels,
        }
        for s in ch.slides
    ]
```

### 4.5 ContentOrchestrator PPT智能重构

**修改文件**: `src/content/content_orchestrator.py`

**核心改动**：替换 `_generate_ppt_html()` 中的段落感知分块逻辑

**当前逻辑**（line 910-963）:
- `_split_content_for_slides()`（line 1295-1323）：以 `MAX_SLIDE_CONTENT = 500`（line 36）为软上限，按段落累加分块，不在段落中间截断
- `_render_section_slides()`（line 1261-1293）：每个chunk生成一个`<section class="slide">`
- **问题本质**：分块逻辑本身是段落感知的，但因源头内容（ChapterWriter输出）格式无关，每个chunk仍是密集长段落，而非精炼要点

**PPT图表丢失的三个环节**：
1. **ContentOrchestrator 跳过图表插入**（line 346-347）：PPTX路径的 `section_dict["charts"]` 仅传递原始数据，`_insert_charts_into_html()` 从未被调用
2. **`html.escape()` 销毁HTML标签**（line 1287）：`_render_section_slides()` 用 `html.escape(chunk)` 渲染内容，所有 `<img>` 标签被转义为 `&lt;img...&gt;` 纯文本，即使内容中嵌入了图表HTML也会被销毁
3. **HTMLToPPTConverter 不处理 image 元素**：`_create_content_slide()` 只处理 title/content/items，无 `add_picture()` 调用

**改造后逻辑**:

```python
def _generate_ppt_html(self, research_result: Dict, ...) -> str:
    sections = self._parse_sections(research_result.get("sections", []))

    # 优先使用结构化slides数据（来自ChapterWriter PPT感知输出）
    has_structured_slides = any(
        s.get("slides") for s in research_result.get("sections", [])
    )

    if has_structured_slides:
        return self._generate_ppt_html_from_slides(research_result)
    else:
        return self._generate_ppt_html_fallback(research_result)


def _generate_ppt_html_from_slides(self, research_result: Dict) -> str:
    """从结构化slides数据生成PPT HTML（PPT感知模式）"""
    slides_html = []

    # 封面
    slides_html.append(self._render_cover_slide(research_result))

    # 目录
    slides_html.append(self._render_toc_slide(research_result))

    for section in research_result.get("sections", []):
        structured_slides = section.get("slides", [])

        if structured_slides:
            # 章节标题页
            slides_html.append(
                self._render_section_title_slide(section["title"])
            )

            for slide_data in structured_slides:
                chart_suggestion = slide_data.get("chart_suggestion")

                if chart_suggestion:
                    # 图文混排页：左侧要点 + 右侧图表占位
                    slides_html.append(
                        self._render_chart_split_slide(
                            title=slide_data["slide_title"],
                            bullets=slide_data["bullets"],
                            chart_suggestion=chart_suggestion,
                            data_labels=slide_data.get("data_labels", []),
                        )
                    )
                else:
                    # 纯要点页
                    slides_html.append(
                        self._render_bullet_slide(
                            title=slide_data["slide_title"],
                            bullets=slide_data["bullets"],
                        )
                    )
        else:
            # 降级到旧逻辑
            slides_html.extend(
                self._render_section_slides(section)
            )

    # 结尾页
    slides_html.append(self._render_end_slide(research_result))

    return self._wrap_ppt_html(slides_html)


def _render_chart_split_slide(
    self,
    title: str,
    bullets: List[str],
    chart_suggestion: Dict,
    data_labels: List[Dict],
) -> str:
    """渲染图文混排幻灯片HTML"""
    bullets_html = "".join(
        f"<li>{html.escape(b)}</li>" for b in bullets
    )
    data_html = "".join(
        f'<span class="data-label">{html.escape(d["value"])}'
        f" - {html.escape(d.get('context', ''))}</span>"
        for d in data_labels
    )

    return (
        f'<section class="slide" data-type="chart_split"'
        f' data-chart-type="{chart_suggestion.get("type", "bar")}">'
        f"  <h2>{html.escape(title)}</h2>"
        f'  <div class="slide-content split-layout">'
        f'    <div class="text-column">'
        f"      <ul>{bullets_html}</ul>"
        f'      <div class="data-labels">{data_html}</div>'
        f"    </div>"
        f'    <div class="chart-column">'
        f'      <div class="chart-placeholder"'
        f'        data-chart-type="{chart_suggestion.get("type", "bar")}"'
        f'        data-chart-desc="{html.escape(chart_suggestion.get("description", ""))}"'
        f'        data-section-title="{html.escape(title)}"'
        f"      />"
        f"    </div>"
        f"  </div>"
        f"</section>"
    )


def _generate_ppt_html_fallback(self, research_result: Dict) -> str:
    """降级模式：无结构化slides时使用智能要点提取（替代段落感知分块）"""
    # ... 类似旧逻辑，但使用 _extract_bullets_from_content() 替代 _split_content_for_slides()
    pass


def _extract_bullets_from_content(self, content: str) -> List[str]:
    """从段落内容中智能提取要点（替代段落感知分块的密集段落输出）"""
    # 1. 优先提取已有的列表项
    # 2. 按句号分割，取每句核心
    # 3. 去除冗余修饰，保留"主语+数据+结论"
    pass
```

### 4.6 图表传递链修复

**修改文件**: `src/content/content_orchestrator.py`

**核心改动**：PPTX路径不再跳过图表

**当前代码**（line 290-347）：
```python
if output_format == "html":
    # 图表解析为base64或文件路径，插入HTML
    ...
else:
    # DOCX/PPTX: 传递原始数据（PPT模板跳过图表渲染）
    section_dict["charts"] = charts_data  # template skips
```

**改造后**：

```python
if output_format == "html":
    # HTML: 图表解析为base64或文件路径
    for chart in charts:
        chart_dict = self._resolve_chart_for_html(chart, output_dir)
        resolved_charts.append(chart_dict)
elif output_format == "pptx":
    # PPTX: 图表生成为PNG文件，路径传递给转换器
    for chart in charts:
        chart_path = self._generate_chart_image(chart, strategy.get_chart_style())
        resolved_charts.append({
            "type": "image",
            "src": str(chart_path),
            "alt": chart.get("title", ""),
            "chart_type": chart.get("chart_type", "bar"),
            "width": 7.5,
            "height": 4.5,
        })
    section_dict["charts"] = resolved_charts
else:
    # DOCX/PDF: 保持现有逻辑
    section_dict["charts"] = charts_data
```

> **⚠️ `_generate_chart_image()` 实现细节**：
> 此方法为新增方法，需完成从 `charts_data` 字典到 `ChartConfig` 再到 PNG 的转换：
> ```python
> def _generate_chart_image(
>     self,
>     chart_data: Dict,
>     chart_style: ChartStyleConfig,
> ) -> str:
>     """从图表数据字典生成格式适配的PNG图片"""
>     # 1. 从 chart_data 构建 ChartConfig
>     from src.services.chart_generator import ChartType
>     config = ChartConfig(
>         chart_type=ChartType(chart_data.get("chart_type", "bar")),
>         title=chart_data.get("title", ""),
>         data=chart_data.get("data", {}),
>         xlabel=chart_data.get("xlabel", ""),
>         ylabel=chart_data.get("ylabel", ""),
>         width=int(chart_style.figsize[0]),
>         height=int(chart_style.figsize[1]),
>         dpi=chart_style.dpi,
>     )
>     # 2. 调用 ChartGenerator 生成 PNG
>     generator = ChartGenerator(output_dir=self._output_dir)
>     result = generator.generate_with_format_config(config, chart_style)
>     if result.success:
>         return result.image_path
>     else:
>         logger.warning(f"Chart generation failed: {result.error}")
>         return ""
> ```
> 若 `charts_data` 为 `chart_suggestion` 文本描述（非结构化数据），
> 需先经 `ChartPlannerAgent`（`src/services/chart_planner.py`）规划为 `ChartConfig`。

---

## 5. 改造项三：PPT图表渲染与视觉体系

### 5.1 图表生成格式适配

**修改文件**: `src/services/chart_generator.py`

> **⚠️ 真实代码约束**：`ChartConfig` 的 `width`/`height` 字段标注为 `int` 类型（英寸，line 71-72），
> 但 `height: int = 5.5` 存在类型标注与默认值不匹配的已有bug（应为 `float`）。
> `figsize` 在 `_create_figure()` 中由 `(config.width, config.height)` 构建（line 206）。
> 因此格式适配应修改 `config.width`/`config.height`，且应使用 `float` 而非 `int` 转换。
> 此外，`_save_figure()`（line 228）硬编码 `dpi=150`，忽略了 `config.dpi` 字段。
> `ChartGenerator` 无 `_default_dpi` 属性。需一并修复 `_save_figure()` 以使用 `config.dpi`。

**新增方法**：

```python
def generate_with_format_config(
    self,
    config: ChartConfig,
    format_style: Optional[ChartStyleConfig] = None,
) -> str:
    """格式感知的图表生成"""
    if format_style is None:
        return self.generate(config)

    original_width = config.width
    original_height = config.height
    original_dpi = config.dpi

    try:
        config.width = float(format_style.figsize[0])
        config.height = float(format_style.figsize[1])
        config.dpi = format_style.dpi
        return self.generate(config)
    finally:
        config.width = original_width
        config.height = original_height
        config.dpi = original_dpi
```

**`_save_figure()` 修复**（line 222-231）：当前硬编码 `dpi=150`，需改为使用 `config.dpi`：

```python
def _save_figure(self, fig: plt.Figure, name: str, config: ChartConfig = None) -> str:
    """Save figure with unique filename"""
    if config:
        self._add_annotations(fig, config)
    self._chart_counter += 1
    image_path = str(self.output_dir / f"{name}_{self._chart_counter}.png")
    dpi = config.dpi if config else 150  # 修复：使用 config.dpi 而非硬编码
    fig.savefig(image_path, dpi=dpi, bbox_inches='tight',
               facecolor='white', edgecolor='none')
    plt.close(fig)
    return image_path
```

**`_create_figure()` 方法改造**（line 204）：

> **⚠️ 真实代码约束**：`ChartConfig` 只有 `width`/`height` 字段（无 `figsize` 属性），
> 且 `height: int = 5.5` 存在类型标注与默认值不匹配的已有bug。
> 格式适配时应统一使用 `float` 类型，避免 `int()` 截断小数（如 4.5→4）。

```python
def _create_figure(
    self,
    config: ChartConfig,
    format_style: Optional[ChartStyleConfig] = None,
) -> tuple:
    style = format_style or ChartStyleConfig()

    fig, ax = plt.subplots(
        figsize=(config.width, config.height),
        dpi=style.dpi,
    )

    fig.patch.set_alpha(0 if style.transparent_bg else 1.0)
    ax.set_facecolor("#FAFAFA" if not style.transparent_bg else "none")

    ax.set_title(
        config.title or "",
        fontsize=style.title_fontsize,
        fontweight="bold",
        color="#1A2744",
        pad=15,
    )

    ax.tick_params(labelsize=style.tick_fontsize)
    ax.xaxis.label.set_size(style.label_fontsize)
    ax.yaxis.label.set_size(style.label_fontsize)

    return fig, ax
```

### 5.2 PPT布局引擎

**新增文件**: `src/converters/ppt_layout_engine.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor


@dataclass
class LayoutContext:
    slide_width: float = 13.333
    slide_height: float = 7.5
    margin_left: float = 0.5
    margin_right: float = 0.5
    margin_top: float = 0.5
    margin_bottom: float = 0.5
    title_height: float = 1.0
    footer_height: float = 0.3
    accent_color: str = "#C9A227"
    primary_color: str = "#1A2744"
    bg_gradient_start: str = "#1A2744"
    bg_gradient_end: str = "#2C3E50"


class SlideLayoutBase(ABC):

    @abstractmethod
    def render(
        self,
        prs: Presentation,
        ctx: LayoutContext,
        **kwargs,
    ) -> None:
        pass


class CoverLayout(SlideLayoutBase):

    def render(self, prs, ctx, title="", subtitle="", **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 渐变背景
        # 注意：python-pptx 的 gradient API 需要使用 fill.gradient_stops 添加色标
        # 如果 gradient_stops 默认数量不足2个，需先 add_stop 再设置颜色
        bg = slide.background
        fill = bg.fill
        fill.gradient()
        try:
            fill.gradient_stops[0].color.rgb = RGBColor.from_string(ctx.bg_gradient_start[1:])
            fill.gradient_stops[0].position = 0.0
            fill.gradient_stops[1].color.rgb = RGBColor.from_string(ctx.bg_gradient_end[1:])
            fill.gradient_stops[1].position = 1.0
        except IndexError:
            # 降级：使用纯色背景
            fill.solid()
            fill.fore_color.rgb = RGBColor.from_string(ctx.bg_gradient_start[1:])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(2.5),
            Inches(ctx.slide_width - ctx.margin_left - ctx.margin_right),
            Inches(1.5),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(44)
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        p.font.bold = True
        p.alignment = 1

        # 副标题
        if subtitle:
            sub_box = slide.shapes.add_textbox(
                Inches(ctx.margin_left),
                Inches(4.2),
                Inches(ctx.slide_width - ctx.margin_left - ctx.margin_right),
                Inches(0.8),
            )
            tf = sub_box.text_frame
            p = tf.paragraphs[0]
            p.text = subtitle
            p.font.size = Pt(20)
            p.font.color.rgb = RGBColor(0xC9, 0xA2, 0x27)
            p.alignment = 1

        # 底部装饰条
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(ctx.slide_height - ctx.footer_height),
            Inches(ctx.slide_width),
            Inches(ctx.footer_height),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        bar.line.fill.background()


class ChartFullLayout(SlideLayoutBase):
    """全幅图表页：标题 + 图表 + 底部要点"""

    def render(self, prs, ctx, title="", chart_path="", bullets=None, **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 标题栏 + 底部金色线
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(ctx.margin_top),
            Inches(ctx.slide_width - 1),
            Inches(0.8),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
        p.font.bold = True

        # 标题底部装饰线
        accent_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(ctx.margin_left),
            Inches(1.3),
            Inches(2),
            Inches(0.04),
        )
        accent_line.fill.solid()
        accent_line.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        accent_line.line.fill.background()

        # 图表
        if chart_path:
            chart_left = Inches(1.5)
            chart_top = Inches(1.6)
            chart_width = Inches(10)
            chart_height = Inches(4.5)
            slide.shapes.add_picture(
                chart_path, chart_left, chart_top, chart_width, chart_height
            )

        # 底部要点
        if bullets:
            bullet_box = slide.shapes.add_textbox(
                Inches(ctx.margin_left),
                Inches(6.3),
                Inches(ctx.slide_width - 1),
                Inches(1.0),
            )
            tf = bullet_box.text_frame
            for i, bullet in enumerate(bullets[:3]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = f"• {bullet}"
                p.font.size = Pt(14)
                p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
                p.space_after = Pt(4)


class ChartSplitLayout(SlideLayoutBase):
    """图文混排页：左侧要点 + 右侧图表"""

    def render(
        self,
        prs,
        ctx,
        title="",
        bullets=None,
        chart_path="",
        data_labels=None,
        **kwargs,
    ):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(ctx.margin_top),
            Inches(ctx.slide_width - 1),
            Inches(0.8),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
        p.font.bold = True

        # 标题装饰线
        accent_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(ctx.margin_left),
            Inches(1.3),
            Inches(2),
            Inches(0.04),
        )
        accent_line.fill.solid()
        accent_line.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        accent_line.line.fill.background()

        # 左侧要点（占40%宽度）
        left_width = (ctx.slide_width - ctx.margin_left - ctx.margin_right) * 0.4
        bullet_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(1.6),
            Inches(left_width),
            Inches(4.5),
        )
        tf = bullet_box.text_frame
        tf.word_wrap = True
        if bullets:
            for i, bullet in enumerate(bullets[:5]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = f"• {bullet}"
                p.font.size = Pt(16)
                p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
                p.space_after = Pt(8)

        # 数据标签
        if data_labels:
            label_box = slide.shapes.add_textbox(
                Inches(ctx.margin_left),
                Inches(6.2),
                Inches(left_width),
                Inches(0.8),
            )
            tf = label_box.text_frame
            for i, dl in enumerate(data_labels[:3]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = f"{dl.get('value', '')} - {dl.get('context', '')}"
                p.font.size = Pt(12)
                p.font.color.rgb = RGBColor.from_string(ctx.accent_color[1:])
                p.font.bold = True

        # 右侧图表（占55%宽度）
        if chart_path:
            chart_left = Inches(ctx.margin_left + left_width + 0.3)
            chart_top = Inches(1.6)
            chart_width = Inches(
                (ctx.slide_width - ctx.margin_left - ctx.margin_right) * 0.55
            )
            chart_height = Inches(4.5)
            slide.shapes.add_picture(
                chart_path, chart_left, chart_top, chart_width, chart_height
            )

        # 底部装饰条
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(ctx.slide_height - 0.15),
            Inches(ctx.slide_width),
            Inches(0.15),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        bar.line.fill.background()


class BulletLayout(SlideLayoutBase):
    """纯要点页"""

    def render(self, prs, ctx, title="", bullets=None, **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(ctx.margin_top),
            Inches(ctx.slide_width - 1),
            Inches(0.8),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
        p.font.bold = True

        # 装饰线
        accent_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(ctx.margin_left),
            Inches(1.3),
            Inches(2),
            Inches(0.04),
        )
        accent_line.fill.solid()
        accent_line.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        accent_line.line.fill.background()

        # 要点
        if bullets:
            bullet_box = slide.shapes.add_textbox(
                Inches(ctx.margin_left + 0.3),
                Inches(1.6),
                Inches(ctx.slide_width - 1.6),
                Inches(5.0),
            )
            tf = bullet_box.text_frame
            tf.word_wrap = True
            for i, bullet in enumerate(bullets[:7]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = f"• {bullet}"
                p.font.size = Pt(18)
                p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
                p.space_after = Pt(10)


class KPIHighlightLayout(SlideLayoutBase):
    """KPI指标突出页"""

    def render(self, prs, ctx, title="", data_labels=None, **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(ctx.margin_top),
            Inches(ctx.slide_width - 1),
            Inches(0.8),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
        p.font.bold = True

        # KPI大数字
        if data_labels:
            num_kpis = min(len(data_labels), 4)
            kpi_width = (ctx.slide_width - 1) / num_kpis

            for i, dl in enumerate(data_labels[:4]):
                left = Inches(ctx.margin_left + i * kpi_width)
                top = Inches(2.5)
                width = Inches(kpi_width - 0.3)
                height = Inches(3.0)

                # 背景矩形
                bg_shape = slide.shapes.add_shape(
                    MSO_SHAPE.ROUNDED_RECTANGLE,
                    left, top, width, height,
                )
                bg_shape.fill.solid()
                bg_shape.fill.fore_color.rgb = RGBColor(0xF5, 0xF5, 0xF5)
                bg_shape.line.color.rgb = RGBColor.from_string(ctx.accent_color[1:])
                bg_shape.line.width = Pt(2)

                # 数值
                kpi_box = slide.shapes.add_textbox(
                    left + Inches(0.1),
                    top + Inches(0.5),
                    width - Inches(0.2),
                    Inches(1.5),
                )
                tf = kpi_box.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = dl.get("value", "")
                p.font.size = Pt(36)
                p.font.color.rgb = RGBColor.from_string(ctx.accent_color[1:])
                p.font.bold = True
                p.alignment = 1

                # 说明
                desc_box = slide.shapes.add_textbox(
                    left + Inches(0.1),
                    top + Inches(2.0),
                    width - Inches(0.2),
                    Inches(0.8),
                )
                tf = desc_box.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = dl.get("context", "")
                p.font.size = Pt(14)
                p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
                p.alignment = 1


class DataTableLayout(SlideLayoutBase):
    """数据表格页"""

    def render(self, prs, ctx, title="", table_data=None, **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(ctx.margin_top),
            Inches(ctx.slide_width - 1),
            Inches(0.8),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.color.rgb = RGBColor.from_string(ctx.primary_color[1:])
        p.font.bold = True

        # 表格
        if table_data:
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            num_rows = len(rows) + 1
            num_cols = len(headers)

            tbl_shape = slide.shapes.add_table(
                num_rows, num_cols,
                Inches(1), Inches(1.6),
                Inches(ctx.slide_width - 2), Inches(0.45 * num_rows),
            )
            tbl = tbl_shape.table

            # 表头样式
            for j, h in enumerate(headers):
                cell = tbl.cell(0, j)
                cell.text = h
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.font.size = Pt(14)
                    paragraph.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    paragraph.font.bold = True
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(ctx.primary_color[1:])

            # 数据行
            for i, row in enumerate(rows):
                for j, val in enumerate(row):
                    if j < num_cols:
                        cell = tbl.cell(i + 1, j)
                        cell.text = str(val)
                        for paragraph in cell.text_frame.paragraphs:
                            paragraph.font.size = Pt(12)
                        if i % 2 == 0:
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = RGBColor(0xF5, 0xF5, 0xF5)


class EndLayout(SlideLayoutBase):

    def render(self, prs, ctx, title="谢谢", **kwargs):
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 渐变背景（与CoverLayout相同的降级策略）
        bg = slide.background
        fill = bg.fill
        fill.gradient()
        try:
            fill.gradient_stops[0].color.rgb = RGBColor.from_string(ctx.bg_gradient_start[1:])
            fill.gradient_stops[0].position = 0.0
            fill.gradient_stops[1].color.rgb = RGBColor.from_string(ctx.bg_gradient_end[1:])
            fill.gradient_stops[1].position = 1.0
        except IndexError:
            fill.solid()
            fill.fore_color.rgb = RGBColor.from_string(ctx.bg_gradient_start[1:])

        # 标题
        title_box = slide.shapes.add_textbox(
            Inches(ctx.margin_left),
            Inches(2.5),
            Inches(ctx.slide_width - 1),
            Inches(1.5),
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(44)
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        p.font.bold = True
        p.alignment = 1

        # 底部装饰条
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0),
            Inches(ctx.slide_height - ctx.footer_height),
            Inches(ctx.slide_width),
            Inches(ctx.footer_height),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(ctx.accent_color[1:])
        bar.line.fill.background()


LAYOUT_REGISTRY = {
    "cover": CoverLayout(),
    "chart_full": ChartFullLayout(),
    "chart_split": ChartSplitLayout(),
    "bullet_points": BulletLayout(),
    "kpi_highlight": KPIHighlightLayout(),
    "data_table": DataTableLayout(),
    "end": EndLayout(),
}


def get_layout(layout_name: str) -> SlideLayoutBase:
    return LAYOUT_REGISTRY.get(layout_name, BulletLayout())
```

### 5.3 HTMLToPPTConverter 改造

**修改文件**: `src/converters/html_to_ppt.py`

**核心改动**:

1. 幻灯片尺寸改为16:9（`13.333" x 7.5"`）

2. `_create_pptx_document()` 使用布局引擎替代硬编码

3. 新增图表渲染逻辑

4. **修复 SlideElementParser 输出格式不匹配问题**

> **⚠️ 真实代码约束**：`SlideElementParser.get_slides()` 返回 `List[List[Dict]]`（每页是一个元素字典列表），
> 但当前 `_create_pptx_document()` 期望 `List[Dict]`（每个 dict 带 `slide_type`/`title`/`content`/`items` 键）。
> 这两者格式不匹配。需要新增一个 **适配层**，将 `SlideElementParser` 的元素列表转换为布局引擎所需的 `slides_data` 格式：
> - 按 `<h1>` 分页的元素列表 → 提取每页的 slide_type、title、bullets、chart_path 等
> - `<section class="slide" data-type="...">` 标签 → slide_type 字段
> - `{"type": "image", "src": "..."}` 元素 → chart_path 字段

```python
from src.converters.ppt_layout_engine import get_layout, LayoutContext


class HTMLToPPTConverter:

    def _create_pptx_document(self, slides_data, styles=None, template_html=None):
        ctx = LayoutContext(
            slide_width=13.333,
            slide_height=7.5,
        )

        if styles:
            ctx.accent_color = styles.get("accent_color", ctx.accent_color)
            ctx.primary_color = styles.get("primary_color", ctx.primary_color)

        prs = Presentation()
        prs.slide_width = Inches(ctx.slide_width)
        prs.slide_height = Inches(ctx.slide_height)

        for slide_data in slides_data:
            slide_type = slide_data.get("type", "content")
            layout_name = self._map_slide_type_to_layout(slide_type, slide_data)
            layout = get_layout(layout_name)

            kwargs = self._prepare_layout_kwargs(slide_data, slide_type)

            layout.render(prs, ctx, **kwargs)

        return prs

    def _map_slide_type_to_layout(self, slide_type: str, slide_data: dict) -> str:
        """根据幻灯片类型和数据选择布局"""
        mapping = {
            "cover": "cover",
            "end": "end",
            "toc": "bullet_points",
            "findings": "bullet_points",
            "data": "data_table",
        }

        if slide_type in mapping:
            return mapping[slide_type]

        # 图文混排判断
        has_chart = (
            slide_data.get("chart_suggestion")
            or slide_data.get("chart_path")
            or slide_data.get("chart_placeholder")
        )
        has_bullets = bool(slide_data.get("bullets"))

        if has_chart and has_bullets:
            return "chart_split"
        elif has_chart:
            return "chart_full"
        elif slide_data.get("data_labels") and not has_bullets:
            return "kpi_highlight"
        else:
            return "bullet_points"

    def _prepare_layout_kwargs(self, slide_data: dict, slide_type: str) -> dict:
        """从解析后的幻灯片数据提取布局参数"""
        kwargs = {
            "title": slide_data.get("title", ""),
        }

        if slide_type == "data":
            kwargs["table_data"] = slide_data.get("table_data")
        elif slide_type == "cover":
            kwargs["subtitle"] = slide_data.get("subtitle", "")
        else:
            kwargs["bullets"] = slide_data.get("bullets", [])
            kwargs["chart_path"] = slide_data.get("chart_path", "")
            kwargs["data_labels"] = slide_data.get("data_labels")

        return kwargs
```

### 5.4 CSS样式提取扩展

**修改文件**: `src/converters/css_extractor.py`

**改动点**: `to_ppt_styles()` 方法（line 83-93）扩展提取颜色和装饰信息

> **⚠️ 真实代码约束**：
> - `ExtractedStyles` dataclass 当前**不包含**颜色字段（`accent_color`、`bg_gradient_start` 等）
> - `_extract_color()` 方法**不存在**于 `ExtractedStyles` 中，实际的色彩解析方法是 `CSSStyleExtractor._parse_color()`（line 525）
> - 颜色数据需从 `CSSStyleExtractor._extract_key_styles()`（line 383）填充到 `ExtractedStyles` 字段
> 
> 因此扩展方案需三步改造：
> 1. 在 `ExtractedStyles` dataclass 中新增颜色字段
> 2. 在 `CSSStyleExtractor._extract_key_styles()` 中从 CSS 规则提取颜色并填充
> 3. `to_ppt_styles()` 中引用新增字段

```python
# Step 1: ExtractedStyles dataclass 新增字段
@dataclass
class ExtractedStyles:
    # ... 现有字段 ...
    # 新增颜色字段
    primary_color: str = "#1A2744"
    accent_color: str = "#C9A227"
    bg_gradient_start: str = "#1A2744"
    bg_gradient_end: str = "#2C3E50"
    text_light: str = "#FFFFFF"
    table_header_bg: str = "#1A2744"
    footer_bar_color: str = "#C9A227"

# Step 2: CSSStyleExtractor._extract_key_styles() 中填充颜色
# 在现有提取逻辑中增加颜色提取（使用 self._parse_color()）

# Step 3: to_ppt_styles() 扩展
def to_ppt_styles(self) -> Dict[str, Any]:
    styles = {
        "title_font": self.title_font,
        "body_font": self.body_font,
        "title_size": self.ppt_title_size,
        "subtitle_size": self.ppt_subtitle_size,
        "body_size": self.ppt_body_size,
        "slide_width": 13.333,
        "slide_height": 7.5,
        # 新增颜色
        "primary_color": self.primary_color,
        "accent_color": self.accent_color,
        "bg_gradient_start": self.bg_gradient_start,
        "bg_gradient_end": self.bg_gradient_end,
        "text_light": self.text_light,
        "table_header_bg": self.table_header_bg,
        "footer_bar_color": self.footer_bar_color,
    }
    return styles
```

### 5.5 PPT图表生成与插入流程

完整的PPT图表流程（修复后）：

```
ChapterWriter (PPT模式)
  ↓ 输出 chart_suggestion: {type: "bar", description: "市场规模对比"}
  ↓
ReportOrchestrator._assemble_final_report(output_format="pptx")
  ↓ 写入 section_dict["chart_suggestions"]（修正原硬编码 charts: []）
  ↓
ContentOrchestrator._generate_ppt_html_from_slides()
  ↓ chart_suggestion → chart_placeholder (data-chart-type, data-chart-desc)
  ↓
【关键环节】ChartPlannerAgent 分析 section 数据 + chart_suggestion
  ↓ 确定 ChartConfig（类型、数据、标题）
  ↓
ChartGenerator.generate_with_format_config(PPTXStrategy.get_chart_style())
  ↓ 产出 PNG (7.5"×4.5", 200DPI, 透明背景, 16pt字号)
  ↓ PNG路径写入 chart_placeholder 的 data-chart-src 属性
  ↓
SlideElementParser 解析 HTML
  ↓ chart_placeholder → {"type": "chart_placeholder", "chart_src": PNG路径, ...}
  ↓
HTMLToPPTConverter._prepare_layout_kwargs()
  ↓ 从 slide_data 提取 chart_path = slide_data["chart_src"]
  ↓
ChartSplitLayout.render(chart_path=PNG路径)
  ↓ slide.shapes.add_picture(chart_path, ...)
  ↓ 产出图文混排幻灯片
```

> **⚠️ 重要补充**：当前设计文档中的流程在 `_generate_ppt_html_from_slides()` 到 `ChartGenerator.generate()` 之间缺少
> **图表规划**这一步。`chart_suggestion` 只是文本描述（如"柱状图展示市场规模"），不能直接传给 `ChartGenerator`。
> 需要现有的 `ChartPlannerAgent`（`src/services/chart_planner.py`）分析 section 数据 + chart_suggestion，
> 产出具体的 `ChartConfig`（类型、数据列、标题），才能调用 `ChartGenerator` 生成 PNG。
> 这一步在 PPT 图表流程中不可省略，`SmartChartGenerator` 为假设概念，实际复用 `ChartPlannerAgent`。
> 
> **⚠️ PDF图表流程**：当前 `HTMLToPDFConverter`（`html_to_pdf.py`）的 `_create_reportlab_document()` 方法
> **完全没有 `image` 元素类型的处理**，图表和图片在PDF中完全丢失。需补充使用 `reportlab.platypus.Image`
> 的图片渲染逻辑。PDF图表流程修复应作为 P1 优先级，与PPT图表修复同步进行。

---

## 6. 改造项四：质检阶段格式适配

### 6.1 QualityCheckAgent 扩展

**修改文件**: `src/agents/fixed_agents/quality_check_agent.py`

**改动点**：`execute()` 方法增加 `output_format` 参数

```python
async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
    report_data = input_data.get("report", {})
    output_format = input_data.get("output_format", "docx")

    strategy = get_format_strategy(output_format)
    quality_standard = strategy.get_quality_standard()

    # ⚠️ 当前 _check_completeness/_check_accuracy/_check_format 签名为 (report, standards: Dict)
    # QualityStandard 对象需转换为 Dict 后传入
    standards_dict = {
        "max_paragraph_chars": quality_standard.max_paragraph_chars,
        "min_chart_count_per_section": quality_standard.min_chart_count_per_section,
        "max_slide_text_chars": quality_standard.max_slide_text_chars,
        "require_visual_balance": quality_standard.require_visual_balance,
        "check_items": quality_standard.check_items,
    }

    completeness_result = self._check_completeness(report_data, standards_dict)
    accuracy_result = self._check_accuracy(report_data, standards_dict)
    consistency_result = self._check_consistency(report_data)  # 注意：此方法只接收 report
    format_result = self._check_format(report_data, standards_dict)

    # 格式专项检查
    if output_format == "pptx":
        ppt_result = self._check_ppt_quality(report_data, quality_standard)
        format_result["issues"].extend(ppt_result.get("issues", []))
        format_result["suggestions"].extend(ppt_result.get("suggestions", []))

    # ... 评分逻辑 ...
```

### 6.2 PPT专项质检

**新增方法**：

```python
def _check_ppt_quality(
    self,
    report_data: Dict,
    standard: QualityStandard,
) -> Dict[str, Any]:
    issues = []
    suggestions = []

    for section in report_data.get("sections", []):
        section_title = section.get("title", "")

        # 检查1：图表覆盖率
        has_chart = bool(section.get("chart_suggestions") or section.get("charts"))
        slides = section.get("slides", [])

        if slides:
            slides_with_chart = sum(
                1 for s in slides if s.get("chart_suggestion")
            )
            chart_ratio = slides_with_chart / len(slides) if slides else 0

            if chart_ratio < 0.3 and standard.min_chart_count_per_section > 0:
                issues.append({
                    "type": "low_chart_coverage",
                    "section": section_title,
                    "message": f"图表覆盖率仅{chart_ratio:.0%}，建议至少30%",
                    "severity": "medium",
                })

        # 检查2：要点精炼度
        for slide in slides:
            for bullet in slide.get("bullets", []):
                if len(bullet) > standard.max_slide_text_chars:
                    issues.append({
                        "type": "verbose_bullet",
                        "section": section_title,
                        "message": f"要点过长({len(bullet)}字): {bullet[:30]}...",
                        "severity": "low",
                    })

        # 检查3：幻灯片焦点（每页应只有一个核心观点）
        for slide in slides:
            if len(slide.get("bullets", [])) > 6:
                issues.append({
                    "type": "slide_overload",
                    "section": section_title,
                    "message": f"单页要点数{len(slide['bullets'])}个，建议不超过6个",
                    "severity": "medium",
                })

    return {"issues": issues, "suggestions": suggestions}
```

---

## 7. 改造项五：格式约束一致性

### 7.1 统一枚举定义

**当前问题**：`OutputFormat` 枚举在三个地方定义且不一致：
- `smart_clarifier.py:84-90` — DOCX, PPTX, PDF, MD, HTML（含MD）
- `document_models.py:25-30` — DOCX, PPTX, PDF, HTML（无MD）
- `document_api.py:82-87` — DOCX, PPTX, PDF, HTML（无MD）

**改造方案**：统一到 `src/content/format_strategy.py` 中的 `OutputFormat` 枚举，其他文件引用它。

```python
# src/content/format_strategy.py
class OutputFormat(Enum):
    DOCX = "docx"
    PPTX = "pptx"
    PDF = "pdf"
    HTML = "html"
    # MD 暂不支持，待后续实现转换器后加入
```

**修改文件**:
- `src/core/orchestrator/smart_clarifier.py` — 删除本地 `OutputFormat`，引用统一枚举
- `src/agents/fixed_agents/document_models.py` — 删除本地 `DocumentFormat`，引用统一枚举
- `src/api/document_api.py` — 删除本地 `OutputFormat`，引用统一枚举

### 7.2 模板格式约束校验

**现状**：`Template` dataclass（`smart_clarifier.py:146-157`）已有 `supported_formats` 字段，
由 `TemplateLoader._load_template_from_yaml()`（`smart_clarifier.py:233-268`）从 YAML 解析填充。
所有 YAML 模板文件均已配置 `supported_formats`。

**⚠️ 需修复问题**：部分 YAML 模板的 `supported_formats` 为空列表（如 `commercial_plan.yaml`、
`conference_call.yaml`、`industry_weekly.yaml` 等），`TemplateLoader` 解析后降级为 `[DOCX]`
（line 256-257），导致这些模板只能输出 DOCX。需补全这些 YAML 模板的 `supported_formats` 配置。

**修改文件**: `config/templates/*.yaml`（补全空列表模板的 supported_formats）

用户选择格式时，校验是否在模板的 `supported_formats` 范围内：

```python
def select_output_format(self, session_id, output_type, selected_template):
    template = self._templates.get(selected_template)
    supported = [f.value for f in template.supported_formats]

    return {
        "format_options": supported,
        "default": "docx" if "docx" in supported else supported[0],
    }
```

---

## 8. 实施优先级与里程碑

### 8.1 优先级定义

| 优先级 | 定义 | 理由 |
|--------|------|------|
| P0 | 阻断性修复 | 没有这些，PPT完全不可用 |
| P1 | 核心功能 | 实现格式感知的核心价值 |
| P2 | 品质提升 | 提升专业度和用户体验 |
| P3 | 锦上添花 | 非必要但提升竞争力 |

### 8.2 分期实施计划

#### Phase 1：断裂修复（P0，预计4天）

| # | 改造项 | 文件 | 产出 |
|---|--------|------|------|
| 1.1 | HTMLToPPTConverter增加`add_picture()` | `html_to_ppt.py` | PPT可显示图表 |
| 1.2 | ContentOrchestrator PPTX路径不跳过图表 | `content_orchestrator.py:290-347` | 图表传递到PPT |
| 1.3 | HTMLToPDFConverter增加`image`元素处理 | `html_to_pdf.py` | PDF可显示图表 |
| 1.4 | `_export_document()` 格式路由 | `document_api.py:497-620` | format参数实际生效 |
| 1.5 | 幻灯片尺寸改为16:9 | `html_to_ppt.py:464-465` | 现代宽屏PPT |
| 1.6 | 导出按钮格式选择 | `DocumentPreview.tsx:425` | 用户可选格式导出 |
| 1.7 | `_save_figure()` 使用 `config.dpi` | `chart_generator.py:228` | DPI配置生效 |

**验收标准**：选择PPTX格式导出后，PPT中包含matplotlib生成的图表图片；选择PDF格式导出后，PDF中包含图表图片；`_export_document()` 根据format参数路由到正确转换器。

#### Phase 2：格式感知核心（P1，预计5天）

> **⚠️ 前提条件**：Phase 2 依赖部分 YAML 模板补全 `supported_formats` 配置（当前为空列表导致降级为DOCX only）。

| # | 改造项 | 文件 | 产出 |
|---|--------|------|------|
| 2.0 | YAML模板补全`supported_formats`空列表 | `config/templates/*.yaml` | 模板格式约束可用 |
| 2.1 | FormatStrategy接口+三种实现 | 新建`format_strategy.py` | 格式策略层 |
| 2.2 | ChapterWriteInput/Output扩展 | `models.py` | 格式感知数据模型 |
| 2.3 | ChapterWriter PPT格式感知 | `chapter_writer.py` + `chapter_write.tmpl` | PPT内容源头产出要点 |
| 2.4 | SmartClarifier格式选择步骤 | `smart_clarifier.py` + `main.py` + 前端 | 用户可选格式 |
| 2.5 | ChartGenerator格式适配 | `chart_generator.py` | PPT专用图表样式 |
| 2.6 | ContentOrchestrator智能PPT生成 | `content_orchestrator.py` | 替代段落感知分块 |
| 2.7 | SlideElementParser扩展chart_placeholder | `base_parser.py` | 解析data-chart-*属性 |

**验收标准**：用户在任务配置阶段选择PPTX后，ChapterWriter产出要点式内容，PPT中包含精炼要点和格式适配的图表；SlideElementParser能解析chart_placeholder的data-chart-*属性。

#### Phase 3：PPT视觉体系（P2，预计5天）

| # | 改造项 | 文件 | 产出 |
|---|--------|------|------|
| 3.1 | PPT布局引擎 | 新建`ppt_layout_engine.py` | 7种幻灯片布局 |
| 3.2 | HTMLToPPTConverter使用布局引擎 | `html_to_ppt.py` | 图文混排幻灯片 |
| 3.3 | CSS提取器扩展 | `css_extractor.py` + `ExtractedStyles` | 提取颜色/渐变（含dataclass字段新增） |
| 3.4 | QualityCheckAgent PPT质检 | `quality_check_agent.py` | 图表覆盖率检查 |
| 3.5 | 统一OutputFormat枚举 | 多文件 | 格式定义一致性 |

**验收标准**：PPT包含渐变封面、金色装饰线、图文混排页、带样式的数据表格，质检报告包含图表覆盖率指标。

#### Phase 4：增强特性（P3，预计3天）

| # | 改造项 | 文件 | 产出 |
|---|--------|------|------|
| 4.1 | KPI突出页布局 | `ppt_layout_engine.py` | 大数字展示 |
| 4.2 | 对比双栏布局 | `ppt_layout_engine.py` | 左右对比分析 |
| 4.3 | python-pptx原生图表 | `html_to_ppt.py` | PPT中可编辑图表 |
| 4.4 | 幻灯片备注（Speaker Notes） | `html_to_ppt.py` | 演讲者提示 |
| 4.5 | MD格式转换器 | 新建`html_to_md.py` | Markdown输出 |

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ChapterWriter PPT模式LLM输出格式不稳定 | 中 | PPT内容解析失败 | 降级到旧逻辑（段落感知分块）；增加输出格式校验和重试 |
| 图表PNG尺寸在PPT中不协调 | 低 | 视觉效果差 | PPTStrategy配置精确尺寸；ChartSplitLayout自适应缩放 |
| 格式选择UI增加步骤后用户流失 | 低 | 体验下降 | 单格式模板自动跳过；多格式默认选DOCX保持现有行为 |
| 布局引擎与现有SlideElementParser冲突 | 中 | PPT生成失败 | Phase 3中保持两条路径，布局引擎为优先路径，旧路径为fallback |
| 质检PPT专项检查误报 | 低 | 质检循环过多 | 初期仅medium级别提示不阻断，积累数据后调优阈值 |

---

## 10. 兼容性保证

### 10.1 向后兼容

- `output_format` 默认值为 `"docx"`，所有未指定格式的调用保持原有行为
- `ChapterWriteInput.output_format` 默认 `"docx"`，不传参时ChapterWriter行为不变
- `FormatStrategy` 只在明确选择格式后生效
- PPT布局引擎为新增代码，不修改现有 `SlideElementParser` 逻辑

### 10.2 渐进式启用

```python
# settings.py 新增
class FormatAwareConfig:
    enabled: bool = True
    ppt_layout_engine: bool = True       # False时降级到旧逻辑
    ppt_chart_embedding: bool = True     # False时PPT不含图表
    chapter_writer_format_aware: bool = True  # False时ChapterWriter不感知格式
    quality_check_format_aware: bool = True   # False时质检不区分格式
```

---

## 附录A：当前代码文件影响清单

| 文件 | 改动类型 | 优先级 | 改动说明 |
|------|---------|--------|---------|
| `src/content/format_strategy.py` | 新增 | P1 | FormatStrategy接口+三种实现 |
| `src/converters/ppt_layout_engine.py` | 新增 | P2 | PPT布局引擎 |
| `src/converters/html_to_ppt.py` | 修改 | P0/P2 | add_picture支持+布局引擎集成 |
| `src/converters/html_to_pdf.py` | 修改 | P0 | 新增image元素处理（reportlab.platypus.Image） |
| `src/converters/base_parser.py` | 修改 | P1 | SlideElementParser扩展data-chart-*属性解析 |
| `src/content/content_orchestrator.py` | 修改 | P0/P1 | 图表传递修复+智能PPT生成+_generate_chart_image() |
| `src/agents/fixed_agents/report_upgrade/models.py` | 修改 | P1 | ChapterWriteInput/Output扩展+SlideContent新增 |
| `src/agents/fixed_agents/report_upgrade/chapter_writer.py` | 修改 | P1 | PPT格式感知写作（string.Template变量注入） |
| `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl` | 修改 | P1 | 新增${format_directive}占位符 |
| `src/agents/fixed_agents/report_upgrade/orchestrator.py` | 修改 | P1 | output_format传递+slides数据组装 |
| `src/services/chart_generator.py` | 修改 | P0/P1 | _save_figure()使用config.dpi+格式适配图表生成 |
| `src/agents/fixed_agents/quality_check_agent.py` | 修改 | P2 | PPT专项质检（QualityStandard→Dict转换） |
| `src/converters/css_extractor.py` | 修改 | P2 | ExtractedStyles新增颜色字段+to_ppt_styles()扩展 |
| `src/config/report_template.py` | 修改 | P1 | ReportTemplate新增supported_formats字段 |
| `src/core/orchestrator/smart_clarifier.py` | 修改 | P1 | 格式选择步骤 |
| `src/core/orchestrator/orchestrator.py` | 修改 | P1 | output_format传递至generate_report() |
| `src/api/main.py` | 修改 | P1 | interact端点新增select_format action |
| `src/api/document_api.py` | 修改 | P0 | OutputFormat枚举统一+_export_document()格式路由 |
| `src/agents/fixed_agents/document_models.py` | 修改 | P1 | OutputFormat枚举统一 |
| `src/config/settings.py` | 修改 | P2 | FormatAwareConfig |
| `web/src/components/preview/DocumentPreview.tsx` | 修改 | P0 | 导出格式选择器 |
| `web/src/hooks/useResearch.ts` | 修改 | P1 | 格式选择步骤（调用interact端点） |
| `web/src/components/chat/FormatSelector.tsx` | 新增 | P1 | 格式选择UI组件 |

## 附录B：数据流对比

### B.1 当前数据流（DOCX）

```
ResearchRequirement(output_format=DOCX)
  → Research Agents → 分析数据
  → ChapterWriter.write() → 长段落Markdown
  → ReportOrchestrator._assemble_final_report() → {sections: [{content: "长段落..."}]}
  → ContentOrchestrator.transform_to_html("docx") → word_default模板 → 段落式HTML
  → HTMLToWordConverter → .docx (5"宽图表嵌入)
```

### B.2 改造后数据流（PPTX）

```
ResearchRequirement(output_format=PPTX)
  → Research Agents → 分析数据（不变）
  → ChapterWriter.write(output_format="pptx") → 结构化slides + chart_suggestions
  → ReportOrchestrator._assemble_final_report() → {sections: [{slides: [...], chart_suggestions: [...]}]}
  → ContentOrchestrator.transform_to_html("pptx")
      → _generate_ppt_html_from_slides()
      → chart_suggestion → chart_placeholder → ChartPlannerAgent → ChartConfig → PNG
      → ChartGenerator.generate_with_format_config(PPTXStrategy) → PNG (7.5"×4.5", 200DPI)
      → 产出含chart_placeholder的HTML
  → HTMLToPPTConverter._create_pptx_document()
      → _map_slide_type_to_layout() → ChartSplitLayout
      → ChartSplitLayout.render(chart_path=PNG路径) → slide.shapes.add_picture()
  → 产出图文混排PPT
```

### B.3 改造后数据流（DOCX，向后兼容）

```
ResearchRequirement(output_format=DOCX)  # 默认值，未选择格式时行为不变
  → Research Agents → 分析数据（不变）
  → ChapterWriter.write(output_format="docx") → 长段落Markdown（与当前相同）
  → 后续流程与当前完全一致
```

---

## 附录C：审计修正记录

### C.1 v1→v1.1 修正记录

| # | 缺陷描述 | 严重度 | 修正位置 | 修正内容 |
|---|---------|--------|---------|---------|
| 1 | `_assemble_final_report()` 是 `@staticmethod`，设计文档中用 `self._output_format` 访问实例属性 | CRITICAL | 第4.4节 | 将 `output_format` 作为参数传入静态方法，不再依赖 `self` |
| 2 | ChapterWriter 使用 `PromptManager` 模板系统（`self._prompts.get()`），不是字符串拼接 | HIGH | 第4.2节 | 改为通过新增模板变量 `format_directive` 和 `output_format` 注入，配套修改 `chapter_write.tmpl` |
| 3 | `_assemble_final_report()` 中 `charts: []` 硬编码为空，PPT的 `chart_suggestions` 传递受阻 | HIGH | 第4.4节 | 将 `charts: []` 改为 `ch.chart_suggestions or []`，保证图表建议数据流出 |
| 4 | PPT图表流程缺少从 `chart_suggestion`（文本描述）到 `ChartConfig`（具体配置）的规划环节 | HIGH | 第5.5节 | 补充 `ChartPlannerAgent` 步骤，明确不可省略 |
| 5 | `ChartConfig` 的尺寸字段是 `width: int`/`height: int`（英寸），不是 `figsize: tuple` | MEDIUM | 第5.1节 | `generate_with_format_config` 改为修改 `config.width`/`config.height` |
| 6 | python-pptx 渐变背景 `gradient_stops` 默认数量可能不足，需 IndexError 降级处理 | MEDIUM | 第5.2节 CoverLayout/EndLayout | 添加 `try/except IndexError` 降级为纯色背景 |

### C.2 v1.1→v2.0 修正记录

| # | 缺陷描述 | 严重度 | 修正位置 | 修正内容 |
|---|---------|--------|---------|---------|
| 1 | 模板语法体系错误：用了Jinja2 `{% if %}`/`{{var}}`，但 `PromptManager` 使用 `string.Template`（`${var}`），不支持条件逻辑 | CRITICAL | 第4.2节 | 改为Python层面拼接 `format_directive_text`，模板只加 `${format_directive}` 占位符 |
| 2 | `ReportTemplate` dataclass 无 `supported_formats` 字段，`template.supported_formats` 会抛 `AttributeError` | CRITICAL | 第3.1.1节/第7.2节 | 新增前提条件说明+临时降级方案（`hasattr` 检查），Phase 2 首项增加 `report_template.py` 改造 |
| 3 | "500字硬切"描述不准确，实际为段落感知软限制分块 | HIGH | 第0.1/0.2/0.3/4.5/8.2/9节 | 全部修正为"500字符段落感知分块"并说明问题本质 |
| 4 | `ChartConfig.height: int = 5.5` 类型标注与默认值矛盾；`int()` 转换会截断小数 | HIGH | 第5.1节 | `generate_with_format_config()` 改用 `float()` 转换，标注已有类型bug |
| 5 | `_save_figure()` 硬编码 `dpi=150`，`config.dpi` 被完全忽略；`ChartGenerator` 无 `_default_dpi` 属性 | HIGH | 第5.1节 | 重写 `generate_with_format_config()` 使用 `config.dpi`；新增 `_save_figure()` 修复代码；P0新增修复项1.7 |
| 6 | `select_output_type()` 行号错误（文档说565-586，实际588-604） | HIGH | 第3.1.1节 | 修正为 line 588-604 |
| 7 | `ResearchRequirement`/`UserChoice` 行号不精确（类定义与字段位置混淆） | HIGH | 第3.1.1节 | 修正为类定义行号+字段行号 |
| 8 | SmartClarifier 步骤数错误（文档说5步，实际7步） | HIGH | 第3.1节 | 修正为7步→8步 |
| 9 | `to_ppt_styles()` 扩展方案缺少 `ExtractedStyles` dataclass 字段新增和 `CSSStyleExtractor._extract_key_styles()` 数据传递链 | MEDIUM | 第5.4节 | 补充三步改造：dataclass新增字段→_extract_key_styles填充→to_ppt_styles引用 |
| 10 | `_generate_chart_image()` 缺少实现细节（chart_data→ChartConfig→PNG转换逻辑） | MEDIUM | 第4.6节 | 补充完整方法实现代码 |
| 11 | API架构不匹配：文档建议独立端点，但实际通过 `POST /api/v1/research/interact` 统一路由 | MEDIUM | 第3.1.2节/3.1.3节 | 改为 `interact` 端点新增 `action: "select_format"` 分支；修正前端API调用路径 |
| 12 | `HTMLToPDFConverter` 完全无 `image` 元素处理，PDF图表丢失，文档未提及 | MEDIUM | 第0.1/0.2/0.3/5.5/8.2节 | 新增D4缺陷；格式传递链补充PDF图表丢失；Phase 1 新增1.3修复项 |
| 13 | `document_api.py._export_document()` 始终使用HTMLToWordConverter，format参数被忽略 | MEDIUM | 第3.2节 | 新增格式路由改造代码；升级为P0修复项 |
| 14 | `_create_figure()` 改造代码引用不存在的 `config.figsize`，会抛 `AttributeError` | MEDIUM | 第5.1节 | 修正为 `figsize=(config.width, config.height)` |
| 15 | `chapter_write.tmpl` 路径不精确（`prompts/` 有两套体系） | LOW | 第4.2节 | 修正为完整路径 `src/agents/fixed_agents/report_upgrade/prompts/chapter_write.tmpl` |
| 16 | `_check_format` 签名需要 `standards: Dict`，但设计传入 `QualityStandard` 对象；`_check_consistency` 只接收一个参数 | LOW | 第6.1节 | 新增 `QualityStandard`→`Dict` 转换代码；标注 `_check_consistency` 签名差异 |

### C.3 v2.0→v2.1 修正记录

| # | 缺陷描述 | 严重度 | 修正位置 | 修正内容 |
|---|---------|--------|---------|---------|
| 1 | `Template` 类（smart_clarifier.py:146）已有 `supported_formats` 字段且YAML已配置，文档误导说"ReportTemplate需新增此字段" | HIGH | 第3.1.1节/第7.2节/Phase 2前提条件 | 删除"ReportTemplate需新增"的前提条件和hasattr降级；改为说明YAML空列表需补全；Phase 2首项改为YAML补全而非report_template.py改造 |
| 2 | `handle_interact` 用 `step` 整数路由（research_api.py:1988-2107），不是 `action` 字段，文档中用 `action: "select_format"` 的代码示例不匹配实际架构 | HIGH | 第3.1.2节/3.1.3节 | 改为 `step` 编号路由；前端调用改为传递step+response JSON；修正API约束说明 |
| 3 | 部分 YAML 模板 `supported_formats` 为空列表（commercial_plan、conference_call等），TemplateLoader降级为 `[DOCX]`，文档未提及此降级行为 | MEDIUM | 第7.2节 | 新增"需修复问题"说明，列出空列表模板；Phase 2首项改为YAML补全 |
| 4 | `SlideElementParser.get_slides()` 返回 `List[List[Dict]]` 元素列表，但 `_create_pptx_document` 期望 `List[Dict]` 带 slide_type/title/content 键，格式不匹配 | MEDIUM | 第0.3节/第5.3节 | 0.3节PPT图表渲染行补充格式不匹配说明；5.3节新增适配层设计说明 |
| 5 | PPT图表丢失有3个环节而非2个：ContentOrchestrator跳过 → `html.escape()`销毁HTML标签（line 1287）→ HTMLToPPTConverter不处理image元素；文档仅提及2个 | MEDIUM | 第4.5节 | 补充第2个环节：`html.escape(chunk)` 将 `<img>` 转义为纯文本，即使图表嵌入HTML也会被销毁 |
