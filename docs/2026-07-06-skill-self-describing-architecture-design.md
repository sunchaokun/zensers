# Skill 自描述架构重构方案

> 日期: 2026-07-06
> 状态: 审查中
> 目标: 新增 1 个 Skill 只需创建 1 个目录 + SKILL.md(+ 可选 skill.py)，零其他文件改动

---

## 1. 问题诊断

### 1.1 现状：15 处手动触点

新增一个 Skill（如 xueqiu）需要手动修改 **8 个文件、15 个位置**：

| # | 文件 | 改什么 | 类型 |
|---|------|--------|------|
| 1 | `src/skills/analysis/__init__.py` | import + `__all__` | 导出 |
| 2 | `src/skills/registry.py` → `register_core_skills()` | import + `self.register()` | 注册 |
| 3 | `src/skills/registry.py` → `CATEGORY_TO_SKILLS` | 分类列表 | 分类 |
| 4 | `src/skills/skill_keywords.py` → `SKILL_KEYWORDS` | 关键词集合 | 关键词 |
| 5 | `src/skills/skill_keywords.py` → `get_skill_description()` | 描述字符串 | 描述 |
| 6 | `src/core/decomposition/strategies.py` → `SKILL_PRIORITY_MAP` | 优先级分层 | 分层 |
| 7 | `src/core/decomposition/strategies.py` → `DATA_SOURCE_SKILL_MAP` | 数据源映射 | 路由 |
| 8 | `src/core/decomposition/strategies.py` → `ASPECT_SKILL_MAP` | 研究维度映射 | 路由 |
| 9 | `src/core/decomposition/strategies.py` → `STRUCTURED_DATA_CAPABILITIES` | 能力声明 | 能力 |
| 10 | `src/core/orchestrator/orchestrator.py` | import + factory 注册 | 注册 |
| 11 | `src/core/agents/generic_agent.py` → `ACTION_TO_SKILL` | action 路由 | 路由 |
| 12 | `src/core/agents/generic_agent.py` → `_fetch_structured_data()` | skill-specific 分支 | 执行 |
| 13 | `src/core/agents/generic_agent.py` → `_infer_*_actions()` | action 推断 | 推断 |
| 14 | `src/core/agents/factory.py` → `_SKILL_ALIAS_MAP` | 别名映射 | 别名 |
| 15 | `config/keyword_mappings.yaml` → `skill_inference` | YAML 关键词（注：xueqiu 条目已存在，但 stock_data 缺失） | 配置 |

### 1.2 根因

1. **Skill 不能自描述** — 系统不知道一个 skill 支持什么 action、属于什么分类、匹配什么关键词，必须在 6+ 个地方手动声明
2. **没有自动发现** — 放个文件在 skills/ 目录，系统不会识别
3. **Agent 紧耦合** — `generic_agent.py` 内写 `_infer_stock_actions()` + `_infer_xueqiu_actions()` 等 skill-specific 方法，每加一个 skill 就改 agent 代码
4. **数据散布** — 同一个 skill 的关键词同时存在于 `skill_keywords.py`（Python dict）和 `keyword_mappings.yaml`（YAML），两者不同步
5. **格式化逻辑外泄** — `_format_structured_data()` 等 5 个方法 + `_FINANCIALS_KEY_COLUMNS` / `_THS_METRIC_CN` 2 个常量包含 stock_data 的字段名和格式化逻辑，应在 skill 内部

### 1.3 不改的后果

- 10 个 skill → 150+ 处手动维护，遗漏率近 100%
- 新 skill 上线周期 = 开发 + 改 8 个文件 + 排查遗漏 + 回归测试
- 死条目累积（现有 `wind_data`、`bloomberg_data` 等未实现的条目散布在各 map 中）

---

## 2. 目标架构

### 2.1 核心原则

**SKILL.md（必需）+ Python 代码（可选）+ 自描述元数据**

与 opencode / Claude Code 的 Skill 体系完全对齐：

| 类型 | SKILL.md | skill.py | 执行方式 |
|------|----------|----------|----------|
| 纯指令型 | ✅ 必需 | 无 | Agent 读取 SKILL.md 指令自行完成 |
| 代码型 | ✅ 必需 | ✅ 必需 | 系统实例化 Python 类执行 |

### 2.2 目录结构

> **注意**：以下为重构后的目标目录结构。当前实际文件布局为：
> - 代码型 skill 分散在 `src/skills/` 根目录（`search_skill.py`, `file_skill.py` 等）和 `src/skills/analysis/` 子目录（`stock_data.py`, `xueqiu_skill.py` 等）
> - `news_search` 是 `search_skill.py` 中的 `NewsSearchSkill` 类，无独立文件
> - `market_analysis`, `stock_analysis`, `data_analysis`, `policy_analysis`, `tech_trend`, `risk_analysis` 在 `src/skills/analysis/` 下，但未被 `register_core_skills()` 注册，仅在 `SKILL_KEYWORDS` 和 `ASPECT_SKILL_MAP` 中有引用（虚拟条目）
> - `knowledge_query` 在 `src/skills/builtin/` 下，已通过 `register_core_skills()` 注册
> - LangChain 型 skill 无 Python 文件，由 `registry.py` 的 `_create_*_skill()` 方法动态创建

