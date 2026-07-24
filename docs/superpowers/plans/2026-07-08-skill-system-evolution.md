# Skill System Evolution: 迁移、通用数据管道、职责边界与Agent通用化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 Skill 零改动上线，所有 Skill 被正确触发，任意 Skill 的数据被正确消费——不依赖 Skill 的配合，不修改下游 Agent。

**Architecture:** 三个核心改动：(1) 完成所有 Skill 的 SKILL.md 迁移 + ManifestDrivenStrategy 替换硬编码路由表；(2) 在 Agent 的 `_fetch_structured_data()` 基础上构建通用数据管道 `_process_skill_output()`，用三层内容转换（Skill自带content → Skill.format_data() → LLM总结）处理任意未知数据结构，不需要 Skill 配合；(3) 明确 Skill 的多种输出类型与消费方式，Agent 根据上下文选择合适的消费策略。

**Tech Stack:** python-frontmatter, pyyaml, importlib, pytest

---

## 核心设计论证

### 论证1：为什么不用 Data Contract

**Data Contract 方案**要求每个 Skill 在 SKILL.md 中声明 `data_contract`，将原生字段映射到标准字段。这个方案有三个致命问题：

1. **第三方 Skill 无法配合**：用户加载的通用 Skill 不会实现我们的基类，不会写 data_contract，返回什么完全不可控。
2. **标准字段本身不可穷举**：财务数据可以定义标准字段（revenue/net_income/eps），但一个 UI 设计 Skill 返回什么？"palette"? "color_scheme"? "font_config"? 无法预先定义所有域的标准字段。
3. **维护成本随 Skill 数量线性增长**：每个新 Skill 都要写 data_contract，每加一个同类 Skill 都要确保字段映射与已有 Skill 一致。这违反"零改动上线"的目标。

**正确做法**：Agent 端通用数据管道。Agent 不假设 Skill 返回什么结构，而是用三层策略将任意数据转为下游可消费的 `content` 字符串 + `canonical_metrics` 数值。这个转换只发生在一个地方（`_process_skill_output()`），下游 Agent 完全不感知 Skill 的数据结构。

> **隐含假设与风险**：L3 LLM 总结的质量替代结构化字段映射的前提是摘要能保留关键数值。对于 `structured_db` 类 Skill（如 stock_data、xueqiu），L2 `format_data()` 是**必需**而非可选——它们必须实现精确的数值格式化。L3 仅作为第三方未知 Skill 的兜底，且摘要字数应根据数据量动态调整（见 Task 3.1 实现细节）。

### 论证2：为什么三层转换足够

看下游 Agent 如何消费数据：

```
DEEP_ANALYSIS Agent:
  aggregated_data_points → 拼进 LLM prompt → call_llm()
  LLM 读的是 content 字符串，不关心原始 JSON 结构

SYNTHESIS / REPORT Agent:
  同上，只读 content

SharedMemory:
  写入 canonical_metrics（数值型），提取自 _extract_numeric_metrics()
  这个方法已经通用——递归提取所有数值字段，不需要知道字段名含义
```

所以下游消费只有两种形式：(1) **content 字符串** 喂给 LLM，(2) **canonical_metrics 数值** 写入 SharedMemory。只要通用管道能把任意数据转为这两种形式，就不需要 Data Contract。

三层转换：

| 层 | 机制 | 适用场景 | 速度 | 需要Skill配合 |
|---|------|---------|------|:---:|
| L1 | `skill_result.get("content")` | Skill 自带可读文本（任何 Skill 都能返回 content 字段） | 0ms | 否 |
| L2 | `skill.format_data()` | 我们自己开发的 Skill，**structured_db 类必需** | 0ms | 可选（但 structured_db 类必需） |
| L3 | LLM 总结 | 任意第三方 Skill，数据结构完全未知 | ~1s | 否 |
| 兜底 | `json.dumps(data)` | 所有层都失败 | 0ms | 否 |

### 论证3：为什么通用管道只需要改一个地方

当前 DATA_COLLECTION 阶段调用 Skill 的代码分散在三处（均为调用点，非方法定义）：

```
generic_agent.py:470-499  → Tier 1: structured_db → _fetch_structured_data()（方法定义在2313行）
generic_agent.py:521-541  → Tier 2: search_skill → _do_deep_research()（方法定义在2895行） → 手动拼 data_points
generic_agent.py:544-576  → Tier 2: news_search → news_skill.execute() → 手动拼 data_points
```

三处代码做的是**同一件事**：调用 Skill → 转换输出 → 存入 data_points。只是因为每种 Skill 的输出结构不同，各自硬编码了不同的转换逻辑。

通用管道将三处合并为一个方法 `_process_skill_output()`。**改这一个方法，所有 Skill 的数据都走同一条路径。** 下游 Agent 不需要改动，因为它们本来就只读 `data_points` 里的 `content` 字符串。

> **B-FIX-3 逻辑保留**：当前 Tier 2 web_search 之后有一段 B-FIX-3 逻辑（generic_agent.py:578-611），用正则从 `data_points` 的 `content` 中提取数值写入 SharedMemory。这段跨 Tier 的数据后处理逻辑**不属于任何单个 Skill**，必须保留在统一循环中。见 Task 3.2 重构代码。

### 论证4：Symbol 解析的通用化

当前 `_fetch_structured_data()` 中有一大段 symbol 解析逻辑（方法定义在 2313-2368 行）：

```
entities → _extract_stock_symbol → _resolve_company_to_code → manifest.resolve_identifier
```

这段逻辑对财务类 Skill 有意义（需要股票代码），但对一个 UI 设计 Skill 无意义（不需要 symbol）。通用化后：

- 有 `action_rules` 和 `action_param_map` 的 Skill → 通过 manifest 构建参数（可能包含 symbol，也可能不包含）
- 没有 manifest 的 Skill → 直接 `skill.execute(action="default")`
- symbol 解析只在 Skill 需要 symbol 参数时才执行

> **并发安全注意**：当前代码通过 `skill._manifest = manifest` 临时修改 Skill 实例属性（2359行、2375行）。如果未来多 Agent 并发执行，同一个 Skill 实例的 `_manifest` 会被覆盖。`_resolve_identifiers()` 和 `_infer_actions_from_manifest()` 中应避免修改实例属性，改用局部变量传参。见 Task 3.1 实现中的修复。

### 论证5：Skill 的多种输出类型与消费方式

**"Skill 只输出数据"是错误的。** 实际系统中 Skill 至少有 5 种输出类型：

| 输出类型 | 代表 Skill | execute() 返回什么 | 下游如何消费 |
|---------|-----------|-------------------|------------|
| **结构化数据** | stock_data, xueqiu | `{data: {income_statement: [...], ...}}` | `_process_skill_output()` → 三层转换 → `data_points[].content` |
| **搜索结果** | search_skill, news_search | `{results: [{title, body, href}, ...]}` | `_process_search_skill()` → 拆为 `data_points[]` |
| **文件产物** | docx_skill | `{filepath: "/tmp/report.docx"}` | Agent 直接读取 filepath，不走数据管道 |
| **指令/知识** | knowledge_query, InstructionSkill | `{data: {instructions: "..."}, content: "..."}` | L1 content 直接命中，或 L2 format_data |
| **业务流程** | survey_skill, persona_skill, simulation_skill | `{survey_id: "xxx", status: "created"}` | Agent 根据返回的 ID/状态编排后续步骤 |

**关键洞察**：通用数据管道 `_process_skill_output()` 只处理**数据类 Skill**（structured_db / web_search）。文件产物类和业务流程类 Skill 的输出不适合走三层转换——它们的消费方式完全不同：

- **docx_skill**：Agent 调用 `generate_docx` action，拿到 filepath，后续模块直接操作文件。走数据管道会把 filepath 转成 content 字符串，毫无意义。
- **survey_skill**：Agent 调用 `create` action，拿到 survey_id，后续用 `distribute`/`get_results` 编排流程。走数据管道会把 survey_id 转成 content，丢失结构。
- **InstructionSkill**：纯文本指令，L1 content 直接命中，不需要 L2/L3。

**设计原则**：`_process_skill_output()` 的三层转换是**数据类 Skill 的消费策略**，不是所有 Skill 的通用消费策略。Agent 应根据 Skill 的 `priority` 和 `categories` 选择消费方式：

```
priority=structured_db / web_search → _process_skill_output() 三层转换
priority=llm + categories 含 file-operation → 直接消费返回值（filepath 等）
skill_type=langchain → 直接消费返回值
其他 → _process_skill_output() 兜底（L1/L3 处理）
```

> **与 Phase 5 职责边界的关系**：Phase 5 的 ArtifactService 是为文件产物类 Skill 设计的（ui_design 输出主题配置 → ArtifactService 存储 → html_to_ppt 消费）。但当前系统中 docx_skill 已经直接返回 filepath，不需要 ArtifactService 中转。ArtifactService 的价值在于让**未来的** Skill（如 ui_design）的产出物可被多个模块共享消费，而非替代现有的 filepath 返回模式。

---

## Phase 1: 完成 Skill 迁移到目录 + SKILL.md

### Task 1.1: 迁移 search_skill (SearchSkill + NewsSearchSkill)

**Files:**
- Create: `src/skills/search/SKILL.md`
- Create: `src/skills/search/skill.py`
- Create: `src/skills/news_search/SKILL.md`
- Create: `src/skills/news_search/skill.py`
- Test: `tests/unit/skills/test_skill_migration_search.py`

search SKILL.md:

```markdown
---
name: search_skill
description: "多搜索引擎集成 (Baidu/DuckDuckGo/Google/Bing 等6引擎)"
version: "1.0"
categories:
  - data-collection
  - web-search
priority: web_search
keywords:
  - 搜索
  - 搜索引擎
  - web search
  - search
  - 百度
  - 必应
  - 谷歌
aliases:
  - web_search
capabilities:
  - search
action_rules:
  - pattern: ".*"
    actions: [search]
action_param_map:
  search: {query: query}
supports_topic_fallback: false
is_intrinsic: false
skill_type: standard
aspect_coverage: []
---
```

news_search SKILL.md:

```markdown
---
name: news_search
description: "新闻搜索 (DuckDuckGo News)"
version: "1.0"
categories:
  - data-collection
  - web-search
priority: web_search
keywords:
  - 新闻
  - 新闻搜索
  - news
  - news search
capabilities:
  - search
action_rules:
  - pattern: ".*"
    actions: [search]
action_param_map:
  search: {query: query}
supports_topic_fallback: false
is_intrinsic: false
skill_type: standard
aspect_coverage: []
---
```

skill.py 示例（re-export wrapper）:

`src/skills/search/skill.py`:
```python
from src.skills.search_skill import SearchSkill

__all__ = ["SearchSkill"]
```

`src/skills/news_search/skill.py`:
```python
from src.skills.search_skill import NewsSearchSkill

__all__ = ["NewsSearchSkill"]
```

- [ ] **Step 1:** Create `src/skills/search/` and `src/skills/news_search/` directories
- [ ] **Step 2:** Create SKILL.md files for both
- [ ] **Step 3:** Create skill.py re-export wrappers for both
- [ ] **Step 4:** Write discovery test

```python
def test_discovery_finds_search_skills(tmp_path):
    from src.skills.discovery import SkillDiscovery
    from pathlib import Path
    d = SkillDiscovery()
    manifests = d.discover_all(Path("src/skills"))
    names = [m.name for m in manifests]
    assert "search_skill" in names
    assert "news_search" in names
```

- [ ] **Step 5:** Run test, verify pass
- [ ] **Step 6:** Commit

### Task 1.2: 迁移 file_skill, http_skill, docx_skill, web_scraper

Same pattern as Task 1.1.

**Files:**
- Create: `src/skills/file/SKILL.md`, `src/skills/file/skill.py`
- Create: `src/skills/http/SKILL.md`, `src/skills/http/skill.py`
- Create: `src/skills/docx/SKILL.md`, `src/skills/docx/skill.py`
- Create: `src/skills/web_scraper/SKILL.md`, `src/skills/web_scraper/skill.py`

关键 SKILL.md 字段：

- `file_skill`: categories=[file-operation], priority=llm, capabilities=[read, write, list, delete]
- `http_skill`: categories=[network], priority=llm, capabilities=[get, post, put, delete]
- `docx_skill`: categories=[document-generation], priority=llm, capabilities=[generate_docx]
- `web_scraper`: categories=[data-collection, web-search], priority=web_search, capabilities=[scrape]

- [ ] **Step 1:** Create all 4 directories with SKILL.md and skill.py
- [ ] **Step 2:** Write discovery test for all 4
- [ ] **Step 3:** Run test, commit

### Task 1.3a: 修复 `base.py:infer_actions()` 为累加匹配模式（前置条件）

**前置条件**：Task 1.3 的 stock_data action_rules 依赖累加语义

**Files:**
- Modify: `src/skills/base.py` — 修改 `infer_actions()` 方法
- Modify: `src/core/agents/generic_agent.py` — 修改 `_infer_actions_from_manifest()` fallback 逻辑

当前 `base.py:infer_actions()` (94-106行) 遇到第一个匹配的 rule 就 return，是**排他匹配**。但 `_infer_stock_actions()` (2734-2759行) 是**累加匹配**——多个关键词组可同时匹配，actions 累加后去重。

修改为累加模式：

```python
# base.py
def infer_actions(self, aspect: str, symbol: str) -> List[str]:
    manifest = getattr(self, '_manifest', None)
    if manifest and manifest.action_rules:
        all_actions = []
        matched = False
        for rule in manifest.action_rules:
            if not re.match(rule.pattern, symbol):
                continue
            if rule.aspect_keywords:
                aspect_lower = (aspect or "").lower()
                if any(kw.lower() in aspect_lower for kw in rule.aspect_keywords):
                    all_actions.extend(rule.actions)
                    matched = True
                continue
            # 无 aspect_keywords 的 rule 作为默认兜底，只在无其他匹配时使用
            if not matched:
                return rule.actions
        if matched:
            return list(dict.fromkeys(all_actions))
    return ["default"]
```

同步修改 `_infer_actions_from_manifest()` 的 fallback 逻辑（Task 3.1 中的实现），也采用累加模式。

- [ ] **Step 1:** 修改 `base.py:infer_actions()` 为累加模式
- [ ] **Step 2:** 写测试验证累加行为：aspect="盈利估值分析" 同时返回 `["financials", "key_metrics"]`
- [ ] **Step 3:** Run existing tests, ensure no regression
- [ ] **Step 4:** Commit

### Task 1.3: 迁移 7 个分析 Skill

**Files:**
- Create: `src/skills/stock_data/SKILL.md`, `src/skills/stock_data/skill.py`
- Create: `src/skills/stock_analysis/SKILL.md`, `src/skills/stock_analysis/skill.py`
- Create: `src/skills/market_analysis/SKILL.md`, `src/skills/market_analysis/skill.py`
- Create: `src/skills/data_analysis/SKILL.md`, `src/skills/data_analysis/skill.py`
- Create: `src/skills/policy_analysis/SKILL.md`, `src/skills/policy_analysis/skill.py`
- Create: `src/skills/tech_trend/SKILL.md`, `src/skills/tech_trend/skill.py`
- Create: `src/skills/risk_analysis/SKILL.md`, `src/skills/risk_analysis/skill.py`

> **⚠️ xueqiu SKILL.md 已存在**：`src/skills/xueqiu/SKILL.md` 已经是完整的 SKILL.md（127 行），包含 action_rules、action_param_map、aspect_coverage 等所有字段。不需要重新创建，只需验证其与代码的一致性（见下方 xueqiu 验证清单）。但 xueqiu 的 SKILL.md 遗漏了 `user_posts` capability（代码支持 8 个 action，SKILL.md 只列了 7 个），需要补充。

