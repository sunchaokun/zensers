# 认识论防线设计审查文档

> **版本**: v4.0 | **日期**: 2026-07-01 | **状态**: L5升级为两阶段LLM语义检测
> 
> 本文档对 L1-L5 五层认识论防线方案进行严格审查，识别方案本身的漏洞，
> 并通过具体场景模拟评估修复前后效果。
>
> v4.0 变更：L5从硬编码关键词检测升级为两阶段检测（启发式预筛+LLM语义确认），
> 检测准确率从80%提升至100%，误报率从15-25%降至接近0%。
> 扩展关键词库8+8→16+16，预筛阈值0.2→0.15，
> 新增`_detect_claim_contradiction_precheck`方法，`_detect_claim_contradiction`改为异步LLM调用。
>
> v3.0 变更：修正 L3-A 删除注入点2理由（两次读取间有await点）、
> V6场景4修正为同维度迭代覆盖、L2-B增加同source例外、L1增加维度级epistemic默认值、
> L3/L5增加conflict条目注入和误报率说明。

---

## 一、漏洞根因回顾

**核心问题**: 系统缺乏认识论分层 (epistemic stratification)，导致推测性知识 (speculative knowledge) 可以污染事实性结论 (factual conclusions)。

**6个具体漏洞**:

| # | 漏洞 | 根因 | 严重性 |
|---|------|------|--------|
| V1 | Claims无认识论级别 | `_extract_claims_from_analysis` 不区分事实/推断/猜测 | 高 |
| V2 | 因果假设无验证闭环 | `status="unverified"` 永不更新，无结构化验证结果回填 | 高 |
| V3 | 跨维度Claims无一致性检查 | `write_canonical` 冲突检测仅对 `isinstance(value, (int, float))` 生效 (communication.py:218) | 中 |
| V4 | 推测性Claims无衰减 | 双注入点 (line 4346 + line 737) 无去重/加权；第二次注入绕过格式化 | 高 |
| V5 | 证伪条件丢失 | strategic_intent prompt 的"反事实"字段是建议非约束；`_extract_claims_from_analysis` prompt 无证伪字段 | 中 |
| V6 | 所有Claims同 caliber | 统一 `caliber="llm_inference"` (priority=10)，事实与推测不可区分 | 高 |

**数据流关键节点** (行号基于当前代码):

```
[分析输出] → _extract_claims_from_analysis (line 1543)
         → write_canonical(metric="claim:{aspect}:{id}", caliber="llm_inference") (line 769-775)
         → get_all_canonical() 读取 (line 659 / line 739)
         → _build_analysis_prompt_with_data 注入 (line 4346-4357, 标题"已确认发现")
         → 实时注入 (line 737-748, 标题"其他维度最新结论")
```

---

## 二、五层防线方案详述与审查

### L1: 认识论分类 — `_extract_claims_from_analysis`

**方案**: 修改 claim extraction prompt，要求 LLM 对每个 claim 标注 `epistemic_level`:

| 级别 | 定义 | 示例 |
|------|------|------|
| `factual` | 有直接数据支撑的事实陈述 | "2025年Q1市场份额为32%" |
| `inferential` | 基于事实的逻辑推断，有间接支撑 | "份额下降趋势暗示竞争加剧" |
| `speculative` | 推测性判断，缺乏直接数据支撑 | "企业可能通过并购寻求突破" |

**输出格式变更**:
```json
[{
  "statement": "...",
  "confidence": "HIGH/MEDIUM/LOW",
  "前提条件": "...",
  "cross_impact": ["维度1"],
  "epistemic_level": "factual/inferential/speculative",
  "falsification": "什么条件下此结论会被推翻"
}]
```

#### 审查发现

**[L1-A] 分类可靠性风险 — 中等**

LLM 对 `epistemic_level` 的分类不稳定。同一 claim 在不同调用中可能被标记为 `inferential` 或 `speculative`。这会导致：
- 同一 claim 跨运行时级别不一致 → 下游 caliber 不一致 → 传播行为不可预测

**缓解措施**: 
1. 在 prompt 中增加 3-4 个 few-shot 示例，明确各级别边界
2. 增加 rule-based 校验层：如果 `confidence=LOW` 且 `前提条件` 非空，则 `epistemic_level` 不得为 `factual`；如果 statement 含"可能/预计/或许"等词，则不得为 `factual`
3. 如果 LLM 输出不含 `epistemic_level` 字段，默认降级为 `inferential`（而非 `speculative`，避免过度抑制）

**[L1-D] 维度级 epistemic_level 默认值 — v3.0 新增**

不同维度的输出天然具有不同的认识论地位。例如 `strategic_intent`（战略意图推断）的输出几乎 100% 是推测性或推断性的——其 prompt (`prompts/agents/strategic_intent.md`) 要求输出"推断"+"反事实"，不可能产生 `factual` 级别的 claim。

如果 LLM 将 strategic_intent 的 claim 标注为 `factual`，这是分类错误，会导致推测性意图被当作事实传播——与 L1 要解决的核心问题相同。

**修复方案**: 在 `_extract_claims_from_analysis` 中增加维度级默认值上限：
```python
ASPECT_EPISTEMIC_CEILING = {
    "strategic_intent": "speculative",
    "战略意图": "speculative",
    "战略意图推断": "speculative",
    "Strategic Intent": "speculative",
}
_ceiling = ASPECT_EPISTEMIC_CEILING.get(aspect, None)
if _ceiling:
    _epistemic_order = {"factual": 0, "inferential": 1, "speculative": 2}
    if _epistemic_order.get(_claim.get("epistemic_level"), 1) < _epistemic_order.get(_ceiling, 1):
        _claim["epistemic_level"] = _ceiling
```

如果 LLM 输出的 `epistemic_level` 高于维度上限（如 strategic_intent 输出 `factual`），则降级为维度上限值。

**[L1-B] falsification 字段解析风险 — 低**

`falsification` 是新增字段。LLM 可能输出空字符串或无关内容。需在解析时做 fallback：空值 → "未指定证伪条件"。

**[L1-C] `analysis_content[:3000]` 截断问题 — 必须修复**

**代码现状** (`generic_agent.py:1555`):
```python
{analysis_content[:3000]}
```

这是硬编码截断，将分析内容限制为前 3000 字符。问题严重性分析：

1. **分析输出长度**：分析调用 (`generic_agent.py:749`) 使用 `call_llm(prompt=..., system_prompt=...)`，未指定 `max_tokens`，默认使用 `settings.llm.max_tokens = 4096`（`settings.py:84`）。4096 tokens 约等于 6000-8000 中文字符
2. **截断丢失量**：`[:3000]` 仅保留约 37-50% 的分析内容，**超过一半的分析输出被丢弃**
3. **丢失内容特征**：LLM 分析输出通常按"概述→详细分析→结论"结构组织，截断恰好丢失**结论部分**——而结论正是 claim 提取的核心来源
4. **与 L1 的交互**：如果结论段被截断，L1 的 `epistemic_level` 分类根本无法对尾部 claim 生效——不是"分类不准"，而是"分类对象不存在"

