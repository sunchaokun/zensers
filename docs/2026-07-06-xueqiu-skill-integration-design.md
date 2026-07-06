# 雪球 Skill 集成方案

> 日期：2026-07-06
> 状态：方案设计 v3（实现后审查标注）
> 来源：`E:\Agent-Reach-main\docs\xueqiu-skill`
> 
> **实现状态总览**：本文档描述的方案已全部实现。以下标注为 **[已实现]** 的章节表示代码已落地且与方案一致；标注为 **[已实现·有差异]** 的章节表示已实现但与方案有细微差异，需注意；标注为 **[遗留]** 的表示尚未修复的遗留问题。

---

## 一、背景

### 1.1 现有金融数据能力

系统当前通过 `StockDataSkill`（akshare）获取 A 股金融数据，数据源为东方财富：

| 能力 | StockDataSkill (akshare) |
|------|--------------------------|
| A 股财报 | 利润表/资产负债表/现金流量表 |
| 公司信息 | 行业/股本/主营业务 |
| 股价 | 历史日线（120 日） |
| 港股/美股 | 不支持 |
| 实时行情 | 不支持（日线级别延迟） |
| K 线多周期 | 不支持（仅日线） |
| 市场情绪 | 不支持 |

### 1.2 雪球 Skill 能力

雪球 Skill 是一个独立的、零外部依赖的 Python API 客户端，提供：

| 能力 | XueqiuSkill (雪球) |
|------|---------------------|
| 实时行情 | A 股/港股/美股实时报价（含盘中） |
| 股票搜索 | 按代码/中文名搜索 |
| 热门帖子 | 雪球社区热门讨论 |
| 热门股票 | 人气榜/关注榜排行 |
| K 线数据 | 1m/5m/15m/30m/60m/日/周/月 |
| 用户帖子 | 大 V 观点追踪 |
| 认证 | 三层 Cookie 回退（配置文件→浏览器→首页） |

### 1.3 互补关系

两者**互补而非替代**：

- akshare = 财报数据（结构化三表）
- 雪球 = 实时行情 + 市场情绪 + 港股/美股

---

## 二、审查发现的问题 **[已实现]**

> 8 个问题中，问题 1-7 均已在代码中修复。问题 8（同步 API 阻塞风险）已通过 `asyncio.to_thread()` 包装解决。具体修复位置见各问题下方的「修复」描述。

深度审查代码后，发现 **8 个问题**，其中 4 个为阻断性/严重问题：

### 问题 1（阻断）：`SKILL_PRIORITY_MAP` 缺少 xueqiu

**位置**：`src/core/decomposition/strategies.py:106-115`

**现象**：`generic_agent.py:437-438` 的数据采集核心逻辑：

```python
def _skill_tier(name: str) -> str:
    return SKILL_PRIORITY_MAP.get(name, "web_search")  # 默认 web_search
```

`SKILL_PRIORITY_MAP` 只定义了 `stock_data` → `structured_db`。如果 xueqiu 不加入，它会被降级到 `web_search` 层级，**永远不会在 Tier 1 结构化数据阶段被触发**。

**修复**：`SKILL_PRIORITY_MAP` 新增 `"xueqiu": "structured_db"`。

### 问题 2（阻断）：`DATA_SOURCE_SKILL_MAP` 缺少 xueqiu

**位置**：`src/core/decomposition/strategies.py:117-140`

**现象**：`DATA_SOURCE_SKILL_MAP` 控制哪些方面（financial/估值/公司等）触发结构化数据采集。当前只映射到 `stock_data`，xueqiu 永远不会作为数据源被自动选中。

**修复**：各相关条目加入 `"xueqiu"`。

### 问题 3（严重）：`_fetch_structured_data` 硬编码了 StockDataSkill 的 action

**位置**：`src/core/agents/generic_agent.py:2277-2358`

**现象**：`_fetch_structured_data` 调用 `self._infer_stock_actions(aspect)` 推断 actions（`company_info`, `financials`, `key_metrics` 等），这些是 `StockDataSkill` 的接口，不是 `XueqiuSkill` 的接口。虽然方法签名已有 `skill_name` 参数（L2282），但从未被使用来分派 action。如果 xueqiu 被传入，会收到不支持的 action，返回 `_failure`。

**修复**：利用现有 `skill_name` 参数分派不同的 action 集合（无需新增参数）。

### 问题 4（严重）：`_get_data_collection_skills` 的 `intent_result` 路径只添加 `stock_data`，不添加 `xueqiu`

**位置**：`src/core/decomposition/strategies.py:154-160`

**现象**：

```python
if intent_result:
    primary_type = getattr(intent_result, 'primary_research_type', None)
    if primary_type and getattr(primary_type, 'value', '') in (
        "company_research", "investment", "competitive_analysis"
    ):
        if "stock_data" not in aspect_skills:
            aspect_skills.append("stock_data")
```

当 `primary_research_type` 为 `company_research` / `investment` / `competitive_analysis` 时，只添加 `stock_data`，**不添加 xueqiu**。这意味着即使 DATA_SOURCE_SKILL_MAP 的关键词没有匹配到（aspect 名称不含"财务"/"估值"等），通过 intent 路径也无法触发 xueqiu。

**更严重的是**：`industry_research`（行业研究）根本不在检查列表中！行业研究场景下，即使 `stock_data` 也不会被 intent 路径触发，只能依赖 aspect 关键词匹配。

**修复**：
1. 在 intent 路径中同时添加 `"xueqiu"`
2. 扩展检查列表，加入 `"industry_research"` 和 `"brand_research"`

### 问题 5（中等）：`EntityResolver` 只解析 A 股，xueqiu 支持 港股/美股

**位置**：`src/core/entity_resolver.py`

**现象**：`EntityResolver` 通过 akshare 的 `stock_zh_a_spot_em()` 构建股票名称表，仅覆盖 A 股。`_fetch_structured_data` 中的 `_extract_stock_symbol` + `_resolve_company_to_code` 两层 fallback 也依赖 A 股数据源，对港股/美股无效。xueqiu 的独特价值（港股/美股行情）无法自动触发。

**修复**：在 XueqiuSkill 中实现 `search_and_quote` 复合 action，允许通过中文名直接搜索并获取行情。同时在 `_infer_xueqiu_actions` 中，当 symbol 非标准 A 股格式时自动切换为 `search_and_quote`。

### 问题 6（中等）：`ASPECT_SKILL_MAP` 不包含 xueqiu

