"""
Epistemic Defense A/B Evaluation: 报告质量影响评估

评估认知防御系统对最终报告质量的影响：
- A组（无防御）: 跨维度claims不分层级，全部以"其他维度最新结论"注入
- B组（有防御）: L3分层注入 + L5矛盾检测 + L4假设验证

评估维度：
1. 推测性结论引用率: 推测性claim被当作结论依据的频率（越低越好）
2. 矛盾处理率: 检测到矛盾后报告是否主动处理（越高越好）
3. 认知透明度: 推断性结论是否标注来源和前提（越高越好）
4. 事实准确率: 事实性claim是否被正确引用（越高越好）
5. 假设验证率: 假设是否被验证/修正/推翻（越高越好）
"""
import asyncio
import json
import os
import re
import sys
import time
import logging

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from src.core.llm_client import call_llm

# ================================================================
# 跨维度claims数据集（模拟3个维度已完成分析后的claims）
# ================================================================

CROSS_DIMENSION_CLAIMS = [
    # 竞争格局 - factual
    {"statement": "2025年Q1华为智能手机市场份额32%，苹果28%", "confidence": "HIGH",
     "前提条件": "IDC数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual",
     "falsification": "IDC修正数据时", "source_aspect": "竞争格局"},
    # 竞争格局 - inferential
    {"statement": "华为份额从35%降至32%暗示高端市场竞争加剧", "confidence": "MEDIUM",
     "前提条件": "份额数据准确且趋势持续", "cross_impact": ["战略意图"], "epistemic_level": "inferential",
     "falsification": "若份额下降由行业整体萎缩导致而非竞争加剧", "source_aspect": "竞争格局"},
    # 竞争格局 - speculative
    {"statement": "头部企业可能通过并购或技术整合寻求突破", "confidence": "LOW",
     "前提条件": "行业整合趋势持续", "cross_impact": ["投资建议"], "epistemic_level": "speculative",
     "falsification": "若未来6个月无并购公告则推断不成立", "source_aspect": "竞争格局"},
    # 市场规模 - factual
    {"statement": "2025年Q1中国智能手机出货量6800万台，同比下降8.2%", "confidence": "HIGH",
     "前提条件": "IDC数据准确", "cross_impact": ["风险分析"], "epistemic_level": "factual",
     "falsification": "数据源修正时", "source_aspect": "市场规模"},
    # 市场规模 - inferential
    {"statement": "5G换机潮推动市场但消费降级压力导致增速放缓", "confidence": "MEDIUM",
     "前提条件": "换机周期数据和宏观经济数据准确", "cross_impact": ["行业趋势"], "epistemic_level": "inferential",
     "falsification": "若消费信心指数回升则增速可能超预期", "source_aspect": "市场规模"},
    # 市场规模 - speculative
    {"statement": "如果宏观经济持续承压，市场规模可能进一步萎缩", "confidence": "LOW",
     "前提条件": "宏观压力持续", "cross_impact": ["风险分析"], "epistemic_level": "speculative",
     "falsification": "若Q2-Q3出现反弹迹象则不成立", "source_aspect": "市场规模"},
    # 行业趋势 - factual
    {"statement": "AI手机成为2025年最显著技术趋势，华为小米均搭载端侧大模型", "confidence": "HIGH",
     "前提条件": "产品发布数据准确", "cross_impact": ["竞争格局"], "epistemic_level": "factual",
     "falsification": "若产品发布信息虚假", "source_aspect": "行业趋势"},
    # 行业趋势 - speculative
    {"statement": "AI手机可能催生AI服务订阅新商业模式", "confidence": "LOW",
     "前提条件": "商业模式创新可行性", "cross_impact": ["投资建议"], "epistemic_level": "speculative",
     "falsification": "若18个月内无主流厂商推出AI订阅服务则推断不成立", "source_aspect": "行业趋势"},
    # 风险分析 - factual
    {"statement": "台积电3nm产能利用率达95%，芯片供应不确定性增加", "confidence": "HIGH",
     "前提条件": "台积电产能数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual",
     "falsification": "台积电产能数据修正时", "source_aspect": "风险分析"},
    # 风险分析 - speculative（与市场规模factual矛盾）
    {"statement": "中美贸易摩擦升级可能导致芯片禁运加剧", "confidence": "LOW",
     "前提条件": "贸易摩擦持续升级", "cross_impact": ["市场规模", "战略意图"], "epistemic_level": "speculative",
     "falsification": "若6个月内无新的禁令公告则风险评估需下调", "source_aspect": "风险分析"},
    # 战略意图 - inferential
    {"statement": "华为在芯片领域的持续投入暗示其寻求技术自主的战略意图", "confidence": "MEDIUM",
     "前提条件": "产品迭代数据和供应链信息准确", "cross_impact": ["竞争格局"], "epistemic_level": "inferential",
     "falsification": "若华为转向采购外部芯片则推断不成立", "source_aspect": "战略意图"},
    # 战略意图 - speculative
    {"statement": "小米可能通过生态整合寻求差异化竞争", "confidence": "LOW",
     "前提条件": "MIUI向HyperOS转型暗示意图", "cross_impact": ["行业趋势"], "epistemic_level": "speculative",
     "falsification": "若小米放弃HyperOS生态战略则推断不成立", "source_aspect": "战略意图"},
]