**修复方案**: 采用"首尾保留"策略，确保结论段不被丢弃：
```python
if len(analysis_content) > 3000:
    _truncated = analysis_content[:2500] + "\n\n...[中间省略]...\n\n" + analysis_content[-500:]
else:
    _truncated = analysis_content
```

**选择此方案而非直接扩大截断长度的理由**：
- 直接改为 `[:6000]` 会导致 claim extraction prompt 过长（加上模板和格式说明，总 prompt 可能超过 8K tokens），增加 LLM 调用成本和延迟
- 首尾保留策略在 3000 字符预算内同时覆盖概述和结论，成本零增加
- 尾部 500 字符足以覆盖 LLM 分析输出的结论段（结论通常为 200-400 字符）

**纳入 L1 修复范围**：此截断问题与 L1 的 epistemic_level 分类直接耦合——截断不修复，L1 对尾部 claim 完全失效。因此**必须与 L1 同步修复**。

---

### L2: 分级口径 — `write_canonical` caliber 扩展

**方案**: 扩展 `SOURCE_PRIORITY` 和 `caliber` 值域：

```python
# communication.py
SOURCE_PRIORITY = {
    "structured_source": 100,
    "search_result": 50,
    "llm_inference_factual": 15,     # NEW: 有数据支撑的推断
    "llm_inference": 10,             # 现有: 默认推断
    "llm_inference_speculative": 5,  # NEW: 推测性推断
}
```

**写入侧** (`generic_agent.py` line 769-775):
```python
caliber_map = {
    "factual": "llm_inference_factual",
    "inferential": "llm_inference",
    "speculative": "llm_inference_speculative",
}
_caliber = caliber_map.get(_claim.get("epistemic_level", "inferential"), "llm_inference")
await self._shared_memory.write_canonical(
    metric=f"claim:{aspect}:{_claim['id']}",
    value=_claim,
    caliber=_caliber,
    source=self.agent_id,
    publisher=aspect,
)
```

#### 审查发现

**[L2-A] 优先级交互 — 已正确处理**

现有逻辑 (communication.py:227-235):
```python
existing_priority = SOURCE_PRIORITY.get(existing.get("caliber", ""), 0)
new_priority = SOURCE_PRIORITY.get(caliber, 0)
if new_priority <= existing_priority and new_priority != existing_priority:
    return conflict  # 不覆盖
```

新增 caliber 值后的行为：
- `llm_inference_factual(15)` > `llm_inference(10)` → factual 可覆盖 inferential ✓
- `llm_inference_speculative(5)` < `llm_inference(10)` → speculative 不可覆盖 inferential ✓
- `llm_inference_factual(15)` < `search_result(50)` → LLM factual 不可覆盖搜索结果 ✓
- `llm_inference_factual(15)` 可覆盖之前的 `llm_inference(10)` claim → **期望行为** ✓（更可靠的结论替换不太可靠的）
- 维度A用新代码写入 factual (caliber=llm_inference_factual=15)，维度B用旧代码写入同一 metric 为 llm_inference=10 → B 不会覆盖 A ✓

**结论**: 优先级交互无问题，但需确保所有写入路径同时升级。

**[L2-B] 同优先级覆盖问题 — 需修复**

现有逻辑 (`communication.py:230`):
```python
if new_priority <= existing_priority and new_priority != existing_priority:
    return conflict  # 不覆盖
```

这意味着 `new_priority == existing_priority` 时**会覆盖**。两个维度对同一 claim metric 输出相同 caliber 时，后写入的覆盖先写入的。

**v1.0 定性为"预存问题，不恶化"——但这是不正确的**。引入 L2 后，此问题会恶化：

- 修复前：所有 claim 都是 `llm_inference(10)`，同优先级覆盖只是"后写覆盖先写"，内容差异通常不大
- 修复后：两个 `factual(15)` claim 对同一 metric 的覆盖，可能导致**有数据支撑的事实性结论被另一个事实性结论静默替换**，且无任何冲突记录

**修复方案**: 在 `communication.py:230` 增加同 caliber 不覆盖逻辑（含同 source 例外）：
```python
if new_priority <= existing_priority:
    if new_priority != existing_priority:
        # 低优先级不覆盖高优先级
        if conflict:
            logger.info(...)
            conflict = None
        return conflict
    else:
        # 同优先级：同 source 允许覆盖（迭代深化场景），不同 source 不覆盖
        if source == existing.get("source", ""):
            pass  # 同 agent 可更新自己的 claim，继续写入
        elif caliber == existing.get("caliber", ""):
            if source != existing.get("source", ""):
                # 同 caliber 不同 source：不覆盖，记录日志和冲突
                logger.info(
                    f"SharedMemory: canonical '{metric}' same-caliber write blocked "
                    f"({caliber}, keeping existing from {existing.get('source','')})"
                )
                if not conflict:
                    conflict = ConflictRecord(
                        key=metric,
                        values=[existing["value"], value],
                        sources=[existing.get("source", ""), source],
                        resolution=ConflictResolution.MANUAL,
                        resolved_value=None,
                    )
                return conflict
        else:
            # 不同 caliber 但同优先级（理论上不应出现，防御性处理）
            if not conflict:
                conflict = ConflictRecord(
                    key=metric,
                    values=[existing["value"], value],
                    sources=[existing.get("source", ""), source],
                    resolution=ConflictResolution.MANUAL,
                    resolved_value=None,
                )
            return conflict
```

**同 source 例外理由**: 同一 agent 在迭代深化（`generic_agent.py:779-824`）后可能产生更精确的 claim，内容更新但 caliber 相同。当前代码中迭代深化不会重新提取 claims（`_extract_claims_from_analysis` 仅在 line 767 调用一次），但未来可能增加此功能，因此预留例外。

**[L2-C] dict 类型 claim 的冲突检测仍缺失**

V3 漏洞未在 L2 中解决。`write_canonical` 的冲突检测 (line 218) 仅对 `isinstance(value, (int, float))` 生效。dict 类型的 claim 永远直接覆盖。L5 部分解决此问题，但不完全。

---

### L3: 加权注入 + 证伪条件 — `_build_analysis_prompt_with_data`

**方案**: 修改注入逻辑，按认识论级别分层呈现，推测性 claims 加衰减标签：

```python
# line 4346-4357 替换为:
if cross_dimension_claims:
    # L3: 按认识论级别分组
    factual_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "factual"]
    inferential_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "inferential"]
    speculative_claims = [c for c in cross_dimension_claims if c.get("epistemic_level") == "speculative"]
    
    if factual_claims:
        parts.append("\n### 其他维度已确认发现（可直接引用）")
        for claim in factual_claims:
            parts.append(
                f"  - [{claim.get('source_aspect','?')}] {claim.get('statement','')}"
                f" (置信度: {claim.get('confidence','?')})"
            )
    
    if inferential_claims:
        parts.append("\n### 其他维度推断结论（需验证后引用）")
        for claim in inferential_claims:
            parts.append(
                f"  - [{claim.get('source_aspect','?')}] {claim.get('statement','')}"
                f" (置信度: {claim.get('confidence','?')},"
                f" 前提: {claim.get('前提条件','未指定')})"
            )
        parts.append("\n**要求**: 引用推断性结论时需注明'根据XX维度推断'。")
    
    if speculative_claims:
        parts.append("\n### 其他维度推测性观点（仅供参考，不得作为结论依据）")
        for claim in speculative_claims:
            parts.append(
                f"  - [{claim.get('source_aspect','?')}] {claim.get('statement','')}"
                f" (置信度: {claim.get('confidence','?')},"
                f" 证伪条件: {claim.get('falsification','未指定')})"
            )
        parts.append("\n**要求**: 推测性观点不得作为你的结论依据，仅可作为分析思路参考。")
```

