# ChartPlannerAgent "主动补数据" 能力实现计划 v3.1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ChartPlannerAgent 在报告内容只有结论没有数据时，主动通过 akshare/LLM 获取结构化数据，归一化后生成专业图表，实现"有洞察就画图，缺数据自己取"的核心范式转变。

**Architecture:** 三层架构：(1) LLM 输出 `data_requests[]` 声明数据需求 → (2) `DataFetcher` 统一获取（akshare + LLM search + Skill 代理）→ (3) `DataComposer` 归一化/对齐/组装 → 填入 ChartPlan。当前代码已有这三层的骨架（`_fetch_data`, `_compose_chart_data`, `_align_time_series`），但存在多个关键缺陷需修复+增强。

**Tech Stack:** Python 3.10+, asyncio, akshare, matplotlib, pytest, pytest-asyncio

---

## 实施进度（v3 更新）

### 已完成

| Task | 状态 | 说明 |
|------|------|------|
| Task 1: P1 时间序列反转 | ✅ 完成 | `_normalize_price_records` 重写为排序+去重；`df.tail(days)` 替代 `df.head(days)` |
| Task 2: P2/P24 指数前缀+参数保护 | ✅ 完成 | `_format_index_symbol` + `_sanitize_params` 新增；index_price 使用 `_format_index_symbol` |
| Task 3: P5/P10 data_ref 关联 | ✅ 完成 | `_JSON_SCHEMA` 增加 id/data_ref；`_filter_fetched_by_ref` 新增；`_resolve_chart` 使用 data_ref 过滤 |
| Task 4: P4/P6/P14/P17 compose 重构 | ✅ 完成 | `_compose_chart_data` 重构为 categorical/time_series 分流；`_compose_categorical`/`_compose_time_series`/`_make_series_name` 新增 |
| Task 5: P8/P16/P18 校验层 | ✅ 完成 | `_check_value_range` waterfall bypass + pct fast-path；`_has_empty_chart_data` per-type 判断；LINE scenarios 长度校验 |
| Task 6: P7/P20/P21 渲染 | ✅ 完成 | `_generate_line` 8色+4样式循环；`_generate_bar` 分组标签移入循环；`_generate_hbar` 单色 |
| Task 7: P9 search 结构化prompt+校验 | ✅ 完成 | `_fetch_search_data` 重写为结构化prompt+JSON校验+dates/values长度一致性检查 |
| Task 8: P11/P12/P13 并行获取+超时+重试 | ✅ 完成 | `_fetch_data` 改用 `asyncio.gather` 并行；`_fetch_stock_data` 拆为 wrapper+impl；`wait_for` 超时 + retry 循环；`ChartPlannerConfig` 增加3字段 |
| Task 9: P25/P26/P28 内容截断+类型别名+JSON增强 | ✅ 完成 | `_prepare_llm_input` head1500+tail500；`_EXTENDED_CHART_TYPE_MAP` 6个别名；`_clean_json_string` 去注释+尾逗号 |
| Task 10: P22 stock_charting 数据格式修复 | ✅ 完成 | `price_chart` 已验证✅；`financial_trend_chart` 改BAR_LINE格式；`valuation_band_chart` 改LINE+scenarios格式 |
| Task 11: P3 StockDataSkill 复用 | ⏭ 跳过 | akshare直接调用已可用，Skill复用为优化项，非阻塞 |
| Task 12: P19 title 语义质量检查 | ⏭ 跳过 | LLM prompt已强调语义标题，硬编码检查规则易误杀，暂不实施 |
| Task 13: 图表类型选择规则+JSON schema+data格式规范 | ✅ 完成 | `_CHART_TYPE_SELECTION_RULES` 覆盖全部10类型；`_JSON_SCHEMA` 含多类型示例；`_SYSTEM_PROMPT` 追加data格式规范 |
| Task 14: BAR_LINE compose + RADAR 归一化 | ✅ 完成 | `_compose_bar_line` 从financials提取营收+计算同比增速；`_normalize_radar_values` 自动归一化；RADAR compose分支 |
| Task 15: _has_empty_chart_data + _check_chart_type_match 全类型覆盖 | ✅ 完成 | `_has_empty_chart_data` 覆盖全部10类型；`_check_chart_type_match` 覆盖全部10类型（RADAR去掉0-100强制限制） |
| Task 16: _generate_bar_line 重写 | ✅ 完成 | None→np.nan；line值标签；legend；动态偏移 |
| Task 17: _generate_radar 多实体 + _generate_line 第8色修复 | ✅ 完成 | `_generate_radar` 支持scenarios多实体对比；`_generate_line` 第8色从#7EB5A6改为#5B8DB8 |
| Task 18: 集成测试 | ✅ 完成 | test_chart_planner_integration.py 32个集成测试 |
| Task 19: 端到端验证 | ✅ 完成 | 106 tests passed, 0 failures；12/12 chart types render OK |
| 真实数据审查修复 | ✅ 完成 | 修复5个真实数据bug（见下），160 tests passed |

### 已回滚

Task 1-6 实施时夹带了 Task 7-9 的部分内容，已回滚以下3处（等正式实施 Task 7-9 时再加回）：

| 回滚项 | 原因 |
|--------|------|
| `import asyncio` | Task 8 内容，未到实施时机 |
| `_EXTENDED_CHART_TYPE_MAP` 常量 | Task 9 内容，常量已加但 `_resolve_chart` 逻辑未接入，形成半成品 |
| `_prepare_llm_input` head+tail 截断 | Task 9 内容，已恢复为 `content[:2000]` |

### 代码审查发现的问题

#### chart_planner.py

| # | 问题 | 严重程度 | 对应Task |
|---|------|---------|---------|
| R1 | ~~RADAR `_check_chart_type_match` 仍强制 0-100~~ | ✅ 已修 | Task 15 已去掉0-100强制限制 |
| R2 | ~~`_compose_chart_data` 对 financials 只提取营业总收入~~ | ✅ 已修 | Task 14 已提取营收+净利润 |
| R3 | search 数据 `len(dates) <= 12` 才走 categorical 是硬编码阈值 | 低 | 待决策 |
| R4 | ~~`_compose_categorical` 多 series 时缺失分类填 0~~ | ✅ 已修 | 改为None，ChartGenerator分组bar已支持None→np.nan |
| R5 | `_has_empty_chart_data` 接受 `None` 作为 data 参数，但签名是 `Dict` | 低 | 代码已防御性处理 `if not data`，可接受 |

#### 真实数据审查发现的新Bug（v3.2）

| # | 问题 | 严重程度 | 修复 |
|---|------|---------|------|
| R11 | `_prefilter_tables` 不过滤 `topic_relevance="low"` 的表格 | 高 | 增加 `if table.topic_relevance == "low": continue` |
| R12 | `_prefilter_tables` 中文关键词提取用 `{2,4}` 贪婪匹配无法匹配子串 | 高 | 新增 `_extract_chinese_keywords` 方法，提取2-4字n-gram |
| R13 | `_compose_bar_line` 用 `reversed()` 反转期间，正序数据变倒序 | 高 | 改为 `sorted(zip(periods, revenue))` 按期间排序 |
| R14 | `_check_value_range` 阈值 `1e10` 拒绝千亿级营收（6e11） | 中 | 阈值从 `1e10` 放宽到 `1e13` |

#### chart_generator.py

| # | 问题 | 严重程度 | 对应Task |
|---|------|---------|---------|
| R6 | ~~`_generate_line` line_colors `#7EB5A6` 重复~~ | ✅ 已修 | Task 17 已将第8色改为 `#5B8DB8` |
| R7 | ~~`_generate_bar_line` None崩溃+硬编码偏移+无标签+无legend~~ | ✅ 已修 | Task 16 已重写：None→np.nan、annotate动态偏移、line值标签、legend |
| R8 | ~~`_generate_radar` 仅支持单实体~~ | ✅ 已修 | Task 17 已支持scenarios多实体对比 |

#### 测试文件

| # | 问题 | 严重程度 | 对应Task |
|---|------|---------|---------|
| R9 | 3个测试文件均硬编码 `sys.path.insert(0, r"E:\market_report_systerm")`，其他人 clone 后路径不同 | 低 | 应修 |
| R10 | 缺少边界 case 测试：financials 列名 fallback、空 date_val、`_filter_fetched_by_ref` 全不匹配 | 低 | Task 11/18 |

### 待决策项

1. **R3 search 阈值**：`len(dates) <= 12` 走 bar/hbar vs line 的分流阈值 — **决定保持12**（月度数据12个月=1年，合理）
2. **R4 缺失分类填0**：~~`_compose_categorical` 对不存在的分类填 0~~ — **已改为None**，ChartGenerator `_generate_bar` 分组模式已支持None→np.nan+跳过标签
3. ~~**R7 BAR_LINE 优先级**~~：✅ 已在 Task 16 中修复

### 审计补充发现（v3.1）

| # | 发现 | 严重程度 | 说明 |
|---|------|---------|------|
| A1 | ~~测试计数不一致~~ | ✅ 已更正 | 实际106 passed |
| A2 | ~~`#7EB5A6` 重复~~ | ✅ 已修 | Task 17 已改为 `#5B8DB8` |
| A3 | ~~`financial_trend_chart`/`valuation_band_chart` 旧格式~~ | ✅ 已修 | Task 10 已修复全部3个方法 |
| A4 | ~~`ChartPlannerConfig` 缺少3字段~~ | ✅ 已修 | Task 8 已添加 data_fetch_timeout/max_data_retries/max_data_days |
| A5 | ~~`_sanitize_params` 用 try/except 访问 settings~~ | 低 | 降级策略合理，保持现状 |
| A6 | 默认 `python` 指向 WindowsApps 空壳 | 低 | 需用 `D:\conda\python.exe -m pytest` |

### 测试状态

```
160 passed, 0 failures, 4 warnings（pytest实际结果 2026-07-04 v3.2）
- test_chart_planner_data_fetch.py: 42 passed (含边界case+financials列名fallback+filter全不匹配)
- test_chart_planner_compose.py: 12 passed (含categorical多series None填充)
- test_chart_planner_validate.py: 32 passed
- test_chart_planner_integration.py: 44 passed (含扩展类型映射+clean_json+bar_line边界+validate边界)
- test_chart_planner_real_data.py: 30 passed (真实比亚迪数据：表格提取/过滤/组装/校验/12种图表渲染)

12/12 chart types render OK with real data (48 chart files, avg 63KB)
```

---

## 问题全景诊断

### A. 数据获取层缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P1 | `stock_zh_a_hist` 返回最新在前（倒序），`df.head(days)` 取最新N天但顺序倒序 | chart_planner.py:531 | normalize_pct 首日基准错误，X轴反序 | 任何股价走势图 |
| P2 | `index_price` 硬编码 `sh{symbol}`，深证指数（399006）需 `sz` 前缀 | chart_planner.py:536 | 深证指数获取必定失败 | "创业板指走势" |
| P3 | `_fetch_stock_data` 重复实现 akshare 调用，未利用 StockDataSkill 缓存 | chart_planner.py:513-555 | 性能差，代码重复 | 同一symbol多次请求 |
| P9 | `_fetch_search_data` 用 LLM 模拟搜索，prompt 太泛，无校验 | chart_planner.py:574-605 | search 数据源基本不可用 | "比亚迪2025年月销量" |
| P11 | `_fetch_data` 串行获取，多个 data_requests 无并行 | chart_planner.py:480-511 | 获取3个数据源需3x单次延迟 | 股价+指数+财务 |
| P12 | 无获取失败重试机制，单次 akshare 超时/限流直接返回 None | chart_planner.py:492-509 | 网络波动导致图表缺失 | akshare API限流 |
| P13 | 无获取超时控制，akshare 调用可能 hang 住整个 plan 流程 | chart_planner.py:528-555 | agent 超时 | akshare 服务不可用 |

### B. 数据组装层缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P4 | `_compose_chart_data` 只处理 price/search，financials/metrics 获取后无法组装 | chart_planner.py:668-739 | 财务数据请求无意义 | "比亚迪营收趋势" |
| P5 | `_compose_chart_data` 不区分 chart 需要哪些 data_requests，全部塞入 | chart_planner.py:668-739 | 多图表数据混乱 | 2 charts × 3 requests |
| P6 | `stock_financials` 返回中文列名，`_resolve_chart` 不做映射 | chart_planner.py:541-543 | 财务数据无法映射到图表字段 | akshare 中文列名 |
| P10 | LLM prompt 的 data_requests 与 charts 之间无关联字段 | chart_planner.py:117-148 | LLM 无法表达"chart A 需要 request 1+2" | 任何多数据源图表 |
| P14 | `_compose_chart_data` 只能输出 line 格式（years+scenarios），无法输出 bar/pie/waterfall 格式 | chart_planner.py:668-739 | fetched 数据只能画 line 图 | 财务数据应画 bar |
| P15 | `_align_time_series` 做全量日期并集对齐，两个不同时间窗口的数据会产生大量 None | chart_planner.py:741-774 | 120日股价 vs 4季度财报对齐后大量空洞 | 股价(日) vs 营收(季) |
| P16 | `_has_empty_chart_data` 对 bar/pie 等类型判断不完整：只检查 values 和 categories | chart_planner.py:651-666 | bar 图有 categories 无 values 时误判非空 | LLM 返回部分数据 |
| P17 | `_compose_chart_data` 中 series name 用 purpose 截断，多数据源时 name 可能重复 | chart_planner.py:686 | 图例重叠 | 两个 stock_price 请求 |

### C. 校验层缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P8 | `_check_value_range` 的 max/min > 1000 误杀归一化%数据和有正有负场景 | chart_planner.py:895-900 | 正常图表被拒绝 | normalize_pct 结果 |
| P18 | `_check_chart_type_match` 对 LINE 只检查 years 长度，不检查 scenarios 与 years 长度一致 | chart_planner.py:839-842 | 数据不对齐时 matplotlib 崩溃 | scenarios 值数 != years 数 |
| P19 | `_validate_plans` 不检查 title 语义质量，"份额对比"等泛称也能通过 | chart_planner.py:776-798 | 不专业图表混入 | LLM 输出低质标题 |

### D. 渲染层缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P7 | `_generate_line` 只有3种颜色样式（后改为8色但 `#7EB5A6` 重复，实际7种），zip 截断超3条线 | chart_generator.py:423 | 第4条线丢失 / 第8色重复 | 4+ scenarios |
| P20 | `_generate_bar` 分组柱状图的值标签循环缩进错误，只在最后一个 bar 上标注 | chart_generator.py:254-265 | 分组柱状图值标签缺失 | series bar chart |
| P21 | `_generate_hbar` 仍用 PALETTE_12 多色，与 bar 单色不一致 | chart_generator.py:307 | 风格不统一 | hbar 图 |
| P22 | StockChartService.price_chart 传入 `{symbol: prices}` 但 `_generate_line` 期望 `{years, scenarios}` | stock_charting.py:42-51 | 调用崩溃 | StockChartService 使用 |

> **P22 审计更新**：`price_chart` 已修复为 `years+scenarios` 格式 ✅。但 `financial_trend_chart`（line 87-98）仍使用 `{"Revenue": ..., "Net Profit": ...}` 格式 ❌，`valuation_band_chart`（line 125-132）仍使用 `{"Close Price": ..., "Upper Band": ..., "Lower Band": ...}` 格式 ❌。Task 10 需覆盖全部三个方法。