```
src/skills/
├── search/                    # 代码型（当前: search_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── news_search/               # 代码型（当前: search_skill.py 中的 NewsSearchSkill）
│   ├── SKILL.md
│   └── skill.py
├── xueqiu/                    # 代码型（structured_db，当前: analysis/xueqiu_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── stock_data/                # 代码型（structured_db，当前: analysis/stock_data.py）
│   ├── SKILL.md
│   └── skill.py
├── stock_analysis/            # 代码型（当前: analysis/stock_analysis.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── market_analysis/           # 代码型（当前: analysis/market_analysis.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── data_analysis/             # 代码型（当前: analysis/data_analysis.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── policy_analysis/           # 代码型（当前: analysis/policy_analysis.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── tech_trend/                # 代码型（当前: analysis/tech_trend.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── risk_analysis/             # 代码型（当前: analysis/risk_analysis.py，虚拟条目）
│   ├── SKILL.md
│   └── skill.py
├── annual_report_parser/      # 代码型（当前: analysis/annual_report_parser.py）
│   ├── SKILL.md
│   └── skill.py
├── knowledge_query/           # 代码型(builtin)（当前: builtin/knowledge_query_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── llm/                       # 纯指令型（当前: llm_skill.py，已注册但标记 deprecated）
│   └── SKILL.md
├── web_scraper/               # 代码型（当前: web_scraper_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── file/                      # 代码型（当前: file_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── http/                      # 代码型（当前: http_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── docx/                      # 代码型（当前: docx_skill.py）
│   ├── SKILL.md
│   └── skill.py
├── lc_tavily_search/          # LangChain 型（无 Python 文件，registry._create_tavily_skill）
│   └── SKILL.md               # skill_type: langchain
├── lc_arxiv/
│   └── SKILL.md
├── lc_wikipedia/
│   └── SKILL.md
├── lc_python_repl/
│   └── SKILL.md
├── discovery.py               # 新增：自动发现引擎
├── base.py                    # 现有：Skill 基类 + 简化版 SkillRegistry（hot_reload 用，不合并）
├── registry.py                # 现有：完整版 SkillRegistry（增强，不合并）
└── skill_keywords.py          # 现有：废弃，数据来自 SKILL.md
```

### 2.3 SKILL.md 规范

YAML front matter（机器可读元数据）+ Markdown body（AI 可读指令）：

```markdown
---
name: xueqiu
description: 雪球实时行情/热门股票/热帖/K线 (A股/港股/美股)
version: "1.0"
categories:
  - financial-analysis
  - research
  - data-collection
priority: structured_db
keywords:
  - 雪球
  - 行情
  - 港股
  - 美股
  - 热门股
  - 换手率
  - 实时行情
  - K线
aliases:
  - xueqiu_stock
  - stock_quote
capabilities:
  - quote
  - kline
  - hot_stocks
  - search
  - search_and_quote
  - hot_posts
  - check
data_types:
  zh:
    - 股价
    - 估值
    - 换手率
    - 热门股
    - 实时行情
data_source_keywords:
  - 财务
  - 估值
  - 公司
  - 盈利
  - 营收
  - 市值
  - 市场规模
  - 行情
  - 热门
  - 港股
  - 美股
  - 趋势
  - 竞争
action_rules:
  - pattern: "^(SH|SZ|BJ)?\\d{6}$"    # A股代码（前缀可选，匹配 SH600519 和 600519）
    aspect_keywords: [竞争, 热门, 人气, 排行, competitive, hot]
    actions: [quote, kline, hot_stocks]
  - pattern: "^(SH|SZ|BJ)?\\d{6}$"
    actions: [quote, kline]
  - pattern: ".*"                       # 非A股代码（港股/美股/中文名）→ search_and_quote
    actions: [search_and_quote]
action_param_map:
  quote: {symbol: symbol}
  kline: {symbol: symbol}
  hot_stocks: {}
  search: {query: query}
  search_and_quote: {query: symbol}
  hot_posts: {}
  check: {}
supports_topic_fallback: true
topic_fallback_pattern: "[\\u4e00-\\u9fff]+"
is_intrinsic: false
skill_type: standard
aspect_coverage:
  - Financial Analysis
  - 财务分析
  - Valuation
  - 估值分析
  - Company Research
  - 公司研究
  - Investment Analysis
  - 投资分析
  - Competitive Landscape
  - 竞争格局
  - Industry Research
  - 行业研究
---

# Xueqiu Skill

## When to use
用户需要实时股票行情、港股/美股数据、热门股票排名时使用。
当 EntityResolver 无法解析港股/美股代码时，xueqiu 可通过 search_and_quote 用中文名搜索。

## Actions

| Action | 描述 | 必需参数 | 可选参数 |
|--------|------|----------|----------|
| quote | 获取股票实时报价 | symbol | - |
| kline | 获取K线历史数据 | symbol | period, count |
| hot_stocks | 获取热门股票排名 | - | limit |
| search | 搜索股票 | query | limit |
| search_and_quote | 搜索并获取报价 | query | - |
| hot_posts | 获取热门帖子 | - | limit |
| check | 检查API连通性 | - | - |

## Notes
- 未登录时 quote/hot_stocks/search 自动通过 Screener 公共 API 降级
- kline 需要登录 Cookie，Screener 无法提供
- symbol 格式: A股=SH600519/SZ002594, 港股=00700, 美股=AAPL
```

