"""
Epistemic Defense: Report Depth & Quality A/B Evaluation

A组（无防御）: claims平铺注入，无分层、无矛盾提示、无假设验证要求
B组（有防御）: L3分层注入 + L5矛盾检测 + L4假设验证要求

用LLM从以下维度评估报告质量：
1. 分析深度: 表面复述 vs 深入因果挖掘
2. 洞察质量: 重复数据 vs 产生新理解
3. 结论可靠性: 空泛判断 vs 基于证据的推理
4. 逻辑链条: 断裂跳跃 vs 完整推理链
5. 矛盾处理: 忽略矛盾 vs 主动解释矛盾
6. 假设驱动: 无假设 vs 假设-验证-结论
"""
import asyncio
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import logging
logging.basicConfig(level=logging.INFO)

from src.core.llm_client import call_llm
from src.core.agents.generic_agent import COGNITIVE_STRATEGY

# ================================================================
# 跨维度claims数据集
# ================================================================

CROSS_DIMENSION_CLAIMS = [
    {"statement": "2025年Q1华为智能手机市场份额32%，苹果28%，小米18%", "confidence": "HIGH",
     "前提条件": "IDC数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual",
     "falsification": "IDC修正数据时", "source_aspect": "竞争格局"},
    {"statement": "华为份额从35%降至32%暗示高端市场竞争加剧", "confidence": "MEDIUM",
     "前提条件": "份额数据准确且趋势持续", "cross_impact": ["战略意图"], "epistemic_level": "inferential",
     "falsification": "若份额下降由行业整体萎缩导致而非竞争加剧", "source_aspect": "竞争格局"},
    {"statement": "头部企业可能通过并购或技术整合寻求突破", "confidence": "LOW",
     "前提条件": "行业整合趋势持续", "cross_impact": ["投资建议"], "epistemic_level": "speculative",
     "falsification": "若未来6个月无并购公告则推断不成立", "source_aspect": "竞争格局"},
    {"statement": "2025年Q1中国智能手机出货量6800万台，同比下降8.2%", "confidence": "HIGH",
     "前提条件": "IDC数据准确", "cross_impact": ["风险分析"], "epistemic_level": "factual",
     "falsification": "数据源修正时", "source_aspect": "市场规模"},
    {"statement": "5G换机潮推动市场但消费降级压力导致增速放缓", "confidence": "MEDIUM",
     "前提条件": "换机周期数据和宏观经济数据准确", "cross_impact": ["行业趋势"], "epistemic_level": "inferential",
     "falsification": "若消费信心指数回升则增速可能超预期", "source_aspect": "市场规模"},
    {"statement": "如果宏观经济持续承压，市场规模可能进一步萎缩", "confidence": "LOW",
     "前提条件": "宏观压力持续", "cross_impact": ["风险分析"], "epistemic_level": "speculative",
     "falsification": "若Q2-Q3出现反弹迹象则不成立", "source_aspect": "市场规模"},
    {"statement": "AI手机成为2025年最显著技术趋势，华为小米均搭载端侧大模型", "confidence": "HIGH",
     "前提条件": "产品发布数据准确", "cross_impact": ["竞争格局"], "epistemic_level": "factual",
     "falsification": "若产品发布信息虚假", "source_aspect": "行业趋势"},
    {"statement": "端侧AI能力提升将推动智能手机向智能助手演进", "confidence": "MEDIUM",
     "前提条件": "技术路线和产品布局分析准确", "cross_impact": ["战略意图"], "epistemic_level": "inferential",
     "falsification": "若AI功能用户接受度低则演进路径受阻", "source_aspect": "行业趋势"},
    {"statement": "AI手机可能催生AI服务订阅新商业模式", "confidence": "LOW",
     "前提条件": "商业模式创新可行性", "cross_impact": ["投资建议"], "epistemic_level": "speculative",
     "falsification": "若18个月内无主流厂商推出AI订阅服务则推断不成立", "source_aspect": "行业趋势"},
    {"statement": "台积电3nm产能利用率达95%，芯片供应不确定性增加", "confidence": "HIGH",
     "前提条件": "台积电产能数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual",
     "falsification": "台积电产能数据修正时", "source_aspect": "风险分析"},
    {"statement": "中美贸易摩擦升级可能导致芯片禁运加剧", "confidence": "LOW",
     "前提条件": "贸易摩擦持续升级", "cross_impact": ["市场规模", "战略意图"], "epistemic_level": "speculative",
     "falsification": "若6个月内无新的禁令公告则风险评估需下调", "source_aspect": "风险分析"},
    {"statement": "华为在芯片领域的持续投入暗示其寻求技术自主的战略意图", "confidence": "MEDIUM",
     "前提条件": "产品迭代数据和供应链信息准确", "cross_impact": ["竞争格局"], "epistemic_level": "inferential",
     "falsification": "若华为转向采购外部芯片则推断不成立", "source_aspect": "战略意图"},
    {"statement": "小米可能通过生态整合寻求差异化竞争", "confidence": "LOW",
     "前提条件": "MIUI向HyperOS转型暗示意图", "cross_impact": ["行业趋势"], "epistemic_level": "speculative",
     "falsification": "若小米放弃HyperOS生态战略则推断不成立", "source_aspect": "战略意图"},
]

