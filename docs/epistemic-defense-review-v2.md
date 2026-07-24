# 认识论防线 v2.0 二次审查报告

> **审查人**: opencode | **日期**: 2026-07-01 | **审查对象**: epistemic-defense-audit.md v2.0
> 
> 本报告对 v2.0 设计方案进行逐项验证，所有代码引用均已对照实际代码确认。

---

## 一、代码引用准确性验证

| 文档引用 | 实际代码 | 准确? |
|----------|----------|-------|
| `_extract_claims_from_analysis` line 1543 | `generic_agent.py:1543` | ✓ |
| `analysis_content[:3000]` line 1555 | `generic_agent.py:1555` | ✓ |
| `caliber="llm_inference"` line 772 | `generic_agent.py:772` | ✓ |
| `SOURCE_PRIORITY` communication.py:117 | `communication.py:117-121` | ✓ |
| `write_canonical` conflict detection line 218 | `communication.py:218` | ✓ |
| `write_canonical` priority logic line 227-235 | `communication.py:227-235` | ✓ |
| 注入点1 `_build_analysis_prompt_with_data` line 4346 | `generic_agent.py:4346` | ✓ |
| 注入点2 实时注入 line 737 | `generic_agent.py:737-748` | ✓ |
| `get_all_canonical` 格式化读取 line 659 | `generic_agent.py:659` | ✓ |
| `settings.llm.max_tokens = 4096` | `settings.py:84` | ✓ |
| `_parse_causal_hypotheses` line 1579 | `generic_agent.py:1579-1602` | ✓ |
| `ConflictResolution.MANUAL` | `result_aggregator.py:47` | ✓ |

**结论**: 所有代码引用均准确。

---

## 二、L3-A "同一快照" 论断的致命错误

### 文档声称 (Section L3-A):
> "两者都在 `call_llm` (line 749) 之前执行，读取的是 SharedMemory 在同一时刻的状态——**不存在'实时性'差异**"

### 实际情况:

这是一个**事实性错误**。代码流程为：

```
line 659: _all_canon = self._shared_memory.get_all_canonical()   ← 第1次读取
line 664: cross_dimension_claims.append(_claim_val)
...
line 694: prompt = self._build_analysis_prompt_with_data(..., cross_dimension_claims=cross_dimension_claims, ...)
...
line 739: _all_canon_rt = self._shared_memory.get_all_canonical()  ← 第2次读取
line 748: prompt += f"\n\n## 其他维度最新结论\n{_cs_rt}\n"
line 749: result = await call_llm(prompt=prompt, system_prompt=system_prompt)
```

两次 `get_all_canonical()` 调用之间，存在**多个 await 点**：
- line 683: `hypothesis_result = await call_llm(...)` — 假设生成调用
- line 692: `system_prompt = self._get_professional_role_prompt(aspect)` — 可能是同步调用但仍有间隙

**Agent 是通过 `asyncio.gather` 并发执行的**（`agent_coordinator.py:617`），当一个 agent 在 await 等待 LLM 响应时，事件循环会调度其他 agent 运行，其他 agent 可能在此时写入新的 claims。

**修正后的结论**: 注入点2 确实有增量价值——它可以捕获两次读取之间其他 agent 写入的新 claims。但这不是删除注入点2的充分理由，而是需要**合并去重**而非简单删除。

### 建议修正方案:

**方案 A (推荐): 合并去重 — 保留实时性，消除重复**

```python
# 在注入点2处，仅注入注入点1中未出现的claims
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    _all_canon_rt = self._shared_memory.get_all_canonical()
    _claim_entries_rt = {k: v for k, v in _all_canon_rt.items() if k.startswith("claim:")}
    # 去重：仅保留不在 cross_dimension_claims 中的新 claims
    _existing_keys = set()
    for c in cross_dimension_claims:
        _src = c.get("source_aspect", "")
        _stmt = c.get("statement", "")
        for k, v in _claim_entries_rt.items():
            if (v.get('value',{}).get('source_aspect','') == _src and 
                v.get('value',{}).get('statement','') == _stmt):
                _existing_keys.add(k)
                break
    _new_claims_rt = {k: v for k, v in _claim_entries_rt.items() if k not in _existing_keys}
    if _new_claims_rt:
        # 使用与L3相同的分层注入格式
        _new_factual = []
        _new_inferential = []
        _new_speculative = []
        for k, v in _new_claims_rt.items():
            if v.get('value',{}).get('source_aspect','') != aspect:
                _cv = v.get('value', {})
                _ep = _cv.get('epistemic_level', 'inferential')
                if _ep == 'factual': _new_factual.append(_cv)
                elif _ep == 'inferential': _new_inferential.append(_cv)
                else: _new_speculative.append(_cv)
        # 复用L3的分层格式
        ...
```