**位置**：`src/core/decomposition/strategies.py:41-70`

**现象**：`ASPECT_SKILL_MAP` 定义了 DEEP_ANALYSIS 阶段各 aspect 需要的 skills。当前 "Financial Analysis"、"Valuation Analysis"、"Company Analysis" 等只包含 `stock_analysis`，不包含 `xueqiu`。

**分析**：DEEP_ANALYSIS 阶段的 Agent 不直接调用数据采集 Skill（数据已在 DATA_COLLECTION 阶段采集），但 `stock_analysis` 会间接使用 `stock_data`。xueqiu 的数据在 DATA_COLLECTION 阶段已采集并写入 SharedMemory，DEEP_ANALYSIS Agent 通过 LLM 消费这些数据，**不需要在 ASPECT_SKILL_MAP 中添加 xueqiu**。

**结论**：此问题**不需要修复**。ASPECT_SKILL_MAP 只控制 DEEP_ANALYSIS 阶段，数据采集在 DATA_COLLECTION 阶段完成。

### 问题 7（中等）：`STRUCTURED_DATA_CAPABILITIES` 不包含 xueqiu

**位置**：`src/core/decomposition/strategies.py:212-218`

**现象**：

```python
STRUCTURED_DATA_CAPABILITIES = {
    "stock_data": {
        "zh": ["营收", "净利润", "毛利率", ...],
    },
}
```

`STRUCTURED_DATA_CAPABILITIES` 用于 `derive_data_source_type()` 判断数据需求的结构化类型。缺少 xueqiu 会导致行情类数据需求（如"换手率"、"市盈率"、"实时行情"）被判定为 `"search"` 而非 `"structured"`，从而走 web 搜索而非结构化数据路径。

**修复**：新增 xueqiu 的 capabilities 条目。

### 问题 8（低）：同步 API 在异步上下文中的阻塞风险

**位置**：雪球 API 全部基于 `urllib` 同步调用。

**现象**：`ensure_cookies()` 中的 `_load_from_browser()` 和 `_load_from_homepage()` 可能耗时较长，直接在 `execute()` 中调用会阻塞事件循环。

**修复**：所有雪球 API 调用通过 `asyncio.to_thread()` 包装。

---

## 三、触发场景覆盖分析 **[已实现]**

### 3.1 触发链路全景

雪球 Skill 被触发需要经过以下链路：

```
用户输入
  → Orchestrator 意图分析 (IntentAnalysis)
  → 任务分解 (Decomposition)
  → DATA_COLLECTION Agent 创建 (skills 参数)
  → GenericAgent.execute (category="research")
  → _skill_tier 分层
  → Tier 1: structured_db → _fetch_structured_data
  → skill.execute(action=...)
```

**关键节点**：`_get_data_collection_skills(aspect, topic, intent_result)` 决定了 DATA_COLLECTION Agent 的 `skills` 列表，这是 xueqiu 能否被触发的**唯一入口**。

### 3.2 场景覆盖矩阵

| 场景 | aspect 示例 | 触发路径 | 当前是否覆盖 | 修复后 |
|------|------------|----------|-------------|--------|
| **行业研究** | "市场规模"、"行业趋势"、"竞争格局" | DATA_SOURCE_SKILL_MAP 关键词匹配 | 部分覆盖（"市场规模"不含 xueqiu） | 全覆盖 |
| **公司研究** | "财务分析"、"估值分析"、"公司分析" | DATA_SOURCE_SKILL_MAP + intent_result | 不覆盖（intent 路径只加 stock_data） | 全覆盖 |
| **投资分析** | "投资价值"、"估值分析" | DATA_SOURCE_SKILL_MAP + intent_result | 不覆盖 | 全覆盖 |
| **竞争分析** | "竞争格局"、"市场份额" | DATA_SOURCE_SKILL_MAP + intent_result | 不覆盖 | 全覆盖 |
| **港股研究** | "财务分析"（腾讯控股） | EntityResolver 无法解析 → symbol 为空 | 不覆盖 | search_and_quote 补位 |
| **美股研究** | "估值分析"（Apple Inc） | EntityResolver 无法解析 → symbol 为空 | 不覆盖 | search_and_quote 补位 |
| **行情查询** | "实时行情"、"热门股票" | DATA_SOURCE_SKILL_MAP 关键词匹配 | 不覆盖（无"行情"关键词） | 全覆盖 |
| **市场情绪** | "热门帖子"、"人气股" | DATA_SOURCE_SKILL_MAP 关键词匹配 | 不覆盖 | 全覆盖 |

### 3.3 场景详细分析

#### 场景 A：行业研究（如"新能源汽车行业研究"）

**当前问题**：

1. `primary_research_type = "industry_research"` → 不在 `_get_data_collection_skills` 的 intent 检查列表中 → **不添加 stock_data，也不添加 xueqiu**
2. aspect 如"市场规模" → `DATA_SOURCE_SKILL_MAP["市场规模"] = ["stock_data"]` → **不含 xueqiu**
3. aspect 如"行业趋势" → `DATA_SOURCE_SKILL_MAP` 无匹配 → **只有 base_skills**

**修复后**：

1. intent 路径：`"industry_research"` 加入检查列表 → 同时添加 `stock_data` + `xueqiu`
2. `DATA_SOURCE_SKILL_MAP["市场规模"] = ["stock_data", "xueqiu"]`
3. 即使 aspect 关键词不匹配，intent 路径也能兜底

#### 场景 B：公司研究（如"比亚迪公司深度研究"）

**当前问题**：

1. `primary_research_type = "company_research"` → 在检查列表中 → **只添加 stock_data，不添加 xueqiu**
2. aspect 如"财务分析" → `DATA_SOURCE_SKILL_MAP["财务"] = ["stock_data"]` → **不含 xueqiu**

**修复后**：

1. intent 路径：同时添加 `stock_data` + `xueqiu`
2. `DATA_SOURCE_SKILL_MAP["财务"] = ["stock_data", "xueqiu"]`
3. 双重保障：即使 intent 路径失效，aspect 关键词也能触发

#### 场景 C：港股/美股研究（如"腾讯控股投资价值分析"）

**当前问题**：

1. `EntityResolver` 基于 A 股名称表 → "腾讯控股" 无法解析 → `symbols = []`
2. `_fetch_structured_data` 中 `symbols` 为空后，还有两层 A 股 fallback（`_extract_stock_symbol` 提取 6 位数字/中文公司名 → `_resolve_company_to_code` 通过 akshare `stock_zh_a_spot_em()` 解析），但两者都依赖 A 股数据源，对港股/美股无效 → 最终 `symbols` 仍为空 → **返回空结果**，xueqiu 根本不会被调用