**stock_data 的 SKILL.md 必须包含完整的 action_rules**，这是消灭 `_infer_stock_actions()` 的前提。action_rules 直接从 `_infer_stock_actions()` 的关键词匹配逻辑翻译而来：

> **⚠️ 功能变更说明**：当前 `ASPECT_SKILL_MAP` 中不包含 `stock_data`（Financial Analysis 只映射到 stock_analysis + data_analysis）。给 stock_data 设置 `aspect_coverage` 后，ManifestStrategyBuilder 会将 stock_data 也加入对应 aspect 的 Skill 列表。这是**有意的行为变更**：让 stock_data 参与 DEEP_ANALYSIS 阶段的数据获取，不再仅通过 DATA_SOURCE_SKILL_MAP 间接发现。**同理，xueqiu 的 SKILL.md 已有 `aspect_coverage`（Financial Analysis/Valuation/Company Research 等），而 `ASPECT_SKILL_MAP` 中也没有 xueqiu**。ManifestStrategyBuilder 会将 xueqiu 也加入这些 aspect，这也是行为变更——xueqiu 将同时出现在 DEEP_ANALYSIS 和 DATA_COLLECTION 阶段的 Skill 列表中。

```markdown
---
name: stock_data
description: "A股上市公司财务数据 (akshare 实时数据): 财务报表/股价/公司信息"
version: "1.0"
categories:
  - financial-analysis
  - data-collection
  - research
priority: structured_db
keywords:
  - 股票数据
  - 财务数据
  - akshare
  - 利润表
  - 资产负债表
  - 现金流量表
  - stock data
  - financial data
aliases: []
capabilities:
  - company_info
  - financials
  - key_metrics
  - price_history
  - industry_comparison
action_rules:
  - pattern: ".*"
    aspect_keywords: [盈利, 利润, 营收, 收入, 研发, 技术, 创新, 偿债, 现金流, 运营效率, financial]
    actions: [financials]
  - pattern: ".*"
    aspect_keywords: [估值, 价值, pe, pb, 回报, roe, roa, roic, 投资价值, valuation]
    actions: [key_metrics, financials]
  - pattern: ".*"
    aspect_keywords: [杠杆, 负债, 资本结构, 稳健, leverage]
    actions: [financials]
  - pattern: ".*"
    aspect_keywords: [对比, 竞争, industry]
    actions: [industry_comparison]
  - pattern: ".*"
    aspect_keywords: [增长, 增速, 发展, 成长性, growth]
    actions: [financials, key_metrics]
  - pattern: ".*"
    aspect_keywords: [销售, 渠道, 营收分析, sales]
    actions: [financials]
  - pattern: ".*"
    aspect_keywords: [市场份额, 市占率, market share]
    actions: [industry_comparison]
  - pattern: ".*"
    aspect_keywords: [公司, 企业, company]
    actions: [company_info, financials]
  - pattern: ".*"
    aspect_keywords: [股价, 行情, 走势, 市值变动, price, market_cap]
    actions: [price_history]
  - pattern: ".*"
    actions: [company_info, financials]
action_param_map:
  company_info: {symbol: symbol}
  financials: {symbol: symbol}
  key_metrics: {symbol: symbol}
  price_history: {symbol: symbol}
  industry_comparison: {symbol: symbol}
supports_topic_fallback: false
is_intrinsic: false
skill_type: standard
data_source_keywords:
  - 财务
  - 估值
  - 公司
  - 盈利
  - 营收
  - 市值
  - 市场规模
  - 利润
  - 资产负债
  - roe
  - pe
  - pb
  - 增长
  - 投资
aspect_coverage:
  - Financial Analysis
  - 财务分析
  - Valuation Analysis
  - 估值分析
  - Company Analysis
  - 公司分析
  - Investment Advice
  - 投资建议
  - Growth Analysis
  - 增长分析
  - Sales Analysis
  - 销售分析
---
```

> **action_rules 修正说明**：相比原始 `_infer_stock_actions()` (generic_agent.py:2734-2759)，补充了 `技术` 和 `创新` 关键词（原代码 2737 行有 `"技术", "创新"`），补充了 `回报` 关键词（原代码 2739 行有 `"回报"`），以及 `资产负债` data_source_keyword（对应 DATA_SOURCE_SKILL_MAP 中的 `"资产负债": ["stock_data"]` 条目，当前文档遗漏了此项）。

> **⚠️ 语义差异风险：action_rules 是排他匹配，`_infer_stock_actions()` 是累加匹配**。当前 `base.py:infer_actions()` (94-106行) 遇到第一个匹配的 rule 就 return，而 `_infer_stock_actions()` 对每个关键词组独立判断，actions 累加后去重。例如 aspect="盈利估值分析" 时：
> - `_infer_stock_actions()`: 匹配"盈利"→`["financials"]`，匹配"估值"→`["key_metrics", "financials"]`，最终=`["financials", "key_metrics"]`
> - `infer_actions()` with action_rules: 匹配第一个 rule（盈利...）→ return `["financials"]`，**丢失 `key_metrics`**
> 
> **修复方案**：修改 `base.py:infer_actions()` 为累加模式——遍历所有 rule，将匹配的 actions 累加到列表，最后去重返回。同时在 `_infer_actions_from_manifest()` 的 fallback 逻辑中也采用累加模式。实现如下：
> ```python
> def infer_actions(self, aspect: str, symbol: str) -> List[str]:
>     manifest = getattr(self, '_manifest', None)
>     if manifest and manifest.action_rules:
>         all_actions = []
>         matched = False
>         for rule in manifest.action_rules:
>             if not re.match(rule.pattern, symbol):
>                 continue
>             if rule.aspect_keywords:
>                 aspect_lower = (aspect or "").lower()
>                 if any(kw.lower() in aspect_lower for kw in rule.aspect_keywords):
>                     all_actions.extend(rule.actions)
>                     matched = True
>                 continue
>             # 无 aspect_keywords 的 rule 作为默认兜底，只在无其他匹配时使用
>             if not matched:
>                 return rule.actions
>         if matched:
>             return list(dict.fromkeys(all_actions))
>     return ["default"]
> ```
> 此修改必须在 Task 1.3 之前完成（Task 1.3 的 action_rules 依赖累加语义才能正确工作）。

其余 6 个分析 Skill 的 aspect_coverage 直接从 `strategies.py:ASPECT_SKILL_MAP` 当前硬编码翻译：

| Skill | aspect_coverage (从 ASPECT_SKILL_MAP 翻译) |
|-------|-------------------------------------------|
| stock_analysis | Financial Analysis, Valuation Analysis, Investment Advice, Company Analysis |
| market_analysis | Competitive Landscape, Industry Chain, Strategic Intent, 战略意图, 战略意图推断 |
| data_analysis | Market Size, Market Share, Industry Trends, Development Trends, User Analysis, Regional Distribution, Growth Analysis, Sales Analysis, Data Comparison |
| policy_analysis | Policy Environment |
| tech_trend | Technology Trends |
| risk_analysis | Risk Analysis |

> **注意**：`market_analysis` 的 aspect_coverage 包含中文条目 `战略意图` 和 `战略意图推断`，因为当前 `ASPECT_SKILL_MAP` 中这两个键映射到 `["market_analysis"]`。

- [ ] **Step 1:** Create stock_data/SKILL.md with full action_rules (above)
- [ ] **Step 2:** Create the other 6 SKILL.md files with aspect_coverage from ASPECT_SKILL_MAP
- [ ] **Step 3:** Create skill.py re-export wrappers for all 7
- [ ] **Step 4:** Write discovery test verifying all 7 are found with correct manifests
- [ ] **Step 5:** Write parity test: ManifestStrategyBuilder output matches current hardcoded maps

```python
def test_manifest_strategy_matches_hardcoded_aspect_map():
    from src.skills.discovery import SkillDiscovery
    from src.core.decomposition.manifest_strategy import ManifestStrategyBuilder
    from src.core.decomposition.strategies import ASPECT_SKILL_MAP
    from pathlib import Path
    d = SkillDiscovery()
    manifests = {m.name: m for m in d.discover_all(Path("src/skills"))}
    builder = ManifestStrategyBuilder(manifests)
    manifest_map = builder.build_aspect_skill_map()
    for aspect, expected_skills in ASPECT_SKILL_MAP.items():
        if aspect in manifest_map:
            # manifest_map 可能包含比硬编码更多的 Skill（如 stock_data），
            # 只验证硬编码中的 Skill 仍然存在，不要求完全一致
            for expected_skill in expected_skills:
                assert expected_skill in manifest_map[aspect], \
                    f"aspect={aspect}: expected '{expected_skill}' in manifest_map but got {manifest_map[aspect]}"
```

- [ ] **Step 6:** Run tests, fix any mismatches, commit

### Task 1.4: 迁移 annual_report_parser, knowledge_query

- [ ] **Step 1:** Create annual_report_parser/SKILL.md + skill.py
- [ ] **Step 2:** Create knowledge_query/SKILL.md + skill.py
- [ ] **Step 3:** Write test, run, commit

### Task 1.5: 创建 LangChain Skill 的 SKILL.md (无 skill.py)

LangChain Skill 用 `skill_type: langchain`，registry 用已有的 `_create_*_skill()` 方法，不需要 skill.py。

```markdown
---
name: lc_tavily_search
description: "Tavily 实时网络搜索"
version: "1.0"
categories:
  - data-collection
  - web-search
priority: web_search
keywords:
  - tavily
  - web search
  - search
  - 搜索
capabilities:
  - search
action_rules:
  - pattern: ".*"
    actions: [search]
action_param_map:
  search: {query: query}
is_intrinsic: false
skill_type: langchain
---
```

- [ ] **Step 1:** Create lc_tavily_search/SKILL.md, lc_arxiv/SKILL.md, lc_wikipedia/SKILL.md, lc_python_repl/SKILL.md
- [ ] **Step 2:** Verify registry.init_from_discovery() handles skill_type=langchain correctly (it already does in current code — `if manifest.skill_type == "langchain": continue`).**关键：** SKILL.md 的 `name` 字段必须与 `auto_discover_langchain_tools()` 注册的 Skill 实例名称一致（`lc_` 前缀），否则 `get_manifest()` 无法匹配。
- [ ] **Step 2a:** ⚠️ **LangChain manifest 双重注册问题**：当前 `init_from_discovery()` 在 `continue` 之前已经调用了 `register_manifest(manifest)`（592 行），而 `auto_discover_langchain_tools()` 内部也会调用 `register_manifest()`。导致 langchain manifest 被注册两次。修复：在 `init_from_discovery()` 中，`skill_type == "langchain"` 时也应 `continue` **跳过 manifest 注册**，让 `auto_discover_langchain_tools()` 统一负责注册。
- [ ] **Step 3:** Write test, commit

### Task 1.6: 创建 llm/SKILL.md (纯指令型)

- [ ] **Step 1:** Create llm/SKILL.md with `is_intrinsic: true`, no skill.py

```markdown
---
name: llm
description: "内在LLM能力 (call_llm)，非外部Skill"
version: "1.0"
categories:
  - intrinsic
priority: llm
keywords: []
aliases: []
capabilities: []
is_intrinsic: true
skill_type: standard
---
```

- [ ] **Step 2:** Write test, commit

### Task 1.7: 移除 orchestrator.py 中的手动注册

**Files:**
- Modify: `src/core/orchestrator/orchestrator.py:272-298`

当前 orchestrator.py 先手动 `register_core_skills()` + `register_factory()` 7 个分析 Skill，再调用 `init_from_discovery()`。迁移完成后 `init_from_discovery()` 覆盖所有 Skill 的注册。

**关键验证**：`init_from_discovery()` 必须能注册 `register_core_skills()` 当前注册的所有 Skill。逐项核对：

| Skill | register_core_skills | init_from_discovery |
|-------|:--------------------:|:-------------------:|
| search_skill | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| web_search (alias) | ✅ 手动注册 | ✅ search SKILL.md aliases |
| news_search | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| file_skill | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| http_skill | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| docx_skill | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| web_scraper | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| knowledge_query | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| annual_report_parser | ✅ 手动注册 | ✅ SKILL.md + skill.py |
| 7个分析Skill | ✅ register_factory | ✅ SKILL.md + skill.py |
| LangChain Skills | ✅ auto_discover | ✅ SKILL.md (langchain type) |

**但 web_search 是 search_skill 的别名**——当前 `register_core_skills()` 注册两个独立 SearchSkill **实例**（registry.py:296-301）。`init_from_discovery()` 只注册 `search_skill`。需要确保 `search_skill` 的 SKILL.md 中 `aliases: [web_search]` 被正确处理。

当前 `init_from_discovery()` 不处理 aliases。需要补充：

> **⚠️ 并发安全与实例共享问题**：当前 `register_core_skills()` 注册 `search_skill` 和 `web_search` 为**两个独立的 SearchSkill 实例**。如果用工厂注册 alias，`get("web_search")` 会创建一个新实例，与 `get("search_skill")` 的实例不共享状态。正确做法是让 alias 指向**同一个已创建的实例**，而非同一个工厂函数。虽然当前 SearchSkill 没有 `_memory_cache` 等实例状态，但未来添加缓存等状态时，实例不共享会导致数据不一致。

```python
# 在 init_from_discovery() 中，注册完 manifest 和 factory 后处理 aliases
for manifest in manifests:
    self.register_manifest(manifest)
    # ... 现有注册逻辑 ...

# 新增：处理 aliases — 确保指向同一实例
for manifest in manifests:
    for alias in manifest.aliases:
        if alias in self._skills or alias in self._factories:
            continue
        # 优先复用已创建的实例，避免状态不共享
        if manifest.name in self._skills:
            self._skills[alias] = self._skills[manifest.name]
        elif manifest.name in self._factories:
            # 用闭包确保 alias 的 get() 返回与原名相同的实例
            # 关键：闭包必须通过 self._skills[name] 获取已创建的实例，
            # 而非调用 _factory() 创建新实例
            original_name = manifest.name
            def _alias_factory(_name=original_name):
                existing = self._skills.get(_name)
                if existing:
                    return existing
                # 首次调用：通过原名 factory 创建实例，存入 _skills
                original_factory = self._factories.get(_name)
                if original_factory:
                    instance = original_factory()
                    self._skills[_name] = instance
                    return instance
                return None
            self._factories[alias] = _alias_factory
```

- [ ] **Step 1:** 在 `registry.init_from_discovery()` 中添加 aliases 注册逻辑（注意实例共享）
- [ ] **Step 2:** 验证 `registry.get("web_search")` 和 `registry.get("search_skill")` 返回**同一个** SearchSkill 实例（`is` 比较）
- [ ] **Step 3:** 移除 orchestrator.py:276-292 的手动 register_factory
- [ ] **Step 4:** 保留 `register_core_skills()` 调用但内部清空，逐步废弃（向后兼容）
- [ ] **Step 5:** 运行全量测试
- [ ] **Step 6:** Commit

---

## Phase 2: ManifestDrivenStrategy（替换硬编码路由表）

### Task 2.1: 创建 ManifestStrategyBuilder

**Files:**
- Create: `src/core/decomposition/manifest_strategy.py`
- Test: `tests/unit/core/test_manifest_strategy.py`

