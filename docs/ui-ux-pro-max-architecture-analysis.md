# UI/UX Pro Max Skill 架构深度分析

> 生成日期：2026-07-08
> 分析范围：`src/ui-ux-pro-max/` 核心模块 + `.claude/skills/` 关联 skill（design-system, slides）

---

## 一、项目全景

### 1.1 定位

UI/UX Pro Max 是一个**知识驱动的 UI 设计决策引擎**，以 CSV 数据库为知识层、BM25 搜索引擎为检索层、推理规则为决策层，为 AI 编码助手（Claude Code / Cursor / Windsurf 等）提供可搜索、可推理、可持久化的设计系统生成能力。

### 1.2 核心数据流

```
用户查询（如 "SaaS dashboard"）
        │
        ▼
  ┌─────────────┐     ┌──────────────────┐
  │  BM25 搜索   │────▶│  12个域 + 22个栈  │  ← CSV 知识库（~5100+ 条）
  └──────┬──────┘     └──────────────────┘
         │
         ▼
  ┌─────────────┐     ┌──────────────────┐
  │  推理引擎    │────▶│  ui-reasoning.csv │  ← 161 条决策规则
  └──────┬──────┘     └──────────────────┘
         │
         ▼
  ┌─────────────┐     ┌──────────────────┐
  │  设计拨盘    │────▶│  variance/motion/ │  ← 3 个 1-10 滑块
  │  (可选)      │     │  density          │
  └──────┬──────┘     └──────────────────┘
         │
         ▼
  ┌─────────────────────────────────────┐
  │  完整设计系统输出                      │
  │  Pattern + Style + Colors +          │
  │  Typography + Spacing + Shadows +    │
  │  Components + Motion + Anti-patterns │
  └─────────────────────────────────────┘
         │
         ▼ (可选 --persist)
  ┌─────────────────────────────────────┐
  │  持久化文件系统                        │
  │  MASTER.md + pages/*.md (Overrides)  │
  └─────────────────────────────────────┘
```

---

## 二、模块详解

### 2.1 数据层（`data/`）— 15 个 CSV 知识库

| CSV 文件 | 行数 | 列数 | 核心字段 | 用途 |
|----------|------|------|----------|------|
| `styles.csv` | 84 | 22 | Style Category, Keywords, AI Prompt Keywords, CSS/Technical Keywords, Design System Variables | UI 风格百科（极简主义、玻璃拟态、粗野主义等） |
| `colors.csv` | 192 | 18 | Product Type, Primary→Ring (10色), Notes | 按产品类型的完整语义色板 |
| `products.csv` | 192 | 9 | Product Type, Primary Style Recommendation, Secondary Styles, Landing Page Pattern | 产品类型→风格/落地页映射 |
| `typography.csv` | 74 | 11 | Font Pairing Name, Heading/Body Font, Google Fonts URL, CSS Import, Tailwind Config | 字体配对方案 |
| `charts.csv` | 25 | 13 | Data Type, Best Chart Type, Accessibility Grade, Library Recommendation | 图表类型推荐 |
| `landing.csv` | 34 | 7 | Pattern Name, Section Order, Primary CTA Placement, Conversion Optimization | 落地页结构策略 |
| `ux-guidelines.csv` | 99 | 10 | Category, Issue, Do/Don't, Code Example Good/Bad, Severity | UX 最佳实践 |
| `motion.csv` | 16 | 11 | Category, Intensity Tier, GSAP Snippet, Framework Notes, Do/Don't | GSAP 动画骨架 |
| `icons.csv` | 105 | 9 | Category, Icon Name, Library, Import Code, Usage | 图标推荐 |
| `google-fonts.csv` | 1,923 | 15 | Family, Category, Styles, Variable Axes, Popularity Rank | Google Fonts 完整数据库 |
| `ui-reasoning.csv` | 161 | 9 | UI_Category, Recommended_Pattern, Style_Priority, Decision_Rules (JSON), Anti_Patterns | **推理决策规则** |
| `app-interface.csv` | 30 | 11 | Category, Issue, Do/Don't, Code Example Good/Bad | 跨平台 App 界面指南 |
| `react-performance.csv` | 44 | 11 | Category, Issue, Do/Don't, Code Example Good/Bad | React/Next.js 性能优化 |
| `design.csv` | 1,601 | — | 风格名 + 描述 + 适用场景 + 完整 design-system XML | 设计风格深度参考（中文） |
| `draft.csv` | 1,602 | — | design.csv 的备份 | 备份文件 |

