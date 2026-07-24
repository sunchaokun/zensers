# Aspect-Adaptive Cognitive Strategy Design

> Version: 1.3 | Date: 2026-07-01 | Status: Self-reviewed (round 3 complete)

## 1. Problem Statement

Current epistemic defense (L1-L5) applies identical strategies across all research aspects:
- Same hypothesis generation prompt for "Market Size" and "Investment Advice"
- Same verification template for "Technology Trends" and "Risk Analysis"
- Same reasoning injection for "Valuation" and "Competitive Landscape"
- Same contradiction handling for all dimension types

This one-size-fits-all approach caused measurable quality degradation:
- Investment advice lost depth when speculative claims were blanket-banned
- Hypothesis-driven scores stayed at 6/10 because factual dimensions don't need causal hypotheses
- Strategic judgment contradiction handling scored 9/10 but risk analysis only 4/10 — same strategy, different fit

**Root cause**: Different research dimensions have fundamentally different cognitive profiles. Applying the same epistemic defense strategy to all is itself a cognitive error.

## 2. Cognitive Type Taxonomy

Four cognitive types, defined by their core analytical task:

| Type | Core Task | Primary Epistemic Level | Example Aspects |
|------|-----------|------------------------|-----------------|
| `fact_driven` | Describe current state | factual | Market Size, Competitive Landscape, Industry Chain, Market Structure |
| `inference_driven` | Derive conclusions & guide action | inferential | Investment Advice, Strategic Judgment, Strategic Intent |
| `forward_looking` | Predict future & prospective analysis | speculative | Technology Trends, Policy & Regulation, Development Trends, Outlook |
| `assessment_driven` | Quantify & evaluate under conditions | factual + inferential | Valuation, Risk Analysis, Financial Analysis |

### Cognitive Profile Comparison

| Characteristic | fact_driven | inference_driven | forward_looking | assessment_driven |
|---------------|-------------|------------------|-----------------|-------------------|
| Hypothesis nature | Descriptive (what is) | Causal (why) | Predictive (what will be) | Conditional (if...then) |
| Verification method | Data cross-validation | Logic chain verification | Falsification test | Sensitivity analysis |
| Contradiction handling | Data conflict → pick credible source | Logic conflict → re-examine premises | Prediction conflict → scenario analysis | Assumption conflict → sensitivity analysis |
| Speculative tolerance | Very low | Medium (requires labeling) | Higher (requires falsification conditions) | Low (requires quantified ranges) |
| Default claim ceiling | inferential | speculative | none | inferential |
| Hypothesis count | 1-2 (data verification) | 3-5 (causal chain) | 2-3 (scenario prediction) | 2-3 (sensitivity assumption) |

## 3. Dynamic Cognitive Type Inference

### 3.1 Why Not Hardcoded Mapping

Hardcoding `aspect_name → cognitive_type` has the same design flaw as the old L5 keyword lookup table:
- New research dimensions require code changes
- Same aspect name can mean different things across topics
- Cannot scale to user-defined custom dimensions

### 3.2 LLM-Based Dynamic Classification

Use LLM to infer cognitive type from aspect name + topic context:

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

    # Level 1: LLM full classification (bilingual prompt)
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
        # Extract type: find exact word boundary match to avoid "not fact_driven" false positive
        for vt in valid_types:
            if re.search(r'\b' + re.escape(vt) + r'\b', content):
                inferred = vt
                method_used = "llm_full"
                break
    except Exception as e:
        logger.warning(f"GenericAgent: cognitive type LLM full attempt failed: {e}")

    # Level 2: LLM simplified retry (bilingual, stripped prompt)
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
                if re.search(r'\b' + re.escape(vt) + r'\b', content):
                    inferred = vt
                    method_used = "llm_retry"
                    break
        except Exception as e:
            logger.warning(f"GenericAgent: cognitive type LLM retry failed: {e}")

    # Level 3: Keyword heuristic fallback (if both LLM attempts failed)
    if inferred is None:
        inferred = self._heuristic_cognitive_type(aspect)
        method_used = "heuristic"

    # Level 4: Ultimate fallback (if heuristic returned None)
    if inferred is None:
        inferred = "fact_driven"
        method_used = "fallback"

    logger.info(f"GenericAgent: cognitive type for '{aspect}' = {inferred} (method: {method_used})")
    self._context[cache_key] = inferred
    return inferred

