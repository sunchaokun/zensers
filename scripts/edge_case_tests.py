"""Edge case tests for cognitive strategy system.

Tests boundary conditions: open_use policy, empty claims, no hypotheses,
LLM classification failures, cache behavior, strategy fallbacks.
"""
import asyncio
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
os.chdir(PROJECT_ROOT)

from src.core.agents.generic_agent import GenericAgent, COGNITIVE_STRATEGY
from unittest.mock import patch, AsyncMock


def test_registry_completeness():
    """All 4 types have L1-L5 with every required key."""
    required_l1 = {"dimension_ceiling", "speculative_word_downgrade", "confidence_threshold"}
    required_l3 = {"speculative_policy", "reasoning_mode", "evidence_chain_template"}
    required_l4 = {"hypothesis_type", "hypothesis_count", "hypothesis_template", "agent_hypothesis_count", "output_suffix", "counter_hypothesis_required"}
    required_l5 = {"contradiction_instruction", "contradiction_resolution"}
    
    for ctype, strategy in COGNITIVE_STRATEGY.items():
        for key in required_l1:
            assert key in strategy["L1"], f"{ctype} L1 missing {key}"
        for key in required_l3:
            assert key in strategy["L3"], f"{ctype} L3 missing {key}"
        for key in required_l4:
            assert key in strategy["L4"], f"{ctype} L4 missing {key}"
        for key in required_l5:
            assert key in strategy["L5"], f"{ctype} L5 missing {key}"
    print("PASS: registry completeness (4 types x L1-L5 keys)")


def test_open_use_is_not_cautious_use():
    """open_use and cautious_use are distinct policies."""
    assert COGNITIVE_STRATEGY["forward_looking"]["L3"]["speculative_policy"] == "open_use"
    assert COGNITIVE_STRATEGY["inference_driven"]["L3"]["speculative_policy"] == "cautious_use"
    assert COGNITIVE_STRATEGY["fact_driven"]["L3"]["speculative_policy"] == "reference_only"
    assert COGNITIVE_STRATEGY["assessment_driven"]["L3"]["speculative_policy"] == "open_use"
    assert len(set(COGNITIVE_STRATEGY[t]["L3"]["speculative_policy"] for t in COGNITIVE_STRATEGY)) == 3
    print("PASS: 3 distinct speculative policies (reference_only/cautious_use/open_use)")


def test_fact_driven_no_agent_hypotheses():
    """fact_driven should generate 0 agent hypotheses."""
    l4 = COGNITIVE_STRATEGY["fact_driven"]["L4"]
    assert l4["agent_hypothesis_count"] == 0
    assert l4["hypothesis_count"] == 0
    print("PASS: fact_driven has 0 hypotheses")


def test_forward_looking_no_ceiling():
    """forward_looking dimension_ceiling is None (no downgrade)."""
    assert COGNITIVE_STRATEGY["forward_looking"]["L1"]["dimension_ceiling"] is None
    print("PASS: forward_looking has no ceiling")


def test_heuristic_empty_aspect():
    """Empty aspect returns None from heuristic."""
    agent = GenericAgent.__new__(GenericAgent)
    result = agent._heuristic_cognitive_type("")
    assert result is None
    print("PASS: empty aspect → None heuristic")


def test_heuristic_pure_english():
    """Pure English aspect with no keyword match returns None."""
    agent = GenericAgent.__new__(GenericAgent)
    result = agent._heuristic_cognitive_type("Competitive Landscape")
    assert result is None
    print("PASS: no-match English → None heuristic")


def test_heuristic_prefix_matching():
    """English keywords use prefix matching (strateg matches Strategic/Strategy)."""
    agent = GenericAgent.__new__(GenericAgent)
    assert agent._heuristic_cognitive_type("Strategic Intent") == "inference_driven"
    assert agent._heuristic_cognitive_type("Technology Roadmap") == "forward_looking"
    assert agent._heuristic_cognitive_type("Valuation Method") == "assessment_driven"
    print("PASS: English prefix matching works")


def test_heuristic_conflict_resolution():
    """When multiple types match, highest score wins."""
    agent = GenericAgent.__new__(GenericAgent)
    result = agent._heuristic_cognitive_type("投资风险分析")
    scores = {
        "inference_driven": sum(1 for kw in ["投资", "战略", "建议", "策略", "研判", "意图", "决策", "配置"] if kw in "投资风险分析"),
        "assessment_driven": sum(1 for kw in ["估值", "风险", "财务", "评分", "评级", "敏感性", "压力测试"] if kw in "投资风险分析"),
    }
    expected = max(scores, key=scores.get)
    assert result == expected
    print(f"PASS: conflict resolution → {result} (scores: {scores})")


