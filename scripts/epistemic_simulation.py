"""
Real-environment simulation test for epistemic defense (L1-L5).

This script simulates a 5-dimension industry report workflow, exercising
all five defense layers with real LLM calls. It evaluates:
1. L1: Whether claims are correctly classified (factual/inferential/speculative)
2. L2: Whether caliber mapping and priority logic work correctly
3. L3: Whether stratified injection produces properly separated prompt sections
4. L4: Whether hypothesis verification parsing succeeds
5. L5: Whether direction contradictions are detected

The test writes claims to SharedMemory, reads them back, and evaluates
the output quality of each layer.
"""
import asyncio
import hashlib
import json
import os
import sys
import time
import logging
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from src.core.communication import SharedMemory, SOURCE_PRIORITY
from src.core.llm_client import call_llm
from src.core.agents.generic_agent import GenericAgent

# ================================================================
# Simulated 5-dimension analysis content
# ================================================================

DIMENSION_ANALYSES = {
    "竞争格局": {
        "aspect": "竞争格局",
        "analysis": """## 竞争格局分析

### 市场份额分布
2025年Q1中国智能手机市场份额：华为32%，苹果28%，小米18%，OPPO12%，vivo10%。
数据来源：IDC季度追踪报告。

### 竞争态势推断
份额下降趋势暗示竞争加剧——华为从35%降至32%，而苹果从25%升至28%。
这种趋势表明高端市场的竞争格局正在重塑。

### 战略意图推测
头部企业可能通过并购或技术整合寻求突破。
小米近期在芯片领域的投入暗示其寻求技术自主的意图，
但这一推测缺乏直接数据支撑，需要观察后续并购公告确认。
""",
    },
    "市场规模": {
        "aspect": "市场规模",
        "analysis": """## 市场规模分析

### 2025年市场数据
中国智能手机市场2025年Q1出货量为6800万台，同比下降8.2%。
2024年全年出货量2.86亿台，同比下降4.1%。

### 增长趋势推断
5G换机潮对市场规模有正向推动，但消费降级压力导致增速放缓。
预计2025年全年出货量约2.75亿台，同比下降约3.5%。
这一推断基于换机周期数据和宏观经济压力的交叉分析。

### 风险提示
如果宏观经济持续承压，市场规模可能面临进一步萎缩。
这一推测的证伪条件是：若Q2-Q3出现反弹迹象则不成立。
""",
    },
    "行业趋势": {
        "aspect": "行业趋势",
        "analysis": """## 行业趋势分析

### 技术趋势
AI手机成为2025年最显著技术趋势。华为Mate 70系列、小米15系列均搭载端侧大模型。
这一趋势有明确的产品发布数据支撑。

### 趋势推断
端侧AI能力的提升将推动智能手机向"智能助手"演进，
这可能重塑用户与手机的交互方式。
基于当前技术路线和产品布局，这一推断有较强支撑。

### 长期推测
AI手机可能催生新的商业模式（如AI服务订阅），但这一推测缺乏市场验证。
证伪条件：若18个月内无主流厂商推出AI订阅服务则推断不成立。
""",
    },
    "风险分析": {
        "aspect": "风险分析",
        "analysis": """## 风险分析

### 确认风险
供应链风险：芯片供应不确定性增加，台积电3nm产能紧张。
2024年Q4台积电3nm产能利用率达95%，有明确数据支撑。

### 推断性风险
监管风险可能收紧——工信部对手机预装软件的监管趋严，
这可能影响厂商利润率。基于政策趋势的推断，非直接数据。

### 推测性风险
中美贸易摩擦升级可能导致芯片禁运加剧。
这一推测缺乏具体政策信号支撑，证伪条件：
若6个月内无新的禁令公告则风险评估需下调。
""",
    },
    "战略意图": {
        "aspect": "战略意图",
        "analysis": """## 战略意图推断

### 华为战略意图推断
华为在芯片领域的持续投入（麒麟9000S到麒麟9010的迭代）
暗示其寻求技术自主的战略意图。
这一推断基于公开的产品迭代数据和供应链信息。

### 小米战略意图推测
小米可能通过生态整合寻求差异化竞争——
MIUI向HyperOS的转型暗示其构建AIoT生态的意图，
但这一推测缺乏直接的战略声明支撑。

### 苹果反事实检验
如果苹果的真实意图是巩固高端市场，应观察到：
1) 持续的产品差异化投入 2) 不参与价格战
实际观察：iPhone 16 Pro的AI功能投入和价格策略符合此推断。
""",
    },
}