**技术栈数据（`data/stacks/`）— 22 个 CSV：**

| 栈 | 行数 | 栈 | 行数 |
|----|------|----|------|
| react | 53 | vue | 49 |
| nextjs | 52 | svelte | 53 |
| astro | 53 | swiftui | 50 |
| react-native | 51 | flutter | 52 |
| nuxtjs | 58 | nuxt-ui | 70 |
| html-tailwind | 55 | shadcn | 60 |
| jetpack-compose | 52 | threejs | 53 |
| angular | 50 | laravel | 50 |
| javafx | 75 | wpf | 56 |
| winui | 59 | avalonia | 56 |
| uno | 59 | uwp | 55 |

**数据总量：** ~5,100+ 条结构化设计知识记录

### 2.2 搜索引擎层（`scripts/core.py` — 274 行）

#### 2.2.1 BM25 算法实现

```python
class BM25:
    k1 = 1.5    # 词频饱和参数
    b  = 0.75   # 文档长度归一化参数

    tokenize()  → 小写 + 去标点 + 过滤 <2 字符词
    fit()       → 建索引：语料 → 词频 → IDF
    score()     → 查询评分：TF-IDF 变体排序
```

**特点：**
- 纯 Python 实现，零外部依赖
- 每次查询实时建索引（无持久化索引），适合小数据集
- 分词简单（空格分割），对中文支持弱

#### 2.2.2 域搜索配置

每个域定义了 `search_cols`（搜索哪些列）和 `output_cols`（输出哪些列），实现**搜索字段与输出字段分离**：

```python
CSV_CONFIG = {
    "style": {
        "file": "styles.csv",
        "search_cols": ["Style Category", "Keywords", "Best For", "Type", "AI Prompt Keywords"],
        "output_cols": ["Style Category", "Type", "Keywords", ..., "Design System Variables"]
    },
    # ... 12 个域
}
```

#### 2.2.3 自动域检测

`detect_domain()` 基于关键词匹配自动判断查询属于哪个域：

```python
domain_keywords = {
    "color": ["color", "palette", "hex", "#", "rgb", ...],
    "chart": ["chart", "graph", "visualization", ...],
    "product": ["saas", "ecommerce", "fintech", ...],
    # ... 12 个域，每个域 10-50+ 关键词
}
```

**局限：** 纯关键词匹配，无语义理解，对模糊查询可能误判。

### 2.3 设计系统生成器（`scripts/design_system.py` — 1,329 行）

这是整个 skill 最核心、最复杂的模块。

#### 2.3.1 生成流程（5 步）

```
Step 1: search(query, "product", 1)
        → 获取产品类别（如 "SaaS (General)"）

Step 2: _apply_reasoning(category)
        → 从 ui-reasoning.csv 匹配推理规则
        → 输出: style_priority, color_mood, typography_mood,
                key_effects, anti_patterns, decision_rules

Step 3: _multi_domain_search(query, style_priority)
        → 并行搜索 5 个域: product / style / color / landing / typography
        → style 域会注入 style_priority 关键词增强匹配

Step 4: _select_best_match(results, priority_keywords)
        → 用推理规则的 style_priority 选择最佳匹配
        → 三级匹配: 精确名称匹配 → 关键词评分 → 默认首个

Step 5: 组装完整设计系统
        → pattern + style + colors + typography + effects
          + anti_patterns + dials + motion_snippet + spacing_scale
```

#### 2.3.2 推理引擎

`ui-reasoning.csv` 是决策的核心，每条规则包含：