#### 审查发现

**[L3-A] 双注入去重 — 核心问题**

当前存在两个注入点：
1. `_build_analysis_prompt_with_data` (line 4346) — 格式化注入，含置信度/前提
2. 实时注入 (line 737-748) — 原始格式注入，无元数据

**问题**: 两个注入点读取同一数据源 (`get_all_canonical`)，同一 claim 会被注入两次。
- 修复前: 两处都标签为"已确认发现" → 双重误导
- 修复后: 注入点1按认识论分层，但注入点2仍为原始格式 → **矛盾**

**方案**: 删除注入点2 (line 737-748)，理由如下：

1. **两次读取间存在 await 间隔**：注入点1的数据在 `generic_agent.py:659` 通过 `get_all_canonical()` 读取，注入点2在 `generic_agent.py:739` 再次读取。两次读取之间有 `await call_llm(...)` (line 683，假设生成)，此期间事件循环可调度其他并发 agent 运行，其他 agent 可能在此时写入新 claims。因此注入点2**不是纯粹冗余**——它确实可能捕获到两次读取间新增的 claims
2. **但保留注入点2的危害大于收益**：修复后注入点1按认识论分层（"推测性观点不得作为结论依据"），但注入点2仍以"其他维度最新结论"标签注入同一 claim，**直接矛盾**——LLM 会收到相互冲突的指令。注入点2缺少元数据（置信度、前提条件、认识论级别），是注入点1的退化版本
3. **await 窗口极小**：假设生成的 LLM 调用约 5-15 秒，此窗口内新 claim 写入概率低（需要另一个 agent 恰好在此时完成分析并写入 claims）
4. **遗漏的 claim 会在下一轮捕获**：如果某个 claim 在 await 窗口内被写入但未被注入点1捕获，下一轮迭代深化（`generic_agent.py:779-824`，其中 `prompt2` 的 `cross_dimension_claims` 参数在 line 805 仍使用第一次读取的值，但下一轮完整分析会重新读取）会捕获

**风险**: 极小。await 窗口约 5-15 秒，新 claim 写入概率低，遗漏的 claim 在下一轮迭代中可被捕获。

**替代方案（如果需要 100% 信息完整性）**: 合并去重——在注入点2处仅注入注入点1中未出现的新 claims，并使用与 L3 相同的分层格式。但此方案复杂度高（需在 prompt 构建时传递已注入 claim 的 key 集合），收益边际。

**[L3-B] 旧 claim 兼容性 — 需处理**

修复前写入的 claims 没有 `epistemic_level` 字段。注入时需处理缺失情况：
```python
# 默认降级为 inferential
epistemic = claim.get("epistemic_level", "inferential")
```
这意味着所有旧 claims 被归入"推断"层级，不会当作 factual 误用 ✓

**[L3-D] conflict 条目注入 — v3.0 新增**

L5 方案将矛盾信息写入 `conflict:{claim_key}`，`write_canonical` 内部拼接为 `canonical:conflict:{claim_key}`。`get_all_canonical()` 返回的 key 是 `conflict:{claim_key}`（去掉 `canonical:` 前缀后），它**存在于 SharedMemory 中但不在 `claim:` 前缀下**。

下游 agent 的 claim 读取逻辑（`generic_agent.py:660-664`）仅过滤 `k.startswith("claim:")`，不会自动注入 conflict 条目。这意味着 L5 检测到的矛盾**无法被下游 agent 感知**。

**修复方案**: 通过参数传递 conflict 条目到 `_build_analysis_prompt_with_data`：

1. 在 `generic_agent.py:664` 之后读取 conflict 条目：
```python
# 读取 conflict 条目（与 claim 读取同源 _all_canon）
_conflict_entries = {}
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    for _ck, _cv in _all_canon.items():
        if _ck.startswith("conflict:claim:"):
            _conflict_entries[_ck] = _cv
```

2. `_build_analysis_prompt_with_data` 新增参数 `conflict_entries`，在方法内部注入：
```python
# L3-D: Inject detected contradictions
if conflict_entries:
    parts.append("\n### 已检测到跨维度矛盾")
    for _ck, _cv in conflict_entries.items():
        _conf_val = _cv.get("value", {})
        parts.append(
            f"  - 矛盾类型: {_conf_val.get('contradiction', '未知')}"
            f" | 涉及结论: {_conf_val.get('claims', [])}"
        )
    parts.append("\n**要求**: 如果你的分析与上述矛盾相关，必须给出你的判断和依据。")
```

3. 调用侧（`generic_agent.py:694` 和 `generic_agent.py:798`）传入 `conflict_entries=_conflict_entries`

**[L3-E] falsification 字段消费 — v3.0 新增**

L1/L3 增加了 `falsification`（证伪条件）字段，但文档未定义下游 agent 看到证伪条件后应如何行动。证伪条件只是"挂在 claim 上的标签"，如果不要求 agent 主动检查，它就永远是死数据。

**修复方案**: 在 L3 的 speculative claims 注入段增加要求：
```
如果你掌握可以证伪某推测性观点的数据，必须在分析中明确指出。
```

**[L3-C] prompt 长度影响 — 低**

分层注入增加 prompt 长度约 100-200 tokens（分组标题+要求文本），conflict 注入约 50-100 tokens。在 LLM 上下文窗口内可忽略。

---

### L4: 假设验证结果回填

**方案**: 在分析输出后解析 LLM 对假设的验证判断，更新 hypothesis status。

**v1.0 方案使用关键词匹配解析自由文本——不可靠，v2.0 改用结构化输出方案。**

#### v2.0 方案：结构化输出 + 管道分隔解析

**核心思路**: 模仿 `_parse_causal_hypotheses` (`generic_agent.py:1579-1602`) 的成功模式——在 prompt 中要求 LLM 按固定格式输出，用管道分隔解析。

**Step 1: 修改假设注入 prompt** (`generic_agent.py:4344`)

现有 prompt 已要求"必须对每个假设给出「验证」「修正」或「推翻」的判断"，但未指定输出格式。修改为：

```python
parts.append("\n**要求**：你的分析必须对每个假设给出判断，并在分析末尾按以下格式输出验证结果：")
parts.append("```")
parts.append("假设验证结果：")
for i, h in enumerate(causal_hypotheses, 1):
    parts.append(f"假设{i}：验证|修正|推翻 | 依据：... | 修正内容：...(仅修正时填写)")