### 2.4 SKILL.md 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | Skill 唯一标识，全小写 + 下划线 |
| `description` | string | ✅ | 一句话描述 |
| `version` | string | ✅ | 语义化版本 |
| `categories` | list[str] | ✅ | 所属分类，用于 `CATEGORY_TO_SKILLS` 自动构建 |
| `priority` | enum | ✅ | `structured_db` / `web_search` / `llm` / `enrichment` |
| `keywords` | list[str] | ✅ | 触发关键词，用于 `SKILL_KEYWORDS` 自动构建 |
| `aliases` | list[str] | ❌ | 别名，用于 `_SKILL_ALIAS_MAP` 自动构建 |
| `capabilities` | list[str] | 代码型必需 | 支持的 action 列表 |
| `data_types` | dict | ❌ | 按语言分类的能力描述，用于 `STRUCTURED_DATA_CAPABILITIES` 和 `derive_data_source_type()` |
| `data_source_keywords` | list[str] | ❌ | aspect 关键词匹配列表，用于 `DATA_SOURCE_SKILL_MAP` 自动构建（与 `data_types` 不同：data_types 是结构化能力关键词如"换手率"，data_source_keywords 是 aspect 匹配关键词如"财务"、"估值"） |
| `action_rules` | list[dict] | 代码型必需 | action 推断规则，消灭 `_infer_*_actions()` |
| `action_param_map` | dict | 代码型必需 | action → execute 必需参数映射，消灭 execute 分支。key=参数名，value=来源（`symbol` 表示从 agent 的 symbol 变量取值，`query` 同理）。可选参数不在此映射，由调用者直接传递 |
| `supports_topic_fallback` | bool | ❌ | 是否支持 topic → symbol 降级 |
| `topic_fallback_pattern` | string | ❌ | 从 topic 提取 symbol 的正则 |
| `is_intrinsic` | bool | ❌ | 是否内置 skill（如 llm_skill），默认 false |
| `aspect_coverage` | list[str] | ❌ | 此 skill 可覆盖的研究维度，用于自动构建 ASPECT_SKILL_MAP |
| `skill_type` | enum | ❌ | `standard`（默认）/ `langchain`，LangChain 型使用 registry 已有的创建方法 |

---

## 3. 自动发现引擎

### 3.1 SkillManifest 数据类

```python
# src/skills/discovery.py

@dataclass
class SkillManifest:
    name: str
    description: str
    version: str
    categories: List[str]
    priority: str
    keywords: List[str]
    aliases: List[str]
    capabilities: List[str]
    data_types: Dict[str, List[str]]
    data_source_keywords: List[str]
    action_rules: List[ActionRule]
    action_param_map: Dict[str, Dict[str, str]]
    supports_topic_fallback: bool
    topic_fallback_pattern: Optional[str]
    is_intrinsic: bool
    aspect_coverage: List[str]
    skill_type: str  # "standard" | "langchain"
    skill_dir: Path
    has_code: bool
    instructions: str  # Markdown body

@dataclass
class ActionRule:
    pattern: str
    actions: List[str]
    aspect_keywords: Optional[List[str]] = None
```

### 3.2 SkillDiscovery 类

```python
class SkillDiscovery:
    def discover_all(self, skills_dir: Path) -> List[SkillManifest]:
        manifests = []
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_dir.is_dir() or not skill_md.exists():
                continue
            manifest = self._parse_skill_md(skill_md)
            manifest.skill_dir = skill_dir
            manifest.has_code = (skill_dir / "skill.py").exists()
            manifests.append(manifest)
        return manifests

    def _parse_skill_md(self, path: Path) -> SkillManifest:
        # 解析 YAML front matter + Markdown body
        # 使用 python-frontmatter 或手动解析
        ...

    def load_skill_class(self, manifest: SkillManifest) -> Optional[Type[Skill]]:
        if not manifest.has_code:
            return None
        # importlib 动态导入 skill_dir / "skill.py"
        # 找到 Skill 子类
        ...

    def build_registries(self, manifests: List[SkillManifest]) -> SkillRegistries:
        """从所有 manifest 自动构建全链路注册数据"""
        return SkillRegistries(
            category_to_skills=self._build_category_map(manifests),
            priority_map=self._build_priority_map(manifests),
            keywords_map=self._build_keywords_map(manifests),
            alias_map=self._build_alias_map(manifests),
            capabilities_map=self._build_capabilities_map(manifests),
            action_rules=self._build_action_rules(manifests),
        )
```

### 3.3 自动构建的注册数据

以下数据全部从 SKILL.md 的 YAML front matter 自动生成，**不再手动维护**：

| 原硬编码位置 | 自动构建来源 | 生成逻辑 |
|-------------|-------------|---------|
| `CATEGORY_TO_SKILLS` | `manifest.categories` | 遍历所有 manifest，按 category 分组 |
| `SKILL_PRIORITY_MAP` | `manifest.priority` | `{m.name: m.priority for m in manifests}` |
| `SKILL_KEYWORDS` | `manifest.keywords` | `{m.name: set(m.keywords) for m in manifests}` |
| `_SKILL_ALIAS_MAP` | `manifest.aliases` | 扁平化 alias→name 映射 |
| `ACTION_TO_SKILL` | `manifest.capabilities` | action→skill 反向映射 |
| `ASPECT_SKILL_MAP` | `manifest.aspect_coverage` | 维度→skill 列表，自动添加 llm_skill |
| `STRUCTURED_DATA_CAPABILITIES` | `manifest.data_types` | `{m.name: m.data_types for m in manifests if m.data_types}` |
| `DATA_SOURCE_SKILL_MAP` | `manifest.data_source_keywords` | 反向索引：data_source_keyword→skills |
| `get_skill_description()` | `manifest.description` | `{m.name: m.description for m in manifests}` |