| 字段 | 示例 | 说明 |
|------|------|------|
| UI_Category | SaaS (General) | 产品类别 |
| Recommended_Pattern | Hero + Features + CTA | 推荐页面模式 |
| Style_Priority | Glassmorphism + Flat Design | 风格优先级（+分隔） |
| Color_Mood | Trust blue + Accent contrast | 色彩情绪 |
| Typography_Mood | Professional + Hierarchy | 排版情绪 |
| Key_Effects | Subtle hover (200-250ms) + Smooth transitions | 关键效果 |
| Decision_Rules | `{"if_ux_focused":"prioritize-minimalism","if_data_heavy":"add-glassmorphism"}` | 条件决策规则（JSON） |
| Anti_Patterns | Excessive animation + Dark mode by default | 反模式 |
| Severity | HIGH | 严重度 |

**决策规则支持条件分支**，但目前仅作为参考信息输出，未在代码中实现自动分支逻辑。

#### 2.3.3 设计拨盘（Design Dials）

3 个可选的 1-10 滑块，不影响默认行为（未设置时完全等价于旧版）：

| 拨盘 | 低 (1-3) | 中 (4-7) | 高 (8-10) | 影响机制 |
|------|----------|----------|-----------|----------|
| `--variance` | 居中/极简 | 平衡/现代 | 大胆/不对称 | 在 style_priority 前插入偏向关键词 |
| `--motion` | 微交互 | 标准滚动 | 复杂编排 | 从 motion.csv 拉取匹配 Intensity Tier 的 GSAP 代码片段 |
| `--density` | 宽松 (24-96px) | 标准 (16-64px) | 密集 (8-32px) | 覆盖 spacing scale 的 7 个 CSS 变量 |

**实现方式：**
```python
DIAL_TIERS = {
    "variance": [
        (1, 3, {"label": "Centered / Minimal", "style_keywords": ["Minimalism", ...]}),
        (4, 7, {"label": "Balanced / Modern",   "style_keywords": ["modern", ...]}),
        (8,10, {"label": "Bold / Asymmetric",   "style_keywords": ["Brutalism", ...]}),
    ],
    # motion, density 类似
}
```

#### 2.3.4 持久化系统（Master + Overrides 模式）

```
design-system/
└── <project-slug>/
    ├── MASTER.md          ← 全局真相源（完整设计系统）
    └── pages/
        ├── dashboard.md   ← 页面覆盖（仅记录偏差）
        ├── checkout.md
        └── ...
```

**层级逻辑：**
1. 构建某页面时，先查 `pages/[page].md`
2. 若存在，其规则**覆盖** MASTER.md
3. 若不存在，严格遵循 MASTER.md

**智能页面覆盖生成（`_generate_intelligent_overrides`）：**
- 自动检测页面类型（10 种：Dashboard/Checkout/Settings/Landing/Auth/Pricing/Blog/Product/Search/Empty State）
- 跨域搜索（style + ux + landing）生成页面专属的布局/间距/排版/颜色/组件覆盖
- 从 UX 搜索结果提取 Do/Don't 作为推荐/警告

#### 2.3.5 输出格式