**修复后**：

1. `_fetch_structured_data` 中，当 `skill_name == "xueqiu"` 且 `symbols` 为空时，**用 topic（公司名）作为 symbol 传入**
2. `_infer_xueqiu_actions` 检测到非标准 A 股代码 → 切换为 `search_and_quote`
3. 雪球搜索 "腾讯控股" → 获得 symbol="00700" → 获取行情

**关键修改点**：`_fetch_structured_data` 中，当 EntityResolver + `_extract_stock_symbol` + `_resolve_company_to_code` 三层 A 股 fallback 均失效后，xueqiu 分支需要在 `symbols` 仍为空时，用 `topic` 作为 fallback：

```python
if skill_name == "xueqiu" and not symbols:
    # xueqiu 支持 search_and_quote，可以用公司名直接搜索
    if topic:
        symbols = [topic]
```

#### 场景 D：行情/情绪查询（如"A股热门股票排行"）

**当前问题**：

1. `DATA_SOURCE_SKILL_MAP` 无"行情"/"热门"关键词 → **不触发 xueqiu**
2. `STRUCTURED_DATA_CAPABILITIES` 无 xueqiu 条目 → 行情数据需求被判定为 `"search"` → 走 web 搜索

**修复后**：

1. `DATA_SOURCE_SKILL_MAP` 新增 `"行情": ["xueqiu"]`, `"热门": ["xueqiu"]`
2. `STRUCTURED_DATA_CAPABILITIES` 新增 xueqiu 条目
3. `derive_data_source_type("换手率")` → `"structured"` → 走结构化数据路径

---

## 四、最终方案 **[已实现]**

> 以下所有 4.1-4.4 节描述的方案均已在代码中落地。

### 4.1 文件结构 **[已实现]**

> 当前实际文件结构与方案一致。`src/skills/analysis/xueqiu_skill.py` 已创建（594 行），`__init__.py` 已导出 XueqiuSkill。

```
src/skills/analysis/
├── __init__.py              # 修改：导出 XueqiuSkill
├── stock_data.py            # 不变
├── xueqiu_skill.py          # 新建：雪球 Skill（内嵌 auth + api）
└── ...

src/core/decomposition/
├── strategies.py            # 修改：SKILL_PRIORITY_MAP + DATA_SOURCE_SKILL_MAP
│                           #        + _get_data_collection_skills intent 路径
│                           #        + STRUCTURED_DATA_CAPABILITIES
└── ...

src/core/agents/
├── generic_agent.py         # 修改：_fetch_structured_data 分派逻辑
│                           #        + _infer_xueqiu_actions
│                           #        + xueqiu topic fallback
└── ...

src/core/orchestrator/
├── orchestrator.py          # 修改：工厂注册
└── ...

src/skills/
├── skill_keywords.py        # 修改：关键词映射
├── registry.py              # 修改：CATEGORY_TO_SKILLS
└── ...

config/
├── keyword_mappings.yaml    # 修改：skill_inference 扩展
└── ...
```

### 4.2 XueqiuSkill 设计 **[已实现]**

> `src/skills/analysis/xueqiu_skill.py` 已实现全部设计，包括：
> - 内嵌 `_XueqiuAuth` + `_XueqiuAPI` ✓
> - 8 个 action（quote/search/hot_posts/hot_stocks/kline/user_posts/check/search_and_quote）✓
> - `search_and_quote` 复合 action ✓
> - `asyncio.to_thread()` 异步包装 ✓
> - 类级别 `_memory_cache` ✓
> - `_rate_limited_call` 限流（500ms 最小间隔）✓

#### 4.2.1 类结构

```python
class XueqiuSkill(Skill):
    """雪球实时行情/热帖/热门股票 Skill（A股/港股/美股）"""

    _memory_cache: Dict[tuple, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "xueqiu"

    @property
    def description(self) -> str:
        return "雪球实时行情/热门股票/热帖/K线 (A股/港股/美股)"

    async def execute(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "quote")
        ...
```

#### 4.2.2 Action 设计

| action | 参数 | 说明 | 返回 |
|--------|------|------|------|
| `quote` | `symbol` (SH600519/AAPL/00700) | 实时行情 | symbol, name, current, percent, chg, high, low, open, last_close, volume, amount, market_capital, turnover_rate, pe_ttm, timestamp |
| `search` | `query`, `limit=10` | 股票搜索 | [{symbol, name, exchange}] |
| `hot_posts` | `limit=20` | 热门帖子 | [{id, title, text, author, likes, url}] |
| `hot_stocks` | `limit=10`, `stock_type=10` | 热门股票 | [{symbol, name, current, percent, rank}] |
| `kline` | `symbol`, `period="day"`, `count=30` | K 线数据 | [{timestamp, open, high, low, close, volume}] |
| `user_posts` | `user_id`, `limit=10` | 用户帖子 | [{id, title, text, created_at, likes, retweets}] |
| `check` | 无 | 健康检查 | {status, message} |
| `search_and_quote` | `query` | **复合 action**：先搜索再获取行情 | {symbol, name, quote: {...}} |

#### 4.2.3 `search_and_quote` 复合 action（解决问题 5）

这是解决港股/美股无法通过 `EntityResolver` 自动触发的关键设计：

```python
async def _search_and_quote(self, query: str) -> Dict[str, Any]:
    """
    复合操作：搜索股票 → 获取行情。
    用于 _fetch_structured_data 中，当 EntityResolver 无法解析时，
    通过中文名直接搜索并获取行情数据。
    """
    results = await self._rate_limited_call(self._api.search_stock, query, limit=1)
    if not results:
        return self._failure(f"未找到股票: {query}")
    symbol = results[0]["symbol"]
    quote = await self._rate_limited_call(self._api.get_stock_quote, symbol)
    return self._success(
        data={"search": results[0], "quote": quote},
        content=f"{results[0]['name']}({symbol}): 当前价 {quote.get('current')}, "
                f"涨跌幅 {quote.get('percent')}%, "
                f"成交量 {quote.get('volume')}, 市值 {quote.get('market_capital')}"
    )
```

#### 4.2.4 内嵌 auth + api 的策略

原雪球 Skill 的 `auth.py` 和 `xueqiu_api.py` 加起来约 640 行。集成策略：