CONTRADICTION_PAIR = {
    "contradiction": "方向矛盾: 市场规模同比下降8.2% vs 市场规模可能进一步萎缩",
    "claims": ["2025年Q1中国智能手机出货量6800万台，同比下降8.2%", "如果宏观经济持续承压，市场规模可能进一步萎缩"]
}

CAUSAL_HYPOTHESES = [
    {"statement": "芯片供应紧张导致出货量下降", "verification_data": "供应链数据和出货量数据", "transmission": "风险分析→市场规模"},
    {"statement": "AI手机普及推动换机需求", "verification_data": "AI手机销量和换机周期数据", "transmission": "行业趋势→市场规模"},
]

# ================================================================
# Prompt构建
# ================================================================

def build_no_defense_prompt(topic, aspect):
    """A组：无防御 — 所有claims以'其他维度最新结论'平铺注入"""
    parts = [
        f"你是一位行业研究分析师，正在分析{topic}的{aspect}维度。",
        "",
        "## 其他维度最新结论",
    ]
    for c in CROSS_DIMENSION_CLAIMS:
        parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']})")
    
    parts.extend([
        "",
        "请基于以上信息，撰写详细的维度分析报告。要求：",
        "1. 综合所有维度信息给出你的分析结论",
        "2. 明确指出关键趋势和风险",
        "3. 给出你的判断和建议",
    ])
    return "\n".join(parts)


def build_with_defense_prompt(topic, aspect):
    """B组：有防御 — L3分层注入 + L5矛盾 + L4假设验证"""
    parts = [
        f"你是一位行业研究分析师，正在分析{topic}的{aspect}维度。",
    ]
    
    factual = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "factual"]
    inferential = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "inferential"]
    speculative = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "speculative"]
    
    if factual:
        parts.append("\n### 其他维度已确认发现（可直接引用）")
        for c in factual:
            parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']})")
    
    if inferential:
        parts.append("\n### 其他维度推断结论（需验证后引用）")
        for c in inferential:
            parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 前提: {c.get('前提条件','未指定')})")
        parts.append("\n**要求**: 引用推断性结论时需注明'根据XX维度推断'。")
    
    if speculative:
        parts.append("\n### 其他维度推测性观点（仅供参考，不得作为结论依据）")
        for c in speculative:
            parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 证伪条件: {c.get('falsification','未指定')})")
        parts.append("\n**要求**: 推测性观点不得作为你的结论依据，仅可作为分析思路参考。如果你掌握可以证伪某推测性观点的数据，必须在分析中明确指出。")
    
    # L3-D: 矛盾注入
    parts.append("\n### 已检测到跨维度矛盾")
    parts.append(f"  - 矛盾类型: {CONTRADICTION_PAIR['contradiction']}")
    parts.append(f"    涉及结论: {CONTRADICTION_PAIR['claims']}")
    parts.append("\n**要求**: 如果你的分析与上述矛盾相关，必须给出你的判断和依据。")
    
    # L4: 假设验证
    parts.append("\n### 因果假设（必须验证或修正）")
    for i, h in enumerate(CAUSAL_HYPOTHESES, 1):
        parts.append(f"  {i}. {h['statement']}")
        parts.append(f"     验证数据需求：{h['verification_data']}")
        parts.append(f"     跨维度传导：{h['transmission']}")
    parts.append("\n**要求**：你的分析必须对每个假设给出「验证」「修正」或「推翻」的判断。")
    
    parts.extend([
        "",
        "请基于以上信息，撰写详细的维度分析报告。要求：",
        "1. 综合所有维度信息给出你的分析结论",
        "2. 明确指出关键趋势和风险",
        "3. 给出你的判断和建议",
    ])
    return "\n".join(parts)


