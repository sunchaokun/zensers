# Aspect-Adaptive Cognitive Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement dimension-specific cognitive strategies for L1-L5 epistemic defense, with LLM-dynamic cognitive type inference and 4-level degradation chain.

**Architecture:** COGNITIVE_STRATEGY registry maps 4 cognitive types to L1-L5 parameters. `infer_cognitive_type()` uses LLM with 4-level fallback (LLM full → LLM retry → keyword heuristic → fact_driven). Each L1-L5 integration point reads strategy from cached context instead of hardcoded logic.

**Tech Stack:** Python 3.13, asyncio, DeepSeek LLM, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/core/agents/generic_agent.py` | `infer_cognitive_type()`, `_heuristic_cognitive_type()`, `COGNITIVE_STRATEGY` registry, L1/L3/L4/L5 strategy-driven execution |
| `src/core/communication.py` | L2 strategy-aware `write_canonical()` (deferred — see Task 6) |
| `tests/unit/test_epistemic_defense.py` | Tests for cognitive type inference, heuristic, cache, strategy lookup |
| `scripts/epistemic_quality_eval.py` | Updated A/B eval with 4 cognitive types |

---

### Task 1: COGNITIVE_STRATEGY Registry

**Files:**
- Modify: `src/core/agents/generic_agent.py` (top of class or module-level)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_epistemic_defense.py`:

```python
class TestCognitiveStrategyRegistry:
    def test_all_four_types_exist(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        for ct in ["fact_driven", "inference_driven", "forward_looking", "assessment_driven"]:
            assert ct in COGNITIVE_STRATEGY
            assert "L1" in COGNITIVE_STRATEGY[ct]
            assert "L3" in COGNITIVE_STRATEGY[ct]
            assert "L4" in COGNITIVE_STRATEGY[ct]
            assert "L5" in COGNITIVE_STRATEGY[ct]

    def test_fact_driven_dimension_ceiling(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["fact_driven"]["L1"]["dimension_ceiling"] == "inferential"

    def test_forward_looking_no_ceiling(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["forward_looking"]["L1"]["dimension_ceiling"] is None

    def test_inference_driven_speculative_policy(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["inference_driven"]["L3"]["speculative_policy"] == "cautious_use"

    def test_forward_looking_speculative_policy(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["forward_looking"]["L3"]["speculative_policy"] == "open_use"

    def test_fact_driven_hypothesis_count(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["fact_driven"]["L4"]["hypothesis_count"] == 0
        assert COGNITIVE_STRATEGY["fact_driven"]["L4"]["agent_hypothesis_count"] == 0

    def test_inference_driven_hypothesis_count(self):
        from src.core.agents.generic_agent import COGNITIVE_STRATEGY
        assert COGNITIVE_STRATEGY["inference_driven"]["L4"]["hypothesis_count"] == (3, 5)
        assert COGNITIVE_STRATEGY["inference_driven"]["L4"]["agent_hypothesis_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestCognitiveStrategyRegistry -v`
Expected: FAIL (ImportError or KeyError)

- [ ] **Step 3: Write COGNITIVE_STRATEGY registry**

Add to `src/core/agents/generic_agent.py` at module level (after imports, before class definition):