> **设计决策：复用 SkillRegistries vs 新建 ManifestStrategyBuilder**。`discovery.py:SkillRegistries` 已经实现了 category_map、priority_map、keywords_map、alias_map、capabilities_map、data_source_skill_map、structured_data_capabilities、aspect_skill_map 的构建逻辑（discovery.py:148-212）。`ManifestStrategyBuilder` 本质上是 `SkillRegistries` 的超集，额外提供了 `get_skills_for_aspect()`、`get_data_collection_skills()`、`build_action_to_skill_map()`。建议 `ManifestStrategyBuilder` 内部持有 `SkillRegistries` 实例，复用其构建结果，避免重复实现 map 构建逻辑。

```python
class ManifestStrategyBuilder:
    """从 SkillManifest 动态构建策略映射，替代 strategies.py 中的硬编码 dict。
    
    内部复用 SkillRegistries 的构建结果，额外提供业务方法。
    """

    def __init__(self, manifests: Dict[str, 'SkillManifest']):
        self._manifests = manifests
        from src.skills.discovery import SkillDiscovery
        discovery = SkillDiscovery()
        self._registries = discovery.build_registries(list(manifests.values()))

    def build_aspect_skill_map(self) -> Dict[str, List[str]]:
        """替代 ASPECT_SKILL_MAP"""
        return self._registries.aspect_skill_map

    def build_skill_priority_map(self) -> Dict[str, str]:
        """替代 SKILL_PRIORITY_MAP"""
        return self._registries.priority_map

    def build_data_source_skill_map(self) -> Dict[str, List[str]]:
        """替代 DATA_SOURCE_SKILL_MAP"""
        return self._registries.data_source_skill_map

    def build_structured_data_capabilities(self) -> Dict[str, Dict[str, List[str]]]:
        """替代 STRUCTURED_DATA_CAPABILITIES"""
        return self._registries.structured_data_capabilities

    def build_action_to_skill_map(self) -> Dict[str, Optional[str]]:
        """替代 generic_agent.py 中的 ACTION_TO_SKILL。
        从 manifest.capabilities 反向构建 action→skill 映射。
        LLM 内在能力映射为 None。
        
        ⚠️ capabilities_map 的覆盖问题：discovery.py:_build_capabilities_map() 
        中，当多个 Skill 有相同 capability 时，后遍历的会覆盖先遍历的。
        例如 search_skill 和 news_search 都有 capability "search"，
        遍历顺序取决于 sorted(dir.iterdir())，news_search 会覆盖 search_skill。
        因此显式覆盖（下面的 result["search"] = "search_skill"）是必需的，
        不能依赖 capabilities_map 的自动构建。"""
        intrinsic_actions = {
            "llm": None, "analyze": None, "analysis": None,
            "reasoning": None, "summarize": None, "translate": None,
            "research": None, "data_collection": None,
            "calibration": None, "execute": None,
        }
        result = dict(intrinsic_actions)
        # 复用 SkillRegistries.capabilities_map
        for cap, skill_name in self._registries.capabilities_map.items():
            if cap not in result:
                result[cap] = skill_name
        return result

    def get_skills_for_aspect(self, aspect: str) -> List[str]:
        """替代 get_skills_for_aspect()"""
        aspect_map = self.build_aspect_skill_map()
        if aspect in aspect_map:
            return aspect_map[aspect]
        for key, skills in aspect_map.items():
            if key in aspect:
                return skills
        return []

    def get_data_collection_skills(self, aspect: str, topic: str = "",
                                    intent_result: Any = None) -> List[str]:
        """替代 _get_data_collection_skills()"""
        db_skills = []
        web_skills = []
        base_skills = ["search_skill", "news_search"]
        aspect_skills = []
        ds_map = self.build_data_source_skill_map()
        priority_map = self.build_skill_priority_map()
        aspect_lower = aspect.lower()
        for keyword, extra_skills in ds_map.items():
            if keyword in aspect_lower:
                aspect_skills.extend(extra_skills)
        if intent_result:
            primary_type = getattr(intent_result, 'primary_research_type', None)
            if primary_type and getattr(primary_type, 'value', '') in (
                "company_research", "investment", "competitive_analysis",
                "industry_research", "brand_research",
            ):
                for name, m in self._manifests.items():
                    if m.priority == "structured_db" and name not in aspect_skills:
                        aspect_skills.append(name)
        all_unique = list(dict.fromkeys(aspect_skills + base_skills))
        for skill in all_unique:
            tier = priority_map.get(skill, "web_search")
            if tier == "structured_db":
                db_skills.append(skill)
            else:
                web_skills.append(skill)
        return db_skills + web_skills
```

- [ ] **Step 1:** Create `src/core/decomposition/manifest_strategy.py`
- [ ] **Step 2:** Write parity test comparing builder output with current hardcoded maps

```python
def test_builder_matches_hardcoded_maps():
    from src.skills.discovery import SkillDiscovery
    from src.core.decomposition.manifest_strategy import ManifestStrategyBuilder
    from src.core.decomposition.strategies import (
        ASPECT_SKILL_MAP, SKILL_PRIORITY_MAP,
        DATA_SOURCE_SKILL_MAP, STRUCTURED_DATA_CAPABILITIES,
    )
    from pathlib import Path
    d = SkillDiscovery()
    manifests = {m.name: m for m in d.discover_all(Path("src/skills"))}
    builder = ManifestStrategyBuilder(manifests)

    # Aspect map: manifest_map 可能包含更多 Skill（如 stock_data），
    # 只验证硬编码中的 Skill 仍存在于对应 aspect
    manifest_aspects = builder.build_aspect_skill_map()
    for aspect, expected in ASPECT_SKILL_MAP.items():
        if aspect in manifest_aspects:
            for skill in expected:
                assert skill in manifest_aspects[aspect], \
                    f"ASPECT_SKILL_MAP mismatch for '{aspect}': expected '{skill}' missing"

    # Priority map
    manifest_priority = builder.build_skill_priority_map()
    for skill, expected_tier in SKILL_PRIORITY_MAP.items():
        if skill in manifest_priority:
            assert manifest_priority[skill] == expected_tier, \
                f"SKILL_PRIORITY_MAP mismatch for '{skill}'"

    # Data source map
    manifest_ds = builder.build_data_source_skill_map()
    for keyword, expected_skills in DATA_SOURCE_SKILL_MAP.items():
        if keyword in manifest_ds:
            for skill in expected_skills:
                assert skill in manifest_ds[keyword], \
                    f"DATA_SOURCE_SKILL_MAP mismatch for '{keyword}': expected '{skill}' missing"
```

- [ ] **Step 3:** Run test, fix mismatches, commit

### Task 2.2: 将 ManifestStrategyBuilder 接入 strategies.py

**Files:**
- Modify: `src/core/decomposition/strategies.py`
- Modify: `src/core/orchestrator/orchestrator.py`

策略：保留现有硬编码 dict 作为 fallback，新增 `_manifest_strategy` 类变量。当 orchestrator 注入 manifests 后，策略方法优先使用 builder 输出。

```python
# strategies.py 顶部新增
_manifest_strategy: Optional['ManifestStrategyBuilder'] = None

def set_manifest_strategy(builder: 'ManifestStrategyBuilder') -> None:
    global _manifest_strategy
    _manifest_strategy = builder

def get_skills_for_aspect(aspect: str) -> List[str]:
    if _manifest_strategy:
        return _manifest_strategy.get_skills_for_aspect(aspect)
    # fallback to hardcoded
    if aspect in ASPECT_SKILL_MAP:
        return ASPECT_SKILL_MAP[aspect]
    for key, skills in ASPECT_SKILL_MAP.items():
        if key in aspect:
            return skills
    return DEFAULT_ASPECT_SKILLS.copy()
```

```python
# orchestrator.py init 中，在 init_from_discovery() 之后
from src.core.decomposition.manifest_strategy import ManifestStrategyBuilder
from src.core.decomposition.strategies import set_manifest_strategy
builder = ManifestStrategyBuilder(skill_registry.all_manifests())
set_manifest_strategy(builder)
```

- [ ] **Step 1:** 在 strategies.py 中添加 `_manifest_strategy` 全局变量和 `set_manifest_strategy()`
- [ ] **Step 2:** 修改 `get_skills_for_aspect()` 和 `_get_data_collection_skills()` 优先使用 builder
- [ ] **Step 3:** 在 orchestrator.py 中 init_from_discovery 后注入 builder
- [ ] **Step 4:** 写集成测试：完整的 decompose 流程使用 manifest 驱动的路由
- [ ] **Step 5:** Run tests, commit

### Task 2.3: 替换 generic_agent.py 中的 ACTION_TO_SKILL

**Files:**
- Modify: `src/core/agents/generic_agent.py`

当前 `ACTION_TO_SKILL` 是 `execute()` 方法内的局部变量（定义在 280 行，280-305 行）。改为从 manifest 动态构建。

```python
def _build_action_to_skill_map(self) -> Dict[str, Optional[str]]:
    intrinsic = {
        "llm": None, "analyze": None, "analysis": None,
        "reasoning": None, "summarize": None, "translate": None,
        "research": None, "data_collection": None,
        "calibration": None, "execute": None,
    }
    result = dict(intrinsic)
    if self._skill_registry:
        for name, manifest in self._skill_registry.all_manifests().items():
            for cap in manifest.capabilities:
                if cap not in result:
                    result[cap] = name
    # 显式覆盖：确保常用 action 不被意外覆盖（与当前 ACTION_TO_SKILL 280-304行对齐）
    result["search"] = "search_skill"
    result["news_search"] = "news_search"
    result["file_operation"] = "file_skill"
    result["http_request"] = "http_skill"
    result["generate_docx"] = "docx_skill"
    result["generate_pptx"] = "pptx_skill"
    result["web_search"] = "lc_tavily_search"
    result["tavily_search"] = "lc_tavily_search"
    result["academic_search"] = "lc_arxiv"
    result["arxiv_search"] = "lc_arxiv"
    result["wiki_search"] = "lc_wikipedia"
    result["wikipedia_search"] = "lc_wikipedia"
    result["data_analysis"] = "lc_python_repl"
    result["python_repl"] = "lc_python_repl"
    return result
```

> **注意**：当前 `ACTION_TO_SKILL` 中 `web_search` 映射到 `lc_tavily_search`（297行），而 `_do_deep_research()` 中 `registry.get("web_search")` 获取的是 `SearchSkill` 实例（2928行）。这两处的 `web_search` 语义不同：ACTION_TO_SKILL 中的 `web_search` 是 LangChain tavily 的 action 名，而 registry 中的 `web_search` 是 search_skill 的 alias。Task 4.3 将统一处理这个不一致。

- [ ] **Step 1:** 添加 `_build_action_to_skill_map()` 方法
- [ ] **Step 2:** 在 execute() 中替换硬编码 ACTION_TO_SKILL 为 `self._build_action_to_skill_map()`
- [ ] **Step 3:** 写测试：新 Skill 的 capability 自动出现在映射中
- [ ] **Step 4:** Run tests, commit

---

## Phase 3: 通用数据管道（核心改动）

### 防御性设计原则

> **核心约束**：不管 Skill 返回什么烂数据，管道都不能崩、不能卡、不能丢数据。
> 以下逐条审查每个故障模式及其防御措施。

| # | 故障模式 | 触发条件 | 后果 | 当前代码防御 | Plan 防御 | 差距 |
|---|---------|---------|------|:---:|:---:|:---:|
| F1 | Skill.execute() 返回 None | Skill 实现有 bug / 网络超时 | `None.get("success")` → AttributeError 崩溃 | ❌ 无 | `if not skill_result` ✅ | **当前代码有 bug** |
| F2 | Skill.execute() 返回非 dict（如 str/int） | 第三方 Skill 不遵守协议 | `.get("success")` → AttributeError | ❌ 无 | ❌ 无 | **需修复** |
| F3 | skill_result["data"] 含循环引用 | 第三方 Skill 返回自引用对象 | `json.dumps(data)` → ValueError | ❌ 无 | ❌ 无 | **需修复** |
| F4 | skill_result["data"] 含不可序列化对象（bytes/datetime/Decimal） | akshare 等返回非 JSON 类型 | `json.dumps(data)` → TypeError | ❌ 无 | ❌ 无 | **需修复** |
| F5 | skill_result["data"] 是巨型 dict（>10MB） | 未分页的 API 返回 | `len(str(data))` 消耗内存；`json.dumps` 消耗 CPU | ❌ 无 | 截断 6000 字 ✅ | L3 截断 OK，但 L3 之前 `str(data)` 无截断 |
| F6 | skill_result["data"] 是 None | Skill 返回 `{"success": True, "data": None}` | `isinstance(None, dict)` → False，跳过所有处理 | `if isinstance(data, dict):` ✅ | ❌ `data={}` 默认值后不检查 | **需修复** |
| F7 | _extract_numeric_metrics 遇到深层嵌套 | Skill 返回递归嵌套的 dict/list | 当前只处理 2 层（dict→list→dict）无递归 | 限制 2 层 ✅ | 限制 2 层 ✅ | OK |
| F8 | _extract_numeric_metrics 遇到 NaN/Inf | pandas 返回 float('nan') | `metrics[key] = NaN` 污染 SharedMemory | `val != val` 检查 ✅ | 同 ✅ | OK |
| F9 | skill.execute() 永不返回（卡死） | 网络/Skill 死锁 | 整个 Agent 卡死 | ❌ 无 | ❌ 无 | **需修复** |
| F10 | _to_readable_content L3 LLM 调用超时 | LLM 服务慢/挂 | 等待 30s+ | ❌ 无 | `except Exception: pass` ✅ | OK（call_llm 内部有超时） |
| F11 | identifiers 列表过长 | context 中有 50+ entities | 对每个 identifier × 每个 action 都调 execute | ❌ 无 | ❌ 无 | **需修复** |
| F12 | _process_news_skill 中 nr 不是 dict | NewsSearchSkill 返回格式异常 | `nr.get("title")` → AttributeError | ❌ 无 | ❌ 无 | **需修复** |
| F13 | _build_execute_kwargs 传入了 skill 不接受的参数 | manifest action_param_map 配错 | Skill.execute() TypeError | ❌ 无 | ❌ 无 | **需修复** |

**修复方案（补充到 Task 3.1 实现）：**

```python
async def _process_skill_output(
    self, skill, skill_name: str, topic: str, aspect: str,
    skill_registry: Any = None,
    structured_data_sufficient: bool = False,
    preloaded_search_results: Optional[List] = None,
    search_depth: str = "deep",
) -> Dict[str, Any]:
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}

    # [F9] 超时保护：整个 Skill 执行限时 60s
    try:
        processed = await asyncio.wait_for(
            self._process_skill_output_inner(
                skill, skill_name, topic, aspect, skill_registry,
                structured_data_sufficient, preloaded_search_results, search_depth,
            ),
            timeout=60.0,
        )
        return processed
    except asyncio.TimeoutError:
        logger.error(f"GenericAgent {self.agent_id}: {skill_name} timed out (60s)")
        return result
    except Exception as e:
        logger.error(f"GenericAgent {self.agent_id}: {skill_name} unexpected error: {e}")
        return result

async def _process_skill_output_inner(self, ...) -> Dict[str, Any]:
    """实际处理逻辑，被 _process_skill_output 包裹超时保护"""
    # ... 原有特殊分发 + action 循环逻辑 ...

    # ---- 3. 执行每个 action ----
    for identifier in identifiers[:5]:  # [F11] 限制 identifier 数量
        for action in actions:
            try:
                kwargs = self._build_execute_kwargs(
                    manifest, action, identifier, topic
                )
                # [F13] 捕获参数不匹配
                try:
                    skill_result = await skill.execute(**kwargs)
                except TypeError as te:
                    logger.warning(f"GenericAgent {self.agent_id}: {skill_name}.execute() "
                                   f"rejected kwargs {kwargs}: {te}")
                    continue

                # [F1+F2] 防御：返回值必须是 dict 且非 None
                if skill_result is None:
                    continue
                if not isinstance(skill_result, dict):
                    logger.warning(f"GenericAgent {self.agent_id}: {skill_name} returned "
                                   f"{type(skill_result).__name__}, expected dict")
                    skill_result = {"success": False, "data": {}, 
                                    "content": str(skill_result)}
                
                if not skill_result.get("success"):
                    continue

                data = skill_result.get("data")
                # [F6] data 是 None → 用空 dict，但仍保留 content
                if data is None:
                    data = {}
                elif isinstance(data, list):
                    data = {"records": data}
                elif not isinstance(data, dict):
                    # data 是 str/int 等 → 包装成 {"value": data}
                    data = {"value": data}

                # ---- 4. 三层内容转换 ----
                content = await self._to_readable_content(
                    skill_result, skill, data, action, identifier, skill_name, topic
                )

                # ---- 5. 通用数值提取 ----
                metrics = self._extract_numeric_metrics(data)

                # ---- 6. 统一存储 ----
                result["data_points"].append({...})
                result["sources"].append({...})
                result["canonical_metrics"].update(metrics)

            except Exception as action_err:
                logger.warning(...)

    return result
```