---

## 4. Agent 通用化

### 4.1 消灭 `_infer_*_actions()` — action 推断通用化

**现状**: `_infer_stock_actions()` + `_infer_xueqiu_actions()` 是 skill-specific 方法。

**新方案**: 从 skill 的 `action_rules` 通用匹配：

```python
# generic_agent.py

def _infer_actions(self, skill_name: str, aspect: str, symbol: str) -> List[str]:
    manifest = self._get_manifest(skill_name)
    if not manifest or not manifest.action_rules:
        return ["default"]

    for rule in manifest.action_rules:
        if not re.match(rule.pattern, symbol):
            continue
        if rule.aspect_keywords:
            aspect_lower = (aspect or "").lower()
            if any(kw.lower() in aspect_lower for kw in rule.aspect_keywords):
                return rule.actions
            continue
        return rule.actions  # pattern 匹配且无 aspect 过滤

    return ["default"]
```

**删除**: `_infer_stock_actions()`, `_infer_xueqiu_actions()`。

**`_get_manifest()` 实现**: agent 从 `self._skill_registry.get_manifest(skill_name)` 获取 manifest，在 `__init__` 或首次使用时缓存到 `self._manifests` dict。

### 4.2 消灭 execute 参数分支 — `action_param_map` 通用化

**现状**: `_fetch_structured_data()` 中有 `if skill_name == "xueqiu"` 分支处理 `query=` vs `symbol=`。

**新方案**: 从 `action_param_map` 通用构建 execute 参数：

```python
# generic_agent.py

def _build_execute_kwargs(self, skill_name: str, action: str, symbol: str) -> dict:
    manifest = self._get_manifest(skill_name)
    if manifest and manifest.action_param_map and action in manifest.action_param_map:
        param_map = manifest.action_param_map[action]
        kwargs = {"action": action}
        for param_name, source in param_map.items():
            if source == "symbol":
                kwargs[param_name] = symbol
            elif source == "query":
                kwargs[param_name] = symbol
            # 其他 source 可扩展
        return kwargs
    return {"action": action, "symbol": symbol}
```

**删除**: `_fetch_structured_data()` 中的 `if skill_name == "xueqiu"` 分支。

### 4.3 消灭 topic fallback 硬编码

**现状**: `if skill_name == "xueqiu" and topic:` 专用分支。

**新方案**: 从 manifest 的 `supports_topic_fallback` + `topic_fallback_pattern` 通用处理：

```python
# generic_agent.py 中替换 xueqiu 专用 fallback

if not symbols:
    manifest = self._get_manifest(skill_name)
    if manifest and manifest.supports_topic_fallback and topic:
        m = re.search(manifest.topic_fallback_pattern, topic)
        if m:
            symbols = [m.group(0)]
```

### 4.4 消灭 `llm_skill` 特殊分支

**现状**: `if skill_name == "llm_skill"` 多处硬编码。

**新方案**: manifest 的 `is_intrinsic` 属性：

```python
# 替换
if skill_name == "llm_skill" or skill:
# 为
manifest = self._get_manifest(skill_name)
if (manifest and manifest.is_intrinsic) or skill:
```

### 4.5 消灭 search_skill 多处硬编码查找

**现状**: 12 处 `skill_registry.get("search_skill") or skill_registry.get("web_search") or ...`（generic_agent.py 9 处 + orchestrator.py 2 处 + engine.py 1 处）。

**新方案**: registry 按 capability 查询：

```python
# registry.py 新增方法
def get_by_capability(self, capability: str) -> Optional[Skill]:
    for name, manifest in self._manifests.items():
        if capability in manifest.capabilities:
            instance = self.get(name)
            if instance:
                return instance
    return None

def get_by_priority(self, priority: str) -> List[Skill]:
    results = []
    for name, manifest in self._manifests.items():
        if manifest.priority == priority:
            instance = self.get(name)
            if instance:
                results.append(instance)
    return results
```

```python
# generic_agent.py 替换
search_skill = skill_registry.get_by_capability("search")
```

### 4.6 结构化数据 URL scheme 检测通用化

**现状**: `any(url.startswith(f"{s}://") for s in ("stock_data", "wind_data", "bloomberg_data"))`，3 处。

**新方案**: 统一用 `credibility` 字段判断，不依赖 URL scheme：

```python
# 替换
is_structured = (
    dp.get("credibility") == "structured_source"
    or any(url.startswith(f"{s}://") for s in ("stock_data", "wind_data", "bloomberg_data"))
)
# 为
is_structured = dp.get("credibility") == "structured_source"
```

URL scheme 统一改为 `structured://skill_name/symbol/action`。

### 4.7 格式化逻辑内迁到 Skill

**现状**: `_format_structured_data()`, `_format_financials()`, `_format_price_history()`, `_format_key_metrics()`, `_format_company_info()` 5 个方法 + `_FINANCIALS_KEY_COLUMNS`, `_THS_METRIC_CN` 2 个常量，都是 stock_data skill 的格式化逻辑，放在 agent 中。

**新方案**: Skill 基类增加 `format_data()` 方法，各 skill 自行实现：

```python
# base.py
class Skill(ABC):
    ...
    def format_data(self, data: dict, action: str, symbol: str) -> str:
        return ""  # 默认不格式化，使用 JSON dump

# stock_data/skill.py
class StockDataSkill(Skill):
    def format_data(self, data: dict, action: str, symbol: str) -> str:
        if action == "financials":
            return self._format_financials(data, symbol)
        elif action == "price_history":
            return self._format_price_history(data, symbol)
        ...
```