1. **将 `XueqiuAuth` 类完整内嵌到 `xueqiu_skill.py` 中**
   - 原因：原代码使用 `from auth import XueqiuAuth`，这是相对于项目根的导入，在 `src/skills/analysis/` 下不可用
   - 内嵌后模块自包含，不依赖外部路径

2. **将 `XueqiuAPI` 类完整内嵌到 `xueqiu_skill.py` 中**
   - 将 `_get_json` 等同步方法包装为 `XueqiuSkill` 的内部调用
   - 所有外部调用通过 `asyncio.to_thread()` 包装

3. **文件结构**：

```python
# src/skills/analysis/xueqiu_skill.py

# ── 内嵌 XueqiuAuth ──────────────────────────────
class _XueqiuAuth:
    """三层 Cookie 管理（从 auth.py 内嵌，改名为 _XueqiuAuth 避免命名冲突）"""
    ...

# ── 内嵌 XueqiuAPI ──────────────────────────────
class _XueqiuAPI:
    """雪球 API 客户端（从 xueqiu_api.py 内嵌，改名为 _XueqiuAPI）"""
    ...

# ── XueqiuSkill ──────────────────────────────
class XueqiuSkill(Skill):
    """雪球 Skill"""
    ...
```

#### 4.2.5 异步包装策略（解决问题 8）

```python
async def execute(self, **kwargs) -> Dict[str, Any]:
    action = kwargs.get("action", "quote")

    # 首次调用时惰性初始化 API
    if self._api is None:
        self._api = await asyncio.to_thread(self._init_api)

    # 所有 API 调用通过 _rate_limited_call 包装（含 to_thread）
    if action == "quote":
        result = await self._rate_limited_call(
            self._api.get_stock_quote, kwargs["symbol"]
        )
        return self._success(data=result, ...)
    ...
```

#### 4.2.6 缓存策略

与 `StockDataSkill` 一致，使用类级别 `_memory_cache`：

```python
_memory_cache: Dict[tuple, Dict[str, Any]] = {}

async def execute(self, **kwargs) -> Dict[str, Any]:
    action = kwargs.get("action", "quote")
    cache_key = (action, str(kwargs))
    if cache_key in self._memory_cache:
        return self._memory_cache[cache_key]
    ...
    if result.get("success"):
        self._memory_cache[cache_key] = result
    return result
```

行情数据 TTL 建议 60 秒（实时数据），热门数据 TTL 建议 5 分钟。后续可引入时间戳过期机制。

#### 4.2.7 限流策略

雪球 API 无官方限流文档，建议保守策略：

```python
import time

class XueqiuSkill(Skill):
    _last_request_time: float = 0.0
    _MIN_INTERVAL: float = 0.5  # 最小请求间隔 500ms

    async def _rate_limited_call(self, func, *args, **kwargs):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._MIN_INTERVAL:
            await asyncio.sleep(self._MIN_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()
        return await asyncio.to_thread(func, *args, **kwargs)
```

---

### 4.3 注册集成（10 处修改） **[已实现·有差异]**

> 已实现的触点（8/10，缺 2 处见下）：
> - 4.3.1 `analysis/__init__.py` 导出 XueqiuSkill ✓
> - 4.3.2 `orchestrator.py` 工厂注册 `("xueqiu", XueqiuSkill)` ✓
> - 4.3.3 `skill_keywords.py` xueqiu 关键词 + 描述 ✓
> - 4.3.4 `registry.py` CATEGORY_TO_SKILLS 加入 xueqiu ✓
> - 4.3.5 `strategies.py` SKILL_PRIORITY_MAP + DATA_SOURCE_SKILL_MAP + intent 路径 + STRUCTURED_DATA_CAPABILITIES ✓
> - 4.3.6 `generic_agent.py` _fetch_structured_data 分派 + _infer_xueqiu_actions + topic fallback ✓
> - 4.3.7 `keyword_mappings.yaml` skill_inference 扩展 + stock_quote 条目 ✓
>
> **[未实现]** `factory.py._SKILL_ALIAS_MAP` 未添加 xueqiu 别名（`xueqiu_stock`, `stock_quote`）。xueqiu 的 action 分派通过 `skill_name == "xueqiu"` 专用分支实现，不走 `ACTION_TO_SKILL`，因此别名映射从未被添加。需在自描述架构迁移时补上。
>
> **[未实现]** `generic_agent.py ACTION_TO_SKILL` 未添加 xueqiu 的 action 映射（quote→xueqiu, kline→xueqiu 等）。当前通过 `_fetch_structured_data` 中的 `skill_name == "xueqiu"` 专用分支绕过。需在自描述架构迁移时从 manifest.capabilities 自动构建。
>
> **[遗留]** `keyword_mappings.yaml` 的 `financial.skills`（L283-285）仍缺少 `stock_data`：
> 当前值为 `["stock_analysis", "data_analysis", "xueqiu"]`，应为 `["stock_analysis", "stock_data", "data_analysis", "xueqiu"]`。
> 此遗漏影响的是 stock_data 的 keyword_mappings 触发，不是 xueqiu 的问题，但在此标注提醒。
>
> **[代码小问题]** `orchestrator.py` L292 日志消息仍为 `"registered 7 professional analysis Skills"`，但实际注册了 8 个（含 xueqiu），应更新为 8。

#### 4.3.1 `src/skills/analysis/__init__.py`

```python
from .xueqiu_skill import XueqiuSkill

__all__ = [
    ...,
    "XueqiuSkill",
]
```

#### 4.3.2 `src/core/orchestrator/orchestrator.py`

在工厂注册区块（约 L276-289）新增：

```python
from src.skills.analysis import XueqiuSkill

for name, cls in [
    ...,
    ("xueqiu", XueqiuSkill),
]:
    skill_registry.register_factory(name, cls)
```

#### 4.3.3 `src/skills/skill_keywords.py`

新增 `xueqiu` 关键词条目：

```python
SKILL_KEYWORDS: Dict[str, Set[str]] = {
    ...,
    "xueqiu": {
        "xueqiu", "雪球", "stock quote", "real-time quote", "行情",
        "实时行情", "hot stock", "热门股票", "人气股", "关注榜",
        "热帖", "kline", "K线", "港股行情", "美股行情", "A股行情",
        "股票搜索", "turnover rate", "换手率", "pe_ttm", "市盈率",
        "market capital", "市值", "涨跌", "大盘",
    },
}
```

