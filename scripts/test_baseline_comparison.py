"""
基线对比测试：用 git stash 切换原始代码 vs 修改后代码，
对比 _validate_query 和 _evaluate_data_quality 的行为差异。
"""
import subprocess
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_test_on_current(code_label):
    """在当前代码状态下运行测试，返回结果"""
    results = {}

    # Test 1: _validate_query
    from src.core.agents.generic_agent import GenericAgent
    agent = GenericAgent.__new__(GenericAgent)

    test_queries = [
        ("新能源汽车 行业分析报告 2025", "含'分析''报告'"),
        ("McKinsey 中国电动汽车行业报告 2024", "咨询报告"),
        ("新能源汽车 券商研报 市场份额 2025", "券商研报"),
        ("Gartner technology trends analysis", "英文分析"),
        ("新能源汽车 销量 2025", "泛查询"),
        ("ab", "过短"),
        ("", "空查询"),
    ]

    validate_results = {}
    for query, desc in test_queries:
        result = agent._validate_query(query)
        validate_results[desc] = result

    results["validate_query"] = validate_results

    # Test 2: _evaluate_data_quality - mixed authority vs all tier4
    scenarios = {
        "2tier1_10tier4": {
            "results": {"searches": [{
                "results": [
                    {"quality_score": 90, "credibility": "tier1_authority"},
                    {"quality_score": 90, "credibility": "tier1_authority"},
                ] + [{"quality_score": 50, "credibility": "tier4_general"}] * 10
            }]}
        },
        "all_tier4": {
            "results": {"searches": [{
                "results": [{"quality_score": 50, "credibility": "tier4_general"}] * 12
            }]}
        },
        "all_tier1": {
            "results": {"searches": [{
                "results": [{"quality_score": 90, "credibility": "tier1_authority"}] * 12
            }]}
        },
    }

    quality_results = {}
    for name, data in scenarios.items():
        score = agent._evaluate_data_quality(data)
        simple_avg = sum(
            r.get("quality_score", 30) for r in data["results"]["searches"][0]["results"]
        ) / len(data["results"]["searches"][0]["results"])
        quality_results[name] = {"weighted": round(score, 2), "simple_avg": round(simple_avg, 2)}

    results["evaluate_data_quality"] = quality_results

    # Test 3: Check if _parse_causal_hypotheses exists
    results["has_parse_causal_hypotheses"] = hasattr(agent, "_parse_causal_hypotheses")

    # Test 4: Check if _extract_claims_from_analysis exists
    results["has_extract_claims"] = hasattr(agent, "_extract_claims_from_analysis")

    # Test 5: Check ASPECT_SKILL_MAP for strategic_intent
    from src.core.decomposition.strategies import ASPECT_SKILL_MAP
    has_strategic_intent = any(
        "strategic_intent" in str(v) or "战略意图" in str(v)
        for v in ASPECT_SKILL_MAP.values()
    )
    results["has_strategic_intent_in_skill_map"] = has_strategic_intent

    # Test 6: Check industry_report.yaml for strategic_intent section
    import yaml
    yaml_path = Path(__file__).parent.parent / "config" / "templates" / "industry_report.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        template = yaml.safe_load(f)
    sections = template.get("sections", [])
    has_strategic_section = any(
        s.get("id") == "strategic_intent" or "战略意图" in str(s.get("name", ""))
        for s in sections
    )
    results["has_strategic_intent_section"] = has_strategic_section

    # Test 7: Check forbidden_words in _validate_query
    import inspect
    source = inspect.getsource(agent._validate_query)
    results["has_forbidden_words"] = "forbidden_words" in source

    # Test 8: Check _generate_smart_queries_with_llm prompt
    try:
        source = inspect.getsource(agent._generate_smart_queries_with_llm)
        results["prompt_has_精准"] = "精准" in source or "指定来源" in source
        results["prompt_has_禁止报告"] = "禁止报告" in source or "禁止分析" in source
    except Exception:
        results["prompt_has_精准"] = None
        results["prompt_has_禁止报告"] = None

    # Test 9: Check DEPENDENT_SECTIONS
    from src.core.decomposition.strategies import IndustryResearchStrategy
    dep_sections = IndustryResearchStrategy.DEPENDENT_SECTIONS
    results["dependent_sections_has_strategic"] = any(
        "strategic_intent" in str(s) or "战略意图" in str(s)
        for s in dep_sections
    )

    # Test 10: Check ASPECT_NAME_MAP
    from src.core.prompt_manager import ASPECT_NAME_MAP
    results["aspect_name_map_has_strategic"] = any(
        "战略意图" in str(v) or "strategic_intent" in str(k).lower()
        for k, v in ASPECT_NAME_MAP.items()
    )

    print(f"\n  [{code_label}] 测试完成")
    return results