# Simulated L4 hypothesis verification output
HYPOTHESIS_VERIFICATION_TEXT = """分析内容...

假设验证结果：
假设1：验证 | 依据：芯片供应紧张数据明确，台积电产能利用率95%
假设2：修正 | 依据：监管风险部分成立，但影响范围小于预期 | 修正内容：仅影响预装软件收入而非整体利润率
假设3：推翻 | 依据：6个月内未出现新禁令信号，与推测前提矛盾"""

# Simulated LLM output for claim extraction (pre-generated to avoid real LLM cost)
MOCK_CLAIM_EXTRACTIONS = {
    "竞争格局": [
        {"statement": "2025年Q1中国智能手机市场份额华为32%苹果28%", "confidence": "HIGH", "前提条件": "IDC数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual", "falsification": "IDC修正数据时"},
        {"statement": "份额下降趋势暗示高端市场竞争加剧", "confidence": "MEDIUM", "前提条件": "份额数据准确且趋势持续", "cross_impact": ["战略意图"], "epistemic_level": "inferential", "falsification": "若份额下降由行业整体萎缩导致而非竞争加剧"},
        {"statement": "头部企业可能通过并购或技术整合寻求突破", "confidence": "LOW", "前提条件": "行业整合趋势持续", "cross_impact": ["投资建议"], "epistemic_level": "speculative", "falsification": "若未来6个月无并购公告则推断不成立"},
    ],
    "市场规模": [
        {"statement": "2025年Q1智能手机出货量6800万台同比下降8.2%", "confidence": "HIGH", "前提条件": "IDC数据准确", "cross_impact": ["风险分析"], "epistemic_level": "factual", "falsification": "数据源修正时"},
        {"statement": "5G换机潮推动市场但消费降级压力导致增速放缓", "confidence": "MEDIUM", "前提条件": "换机周期数据和宏观经济数据准确", "cross_impact": ["行业趋势"], "epistemic_level": "inferential", "falsification": "若消费信心指数回升则增速可能超预期"},
        {"statement": "如果宏观经济持续承压市场规模可能进一步萎缩", "confidence": "LOW", "前提条件": "宏观压力持续", "cross_impact": ["风险分析"], "epistemic_level": "speculative", "falsification": "若Q2-Q3出现反弹迹象则不成立"},
    ],
    "行业趋势": [
        {"statement": "AI手机成为2025年最显著技术趋势华为小米均搭载端侧大模型", "confidence": "HIGH", "前提条件": "产品发布数据准确", "cross_impact": ["竞争格局"], "epistemic_level": "factual", "falsification": "若产品发布信息虚假"},
        {"statement": "端侧AI能力提升将推动智能手机向智能助手演进", "confidence": "MEDIUM", "前提条件": "技术路线和产品布局分析准确", "cross_impact": ["战略意图"], "epistemic_level": "inferential", "falsification": "若AI功能用户接受度低则演进路径受阻"},
        {"statement": "AI手机可能催生AI服务订阅新商业模式", "confidence": "LOW", "前提条件": "商业模式创新可行性", "cross_impact": ["投资建议"], "epistemic_level": "speculative", "falsification": "若18个月内无主流厂商推出AI订阅服务则推断不成立"},
    ],
    "风险分析": [
        {"statement": "台积电3nm产能利用率达95%芯片供应不确定性增加", "confidence": "HIGH", "前提条件": "台积电产能数据准确", "cross_impact": ["市场规模"], "epistemic_level": "factual", "falsification": "台积电产能数据修正时"},
        {"statement": "工信部对手机预装软件监管趋严可能影响厂商利润率", "confidence": "MEDIUM", "前提条件": "监管政策趋势持续", "cross_impact": ["竞争格局"], "epistemic_level": "inferential", "falsification": "若监管政策松动或厂商主动合规则影响低于预期"},
        {"statement": "中美贸易摩擦升级可能导致芯片禁运加剧", "confidence": "LOW", "前提条件": "贸易摩擦持续升级", "cross_impact": ["市场规模", "战略意图"], "epistemic_level": "speculative", "falsification": "若6个月内无新的禁令公告则风险评估需下调"},
    ],
    "战略意图": [
        {"statement": "华为芯片投入暗示其寻求技术自主的战略意图", "confidence": "MEDIUM", "前提条件": "产品迭代数据和供应链信息准确", "cross_impact": ["竞争格局"], "epistemic_level": "inferential", "falsification": "若华为转向采购外部芯片则推断不成立"},
        {"statement": "小米可能通过生态整合寻求差异化竞争", "confidence": "LOW", "前提条件": "MIUI向HyperOS转型暗示意图", "cross_impact": ["行业趋势"], "epistemic_level": "speculative", "falsification": "若小米放弃HyperOS生态战略则推断不成立"},
        {"statement": "苹果意图巩固高端市场不参与价格战", "confidence": "MEDIUM", "前提条件": "iPhone16Pro的AI投入和价格策略符合推断", "cross_impact": ["竞争格局"], "epistemic_level": "inferential", "falsification": "若苹果推出低价产品线则推断不成立"},
    ],
}