| 格式 | 用途 | 特点 |
|------|------|------|
| ASCII box | 终端展示 | Unicode 框线 + ANSI True Color 色块 ██ |
| Markdown | 文档化 | 表格 + 代码块 + CSS 变量 |
| MASTER.md | 持久化 | 完整 CSS 变量 + 组件规格 + 阴影深度 + 检查清单 |
| pages/*.md | 页面覆盖 | 仅记录与 MASTER 的偏差 |

**MASTER.md 包含的完整内容：**
1. Global Rules — 色板（10色 + CSS变量）、字体（含 Google Fonts URL + CSS Import）、间距变量（7级）、阴影深度（4级）
2. Component Specs — Button / Card / Input / Modal 的完整 CSS
3. Style Guidelines — 风格关键词 + 最佳场景 + 关键效果
4. Page Pattern — 模式名 + 转化策略 + CTA 位置 + 区块顺序
5. Motion — GSAP 代码片段（仅 --motion 设置时）
6. Anti-Patterns — 反模式 + 通用禁止模式
7. Pre-Delivery Checklist — 10 项交付前检查

### 2.4 CLI 入口（`scripts/search.py` — 127 行）

参数解析 + 格式化输出，支持：

```
python search.py "<query>"
  [--domain <domain>]          # 单域搜索
  [--stack <stack>]            # 技术栈搜索
  [--design-system]            # 设计系统生成
  [--persist] [--page <name>]  # 持久化
  [--variance <1-10>]          # 设计拨盘
  [--motion <1-10>]
  [--density <1-10>]
  [--json]                     # JSON 输出
  [-n <max_results>]           # 结果数量
```

### 2.5 模板系统（`templates/`）

| 路径 | 作用 |
|------|------|
| `base/skill-content.md` | 通用 SKILL.md 内容（工作流 + 规则 + 检查清单，392 行） |
| `base/quick-reference.md` | 快速参考段（仅 Claude 平台使用） |
| `platforms/*.json` (18个) | 各 AI 平台的安装配置 |

**18 个平台配置：** agent, augment, claude, codebuddy, codex, continue, copilot, cursor, droid, gemini, kilocode, kiro, opencode, qoder, roocode, trae, warp, windsurf

每个 JSON 配置定义了：安装路径、SKILL.md 文件名、脚本路径、frontmatter（name/description）、是否包含 quick-reference 等。

---

## 三、关联 Skill 分析

项目中除了 `ui-ux-pro-max` 主 skill，还有两个紧密关联的 skill：

### 3.1 design-system skill（`.claude/skills/design-system/`）

**定位：** Token 架构 + 组件规格 + **幻灯片生成**

**与 ui-ux-pro-max 的关系：**
- design-system 专注于**设计 Token 体系**（Primitive → Semantic → Component 三层）
- ui-ux-pro-max 专注于**设计决策**（风格/色板/字体推荐）
- 两者互补：ui-ux-pro-max 决定"用什么"，design-system 决定"怎么系统化表达"

**幻灯片子系统：**

| 组件 | 文件 | 功能 |
|------|------|------|
| 搜索引擎 | `slide_search_core.py` (453行) | BM25 搜索 + 上下文决策系统 |
| CLI | `search-slides.py` (218行) | 搜索入口 + 上下文推荐 |
| 生成器 | `generate-slide.py` (770行) | HTML 幻灯片生成（8种幻灯片类型） |
| Token 验证 | `slide-token-validator.py` | 验证幻灯片 HTML 的 Token 合规性 |
| 背景图 | `fetch-background.py` | 从 Pexels/Unsplash 获取背景图 |

**8 个幻灯片数据 CSV：**

| CSV | 用途 |
|-----|------|
| slide-strategies.csv | 15 种演示结构 + 情绪弧线 |
| slide-layouts.csv | 25 种布局 + 组件变体 + 动画 |
| slide-layout-logic.csv | 目标 → 布局 + break_pattern 标志 |
| slide-typography.csv | 内容类型 → 排版规格 |
| slide-color-logic.csv | 情绪 → 色彩处理 |
| slide-backgrounds.csv | 幻灯片类型 → 背景图配置 |
| slide-copy.csv | 25 种文案公式（PAS, AIDA, FAB） |
| slide-charts.csv | 25 种图表 + Chart.js 配置 |

**上下文决策系统（Premium Feature）：**

```
search_with_context(query, slide_position, total_slides, previous_emotion)
    → 推荐布局 + 排版规格 + 色彩处理 + 背景图
    → 模式断裂计算（Duarte Sparkline 技术）
    → 全出血推荐
    → 动画类推荐
```

### 3.2 slides skill（`.claude/skills/slides/`）

**定位：** 轻量级幻灯片创建 skill，是 design-system 幻灯片功能的简化封装。

**5 个参考文档：**
- `create.md` — 创建命令入口
- `layout-patterns.md` — 25 种布局 + CSS 结构 + 动画类
- `slide-strategies.md` — 15 种演示结构 +5 种演示结构 + 情绪弧线
- `html-template.md` — 完整 HTML 模板（16:9 + Chart.js + 导航 + 动画）
- `copywriting-formulas.md` — 25 种文案公式

**与 design-system 的关系：** slides skill 是 design-system 幻灯片功能的"使用指南"，实际搜索和生成由 design-system 的脚本执行。

---

## 四、架构优缺点分析

### 4.1 优点

| 方面 | 说明 |
|------|------|
| **零依赖** | 纯 Python 标准库，无需 pip install |
| **知识可扩展** | CSV 格式，非开发者也能增删改查 |
| **多域聚合** | 一次查询跨 5 个域搜索，自动推理关联 |
| **推理规则** | 161 条决策规则，不是简单搜索而是有逻辑的推荐 |
| **设计拨盘** | 3 个滑块微调输出，不改变默认行为 |
| **持久化** | Master + Overrides 模式，支持跨会话复用 |
| **多平台** | 18 个 AI 平台配置，一次编写到处安装 |
| **22 个技术栈** | 覆盖 Web/移动/桌面全平台 |

### 4.2 缺点 / 改进空间

| 方面 | 问题 | 改进建议 |
|------|------|----------|
| **中文支持** | BM25 分词按空格分割，对中文查询效果差 | 引入 jieba 分词或字符级 n-gram |
| **无持久索引** | 每次查询重建 BM25 索引，大数据集（google-fonts 1923行）有性能开销 | 预建索引或缓存 |
| **推理规则未执行** | Decision_Rules 的条件分支仅作为文本输出，未在代码中实现自动分支 | 实现 `if_ux_focused` 等条件的运行时判断 |
| **design.csv 冗余** | 1601 行的中文设计参考，格式非标准 CSV，搜索引擎不读取 | 要么纳入搜索体系，要么移除 |
| **skill 间耦合松散** | ui-ux-pro-max / design-system / slides 三个 skill 各自独立，无统一调用链 | 建立统一的 pipeline |
| **无反馈闭环** | 搜索结果无用户反馈机制，无法学习优化 | 添加评分/反馈机制 |

---

## 五、改造为 PPT 生成 Skill 的工作难度分析

### 5.1 现有基础评估

| 维度 | 现有资产 | 可复用度 | 说明 |
|------|----------|----------|------|
| **搜索引擎** | `core.py` BM25 | ★★★★★ | 完全复用，只需新增 PPT 相关域配置 |
| **设计系统生成** | `design_system.py` | ★★★★☆ | 色板/字体/间距可直接用于 PPT，需新增 PPT 布局/模板逻辑 |
| **幻灯片数据** | design-system 的 8 个 slide-*.csv | ★★★★★ | 策略/布局/文案/图表/色彩逻辑/背景图全部可复用 |
| **幻灯片生成器** | `generate-slide.py` | ★★★☆☆ | 当前生成 HTML，需改造为 PPT 格式输出 |
| **上下文决策** | `slide_search_core.py` | ★★★★★ | 上下文推荐系统完全可复用 |
| **模板系统** | `html-template.md` | ★★☆☆☆ | HTML 模板无法直接用于 PPT，需重写 |
| **Token 体系** | design-tokens.json/css | ★★★☆☆ | 概念可复用，但 PPT 用 XML/主题格式表达 |

### 5.2 PPT 生成技术路线对比

| 方案 | 技术栈 | 优势 | 劣势 | 难度 |
|------|--------|------|------|------|
| **A. python-pptx** | Python 库直接生成 .pptx | 原生 PPT 格式；可编辑；支持母版/主题/动画 | 布局控制复杂；中文字体处理需注意；无实时预览 | ★★★☆☆ |
| **B. HTML→截图→插入** | HTML 渲染 + playwright 截图 + python-pptx | 视觉效果最好；复用现有 HTML 模板 | 依赖浏览器；生成慢；不可编辑文字 | ★★★★☆ |
| **C. HTML→Pandoc→PPTX** | Pandoc 转换 | 简单快速 | 布局控制弱；丢失大量样式 | ★★☆☆☆ |
| **D. Google Slides API** | 云端 API | 协作友好 | 需网络；需 Google 账号；复杂 | ★★★★☆ |
| **E. 纯 HTML 演示** | reveal.js / Slidev | 已有基础；跨平台 | 非 .pptx 格式；用户期望不符 | ★★☆☆☆ |

**推荐方案：A（python-pptx）**，理由：
1. 用户期望得到 .pptx 文件
2. 可编辑性是核心需求
3. 与现有 Python 技术栈一致
4. 社区成熟，文档完善

### 5.3 工作量拆解

#### Phase 1：数据层扩展（2-3 天，难度 ★★☆☆☆）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 新增 `ppt-layouts.csv` | 0.5 天 | PPT 布局定义（标题页/内容页/双栏/图片页等），可从 slide-layouts.csv 改造 |
| 新增 `ppt-themes.csv` | 0.5 天 | PPT 主题定义（配色/字体/母版映射），可从 colors.csv + typography.csv 提取 |
| 新增 `ppt-master-templates.csv` | 0.5 天 | 母版模板定义（占位符位置/大小/对齐），这是 PPT 独有的 |
| 扩展 `ui-reasoning.csv` | 0.5 天 | 新增 PPT 场景的推理规则 |
| 扩展 `CSV_CONFIG` | 0.5 天 | 在 core.py 中注册新域 |

#### Phase 2：PPT 生成引擎（5-7 天，难度 ★★★★☆）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 安装 python-pptx | 0.5 天 | `pip install python-pptx`，需更新 CLAUDE.md 的依赖说明 |
| 母版模板系统 | 2 天 | 设计 8-10 个母版布局（标题/内容/双栏/图片/图表/引用/CTA/空白），这是最核心的工作 |
| 主题映射 | 1 天 | 将 design system 的色板/字体映射到 PPT 主题 XML |
| 内容填充引擎 | 1.5 天 | 根据搜索结果自动选择母版 + 填充占位符 |
| 图表生成 | 1 天 | 将 charts.csv 推荐映射为 python-pptx 图表对象 |
| 动画/过渡 | 0.5 天 | PPT 切换动画 + 元素入场动画（python-pptx 支持有限） |
| 中文支持 | 0.5 天 | 字体回退链、文本编码处理 |

#### Phase 3：集成与工作流（3-4 天，难度 ★★★☆☆）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 新增 `--ppt` 模式 | 1 天 | 在 search.py 中新增 PPT 生成入口 |
| Pipeline 整合 | 1 天 | ui-ux-pro-max 设计系统 → PPT 主题/母版/内容的完整链路 |
| 上下文决策集成 | 1 天 | 将 slide_search_core.py 的上下文推荐接入 PPT 布局选择 |
| 持久化适配 | 0.5 天 | PPT 输出路径 + 设计系统 MASTER.md 同步 |
| SKILL.md 更新 | 0.5 天 | 新增 PPT 工作流文档 |

#### Phase 4：测试与优化（2-3 天，难度 ★★★☆☆）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 端到端测试 | 1 天 | 各类场景（融资/销售/产品/报告）的 PPT 生成测试 |
| 视觉调优 | 1 天 | 母版布局微调、间距/字号/配色在 PPT 中的实际效果 |
| 边界情况 | 0.5 天 | 长文本溢出、中文换行、图片比例、大数据图表 |
| 文档 | 0.5 天 | 使用说明 + 示例 |

### 5.4 总工作量估算

| 阶段 | 天数 | 难度 | 风险 |
|------|------|------|------|
| Phase 1: 数据层 | 2-3 天 | ★★☆☆☆ | 低 |
| Phase 2: PPT 引擎 | 5-7 天 | ★★★★☆ | **中高** — 母版设计是核心难点 |
| Phase 3: 集成 | 3-4 天 | ★★★☆☆ | 中 |
| Phase 4: 测试 | 2-3 天 | ★★★☆☆ | 中 |
| **合计** | **12-17 天** | | |

### 5.5 核心难点与风险

#### 难点 1：PPT 母版布局系统（风险 ★★★★☆）

python-pptx 的布局控制是**绝对定位**模式（英寸/厘米），不像 HTML 有 flexbox/grid 自动排版。需要：

- 手动计算每个占位符的精确位置和大小
- 处理不同内容长度下的自适应（文本溢出、图片比例）
- 设计 8-10 个覆盖常见场景的母版

**缓解方案：** 参考现有 slide-layouts.csv 的布局定义，建立一套"逻辑布局 → 物理坐标"的映射层。

#### 难点 2：设计系统 → PPT 主题映射（风险 ★★★☆☆）

PPT 主题系统（theme1.xml）有自己的色彩/字体体系，与 CSS 变量体系不同：

| CSS 概念 | PPT 概念 |
|----------|----------|
| `--color-primary` | `dk1` / `accent1` |
| `--color-background` | `bg1` / `bg2` |
| `--typography-font-heading` | `majorFont` |
| `--typography-font-body` | `minorFont` |

需要建立一套映射规则，将 ui-ux-pro-max 的 10 色语义色板映射到 PPT 的 12 色主题体系。

#### 难点 3：图表生成（风险 ★★★☆☆）

python-pptx 支持原生 PPT 图表（条形图/折线图/饼图等），但：
- 配置项不如 Chart.js 丰富
- 样式控制有限
- 需要将 charts.csv 的推荐映射为 python-pptx 图表对象

#### 难点 4：动画支持（风险 ★★☆☆☆）

python-pptx 对 PPT 动画的支持**非常有限**（基本只能设置切换动画），无法实现 GSAP 级别的精细动画。这是 PPT 格式的固有限制，不是代码问题。

### 5.6 与现有 slides skill 的关系

**建议策略：融合而非替代**

```
当前架构：
  ui-ux-pro-max (设计决策) ──→ design-system (Token + 幻灯片搜索) ──→ slides (HTML 幻灯片)

改造后架构：
  ui-ux-pro-max (设计决策) ──→ ppt-generator (新增，PPT 生成引擎)
                          ──→ design-system (Token + 幻灯片搜索) ──→ slides (HTML 幻灯片，保留)

  两者共享：
    - 搜索引擎 (core.py)
    - 设计系统生成 (design_system.py)
    - 上下文决策 (slide_search_core.py)
    - 数据库 (slide-*.csv + colors/typography/products 等)
```

**关键决策点：**

| 问题 | 选项 A | 选项 B | 推荐 |
|------|--------|--------|------|
| PPT skill 独立还是合并？ | 新建 `ppt-generator` skill | 扩展现有 `slides` skill | **A — 独立**，避免职责混淆 |
| 输出格式 | 仅 .pptx | .pptx + HTML 双输出 | **A — 仅 .pptx**，HTML 由 slides skill 负责 |
| python-pptx 依赖 | 作为可选依赖 | 作为必需依赖 | **A — 可选**，检测到时才启用 PPT 模式 |

### 5.7 最小可行产品（MVP）定义

如果要在最短时间内验证可行性，MVP 应包含：

1. **3 个母版布局**：标题页 / 内容页 / 结束页
2. **1 个主题映射**：将 design system 色板/字体映射到 PPT 主题
3. **1 个完整 Pipeline**：`search.py "SaaS pitch" --ppt` → 生成 5-8 页 .pptx
4. **基础文案填充**：标题/副标题/要点列表

**MVP 工作量：5-7 天**

---

## 六、总结

### 6.1 ui-ux-pro-max 的核心价值

1. **知识即代码**：5100+ 条结构化设计知识，可搜索、可推理、可版本控制
2. **推理而非搜索**：161 条决策规则让输出不是"搜索结果"而是"设计决策"
3. **可组合性**：12 个域 + 22 个栈 + 3 个拨盘，排列组合覆盖大量场景
4. **持久化**：Master + Overrides 模式让设计系统可跨会话演进

### 6.2 PPT 改造结论

| 维度 | 评估 |
|------|------|
| **可行性** | ★★★★☆ — 技术上完全可行，python-pptx 成熟 |
| **复用度** | ★★★★☆ — 70%+ 的现有代码/数据可直接复用 |
| **核心难点** | 母版布局系统（绝对定位 vs 自动排版） |
| **总工作量** | 12-17 天（完整版）/ 5-7 天（MVP） |
| **最大风险** | PPT 母版设计的视觉质量 — 需要大量微调 |
| **推荐策略** | 先做 MVP 验证，再逐步扩展母版和功能 |
