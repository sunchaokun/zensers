"""
端到端集成测试：认知策略全流程验证

测试范围（覆盖L1-L5在全流程中的实际运行）：
1. DATA_COLLECTION → 搜索数据 → 写入SharedMemory
2. Canonical Data → L2 caliber裁决 → 数据冲突解决
3. DEEP_ANALYSIS → 认知策略推理 → claim提取 → 写入SharedMemory
4. Cross-Dimension → claims读取 → 矛盾检测 → L5矛盾处理
5. SYNTHESIS → 跨维度综合 → 最终报告

对比：
- A组（无防御）：全流程运行，不注入认知策略
- B组（有防御）：全流程运行，注入认知策略

评估维度：
1. 报告质量（depth/insight/reliability/logic/contradiction/hypothesis）
2. Claim质量（epistemic_level分布、falsification覆盖率、cross_impact密度）
3. 数据一致性（canonical冲突率、claim矛盾率）
4. 信息密度（每千字claim数、跨维度引用率）
"""
import asyncio
import json
import os
import re
import sys
import time
import logging
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

logging.basicConfig(level=logging.WARNING)

from src.core.llm_client import call_llm
from src.core.communication import SharedMemory
from src.core.agents.generic_agent import COGNITIVE_STRATEGY

# ================================================================
# 模拟数据：替代真实搜索，提供可控的跨维度数据集
# ================================================================

MOCK_SEARCH_RESULTS = {
    "竞争格局": {
        "data_points": [
            {"metric": "华为市场份额", "value": "32%", "source": "IDC 2025Q1", "caliber": "structured_source"},
            {"metric": "苹果市场份额", "value": "28%", "source": "IDC 2025Q1", "caliber": "structured_source"},
            {"metric": "小米市场份额", "value": "18%", "source": "IDC 2025Q1", "caliber": "structured_source"},
            {"metric": "华为份额变化", "value": "-3pp YoY", "source": "IDC 2025Q1", "caliber": "structured_source"},
        ],
        "sources": [
            {"title": "2025Q1中国智能手机市场份额报告", "source": "IDC", "date": "2025-04-15", "reliability": "high"},
            {"title": "华为高端市场竞争分析", "source": "Counterpoint", "date": "2025-03-20", "reliability": "high"},
        ]
    },
    "投资建议": {
        "data_points": [
            {"metric": "行业PE", "value": "25.3x", "source": "Wind", "caliber": "structured_source"},
            {"metric": "行业营收增速", "value": "-8.2%", "source": "国家统计局", "caliber": "structured_source"},
            {"metric": "AI手机渗透率", "value": "35%", "source": "Gartner预测", "caliber": "search_result"},
        ],
        "sources": [
            {"title": "智能手机行业2025年投资展望", "source": "中金公司", "date": "2025-05-01", "reliability": "high"},
            {"title": "AI手机产业链投资机会", "source": "国泰君安", "date": "2025-04-28", "reliability": "medium"},
        ]
    },
    "技术趋势": {
        "data_points": [
            {"metric": "端侧AI芯片出货量", "value": "1.2亿片", "source": "TrendForce", "caliber": "search_result"},
            {"metric": "3nm产能利用率", "value": "95%", "source": "台积电季报", "caliber": "structured_source"},
            {"metric": "AI手机换机周期", "value": "2.5年(预计)", "source": "IDC预测", "caliber": "search_result"},
        ],
        "sources": [
            {"title": "2025年AI手机技术路线图", "source": "GSMA", "date": "2025-03-15", "reliability": "high"},
            {"title": "端侧大模型发展趋势", "source": "量子位", "date": "2025-04-10", "reliability": "medium"},
        ]
    },
    "风险分析": {
        "data_points": [
            {"metric": "台积电3nm产能利用率", "value": "95%", "source": "台积电季报", "caliber": "structured_source"},
            {"metric": "中美贸易摩擦指数", "value": "高位", "source": "CSIS", "caliber": "search_result"},
            {"metric": "消费信心指数", "value": "87.2", "source": "国家统计局", "caliber": "structured_source"},
        ],
        "sources": [
            {"title": "芯片供应链风险评估", "source": "Gartner", "date": "2025-04-20", "reliability": "high"},
            {"title": "中美科技脱钩影响分析", "source": "麦肯锡", "date": "2025-03-30", "reliability": "medium"},
        ]
    },
}