```python
COGNITIVE_STRATEGY = {
    "fact_driven": {
        "L1": {
            "dimension_ceiling": "inferential",
            "speculative_word_downgrade": "strict",
            "confidence_threshold": {"factual": "HIGH"},
        },
        "L2": {
            "caliber_floor_for_citation": "llm_inference_factual",
            "same_caliber_resolution": "newer_timestamp",
            "speculative_write_policy": "never",
        },
        "L3": {
            "speculative_policy": "reference_only",
            "reasoning_mode": "cross_validation",
            "inferential_instruction": "Verify with data; flag unsupported claims",
            "falsification_requirement": "all_inferential",
            "evidence_chain_template": "Data → Finding → Confirmation",
            "cross_dimension_instruction": "Cross-validate with other factual dimensions",
        },
        "L4": {
            "hypothesis_type": "Descriptive",
            "hypothesis_count": 0,
            "hypothesis_template": "【Data Observation H1】 → 【Supporting Evidence】→ 【Confirmed/Disconfirmed】→ 【Finding】",
            "counter_hypothesis_required": False,
            "agent_hypothesis_count": 0,
            "verification_focus": "Data accuracy",
            "output_suffix": "数据验证结果：",
        },
        "L5": {
            "contradiction_resolution": "Data conflict resolution (pick credible source, flag discrepancy)",
            "contradiction_instruction": "两项事实性主张冲突，请判断哪个数据源更可信并说明理由。",
            "auto_resolve_threshold": 0.8,
            "escalation_action": "Flag for human review",
        },
    },
    "inference_driven": {
        "L1": {
            "dimension_ceiling": "speculative",
            "speculative_word_downgrade": "moderate",
            "confidence_threshold": {"factual": "MEDIUM"},
        },
        "L2": {
            "caliber_floor_for_citation": "llm_inference_speculative",
            "same_caliber_resolution": "higher_source_count",
            "speculative_write_policy": "with_uncertainty_tag",
        },
        "L3": {
            "speculative_policy": "cautious_use",
            "reasoning_mode": "causal_chain",
            "inferential_instruction": "Build causal chain; check premises",
            "falsification_requirement": "speculative_only",
            "evidence_chain_template": "Premise → Reasoning → Conclusion",
            "cross_dimension_instruction": "Trace causal transmission from other dimensions",
        },
        "L4": {
            "hypothesis_type": "Causal",
            "hypothesis_count": (3, 5),
            "hypothesis_template": "【Causal Hypothesis H1】 → 【Supporting Evidence】→ 【Confirmed/Revised/Refuted】→ 【Conclusion】",
            "counter_hypothesis_required": True,
            "agent_hypothesis_count": 2,
            "verification_focus": "Logic completeness",
            "output_suffix": "假设验证结果：",
        },
        "L5": {
            "contradiction_resolution": "Premise re-examination (trace which premise failed)",
            "contradiction_instruction": "两项结论冲突，请追溯哪个前提或推理步骤出现了分歧。",
            "auto_resolve_threshold": 0.6,
            "escalation_action": "Inject as reasoning challenge",
        },
    },
    "forward_looking": {
        "L1": {
            "dimension_ceiling": None,
            "speculative_word_downgrade": "relaxed",
            "confidence_threshold": {"speculative": "LOW"},
        },
        "L2": {
            "caliber_floor_for_citation": "llm_inference_speculative",
            "same_caliber_resolution": "wider_coverage",
            "speculative_write_policy": "with_falsification_condition",
        },
        "L3": {
            "speculative_policy": "open_use",
            "reasoning_mode": "scenario_analysis",
            "inferential_instruction": "Map to scenarios; assign probabilities",
            "falsification_requirement": "all_claims",
            "evidence_chain_template": "Signal → Scenario → Probability",
            "cross_dimension_instruction": "Check consistency with other forward-looking claims",
        },
        "L4": {
            "hypothesis_type": "Predictive",
            "hypothesis_count": (2, 3),
            "hypothesis_template": "【Predictive Hypothesis H1】 → 【Supporting Signals】→ 【Probability Assessment】→ 【Scenario】",
            "counter_hypothesis_required": True,
            "agent_hypothesis_count": 1,
            "verification_focus": "Falsification conditions",
            "output_suffix": "前瞻验证结果：",
        },
        "L5": {
            "contradiction_resolution": "Scenario reconciliation (both may be valid under different scenarios)",
            "contradiction_instruction": "两项预测冲突，请分析在什么条件下各自成立，并给出情景分析。",
            "auto_resolve_threshold": 0.4,
            "escalation_action": "Present both scenarios",
        },
    },
    "assessment_driven": {
        "L1": {
            "dimension_ceiling": "inferential",
            "speculative_word_downgrade": "strict",
            "confidence_threshold": {"factual": "HIGH", "inferential": "HIGH"},
        },
        "L2": {
            "caliber_floor_for_citation": "llm_inference_factual",
            "same_caliber_resolution": "more_precise_data",
            "speculative_write_policy": "with_confidence_interval",
        },
        "L3": {
            "speculative_policy": "reference_only",
            "reasoning_mode": "sensitivity_analysis",
            "inferential_instruction": "Quantify impact; define assumptions",
            "falsification_requirement": "all_key_assumptions",
            "evidence_chain_template": "Assumption → Model → Range",
            "cross_dimension_instruction": "Verify assumptions against factual dimension data",
        },
        "L4": {
            "hypothesis_type": "Conditional",
            "hypothesis_count": (2, 3),
            "hypothesis_template": "【Conditional Hypothesis H1】 → 【Assumption Base】→ 【Sensitivity Test】→ 【Value Range】",
            "counter_hypothesis_required": True,
            "agent_hypothesis_count": 1,
            "verification_focus": "Assumption sensitivity",
            "output_suffix": "假设敏感性检验：",
        },
        "L5": {
            "contradiction_resolution": "Assumption divergence (which assumption drives the difference)",
            "contradiction_instruction": "两项评估冲突，请识别哪个假设差异导致了分歧，并量化影响。",
            "auto_resolve_threshold": 0.7,
            "escalation_action": "Show sensitivity of each assumption",
        },
    },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestCognitiveStrategyRegistry -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/agents/generic_agent.py tests/unit/test_epistemic_defense.py
git commit -m "feat: add COGNITIVE_STRATEGY registry with 4 cognitive types x L1-L5 parameters"
```

