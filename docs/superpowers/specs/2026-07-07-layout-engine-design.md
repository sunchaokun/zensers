# LayoutEngine 动态布局引擎设计 v3

> 基于对 AI PPT 生成领域的深度调研（Beautiful.ai、Gamma、AiPPT、DeepSlides、AeSlides 等），重新论证设计方案。
> v3: 新增图片服务（ImageProvider）章节

---

## 0. 行业调研摘要

### 0.1 商业工具的布局方法

| 工具 | 布局方法 | 核心特点 |
|------|---------|---------|
| **Beautiful.ai** | 300+ 约束模板 + Flex Grid | Smart Slides 自动重排，用户不能自由放置元素。**约束而非自由是质量保证** |
| **Gamma** | Card-based CSS-like flow | 内容组织为响应式卡片，同一内容可渲染为 PPT/网页/文档 |
| **AiPPT** | 5页型模板系统 + 专业布局AI | Cover/Catalog/Chapter/Content/Ending，有 Pro Layout AI 自动编排 |
| **Tome** | AI-native block editor | AI 决定 block 位置，类似 Notion 的块编辑器 |

**核心发现**：所有高质量工具的共同点是——**限制用户自由度来保证设计质量**。Beautiful.ai 最直接："The software needs to know when to enforce best practices on its own."

### 0.2 学术前沿

| 论文 | 方法 | 对我们的启示 |
|------|------|-------------|
| **DeepSlides (ACL 2026)** | Design-first 三层架构（Background→Layout→Content），多智能体 RL | 先推理设计，再生成代码 |
| **AeSlides (2026)** | 可验证美学奖励的 RL（宽高比/留白/碰撞/失衡），仅5K样本微调 | 4个可编程美学指标可直接使用 |
| **Desigen (CVPR 2024)** | Diffusion 背景 + Transformer 自回归布局 + 迭代精修 | 迭代优化思路 |
| **LACE (ICLR 2024)** | 连续扩散 + 可微美学约束函数 | 约束驱动的布局生成 |
| **PPTBench (2025)** | MLLMs 能理解内容但**无法产出合理空间布局** | 纯 LLM 布局不可靠，需要规则引擎 |

**核心发现**：
1. 学术界已从纯 ML 转向 **LLM Agent + 设计规则** 的混合模式
2. AeSlides 的4个可验证美学指标（宽高比、留白、碰撞、失衡）是程序化质量检查的最佳实践
3. **数据密集型幻灯片（KPI+图表+表格）是学术空白领域**——没有论文专门解决这个场景

### 0.3 对我们设计的影响

1. **约束优于自由**（Beautiful.ai 哲学）：LayoutEngine 应限制"不合理布局"，而非尝试生成"所有可能布局"
2. **可验证美学指标**（AeSlides）：我们应在 LayoutEngine 中内嵌质量检查，而非仅凭规则产出布局
3. **Design-first 架构**（DeepSlides）：先判断内容组合应该用什么"设计范式"，再计算具体位置
4. **无需 ML/Diffusion**：我们的内容组合是有限的（10种场景），规则引擎比 ML 更可靠更快

---

## 1. 问题陈述

### 1.1 现状

当前模板系统的 slot position 硬编码在 JSON 中。当 `_auto_generate_charts` 为 KPI 页面自动生成图表后，图表被塞入预定义的右侧 chart slot，导致：

- KPI 卡片宽度从 11.7" 压缩到 7.5"，4张卡片每张仅 1.575" 宽，视觉拥挤
- 图表 4"×3.5" 与 KPI 卡片 7.5"×3.5" 左右拼接，无统一视觉层次
- data_table 的左表格+右图表布局，表格被压缩到 5.6" 宽，数据列多时不可读
- findings 页面同样被图表挤压，文字区域从 11.7" 缩到 7.5"

### 1.2 根因

模板是**静态布局**——position 在 JSON 中写死，不关心实际内容组合。这是 Beautiful.ai 2019年之前就解决的问题：**"The software needs to know what's on the slide, what might be added later, and the best way to get from Point A to Point B."**

### 1.3 目标

实现 Beautiful.ai Smart Slides 式的**内容响应式布局**：系统感知实际内容组合，自动计算最优排版，确保每一页都像专业设计师手工排版。

---

## 2. 设计原则

### 2.1 从调研提炼的5条原则

| # | 原则 | 来源 | 说明 |
|---|------|------|------|
| 1 | **约束优于自由** | Beautiful.ai | 限制不合理布局比允许创意自由更能保证质量。LayoutEngine 只产出经过验证的专业布局 |
| 2 | **内容驱动布局** | Beautiful.ai / Gamma | 有什么内容→选什么布局。不是"模板有什么slot就塞什么" |
| 3 | **区域分解** | 行业通用 | 先划分页面区域（header/primary/sidebar/footer），再在区域内排列元素 |
| 4 | **可验证美学** | AeSlides | 每个布局结果必须通过4项美学检查（宽高比、留白、碰撞、失衡），不通过则降级到更保守的布局 |
| 5 | **优雅降级** | 所有工具 | 缺少某类内容时，剩余元素自动扩展占满空间；图表放不下时宁可不放，不破坏主内容 |

### 2.2 视觉层次权重

参考 Beautiful.ai 的 hierarchy enforcement：

```
KPI 数字（hero number）  → 最大视觉空间，不可压缩
图表（chart）            → 次级视觉空间，可缩小但保持可读
表格（table）            → 需要全宽，高度自适应
文字列表（items）        → 最灵活，可宽可窄
洞察条（insight）        → 固定底部，不受影响
```

---

## 3. 页面坐标系与设计令牌

### 3.1 画布尺寸

```
SLIDE_WIDTH   = 13.333 inches
SLIDE_HEIGHT  = 7.500 inches
```

### 3.2 设计令牌（Design Tokens）

借鉴 Beautiful.ai / Pitch 的 theme token 系统，将所有布局常量统一为令牌：

```python
LAYOUT_TOKENS = {
    # 边距
    "margin.left":    0.8,
    "margin.right":   0.8,
    "margin.top":     0.3,
    
    # 内容区域
    "content.top":    1.1,       # title(0.7) + 间距(0.4)
    "content.width":  11.7,      # slide_width - margin_left - margin_right
    "content.height": 4.7,       # T.footer.top - T.content.top = 5.8 - 1.1
    
    # 底部区域
    "footer.top":     5.8,
    "footer.height":  1.0,
    
    # 间距
    "gap.element":    0.3,       # 元素间最小间距
    "gap.section":    0.5,       # 区域间间距（KPI与图表之间）
    "gap.card":       0.4,       # KPI卡片之间
    
    # 图表
    "chart.center_width":  8.0,  # 居中图表宽度
    "chart.max_height":    2.5,  # 图表最大高度
    "chart.min_height":    1.8,  # 图表最小高度
    
    # KPI
    "kpi.solo_height":     3.5,  # 纯KPI卡片高度
    "kpi.with_chart_height": 2.0, # KPI+图表时卡片高度
    "kpi.number_size":     36,    # 纯KPI数字字号
    "kpi.number_size_sm":  28,    # KPI+图表时数字字号
    "kpi.label_size":      12,    # 标签字号
    "kpi.label_size_sm":   11,    # 小标签字号
    "kpi.max_cards":       4,     # 最大卡片数
    
    # 表格
    "table.row_height":    0.4,
    "table.max_display_height": 2.5,
    
    # 排版
    "typography.title_size":  24,
    "typography.body_size":   14,
    "typography.min_size":    10,
}
```

