"""
Phase 3: E2E Report Quality Evaluation
Evaluate existing reports and run minimal real test
"""
import asyncio
import os
import sys
import json
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


def evaluate_report(report_data):
    scores = {}
    issues = []

    data = report_data.get("result", {}).get("data", {})
    if not data:
        return {"error": "No report data"}

    stats = report_data.get("result", {}).get("stats", {})
    sources = report_data.get("result", {}).get("sources", [])

    total_content = ""
    section_count = 0
    for key, content in data.items():
        if isinstance(content, str):
            total_content += content
            section_count += 1

    word_count = len(total_content)
    source_count = stats.get("total_sources", len(sources))
    agent_count = stats.get("total_agents", 0)

    # 1. Data Quality (0-100)
    data_score = min(100, source_count * 2)
    if source_count >= 30:
        data_score = 80
    if source_count >= 50:
        data_score = 90
    if source_count >= 70:
        data_score = 95

    # Check for cross-validation markers
    cross_val_count = total_content.count("交叉验证") + total_content.count("来源") + total_content.count("据")
    if cross_val_count > 10:
        data_score = min(100, data_score + 5)

    scores["data_quality"] = data_score

    # 2. Content Depth (0-100)
    depth_score = 50
    if word_count > 10000:
        depth_score += 10
    if word_count > 20000:
        depth_score += 10
    if word_count > 30000:
        depth_score += 5

    # Check for analytical depth markers
    depth_markers = [
        "原创洞察", "核心判断", "关键洞察", "专业洞察",
        "CAGR", "渗透率", "市占率", "集中度",
        "SWOT", "波特五力", "PEST", "产业链",
        "风险", "不确定", "假设",
    ]
    marker_hits = sum(1 for m in depth_markers if m in total_content)
    depth_score += min(20, marker_hits * 2)

    # Check for quantitative data
    import re
    number_patterns = re.findall(r'\d+\.?\d*[亿万千万]', total_content)
    depth_score += min(10, len(number_patterns))

    scores["content_depth"] = min(100, depth_score)

    # 3. Structural Completeness (0-100)
    struct_score = 50
    if section_count >= 3:
        struct_score += 15
    if section_count >= 5:
        struct_score += 10
    if "执行摘要" in data:
        struct_score += 10
    if "研究结论" in data:
        struct_score += 10
    if any("市场" in k for k in data.keys()):
        struct_score += 5
    scores["structural_completeness"] = min(100, struct_score)

    # 4. Professional Level (0-100)
    prof_score = 50
    prof_markers = ["CAGR", "渗透率", "CR5", "HHI", "同比", "环比", "复合增长率"]
    prof_hits = sum(1 for m in prof_markers if m in total_content)
    prof_score += min(20, prof_hits * 3)

    # Source citation quality
    citation_markers = re.findall(r'【来源[:：].*?】', total_content)
    prof_score += min(15, len(citation_markers))

    # Professional frameworks
    framework_markers = ["Porter", "SWOT", "PEST", "波特", "五力", "护城河"]
    framework_hits = sum(1 for m in framework_markers if m in total_content)
    prof_score += min(15, framework_hits * 3)

    scores["professional_level"] = min(100, prof_score)

    # 5. Logic & Consistency (0-100)
    logic_score = 70  # Base score
    # Check for contradiction markers
    contradiction_markers = ["矛盾", "不一致", "冲突"]
    contradiction_count = sum(1 for m in contradiction_markers if m in total_content)
    if contradiction_count > 0:
        logic_score -= 5

    # Check for causal reasoning
    causal_markers = ["因此", "导致", "驱动", "推动", "拉动"]
    causal_count = sum(1 for m in causal_markers if m in total_content)
    logic_score += min(15, causal_count * 2)

    scores["logic_consistency"] = min(100, logic_score)

    # Overall score
    weights = {
        "data_quality": 0.25,
        "content_depth": 0.25,
        "structural_completeness": 0.15,
        "professional_level": 0.20,
        "logic_consistency": 0.15,
    }
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 1)

    return {
        "scores": scores,
        "metrics": {
            "word_count": word_count,
            "section_count": section_count,
            "source_count": source_count,
            "agent_count": agent_count,
            "cross_val_markers": cross_val_count,
            "depth_markers": marker_hits,
            "quantitative_data_points": len(number_patterns),
            "citation_count": len(citation_markers),
        },
        "sections": list(data.keys()),
    }


def main():
    from pathlib import Path

    print("=" * 70)
    print("Zensers Report Quality Evaluation")
    print("=" * 70)

    reports_dir = Path("output/reports")
    json_files = sorted(reports_dir.glob("research_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    results = []
    for jf in json_files[:5]:
        try:
            data = json.loads(jf.read_text(encoding='utf-8'))
            topic = data.get("topic", "Unknown")
            print(f"\n--- Evaluating: {jf.stem} | {topic} ---")

            eval_result = evaluate_report(data)
            eval_result["file"] = jf.name
            eval_result["topic"] = topic

            scores = eval_result.get("scores", {})
            metrics = eval_result.get("metrics", {})
            print(f"  Word count: {metrics.get('word_count', 0):,}")
            print(f"  Sections: {metrics.get('section_count', 0)}")
            print(f"  Sources: {metrics.get('source_count', 0)}")
            print(f"  Data Quality: {scores.get('data_quality', 0)}/100")
            print(f"  Content Depth: {scores.get('content_depth', 0)}/100")
            print(f"  Structural: {scores.get('structural_completeness', 0)}/100")
            print(f"  Professional: {scores.get('professional_level', 0)}/100")
            print(f"  Logic: {scores.get('logic_consistency', 0)}/100")
            print(f"  OVERALL: {scores.get('overall', 0)}/100")
            print(f"  Sections: {eval_result.get('sections', [])}")

            results.append(eval_result)
        except Exception as e:
            print(f"  Error evaluating {jf.name}: {e}")

    summary = {
        "evaluation_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reports_evaluated": len(results),
        "results": results,
    }

    summary_path = Path("output/e2e_test/quality_evaluation.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nEvaluation saved to: {summary_path}")

    if results:
        avg_scores = {}
        for key in ["data_quality", "content_depth", "structural_completeness", "professional_level", "logic_consistency", "overall"]:
            vals = [r["scores"][key] for r in results if key in r.get("scores", {})]
            avg_scores[key] = round(sum(vals) / len(vals), 1) if vals else 0
        print(f"\nAverage Scores ({len(results)} reports):")
        for k, v in avg_scores.items():
            print(f"  {k}: {v}/100")


if __name__ == '__main__':
    main()