---

### Task 2: Heuristic Fallback (_heuristic_cognitive_type)

**Files:**
- Modify: `src/core/agents/generic_agent.py` (add method)
- Modify: `tests/unit/test_epistemic_defense.py` (add tests)

- [ ] **Step 1: Write the failing test**

```python
class TestHeuristicCognitiveType:
    def _heuristic(self, aspect):
        agent = GenericAgent.__new__(GenericAgent)
        return agent._heuristic_cognitive_type(aspect)

    def test_chinese_inference_driven(self):
        assert self._heuristic("投资建议") == "inference_driven"
        assert self._heuristic("战略研判") == "inference_driven"

    def test_chinese_forward_looking(self):
        assert self._heuristic("技术趋势") == "forward_looking"
        assert self._heuristic("政策法规") == "forward_looking"

    def test_chinese_assessment_driven(self):
        assert self._heuristic("估值分析") == "assessment_driven"
        assert self._heuristic("风险分析") == "assessment_driven"

    def test_english_inference_driven(self):
        assert self._heuristic("Investment Strategy") == "inference_driven"
        assert self._heuristic("Strategic Intent") == "inference_driven"

    def test_english_forward_looking(self):
        assert self._heuristic("Technology Trends") == "forward_looking"
        assert self._heuristic("Policy Analysis") == "forward_looking"

    def test_english_assessment_driven(self):
        assert self._heuristic("Risk Assessment") == "assessment_driven"
        assert self._heuristic("Valuation") == "assessment_driven"

    def test_no_match_returns_none(self):
        assert self._heuristic("市场规模") is None
        assert self._heuristic("竞争格局") is None

    def test_mixed_chinese_english(self):
        result = self._heuristic("投资Valuation")
        assert result in ("inference_driven", "assessment_driven")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestHeuristicCognitiveType -v`
Expected: FAIL

- [ ] **Step 3: Implement _heuristic_cognitive_type**

Add method to `GenericAgent` class in `src/core/agents/generic_agent.py`:

```python
    def _heuristic_cognitive_type(self, aspect: str):
        _SIGNALS = {
            "inference_driven": [
                "投资", "战略", "建议", "策略", "研判", "意图", "决策", "配置",
                "invest", "strateg", "advice", "recommend", "intent", "decision", "allocat",
            ],
            "forward_looking": [
                "趋势", "前景", "技术", "政策", "法规", "展望", "预测", "路线", "演进",
                "trend", "outlook", "forecast", "predict", "policy", "regulat", "roadmap", "evolution",
            ],
            "assessment_driven": [
                "估值", "风险", "财务", "评分", "评级", "敏感性", "压力测试",
                "valuat", "risk", "financ", "scor", "rat", "sensitiv", "stress",
            ],
        }
        aspect_lower = aspect.lower()
        scores = {}
        for ctype, keywords in _SIGNALS.items():
            scores[ctype] = sum(1 for kw in keywords if kw in aspect or kw in aspect_lower)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestHeuristicCognitiveType -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/agents/generic_agent.py tests/unit/test_epistemic_defense.py
git commit -m "feat: add _heuristic_cognitive_type bilingual keyword fallback"
```

