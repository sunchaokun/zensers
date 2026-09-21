# Data Collector Precision Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从源头提升数据搜集精准度：关键词派生更准、口径冲突可追溯、证据强度透明化。

**Architecture:** 三个独立模块，分别验证后再组合：(1) 关键词派生模块 (2) 口径一致性校验 (3) 证据强度标签。

**Tech Stack:** Python, 现有 search_quality_filter / generic_agent 框架

---

### Task 1: 关键词派生模块（KeywordDeriver）

**Files:**
- Create: `src/core/search/keyword_deriver.py`
- Create: `tests/unit/search/test_keyword_deriver.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/search/test_keyword_deriver.py
from src.core.search.keyword_deriver import KeywordDeriver


def test_derive_core_words():
    deriver = KeywordDeriver()
    result = deriver.derive("中国新能源汽车市场 增长趋势")
    assert "新能源汽车" in result["core"]
    assert any("出货量" in w or "销量" in w for w in result["caliber"])
    assert any("2025" in w or "2026" in w for w in result["time"])


def test_derive_exclusion_words():
    deriver = KeywordDeriver()
    result = deriver.derive("中国智能手机市场")
    assert "猪肉" not in result["core"]
    assert isinstance(result["exclude"], list)


def test_derive_empty_topic():
    deriver = KeywordDeriver()
    result = deriver.derive("")
    assert result["core"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/search/test_keyword_deriver.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/search/keyword_deriver.py
"""Keyword Deriver — derive search keywords from research topic + aspect."""

import re
from datetime import datetime
from typing import Dict, List


# 口径词典：按行业领域自动匹配
CALIBER_TERMS = {
    "market": ["出货量", "销量", "零售量", "批发量", "激活量", "ASP", "均价", "市场份额"],
    "production": ["产量", "产能", "产能利用率", "开工率"],
    "finance": ["营收", "利润", "毛利率", "净利率", "估值"],
    "policy": ["补贴", "法规", "标准", "规划", "通知"],
    "technology": ["专利", "研发投入", "技术路线", "专利数量"],
}

# 排除词：跨行业噪音
EXCLUDE_terms_DEFAULT = ["猪肉", "新能源汽车", "AI芯片"]


class KeywordDeriver:
    def derive(self, topic: str, aspect: str = "") -> Dict[str, List[str]]:
        """从 topic + aspect 派生搜索关键词组。"""
        core = self._extract_core(topic)
        caliber = self._match_caliber(topic, aspect)
        time_words = self._time_words()
        exclude = self._exclude_words(topic)
        return {
            "core": core,
            "caliber": caliber,
            "time": time_words,
            "exclude": exclude,
        }

    def _extract_core(self, topic: str) -> List[str]:
        t = re.sub(
            r"(深度研究|市场研究|研究报告|分析报告|行业分析|行业研究|发展研究|"
            r"发展分析|前景分析|市场分析|调查报告|调研报告|白皮书|蓝皮书)",
            "", topic,
        )
        t = re.sub(r"^(中国|全球|国内|国外|亚太|欧美)\s*", "", t)
        t = t.strip()
        return [t] if t else []

    def _match_caliber(self, topic: str, aspect: str) -> List[str]:
        combined = (topic + " " + aspect).lower()
        matched = []
        for domain, terms in CALIBER_TERMS.items():
            for term in terms:
                if term.lower() in combined:
                    matched.append(term)
        if not matched:
            matched = CALIBER_TERMS.get("market", [])[:3]
        return matched

    def _time_words(self) -> List[str]:
        now = datetime.now()
        return [str(now.year), str(now.year - 1), f"Q{min((now.month - 1) // 3 + 1, 4)}"]

    def _exclude_words(self, topic: str) -> List[str]:
        excludes = list(EXCLUDE_terms_DEFAULT)
        topic_lower = topic.lower()
        for word in EXCLUDE_terms_DEFAULT:
            if word in topic_lower:
                excludes.remove(word)
        return excludes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/search/test_keyword_deriver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/search/keyword_deriver.py tests/unit/search/test_keyword_deriver.py
git commit -m "feat: add KeywordDeriver for structured keyword derivation"
```

### Task 2: 集成 KeywordDeriver 到 GenericAgent 查询生成

**Files:**
- Modify: `src/core/agents/generic_agent.py:4481-4680`（`_generate_search_queries` 方法）

- [ ] **Step 1: 在 _generate_search_queries 中使用 KeywordDeriver**