同时更新 `get_skill_description()`：

```python
"xueqiu": "雪球实时行情/热门股票/热帖 (A股/港股/美股)",
```

#### 4.3.4 `src/skills/registry.py` — `CATEGORY_TO_SKILLS`

> **注意**：`CATEGORY_TO_SKILLS` 是 `SkillRegistry.load_skills_for_category()` 方法内部的**局部变量**（L398-411），不是模块级常量。修改时需定位到该方法内部。

```python
CATEGORY_TO_SKILLS = {
    "market-analysis": ["market_analysis", "lc_tavily_search", "lc_wikipedia", "llm_skill"],
    "data-collection": ["lc_tavily_search", "lc_wikipedia", "xueqiu"],           # 新增 xueqiu
    "academic-research": ["lc_arxiv", "lc_wikipedia", "llm_skill"],
    "financial-analysis": ["stock_data", "stock_analysis", "xueqiu", "lc_tavily_search", "lc_wikipedia", "llm_skill"],  # 新增 xueqiu
    "data-analysis": ["data_analysis", "lc_python_repl", "llm_skill"],
    "report-generation": ["llm_skill"],
    "quality-check": ["llm_skill"],
    "visual-engineering": [],
    "research": ["stock_data", "xueqiu", "lc_tavily_search", "lc_wikipedia", "llm_skill"],  # 新增 xueqiu
    "synthesis": ["llm_skill"],
    "calibration": ["llm_skill"],
    "annual-report": ["annual_report_parser", "stock_data", "stock_analysis", "llm_skill"],
}
```

#### 4.3.5 `src/core/decomposition/strategies.py`（解决问题 1、2、4、7）

**A. SKILL_PRIORITY_MAP** 新增：

```python
SKILL_PRIORITY_MAP = {
    "stock_data": "structured_db",
    "wind_data": "structured_db",
    "bloomberg_data": "structured_db",
    "xueqiu": "structured_db",          # 新增
    "search_skill": "web_search",
    ...
}
```

**B. DATA_SOURCE_SKILL_MAP** 各相关条目新增 xueqiu：

```python
DATA_SOURCE_SKILL_MAP = {
    "financial": ["stock_data", "xueqiu"],
    "valuation": ["stock_data", "xueqiu"],
    "company": ["stock_data", "xueqiu"],
    "market_size": ["stock_data", "xueqiu"],   # 行业研究也需要行情数据
    "competitive": ["xueqiu"],                 # 竞争分析：热门股票/人气排行
    "policy": [],
    "technology": [],
    "risk": [],
    "财务": ["stock_data", "xueqiu"],
    "估值": ["stock_data", "xueqiu"],
    "公司": ["stock_data", "xueqiu"],
    "盈利": ["stock_data", "xueqiu"],
    "营收": ["stock_data", "xueqiu"],
    "市值": ["stock_data", "xueqiu"],
    "市场规模": ["stock_data", "xueqiu"],       # 行业研究核心 aspect
    "利润": ["stock_data", "xueqiu"],
    "资产负债": ["stock_data"],                  # 雪球不提供三表，仅 stock_data
    "roe": ["stock_data", "xueqiu"],
    "pe": ["stock_data", "xueqiu"],
    "pb": ["stock_data", "xueqiu"],
    "增长": ["stock_data", "xueqiu"],
    "投资": ["stock_data", "xueqiu"],
    "行情": ["xueqiu"],                         # 新增：纯行情关键词 → 仅 xueqiu
    "热门": ["xueqiu"],                         # 新增：热门股票/帖子 → 仅 xueqiu
    "港股": ["xueqiu"],                         # 新增
    "美股": ["xueqiu"],                         # 新增
    "趋势": ["xueqiu"],                         # 新增：行情趋势
    "竞争": ["xueqiu"],                         # 新增：竞争 → 热门排行
}
```

**C. `_get_data_collection_skills` intent 路径修复**（解决问题 4）：

```python
def _get_data_collection_skills(aspect: str, topic: str = "", intent_result: Any = None) -> List[str]:
    db_skills: List[str] = []
    web_skills: List[str] = []
    llm_skills: List[str] = []

    base_skills = ["search_skill", "news_search", "llm_skill"]
    aspect_skills: List[str] = []
    aspect_lower = aspect.lower()
    for keyword, extra_skills in DATA_SOURCE_SKILL_MAP.items():
        if keyword in aspect_lower:
            aspect_skills.extend(extra_skills)
    if intent_result:
        primary_type = getattr(intent_result, 'primary_research_type', None)
        if primary_type and getattr(primary_type, 'value', '') in (
            "company_research", "investment", "competitive_analysis",
            "industry_research", "brand_research",   # 新增：行业研究、品牌研究
        ):
            if "stock_data" not in aspect_skills:
                aspect_skills.append("stock_data")
            if "xueqiu" not in aspect_skills:        # 新增：同时添加 xueqiu
                aspect_skills.append("xueqiu")

    all_unique = list(dict.fromkeys(aspect_skills + base_skills))
    for skill in all_unique:
        tier = SKILL_PRIORITY_MAP.get(skill, "web_search")
        if tier == "structured_db":
            db_skills.append(skill)
        elif tier == "llm":
            llm_skills.append(skill)
        else:
            web_skills.append(skill)
    return db_skills + web_skills + llm_skills
```

**D. STRUCTURED_DATA_CAPABILITIES 新增 xueqiu**（解决问题 7）：

```python
STRUCTURED_DATA_CAPABILITIES = {
    "stock_data": {
        "zh": ["营收", "净利润", "毛利率", "净利率", "ROE", "ROA", "ROIC",
               "资产负债率", "流动比率", "速动比率", "现金流", "研发费用",
               "销量", "产量", "市场份额", "PE", "PB", "利润表", "资产负债表", "现金流量表"],
    },
    "xueqiu": {  # 新增
        "zh": ["换手率", "市盈率", "实时行情", "当前价", "涨跌幅", "成交量",
               "成交额", "市值", "PE_TTM", "K线", "行情", "热门股票",
               "人气排行", "关注排行", "热帖"],
    },
}
```

#### 4.3.6 `src/core/agents/generic_agent.py`（解决问题 3、5）

**A. `_fetch_structured_data` 分派逻辑**：

> **注意**：`skill_name` 参数已存在于方法签名（L2282: `skill_name: str = "stock_data"`），当前未被使用来分派 action。修复方案只需**利用现有参数**做分派，无需新增参数。