---

### Task 3: LLM Dynamic Classification (infer_cognitive_type)

**Files:**
- Modify: `src/core/agents/generic_agent.py` (add async method)
- Modify: `tests/unit/test_epistemic_defense.py` (add tests with mock)

- [ ] **Step 1: Write the failing test**

```python
class TestInferCognitiveType:
    @pytest.mark.asyncio
    async def test_llm_full_classification(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "inference_driven", "success": True}
            result = await agent.infer_cognitive_type("投资建议", "中国智能手机")
            assert result == "inference_driven"
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_retry_on_empty(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [{"content": "", "success": True}, {"content": "forward_looking", "success": True}]
            result = await agent.infer_cognitive_type("技术趋势", "中国智能手机")
            assert result == "forward_looking"
            assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_heuristic_fallback(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [{"content": "", "success": True}, {"content": "", "success": True}]
            result = await agent.infer_cognitive_type("投资建议", "中国智能手机")
            assert result == "inference_driven"

    @pytest.mark.asyncio
    async def test_ultimate_fallback(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [{"content": "", "success": True}, {"content": "", "success": True}]
            result = await agent.infer_cognitive_type("市场规模", "中国智能手机")
            assert result == "fact_driven"

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": "assessment_driven", "success": True}
            r1 = await agent.infer_cognitive_type("风险分析", "中国智能手机")
            r2 = await agent.infer_cognitive_type("风险分析", "中国智能手机")
            assert r1 == "assessment_driven"
            assert r2 == "assessment_driven"
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_exception_falls_to_heuristic(self):
        agent = GenericAgent.__new__(GenericAgent)
        agent._context = {}
        with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [Exception("timeout"), Exception("timeout")]
            result = await agent.infer_cognitive_type("估值分析", "中国智能手机")
            assert result == "assessment_driven"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestInferCognitiveType -v`
Expected: FAIL

- [ ] **Step 3: Implement infer_cognitive_type**

Add async method to `GenericAgent` class:

```python
    async def infer_cognitive_type(self, aspect: str, topic: str = "") -> str:
        cache_key = f"cog_type:{aspect}:{topic}"
        cached = self._context.get(cache_key)
        if cached:
            return cached

        valid_types = {"fact_driven", "inference_driven", "forward_looking", "assessment_driven"}
        inferred = None
        method_used = "none"
        import re as _re

        try:
            result = await call_llm(
                prompt=f"""Classify the following research aspect into a cognitive type. Output ONLY the type name.

Research Topic: {topic}
Research Aspect: {aspect}

Cognitive type definitions:
- fact_driven: Describe current state, quantify facts (e.g., Market Size, Competitive Landscape, Industry Chain, 市场规模, 竞争格局, 产业链)
- inference_driven: Derive conclusions, guide action (e.g., Investment Advice, Strategic Judgment, 投资建议, 战略研判)
- forward_looking: Predict future, prospective analysis (e.g., Technology Trends, Policy & Regulation, 技术趋势, 政策法规)
- assessment_driven: Quantify & evaluate under conditions (e.g., Valuation, Risk Analysis, 估值分析, 风险分析)

Output ONE type name only: fact_driven / inference_driven / forward_looking / assessment_driven""",
                system_prompt="You are a research methodology expert.",
                max_tokens=50,
                temperature=0.0,
            )
            content = result.get("content", "").strip().lower()
            for vt in valid_types:
                if _re.search(r'\b' + _re.escape(vt) + r'\b', content):
                    inferred = vt
                    method_used = "llm_full"
                    break
        except Exception as e:
            logger.warning(f"GenericAgent {self.agent_id}: cognitive type LLM full attempt failed: {e}")

        if inferred is None:
            try:
                result = await call_llm(
                    prompt=f"Which cognitive type is '{aspect}'? Output only: fact_driven / inference_driven / forward_looking / assessment_driven",
                    system_prompt="Output type name only.",
                    max_tokens=30,
                    temperature=0.0,
                )
                content = result.get("content", "").strip().lower()
                for vt in valid_types:
                    if _re.search(r'\b' + _re.escape(vt) + r'\b', content):
                        inferred = vt
                        method_used = "llm_retry"
                        break
            except Exception as e:
                logger.warning(f"GenericAgent {self.agent_id}: cognitive type LLM retry failed: {e}")

        if inferred is None:
            inferred = self._heuristic_cognitive_type(aspect)
            if inferred:
                method_used = "heuristic"

        if inferred is None:
            inferred = "fact_driven"
            method_used = "fallback"

        logger.info(f"GenericAgent {self.agent_id}: cognitive type for '{aspect}' = {inferred} (method: {method_used})")
        self._context[cache_key] = inferred
        return inferred
```