CONTRADICTION_PAIR = {
    "contradiction": "方向矛盾: 市场规模同比下降8.2% vs 市场规模可能进一步萎缩",
    "claims": ["2025年Q1中国智能手机出货量6800万台，同比下降8.2%", "如果宏观经济持续承压，市场规模可能进一步萎缩"]
}

CAUSAL_HYPOTHESES = [
    {"statement": "芯片供应紧张导致出货量下降", "verification_data": "供应链数据和出货量数据", "transmission": "风险分析→市场规模", "counter_hypothesis": "出货量下降主要由消费需求疲软导致，芯片供应影响有限"},
    {"statement": "AI手机普及推动换机需求", "verification_data": "AI手机销量和换机周期数据", "transmission": "行业趋势→市场规模", "counter_hypothesis": "AI功能尚未形成刚需，换机需求仍由硬件性能驱动"},
]

# ================================================================
# Prompt构建
# ================================================================

def build_no_defense_prompt(topic, aspect):
    """A组：无防御 — 所有claims平铺注入"""
    parts = [
        f"你是一位行业研究分析师，正在分析{topic}的{aspect}维度。",
        "",
        "## 其他维度最新结论",
    ]
    for c in CROSS_DIMENSION_CLAIMS:
        parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']})")
    
    parts.extend([
        "",
        f"请基于以上信息，撰写详细的{aspect}分析报告。要求：",
        "1. 综合所有维度信息给出你的分析结论",
        "2. 明确指出关键趋势和风险",
        "3. 给出你的判断和建议",
    ])
    return "\n".join(parts)


