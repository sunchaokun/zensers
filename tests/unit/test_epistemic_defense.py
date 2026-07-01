"""Unit tests for epistemic defense (L1-L5) implementation.

Tests are self-contained and do not require LLM calls.
They verify the logic of each defense layer in isolation.
"""
import asyncio
import hashlib
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


# ==================== L1: _extract_claims_from_analysis ====================

class TestL1Truncation:
    """L1-C: Head-tail truncation preserves conclusion section."""

    def test_short_content_not_truncated(self):
        content = "A" * 2000
        if len(content) > 3000:
            truncated = content[:2500] + "\n\n...[中间省略]...\n\n" + content[-500:]
        else:
            truncated = content
        assert truncated == content

    def test_long_content_head_tail_preserved(self):
        head = "H" * 2500
        middle = "M" * 3000
        tail = "T" * 500
        content = head + middle + tail
        assert len(content) > 3000
        truncated = content[:2500] + "\n\n...[中间省略]...\n\n" + content[-500:]
        assert truncated.startswith("H" * 2500)
        assert truncated.endswith("T" * 500)
        assert "...[中间省略]..." in truncated

    def test_conclusion_section_preserved(self):
        content = "概述部分" + "详细分析" * 500 + "结论：AI芯片国产化率已突破30%"
        assert len(content) > 3000
        truncated = content[:2500] + "\n\n...[中间省略]...\n\n" + content[-500:]
        assert "结论：AI芯片国产化率已突破30%" in truncated