**令牌化的好处**：所有布局计算引用令牌而非硬编码数字。后续调整只需改令牌值。

### 3.3 固定区域

以下区域在任何布局中位置不变（不受 LayoutEngine 影响）：

| 区域 | 位置 | 说明 |
|------|------|------|
| Title | L=0.8, T=0.3, W=11.7, H=0.7 | 始终在最上方 |
| Insight Bar | L=0.8, T=5.8, W=11.7, H=1.0 | 始终在底部（如果存在） |
| Footer Bar | 装饰层，固定 | 不受 LayoutEngine 影响 |
| Side Accent | 装饰层，固定 | 不受 LayoutEngine 影响 |
| Page Number | 装饰层，固定 | 不受 LayoutEngine 影响 |

动态布局只影响 **content.top (1.1") 到 footer.top (5.8")** 之间的内容区域。

注意：content.height 令牌值为 4.7"（= T.footer.top - T.content.top = 5.8 - 1.1）。下面所有计算使用 `available = T["footer.top"] - T["content.top"]` 动态计算，不依赖令牌中的 content.height。

---

## 4. 布局场景定义

### 4.1 内容指纹（Content Profile）

从 `slide_data` 中提取内容指纹，作为布局决策的输入：

```python
def _profile(self, slide_data) -> Dict:
    kpi_data = slide_data.get("kpi_data", [])
    images = slide_data.get("images", [])
    table_data = slide_data.get("table_data", [])
    items = slide_data.get("items", [])
    insight_text = slide_data.get("insight_text", "")
    
    return {
        "has_kpis":      bool(kpi_data) and len(kpi_data) >= 2,
        "kpi_count":     min(len(kpi_data), 4),
        "has_chart":     bool(images) and all(
            img.get("image_type", "chart") == "chart" for img in images
        ),
        "has_photo":     bool(images) and any(
            img.get("image_type") in ("product", "technology", "illustration") for img in images
        ),
        "chart_count":   len(images),
        "has_table":     bool(table_data) and len(table_data) >= 2,
        "table_rows":    len(table_data) if table_data else 0,
        "has_items":     bool(items),
        "item_count":    len(items),
        "has_insight":   bool(insight_text),
    }
```

### 4.2 场景分类器

**优先级决策树**（KPI > 表格 > 图表/图片 > 文字）：

```python
def _classify(self, profile) -> str:
    # KPI 页面
    if profile["has_kpis"]:
        if profile["has_photo"]:
            return "kpi_with_photo"
        if profile["has_chart"]:
            return "kpi_with_chart"
        return "kpi_solo"
    # 表格页面
    if profile["has_table"]:
        if profile["has_photo"]:
            return "table_with_photo"
        if profile["has_chart"]:
            return "table_with_chart"
        return "table_solo"
    # 文字+图片/图表
    if profile["has_items"]:
        if profile["has_photo"]:
            return "items_with_photo"
        if profile["has_chart"]:
            return "items_with_chart"
    # 纯图表
    if profile["chart_count"] >= 2 and profile["has_chart"] and not profile["has_items"]:
        return "dual_chart"
    return "text_only"
```

### 4.3 十种布局场景

#### 场景1: KPI纯数字 (kpi_solo)

**触发条件**: `has_kpis=True AND has_chart=False`

```
┌──────────────────────────────────────────────┐
│  Title                                        │ 0.3"
├──────────────────────────────────────────────┤
│                                              │ 1.1"
│   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐           │
│   │ KPI │ │ KPI │ │ KPI │ │ KPI │           │
│   │     │ │     │ │     │ │     │  h=3.5"    │
│   └─────┘ └─────┘ └─────┘ └─────┘           │
│                                              │ 4.7"
│   ┌──────────────────────────────────────┐   │
│   │  💡 Insight Bar                       │   │ 5.8"
│   └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘

KPI卡片: left_start=T.margin.left, total_width=T.content.width,
         height=T.kpi.solo_height, gap=T.gap.card
```

#### 场景2: KPI+图表 (kpi_with_chart) ★ 核心场景

**触发条件**: `has_kpis=True AND has_chart=True`

**设计论证**——为什么是"KPI在上图表在下"而非"KPI左图表右"：

1. **KPI卡片必须全宽**：4张卡片需要至少 11.7" 宽度才能容纳 36pt 数字+12pt 标签+内边距。压缩到 7.5" 后每卡仅 1.575"，连3位数字都放不下
2. **视觉逻辑流**：从上到下"结论(KPI)→证据(图表)"，符合麦肯锡金字塔原理
3. **Beautiful.ai 的 Data Dashboard 模板**采用相同布局——KPI metrics 在上方，chart 在下方
4. **图表居中8"宽**：比右对齐4"宽更专业——4"宽的图表信息密度太低

```
┌──────────────────────────────────────────────┐
│  Title                                        │ 0.3"
├──────────────────────────────────────────────┤
│                                              │ 1.1"
│   ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐           │
│   │ KPI │ │ KPI │ │ KPI │ │ KPI │  h=2.0"   │
│   └─────┘ └─────┘ └─────┘ └─────┘           │
│                                              │ 3.4"
│          ┌──────────────────────┐            │
│          │                      │            │
│          │      Chart           │  h=2.2"    │
│          │                      │            │
│          └──────────────────────┘            │
│              w=8.0, 居中                      │ 5.8"
│   ┌──────────────────────────────────────┐   │
│   │  💡 Insight Bar                       │   │ 5.8"
│   └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘

KPI: left=T.margin.left, width=T.content.width, height=T.kpi.with_chart_height
     number_size=T.kpi.number_size_sm (28pt), label_size=T.kpi.label_size_sm (11pt)
Chart: left=(SLIDE_WIDTH - T.chart.center_width)/2, width=T.chart.center_width
       top=T.content.top + T.kpi.with_chart_height + T.gap.section
        height=clamp(available - kpi_h - T.gap.section, T.chart.min_height, T.chart.max_height)
```

**高度分配计算**：
```
available = T.footer.top - T.content.top = 5.8 - 1.1 = 4.7"
kpi_h     = 2.0"
gap       = 0.5"
chart_h   = available - kpi_h - gap
          = 4.7 - 2.0 - 0.5 = 2.2"
chart_h   = clamp(chart_h, T.chart.min_height, T.chart.max_height)
```

注意：Insight Bar 位于 T=5.8"，在内容区域（T.content.top=1.1" ~ T.footer.top=5.8"）之外，不占用内容区域高度。

#### 场景3: 表格+图表 (table_with_chart)

**触发条件**: `has_table=True AND has_chart=True`

**设计论证**——为什么是"表格在上图表在下"而非"表格左图表右"：

1. **表格天然需要宽幅**：5-6列中文表格至少需要 8-10" 宽度，压缩到 5.6" 会导致列宽不足、文字换行
2. **信息层次**：表格是"原始数据"，图表是"数据解读"，从上到下是从"详细→概要"的阅读顺序
3. **表格高度有限**：通常 3-6 行，占 1.2-2.4"，下方有足够空间放图表