# ================================================================
# 模拟SharedMemory写入
# ================================================================

async def write_mock_data_to_shared_memory(shared_mem, aspect, data):
    """将模拟数据写入SharedMemory，模拟DATA_COLLECTION阶段的输出"""
    canonical = data.get("data_points", [])
    for dp in canonical:
        metric = dp.get("metric", "")
        value = dp.get("value", "")
        caliber = dp.get("caliber", "search_result")
        source = dp.get("source", "unknown")
        await shared_mem.write_canonical(
            metric=metric,
            value=value,
            caliber=caliber,
            source=source,
            publisher=f"agent_{aspect}"
        )


# ================================================================
# L1: Claim提取（从分析结果中）
# ================================================================

async def extract_claims_from_analysis(content, aspect, cog_strategy):
    """L1: 从分析结果中提取claims，应用dimension_ceiling和falsification"""
    ceiling = cog_strategy["L1"]["dimension_ceiling"]
    confidence_threshold = cog_strategy["L1"]["confidence_threshold"]

    prompt = f"""从以下{aspect}维度分析文本中提取关键claims，每个claim包含：
- statement: 陈述内容
- confidence: HIGH/MEDIUM/LOW
- 前提条件: 该claim成立的前提
- cross_impact: 影响哪些其他维度（列表）
- epistemic_level: factual/inferential/speculative
- falsification: 什么条件下该claim可被证伪
- source_aspect: {aspect}

认知约束：
- 维度天花板：{ceiling or '无限制'}（超过此层级的claim需降级）
- 置信度门槛：{json.dumps(confidence_threshold, ensure_ascii=False)}

输出JSON数组，不要其他内容。

分析文本：
{content[:3000]}"""

    try:
        result = await call_llm(
            prompt=prompt,
            system_prompt="你是专业的信息提取专家，只输出JSON。",
            max_tokens=3000,
            temperature=0.0,
        )
        content = result.get("content", "").strip()
        if not content:
            return []
        # 多策略JSON解析
        claims = None
        # 策略1: 直接找JSON数组
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            try:
                claims = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        # 策略2: 修复常见JSON错误（中文引号、尾逗号）
        if claims is None and json_match:
            raw = json_match.group()
            raw = raw.replace('"', '"').replace('"', '"').replace(''', "'").replace(''', "'")
            raw = re.sub(r',\s*([}\]])', r'\1', raw)  # 尾逗号
            try:
                claims = json.loads(raw)
            except json.JSONDecodeError:
                pass
        # 策略3: 逐个提取{}对象
        if claims is None:
            claims = []
            for obj_match in re.finditer(r'\{[^{}]*\}', content):
                try:
                    obj = json.loads(obj_match.group())
                    if "statement" in obj or "epistemic_level" in obj:
                        claims.append(obj)
                except json.JSONDecodeError:
                    continue
        if claims:
            for c in claims:
                if not isinstance(c, dict):
                    continue
                if ceiling and c.get("epistemic_level") not in ("factual", "inferential", "speculative"):
                    c["epistemic_level"] = "inferential"
                if ceiling == "inferential" and c.get("epistemic_level") == "speculative":
                    c["epistemic_level"] = "inferential"
                    c["confidence"] = "MEDIUM"
                if "source_aspect" not in c:
                    c["source_aspect"] = aspect
            return [c for c in claims if isinstance(c, dict) and c.get("statement")]
    except Exception as e:
        logging.warning(f"Claim extraction failed for {aspect}: {e}")
    return []


# ================================================================
# L5: 矛盾检测（跨维度）
# ================================================================