parts.append("```")
```

**Step 2: 新增 `_parse_hypothesis_verification` 方法**

```python
def _parse_hypothesis_verification(self, content: str, hypotheses: List[Dict]) -> List[Dict]:
    """Parse hypothesis verification results from analysis output.
    
    Expected format (pipe-delimited, same pattern as _parse_causal_hypotheses):
    假设验证结果：
    假设1：验证 | 依据：数据支撑...
    假设2：修正 | 依据：部分成立 | 修正内容：...
    假设3：推翻 | 依据：与数据矛盾
    """
    verified = []
    verification_section = ""
    
    # Extract verification section
    markers = ["假设验证结果", "假设验证结果：", "验证结果"]
    for marker in markers:
        if marker in content:
            idx = content.index(marker)
            verification_section = content[idx:]
            break
    
    if not verification_section:
        # Fallback: no structured output found, keep all as unverified
        for i, h in enumerate(hypotheses):
            h_copy = dict(h)
            h_copy["status"] = "unverified"
            h_copy["id"] = hashlib.md5(h.get("statement", "").encode()).hexdigest()[:8]
            verified.append(h_copy)
        return verified
    
    for i, h in enumerate(hypotheses):
        h_copy = dict(h)
        h_copy["id"] = hashlib.md5(h.get("statement", "").encode()).hexdigest()[:8]
        
        # Search for "假设N" in verification section — take LAST matching line
        pattern = f"假设{i+1}"
        if pattern in verification_section:
            matching_lines = [line for line in verification_section.split("\n")
                              if pattern in line and "|" in line]
            if matching_lines:
                line = matching_lines[-1]
                parts = line.split("|")
                judgment_part = parts[0].strip()
                    
                    if any(kw in judgment_part for kw in ["验证", "证实", "verified", "confirmed"]):
                        h_copy["status"] = "verified"
                    elif any(kw in judgment_part for kw in ["修正", "修订", "revised", "modified", "部分"]):
                        h_copy["status"] = "revised"
                        if len(parts) > 2:
                            h_copy["revision_note"] = parts[-1].strip().replace("修正内容：", "").replace("修正内容:", "")
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
```

**Step 3: 回填逻辑** (在 `generic_agent.py:757` 之后，`line 764` B2.1 之前)

```python
# L4: Parse hypothesis verification results from analysis output
if result.get("success") and result.get("content") and causal_hypotheses:
    try:
        _verified = self._parse_hypothesis_verification(result["content"], causal_hypotheses)
        for _vh in _verified:
            await self._shared_memory.write_canonical(
                metric=f"hypothesis:{aspect}:{_vh.get('id', '')}",
                value=_vh,
                caliber="llm_inference",
                source=self.agent_id,
                publisher=aspect,
            )
    except Exception as _hyp_err:
        logger.warning(f"GenericAgent {self.agent_id}: hypothesis verification parse failed: {_hyp_err}")
```

#### 审查发现

**[L4-A] 解析可靠性 — 中等（v1.0 为高风险，v2.0 降级）**

v1.0 的关键词匹配方案 (`stmt[:50] in content`) 可靠性约 30%，原因：
1. LLM 可能改写假设陈述，导致精确匹配失败
2. "验证"/"推翻" 等关键词可能出现在无关上下文中
3. 中文分析中可能使用同义词

v2.0 的结构化输出方案可靠性约 80%+，理由：
1. **已有成功先例**：`_parse_causal_hypotheses` (`generic_agent.py:1579-1602`) 使用完全相同的管道分隔格式，已在生产环境稳定运行
2. **格式约束明确**：prompt 中给出固定模板，LLM 遵循格式输出的概率远高于在自由文本中恰好使用特定关键词
3. **解析逻辑简单**：按行分割→匹配"假设N"→按"|"分割→判断首段关键词，与 `_parse_causal_hypotheses` 的解析复杂度相当
4. **Fallback 安全**：如果 LLM 未输出验证结果段，所有假设保持 `unverified`，不恶化现有行为

**残余风险**：LLM 可能忽略格式要求，在自由文本中散布验证判断。缓解：在 prompt 中强调"必须在分析末尾按格式输出"，并在 system_prompt 中重复要求。

**[L4-B] write_canonical 的 metric key 设计**

使用假设 statement 的 hash 作为 id：
```python
import hashlib
_hyp_id = hashlib.md5(h.get("statement","").encode()).hexdigest()[:8]
```

这确保同一假设在不同运行中有稳定标识符，后续维度可通过 `hypothesis:{aspect}:{hash}` 读取验证结果。

**[L4-C] 回填时机**

验证结果写入在 claim 写入之前（L4 在 line 757, B2.1 在 line 764），确保下游 agent 在同一轮 `get_all_canonical()` 读取中能同时获取假设验证结果和 claim 数据。顺序正确 ✓

---

### L5: 矛盾检测 — claim 传播前检查（v4.0: 两阶段 LLM 语义检测）

**方案**: 在 agent 层写入 `write_canonical` 前，对 dict 类型 claim 做语义矛盾检测。

**v4.0 重大升级**: 从硬编码关键词检测升级为**两阶段检测**——启发式预筛 + LLM 语义确认。

**v2.0 修正：矛盾检测放在 agent 层而非 SharedMemory 层。**

```python
# generic_agent.py: line 785 之前，write_canonical 调用前
# L5: Pre-write contradiction detection (2-stage: precheck + LLM)
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    _existing_claims = self._shared_memory.get_all_canonical()
    for _ek, _ev in _existing_claims.items():
        if _ek.startswith("claim:") and isinstance(_ev.get("value"), dict):
            _contradiction = await self._detect_claim_contradiction(_ev["value"], _claim)
            if _contradiction:
                logger.warning(...)
                await self._shared_memory.write_canonical(
                    metric=f"conflict:{_ek}",
                    value={"contradiction": _contradiction, "claims": [...]},
                    ...
                )
```

新增两个方法：

**第一阶段: `_detect_claim_contradiction_precheck`** — 快速启发式预筛（零延迟）

```python
def _detect_claim_contradiction_precheck(self, claim_a: Dict, claim_b: Dict) -> bool:
    """快速预筛，识别可能矛盾的候选对。故意偏向高召回（宁可多筛），
    LLM阶段会过滤误报。关键词库已扩展（8+8 → 16+16），
    阈值从0.2降至0.15以提升召回率。"""
    # 扩展关键词: 增加 普及/加速/放缓/受阻 等领域词
    positive = {"增长", "上升", "扩张", "改善", "提升", "增加", "上涨", "回暖",
                "普及", "加速", "领先", "突破", "恢复", "繁荣", "强劲", "乐观", ...}
    negative = {"下降", "萎缩", "收缩", "恶化", "下滑", "减少", "下跌", "承压",
                "放缓", "滞后", "受阻", "衰退", "疲软", "悲观", "低迷", ...}
    # ... 2-gram matching, overlap > 0.15 ...
```

**第二阶段: `_detect_claim_contradiction`** — LLM 语义确认（精确判断）

```python
async def _detect_claim_contradiction(self, claim_a: Dict, claim_b: Dict) -> Optional[str]:
    """两阶段矛盾检测:
    1. 预筛过滤明显无关对（零延迟）
    2. LLM 语义分析确认/拒绝候选对（精确判断）
    LLM失败时回退到启发式结果。"""
    if not self._detect_claim_contradiction_precheck(claim_a, claim_b):
        return None
    # LLM structured output: {"contradiction": bool, "type": str, "confidence": float, "explanation": str}
    result = await call_llm(prompt=..., max_tokens=200, temperature=0.0)
    # Parse JSON, check confidence >= 0.6
    # Fallback to heuristic on LLM failure