```
┌──────────────────────────────────────────────┐
│  Title                                        │
├──────────────────────────────────────────────┤
│   ┌──────────────────────────────────────┐   │
│   │  Table (full width, h=rows*0.4)      │   │
│   └──────────────────────────────────────┘   │
│          ┌──────────────────────┐            │
│          │      Chart           │            │
│          │      w=8.0 居中      │            │
│          └──────────────────────┘            │
└──────────────────────────────────────────────┘

Table: left=T.margin.left, width=T.content.width, 
       height=min(rows * T.table.row_height, T.table.max_display_height)
Chart: 居中，top=table_bottom + T.gap.section, 
        height=clamp(available - table_h - T.gap.section, T.chart.min_height, T.chart.max_height)
```

#### 场景4: 表格+产品图 (table_with_photo)

**触发条件**: `has_table=True AND has_photo=True`

**设计论证**——与 table_with_chart 的上下布局不同，产品图采用左右布局：

1. **产品图是视觉证据**，与主内容并列展示比上下堆叠更自然
2. **表格全宽需求可通过调整列宽解决**：5列表格在 5.6" 宽度内可读（与原 data_table 模板一致）
3. **与 kpi_with_photo 布局一致**：都是左内容+右图片

**但需注意**：行数少的表格（≤4行）与等高图片左右排列时，视觉重心偏向右侧。因此：
- **表格 ≥ 5行**：左右布局（表格高度≥2.0"，视觉更平衡）
- **表格 ≤ 4行**：仍用上下布局（table_with_chart 的布局策略，图片居中在表格下方）

```
┌──────────────────────────────────────────────┐
│  Title                                        │
├──────────────────────────────────────────────┤
│   ┌──────────────┐  ┌────────────────────┐   │
│   │  Table       │  │   Photo            │   │
│   │  w=5.6"      │  │   w=5.6"           │   │
│   │              │  │                    │   │
│   └──────────────┘  └────────────────────┘   │
│   gap=0.5"                                   │
└──────────────────────────────────────────────┘

（仅当 rows >= 5 时使用此左右布局）

Table:  left=T.margin.left, top=T.content.top, width=5.6, 
        height=min(rows * T.table.row_height, T.table.max_display_height)
Photo:  left=T.margin.left + 5.6 + T.gap.section, top=T.content.top, width=5.6,
        height=T.footer.top - T.content.top  (4.7")
```

注意：当 rows < 5 时，LayoutEngine 退回 table_with_chart 的上下布局（图片居中在表格下方），而非左右布局。这保证了视觉平衡。

#### 场景5: 表格纯 (table_solo)

**触发条件**: `has_table=True AND has_chart=False`

```
Table: left=T.margin.left, width=T.content.width, height=auto
无图表时表格全宽，LayoutEngine 不需覆盖（template 默认即可）
```

#### 场景6: 文字+图表 (items_with_chart)

**触发条件**: `has_items=True AND has_chart=True AND has_kpis=False AND has_table=False`

**设计论证**——左右布局合理，但比例要调整：

1. 文字内容 5.0" + 间距 0.5" + 图表 6.2" = 11.7"，总宽匹配
2. **图表 6.2" 而非 6.4"**：留出更多间距，避免左右"贴墙"
3. 两侧等高 4.7"，视觉平衡

```
┌──────────────────────────────────────────────┐
│  Title                                        │
├──────────────────────────────────────────────┤
│   ┌──────────────┐  ┌────────────────────┐   │
│   │  Text Items  │  │      Chart         │   │
│   │  w=5.0"      │  │  w=6.2"           │   │
│   └──────────────┘  └────────────────────┘   │
│   gap=0.5"                                   │
│   ┌──────────────────────────────────────┐   │
│   │  💡 Insight Bar                       │   │
│   └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘

Items:  left=T.margin.left, top=T.content.top, width=5.0, 
        height=T.footer.top - T.content.top  (4.7")
Chart:  left=T.margin.left + 5.0 + T.gap.section, width=6.2, 等高
```

#### 场景7: 双图表 (dual_chart)

**触发条件**: `chart_count>=2 AND has_chart=True AND has_kpis=False AND has_table=False AND has_items=False`

```
Chart_L: left=0.5, top=1.2, width=5.6, height=4.5
Chart_R: left=6.6, top=1.2, width=5.6, height=4.5
（与现有 chart_split 模板一致，LayoutEngine 不覆盖）
```

#### 场景8: 纯文字 (text_only)

**触发条件**: 无KPI、无图表、无表格

```
Items: left=T.margin.left, top=1.3, width=T.content.width, height=5.2
（与现有 content_text_only 模板一致，LayoutEngine 不覆盖）
```

---

## 5. 可验证美学检查（AeSlides 启发）

**这是设计的关键特性**。每个 LayoutEngine 产出的布局，必须通过 4 项程序化美学检查。不通过则自动降级到更保守的布局。

### 5.1 四项检查

```python
def _validate(self, layout: Dict, profile: Dict) -> Tuple[bool, List[str]]:
    T = self.T  # 设计令牌
    issues = []
    
    # 1. 宽高比合规（Distorted Aspect Ratio）
    #    AeSlides 的 [1.2, 3.0] 阈值是为单个图片/文本块设计的。
    #    全宽容器（KPI行、表格）天然比率 > 3.0，窄侧栏天然比率 < 1.2。
    #    因此豁免：全宽元素（width == T.content.width）和全高元素（height == available）。
    available = T["footer.top"] - T["content.top"]
    for slot_id, pos in layout.items():
        w, h = pos.get("width"), pos.get("height")
        if w is not None and h is not None and h > 0:
            ratio = w / h
            # 全宽容器豁免（如 KPI行 11.7×2.0 = 5.85）
            # 全高侧栏豁免（如 文字列 5.0×4.7 = 1.06）
            is_full_width = (w >= T["content.width"] * 0.95)
            is_full_height = (h >= available * 0.95)
            if not is_full_width and not is_full_height:
                # 图表类 slot（宽 > 高的横条形）放宽上限到 4.0
                # 8"宽×2.2"高 = 3.64，在 PPT 图表中是常见且合理的比率
                max_ratio = 4.0 if slot_id == "chart" else 3.0
                if ratio < 1.2 or ratio > max_ratio:
                    issues.append(f"{slot_id}: aspect ratio {ratio:.1f} out of [1.2, {max_ratio}]")
    
    # 2. 留白率（Excessive Whitespace）
    #    内容区域利用率应 >= 50%（仅计算有 width+height 的区域）
    content_area = T["content.width"] * (T["footer.top"] - T["content.top"])
    used_area = sum(
        pos.get("width", 0) * pos.get("height", 0)
        for pos in layout.values()
        if isinstance(pos.get("width"), (int, float)) and isinstance(pos.get("height"), (int, float))
    )
    utilization = used_area / content_area if content_area > 0 else 0
    if utilization < 0.5:
        issues.append(f"Content utilization {utilization:.0%} < 50%")
    
    # 3. 元素碰撞（Element Collision）
    #    任意两个有面积的 slot 不能重叠
    rects = [(sid, pos) for sid, pos in layout.items() 
             if isinstance(pos.get("width"), (int, float)) and isinstance(pos.get("height"), (int, float))]
    for i, (sid_a, a) in enumerate(rects):
        for sid_b, b in rects[i+1:]:
            if self._overlaps(a, b):
                issues.append(f"{sid_a} overlaps {sid_b}")
    
    # 4. 视觉失衡（Visual Imbalance）
    #    内容重心应靠近页面中心，偏移不超过 30%
    #    左右布局天然偏移，但双元素左右布局的重心应在中间
    weighted = [(pos.get("left", 0) + pos.get("width", 0)/2, pos.get("width", 0) * pos.get("height", 0))
                for pos in layout.values() 
                if isinstance(pos.get("left"), (int, float)) 
                and isinstance(pos.get("width"), (int, float))
                and isinstance(pos.get("height"), (int, float))]  # 仅有面积的 slot 参加重心计算
    if weighted:
        total_area = sum(w for _, w in weighted)
        if total_area > 0:
            cx = sum(x * w for x, w in weighted) / total_area
        else:
            cx = sum(x for x, _ in weighted) / len(weighted)
        page_center = T["margin.left"] + T["content.width"] / 2
        offset = abs(cx - page_center) / (T["content.width"] / 2)
        if offset > 0.3:
            issues.append(f"Visual imbalance: center offset {offset:.0%}")
    
    return len(issues) == 0, issues
```