async def detect_contradictions(all_claims):
    """L5: 检测跨维度claim矛盾（启发式+LLM语义确认）"""
    contradictions = []
    claim_list = []
    for aspect, claims in all_claims.items():
        for c in claims:
            c["source_aspect"] = aspect
            claim_list.append(c)

    # 启发式预检
    candidates = []
    for i in range(len(claim_list)):
        for j in range(i + 1, len(claim_list)):
            c1 = claim_list[i]
            c2 = claim_list[j]
            if c1.get("source_aspect") == c2.get("source_aspect"):
                continue
            # 宽松匹配：不同认知层级也可矛盾
            s1 = c1.get("statement", "").lower()
            s2 = c2.get("statement", "").lower()
            # 数值矛盾检测
            nums1 = re.findall(r'[\d.]+%?', s1)
            nums2 = re.findall(r'[\d.]+%?', s2)
            # 方向矛盾检测
            pos_words = ["增长", "上升", "扩张", "加速", "提升", "改善", "恢复"]
            neg_words = ["下降", "萎缩", "放缓", "减少", "恶化", "承压", "下滑"]
            has_pos1 = any(w in s1 for w in pos_words)
            has_neg1 = any(w in s1 for w in neg_words)
            has_pos2 = any(w in s2 for w in pos_words)
            has_neg2 = any(w in s2 for w in neg_words)
            if (has_pos1 and has_neg2) or (has_neg1 and has_pos2):
                candidates.append((c1, c2, "方向矛盾"))

    # LLM语义确认（批量）
    if candidates:
        for c1, c2, h_type in candidates[:5]:  # 最多5对
            try:
                result = await call_llm(
                    prompt=f"以下两个结论是否构成矛盾？\nA: {c1.get('statement','')}\nB: {c2.get('statement','')}\n只回答YES或NO。",
                    system_prompt="你是逻辑分析专家。",
                    max_tokens=20,
                    temperature=0.0,
                )
                if "yes" in result.get("content", "").lower():
                    contradictions.append({
                        "type": h_type,
                        "claims": [c1.get("statement", ""), c2.get("statement", "")],
                        "aspects": [c1.get("source_aspect"), c2.get("source_aspect")],
                    })
            except:
                pass

    # 如果LLM确认不够，保留启发式结果
    if not contradictions and candidates:
        for c1, c2, h_type in candidates[:3]:
            contradictions.append({
                "type": h_type,
                "claims": [c1.get("statement", ""), c2.get("statement", "")],
                "aspects": [c1.get("source_aspect"), c2.get("source_aspect")],
            })

    return contradictions


# ================================================================
# Prompt构建：全流程版本
# ================================================================