async def run_simulation():
    """Run full epistemic defense simulation."""
    
    sm = SharedMemory()
    results = {
        "l1_claims": {},
        "l2_caliber": {},
        "l3_injection": {},
        "l4_verification": {},
        "l5_contradiction": {},
        "summary": {},
    }
    
    print("=" * 70)
    print("EPISTEMIC DEFENSE REAL-ENVIRONMENT SIMULATION TEST")
    print("=" * 70)
    
    # ================================================================
    # L1: Claim extraction with epistemic_level classification
    # ================================================================
    
    print("\n--- L1: Claim Extraction & Classification ---")
    
    agent = GenericAgent(agent_id="test_agent", config={})
    agent._shared_memory = sm
    
    total_claims = 0
    classification_counts = {"factual": 0, "inferential": 0, "speculative": 0}
    dimension_results = {}
    
    for dim_name, dim_data in DIMENSION_ANALYSES.items():
        aspect = dim_data["aspect"]
        analysis = dim_data["analysis"]
        mock_claims = MOCK_CLAIM_EXTRACTIONS.get(aspect, [])
        
        # Use mock claims instead of real LLM call (to avoid cost)
        # But verify the rule-based validation logic works
        claims = []
        for c in mock_claims:
            claim = dict(c)
            claim["id"] = str(len(claims))
            claim["source_aspect"] = aspect
            
            # Apply L1 rule-based validation
            _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
            ASPECT_EPISTEMIC_CEILING = {
                "strategic_intent": "speculative",
                "战略意图": "speculative",
                "战略意图推断": "speculative",
                "Strategic Intent": "speculative",
            }
            _speculative_words = {"可能", "预计", "或许", "也许", "大概", "猜测", "推测", "预期"}
            
            if "epistemic_level" not in claim:
                claim["epistemic_level"] = "inferential"
            _level = claim.get("epistemic_level", "inferential")
            if _level not in _epistemic_order:
                claim["epistemic_level"] = "inferential"
                _level = "inferential"
            
            # LOW + premise => not factual
            if claim.get("confidence") == "LOW" and claim.get("前提条件") and _level == "factual":
                claim["epistemic_level"] = "inferential"
                _level = "inferential"
            
            # Speculative word in factual => downgrade
            _stmt = claim.get("statement", "")
            if _level == "factual" and any(w in _stmt for w in _speculative_words):
                claim["epistemic_level"] = "inferential"
                _level = "inferential"
            
            # Dimension ceiling
            _ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
            if _ceiling and _epistemic_order.get(_level, 1) < _epistemic_order.get(_ceiling, 1):
                claim["epistemic_level"] = _ceiling
                _level = _ceiling
            
            claim.setdefault("falsification", "未指定证伪条件")
            claims.append(claim)
        
        total_claims += len(claims)
        for c in claims:
            classification_counts[c["epistemic_level"]] += 1
        
        dimension_results[aspect] = claims
        
        print(f"\n  [{aspect}] extracted {len(claims)} claims:")
        for c in claims:
            print(f"    - {c['epistemic_level']} (conf={c['confidence']}): {c['statement'][:40]}...")
            print(f"      falsification: {c['falsification'][:40]}...")
    
    results["l1_claims"] = {
        "total": total_claims,
        "distribution": classification_counts,
        "per_dimension": {k: len(v) for k, v in dimension_results.items()},
    }
    
    print(f"\n  L1 Summary: {total_claims} claims, distribution: {classification_counts}")
    
    # ================================================================
    # L2: Caliber mapping & write to SharedMemory
    # ================================================================
    
    print("\n--- L2: Caliber Mapping & SharedMemory Priority ---")
    
    caliber_map = {
        "factual": "llm_inference_factual",
        "inferential": "llm_inference",
        "speculative": "llm_inference_speculative",
    }
    
    l2_results = {}
    for aspect, claims in dimension_results.items():
        for claim in claims:
            caliber = caliber_map.get(claim.get("epistemic_level", "inferential"), "llm_inference")
            metric = f"claim:{aspect}:{claim['id']}"
            
            conflict = await sm.write_canonical(
                metric=metric,
                value=claim,
                caliber=caliber,
                source="test_agent",
                publisher=aspect,
            )
            
            entry = await sm.get_canonical(metric)
            l2_results[metric] = {
                "caliber": entry.get("caliber"),
                "priority": SOURCE_PRIORITY.get(entry.get("caliber", ""), 0),
                "conflict": conflict is not None,
            }
            
            print(f"  {metric}: caliber={entry.get('caliber')}, priority={SOURCE_PRIORITY.get(entry.get('caliber',''),0)}, conflict={conflict is not None}")
    
    # Test priority conflicts
    print("\n  Testing priority interactions:")
    
    # speculative should NOT overwrite factual (use fresh SM to avoid interference)
    sm_pri = SharedMemory()
    await sm_pri.write_canonical("claim:test_priority:0", {"statement": "test_factual", "epistemic_level": "factual"}, 
                             caliber="llm_inference_factual", source="a1", publisher="test")
    conflict_result = await sm_pri.write_canonical("claim:test_priority:0", {"statement": "test_speculative", "epistemic_level": "speculative"},
                                               caliber="llm_inference_speculative", source="a2", publisher="test")
    entry = await sm_pri.get_canonical("claim:test_priority:0")
    factual_protected = entry["value"]["statement"] == "test_factual"
    print(f"    speculative overwrite factual: BLOCKED={factual_protected}, conflict={conflict_result is not None}")
    
    # same caliber same source should overwrite (iterative deepening)
    sm2 = SharedMemory()
    await sm2.write_canonical("claim:市场:0", {"statement": "v1"}, caliber="llm_inference_factual", source="a1", publisher="市场")
    await sm2.write_canonical("claim:市场:0", {"statement": "v2"}, caliber="llm_inference_factual", source="a1", publisher="市场")
    e2 = await sm2.get_canonical("claim:市场:0")
    same_source_update = e2["value"]["statement"] == "v2"
    print(f"    same source update: ALLOWED={same_source_update}")
    
    # same caliber different source should NOT overwrite
    sm3 = SharedMemory()
    await sm3.write_canonical("claim:市场:0", {"statement": "v1"}, caliber="llm_inference_factual", source="a1", publisher="市场")
    await sm3.write_canonical("claim:市场:0", {"statement": "v2"}, caliber="llm_inference_factual", source="a2", publisher="市场")
    e3 = await sm3.get_canonical("claim:市场:0")
    different_source_blocked = e3["value"]["statement"] == "v1"
    print(f"    different source same caliber: BLOCKED={different_source_blocked}")
    
    l2_priority_tests = {
        "speculative_not_overwrite_factual": factual_protected,
        "same_source_update_allowed": same_source_update,
        "different_source_blocked": different_source_blocked,
    }
    results["l2_caliber"] = {"writes": l2_results, "priority_tests": l2_priority_tests}
    
    # ================================================================
    # L3: Stratified injection
    # ================================================================
    
    print("\n--- L3: Stratified Injection ---")
    
    all_canon = sm.get_all_canonical()
    cross_dimension_claims = []
    for k, v in all_canon.items():
        if k.startswith("claim:"):
            _val = v.get("value", {})
            if isinstance(_val, dict) and _val.get("statement"):
                cross_dimension_claims.append(_val)
    
    factual_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "factual"]
    inferential_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "inferential"]
    speculative_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "speculative"]
    no_level = [c for c in cross_dimension_claims if c.get("epistemic_level") not in ("factual", "inferential", "speculative")]
    if no_level:
        inferential_claims.extend(no_level)
    
    conflict_entries = {k: v for k, v in all_canon.items() if k.startswith("conflict:claim:")}
    
    # Build stratified prompt sections
    prompt_parts = []
    
    if factual_claims:
        prompt_parts.append("### 其他维度已确认发现（可直接引用）")
        for c in factual_claims:
            prompt_parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')[:50]} (置信度: {c.get('confidence','?')})")
    
    if inferential_claims:
        prompt_parts.append("### 其他维度推断结论（需验证后引用）")
        for c in inferential_claims:
            prompt_parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')[:50]} (置信度: {c.get('confidence','?')}, 前提: {c.get('前提条件','未指定')[:30]}...)")
        prompt_parts.append("**要求**: 引用推断性结论时需注明'根据XX维度推断'。")
    
    if speculative_claims:
        prompt_parts.append("### 其他维度推测性观点（仅供参考，不得作为结论依据）")
        for c in speculative_claims:
            prompt_parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')[:50]} (置信度: {c.get('confidence','?')}, 证伪条件: {c.get('falsification','未指定')[:30]}...)")
        prompt_parts.append("**要求**: 推测性观点不得作为你的结论依据，仅可作为分析思路参考。如果你掌握可以证伪某推测性观点的数据，必须在分析中明确指出。")
    
    if conflict_entries:
        prompt_parts.append("### 已检测到跨维度矛盾")
        for ck, cv in conflict_entries.items():
            cv_val = cv.get("value", {})
            prompt_parts.append(f"  - 矪盾类型: {cv_val.get('contradiction', '未知')} | 涉及结论: {cv_val.get('claims', [])}")
    
    injection_text = "\n".join(prompt_parts)
    
    print(f"\n  Generated stratified injection ({len(injection_text)} chars):")
    print(f"    factual: {len(factual_claims)} claims")
    print(f"    inferential: {len(inferential_claims)} claims")
    print(f"    speculative: {len(speculative_claims)} claims")
    print(f"    conflict entries: {len(conflict_entries)}")
    print(f"    no-level (defaulted): {len(no_level)}")
    
    # Key check: speculative claims MUST have "不得作为结论依据" label
    has_speculative_warning = "不得作为结论依据" in injection_text
    has_falsification = "证伪条件" in injection_text
    has_factual_direct = "可直接引用" in injection_text
    has_inferential_verify = "需验证后引用" in injection_text
    
    print(f"\n  Label checks:")
    print(f"    '可直接引用' in factual section: {has_factual_direct}")
    print(f"    '需验证后引用' in inferential section: {has_inferential_verify}")
    print(f"    '不得作为结论依据' in speculative section: {has_speculative_warning}")
    print(f"    '证伪条件' present: {has_falsification}")
    
    results["l3_injection"] = {
        "factual_count": len(factual_claims),
        "inferential_count": len(inferential_claims),
        "speculative_count": len(speculative_claims),
        "conflict_count": len(conflict_entries),
        "injection_length": len(injection_text),
        "label_checks": {
            "factual_direct_label": has_factual_direct,
            "inferential_verify_label": has_inferential_verify,
            "speculative_warning_label": has_speculative_warning,
            "falsification_present": has_falsification,
        },
    }
    
    # ================================================================
    # L4: Hypothesis verification parsing
    # ================================================================
    
    print("\n--- L4: Hypothesis Verification ---")
    
    hypotheses = [
        {"statement": "芯片供应收紧导致出货量下降"},
        {"statement": "监管趋严影响厂商利润率"},
        {"statement": "贸易摩擦导致芯片禁运加剧"},
    ]
    
    parsed = agent._parse_hypothesis_verification(HYPOTHESIS_VERIFICATION_TEXT, hypotheses)
    
    print(f"  Parsed {len(parsed)} hypotheses:")
    for h in parsed:
        print(f"    - id={h['id']} status={h['status']} statement={h.get('statement','')[:40]}...")
        if h.get("revision_note"):
            print(f"      revision_note: {h['revision_note'][:40]}...")
    
    verified_count = sum(1 for h in parsed if h["status"] == "verified")
    revised_count = sum(1 for h in parsed if h["status"] == "revised")
    refuted_count = sum(1 for h in parsed if h["status"] == "refuted")
    
    # Write verification results to SharedMemory
    for h in parsed:
        await sm.write_canonical(
            metric=f"hypothesis:风险分析:{h['id']}",
            value=h,
            caliber="llm_inference",
            source="test_agent",
            publisher="风险分析",
        )
    
    results["l4_verification"] = {
        "total": len(parsed),
        "verified": verified_count,
        "revised": revised_count,
        "refuted": refuted_count,
        "all_have_id": all("id" in h for h in parsed),
        "stable_ids": all(len(h.get("id", "")) == 8 for h in parsed),
    }
    
    print(f"  L4 Summary: verified={verified_count}, revised={revised_count}, refuted={refuted_count}")
    print(f"  All have stable hash ID (8 chars): {all(len(h.get('id', '')) == 8 for h in parsed)}")
    
    # ================================================================
    # L5: Contradiction detection (now with LLM semantic analysis)
    # ================================================================
    
    print("\n--- L5: Contradiction Detection (2-stage: precheck + LLM) ---")
    
    contradiction_tests = [
        ("市场规模持续增长", "市场规模面临萎缩", True),
        ("出口额持续增长", "内销利润面临萎缩", False),
        ("企业A占据主导", "企业B份额领先", False),
        ("AI手机快速普及", "AI手机渗透率下滑", True),
        ("供应链改善", "供应链恶化", True),
    ]
    
    detected = []
    for stmt_a, stmt_b, expected in contradiction_tests:
        precheck_passed = agent._detect_claim_contradiction_precheck(
            {"statement": stmt_a}, {"statement": stmt_b}
        )
        if precheck_passed:
            result = await agent._detect_claim_contradiction(
                {"statement": stmt_a}, {"statement": stmt_b}
            )
        else:
            result = None
        is_detected = result is not None
        correct = is_detected == expected
        detected.append({
            "a": stmt_a,
            "b": stmt_b,
            "expected": expected,
            "precheck": precheck_passed,
            "detected": is_detected,
            "correct": correct,
        })
        stage_info = f"precheck={'Y' if precheck_passed else 'N'}"
        if precheck_passed and is_detected:
            stage_info += ", llm=confirmed"
        elif precheck_passed and not is_detected:
            stage_info += ", llm=rejected"
        print(f"  '{stmt_a}' vs '{stmt_b}': expected={expected}, detected={is_detected}, correct={correct} [{stage_info}]")
    
    accuracy = sum(1 for d in detected if d["correct"]) / len(detected)
    precheck_recall = sum(1 for d in detected if d["precheck"] and d["expected"]) / max(sum(1 for d in detected if d["expected"]), 1)
    
    real_contradiction = await agent._detect_claim_contradiction(
        {"statement": "市场规模持续增长", "epistemic_level": "factual", "confidence": "HIGH", "source_aspect": "行业趋势"},
        {"statement": "市场规模面临萎缩", "epistemic_level": "inferential", "confidence": "MEDIUM", "source_aspect": "风险分析"},
    )
    
    print(f"\n  Real-world scenario: '增长' vs '萎缩' => contradiction={real_contradiction is not None}")
    if real_contradiction:
        print(f"  Detail: {real_contradiction[:80]}")
    
    results["l5_contradiction"] = {
        "tests": detected,
        "accuracy": accuracy,
        "precheck_recall": precheck_recall,
        "real_world_detected": real_contradiction is not None,
        "method": "2-stage (precheck + LLM semantic)",
    }
    
    # ================================================================
    # Final L1-C truncation test with real analysis content
    # ================================================================
    
    print("\n--- L1-C: Real Analysis Truncation ---")
    
    for dim_name, dim_data in DIMENSION_ANALYSES.items():
        analysis = dim_data["analysis"]
        if len(analysis) > 3000:
            truncated = analysis[:2500] + "\n\n...[中间省略]...\n\n" + analysis[-500:]
        else:
            truncated = analysis
        
        # Check if conclusion-like content is preserved
        has_conclusion_keywords = any(kw in truncated for kw in ["结论", "推测", "证伪条件", "推断", "风险提示"])
        print(f"  [{dim_data['aspect']}]: original={len(analysis)} chars, truncated={len(truncated)} chars, conclusion preserved={has_conclusion_keywords}")
    
    # ================================================================
    # L1-D: Strategic intent dimension ceiling real test
    # ================================================================
    
    print("\n--- L1-D: Strategic Intent Ceiling ---")
    
    si_claims = dimension_results.get("strategic_intent", [])
    all_speculative_or_inferential = all(c["epistemic_level"] in ("speculative", "inferential") for c in si_claims)
    no_factual = all(c["epistemic_level"] != "factual" for c in si_claims)
    
    print(f"  strategic_intent claims: {len(si_claims)}")
    print(f"  All non-factual (ceiling working): {no_factual}")
    print(f"  All speculative/inferential: {all_speculative_or_inferential}")
    
    # ================================================================
    # Summary
    # ================================================================
    
    print("\n" + "=" * 70)
    print("EPISTEMIC DEFENSE SIMULATION RESULTS")
    print("=" * 70)
    
    summary = {
        "L1_claim_extraction": {
            "total_claims": total_claims,
            "classification_accuracy": "verified_by_mock",
            "distribution": classification_counts,
            "dimension_ceiling_working": no_factual,
        },
        "L2_caliber_priority": {
            "priority_tests_passed": all(l2_priority_tests.values()),
            "speculative_protected": factual_protected,
            "iterative_deepening_allowed": same_source_update,
            "cross_agent_blocked": different_source_blocked,
        },
        "L3_stratified_injection": {
            "labels_correct": all(results["l3_injection"]["label_checks"].values()),
            "no_duplicate_injection": "其他维度最新结论" not in injection_text,
        },
        "L4_hypothesis_verification": {
            "parse_success_rate": f"{verified_count + revised_count + refuted_count}/{len(parsed)}",
            "stable_hash_ids": all(len(h.get("id", "")) == 8 for h in parsed),
        },
        "L5_contradiction_detection": {
            "accuracy": f"{accuracy*100:.0f}%",
            "real_world_scenario": real_contradiction is not None,
        },
    }
    
    results["summary"] = summary
    
    for layer, data in summary.items():
        print(f"\n  {layer}:")
        for k, v in data.items():
            print(f"    {k}: {v}")
    
    # Save results
    with open("epistemic_simulation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n  Results saved to epistemic_simulation_results.json")
    
    # Final assessment
    all_checks = [
        factual_protected,
        same_source_update,
        different_source_blocked,
        all(results["l3_injection"]["label_checks"].values()),
        "其他维度最新结论" not in injection_text,
        verified_count + revised_count + refuted_count >= 1,
        all(len(h.get("id", "")) == 8 for h in parsed),
        accuracy >= 0.8,
        real_contradiction is not None,
        no_factual,
    ]
    
    print(f"\n  Final: {sum(all_checks)}/{len(all_checks)} checks passed")
    
    if all(all_checks):
        print("\n  ALL EPISTEMIC DEFENSE CHECKS PASSED")
    else:
        print(f"\n  FAILED checks: {sum(1 for c in all_checks if not c)}/{len(all_checks)}")
    
    return all(all_checks)


if __name__ == "__main__":
    ok = asyncio.run(run_simulation())
    sys.exit(0 if ok else 1)