**宽高比豁免的设计论证**：

AeSlides 原始阈值 [1.2, 3.0] 是为**单个内容块**（图片、文本框）设计的。在 PPT 布局场景中：

| 元素类型 | 典型比率 | 是否豁免 | 原因 |
|---------|---------|---------|------|
| 全宽KPI行 (11.7×2.0) | 5.85 | 是（full_width） | 宽度等于内容宽度，横向排列4卡片 |
| 全宽表格 (11.7×1.2) | 9.75 | 是（full_width） | 表格天然全宽横排 |
| 居中图表 (8.0×2.2) | 3.64 | 否 | 非全宽非全高，应检查 |
| 左侧文字 (5.0×4.7) | 1.06 | 是（full_height） | 等高布局，高度等于可用高度 |
| 右侧图表 (6.2×4.7) | 1.32 | 否 | 正常范围 [1.2, 3.0] |

实际只有居中图表可能超标（3.64 > 3.0），但图表的合理比率范围本就较宽。将图表的比率上限放宽到 **4.0** 更合理——8"宽×2"高 = 4.0，这在PPT图表中是常见的。

### 5.2 降级策略

```python
def compute(self, slide_data, template):
    profile = self._profile(slide_data)
    scenario = self._classify(profile)
    layout = self._layout(scenario, profile, slide_data, template)
    
    valid, issues = self._validate(layout, profile)
    if not valid:
        logger.warning(f"Layout validation failed for '{scenario}': {issues}")
        # 降级：移除图表，只保留核心内容
        fallback = self._fallback_layout(profile, slide_data, template)
        return fallback
    
    return layout
```

降级逻辑：如果某个场景的布局验证失败（通常因为内容过多导致碰撞），则退回到不含图表的纯布局（kpi_solo / table_solo / text_only），宁可不放图表也不破坏主内容。

```python
def _fallback_layout(self, profile, slide_data, template) -> Dict:
    """降级到不含图表/图片的纯布局"""
    T = self.T
    if profile["has_kpis"]:
        return {
            "kpi_row": {
                "left": T["margin.left"],
                "top": T["content.top"],
                "width": T["content.width"],
                "height": T["kpi.solo_height"],
            },
        }
    if profile["has_table"]:
        return {
            "data_table": {
                "left": T["margin.left"],
                "top": T["content.top"],
                "width": T["content.width"],
            },
        }
    return {}  # text_only/dual_chart 等用 template 默认布局兜底
```

---

## 6. LayoutEngine 架构

### 6.1 类设计

```python
class LayoutEngine:
    """
    内容响应式布局引擎。
    
    灵感来源：
    - Beautiful.ai Smart Slides 的约束模板系统
    - AeSlides 的可验证美学指标
    - DeepSlides 的 design-first 架构
    
    工作流程：
    1. 内容指纹提取 → _profile()
    2. 场景分类 → _classify()  
    3. 布局计算 → _layout()
    4. 美学验证 → _validate()
    5. 降级兜底 → _fallback_layout()
    """
    
    def __init__(self, tokens: Dict = None):
        self.T = {**LAYOUT_TOKENS, **(tokens or {})}
    
    def compute(self, slide_data: Dict, template: Dict) -> Dict[str, Dict]:
        """
        输入: slide_data, template
        输出: {slot_id: {"left": x, "top": y, "width": w, "height": h}}
        """
        ...
    
    def can_accommodate_chart(self, slide_data: Dict, template_name: str) -> bool:
        """判断此模板+内容组合是否允许添加图表"""
        ...
    
    def _profile(self, slide_data) -> Dict: ...
    def _classify(self, profile) -> str: ...
    def _layout(self, scenario, profile, slide_data, template) -> Dict: ...
    def _validate(self, layout, profile) -> Tuple[bool, List[str]]: ...
    def _fallback_layout(self, profile, slide_data, template) -> Dict: ...
    def _overlaps(self, a, b) -> bool: ...
    
    # 各场景布局方法（7.0-7.7节详细算法）
    def _layout_kpi_solo(self, profile, slide_data, template) -> Dict: ...
    def _layout_kpi_with_chart(self, profile, slide_data, template) -> Dict: ...
    def _layout_table_with_chart(self, profile, slide_data, template) -> Dict: ...
    def _layout_items_with_chart(self, profile, slide_data, template) -> Dict: ...
    def _layout_kpi_with_photo(self, profile, slide_data, template) -> Dict: ...
    def _layout_items_with_photo(self, profile, slide_data, template) -> Dict: ...
    def _layout_table_with_photo(self, profile, slide_data, template) -> Dict: ...
```

### 6.2 与现有系统的集成

**插入点**：在 `_create_pptx_document` 的模板渲染分支中，`_auto_generate_charts` 之前（注意顺序调整！）：

```python
# 新流程
layout_engine = LayoutEngine()

for slide_data in slides:
    slide = prs.slides.add_slide(slide_layouts[6])
    
    # 1. 模板选择（不变）
    template_name = selector.select_and_enhance(slide_data, section_index)
    template = registry.get(template_name)
    
    # 2. 图表生成（新逻辑：用 LayoutEngine 判断是否允许）
    if chart_gen and not slide_data.get("images"):
        if layout_engine.can_accommodate_chart(slide_data, template_name):
            self._auto_generate_charts(slide_data, template_name, chart_gen)
    
    # 3. 动态布局计算（新增）
    layout_overrides = layout_engine.compute(slide_data, template)
    
    # 4. 渲染（传入 layout_overrides）
    renderer.render(slide, slide_data, template, styles, 
                    page_num=slides_count, layout_overrides=layout_overrides)
```

**关键顺序**：先决定是否生成图表 → 生成图表 → 再计算布局。这样 LayoutEngine 能看到完整的 slide_data（含可能新生成的图表）。

### 6.3 SlideRenderer 改动

`render()` 方法接受 `layout_overrides` 参数，传递到 `_render_slot`：

```python
def render(self, slide, slide_data, template, styles, page_num=0, layout_overrides=None):
    # ... background, bottom decorations ...
    for slot in template.get("slots", []):
        self._render_slot(slide, slot, slide_data, styles, layout_overrides)
    # ... top decorations ...

def _render_slot(self, slide, slot, slide_data, styles, layout_overrides=None):
    if layout_overrides and slot["id"] in layout_overrides:
        override = layout_overrides[slot["id"]]
        slot = dict(slot)  # 浅拷贝
        # 先提取 _style_delta，避免污染 position
        style_delta = override.pop("_style_delta", None)
        # 合并 position（override 中只剩位置字段）
        slot["position"] = {**slot.get("position", {}), **override}
        # 合并 _style_delta 到 style
        if style_delta:
            slot["style"] = {**slot.get("style", {}), **style_delta}
    # 原有 dispatch 逻辑不变
    ...
```

