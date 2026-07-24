# UI/UX Pro Max → Zensers PPT 设计决策引擎集成方案

> 版本：v1.0 | 日期：2026-07-08
> 目标：将 UI/UX Pro Max 的知识驱动设计决策能力集成到 Zensers 的 PPT 生成管线中，提升 PPT 视觉质量
> 约束：**不复制对方代码和文件**，降低重合度；复用设计思想，自主实现

---

## 一、现状对比

### 1.1 Zensers 现有 PPT 系统

| 层级 | 组件 | 能力 | 缺陷 |
|------|------|------|------|
| 数据提取 | `PptInputAdapter` + 7 DataParser | DOCX/PDF/Excel/TXT/CSV/JSON → ExtractionResult | 表格未关联到 section |
| 需求提取 | `PptRequirementExtractor` | 正则提取主题/风格 | 无产品类型识别、无情绪弧线 |
| 数据补充 | `PptDataSupplementer` | 缺口分析 + mock search | 无真实搜索能力 |
| 幻灯片构建 | `SlideDataBuilder` | 13 字段 slide_data | 无策略选择、无布局决策 |
| 模板选择 | `TemplateSelector` + 12 JSON 模板 | 基于启发式选择模板 | 无上下文感知、无情绪驱动 |
| 渲染 | `SlideRenderer` + `HTMLToPPTConverter` | KPI 卡片/表格/图表/分栏 | 固定配色、无产品主题适配 |
| 图表 | `SmartChartGenerator` | 自动分析内容→生成图表 | 无图表类型推荐引擎 |

### 1.2 UI/UX Pro Max 核心能力（需吸收）

| 能力 | 数据源 | 价值 | 集成优先级 |
|------|--------|------|-----------|
| **产品→风格映射** | products.csv (192条) | "新能源汽车" → 专业蓝+数据密集风格 | P0 |
| **情绪弧线决策** | slide-strategies.csv (15条) + slide-layout-logic.csv (15条) | 每页的 goal→layout+color+typography 联动 | P0 |
| **语义色板** | colors.csv (192条×18色) | 产品类型→完整 18 色语义 token | P0 |
| **排版规格** | slide-typography.csv (14条) | content_type→primary/secondary/accent 尺寸 | P1 |
| **情绪→色彩** | slide-color-logic.csv (13条) | emotion→背景/文字/强调色处理 | P1 |
| **图表推荐** | slide-charts.csv (25条) | data_type→best_chart + 上下文 | P1 |
| **文案公式** | slide-copy.csv (25条) | slide_type→copywriting formula | P2 |
| **背景图配置** | slide-backgrounds.csv (10条) | slide_type→image_category+overlay | P2 |
| **BM25 搜索** | core.py (274行) | 跨域搜索设计知识 | P2（用 jieba 增强版） |
| **推理规则** | ui-reasoning.csv (161条) | 产品类型→风格优先级+反模式 | P1 |

### 1.3 差距分析

**Zensers 缺失的核心能力：**

1. **没有产品类型识别** — 不知道"新能源汽车报告"应该用什么风格/色板
2. **没有情绪弧线** — 每页独立渲染，没有 story arc 驱动布局变化
3. **没有语义色板系统** — 硬编码 navy/gold/white，无法适配不同产品
4. **没有上下文感知布局** — TemplateSelector 只看当前 slide_data，不知道前后页
5. **没有图表类型推荐** — SmartChartGenerator 靠 LLM 猜测，无结构化推荐

---

## 二、集成架构

### 2.1 总体架构

```
用户输入 (研究报告主题/文件)
        │
        ▼
┌─────────────────────────┐
│  PptDesignAdvisor (新增)  │  ← 设计决策引擎
│  ┌───────────────────┐  │
│  │ ProductClassifier  │  │  产品类型识别 → 风格+色板
│  │ EmotionArcPlanner  │  │  情绪弧线规划 → 每页 goal+emotion
│  │ LayoutDecider      │  │  goal+emotion → layout+typography+color
│  │ ChartRecommender   │  │  data_type → chart_type
│  └───────────────────┘  │
│  数据: 5 个自建 CSV       │
└──────────┬──────────────┘
           │ design_context (每页的设计决策)
           ▼
┌─────────────────────────┐
│  现有 PPT 生成管线        │
│  SlideDataBuilder       │  ← 注入 design_context
│  TemplateSelector       │  ← 用 design_context 替代启发式
│  SlideRenderer          │  ← 用语义色板替代硬编码
│  HTMLToPPTConverter     │
└─────────────────────────┘
```