def compare_results(baseline, modified):
    """对比基线和修改后的结果"""
    print("\n" + "=" * 70)
    print("基线 vs 修改后 对比报告")
    print("=" * 70)

    improvements = []
    regressions = []
    neutrals = []

    # 1. validate_query
    print("\n--- 1. _validate_query 行为变化 ---")
    for desc in baseline["validate_query"]:
        b = baseline["validate_query"][desc]
        m = modified["validate_query"][desc]
        if b != m:
            if not b and m:
                improvements.append(f"validate_query({desc}): BLOCKED -> ALLOWED")
                print(f"  [+] {desc}: BLOCKED -> ALLOWED")
            else:
                regressions.append(f"validate_query({desc}): {b} -> {m}")
                print(f"  [-] {desc}: {b} -> {m}")
        else:
            neutrals.append(f"validate_query({desc}): {b}")
            print(f"  =  {desc}: {b} (无变化)")

    # 2. evaluate_data_quality
    print("\n--- 2. _evaluate_data_quality 权威度加权效果 ---")
    for name in baseline["evaluate_data_quality"]:
        b = baseline["evaluate_data_quality"][name]
        m = modified["evaluate_data_quality"][name]
        delta = m["weighted"] - b["weighted"]
        simple_delta = m["weighted"] - m["simple_avg"]
        if delta != 0:
            improvements.append(f"evaluate_quality({name}): weighted {b['weighted']} -> {m['weighted']} (delta={delta:+.1f})")
        print(f"  {name}: baseline_weighted={b['weighted']}, modified_weighted={m['weighted']}, delta={delta:+.1f}, vs_simple_avg={simple_delta:+.1f}")

    # 3-10. Feature additions
    feature_checks = [
        ("has_parse_causal_hypotheses", "因果假设解析"),
        ("has_extract_claims", "声明提取"),
        ("has_strategic_intent_in_skill_map", "战略意图技能映射"),
        ("has_strategic_intent_section", "战略意图报告章节"),
        ("has_forbidden_words", "禁忌词过滤(应为消除)"),
        ("prompt_has_精准", "精准查询提示"),
        ("prompt_has_禁止报告", "禁止报告提示(应为消除)"),
        ("dependent_sections_has_strategic", "战略意图依赖关系"),
        ("aspect_name_map_has_strategic", "战略意图名称映射"),
    ]

    print("\n--- 3. 新功能/消除项 ---")
    for key, label in feature_checks:
        b = baseline.get(key)
        m = modified.get(key)
        if b != m:
            if key == "has_forbidden_words":
                if b and not m:
                    improvements.append(f"{label}: exist -> removed (expected)")
                    print(f"  [+] {label}: exist -> removed (D3.2)")
                elif not b and m:
                    regressions.append(f"{label}: removed -> exist (unexpected)")
                    print(f"  [-] {label}: removed -> exist (unexpected)")
            elif key == "prompt_has_禁止报告":
                if b and not m:
                    improvements.append(f"{label}: exist -> removed (expected)")
                    print(f"  [+] {label}: exist -> removed (D3.1)")
            elif not b and m:
                improvements.append(f"{label}: none -> has (new)")
                print(f"  [+] {label}: none -> has (new feature)")
            else:
                neutrals.append(f"{label}: {b} -> {m}")
                print(f"  =  {label}: {b} -> {m}")
        else:
            neutrals.append(f"{label}: {b}")
            print(f"  =  {label}: {b} (无变化)")

    print("\n" + "=" * 70)
    print(f"汇总: {len(improvements)} 项改进, {len(regressions)} 项回归, {len(neutrals)} 项无变化")
    print("=" * 70)

    if improvements:
        print("\nImprovements:")
        for imp in improvements:
            print(f"  [+] {imp}")
    if regressions:
        print("\nRegressions:")
        for reg in regressions:
            print(f"  [-] {reg}")

    return {"improvements": improvements, "regressions": regressions, "neutrals": neutrals}


def main():
    print("=" * 70)
    print("基线对比测试：原始代码 vs 修改后代码")
    print("=" * 70)

    results_dir = Path("data/baseline_comparison")
    results_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Run on MODIFIED code (current state)
    print("\n>>> 阶段1: 在修改后代码上运行测试")
    try:
        modified_results = run_test_on_current("MODIFIED")
        with open(results_dir / "modified_results.json", "w", encoding="utf-8") as f:
            json.dump(modified_results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  修改后代码测试失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 2: Stash changes, run on ORIGINAL code
    print("\n>>> 阶段2: 暂存修改，在原始代码上运行测试")
    try:
        subprocess.run(["git", "stash", "--include-untracked"], check=True, capture_output=True)
        print("  git stash 完成")

        # Need to reimport
        import importlib
        import src.core.agents.generic_agent
        import src.core.decomposition.strategies
        import src.core.prompt_manager
        importlib.reload(src.core.agents.generic_agent)
        importlib.reload(src.core.decomposition.strategies)
        importlib.reload(src.core.prompt_manager)

        baseline_results = run_test_on_current("BASELINE")
        with open(results_dir / "baseline_results.json", "w", encoding="utf-8") as f:
            json.dump(baseline_results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  原始代码测试失败: {e}")
        import traceback
        traceback.print_exc()
        # Restore changes even on failure
        subprocess.run(["git", "stash", "pop"], capture_output=True)
        return
    finally:
        # Always restore changes
        print("\n>>> 恢复修改后代码")
        result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True)
        if result.returncode == 0:
            print("  git stash pop 完成")
        else:
            print(f"  git stash pop 失败: {result.stderr}")

    # Step 3: Compare
    comparison = compare_results(baseline_results, modified_results)

    with open(results_dir / "comparison.json", "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    print(f"\n对比结果已保存到: {results_dir}")


if __name__ == "__main__":
    main()
