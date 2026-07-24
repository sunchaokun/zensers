# 认识论防线 v3.0 三次审查报告

> **审查人**: opencode | **日期**: 2026-07-01 | **审查对象**: epistemic-defense-audit.md v3.0
>
> 本次审查逐条对照实际代码验证，重点关注 v2.0 审查中发现的问题是否已修复，
> 以及 v3.0 新增内容是否引入新错误。

---

## 一、v2.0 审查问题修复验证

| v2.0 问题 | v3.0 修复状态 | 验证结果 |
|------------|---------------|----------|
| L3-A "同一快照"论断错误 | ✅ 已修正 | v3.0 正确指出两次读取间有 await 窗口，理由修正为"保留危害大于收益" |
| V6 场景4 跨维度覆盖前提错误 | ✅ 已修正 | v3.0 场景4改为"同维度迭代覆盖"，正确指出 key 含 aspect 导致跨维度覆盖不存在 |
| L2-B 缺少同 source 例外 | ✅ 已修正 | v3.0 L2-B 增加了 `source == existing.source` 允许覆盖 |
| O1 strategic_intent 维度无特殊处理 | ✅ 已修正 | v3.0 L1-D 增加 ASPECT_EPISTEMIC_CEILING |
| O4 conflict 条目不可被下游消费 | ✅ 已修正 | v3.0 L3-D 增加 conflict 条目注入 |
| L5 误报率未提及 | ✅ 已修正 | v3.0 L5-C 增加 15-25% 误报率估计 |

**v2.0 全部问题已修复** ✓

---

## 二、v3.0 新发现的错误

### 错误 1: L3-D 代码引用不存在的变量 `_all_canon` [严重性: 高]

**文档位置**: L3-D 代码片段 (line 322 of doc)

```python
_conflict_entries = {k: v for k, v in _all_canon.items() if k.startswith("conflict:claim:")}
```

**问题**: `_all_canon` 是在 `generic_agent.py:659` 的主流程中定义的局部变量，不在 `_build_analysis_prompt_with_data` 方法的作用域内。该方法签名 (`generic_agent.py:4251-4263`) 不接受 `_all_canon` 参数。

**影响**: 按此代码实施会直接抛出 `NameError`。

**修复方案**: 有两种选择：

**方案 A (推荐): 通过参数传递**

在 `_build_analysis_prompt_with_data` 中新增 `conflict_entries` 参数：

```python
def _build_analysis_prompt_with_data(
    self,
    topic: str, aspect: str, aspects: List[str],
    data_points: List[Dict[str, Any]], sources: List[Dict[str, Any]],
    core_question: str = "", role_in_report: str = "",
    sibling_aspects: Optional[List[str]] = None,
    sub_aspects: Optional[List[str]] = None,
    cross_dimension_claims: Optional[List[Dict]] = None,
    causal_hypotheses: Optional[List[Dict]] = None,
    conflict_entries: Optional[Dict[str, Dict]] = None,  # NEW
) -> str:
```

调用侧 (`generic_agent.py:694-703`) 同步修改，在构建 prompt 前读取 conflict 条目：

```python
# 在 line 664 之后，line 665 之前
_conflict_entries = {}
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    for _ck, _cv in _all_canon.items():
        if _ck.startswith("conflict:claim:"):
            _conflict_entries[_ck] = _cv

# line 694 调用时传入
prompt = self._build_analysis_prompt_with_data(
    ...,
    conflict_entries=_conflict_entries,
)
```

迭代深化调用 (`generic_agent.py:798-807`) 也需传入 `_conflict_entries`。

**方案 B: 方法内部读取**

在 `_build_analysis_prompt_with_data` 内部直接调用 `self._shared_memory.get_all_canonical()`。但此方法不是 async，而 `get_all_canonical` 是同步方法 ✓，可以直接调用。但这破坏了方法的纯函数特性（输入→输出），且需处理 `self._shared_memory` 不存在的情况。