def build_with_defense_prompt(topic, aspect):
    """B组：L3+ 推理驱动注入 + 维度自适应 + 证据链要求"""
    parts = [
        f"你是一位行业研究分析师，正在分析{topic}的{aspect}维度。",
    ]
    
    factual = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "factual"]
    inferential = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "inferential"]
    speculative = [c for c in CROSS_DIMENSION_CLAIMS if c["epistemic_level"] == "speculative"]
    
    _ASPECT_TYPE_MAP = {
        "竞争格局": "fact_driven",
        "投资建议": "inference_driven",
        "技术趋势": "forward_looking",
        "风险分析": "assessment_driven",
    }
    _cog_type = _ASPECT_TYPE_MAP.get(aspect, "fact_driven")
    _strategy = COGNITIVE_STRATEGY[_cog_type]
    _aspect_policy = _strategy["L3"]["speculative_policy"]
    
    if factual:
        parts.append("\n### 其他维度已确认发现（可直接引用）")
        for c in factual:
            parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']})")
    
    if inferential:
        parts.append("\n### 其他维度推断结论（需验证后引用）")
        for c in inferential:
            parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 前提: {c.get('前提条件','未指定')})")
        parts.append("\n**推理要求**:")
        _infer_inst = _strategy["L3"].get("inferential_instruction", "")
        _cross_inst = _strategy["L3"].get("cross_dimension_instruction", "")
        if _infer_inst:
            parts.append(f"  - {_infer_inst}")
        if _cross_inst:
            parts.append(f"  - {_cross_inst}")
        parts.append("  - 若推断前提在你掌握的数据中不成立，需指出并修正结论")
    
    if speculative:
        if _aspect_policy == "open_use":
            parts.append("\n### 其他维度前瞻性判断（前瞻性判断是本维度核心输出，可直接推导）")
            for c in speculative:
                parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 证伪条件: {c.get('falsification','未指定')})")
            parts.append("\n**推理要求**:")
            parts.append("  - 前瞻性判断是本维度的核心分析对象，应作为主要推理起点")
            parts.append("  - 基于前瞻性判断构建完整的情景推演（乐观/中性/悲观），评估各情景概率")
            parts.append("  - 对每个前瞻性判断，评估其证伪条件在当前数据下是否可能触发")
            parts.append("  - 可将多个前瞻性判断交叉组合，推演复合情景")
        elif _aspect_policy == "cautious_use":
            parts.append("\n### 其他维度前瞻性判断（可作为方向性参考，但需明确标注不确定性）")
            for c in speculative:
                parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 证伪条件: {c.get('falsification','未指定')})")
            parts.append("\n**推理要求**:")
            parts.append("  - 引用前瞻性判断时必须标注「前瞻性判断，置信度XX，证伪条件：XX」")
            parts.append("  - 若你掌握的数据可以证伪某前瞻性判断，必须明确指出")
            parts.append("  - 可基于前瞻性判断推导情景分析（乐观/中性/悲观），但需说明各情景的概率依据")
        else:
            parts.append("\n### 其他维度推测性观点（仅供参考，不得作为结论依据）")
            for c in speculative:
                parts.append(f"  - [{c['source_aspect']}] {c['statement']} (置信度: {c['confidence']}, 证伪条件: {c.get('falsification','未指定')})")
            parts.append("\n**推理要求**:")
            parts.append("  - 推测性观点不得作为你的结论依据，仅可作为分析思路参考")
            parts.append("  - 如果你掌握可以证伪某推测性观点的数据，必须在分析中明确指出")
            parts.append("  - 若推测性观点启发了你的分析方向，需说明启发路径")
    
    # L3-D: 矛盾注入（策略驱动）
    _l5 = _strategy["L5"]
    _contradiction_instruction = _l5.get("contradiction_instruction", "如果你的分析与上述矛盾相关，必须给出你的判断和依据。")
    parts.append("\n### 已检测到跨维度矛盾")
    parts.append(f"  - 矛盾类型: {CONTRADICTION_PAIR['contradiction']}")
    parts.append(f"    涉及结论: {CONTRADICTION_PAIR['claims']}")
    parts.append(f"\n**要求**: {_contradiction_instruction}")
    
    # L4: 假设验证（策略驱动）
    _l4 = _strategy["L4"]
    _hypothesis_count = _l4["hypothesis_count"]
    _agent_hypothesis_count = _l4["agent_hypothesis_count"]
    _output_suffix = _l4["output_suffix"]
    _hcount_val = _hypothesis_count[0] if isinstance(_hypothesis_count, tuple) else _hypothesis_count
    
    if _hcount_val > 0 or _agent_hypothesis_count > 0:
        parts.append("\n### 因果假设（必须验证或修正）")
        for i, h in enumerate(CAUSAL_HYPOTHESES[:_hcount_val], 1):
            parts.append(f"  {i}. {h['statement']}")
            parts.append(f"     验证数据需求：{h['verification_data']}")
            parts.append(f"     跨维度传导：{h['transmission']}")
            if h.get('counter_hypothesis'):
                parts.append(f"     反面假设：{h['counter_hypothesis']}")
        parts.append("\n**假设驱动分析要求**：")
        parts.append("  1. 对每个给定假设进行验证，给出支持/反对证据和验证结果（确认/修正/推翻）")
        if _agent_hypothesis_count > 0:
            parts.append(f"  2. 基于你掌握的数据，额外提出至少{_agent_hypothesis_count}个新的因果假设并验证")
        parts.append("  3. 对关键假设评估其反面假设成立的可能性")
        parts.append("  4. 最终结论必须基于假设验证结果推导，而非直接下判断")
        parts.append(f"\n**输出格式**：在分析末尾标注「{_output_suffix}」，列出每个假设的验证结论")
    else:
        parts.append("\n### 数据验证要求")
        parts.append("  - 本维度以事实数据为核心，所有结论必须基于可验证的数据")
        parts.append("  - 对引用的每个数据点，标注来源和时效性")
        parts.append("  - 若发现数据间矛盾，必须指出并给出你的判断")
        parts.append(f"\n**输出格式**：在分析末尾标注「{_output_suffix}」，列出关键数据点的验证结论")
    
    # L3-E: 证据链要求（策略驱动）
    _evidence_template = _strategy["L3"].get("evidence_chain_template", "支持证据 → 推理步骤 → 结论")
    _insight_inst = _strategy["L3"].get("insight_instruction")
    parts.append("\n### 分析输出规范")
    parts.append(f"  - 每个关键结论必须附带：{_evidence_template}，标注每步的认知层级（事实/推断/前瞻）")
    parts.append("  - 若结论基于多个来源交叉验证，注明交叉验证过程")
    parts.append("  - 若存在反对证据，必须列出并解释为何仍得出该结论")
    
    # Insight discovery section (placed last to counter template rigidity)
    if _insight_inst:
        parts.append("\n### 洞察发现（独立于上述结构化要求）")
        parts.append(f"  {_insight_inst}")
        parts.append("  在报告末尾单独列出你发现的最重要的非常规洞察，标注为「核心洞察」")
    
    parts.extend([
        "",
        f"请基于以上信息，撰写详细的{aspect}分析报告。要求：",
        "1. 综合所有维度信息给出你的分析结论",
        "2. 明确指出关键趋势和风险",
        "3. 给出你的判断和建议",
    ])
    return "\n".join(parts)