**方案 B (简化): 合并为单次读取**

将 line 659 的读取移到 line 738 之前（即 `_build_analysis_prompt_with_data` 调用之前），只读一次，然后同时传给两个注入点。但这样会丧失实时性。

**方案 C (文档原文): 删除注入点2**

接受实时性窗口极小（await 间隔约 5-30 秒的 LLM 调用），新 claim 在此窗口出现的概率低。如果出现，下一轮迭代会捕获。风险可控但信息有损。

### 严重性评估

| 方案 | 实时性 | 去重 | 复杂度 | 信息完整性 |
|------|--------|------|--------|------------|
| A | 保留 | 完全 | 高 | 100% |
| B | 丧失 | 完全 | 低 | 95% |
| C | 丧失 | 完全 | 最低 | 95% |

**建议**: 方案 A 最严谨但复杂度高。如果团队倾向简洁，方案 C 可接受（文档中"同一快照"的理由需修正为"实时窗口极小，信息损益可接受"）。

---

## 三、L2-B 同 caliber 不覆盖方案的逻辑缺陷

### 文档方案:
```python
if new_priority <= existing_priority:
    if new_priority != existing_priority:
        # 低优先级不覆盖高优先级
        ...
    else:
        # 同优先级：同 caliber 不覆盖，不同 caliber 记录冲突
        if caliber == existing.get("caliber", ""):
            return conflict  # 不覆盖
```

### 问题 1: claim 内容更新被阻止

场景：维度"市场规模"分析后提取 claim A（factual），迭代深化后同一 agent 重新分析，产生更精确的 claim A'（同样 factual），此时 A' 会被拒绝，因为 caliber 相同。

**严重性**: 中等。迭代深化是系统的核心特性之一（`generic_agent.py:779-820`），同 agent 产生同 caliber 更新 claim 是正常场景。

### 问题 2: claim key 不包含 aspect 时的歧义

当前 claim metric key 格式为 `claim:{aspect}:{id}`。如果两个不同 aspect 写入同一个 metric key（理论上不会，因为 aspect 不同），会被同 caliber 规则误阻止。但实际由于 aspect 在 key 中，此问题不发生。✓

### 问题 3: 与迭代深化的交互

迭代深化流程（line 779-820）：
1. 第一次分析 → 写入 claim (caliber=llm_inference_factual)
2. 检测知识缺口 → 补充搜索
3. 第二次分析（含新数据） → 尝试写入同一 claim → **被 L2-B 阻止**

**修正方案**: 增加"同 source 允许覆盖"例外：

```python
if caliber == existing.get("caliber", ""):
    if source == existing.get("source", ""):
        # 同 agent 可更新自己的 claim
        pass  # 允许覆盖
    else:
        return conflict  # 不同 agent 不覆盖
```

**评估**: 此修正与文档待决问题 #3 一致。建议纳入 L2-B 修复。

---

## 四、L4 结构化输出方案的可靠性评估

### 文档声称:
> "v2.0 的结构化输出方案可靠性约 80%+"

### 审查:

**支持因素**:
1. `_parse_causal_hypotheses` 已在生产环境运行，管道分隔解析稳定 ✓
2. fallback 为 `unverified`，不恶化 ✓
3. prompt 中给出固定模板 ✓

**风险因素**:
1. **LLM 输出位置不稳定**: 假设验证结果可能出现在分析正文中间而非末尾。文档假设"分析末尾按格式输出"，但 LLM 经常在思考过程中穿插判断。
2. **编号偏移**: prompt 中要求"假设1: ... | 假设2: ..."，但 LLM 可能输出"假设1: ... 假设1b: ... 假设2: ..."，导致编号错位。
3. **多行验证**: LLM 可能对一个假设输出多行验证判断（先分析再判断），解析器只取含"假设N"的第一行，可能取到中间分析行而非最终判断。

### 量化修正

| 情况 | 概率 | 解析结果 |
|------|------|----------|
| LLM 严格按格式输出 | ~60% | 正确 |
| LLM 输出验证结果但有格式偏差（多空格、换行等） | ~20% | 正确（解析器容错） |
| LLM 输出验证结果但编号偏移 | ~5% | 部分正确 |
| LLM 在分析中间散布验证判断 | ~10% | 可能取到中间行 |
| LLM 完全不输出验证结果段 | ~5% | fallback unverified |

**修正后可靠率估计**: ~80% 完全正确 + ~15% 部分正确 + ~5% 假阴性

与文档声称一致，但需注意"部分正确"中的编号偏移风险。

### 建议增强

在 `_parse_hypothesis_verification` 中增加：
1. 对每个假设，搜索**最后**包含"假设N"且含"|"的行（而非第一行），避免取到中间分析
2. 如果编号不连续（如假设1后跳到假设3），检查是否假设2被合并或跳过