```python
async def _fetch_structured_data(
    self,
    stock_skill: Any,
    topic: str,
    aspect: str,
    skill_name: str = "stock_data",
) -> Dict[str, Any]:
    result = {"data_points": [], "sources": [], "canonical_metrics": {}}
    try:
        symbols: List[str] = []
        # ... (现有的 EntityResolver symbol 解析逻辑不变) ...

        # 【新增】xueqiu topic fallback：当 EntityResolver + _extract_stock_symbol
        # + _resolve_company_to_code 三层 A 股 fallback 均失效后，symbols 仍为空时，
        # 用 topic 作为 fallback（因为 xueqiu 支持 search_and_quote，可以通过公司名直接搜索）
        if skill_name == "xueqiu" and not symbols and topic:
            # 从 topic 中提取公司名
            chinese_match = re.search(r'[\u4e00-\u9fff]+', topic)
            if chinese_match:
                symbols = [chinese_match.group(0)]
                logger.info(
                    f"GenericAgent {self.agent_id}: xueqiu topic fallback "
                    f"→ symbol='{symbols[0]}' (for search_and_quote)"
                )

        for symbol in symbols:
            # 【修改】根据 skill_name 推断 actions
            if skill_name == "xueqiu":
                actions = self._infer_xueqiu_actions(aspect, symbol)
            else:
                actions = self._infer_stock_actions(aspect)

            for action in actions:
                try:
                    skill_result = await stock_skill.execute(
                        action=action, symbol=symbol,
                    )
                    # ... (现有的结果处理逻辑不变) ...
```

**B. 新增 `_infer_xueqiu_actions` 方法**：

```python
def _infer_xueqiu_actions(self, aspect: str, symbol: str) -> List[str]:
    """推断 XueqiuSkill 需要执行的 actions。

    与 _infer_stock_actions 不同：
    - 默认 action 是 quote（实时行情），而非 company_info
    - 不含 financials/key_metrics（雪球不提供财报三表）
    - 非标准 A 股代码 → search_and_quote
    """
    aspect_lower = (aspect or "").lower()

    # 非标准 A 股代码 → search_and_quote（解决港股/美股触发问题）
    if symbol and not re.match(r'^(SH|SZ|BJ)\d{6}$', symbol):
        return ["search_and_quote"]

    actions = ["quote"]

    # 行情/估值/盈利类 → 加 K 线
    if any(kw in aspect_lower for kw in (
        "行情", "估值", "盈利", "营收", "市值",
        "pe", "pb", "roe", "增长", "投资",
        "financial", "valuation", "growth",
        "股价", "走势", "price", "market_cap",
    )):
        actions.append("kline")

    # 竞争/市场类 → 加热门股票
    if any(kw in aspect_lower for kw in (
        "竞争", "热门", "人气", "排行",
        "competitive", "hot", "popular",
    )):
        actions.append("hot_stocks")

    return list(dict.fromkeys(actions))
```

**关键设计**：

1. 当 `symbol` 不是标准 A 股代码格式时（如港股 `00700`、美股 `AAPL`，或从 `EntityResolver` 解析失败时的中文名"腾讯控股"），自动切换为 `search_and_quote` 复合 action
2. 默认 action 是 `quote`（实时行情），而非 `company_info`（雪球不提供公司详情）
3. 竞争/热门类 aspect 额外添加 `hot_stocks`

#### 4.3.7 `config/keyword_mappings.yaml`

在 `skill_inference.financial.skills` 中加入 `stock_data`（当前缺失）和 `xueqiu`：

```yaml
skill_inference:
  financial:
    keywords:
      - "Finance"
      - "Valuation"
      - ...
    skills:
      - "stock_analysis"
      - "stock_data"         # 新增：当前 financial.skills 缺失 stock_data
      - "data_analysis"
      - "xueqiu"             # 新增
```

新增行情专属条目：

```yaml
  stock_quote:
    keywords:
      - "行情"
      - "Quote"
      - "Hot Stock"
      - "热门股票"
      - "热帖"
      - "港股"
      - "美股"
      - "K线"
      - "涨跌"
    skills:
      - "xueqiu"
```

---

### 4.4 数据获取阶段触发路径 **[已实现]**

> 路径 A-E 描述的触发逻辑均已在代码中实现。关键代码位置：
> - `strategies.py:110` SKILL_PRIORITY_MAP["xueqiu"] = "structured_db"
> - `strategies.py:119-146` DATA_SOURCE_SKILL_MAP 含 xueqiu 条目
> - `strategies.py:166-170` intent 路径含 xueqiu
> - `strategies.py:228` STRUCTURED_DATA_CAPABILITIES 含 xueqiu
> - `generic_agent.py:2319-2324` topic fallback
> - `generic_agent.py:2717` _infer_xueqiu_actions

#### 路径 A：A 股公司研究（如"比亚迪公司深度研究"）

```
用户输入 "比亚迪公司深度研究"
    ↓
Orchestrator 意图分析 → primary_research_type = "company_research"
    ↓
任务分解 → aspects = ["财务分析", "估值分析", "竞争格局", ...]
    ↓
_get_data_collection_skills("财务分析", "比亚迪公司深度研究", intent_result):
    ├─ DATA_SOURCE_SKILL_MAP["财务"] → ["stock_data", "xueqiu"]  ✓
    └─ intent_result: "company_research" → 额外添加 stock_data + xueqiu  ✓
    → 返回 ["stock_data", "xueqiu", "search_skill", "news_search", "llm_skill"]
    ↓
GenericAgent.execute (category="research"):
    → _skill_tier("stock_data") = "structured_db"  ✓
    → _skill_tier("xueqiu") = "structured_db"  ✓
    ↓
Tier 1: structured_db
    ├─ skill_name="stock_data"
    │   → EntityResolver 解析 "比亚迪" → symbol="002594"
    │   → _infer_stock_actions("财务分析") → ["financials", "company_info"]
    │   → akshare 返回三表 + 公司信息
    │
    └─ skill_name="xueqiu"
        → EntityResolver 解析 "比亚迪" → symbol="002594"
        → _infer_xueqiu_actions("财务分析", "002594") → ["quote", "kline"]
        → 雪球返回实时行情 + K 线
    ↓
数据合并 → stock_data 提供 3 条 + xueqiu 提供 2 条 = 5 条
    → _structured_data_sufficient = True → 减少不必要的 web 搜索
    ↓
DEEP_ANALYSIS: stock_analysis 使用 stock_data 数据 + xueqiu 行情数据
```