def build_e2e_analysis_prompt(topic, aspect, data_str, cross_claims, contradictions, cog_strategy, with_defense=True):
    """构建全流程分析prompt（含真实数据+跨维度claims+矛盾）"""
    parts = [f"你是一位行业研究分析师，正在分析{topic}的{aspect}维度。"]

    if with_defense:
        _policy = cog_strategy["L3"]["speculative_policy"]
        _ect = cog_strategy["L3"]["evidence_chain_template"]
        _infer_inst = cog_strategy["L3"].get("inferential_instruction", "")
        _cross_inst = cog_strategy["L3"].get("cross_dimension_instruction", "")
        _insight_inst = cog_strategy["L3"].get("insight_instruction", "")
        _l4 = cog_strategy["L4"]
        _l5 = cog_strategy["L5"]
    else:
        _policy = "open_use"
        _ect = "证据 → 推理 → 结论"
        _infer_inst = ""
        _cross_inst = ""
        _insight_inst = ""
        _l4 = None
        _l5 = None

    # 数据注入
    parts.append(f"\n## {aspect}维度研究数据\n{data_str}")

    # 跨维度claims
    if cross_claims:
        if with_defense:
            factual = [c for c in cross_claims if c.get("epistemic_level") == "factual"]
            inferential = [c for c in cross_claims if c.get("epistemic_level") == "inferential"]
            speculative = [c for c in cross_claims if c.get("epistemic_level") == "speculative"]

            if factual:
                parts.append("\n### 其他维度已确认发现（可直接引用）")
                for c in factual:
                    parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')})")

            if inferential:
                parts.append("\n### 其他维度推断结论（需验证后引用）")
                for c in inferential:
                    parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')}, 前提: {c.get('前提条件','未指定')})")
                parts.append("\n**推理要求**:")
                if _infer_inst:
                    parts.append(f"  - {_infer_inst}")
                if _cross_inst:
                    parts.append(f"  - {_cross_inst}")
                parts.append("  - 若推断前提在你掌握的数据中不成立，需指出并修正结论")

            if speculative:
                if _policy == "open_use":
                    parts.append("\n### 其他维度前瞻性判断（本维度核心输出，需系统化处理）")
                    for c in speculative:
                        parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')}, 证伪条件: {c.get('falsification','未指定')})")
                    parts.append("\n**推理要求**:")
                    parts.append("  - 前瞻性判断是本维度的核心输出，可直接作为结论基础；每个判断须含证伪条件和概率评估")
                    parts.append("  - 必须引用上述其他维度的信息来支撑或修正你的风险情景分析")
                elif _policy == "cautious_use":
                    parts.append("\n### 其他维度前瞻性判断（可作为方向性参考，但需明确标注不确定性）")
                    for c in speculative:
                        parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')}, 证伪条件: {c.get('falsification','未指定')})")
                    parts.append("\n**推理要求**:")
                    parts.append("  - 引用前瞻性判断时必须标注「前瞻性判断，置信度XX，证伪条件：XX」")
                    parts.append("  - 可基于前瞻性判断推导情景分析，但需说明各情景的概率依据")
                else:
                    parts.append("\n### 其他维度推测性观点（仅供参考，不得作为结论依据）")
                    for c in speculative:
                        parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')}, 证伪条件: {c.get('falsification','未指定')})")
                    parts.append("\n**推理要求**:")
                    parts.append("  - 推测性观点仅供参考，不得作为结论依据；若数据可证伪某观点须指出，若启发分析方向须说明")
        else:
            parts.append("\n## 其他维度最新结论")
            for c in cross_claims:
                parts.append(f"  - [{c.get('source_aspect','?')}] {c.get('statement','')} (置信度: {c.get('confidence','?')})")

    # 矛盾注入（优先于假设——确保LLM先处理矛盾）
    if contradictions and with_defense and _l5:
        parts.append("\n### 已检测到跨维度矛盾（优先处理）")
        for cx in contradictions:
            parts.append(f"  - 矛盾类型: {cx.get('type','未知')} | 涉及结论: {cx.get('claims',[])}")
        parts.append(f"\n**要求**: {_l5['contradiction_instruction']}")

    # 假设注入（按认知类型差异化强度）
    if with_defense and _l4:
        _hcount = _l4.get("hypothesis_count", 0)
        _hcount_val = _hcount[0] if isinstance(_hcount, tuple) else _hcount
        if _hcount_val > 0:
            _is_fact = (cog_strategy is COGNITIVE_STRATEGY.get("fact_driven"))
            _hypo_title = "建议探索" if _is_fact else "必须验证或修正"
            parts.append(f"\n### {_l4['hypothesis_type']}假设（{_hypo_title}）")
            parts.append("请基于以上数据和跨维度信息，提出假设并验证")
            if _is_fact:
                parts.append("  - 尝试用数据验证上述观察，确认或否定后得出发现")
            else:
                if _l4.get("agent_hypothesis_count", 0) > 0:
                    parts.append(f"  - 必须额外提出至少{_l4['agent_hypothesis_count']}个新的{_l4['hypothesis_type']}假设并验证")
                if _l4.get("counter_hypothesis_required"):
                    parts.append("  - 对关键假设评估其反面假设成立的可能性")
                parts.append("  - 最终结论必须基于假设验证结果推导")
            parts.append(f"\n**输出格式**：在分析末尾标注「{_l4['output_suffix']}」，列出每个假设的验证结论")

    # 证据链 + 洞察（按认知类型差异化）
    if with_defense:
        _is_fact = (cog_strategy is COGNITIVE_STRATEGY.get("fact_driven"))
        parts.append("\n### 分析输出规范")
        parts.append(f"  - 每个关键结论附带：{_ect}")
        if not _is_fact:
            parts.append("  - 标注每步的认知层级（事实/推断/前瞻）")
            parts.append("  - 若存在反对证据，列出并解释为何仍得出该结论")
        if _insight_inst:
            if _is_fact:
                parts.append(f"\n**洞察要求**：{_insight_inst}，在分析中自然呈现，标注「核心洞察」")
            else:
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
# LLM评估
# ================================================================