```python
# generic_agent.py 替换
formatted = self._format_structured_data(data, action, symbol)
# 为
formatted = stock_skill.format_data(data, action, symbol)
```

**删除**: agent 中的 `_format_structured_data()`, `_format_financials()`, `_format_price_history()`, `_format_key_metrics()`, `_format_company_info()` 5 个方法，以及 `_FINANCIALS_KEY_COLUMNS`, `_THS_METRIC_CN` 2 个常量。

---

## 5. Skill 基类增强

### 5.1 新增属性和方法

> **注意**：当前 `src/skills/base.py` 中存在一个简化版 `SkillRegistry`（L91-118，注册 `Type[Skill]` 类），与 `src/skills/registry.py` 中的完整版 `SkillRegistry`（注册 `Skill` 实例 + factory + LangChain 发现）职责不同。`base.py` 版被 `hot_reload.py` 使用，`registry.py` 版被 orchestrator 等核心模块使用。`src/skills/__init__.py` 通过别名 `_BaseSkillRegistry` 同时导出两者。**两者必须共存，不合并**——hot_reload.py 依赖 base.py 版注册 `Type[Skill]` 类的接口，registry.py 版的 `register()` 接受 `Skill` 实例，两者签名不兼容。迁移阶段仅新增 discovery 叠加层，不删除或合并任何一个。

```python
# src/skills/base.py

class Skill(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]: ...

    # ---- 新增 ----

    def format_data(self, data: dict, action: str, symbol: str) -> str:
        """将 execute 返回的 data 格式化为可读文本。子类可覆盖。"""
        return ""

    def infer_actions(self, aspect: str, symbol: str) -> List[str]:
        """根据 aspect 和 symbol 推断应执行的 action 列表。
        默认从 manifest.action_rules 匹配，子类可覆盖实现更复杂逻辑。"""
        manifest = getattr(self, '_manifest', None)
        if manifest and manifest.action_rules:
            for rule in manifest.action_rules:
                if not re.match(rule.pattern, symbol):
                    continue
                if rule.aspect_keywords:
                    aspect_lower = (aspect or "").lower()
                    if any(kw.lower() in aspect_lower for kw in rule.aspect_keywords):
                        return rule.actions
                    continue
                return rule.actions
        return ["default"]

    def resolve_identifier(self, topic: str, aspect: str) -> Optional[str]:
        """从 topic 中提取此 skill 可用的标识符（如股票代码/公司名）。
        默认从 manifest.topic_fallback_pattern 匹配，子类可覆盖。"""
        manifest = getattr(self, '_manifest', None)
        if manifest and manifest.supports_topic_fallback and manifest.topic_fallback_pattern:
            import re
            m = re.search(manifest.topic_fallback_pattern, topic)
            if m:
                return m.group(0)
        return None
```

### 5.2 InstructionSkill — 纯指令型 Skill

```python
# src/skills/base.py

class InstructionSkill(Skill):
    """纯指令型 Skill，无 Python 执行逻辑，仅提供 SKILL.md 指导 AI 完成。"""

    def __init__(self, manifest: SkillManifest):
        self._manifest = manifest
        self._name = manifest.name
        self._description = manifest.description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return {
            "success": True,
            "data": {"instructions": self._manifest.instructions},
            "content": self._manifest.instructions[:500],
            "source": self.name,
        }
```

---

## 6. 注册表重构

### 6.1 SkillRegistry 增强

```python
# src/skills/registry.py

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._factories: Dict[str, Callable[[], Skill]] = {}
        self._manifests: Dict[str, SkillManifest] = {}  # 新增

    def register_manifest(self, manifest: SkillManifest):
        self._manifests[manifest.name] = manifest

    def get_manifest(self, name: str) -> Optional[SkillManifest]:
        return self._manifests.get(name)

    def get_by_capability(self, capability: str) -> Optional[Skill]:
        """按 capability 查找 skill 实例"""
        for name, manifest in self._manifests.items():
            if capability in manifest.capabilities:
                skill = self.get(name)
                if skill:
                    return skill
        return None

    def get_by_priority(self, priority: str) -> List[Skill]:
        """按优先级分层查找 skill 列表"""
        results = []
        for name, manifest in self._manifests.items():
            if manifest.priority == priority:
                skill = self.get(name)
                if skill:
                    results.append(skill)
        return results

    def get_skills_by_category(self, category: str) -> List[str]:
        """按分类查找 skill 名称列表"""
        return [
            name for name, m in self._manifests.items()
            if category in m.categories
        ]

    def all_manifests(self) -> Dict[str, SkillManifest]:
        return dict(self._manifests)
```

### 6.2 启动初始化流程

```python
# src/skills/registry.py → SkillRegistry.init_from_discovery()

def init_from_discovery(self, skills_dir: Path):
    discovery = SkillDiscovery()
    manifests = discovery.discover_all(skills_dir)

    for manifest in manifests:
        # 1. 注册 manifest
        self.register_manifest(manifest)

        # 2. LangChain 型：使用 registry 已有的 _create_*_skill() 方法
        if manifest.skill_type == "langchain":
            creator = self._langchain_creators.get(manifest.name)
            if creator:
                self.register_factory(manifest.name, creator)
            continue

        # 3. 代码型：动态加载 skill 类并注册 factory
        if manifest.has_code:
            skill_cls = discovery.load_skill_class(manifest)
            if skill_cls:
                self.register_factory(manifest.name, skill_cls)
        else:
            # 4. 纯指令型：注册 InstructionSkill factory
            self.register_factory(
                manifest.name,
                lambda m=manifest: InstructionSkill(m)
            )

    # 5. 启动校验
    self._validate_manifests()
```