Also add necessary imports at top of test file:
```python
from unittest.mock import patch, AsyncMock
```

- [ ] **Step 4: Run test to verify it passes**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py::TestInferCognitiveType -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/agents/generic_agent.py tests/unit/test_epistemic_defense.py
git commit -m "feat: add infer_cognitive_type with 4-level degradation chain"
```

---

### Task 4: Integrate infer_cognitive_type into Execution Flow

**Files:**
- Modify: `src/core/agents/generic_agent.py` (~line 708 in _execute_research_phase)

- [ ] **Step 1: Add cognitive type inference call**

In `_execute_research_phase()`, BEFORE the hypothesis generation block (~line 708), add:

```python
                        _cog_type = await self.infer_cognitive_type(aspect, topic)
                        _cog_strategy = COGNITIVE_STRATEGY.get(_cog_type, COGNITIVE_STRATEGY["fact_driven"])
                        self._context[f"cog_strategy:{aspect}"] = _cog_strategy
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py -v`
Expected: All 50+ tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/agents/generic_agent.py
git commit -m "feat: integrate infer_cognitive_type into execution flow"
```

---

### Task 5: Strategy-Driven L3 + L4 Injection

**Files:**
- Modify: `src/core/agents/generic_agent.py` (_build_analysis_prompt_with_data)

- [ ] **Step 1: Replace _ASPECT_SPECULATIVE_POLICY with strategy lookup**

In `_build_analysis_prompt_with_data()`, replace the `_ASPECT_SPECULATIVE_POLICY` dict and `_aspect_policy` lookup with:

```python
            _cog_strategy = self._context.get(f"cog_strategy:{aspect}", COGNITIVE_STRATEGY["fact_driven"])
            _aspect_policy = _cog_strategy["L3"]["speculative_policy"]
```

Remove the entire `_ASPECT_SPECULATIVE_POLICY` dict.

- [ ] **Step 2: Replace L4 hardcoded hypothesis parameters with strategy**

Replace the hypothesis injection block with strategy-driven values:

```python
            if causal_hypotheses:
                _l4 = _cog_strategy["L4"]
                parts.append(f"\n### {_l4['hypothesis_type']}假设（必须验证或修正）")
                for i, h in enumerate(causal_hypotheses, 1):
                    parts.append(f"  {i}. {h.get('statement','')}")
                    parts.append(f"     验证数据需求：{h.get('verification_data','')}")
                    parts.append(f"     跨维度传导：{h.get('transmission','')}")
                    if h.get('counter_hypothesis'):
                        parts.append(f"     反面假设：{h['counter_hypothesis']}")
                parts.append("\n**假设驱动分析要求**：")
                parts.append(f"  1. 对每个给定假设，按以下格式逐一验证：")
                parts.append(f"     {_l4['hypothesis_template']}")
                if _l4['agent_hypothesis_count'] > 0:
                    parts.append(f"  2. 基于你掌握的数据，你必须额外提出至少{_l4['agent_hypothesis_count']}个新的{_l4['hypothesis_type']}假设，同样按上述格式验证")
                if _l4['counter_hypothesis_required']:
                    parts.append(f"  3. 对每个关键假设（包括你提出的），评估其反面假设成立的可能性")
                parts.append(f"  4. 最终结论必须基于假设验证结果推导，而非直接下判断")
                parts.append(f"\n**输出格式**：在分析末尾按以下格式输出验证结果：")
                parts.append(_l4['output_suffix'])
                for i, h in enumerate(causal_hypotheses, 1):
                    parts.append(f"假设{i}：验证|修正|推翻 | 依据：... | 修正内容：...(仅修正时填写) | 反面假设可能性：高/中/低")
                if _l4['agent_hypothesis_count'] > 0:
                    for j in range(1, _l4['agent_hypothesis_count'] + 1):
                        parts.append(f"假设{len(causal_hypotheses)+j}(新)：[陈述] | 验证|修正|推翻 | 依据：... | 反面假设可能性：高/中/低")
```

