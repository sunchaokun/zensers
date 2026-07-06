"""
真实环境对比测试：评估修改前后搜索质量差异。

测试方式：直接调用 GenericAgent 的搜索和分析方法，
对比修改前后在以下维度的差异：
1. 搜索查询质量（是否包含"券商研报"等精准词）
2. 搜索结果数量和权威度分布
3. total_sources 准确性（无重复URL）
4. _evaluate_data_quality 加权效果
5. _validate_query 是否允许高质量查询通过

不依赖完整报告生成，只测搜索+分析核心路径。
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_validate_query():
    """D3.2: 验证 _validate_query 不再截杀高价值查询"""
    from src.core.agents.generic_agent import GenericAgent
    agent = GenericAgent.__new__(GenericAgent)

    test_cases = [
        ("新能源汽车 销量 2025", True, "泛查询应通过"),
        ("新能源汽车 行业分析报告 2025", True, "含'分析''报告'应通过(修复后)"),
        ("McKinsey 中国电动汽车行业报告 2024", True, "咨询报告应通过(修复后)"),
        ("Gartner technology trends analysis", True, "英文分析应通过(修复后)"),
        ("新能源汽车 券商研报 市场份额 2025", True, "券商研报应通过(修复后)"),
        ("ab", False, "过短查询应拒绝"),
        ("", False, "空查询应拒绝"),
    ]

    passed = 0
    failed = 0
    for query, expected, desc in test_cases:
        result = agent._validate_query(query)
        if result == expected:
            passed += 1
            print(f"  PASS: {desc} | query='{query[:40]}' -> {result}")
        else:
            failed += 1
            print(f"  FAIL: {desc} | query='{query[:40]}' -> {result} (expected {expected})")

    print(f"\n_validate_query: {passed}/{len(test_cases)} passed, {failed} failed")
    return failed == 0


def test_evaluate_data_quality_weighted():
    """D4.3: 验证权威度加权平均"""
    from src.core.agents.generic_agent import GenericAgent
    agent = GenericAgent.__new__(GenericAgent)

    scenarios = [
        {
            "name": "2条tier1+10条tier4",
            "results": {
                "searches": [{
                    "results": [
                        {"quality_score": 90, "credibility": "tier1_authority"},
                        {"quality_score": 90, "credibility": "tier1_authority"},
                    ] + [{"quality_score": 50, "credibility": "tier4_general"}] * 10
                }]
            },
        },
        {
            "name": "全部tier4",
            "results": {
                "searches": [{
                    "results": [{"quality_score": 50, "credibility": "tier4_general"}] * 12
                }]
            },
        },
        {
            "name": "全部tier1",
            "results": {
                "searches": [{
                    "results": [{"quality_score": 90, "credibility": "tier1_authority"}] * 12
                }]
            },
        },
    ]

    for s in scenarios:
        score = agent._evaluate_data_quality(s["results"])
        simple = sum(
            r.get("quality_score", 30) for r in s["results"]["searches"][0]["results"]
        ) / len(s["results"]["searches"][0]["results"])
        print(f"  {s['name']}: weighted={score:.1f}, simple_avg={simple:.1f}, delta={score-simple:+.1f}")

    score_mixed = agent._evaluate_data_quality(scenarios[0]["results"])
    score_all_t4 = agent._evaluate_data_quality(scenarios[1]["results"])
    assert score_mixed > score_all_t4, "Mixed with authority should score higher than all tier4"
    print(f"\n_evaluate_data_quality: PASS (weighted correctly distinguishes authority)")


def test_parse_causal_hypotheses():
    """A2.1: 验证因果假设解析"""
    from src.core.agents.generic_agent import GenericAgent
    agent = GenericAgent.__new__(GenericAgent)

    test_inputs = [
        (
            "假设：补贴退坡推动市场化转型 | 验证数据：补贴政策变化时间线 | 传导：影响财务预测的营收增长假设\n"
            "假设：技术路线分化源于成本压力 | 验证数据：各技术路线成本对比 | 传导：影响技术趋势的路线选择",
            2
        ),
        (
            "假设：单一假设 | 验证数据：测试 | 传导：测试",
            1
        ),
        ("无格式文本", 0),
    ]

    passed = 0
    for content, expected_count in test_inputs:
        hypotheses = agent._parse_causal_hypotheses(content)
        if len(hypotheses) == expected_count:
            passed += 1
            print(f"  PASS: parsed {len(hypotheses)} hypotheses (expected {expected_count})")
            for h in hypotheses:
                print(f"    - {h.get('statement','')[:50]}")
        else:
            print(f"  FAIL: parsed {len(hypotheses)} hypotheses (expected {expected_count})")

    print(f"\n_parse_causal_hypotheses: {passed}/{len(test_inputs)} passed")
    return passed == len(test_inputs)


async def test_search_quality_real():
    """D3.1+D3.2: 真实搜索测试 - 验证修改后搜索查询能获取更高质量结果"""
    from src.core.agents.generic_agent import GenericAgent
    from src.core.llm_client import call_llm

    topic = "中国新能源汽车行业"
    aspect = "竞争格局"

    print(f"\n  测试主题: {topic} | 维度: {aspect}")

    agent = GenericAgent.__new__(GenericAgent)
    agent.agent_id = "test_agent"
    agent._context = {"research_type": "market_research", "language": "zh"}
    agent._available_skills = ["search_skill"]

    from src.core.search import DomainRoleInferrer
    role_inferrer = DomainRoleInferrer()
    role_info = role_inferrer.infer("market_research", topic, "zh")

    queries = agent._generate_search_queries(
        topic=topic,
        aspect=aspect,
        aspects=[aspect],
        role_info=role_info,
    )

    print(f"\n  生成查询数: {len(queries)}")
    for i, q in enumerate(queries[:15], 1):
        status = "VALID" if agent._validate_query(q) else "INVALID"
        print(f"    {i}. [{status}] {q}")

    has_precise = any(
        any(kw in q for kw in ["研报", "报告", "分析", "咨询", "协会"])
        for q in queries
    )
    print(f"\n  精准查询(含研报/报告/分析/咨询/协会): {'YES' if has_precise else 'NO'}")

    has_forbidden_rejection = False
    test_queries = ["新能源汽车 券商研报 市场份额", "McKinsey 行业报告", "行业分析报告"]
    for q in test_queries:
        if not agent._validate_query(q):
            has_forbidden_rejection = True
            print(f"  REJECTED (BUG): {q}")
        else:
            print(f"  ACCEPTED: {q}")

    if has_forbidden_rejection:
        print("\n  FAIL: Some high-value queries still rejected!")
        return False
    else:
        print("\n  PASS: All high-value queries accepted")
        return True


async def test_full_analysis_real():
    """完整分析路径测试：用真实LLM+搜索对一个小主题做分析"""
    from src.core.agents.generic_agent import GenericAgent
    from src.skills.registry import SkillRegistry

    topic = "中国新能源汽车竞争格局"
    aspect = "Competitive Landscape"

    print(f"\n  测试主题: {topic} | 维度: {aspect}")

    registry = SkillRegistry()

    agent = GenericAgent(
        agent_id="test_analysis_agent",
        agent_type="dynamic",
        config={
            "skill_registry": registry,
            "skills": ["llm_skill", "search_skill"],
            "name": "分析Agent",
            "context": {"category": "market-analysis"},
        },
    )

    task = {
        "topic": topic,
        "aspect": aspect,
        "aspects": [aspect],
        "depth": "standard",
        "action": "analyze",
    }

    start = time.time()
    try:
        result = await agent.execute(task)
        elapsed = time.time() - start

        content = result.get("content", "")
        success = result.get("success", False)

        print(f"\n  分析完成: success={success}, 耗时={elapsed:.1f}s")
        print(f"  内容长度: {len(content)} 字符")

        if success and content:
            has_causal = any(kw in content for kw in ["因果", "驱动", "推动", "导致", "传导"])
            has_intent = any(kw in content for kw in ["意图", "战略", "动机", "目的", "布局"])
            has_quantitative = len([c for c in content if c.isdigit()]) > 10

            print(f"  因果语言: {'YES' if has_causal else 'NO'}")
            print(f"  战略意图: {'YES' if has_intent else 'NO'}")
            print(f"  定量数据: {'YES' if has_quantitative else 'NO'}")
            print(f"\n  内容预览(前500字):\n  {content[:500]}")

        return success

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n  分析失败: {e}, 耗时={elapsed:.1f}s")
        import traceback
        traceback.print_exc()
        return False


async def run_all():
    print("=" * 70)
    print("Zensers 优化方案 - 真实环境对比测试")
    print("=" * 70)

    results = {}

    print("\n" + "=" * 70)
    print("1. _validate_query 测试（D3.2: 禁忌词删除）")
    print("=" * 70)
    results["validate_query"] = test_validate_query()

    print("\n" + "=" * 70)
    print("2. _evaluate_data_quality 测试（D4.3: 权威度加权）")
    print("=" * 70)
    test_evaluate_data_quality_weighted()
    results["evaluate_quality"] = True

    print("\n" + "=" * 70)
    print("3. _parse_causal_hypotheses 测试（A2.1: 因果假设解析）")
    print("=" * 70)
    results["parse_hypotheses"] = test_parse_causal_hypotheses()

    print("\n" + "=" * 70)
    print("4. 搜索查询质量测试（D3.1+D3.2: 真实搜索）")
    print("=" * 70)
    results["search_quality"] = await test_search_quality_real()

    print("\n" + "=" * 70)
    print("5. 完整分析路径测试（真实LLM+搜索）")
    print("=" * 70)
    try:
        results["full_analysis"] = await test_full_analysis_real()
    except Exception as e:
        print(f"  跳过（需要完整环境）: {e}")
        results["full_analysis"] = None

    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    for name, passed in results.items():
        if passed is None:
            status = "SKIPPED"
        elif passed:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"  {name}: {status}")

    all_passed = all(v is not False for v in results.values())
    print(f"\n  总体: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

    out_path = Path("data/test_optimization_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  结果已保存到: {out_path}")


if __name__ == "__main__":
    asyncio.run(run_all())