**零侵入设计**：所有 `render_xxx_slot` 方法都不需要改动。它们仍然从 `slot["position"]` 和 `slot["style"]` 读取值，只是这些值可能被 LayoutEngine 覆盖了。

### 6.4 模板恢复

LayoutEngine 接管了有图表时的布局计算，模板 JSON 恢复为**纯内容（无图表）**的基准布局：

| 模板 | 变更 |
|------|------|
| kpi_highlight.json | 移除 chart slot，KPI 卡片恢复全宽 11.7" |
| data_table.json | 移除 chart slot，表格恢复全宽 11.7" |
| findings.json | 移除 chart slot，文字恢复全宽 11.7" |
| chart_full / chart_split 等 | 不变（LayoutEngine 不干预纯图表模板） |

### 6.5 can_accommodate_chart 逻辑

```python
def can_accommodate_chart(self, slide_data, template_name):
    """哪些模板+内容组合允许添加图表"""
    no_chart_templates = {"cover", "toc", "section_title", "end", "comparison"}
    if template_name in no_chart_templates:
        return False
    
    # 内容太多时不添加图表（避免拥挤）
    profile = self._profile(slide_data)
    if profile["kpi_count"] >= 4 and profile["has_table"]:
        return False  # KPI+表格已满，无空间
    if profile["table_rows"] > 8 and profile["has_items"] and profile["item_count"] > 5:
        return False  # 表格+文字过多
    
    return True
```

---

## 7. 布局计算详细算法

> 以下列出需要 LayoutEngine 覆盖布局的场景。table_solo / dual_chart / text_only 返回 `{}`，由 template 默认布局兜底，无需算法代码。

### 7.0 KPI纯数字 (kpi_solo)

```python
def _layout_kpi_solo(self, profile, slide_data, template) -> Dict:
    T = self.T
    # 恢复 KPI 卡片为全宽（模板恢复后 width=11.7 已在模板中，此覆盖确保 top 和 height）
    return {
        "kpi_row": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": T["content.width"],
            "height": T["kpi.solo_height"],
        },
    }
```

### 7.1 KPI+图表 (kpi_with_chart)

```python
def _layout_kpi_with_chart(self, profile, slide_data, template):
    T = self.T
    kpi_count = profile["kpi_count"]
    
    # 可用高度（Insight Bar 在 footer.top 之外，不占内容区域）
    available = T["footer.top"] - T["content.top"]  # 4.7"
    
    # KPI 区域
    kpi_h = T["kpi.with_chart_height"]  # 2.0"
    
    # 图表区域
    chart_h = available - kpi_h - T["gap.section"]  # 4.7 - 2.0 - 0.5 = 2.2"
    chart_h = max(min(chart_h, T["chart.max_height"]), T["chart.min_height"])
    chart_top = T["content.top"] + kpi_h + T["gap.section"]
    
    return {
        "kpi_row": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": T["content.width"],
            "height": kpi_h,
            "_style_delta": {
                "number_size": T["kpi.number_size_sm"],
                "label_size": T["kpi.label_size_sm"],
            },
        },
        "chart": {
            "left": (SLIDE_WIDTH - T["chart.center_width"]) / 2,
            "top": chart_top,
            "width": T["chart.center_width"],
            "height": chart_h,
        },
    }
```

### 7.2 表格+图表 (table_with_chart)

```python
def _layout_table_with_chart(self, profile, slide_data, template):
    T = self.T
    table_rows = profile["table_rows"]
    
    table_h = min(table_rows * T["table.row_height"], T["table.max_display_height"])
    available = T["footer.top"] - T["content.top"]  # 4.7"
    chart_h = available - table_h - T["gap.section"]
    chart_h = max(min(chart_h, T["chart.max_height"]), T["chart.min_height"])
    chart_top = T["content.top"] + table_h + T["gap.section"]
    
    return {
        "data_table": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": T["content.width"],
            "height": table_h,
        },
        "chart": {
            "left": (SLIDE_WIDTH - T["chart.center_width"]) / 2,
            "top": chart_top,
            "width": T["chart.center_width"],
            "height": chart_h,
        },
    }
```

### 7.3 文字+图表 (items_with_chart)

```python
def _layout_items_with_chart(self, profile, slide_data, template):
    T = self.T
    
    items_w = 5.0
    chart_w = T["content.width"] - items_w - T["gap.section"]  # 11.7 - 5.0 - 0.5 = 6.2
    content_h = T["footer.top"] - T["content.top"]  # 4.7"
    
    return {
        "bullet_items": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": items_w,
            "height": content_h,
        },
        "chart": {
            "left": T["margin.left"] + items_w + T["gap.section"],
            "top": T["content.top"],
            "width": chart_w,
            "height": content_h,
        },
    }
```

### 7.4 KPI+产品图 (kpi_with_photo)

```python
def _layout_kpi_with_photo(self, profile, slide_data, template):
    T = self.T
    # 左右布局：KPI 2×2 网格 | 产品图
    # 总宽 = kpi_w + gap + photo_w = T.content.width
    photo_w = 5.5
    kpi_w = T["content.width"] - photo_w - T["gap.section"]  # 11.7 - 5.5 - 0.5 = 5.7
    content_h = T["footer.top"] - T["content.top"]  # 4.7"
    
    return {
        "kpi_row": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": kpi_w,
            "height": content_h,
            "_style_delta": {
                "number_size": T["kpi.number_size_sm"],
                "label_size": T["kpi.label_size_sm"],
                "layout_mode": "grid",
                "grid_cols": 2,
            },
        },
        "chart": {  # slot id 仍为 "chart"，复用现有 image slot
            "left": T["margin.left"] + kpi_w + T["gap.section"],
            "top": T["content.top"],
            "width": photo_w,
            "height": content_h,
        },
    }
```

**注意**：kpi_w = 5.7"（非 11.6 节 ASCII 图中的 5.8"）。5.7 + 0.5 + 5.5 = 11.7 = T.content.width，精确匹配。每卡宽 = (5.7 - 0.4) / 2 = 2.65"，仍可容纳 28pt 数字。

**KPI grid 模式渲染算法**（在 `_render_kpi_cards_slot` 中增加）：

```python
# 当 style 中 layout_mode == "grid" 时，2×2 网格布局
# 注意：此逻辑在 _render_kpi_cards_slot 中，当 _style_delta 包含 layout_mode="grid" 时触发
if st.get("layout_mode") == "grid":
    grid_cols = st.get("grid_cols", 2)
    grid_rows = math.ceil(len(kpi_data) / grid_cols)
    # grid 模式下 card_width 基于 grid_cols 而非 len(kpi_data)
    card_width = (total_width - gap * (grid_cols - 1)) / grid_cols
    card_h = (card_height - gap * (grid_rows - 1)) / grid_rows
    for i, kpi in enumerate(kpi_data):
        row = i // grid_cols
        col = i % grid_cols
        card_left = start_left + col * (card_width + gap)
        card_top_grid = start_top + row * (card_h + gap)
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(card_left), Inches(card_top_grid),
            Inches(card_width), Inches(card_h),
        )
        # ... 填充数字+标签（与现有逻辑相同）
```

### 7.5 文字+产品图 (items_with_photo)