**`_to_readable_content` 防御增强（F3/F4/F5）：**

```python
async def _to_readable_content(
    self, skill_result, skill, data, action, identifier, skill_name, topic,
) -> str:
    # L1
    content = skill_result.get("content", "")
    if content and not isinstance(content, str):
        content = str(content)  # [F2] content 不是字符串
    
    # L2
    formatted = ""
    if hasattr(skill, 'format_data') and callable(skill.format_data):
        try:
            formatted = skill.format_data(data, action, identifier) or ""
            if not isinstance(formatted, str):
                formatted = str(formatted)
        except Exception:
            pass

    if formatted and (not content or len(formatted) > len(content)):
        content = formatted
    if content:
        return content

    # L3
    manifest = None
    if hasattr(self, '_skill_registry') and self._skill_registry:
        manifest = self._skill_registry.get_manifest(skill_name)
    
    # [F5] 先截断 data 的字符串表示，避免 str(data) 消耗过多内存
    data_preview = str(data)
    if len(data_preview) > 2000:
        data_preview = data_preview[:2000] + "...(truncated)"
    
    if data and len(data_preview) > 100 and (not manifest or manifest.priority != "structured_db"):
        try:
            llm_summary = await self._llm_summarize_data(
                data, skill_name, action, topic
            )
            if llm_summary:
                return llm_summary
        except Exception:
            pass

    # 兜底: JSON dump — [F3/F4] 防御循环引用和不可序列化对象
    if isinstance(data, dict) and data:
        try:
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        except (ValueError, TypeError, OverflowError) as e:
            logger.warning(f"GenericAgent {self.agent_id}: JSON dump failed for "
                           f"{skill_name}: {e}")
            return str(data)[:2000]
    return content or ""
```

**关键修复点：**
- `json.dumps(..., default=str)` — [F4] 遇到不可序列化对象（datetime/Decimal/bytes）自动转 str
- `try/except ValueError` — [F3] 循环引用时 fallback 到 `str(data)`
- `identifiers[:5]` — [F11] 限制 identifier 数量防止 O(N×M) 执行膨胀
- `asyncio.wait_for(timeout=60)` — [F9] 整体超时保护
- `isinstance(skill_result, dict)` 检查 — [F2] 非法返回值防御
- `data is None` → `{}` — [F6] None data 不丢失 content

**`_process_news_skill` 防御增强（F12）：**

```python
async def _process_news_skill(self, skill, topic, aspect, max_results=10):
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}
    news_query = f"{topic} {aspect} 最新 动态" if aspect else f"{topic} 最新 动态"
    try:
        news_result = await skill.execute(
            query=news_query, max_results=max_results, time_range="w",
        )
        if news_result and isinstance(news_result, dict) and news_result.get("success"):
            results_data = news_result.get("results", [])
            if not results_data:
                results_data = news_result.get("data", {}).get("results", [])
            if not isinstance(results_data, list):
                logger.warning(f"news_search results is {type(results_data).__name__}, skipping")
                return result
            for nr in results_data[:20]:  # [F11] 限制数量
                if not isinstance(nr, dict):  # [F12] 防御非 dict 元素
                    continue
                news_body = nr.get("body", "") or nr.get("snippet", "")
                news_url = nr.get("href", "") or nr.get("url", "")
                result["data_points"].append({...})
                result["sources"].append({...})
    except Exception as e:
        logger.warning(f"GenericAgent {self.agent_id}: news_search failed: {e}")
    return result
```

### Task 3.0: 编写 DATA_COLLECTION 阶段的行为快照测试（前置条件）

**Files:**
- Create: `tests/unit/agents/test_data_collection_snapshot.py`

在重构前，必须先写集成测试覆盖当前 DATA_COLLECTION 阶段的行为，确保重构后行为一致。

```python
@pytest.mark.asyncio
async def test_data_collection_structured_db_stock_data():
    """验证 structured_db Tier: stock_data 通过 _fetch_structured_data 获取数据"""
    # Mock SkillRegistry, stock_data Skill, SharedMemory
    # 验证 data_points 结构、canonical_metrics 写入、quality_score 等
    ...

@pytest.mark.asyncio
async def test_data_collection_web_search():
    """验证 web_search Tier: search_skill + news_search"""
    # Mock _do_deep_research, news_skill
    # 验证 data_points 合并、sources 合并
    ...

@pytest.mark.asyncio
async def test_data_collection_b_fix_3_metrics():
    """验证 B-FIX-3: 从 web search content 中正则提取数值写入 SharedMemory"""
    # 模拟 data_points 包含 "净利润 150.5亿元" 等文本
    # 验证 SharedMemory.write_canonical 被正确调用
    ...

@pytest.mark.asyncio
async def test_data_collection_fallback_queries():
    """验证 structured_db 不可用时注入 fallback queries"""
    # 模拟 _structured_data_fetched = False
    # 验证 _generate_structured_fallback_queries 被调用
    ...
```

- [ ] **Step 1:** 编写行为快照测试，覆盖当前 DATA_COLLECTION 阶段的 4 个关键行为
- [ ] **Step 2:** 运行测试，确认当前行为正确
- [ ] **Step 3:** Commit

### Task 3.1: 创建通用数据管道 `_process_skill_output()`

**Files:**
- Modify: `src/core/agents/generic_agent.py`

这是整个方案的核心。将当前分散在三处的 Skill 调用逻辑合并为一个通用方法。

**当前三处调用点分析**（均为调用点，方法定义位置不同）：

1. `generic_agent.py:470-499`（调用点） — structured_db Tier，调用 `_fetch_structured_data()`（定义在2313行）
2. `generic_agent.py:521-541`（调用点） — search_skill Tier，调用 `_do_deep_research()`（定义在2895行），手动拼 data_points
3. `generic_agent.py:544-576`（调用点） — news_search Tier，直接 `news_skill.execute()`，手动拼 data_points

**通用管道设计：**

```python
async def _process_skill_output(
    self,
    skill,
    skill_name: str,
    topic: str,
    aspect: str,
    skill_registry: Any = None,
    structured_data_sufficient: bool = False,
    preloaded_search_results: Optional[List] = None,
    search_depth: str = "deep",
) -> Dict[str, Any]:
    """
    通用 Skill 输出处理器。
    
    不假设 Skill 返回什么数据结构，用三层策略将任意数据
    转为下游可消费的 content + canonical_metrics。
    
    这是所有 Skill 数据进入系统的唯一入口。
    
    Args:
        structured_data_sufficient: 跨 Tier 状态，控制 news_search 数量和 search_depth
        preloaded_search_results: 跨 Tier 状态，search_skill 的预加载结果
        search_depth: 跨 Tier 状态，"basic" 或 "deep"
    """
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}

    # ---- 特殊分发：search_skill 保留完整的搜索策略逻辑 ----
    if skill_name == "search_skill":
        return await self._process_search_skill(
            skill, topic, aspect, skill_registry,
            preloaded_search_results=preloaded_search_results,
            search_depth=search_depth,
        )

    # ---- 特殊分发：news_search 参数格式不同于 structured_db ----
    if skill_name == "news_search":
        return await self._process_news_skill(
            skill, topic, aspect,
            max_results=5 if structured_data_sufficient else 10,
        )

    # ---- 1. 推断 identifier (symbol / query / topic) ----
    identifiers = self._resolve_identifiers(
        skill_name, topic, aspect, skill_registry
    )
    if not identifiers:
        identifiers = [topic]

    # ---- 2. 推断 actions ----
    manifest = skill_registry.get_manifest(skill_name) if skill_registry else None
    actions = self._infer_actions_from_manifest(manifest, skill, aspect, identifiers[0])

    # ---- 3. 执行每个 action ----
    # ⚠️ 防御性设计：下面的代码是核心逻辑的简化版。
    # 实际实现必须包含 F1-F13 防御措施（见上方"防御性设计原则"章节）：
    # - F9: asyncio.wait_for 超时保护
    # - F11: identifiers[:5] 数量限制
    # - F2: isinstance(skill_result, dict) 检查
    # - F13: TypeError 捕获（参数不匹配）
    for identifier in identifiers[:5]:  # [F11] 限制 identifier 数量
        for action in actions:
            try:
                kwargs = self._build_execute_kwargs(
                    manifest, action, identifier, topic
                )
                skill_result = await skill.execute(**kwargs)

                if not skill_result or not skill_result.get("success"):
                    continue

                data = skill_result.get("data")
                # [F6] data 是 None → 用空 dict，但仍保留 content
                if data is None:
                    data = {}
                elif isinstance(data, list):
                    data = {"records": data}

                # ---- 4. 三层内容转换 ----
                content = await self._to_readable_content(
                    skill_result, skill, data, action, identifier, skill_name, topic
                )

                # ---- 5. 通用数值提取 ----
                metrics = self._extract_numeric_metrics(data)

                # ---- 6. 统一存储 ----
                # 根据 manifest.priority 推断 quality_score / credibility / type
                # search_skill / news_search 已在入口处特殊分发，不会走到这里
                _manifest_priority = (manifest.priority if manifest else "web_search")
                if _manifest_priority == "structured_db":
                    _dp_quality = 95
                    _dp_credibility = "structured_source"
                    _src_type = "structured"
                    _src_quality = 95
                else:
                    _dp_quality = 50
                    _dp_credibility = "search_result"
                    _src_type = "web"
                    _src_quality = 50
                result["data_points"].append({
                    "title": f"{identifier} {action}",
                    "content": content,
                    "url": f"{skill_name}://{identifier}/{action}",
                    "quality_score": _dp_quality,
                    "credibility": _dp_credibility,
                })
                result["sources"].append({
                    "title": f"{skill_name} {identifier} {action}",
                    "url": f"{skill_name}://{identifier}/{action}",
                    "type": _src_type,
                    "quality_score": _src_quality,
                })
                result["canonical_metrics"].update(metrics)

            except Exception as action_err:
                logger.warning(
                    f"GenericAgent {self.agent_id}: {skill_name} "
                    f"action '{action}' failed: {action_err}"
                )

    return result
```

**news_search 特殊处理：**

> **⚠️ NewsSearchSkill 返回格式**：当前 `NewsSearchSkill.execute()` 通过 `self._success()` 返回结果（search_skill.py:479-482），结构为 `{"success": True, "results": [...], "query": ..., "total": ...}`。注意 `results` 在**顶层**而非 `data` 子键下。`_process_news_skill()` 必须优先从顶层取 `results`。

```python
async def _process_news_skill(self, skill, topic: str, aspect: str, max_results: int = 10) -> Dict[str, Any]:
    """news_search 的特殊处理：参数格式为 query/max_results/time_range"""
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}
    news_query = f"{topic} {aspect} 最新 动态" if aspect else f"{topic} 最新 动态"
    try:
        news_result = await skill.execute(
            query=news_query, max_results=max_results, time_range="w",
        )
        if news_result and news_result.get("success"):
            # NewsSearchSkill 通过 _success() 返回，results 在顶层
            results_data = news_result.get("results", [])
            if not results_data:
                results_data = news_result.get("data", {}).get("results", [])
            for nr in results_data:
                news_body = nr.get("body", "") or nr.get("snippet", "")
                news_url = nr.get("href", "") or nr.get("url", "")
                result["data_points"].append({
                    "title": nr.get("title", ""),
                    "content": news_body,
                    "url": news_url,
                    "quality_score": 70,
                    "credibility": "news_source",
                    "source_type": "news",
                    "source_name": nr.get("source", ""),
                    "date": nr.get("date", ""),
                })
                result["sources"].append({
                    "title": nr.get("title", ""),
                    "url": news_url,
                    "type": "news",
                    "quality_score": 70,
                })
    except Exception as e:
        logger.warning(f"GenericAgent {self.agent_id}: news_search failed: {e}")
    return result
```

**三层内容转换实现：**

> **L1 阈值修正**：原方案用 `len(content) > 50`，但实际 Skill 返回的可读 content 可能很短（如 `"贵州茅台(SH600519): 当前价1800.5"` 约 25 字符）。改为与 L2 比较长度的策略（与当前 `_fetch_structured_data` 的 2401 行逻辑一致）。

```python
async def _to_readable_content(
    self,
    skill_result: Dict,
    skill: Any,
    data: dict,
    action: str,
    identifier: str,
    skill_name: str,
    topic: str,
) -> str:
    """
    三层内容转换 — 适用于任意 Skill，不依赖 Skill 配合。
    
    L1: Skill 自带的 content 字段（任何 Skill 都能返回）
    L2: Skill 实现了 format_data()（我们自己的 Skill 可选优化，structured_db 类必需）
    L3: LLM 总结（通用兜底，适用于任何第三方 Skill，structured_db 类跳过以控制成本）
    兜底: JSON dump
    """
    # L1: Skill 自带的可读文本
    content = skill_result.get("content", "")
    
    # L2: Skill 实现了 format_data()
    formatted = ""
    if hasattr(skill, 'format_data') and callable(skill.format_data):
        try:
            formatted = skill.format_data(data, action, identifier) or ""
        except Exception:
            pass

    # 合并 L1 和 L2：取较长者（与当前 _fetch_structured_data 逻辑一致）
    if formatted and (not content or len(formatted) > len(content)):
        content = formatted

    # L1+L2 命中：直接返回
    if content:
        return content

    # L3: LLM 总结（通用兜底）
    # 对 structured_db 类 Skill 跳过 L3：它们应该实现 format_data()，
    # 如果 L2 没命中说明 Skill 实现有 bug，应走 JSON dump 兜底而非 LLM
    manifest = None
    if hasattr(self, '_skill_registry') and self._skill_registry:
        manifest = self._skill_registry.get_manifest(skill_name)
    
    # [F5] 先截断 data 的字符串表示，避免 str(data) 消耗过多内存
    data_preview = str(data)
    if len(data_preview) > 2000:
        data_preview = data_preview[:2000] + "...(truncated)"
    
    if data and len(data_preview) > 100 and (not manifest or manifest.priority != "structured_db"):
        try:
            llm_summary = await self._llm_summarize_data(
                data, skill_name, action, topic
            )
            if llm_summary:
                return llm_summary
        except Exception:
            pass  # LLM 失败，用 JSON dump 兜底

    # 兜底: JSON dump
    if isinstance(data, dict) and data:
        return json.dumps(data, ensure_ascii=False, indent=2)
    return content or ""
```