### 6.3 启动校验

```python
def _validate_manifests(self):
    """校验 manifest 完整性，warn 不阻塞"""
    for name, manifest in self._manifests.items():
        # 检查代码型 skill 是否有对应类
        if manifest.has_code and name not in self._factories and name not in self._skills:
            logger.warning(f"Skill '{name}' has skill.py but no Skill subclass found")

        # 检查 action_param_map 覆盖所有 capabilities
        if manifest.action_param_map:
            for cap in manifest.capabilities:
                if cap not in manifest.action_param_map:
                    logger.warning(f"Skill '{name}' capability '{cap}' not in action_param_map")

        # 检查 action_rules 的 actions 都在 capabilities 中
        if manifest.action_rules:
            for rule in manifest.action_rules:
                for action in rule.actions:
                    if action not in manifest.capabilities:
                        logger.warning(f"Skill '{name}' action_rule references '{action}' not in capabilities")
```

---

## 7. strategies.py 重构

### 7.1 硬编码 dict → 从 manifest 动态生成

```python
# src/core/decomposition/strategies.py

# 删除以下硬编码：
# - SKILL_PRIORITY_MAP
# - DATA_SOURCE_SKILL_MAP
# - STRUCTURED_DATA_CAPABILITIES
# - ASPECT_SKILL_MAP 中的 skill 列表部分

# 新增：从 registry 的 manifest 数据构建

def build_skill_priority_map(registry: SkillRegistry) -> Dict[str, str]:
    return {name: m.priority for name, m in registry.all_manifests().items()}

def build_data_source_skill_map(registry: SkillRegistry) -> Dict[str, List[str]]:
    """从 manifest.data_source_keywords 反向构建 aspect_keyword → skill 列表。

    注意：此映射与 data_types 不同。data_types 用于 derive_data_source_type()，
    而 data_source_keywords 用于 _get_data_collection_skills() 的 aspect 关键词匹配。
    两者需在 SKILL.md 中分别声明。
    """
    result = {}
    for name, manifest in registry.all_manifests().items():
        for keyword in (manifest.data_source_keywords or []):
            result.setdefault(keyword, [])
            if name not in result[keyword]:
                result[keyword].append(name)
    return result

def build_structured_data_capabilities(registry: SkillRegistry) -> Dict[str, Dict[str, List[str]]]:
    return {
        name: m.data_types
        for name, m in registry.all_manifests().items()
        if m.data_types and m.priority == "structured_db"
    }

def build_category_to_skills(registry: SkillRegistry) -> Dict[str, List[str]]:
    result = {}
    for name, manifest in registry.all_manifests().items():
        for cat in manifest.categories:
            result.setdefault(cat, [])
            result[cat].append(name)
    return result

def build_aspect_skill_map(registry: SkillRegistry) -> Dict[str, List[str]]:
    """从 manifest.aspect_coverage 构建 ASPECT_SKILL_MAP。
    每个 skill 声明它能覆盖的研究维度，反向索引后与 llm_skill 合并。"""
    result = {}
    for name, manifest in registry.all_manifests().items():
        for aspect in (manifest.aspect_coverage or []):
            result.setdefault(aspect, [])
            if name not in result[aspect]:
                result[aspect].append(name)
    # 所有维度都加入 llm_skill
    llm = "llm_skill"
    for aspect in result:
        if llm not in result[aspect]:
            result[aspect].insert(0, llm)
    return result
```

### 7.2 _get_data_collection_skills 简化

```python
def _get_data_collection_skills(aspect: str, topic: str = "", intent_result: Any = None,
                                 registry: SkillRegistry = None) -> List[str]:
    if not registry:
        return ["search_skill", "llm_skill"]

    skills = set()

    # 从 data_source_keywords 匹配
    data_source_map = build_data_source_skill_map(registry)
    aspect_lower = (aspect or "").lower()
    for keyword, skill_list in data_source_map.items():
        if keyword.lower() in aspect_lower:
            skills.update(skill_list)

    # intent 路径：从 primary_research_type 推断需要的 structured_db skills
    if intent_result:
        primary_type = getattr(intent_result, 'primary_research_type', None)
        if primary_type and getattr(primary_type, 'value', '') in (
            "company_research", "investment", "competitive_analysis",
            "industry_research", "brand_research",
        ):
            for name, manifest in registry.all_manifests().items():
                if manifest.priority == "structured_db":
                    skills.add(name)

    # 始终包含 web_search 和 llm
    for s in registry.get_skills_by_category("data-collection"):
        skills.add(s)
    skills.add("llm_skill")

    # 按 priority 排序
    _TIER_ORDER = ["structured_db", "enrichment", "web_search", "llm"]
    priority_map = build_skill_priority_map(registry)
    return sorted(skills, key=lambda s: _TIER_ORDER.index(priority_map.get(s, "web_search")))
```

---

## 8. 迁移计划

### Phase 1：基础设施（不破坏现有代码）

**目标**：建 SkillDiscovery + SkillManifest + 自动构建逻辑，与旧代码并行运行。