**推荐方案 A**，因为更清晰且与现有参数传递模式一致。

---

### 错误 2: L1-D ASPECT_EPISTEMIC_CEILING 缺少英文名称 [严重性: 中]

**文档位置**: L1-D 代码片段

```python
ASPECT_EPISTEMIC_CEILING = {
    "strategic_intent": "speculative",
    "战略意图": "speculative",
    "战略意图推断": "speculative",
}
```

**问题**: 缺少 `"Strategic Intent"` 键。系统中 aspect 名称可能来自 `ASPECT_SKILL_MAP` (`strategies.py:41-70`) 或 `ASPECT_NAME_MAP` (`prompt_manager.py:381-384`)，其中包含 `"Strategic Intent"`。如果 agent 收到的 aspect 是英文名，天花板不会生效。

**修复**: 增加 `"Strategic Intent": "speculative"`。

此外，`ASPECT_EPISTEMIC_CEILING` 定义位置应考虑放在哪里。如果放在 `_extract_claims_from_analysis` 方法内部作为局部变量，每次调用都创建字典，浪费但可忽略。如果放在类属性或模块级别，需确认 `GenericAgent` 类的定义位置。

**建议**: 放在 `_extract_claims_from_analysis` 方法内部即可，与 `caliber_map` 同级。

---

### 错误 3: `_parse_hypothesis_verification` 代码使用 `break` 取首行，但实施清单写"取最后匹配行" [严重性: 低]

**文档位置**: 
- 实施清单 (line 922): "取最后匹配行"
- `_parse_hypothesis_verification` 代码: 使用 `for line in ...: ... break` 取第一个匹配行

**问题**: 文档内部不一致。v2.0 审查建议取最后匹配行（避免取到中间分析行），但代码未更新。

**修复**: 将代码改为收集所有匹配行，取最后一个：

```python
matching_lines = [line for line in verification_section.split("\n") 
                  if pattern in line and "|" in line]
if matching_lines:
    line = matching_lines[-1]  # 取最后匹配行
    parts = line.split("|")
    ...
```

---

### 错误 4: hashlib 未在 generic_agent.py 中导入 [严重性: 中]

**文档位置**: L4 和 L5 的代码使用 `hashlib.md5(...)`

**问题**: `generic_agent.py` 当前未导入 `hashlib`（通过 `grep` 验证）。L4 的 `_parse_hypothesis_verification` 和 L5 的 `write_canonical(metric=f"hypothesis:{aspect}:{hash}")` 都依赖 `hashlib`。

**修复**: 在 `generic_agent.py` 顶部增加 `import hashlib`，或在方法内部延迟导入 `import hashlib`。

**建议**: 在方法内部延迟导入，与现有 `import json as _json` (line 1566) 模式一致。

---

### 错误 5: L4-C "回填时机"说明有误导 [严重性: 低]

**文档位置**: L4-C

> "验证结果写入在 claim 写入之前（L4 在 line 757, B2.1 在 line 764），所以假设验证结果可以被后续 claim 提取引用"

**问题**: 
1. L4 写入的是 `hypothesis:{aspect}:{hash}` key，B2.1 写入的是 `claim:{aspect}:{id}` key，是不同的 key，不存在"被 claim 提取引用"的关系
2. `_extract_claims_from_analysis` (line 1543) 不读取假设数据，只从分析文本中提取 claim
3. 顺序正确的理由应该是"假设验证结果先于 claim 写入 SharedMemory，使下游 agent 在读取 `get_all_canonical()` 时能同时看到 hypothesis 和 claim 数据"，而非"claim 提取引用假设"

**修复**: 删除"可以被后续 claim 提取引用"，改为"假设验证结果先于 claim 写入，确保下游 agent 在同一轮读取中能同时获取假设验证结果和 claim 数据"。

---

### 错误 6: L2-B 对 dict claim 的同 caliber 不覆盖返回 conflict=None [严重性: 低]