**LLM 总结实现：**

```python
async def _llm_summarize_data(
    self,
    data: dict,
    skill_name: str,
    action: str,
    topic: str,
) -> str:
    """
    用 LLM 将任意结构的数据转成人类可读摘要。
    适用于第三方 Skill 返回未知数据结构的场景。
    
    使用 RoutingHint(action="data_summarization") 指向合适的模型配置，控制成本。
    摘要字数根据数据量动态调整：小数据 200 字，大数据 500 字。
    """
    data_str = json.dumps(data, ensure_ascii=False, indent=2)
    # 截断防止超长
    if len(data_str) > 6000:
        data_str = data_str[:6000] + "\n... (truncated)"

    # 动态调整摘要长度
    max_chars = 500 if len(data_str) > 2000 else 200

    from src.config.llm_profiles import RoutingHint
    from src.core.llm_client import call_llm
    result = await call_llm(
        prompt=(
            f"将以下来自 {skill_name} 的 {action} 数据整理为结构化摘要。\n"
            f"研究主题：{topic}\n\n"
            f"原始数据：\n{data_str}\n\n"
            f"要求：\n"
            f"1. 提取关键数值并标注含义（如'市值22600亿'而非'market_capital: 22600'）\n"
            f"2. 用中文表述\n"
            f"3. 不超过{max_chars}字"
        ),
        system_prompt="你是数据摘要引擎，只输出摘要，不分析。",
        routing_hint=RoutingHint(action="data_summarization"),
    )
    if result.get("success") and result.get("content"):
        return result["content"]
    return ""
```

**identifier 解析实现：**

> **并发安全修复**：不修改 `skill._manifest`，而是将 manifest 作为参数传递给 `infer_actions`/`resolve_identifier`。由于 `infer_actions` 和 `resolve_identifier` 当前从 `self._manifest` 读取，最简单的修复是临时设置并在使用后恢复原值。长期方案是修改 Skill 基类使这些方法接受 manifest 参数。

```python
def _resolve_identifiers(
    self,
    skill_name: str,
    topic: str,
    aspect: str,
    skill_registry: Any = None,
) -> List[str]:
    """
    解析 Skill 执行所需的标识符（股票代码/搜索词/主题）。
    
    优先级：
    1. context entities 中已解析的代码
    2. topic 中提取的股票代码
    3. 公司名→代码解析
    4. manifest.resolve_identifier (如 xueqiu 的 topic fallback)
    5. 返回空列表（web_search 类 Skill 不需要 identifier）
    """
    identifiers = []

    # 1. 从 context entities 获取
    raw_entities = getattr(self, '_context', {}).get("entities", [])
    if raw_entities:
        from src.core.entity_resolver import EntityInfo
        entities = [
            EntityInfo.from_dict(e) if isinstance(e, dict) else e
            for e in raw_entities
        ]
        listed = [e for e in entities if e.is_listed and e.resolved_code]
        if listed:
            identifiers = [e.resolved_code for e in listed]
            return identifiers

    # 2. 从 topic 提取股票代码
    symbol = self._extract_stock_symbol(topic)
    if symbol:
        return [symbol]

    # 3. 公司名→代码
    chinese_m = re.search(r'[\u4e00-\u9fff]+', topic)
    if chinese_m:
        resolved = self._resolve_company_to_code(chinese_m.group(0))
        if resolved:
            return [resolved]

    # 4. manifest.resolve_identifier
    # 注意：临时设置 _manifest，使用后恢复，保证并发安全
    if skill_registry:
        manifest = skill_registry.get_manifest(skill_name)
        if manifest and manifest.supports_topic_fallback and topic:
            skill = skill_registry.get(skill_name)
            if skill:
                old_manifest = getattr(skill, '_manifest', None)
                try:
                    skill._manifest = manifest
                    identifier = skill.resolve_identifier(topic, aspect)
                    if identifier:
                        return [identifier]
                finally:
                    skill._manifest = old_manifest

    return identifiers
```

**action 推断实现：**

```python
def _infer_actions_from_manifest(
    self,
    manifest: Any,
    skill: Any,
    aspect: str,
    identifier: str,
) -> List[str]:
    """
    从 manifest.action_rules 推断 actions。
    通用方法，不包含任何 skill-specific 逻辑。
    """
    if manifest and manifest.action_rules:
        if skill:
            # 临时设置 _manifest，使用后恢复，保证并发安全
            old_manifest = getattr(skill, '_manifest', None)
            try:
                skill._manifest = manifest
                return skill.infer_actions(aspect, identifier)
            finally:
                skill._manifest = old_manifest
        # 没有 skill 实例，直接匹配 action_rules（累加模式，与 infer_actions 一致）
        all_actions = []
        matched = False
        for rule in manifest.action_rules:
            if not re.match(rule.pattern, identifier):
                continue
            if rule.aspect_keywords:
                aspect_lower = (aspect or "").lower()
                if any(kw.lower() in aspect_lower for kw in rule.aspect_keywords):
                    all_actions.extend(rule.actions)
                    matched = True
                continue
            # 无 aspect_keywords 的 rule 作为默认兜底
            if not matched:
                return rule.actions
        if matched:
            return list(dict.fromkeys(all_actions))

    # 没有 manifest 或没有 action_rules → 默认 action
    return ["default"]
```

**execute 参数构建实现：**

```python
def _build_execute_kwargs(
    self,
    manifest: Any,
    action: str,
    identifier: str,
    topic: str,
) -> Dict[str, Any]:
    """
    从 manifest.action_param_map 构建 execute 参数。
    通用方法，不包含任何 skill-specific 逻辑。
    """
    kwargs = {"action": action}

    if manifest and manifest.action_param_map and action in manifest.action_param_map:
        param_map = manifest.action_param_map[action]
        for param_name, source in param_map.items():
            if source == "symbol":
                kwargs[param_name] = identifier
            elif source == "query":
                kwargs[param_name] = identifier
            elif source == "topic":
                kwargs[param_name] = topic
            else:
                kwargs[param_name] = identifier  # 未知 source 默认用 identifier
    else:
        # 没有 manifest → 根据 Skill 类型推断参数名
        # structured_db 类 Skill 用 symbol，web_search 类用 query
        # 但 search_skill 和 news_search 已在 _process_skill_output 中特殊分发
        # 走到这里的是 structured_db 类 Skill，默认用 symbol
        kwargs["symbol"] = identifier

    return kwargs
```

> **注意：** `_build_execute_kwargs()` 的默认 `symbol` 参数是安全的，因为 `search_skill` 和 `news_search` 已在 `_process_skill_output()` 入口处被特殊分发，不会走到这个默认分支。对于未来新增的 web_search 类 Skill，必须在 SKILL.md 的 `action_param_map` 中声明 `query` 参数映射，否则会错误地传入 `symbol`。建议在运行时增加检测：当 kwargs 中有 `symbol` 但 manifest.priority 是 `web_search` 时，打印 warning。

- [ ] **Step 1:** 在 generic_agent.py 中添加 `_process_skill_output()` 及其辅助方法
- [ ] **Step 2:** 写单元测试：每个辅助方法独立测试

```python
@pytest.mark.asyncio
async def test_to_readable_content_l1_skill_content():
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    skill_result = {"success": True, "content": "贵州茅台(SH600519): 当前价1800.5", "data": {}}
    content = await agent._to_readable_content(
        skill_result, None, {}, "quote", "SH600519", "xueqiu", "茅台"
    )
    assert "1800.5" in content

@pytest.mark.asyncio
async def test_to_readable_content_l2_format_data():
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    skill_result = {"success": True, "content": "", "data": {"current": 1800}}
    class MockSkill:
        def format_data(self, data, action, symbol):
            return f"当前价 {data.get('current')}"
    content = await agent._to_readable_content(
        skill_result, MockSkill(), {"current": 1800}, "quote", "SH600519", "xueqiu", "茅台"
    )
    assert "1800" in content

@pytest.mark.asyncio
async def test_to_readable_content_fallback_json():
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    skill_result = {"success": True, "content": "", "data": {"key": "value"}}
    content = await agent._to_readable_content(
        skill_result, None, {"key": "value"}, "default", "test", "unknown_skill", "test"
    )
    assert "key" in content  # JSON dump fallback

@pytest.mark.asyncio
async def test_to_readable_content_skips_l3_for_structured_db():
    """structured_db 类 Skill 跳过 L3，直接走 JSON dump 兜底"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    # 需要 mock skill_registry.get_manifest() 返回 priority=structured_db
    # 验证 _llm_summarize_data 不被调用
    ...
```

- [ ] **Step 2a:** 写防御性测试（对应 F1-F13 故障模式）

```python
@pytest.mark.asyncio
async def test_process_skill_output_returns_none():
    """F1: Skill.execute() 返回 None 不崩溃"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    class NoneSkill:
        name = "none_skill"
        async def execute(self, **kwargs): return None
    result = await agent._process_skill_output_inner(
        NoneSkill(), "none_skill", "test", "test", None,
    )
    assert result == {"data_points": [], "sources": [], "canonical_metrics": []}

@pytest.mark.asyncio
async def test_process_skill_output_returns_string():
    """F2: Skill.execute() 返回 str 不崩溃"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    class StringSkill:
        name = "string_skill"
        async def execute(self, **kwargs): return "I'm not a dict"
    result = await agent._process_skill_output_inner(
        StringSkill(), "string_skill", "test", "test", None,
    )
    assert result["data_points"] == []  # success=False, 不进入处理

@pytest.mark.asyncio
async def test_process_skill_output_data_none():
    """F6: Skill 返回 data=None 不崩溃，保留 content"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    class NoneDataSkill:
        name = "none_data"
        async def execute(self, **kwargs):
            return {"success": True, "data": None, "content": "some content"}
    # 需要 mock skill_registry 才能走完 action 循环
    # ... 或直接测 _to_readable_content
    content = await agent._to_readable_content(
        {"success": True, "data": None, "content": "some content"},
        None, {}, "default", "test", "none_data", "test",
    )
    assert content == "some content"

@pytest.mark.asyncio
async def test_to_readable_content_circular_ref():
    """F3: 循环引用 data 不崩溃"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    data = {}
    data["self"] = data  # 循环引用
    content = await agent._to_readable_content(
        {"success": True, "content": "", "data": data},
        None, data, "default", "test", "circular_skill", "test",
    )
    assert content  # 不崩溃，返回 str(data) 或部分 JSON

@pytest.mark.asyncio
async def test_to_readable_content_non_serializable():
    """F4: 含 datetime/bytes 的 data 不崩溃"""
    import datetime
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    data = {"ts": datetime.datetime.now(), "raw": b"bytes"}
    content = await agent._to_readable_content(
        {"success": True, "content": "", "data": data},
        None, data, "default", "test", "weird_skill", "test",
    )
    assert "ts" in content  # json.dumps(default=str) 能处理

@pytest.mark.asyncio
async def test_process_skill_output_timeout():
    """F9: Skill 卡死不阻塞整个 Agent"""
    import asyncio
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    class HungSkill:
        name = "hung_skill"
        async def execute(self, **kwargs):
            await asyncio.sleep(9999)  # 永远不返回
    result = await agent._process_skill_output(
        HungSkill(), "hung_skill", "test", "test", None,
    )
    assert result == {"data_points": [], "sources": [], "canonical_metrics": {}}

@pytest.mark.asyncio
async def test_process_news_skill_non_dict_elements():
    """F12: news results 中含非 dict 元素不崩溃"""
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    class BadNewsSkill:
        name = "bad_news"
        async def execute(self, **kwargs):
            return {
                "success": True,
                "results": [{"title": "ok"}, "string_item", None, 42],
            }
    result = await agent._process_news_skill(BadNewsSkill(), "test", "test")
    assert len(result["data_points"]) == 1  # 只有第一个 dict 元素被处理
```

- [ ] **Step 3:** Run tests, commit

### Task 3.2: 重构 DATA_COLLECTION 阶段使用通用管道

**Files:**
- Modify: `src/core/agents/generic_agent.py`

将当前三处分散的 Skill 调用逻辑替换为统一的 `_process_skill_output()` 调用。

**当前代码结构**（generic_agent.py:449-633，DATA_COLLECTION 阶段执行逻辑）：

```
Tier 1 (structured_db, 470-499行):
  for db_skill_name in tiered_skills["structured_db"]:
    db_skill = registry.get(db_skill_name)
    structured = await self._fetch_structured_data(db_skill, topic, aspect, skill_name=db_skill_name)
    data_points.extend(structured["data_points"])
    sources.extend(structured["sources"])
    canonical_metrics → SharedMemory

Tier 2 (web_search, 506-576行):
  if "search_skill" in web_skills:
    search_results = await self._do_deep_research(...)
    手动拼 data_points
  if "news_search" in web_skills:
    news_skill.execute(...)
    手动拼 data_points

B-FIX-3 (578-611行):
  从 data_points content 中正则提取数值 → SharedMemory
```

**重构后：**

```python
# Tier 1 + Tier 2 统一处理
_structured_data_fetched = False
_structured_data_sufficient = False
_has_doc_data_t2 = bool(
    self._context.get("document_context")
    or self._context.get("has_preloaded_data")
    or task.get("document_context")
)

for skill_name in execution_order:
    if not skill_registry:
        continue
    skill = skill_registry.get(skill_name)
    if not skill:
        continue

    # ---- 跳过非数据类 Skill ----
    # _process_skill_output() 的三层转换只适用于数据类 Skill。
    # 文件产物类（docx_skill, priority=llm）和业务流程类（survey_skill）
    # 不走数据管道——它们的返回值（filepath/survey_id 等）由 Agent
    # 在其他阶段（如 REPORT_GENERATION）直接消费。
    # 当前 execution_order 仅包含 structured_db + web_search tier 的 Skill，
    # 所以这个循环天然不会遇到 docx_skill 等非数据类 Skill。
    # 但为了防御性，仍检查 priority：
    tier = SKILL_PRIORITY_MAP.get(skill_name, "web_search")
    if tier == "llm":
        continue

    # ---- 跨 Tier 状态控制 ----
    # Phase 2 完成后，此处应改为 builder.build_skill_priority_map()
    tier = SKILL_PRIORITY_MAP.get(skill_name, "web_search")

    # web_search tier: 如果有预加载文档数据，跳过
    if tier == "web_search" and _has_doc_data_t2:
        continue

    # web_search tier: 如果 structured_db 未获取到数据，注入 fallback queries
    if tier == "web_search" and not _structured_data_fetched and topic:
        fallback_queries = self._generate_structured_fallback_queries(topic, aspect or "")
        if fallback_queries:
            preloaded = task.get("preloaded_search_results")
            if not preloaded:
                preloaded = []
            preloaded.extend([{"query": q, "results": []} for q in fallback_queries])
            task["preloaded_search_results"] = preloaded

    try:
        processed = await self._process_skill_output(
            skill, skill_name, topic, aspect, skill_registry,
            structured_data_sufficient=_structured_data_sufficient,
            preloaded_search_results=task.get("preloaded_search_results"),
            search_depth="basic" if _structured_data_sufficient else "deep",
        )
        dp_count = len(processed.get("data_points", []))
        if dp_count > 0:
            data_points.extend(processed.get("data_points", []))
            sources.extend(processed.get("sources", []))
            # 写入 SharedMemory（来自 _extract_numeric_metrics 的 canonical_metrics）
            if self._shared_memory and hasattr(self._shared_memory, 'write_canonical'):
                # caliber 根据 tier 区分：structured_db 用 structured_source，其他用 search_result
                _caliber = "structured_source" if tier == "structured_db" else "search_result"
                for metric, value in processed.get("canonical_metrics", {}).items():
                    await self._shared_memory.write_canonical(
                        metric=metric, value=value,
                        caliber=_caliber,
                        source=skill_name,
                        publisher=self.agent_id,
                    )
            # 更新获取状态标记
            if tier == "structured_db":
                _structured_data_fetched = True
                if dp_count >= 3:
                    _structured_data_sufficient = True
    except Exception as skill_err:
        logger.warning(f"GenericAgent {self.agent_id}: {skill_name} failed: {skill_err}")

# B-FIX-3: 从 web search 的 data_points content 中正则提取关键数值
if self._shared_memory and hasattr(self._shared_memory, 'write_canonical'):
    import re as _re
    _section_id = self.section_id
    for _dp in data_points[:10]:
        _c = _dp.get("content", "")
        _u = _dp.get("url", "")
        for _p, _mn in [
            (r'(?:净利润|归母|扣非)[^\d]*?(\d+\.?\d*)\s*亿元', "净利润"),
            (r'(?:(?:营业)?收入|营收)[^\d]*?(\d+\.?\d*)\s*亿元', "营收"),
            (r'销量[^\d]*?(\d+\.?\d*)\s*万辆', "销量"),
            (r'研发[^\d]*?(\d+\.?\d*)\s*亿元', "研发投入"),
            (r'毛利率[^\d]*?(\d+\.?\d*)\s*%', "毛利率"),
        ]:
            _m = _re.search(_p, _c)
            if _m:
                _metric_key = _mn if not _section_id else f"{_section_id}/{_mn}"
                _conflict = await self._shared_memory.write_canonical(
                    metric=_metric_key,
                    value=float(_m.group(1)),
                    caliber="search_result",
                    source=_u,
                    publisher=self.agent_id,
                )
                if _conflict and self._message_bus:
                    from src.core.communication import Event
                    await self._message_bus.publish(
                        "data.conflict.detected",
                        Event(type="data.conflict.detected", data={
                            "metric": _conflict.key,
                            "values": _conflict.values,
                            "sources": _conflict.sources,
                        })
                    )
```