---

## 五、L5 矛盾检测的误报率分析

### 文档声称:
> "2-gram 方向矛盾检测，~70% 检出率"

### 误报场景分析

**误报类型 1: 同一主体的不同子维度方向相反**

- "市场规模增长" vs "利润率萎缩"  
- bigram 主体匹配: "市场" 重叠 → 可能误判为矛盾
- 实际: 市场规模和利润率是不同指标，方向相反合理

**误报类型 2: 时间限定不同**

- "短期增速下降" vs "长期趋势增长"  
- bigram 主体匹配: "增速"/"趋势" 部分重叠 → 可能误判
- 实际: 不矛盾，时间框架不同

**误报率估计**: 在典型行业报告中，约 15-25% 的检测会产生误报。

### 修正方案

增加**方向词语境检查**：方向词前后 5 个字符内是否含限定词（如"短期/长期/利润率/营收"等），如果两个 claim 的限定词集合不重叠，则降低矛盾置信度：

```python
# 简化方案: 方向词前5字符是否含限定词
qualifiers = {"短期", "长期", "利润率", "营收", "出口", "内销", ...}
a_qualified = any(q in stmt_a[max(0, stmt_a.index(w)-5):stmt_a.index(w)] for w in positive if w in stmt_a for q in qualifiers)
# 如果两边都有不同限定词，降低矛盾置信度但不完全抑制
```

**评估**: 此修正增加复杂度但显著降低误报。建议记录为后续优化，初始版本接受 15-25% 误报率（只产生 warning，不阻塞写入）。

---

## 六、量化评估审查 (Section IV-B)

### V1 推测性 claim 被当作事实引用率: "修复前 ~60%"

**审查**: 此估计合理但缺乏直接测量。依据：
- 修复前所有 claim 标签为"已确认发现（必须纳入分析考量）" → LLM 将其视为确认事实
- 但 LLM 是否真的将 LOW confidence claim 当作事实引用，取决于 LLM 的指令遵从度
- 实际概率可能在 40-70% 范围，60% 是中位数估计

**建议**: 标注为"估计值 40-70%，中位数 60%"

### V2 因果假设验证闭环率: "修复后 ~80%"

**审查**: 此处"闭环率"指假设从 unverified 变为 verified/revised/refuted 的概率，取决于 L4 解析成功率。基于上方分析，修正为 "~80% 完全正确 + ~15% 部分正确"。

### V4 同一 claim 重复注入率: "修复前 100%"

**审查**: 严格来说是"100% 的 claim 被注入至少2次"。但需注意：
- 某些 claim 可能只在注入点1被注入（如果注入点2读取时该 claim 尚未写入）
- 但对于已写入的 claim，确实 100% 被注入2次

**建议**: 修正为"已写入的 claim 100% 被双重注入"

### V6 推测性 claim 覆盖事实性 claim 率: "修复前 ~50%"

**审查**: 此估计过于笼统。实际发生概率取决于：
1. 两个维度写入同一 metric key 的概率（取决于 claim:XX:N 中 XX 和 N 是否相同）
2. 由于 claim key 包含 aspect，**同一 metric key 的概率极低**（`claim:竞争格局:0` vs `claim:风险分析:0`，key 不同）

**这是一个重要的逻辑错误**：claim 的 metric key 格式为 `claim:{aspect}:{id}`，不同维度的 claim 有不同的 key，**不存在覆盖问题**！

V6 描述的场景是"维度A先输出 factual claim，维度B后输出同一 metric 的 speculative claim"，但由于 aspect 不同，key 不同，B 的 claim 不会覆盖 A 的 claim。覆盖只发生在**同维度迭代**中（同一 agent 重复分析产生同 id 的 claim）。

**严重性**: 高。文档场景4的逻辑前提不成立。L2 的 caliber 分级对 claim 的覆盖保护**几乎无效**（因为 key 不同），但对同维度的迭代更新有保护意义。

**修正**: 
1. V6 的场景应修正为"同维度迭代中，新 speculative claim 覆盖旧 factual claim"
2. 量化估计应基于"同一 agent 迭代时产生同 id claim 且 epistemic_level 降级的概率"，而非跨维度覆盖

---

## 七、遗漏问题

### O1: strategic_intent 的 claim extraction 无特殊处理

`_extract_claims_from_analysis` 对所有维度统一处理，但 strategic_intent 维度的输出天然是推测性的。文档中 L1 方案依赖 LLM 正确标注 epistemic_level，但对 strategic_intent 维度，几乎 100% 的 claim 应为 speculative 或 inferential。