#### 路径 B：行业研究（如"新能源汽车行业研究"）

```
用户输入 "新能源汽车行业研究"
    ↓
Orchestrator 意图分析 → primary_research_type = "industry_research"
    ↓
任务分解 → aspects = ["市场规模", "竞争格局", "行业趋势", ...]
    ↓
_get_data_collection_skills("市场规模", "新能源汽车行业研究", intent_result):
    ├─ DATA_SOURCE_SKILL_MAP["市场规模"] → ["stock_data", "xueqiu"]  ✓ (修复后)
    └─ intent_result: "industry_research" → 额外添加 stock_data + xueqiu  ✓ (修复后)
    → 返回 ["stock_data", "xueqiu", "search_skill", "news_search", "llm_skill"]
    ↓
_get_data_collection_skills("竞争格局", ...):
    ├─ DATA_SOURCE_SKILL_MAP["竞争"] → ["xueqiu"]  ✓ (修复后：热门排行数据)
    → 返回 ["xueqiu", "search_skill", "news_search", "llm_skill"]
    ↓
Tier 1: structured_db
    ├─ "市场规模" aspect: stock_data(行业对比) + xueqiu(行情)
    └─ "竞争格局" aspect: xueqiu(hot_stocks) → 行业热门股票排行
```

#### 路径 C：港股研究（如"腾讯控股投资价值分析"）

```
用户输入 "腾讯控股投资价值分析"
    ↓
Orchestrator 意图分析 → primary_research_type = "company_research"
    ↓
任务分解 → aspects = ["估值分析", "财务分析", ...]
    ↓
_get_data_collection_skills("估值分析", "腾讯控股投资价值分析", intent_result):
    → 返回 ["stock_data", "xueqiu", "search_skill", ...]
    ↓
Tier 1: structured_db
    ├─ skill_name="stock_data"
    │   → EntityResolver 解析 "腾讯控股" → stock_code=None (港股不在 A 股表)
    │   → _extract_stock_symbol + _resolve_company_to_code 两层 A 股 fallback 均无效
    │   → symbols = [] → 跳过（akshare 不支持港股）
    │
    └─ skill_name="xueqiu"
        → EntityResolver 解析 "腾讯控股" → stock_code=None
        → symbols = [] → 【topic fallback】→ symbols = ["腾讯控股"]
        → _infer_xueqiu_actions("估值分析", "腾讯控股")
            → "腾讯控股" 不匹配 ^(SH|SZ|BJ)\d{6}$ → actions=["search_and_quote"]
        → 雪球搜索 "腾讯控股" → symbol="00700" → 获取港股行情
    ↓
返回港股实时行情数据（current, percent, pe_ttm, market_capital, ...）
```

#### 路径 D：美股研究（如"Apple Inc 估值分析"）

```
用户输入 "Apple Inc 估值分析"
    ↓
与路径 C 类似，topic fallback → symbols = ["Apple"]
    → _infer_xueqiu_actions → actions=["search_and_quote"]
    → 雪球搜索 "Apple" → symbol="AAPL" → 获取美股行情
```

#### 路径 E：行情/情绪查询（如"A股热门股票排行"）

```
用户输入 "A股热门股票排行"
    ↓
_get_data_collection_skills("热门股票排行", ...):
    ├─ DATA_SOURCE_SKILL_MAP["热门"] → ["xueqiu"]  ✓ (修复后)
    → 返回 ["xueqiu", "search_skill", ...]
    ↓
Tier 1: structured_db
    └─ skill_name="xueqiu"
        → _infer_xueqiu_actions → actions=["quote", "hot_stocks"]
        → 雪球返回热门股票排行 + 实时行情
```

---

## 五、与 StockDataSkill 协同详解 **[已实现]**

### 5.1 数据互补矩阵

| 维度 | StockDataSkill (akshare) | XueqiuSkill (雪球) | 协同效果 |
|------|--------------------------|---------------------|----------|
| 数据源 | 东方财富 | 雪球 | 双源交叉验证 |
| A 股财报 | 三表完整 | 无 | stock_data 主导 |
| A 股行情 | 历史日线 | 实时 tick | xueqiu 补充实时 |
| 港股行情 | 不支持 | 支持 | xueqiu 独有 |
| 美股行情 | 不支持 | 支持 | xueqiu 独有 |
| K 线周期 | 日线 | 8 种周期 | xueqiu 更精细 |
| 市场情绪 | 无 | 热帖/热门股 | xueqiu 独有 |
| PE/换手率 | 财务指标 | 实时交易指标 | 互补 |
| 认证要求 | 无 | Cookie（三层回退） | stock_data 零门槛 |

### 5.2 执行优先级

两者同为 `structured_db` tier，执行顺序取决于 `available_skills` 列表顺序。建议：

1. **stock_data 先执行**：获取基础财报数据，判断数据充分性
2. **xueqiu 后执行**：补充实时行情 + 市场情绪

在 `_fetch_structured_data` 中，两个 skill 依次被调用（循环 `tiered_skills["structured_db"]`），天然满足此顺序。

### 5.3 数据去重

两个 Skill 的数据通过不同的 `skill_name://` URL 前缀天然隔离：

- `stock_data://002594/company_info`
- `xueqiu://002594/quote`

不会触发数据去重逻辑的误判。

---

## 六、风险与缓解 **[已实现]**

> 7 项风险中，降级策略（6.1）已在 `generic_agent.py` 的 `_fetch_structured_data` 中实现：xueqiu 执行失败时 warning 但不阻断整体数据采集。

| # | 风险 | 严重度 | 缓解措施 |
|---|------|--------|----------|
| 1 | Cookie 过期导致 API 400 | 中 | `check()` 健康检查 + 自动回退到 fallback tier + 缓存已有数据 |
| 2 | `rookiepy` 未安装 | 低 | Tier 2 跳过，回退到 Tier 1/3；pyproject.toml 中为可选依赖 |
| 3 | 雪球 API 限流/封禁 | 高 | 500ms 最小请求间隔 + _memory_cache + 优雅降级（失败时跳过，不阻断整个数据采集） |
| 4 | 网络超时 | 中 | 10s 超时 + `asyncio.to_thread()` 不阻塞事件循环 |
| 5 | 雪球 API 变更 | 中 | 内嵌代码可独立更新，不影响其他 Skill |
| 6 | Windows 下 Cookie 权限设置 | 低 | auth.py 已有 `os.name != "nt"` 跳过逻辑 |
| 7 | search_and_quote 搜索歧义 | 低 | 搜索结果取第一条（limit=1），对歧义公司名需用户确认；日志记录搜索结果 |