> **关键设计决策：**
> 1. `_has_doc_data_t2`、`_structured_data_sufficient`、`_generate_structured_fallback_queries()` 是**跨 Tier 状态**，不属于单个 Skill 的处理逻辑。它们保留在统一循环中，不放入 `_process_skill_output()`。
> 2. **B-FIX-3 逻辑必须保留**：正则从 data_points content 提取数值的逻辑是跨 Tier 的数据后处理，不属于任何单个 Skill，放在统一循环之后。

**search_skill 和 news_search 的特殊处理**

当前 search_skill 走 `_do_deep_research()`，内部有完整的搜索→结果聚合逻辑。如果直接用 `_process_skill_output()`，搜索结果的结构（`{searches: [{results: [...]}]}`）会走 L3 JSON dump，丢失可读性。

**决策**：保留 `_do_deep_research()` 作为 search_skill 的高级调用方法，但其**输出格式**与 `_process_skill_output()` 对齐（返回 `{data_points, sources, canonical_metrics}`）。在通用管道中，对 search_skill 做特殊分发：

```python
# 在 _process_skill_output() 开头添加
if skill_name == "search_skill":
    return await self._process_search_skill(skill, topic, aspect, skill_registry)
```

```python
async def _process_search_skill(
    self, skill, topic, aspect, skill_registry,
    preloaded_search_results=None, search_depth="deep",
):
    """search_skill 的特殊处理：保留 _do_deep_research 的搜索策略逻辑"""
    search_results = await self._do_deep_research(
        topic=topic, aspect=aspect, aspects=[], skill_registry=skill_registry,
        preloaded_search_results=preloaded_search_results,
        depth=search_depth,
    )
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}
    for search in search_results.get("searches", []):
        for item in search.get("results", []):
            body = item.get("body", "") or item.get("snippet", "")
            url = item.get("href", "") or item.get("url", "")
            result["data_points"].append({
                "title": item.get("title", ""),
                "content": body,
                "url": url,
                "quality_score": item.get("quality_score", 0),
                "credibility": item.get("credibility", "unknown"),
            })
            result["sources"].append({
                "title": item.get("title", ""),
                "url": url,
                "type": "web",
                "quality_score": item.get("quality_score", 0),
            })
    return result
```

- [ ] **Step 1:** 添加 `_process_search_skill()` 方法
- [ ] **Step 2:** 在 `_process_skill_output()` 开头添加 search_skill 特殊分发
- [ ] **Step 3:** 重构 DATA_COLLECTION 阶段，用统一的 `_process_skill_output()` 循环替换三处分散逻辑
- [ ] **Step 4:** 保留 B-FIX-3 逻辑在统一循环之后
- [ ] **Step 5:** 保留 `_fetch_structured_data()` 作为废弃方法（向后兼容），内部转发到 `_process_skill_output()`。经确认，`_fetch_structured_data()` 仅在 generic_agent.py:478 被调用，重构后该调用点将被统一循环替换，因此废弃方法仅作为安全网，无其他调用者需要迁移。
- [ ] **Step 6:** 运行 Task 3.0 的行为快照测试，确认行为一致
- [ ] **Step 7:** 运行全量测试
- [ ] **Step 8:** Commit

### Task 3.3: 将 stock_data 的格式化逻辑迁移到 StockDataSkill.format_data()

**Files:**
- Modify: `src/skills/analysis/stock_data.py` — 添加 `format_data()` 和相关常量/方法
- Modify: `src/core/agents/generic_agent.py` — 删除 `_format_structured_data()` 等 5 个方法 + 2 个常量

将 generic_agent.py 中 stock_data 专用的格式化逻辑内迁到 Skill 本身：

```python
# stock_data.py
class StockDataSkill(Skill):
    # 从 generic_agent.py 迁入
    _FINANCIALS_KEY_COLUMNS = {
        "income_statement": { ... },
        "balance_sheet": { ... },
        "cash_flow": { ... },
    }
    _THS_METRIC_CN = { ... }

    def format_data(self, data: dict, action: str, symbol: str) -> str:
        if action == "financials":
            return self._format_financials(data, symbol)
        elif action == "price_history":
            return self._format_price_history(data, symbol)
        elif action == "key_metrics":
            return self._format_key_metrics(data, symbol)
        elif action == "company_info":
            return self._format_company_info(data, symbol)
        return ""

    def _format_financials(self, data, symbol):
        # 从 generic_agent.py:2523-2562 迁入
        ...

    def _format_price_history(self, data, symbol):
        # 从 generic_agent.py:2564-2598 迁入
        ...

    def _format_key_metrics(self, data, symbol):
        # 从 generic_agent.py:2627-2644 迁入
        ...

    def _format_company_info(self, data, symbol):
        # 从 generic_agent.py:2646-2660 迁入
        ...
```

**验证**：`StockDataSkill.format_data()` 的输出必须与原 `generic_agent._format_structured_data()` 完全一致。

- [ ] **Step 1:** 迁移 `_FINANCIALS_KEY_COLUMNS` 和 `_THS_METRIC_CN` 到 StockDataSkill
- [ ] **Step 2:** 迁移 4 个 format 方法到 StockDataSkill.format_data()
- [ ] **Step 3:** 写对比测试：确认 format_data 输出与原方法一致
- [ ] **Step 4:** 删除 generic_agent.py 中的 `_format_structured_data()` 及相关方法和常量（定义在 2493-2660 行）
- [ ] **Step 5:** 运行全量测试
- [ ] **Step 6:** Commit

### Task 3.4: 实现 XueqiuSkill.format_data()

**Files:**
- Modify: `src/skills/analysis/xueqiu_skill.py`

当前 xueqiu 数据在 agent 中走 JSON dump。实现 format_data() 优化呈现：

> **⚠️ XueqiuSkill 支持 8 个 action**（quote, search, hot_posts, hot_stocks, kline, user_posts, check, search_and_quote），但现有 SKILL.md 只列了 7 个（遗漏 `user_posts`）。实现 format_data() 时必须覆盖所有 8 个 action，同时更新 SKILL.md 的 capabilities 列表。

```python
class XueqiuSkill(Skill):
    def format_data(self, data: dict, action: str, symbol: str) -> str:
        if action == "quote":
            return (
                f"{data.get('name', '')}({data.get('symbol', '')}): "
                f"当前价 {data.get('current')}, "
                f"涨跌幅 {data.get('percent')}%, "
                f"市值 {data.get('market_capital')}, "
                f"PE_TTM {data.get('pe_ttm')}, "
                f"换手率 {data.get('turnover_rate')}"
            )
        elif action == "kline":
            count = len(data) if isinstance(data, list) else 0
            return f"{symbol} K线数据 {count} 条"
        elif action == "hot_stocks":
            lines = []
            for item in (data if isinstance(data, list) else [])[:10]:
                lines.append(
                    f"{item.get('rank', '')}. {item.get('name', '')}"
                    f"({item.get('symbol', '')}): "
                    f"当前价 {item.get('current')}, "
                    f"涨跌幅 {item.get('percent')}%"
                )
            return "\n".join(lines)
        elif action == "search":
            items = data if isinstance(data, list) else []
            if not items:
                return f"{symbol} 搜索无结果"
            lines = [f"=== {symbol} 搜索结果 ({len(items)}条) ==="]
            for item in items[:5]:
                lines.append(f"{item.get('name', '')}({item.get('symbol', '')}): "
                             f"当前价 {item.get('current', 'N/A')}")
            return "\n".join(lines)
        elif action == "hot_posts":
            items = data if isinstance(data, list) else []
            if not items:
                return "热门帖子无数据"
            lines = [f"=== 热门帖子 ({len(items)}条) ==="]
            for item in items[:5]:
                lines.append(f"- {item.get('title', '')} (回复{item.get('reply_count', 0)})")
            return "\n".join(lines)
        elif action == "user_posts":
            items = data if isinstance(data, list) else []
            if not items:
                return "用户帖子无数据"
            lines = [f"=== 用户帖子 ({len(items)}条) ==="]
            for item in items[:5]:
                lines.append(f"- {item.get('title', '')}")
            return "\n".join(lines)
        elif action == "check":
            status = data.get("status", "unknown")
            message = data.get("message", "")
            return f"API状态: {status}, {message}"
        elif action == "search_and_quote":
            if isinstance(data, dict) and "quote" in data:
                q = data["quote"]
                return (
                    f"{q.get('name', '')}({q.get('symbol', '')}): "
                    f"当前价 {q.get('current')}, "
                    f"涨跌幅 {q.get('percent')}%, "
                    f"市值 {q.get('market_capital')}"
                )
        return ""
```

- [ ] **Step 1:** 实现 XueqiuSkill.format_data()
- [ ] **Step 2:** 写测试验证输出格式
- [ ] **Step 3:** Run tests, commit

---

## Phase 4: Agent 通用化（消灭 skill-specific 代码）

### Task 4.1: 删除 `_infer_stock_actions()`

**前置条件**：Task 1.3 完成（stock_data 有 SKILL.md + action_rules）

当前 `generic_agent.py:2378-2380`（`_fetch_structured_data` 方法内的 else 分支）：
```python
else:
    actions = self._infer_stock_actions(aspect)
```

迁移后所有 structured_db Skill 都有 manifest + action_rules，这个 else 分支不可达。

- [ ] **Step 1:** 将 `self._infer_stock_actions(aspect)` 替换为 `["default"]`
- [ ] **Step 2:** 删除 `_infer_stock_actions()` 方法（定义在 2734-2759 行）
- [ ] **Step 3:** 写测试确认 stock_data action 推断仍通过 manifest 正确工作
- [ ] **Step 4:** Run tests, commit

### Task 4.2: 删除 `_format_structured_data()` 及相关方法

**前置条件**：Task 3.3 完成（格式化逻辑已迁移到 StockDataSkill.format_data()）

删除 generic_agent.py 中的：
- `_format_structured_data()` (定义在 2512-2521 行)
- `_format_financials()` (定义在 2523-2562 行)
- `_format_price_history()` (定义在 2564-2598 行)
- `_format_key_metrics()` (定义在 2627-2644 行)
- `_format_company_info()` (定义在 2646-2660 行)
- `_FINANCIALS_KEY_COLUMNS` (定义在 2493-2510 行)
- `_THS_METRIC_CN` (定义在 2600-2625 行)

- [ ] **Step 1:** 删除上述方法和常量
- [ ] **Step 2:** 搜索项目中是否还有其他地方引用这些方法
- [ ] **Step 3:** Run tests, commit

### Task 4.3: 替换 search_skill 硬编码查找为 registry.get_by_capability()

**Files:**
- Modify: `src/core/agents/generic_agent.py`
- Modify: `src/core/orchestrator/orchestrator.py`

当前 4 处 `registry.get("web_search")`（generic_agent.py:668, 1397, 2928, 3708）和 4 处 `registry.get("search_skill")`（generic_agent.py:670, 1396, 2931, 3710）。注意：164 行的 `registry.get("search_skill")` 在 docstring 注释中，不是实际代码，不计入。另外，当前代码中还有 3 处 `registry.get("multi_search")`（669, 1398, 2929, 3709）和 1 处 `registry.get("baidu_search")`（2930）作为 fallback 链的一部分——这些是遗留名称，registry 中不存在，`get()` 始终返回 None，可以安全删除。

> **⚠️ get_by_capability() 的不确定性**：当前 `get_by_capability()` 实现（registry.py:559-565）只返回**第一个**匹配 capability 的 Skill，且遍历顺序取决于 dict 插入顺序。如果 search_skill 和 lc_tavily_search 都有 `search` capability，返回哪个不确定。建议先为 `get_by_capability()` 添加 `priority` 参数，优先返回指定 priority 的 Skill；或者更简单地，保留 `registry.get("search_skill")` 的直接查找方式，因为它比 `get_by_capability("search")` 更明确。**本 Task 改为统一使用 `registry.get("search_skill")`，不再混用 `web_search` alias**。

- [ ] **Step 1:** 验证 search_skill SKILL.md 有 `capabilities: [search]`
- [ ] **Step 2:** 替换所有 `registry.get("web_search") or registry.get("multi_search") or registry.get("search_skill")` 和类似 fallback 链为 `registry.get("search_skill")`（统一通过 aliases 机制保证 `web_search` 也能访问）。同时删除 `registry.get("multi_search")` 和 `registry.get("baidu_search")` 等遗留名称的 fallback
- [ ] **Step 3:** Run tests, commit

### Task 4.4: 废弃 skill_keywords.py

**Files:**
- Modify: `src/skills/registry.py` — `discover_skills()` 改用 manifest keywords
- Modify: `src/skills/skill_keywords.py` — 添加 DeprecationWarning

当前 `registry.discover_skills()` 调用 `skill_keywords.match_skills()`。改为从 manifest.keywords 匹配：

> **⚠️ 降级风险**：当前 `skill_keywords.match_skills()` 使用 `difflib.get_close_matches()` 做模糊匹配（skill_keywords.py:149），而 manifest keywords 方案只做子串匹配。模糊匹配能匹配 "finacial" → "financial"，子串匹配不能。迁移后 `discover_skills()` 的匹配能力会降级。建议在 manifest keywords 匹配后，如果无结果，fallback 到 `difflib` 模糊匹配。