def _heuristic_cognitive_type(self, aspect: str) -> Optional[str]:
    """Bilingual keyword heuristic fallback — NOT the primary classification method.
    Only used when LLM classification fails twice.
    Keywords describe signals, not mappings. Both Chinese and English signals included."""
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

### 3.3 Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Classification method | LLM dynamic (primary) | Zero maintenance, semantic understanding, context-aware |
| Bilingual support | All 4 levels support Chinese & English | System receives both Chinese ("投资建议") and English ("Strategic Intent") aspects; LLM prompts include bilingual examples; heuristic keywords include both languages; English keywords use prefix matching (e.g., "strateg" matches "strategy"/"strategic") |
| Degradation chain | LLM full → LLM retry → Keyword heuristic → fact_driven fallback | 4-level resilience ensures system never blocks on classification failure |
| Cache strategy | Per aspect+topic in agent context | Same aspect only classified once per report generation |
| LLM full max_tokens | 50 | Only need one type name (~15 chars), but DeepSeek reasoning_tokens consume budget; 50 gives margin for reasoning overhead |
| LLM retry max_tokens | 30 | Simplified prompt, but still needs margin for reasoning_tokens |
| temperature | 0.0 | Deterministic classification |
| Keyword heuristic | Yes, as Level 3 fallback only, bilingual | Not the primary method — only used when LLM fails twice; keywords describe signals not mappings; English keywords use prefix matching to handle morphological variation |
| Ultimate fallback | fact_driven | Most conservative strategy, matches current default behavior |
| Degradation logging | Every level logs method_used | Monitor degradation frequency; if heuristic rate > 20%, investigate LLM reliability |
| Topic as context | Yes (L1 only) | Disambiguate "technology" in "Technology Trends" vs "Technology Valuation"; L2 retry omits topic for speed |
| LLM prompt language | English with bilingual examples | English prompt avoids DeepSeek reasoning_tokens overhead with CJK; bilingual examples ensure LLM understands both Chinese and English aspect names |

### 3.4 Degradation Chain Detail

```
infer_cognitive_type(aspect, topic)
│
├─ Cache hit? ──→ return cached
│
├─ Level 1: LLM full prompt (max_tokens=50)
│   ├─ Valid type extracted → return (method: llm_full)
│   └─ Empty/invalid/exception → continue
│
├─ Level 2: LLM simplified retry (max_tokens=30)
│   ├─ Valid type extracted → return (method: llm_retry)
│   └─ Empty/invalid/exception → continue
│
├─ Level 3: Keyword heuristic (_heuristic_cognitive_type)
│   ├─ Best score > 0 → return (method: heuristic)
│   └─ No keyword match → continue
│
└─ Level 4: Ultimate fallback
    └─ return fact_driven (method: fallback)
```

**Why L2 retry uses simplified prompt**: DeepSeek-v4-flash uses reasoning_tokens that consume max_tokens budget. If L1's 4-type definition triggers excessive reasoning, the 50-token budget may be consumed by reasoning alone, leaving 0 tokens for the actual answer. L2 strips the definitions to minimize reasoning overhead.

**Why keyword heuristic is Level 3, not Level 2**: Keywords are less accurate than LLM but faster and deterministic. Placing them after one LLM retry gives the LLM a fair chance while ensuring the system doesn't hang on LLM failures.

## 4. Cognitive Strategy Registry

### 4.1 Strategy Structure

```python
COGNITIVE_STRATEGY = {
    "fact_driven": {
        "L1": { ... },
        "L2": { ... },
        "L3": { ... },
        "L4": { ... },
        "L5": { ... },
    },
    "inference_driven": { ... },
    "forward_looking": { ... },
    "assessment_driven": { ... },
}
```

### 4.2 L1: Claim Extraction & Epistemic Level Validation

| Parameter | fact_driven | inference_driven | forward_looking | assessment_driven |
|-----------|-------------|------------------|-----------------|-------------------|
| `dimension_ceiling` | `"inferential"` | `"speculative"` | `None` (no ceiling) | `"inferential"` |
| `speculative_word_downgrade` | `"strict"` (any speculative word in any claim → downgrade) | `"moderate"` (only downgrade factual claims containing speculative words) | `"relaxed"` (preserve original epistemic_level) | `"strict"` (only downgrade factual claims containing speculative words) |
| `confidence_threshold` | `{"factual": "HIGH"}` (factual claims require HIGH confidence) | `{"factual": "MEDIUM"}` (factual claims accepted at MEDIUM) | `{"speculative": "LOW"}` (speculative claims accepted at LOW) | `{"factual": "HIGH", "inferential": "HIGH"}` (both factual and inferential require HIGH; quantitative assertions are inferential-level claims) |