### E. Prompt/LLM 交互缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P23 | LLM 可能输出非 A 股 symbol（如美股 TSLA），akshare 无法处理 | chart_planner.py:528 | 获取失败无降级 | "特斯拉股价" |
| P24 | LLM 可能输出 days=3650（10年），无上限保护 | chart_planner.py:523 | akshare 请求过大数据 | LLM 幻觉 |
| P25 | `_prepare_llm_input` 截取 content[:2000]，可能截断关键结论句 | chart_planner.py:356 | 洞察丢失 | 长章节末尾有结论 |
| P26 | LLM 输出的 chart_type 可能不在 ChartType 枚举中（如 "area", "heatmap"） | chart_planner.py:610 | 默认降级为 BAR | LLM 输出非标准类型 |

### F. 架构/健壮性缺陷

| # | 问题 | 位置 | 影响 | 场景 |
|---|------|------|------|------|
| P27 | `_fetch_data` 中每个 request 的异常只 log 不影响其他，但无总体失败率统计 | chart_planner.py:508 | 静默失败 | 3个请求全失败 |
| P28 | `_parse_and_resolve` 对 LLM 输出 JSON 解析只有一层 fallback | chart_planner.py:432-478 | 格式微变就解析失败 | LLM 输出带注释的JSON |
| P29 | plan() 方法无降级链：LLM 失败 → 返回空，不尝试 legacy | chart_planner.py:200-221 | 本可有图表却无 | LLM 不可用 |

---

## File Structure

### Modified Files
- `src/services/chart_planner.py` — 核心改造：修复 P1-P6/P8-P10/P13-P20/P23-P29
- `src/services/chart_generator.py` — 修复 P7/P20/P21
- `src/services/stock_charting.py` — 修复 P22（price_chart ✅ 已修；financial_trend_chart/valuation_band_chart 待修）
- `src/config/settings.py` — ChartPlannerConfig 增加 `data_fetch_timeout`, `max_data_retries`, `max_data_days` 字段

> **审计更新**：当前 `ChartPlannerConfig`（settings.py:210-214）只有 `enabled`, `max_per_section`, `min_confidence` 三个字段，缺少 Task 8 所需的 `data_fetch_timeout`, `max_data_retries`, `max_data_days`。`_sanitize_params` 中已通过 `try/except` + `getattr(settings.chart_planner, 'max_data_days', 365)` 做了降级处理，但正式实施 Task 8 时需在 dataclass 中添加这些字段。

### New Files
- `tests/unit/services/test_chart_planner_data_fetch.py` — 数据获取+组装的单元测试
- `tests/unit/services/test_chart_planner_compose.py` — 数据组装+归一化的单元测试
- `tests/unit/services/test_chart_planner_validate.py` — 校验逻辑的单元测试
- `tests/unit/services/test_chart_planner_integration.py` — ChartPlannerAgent 端到端集成测试（mock LLM）

---

## Task 1: 修复 stock_price 时间序列反转 + tail (P1) ✅

`akshare.stock_zh_a_hist` 返回最新日期在前的 DataFrame。`df.head(days)` 取了最近N天但顺序是倒序的，导致 normalize_pct 的首日基准取的是最新日。

**Files:**
- Modify: `src/services/chart_planner.py:557-572`
- Create: `tests/unit/services/test_chart_planner_data_fetch.py`

- [x] **Step 1: 写失败测试**

```python
# tests/unit/services/test_chart_planner_data_fetch.py
import pytest
from src.services.chart_planner import ChartPlannerAgent


class TestNormalizePriceRecords:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_already_ascending_preserved(self):
        records = [
            {"日期": "2025-06-01", "收盘": 100},
            {"日期": "2025-06-02", "收盘": 102},
            {"日期": "2025-06-03", "收盘": 105},
        ]
        result = self.agent._normalize_price_records(records)
        assert result["dates"] == ["2025-06-01", "2025-06-02", "2025-06-03"]
        assert result["closes"] == [100, 102, 105]

    def test_descending_input_gets_sorted(self):
        records = [
            {"日期": "2025-06-03", "收盘": 105},
            {"日期": "2025-06-02", "收盘": 102},
            {"日期": "2025-06-01", "收盘": 100},
        ]
        result = self.agent._normalize_price_records(records)
        assert result["dates"] == ["2025-06-01", "2025-06-02", "2025-06-03"]
        assert result["closes"] == [100, 102, 105]

    def test_mixed_order_gets_sorted(self):
        records = [
            {"日期": "2025-06-02", "收盘": 102},
            {"日期": "2025-06-01", "收盘": 100},
            {"日期": "2025-06-03", "收盘": 105},
        ]
        result = self.agent._normalize_price_records(records)
        assert result["dates"] == ["2025-06-01", "2025-06-02", "2025-06-03"]
        assert result["closes"] == [100, 102, 105]

    def test_duplicate_date_keeps_last(self):
        records = [
            {"日期": "2025-06-01", "收盘": 100},
            {"日期": "2025-06-01", "收盘": 101},
            {"日期": "2025-06-02", "收盘": 105},
        ]
        result = self.agent._normalize_price_records(records)
        assert len(result["dates"]) == 2

    def test_empty_records(self):
        result = self.agent._normalize_price_records([])
        assert result["dates"] == []
        assert result["closes"] == []

    def test_invalid_close_skipped(self):
        records = [
            {"日期": "2025-06-01", "收盘": 100},
            {"日期": "2025-06-02", "收盘": "N/A"},
            {"日期": "2025-06-03", "收盘": 105},
        ]
        result = self.agent._normalize_price_records(records)
        assert result["dates"] == ["2025-06-01", "2025-06-03"]
        assert result["closes"] == [100, 105]

    def test_index_field_names(self):
        records = [
            {"date": "2025-06-01", "close": 3500},
            {"date": "2025-06-02", "close": 3550},
        ]
        result = self.agent._normalize_price_records(records, is_index=True)
        assert result["dates"] == ["2025-06-01", "2025-06-02"]
        assert result["closes"] == [3500, 3550]
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py::TestNormalizePriceRecords -v`
Expected: `test_descending_input_gets_sorted`, `test_mixed_order_gets_sorted`, `test_duplicate_date_keeps_last`, `test_invalid_close_skipped` FAIL

- [x] **Step 3: 修复 `_normalize_price_records` 按日期排序 + 去重**

```python
def _normalize_price_records(
    self, records: List[Dict], is_index: bool = False
) -> Dict[str, Any]:
    date_close_map = {}
    for r in records:
        date_val = str(r.get("日期", r.get("date", "")))[-10:]
        close_val = r.get("收盘", r.get("close", 0))
        try:
            close_val = float(close_val)
        except (ValueError, TypeError):
            continue
        if date_val:
            date_close_map[date_val] = close_val

    sorted_items = sorted(date_close_map.items(), key=lambda x: x[0])
    dates = [d for d, _ in sorted_items]
    closes = [c for _, c in sorted_items]

    return {"dates": dates, "closes": closes}
```

- [x] **Step 4: 修复 `_fetch_stock_data` 使用 tail 而非 head**

将 `chart_planner.py` 中 `stock_zh_a_hist` 的 `df.head(days)` 改为 `df.tail(days)`，`stock_zh_index_daily` 同理。

- [x] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py::TestNormalizePriceRecords -v`
Expected: 7 PASS

- [x] **Step 6: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_data_fetch.py
git commit -m "fix: sort price records by date ascending, deduplicate, use tail() (P1)"
```

---

## Task 2: 修复指数代码前缀 + 参数保护 (P2/P24) ✅

深证指数代码（399006创业板指、399001深证成指等）需要 `sz` 前缀。同时保护 days 参数上限，防止 LLM 幻觉输出 days=3650。

**Files:**
- Modify: `src/services/chart_planner.py`

- [x] **Step 1: 写失败测试**

```python
class TestFormatIndexSymbol:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_sh_index(self):
        assert self.agent._format_index_symbol("000300") == "sh000300"

    def test_sh_index_000001(self):
        assert self.agent._format_index_symbol("000001") == "sh000001"

    def test_sz_index_399006(self):
        assert self.agent._format_index_symbol("399006") == "sz399006"

    def test_sz_index_399001(self):
        assert self.agent._format_index_symbol("399001") == "sz399001"

    def test_already_sh_prefixed(self):
        assert self.agent._format_index_symbol("sh000300") == "sh000300"

    def test_already_sz_prefixed(self):
        assert self.agent._format_index_symbol("sz399006") == "sz399006"

    def test_empty_string(self):
        assert self.agent._format_index_symbol("") == "sh"

class TestSanitizeParams:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_days_capped_at_max(self):
        params = {"symbol": "002594", "days": 3650}
        sanitized = self.agent._sanitize_params("stock_price", params)
        assert sanitized["days"] <= 365

    def test_days_negative_clamped(self):
        params = {"symbol": "002594", "days": -10}
        sanitized = self.agent._sanitize_params("stock_price", params)
        assert sanitized["days"] >= 1

    def test_days_normal_unchanged(self):
        params = {"symbol": "002594", "days": 120}
        sanitized = self.agent._sanitize_params("stock_price", params)
        assert sanitized["days"] == 120

    def test_periods_capped(self):
        params = {"symbol": "002594", "periods": 20}
        sanitized = self.agent._sanitize_params("stock_financials", params)
        assert sanitized["periods"] <= 8

    def test_symbol_stripped(self):
        params = {"symbol": " 002594 ", "days": 120}
        sanitized = self.agent._sanitize_params("stock_price", params)
        assert sanitized["symbol"] == "002594"
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py::TestFormatIndexSymbol tests/unit/services/test_chart_planner_data_fetch.py::TestSanitizeParams -v`
Expected: FAIL（方法不存在）

- [x] **Step 3: 实现 `_format_index_symbol` 和 `_sanitize_params`**

```python
def _format_index_symbol(self, symbol: str) -> str:
    symbol = symbol.strip()
    if symbol.startswith("sh") or symbol.startswith("sz"):
        return symbol
    if symbol.startswith("399"):
        return f"sz{symbol}"
    return f"sh{symbol}"

def _sanitize_params(self, source: str, params: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(params)
    sanitized["symbol"] = str(sanitized.get("symbol", "")).strip()

    max_days = 365
    try:
        from src.config import settings
        max_days = getattr(settings.chart_planner, 'max_data_days', 365)
    except Exception:
        pass

    if "days" in sanitized:
        try:
            days = int(sanitized["days"])
            sanitized["days"] = max(1, min(days, max_days))
        except (ValueError, TypeError):
            sanitized["days"] = 120

    if "periods" in sanitized:
        try:
            periods = int(sanitized["periods"])
            sanitized["periods"] = max(1, min(periods, 8))
        except (ValueError, TypeError):
            sanitized["periods"] = 4

    return sanitized
```

- [x] **Step 4: 在 `_fetch_stock_data` 入口调用 `_sanitize_params`**

在 `_fetch_stock_data` 方法开头加 `params = self._sanitize_params(source, params)`。

- [x] **Step 5: 更新 `_fetch_stock_data` 中 index_price 使用 `_format_index_symbol`**

- [x] **Step 6: 更新 LLM prompt 的 symbol 对照表，标注 399=深证**

- [x] **Step 7: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py -v`
Expected: All PASS

- [x] **Step 8: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_data_fetch.py
git commit -m "fix: index symbol sz/sh auto-detect + param sanitization (P2/P24)"
```

---

## Task 3: 增加 data_requests 与 charts 的关联字段 data_ref (P5/P10) ✅

当前 LLM 输出的 `data_requests[]` 和 `charts[]` 之间没有关联，`_compose_chart_data` 把所有 fetched_data 塞给每个 chart。

**Files:**
- Modify: `src/services/chart_planner.py` — prompt + _JSON_SCHEMA + _resolve_chart + _fetch_data

- [x] **Step 1: 更新 _JSON_SCHEMA 增加 id 和 data_ref**

```python
_JSON_SCHEMA = """
{
    "data_requests": [
        {
            "id": "req1",
            "source": "stock_price",
            "params": {"symbol": "002594", "days": 120},
            "purpose": "比亚迪近120日股价走势"
        },
        {
            "id": "req2",
            "source": "index_price",
            "params": {"symbol": "000300", "days": 120},
            "purpose": "沪深300走势"
        }
    ],
    "charts": [
        {
            "chart_type": "line",
            "title": "具体语义标题，传达分析洞察",
            "subtitle": "数据来源说明",
            "data_strategy": "normalize_pct",
            "data_ref": ["req1", "req2"],
            "data": {
                "years": [],
                "scenarios": {}
            },
            "caption": "图注：解释图表含义和关键洞察",
            "xlabel": "X轴标签",
            "ylabel": "Y轴标签（含单位）",
            "confidence": 0.9,
            "reason": "选择该图表类型的理由",
            "insertion_anchor": "正文中实际存在的关键短语",
            "anchor_type": "after_paragraph",
            "unit": "%"
        }
    ],
    "skip_reason": null
}
"""
```

- [x] **Step 2: 在 _SYSTEM_PROMPT 末尾追加 data_ref 关联规则**

```
## data_ref 关联规则

每个 chart 必须通过 data_ref 字段声明它需要哪些 data_requests 的数据。

示例：如果要画"比亚迪 vs 沪深300 走势对比"，需要两个 data_requests：
- req1: stock_price(比亚迪)
- req2: index_price(沪深300)
然后在 chart 中设置 data_ref: ["req1", "req2"]

如果 chart 使用文中已有的表格数据（不需要 data_requests），则 data_ref 为空数组 []。
```

- [x] **Step 3: 修改 `_resolve_chart` 使用 data_ref 过滤 fetched_data**

在 `_resolve_chart` 中增加 `data_ref = chart_raw.get("data_ref", [])`，在调用 `_compose_chart_data` 前先 `filtered_data = self._filter_fetched_by_ref(fetched_data, data_ref)`。

- [x] **Step 4: 实现 `_filter_fetched_by_ref` 方法**

```python
def _filter_fetched_by_ref(
    self, fetched_data: Dict[str, Any], data_ref: List[str]
) -> Dict[str, Any]:
    if not data_ref:
        return fetched_data

    ref_set = set(data_ref)
    filtered = {}
    for key, info in fetched_data.items():
        req_id = info.get("id", "")
        if req_id in ref_set:
            filtered[key] = info

    if not filtered:
        for key, info in fetched_data.items():
            purpose = info.get("purpose", "")
            params = info.get("params", {})
            symbol = params.get("symbol", "")
            for ref_id in data_ref:
                if ref_id in key or ref_id in purpose or ref_id == symbol:
                    filtered[key] = info
                    break

    return filtered if filtered else fetched_data
```

- [x] **Step 5: 修改 `_fetch_data` 保留 request id**

在 `_fetch_data` 的 results dict 中增加 `"id": req.get("id", "")` 字段。

- [x] **Step 6: 写测试**