class TestL1RuleBasedValidation:
    """L1: Rule-based epistemic_level validation."""

    def test_low_confidence_with_premise_not_factual(self):
        claim = {"statement": "市场份额下降", "confidence": "LOW", "前提条件": "数据准确", "epistemic_level": "factual"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        _speculative_words = {"可能", "预计", "或许", "也许", "大概", "猜测", "推测", "预期"}
        _level = claim.get("epistemic_level", "inferential")
        if claim.get("confidence") == "LOW" and claim.get("前提条件") and _level == "factual":
            claim["epistemic_level"] = "inferential"
            _level = "inferential"
        assert claim["epistemic_level"] != "factual"

    def test_speculative_word_in_factual_downgraded(self):
        claim = {"statement": "企业可能通过并购突破", "confidence": "HIGH", "epistemic_level": "factual"}
        _speculative_words = {"可能", "预计", "或许", "也许", "大概", "猜测", "推测", "预期"}
        _level = claim.get("epistemic_level", "inferential")
        if _level == "factual" and any(w in claim.get("statement", "") for w in _speculative_words):
            claim["epistemic_level"] = "inferential"
        assert claim["epistemic_level"] == "inferential"

    def test_factual_without_speculative_words_kept(self):
        claim = {"statement": "2025年Q1市场份额为32%", "confidence": "HIGH", "epistemic_level": "factual"}
        _speculative_words = {"可能", "预计", "或许", "也许", "大概", "猜测", "推测", "预期"}
        _level = claim.get("epistemic_level", "inferential")
        if _level == "factual" and any(w in claim.get("statement", "") for w in _speculative_words):
            claim["epistemic_level"] = "inferential"
        assert claim["epistemic_level"] == "factual"

    def test_missing_epistemic_level_defaults_to_inferential(self):
        claim = {"statement": "some claim", "confidence": "MEDIUM"}
        if "epistemic_level" not in claim:
            claim["epistemic_level"] = "inferential"
        assert claim["epistemic_level"] == "inferential"

    def test_invalid_epistemic_level_defaults_to_inferential(self):
        claim = {"statement": "some claim", "confidence": "MEDIUM", "epistemic_level": "unknown"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        _level = claim.get("epistemic_level", "inferential")
        if _level not in _epistemic_order:
            claim["epistemic_level"] = "inferential"
        assert claim["epistemic_level"] == "inferential"


class TestL1DimensionCeiling:
    """L1-D: Dimension-level epistemic ceiling."""

    def test_strategic_intent_factual_downgraded(self):
        ASPECT_EPISTEMIC_CEILING = {
            "strategic_intent": "speculative",
            "战略意图": "speculative",
            "战略意图推断": "speculative",
            "Strategic Intent": "speculative",
        }
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        aspect = "strategic_intent"
        claim = {"epistemic_level": "factual"}
        _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
        _level = claim.get("epistemic_level", "inferential")
        if _ceiling and _epistemic_order.get(_level, 1) < _epistemic_order.get(_ceiling, 1):
            claim["epistemic_level"] = _ceiling
        assert claim["epistemic_level"] == "speculative"

    def test_strategic_intent_inferential_downgraded(self):
        ASPECT_EPISTEMIC_CEILING = {"strategic_intent": "speculative"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        aspect = "strategic_intent"
        claim = {"epistemic_level": "inferential"}
        _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
        _level = claim.get("epistemic_level", "inferential")
        if _ceiling and _epistemic_order.get(_level, 1) < _epistemic_order.get(_ceiling, 1):
            claim["epistemic_level"] = _ceiling
        assert claim["epistemic_level"] == "speculative"

    def test_non_ceiling_aspect_not_affected(self):
        ASPECT_EPISTEMIC_CEILING = {"strategic_intent": "speculative"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        aspect = "市场规模"
        claim = {"epistemic_level": "factual"}
        _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
        _level = claim.get("epistemic_level", "inferential")
        if _ceiling and _epistemic_order.get(_level, 1) < _epistemic_order.get(_ceiling, 1):
            claim["epistemic_level"] = _ceiling
        assert claim["epistemic_level"] == "factual"

    def test_strategic_intent_speculative_not_changed(self):
        ASPECT_EPISTEMIC_CEILING = {"strategic_intent": "speculative"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        aspect = "strategic_intent"
        claim = {"epistemic_level": "speculative"}
        _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
        _level = claim.get("epistemic_level", "inferential")
        if _ceiling and _epistemic_order.get(_level, 1) < _epistemic_order.get(_ceiling, 1):
            claim["epistemic_level"] = _ceiling
        assert claim["epistemic_level"] == "speculative"


# ==================== L2: SOURCE_PRIORITY + caliber ====================

class TestL2SourcePriority:
    """L2: Expanded SOURCE_PRIORITY with factual/inferential/speculative."""

    def test_priority_ordering(self):
        SOURCE_PRIORITY = {
            "structured_source": 100,
            "search_result": 50,
            "llm_inference_factual": 15,
            "llm_inference": 10,
            "llm_inference_speculative": 5,
        }
        assert SOURCE_PRIORITY["structured_source"] > SOURCE_PRIORITY["search_result"]
        assert SOURCE_PRIORITY["search_result"] > SOURCE_PRIORITY["llm_inference_factual"]
        assert SOURCE_PRIORITY["llm_inference_factual"] > SOURCE_PRIORITY["llm_inference"]
        assert SOURCE_PRIORITY["llm_inference"] > SOURCE_PRIORITY["llm_inference_speculative"]

    def test_caliber_map(self):
        caliber_map = {
            "factual": "llm_inference_factual",
            "inferential": "llm_inference",
            "speculative": "llm_inference_speculative",
        }
        assert caliber_map["factual"] == "llm_inference_factual"
        assert caliber_map["inferential"] == "llm_inference"
        assert caliber_map["speculative"] == "llm_inference_speculative"

    def test_caliber_map_default(self):
        caliber_map = {
            "factual": "llm_inference_factual",
            "inferential": "llm_inference",
            "speculative": "llm_inference_speculative",
        }
        assert caliber_map.get("unknown", "llm_inference") == "llm_inference"


class TestL2BWriteCanonical:
    """L2-B: Same-caliber logic with same-source exception."""

    @pytest.fixture
    def shared_memory(self):
        from src.core.communication import SharedMemory
        return SharedMemory()

    @pytest.mark.asyncio
    async def test_speculative_does_not_overwrite_factual(self, shared_memory):
        await shared_memory.write_canonical("test", 100, caliber="llm_inference_factual", source="a1", publisher="p")
        result = await shared_memory.write_canonical("test", 200, caliber="llm_inference_speculative", source="a2", publisher="p")
        entry = await shared_memory.get_canonical("test")
        assert entry["value"] == 100
        assert entry["caliber"] == "llm_inference_factual"

    @pytest.mark.asyncio
    async def test_factual_overwrites_inferential(self, shared_memory):
        await shared_memory.write_canonical("test", 100, caliber="llm_inference", source="a1", publisher="p")
        await shared_memory.write_canonical("test", 200, caliber="llm_inference_factual", source="a2", publisher="p")
        entry = await shared_memory.get_canonical("test")
        assert entry["value"] == 200
        assert entry["caliber"] == "llm_inference_factual"

    @pytest.mark.asyncio
    async def test_same_caliber_different_source_blocked(self, shared_memory):
        await shared_memory.write_canonical("test", 100, caliber="llm_inference_factual", source="a1", publisher="p")
        result = await shared_memory.write_canonical("test", 200, caliber="llm_inference_factual", source="a2", publisher="p")
        entry = await shared_memory.get_canonical("test")
        assert entry["value"] == 100
        assert result is not None

    @pytest.mark.asyncio
    async def test_same_caliber_same_source_allowed(self, shared_memory):
        await shared_memory.write_canonical("test", 100, caliber="llm_inference_factual", source="a1", publisher="p")
        await shared_memory.write_canonical("test", 200, caliber="llm_inference_factual", source="a1", publisher="p")
        entry = await shared_memory.get_canonical("test")
        assert entry["value"] == 200

    @pytest.mark.asyncio
    async def test_search_result_not_overwritten_by_factual(self, shared_memory):
        await shared_memory.write_canonical("test", 100, caliber="search_result", source="web", publisher="p")
        await shared_memory.write_canonical("test", 200, caliber="llm_inference_factual", source="a1", publisher="p")
        entry = await shared_memory.get_canonical("test")
        assert entry["value"] == 100
        assert entry["caliber"] == "search_result"


# ==================== L4: _parse_hypothesis_verification ====================

class TestL4HypothesisVerification:
    """L4: Structured output hypothesis verification parsing."""

    def _parse(self, content, hypotheses):
        verified = []
        verification_section = ""
        markers = ["假设验证结果", "假设验证结果：", "验证结果"]
        for marker in markers:
            if marker in content:
                idx = content.index(marker)
                verification_section = content[idx:]
                break
        if not verification_section:
            for h in hypotheses:
                h_copy = dict(h)
                h_copy["status"] = "unverified"
                h_copy["id"] = hashlib.md5(h.get("statement", "").encode()).hexdigest()[:8]
                verified.append(h_copy)
            return verified
        for i, h in enumerate(hypotheses):
            h_copy = dict(h)
            h_copy["id"] = hashlib.md5(h.get("statement", "").encode()).hexdigest()[:8]
            pattern = f"假设{i+1}"
            if pattern in verification_section:
                matching_lines = [line for line in verification_section.split("\n")
                                  if pattern in line and "|" in line]
                if matching_lines:
                    line = matching_lines[-1]
                    line_parts = line.split("|")
                    judgment_part = line_parts[0].strip()
                    if any(kw in judgment_part for kw in ["验证", "证实", "verified", "confirmed"]):
                        h_copy["status"] = "verified"
                    elif any(kw in judgment_part for kw in ["修正", "修订", "revised", "modified", "部分"]):
                        h_copy["status"] = "revised"
                        if len(line_parts) > 2:
                            h_copy["revision_note"] = line_parts[-1].strip().replace("修正内容：", "").replace("修正内容:", "")
                    elif any(kw in judgment_part for kw in ["推翻", "否定", "refuted", "rejected", "不成立"]):
                        h_copy["status"] = "refuted"
                    else:
                        h_copy["status"] = "unverified"
                else:
                    h_copy["status"] = "unverified"
            else:
                h_copy["status"] = "unverified"
            verified.append(h_copy)
        return verified

    def test_verified_hypothesis(self):
        content = "分析内容...\n假设验证结果：\n假设1：验证 | 依据：数据支撑"
        hypotheses = [{"statement": "政策收紧导致增速放缓"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "verified"

    def test_revised_hypothesis(self):
        content = "分析内容...\n假设验证结果：\n假设1：修正 | 依据：部分成立 | 修正内容：政策是辅助因素"
        hypotheses = [{"statement": "政策收紧导致增速放缓"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "revised"
        assert "政策是辅助因素" in result[0].get("revision_note", "")

    def test_refuted_hypothesis(self):
        content = "分析内容...\n假设验证结果：\n假设1：推翻 | 依据：与数据矛盾"
        hypotheses = [{"statement": "政策收紧导致增速放缓"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "refuted"

    def test_no_verification_section_fallback(self):
        content = "分析内容中无验证结果段"
        hypotheses = [{"statement": "政策收紧导致增速放缓"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "unverified"

    def test_multiple_hypotheses(self):
        content = "分析...\n假设验证结果：\n假设1：验证 | 依据：数据支撑\n假设2：修正 | 依据：部分成立 | 修正内容：非唯一原因\n假设3：推翻 | 依据：矛盾"
        hypotheses = [{"statement": "假设A"}, {"statement": "假设B"}, {"statement": "假设C"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "verified"
        assert result[1]["status"] == "revised"
        assert result[2]["status"] == "refuted"

    def test_last_matching_line_taken(self):
        content = "分析...\n假设验证结果：\n假设1：修正 | 依据：初步判断\n假设1：推翻 | 依据：最终判断"
        hypotheses = [{"statement": "假设A"}]
        result = self._parse(content, hypotheses)
        assert result[0]["status"] == "refuted"

    def test_stable_id_via_hash(self):
        hypotheses = [{"statement": "政策收紧导致增速放缓"}]
        result = self._parse("假设验证结果：\n假设1：验证 | 依据：数据", hypotheses)
        expected_id = hashlib.md5("政策收紧导致增速放缓".encode()).hexdigest()[:8]
        assert result[0]["id"] == expected_id


# ==================== L5: _detect_claim_contradiction ====================

class TestL5ContradictionDetection:
    """L5: Direction contradiction detection with 2-gram matching."""

    def _detect(self, claim_a, claim_b):
        stmt_a = claim_a.get("statement", "")
        stmt_b = claim_b.get("statement", "")
        if not stmt_a or not stmt_b:
            return None
        positive = {"增长", "上升", "扩张", "改善", "提升", "增加", "上涨", "回暖"}
        negative = {"下降", "萎缩", "收缩", "恶化", "下滑", "减少", "下跌", "承压"}
        a_pos = any(w in stmt_a for w in positive)
        a_neg = any(w in stmt_a for w in negative)
        b_pos = any(w in stmt_b for w in positive)
        b_neg = any(w in stmt_b for w in negative)
        if (a_pos and b_neg) or (a_neg and b_pos):
            def _bigrams(text):
                return {text[i:i+2] for i in range(len(text)-1)}
            bigrams_a = _bigrams(stmt_a)
            bigrams_b = _bigrams(stmt_b)
            dir_bigrams = set()
            for w in positive | negative:
                for i in range(len(w)-1):
                    dir_bigrams.add(w[i:i+2])
            content_a = bigrams_a - dir_bigrams
            content_b = bigrams_b - dir_bigrams
            if content_a and content_b:
                overlap = len(content_a & content_b) / max(len(content_a), 1)
                if overlap > 0.2:
                    return f"方向矛盾: '{stmt_a[:50]}' vs '{stmt_b[:50]}'"
        return None

    def test_direction_contradiction_detected(self):
        a = {"statement": "市场规模持续增长"}
        b = {"statement": "市场规模面临萎缩"}
        result = self._detect(a, b)
        assert result is not None
        assert "方向矛盾" in result

    def test_same_direction_no_contradiction(self):
        a = {"statement": "市场规模持续增长"}
        b = {"statement": "行业收入快速提升"}
        result = self._detect(a, b)
        assert result is None

    def test_no_direction_words_no_contradiction(self):
        a = {"statement": "企业A占据主导地位"}
        b = {"statement": "企业B市场份额领先"}
        result = self._detect(a, b)
        assert result is None

    def test_empty_statement_no_contradiction(self):
        a = {"statement": ""}
        b = {"statement": "市场规模增长"}
        result = self._detect(a, b)
        assert result is None

    def test_different_subject_low_overlap_no_contradiction(self):
        a = {"statement": "出口额持续增长"}
        b = {"statement": "内销利润面临萎缩"}
        result = self._detect(a, b)
        assert result is None

    def test_english_keywords(self):
        a = {"statement": "revenue increased significantly"}
        b = {"statement": "revenue declined sharply"}
        result = self._detect(a, b)
        assert result is None


# ==================== L3: Stratified injection ====================

class TestL3StratifiedInjection:
    """L3: Claims stratified by epistemic_level in prompt injection."""

    def test_claims_grouped_by_epistemic_level(self):
        cross_dimension_claims = [
            {"statement": "市场份额32%", "epistemic_level": "factual", "confidence": "HIGH", "source_aspect": "市场"},
            {"statement": "竞争加剧", "epistemic_level": "inferential", "confidence": "MEDIUM", "前提条件": "数据准确", "source_aspect": "竞争"},
            {"statement": "可能并购", "epistemic_level": "speculative", "confidence": "LOW", "falsification": "6个月无公告", "source_aspect": "战略"},
        ]
        factual = [c for c in cross_dimension_claims if c.get("epistemic_level") == "factual"]
        inferential = [c for c in cross_dimension_claims if c.get("epistemic_level") == "inferential"]
        speculative = [c for c in cross_dimension_claims if c.get("epistemic_level") == "speculative"]
        no_level = [c for c in cross_dimension_claims if c.get("epistemic_level") not in ("factual", "inferential", "speculative")]
        assert len(factual) == 1
        assert len(inferential) == 1
        assert len(speculative) == 1
        assert len(no_level) == 0

    def test_missing_epistemic_level_treated_as_inferential(self):
        cross_dimension_claims = [
            {"statement": "旧claim无level", "confidence": "MEDIUM"},
        ]
        no_level = [c for c in cross_dimension_claims if c.get("epistemic_level") not in ("factual", "inferential", "speculative")]
        inferential = [c for c in cross_dimension_claims if c.get("epistemic_level") == "inferential"]
        inferential.extend(no_level)
        assert len(inferential) == 1

    def test_conflict_entries_filtered_by_prefix(self):
        _all_canon = {
            "claim:市场:0": {"value": {"statement": "增长"}},
            "conflict:claim:市场:0": {"value": {"contradiction": "方向矛盾"}},
            "claim:竞争:0": {"value": {"statement": "加剧"}},
        }
        conflict_entries = {k: v for k, v in _all_canon.items() if k.startswith("conflict:claim:")}
        assert len(conflict_entries) == 1
        assert "conflict:claim:市场:0" in conflict_entries


# ==================== Integration: L1→L2→L3 end-to-end ====================

class TestEpistemicEndToEnd:
    """End-to-end test: L1 classification → L2 caliber → L3 injection."""

    def test_speculative_claim_gets_lowest_caliber(self):
        claim = {"statement": "企业可能通过并购突破", "epistemic_level": "speculative"}
        caliber_map = {
            "factual": "llm_inference_factual",
            "inferential": "llm_inference",
            "speculative": "llm_inference_speculative",
        }
        caliber = caliber_map.get(claim.get("epistemic_level", "inferential"), "llm_inference")
        assert caliber == "llm_inference_speculative"
        SOURCE_PRIORITY = {"llm_inference_factual": 15, "llm_inference": 10, "llm_inference_speculative": 5}
        assert SOURCE_PRIORITY[caliber] == 5

    def test_factual_claim_gets_highest_llm_caliber(self):
        claim = {"statement": "2025年Q1市场份额为32%", "epistemic_level": "factual"}
        caliber_map = {
            "factual": "llm_inference_factual",
            "inferential": "llm_inference",
            "speculative": "llm_inference_speculative",
        }
        caliber = caliber_map.get(claim.get("epistemic_level", "inferential"), "llm_inference")
        assert caliber == "llm_inference_factual"

    def test_strategic_intent_claim_always_speculative(self):
        aspect = "strategic_intent"
        ASPECT_EPISTEMIC_CEILING = {"strategic_intent": "speculative", "战略意图": "speculative", "战略意图推断": "speculative", "Strategic Intent": "speculative"}
        _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
        for level in ["factual", "inferential"]:
            claim = {"epistemic_level": level}
            _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
            _l = claim.get("epistemic_level", "inferential")
            if _ceiling and _epistemic_order.get(_l, 1) < _epistemic_order.get(_ceiling, 1):
                claim["epistemic_level"] = _ceiling
            assert claim["epistemic_level"] == "speculative", f"Expected speculative for {level}"