# ================================================================
# 质量评估
# ================================================================

SPECULATIVE_STATEMENTS = [c["statement"] for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "speculative"]
INFERENTIAL_STATEMENTS = [c["statement"] for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "inferential"]
FACTUAL_STATEMENTS = [c["statement"] for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "factual"]


def evaluate_report(report_text, group_label):
    """评估报告质量，返回各项指标"""
    results = {}
    
    # 1. 推测性结论引用率: 推测性claim被当作结论依据的频率
    # 检查推测性观点是否出现在结论性语句中（"因此"/"所以"/"结论是"/"表明"后面跟推测性内容）
    speculative_as_conclusion = 0
    conclusion_patterns = ["因此", "所以", "结论是", "表明", "说明", "可见", "证明"]
    for stmt in SPECULATIVE_STATEMENTS:
        short_stmt = stmt[:15]
        if short_stmt in report_text:
            for pattern in conclusion_patterns:
                if pattern in report_text:
                    idx = report_text.find(short_stmt)
                    context_before = report_text[max(0, idx-50):idx]
                    if pattern in context_before:
                        speculative_as_conclusion += 1
                        break
    results["speculative_as_conclusion_count"] = speculative_as_conclusion
    results["speculative_as_conclusion_rate"] = speculative_as_conclusion / max(len(SPECULATIVE_STATEMENTS), 1)
    
    # 2. 矛盾处理率: 报告是否主动处理矛盾
    contradiction_keywords = ["矛盾", "不一致", "相反", "冲突", "对立", "需判断", "综合判断", "权衡"]
    results["contradiction_addressed"] = any(kw in report_text for kw in contradiction_keywords)
    
    # 3. 认知透明度: 推断性结论是否标注来源
    source_annotations = 0
    for stmt in INFERENTIAL_STATEMENTS:
        short_stmt = stmt[:15]
        if short_stmt in report_text:
            idx = report_text.find(short_stmt)
            context = report_text[max(0, idx-80):idx+len(stmt)]
            if any(src in context for src in ["根据", "推断", "维度推断", "前提", "假设"]):
                source_annotations += 1
    results["source_annotation_count"] = source_annotations
    results["source_annotation_rate"] = source_annotations / max(len(INFERENTIAL_STATEMENTS), 1)
    
    # 4. 事实准确率: 事实性claim是否被正确引用
    factual_cited = 0
    for stmt in FACTUAL_STATEMENTS:
        short_stmt = stmt[:20]
        if short_stmt in report_text:
            factual_cited += 1
    results["factual_cited_count"] = factual_cited
    results["factual_cited_rate"] = factual_cited / max(len(FACTUAL_STATEMENTS), 1)
    
    # 5. 假设验证率: 假设是否被验证/修正/推翻
    verification_keywords = ["验证", "修正", "推翻", "确认", "否定", "部分成立"]
    hypothesis_verified = 0
    for h in CAUSAL_HYPOTHESES:
        short_h = h["statement"][:15]
        if short_h in report_text:
            idx = report_text.find(short_h)
            context_after = report_text[idx:idx+200]
            if any(kw in context_after for kw in verification_keywords):
                hypothesis_verified += 1
    results["hypothesis_verified_count"] = hypothesis_verified
    results["hypothesis_verified_rate"] = hypothesis_verified / max(len(CAUSAL_HYPOTHESES), 1)
    
    # 6. 推测性观点标注率: 推测性内容是否被标注为推测
    speculative_labeled = 0
    speculative_label_keywords = ["推测", "可能", "预期", "假设", "仅供参考", "尚无定论", "不确定", "待验证"]
    for stmt in SPECULATIVE_STATEMENTS:
        short_stmt = stmt[:15]
        if short_stmt in report_text:
            idx = report_text.find(short_stmt)
            context = report_text[max(0, idx-60):idx+len(stmt)+60]
            if any(kw in context for kw in speculative_label_keywords):
                speculative_labeled += 1
    results["speculative_labeled_count"] = speculative_labeled
    results["speculative_labeled_rate"] = speculative_labeled / max(len(SPECULATIVE_STATEMENTS), 1)
    
    # 7. 证伪条件提及率
    falsification_mentioned = 0
    for c in CROSS_DIMENSION_CLAIMS:
        falsif = c.get("falsification", "")
        if falsif and falsif[:10] in report_text:
            falsification_mentioned += 1
    results["falsification_mentioned_count"] = falsification_mentioned
    
    # 8. 报告长度
    results["report_length"] = len(report_text)
    
    return results