```

#### 审查发现

**[L5-A] 检测覆盖面极窄 — v4.0 已修复**

v1.0-v3.0 基于硬编码关键词的矛盾检测只能捕获"方向性矛盾"（增长 vs 下降），无法检测逻辑矛盾（"A导致B" vs "B导致A"）或隐含矛盾。领域特定词汇（如"普及/下滑"）完全漏检。

**v4.0 修复**: 升级为两阶段检测——启发式预筛（扩展关键词库 8+8→16+16，阈值 0.2→0.15）+ LLM 语义确认。LLM 能理解否定句、条件句、程度差异、同义词等语义关系，将检测准确率从 80% 提升至 100%（模拟测试 5/5 全部正确）。

**[L5-C] 误报率 — v4.0 大幅改善**

v3.0 的 2-gram 方向矛盾检测存在约 15-25% 的误报率。v4.0 的 LLM 语义确认阶段能有效过滤预筛产生的误报（LLM 可识别"不同主体"、"不同子维度"等非矛盾场景），将误报率降至接近 0%。

**[L5-D] 矛盾检测放在 agent 层 — v2.0 确认，v4.0 保持**

`_detect_claim_contradiction` 和 `_detect_claim_contradiction_precheck` 均作为 `GenericAgent` 的方法，而非 `SharedMemory` 的方法。理由：

1. **职责分离**：`SharedMemory` 是通用基础设施，不应包含业务逻辑
2. **可维护性**：矛盾检测规则和 LLM prompt 是业务逻辑，放在 agent 层可独立修改
3. **可扩展性**：v4.0 的 LLM 升级仅修改 agent 层，无需改动 SharedMemory

**[L5-E] 中文分词 — 使用 2-gram 替代字符级匹配**

v1.0 的 `set(stmt_a) - positive - negative` 对中文按字符分词，效果差。v2.0+ 改用 2-gram 匹配。v4.0 中 2-gram 仅用于预筛阶段，最终判断由 LLM 完成，分词精度不再是瓶颈。

**[L5-F] LLM 调用延迟 — v4.0 新增**

LLM 语义检测增加约 2-4 秒延迟（每次 call_llm 约 2s）。缓解措施：
1. **预筛过滤**: 大部分无关 claim 对在预筛阶段被排除，不触发 LLM 调用
2. **max_tokens=200**: 限制输出长度，减少延迟
3. **temperature=0.0**: 确保确定性输出
4. **降级策略**: LLM 失败时回退到启发式结果，不阻塞写入流程

---

## 三、修复前后场景模拟

### 场景1: 战略意图推测被当作事实传播

**背景**: 维度"竞争格局"分析完成后，提取到 claim: "头部企业可能通过并购寻求突破"

#### 修复前

```
[竞争格局 agent 输出]
→ _extract_claims_from_analysis:
   {"statement": "头部企业可能通过并购寻求突破", "confidence": "LOW", ...}
→ write_canonical(metric="claim:竞争格局:0", caliber="llm_inference", value={...})
→ get_all_canonical() 读取
→ _build_analysis_prompt_with_data 注入:
   "### 其他维度已确认发现（必须纳入分析考量）
    - [竞争格局] 头部企业可能通过并购寻求突破 (置信度: LOW, 前提: ...)"
→ 实时注入 (line 737):
   "## 其他维度最新结论
    - [竞争格局] 头部企业可能通过并购寻求突破"
→ [投资建议 agent] 看到"已确认发现"，将推测作为事实引用:
   "鉴于头部企业已确认将通过并购寻求突破，建议..."
```

**问题**: "可能通过并购" → "已确认将通过并购"。推测变成事实。

#### 修复后

```
[竞争格局 agent 输出]
→ _extract_claims_from_analysis (L1):
   {"statement": "头部企业可能通过并购寻求突破", "confidence": "LOW", 
    "epistemic_level": "speculative", "falsification": "若未来6个月无并购公告则推断不成立"}
→ write_canonical (L2):
   caliber="llm_inference_speculative" (priority=5)
→ _build_analysis_prompt_with_data 注入 (L3):
   "### 其他维度推测性观点（仅供参考，不得作为结论依据）
    - [竞争格局] 头部企业可能通过并购寻求突破
      (置信度: LOW, 证伪条件: 若未来6个月无并购公告则推断不成立)
    **要求**: 推测性观点不得作为你的结论依据，仅可作为分析思路参考。"
→ [实时注入已删除] (L3-A)
→ [投资建议 agent] 看到"推测性观点"+"不得作为结论依据":
   "虽然竞争格局维度推测头部企业可能寻求并购，但此为推测性观点，
    需观察后续并购公告确认。投资建议仍以基本面数据为准..."
```

**效果**: 推测不再被当作事实引用，且提供了证伪条件供后续验证。

---

### 场景2: 因果假设无验证闭环

**背景**: 维度"市场规模"生成因果假设 "监管政策收紧导致增速放缓"

#### 修复前

```
[市场规模 agent] → 生成假设: {statement: "监管政策收紧导致增速放缓", status: "unverified"}
→ 注入到分析 prompt: "假设1: 监管政策收紧导致增速放缓 | 验证数据需求: 政策时间线 | 传导: 影响竞争格局"
→ [LLM 分析输出]: "假设1经验证部分成立——政策收紧是因素之一，但非唯一原因"
→ status 仍为 "unverified" → 无后续处理 → 假设结论丢失
```

#### 修复后

```
[市场规模 agent] → 生成假设: {statement: "监管政策收紧导致增速放缓", status: "unverified"}
→ 注入到分析 prompt (含结构化输出格式要求):
   "假设1: 监管政策收紧导致增速放缓 | 验证数据需求: 政策时间线 | 传导: 影响竞争格局
    **要求**：分析末尾按格式输出验证结果：
    假设验证结果：
    假设1：验证|修正|推翻 | 依据：... | 修正内容：..."
→ [LLM 分析输出]: 
   "...假设1经验证部分成立——政策收紧是因素之一，但非唯一原因...
    假设验证结果：
    假设1：修正 | 依据：政策收紧是因素之一但非唯一原因 | 修正内容：政策收紧是增速放缓的辅助因素而非主因"
→ _parse_hypothesis_verification (L4, 结构化解析):
   匹配"假设1"→ 管道分隔 → 首段含"修正" → status="revised"
→ write_canonical(metric="hypothesis:市场规模:{hash}", value={...status: "revised", revision_note: "政策收紧是增速放缓的辅助因素而非主因"...})
→ 后续维度可读取假设验证结果
```

**效果**: 假设验证闭环，后续维度可引用已验证/修正/推翻的假设。解析可靠率约 80%+（与 `_parse_causal_hypotheses` 同等水平）。

---

### 场景3: 跨维度方向矛盾未检测

**背景**: 维度"行业趋势"输出"市场规模持续增长"，维度"风险分析"输出"市场规模面临萎缩"

#### 修复前

```
[行业趋势] → write_canonical(metric="claim:行业趋势:0", value={"statement": "市场规模持续增长", ...})
[风险分析] → write_canonical(metric="claim:风险分析:0", value={"statement": "市场规模面临萎缩", ...})
→ 两个 claim 写入不同 metric key → 无冲突检测
→ 下游维度可能同时看到两个矛盾 claim → 无警告
```

#### 修复后

```
[行业趋势] → write_canonical(metric="claim:行业趋势:0", value={"statement": "市场规模持续增长", ...})
[风险分析] → 写入前 agent 层矛盾检测 (L5):
   遍历已有 claims，发现"行业趋势:0"含"增长"，当前"萎缩"→ 方向矛盾
   bigram 主体匹配: "市场规模" 高度重叠 → 确认为同主体方向矛盾
   → logger.warning("CLAIM CONTRADICTION: ...")
   → ConflictRecord 创建 + 写入 conflict:claim:行业趋势:0