# ================================================================
# LLM深度评估
# ================================================================

async def llm_evaluate_single(report, aspect, group):
    """用LLM评估单份报告的深度和质量"""
    prompt = (
        f"评估以下行业分析报告的质量，每项1-10分：\n\n"
        f"1. depth(分析深度): 表面复述 vs 深入因果挖掘\n"
        f"2. insight(洞察质量): 重复信息 vs 产生新理解\n"
        f"3. reliability(结论可靠性): 空泛套话 vs 基于证据推理；推测是否被误用为确定结论\n"
        f"4. logic(逻辑链条): 断裂跳跃 vs 完整推理链\n"
        f"5. contradiction(矛盾处理): 忽略矛盾 vs 主动解释矛盾\n"
        f"6. hypothesis(假设驱动): 直接下结论 vs 假设-验证-结论\n\n"
        f"报告:\n{report[:800]}\n\n"
        f'只输出JSON: {{"depth":N,"insight":N,"reliability":N,"logic":N,"contradiction":N,"hypothesis":N,"total":N}} No note field. Numbers only.'
    )
    
    try:
        result = await call_llm(
            prompt=prompt,
            system_prompt="You are a professional report quality evaluator.",
            max_tokens=2000,
            temperature=0.0,
        )
        content = result.get("content", "").strip()
        if not content:
            logging.warning(f"LLM eval returned empty for {group}, success={result.get('success')}, usage={result.get('usage')}")
            return None
        json_match = re.search(r'\{[^{}]*\}', content)
        if not json_match:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        logging.warning(f"JSON parse failed for {group}: {content[:200]}")
    except Exception as e:
        logging.warning(f"LLM eval failed for {group}: {e}")
    return None