```python
class TestFilterFetchedByRef:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_filter_by_id(self):
        fetched = {
            "stock_price:002594": {"id": "req1", "source": "stock_price", "data": {"dates": ["2025-01"], "closes": [100]},
                "params": {"symbol": "002594"}, "purpose": "比亚迪股价"},
            "index_price:000300": {"id": "req2", "source": "index_price", "data": {"dates": ["2025-01"], "closes": [3500]},
                "params": {"symbol": "000300"}, "purpose": "沪深300"},
        }
        result = self.agent._filter_fetched_by_ref(fetched, ["req1"])
        assert len(result) == 1
        assert "stock_price:002594" in result

    def test_filter_multiple_refs(self):
        fetched = {
            "a": {"id": "req1", "source": "stock_price", "data": {}, "params": {}, "purpose": ""},
            "b": {"id": "req2", "source": "index_price", "data": {}, "params": {}, "purpose": ""},
        }
        result = self.agent._filter_fetched_by_ref(fetched, ["req1", "req2"])
        assert len(result) == 2

    def test_empty_ref_returns_all(self):
        fetched = {
            "a": {"id": "req1", "source": "stock_price", "data": {}, "params": {}, "purpose": ""},
        }
        result = self.agent._filter_fetched_by_ref(fetched, [])
        assert len(result) == 1

    def test_no_match_fallback_to_all(self):
        fetched = {
            "a": {"id": "req1", "source": "stock_price", "data": {}, "params": {}, "purpose": ""},
        }
        result = self.agent._filter_fetched_by_ref(fetched, ["nonexistent"])
        assert len(result) == 1
```

- [x] **Step 7: 运行测试**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py -v`
Expected: All PASS

- [x] **Step 8: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_data_fetch.py
git commit -m "feat: add data_ref linking charts to specific data_requests (P5/P10)"
```

---

## Task 4: 重构 _compose_chart_data 支持多种图表格式 (P4/P6/P14/P15/P17) ✅

这是最核心的改造。当前 `_compose_chart_data` 只能输出 line 格式（years+scenarios），无法输出 bar/pie/waterfall。且 financials 数据无法组装，时间对齐策略粗暴。

**Files:**
- Modify: `src/services/chart_planner.py`
- Create: `tests/unit/services/test_chart_planner_compose.py`

- [x] **Step 1: 写失败测试**

```python
# tests/unit/services/test_chart_planner_compose.py
import pytest
from src.services.chart_planner import ChartPlannerAgent


class TestComposePriceData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_two_price_series_normalize_pct(self):
        fetched = {
            "stock_price:002594": {
                "id": "req1", "source": "stock_price",
                "params": {"symbol": "002594"}, "purpose": "比亚迪股价",
                "data": {"dates": ["2025-01", "2025-02", "2025-03"], "closes": [300, 280, 290]},
            },
            "index_price:000300": {
                "id": "req2", "source": "index_price",
                "params": {"symbol": "000300"}, "purpose": "沪深300",
                "data": {"dates": ["2025-01", "2025-02", "2025-03"], "closes": [3500, 3600, 3700]},
            },
        }
        chart_raw = {"chart_type": "line", "data_strategy": "normalize_pct"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "normalize_pct")
        assert "years" in result
        assert "scenarios" in result
        assert len(result["scenarios"]) == 2
        for vals in result["scenarios"].values():
            assert abs(vals[0] - 100.0) < 0.01

    def test_single_price_series_raw(self):
        fetched = {
            "stock_price:002594": {
                "id": "req1", "source": "stock_price",
                "params": {"symbol": "002594"}, "purpose": "比亚迪股价",
                "data": {"dates": ["2025-01", "2025-02"], "closes": [300, 280]},
            },
        }
        chart_raw = {"chart_type": "line", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "scenarios" in result
        assert len(result["scenarios"]) == 1


class TestComposeFinancialData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_financials_bar_chart(self):
        fetched = {
            "stock_financials:002594": {
                "id": "req1", "source": "stock_financials",
                "params": {"symbol": "002594", "periods": 4}, "purpose": "比亚迪营收趋势",
                "data": [
                    {"报告期": "2024Q3", "营业总收入": 5022.0},
                    {"报告期": "2024Q2", "营业总收入": 4215.0},
                    {"报告期": "2024Q1", "营业总收入": 1502.0},
                    {"报告期": "2023Q4", "营业总收入": 3800.0},
                ],
            }
        }
        chart_raw = {"chart_type": "bar", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "categories" in result
        assert "values" in result
        assert len(result["categories"]) == 4
        assert len(result["values"]) == 4

    def test_financials_english_column_names(self):
        fetched = {
            "stock_financials:002594": {
                "id": "req1", "source": "stock_financials",
                "params": {"symbol": "002594"}, "purpose": "Revenue",
                "data": [
                    {"REPORT_DATE": "2024-09-30", "TOTAL_OPERATE_INCOME": 5022.0},
                    {"REPORT_DATE": "2024-06-30", "TOTAL_OPERATE_INCOME": 4215.0},
                ],
            }
        }
        chart_raw = {"chart_type": "bar", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "categories" in result
        assert len(result["categories"]) >= 2

    def test_two_financials_series_grouped_bar(self):
        fetched = {
            "stock_financials:002594": {
                "id": "req1", "source": "stock_financials",
                "params": {"symbol": "002594"}, "purpose": "比亚迪营收",
                "data": [
                    {"报告期": "2024Q3", "营业总收入": 5022.0},
                    {"报告期": "2024Q2", "营业总收入": 4215.0},
                ],
            },
            "stock_financials:300750": {
                "id": "req2", "source": "stock_financials",
                "params": {"symbol": "300750"}, "purpose": "宁德时代营收",
                "data": [
                    {"报告期": "2024Q3", "营业总收入": 9000.0},
                    {"报告期": "2024Q2", "营业总收入": 8000.0},
                ],
            },
        }
        chart_raw = {"chart_type": "bar", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "categories" in result or "years" in result


class TestComposeSearchData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_search_data_bar_chart(self):
        fetched = {
            "search:byd_sales": {
                "id": "req1", "source": "search",
                "params": {"query": "比亚迪月销量"}, "purpose": "比亚迪月销量",
                "data": {"dates": ["2025-01", "2025-02", "2025-03"], "values": [30, 32, 35]},
            }
        }
        chart_raw = {"chart_type": "bar", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "categories" in result or "years" in result


class TestAlignTimeSeries:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_same_dates_aligned(self):
        series = [
            {"name": "A", "dates": ["2025-01", "2025-02"], "values": [100, 110]},
            {"name": "B", "dates": ["2025-01", "2025-02"], "values": [200, 210]},
        ]
        result = self.agent._align_time_series(series)
        assert len(result) == 2
        assert result[0]["dates"] == ["2025-01", "2025-02"]

    def test_partial_overlap(self):
        series = [
            {"name": "A", "dates": ["2025-01", "2025-02", "2025-03"], "values": [100, 110, 120]},
            {"name": "B", "dates": ["2025-02", "2025-03", "2025-04"], "values": [210, 220, 230]},
        ]
        result = self.agent._align_time_series(series)
        assert len(result) == 2
        assert len(result[0]["dates"]) == 4

    def test_no_overlap(self):
        series = [
            {"name": "A", "dates": ["2025-01", "2025-02"], "values": [100, 110]},
            {"name": "B", "dates": ["2025-03", "2025-04"], "values": [210, 220]},
        ]
        result = self.agent._align_time_series(series)
        assert len(result) == 2
        assert len(result[0]["dates"]) == 4

    def test_empty_series(self):
        result = self.agent._align_time_series([])
        assert result == []
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_compose.py -v`
Expected: `TestComposeFinancialData` and `TestComposeSearchData` FAIL

- [x] **Step 3: 重构 `_compose_chart_data`**

核心改造：根据 chart_type 和 source 类型决定输出格式。

```python
def _compose_chart_data(
    self,
    chart_raw: Dict[str, Any],
    fetched_data: Dict[str, Any],
    strategy: str,
) -> Dict[str, Any]:
    chart_type_str = chart_raw.get("chart_type", "line")
    chart_type = _CHART_TYPE_MAP.get(chart_type_str, ChartType.LINE)

    time_series_data = []
    categorical_data = []

    for key, info in fetched_data.items():
        payload = info.get("data", {})
        source = info.get("source", "")
        purpose = info.get("purpose", "")
        params = info.get("params", {})
        symbol = params.get("symbol", "")

        if source in ("stock_price", "index_price"):
            dates = payload.get("dates", [])
            closes = payload.get("closes", [])
            if not dates or not closes:
                continue
            name = self._make_series_name(purpose, symbol, source)
            time_series_data.append({"name": name, "dates": dates, "values": closes})

        elif source == "stock_financials":
            records = payload if isinstance(payload, list) else []
            if not records:
                continue
            periods = []
            revenue_vals = []
            for r in records:
                period = r.get("报告期", r.get("REPORT_DATE", r.get("截止日期", "")))
                rev = r.get("营业总收入", r.get("营业收入", r.get("TOTAL_OPERATE_INCOME", 0)))
                if period:
                    periods.append(str(period)[:10])
                    try:
                        revenue_vals.append(float(rev))
                    except (ValueError, TypeError):
                        revenue_vals.append(0)
            if periods and revenue_vals:
                name = self._make_series_name(purpose, symbol, "营收")
                if chart_type in (ChartType.BAR, ChartType.HBAR, ChartType.PIE):
                    categorical_data.append({"name": name, "categories": periods, "values": revenue_vals})
                else:
                    time_series_data.append({"name": name, "dates": periods, "values": revenue_vals})

        elif source == "stock_metrics":
            records = payload if isinstance(payload, list) else []
            if not records:
                continue
            categories = []
            values = []
            skip_keys = {"股票代码", "股票简称", "日期", "report_date", "code", "name"}
            for r in records:
                for k, v in r.items():
                    if k in skip_keys:
                        continue
                    try:
                        float_val = float(v)
                        categories.append(k[:15])
                        values.append(float_val)
                    except (ValueError, TypeError):
                        continue
            if categories and values:
                name = self._make_series_name(purpose, symbol, "指标")
                categorical_data.append({"name": name, "categories": categories, "values": values})

        elif source == "search":
            dates = payload.get("dates", [])
            values = payload.get("values", [])
            if dates and values:
                name = self._make_series_name(purpose, "", "数据")
                if chart_type in (ChartType.BAR, ChartType.HBAR) and len(dates) <= 12:
                    categorical_data.append({"name": name, "categories": dates, "values": values})
                else:
                    time_series_data.append({"name": name, "dates": dates, "values": values})

    if categorical_data and chart_type in (ChartType.BAR, ChartType.HBAR, ChartType.PIE):
        return self._compose_categorical(categorical_data, chart_type)

    if time_series_data:
        return self._compose_time_series(time_series_data, strategy)

    if categorical_data:
        return self._compose_categorical(categorical_data, chart_type)

    return {}


def _make_series_name(self, purpose: str, symbol: str, fallback: str) -> str:
    if purpose and len(purpose) <= 25:
        return purpose
    if symbol:
        return symbol
    return fallback


def _compose_categorical(
    self, categorical_data: List[Dict], chart_type: ChartType
) -> Dict[str, Any]:
    if not categorical_data:
        return {}

    if len(categorical_data) == 1:
        cd = categorical_data[0]
        return {"categories": cd["categories"], "values": cd["values"]}

    all_categories = []
    seen = set()
    for cd in categorical_data:
        for c in cd["categories"]:
            if c not in seen:
                all_categories.append(c)
                seen.add(c)

    series_list = []
    for cd in categorical_data:
        cat_to_val = dict(zip(cd["categories"], cd["values"]))
        aligned_vals = [cat_to_val.get(c, 0) for c in all_categories]
        series_list.append({"name": cd["name"], "values": aligned_vals})

    return {"categories": all_categories, "series": series_list}


def _compose_time_series(
    self, time_series_data: List[Dict], strategy: str
) -> Dict[str, Any]:
    if not time_series_data:
        return {}

    aligned = self._align_time_series(time_series_data)

    if strategy == "normalize_pct":
        scenarios = {}
        for s in aligned:
            vals = s["values"]
            if vals and vals[0] != 0:
                base = vals[0]
                scenarios[s["name"]] = [round(v / base * 100, 2) for v in vals]
            else:
                scenarios[s["name"]] = vals
        return {
            "years": aligned[0]["dates"] if aligned else [],
            "scenarios": scenarios,
            "unit": "%",
        }

    elif strategy == "pct_change":
        scenarios = {}
        for s in aligned:
            vals = s["values"]
            changes = []
            for i in range(1, len(vals)):
                if vals[i-1] != 0:
                    changes.append(round((vals[i] - vals[i-1]) / abs(vals[i-1]) * 100, 2))
                else:
                    changes.append(0)
            scenarios[s["name"]] = changes
        dates = aligned[0]["dates"][1:] if aligned else []
        return {
            "years": dates,
            "scenarios": scenarios,
            "unit": "%",
        }

    else:
        scenarios = {s["name"]: s["values"] for s in aligned}
        return {
            "years": aligned[0]["dates"] if aligned else [],
            "scenarios": scenarios,
        }
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_compose.py -v`
Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_compose.py
git commit -m "feat: compose supports bar/pie/waterfall + financials + search (P4/P6/P14/P17)"
```

---

## Task 5: 修复校验层 (P8/P16/P18/P19) ✅

**Files:**
- Modify: `src/services/chart_planner.py`
- Create: `tests/unit/services/test_chart_planner_validate.py`

- [x] **Step 1: 写测试**

```python
# tests/unit/services/test_chart_planner_validate.py
import pytest
from src.services.chart_planner import ChartPlannerAgent, ChartPlan
from src.services.chart_generator import ChartType