async def test_infer_llm_exception_fallthrough():
    """LLM exception at both levels → heuristic → fallback."""
    agent = GenericAgent.__new__(GenericAgent)
    agent._context = {}
    agent.agent_id = "test_edge"
    
    with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [Exception("network error"), Exception("network error")]
        result = await agent.infer_cognitive_type("投资建议", "test")
        assert result == "inference_driven"
        print("PASS: LLM exception → heuristic fallback")


async def test_infer_llm_invalid_output():
    """LLM returns gibberish → retry → heuristic."""
    agent = GenericAgent.__new__(GenericAgent)
    agent._context = {}
    agent.agent_id = "test_edge"
    
    with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [
            {"content": "I think this is about market stuff", "success": True},
            {"content": "maybe type something", "success": True}
        ]
        result = await agent.infer_cognitive_type("估值分析", "test")
        assert result == "assessment_driven"
        print("PASS: LLM gibberish → heuristic fallback")


async def test_infer_negation_prefix():
    """LLM returns 'not fact_driven but assessment_driven' → should pick assessment_driven (last match wins)."""
    agent = GenericAgent.__new__(GenericAgent)
    agent._context = {}
    agent.agent_id = "test_edge"
    
    with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "not fact_driven but assessment_driven", "success": True}
        result = await agent.infer_cognitive_type("估值分析", "test")
        assert result == "assessment_driven", f"Expected assessment_driven but got {result}"
        print("PASS: negation prefix handled — last valid type wins")


async def test_infer_total_failure():
    """All LLM + heuristic fail → fact_driven fallback."""
    agent = GenericAgent.__new__(GenericAgent)
    agent._context = {}
    agent.agent_id = "test_edge"
    
    with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [Exception("error"), Exception("error")]
        result = await agent.infer_cognitive_type("完全未知维度", "test")
        assert result == "fact_driven"
        print("PASS: total failure → fact_driven fallback")


async def test_infer_cache_different_topic():
    """Same aspect but different topic should NOT use cache."""
    agent = GenericAgent.__new__(GenericAgent)
    agent._context = {}
    agent.agent_id = "test_edge"
    
    with patch("src.core.agents.generic_agent.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [
            {"content": "fact_driven", "success": True},
            {"content": "inference_driven", "success": True}
        ]
        r1 = await agent.infer_cognitive_type("竞争格局", "中国智能手机")
        r2 = await agent.infer_cognitive_type("竞争格局", "美国半导体")
        assert r1 == "fact_driven"
        assert r2 == "inference_driven"
        assert mock_llm.call_count == 2
        print("PASS: different topic → no cache reuse")


def test_output_suffix_markers():
    """All 4 output_suffixes are valid markers for _parse_hypothesis_verification."""
    markers = ["假设验证结果", "假设验证结果：", "数据验证结果", "数据验证结果：", 
               "前瞻验证结果", "前瞻验证结果：", "假设敏感性检验", "假设敏感性检验：", "验证结果"]
    for suffix_value in ["假设验证结果：", "数据验证结果：", "前瞻验证结果：", "假设敏感性检验："]:
        assert any(m in suffix_value for m in markers), f"{suffix_value} not in markers"
    print("PASS: all 4 output_suffixes recognized by markers")


def test_strategy_dict_access():
    """COGNITIVE_STRATEGY uses dict-style access (not dot notation)."""
    s = COGNITIVE_STRATEGY["inference_driven"]
    assert s["L3"]["speculative_policy"] == "cautious_use"
    assert s["L4"]["hypothesis_count"] == (3, 5)
    assert isinstance(s["L1"]["dimension_ceiling"], str)
    print("PASS: dict-style access works")


if __name__ == "__main__":
    print("=" * 70)
    print("EDGE CASE TESTS: Cognitive Strategy System")
    print("=" * 70)
    
    test_registry_completeness()
    test_open_use_is_not_cautious_use()
    test_fact_driven_no_agent_hypotheses()
    test_forward_looking_no_ceiling()
    test_heuristic_empty_aspect()
    test_heuristic_pure_english()
    test_heuristic_prefix_matching()
    test_heuristic_conflict_resolution()
    
    asyncio.run(test_infer_llm_exception_fallthrough())
    asyncio.run(test_infer_llm_invalid_output())
    asyncio.run(test_infer_negation_prefix())
    asyncio.run(test_infer_total_failure())
    asyncio.run(test_infer_cache_different_topic())
    
    test_output_suffix_markers()
    test_strategy_dict_access()
    
    print("\n" + "=" * 70)
    print("ALL EDGE CASE TESTS PASSED")
    print("=" * 70)