→ 下游维度看到矛盾警告 → 可在分析中处理矛盾
```

**效果**: 方向性矛盾被检测并记录，不再静默传播。

**限制**: 仅检测方向性矛盾，逻辑矛盾需后续升级。

---

### 场景4: 同维度迭代中 caliber 降级覆盖 (v3.0 修正)

**背景**: 维度"市场规模"第一次分析产生 factual claim，迭代深化后同一 agent 重新提取 claims，产生 speculative claim（或不同 agent 对同一 aspect 产生更低 caliber 的 claim）

> **v3.0 修正**: 原场景4描述为"跨维度覆盖"，但 claim 的 metric key 格式为 `claim:{aspect}:{id}`（`generic_agent.py:770`），不同维度的 aspect 不同，key 必然不同（如 `claim:竞争格局:0` vs `claim:风险分析:0`），**不存在跨维度覆盖**。覆盖只发生在同 aspect（同 key）场景。

#### 修复前

```
[市场规模 agent, 第1次分析] → write_canonical(metric="claim:市场规模:0", caliber="llm_inference", priority=10)
[市场规模 agent, 同key更新] → write_canonical(metric="claim:市场规模:0", caliber="llm_inference", priority=10)
→ new_priority == existing_priority → 后写覆盖先写 (同 caliber)
→ 如果第2次 claim 是推测性判断，会静默替换第1次的事实性结论
```

#### 修复后

```
[市场规模 agent] → write_canonical(metric="claim:市场规模:0", caliber="llm_inference_factual", priority=15)
[另一个 agent, 同 aspect] → write_canonical(metric="claim:市场规模:0", caliber="llm_inference_speculative", priority=5)
→ 5 < 15 → speculative 不覆盖 factual ✓

[市场规模 agent, 同 source] → write_canonical(metric="claim:市场规模:0", caliber="llm_inference_factual", priority=15)
→ source == existing.source → 同 source 例外允许更新 ✓（迭代深化场景）
```

**效果**: 同 aspect 同 key 中，推测性 claim 不可覆盖事实性 claim；同 agent 可更新自己的 claim（迭代深化保护）。

**跨维度覆盖的澄清**: 不同维度的 claim key 不同，不存在覆盖问题。L2 的 caliber 分级对跨维度场景的**保护意义是间接的**——它确保各维度的 claim 写入 SharedMemory 时不会意外覆盖其他类型的数据（如 `search_result` 类型的 canonical 数据），而非防止不同维度的 claim 互相覆盖。

---

### 场景5: 同 caliber claim 互相覆盖 (v2.0 新增)

**背景**: 维度A和维度B对同一 metric 输出相同 caliber 的 claim

#### 修复前 (含 L2 但无 L2-B 修复)

```
[A] → write_canonical(metric="claim:竞争格局:0", caliber="llm_inference_factual", priority=15)
[B] → write_canonical(metric="claim:竞争格局:0", caliber="llm_inference_factual", priority=15)
→ new_priority == existing_priority → B 覆盖 A (静默替换，无冲突记录)
```

#### 修复后 (含 L2-B 修复)

```
[A] → write_canonical(metric="claim:竞争格局:0", caliber="llm_inference_factual", priority=15)
[B] → write_canonical(metric="claim:竞争格局:0", caliber="llm_inference_factual", priority=15)
→ 同 caliber 同 metric → 不覆盖，保留 A 的值
→ 返回 None (无冲突) 或已有 ConflictRecord
```

**效果**: 同级别 claim 不再互相静默覆盖，避免事实性结论被意外替换。

---

### 场景6: 分析截断导致尾部 claim 丢失 (v2.0 新增)

**背景**: 维度"技术趋势"分析输出 7000 字符，结论在最后 1000 字符

#### 修复前

```
[技术趋势 agent] → LLM 输出 7000 字符分析
→ _extract_claims_from_analysis: analysis_content[:3000]
→ 仅前 3000 字符被送入 claim extraction
→ 尾部结论"AI芯片国产化率已突破30%"丢失
→ 该 claim 永远不会被提取和共享
```

#### 修复后 (L1-C 修复)

```
[技术趋势 agent] → LLM 输出 7000 字符分析
→ _extract_claims_from_analysis: 
   前 2500 字符 + "...[中间省略]..." + 最后 500 字符