async def llm_compare(report_a, report_b, aspect, eval_a, eval_b):
    """用LLM给出对比总结"""
    prompt = (
        f"两份关于「中国智能手机行业{aspect}」的分析报告，评分如下：\n"
        f"A: depth={eval_a.get('depth',0)}, insight={eval_a.get('insight',0)}, reliability={eval_a.get('reliability',0)}, "
        f"logic={eval_a.get('logic',0)}, contradiction={eval_a.get('contradiction',0)}, hypothesis={eval_a.get('hypothesis',0)}\n"
        f"B: depth={eval_b.get('depth',0)}, insight={eval_b.get('insight',0)}, reliability={eval_b.get('reliability',0)}, "
        f"logic={eval_b.get('logic',0)}, contradiction={eval_b.get('contradiction',0)}, hypothesis={eval_b.get('hypothesis',0)}\n\n"
        f"报告A摘要: {report_a[:500]}\n"
        f"报告B摘要: {report_b[:500]}\n\n"
        f"B使用了认知防御系统（分层注入+矛盾检测+假设验证）。"
        f"用一句话说明B相比A最关键的质量提升是什么？"
    )
    try:
        result = await call_llm(prompt=prompt, system_prompt="You are a report quality expert.", max_tokens=150, temperature=0.0)
        return result.get("content", "").strip()
    except:
        return ""


# ================================================================
# 主流程
# ================================================================