**文档位置**: L2-B 代码片段

```python
elif caliber == existing.get("caliber", ""):
    # 同 caliber 不同 source：不覆盖，保留先入值
    return conflict
```

**问题**: 对于 dict 类型 claim，`conflict` 在 line 217 初始化为 `None`，且 line 218-226 的 numeric 冲突检测不会触发（因为 value 是 dict）。因此 `return conflict` 返回 `None`——不覆盖但不记录冲突。

**影响**: 同 caliber 不同 source 的 dict claim 被静默拒绝，无日志、无 ConflictRecord。调用方无法知道写入被跳过。

**修复**: 增加日志和 ConflictRecord：

```python
elif caliber == existing.get("caliber", ""):
    if source != existing.get("source", ""):
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
```

---

## 三、代码引用准确性验证

| 文档引用 | 实际代码 | 准确? |
|----------|----------|-------|
| `_extract_claims_from_analysis` line 1543 | `generic_agent.py:1543` | ✓ |
| `analysis_content[:3000]` line 1555 | `generic_agent.py:1555` | ✓ |
| `caliber="llm_inference"` line 772 | `generic_agent.py:772` | ✓ |
| `SOURCE_PRIORITY` communication.py:117 | `communication.py:117-121` | ✓ |
| `write_canonical` conflict detection line 218 | `communication.py:218` | ✓ |
| `write_canonical` priority logic line 227-235 | `communication.py:227-235` | ✓ |
| 注入点1 line 4346 | `generic_agent.py:4346` | ✓ |
| 注入点2 line 737-748 | `generic_agent.py:737-748` | ✓ |
| `get_all_canonical` 格式化读取 line 659 | `generic_agent.py:659` | ✓ |
| `settings.llm.max_tokens = 4096` | `settings.py:84` | ✓ |
| `_parse_causal_hypotheses` line 1579 | `generic_agent.py:1579-1602` | ✓ |
| `asyncio.gather` 并发执行 | `agent_coordinator.py:617` | ✓ |
| `call_llm` 假设生成 line 683 | `generic_agent.py:683` | ✓ |
| 迭代深化复用 `cross_dimension_claims` line 805 | `generic_agent.py:805` | ✓ |
| `ConflictResolution.MANUAL` | `result_aggregator.py:47` | ✓ |
| `get_all_canonical` 返回去除 `canonical:` 前缀的 key | `communication.py:278-280` | ✓ |
| `hashlib` 未导入 | `grep` 确认无结果 | ✓ |
| `_build_analysis_prompt_with_data` 无 `_all_canon` 参数 | `generic_agent.py:4251-4263` | ✓ |

**所有行号引用准确** ✓

---

## 四、额外发现

### 发现 1: 迭代深化路径不执行实时注入 (确认 L3-A 安全)

迭代深化路径 (`generic_agent.py:798-820`) 调用 `_build_analysis_prompt_with_data` (line 798) 和 `call_llm` (line 808)，但**不经过** line 737-748 的实时注入逻辑。这证明实时注入只覆盖主路径，删除它不会影响迭代深化的行为。

### 发现 2: conflict key 通过 get_all_canonical 可访问

v2.0 审查报告 (epistemic-defense-review-v2.md) 声称 conflict 条目不能被 `get_all_canonical()` 返回。这是**错误的**。L5 写入 `metric=f"conflict:{_ek}"`，`write_canonical` 内部拼接为 `canonical:conflict:{_ek}`，`get_all_canonical()` 会返回 `conflict:{_ek}`。

但 L3 注入逻辑 (`generic_agent.py:660`) 只过滤 `k.startswith("claim:")`，不会自动注入 conflict 条目。所以 **L3-D 仍然是需要的**，只是理由不是"conflict 条目不可被 get_all_canonical 返回"，而是"现有 claim 过滤逻辑不包含 conflict 前缀"。