> **Note**: `confidence_threshold` keys correspond to existing epistemic levels (`factual`, `inferential`, `speculative`). There is no `quantitative` epistemic level in the current system — quantitative assertions are classified as `inferential` when derived from data. The `assessment_driven` threshold uses `inferential: HIGH` to cover this case.

**Rationale**: 
- `fact_driven` caps at inferential because factual dimensions should not make speculative claims (e.g., "market size may grow 50%" is inappropriate for a market size dimension). This matches the current `_DIMENSION_CEILING` behavior for non-strategic-intent dimensions.
- `forward_looking` has no ceiling (`None`) because speculative claims are the natural output of predictive dimensions. In code, `dimension_ceiling=None` means no downgrade is applied regardless of epistemic level.
- `assessment_driven` requires HIGH confidence for quantitative assertions because valuation/risk numbers must be well-supported
- **Note**: Current code has no dimension_ceiling for most aspects (only "战略意图" is ceiling-capped to speculative). `fact_driven` inferential ceiling is a tightening — factual dimensions will no longer produce speculative claims. This is intentional but may surface cases where the old behavior was more permissive.

### 4.3 L2: Source Priority & Write Canonical

| Parameter | fact_driven | inference_driven | forward_looking | assessment_driven |
|-----------|-------------|------------------|-----------------|-------------------|
| `caliber_floor_for_citation` | `"llm_inference_factual"` | `"llm_inference_speculative"` | `"llm_inference_speculative"` | `"llm_inference_factual"` |
| `same_caliber_resolution` | `"newer_timestamp"` | `"higher_source_count"` | `"wider_coverage"` | `"more_precise_data"` |
| `speculative_write_policy` | `"never"` (never write speculative to canonical) | `"with_uncertainty_tag"` (write with uncertainty label) | `"with_falsification_condition"` (write with falsification requirement) | `"with_confidence_interval"` (write with quantified range) |

> **Implementation note**: `same_caliber_resolution` and `speculative_write_policy` are new L2 behaviors not present in the current `communication.py`. Implementation requires adding strategy-aware branching to `write_canonical()`. If implementation timeline is tight, these two parameters can be deferred to a follow-up iteration with current behavior as default for all types.

**Rationale**:
- `fact_driven` never writes speculative claims to canonical because factual dimensions should not have speculative canonical data
- `forward_looking` uses `llm_inference_speculative` as citation floor because forward-looking dimensions often derive from reports and news that carry speculative assertions
- `assessment_driven` prefers more precise data (e.g., "32.1%" over "~30%")

### 4.4 L3: Reasoning-Driven Injection

**Speculative Policy Definitions** (3 tiers, replacing the old 2-tier system):

| Policy | Description | Use Case |
|--------|-------------|----------|
| `reference_only` | Speculative claims cannot be used as conclusion basis; only as analytical direction reference. Must state inspiration path. | fact_driven, assessment_driven |
| `cautious_use` | Speculative claims can be used as directional reference with mandatory uncertainty labels + scenario analysis (optimistic/neutral/pessimistic). Must state falsification conditions. | inference_driven |
| `open_use` | Speculative claims are the natural output of this dimension. Must include: (1) falsification conditions, (2) probability assessment, (3) time horizon, (4) alternative predictions. No "cannot use as conclusion" restriction. | forward_looking |

| Parameter | fact_driven | inference_driven | forward_looking | assessment_driven |
|-----------|-------------|------------------|-----------------|-------------------|
| `speculative_policy` | reference_only | cautious_use | open_use | reference_only |
| `reasoning_mode` | cross_validation | causal_chain | scenario_analysis | sensitivity_analysis |
| `inferential_instruction` | "Verify with data; flag unsupported claims" | "Build causal chain; check premises" | "Map to scenarios; assign probabilities" | "Quantify impact; define assumptions" |
| `falsification_requirement` | Required for all inferential claims | Required for speculative claims | Required for all claims | Required for all key assumptions |
| `evidence_chain_template` | Data → Finding → Confirmation | Premise → Reasoning → Conclusion | Signal → Scenario → Probability | Assumption → Model → Range |
| `cross_dimension_instruction` | "Cross-validate with other factual dimensions" | "Trace causal transmission from other dimensions" | "Check consistency with other forward-looking claims" | "Verify assumptions against factual dimension data" |