### 2.2 核心原则

| 原则 | 说明 |
|------|------|
| **知识自建** | 自建 5 个 CSV，数据结构和内容参考 UI/UX Pro Max 的设计思想，但不复制其文件 |
| **引擎自研** | BM25 搜索引擎用 Zensers 已有的 jieba 分词能力增强，不复制 core.py |
| **接口优先** | PptDesignAdvisor 输出标准 `DesignContext` dataclass，与现有管线松耦合 |
| **渐进集成** | Phase 1 仅注入色板+布局决策，Phase 2 加入情绪弧线，Phase 3 加入图表推荐 |

---

## 三、数据层设计（5 个自建 CSV）

### 3.1 `ppt_product_styles.csv` — 产品→风格+色板映射

**来源思想：** UI/UX Pro Max 的 products.csv + colors.csv，但针对 PPT 场景重新设计

| 列 | 类型 | 说明 | 示例 |
|----|------|------|------|
| `product_type` | str | 产品/行业类型 | "新能源汽车" |
| `keywords` | str | 匹配关键词 | "新能源,电动车,BEV,NEV,充电" |
| `style_name` | str | 设计风格名 | "数据驱动专业" |
| `color_primary` | str | 主色 hex | "#1A56DB" |
| `color_secondary` | str | 辅色 hex | "#0F172A" |
| `color_accent` | str | 强调色 hex | "#C9A227" |
| `color_background` | str | 背景色 hex | "#FFFFFF" |
| `color_text` | str | 正文色 hex | "#1E293B" |
| `color_muted` | str | 弱化色 hex | "#94A3B8" |
| `color_success` | str | 正向色 hex | "#16A34A" |
| `color_danger` | str | 负向色 hex | "#DC2626" |
| `typography_heading` | str | 标题字体 | "Microsoft YaHei" |
| `typography_body` | str | 正文字体 | "Microsoft YaHei" |
| `density` | str | 信息密度 | "high" / "medium" / "low" |
| `anti_patterns` | str | 反模式 | "过度动画,卡通图标" |

**计划条目（~30条，覆盖主要行业）：**
新能源汽车, 半导体, AI/大模型, SaaS, 金融/银行, 医疗健康, 教育, 消费品, 房地产, 能源/电力, 制造业, 物流, 农业, 政府/公共, 电商, 游戏, 文娱, 旅游, 环保, 零售, 餐饮, 保险, 证券, 基金, 区块链, 航空航天, 国防, 电信, 钢铁/化工, 通用(默认)

### 3.2 `ppt_slide_strategies.csv` — 演示策略+情绪弧线

**来源思想：** UI/UX Pro Max 的 slide-strategies.csv，针对研究报告场景定制

| 列 | 类型 | 说明 | 示例 |
|----|------|------|------|
| `strategy_id` | str | 策略标识 | "industry_report" |
| `strategy_name` | str | 策略名 | "行业深度研究报告" |
| `keywords` | str | 匹配关键词 | "行业,研究,深度,报告,产业" |
| `slide_structure` | str | 页面结构序列 | "cover,toc,overview,kpi,data,competition,tech,investment,end" |
| `emotion_arc` | str | 情绪序列 | "curiosity,interest,confidence,trust,evaluation,clarity,urgency" |
| `audience` | str | 目标受众 | "投资机构,企业战略部" |
| `tone` | str | 语调 | "专业,数据驱动,客观" |

**计划条目（~10条）：**
行业深度研究报告, 融资BP, 季度经营复盘, 竞争分析简报, 产品发布, 技术白皮书, 投资尽调报告, 政策解读, 市场快报, 通用(默认)