```python
def _layout_items_with_photo(self, profile, slide_data, template):
    T = self.T
    
    items_w = 5.5
    photo_w = T["content.width"] - items_w - T["gap.section"]  # 11.7 - 5.5 - 0.5 = 5.7
    content_h = T["footer.top"] - T["content.top"]  # 4.7"
    
    return {
        "bullet_items": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": items_w,
            "height": content_h,
        },
        "chart": {  # slot id 仍为 "chart"，复用现有 image slot
            "left": T["margin.left"] + items_w + T["gap.section"],
            "top": T["content.top"],
            "width": photo_w,
            "height": content_h,
        },
    }
```

### 7.6 表格+产品图 (table_with_photo)

```python
def _layout_table_with_photo(self, profile, slide_data, template):
    T = self.T
    table_rows = profile["table_rows"]
    
    table_w = 5.6
    photo_w = T["content.width"] - table_w - T["gap.section"]  # 11.7 - 5.6 - 0.5 = 5.6
    content_h = T["footer.top"] - T["content.top"]  # 4.7"
    table_h = min(table_rows * T["table.row_height"], T["table.max_display_height"])
    
    return {
        "data_table": {
            "left": T["margin.left"],
            "top": T["content.top"],
            "width": table_w,
            "height": table_h,
        },
        "chart": {  # slot id 仍为 "chart"，复用现有 image slot
            "left": T["margin.left"] + table_w + T["gap.section"],
            "top": T["content.top"],
            "width": photo_w,
            "height": content_h,
        },
    }
```

## 8. 边界情况处理

| 边界情况 | 处理方式 |
|---------|---------|
| KPI只有1个 | kpi_solo 布局，1张居中全宽卡片 |
| KPI有5个+ | 取前4个（max_cards），多出的忽略 |
| 表格行数>6 | table_with_chart：表格高度封顶 2.5"，超出部分截断；table_with_photo：同 |
| 图表宽高比极端 | _render_image_slot 的 aspect ratio 逻辑自动处理 |
| 内容为空 | LayoutEngine 返回空 dict，template 默认布局兜底 |
| insight_text 为空 | insight bar 不渲染（现有逻辑已处理） |
| 美学验证失败 | 降级到不含图表的纯布局（_fallback_layout） |
| comparison 模板 | LayoutEngine 不干预，保持现有布局 |
| chart_full / chart_split | LayoutEngine 不干预，保持现有布局 |

---

## 9. 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/converters/layout_engine.py` | **新增** | LayoutEngine 类，含 profile/classify/layout/validate/fallback，10种场景，约350行 |
| `src/converters/slide_renderer.py` | 修改 | render() 和 _render_slot() 接受 layout_overrides 参数，浅拷贝+合并 position 和 style；_render_kpi_cards_slot 增加 grid 模式（2×2布局）；_render_image_slot 增加 URL→本地路径转换 |
| `src/converters/html_to_ppt.py` | 修改 | _create_pptx_document 中实例化 LayoutEngine，调整图表生成逻辑顺序，传 layout_overrides 给 renderer |
| `config/ppt_templates/kpi_highlight.json` | 修改 | 移除 chart slot，KPI 卡片恢复全宽 11.7" |
| `config/ppt_templates/data_table.json` | 修改 | 移除 chart slot，表格恢复全宽 11.7" |
| `config/ppt_templates/findings.json` | 修改 | 移除 chart slot，文字恢复全宽 11.7" |
| `tests/unit/test_layout_engine.py` | **新增** | LayoutEngine 单元测试（profile/classify/validate/各场景布局） |

---

## 10. 不做的事

1. **不做约束求解器**（Cassowary/AutoLayout）——10种场景的规则引擎足够，约束求解器是过度工程
2. **不做 ML/Diffusion 布局生成**——内容组合有限，规则引擎更可靠更快。PPTBench 已证明纯 LLM 布局不可靠
3. **不改 chart_full / chart_split / comparison 模板**——这些是纯图表/对比布局，不需要动态调整
4. **不改 TemplateSelector 的模板选择逻辑**——LayoutEngine 在模板选择之后工作，是补充而非替代
5. **不做用户可调布局**——Beautiful.ai 的教训是"约束优于自由"，我们预设最优布局

---

## 11. 图片服务（ImageProvider）

### 11.1 问题陈述

市场研究报告经常需要插入产品图片、技术示意图、行业场景图等。当前系统存在的关键缺陷：

| 缺陷 | 说明 |
|------|------|
| **URL 图片不可用** | `<img src="https://...">` 会被解析但渲染时 `os.path.isfile()` 检查失败，图片被静默跳过 |
| **无图片搜索能力** | 没有 Unsplash/Pexels 等图片 API 集成 |
| **无 AI 图片生成** | 没有 DALL-E/Stable Diffusion 集成 |
| **图表和插图混为一谈** | 系统只有 chart images（matplotlib 生成），没有 illustrative images 的概念 |
| **LayoutEngine 不区分图片类型** | 图表和产品图在布局中应受到不同对待，但当前 `slide_data["images"]` 没有类型标记 |

### 11.2 行业调研发现

| 工具 | 图片方案 | 关键特点 |
|------|---------|---------|
| **Beautiful.ai** | Stock + AI生成 + Web + None 四选一 | 用户生成前选择图片来源，可设统一 AI 风格 |
| **Gamma** | AI 生成 + Stock 搜索 | 基于幻灯片内容自动选择/生成相关图片 |
| **Tome** | DALL-E 集成 | 首批整合 DALL-E 的 PPT 工具，每张幻灯片可获 AI 插图 |
| **AiPPT** | 版权图库 + AI作图 + 用户上传 | 中国市场强调版权合规，有专属图库 |

**核心洞察**：成功的工具都采用**混合路由**策略——不同类型的图片走不同来源，而非一刀切。

### 11.3 图片分类与路由策略

```
Slide 内容 → LLM 关键词提取 → ImageRouter
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
         产品/品牌图片         技术/行业图片         概念/抽象图片
                │                   │                   │
        用户上传优先          Stock API 搜索         AI 图片生成
        Web 搜索其次          (Unsplash/Pexels)     (DALL-E/SD)
                │                   │                   │
                └───────────────────┼───────────────────┘
                                    │
                              本地缓存 + 下载
                                    │
                              slide_data["images"]
```

**图片类型定义**：

```python
class ImageType(Enum):
    CHART = "chart"           # 数据图表（matplotlib 生成，已有）
    PRODUCT = "product"       # 产品图片（需要精确匹配，用户上传或web搜索）
    TECHNOLOGY = "technology" # 技术图片（服务器、芯片、代码等，stock搜索）
    ILLUSTRATION = "illustration" # 概念插图（抽象概念，AI生成）
    USER = "user"             # 用户直接提供的图片
```

### 11.4 ImageProvider 架构