### 6.1 降级策略

当雪球 API 完全不可用时，系统应**优雅降级**而非报错：

```python
# generic_agent.py _fetch_structured_data 中
try:
    skill_result = await stock_skill.execute(action=action, symbol=symbol)
    ...
except Exception as action_err:
    logger.warning(f"XueqiuSkill action '{action}' failed: {action_err}")
    # 不设置 _structured_data_fetched = True，让 web_search 补位
```

这与现有 `stock_data` 的降级行为一致。

---

## 七、实施步骤 **[已实现]**

> Phase 1-3 全部完成。Phase 4（测试）需根据项目测试框架补充。

### Phase 1：核心 Skill 实现

| 步骤 | 文件 | 内容 |
|------|------|------|
| 1.1 | `src/skills/analysis/xueqiu_skill.py` | 创建 XueqiuSkill（内嵌 _XueqiuAuth + _XueqiuAPI） |
| 1.2 | `src/skills/analysis/__init__.py` | 导出 XueqiuSkill |

### Phase 2：注册与发现

| 步骤 | 文件 | 内容 |
|------|------|------|
| 2.1 | `src/core/orchestrator/orchestrator.py` | 工厂注册 `("xueqiu", XueqiuSkill)` |
| 2.2 | `src/skills/skill_keywords.py` | 新增 xueqiu 关键词 + 描述 |
| 2.3 | `src/skills/registry.py` | CATEGORY_TO_SKILLS 加入 xueqiu |
| 2.4 | `config/keyword_mappings.yaml` | skill_inference 扩展 |

### Phase 3：数据采集路由（修复阻断问题）

| 步骤 | 文件 | 内容 |
|------|------|------|
| 3.1 | `src/core/decomposition/strategies.py` | SKILL_PRIORITY_MAP + DATA_SOURCE_SKILL_MAP + _get_data_collection_skills intent 路径 + STRUCTURED_DATA_CAPABILITIES |
| 3.2 | `src/core/agents/generic_agent.py` | _fetch_structured_data 分派 + _infer_xueqiu_actions + topic fallback |

### Phase 4：测试

| 步骤 | 内容 |
|------|------|
| 4.1 | XueqiuSkill 单元测试（各 action） |
| 4.2 | SKILL_PRIORITY_MAP 路由测试 |
| 4.3 | DATA_SOURCE_SKILL_MAP 触发测试 |
| 4.4 | _get_data_collection_skills intent 路径测试（company_research / industry_research） |
| 4.5 | STRUCTURED_DATA_CAPABILITIES 路由测试 |
| 4.6 | _fetch_structured_data 分派测试 |
| 4.7 | _infer_xueqiu_actions 测试（A 股代码 / 港股代码 / 中文名） |
| 4.8 | topic fallback 测试（EntityResolver 无法解析时） |
| 4.9 | 端到端：A 股公司研究 → stock_data + xueqiu 均触发 |
| 4.10 | 端到端：行业研究 → xueqiu 通过 intent 路径触发 |
| 4.11 | 端到端：港股研究 → search_and_quote 补位 |

---

## 八、验收标准 **[待验证]**

> 15 项验收标准中，1-14 项可通过代码审查确认已实现。第 15 项（缓存生效）需运行时验证。
> 建议编写自动化测试覆盖全部 15 项标准。

1. **注册成功**：`registry.get("xueqiu")` 返回 XueqiuSkill 实例
2. **关键词触发**：`match_skills("行情")` 包含 `"xueqiu"`
3. **分类触发**：`load_skills_for_category("financial-analysis")` 包含 `"xueqiu"`
4. **优先级正确**：`SKILL_PRIORITY_MAP["xueqiu"]` == `"structured_db"`
5. **数据源映射**：`DATA_SOURCE_SKILL_MAP["财务"]` 包含 `"xueqiu"`
6. **intent 路径**：`_get_data_collection_skills("行业趋势", intent_result=company_research)` 包含 `"xueqiu"`
7. **行业研究 intent**：`_get_data_collection_skills("市场规模", intent_result=industry_research)` 包含 `"xueqiu"` 和 `"stock_data"`
8. **结构化能力**：`derive_data_source_type("换手率")` == `"structured"`
9. **结构化数据采集**：A 股公司研究时，stock_data + xueqiu 均被调用
10. **行业研究触发**：行业研究时，xueqiu 通过 intent 路径被触发
11. **港股/美股降级**：EntityResolver 无法解析时，xueqiu 通过 search_and_quote 补位
12. **topic fallback**：symbols 为空时，xueqiu 用 topic 中文名作为 fallback
13. **优雅降级**：Cookie 过期时，xueqiu 返回 failure 但不阻断整体数据采集
14. **无阻塞**：所有 API 调用通过 `asyncio.to_thread()` 包装
15. **缓存生效**：重复请求命中 `_memory_cache`

---

## 九、修改文件清单 **[已实现]**

> 8 个文件全部已修改/新建，与方案一致。

| # | 文件 | 修改类型 | 修改内容 |
|---|------|----------|----------|
| 1 | `src/skills/analysis/xueqiu_skill.py` | **新建** | XueqiuSkill（内嵌 _XueqiuAuth + _XueqiuAPI + search_and_quote） |
| 2 | `src/skills/analysis/__init__.py` | 修改 | 导出 XueqiuSkill |
| 3 | `src/core/orchestrator/orchestrator.py` | 修改 | 工厂注册 `("xueqiu", XueqiuSkill)` |
| 4 | `src/skills/skill_keywords.py` | 修改 | 新增 xueqiu 关键词 + 描述 |
| 5 | `src/skills/registry.py` | 修改 | CATEGORY_TO_SKILLS 加入 xueqiu |
| 6 | `src/core/decomposition/strategies.py` | 修改 | SKILL_PRIORITY_MAP + DATA_SOURCE_SKILL_MAP + _get_data_collection_skills intent 路径 + STRUCTURED_DATA_CAPABILITIES |
| 7 | `src/core/agents/generic_agent.py` | 修改 | _fetch_structured_data 分派 + _infer_xueqiu_actions + topic fallback |
| 8 | `config/keyword_mappings.yaml` | 修改 | skill_inference 扩展 + stock_quote 条目 |