### 3.3 `ppt_layout_logic.csv` — goal→布局+排版+色彩决策

**来源思想：** UI/UX Pro Max 的 slide-layout-logic.csv + slide-typography.csv + slide-color-logic.csv 三表合一

| 列 | 类型 | 说明 | 示例 |
|----|------|------|------|
| `goal` | str | 页面目标 | "overview" |
| `emotion` | str | 情绪 | "curiosity" |
| `layout_template` | str | 对应模板名 | "content_left_right" |
| `visual_weight` | str | 视觉权重 | "balanced" / "text-heavy" / "visual-heavy" |
| `title_size_pt` | int | 标题字号(pt) | 32 |
| `body_size_pt` | int | 正文字号(pt) | 14 |
| `accent_size_pt` | int | 辅助字号(pt) | 11 |
| `bg_treatment` | str | 背景处理 | "solid" / "gradient" / "full_bleed" |
| `accent_usage` | str | 强调色用法 | "kpi_cards" / "title_underline" / "side_bar" |
| `break_pattern` | bool | 是否打破节奏 | false |

**计划条目（~15条，覆盖所有 goal 类型）：**
overview, kpi, data_analysis, comparison, competition, technology, investment, risk, conclusion, cta, timeline, quote, feature_grid, section_divider, end

### 3.4 `ppt_chart_recommendations.csv` — 图表类型推荐

**来源思想：** UI/UX Pro Max 的 slide-charts.csv，精简为 PPT 实用场景

| 列 | 类型 | 说明 | 示例 |
|----|------|------|------|
| `data_type` | str | 数据结构类型 | "time_series" |
| `recommended_chart` | str | 推荐图表 | "line_chart" |
| `alt_chart` | str | 备选图表 | "area_chart" |
| `best_for` | str | 最佳场景 | "趋势变化,时间序列" |
| `max_categories` | int | 最大分类数 | 12 |
| `ppt_implementation` | str | PPT 实现方式 | "python-pptx XL_CHART_TYPE.LINE" |

**计划条目（~15条）：**
time_series→line, categorical_comparison→bar, composition→pie/donut, kpi_progress→gauge, ranking→horizontal_bar, correlation→scatter, funnel→funnel, distribution→histogram, multi_series→grouped_bar, proportion→stacked_bar, trend_with_range→area, geographic→choropleth(图片), flow→sankey(图片), comparison_over_time→multi_line, single_value→kpi_card

### 3.5 `ppt_reasoning_rules.csv` — 推理决策规则

**来源思想：** UI/UX Pro Max 的 ui-reasoning.csv，精简为 PPT 场景

| 列 | 类型 | 说明 | 示例 |
|----|------|------|------|
| `product_category` | str | 产品类别 | "数据密集型" |
| `style_priority` | str | 风格优先级 | "数据驱动 > 极简 > 专业" |
| `color_mood` | str | 色彩情绪 | "信任蓝 + 数据强调" |
| `key_effects` | str | 关键效果 | "KPI卡片, 渐变标题, 表格+图表双栏" |
| `anti_patterns` | str | 反模式 | "过度动画, 卡通风格, 霓虹色" |
| `decision_rules` | str | 条件决策(JSON) | '{"if_data_heavy":"use_table_chart_split","if_creative":"add_full_bleed"}' |

**计划条目（~10条）：**
数据密集型(金融/半导体), 品牌展示型(消费品/文娱), 说服转化型(融资BP/销售), 教育解释型(培训/白皮书), 技术前瞻型(AI/科技), 政策合规型(政府/医疗), 竞争分析型, 投资决策型, 运营复盘型, 通用型

---

## 四、引擎层设计

### 4.1 `PptDesignAdvisor` — 设计决策引擎