| 步骤 | 内容 | 风险 |
|------|------|------|
| 1.1 | 新建 `src/skills/discovery.py`（SkillDiscovery + SkillManifest + ActionRule） | 无 |
| 1.2 | 增强 `src/skills/base.py`（format_data, infer_actions, resolve_identifier, InstructionSkill） | 无 |
| 1.3 | 增强 `src/skills/registry.py`（register_manifest, get_by_capability, get_by_priority, init_from_discovery） | 无 |
| 1.4 | 在启动流程中调用 `init_from_discovery()`，将结果与旧硬编码 dict 对比，仅 log diff 不替换 | 无 |
| 1.5 | 编写单元测试验证 discovery 和自动构建的正确性 | 无 |

### Phase 2：迁移现有 Skill（逐个迁移，旧触点逐个删除）

**目标**：每个 skill 迁移到目录式 + SKILL.md，删除对应的硬编码条目。

迁移顺序（从简单到复杂）：

| 批次 | Skill | 类型 | 复杂度 | 迁移动作 |
|------|-------|------|--------|----------|
| 2.1 | llm | 纯指令型 | 低 | 创建 llm/SKILL.md，is_intrinsic=true |
| 2.2 | search | 代码型 | 低 | search/SKILL.md + 迁移 SearchSkill |
| 2.3 | news_search | 代码型 | 低 | news_search/SKILL.md + 迁移 NewsSearchSkill |
| 2.4 | file | 代码型 | 中 | file/SKILL.md + 迁移 FileSkill |
| 2.5 | http | 代码型 | 中 | http/SKILL.md + 迁移 HTTPSkill |
| 2.6 | docx | 代码型 | 中 | docx/SKILL.md + 迁移 DocxSkill |
| 2.7 | pptx | 代码型 | 中 | pptx/SKILL.md + 迁移 PptxSkill（如存在） |
| 2.8 | web_scraper | 代码型 | 中 | web_scraper/SKILL.md + 迁移 WebScraperSkill |
| 2.9 | knowledge_query | 代码型(builtin) | 中 | knowledge_query/SKILL.md + 迁移（当前位于 src/skills/builtin/，迁移时移至 src/skills/knowledge_query/） |
| 2.10 | annual_report_parser | 代码型 | 中 | annual_report_parser/SKILL.md + 迁移 |
| 2.11 | market_analysis | 代码型 | 中 | market_analysis/SKILL.md + 迁移 MarketAnalysisSkill |
| 2.12 | data_analysis | 代码型 | 中 | data_analysis/SKILL.md + 迁移 DataAnalysisSkill |
| 2.13 | stock_analysis | 代码型 | 中 | stock_analysis/SKILL.md + 迁移 StockAnalysisSkill |
| 2.14 | policy_analysis | 代码型 | 中 | policy_analysis/SKILL.md + 迁移 PolicyAnalysisSkill |
| 2.15 | tech_trend | 代码型 | 中 | tech_trend/SKILL.md + 迁移 TechTrendSkill |
| 2.16 | risk_analysis | 代码型 | 中 | risk_analysis/SKILL.md + 迁移 RiskAnalysisSkill |
| 2.17 | lc_tavily_search | 代码型(LC) | 中 | lc_tavily_search/SKILL.md + 保留 LangChain 创建逻辑 |
| 2.18 | lc_arxiv | 代码型(LC) | 中 | lc_arxiv/SKILL.md + 保留 LangChain 创建逻辑 |
| 2.19 | lc_wikipedia | 代码型(LC) | 中 | lc_wikipedia/SKILL.md + 保留 LangChain 创建逻辑 |
| 2.20 | lc_python_repl | 代码型(LC) | 中 | lc_python_repl/SKILL.md + 保留 LangChain 创建逻辑 |
| 2.21 | stock_data | 代码型 | 高 | stock_data/SKILL.md + 迁移 + format_data 内迁 + action_rules |
| 2.22 | xueqiu | 代码型 | 高 | xueqiu/SKILL.md + 迁移 + action_rules + topic_fallback |

> **xueqiu 迁移特殊说明**：xueqiu 已通过旧路径完成集成（`src/skills/analysis/xueqiu_skill.py` 594 行），且以下旧触点已到位：
> - `SKILL_PRIORITY_MAP["xueqiu"] = "structured_db"` ✓
> - `DATA_SOURCE_SKILL_MAP` 各条目已含 xueqiu ✓
> - `STRUCTURED_DATA_CAPABILITIES["xueqiu"]` ✓
> - `generic_agent.py` 已有 `_infer_xueqiu_actions()` (L2717) + topic fallback ✓
> - `skill_keywords.py` 已有 xueqiu 条目 ✓
> - `keyword_mappings.yaml` 已有 xueqiu 条目 ✓
> - `CATEGORY_TO_SKILLS` 已含 xueqiu ✓
> - `factory.py._SKILL_ALIAS_MAP` **未含** xueqiu 别名 ✗（xueqiu 的 `aliases: [xueqiu_stock, stock_quote]` 从未添加到 `_SKILL_ALIAS_MAP`，需在迁移时补上）
> - `orchestrator.py` 已注册 xueqiu factory ✓
> - `strategies.py._get_data_collection_skills` intent 路径已含 xueqiu ✓
> - `generic_agent.py ACTION_TO_SKILL` **未含** xueqiu 条目 ✗（xueqiu 的 action 分派通过 `skill_name == "xueqiu"` 专用分支实现，不走 `ACTION_TO_SKILL`，迁移时需将 action→skill 映射补入 `ACTION_TO_SKILL` 并删除专用分支）
>
> Phase 2.22 的迁移动作是：将现有 `analysis/xueqiu_skill.py` 移入 `xueqiu/skill.py`，创建 `xueqiu/SKILL.md`（将上述硬编码数据声明为元数据），然后逐个删除旧触点中的 xueqiu 条目。**功能不变，只是数据来源从硬编码变为 SKILL.md**。
>
> **已知遗留**：`keyword_mappings.yaml` 的 `financial.skills` 仍缺少 `stock_data`（非 xueqiu 问题，是 stock_data 的遗漏），需在迁移 stock_data (2.21) 时一并修复。