# ================================================================
# LLM评估（用LLM评估报告质量）
# ================================================================

async def llm_evaluate_report(report_text, group_label):
    """用LLM评估报告的认知严谨性"""
    prompt = (
        "请评估以下行业分析报告的认知严谨性，按1-5分打分（5分最好）。\n\n"
        "评估标准：\n"
        "1. 推测与事实是否区分清晰（推测性内容是否被标注为推测/可能/假设）\n"
        "2. 推断性结论是否标注了来源和前提条件\n"
        "3. 是否主动处理了跨维度矛盾（市场规模下降 vs 可能进一步萎缩）\n"
        "4. 因果假设是否被验证/修正/推翻\n"
        "5. 推测性观点是否被当作结论依据使用\n\n"
        f"报告内容：\n{report_text[:1500]}\n\n"
        "请严格按以下JSON格式回答，不要添加任何其他内容：\n"
        '{"spec_fact_sep": 1-5, "source_transp": 1-5, '
        '"contra_handle": 1-5, "hypo_verify": 1-5, '
        '"spec_penalty": 1-5, "overall": 1-5, '
        '"note": "brief explanation"}'
    )
    
    try:
        result = await call_llm(
            prompt=prompt,
            system_prompt="You are an academic rigor evaluator. Output ONLY valid JSON, nothing else.",
            max_tokens=500,
            temperature=0.0,
        )
        content = result.get("content", "").strip()
        if not content:
            logger.warning(f"LLM eval returned empty content")
            return None
        # Try multiple JSON extraction strategies
        json_match = re.search(r'\{[^{}]*\}', content)
        if not json_match:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            return parsed
        logger.warning(f"LLM eval JSON parse failed: {content[:200]}")
    except Exception as e:
        logger.warning(f"LLM evaluation failed: {e}")
    return None


# ================================================================
# 主评估流程
# ================================================================