```python
@dataclass
class DesignContext:
    """每页的设计决策上下文"""
    product_type: str                    # "新能源汽车"
    style_name: str                      # "数据驱动专业"
    colors: SemanticColorPalette         # 7色语义色板
    typography: TypographySpec           # 标题/正文/辅助字号
    layout_template: str                 # "content_left_right"
    bg_treatment: str                    # "solid"
    accent_usage: str                    # "kpi_cards"
    emotion: str                         # "confidence"
    break_pattern: bool                  # False
    chart_recommendation: Optional[str]  # "bar_chart"

@dataclass
class SemanticColorPalette:
    primary: str      # "#1A56DB"
    secondary: str    # "#0F172A"
    accent: str       # "#C9A227"
    background: str   # "#FFFFFF"
    text: str         # "#1E293B"
    muted: str        # "#94A3B8"
    success: str      # "#16A34A"
    danger: str       # "#DC2626"

@dataclass
class TypographySpec:
    heading_font: str   # "Microsoft YaHei"
    body_font: str      # "Microsoft YaHei"
    title_size: int     # 32
    body_size: int      # 14
    accent_size: int    # 11

class PptDesignAdvisor:
    def __init__(self, data_dir: str):
        self._load_csv_knowledge(data_dir)

    def advise_deck(self, topic: str, slide_count: int) -> List[DesignContext]:
        """为整份报告生成设计决策序列"""
        product = self._classify_product(topic)
        strategy = self._select_strategy(topic, slide_count)
        contexts = []
        for i, goal in enumerate(strategy.goals):
            ctx = self._advise_slide(product, goal, i, len(strategy.goals), contexts)
            contexts.append(ctx)
        return contexts

    def advise_slide(self, product: str, goal: str,
                     position: int, total: int,
                     previous: Optional[DesignContext]) -> DesignContext:
        """为单页生成设计决策"""
        ...

    def _classify_product(self, topic: str) -> str:
        """主题→产品类型（jieba 分词 + 关键词匹配）"""
        ...

    def _select_strategy(self, topic: str, slide_count: int) -> Strategy:
        """主题→演示策略（含情绪弧线）"""
        ...

    def _resolve_layout(self, goal: str, emotion: str) -> LayoutDecision:
        """goal+emotion→布局+排版+色彩决策"""
        ...
```

### 4.2 产品分类器 — `_classify_product()`

**实现方式：** jieba 分词 + CSV 关键词匹配（不复制 BM25，用 Zensers 已有的搜索能力）

```python
def _classify_product(self, topic: str) -> str:
    import jieba
    tokens = set(jieba.cut(topic))
    best_match = "通用"
    best_score = 0
    for row in self._product_styles:
        keywords = set(row["keywords"].split(","))
        score = len(tokens & keywords)
        if score > best_score:
            best_score = score
            best_match = row["product_type"]
    return best_match
```

### 4.3 情绪弧线规划器 — `_select_strategy()`

**核心逻辑：**

1. 用 jieba 分词匹配 `ppt_slide_strategies.csv` 的 keywords
2. 取匹配度最高的策略
3. 解析 `slide_structure` → goal 列表
4. 解析 `emotion_arc` → emotion 列表
5. 两者 zip → 每页的 (goal, emotion) 对

**情绪弧线示例（行业深度研究报告）：**

```
cover      → curiosity    (吸引注意)
toc        → interest     (建立期待)
overview   → confidence   (展示专业)
kpi        → trust        (数据证明)
data       → evaluation   (理性分析)
competition→ clarity      (清晰对比)
technology → hope         (未来展望)
investment → urgency      (行动呼吁)
end        → warmth       (友好收尾)
```

### 4.4 布局决策器 — `_resolve_layout()`

**查表逻辑：** goal + emotion → `ppt_layout_logic.csv` → DesignContext

**模式断裂（Pattern Break）：**
- 当 `break_pattern=true` 时，切换背景处理（solid→gradient 或 gradient→full_bleed）
- 在 1/3 和 2/3 位置强制 break，避免视觉单调
- 情绪从负面→正面切换时也 break（frustration→hope, fear→relief）

---

## 五、集成点设计

### 5.1 与 `SlideDataBuilder` 集成

**现状：** `build_list()` 只接收 sections，输出纯数据 slide_data

**改造：** 新增 `build_list_with_design()` 方法，注入 DesignContext