```python
def discover_skills(self, query: str, auto_load: bool = True) -> List[str]:
    query_lower = query.lower().strip()
    matched = []

    # 1. 精确子串匹配（从 manifest keywords）
    for name, manifest in self._manifests.items():
        for kw in manifest.keywords:
            if query_lower in kw.lower() or kw.lower() in query_lower:
                if name not in matched:
                    matched.append(name)
                break

    # 2. 如果精确匹配无结果，fallback 到 difflib 模糊匹配
    if not matched:
        import difflib
        all_keywords = {}
        for name, manifest in self._manifests.items():
            for kw in manifest.keywords:
                all_keywords[kw.lower()] = name
        close = difflib.get_close_matches(
            query_lower, all_keywords.keys(), n=5, cutoff=0.6
        )
        for kw in close:
            name = all_keywords[kw]
            if name not in matched:
                matched.append(name)

    # auto_load 逻辑保持不变
    loaded = []
    if auto_load:
        for skill_name in matched:
            if skill_name in self._skills:
                loaded.append(skill_name)
            elif skill_name in self._factories:
                skill = self.get(skill_name)
                if skill:
                    loaded.append(skill_name)
            elif skill_name.startswith("lc_"):
                if self.load_langchain_skill(skill_name):
                    loaded.append(skill_name)

    return loaded
```

- [ ] **Step 1:** 重写 `discover_skills()` 使用 manifest keywords + difflib fallback
- [ ] **Step 2:** 给 skill_keywords.py 添加 DeprecationWarning
- [ ] **Step 3:** 写测试：`discover_skills("financial data")` 找到 stock_data
- [ ] **Step 4:** Run tests, commit

---

## Phase 5: Skill 与模块职责边界

> **建议推迟**：ArtifactService 和 SkillLifecycleState 是好的前瞻设计，但当前没有 Skill 产生持久化产物（ui_design Skill 尚不存在），ArtifactService 的 CRUD 接口与现有 `SharedMemory` 功能重叠。建议在 Phase 6 验证通过后，作为独立 PR 实施，避免过度设计阻塞核心交付。

### Task 5.1: 定义 SkillArtifact 协议

**Files:**
- Create: `src/skills/artifact.py`
- Test: `tests/unit/skills/test_artifact.py`

当 Skill 产生持久化产物（如 ui_design 输出主题配置、docx_skill 输出文件），通过 ArtifactService 统一管理 CRUD。

```python
@dataclass
class SkillArtifact:
    artifact_id: str
    skill_name: str
    artifact_type: str  # "file", "config", "data"
    path: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    created_at: str = ""
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

class ArtifactService:
    def __init__(self, base_dir: str):
        self._base_dir = Path(base_dir)
        self._artifacts: Dict[str, SkillArtifact] = {}

    def create(self, skill_name: str, artifact_type: str,
               data: Optional[Dict] = None, path: Optional[str] = None) -> SkillArtifact: ...
    def read(self, artifact_id: str) -> Optional[SkillArtifact]: ...
    def update(self, artifact_id: str, data: Optional[Dict] = None, path: Optional[str] = None) -> SkillArtifact: ...
    def delete(self, artifact_id: str) -> bool: ...
    def list_by_skill(self, skill_name: str) -> List[SkillArtifact]: ...
    def list_by_type(self, artifact_type: str) -> List[SkillArtifact]: ...
```

**边界规则**：
- Skill 输出数据（设计规范、操作指令），不直接操作产出物
- 模块（html_to_ppt、ppt_revision_service）消费数据，执行文件操作
- Agent 编排 Skill + 模块，通过 ArtifactService 管理产出物

例如 ui_design Skill：
```
ui_design Skill 输出: {palette: [...], font_primary: "...", layout_rules: {...}}
  → ArtifactService.create(skill_name="ui_design", artifact_type="config", data=...)
  → html_to_ppt 读取 Artifact → 生成 .pptx
  → ppt_revision_service 修改 .pptx
```

- [ ] **Step 1:** Create `src/skills/artifact.py` with SkillArtifact and ArtifactService
- [ ] **Step 2:** 写 CRUD 测试
- [ ] **Step 3:** Run tests, commit

### Task 5.2: Skill 生命周期状态

```python
class SkillLifecycleState(Enum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    INSTANTIATED = "instantiated"
    FAILED = "failed"
    DEPRECATED = "deprecated"
```

在 SkillRegistry 中添加：

```python
def get_lifecycle_state(self, name: str) -> Optional[SkillLifecycleState]:
    if name in self._skills:
        return SkillLifecycleState.INSTANTIATED
    if name in self._factories:
        return SkillLifecycleState.LOADED
    if name in self._manifests:
        manifest = self._manifests[name]
        if manifest.version and manifest.version.startswith("0.") or \
           getattr(manifest, 'deprecated', False):
            return SkillLifecycleState.DEPRECATED
        return SkillLifecycleState.DISCOVERED
    return None
```

- [ ] **Step 1:** 在 registry.py 中添加 lifecycle state 方法
- [ ] **Step 2:** 在 orchestrator 启动日志中打印每个 Skill 的 lifecycle state
- [ ] **Step 3:** 写测试, run, commit

---

## Phase 6: 端到端验证

### Task 6.1: 零改动上线测试

创建一个临时 Skill 目录，验证从发现到消费的全链路不需要改任何其他文件。

```python
@pytest.mark.asyncio
async def test_zero_touch_skill_onboarding(tmp_path):
    # 1. 创建新 Skill
    skill_dir = tmp_path / "test_data_source"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: test_data_source
description: "测试数据源"
version: "1.0"
categories:
  - financial-analysis
  - data-collection
priority: structured_db
keywords:
  - 测试数据
  - test data
capabilities:
  - fetch
action_rules:
  - pattern: ".*"
    actions: [fetch]
action_param_map:
  fetch: {query: query}
supports_topic_fallback: false
is_intrinsic: false
skill_type: standard
data_source_keywords:
  - 测试
aspect_coverage:
  - Test Analysis
---
""")
    (skill_dir / "skill.py").write_text("""
from src.skills.base import Skill
from typing import Any, Dict

class TestDataSourceSkill(Skill):
    @property
    def name(self): return "test_data_source"
    @property
    def description(self): return "Test data source"
    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "fetch")
        if action == "fetch":
            return {
                "success": True,
                "data": {"revenue": 100.5, "net_income": 20.3, "employees": 5000},
                "content": "测试公司: 营收100.5亿, 净利润20.3亿, 员工5000人",
                "source": "test_data_source",
            }
        return {"success": False, "error": "unknown action"}
""")

    # 2. 发现并注册
    from src.skills.registry import SkillRegistry
    registry = SkillRegistry()
    registry.init_from_discovery(tmp_path)

    # 3. 验证注册
    skill = registry.get("test_data_source")
    assert skill is not None, "Skill should be registered"

    # 4. 验证 manifest-driven 路由
    from src.core.decomposition.manifest_strategy import ManifestStrategyBuilder
    builder = ManifestStrategyBuilder(registry.all_manifests())
    
    assert "test_data_source" in builder.build_skill_priority_map()
    assert builder.build_skill_priority_map()["test_data_source"] == "structured_db"
    
    aspect_map = builder.build_aspect_skill_map()
    assert "test_data_source" in aspect_map.get("Test Analysis", [])
    
    ds_map = builder.build_data_source_skill_map()
    assert "test_data_source" in ds_map.get("测试", [])
    
    action_map = builder.build_action_to_skill_map()
    assert action_map.get("fetch") == "test_data_source"

    # 5. 验证执行
    result = await skill.execute(action="fetch", query="test")
    assert result["success"] is True

    # 6. 验证通用数据管道能处理其输出
    # （模拟 _process_skill_output 的核心逻辑）
    data = result.get("data", {})
    content = result.get("content", "")
    assert content  # L1: Skill 自带 content

    from src.core.agents.generic_agent import GenericAgent
    agent = GenericAgent(agent_id="test", agent_type="dynamic", config={})
    metrics = agent._extract_numeric_metrics(data)
    assert "revenue" in metrics
    assert metrics["revenue"] == 100.5
```

- [ ] **Step 1:** Write the test
- [ ] **Step 2:** Run test, fix any failures
- [ ] **Step 3:** Commit

### Task 6.2: 已有 Skill 回归测试

> **新增**：零改动上线测试只验证新 Skill，还需要验证**已有 Skill**（stock_data、xueqiu、search_skill）在新管道下的行为与旧管道一致。

```python
@pytest.mark.asyncio
async def test_stock_data_through_new_pipeline():
    """验证 stock_data 通过 _process_skill_output 获取的数据与旧 _fetch_structured_data 一致"""
    ...

@pytest.mark.asyncio
async def test_xueqiu_through_new_pipeline():
    """验证 xueqiu 通过 _process_skill_output + format_data 获取可读数据"""
    ...

@pytest.mark.asyncio
async def test_search_skill_through_new_pipeline():
    """验证 search_skill 通过 _process_search_skill 获取数据"""
    ...
```

- [ ] **Step 1:** 编写已有 Skill 回归测试
- [ ] **Step 2:** Run tests, fix any failures
- [ ] **Step 3:** Commit

### Task 6.3: 全量回归测试

- [ ] **Step 1:** Run full test suite: `pytest tests/ -q --tb=short`
- [ ] **Step 2:** Run e2e test for report generation
- [ ] **Step 3:** Verify xueqiu data flows correctly through new pipeline
- [ ] **Step 4:** Verify stock_data data flows correctly through new pipeline
- [ ] **Step 5:** Commit

### Task 6.4: 删除 skill_keywords.py

**前置条件**：Task 4.4 完成，所有 discover_skills() 调用已改用 manifest keywords

- [ ] **Step 1:** 搜索项目中所有 `from src.skills.skill_keywords import` 引用
- [ ] **Step 2:** 替换为 manifest-based 替代
- [ ] **Step 3:** 删除 `src/skills/skill_keywords.py`
- [ ] **Step 4:** Run full test suite
- [ ] **Step 5:** Commit

---

## 新增 Skill 检查清单（完成后）

添加一个新 Skill 只需：

```
1. 创建 src/skills/<name>/SKILL.md     # 必需
2. 创建 src/skills/<name>/skill.py     # 可选（纯指令型不需要）
3. 运行测试
```

系统自动：
- ✅ SkillDiscovery 发现并注册
- ✅ ManifestStrategyBuilder 动态构建路由表（ASPECT_SKILL_MAP 等）
- ✅ ACTION_TO_SKILL 从 capabilities 自动构建
- ✅ 关键词匹配从 keywords 自动构建
- ✅ _process_skill_output() 通用数据管道处理任意输出
- ✅ 三层内容转换（content → format_data → LLM总结 → JSON dump）
- ✅ _extract_numeric_metrics() 通用数值提取
- ✅ 下游 Agent 只读 content 字符串，完全不感知 Skill

**不需要修改的文件：**
- ❌ strategies.py
- ❌ generic_agent.py
- ❌ orchestrator.py
- ❌ factory.py
- ❌ skill_keywords.py（已删除）

---

## 执行依赖

```
Phase 1 (迁移) ──────→ Phase 2 (策略动态化) ──→ Phase 4 (Agent通用化)
        │                                              │
        └──→ Phase 3 (通用数据管道) ───────────────────┘
                                                        │
Phase 5 (职责边界 + 生命周期) ──[建议推迟]──────────→ Phase 6 (验证)
```

Phase 1 → Phase 2 → Phase 3 可串行执行。
Phase 4 依赖 Phase 1 + Phase 2 + Phase 3。
Phase 5 建议推迟到 Phase 6 验证通过后，作为独立 PR 实施。
Phase 6 依赖 Phase 1-4。

---

## 审查修订记录