- [ ] **Step 3: Replace L3 evidence_chain_template with strategy**

In the evidence chain section, replace hardcoded template:

```python
                parts.append(f"  - 每个关键结论必须附带：{_l4['hypothesis_type'] == 'Causal' and '前提→推理→结论' or _cog_strategy['L3']['evidence_chain_template']}，标注每步的认知层级（事实/推断/前瞻）")
```

- [ ] **Step 4: Add L5 contradiction_instruction to L3 contradiction section**

In the contradiction injection section, add strategy-driven instruction:

```python
                _l5 = _cog_strategy["L5"]
                parts.append(f"\n**要求**: {_l5['contradiction_instruction']}")
```

- [ ] **Step 5: Update hypothesis generation prompt with strategy**

In the hypothesis generation prompt (~line 712), replace hardcoded "3-5个" and "因果假设" with:

```python
                                _l4_gen = _cog_strategy["L4"]
                                _hcount = _l4_gen["hypothesis_count"]
                                _hcount_str = f"{_hcount[0]}-{_hcount[1]}" if isinstance(_hcount, tuple) else str(_hcount)
                                hypothesis_prompt = f"""基于以下数据，生成{_hcount_str}个关于「{aspect}」的{_l4_gen['hypothesis_type']}假设。
每个假设必须：1) 可被数据验证或反驳 2) 涉及跨维度因果传导 3) 不与已知事实矛盾{'' if not _l4_gen['counter_hypothesis_required'] else ' 4) 包含反面假设'}
```

- [ ] **Step 6: Run all tests**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/agents/generic_agent.py
git commit -m "feat: strategy-driven L3/L4/L5 injection replacing hardcoded parameters"
```

---

### Task 6: L2 Strategy Integration (Deferred — Mark Only)

**Files:**
- Modify: `src/core/communication.py` (NOT in this iteration)

Per spec v1.3, L2 `same_caliber_resolution` and `speculative_write_policy` are new features that can be deferred. Current `communication.py` behavior serves as default for all types.

- [ ] **Step 1: Add TODO comment in communication.py**

Add at top of `write_canonical()` method:

```python
        # TODO: L2 strategy integration — accept same_caliber_resolution and speculative_write_policy
        # from COGNITIVE_STRATEGY. Currently uses default behavior for all types.
        # See docs/superpowers/specs/2026-07-01-aspect-cognitive-strategy-design.md Section 4.3
```

- [ ] **Step 2: Commit**

```bash
git add src/core/communication.py
git commit -m "chore: add L2 strategy integration TODO for deferred implementation"
```

---

### Task 7: Update A/B Evaluation Script

**Files:**
- Modify: `scripts/epistemic_quality_eval.py`

- [ ] **Step 1: Update aspects to cover all 4 cognitive types**

Change:
```python
    aspects = ["投资建议", "战略研判"]
```
To:
```python
    aspects = ["竞争格局", "投资建议", "技术趋势", "风险分析"]
```

- [ ] **Step 2: Update build_with_defense_prompt to use COGNITIVE_STRATEGY**

Import and use the registry in the B group prompt builder, replacing hardcoded L4 hypothesis section with strategy-driven values.

- [ ] **Step 3: Commit**

```bash
git add scripts/epistemic_quality_eval.py
git commit -m "feat: update A/B eval with 4 cognitive type coverage"
```

---

### Task 8: Run Full Test Suite + A/B Evaluation

- [ ] **Step 1: Run all pytest**

Run: `D:\conda\python.exe -m pytest tests/unit/test_epistemic_defense.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run A/B evaluation**

Run: `D:\conda\python.exe scripts/epistemic_quality_eval.py`
Expected: Results for 4 aspects saved to JSON

- [ ] **Step 3: Version bump and commit**

Update `pyproject.toml` version to `1.8.0`.

```bash
git add pyproject.toml
git commit -m "chore: bump version to 1.8.0 for aspect-adaptive cognitive strategy"
```

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```