```python
class ImageProvider:
    """
    图片获取服务——根据幻灯片内容自动获取/生成合适图片。
    
    灵感来源：
    - Beautiful.ai 的多源图片选择
    - Gamma 的内容感知图片选择
    - AiPPT 的版权图库 + AI作图
    
    路由策略：
    1. 用户上传 > Stock搜索 > AI生成 > 占位符
    2. 产品图必须真实 → 不用AI生成
    3. 概念图可以抽象 → AI生成即可
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.cache_dir = self.config.get("cache_dir", "output/images")
        self.unsplash_key = self.config.get("unsplash_api_key")
        self.pexels_key = self.config.get("pexels_api_key")
        self.openai_key = self.config.get("openai_api_key")
        self._cache = {}  # keyword → local_path（内存缓存，重启清空；磁盘缓存由 _download 的 sha256 文件名提供持久化）
    
    def get_image(self, keyword: str, image_type: str = "technology",
                  style: str = "landscape") -> Optional[str]:
        """
        根据关键词获取图片，返回本地文件路径。
        
        路由逻辑：
        - product → skip AI gen, stock only
        - technology → stock first, AI gen fallback
        - illustration → AI gen first, stock fallback
        
        Returns: 本地文件路径，或 None（获取失败）
        """
        # 1. 检查缓存
        cache_key = f"{keyword}:{image_type}:{style}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if os.path.isfile(cached):
                return cached
        
        # 2. 按类型路由
        local_path = None
        if image_type == "product":
            # 产品图优先stock搜索，不允许AI生成（产品必须真实）
            local_path = self._search_stock(keyword)
        elif image_type == "technology":
            local_path = self._search_stock(keyword) or self._generate_ai(keyword)
        elif image_type == "illustration":
            local_path = self._generate_ai(keyword) or self._search_stock(keyword)
        else:
            local_path = self._search_stock(keyword)
        
        # 3. 缓存结果
        if local_path:
            self._cache[cache_key] = local_path
        
        return local_path
    
    def _search_stock(self, keyword: str) -> Optional[str]:
        """搜索 Unsplash/Pexels，下载到本地，返回路径"""
        # 先尝试 Unsplash（免费1K请求/小时）
        url = self._search_unsplash(keyword)
        if not url:
            url = self._search_pexels(keyword)
        if url:
            return self._download(url, keyword)
        return None
    
    def _generate_ai(self, keyword: str) -> Optional[str]:
        """调用 DALL-E/SD 生成图片，下载到本地，返回路径"""
        if not self.openai_key:
            return None
        # 用 LLM 生成更精确的图片描述
        prompt = self._build_prompt(keyword)
        url = self._call_dalle(prompt)
        if url:
            return self._download(url, keyword)
        return None
    
    def _download(self, url: str, keyword: str) -> Optional[str]:
        """下载图片到本地缓存目录"""
        os.makedirs(self.cache_dir, exist_ok=True)
        filename = hashlib.sha256(url.encode()).hexdigest()[:16] + ".jpg"
        local_path = os.path.join(self.cache_dir, filename)
        if os.path.isfile(local_path):
            return local_path
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                return local_path
        except Exception:
            logger.warning(f"Failed to download image: {url}")
        return None
    
    def _build_prompt(self, keyword: str) -> str:
        """构建 AI 图片生成 prompt"""
        return (f"Professional business presentation illustration: {keyword}. "
                f"Clean, modern style. Landscape orientation. No text overlays.")
    
    def _search_unsplash(self, keyword: str) -> Optional[str]:
        """搜索 Unsplash，返回图片 URL"""
        if not self.unsplash_key:
            return None
        try:
            resp = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": keyword, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {self.unsplash_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    return results[0]["urls"]["regular"]
        except Exception:
            logger.warning(f"Unsplash search failed: {keyword}")
        return None
    
    def _search_pexels(self, keyword: str) -> Optional[str]:
        """搜索 Pexels，返回图片 URL"""
        if not self.pexels_key:
            return None
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": keyword, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": self.pexels_key},
                timeout=10,
            )
            if resp.status_code == 200:
                photos = resp.json().get("photos", [])
                if photos:
                    return photos[0]["src"]["large"]
        except Exception:
            logger.warning(f"Pexels search failed: {keyword}")
        return None
    
    def _call_dalle(self, prompt: str) -> Optional[str]:
        """调用 DALL-E 3 生成图片，返回图片 URL"""
        if not self.openai_key:
            return None
        try:
            import openai
            client = openai.OpenAI(api_key=self.openai_key)
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1792x1024",  # landscape
                quality="standard",
                n=1,
            )
            return response.data[0].url
        except Exception:
            logger.warning(f"DALL-E generation failed: {prompt[:50]}")
        return None
```

### 11.5 与 LayoutEngine 的集成——图片类型标记

当前 `slide_data["images"]` 格式为 `[{"src": path, "alt": text}]`。需要扩展以支持图片类型：

```python
# 新格式（向后兼容）
{"src": path, "alt": text, "image_type": "chart"}     # 图表
{"src": path, "alt": text, "image_type": "product"}   # 产品图
{"src": path, "alt": text, "image_type": "technology"} # 技术图
{"src": path, "alt": text, "image_type": "illustration"} # 插图

# 无 image_type 时默认为 "chart"（向后兼容）
```

**LayoutEngine 根据图片类型调整布局策略**：

| 图片类型 | 布局策略 | 说明 |
|---------|---------|------|
| `chart` | 居中，8"宽，上下布局 | 图表是数据佐证，不与主内容争宽度 |
| `product` / `technology` | 右侧5.5-5.7"宽，左右布局 | 真实图片是视觉焦点，适合左文右图 |
| `illustration` | 右侧，左右布局（MVP） | 当前统一走左右布局，未来可扩展居中模式 |

图片类型通过 `content_profile` 中的 `has_chart` 和 `has_photo` 字段影响场景分类（见 4.1 和 4.2 节）。`has_chart` 仅在所有图片都是 chart 类型时为 True；`has_photo` 在存在任何非 chart 图片时为 True。

### 11.6 新增布局场景

> **Insight Bar 与左右布局**：所有左右布局场景（kpi_with_photo, items_with_photo, table_with_photo）中，Insight Bar 位于 T=5.8"，在内容区域（1.1"~5.8"）之外，不会与左侧内容或右侧图片重叠。左右布局只影响 1.1"~5.8" 区间内的元素排列。

#### 场景9: KPI+产品图 (kpi_with_photo)

**触发条件**: `has_kpis=True AND has_photo=True`

```
┌──────────────────────────────────────────────┐
│  Title                                        │
├──────────────────────────────────────────────┤
│   ┌──────────────────┐  ┌────────────────┐   │
│   │  ┌───┐ ┌───┐     │  │                │   │
│   │  │KPI│ │KPI│     │  │   Photo        │   │
│   │  └───┘ └───┘     │  │   w=5.5"       │   │
│   │  ┌───┐ ┌───┐     │  │   h=4.7"       │   │
│   │  │KPI│ │KPI│     │  │                │   │
│   │  └───┘ └───┘     │  │                │   │
│   │  w=5.7"          │  └────────────────┘   │
│   └──────────────────┘                        │
│   ┌──────────────────────────────────────┐   │
│   │  💡 Insight Bar                       │   │
│   └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘

KPI: left=0.8, top=1.1, width=5.7, height=4.7
     2×2 grid布局（每行2个卡片）
     每卡宽=(5.7-0.4)/2=2.65", 每卡高=(4.7-0.4)/2=2.15"
     _style_delta: layout_mode="grid", grid_cols=2
Photo: left=0.8+5.7+0.5=7.0, top=1.1, width=5.5, height=4.7
```

**注意**：Photo 在 LayoutEngine 返回值中的 slot id 仍为 `"chart"`，复用现有 image slot 的渲染逻辑（`_render_image_slot`）。模板 JSON 中的 chart slot 会被 LayoutEngine 的 position override 重新定位。