**建议**: 在 `_extract_claims_from_analysis` 中增加维度级别的 epistemic_level 默认值：
```python
aspect_epistemic_default = {
    "strategic_intent": "speculative",
    "战略意图": "speculative", 
    "战略意图推断": "speculative",
}
_default = aspect_epistemic_default.get(aspect, "inferential")
```
如果 LLM 输出的 epistemic_level 高于维度默认值（如 strategic_intent 输出 factual），则降级为维度默认值。

### O2: falsification 字段在 claim 传播后无使用

L1/L3 增加了 falsification 字段，但文档未定义该字段如何被消费。下游 agent 看到证伪条件后应如何行动？

**建议**: 在 L3 注入 prompt 中增加要求：
```
如果你掌握可以证伪某推测性观点的数据，必须在分析中明确指出。
```

### O3: 并发写入的 race condition

多个 agent 并发调用 `write_canonical`。虽然使用了 `async with self._lock`，但如果两个 agent 同时读到 `existing=None`（同一 key），两者都会写入，后者覆盖前者——**锁保护的是读-检查-写序列，但只保证序列化，不保证原子性决策**。

等等，实际上 `async with self._lock` 包裹了整个读-检查-写逻辑（line 215-242），所以**不存在 race condition**。✓ 

### O4: conflict:claim:XX 写入后的消费方式

L5 方案将矛盾信息写入 `conflict:claim:XX`，但下游 agent 如何感知这些冲突？`get_all_canonical()` 返回所有 key 以 `canonical:` 开头的条目，`conflict:` 前缀的条目**不会被返回**。

**建议**: 要么将 conflict key 改为 `canonical:conflict:claim:XX`，要么在 L3 注入时主动读取 conflict 条目并注入 prompt。

---

## 八、总体评估

### 方案整体质量: **良好** (7.5/10)

**优点**:
1. 认识论分层思路正确，抓住了根因
2. L1-C 截断修复是 v2.0 的关键改进，从"不修"到"必修"定性正确
3. L4 从关键词匹配升级为结构化输出，可靠率从 ~30% 提升到 ~80%
4. L5 从 SharedMemory 层移到 agent 层，职责划分更清晰
5. 安全网设计完整，每层失败都不恶化
6. 场景模拟直观展示了修复效果

**需要修正的问题**:

| # | 问题 | 严重性 | 修正方式 |
|---|------|--------|----------|
| 1 | L3-A "同一快照"论断错误 | **高** | 修正为"实时窗口极小但非零"，选择方案 A/C 并修正理由 |
| 2 | V6 场景4逻辑前提错误 | **高** | 修正为同维度迭代覆盖场景，重新量化 |
| 3 | L2-B 缺少同 source 例外 | **中** | 增加 `source == existing.source` 允许覆盖 |
| 4 | L4 编号偏移和多行验证风险 | **低** | 取最后匹配行，文档记录已知限制 |
| 5 | L5 误报率 15-25% 未提及 | **中** | 文档补充误报率估计和后续优化路径 |
| 6 | O1 strategic_intent 维度无特殊处理 | **中** | 增加维度级 epistemic_level 默认值 |
| 7 | O4 conflict 条目不可被下游消费 | **中** | 改 key 前缀或在 L3 注入时主动读取 |

### 修正优先级

1. **必须修**: #1 (L3-A 理由), #2 (V6 场景)
2. **应该修**: #3 (L2-B 同 source), #6 (O1 维度默认值), #7 (O4 conflict 消费)
3. **可以延后**: #4 (L4 增强), #5 (L5 误报率)

---

## 九、修正后的实施建议

实施顺序不变: L1(含L1-C) → L2(含L2-B) → L3 → L4 → L5

但每层需叠加上述修正：

| 步骤 | 修正内容 |
|------|----------|
| L1 | + 维度级 epistemic_level 默认值 (O1) |
| L2-B | + 同 source 允许覆盖 (#3) |
| L3-A | + 修正删除/合并理由 (#1)，采用方案 A 或 C 并修正文档 |
| L3 | + 注入时读取 conflict 条目 (O4) + 证伪数据主动检查 (O2) |
| L4 | + 取最后匹配行而非首行 (#4) |
| L5 | + 文档记录误报率估计 (#5) |
| V6 | + 修正场景为同维度迭代 (#2) |

---

## 十、结论

v2.0 方案整体思路正确，核心认识论分层设计可行。但存在两个高严重性事实性错误：

1. **L3-A "同一快照"论断** — 两次 `get_all_canonical()` 调用之间有 await 点，并发 agent 可在此窗口写入新 claims。删除注入点2的理由需修正。
2. **V6 场景4跨维度覆盖** — claim key 包含 aspect，不同维度的 claim 有不同 key，不存在跨维度覆盖。场景应修正为同维度迭代。

修正这两个问题后，方案可进入实施阶段。