v3.0 文档的 L3-D 理由正确（"不在 claim: 前缀下"），但 v2.0 审查报告的错误理由需注意不要混用。

### 发现 3: L5 遍历所有已有 claims 的性能问题

L5 代码在每次 `write_canonical` 前遍历所有已有 claims：

```python
_existing_claims = self._shared_memory.get_all_canonical()
for _ek, _ev in _existing_claims.items():
    if _ek.startswith("claim:") ...
```

对于 5 维度报告，每个维度最多 5 个 claim，总计 ~25 个 claim。遍历 25 个 dict 做关键词匹配，性能可忽略。但如果报告维度数增加（如 20+ 维度），O(n²) 的矛盾检测可能成为瓶颈。

**评估**: 当前规模下无问题，记录为后续优化点。

---

## 五、总体评估

### 评分: 9.0/10

v3.0 相比 v2.0 显著改进：
- v2.0 的两个高严重性错误（L3-A 论断、V6 场景）均已修正
- L1-D、L2-B 同 source 例外、L3-D、L3-E、L5-C 等新增内容均为实质改进
- 所有行号引用经逐条验证，均准确

扣分项：

| 项目 | 扣分 | 说明 |
|------|------|------|
| L3-D `_all_canon` 作用域错误 | -0.5 | 代码片段引用不存在的变量，直接实施会报 NameError |
| L1-D 缺少英文键 | -0.2 | "Strategic Intent" 未包含 |
| `_parse_hypothesis_verification` break vs 最后匹配行不一致 | -0.1 | 文档内部矛盾 |
| hashlib 未导入 | -0.1 | 遗漏依赖 |
| L4-C 误导性说明 | -0.1 | "claim 提取引用假设"不成立 |

### 6个错误汇总

| # | 错误 | 严重性 | 修复复杂度 |
|---|------|--------|------------|
| 1 | L3-D `_all_canon` 作用域错误 | 高 | 中（需新增参数 + 修改调用侧） |
| 2 | L1-D 缺少英文键 | 中 | 低（加一行） |
| 3 | 验证解析取首行 vs 取末行不一致 | 低 | 低（改 break 为取末行） |
| 4 | hashlib 未导入 | 中 | 低（加一行 import） |
| 5 | L4-C 误导性说明 | 低 | 低（改文字） |
| 6 | L2-B dict claim 同 caliber 无日志/无 ConflictRecord | 低 | 低（加几行代码） |

### 实施前必须修复

仅 **错误 1** (L3-D 作用域) 会导致运行时崩溃，必须修复后才能实施。其余 5 个可在实施时顺手修复。

### 修正后的 L3-D 实施方案

```python
# 1. 在 generic_agent.py:664 之后读取 conflict 条目
_conflict_entries = {}
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    for _ck, _cv in _all_canon.items():
        if _ck.startswith("conflict:claim:"):
            _conflict_entries[_ck] = _cv

# 2. 传入 _build_analysis_prompt_with_data (修改签名和调用)
# signature 新增: conflict_entries: Optional[Dict[str, Dict]] = None

# 3. 在 _build_analysis_prompt_with_data 内部注入
if conflict_entries:
    parts.append("\n### 已检测到跨维度矛盾")
    for _ck, _cv in conflict_entries.items():
        _conf_val = _cv.get("value", {})
        parts.append(
            f"  - 矛盾类型: {_conf_val.get('contradiction', '未知')}"
            f" | 涉及结论: {_conf_val.get('claims', [])}"
        )
    parts.append("\n**要求**: 如果你的分析与上述矛盾相关，必须给出你的判断和依据。")

# 4. 迭代深化调用 (line 798-807) 也传入 _conflict_entries
```

---

## 六、结论

v3.0 方案质量很高，v2.0 的所有问题均已修正。仅剩 1 个运行时错误（L3-D 作用域）和 5 个低/中严重性问题。修复 L3-D 后即可进入实施阶段。