async def run_evaluation():
    topic = "中国智能手机行业"
    aspects = ["风险分析", "投资建议"]
    
    print("=" * 70)
    print("认识论防线报告质量影响评估 (A/B Test)")
    print("=" * 70)
    print(f"\n主题: {topic}")
    print(f"评估维度: {aspects}")
    print(f"跨维度claims: {len(CROSS_DIMENSION_CLAIMS)} 条")
    print(f"  - factual: {len(FACTUAL_STATEMENTS)}")
    print(f"  - inferential: {len(INFERENTIAL_STATEMENTS)}")
    print(f"  - speculative: {len(SPECULATIVE_STATEMENTS)}")
    
    all_results = {}
    
    for aspect in aspects:
        print(f"\n{'='*70}")
        print(f"维度: {aspect}")
        print(f"{'='*70}")
        
        # A组: 无防御
        prompt_a = build_no_defense_prompt(topic, aspect)
        print(f"\n--- A组（无防御）prompt长度: {len(prompt_a)} chars ---")
        
        result_a = await call_llm(
            prompt=prompt_a,
            system_prompt="你是一位专业的行业研究分析师。",
            max_tokens=2000,
            temperature=0.3,
        )
        report_a = result_a.get("content", "")
        print(f"报告A长度: {len(report_a)} chars")
        
        # B组: 有防御
        prompt_b = build_with_defense_prompt(topic, aspect)
        print(f"\n--- B组（有防御）prompt长度: {len(prompt_b)} chars ---")
        
        result_b = await call_llm(
            prompt=prompt_b,
            system_prompt="你是一位专业的行业研究分析师。",
            max_tokens=2000,
            temperature=0.3,
        )
        report_b = result_b.get("content", "")
        print(f"报告B长度: {len(report_b)} chars")
        
        # 规则评估
        metrics_a = evaluate_report(report_a, "A")
        metrics_b = evaluate_report(report_b, "B")
        
        # LLM评估
        print("\n正在用LLM评估报告严谨性...")
        llm_eval_a = await llm_evaluate_report(report_a, "A")
        llm_eval_b = await llm_evaluate_report(report_b, "B")
        
        all_results[aspect] = {
            "A": {"rule_metrics": metrics_a, "llm_eval": llm_eval_a, "report": report_a},
            "B": {"rule_metrics": metrics_b, "llm_eval": llm_eval_b, "report": report_b},
        }
        
        # 打印对比
        print(f"\n{'─'*70}")
        print(f"维度 [{aspect}] A/B对比:")
        print(f"{'─'*70}")
        print(f"{'指标':<30} {'A(无防御)':<15} {'B(有防御)':<15} {'提升':<15}")
        print(f"{'─'*70}")
        
        comparisons = [
            ("推测性结论引用率", "speculative_as_conclusion_rate", False),
            ("矛盾处理率", "contradiction_addressed", True),
            ("推断来源标注率", "source_annotation_rate", True),
            ("事实引用率", "factual_cited_rate", True),
            ("假设验证率", "hypothesis_verified_rate", True),
            ("推测性标注率", "speculative_labeled_rate", True),
        ]
        
        for label, key, higher_is_better in comparisons:
            val_a = metrics_a[key]
            val_b = metrics_b[key]
            if isinstance(val_a, bool):
                str_a = "是" if val_a else "否"
                str_b = "是" if val_b else "否"
                delta = "[OK]" if (val_b and not val_a) else ("=" if val_a == val_b else "[FAIL]")
            else:
                str_a = f"{val_a:.0%}"
                str_b = f"{val_b:.0%}"
                diff = val_b - val_a
                if higher_is_better:
                    delta = f"+{diff:.0%}" if diff > 0 else (f"{diff:.0%}" if diff < 0 else "=")
                else:
                    delta = f"{diff:.0%}" if diff < 0 else (f"+{diff:.0%}" if diff > 0 else "=")
            print(f"{label:<30} {str_a:<15} {str_b:<15} {delta:<15}")
        
        # LLM评估对比
        if llm_eval_a and llm_eval_b:
            print(f"\n{'LLM严谨性评估':<30} {'A(无防御)':<15} {'B(有防御)':<15} {'提升':<15}")
            print(f"{'─'*70}")
            for score_key in ["spec_fact_sep", "source_transp", 
                             "contra_handle", "hypo_verify",
                             "spec_penalty", "overall"]:
                sa = llm_eval_a.get(score_key, 0)
                sb = llm_eval_b.get(score_key, 0)
                diff = sb - sa
                delta = f"+{diff}" if diff > 0 else (str(diff) if diff < 0 else "=")
                label_cn = {
                    "spec_fact_sep": "spec/fact separation",
                    "source_transp": "source transparency",
                    "contra_handle": "contradiction handling",
                    "hypo_verify": "hypothesis verification",
                    "spec_penalty": "speculation penalty",
                    "overall": "overall rigor",
                }.get(score_key, score_key)
                print(f"{label_cn:<30} {sa:<15} {sb:<15} {delta:<15}")
    
    # ================================================================
    # 总结
    # ================================================================
    
    print(f"\n{'='*70}")
    print("总结: 认识论防线对报告质量的影响")
    print(f"{'='*70}")
    
    for aspect in aspects:
        r = all_results[aspect]
        ma = r["A"]["rule_metrics"]
        mb = r["B"]["rule_metrics"]
        la = r["A"]["llm_eval"] or {}
        lb = r["B"]["llm_eval"] or {}
        
        print(f"\n[{aspect}]")
        print(f"  推测性结论误用: A={ma['speculative_as_conclusion_rate']:.0%} → B={mb['speculative_as_conclusion_rate']:.0%}")
        print(f"  矛盾处理: A={'是' if ma['contradiction_addressed'] else '否'} → B={'是' if mb['contradiction_addressed'] else '否'}")
        print(f"  推断来源标注: A={ma['source_annotation_rate']:.0%} → B={mb['source_annotation_rate']:.0%}")
        print(f"  假设验证: A={ma['hypothesis_verified_rate']:.0%} → B={mb['hypothesis_verified_rate']:.0%}")
        print(f"  推测性标注: A={ma['speculative_labeled_rate']:.0%} → B={mb['speculative_labeled_rate']:.0%}")
        
        overall_a = la.get("overall", 0)
        overall_b = lb.get("overall", 0)
        if overall_a and overall_b:
            print(f"  LLM总体严谨性: A={overall_a}/5 → B={overall_b}/5 (Δ={overall_b-overall_a:+d})")
    
    # 保存结果
    save_results = {}
    for aspect in aspects:
        save_results[aspect] = {}
        for group in ["A", "B"]:
            r = all_results[aspect][group]
            save_results[aspect][group] = {
                "rule_metrics": r["rule_metrics"],
                "llm_eval": r["llm_eval"],
                "report_length": len(r["report"]),
            }
    
    with open("epistemic_ab_evaluation_results.json", "w", encoding="utf-8") as f:
        json.dump(save_results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n结果已保存到 epistemic_ab_evaluation_results.json")


if __name__ == "__main__":
    asyncio.run(run_evaluation())