| # | 修订内容 | 原因 |
|---|---------|------|
| 1 | 论证1 补充隐含假设说明 | L3 质量不足以替代结构化映射，structured_db 类 Skill 必需 L2 |
| 2 | 论证2 L1 阈值从 50 改为比较长度策略 | 原阈值 50 过高，短 content（如行情报价）会被跳过 |
| 3 | 论证3 修正行号（调用点 vs 定义位置） | 原文档混淆了调用点和定义位置 |
| 4 | 论证3 补充 B-FIX-3 逻辑保留说明 | 原文档遗漏了跨 Tier 的正则提取逻辑 |
| 5 | 论证4 补充并发安全注意 | `skill._manifest = manifest` 会永久修改实例状态 |
| 6 | Task 1.3 补充"技术"/"创新"关键词到 action_rules | 原 `_infer_stock_actions()` 2737 行有此关键词 |
| 7 | Task 1.3 补充"资产负债"到 data_source_keywords | 当前 DATA_SOURCE_SKILL_MAP 有此条目 |
| 8 | Task 1.3 添加功能变更说明 | stock_data 加入 ASPECT_SKILL_MAP 是行为变更 |
| 9 | Task 1.3 parity test 改为子集验证 | manifest_map 包含更多 Skill，不应要求与硬编码完全一致 |
| 10 | Task 1.7 修正 aliases 实现确保实例共享 | 原方案工厂注册会导致 alias 和原名返回不同实例 |
| 11 | Task 1.7 验证改为 `is` 比较实例同一性 | 确保状态共享 |
| 12 | Task 2.1 复用 SkillRegistries | 避免重复实现 map 构建逻辑 |
| 13 | Task 2.3 补充 ACTION_TO_SKILL 中 web_search 语义不一致说明 | ACTION_TO_SKILL 和 registry 中 web_search 指向不同 Skill |
| 14 | 新增 Task 3.0 行为快照测试 | 重构前必须有覆盖当前行为的测试 |
| 15 | Task 3.1 `_resolve_identifiers` 改为同步方法 | 方法内无 await 调用，不应为 async |
| 16 | Task 3.1 修复 `_manifest` 临时设置后恢复 | 并发安全：try/finally 恢复原值 |
| 17 | Task 3.1 L1 阈值改为比较长度（与 L2 取较长者） | 与当前 `_fetch_structured_data` 逻辑一致 |
| 18 | Task 3.1 L3 跳过 structured_db 类 Skill | 控制成本，structured_db 应实现 format_data |
| 19 | Task 3.1 LLM 摘要字数动态调整 | 小数据 200 字，大数据 500 字 |
| 20 | Task 3.1 补充 call_llm import | 原文档缺少 import |
| 21 | Task 3.1 修正 NewsSearchSkill 返回格式 | results 在顶层而非 data 子键下 |
| 22 | Task 3.2 保留 B-FIX-3 逻辑 | 原统一循环遗漏了正则提取逻辑 |
| 23 | Task 4.3 改为统一 `registry.get("search_skill")` | `get_by_capability()` 返回不确定，直接查找更明确 |
| 24 | Task 4.4 补充 difflib fallback | 防止匹配能力降级 |
| 25 | Phase 5 标记为建议推迟 | 无实际需求，避免过度设计 |
| 26 | 新增 Task 6.2 已有 Skill 回归测试 | 零改动测试只验证新 Skill，遗漏已有 Skill |
| 27 | Task 4.2 修正方法定义行号 | 原文档行号与实际代码一致，但 _format_key_metrics 在 2627 而非 2600 |
| 28 | **[严重]** 新增 Task 1.3a：修复 `infer_actions()` 为累加匹配模式 | `base.py:infer_actions()` 是排他匹配（return first match），而 `_infer_stock_actions()` 是累加匹配（actions 累加去重）。action_rules 翻译依赖累加语义才能正确工作。例如 aspect="盈利估值分析" 时排他匹配只返回 `["financials"]`，丢失 `key_metrics` |
| 29 | Task 1.3 补充"回报"关键词到 action_rules | 原 `_infer_stock_actions()` 2739 行有 `"回报"` 关键词，plan 的 action_rules 遗漏 |
| 30 | Task 3.1 `_llm_summarize_data` docstring 修正 | 原注释 `routing_hint="fast"` 已修正为 `RoutingHint(action="data_summarization")`，docstring 应同步更新 |
| 31 | Task 4.3 修正"12处"为实际数量 | 实际只有 4 处 `registry.get("web_search")` + 5 处 `registry.get("search_skill")`，共 9 处 |
| 32 | Task 2.3 `_build_action_to_skill_map` 补全显式覆盖 | 原方案遗漏 `generate_pptx`→`pptx_skill`、`tavily_search`→`lc_tavily_search`、`arxiv_search`→`lc_arxiv`、`wiki_search`/`wikipedia_search`→`lc_wikipedia`、`python_repl`→`lc_python_repl` 5 个条目 |
| 33 | **[严重]** 新增 F1-F13 防御性设计审查 + 修复 | 审查了 13 个故障模式：返回 None/非 dict(F1/F2)、循环引用(F3)、不可序列化对象(F4)、巨型数据(F5)、data=None(F6)、执行卡死(F9)、identifier 膨胀(F11)、news 非dict 元素(F12)、参数不匹配(F13)。核心修复：`asyncio.wait_for` 超时保护、`json.dumps(default=str)` 不可序列化兜底、`isinstance` 类型检查、`identifiers[:5]` 数量限制、`try/except ValueError` 循环引用兜底 |
| 34 | **[严重]** 新增附录 A：数据流兼容性分析 | 逐类型追踪 4 种数据（structured_db/web_search/news_search/annual_report）在新旧管道下的完整生命周期，识别 3 个数据丢失风险点 |
| 35 | search SKILL.md 描述修正"5引擎"→"6引擎" | 实际代码有 5 个 SEARCH_ENGINES 条目 + DuckDuckGo（通过 DDGS 库单独处理）= 6 个后端 |
| 36 | Task 1.3 补充 xueqiu SKILL.md 已存在说明 | `src/skills/xueqiu/SKILL.md` 已是完整的 127 行 SKILL.md，不需要重新创建，只需验证/更新。遗漏了 `user_posts` capability |
| 37 | Task 1.3 补充 xueqiu 行为变更说明 | xueqiu SKILL.md 已有 `aspect_coverage`，而 `ASPECT_SKILL_MAP` 中没有 xueqiu。ManifestStrategyBuilder 会将 xueqiu 加入 DEEP_ANALYSIS 阶段的 Skill 列表，与 stock_data 一样是行为变更 |
| 38 | Task 1.7 修正 aliases 闭包实现 | 原闭包 `_alias_factory` 调用 `_factory()` 会创建新实例。修正为：先检查 `self._skills[_name]` 是否已有实例，有则直接返回，无则通过原名 factory 创建并存入 `self._skills[_name]`，确保 alias 和原名始终共享同一实例 |
| 39 | Task 1.7 修正 `_memory_cache` 引用 | SearchSkill 实际没有 `_memory_cache` 属性。改为泛化表述"未来添加缓存等状态时实例不共享会导致数据不一致" |
| 40 | Task 3.1 修正 L3 `str(data)` 截断不一致 | 防御性设计章节（960-963 行）先截断 `data_preview` 再判断长度，但 L3 实际代码（1281 行）直接用 `len(str(data))` 无截断。统一为先截断再判断，避免巨型 data 消耗内存 |
| 41 | Task 3.4 补全 XueqiuSkill.format_data() 覆盖所有 8 个 action | 原方案只覆盖 quote/kline/hot_stocks/search_and_quote 4 个 action，遗漏 search/hot_posts/user_posts/check 4 个。同时需更新 xueqiu SKILL.md 的 capabilities 列表补充 `user_posts` |
| 42 | Task 4.3 修正 search_skill 引用计数 | 实际代码中 `registry.get("web_search")` 4 处 + `registry.get("search_skill")` 4 处 = 8 处（164 行在 docstring 注释中，不计入）。原修订 #31 的"9处"有误 |
| 43 | **[严重]** 重写论证5：Skill 输出类型分类 | 原"Skill 只输出数据"是错误的。实际有 5 种输出类型：结构化数据、搜索结果、文件产物、指令/知识、业务流程。`_process_skill_output()` 三层转换只适用于数据类 Skill，文件产物类和业务流程类 Skill 需要不同的消费策略。同时修正 Architecture 描述第(3)点 |
| 44 | Task 3.2 重构循环添加 `tier == "llm"` 跳过检查 | 防御性保护：非数据类 Skill（docx_skill 等 priority=llm）不应走数据管道。当前 execution_order 天然不包含它们，但添加显式检查更安全 |
| 45 | **[严重]** Task 3.1 `_process_skill_output` 统一存储按 priority 区分 quality_score/credibility | 原方案对所有 Skill 硬编码 `quality_score: 95, credibility: "structured_source", type: "structured"`。但未来新增的 web_search 类 Skill（非 search_skill/news_search）走通用路径会得到错误的评分。修改为从 `manifest.priority` 推断：structured_db=95/structured_source/structured，其他=50/search_result/web |
| 46 | **[严重]** Task 3.2 canonical_metrics caliber 按 tier 区分 | 原方案所有 canonical_metrics 以 `caliber="structured_source"` 写入 SharedMemory。但 search_skill/news_search 的指标应以 `caliber="search_result"` 写入。修改为 `caliber = "structured_source" if tier == "structured_db" else "search_result"` |
| 47 | Task 2.1 `build_action_to_skill_map` 补充 capabilities_map 覆盖说明 | `discovery.py:_build_capabilities_map()` 中，多个 Skill 共享同一 capability 时后遍历的覆盖先遍历的。例如 search_skill 和 news_search 都有 `search` capability，news_search 会覆盖 search_skill。显式覆盖（`result["search"] = "search_skill"`）是必需的 |
| 48 | Task 4.3 补充 `multi_search`/`baidu_search` 遗留名称清理 | 当前代码有 3 处 `registry.get("multi_search")` 和 1 处 `registry.get("baidu_search")` 作为 fallback，但 registry 中不存在这些 Skill，始终返回 None。替换时应一并删除 |
| 49 | Task 1.5 LangChain manifest 双重注册修复 | `init_from_discovery()` 在 `skill_type == "langchain"` 时跳过 factory 注册但仍注册了 manifest（592 行），`auto_discover_langchain_tools()` 也会注册 manifest。修复：langchain manifest 的注册也应延迟到 `auto_discover_langchain_tools()` |

---

## 附录 A：数据流兼容性分析

> **目的**：回答"新管道下数据能否正常流转"——逐类型追踪每种数据从 Skill 输出到下游消费的完整路径，识别数据丢失风险。

### A.1 数据流总览

```
Skill.execute() → _process_skill_output() → data_points[] → engine._execute_batch()
    → aggregated_data_points → task dict → DEEP_ANALYSIS/SYNTHESIS Agent → LLM prompt
    → canonical_metrics → SharedMemory.write_canonical() → engine._canonical_registry
    → _active_canonical_data → SharedMemory.set("_canonical_registry") → Agent read
```

### A.2 逐类型数据流追踪

#### 类型 1: structured_db（stock_data / xueqiu）

**旧管道** (`_fetch_structured_data`, generic_agent.py:2313):
```
stock_data.execute() → result["data"] = {financials: [...], key_metrics: [...]}
  → _format_structured_data() → data_points = [{content: "格式化文本", url: "stock_data"}, ...]
  → _extract_numeric_metrics() → canonical_metrics = {"净利润": 150.5, "营收": 1200, ...}
  → return {data_points, sources, canonical_metrics}
```

**新管道** (`_process_skill_output`, Task 3.1):
```
stock_data.execute() → result["data"] = {financials: [...], key_metrics: [...]}
  → L1: result.get("content") → None (stock_data 不返回 content)
  → L2: skill.format_data() → 格式化文本 (需 Task 3.3 实现)
  → L3: 跳过 (structured_db 类 Skill 跳过 L3，见 Task 3.1 修订 #18)
  → content = L2 输出
  → data_points = [{content: L2输出, url: "stock_data"}, ...]
  → _extract_numeric_metrics(result["data"]) → canonical_metrics
  → return {data_points, sources, canonical_metrics}
```

**兼容性结论**: ✅ 兼容，**前提是 Task 3.3 正确实现 `format_data()`**。如果 `format_data()` 未实现或返回空，L1 和 L3 都跳过，最终走 `json.dumps(data, ensure_ascii=False)` 兜底——数据不丢失但可读性差。

**⚠️ 风险 R1**: `_format_structured_data()` (generic_agent.py:2512) 包含 `_FINANCIALS_KEY_COLUMNS` 和 `_THS_METRIC_CN` 映射表（2512-2560 行），这些映射必须完整迁移到 `stock_data.format_data()` 中。遗漏任何列映射会导致对应数据点消失。

#### 类型 2: web_search（search_skill）

**旧管道** (`_do_deep_research`, generic_agent.py:2895):
```
search_skill.execute(query=...) → result["results"] = [{title, body, href, ...}, ...]
  → _do_deep_research 遍历 result["results"]
  → data_points.append({title, content: body, url: href, quality_score, credibility})
  → sources.append({title, url: href, type: "web", quality_score})
```

**新管道** (`_process_skill_output` + `_process_search_skill`, Task 3.1/4.3):
```
search_skill.execute(query=...) → result["results"] = [{title, body, href, ...}, ...]
  → _process_search_skill() 识别为搜索类 Skill
  → 遍历 result["results"]，构建 data_points/sources（与旧管道相同结构）
```

**兼容性结论**: ✅ 兼容。`_process_search_skill()` 是从 `_do_deep_research` 提取的，逻辑完全一致。

**⚠️ 风险 R2**: `_do_deep_research` 还包含 `preloaded_search_results` 合并逻辑（2895-2920 行）和 `depth` 控制（basic vs deep 查询数量）。这些逻辑在 Task 4.3 重构时必须保留在调用方（DATA_COLLECTION 循环），不能移入 `_process_search_skill()`。

#### 类型 3: news_search（NewsSearchSkill）

**旧管道** (generic_agent.py:544-576):
```
news_skill.execute(query=..., max_results=..., time_range="w")
  → result = {success: True, results: [{title, body, href, source, date}, ...]}
  → 遍历 result.get("results", [])
  → data_points.append({title, content: body, url: href, quality_score: 70,
                        credibility: "news_source", source_type: "news",
                        source_name: nr.get("source",""), date: nr.get("date","")})
  → sources.append({title, url: href, type: "news", quality_score: 70})
```

**新管道**:
```
news_skill.execute() → result = {success: True, results: [...]}
  → _process_search_skill() 识别为搜索类 Skill
  → 遍历 result["results"]
  → data_points.append({title, content, url, ...})
```

**兼容性结论**: ⚠️ **部分兼容，有字段丢失风险**。

**⚠️ 风险 R3**: 旧管道为 news data_points 添加了 4 个额外字段：`quality_score: 70`, `credibility: "news_source"`, `source_type: "news"`, `source_name`, `date`。新管道的 `_process_search_skill()` 如果只构建通用搜索 data_point 结构 `{title, content, url}`，这些字段会丢失。下游 DEEP_ANALYSIS Agent 的 prompt 模板可能依赖 `source_type: "news"` 来区分新闻与网页搜索结果。

**修复建议**: `_process_search_skill()` 必须检测 Skill 名称或 manifest 中的 `categories`，为 news 类 Skill 附加 `source_type: "news"`, `credibility: "news_source"`, `quality_score: 70` 等字段。或者在 `_process_skill_output()` 中统一从 manifest 的 `priority` 字段推断 `credibility` 和 `quality_score`。

#### 类型 4: annual_report（document_context 预加载）

**旧管道** (generic_agent.py:504):
```
task.get("document_context") → _has_doc_data_t2 = True
  → 跳过 Tier 2 web_search
  → data_points 来自 Tier 1 structured_db + 预加载的 document_context
```

**新管道**: 无变化——document_context 判断逻辑在 DATA_COLLECTION 循环中，不在 `_process_skill_output()` 内。

**兼容性结论**: ✅ 兼容，不受新管道影响。

### A.3 data_points 聚合与分发

**engine.py 聚合逻辑** (2050-2101 行):
```python
aggregated_data_points = []
for prev_result in previous_results:
    if "data_points" in prev_result:
        aggregated_data_points.extend(prev_result["data_points"])
```

**关键观察**: engine 只关心 `result["data_points"]` 是否存在且为 list。新管道的 `_process_skill_output()` 必须确保返回的 `data_points` 是 list[dict]，每个 dict 至少包含 `content` 和 `url` 字段。当前 `_ensure_standard_result()` (1631 行) 会将 `results` 字段转为 `result` 文本，但**不会**自动构建 `data_points`——这是 `_process_skill_output()` 的职责。

### A.4 canonical_metrics 流转

**写入路径**:
1. `_fetch_structured_data()` → `structured.get("canonical_metrics", {})` → `SharedMemory.write_canonical(caliber="structured_source")` (486-493 行)
2. B-FIX-3 正则提取 → `SharedMemory.write_canonical(caliber="search_result")` (578-611 行)
3. engine S-FIX-2 → `MetricExtractor.extract(data_points)` → `CanonicalDataEntry` → `_canonical_registry.register()` (1356-1388 行)

**新管道影响**:
- 路径 1: `_process_skill_output()` 内部调用 `_extract_numeric_metrics()`，返回 `canonical_metrics`，调用方写入 SharedMemory。✅ 兼容
- 路径 2: B-FIX-3 正则提取在 Task 3.2 中保留在统一循环内。✅ 兼容（需验证 Task 3.2 实现）
- 路径 3: engine 的 S-FIX-2 从 `data_points` 提取，不依赖 Skill 输出格式。✅ 兼容

**caliber 优先级**: `structured_source(100) > search_result(50) > unknown(0)`。新管道必须确保 structured_db Skill 的 canonical_metrics 以 `caliber="structured_source"` 写入，web_search 以 `caliber="search_result"` 写入。当前方案中 caliber 由调用方根据 Skill tier 决定，不受 `_process_skill_output()` 影响。✅ 兼容

### A.5 数据丢失风险汇总

| # | 风险 | 严重度 | 影响范围 | 修复位置 |
|---|------|--------|---------|---------|
| R1 | `_FINANCIALS_KEY_COLUMNS` / `_THS_METRIC_CN` 映射未完整迁移到 `format_data()` | 高 | stock_data 的财务数据点消失 | Task 3.3 |
| R2 | `preloaded_search_results` 合并和 `depth` 控制逻辑丢失 | 中 | 搜索结果不完整 | Task 4.3 |
| R3 | news data_points 丢失 `source_type`/`credibility`/`quality_score`/`date` 字段 | 中 | 下游无法区分新闻与网页，排序/过滤失效 | Task 3.1 `_process_search_skill()` |

### A.6 结论

**数据能否正常流转？** 大体可以，但有 3 个必须修复的风险点：

1. **R1 是阻断性的**——如果 `format_data()` 未正确迁移列映射，stock_data 的核心财务数据会从 data_points 中消失，导致报告缺少关键数值。Task 3.3 必须包含与 `_format_structured_data()` 的逐字段对比验证。
2. **R2 和 R3 是降级性的**——数据不会完全丢失，但会缺少元数据字段，影响下游的排序、过滤和来源区分。应在 Task 3.1 和 Task 4.3 中显式处理。

**建议**: 在 Task 6.2 回归测试中，对每种数据类型编写"字段完整性断言"——不仅验证 data_points 非空，还验证每个 data_point 包含旧管道的所有字段。