**LangChain skill 特殊处理**：LC skills 的 skill.py 不是标准 Skill 子类，而是 wrapper。迁移时在 SKILL.md 中声明 `skill_type: langchain`，discovery 遇到此类型时调用 `registry.py` 中已有的 `_create_*_skill()` 方法，不使用 importlib 动态导入。

每迁移一个 skill：
1. 创建目录 + SKILL.md（+ skill.py）
2. 删除 `registry.py` → `register_core_skills()` 中对应条目
3. 删除 `orchestrator.py` 中对应 factory 注册（由 `init_from_discovery()` 自动替代）
4. 删除 `src/skills/analysis/__init__.py` 中对应 import（discovery 不依赖 __init__.py）
5. 删除 `skill_keywords.py` 中对应条目
6. 删除 `strategies.py` 中对应条目
7. 运行全量测试

### Phase 3：Agent 通用化 + 清理

**目标**：消灭 generic_agent.py 中所有 skill-specific 逻辑，删除废弃文件。

| 步骤 | 内容 |
|------|------|
| 3.1 | 替换 `_infer_*_actions()` → 通用 `_infer_actions()`（从 manifest.action_rules） |
| 3.2 | 替换 execute 参数分支 → `_build_execute_kwargs()`（从 manifest.action_param_map） |
| 3.3 | 替换 topic fallback 硬编码 → 通用 `resolve_identifier()` |
| 3.4 | 替换 `llm_skill` 特殊分支 → `is_intrinsic` 属性 |
|     3.5 | 替换 12 处 search_skill 硬编码查找 → `get_by_capability("search")`（generic_agent.py 9 处 + orchestrator.py 2 处 + engine.py 1 处） |
| 3.6 | 替换 3 处 URL scheme 检测 → `credibility == "structured_source"` |
|     3.7 | 迁移 `_format_*` 系列 5 个方法 + 2 个常量到 stock_data/skill.py |
| 3.8 | 删除 `ACTION_TO_SKILL` → 从 manifest.capabilities 自动构建 |
| 3.9 | factory.py `_SKILL_ALIAS_MAP` → 从 manifest.aliases 自动构建 |
| 3.10 | 删除 `skill_keywords.py`（所有数据来自 SKILL.md） |
| 3.11 | 删除 `strategies.py` 中的硬编码 dict |
| 3.12 | `keyword_mappings.yaml` → `skill_inference` 部分废弃（数据来自 SKILL.md） |
| 3.13 | 全量测试 + 修复 |

### Phase 4：验证 & 文档

| 步骤 | 内容 |
|------|------|
| 4.1 | 新增 Skill 只需 1 目录 + SKILL.md(+ 可选 skill.py) 的端到端验证 |
| 4.2 | 编写 "新增 Skill 指南" 文档 |
| 4.3 | 性能基准：discovery 启动时间 < 200ms |

---

## 9. 新增 Skill 流程（重构后）

重构完成后，新增一个 Skill 只需：

```
1. 创建 src/skills/my_skill/SKILL.md        # 必需：元数据 + 指令
2. 创建 src/skills/my_skill/skill.py        # 可选：执行代码
3. 运行测试
```

**零其他文件改动。**

系统启动时自动：
- 扫描 `src/skills/` 下所有含 SKILL.md 的子目录
- 解析 YAML front matter → SkillManifest
- 动态导入 skill.py → 注册 factory
- 自动构建 CATEGORY_TO_SKILLS、SKILL_PRIORITY_MAP、SKILL_KEYWORDS、ACTION_TO_SKILL、_SKILL_ALIAS_MAP、DATA_SOURCE_SKILL_MAP、STRUCTURED_DATA_CAPABILITIES
- 校验 manifest 完整性

---

## 10. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 启动扫描性能 | SKILL.md 文件数量有限（<50），解析耗时 < 200ms；结果可缓存 |
| YAML front matter 解析失败 | 启动校验 + 严格 schema 校验 + warn 不阻塞 |
| 旧代码依赖硬编码 dict | Phase 1 并行运行 + diff 对比，Phase 2 逐个删除 |
| action_rules 正则匹配不准 | Schema 校验 + 单元测试覆盖；子类可覆盖 `infer_actions()` |
| 纯指令型 Skill 效果不稳定 | InstructionSkill 返回完整 SKILL.md 指令，agent 可阅读执行 |
| importlib 动态导入安全 | 仅扫描 `src/skills/` 目录，不扫描任意路径 |

---

## 11. 依赖

| 依赖 | 用途 | 是否新增 |
|------|------|----------|
| `python-frontmatter` | 解析 SKILL.md 的 YAML + Markdown | 新增 |
| `pyyaml` | YAML front matter 解析 | 已有 |
| `importlib` | 动态导入 skill.py | 标准库 |