```python
class SlideDataBuilder:
    def build_list_with_design(
        self,
        sections: List[ContentSection],
        design_contexts: List[DesignContext],
        title: str = "Report"
    ) -> List[Dict]:
        slide_data_list = self.build_list(sections, add_cover=True, add_end=True, title=title)
        for i, sd in enumerate(slide_data_list):
            if i < len(design_contexts):
                ctx = design_contexts[i]
                sd["design_context"] = {
                    "colors": asdict(ctx.colors),
                    "typography": asdict(ctx.typography),
                    "layout_template": ctx.layout_template,
                    "bg_treatment": ctx.bg_treatment,
                    "accent_usage": ctx.accent_usage,
                    "emotion": ctx.emotion,
                    "break_pattern": ctx.break_pattern,
                }
        return slide_data_list
```

### 5.2 与 `TemplateSelector` 集成

**现状：** `select_and_enhance()` 基于启发式规则选择模板

**改造：** 当 slide_data 包含 `design_context` 时，优先使用其 `layout_template`

```python
class TemplateSelector:
    def select_and_enhance(self, slide_data, section_index=0):
        dc = slide_data.get("design_context")
        if dc and dc.get("layout_template"):
            return dc["layout_template"]  # 设计决策驱动
        # fallback: 原有启发式逻辑
        return self._heuristic_select(slide_data, section_index)
```

### 5.3 与 `SlideRenderer` 集成

**现状：** 硬编码 DESIGN 字典（navy/gold/white 等固定色值）

**改造：** 当 slide_data 包含 `design_context.colors` 时，用语义色板覆盖 DESIGN

```python
class SlideRenderer:
    def render(self, slide, slide_data, template, styles, **kwargs):
        dc = slide_data.get("design_context")
        if dc and "colors" in dc:
            design = self._merge_design(self.DESIGN, dc["colors"])
        else:
            design = self.DESIGN
        # ... 原有渲染逻辑，用 design 替代 self.DESIGN
```

### 5.4 与 `SmartChartGenerator` 集成

**现状：** `analyze_content()` 用 LLM 猜测图表类型

**改造：** 新增 `ChartRecommender` 预过滤，LLM 仅做最终确认

```python
class ChartRecommender:
    def recommend(self, data_type: str, category_count: int) -> str:
        """从 ppt_chart_recommendations.csv 查表推荐"""
        for row in self._chart_rules:
            if row["data_type"] == data_type and category_count <= int(row["max_categories"]):
                return row["recommended_chart"]
        return "bar_chart"  # 默认
```

---

## 六、文件结构

```
src/core/adjustment/
├── ppt_design_advisor.py          # PptDesignAdvisor + DesignContext + SemanticColorPalette
├── ppt_product_classifier.py      # ProductClassifier (jieba + CSV 关键词匹配)
├── ppt_emotion_arc.py             # EmotionArcPlanner (策略选择 + 情绪弧线)
├── ppt_layout_decider.py          # LayoutDecider (goal+emotion→布局决策)
├── ppt_chart_recommender.py       # ChartRecommender (data_type→chart_type)
└── (现有文件不变)

data/ppt_design/                   # 5 个自建 CSV 知识库
├── ppt_product_styles.csv         # ~30 条
├── ppt_slide_strategies.csv       # ~10 条
├── ppt_layout_logic.csv           # ~15 条
├── ppt_chart_recommendations.csv  # ~15 条
└── ppt_reasoning_rules.csv        # ~10 条

config/ppt_templates/              # 现有 12 个模板不变，可选新增
```

---

## 七、实施计划

### Phase 1：色板+布局决策（3 天）

| 任务 | 产出 | 测试 |
|------|------|------|
| 创建 5 个 CSV 知识库 | `data/ppt_design/*.csv` | 每个CSV加载测试 |
| 实现 `PptDesignAdvisor` | `ppt_design_advisor.py` | 10 单元测试 |
| 实现 `ProductClassifier` | `ppt_product_classifier.py` | 8 单元测试（覆盖主要行业） |
| 集成到 `SlideRenderer` | 修改 `slide_renderer.py` 色板覆盖 | 3 集成测试 |
| 集成到 `TemplateSelector` | 修改 `template_selector.py` | 3 集成测试 |