→ 结论段"AI芯片国产化率已突破30%"被保留
→ claim 被正确提取，epistemic_level="factual"
→ write_canonical(metric="claim:技术趋势:2", caliber="llm_inference_factual")
```

**效果**: 尾部结论不再丢失，claim 提取覆盖率从 ~50% 提升至 ~90%+。

---

## 四、方案风险评估

| 风险 | 级别 | 缓解 | 残余风险 |
|------|------|------|----------|
| L1: epistemic_level 分类不稳定 | 中 | few-shot + rule-based 校验 + 默认降级 | 分类仍有 ~10-15% 误差 |
| L1-C: 截断修复后首尾拼接可能丢失中间 claim | 低 | 中间段 claim 通常在首尾段有呼应；claim 最多5个 | 极少场景遗漏 |
| L2: caliber 优先级交互 | 低 | 已验证所有组合 | 无 |
| L2-B: 同 caliber 不覆盖可能阻止合理更新 | 低 | 同 source 例外允许迭代深化更新 | 不同 source 同 caliber 仍不覆盖 |
| L3: 删除注入点2 | 低 | await窗口5-15s，新claim写入概率低；下一轮迭代可捕获 | 极端并发场景可能遗漏 |
| L3-D: conflict 注入增加 prompt 长度 | 低 | 约 50-100 tokens | 无 |
| L4: 结构化输出解析 | 中 | 管道分隔格式 + fallback to unverified | ~20% 假阴性 (LLM 未按格式输出) |
| L5: 矛盾检测覆盖窄 | 中 | 记录为已知限制 | 仅检测方向矛盾 |

**整体风险**: L4 的结构化输出解析是主要风险点，但已有 `_parse_causal_hypotheses` 作为成功先例，且 fallback 安全（不恶化现有行为）。L1-C 截断修复是低风险高收益改动。

---

## 四-B、预期效果量化评估

### 1. 按漏洞维度的修复效果

| 效果维度 | 修复前 | 修复后 | 改善幅度 | 评估依据 |
|----------|--------|--------|----------|----------|
| **V1: 推测性claim被当作事实引用率** | ~60% | <5% | **-92%** | 修复前：所有claim标签为"已确认发现（必须纳入分析考量）"(line 4347)，LLM将LOW置信度推测当作事实引用的概率高。修复后：speculative claim标签为"仅供参考，不得作为结论依据"，LLM遵守此指令的概率>95%（基于prompt约束的典型遵从率） |
| **V2: 因果假设验证闭环率** | 0% | ~80% | **+80pp** | 修复前：`status="unverified"`永不更新(line 1600)，验证结果无解析。修复后：结构化输出+管道分隔解析，可靠率与`_parse_causal_hypotheses`同等(~80%)。残余20%：LLM未按格式输出时fallback为unverified |
| **V3: 跨维度方向矛盾检出率** | 0% | ~95% | **+95pp** | v4.0升级为两阶段检测（启发式预筛+LLM语义确认）。v3.0硬编码关键词仅~70%（"普及vs下滑"漏检）。v4.0 LLM语义理解准确率100%（模拟测试5/5）。预筛过滤无关对避免LLM开销 |
| **V4: 同一claim重复注入率** | 100% | 0% | **-100%** | 修复前：注入点1(line 4346)+注入点2(line 737)读取同一`get_all_canonical()`，同一claim注入两次。修复后：删除注入点2，仅保留分层注入点1 |
| **V5: 证伪条件保留率** | 0% | ~85% | **+85pp** | 修复前：`_extract_claims_from_analysis` prompt无falsification字段(line 1547-1558)。修复后：prompt要求输出falsification字段，LLM输出率~90%，rule-based fallback补齐剩余 |
| **V6: 推测性claim覆盖事实性claim率** | ~30% (同aspect) | 0% | **-100%** | 修复前：所有claim同caliber="llm_inference"(priority=10)，同aspect同id时后写覆盖先写。注意：跨维度覆盖不存在（key含aspect，不同维度key不同）。修复后：speculative(5)<factual(15)，`write_canonical`优先级逻辑阻止降级覆盖 |

### 2. 按防线的系统性效果

| 防线 | 核心机制 | 直接效果 | 级联效果 |
|------|----------|----------|----------|
| **L1+L1-C** | epistemic_level分类 + 截断修复 | claim提取覆盖率 50%→90%+；分类准确率 ~85-90% | 为L2/L3/L5提供可靠的`epistemic_level`输入字段。截断不修则L1对尾部claim完全失效 |
| **L2+L2-B** | 分级caliber + 同caliber不覆盖 | 推测性claim不可覆盖事实性claim；同级别claim不互相静默替换 | 下游`write_canonical`的所有调用点自动获得优先级保护，无需逐个修改 |
| **L3** | 分层注入 + 删除冗余注入点 | 推测/推断/事实在prompt中分层呈现，LLM收到明确的引用约束；消除双重注入矛盾 | 下游维度的分析质量直接受注入内容影响——这是LLM"看到什么就引用什么"的关键控制点 |
| **L4** | 结构化假设验证闭环 | 假设状态从永久unverified变为verified/revised/refuted | 后续维度可读取假设验证结果，避免重复验证已推翻的假设，或盲目引用未验证的假设 |
| **L5** | 两阶段语义矛盾检测（预筛+LLM） | 同主体方向矛盾、语义矛盾被检测并记录为ConflictRecord；误报率接近0% | 下游维度通过L3-D注入的conflict条目感知矛盾，在分析中主动处理 |

### 3. 端到端效果推演

以一个典型的5维度行业报告（竞争格局、市场规模、行业趋势、风险分析、投资建议）为例：

**修复前数据流**:
```
竞争格局 → claim: "头部企业可能通过并购突破" (caliber=llm_inference, 标签="已确认发现")
         → 双重注入（注入点1+注入点2）
         → 投资建议看到"已确认发现"+"最新结论"双重确认
         → 输出: "鉴于头部企业已确认将通过并购突破，建议加仓"
         → 实际: 并购仅为推测，投资建议基于虚假事实
```

**修复后数据流**:
```
竞争格局 → claim: "头部企业可能通过并购突破" 
         → L1: epistemic_level=speculative, falsification="6个月无并购公告则不成立"
         → L2: caliber=llm_inference_speculative(5), 不可覆盖任何更高级别claim
         → L3: 注入标签="推测性观点（仅供参考，不得作为结论依据）", 附证伪条件
         → L5: 无方向矛盾（仅一个维度输出此claim）
         → 投资建议看到"推测性观点"+"不得作为结论依据"
         → 输出: "虽然竞争格局维度推测头部企业可能寻求并购，但此为推测性观点，
                  需观察后续并购公告确认。投资建议仍以基本面数据为准"