在方法开头（`queries = []` 之后）插入：

```python
# 使用 KeywordDeriver 结构化派生关键词
from src.core.search.keyword_deriver import KeywordDeriver
deriver = KeywordDeriver()
kw = deriver.derive(topic, aspect or "")
search_topic = kw["core"][0] if kw["core"] else self._extract_keywords(topic)
```

保留原有硬编码逻辑作为 fallback，但优先使用 deriver 的结果。

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `pytest tests/unit/ -k "generic_agent or search" -v --timeout=30`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/agents/generic_agent.py
git commit -m "feat: integrate KeywordDeriver into GenericAgent query generation"
```

### Task 3: 口径一致性校验（CaliberConsistencyChecker）

**Files:**
- Create: `src/core/search/caliber_checker.py`
- Create: `tests/unit/search/test_caliber_checker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/search/test_caliber_checker.py
from src.core.search.caliber_checker import CaliberConsistencyChecker


def test_detect_caliber_conflict():
    checker = CaliberConsistencyChecker()
    data_points = [
        {"metric": "智能手机出货量", "value": "3.5亿", "unit": "台", "period": "2025", "geographic_scope": "中国"},
        {"metric": "智能手机出货量", "value": "3.2亿", "unit": "台", "period": "2025", "geographic_scope": "中国", "source": "IDC"},
    ]
    conflicts = checker.check(data_points)
    assert len(conflicts) >= 1
    assert conflicts[0]["metric"] == "智能手机出货量"


def test_no_conflict_same_values():
    checker = CaliberConsistencyChecker()
    data_points = [
        {"metric": "智能手机出货量", "value": "3.5亿", "unit": "台", "period": "2025"},
        {"metric": "智能手机出货量", "value": "3.5亿", "unit": "台", "period": "2025"},
    ]
    conflicts = checker.check(data_points)
    assert len(conflicts) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/search/test_caliber_checker.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/search/caliber_checker.py
"""Caliber Consistency Checker — detect conflicting data points."""

import re
from typing import Any, Dict, List


def _normalize_value(val: str) -> str:
    """标准化数值用于比较。"""
    v = str(val).strip().lower()
    v = re.sub(r"[,\s]", "", v)
    v = re.sub(r"(亿|万|百万|千|billion|million|thousand)", "", v)
    v = re.sub(r"[^\d.%+-]", "", v)
    return v


def _normalize_unit(unit: str) -> str:
    u = str(unit).strip().lower()
    mapping = {"台": "units", "万辆": "10k_units", "亿": "100m", "万": "10k", "%": "pct"}
    return mapping.get(u, u)