async def llm_evaluate_single(report, aspect, group):
    """评估单份报告（2次取平均，减少随机性）"""
    prompt = (
        f"评估以下行业分析报告的质量，每项1-10分：\n\n"
        f"1. depth(分析深度): 表面复述 vs 深入因果挖掘\n"
        f"2. insight(洞察质量): 重复信息 vs 产生新理解\n"
        f"3. reliability(结论可靠性): 空泛套话 vs 基于证据推理\n"
        f"4. logic(逻辑链条): 断裂跳跃 vs 完整推理链\n"
        f"5. contradiction(矛盾处理): 忽略矛盾 vs 主动解释矛盾\n"
        f"6. hypothesis(假设驱动): 直接下结论 vs 假设-验证-结论\n\n"
        f"报告:\n{report[:3000]}\n\n"
        f'只输出JSON: {{"depth":N,"insight":N,"reliability":N,"logic":N,"contradiction":N,"hypothesis":N}}'
    )
    scores_list = []
    for _ in range(2):
        try:
            result = await call_llm(
                prompt=prompt,
                system_prompt="You are a professional report quality evaluator.",
                max_tokens=2000,
                temperature=0.0,
            )
            content = result.get("content", "").strip()
            if not content:
                continue
            json_match = re.search(r'\{[^{}]*\}', content)
            if not json_match:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                scores_list.append(json.loads(json_match.group()))
        except Exception as e:
            logging.warning(f"LLM eval failed for {group}: {e}")
    if not scores_list:
        return None
    avg = {}
    for key in scores_list[0]:
        vals = [s.get(key, 0) for s in scores_list if key in s]
        avg[key] = round(sum(vals) / len(vals), 1) if vals else 0
    return avg


def evaluate_claim_quality(claims, aspect):
    """评估claim质量（不依赖LLM）"""
    if not claims:
        return {"count": 0, "epistemic_distribution": {}, "falsification_rate": 0, "cross_impact_rate": 0}

    epistemic_dist = {}
    for c in claims:
        level = c.get("epistemic_level", "unknown")
        epistemic_dist[level] = epistemic_dist.get(level, 0) + 1

    with_falsification = sum(1 for c in claims if c.get("falsification") and c["falsification"] != "未指定")
    with_cross_impact = sum(1 for c in claims if c.get("cross_impact") and c["cross_impact"])

    return {
        "count": len(claims),
        "epistemic_distribution": epistemic_dist,
        "falsification_rate": round(with_falsification / len(claims), 2) if claims else 0,
        "cross_impact_rate": round(with_cross_impact / len(claims), 2) if claims else 0,
    }


def evaluate_report_objective(report, aspect, cross_claims, contradictions):
    """客观评估报告质量（不依赖LLM）"""
    if not report:
        return {}
    
    # 跨维度引用率
    other_aspects = [c.get("source_aspect", "") for c in cross_claims if c.get("source_aspect") != aspect]
    unique_other = set(other_aspects)
    cross_ref_count = 0
    for oa in unique_other:
        if oa and oa in report:
            cross_ref_count += 1
    cross_ref_rate = cross_ref_count / len(unique_other) if unique_other else 0

    # 矛盾处理率
    contradiction_handled = 0
    for cx in contradictions:
        claims_text = " ".join(cx.get("claims", []))
        # 检查报告是否提到了矛盾涉及的关键词
        keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', claims_text)
        matched = sum(1 for kw in keywords if kw in report)
        if matched >= 2:
            contradiction_handled += 1
    contradiction_rate = contradiction_handled / len(contradictions) if contradictions else 0

    # 假设验证结构
    hypothesis_markers = ["假设", "验证", "推翻", "修正", "确认", "H1", "H2", "H3"]
    hypothesis_count = sum(1 for m in hypothesis_markers if m in report)

    # 洞察发现
    insight_markers = ["核心洞察", "洞察发现", "意外发现", "反直觉", "非常规"]
    insight_count = sum(1 for m in insight_markers if m in report)

    # 认知层级标注
    epistemic_markers = ["事实", "推断", "前瞻", "认知层级"]
    epistemic_count = sum(1 for m in epistemic_markers if m in report)

    # 证据链
    evidence_markers = ["支持证据", "交叉验证", "因果链", "推理链", "证据链"]
    evidence_count = sum(1 for m in evidence_markers if m in report)

    return {
        "report_len": len(report),
        "cross_ref_rate": round(cross_ref_rate, 2),
        "contradiction_rate": round(contradiction_rate, 2),
        "hypothesis_structures": hypothesis_count,
        "insight_markers": insight_count,
        "epistemic_markers": epistemic_count,
        "evidence_markers": evidence_count,
    }
    """评估claim质量（不依赖LLM）"""
    if not claims:
        return {"count": 0, "epistemic_distribution": {}, "falsification_rate": 0, "cross_impact_rate": 0}

    epistemic_dist = {}
    for c in claims:
        level = c.get("epistemic_level", "unknown")
        epistemic_dist[level] = epistemic_dist.get(level, 0) + 1

    with_falsification = sum(1 for c in claims if c.get("falsification") and c["falsification"] != "未指定")
    with_cross_impact = sum(1 for c in claims if c.get("cross_impact") and c["cross_impact"])

    return {
        "count": len(claims),
        "epistemic_distribution": epistemic_dist,
        "falsification_rate": round(with_falsification / len(claims), 2) if claims else 0,
        "cross_impact_rate": round(with_cross_impact / len(claims), 2) if claims else 0,
    }