> **Note**: `evidence_chain_template` and `inferential_instruction` are prompt injection strings, injected into the analysis prompt at L3-E section. `cross_dimension_instruction` is prepended to the cross-dimension claims section.

**Rationale**:
- `fact_driven` uses cross_validation because factual claims are verified by data consistency
- `inference_driven` uses causal_chain because conclusions must follow from premises
- `forward_looking` uses scenario_analysis because predictions are inherently uncertain and need scenario decomposition
- `assessment_driven` uses sensitivity_analysis because evaluations depend on assumptions whose sensitivity must be quantified

### 4.5 L4: Hypothesis-Driven Analysis

| Parameter | fact_driven | inference_driven | forward_looking | assessment_driven |
|-----------|-------------|------------------|-----------------|-------------------|
| `hypothesis_type` | Descriptive | Causal | Predictive | Conditional |
| `hypothesis_count` | 0 (data verification, not hypothesis) | 3-5 | 2-3 | 2-3 |
| `hypothesis_template` | 【Data Observation H1】 → 【Supporting Evidence】→ 【Confirmed/Disconfirmed】→ 【Finding】 | 【Causal Hypothesis H1】 → 【Supporting Evidence】→ 【Confirmed/Revised/Refuted】→ 【Conclusion】 | 【Predictive Hypothesis H1】 → 【Supporting Signals】→ 【Probability Assessment】→ 【Scenario】 | 【Conditional Hypothesis H1】 → 【Assumption Base】→ 【Sensitivity Test】→ 【Value Range】 |
| `counter_hypothesis_required` | No | Yes | Yes | Yes |
| `agent_hypothesis_count` | 0 (not needed) | 2+ | 1+ | 1+ |
| `verification_focus` | Data accuracy | Logic completeness | Falsification conditions | Assumption sensitivity |
| `output_suffix` | "数据验证结果：" | "假设验证结果：" | "前瞻验证结果：" | "假设敏感性检验：" |

> **Implementation note**: `output_suffix` varies by cognitive type but `_parse_hypothesis_verification()` currently only recognizes `["假设验证结果", "假设验证结果：", "验证结果"]` as section markers. All 4 suffixes must be added to the marker list. Alternatively, use a single unified marker "验证结果：" across all types to avoid parse fragmentation.

**Rationale**:
- `fact_driven` needs 0 agent-generated hypotheses because factual dimensions verify data, not generate new causal claims
- `inference_driven` needs 2+ agent-generated hypotheses because investment/strategy analysis thrives on discovering hidden causal links
- `forward_looking` focuses on falsification conditions because predictions are only useful when you know what would disprove them
- `assessment_driven` focuses on assumption sensitivity because valuation/risk numbers are only as reliable as their assumptions

### 4.6 L5: Contradiction Detection & Resolution

| Parameter | fact_driven | inference_driven | forward_looking | assessment_driven |
|-----------|-------------|------------------|-----------------|-------------------|
| `contradiction_resolution` | Data conflict resolution (pick credible source, flag discrepancy) | Premise re-examination (trace which premise failed) | Scenario reconciliation (both may be valid under different scenarios) | Assumption divergence (which assumption drives the difference) |
| `contradiction_instruction` | "两项事实性主张冲突，请判断哪个数据源更可信并说明理由。" | "两项结论冲突，请追溯哪个前提或推理步骤出现了分歧。" | "两项预测冲突，请分析在什么条件下各自成立，并给出情景分析。" | "两项评估冲突，请识别哪个假设差异导致了分歧，并量化影响。" |
| `auto_resolve_threshold` | 0.8 | 0.6 | 0.4 | 0.7 |
| `escalation_action` | Flag for human review | Inject as reasoning challenge | Present both scenarios | Show sensitivity of each assumption |