async def run_evaluation():
    topic = "中国智能手机行业"
    aspects = ["竞争格局", "投资建议", "技术趋势", "风险分析"]
    
    print("=" * 70)
    print("Epistemic Defense: Report Depth & Quality A/B Evaluation")
    print("=" * 70)
    print(f"Topic: {topic}")
    print(f"Aspects: {aspects}")
    print(f"Claims: {len(CROSS_DIMENSION_CLAIMS)} (factual={sum(1 for c in CROSS_DIMENSION_CLAIMS if c['epistemic_level']=='factual')}, "
          f"inferential={sum(1 for c in CROSS_DIMENSION_CLAIMS if c['epistemic_level']=='inferential')}, "
          f"speculative={sum(1 for c in CROSS_DIMENSION_CLAIMS if c['epistemic_level']=='speculative')})")
    
    all_results = {}
    
    for aspect in aspects:
        print(f"\n{'='*70}")
        print(f"Aspect: {aspect}")
        print(f"{'='*70}")
        
        prompt_a = build_no_defense_prompt(topic, aspect)
        prompt_b = build_with_defense_prompt(topic, aspect)
        
        print(f"  Prompt A (no defense): {len(prompt_a)} chars")
        print(f"  Prompt B (with defense): {len(prompt_b)} chars")
        print(f"  Generating reports...")
        
        # Generate reports
        ra = await call_llm(prompt=prompt_a, system_prompt="你是一位专业的行业研究分析师。", max_tokens=4000, temperature=0.3)
        rb = await call_llm(prompt=prompt_b, system_prompt="你是一位专业的行业研究分析师。", max_tokens=4000, temperature=0.3)
        
        report_a = ra.get("content", "")
        report_b = rb.get("content", "")
        
        print(f"  Report A: {len(report_a)} chars")
        print(f"  Report B: {len(report_b)} chars")
        
        # Evaluate separately
        print(f"  Evaluating Report A...")
        eval_a = await llm_evaluate_single(report_a, aspect, "A")
        print(f"  Evaluating Report B...")
        eval_b = await llm_evaluate_single(report_b, aspect, "B")
        
        key_diff = ""
        if eval_a and eval_b:
            key_diff = await llm_compare(report_a, report_b, aspect, eval_a, eval_b)
        
        all_results[aspect] = {
            "report_a_len": len(report_a),
            "report_b_len": len(report_b),
            "eval_a": eval_a,
            "eval_b": eval_b,
            "key_diff": key_diff,
            "report_a": report_a,
            "report_b": report_b,
        }
        
        if eval_a and eval_b:
            print(f"\n  --- {aspect} Results ---")
            print(f"  {'Dimension':<25} {'A(no def)':<12} {'B(with def)':<12} {'Delta':<10}")
            print(f"  {'-'*60}")
            for dim in ["depth", "insight", "reliability", "logic", "contradiction", "hypothesis"]:
                va = eval_a.get(dim, 0)
                vb = eval_b.get(dim, 0)
                delta = vb - va
                sign = "+" if delta > 0 else ""
                dim_label = {"depth": "Analysis Depth", "insight": "Insight Quality", 
                            "reliability": "Conclusion Reliability", "logic": "Logic Chain",
                            "contradiction": "Contradiction Handling", "hypothesis": "Hypothesis-Driven"}[dim]
                print(f"  {dim_label:<25} {va:<12} {vb:<12} {sign}{delta}")
            ta = eval_a.get("total", 0)
            tb = eval_b.get("total", 0)
            print(f"  {'TOTAL (max 60)':<25} {ta:<12} {tb:<12} {'+' if tb-ta>0 else ''}{tb-ta}")
            if key_diff:
                print(f"  Key diff: {key_diff}")
        else:
            print(f"  Evaluation failed!")
    
    # ================================================================
    # Summary
    # ================================================================
    
    print(f"\n{'='*70}")
    print("SUMMARY: Epistemic Defense Impact on Report Quality")
    print(f"{'='*70}")
    
    total_a = 0
    total_b = 0
    wins = {"A": 0, "B": 0, "tie": 0}
    dimension_deltas = {}
    
    for aspect, r in all_results.items():
        ea = r.get("eval_a")
        eb = r.get("eval_b")
        if not ea or not eb:
            continue
        ta = ea.get("total", 0)
        tb = eb.get("total", 0)
        total_a += ta
        total_b += tb
        
        for dim in ["depth", "insight", "reliability", "logic", "contradiction", "hypothesis"]:
            if dim not in dimension_deltas:
                dimension_deltas[dim] = []
            dimension_deltas[dim].append(eb.get(dim, 0) - ea.get(dim, 0))
    
    print(f"\n  Total Score: A={total_a}, B={total_b}, Delta={'+' if total_b-total_a>0 else ''}{total_b-total_a}")
    n_aspects = len([r for r in all_results.values() if r.get("eval_a") and r.get("eval_b")])
    if n_aspects > 0:
        print(f"  B wins: {sum(1 for r in all_results.values() if r.get('eval_a') and r.get('eval_b') and r['eval_b'].get('total',0) > r['eval_a'].get('total',0))}/{n_aspects} aspects")
    print(f"\n  Average improvement per dimension (1-10 scale):")
    for dim, deltas in dimension_deltas.items():
        avg = sum(deltas) / len(deltas) if deltas else 0
        dim_label = {"depth": "Analysis Depth", "insight": "Insight Quality", 
                    "reliability": "Conclusion Reliability", "logic": "Logic Chain",
                    "contradiction": "Contradiction Handling", "hypothesis": "Hypothesis-Driven"}[dim]
        print(f"    {dim_label:<30} {'+' if avg>0 else ''}{avg:.1f} points")
    
    # Save
    save_data = {}
    for aspect, r in all_results.items():
        save_data[aspect] = {
            "report_a_len": r["report_a_len"],
            "report_b_len": r["report_b_len"],
            "eval_a": r["eval_a"],
            "eval_b": r["eval_b"],
            "key_diff": r.get("key_diff", ""),
        }
    with open("epistemic_quality_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Results saved to epistemic_quality_eval_results.json")


if __name__ == "__main__":
    asyncio.run(run_evaluation())