**设计论证**：
- 产品图/技术图是"真实视觉证据"，与图表（数据证据）的布局逻辑不同
- 产品图放在右侧作为视觉支撑，左边 KPI 2×2 网格足够紧凑（2.65"/卡宽，2.15"/卡高）
- KPI 卡片从横排4列改为2×2网格，需要在 `_style_delta` 中指定 `layout_mode="grid"`，`_render_kpi_cards_slot` 需增加 grid 模式支持
- 与 Beautiful.ai 的 "Impact Slides + Image" 布局一致

#### 场景10: 文字+产品图 (items_with_photo)

**触发条件**: `has_items=True AND has_photo=True AND has_kpis=False`

```
┌──────────────────────────────────────────────┐
│  Title                                        │
├──────────────────────────────────────────────┤
│   ┌──────────────┐  ┌────────────────────┐   │
│   │  Text Items  │  │   Photo            │   │
│   │  w=5.5"      │  │   w=5.7"           │   │
│   │              │  │                    │   │
│   └──────────────┘  └────────────────────┘   │
│   gap=0.5"                                   │
└──────────────────────────────────────────────┘
```

与 items_with_chart 类似，但比例不同：产品图不需要像图表那么宽（5.7" vs 6.2"），文字需要更多空间来描述图片（5.5" vs 5.0"）。总宽 5.5 + 0.5(gap) + 5.7 = 11.7"。

### 11.7 图片获取的触发时机

图片获取应在**内容生成阶段**（而非渲染阶段）完成：

```
用户输入 → LLM生成大纲 → LLM扩展内容 → ImageProvider获取图片 → slide_data包含images → LayoutEngine → Renderer
                                                    ↑
                                            此处插入图片获取逻辑
```

具体实现：在 `html_to_ppt.py` 的 `_create_pptx_document` 中，模板选择之后、图表生成之前：

```python
# 1. 模板选择
template_name = selector.select_and_enhance(slide_data, section_index)

# 2. 图片获取（新增）
if image_provider and not slide_data.get("images"):
    image_provider.enrich_images(slide_data)

# 3. 图表生成（若 ImageProvider 已添加图片，则跳过图表生成——每页最多1张图）
if chart_gen and not slide_data.get("images"):
    if layout_engine.can_accommodate_chart(slide_data, template_name):
        self._auto_generate_charts(slide_data, template_name, chart_gen)

# 4. 布局计算 + 渲染
layout_overrides = layout_engine.compute(slide_data, template)
renderer.render(slide, slide_data, template, styles, ...)
```

`enrich_images()` 方法根据 slide 内容自动判断是否需要图片：

```python
def enrich_images(self, slide_data: Dict) -> None:
    """根据幻灯片内容自动获取合适图片"""
    slide_type = slide_data.get("slide_type", "")
    if slide_type in ("cover", "toc", "section_title", "end"):
        return  # 这些页面不需要插图
    
    title = slide_data.get("title", "")
    content = slide_data.get("content", "")
    
    # 用 LLM 提取关键词和图片类型
    keywords = self._extract_keywords(title, content)
    if not keywords:
        return
    
    for kw in keywords:
        image_type = kw.get("type", "technology")
        keyword = kw.get("keyword", "")
        local_path = self.get_image(keyword, image_type)
        if local_path:
            images = slide_data.get("images", [])
            images.append({
                "src": local_path,
                "alt": keyword,
                "image_type": image_type,
            })
            slide_data["images"] = images
            break  # 每页最多1张插图
    
    def _extract_keywords(self, title: str, content: str) -> List[Dict]:
        """从标题和内容中提取图片关键词和类型"""
        # 简单规则：根据标题关键词判断图片类型
        # MVP 阶段用关键词匹配，未来可用 LLM
        product_keywords = ["产品", "手机", "汽车", "车型", "芯片", "设备"]
        tech_keywords = ["技术", "AI", "云计算", "服务器", "数据", "5G", "半导体"]
        concept_keywords = ["趋势", "未来", "战略", "展望", "生态", "格局"]
        
        text = f"{title} {content}"
        for kw_list, image_type in [
            (product_keywords, "product"),
            (tech_keywords, "technology"),
            (concept_keywords, "illustration"),
        ]:
            for kw in kw_list:
                if kw in text:
                    return [{"keyword": kw, "type": image_type}]
        return []
```

### 11.8 URL图片下载支持

修复当前"URL图片被跳过"的缺陷。`_resolve_image_src` 方法放在 `ImageProvider` 类中（它已有 `self.cache_dir` 和 `_download` 方法）。`SlideRenderer` 在 `_render_image_slot` 中调用 `image_provider._resolve_image_src(src)` 转换 URL 为本地路径。

```python
# ImageProvider 类中新增方法
def _resolve_image_src(self, src: str) -> Optional[str]:
    """将图片 src 转换为本地文件路径"""
    # 已是本地文件
    if os.path.isfile(src):
        return src
    
    # URL → 下载到缓存
    if src.startswith(("http://", "https://")):
        cache_dir = os.path.join(self.cache_dir, "downloaded")
        os.makedirs(cache_dir, exist_ok=True)
        # 用 URL hash 作为文件名
        filename = hashlib.sha256(src.encode()).hexdigest()[:16] + ".jpg"
        local_path = os.path.join(cache_dir, filename)
        if os.path.isfile(local_path):
            return local_path
        try:
            resp = requests.get(src, timeout=10)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                return local_path
        except Exception:
            logger.warning(f"Failed to download image: {src}")
    
    return None
```

### 11.9 文件改动清单（图片部分新增）

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/services/image_provider.py` | **新增** | ImageProvider 类，含 stock搜索/AI生成/下载/缓存，约250行 |
| `src/converters/layout_engine.py` | 修改 | 场景分类器增加图片类型判断，新增 kpi_with_photo / items_with_photo / table_with_photo 场景 |
| `src/converters/html_to_ppt.py` | 修改 | 集成 ImageProvider.enrich_images()，增加 URL 图片下载逻辑 |
| `src/converters/slide_renderer.py` | 修改 | _render_image_slot 增加 URL→本地路径转换（复用 ImageProvider._resolve_image_src） |
| `config/settings.py` 或环境变量 | 修改 | 新增 UNSPLASH_API_KEY / PEXELS_API_KEY / OPENAI_API_KEY 配置 |

### 11.10 图片 API 优先级

| 优先级 | API | 免费额度 | 最佳场景 |
|--------|-----|---------|---------|
| 1 | **Unsplash** | 1,000 请求/小时 | 高质量技术/行业照片 |
| 2 | **Pexels** | 200 请求/小时, 2万/月 | 补充 Unsplash 找不到的图片 |
| 3 | **DALL-E 3** | ~$0.04-0.08/张 | 概念插图、无法搜到的图片 |
| 4 | **用户上传** | 免费 | 产品图片、品牌素材 |

**不引入的方案**：
- Midjourney：无官方 API，不适合自动化流程
- Bing/Google 图片搜索：付费且法律风险高，版权不清晰
- Pixabay：图片质量较低，不如 Unsplash

---

## 12. 未来扩展方向

1. **AeSlides 式 RL 微调**：收集用户对布局的偏好数据，用 GRPO 微调布局令牌值
2. **Diffusion 背景生成**（Desigen 思路）：为不同场景生成配套的背景装饰
3. **Sketch-to-Layout**：用户画草图指定布局意图，LayoutEngine 据此调整
4. **更多布局场景**：3图表、KPI+表格+图表等复杂组合
5. **品牌令牌系统**：让企业用户自定义 LAYOUT_TOKENS（字体、间距、配色）
6. **更多图片来源**：千图网/包图网等中国图库 API，Shutterstock 企业图库