# ================================================================
# 主流程：端到端集成测试
# ================================================================

async def run_e2e_test():
    topic = "中国智能手机行业"
    aspects = ["竞争格局", "风险分析"]
    type_map = {"竞争格局": "fact_driven", "投资建议": "inference_driven", "技术趋势": "forward_looking", "风险分析": "assessment_driven"}

    print("=" * 70)
    print("端到端集成测试：认知策略全流程验证")
    print("=" * 70)

    # ============================================================
    # Phase 1: DATA_COLLECTION (模拟)
    # ============================================================
    print("\n--- Phase 1: DATA_COLLECTION (模拟搜索) ---")

    shared_mem_a = SharedMemory()  # A组
    shared_mem_b = SharedMemory()  # B组

    for aspect in aspects:
        data = MOCK_SEARCH_RESULTS.get(aspect, {})
        await write_mock_data_to_shared_memory(shared_mem_a, aspect, data)
        await write_mock_data_to_shared_memory(shared_mem_b, aspect, data)
        canonical = shared_mem_b.get_all_canonical()
        print(f"  {aspect}: {len(data.get('data_points', []))} data points written, canonical={len(canonical)} entries")

    # ============================================================
    # Phase 2: DEEP_ANALYSIS (Round 1 - 无跨维度claims)
    # ============================================================
    print("\n--- Phase 2: DEEP_ANALYSIS (Round 1) ---")

    round1_results = {}
    all_claims_a = {}
    all_claims_b = {}

    for aspect in aspects:
        cog_type = type_map[aspect]
        cog_strategy = COGNITIVE_STRATEGY[cog_type]
        data = MOCK_SEARCH_RESULTS.get(aspect, {})
        data_str = json.dumps(data.get("data_points", []), ensure_ascii=False) + "\n" + json.dumps(data.get("sources", []), ensure_ascii=False)

        # A组：无防御
        prompt_a = build_e2e_analysis_prompt(topic, aspect, data_str, [], [], cog_strategy, with_defense=False)
        # B组：有防御（Round 1无跨维度claims，但注入策略）
        prompt_b = build_e2e_analysis_prompt(topic, aspect, data_str, [], [], cog_strategy, with_defense=True)

        print(f"  {aspect}: generating A({len(prompt_a)}c) and B({len(prompt_b)}c)...")

        ra = await call_llm(prompt=prompt_a, system_prompt="你是一位专业的行业研究分析师。", max_tokens=3000, temperature=0.3)
        rb = await call_llm(prompt=prompt_b, system_prompt="你是一位专业的行业研究分析师。", max_tokens=3000, temperature=0.3)

        report_a = ra.get("content", "")
        report_b = rb.get("content", "")

        # L1: 提取claims
        claims_a = await extract_claims_from_analysis(report_a, aspect, cog_strategy)
        claims_b = await extract_claims_from_analysis(report_b, aspect, cog_strategy)

        all_claims_a[aspect] = claims_a
        all_claims_b[aspect] = claims_b

        qa = evaluate_claim_quality(claims_a, aspect)
        qb = evaluate_claim_quality(claims_b, aspect)

        print(f"  {aspect}: A={len(report_a)}c/{qa['count']}claims B={len(report_b)}c/{qb['count']}claims")
        print(f"    A epistemic={qa['epistemic_distribution']} falsification={qa['falsification_rate']} cross_impact={qa['cross_impact_rate']}")
        print(f"    B epistemic={qb['epistemic_distribution']} falsification={qb['falsification_rate']} cross_impact={qb['cross_impact_rate']}")

        round1_results[aspect] = {
            "report_a_len": len(report_a), "report_b_len": len(report_b),
            "claims_a": qa, "claims_b": qb,
            "report_a": report_a, "report_b": report_b,
        }

    # ============================================================
    # Phase 3: L5 矛盾检测
    # ============================================================
    print("\n--- Phase 3: L5 Contradiction Detection ---")

    contradictions_a = await detect_contradictions(all_claims_a)
    contradictions_b = await detect_contradictions(all_claims_b)
    print(f"  A组: {len(contradictions_a)} contradictions detected")
    print(f"  B组: {len(contradictions_b)} contradictions detected")

    # ============================================================
    # Phase 4: DEEP_ANALYSIS (Round 2 - 含跨维度claims和矛盾)
    # ============================================================
    print("\n--- Phase 4: DEEP_ANALYSIS (Round 2 - with cross-dimension claims) ---")

    round2_results = {}

    for aspect in aspects:
        cog_type = type_map[aspect]
        cog_strategy = COGNITIVE_STRATEGY[cog_type]
        data = MOCK_SEARCH_RESULTS.get(aspect, {})
        data_str = json.dumps(data.get("data_points", []), ensure_ascii=False) + "\n" + json.dumps(data.get("sources", []), ensure_ascii=False)

        # 收集其他维度的claims
        cross_claims_a = []
        cross_claims_b = []
        for other_aspect, claims in all_claims_a.items():
            if other_aspect != aspect:
                cross_claims_a.extend(claims)
        for other_aspect, claims in all_claims_b.items():
            if other_aspect != aspect:
                cross_claims_b.extend(claims)

        # A组：无防御，但含跨维度claims
        prompt_a = build_e2e_analysis_prompt(topic, aspect, data_str, cross_claims_a, contradictions_a, cog_strategy, with_defense=False)
        # B组：有防御，含跨维度claims+矛盾（如果B组没检测到矛盾，用A组的矛盾确保矛盾处理能力可评估）
        contradictions_for_b = contradictions_b if contradictions_b else contradictions_a
        prompt_b = build_e2e_analysis_prompt(topic, aspect, data_str, cross_claims_b, contradictions_for_b, cog_strategy, with_defense=True)

        print(f"  {aspect}: generating with {len(cross_claims_a)} cross-claims...")

        ra = await call_llm(prompt=prompt_a, system_prompt="你是一位专业的行业研究分析师。", max_tokens=3000, temperature=0.3)
        rb = await call_llm(prompt=prompt_b, system_prompt="你是一位专业的行业研究分析师。", max_tokens=3000, temperature=0.3)

        report_a = ra.get("content", "")
        report_b = rb.get("content", "")

        # 评估
        eval_a = await llm_evaluate_single(report_a, aspect, "A")
        eval_b = await llm_evaluate_single(report_b, aspect, "B")

        # 重新提取claims（如果提取失败则重试一次）
        claims_a_r2 = await extract_claims_from_analysis(report_a, aspect, cog_strategy)
        claims_b_r2 = await extract_claims_from_analysis(report_b, aspect, cog_strategy)
        if not claims_b_r2 and report_b:
            claims_b_r2 = await extract_claims_from_analysis(report_b, aspect, cog_strategy)
        qa2 = evaluate_claim_quality(claims_a_r2, aspect)
        qb2 = evaluate_claim_quality(claims_b_r2, aspect)

        # 客观评估
        obj_a = evaluate_report_objective(report_a, aspect, cross_claims_a, contradictions_a)
        obj_b = evaluate_report_objective(report_b, aspect, cross_claims_b, contradictions_for_b)

        round2_results[aspect] = {
            "type": cog_type,
            "eval_a": eval_a, "eval_b": eval_b,
            "report_a_len": len(report_a), "report_b_len": len(report_b),
            "claims_a": qa2, "claims_b": qb2,
            "cross_claims_count": len(cross_claims_a),
            "obj_a": obj_a, "obj_b": obj_b,
        }

        if eval_a and eval_b:
            dims = ["depth", "insight", "reliability", "logic", "contradiction", "hypothesis"]
            deltas = {d: eval_b.get(d, 0) - eval_a.get(d, 0) for d in dims}
            wins = sum(1 for v in deltas.values() if v > 0)
            obj_wins = sum(1 for k in obj_a if obj_b.get(k, 0) > obj_a.get(k, 0))
            print(f"  {aspect} ({cog_type}): LLM_wins={wins}/6 obj_wins={obj_wins}/{len(obj_a)}")
            print(f"    obj_A={obj_a}")
            print(f"    obj_B={obj_b}")
        else:
            print(f"  {aspect}: eval failed")

    # ============================================================
    # Phase 5: SYNTHESIS (综合报告)
    # ============================================================
    print("\n--- Phase 5: SYNTHESIS ---")

    for group_name, results in [("A", round2_results), ("B", round2_results)]:
        all_section_content = ""
        for aspect, r in results.items():
            key = f"report_{group_name.lower()}_len" if group_name.lower() in r else None
            if key:
                all_section_content += f"\n\n## {aspect}\n[报告内容约{r[key]}字]"

    # 综合报告评估
    synthesis_prompts = {}
    for aspect, r in round2_results.items():
        synthesis_prompts[aspect] = r

    print("\n--- Phase 5: Cross-dimension claim quality comparison ---")
    for aspect in aspects:
        r1a = round1_results[aspect]["claims_a"]
        r1b = round1_results[aspect]["claims_b"]
        r2 = round2_results[aspect]
        print(f"  {aspect}:")
        print(f"    Round1 A: {r1a['count']} claims, falsification={r1a['falsification_rate']}, cross_impact={r1a['cross_impact_rate']}")
        print(f"    Round1 B: {r1b['count']} claims, falsification={r1b['falsification_rate']}, cross_impact={r1b['cross_impact_rate']}")
        print(f"    Round2 A: {r2['claims_a']['count']} claims, falsification={r2['claims_a']['falsification_rate']}, cross_impact={r2['claims_a']['cross_impact_rate']}")
        print(f"    Round2 B: {r2['claims_b']['count']} claims, falsification={r2['claims_b']['falsification_rate']}, cross_impact={r2['claims_b']['cross_impact_rate']}")

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 70)
    print("端到端集成测试总结")
    print("=" * 70)

    total_wins = 0
    total_dims = 0
    for aspect, r in round2_results.items():
        ea = r.get("eval_a")
        eb = r.get("eval_b")
        if ea and eb:
            dims = ["depth", "insight", "reliability", "logic", "contradiction", "hypothesis"]
            for d in dims:
                total_dims += 1
                if eb.get(d, 0) > ea.get(d, 0):
                    total_wins += 1

    print(f"\n报告质量(LLM): B组胜率 = {total_wins}/{total_dims} ({100*total_wins/total_dims if total_dims else 0:.0f}%)")

    # 客观评估汇总
    print(f"\n报告质量(客观指标):")
    obj_dims = ["cross_ref_rate", "contradiction_rate", "hypothesis_structures", "insight_markers", "epistemic_markers", "evidence_markers"]
    obj_total_wins = 0
    obj_total_dims = 0
    for aspect, r in round2_results.items():
        oa = r.get("obj_a", {})
        ob = r.get("obj_b", {})
        for d in obj_dims:
            if d in oa and d in ob:
                obj_total_dims += 1
                if ob[d] > oa[d]:
                    obj_total_wins += 1
    print(f"  B组客观胜率 = {obj_total_wins}/{obj_total_dims} ({100*obj_total_wins/obj_total_dims if obj_total_dims else 0:.0f}%)")

    # Claim质量对比
    claim_metrics = ["count", "falsification_rate", "cross_impact_rate"]
    claim_wins = {m: 0 for m in claim_metrics}
    for aspect in aspects:
        r2 = round2_results[aspect]
        for m in claim_metrics:
            if r2["claims_b"].get(m, 0) > r2["claims_a"].get(m, 0):
                claim_wins[m] += 1
            elif r2["claims_b"].get(m, 0) < r2["claims_a"].get(m, 0):
                claim_wins[m] -= 1

    print(f"\nClaim质量对比 (B优于A的维度数 - B劣于A的维度数):")
    for m, score in claim_wins.items():
        print(f"  {m}: {score:+d}/4")

    # 数据一致性
    print(f"\n跨维度矛盾检测: A组={len(contradictions_a)}, B组={len(contradictions_b)}")

    # 保存结果
    save_data = {}
    for aspect, r in round2_results.items():
        save_data[aspect] = {
            "type": r["type"],
            "eval_a": r["eval_a"],
            "eval_b": r["eval_b"],
            "claims_a": r["claims_a"],
            "claims_b": r["claims_b"],
            "cross_claims_count": r["cross_claims_count"],
            "contradictions_a": len(contradictions_a),
            "contradictions_b": len(contradictions_b),
        }

    with open("e2e_integration_test_results.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存到 e2e_integration_test_results.json")

    return round2_results


if __name__ == "__main__":
    asyncio.run(run_e2e_test())