class CaliberConsistencyChecker:
    def check(self, data_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检测同一 metric 下的冲突数据点。"""
        by_metric: Dict[str, List[Dict]] = {}
        for dp in data_points:
            metric = str(dp.get("metric") or "").strip()
            if not metric:
                continue
            by_metric.setdefault(metric, []).append(dp)

        conflicts = []
        for metric, items in by_metric.items():
            if len(items) < 2:
                continue
            values = set()
            units = set()
            periods = set()
            for item in items:
                values.add(_normalize_value(str(item.get("value") or "")))
                units.add(_normalize_unit(str(item.get("unit") or "")))
                periods.add(str(item.get("period") or ""))
            has_value_conflict = len([v for v in values if v]) > 1
            has_unit_conflict = len([u for u in units if u]) > 1
            if has_value_conflict or has_unit_conflict:
                conflicts.append({
                    "metric": metric,
                    "reason": "value_conflict" if has_value_conflict else "unit_conflict",
                    "values": list(values),
                    "units": list(units),
                    "periods": list(periods),
                    "data_points": items,
                })
        return conflicts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/search/test_caliber_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/search/caliber_checker.py tests/unit/search/test_caliber_checker.py
git commit -m "feat: add CaliberConsistencyChecker for data conflict detection"
```

### Task 4: 证据强度标签（EvidenceStrengthLabeler）

**Files:**
- Create: `src/core/search/evidence_labeler.py`
- Create: `tests/unit/search/test_evidence_labeler.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/search/test_evidence_labeler.py
from src.core.search.evidence_labeler import EvidenceStrengthLabeler


def test_strong_evidence():
    labeler = EvidenceStrengthLabeler()
    dp = {
        "metric": "出货量",
        "value": "3.5亿",
        "period": "2025",
        "geographic_scope": "中国",
        "source": "IDC",
        "credibility": "tier1_authority",
    }
    label = labeler.label(dp)
    assert label["evidence_strength"] == "strong"


def test_weak_evidence_missing_fields():
    labeler = EvidenceStrengthLabeler()
    dp = {"metric": "出货量", "value": "3.5亿"}
    label = labeler.label(dp)
    assert label["evidence_strength"] in ("weak", "moderate")


def test_empty_datapoint():
    labeler = EvidenceStrengthLabeler()
    label = labeler.label({})
    assert label["evidence_strength"] == "weak"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/search/test_evidence_labeler.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/search/evidence_labeler.py
"""Evidence Strength Labeler — transparent quality labeling for data points."""

from typing import Any, Dict


TIER_STRONG = {"tier1_authority", "tier2_professional"}
TIER_MODERATE = {"tier3_reputable"}
TIER_WEAK = {"tier4_general", "tier5_low_quality"}


class EvidenceStrengthLabeler:
    def label(self, data_point: Dict[str, Any]) -> Dict[str, Any]:
        """为 data_point 打 evidence_strength 标签。"""
        cred = str(data_point.get("credibility") or "").lower()
        period = str(data_point.get("period") or "").strip()
        geo = str(data_point.get("geographic_scope") or "").strip()
        unit = str(data_point.get("unit") or "").strip()
        source = str(data_point.get("source") or "").strip()

        score = 0
        reasons = []

        if cred in TIER_STRONG:
            score += 3
            reasons.append("high_credibility")
        elif cred in TIER_MODERATE:
            score += 2
            reasons.append("moderate_credibility")
        else:
            score += 1
            reasons.append("low_credibility")

        if period:
            score += 1
            reasons.append("has_period")
        else:
            reasons.append("missing_period")

        if geo:
            score += 1
            reasons.append("has_geographic_scope")
        else:
            reasons.append("missing_geographic_scope")

        if unit:
            score += 1
            reasons.append("has_unit")

        if source:
            score += 1
            reasons.append("has_source")

        if score >= 6:
            strength = "strong"
        elif score >= 4:
            strength = "moderate"
        else:
            strength = "weak"

        return {
            "evidence_strength": strength,
            "strength_score": score,
            "strength_reasons": reasons,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/search/test_evidence_labeler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/search/evidence_labeler.py tests/unit/search/test_evidence_labeler.py
git commit -m "feat: add EvidenceStrengthLabeler for transparent data quality labeling"
```

### Task 5: 集成口径校验 + 证据标签到回放脚本

**Files:**
- Modify: `research_analysis_prompt_opt/scripts/run_round.py`

- [ ] **Step 1: 在 run_round.py 中集成两个新模块**

在 `extract_fixture` 返回后，添加口径校验和证据标签：

```python
from src.core.search.caliber_checker import CaliberConsistencyChecker
from src.core.search.evidence_labeler import EvidenceStrengthLabeler

checker = CaliberConsistencyChecker()
labeler = EvidenceStrengthLabeler()

# 对每个 data_point 打标签
for dp in fixture["data_points"]:
    label_info = labeler.label(dp.get("data", {}))
    dp["evidence_strength"] = label_info["evidence_strength"]
    dp["strength_score"] = label_info["strength_score"]

# 检测冲突
conflicts = checker.check([dp.get("data", {}) for dp in fixture["data_points"]])
```

在 result 输出中增加 conflicts 和 evidence_strength 分布统计。

- [ ] **Step 2: Run回放验证结构变化**

Run: `venv\Scripts\python.exe research_analysis_prompt_opt/scripts/run_round.py --round 9 --skip-llm`
Expected: 输出包含 evidence_strength 分布和 conflicts 列表

- [ ] **Step 3: Commit**

```bash
git add research_analysis_prompt_opt/scripts/run_round.py
git commit -m "feat: integrate caliber check and evidence labeling into replay script"
```

### Task 6: 运行全量测试确认无回归

**Files:** none

- [ ] **Step 1: Run all related tests**

Run: `pytest tests/unit/search/ tests/prompts/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run round 9 replay**

Run: `venv\Scripts\python.exe research_analysis_prompt_opt/scripts/run_round.py --round 9 --skip-llm`
Expected: contract_score >= 87.5, evidence_strength 分布合理

- [ ] **Step 3: Log results**

更新 `research_analysis_prompt_opt/progress.md` 添加 Round 9 记录。