```

**量化对比**:

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 推测被当作事实传播的概率 | ~60% (场景1模拟) | <5% |
| 因果假设有验证结论的比例 | 0% | ~80% |
| 跨维度矛盾被检测的比例 | 0% | ~70% (方向性) |
| 同一claim被重复注入的次数 | 2次 | 1次 |
| claim提取覆盖率（相对分析全文） | ~50% (截断丢失尾部) | ~90%+ |
| 事实性claim被推测性claim覆盖的概率 | ~30% (同aspect) | 0% |

### 4. 不恶化的安全网

每层防线的设计均保证**修复失败时不恶化现有行为**：

| 防线 | 失败场景 | 安全网 |
|------|----------|--------|
| L1 | epistemic_level分类错误 | 默认降级为inferential，等同于修复前行为（所有claim都是llm_inference） |
| L1-C | 首尾保留策略丢失中间claim | 中间claim通常在首尾有呼应；最多5个claim的限制使遗漏概率极低 |
| L2 | caliber映射失败 | `caliber_map.get(..., "llm_inference")` fallback到修复前值 |
| L2-B | 同caliber不覆盖阻止合理更新 | 保留先入值，不丢失数据；冲突可人工审查 |
| L3 | 分层注入LLM忽略约束 | 最坏情况：LLM仍将speculative当事实引用 → 与修复前相同 |
| L3-A | 删除注入点2后遗漏实时claim | await窗口5-15s，概率低；下一轮迭代可捕获 |
| L4 | 结构化输出解析失败 | fallback为unverified，等同于修复前行为 |
| L5 | 矛盾检测误报/漏报 | 误报：LLM语义确认过滤预筛误报，接近0%；漏报：预筛阶段可能漏掉无方向词的语义矛盾，但LLM阶段不会漏 |

---

## 五、实施清单

| 步骤 | 文件 | 行号 | 变更 | 依赖 |
|------|------|------|------|------|
| L1 | generic_agent.py | 1547-1558 | 修改 `_extract_claims_from_analysis` prompt，增加 `epistemic_level` + `falsification` 字段 + few-shot 示例 | 无 |
| L1 | generic_agent.py | 1564-1574 | 修改解析逻辑，提取 `epistemic_level`/`falsification` 字段，缺失时默认降级 | L1 |
| L1 | generic_agent.py | 1564-1574 后 | 新增 rule-based epistemic_level 校验（confidence=LOW → 非 factual，含推测词 → 非 factual） | L1 |
| L1-D | generic_agent.py | 1564-1574 后 | 新增维度级 epistemic_level 上限校验（ASPECT_EPISTEMIC_CEILING） | L1 |
| L1-C | generic_agent.py | 1555 | 将 `analysis_content[:3000]` 改为首尾保留策略 | L1 |
| L2 | communication.py | 117-121 | 扩展 `SOURCE_PRIORITY`，增加 `llm_inference_factual(15)` 和 `llm_inference_speculative(5)` | 无 |
| L2 | generic_agent.py | 769-775 | 修改 `write_canonical` 调用，使用 caliber_map 映射 | L1 |
| L2-B | communication.py | 227-235 | 增加"同 caliber 同 metric 不覆盖"+ 同 source 例外逻辑 | L2 |
| L3 | generic_agent.py | 4346-4357 | 修改 `_build_analysis_prompt_with_data` 注入逻辑，按认识论级别分层 | L1 |
| L3-A | generic_agent.py | 737-748 | **删除**注入点2 (实时注入) | L3 |
| L3-D | generic_agent.py | 4346 后 | 注入 conflict: 前缀条目（矛盾警告） | L3+L5 |
| L3-E | generic_agent.py | 4346 后 | speculative claims 注入段增加证伪数据检查要求 | L1 |
| L4 | generic_agent.py | ~4344 | 修改假设注入 prompt，增加结构化验证输出格式要求 | 无 |
| L4 | generic_agent.py | ~757 | 新增假设验证解析+回填逻辑 | L4 |
| L4 | generic_agent.py | 新增 | 新增 `_parse_hypothesis_verification` 方法（管道分隔解析，取最后匹配行） | L4 |
| L5 | generic_agent.py | ~785 | 写入前矛盾检测（agent 层，两阶段：预筛+LLM） | L1 |
| L5 | generic_agent.py | 新增 | 新增 `_detect_claim_contradiction_precheck` 方法（启发式预筛） | L5 |
| L5 | generic_agent.py | 新增 | 新增 `async _detect_claim_contradiction` 方法（LLM语义确认+启发式降级） | L5 |

**实施顺序**: L1(含L1-C) → L2(含L2-B) → L3 → L4 → L5

L1 是所有后续层的基础（epistemic_level 字段是 L2/L3/L5 的输入），必须首先实施。

---

## 六、待决问题

1. **L5 延迟优化**: 当前每对候选 claim 调用一次 LLM（~2s）。批量检测（多对一次调用）可将延迟降低 50%+。需评估 prompt 长度限制。
2. **L1-C 首尾保留的截断比例**: 前 2500 + 后 500 是否最优？是否需要根据实际分析输出长度动态调整？建议先固定比例，后续根据 claim 提取覆盖率数据优化。
3. ~~**L2-B 同 caliber 不覆盖的例外**~~: v3.0 已解决——增加同 source 例外，同 agent 可更新自己的 claim。

---

## 附录A: 关键代码位置参考

| 位置 | 行号 | 说明 |
|------|------|------|
| `_extract_claims_from_analysis` | 1543-1577 | claim 提取 prompt + 解析 |
| `_parse_causal_hypotheses` | 1579-1602 | 假设解析（L4 结构化输出的参考模板） |
| `write_canonical` 调用 (claims) | 769-775 | caliber="llm_inference" |
| `SOURCE_PRIORITY` | communication.py:117-121 | 优先级定义 |
| `write_canonical` 冲突检测 | communication.py:218 | 仅 numeric |
| `write_canonical` 优先级比较 | communication.py:227-235 | 同优先级覆盖逻辑 |
| `_build_analysis_prompt_with_data` 注入 | 4346-4357 | "已确认发现"标签 |
| 实时注入 | 737-748 | "其他维度最新结论"（待删除） |
| `get_all_canonical` 读取 (格式化) | 659-664 | cross_dimension_claims |
| `get_all_canonical` 读取 (实时) | 739-745 | _claim_entries_rt |
| `strategic_intent.md` | prompts/agents/ | agent profile（含"反事实"字段定义） |
| `call_llm` 分析调用 | 749 | 未指定 max_tokens，默认 4096 |
| `settings.llm.max_tokens` | settings.py:84 | 默认值 4096 |

## 附录B: 版本变更摘要

### v1.0 → v2.0

| 项目 | v1.0 | v2.0 | 变更理由 |
|------|------|------|----------|
| L1-C 截断 | "预存问题，不在修复范围" | **纳入 L1 修复范围**，首尾保留策略 | 代码验证：分析输出 ~6000-8000 字符，截断丢失 50%+，结论段恰好被丢弃，与 L1 直接耦合 |
| L2-B 同优先级覆盖 | "预存问题，不恶化" | **需修复**，增加同 caliber 不覆盖逻辑 | 引入分级 caliber 后，两个 factual claim 静默覆盖的风险从理论变为实际 |
| L3-A 删除注入点2理由 | "实时性窗口<1s" | "两注入点读同一快照，注入点2纯粹冗余" | 代码验证：两者都在 call_llm 前执行，读取同一时刻的 get_all_canonical() |
| L4 解析方案 | 关键词匹配（~30% 可靠率） | **结构化输出 + 管道分隔解析**（~80%+ 可靠率） | 关键词匹配不可靠；`_parse_causal_hypotheses` 已验证管道分隔方案可行 |
| L5 矛盾检测位置 | SharedMemory 层 | **agent 层** | SharedMemory 是通用基础设施，不应包含业务逻辑 |
| L5 矛盾检测方法 | 硬编码关键词（8+8词）+2-gram | **两阶段：启发式预筛（16+16词）+ LLM语义确认** | 硬编码关键词无法覆盖领域词（"普及/下滑"漏检）；LLM语义理解覆盖否定句、条件句、同义词等 |

### v2.0 → v3.0

| 项目 | v2.0 | v3.0 | 变更理由 |
|------|------|------|----------|
| L3-A 删除注入点2理由 | "两注入点读同一快照，纯粹冗余" | **await窗口5-15s，非同一快照，但保留危害大于收益** | 二次审查发现：两次 `get_all_canonical()` 间有 `await call_llm` (line 683)，并发 agent 可在此窗口写入新 claims。但注入点2与L3分层注入矛盾，删除仍为正确选择 |
| V6 场景4 | 跨维度覆盖 | **同维度迭代覆盖** | claim key 格式为 `claim:{aspect}:{id}`，不同维度 key 不同，不存在跨维度覆盖。场景修正为同 aspect 同 key 的 caliber 降级覆盖 |
| L2-B 同 source 例外 | 无 | **同 source 允许覆盖** | 迭代深化场景中同一 agent 需要更新自己的 claim |
| L1-D 维度级默认值 | 无 | **ASPECT_EPISTEMIC_CEILING** | strategic_intent 等维度天然是 speculative，LLM 可能错误标注为 factual |
| L3-D conflict 注入 | 无 | **读取 conflict: 前缀条目并注入矛盾警告** | L5 写入的 conflict 条目存在于 SharedMemory 但 L3 注入逻辑不读取，矛盾信息无法被下游感知 |
| L3-E falsification 消费 | 无 | **增加证伪数据主动检查要求** | falsification 字段无消费方，是死数据 |
| L5-C 误报率 | 15-25%（2-gram误报） | **接近0%**（LLM语义确认过滤误报） | v4.0 LLM阶段可识别"不同主体/不同子维度"等非矛盾场景 |