### Phase 2：情绪弧线+策略选择（3 天）

| 任务 | 产出 | 测试 |
|------|------|------|
| 实现 `EmotionArcPlanner` | `ppt_emotion_arc.py` | 8 单元测试 |
| 实现 `LayoutDecider` | `ppt_layout_decider.py` | 8 单元测试 |
| 集成到 `SlideDataBuilder` | `build_list_with_design()` | 5 集成测试 |
| 端到端：主题→完整设计决策 | 脚本验证 | 1 E2E 测试 |

### Phase 3：图表推荐+推理规则（2 天）

| 任务 | 产出 | 测试 |
|------|------|------|
| 实现 `ChartRecommender` | `ppt_chart_recommender.py` | 6 单元测试 |
| 集成到 `SmartChartGenerator` | 预过滤逻辑 | 3 集成测试 |
| 推理规则加载+应用 | `ppt_reasoning_rules.csv` 读取 | 4 单元测试 |

### Phase 4：验证+调优（2 天）

| 任务 | 产出 |
|------|------|
| 生成 3 种行业报告 PPT（新能源/半导体/AI） | 视觉对比验证 |
| 色板在不同模板下的实际效果 | 微调 CSV 数据 |
| 完整管线回归测试 | 0 回归 |

**总工作量：10 天**

---

## 八、与 UI/UX Pro Max 的重合度控制

| 维度 | UI/UX Pro Max | Zensers 集成 | 重合度 |
|------|---------------|-------------|--------|
| CSV 数据格式 | 15 个 CSV, 5100+ 条 | 5 个 CSV, ~80 条 | **低** — 数据量 1.5%，列结构重新设计 |
| 搜索引擎 | BM25 (core.py, 274行) | jieba 分词 + 关键词匹配 | **低** — 完全不同实现 |
| 设计系统生成器 | design_system.py, 1329行 | PptDesignAdvisor, ~300行 | **低** — 功能子集，逻辑自研 |
| 幻灯片生成 | generate-slide.py, 770行 (HTML) | 不使用，保留现有 SlideRenderer | **零** |
| 上下文决策 | slide_search_core.py, 453行 | EmotionArcPlanner + LayoutDecider, ~200行 | **低** — 思想借鉴，代码自研 |
| 推理规则 | ui-reasoning.csv, 161条 | ppt_reasoning_rules.csv, ~10条 | **低** — 精简为 PPT 场景 |
| 模板系统 | 18 平台 JSON | 不使用 | **零** |
| 持久化 | Master+Overrides | 不使用（Zensers 有自己的版本管理） | **零** |

**综合重合度：< 10%**（主要是设计思想借鉴，代码和数据完全自建）

---

## 九、预期效果

### 9.1 定量提升

| 指标 | 当前 | 集成后 |
|------|------|--------|
| 色板适配 | 1 种固定(navy/gold) | 30 种产品主题 |
| 布局决策 | 启发式规则(~60%准确) | 情绪弧线驱动(~90%准确) |
| 图表推荐 | LLM猜测(慢,不稳定) | CSV查表(快,确定) |
| 视觉多样性 | 低(所有报告同风格) | 高(产品类型自适应) |

### 9.2 定性提升

- **新能源汽车报告** → 信任蓝+数据密集风格，KPI卡片+表格图表双栏
- **AI行业报告** → 科技紫+前瞻风格，渐变背景+全出血图
- **融资BP** → 专业深色+转化风格，CTA强调+情绪弧线
- **教育/培训** → 温暖色+清晰风格，大字号+步骤化布局

---

## 十、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| CSV 数据质量不足 | 中 | 色板/布局决策不准 | 先用 30 条核心产品验证，逐步扩展 |
| 情绪弧线与内容不匹配 | 低 | 布局选择错误 | LayoutDecider 输出可被 TemplateSelector fallback 覆盖 |
| jieba 分词对英文主题不准 | 低 | 产品分类失败 | 中英文双语关键词匹配 |
| 与现有模板不兼容 | 低 | 渲染异常 | DesignContext 为可选注入，缺失时走原逻辑 |