> **Implementation notes**:
> 1. `contradiction_instruction` is NOT used in the L5 LLM call. It is injected into the L3 analysis prompt at the contradiction section. L5 detection logic remains type-agnostic; only the downstream handling instruction varies by cognitive type.
> 2. `auto_resolve_threshold` and `escalation_action` are new features, deferred to a follow-up iteration. Currently L5 only detects contradictions and injects them into the analysis prompt.

**Rationale**:
- `fact_driven` contradictions are data conflicts — one claim is usually wrong, needs high confidence to resolve
- `inference_driven` contradictions are logic conflicts — need to trace premises, not just pick a winner
- `forward_looking` contradictions are prediction conflicts — often both are valid under different assumptions, scenario reconciliation is appropriate
- `assessment_driven` contradictions are assumption conflicts — need to show which assumption drives the divergence

## 5. Implementation Architecture

### 5.1 File Changes

| File | Change |
|------|--------|
| `src/core/agents/generic_agent.py` | Add `infer_cognitive_type()`, `_heuristic_cognitive_type()`, `COGNITIVE_STRATEGY` registry, modify L1/L3/L4/L5 execution points to use strategy parameters |
| `src/core/communication.py` | Modify L2 `write_canonical()` and `_compute_claim_caliber()` to accept strategy parameters for `caliber_floor`, `same_caliber_resolution`, `speculative_write_policy` |
| `tests/unit/test_epistemic_defense.py` | Add tests for cognitive type inference, heuristic fallback, cache behavior, and strategy parameter lookup |

### 5.2 Execution Flow

```
1. Agent receives aspect + topic
2. await infer_cognitive_type(aspect, topic) → cognitive_type  [async, called once in _execute_research_phase(), cached in self._context]
3. strategy = COGNITIVE_STRATEGY[cognitive_type]
4. L1: Use strategy["L1"] parameters in _extract_claims_from_analysis()
5. L2: Pass strategy["L2"] to communication.py write_canonical() / _compute_claim_caliber()
6. L3: Use strategy["L3"] parameters in _build_analysis_prompt_with_data()
7. L4: Use strategy["L4"] parameters in hypothesis generation prompt + _build_analysis_prompt_with_data()
8. L5: Use strategy["L5"]["contradiction_instruction"] in L3 contradiction section injection
```

**Call site**: `infer_cognitive_type()` is async and MUST be called in an async context. It is called at the beginning of `_execute_research_phase()` (which is already async, ~line 708), BEFORE `_build_analysis_prompt_with_data()`. The result is stored in `self._context[f"cog_type:{aspect}:{topic}"]` and reused by all layers. `_build_analysis_prompt_with_data()` is synchronous and reads the cached result from `self._context`.

### 5.3 Backward Compatibility

- `infer_cognitive_type()` fallback to `fact_driven` on LLM failure → matches current conservative behavior
- `COGNITIVE_STRATEGY["fact_driven"]` designed to closely match current default behavior
- Existing `_ASPECT_SPECULATIVE_POLICY` entries are absorbed into `COGNITIVE_STRATEGY[type]["L3"]["speculative_policy"]`; the old dict is removed and its call site replaced with strategy lookup
- **Migration mapping**: `投资建议/投资策略/战略研判/战略意图/战略意图推断/前景展望` → `inference_driven.cautious_use`; all other aspects → `fact_driven.reference_only` or `assessment_driven.reference_only`. The new `forward_looking.open_use` has no pre-existing mapping (net new capability).
- All existing 50 pytest tests must continue to pass without modification

### 5.4 Strategy Parameter Integration Points

Each strategy parameter is consumed at a specific location in `generic_agent.py`:

| Layer | Parameter | Integration Point (file:line) | Current Code |
|-------|-----------|-------------------------------|-------------|
| L1 | `dimension_ceiling` | `_extract_claims_from_analysis()` ~line 1660 | Hardcoded `if aspect in ["战略意图", ...]` |
| L1 | `speculative_word_downgrade` | `_extract_claims_from_analysis()` ~line 1640 | Hardcoded `if any(w in content for w in ["可能","预计"])` |
| L1 | `confidence_threshold` | `_extract_claims_from_analysis()` ~line 1625 | Hardcoded `if confidence == "LOW" and premise` |
| L2 | `caliber_floor_for_citation` | `_compute_claim_caliber()` in `communication.py` | No floor, all calibers accepted |
| L2 | `same_caliber_resolution` | `write_canonical()` in `communication.py` ~line 280 | Hardcoded timestamp preference |
| L2 | `speculative_write_policy` | `write_canonical()` in `communication.py` ~line 260 | Hardcoded "speculative cannot overwrite factual" |
| L3 | `speculative_policy` | `_build_analysis_prompt_with_data()` ~line 4773 | `_ASPECT_SPECULATIVE_POLICY` dict |
| L3 | `reasoning_mode` | `_build_analysis_prompt_with_data()` ~line 4795 | Hardcoded "交叉验证/因果链" text |
| L3 | `evidence_chain_template` | `_build_analysis_prompt_with_data()` ~line 4835 | Hardcoded "支持证据→推理步骤→结论" text |
| L4 | `hypothesis_type` | Hypothesis generation prompt ~line 712 | Hardcoded "因果假设" |
| L4 | `hypothesis_count` | Hypothesis generation prompt ~line 712 | Hardcoded "3-5个" |
| L4 | `hypothesis_template` | `_build_analysis_prompt_with_data()` ~line 4730 | Hardcoded "假设H1→证据→验证→结论" |
| L4 | `agent_hypothesis_count` | `_build_analysis_prompt_with_data()` ~line 4733 | Hardcoded "至少2个" |
| L4 | `output_suffix` | `_build_analysis_prompt_with_data()` ~line 4735 | Hardcoded "假设验证结果：" |
| L5 | `contradiction_instruction` | `_detect_claim_contradiction()` ~line 830 | Not yet parameterized |
| L5 | `auto_resolve_threshold` | `_detect_claim_contradiction()` | New feature (deferred) |

**Migration pattern**: Each integration point follows the same pattern:
```python
# Before (hardcoded)
if aspect in ["战略意图", "战略意图推断"]:
    claim["epistemic_level"] = "speculative"

# After (strategy-driven)
cog_type = self._context.get(f"cog_type:{aspect}:{topic}", "fact_driven")
strategy = COGNITIVE_STRATEGY[cog_type]
if strategy["L1"]["dimension_ceiling"] and current_level_index > level_index(strategy["L1"]["dimension_ceiling"]):
    claim["epistemic_level"] = strategy["L1"]["dimension_ceiling"]
```

### 5.5 Performance Consideration

- `infer_cognitive_type()` adds 1-3 LLM calls per aspect (L1 success = 1 call, L1 fail + L2 success = 2 calls, both fail = 0 additional LLM calls, falls to heuristic)
- For a 6-aspect report: best case 6 additional LLM calls, worst case 12 (both L1 and L2 fail for all aspects), each ~20 tokens output → negligible cost
- Cache ensures no repeated calls for same aspect+topic
- L2 retry uses max_tokens=30 to minimize cost on degradation path

## 6. Validation Plan

### 6.1 Unit Tests

- Test `infer_cognitive_type()` with mocked LLM responses for each type
- Test fallback behavior when LLM fails
- Test cache behavior (second call returns cached result)
- Test each L1-L5 strategy parameter is correctly applied

### 6.2 A/B Quality Evaluation

Run `epistemic_quality_eval.py` across 4 cognitive types:
- fact_driven: 竞争格局
- inference_driven: 投资建议
- forward_looking: 技术趋势
- assessment_driven: 风险分析

Expected improvements:
- hypothesis_driven: Each type uses appropriate hypothesis template → higher relevance scores
- contradiction_handling: Type-specific resolution → higher scores for non-factual types
- insight_quality: Reasoning mode matches analytical task → deeper analysis

**Statistical note**: Single-run A/B evaluation is directional, not statistically significant. If results are ambiguous (delta < 2 points on any dimension), run 3 independent evaluations and take median. LLM temperature=0.3 for report generation introduces variance; eval temperature=0.0 for consistency.

### 6.3 Regression Tests

All 50 existing pytest tests must pass. New tests added for cognitive strategy features.

## 7. Future Extensions

- **User override**: Allow users to manually specify cognitive type in config (takes precedence over LLM inference)
- **Learning from feedback**: Track which cognitive type assignments led to highest quality scores, adjust inference prompt accordingly
- **Mixed-type aspects**: Some aspects may span two types (e.g., "competitive strategy" = fact_driven + inference_driven); future version could support primary/secondary type
- **Batch classification**: Classify all aspects in one LLM call instead of per-aspect, reducing latency