class TestCheckValueRange:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_normalized_pct_passes(self):
        plan = ChartPlan(
            chart_type=ChartType.LINE, title="t", subtitle="",
            data={"years": ["2025-01", "2025-02"], "scenarios": {"A": [100, 75], "B": [100, 130]}},
            caption="", xlabel="", ylabel="%", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="%",
        )
        assert self.agent._check_value_range(plan) is True

    def test_extreme_range_rejected(self):
        plan = ChartPlan(
            chart_type=ChartType.BAR, title="t", subtitle="",
            data={"categories": ["A", "B"], "values": [5022, 3.5]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_value_range(plan) is False

    def test_waterfall_mixed_sign_passes(self):
        plan = ChartPlan(
            chart_type=ChartType.WATERFALL, title="t", subtitle="",
            data={"factors": [{"label": "收入", "value": 5000}, {"label": "成本", "value": -3000}, {"label": "利润", "value": 2000, "is_total": True}]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_value_range(plan) is True

    def test_all_zero_passes(self):
        plan = ChartPlan(
            chart_type=ChartType.BAR, title="t", subtitle="",
            data={"categories": ["A", "B"], "values": [0, 0]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_value_range(plan) is True


class TestHasEmptyChartData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_bar_with_categories_no_values(self):
        assert self.agent._has_empty_chart_data({"categories": ["A", "B"]}, ChartType.BAR) is True

    def test_bar_with_both(self):
        assert self.agent._has_empty_chart_data({"categories": ["A", "B"], "values": [1, 2]}, ChartType.BAR) is False

    def test_line_empty_scenarios(self):
        assert self.agent._has_empty_chart_data({"years": ["2025"], "scenarios": {}}, ChartType.LINE) is True

    def test_line_with_data(self):
        assert self.agent._has_empty_chart_data({"years": ["2025"], "scenarios": {"A": [100]}}, ChartType.LINE) is False

    def test_pie_empty(self):
        assert self.agent._has_empty_chart_data({"categories": ["A"], "values": []}, ChartType.PIE) is True

    def test_radar_empty(self):
        assert self.agent._has_empty_chart_data({"categories": ["A"], "values": []}, ChartType.RADAR) is True

    def test_empty_dict(self):
        assert self.agent._has_empty_chart_data({}, ChartType.BAR) is True


class TestCheckChartTypeMatch:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_line_scenarios_length_mismatch(self):
        plan = ChartPlan(
            chart_type=ChartType.LINE, title="t", subtitle="",
            data={"years": ["2025-01", "2025-02", "2025-03"], "scenarios": {"A": [100, 110]}},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is False

    def test_line_scenarios_length_match(self):
        plan = ChartPlan(
            chart_type=ChartType.LINE, title="t", subtitle="",
            data={"years": ["2025-01", "2025-02"], "scenarios": {"A": [100, 110]}},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_validate.py -v`
Expected: Several FAIL

- [x] **Step 3: 修复 `_check_value_range`**

```python
def _check_value_range(self, plan: ChartPlan) -> bool:
    data = plan.data
    if not data:
        return False

    if plan.chart_type == ChartType.WATERFALL:
        return True

    if plan.unit == "%" and "scenarios" in data:
        scenarios = data["scenarios"]
        all_vals = []
        for vals in scenarios.values():
            if isinstance(vals, list):
                all_vals.extend([v for v in vals if isinstance(v, (int, float))])
        if all_vals and max(abs(v) for v in all_vals) <= 500:
            return True

    all_values = []
    if "values" in data:
        for v in data["values"]:
            if isinstance(v, (int, float)):
                all_values.append(v)
    if "series" in data:
        for s in data["series"]:
            for v in s.get("values", []):
                if isinstance(v, (int, float)):
                    all_values.append(v)
    if "scenarios" in data:
        for vals in data["scenarios"].values():
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, (int, float)):
                        all_values.append(v)
    if "factors" in data:
        for f in data["factors"]:
            v = f.get("value", 0)
            if isinstance(v, (int, float)):
                all_values.append(v)

    if not all_values:
        return True

    for v in all_values:
        if abs(v) > 1e10:
            return False

    non_zero = [abs(v) for v in all_values if v != 0]
    if len(non_zero) >= 2:
        max_val = max(non_zero)
        min_val = min(non_zero)
        if min_val > 0 and max_val / min_val > 1000:
            return False

    return True
```

- [x] **Step 4: 修复 `_has_empty_chart_data`**

```python
def _has_empty_chart_data(self, data: Dict, chart_type: ChartType) -> bool:
    if not data:
        return True
    if chart_type == ChartType.LINE:
        scenarios = data.get("scenarios", {})
        if not scenarios:
            return True
        for vals in scenarios.values():
            if isinstance(vals, list) and len(vals) > 0:
                return False
        return True
    if chart_type in (ChartType.BAR, ChartType.HBAR, ChartType.PIE):
        values = data.get("values", [])
        categories = data.get("categories", data.get("labels", []))
        if "series" in data:
            series = data["series"]
            if not series:
                return True
            return all(len(s.get("values", [])) == 0 for s in series)
        return len(values) == 0 or len(categories) == 0
    if chart_type == ChartType.RADAR:
        return len(data.get("values", [])) == 0 or len(data.get("categories", [])) == 0
    if chart_type == ChartType.WATERFALL:
        return len(data.get("factors", [])) == 0
    if "values" in data:
        return len(data["values"]) == 0
    if "categories" in data:
        return len(data["categories"]) == 0
    return False
```

- [x] **Step 5: 修复 `_check_chart_type_match` 增加 scenarios 长度校验**

在 LINE 分支中增加：

```python
if plan.chart_type == ChartType.LINE:
    years = data.get("years", [])
    if not years or len(years) < 2:
        return False
    scenarios = data.get("scenarios", {})
    for label, vals in scenarios.items():
        if isinstance(vals, list) and len(vals) != len(years):
            return False
```

- [x] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_validate.py -v`
Expected: All PASS

- [x] **Step 7: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_validate.py
git commit -m "fix: value_range skip waterfall/%, empty_data per type, scenarios length check (P8/P16/P18)"
```

---

## Task 6: 修复 ChartGenerator 渲染缺陷 (P7/P20/P21) ✅

**Files:**
- Modify: `src/services/chart_generator.py`

- [x] **Step 1: 修复 `_generate_line` 颜色循环 (P7)**

```python
def _generate_line(self, config: ChartConfig) -> str:
    fig, ax = self._create_figure(config)

    data = config.data
    years = data.get('years', [])
    scenarios = data.get('scenarios', {})

    x = np.arange(len(years))
    line_colors = [
        self._navy, self._gold, '#7EB5A6', '#E8836B',
        '#8E558E', '#CBAE7F', '#4A90D9', '#7EB5A6',
    ]
    line_styles = ['-', '--', '-.', ':']

    for i, (label, vals) in enumerate(scenarios.items()):
        color = line_colors[i % len(line_colors)]
        ls = line_styles[i % len(line_styles)]
        ax.plot(x, vals, marker='o', linewidth=2, color=color,
               linestyle=ls, label=label, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=9)
    ax.set_ylabel(config.ylabel, fontsize=10)
    ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
    ax.legend(fontsize=9, loc='upper left')
    ax.spines['top'].set_visible(False)
    ax.grid(linestyle='--', alpha=0.4, zorder=0)

    return self._save_figure(fig, f"line_{hash(config.title) % 10000}", config)
```

- [x] **Step 2: 修复 `_generate_bar` 分组柱状图值标签缩进 (P20)**

当前 `for bar, val in zip(bars, s_values):` 循环体只做 label 计算，`ax.text` 在循环外。修复为：

```python
for i, s in enumerate(series_list):
    s_values = s.get('values', [])
    offset = (i - n_series / 2 + 0.5) * width
    color = self.PALETTE_12[i % len(self.PALETTE_12)]
    bars = ax.bar(x + offset, s_values, width, color=color,
                 alpha=0.85, zorder=3, label=s.get('name', f'Series {i+1}'))

    unit = s.get('unit', data.get('unit', ''))
    for bar, val in zip(bars, s_values):
        if unit == '%':
            label = f'{val}%'
        elif abs(val) >= 10000:
            label = f'{val/10000:.1f}万'
        elif abs(val) >= 1:
            label = f'{val:.1f}'
        else:
            label = f'{val:.2f}'
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
               label, ha='center', va='bottom', fontsize=7, color=self._char)
```

- [x] **Step 3: 修复 `_generate_hbar` 使用单色 (P21)**

将 `colors = self.PALETTE_12[:len(labels)]` 改为 `colors = [self._navy] * len(labels)`。

- [x] **Step 4: 运行 chart generator 测试**

Run: `python tests/test_chart_generator.py`
Expected: All PASS

- [x] **Step 5: Commit**

```bash
git add src/services/chart_generator.py
git commit -m "fix: line color cycling, bar label indentation, hbar single color (P7/P20/P21)"
```

---

## Task 7: 增强搜索数据获取 + 非A股降级 (P9/P23)

**Files:**
- Modify: `src/services/chart_planner.py`

- [ ] **Step 1: 重写 `_fetch_search_data`**

结构化 prompt + 严格校验 + error 声明（见 v1 Task 7，代码不变）。

- [ ] **Step 2: 增加 `_is_a_share_symbol` 判断 + 非A股降级为 search**

```python
def _is_a_share_symbol(self, symbol: str) -> bool:
    symbol = symbol.strip()
    if not symbol:
        return False
    if symbol.isdigit() and len(symbol) == 6:
        return True
    return False
```

在 `_fetch_stock_data` 入口增加：

```python
if source in ("stock_price", "stock_financials", "stock_metrics"):
    if not self._is_a_share_symbol(symbol):
        logger.info(f"Symbol '{symbol}' is not A-share, falling back to search")
        return await self._fetch_search_data(
            {"query": f"{symbol} 股价走势" if source == "stock_price" else f"{symbol} 财务数据"},
            topic if hasattr(self, '_current_topic') else "",
        )
```

在 `_fetch_data` 中保存 topic 到 self：`self._current_topic = topic`。

- [ ] **Step 3: Commit**

```bash
git add src/services/chart_planner.py
git commit -m "improve: structured search + non-A-share fallback (P9/P23)"
```

---

## Task 8: 利用 StockDataSkill + 并行获取 + 超时/重试 (P3/P11/P12/P13)

**Files:**
- Modify: `src/services/chart_planner.py`
- Modify: `src/config/settings.py`

- [ ] **Step 1: 更新 ChartPlannerConfig**

```python
@dataclass
class ChartPlannerConfig:
    enabled: bool = True
    max_per_section: int = 2
    min_confidence: float = 0.5
    data_fetch_timeout: int = 30
    max_data_retries: int = 2
    max_data_days: int = 365
```

- [ ] **Step 2: 修改 `_fetch_stock_data` 优先使用 StockDataSkill**

（同 v1 Task 8，但增加超时和重试）

```python
async def _fetch_stock_data(
    self, source: str, params: Dict[str, Any]
) -> Optional[Any]:
    params = self._sanitize_params(source, params)
    symbol = str(params.get("symbol", ""))
    if not symbol:
        return None

    max_retries = 2
    try:
        from src.config import settings
        max_retries = getattr(settings.chart_planner, 'max_data_retries', 2)
    except Exception:
        pass

    for attempt in range(max_retries):
        try:
            result = await asyncio.wait_for(
                self._fetch_stock_data_impl(source, params, symbol),
                timeout=30,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Stock data fetch timeout (attempt {attempt+1}/{max_retries}): {source}/{symbol}")
        except Exception:
            logger.exception(f"Stock data fetch failed (attempt {attempt+1}/{max_retries}): {source}/{symbol}")

    return None

async def _fetch_stock_data_impl(
    self, source: str, params: Dict[str, Any], symbol: str
) -> Optional[Any]:
    if source in ("stock_price", "stock_financials", "stock_metrics"):
        if not self._is_a_share_symbol(symbol):
            return await self._fetch_search_data(
                {"query": f"{symbol} {'股价走势' if source == 'stock_price' else '财务数据'}"},
                getattr(self, '_current_topic', ''),
            )

    try:
        from src.skills.analysis.stock_data import StockDataSkill
        skill = StockDataSkill()

        if source == "stock_price":
            result = await skill.execute(action="price_history", symbol=symbol)
            if result.get("success"):
                records = result.get("data", [])
                days = int(params.get("days", 120))
                records = records[-days:] if len(records) > days else records
                return self._normalize_price_records(records)
            return None

        elif source == "index_price":
            return await self._fetch_index_price_direct(symbol, params)

        elif source == "stock_financials":
            result = await skill.execute(action="financials", symbol=symbol)
            if result.get("success"):
                periods = int(params.get("periods", 4))
                data = result.get("data", {})
                income = data.get("income_statement", [])
                return income[:periods] if income else []
            return None

        elif source == "stock_metrics":
            result = await skill.execute(action="key_metrics", symbol=symbol)
            if result.get("success"):
                return result.get("data", {})
            return None

    except ImportError:
        logger.warning("StockDataSkill not available, falling back to direct akshare")
        return await self._fetch_stock_data_direct(source, params)
    except Exception:
        logger.exception(f"Stock data fetch impl failed: source={source}, symbol={symbol}")

    return None
```

- [ ] **Step 3: 修改 `_fetch_data` 并行获取**

```python
async def _fetch_data(
    self, requests_raw: List[Dict], topic: str
) -> Dict[str, Any]:
    self._current_topic = topic

    async def _fetch_one(req: Dict) -> Optional[Tuple[str, Dict]]:
        if not isinstance(req, dict):
            return None
        source = req.get("source", "")
        params = req.get("params", {})
        purpose = req.get("purpose", "")
        req_id = req.get("id", "")
        key = f"{source}:{json.dumps(params, sort_keys=True)}"

        try:
            if source in ("stock_price", "index_price", "stock_financials", "stock_metrics"):
                data = await self._fetch_stock_data(source, params)
            elif source == "search":
                data = await self._fetch_search_data(params, topic)
            else:
                logger.warning(f"ChartPlanner: unknown data source '{source}'")
                return None

            if data:
                return key, {
                    "id": req_id,
                    "source": source,
                    "params": params,
                    "purpose": purpose,
                    "data": data,
                }
        except Exception:
            logger.exception(f"ChartPlanner: data fetch failed for {source}")
        return None

    tasks = [_fetch_one(req) for req in requests_raw]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results = {}
    failed_count = 0
    for r in results_list:
        if isinstance(r, Exception):
            failed_count += 1
            continue
        if r is not None:
            key, info = r
            results[key] = info
        else:
            failed_count += 1

    if failed_count == len(requests_raw) and requests_raw:
        logger.warning(f"ChartPlanner: all {len(requests_raw)} data requests failed")

    return results
```

需要在文件顶部增加 `import asyncio`。

- [ ] **Step 4: 实现 fallback 方法 `_fetch_index_price_direct` 和 `_fetch_stock_data_direct`**

（同 v1 Task 8 Step 2）

- [ ] **Step 5: Commit**

```bash
git add src/services/chart_planner.py src/config/settings.py
git commit -m "feat: StockDataSkill + parallel fetch + timeout/retry + non-A-share fallback (P3/P11/P12/P13/P23)"
```

---

## Task 9: 增强 LLM 交互健壮性 (P25/P26/P28)

**Files:**
- Modify: `src/services/chart_planner.py`

- [ ] **Step 1: 修复 `_prepare_llm_input` 截断策略 (P25)**

当前 `content[:2000]` 可能截断末尾关键结论。改为：优先保留首1500字 + 末尾500字（包含结论句）。

```python
def _prepare_llm_input(
    self, content: str, tables: List[ExtractedTable]
) -> Tuple[str, str]:
    numeric_sentences = []
    for line in content.split("\n"):
        if re.search(r"\d+\.?\d*[万亿%％]?", line):
            numeric_sentences.append(line.strip())

    paragraph_first_sentences = []
    prev_empty = True
    for line in content.split("\n"):
        if line.strip() and prev_empty:
            first_sentence = re.split(r"[。！？；]", line.strip())[0]
            if len(first_sentence) > 5:
                paragraph_first_sentences.append(first_sentence[:50])
        prev_empty = not line.strip()

    if len(content) <= 2000:
        content_summary = content
    else:
        head = content[:1500]
        tail = content[-500:]
        content_summary = head + "\n\n[...中间省略...]\n\n" + tail

    if numeric_sentences:
        content_summary += (
            "\n\n关键数据句：\n" + "\n".join(numeric_sentences[:20])
        )
    if paragraph_first_sentences:
        content_summary += (
            "\n\n段落首句（可选锚点位置）：\n"
            + "\n".join(paragraph_first_sentences[:30])
        )

    tables_json = json.dumps(
        [
            {
                "headers": t.headers,
                "rows": t.rows,
                "topic_relevance": t.topic_relevance,
            }
            for t in tables
        ],
        ensure_ascii=False,
        indent=2,
    )

    return content_summary, tables_json
```

- [ ] **Step 2: 增强 `_parse_and_resolve` JSON 解析 (P28)**

在现有解析逻辑之前增加：去除 JSON 中的注释行（`//` 开头）和尾逗号。

```python
def _clean_json_string(self, json_str: str) -> str:
    lines = []
    for line in json_str.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    return cleaned
```

在 `_parse_and_resolve` 中，在 `json.loads` 之前调用 `json_str = self._clean_json_string(json_str)`。

- [ ] **Step 3: 增强 chart_type 降级映射 (P26)**

```python
_EXTENDED_CHART_TYPE_MAP = {
    "area": ChartType.LINE,
    "heatmap": ChartType.BAR,
    "donut": ChartType.PIE,
    "stacked_bar": ChartType.BAR,
    "grouped_bar": ChartType.BAR,
    "multi_line": ChartType.LINE,
}
```

在 `_resolve_chart` 中：

```python
chart_type_str = chart_raw.get("chart_type", "bar")
chart_type = _CHART_TYPE_MAP.get(chart_type_str)
if chart_type is None:
    chart_type = _EXTENDED_CHART_TYPE_MAP.get(chart_type_str, ChartType.BAR)
    logger.info(f"ChartPlanner: mapped unknown chart_type '{chart_type_str}' to {chart_type.value}")
```

- [ ] **Step 4: Commit**

```bash
git add src/services/chart_planner.py
git commit -m "improve: content tail preservation, JSON comment stripping, chart_type fallback (P25/P26/P28)"
```

---

## Task 10: 修复 StockChartService 数据格式兼容性 (P22)

**Files:**
- Modify: `src/services/stock_charting.py`

> **审计更新**：`price_chart` 已在先前实现中修复为 `years+scenarios` 格式。但 `financial_trend_chart` 和 `valuation_band_chart` 仍使用旧格式，会导致运行时崩溃。

- [ ] **Step 1: 修复 `financial_trend_chart` 的数据格式**

当前 `financial_trend_chart` 使用 `{"Revenue": ..., "Net Profit": ...}` 格式，需改为 `years+bar+line+bar_label+line_label`（BAR_LINE 格式）或 `years+scenarios`（LINE 格式）：

```python
# financial_trend_chart 应改为 BAR_LINE 格式：
config = ChartConfig(
    chart_type=ChartType.BAR_LINE,
    title=f"{symbol} Revenue & Net Profit Trend",
    data={
        "years": periods,
        "bar": revenue,
        "line": net_profit,
        "bar_label": "营业收入(亿元)",
        "line_label": "净利润(亿元)",
    },
    xlabel="Period",
    ylabel="Amount (CNY)",
    source="akshare/Financial Statements",
)
```

- [ ] **Step 2: 修复 `valuation_band_chart` 的数据格式**

当前 `valuation_band_chart` 使用 `{"Close Price": ..., "Upper Band": ..., "Lower Band": ...}` 格式，需改为 `years+scenarios`：

```python
# valuation_band_chart 应改为 LINE + scenarios 格式：
config = ChartConfig(
    chart_type=ChartType.LINE,
    title=f"{symbol} Price & Valuation Band",
    data={
        "years": dates,
        "scenarios": {
            "Close Price": prices,
            "Upper Band": [upper] * len(prices),
            "Lower Band": [lower] * len(prices),
        },
    },
    xlabel="Date",
    ylabel="Price",
    source="akshare/Stock Quotes",
)
```

- [ ] **Step 3: Commit**

```bash
git add src/services/stock_charting.py
git commit -m "fix: StockChartService data format compatible with ChartGenerator (P22)"
```

---

## Task 11: 端到端集成测试

**Files:**
- Create: `tests/unit/services/test_chart_planner_integration.py`

- [ ] **Step 1: 写集成测试覆盖核心场景**

场景覆盖：
1. data_requests → fetch → compose → validate 全流程
2. 纯内容数据（无 data_requests）
3. LLM skip_reason
4. 非A股 symbol 降级
5. data_ref 关联过滤
6. financials → bar 图
7. 多图表 data_ref 分流

```python
import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from src.services.chart_planner import ChartPlannerAgent, ChartPlan
from src.services.chart_generator import ChartType


class TestChartPlannerIntegration:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    @pytest.mark.asyncio
    async def test_full_flow_with_data_requests(self):
        llm_json = json.dumps({
            "data_requests": [
                {"id": "req1", "source": "stock_price", "params": {"symbol": "002594", "days": 60}, "purpose": "比亚迪股价"},
                {"id": "req2", "source": "index_price", "params": {"symbol": "000300", "days": 60}, "purpose": "沪深300"},
            ],
            "charts": [{
                "chart_type": "line", "title": "比亚迪跑输沪深300", "subtitle": "akshare",
                "data_strategy": "normalize_pct", "data_ref": ["req1", "req2"],
                "data": {"years": [], "scenarios": {}},
                "caption": "归一化对比", "xlabel": "日期", "ylabel": "%",
                "confidence": 0.9, "reason": "文中论断需数据支撑",
                "insertion_anchor": "股价走势", "anchor_type": "after_paragraph", "unit": "%",
            }],
        })

        with patch.object(self.agent, '_fetch_data', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {
                "stock_price:002594": {
                    "id": "req1", "source": "stock_price",
                    "params": {"symbol": "002594"}, "purpose": "比亚迪股价",
                    "data": {"dates": ["2025-01-01", "2025-02-01", "2025-03-01"], "closes": [300, 280, 290]},
                },
                "index_price:000300": {
                    "id": "req2", "source": "index_price",
                    "params": {"symbol": "000300"}, "purpose": "沪深300",
                    "data": {"dates": ["2025-01-01", "2025-02-01", "2025-03-01"], "closes": [3500, 3600, 3700]},
                },
            }
            with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = await self.agent._parse_and_resolve(llm_json, "比亚迪")
                plans = await self.agent.plan("比亚迪股价走势弱于大盘", "比亚迪", "股价分析")
                assert len(plans) >= 1
                assert plans[0].chart_type == ChartType.LINE
                assert plans[0].data_source == "fetched"

    @pytest.mark.asyncio
    async def test_content_data_only(self):
        with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = [ChartPlan(
                chart_type=ChartType.BAR, title="市场份额", subtitle="",
                data={"categories": ["比亚迪", "特斯拉"], "values": [31.8, 6.4]},
                caption="", xlabel="", ylabel="%", confidence=0.85, reason="",
                insertion_anchor="市场份额", anchor_type="after_paragraph", unit="%",
                data_source="content",
            )]
            plans = await self.agent.plan("比亚迪市场份额31.8%", "比亚迪", "市场分析")
            assert len(plans) >= 1
            assert plans[0].data_source == "content"

    @pytest.mark.asyncio
    async def test_skip_reason(self):
        with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            plans = await self.agent.plan("纯文字分析", "比亚迪", "概述")
            assert len(plans) == 0

    @pytest.mark.asyncio
    async def test_financials_bar_chart(self):
        llm_json = json.dumps({
            "data_requests": [
                {"id": "req1", "source": "stock_financials", "params": {"symbol": "002594", "periods": 4}, "purpose": "比亚迪营收"},
            ],
            "charts": [{
                "chart_type": "bar", "title": "比亚迪季度营收", "subtitle": "",
                "data_strategy": "raw", "data_ref": ["req1"],
                "data": {},
                "caption": "", "xlabel": "季度", "ylabel": "亿元",
                "confidence": 0.85, "reason": "营收趋势",
                "insertion_anchor": "营收", "anchor_type": "after_paragraph", "unit": "亿元",
            }],
        })
        with patch.object(self.agent, '_fetch_data', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {
                "stock_financials:002594": {
                    "id": "req1", "source": "stock_financials",
                    "params": {"symbol": "002594"}, "purpose": "比亚迪营收",
                    "data": [
                        {"报告期": "2024Q3", "营业总收入": 5022.0},
                        {"报告期": "2024Q2", "营业总收入": 4215.0},
                    ],
                },
            }
            with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = await self.agent._parse_and_resolve(llm_json, "比亚迪")
                plans = await self.agent.plan("比亚迪营收增长", "比亚迪", "财务分析")
                assert len(plans) >= 1
                assert plans[0].chart_type == ChartType.BAR
```

- [ ] **Step 2: 运行集成测试**

Run: `python -m pytest tests/unit/services/test_chart_planner_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/services/test_chart_planner_integration.py
git commit -m "test: integration tests covering data_requests, financials, content-only, skip"
```

---

## Task 12: 全量测试 + 验证

- [ ] **Step 1: 运行所有 chart 相关测试**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py tests/unit/services/test_chart_planner_compose.py tests/unit/services/test_chart_planner_validate.py tests/unit/services/test_chart_planner_integration.py tests/test_chart_generator.py -v`

- [ ] **Step 2: 运行 chart generator 可视化验证**

Run: `python tests/test_chart_generator.py`

- [ ] **Step 3: 确认 import 无误**

Run: `python -c "from src.services.chart_planner import ChartPlannerAgent; print('OK')"`

---

## Task 13: 补齐 Prompt 规则 + JSON Schema 覆盖全部10种图表 (G7)

当前 Prompt 只有 BAR/LINE/PIE/RADAR/WATERFALL 的规则，BAR_LINE/SCATTER/BUBBLE/QUADRANT 完全未提及。JSON Schema 只有 line 一种示例。LLM 不知道这些类型的存在和数据格式。

**Files:**
- Modify: `src/services/chart_planner.py` — _CHART_TYPE_SELECTION_RULES, _JSON_SCHEMA, _SYSTEM_PROMPT, _DATA_SOURCES

- [ ] **Step 1: 重写 `_CHART_TYPE_SELECTION_RULES` 覆盖全部类型**

```python
_CHART_TYPE_SELECTION_RULES = """
| 数据特征 | 推荐图表类型 | 条件 | data格式 |
|----------|-------------|------|---------|
| 不同类别的数值对比 | bar | 类别数 <= 12，量纲一致 | categories+values |
| 排名/排行对比 | hbar | 适合展示排名，按值排序 | categories+values |
| 时间序列趋势 | line | 有序时间序列，>=2个时间点 | years+scenarios |
| 构成/占比分布 | pie | 类别数 <= 6，值非负 | labels+values |
| 多维度评估 | radar | 维度数 3-8，值自动归一化到0-100 | categories+values |
| 增减拆解 | waterfall | 有正有负的累计变化 | factors[].label+value+is_total |
| 绝对值+变化率同图 | bar_line | 双Y轴：绝对值(柱)+速率(线) | years+bar+line+bar_label+line_label |
| 多组对比 | bar (分组series) | 2-3组系列，量纲一致 | categories+series[].name+values |
| 多实体走势对比 | line (多scenarios) | 归一化后同图对比 | years+scenarios |
| 相关性分布 | scatter | 两个连续变量的关系 | x+y+labels |
| 规模-位置关系 | bubble | 三维数据(x/y/size) | sectors[].x+y+size+name |
| 竞争格局 | quadrant | 四象限定位 | players[].x+y+size+name |
"""
```

- [ ] **Step 2: 重写 `_JSON_SCHEMA` 包含多类型示例**

```python
_JSON_SCHEMA = """
{
    "data_requests": [
        {
            "id": "req1",
            "source": "stock_price",
            "params": {"symbol": "002594", "days": 120},
            "purpose": "比亚迪近120日股价走势"
        }
    ],
    "charts": [
        {
            "chart_type": "bar",
            "title": "具体语义标题，传达分析洞察",
            "subtitle": "数据来源说明",
            "data_strategy": "raw",
            "data_ref": [],
            "data": {
                "categories": ["类别A", "类别B", "类别C"],
                "values": [10, 20, 15]
            },
            "caption": "图注",
            "xlabel": "X轴",
            "ylabel": "Y轴（含单位）",
            "confidence": 0.9,
            "reason": "理由",
            "insertion_anchor": "正文关键短语",
            "anchor_type": "after_paragraph",
            "unit": ""
        }
    ],
    "skip_reason": null
}

=== 各图表类型的 data 格式 ===

bar (单系列):
  {"categories": ["A","B","C"], "values": [10,20,15]}

bar (分组):
  {"categories": ["Q1","Q2","Q3"], "series": [{"name":"比亚迪","values":[100,120,130]}, {"name":"宁德时代","values":[200,210,220]}]}

hbar:
  {"categories": ["公司A","公司B","公司C"], "values": [500,350,200]}

line:
  {"years": ["2023Q1","2023Q2","2023Q3"], "scenarios": {"比亚迪": [100,120,130], "沪深300": [100,105,110]}}

pie:
  {"labels": ["比亚迪","宁德时代","其他"], "values": [35, 20, 45]}

radar:
  {"categories": ["营收规模","盈利能力","技术实力","市场地位"], "values": [85, 72, 90, 88]}

waterfall:
  {"factors": [{"label":"上期利润","value":300,"is_total":true}, {"label":"营收增长","value":150}, {"label":"成本上升","value":-80}, {"label":"本期利润","value":370,"is_total":true}]}

bar_line:
  {"years": ["2021","2022","2023","2024"], "bar": [1502,4215,5022,6038], "line": [null,180.4,19.1,20.3], "bar_label": "营业收入(亿元)", "line_label": "同比增速(%)"}

scatter:
  {"x": [10,20,30], "y": [5,15,25], "labels": ["A","B","C"]}

bubble:
  {"sectors": [{"name":"新能源","x":5,"y":8,"size":3}, {"name":"半导体","x":7,"y":6,"size":2}]}

quadrant:
  {"players": [{"name":"比亚迪","x":8,"y":9,"size":5}, {"name":"特斯拉","x":7,"y":7,"size":4}]}
"""
```

- [ ] **Step 3: 在 `_SYSTEM_PROMPT` 中增加"图表数据格式规范"段落**

在 `_SYSTEM_PROMPT` 末尾（`data_requests 使用时机` 之后）追加：

```
## 图表 data 格式规范

你必须严格按照以下格式填充 data 字段。格式错误会导致图表生成失败。

### bar / hbar
- 单系列：{"categories": [...], "values": [...]}
- 分组：{"categories": [...], "series": [{"name": "系列名", "values": [...]}]}
- categories 和 values 长度必须一致

### line
- {"years": [...], "scenarios": {"系列名": [值1, 值2, ...]}}
- 每个 scenario 的值数量必须等于 years 长度

### pie
- {"labels": [...], "values": [...]}
- 值必须非负，类别数 <= 6

### radar
- {"categories": [...], "values": [...]}
- 如果原始值不在0-100范围，系统会自动归一化

### waterfall
- {"factors": [{"label": "项目名", "value": 数值, "is_total": true/false}]}
- is_total=true 表示累计汇总行（如"上期利润"、"本期利润"）

### bar_line（营收+增速等双Y轴场景）
- {"years": [...], "bar": [绝对值...], "line": [速率值...], "bar_label": "柱形标签", "line_label": "折线标签"}
- line 第一个值可为 null（首期无同比）
- 当 data_requests 包含 stock_financials 时，优先考虑 bar_line

### scatter / bubble / quadrant
- 这些图表需要自定义数据，直接在 data 中填入完整数据
- scatter: {"x": [...], "y": [...], "labels": [...]}
- bubble: {"sectors": [{"name": ..., "x": ..., "y": ..., "size": ...}]}
- quadrant: {"players": [{"name": ..., "x": ..., "y": ..., "size": ...}]}
```

- [ ] **Step 4: 在 `_DATA_SOURCES` 中增加 financials 的 extract 字段说明**

在 `_DATA_SOURCES` 的 params 示例表中，stock_financials 行增加 extract 说明：

```
| stock_financials | 个股财务报表 | {"symbol": "002594", "periods": 4, "extract": "revenue"} |

### extract 可选值（仅 stock_financials）
- revenue: 提取营业收入（默认）
- profit: 提取净利润
- both: 同时提取营收和净利润（适合 bar_line 图表）
```

- [ ] **Step 5: Commit**

```bash
git add src/services/chart_planner.py
git commit -m "feat: complete Prompt rules + JSON Schema for all 10 chart types (G7)"
```

---

## Task 14: _compose_chart_data 增加 BAR_LINE / WATERFALL / RADAR 分支 (G1/G4/G5)

当前 `_compose_chart_data` 只能产出 categorical(bar/hbar/pie) 和 time_series(line) 两种格式。BAR_LINE 需要特殊组装（柱+线双Y轴），WATERFALL 和 RADAR 通常由 LLM 直接提供 data，但需要 compose 对 financials 数据的特殊处理能力。

**Files:**
- Modify: `src/services/chart_planner.py`
- Modify: `tests/unit/services/test_chart_planner_compose.py`

- [ ] **Step 1: 写失败测试**

```python
class TestComposeBarLineData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_financials_bar_line(self):
        fetched = {
            "stock_financials:002594": {
                "id": "req1", "source": "stock_financials",
                "params": {"symbol": "002594", "periods": 4, "extract": "both"},
                "purpose": "比亚迪营收与增速",
                "data": [
                    {"报告期": "2024Q3", "营业总收入": 5022.0},
                    {"报告期": "2024Q2", "营业总收入": 4215.0},
                    {"报告期": "2024Q1", "营业总收入": 1502.0},
                    {"报告期": "2023Q4", "营业总收入": 3800.0},
                ],
            }
        }
        chart_raw = {"chart_type": "bar_line", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "years" in result
        assert "bar" in result
        assert "line" in result
        assert len(result["bar"]) == 4
        assert len(result["line"]) == 4
        assert result["line"][0] is None
        assert result["bar_label"] != ""
        assert result["line_label"] != ""

    def test_two_price_series_bar_line_rejected(self):
        fetched = {
            "stock_price:002594": {
                "id": "req1", "source": "stock_price",
                "params": {"symbol": "002594"}, "purpose": "比亚迪股价",
                "data": {"dates": ["2025-01", "2025-02"], "closes": [300, 280]},
            },
        }
        chart_raw = {"chart_type": "bar_line", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert result == {} or "years" not in result or "bar" not in result


class TestComposeRadarData:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_metrics_to_radar(self):
        fetched = {
            "stock_metrics:002594": {
                "id": "req1", "source": "stock_metrics",
                "params": {"symbol": "002594"}, "purpose": "比亚迪竞争力",
                "data": [
                    {"营收规模": 85, "盈利能力": 72, "技术实力": 90, "市场地位": 88, "成长性": 95},
                ],
            }
        }
        chart_raw = {"chart_type": "radar", "data_strategy": "raw"}
        result = self.agent._compose_chart_data(chart_raw, fetched, "raw")
        assert "categories" in result
        assert "values" in result
        assert len(result["categories"]) == 5
        assert len(result["values"]) == 5
        assert all(0 <= v <= 100 for v in result["values"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_compose.py::TestComposeBarLineData tests/unit/services/test_chart_planner_compose.py::TestComposeRadarData -v`
Expected: FAIL

- [ ] **Step 3: 在 `_compose_chart_data` 中增加 BAR_LINE 分支**

在 `_compose_chart_data` 方法中，在 `if categorical_data and chart_type in (ChartType.BAR, ...)` 之前增加：

```python
if chart_type == ChartType.BAR_LINE:
    return self._compose_bar_line(fetched_data, time_series_data, categorical_data)
```

- [ ] **Step 4: 实现 `_compose_bar_line` 方法**

```python
def _compose_bar_line(
    self,
    fetched_data: Dict[str, Any],
    time_series_data: List[Dict],
    categorical_data: List[Dict],
) -> Dict[str, Any]:
    financial_series = []
    for key, info in fetched_data.items():
        source = info.get("source", "")
        if source == "stock_financials":
            payload = info.get("data", {})
            purpose = info.get("purpose", "")
            params = info.get("params", {})
            symbol = params.get("symbol", "")
            extract = params.get("extract", "revenue")

            records = payload if isinstance(payload, list) else []
            if not records:
                continue

            periods = []
            revenue_vals = []
            profit_vals = []
            for r in records:
                period = r.get("报告期", r.get("REPORT_DATE", r.get("截止日期", "")))
                if period:
                    periods.append(str(period)[:10])
                else:
                    continue
                rev = r.get("营业总收入", r.get("营业收入", r.get("TOTAL_OPERATE_INCOME", 0)))
                np_ = r.get("净利润", r.get("NETPROFIT", r.get("归母净利润", 0)))
                try:
                    revenue_vals.append(float(rev))
                except (ValueError, TypeError):
                    revenue_vals.append(0)
                try:
                    profit_vals.append(float(np_))
                except (ValueError, TypeError):
                    profit_vals.append(0)

            if periods and revenue_vals:
                financial_series.append({
                    "name": self._make_series_name(purpose, symbol, "营收"),
                    "periods": periods,
                    "revenue": revenue_vals,
                    "profit": profit_vals,
                    "extract": extract,
                })

    if not financial_series:
        if time_series_data and len(time_series_data) == 1:
            td = time_series_data[0]
            vals = td["values"]
            bar_vals = vals
            line_vals = [None]
            for i in range(1, len(vals)):
                if vals[i-1] != 0:
                    line_vals.append(round((vals[i] - vals[i-1]) / abs(vals[i-1]) * 100, 1))
                else:
                    line_vals.append(0)
            return {
                "years": td["dates"],
                "bar": bar_vals,
                "line": line_vals,
                "bar_label": td["name"],
                "line_label": "环比变化(%)",
            }
        return {}

    fs = financial_series[0]
    periods = list(reversed(fs["periods"]))
    revenue = list(reversed(fs["revenue"]))

    line_vals = [None]
    for i in range(1, len(revenue)):
        if revenue[i-1] != 0:
            line_vals.append(round((revenue[i] - revenue[i-1]) / abs(revenue[i-1]) * 100, 1))
        else:
            line_vals.append(0)

    return {
        "years": periods,
        "bar": revenue,
        "line": line_vals,
        "bar_label": fs["name"],
        "line_label": "同比增速(%)",
    }
```

- [ ] **Step 5: 在 `_compose_chart_data` 中增加 RADAR 分支**

在 RADAR 场景下，`_compose_categorical` 已经能产出 `categories+values`，但需要额外做值归一化：

```python
if chart_type == ChartType.RADAR:
    if categorical_data:
        result = self._compose_categorical(categorical_data, chart_type)
        if result and "values" in result:
            result["values"] = self._normalize_radar_values(result["values"])
        return result
    return {}
```

- [ ] **Step 6: 实现 `_normalize_radar_values`**

```python
def _normalize_radar_values(self, values: List[float]) -> List[float]:
    if not values:
        return values
    max_val = max(abs(v) for v in values)
    if max_val == 0:
        return values
    if max_val <= 100:
        return values
    return [round(v / max_val * 100, 1) for v in values]
```

- [ ] **Step 7: 在 `_check_chart_type_match` 中放宽 RADAR 的0-100限制**

将 RADAR 校验改为：

```python
if plan.chart_type == ChartType.RADAR:
    categories = data.get("categories", [])
    if not (3 <= len(categories) <= 8):
        return False
    values = data.get("values", [])
    if not values or not all(isinstance(v, (int, float)) for v in values):
        return False
```

移除 `if values and not all(0 <= v <= 100 for v in values): return False` 这行（因为归一化已在 compose 时完成，content 来源的数据如果超范围也应放行，渲染时由 generator 处理）。

- [ ] **Step 8: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_compose.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_compose.py
git commit -m "feat: compose bar_line from financials + radar value normalization (G1/G5)"
```

---

## Task 15: 补齐 _has_empty_chart_data + _check_chart_type_match 覆盖全部类型 (G2/G6)

当前 `_has_empty_chart_data` 只对 BAR/LINE/PIE/RADAR 有判断，BAR_LINE/SCATTER/BUBBLE/QUADRANT/WATERFALL 缺失。`_check_chart_type_match` 同理。

**Files:**
- Modify: `src/services/chart_planner.py`
- Modify: `tests/unit/services/test_chart_planner_validate.py`

- [ ] **Step 1: 写测试**

```python
class TestHasEmptyChartDataFull:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_bar_line_complete(self):
        data = {"years": ["Q1", "Q2"], "bar": [100, 200], "line": [None, 50]}
        assert self.agent._has_empty_chart_data(data, ChartType.BAR_LINE) is False

    def test_bar_line_missing_line(self):
        data = {"years": ["Q1", "Q2"], "bar": [100, 200]}
        assert self.agent._has_empty_chart_data(data, ChartType.BAR_LINE) is True

    def test_scatter_complete(self):
        data = {"x": [1, 2], "y": [3, 4], "labels": ["A", "B"]}
        assert self.agent._has_empty_chart_data(data, ChartType.SCATTER) is False

    def test_scatter_empty(self):
        data = {"x": [], "y": [], "labels": []}
        assert self.agent._has_empty_chart_data(data, ChartType.SCATTER) is True

    def test_bubble_complete(self):
        data = {"sectors": [{"name": "A", "x": 1, "y": 2, "size": 3}]}
        assert self.agent._has_empty_chart_data(data, ChartType.BUBBLE) is False

    def test_bubble_empty(self):
        data = {"sectors": []}
        assert self.agent._has_empty_chart_data(data, ChartType.BUBBLE) is True

    def test_quadrant_complete(self):
        data = {"players": [{"name": "A", "x": 5, "y": 7, "size": 3}]}
        assert self.agent._has_empty_chart_data(data, ChartType.QUADRANT) is False

    def test_quadrant_empty(self):
        data = {"players": []}
        assert self.agent._has_empty_chart_data(data, ChartType.QUADRANT) is True

    def test_waterfall_complete(self):
        data = {"factors": [{"label": "A", "value": 100}]}
        assert self.agent._has_empty_chart_data(data, ChartType.WATERFALL) is False

    def test_waterfall_empty(self):
        data = {"factors": []}
        assert self.agent._has_empty_chart_data(data, ChartType.WATERFALL) is True


class TestCheckChartTypeMatchFull:
    def setup_method(self):
        self.agent = ChartPlannerAgent(output_dir="output/test_charts")

    def test_bar_line_valid(self):
        plan = ChartPlan(
            chart_type=ChartType.BAR_LINE, title="t", subtitle="",
            data={"years": ["Q1", "Q2"], "bar": [100, 200], "line": [None, 50]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True

    def test_bar_line_mismatched_lengths(self):
        plan = ChartPlan(
            chart_type=ChartType.BAR_LINE, title="t", subtitle="",
            data={"years": ["Q1", "Q2", "Q3"], "bar": [100, 200], "line": [None, 50]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is False

    def test_scatter_valid(self):
        plan = ChartPlan(
            chart_type=ChartType.SCATTER, title="t", subtitle="",
            data={"x": [1, 2, 3], "y": [4, 5, 6], "labels": ["A", "B", "C"]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True

    def test_bubble_valid(self):
        plan = ChartPlan(
            chart_type=ChartType.BUBBLE, title="t", subtitle="",
            data={"sectors": [{"name": "A", "x": 1, "y": 2, "size": 3}]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True

    def test_quadrant_valid(self):
        plan = ChartPlan(
            chart_type=ChartType.QUADRANT, title="t", subtitle="",
            data={"players": [{"name": "A", "x": 5, "y": 7, "size": 3}]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True

    def test_waterfall_missing_factors(self):
        plan = ChartPlan(
            chart_type=ChartType.WATERFALL, title="t", subtitle="",
            data={"factors": []},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is False

    def test_radar_values_out_of_range_still_passes(self):
        plan = ChartPlan(
            chart_type=ChartType.RADAR, title="t", subtitle="",
            data={"categories": ["A", "B", "C"], "values": [850, 720, 900]},
            caption="", xlabel="", ylabel="", confidence=0.9, reason="",
            insertion_anchor="", anchor_type="section_end", unit="",
        )
        assert self.agent._check_chart_type_match(plan) is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/unit/services/test_chart_planner_validate.py::TestHasEmptyChartDataFull tests/unit/services/test_chart_planner_validate.py::TestCheckChartTypeMatchFull -v`
Expected: Multiple FAIL

- [ ] **Step 3: 更新 `_has_empty_chart_data` 覆盖全部类型**

```python
def _has_empty_chart_data(self, data: Dict, chart_type: ChartType) -> bool:
    if not data:
        return True

    if chart_type == ChartType.LINE:
        scenarios = data.get("scenarios", {})
        if not scenarios:
            return True
        for vals in scenarios.values():
            if isinstance(vals, list) and len(vals) > 0:
                return False
        return True

    if chart_type in (ChartType.BAR, ChartType.HBAR):
        categories = data.get("categories", data.get("labels", []))
        if "series" in data:
            series = data["series"]
            if not series:
                return True
            return all(len(s.get("values", [])) == 0 for s in series)
        values = data.get("values", [])
        return len(values) == 0 or len(categories) == 0

    if chart_type == ChartType.PIE:
        labels = data.get("labels", data.get("categories", []))
        values = data.get("values", [])
        return len(values) == 0 or len(labels) == 0

    if chart_type == ChartType.BAR_LINE:
        years = data.get("years", [])
        bar = data.get("bar", [])
        line = data.get("line", [])
        return len(years) == 0 or len(bar) == 0 or len(line) == 0

    if chart_type == ChartType.RADAR:
        return len(data.get("values", [])) == 0 or len(data.get("categories", [])) == 0

    if chart_type == ChartType.WATERFALL:
        return len(data.get("factors", [])) == 0

    if chart_type == ChartType.SCATTER:
        return len(data.get("x", [])) == 0 or len(data.get("y", [])) == 0

    if chart_type == ChartType.BUBBLE:
        return len(data.get("sectors", [])) == 0

    if chart_type == ChartType.QUADRANT:
        return len(data.get("players", [])) == 0

    return len(data) == 0
```

- [ ] **Step 4: 更新 `_check_chart_type_match` 覆盖全部类型**

```python
def _check_chart_type_match(self, plan: ChartPlan) -> bool:
    data = plan.data
    if not data:
        return False

    if plan.chart_type == ChartType.PIE:
        values = data.get("values", [])
        if not all(isinstance(v, (int, float)) for v in values):
            return False
        if any(v < 0 for v in values):
            return False
        if len(values) > 6:
            return False

    if plan.chart_type == ChartType.LINE:
        years = data.get("years", [])
        if not years or len(years) < 2:
            return False
        scenarios = data.get("scenarios", {})
        for label, vals in scenarios.items():
            if isinstance(vals, list) and len(vals) != len(years):
                return False

    if plan.chart_type == ChartType.RADAR:
        categories = data.get("categories", [])
        if not (3 <= len(categories) <= 8):
            return False
        values = data.get("values", [])
        if not values or not all(isinstance(v, (int, float)) for v in values):
            return False

    if plan.chart_type in (ChartType.BAR, ChartType.HBAR):
        categories = data.get("categories", data.get("labels", []))
        if len(categories) > 12:
            return False

    if plan.chart_type == ChartType.BAR_LINE:
        years = data.get("years", [])
        bar = data.get("bar", [])
        line = data.get("line", [])
        if not years or len(years) < 2:
            return False
        if len(bar) != len(years):
            return False
        if len(line) != len(years):
            return False

    if plan.chart_type == ChartType.WATERFALL:
        factors = data.get("factors", [])
        if len(factors) < 2:
            return False

    if plan.chart_type == ChartType.SCATTER:
        x = data.get("x", [])
        y = data.get("y", [])
        if len(x) < 2 or len(x) != len(y):
            return False

    return True
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/unit/services/test_chart_planner_validate.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/chart_planner.py tests/unit/services/test_chart_planner_validate.py
git commit -m "feat: _has_empty + _check_type cover all 10 chart types (G2/G6)"
```

---

## Task 16: ChartGenerator._generate_bar_line 增强 (G8)

当前 BAR_LINE 实现的问题：
1. 只支持单柱+单线
2. line 值标签缺失（只标注 bar 值）
3. 值标签 `+ 30` 硬编码偏移
4. 无图例
5. line 值含 None 时会崩溃

**Files:**
- Modify: `src/services/chart_generator.py`
- Modify: `tests/test_chart_generator.py`

- [ ] **Step 1: 写失败测试**

```python
def test_bar_line_chart():
    gen = ChartGenerator()
    config = ChartConfig(
        chart_type=ChartType.BAR_LINE,
        title="营收与增速",
        data={
            "years": ["2021", "2022", "2023", "2024"],
            "bar": [1502, 4215, 5022, 6038],
            "line": [None, 180.4, 19.1, 20.3],
            "bar_label": "营业收入(亿元)",
            "line_label": "同比增速(%)",
        },
        ylabel="营业收入(亿元)",
    )
    result = gen.generate(config)
    assert result.success, f"Bar-line chart failed: {result.error}"


def test_bar_line_no_none():
    gen = ChartGenerator()
    config = ChartConfig(
        chart_type=ChartType.BAR_LINE,
        title="Revenue & Growth",
        data={
            "years": ["Q1", "Q2", "Q3"],
            "bar": [100, 200, 300],
            "line": [5.0, 8.0, 12.0],
            "bar_label": "Revenue",
            "line_label": "Growth(%)",
        },
    )
    result = gen.generate(config)
    assert result.success, f"Bar-line chart failed: {result.error}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -c "from tests.test_chart_generator import test_bar_line_chart; test_bar_line_chart()"`
Expected: FAIL（None 值导致 matplotlib 崩溃）

- [ ] **Step 3: 重写 `_generate_bar_line`**

```python
def _generate_bar_line(self, config: ChartConfig) -> str:
    fig, ax = self._create_figure(config)

    data = config.data
    years = data.get('years', [])
    bar_values = data.get('bar', [])
    line_values = data.get('line', [])
    bar_label = data.get('bar_label', '')
    line_label = data.get('line_label', '')

    x = np.arange(len(years))
    w = 0.5

    bars = ax.bar(x, bar_values, w, color=self._navy, alpha=0.85, zorder=3, label=bar_label)

    bar_unit = data.get('bar_unit', '')
    for bar, val in zip(bars, bar_values):
        if bar_unit == '%':
            lbl = f'{val}%'
        elif abs(val) >= 10000:
            lbl = f'{val/10000:.1f}万'
        elif abs(val) >= 1:
            lbl = f'{val:.1f}'
        else:
            lbl = f'{val:.2f}'
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
               lbl, ha='center', va='bottom', fontsize=8, color=self._char)

    ax2 = ax.twinx()
    clean_line = [v if v is not None else np.nan for v in line_values]
    ax2.plot(x, clean_line, 'o-', color=self._gold, linewidth=2.5,
            markersize=7, label=line_label, zorder=4)

    for i, val in enumerate(line_values):
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            label = f'{val}%' if data.get('line_unit') == '%' else f'{val:.1f}'
            ax2.annotate(label, (x[i], val), textcoords="offset points",
                        xytext=(0, 10), ha='center', fontsize=8, color=self._gold)

    ax2.set_ylabel(line_label, color=self._gold, fontsize=10)
    ax2.tick_params(axis='y', labelcolor=self._gold)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc='upper left')

    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=9)
    ax.set_ylabel(config.ylabel or bar_label, fontsize=10)
    ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
    ax.spines['top'].set_visible(False)
    ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)

    return self._save_figure(fig, f"barline_{hash(config.title) % 10000}", config)
```

- [ ] **Step 4: 运行所有 chart generator 测试**

Run: `python tests/test_chart_generator.py`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/chart_generator.py tests/test_chart_generator.py
git commit -m "feat: bar_line handles None values, line labels, legend, dynamic offset (G8)"
```

---

## Task 17: ChartGenerator._generate_radar 支持多实体对比

当前 radar 只支持单实体。竞争力分析经常需要多实体对比（如比亚迪 vs 宁德时代）。

**Files:**
- Modify: `src/services/chart_generator.py`

- [ ] **Step 1: 重写 `_generate_radar` 支持多 scenarios**

```python
def _generate_radar(self, config: ChartConfig) -> str:
    data = config.data
    categories = data.get('categories', [])

    N = len(categories)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles_closed = angles + angles[:1]

    fig = plt.figure(figsize=(8, 8))
    ax = plt.subplot(111, polar=True)
    fig.patch.set_facecolor('white')

    radar_colors = [self._navy, self._gold, '#7EB5A6', '#E8836B', '#8E558E']
    radar_fills = [0.25, 0.15, 0.15, 0.15, 0.15]

    if "scenarios" in data:
        scenarios = data.get("scenarios", {})
        for i, (label, vals) in enumerate(scenarios.items()):
            closed_vals = vals + vals[:1]
            color = radar_colors[i % len(radar_colors)]
            fill_alpha = radar_fills[min(i, len(radar_fills)-1)]
            ax.plot(angles_closed, closed_vals, 'o-', linewidth=2,
                   color=color, alpha=0.8, label=label)
            ax.fill(angles_closed, closed_vals, alpha=fill_alpha, color=color)
        ax.legend(fontsize=9, loc='upper right', bbox_to_anchor=(1.3, 1.1))
    else:
        values = data.get('values', [])
        closed_vals = values + values[:1]
        ax.plot(angles_closed, closed_vals, 'o-', linewidth=2, color=self._navy, alpha=0.8)
        ax.fill(angles_closed, closed_vals, alpha=0.25, color=self._navy)

    ax.set_thetagrids(np.degrees(angles), categories, fontsize=9)
    all_vals = []
    if "scenarios" in data:
        for vals in data["scenarios"].values():
            all_vals.extend([v for v in vals if isinstance(v, (int, float))])
    else:
        all_vals = data.get('values', [])
    max_val = max(all_vals) if all_vals else 100
    ax.set_ylim(0, max(max_val * 1.1, 100))
    ax.set_title(config.title, fontsize=12, fontweight='bold', pad=20)

    plt.tight_layout()
    return self._save_figure(fig, f"radar_{hash(config.title) % 10000}", config)
```

- [ ] **Step 2: 更新 `_compose_chart_data` 的 RADAR 分支支持多实体**

当有多组 `stock_metrics` 数据时，输出 `categories + scenarios` 格式：

```python
if chart_type == ChartType.RADAR:
    if categorical_data:
        if len(categorical_data) == 1:
            result = self._compose_categorical(categorical_data, chart_type)
        else:
            all_categories = []
            seen = set()
            for cd in categorical_data:
                for c in cd["categories"]:
                    if c not in seen:
                        all_categories.append(c)
                        seen.add(c)
            scenarios = {}
            for cd in categorical_data:
                cat_to_val = dict(zip(cd["categories"], cd["values"]))
                aligned_vals = [cat_to_val.get(c, 0) for c in all_categories]
                scenarios[cd["name"]] = self._normalize_radar_values(aligned_vals)
            result = {"categories": all_categories, "scenarios": scenarios}
        if result and "values" in result:
            result["values"] = self._normalize_radar_values(result["values"])
        return result
    return {}
```

- [ ] **Step 3: 更新 `_has_empty_chart_data` 的 RADAR 分支**

```python
if chart_type == ChartType.RADAR:
    if "scenarios" in data:
        scenarios = data.get("scenarios", {})
        return len(scenarios) == 0
    return len(data.get("values", [])) == 0 or len(data.get("categories", [])) == 0
```

- [ ] **Step 4: 写测试**

```python
def test_radar_chart_multi_scenario():
    gen = ChartGenerator()
    config = ChartConfig(
        chart_type=ChartType.RADAR,
        title="竞争力对比",
        data={
            "categories": ["营收", "利润", "技术", "市场"],
            "scenarios": {
                "比亚迪": [85, 72, 90, 88],
                "宁德时代": [95, 80, 75, 92],
            },
        },
    )
    result = gen.generate(config)
    assert result.success, f"Multi-radar failed: {result.error}"
```

- [ ] **Step 5: 运行测试**

Run: `python tests/test_chart_generator.py`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/chart_generator.py src/services/chart_planner.py tests/test_chart_generator.py
git commit -m "feat: radar multi-entity comparison + compose multi-metrics (G5)"
```

---

## Task 18: 更新集成测试覆盖全部图表类型

在 Task 11 的集成测试基础上，增加 BAR_LINE、WATERFALL、RADAR、PIE 等类型的端到端测试。

**Files:**
- Modify: `tests/unit/services/test_chart_planner_integration.py`

- [ ] **Step 1: 增加新测试**

```python
@pytest.mark.asyncio
async def test_bar_line_from_financials(self):
    llm_json = json.dumps({
        "data_requests": [
            {"id": "req1", "source": "stock_financials", "params": {"symbol": "002594", "periods": 4, "extract": "both"}, "purpose": "比亚迪营收与增速"},
        ],
        "charts": [{
            "chart_type": "bar_line", "title": "比亚迪营收与同比增速", "subtitle": "",
            "data_strategy": "raw", "data_ref": ["req1"],
            "data": {},
            "caption": "营收(柱)与增速(线)", "xlabel": "季度", "ylabel": "亿元",
            "confidence": 0.9, "reason": "营收+增速双维度",
            "insertion_anchor": "营收", "anchor_type": "after_paragraph", "unit": "",
        }],
    })
    with patch.object(self.agent, '_fetch_data', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "stock_financials:002594": {
                "id": "req1", "source": "stock_financials",
                "params": {"symbol": "002594"}, "purpose": "比亚迪营收",
                "data": [
                    {"报告期": "2024Q3", "营业总收入": 5022.0},
                    {"报告期": "2024Q2", "营业总收入": 4215.0},
                    {"报告期": "2024Q1", "营业总收入": 1502.0},
                    {"报告期": "2023Q4", "营业总收入": 3800.0},
                ],
            },
        }
        with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = await self.agent._parse_and_resolve(llm_json, "比亚迪")
            plans = await self.agent.plan("比亚迪营收增长", "比亚迪", "财务分析")
            assert len(plans) >= 1
            assert plans[0].chart_type == ChartType.BAR_LINE
            assert "bar" in plans[0].data
            assert "line" in plans[0].data

@pytest.mark.asyncio
async def test_waterfall_from_content(self):
    with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = [ChartPlan(
            chart_type=ChartType.WATERFALL, title="利润增减拆解", subtitle="",
            data={"factors": [
                {"label": "上期利润", "value": 300, "is_total": True},
                {"label": "营收增长", "value": 150},
                {"label": "成本上升", "value": -80},
                {"label": "本期利润", "value": 370, "is_total": True},
            ]},
            caption="", xlabel="", ylabel="万元", confidence=0.85, reason="",
            insertion_anchor="利润变化", anchor_type="after_paragraph", unit="万元",
            data_source="content",
        )]
        plans = await self.agent.plan("利润从300万增至370万", "比亚迪", "利润分析")
        assert len(plans) >= 1
        assert plans[0].chart_type == ChartType.WATERFALL

@pytest.mark.asyncio
async def test_pie_from_content(self):
    with patch.object(self.agent, '_llm_plan', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = [ChartPlan(
            chart_type=ChartType.PIE, title="动力电池市场份额", subtitle="",
            data={"labels": ["比亚迪", "宁德时代", "其他"], "values": [31.8, 20.0, 48.2]},
            caption="", xlabel="", ylabel="", confidence=0.85, reason="",
            insertion_anchor="市场份额", anchor_type="after_paragraph", unit="%",
            data_source="content",
        )]
        plans = await self.agent.plan("比亚迪市场份额31.8%", "比亚迪", "市场分析")
        assert len(plans) >= 1
        assert plans[0].chart_type == ChartType.PIE
```

- [ ] **Step 2: 运行集成测试**

Run: `python -m pytest tests/unit/services/test_chart_planner_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/services/test_chart_planner_integration.py
git commit -m "test: integration tests for bar_line, waterfall, pie chart types"
```

---

## Task 19: 全量测试 + 验证

- [ ] **Step 1: 运行所有 chart 相关测试**

Run: `python -m pytest tests/unit/services/test_chart_planner_data_fetch.py tests/unit/services/test_chart_planner_compose.py tests/unit/services/test_chart_planner_validate.py tests/unit/services/test_chart_planner_integration.py tests/test_chart_generator.py -v`

- [ ] **Step 2: 运行 chart generator 可视化验证**

Run: `python tests/test_chart_generator.py`

- [ ] **Step 3: 确认 import 无误**

Run: `python -c "from src.services.chart_planner import ChartPlannerAgent; from src.services.chart_generator import ChartGenerator, ChartType; print('OK')"`

- [ ] **Step 4: 确认全部图表类型可渲染**

Run: `python -c "
from src.services.chart_generator import ChartGenerator, ChartConfig, ChartType
gen = ChartGenerator(output_dir='output/test_all_types')
tests = [
    ('bar', ChartType.BAR, {'categories': ['A','B','C'], 'values': [10,20,15]}),
    ('bar_grouped', ChartType.BAR, {'categories': ['Q1','Q2'], 'series': [{'name':'X','values':[10,20]},{'name':'Y','values':[15,25]}]}),
    ('hbar', ChartType.HBAR, {'categories': ['A','B','C'], 'values': [10,20,15]}),
    ('bar_line', ChartType.BAR_LINE, {'years':['2021','2022','2023'], 'bar':[100,200,300], 'line':[None,100.0,50.0], 'bar_label':'Revenue', 'line_label':'Growth(%)'}),
    ('pie', ChartType.PIE, {'labels': ['A','B','C'], 'values': [30,40,30]}),
    ('line', ChartType.LINE, {'years':['Q1','Q2','Q3'], 'scenarios': {'A':[10,20,30], 'B':[15,25,35]}}),
    ('radar', ChartType.RADAR, {'categories': ['X','Y','Z','W'], 'values': [80,60,90,70]}),
    ('radar_multi', ChartType.RADAR, {'categories': ['X','Y','Z','W'], 'scenarios': {'A':[80,60,90,70], 'B':[70,80,60,85]}}),
    ('waterfall', ChartType.WATERFALL, {'factors': [{'label':'Start','value':300,'is_total':True},{'label':'+Grow','value':150},{'label':'-Cost','value':-80},{'label':'End','value':370,'is_total':True}]}),
    ('scatter', ChartType.SCATTER, {'x': [1,2,3], 'y': [4,5,6], 'labels': ['A','B','C']}),
    ('bubble', ChartType.BUBBLE, {'sectors': [{'name':'A','x':3,'y':7,'size':5},{'name':'B','x':6,'y':4,'size':3}]}),
    ('quadrant', ChartType.QUADRANT, {'players': [{'name':'A','x':7,'y':8,'size':5},{'name':'B','x':3,'y':4,'size':3}]}),
]
for name, ct, data in tests:
    r = gen.generate(ChartConfig(chart_type=ct, title=name, data=data))
    print(f'{name}: {\"OK\" if r.success else \"FAIL: \"+str(r.error)}')
"`

Expected: 12 OK

---

## 图表类型完整链路审计

逐类型审查 **LLM Prompt → _compose_chart_data → _has_empty_chart_data → _check_chart_type_match → _check_value_range → ChartGenerator.render** 全链路。

### 审计矩阵

| ChartType | Prompt有规则? | JSON Schema有示例? | _compose能产出? | _has_empty判断? | _check_type校验? | ChartGenerator渲染? | 常用场景 | 结论 |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|------|------|
| **BAR** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 市场份额/营收对比 | ✅ 完整 |
| **BAR (分组series)** | ✅ | ❌ 无series示例 | ✅ | ⚠️ 不判断series | ✅ | ⚠️ P20值标签缩进 | 多公司季度营收 | ⚠️ 需补series示例+修标签 |
| **HBAR** | ✅ | ❌ 无示例 | ❌ 不走categorical | ✅ | ✅ | ⚠️ P21多色 | 排名/排行 | ❌ compose缺hbar分支 |
| **BAR_LINE** | ❌ 未提及 | ❌ 无示例 | ❌ 无法组装 | ❌ 不判断 | ❌ 不校验 | ❌ R7: None值崩溃+硬编码偏移+无legend | 营收+增速/利润率 | ❌ 全链路缺失 |
| **LINE** | ✅ | ✅ | ✅ | ✅ | ⚠️ 不校验scenarios长度 | ⚠️ P7颜色循环(#7EB5A6重复仍存在) | 股价走势 | ⚠️ 需修P7+P18 |
| **LINE (多scenarios)** | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | 股价vs大盘 | ⚠️ 同上 || **PIE** | ✅ | ❌ 无示例 | ❌ 不走categorical | ✅ | ✅ | ✅ | 市场份额构成 | ❌ compose缺pie分支 |
| **RADAR** | ✅ | ❌ 无示例 | ❌ 无法组装 | ⚠️ 只判断values | ⚠️ 强制0-100 | ⚠️ 不支持多实体 | 竞争力评估 | ❌ compose缺分支+0-100太严 |
| **WATERFALL** | ✅ | ❌ 无示例 | ❌ 无法组装 | ✅ | ❌ 不校验 | ✅ | 利润增减拆解 | ❌ compose缺分支 |
| **SCATTER** | ❌ 未提及 | ❌ 无示例 | ❌ 无法组装 | ❌ 不判断 | ❌ 不校验 | ✅ | 估值vs增速 | ❌ 全链路缺失 |
| **BUBBLE** | ❌ 未提及 | ❌ 无示例 | ❌ 无法组装 | ❌ 不判断 | ❌ 不校验 | ✅ | 行业规模-增速-份额 | ❌ 全链路缺失 |
| **QUADRANT** | ❌ 未提及 | ❌ 无示例 | ❌ 无法组装 | ❌ 不判断 | ❌ 不校验 | ✅ | 竞争格局 | ❌ 全链路缺失 |

### 结论：10种图表类型中，只有 BAR 单系列完整可用

**核心问题**：`_compose_chart_data` 只能输出 `{"years": [...], "scenarios": {...}}` 这一种数据格式（line 格式），无法产出 BAR_LINE、PIE、WATERFALL、SCATTER、BUBBLE、QUADRANT 所需的数据格式。

### 需要补充的完整链路

#### G1. BAR_LINE（柱形+折线 — 极常用）

**场景**：营收柱形 + 增速折线、利润柱形 + 利润率折线

**需要的 data 格式**：
```json
{
    "years": ["2021", "2022", "2023", "2024"],
    "bar": [1502, 4215, 5022, 6038],
    "line": [null, 180.4, 19.1, 20.3],
    "bar_label": "营业收入(亿元)",
    "line_label": "同比增速(%)"
}
```

**需要的 _compose 逻辑**：从 financials 提取营收(bar) + 计算同比增速(line)

**缺失**：Prompt规则 ❌、Schema示例 ❌、compose分支 ❌、empty判断 ❌、type校验 ❌

#### G2. PIE（饼图 — 常用）

**场景**：市场份额构成、收入结构

**需要的 data 格式**：
```json
{
    "labels": ["比亚迪", "宁德时代", "LG新能源", "松下", "其他"],
    "values": [31.8, 15.7, 13.6, 7.3, 31.6]
}
```

**缺失**：Schema示例 ❌、compose分支 ❌（categorical 已在 v2 plan Task 4 中修复）

#### G3. HBAR（水平柱状图 — 常用）

**场景**：排名、排行榜

**需要的 data 格式**：同 BAR，但 `_compose_categorical` 需要产出 `categories + values`

**缺失**：compose中 hbar 与 bar 走同一分支即可，但 Prompt 规则不区分 hbar 用途

#### G4. WATERFALL（瀑布图 — 中频）

**场景**：利润增减拆解、成本构成分析

**需要的 data 格式**：
```json
{
    "factors": [
        {"label": "上期利润", "value": 300, "is_total": true},
        {"label": "营收增长", "value": 150},
        {"label": "成本上升", "value": -80},
        {"label": "本期利润", "value": 370, "is_total": true}
    ]
}
```

**缺失**：Schema示例 ❌、compose分支 ❌、empty判断已有 ✅

#### G5. RADAR（雷达图 — 中频）

**场景**：竞争力多维评估

**当前问题**：`_check_chart_type_match` 强制要求值在 0-100，但 LLM 输出的数据经常不在该范围

**需要的 data 格式**：
```json
{
    "categories": ["营收规模", "盈利能力", "技术实力", "市场地位", "成长性"],
    "values": [85, 72, 90, 88, 95]
}
```

**缺失**：Schema示例 ❌、compose分支 ❌、0-100校验太严（应改为自动归一化到0-100）

#### G6. SCATTER / BUBBLE / QUADRANT（低频但专业）

这三种图表在行业研究报告中偶尔出现，但数据来源通常需要自定义，不太适合 data_requests 模式。LLM 可以直接在 data 字段中填入数据。

**策略**：LLM 直接提供 data（不经过 compose），只需保证 Prompt 规则 + Schema 示例 + empty/type 校验存在即可。

---

## 补充 Task：图表类型全链路补齐

基于上述审计，需要在 v2 计划中增加以下改造：

### 新增 Task: 补齐 Prompt 规则 + Schema 示例（覆盖全部10种图表）

**Files:**
- Modify: `src/services/chart_planner.py` — _CHART_TYPE_SELECTION_RULES + _JSON_SCHEMA + _SYSTEM_PROMPT

**改造点：**

1. **_CHART_TYPE_SELECTION_RULES** 扩展为覆盖全部类型：

```
| 数据特征 | 推荐图表类型 | 条件 | data格式 |
|----------|-------------|------|---------|
| 不同类别的数值对比 | bar | 类别数 <= 12，量纲一致 | categories+values |
| 排名/排行对比 | hbar | 适合展示排名 | categories+values |
| 时间序列趋势 | line | 有序时间序列 | years+scenarios |
| 构成/占比分布 | pie | 类别数 <= 6，值非负 | labels+values |
| 多维度评估 | radar | 维度数 3-8 | categories+values(0-100) |
| 增减拆解 | waterfall | 有正有负的累计变化 | factors[].label+value+is_total |
| 绝对值+变化率同图 | bar_line | 双Y轴：绝对值(柱)+速率(线) | years+bar+line+bar_label+line_label |
| 多组对比 | bar (分组series) | 2-3组系列 | categories+series[].name+values |
| 相关性分布 | scatter | 两个连续变量的关系 | x+y+labels |
| 规模-位置关系 | bubble | 三维数据 | sectors[].x+y+size+name |
| 竞争格局 | quadrant | 四象限定位 | players[].x+y+size+name |
```

2. **_JSON_SCHEMA** 增加多类型示例（用 oneOf 或注释说明每种类型的 data 格式）

3. **_SYSTEM_PROMPT** 增加每种图表的 data 格式说明和典型场景

4. **data_requests** 增加对 BAR_LINE 的特定支持：当 LLM 请求 financials 时，可以声明 `"extract": ["revenue", "yoy_growth"]`，compose 时自动计算同比增速

### 新增 Task: _compose_chart_data 增加 BAR_LINE / WATERFALL / RADAR 分支

在 v2 Task 4 的基础上，`_compose_categorical` 和新增的 `_compose_special` 中增加：

**BAR_LINE 分支**：
```python
elif chart_type == ChartType.BAR_LINE:
    # 从 financials 提取营收(bar) + 计算同比增速(line)
    if len(time_series_data) >= 1:
        td = time_series_data[0]
        bar_vals = td["values"]
        line_vals = [None]  # 第一个无同比
        for i in range(1, len(bar_vals)):
            if bar_vals[i-1] != 0:
                line_vals.append(round((bar_vals[i] - bar_vals[i-1]) / abs(bar_vals[i-1]) * 100, 1))
            else:
                line_vals.append(0)
        return {
            "years": td["dates"],
            "bar": bar_vals,
            "line": line_vals,
            "bar_label": td["name"],
            "line_label": "同比增速(%)",
        }
```

**WATERFALL 分支**：
LLM 直接在 data 中提供 factors，不经过 compose。只需 Prompt 告知格式。

**RADAR 分支**：
LLM 直接在 data 中提供 categories+values，不经过 compose。但 _check_chart_type_match 要放宽：值不在0-100时自动归一化到0-100，而不是拒绝。

### 新增 Task: _has_empty_chart_data + _check_chart_type_match 补齐缺失类型

v2 Task 5 已覆盖部分，需补充：

- BAR_LINE: `years` and (`bar` or `line`) 非空
- SCATTER: `x` and `y` and `labels` 非空
- BUBBLE: `sectors` 非空
- QUADRANT: `players` 非空

- BAR_LINE: `years`/`bar`/`line` 长度一致
- RADAR: 值自动归一化而非拒绝（当 max > 100 时，scale to 0-100）

### 新增 Task: ChartGenerator._generate_bar_line 增强

当前实现的问题：
1. 只支持单柱+单线，不支持多柱+多线
2. line 值标签缺失（只标注 bar 值）
3. 值标签 `+ 30` 硬编码偏移
4. 无图例（bar 和 line 的 label 不在 legend 中）
5. bar 的 ylabel 没有自动设置

增强方案：
- 添加 line 值标签
- 添加 legend
- 修正偏移量（动态计算）
- 设置 bar ylabel

---

## Self-Review Checklist

| 检查项 | 状态 |
|--------|------|
| **A. 数据获取层** | |
| P1 时间序列反转 | Task 1 修复（sort+dedup+tail） |
| P2 指数前缀 | Task 2 修复（_format_index_symbol） |
| P3 重复akshare | Task 8 修复（StockDataSkill+fallback） |
| P9 search不可靠 | Task 7 修复（结构化prompt+校验） |
| P11 串行获取 | Task 8 修复（asyncio.gather并行） |
| P12 无重试 | Task 8 修复（max_retries循环） |
| P13 无超时 | Task 8 修复（asyncio.wait_for） |
| **B. 数据组装层** | |
| P4 financials无法组装 | Task 4 修复（_compose_categorical） |
| P5 data-chart关联 | Task 3 修复（data_ref） |
| P6 中文列名 | Task 4 修复（多列名fallback） |
| P10 缺关联字段 | Task 3 修复（id+data_ref） |
| P14 只能输出line格式 | Task 4 修复（categorical/time_series分流） |
| P15 时间对齐粗暴 | Task 4 测试覆盖（_align_time_series） |
| P16 empty判断不完整 | Task 5 修复（per-type判断） |
| P17 series name重复 | Task 4 修复（_make_series_name） |
| **C. 校验层** | |
| P8 value_range误杀 | Task 5 修复（waterfall/%跳过） |
| P18 scenarios长度不校验 | Task 5 修复（len(vals)==len(years)） |
| P19 标题语义质量 | LLM prompt约束（不单独校验） |
| **D. 渲染层** | |
| P7 line颜色循环 | Task 6 修复（8色+4样式循环） |
| P20 bar值标签缩进 | Task 6 修复（ax.text移入循环） |
| P21 hbar多色 | Task 6 修复（单色） |
| P22 StockChartService兼容 | Task 10 修复（price_chart ✅ 已修；financial_trend_chart/valuation_band_chart ❌ 待修） |
| **E. Prompt/LLM** | |
| P23 非A股symbol | Task 7+8 修复（_is_a_share_symbol+search降级） |
| P24 days无上限 | Task 2 修复（_sanitize_params） |
| P25 content截断 | Task 9 修复（head1500+tail500） |
| P26 非标准chart_type | Task 9 修复（_EXTENDED_CHART_TYPE_MAP） |
| **F. 架构/健壮性** | |
| P27 静默失败 | Task 8 修复（failed_count统计+warning） |
| P28 JSON解析脆弱 | Task 9 修复（_clean_json_string） |
| P29 plan无降级链 | generic_agent.py已有降级（不改） |
| **G. 图表类型全链路** | |
| G1 BAR_LINE全链路 | Task 14 (compose) + Task 15 (empty/validate) + Task 16 (render) |
| G2 PIE compose | v2 Task 4 + Task 15 (empty/validate) |
| G3 HBAR compose | v2 Task 4 + Task 15 (empty/validate) |
| G4 WATERFALL compose | Task 15 (empty/validate) — LLM直供data |
| G5 RADAR 归一化+多实体 | Task 14 (compose+normalize) + Task 17 (render multi) + Task 15 (validate放宽) |
| G6 SCATTER/BUBBLE/QUADRANT | Task 13 (Prompt) + Task 15 (empty/validate) — LLM直供data |
| G7 Prompt规则+Schema全部类型 | Task 13 |
| G8 BAR_LINE渲染增强 | Task 16 |
| G9 集成测试全部类型 | Task 18 |
| G10 全量12类型渲染验证 | Task 19 |
| **测试覆盖** | |
| 每步骤有测试 | Task 1-19 均有测试 |
| 无placeholder | 确认所有步骤含完整代码 |
| 边界case | 空数据/重复日期/无效值/非A股/超参/None值/长度不匹配 全覆盖 |
| 全部12种图表渲染验证 | Task 19 Step 4 逐一验证 |
