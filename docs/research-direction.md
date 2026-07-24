# Zensers 优化方案：从"描述现象"到"理解动机"

---

## 一、问题定义

资深行业研究员与 Zensers 系统的核心差距不是数据获取能力，而是**认知深度**：

| 层次 | 系统现在做什么 | 资深研究员还做什么 |
|------|------------|----------------|
| 因果 | 事后补一句因果联系 | 因果假设驱动搜索方向和分析框架 |
| 跨维度 | 各维度独立反事实，合成时"识别矛盾" | 跨维度因果传导，矛盾自动触发深入分析 |
| 动机 | 分析现象（份额多少、增速多高） | 推断意图（为什么扩张、为什么押注这条技术路线） |

**代码证据**：
- 跨章节因果链是输出格式要求（`generic_agent.py:3938-3943`），不是搜索/分析的驱动机制
- 各维度反事实推理是本维度内部假设，无跨维度传导
- 合成阶段只有 1 次 LLM 调用（`generic_agent.py:889/892`），前序内容截断 2000字×20块
- 所有维度 prompt 都没有战略意图推断

---

## 二、四个方向的实现方案

### 优先级：D > C > A > B

- **D（修复搜索截杀）**：投入产出比最高，15min 核心改动，效果立竿见影
- **C（战略意图推断维度）**：直接解决核心差距——从描述现象到理解动机
- **A（因果假设驱动搜索）**：有了意图理解，因果假设才有据可依；有了 D，假设查询不被截杀
- **B（跨维度 claim 共享）**：A 和 C 的基础设施，让维度间可以交换结论

---

### 方向 C：增加"战略意图推断"维度

#### C1. 设计原理

战略意图推断不是新增一个普通维度（与竞争格局、技术趋势并列），而是一个**元维度**——它的输入是其他维度的分析结论，它的输出是对行业参与者动机的推断。因此：

- 它应该是 `dependent_aspect`（依赖所有 normal_aspects 完成）
- 它不需要独立的 DATA_COLLECTION 阶段（数据来自其他维度的搜索结果）
- 它需要读取其他维度的 **claim**（见方向 B），而不仅仅是 canonical 数字

#### C2. 代码改动

**C2.1 模板 YAML：添加 strategic_intent section**

文件：`config/templates/industry_report.yaml`  
位置：在 `risk_analysis`（line 114）之后插入

```yaml
  - id: strategic_intent
    name:
      zh: 战略意图推断
      en: Strategic Intent Inference
    required: false
    description:
      zh: 行业核心参与者战略布局推断、进入/退出信号、资源分配意图、并购整合方向、政策制定者隐含目标
      en: Strategic intent inference, entry/exit signals, resource allocation intent, M&A direction, policymaker implicit goals
```

**C2.2 ASPECT_SKILL_MAP：添加映射**

文件：`src/core/decomposition/strategies.py`
位置：`ASPECT_SKILL_MAP`（line 41-67）中新增

> **重要**：`get_skills_for_aspect()` 在运行时接收的 `aspect` 参数是**中文名称**（如"竞争格局"），而非英文（如"Competitive Landscape"）。匹配逻辑是精确匹配 → 包含匹配 → 默认值。英文键 `"Strategic Intent"` 对中文 aspect 永远匹配不到，必须同时添加中文键。

```python
"Strategic Intent": ["llm_skill", "market_analysis"],
"战略意图": ["llm_skill", "market_analysis"],
"战略意图推断": ["llm_skill", "market_analysis"],
```

**C2.3 ASPECT_NAME_MAP：添加中英文映射**

文件：`src/core/prompt_manager.py`  
位置：`ASPECT_NAME_MAP`（line 365-381）中新增

```python
"战略意图": "strategic_intent",
"战略意图推断": "strategic_intent",
```

**C2.4 DEPENDENT_SECTIONS：添加战略意图**

文件：`src/core/decomposition/strategies.py`
位置：`DEPENDENT_SECTIONS`（line 439-446）中新增

> **重要**：`DEPENDENT_SECTIONS` 的匹配逻辑是 `aspect.lower() in DEPENDENT_SECTIONS or any(ds in aspect for ds in DEPENDENT_SECTIONS)`。运行时 `aspect` 是中文名称（如"战略意图推断"），英文条目 `"strategic_intent"` 不会被 `"strategic_intent" in "战略意图推断"` 匹配到。必须同时添加中文条目，否则战略意图维度会被错误归入 `normal_aspects`，在 DATA_COLLECTION 阶段执行而非 SYNTHESIS 阶段。

```python
"strategic_intent", "strategic intent",
"战略意图", "战略意图推断",
```

这让战略意图维度自动进入 `dependent_aspects`，在 SYNTHESIS 阶段执行（依赖所有 DEEP_ANALYSIS agents 完成）。

**C2.5 Agent Profile Prompt：创建战略意图推断专属 prompt**

新建文件：`prompts/agents/strategic_intent.md`

核心设计原则：
- **不描述现象，只推断动机**——"市场份额从30%升至35%"不是你要分析的，"为什么选择在这个时点扩张"才是
- **跨维度因果链是核心输入**——竞争格局的份额变化+技术趋势的R&D方向+政策的资源投放→推断战略意图
- **推断必须有据**——每个意图推断必须标注证据来源维度和置信度
- **输出反事实**——"如果意图X为真，我们应观察到Y；如果观察不到Y，则意图可能是Z"

```markdown
# 战略意图推断分析师

你是一位资深行业战略分析师，专长是从参与者的行为中推断其战略意图。

## 核心任务

你不描述行业现象（市场份额多少、增速多高），你推断**为什么**——
为什么头部企业在这个时点扩张？为什么政策制定者选择这种干预方式？
为什么技术路线出现分化？背后是进攻性颠覆还是防御性跟随？

## 分析框架

对每个关键参与者（企业/政策制定者/资本方），从以下维度推断意图：

1. **资源分配信号**：资金、人才、产能投向哪里→意图在哪里
2. **时序模式**：行为的时间序列是否暗示预谋还是被动反应
3. **博弈论视角**：参与者的行为是否是对其他参与者行为的最佳回应
4. **言行对比**：公开表态与实际资源分配是否一致→不一致处暴露真实意图
5. **反事实检验**：如果意图X为真，应观察到Y；如果观察不到→修正推断

## 输出格式

对每个关键推断：
- **推断**：一句话陈述推断的战略意图
- **证据**：来自哪些维度、什么数据支撑
- **置信度**：HIGH/MEDIUM/LOW + 判定理由
- **反事实**：什么条件下此推断会被推翻
- **跨维度因果链**：此意图如何传导至其他维度的结论
```

**C2.6 合成阶段注入跨维度 claim（依赖方向 B）**

文件：`src/core/agents/generic_agent.py`  
位置：`_build_analysis_prompt_with_data()`（line 4111-4122）

添加 `cross_dimension_claims` 参数，在 framework_context 中注入其他维度的 claim。

（详见方向 B 的 B3 部分）

#### C3. 实施步骤

| 步骤 | 改动 | 文件 | 工作量 |
|------|------|------|--------|
| 1 | YAML 添加 section | `industry_report.yaml` | 5min |
| 2 | ASPECT_SKILL_MAP 添加条目 | `strategies.py` | 2min |
| 3 | ASPECT_NAME_MAP 添加条目 | `prompt_manager.py` | 2min |
| 4 | DEPENDENT_SECTIONS 添加条目 | `strategies.py` | 2min |
| 5 | 创建 strategic_intent.md | `prompts/agents/` | 30min |
| 6 | （依赖B）合成 prompt 注入 claims | `generic_agent.py` | 见方向B |

步骤 1-5 可以独立实施，不依赖方向 A/B。没有方向 B 时，战略意图维度仍然可以工作——只是它读不到其他维度的结构化 claim，而是依赖 LLM 从前序分析文本中提取（与现有合成阶段逻辑一致）。

---

### 方向 A：让因果假设驱动搜索和分析

#### A1. 设计原理

当前流程：搜索→分析→结尾补一句因果联系  
目标流程：生成因果假设→为假设设计搜索查询→分析验证/修正假设→因果链自然生长

关键洞察：`_generate_smart_queries_with_llm()` 已经有 LLM 扩展搜索查询的能力（line 3765），但被禁忌词和 prompt 限制截杀。方向 D 解决截杀问题后，A 的因果假设可以进一步让查询从"泛搜索"升级为"精准验证"。

#### A2. 代码改动

**A2.1 DEEP_ANALYSIS 阶段：在分析前生成因果假设**

文件：`src/core/agents/generic_agent.py`  
位置：line 655（canonical_data 补充完成后）与 line 656（system_prompt 构建前）之间

插入"因果假设生成"步骤：

```python
# A2.1: Generate causal hypotheses before analysis
causal_hypotheses = []
if aggregated_data_points and len(aggregated_data_points) >= 5:
    hypothesis_prompt = f"""基于以下数据，生成2-3个关于「{aspect}」的因果假设。
每个假设必须：1) 可被数据验证或反驳 2) 涉及跨维度因果传导 3) 不与已知事实矛盾

数据摘要（前5条）：
{chr(10).join([f"- {dp.get('title','')}: {(dp.get('content','') or '')[:200]}" for dp in aggregated_data_points[:5]])}

其他维度已有发现：
{chr(10).join([f"- [{c.get('source_aspect','?')}] {c.get('statement','')}" for c in (cross_dimension_claims or [])]) if cross_dimension_claims else '暂无'}

输出格式（每行一个假设）：
假设：[因果陈述] | 验证数据：[需要什么数据] | 传导：[影响哪些维度]"""

    hypothesis_result = await call_llm(
        prompt=hypothesis_prompt,
        system_prompt="你是一位因果推断专家。只输出假设，不要分析。"
    )
    if hypothesis_result.get("success") and hypothesis_result.get("content"):
        causal_hypotheses = self._parse_causal_hypotheses(hypothesis_result["content"])
        self._context["causal_hypotheses"] = causal_hypotheses
```

> **新增方法**：`_parse_causal_hypotheses()` 需要在 `GenericAgent` 类中新增，解析 LLM 输出的因果假设文本：

```python
def _parse_causal_hypotheses(self, content: str) -> List[Dict]:
    """Parse causal hypotheses from LLM output.
    
    Expected format per line: 假设：[因果陈述] | 验证数据：[需要什么数据] | 传导：[影响哪些维度]
    """
    hypotheses = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        h = {}
        for part in parts:
            part = part.strip()
            if part.startswith("假设：") or part.startswith("假设:"):
                h["statement"] = part.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif part.startswith("验证数据：") or part.startswith("验证数据:"):
                h["verification_data"] = part.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif part.startswith("传导：") or part.startswith("传导:"):
                h["transmission"] = part.split("：", 1)[-1].split(":", 1)[-1].strip()
        if h.get("statement"):
            h["status"] = "unverified"
            hypotheses.append(h)
    return hypotheses[:3]
```

**A2.2 将因果假设注入分析 prompt**

文件：`src/core/agents/generic_agent.py`
位置：`_build_analysis_prompt_with_data()` 的 framework_context 构建区域（line 4182-4195）

> **注意**：该函数内变量名是 `parts`（不是 `framework_parts`）。`parts` 在 line 4184 初始化，条件是 `if core_question or role_in_report or sibling_str or sub_aspects:`。注入方式是扩展此条件为 `... or causal_hypotheses`，确保 `parts` 被初始化后在其中追加假设内容。

```python
# A2.2: Inject causal hypotheses into analysis prompt
# 重构条件：将 causal_hypotheses 也纳入 parts 初始化判断
# 修改 line 4183: if core_question or role_in_report or sibling_str or sub_aspects:
# 改为: if core_question or role_in_report or sibling_str or sub_aspects or causal_hypotheses:
# 然后在 line 4194 之后注入：
if causal_hypotheses:
    parts.append("\n### 因果假设（必须验证或修正）")
    for i, h in enumerate(causal_hypotheses, 1):
        parts.append(f"  {i}. {h.get('statement','')}")
        parts.append(f"     验证数据需求：{h.get('verification_data','')}")
        parts.append(f"     跨维度传导：{h.get('transmission','')}")
    parts.append("\n**要求**：你的分析必须对每个假设给出「验证」「修正」或「推翻」的判断，并说明依据。")
```

同时修改 `_build_analysis_prompt_with_data()` 签名（line 4111），添加 `causal_hypotheses: Optional[List[Dict]] = None` 参数。

**A2.3 将因果假设注入搜索查询**

文件：`src/core/agents/generic_agent.py`  
位置：`_generate_smart_queries_with_llm()`（line 3765-3772）

添加 `hypotheses: Optional[List[str]] = None` 参数，在 user prompt 中注入：

```python
# A2.3: Inject hypotheses into query generation prompt
if hypotheses:
    prompt += f"\n\n待验证的因果假设：\n"
    for h in hypotheses:
        prompt += f"- {h}\n"
    prompt += "\n请重点生成能验证或反驳上述假设的搜索查询。"
```

调用点也需要传递 hypotheses：
- line 2315（初始 LLM 扩展）：此时还没有假设，不传
- line 2546（质量停滞触发的扩展）：此时已有分析结果，可从 `self._context.get("causal_hypotheses")` 读取

**A2.4 知识缺口补充搜索时使用因果假设**

文件：`src/core/agents/generic_agent.py`  
位置：`_supplementary_search_for_gaps()` 调用点（line 726）

当前：基于知识缺口（"提到但未展开的关键词"）补充搜索  
增强：同时基于因果假设中"需要但未找到的验证数据"补充搜索

```python
# A2.4: Add hypothesis-driven supplementary search
hypothesis_gaps = []
for h in self._context.get("causal_hypotheses", []):
    if h.get("status") == "unverified":
        hypothesis_gaps.append(f"{topic} {h.get('verification_data','')} 证据")
if hypothesis_gaps:
    gaps.extend(hypothesis_gaps[:3])  # 最多补充3个假设驱动的查询
```

#### A3. 实施步骤

| 步骤 | 改动 | 文件 | 工作量 |
|------|------|------|--------|
| 1 | DEEP_ANALYSIS 阶段插入假设生成 | `generic_agent.py:655` | 1h |
| 2 | `_build_analysis_prompt_with_data()` 添加 hypotheses 参数 | `generic_agent.py:4111` | 30min |
| 3 | framework_context 注入假设 | `generic_agent.py:4182-4195` | 30min |
| 4 | `_generate_smart_queries_with_llm()` 添加 hypotheses 参数 | `generic_agent.py:3765` | 20min |
| 5 | 知识缺口补充搜索添加假设驱动 | `generic_agent.py:726` | 20min |
| 6 | 调用点传参修改 | `generic_agent.py:658,733` | 15min |

#### A4. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 假设生成增加 1 次 LLM 调用 | 只在 data_points ≥ 5 时触发；假设生成 prompt 很短（~200 token），成本可控 |
| 假设可能引导分析走向错误方向 | prompt 要求"验证或修正"，不是"证明"；如果数据不支持假设，分析应推翻它 |
| 假设注入可能让 prompt 过长 | 每个假设限制 1 行，最多 3 个假设，总增量 < 200 字 |

---

### 方向 B：跨维度 claim 共享

#### B1. 设计原理

当前 `write_canonical()` 只存数字（净利润、营收等），不存 claim（"我的核心结论是X，前提条件是Y"）。维度间只能共享数字，不能共享结论。

但 `write_canonical()` 的 `value` 类型是 `Any`——它已经可以存字符串。我们不需要修改数据结构，只需要：
1. 让分析 Agent 在完成后写入 claim
2. 让其他 Agent 在分析前读取 claim

#### B2. 代码改动

**B2.1 分析完成后写入 claim**

文件：`src/core/agents/generic_agent.py`  
位置：DEEP_ANALYSIS 阶段结果处理（line 699 之后，LLM 返回分析结果后）

```python
# B2.1: Write cross-dimension claims to SharedMemory
if result.get("success") and result.get("content") and self._shared_memory:
    claims = await self._extract_claims_from_analysis(result["content"], aspect)
    for claim in claims:
        await self._shared_memory.write_canonical(
            metric=f"claim:{aspect}:{claim['id']}",
            value=claim,
            caliber="llm_inference",
            source=self.agent_id,
            publisher=aspect,
        )
```

**B2.2 claim 提取方法**

文件：`src/core/agents/generic_agent.py`  
新增方法：

```python
async def _extract_claims_from_analysis(
    self, analysis_content: str, aspect: str
) -> List[Dict]:
    """Extract structured claims from analysis output for cross-dimension sharing."""
    claim_prompt = f"""从以下「{aspect}」分析中提取核心结论（claim）。
每个 claim 必须包含：
1. statement：一句话结论
2. confidence：HIGH/MEDIUM/LOW
3.前提条件：什么条件下此结论成立
4. 跨维度影响：此结论会影响哪些其他维度

分析内容：
{analysis_content[:3000]}

输出JSON数组，最多5个claim。格式：
[{{"statement":"...", "confidence":"HIGH/MEDIUM/LOW", "前提条件":"...", "cross_impact":["维度1","维度2"]}}]"""

    result = await call_llm(
        prompt=claim_prompt,
        system_prompt="你只输出JSON数组，不要其他文字。"
    )
    if result.get("success") and result.get("content"):
        try:
            import json, re
            content = result["content"]
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                claims = json.loads(match.group())
                for i, c in enumerate(claims):
                    c["id"] = str(i)
                    c["source_aspect"] = aspect
                return claims[:5]
        except (json.JSONDecodeError, AttributeError):
            pass
    return []
```

**B2.3 分析前读取其他维度的 claim**

文件：`src/core/agents/generic_agent.py`
位置：canonical_data 补充区域（line 648-655）

> **数据访问模式说明**：现有代码通过 `self._shared_memory.get("_canonical_registry", {})` 访问规范数据，但 `_canonical_registry` 由 `MetricExtractor` 从搜索 `data_points` 中提取数值指标填充（见 `engine.py:1443-1473`），不包含通过 `write_canonical()` 写入的数据。而 claim 通过 `write_canonical(metric=f"claim:...")` 写入，存储在 `self._shared_memory._data` 中（key 格式 `canonical:claim:{aspect}:{id}`）。因此读取 claim 必须使用 `get_all_canonical()`（遍历 `_data` 中 `canonical:` 前缀的条目），而非 `_canonical_registry`。

```python
# B2.3: Read cross-dimension claims from SharedMemory
cross_dimension_claims = []
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    all_canonical = self._shared_memory.get_all_canonical()
    for key, entry in all_canonical.items():
        if key.startswith("claim:") and entry.get("publisher") != aspect:
            claim_value = entry.get("value", {})
            if isinstance(claim_value, dict) and claim_value.get("statement"):
                cross_dimension_claims.append(claim_value)
```

> `get_all_canonical()` 返回的 key 已去除 `canonical:` 前缀（如 `claim:竞争格局:0`），所以 `key.startswith("claim:")` 可正确匹配。

**B2.4 将 claim 注入分析 prompt**

文件：`src/core/agents/generic_agent.py`
位置：`_build_analysis_prompt_with_data()` 签名（line 4111）添加 `cross_dimension_claims: Optional[List[Dict]] = None`

在 framework_context 构建区域（line 4182-4195）注入：

> **注意**：该函数内变量名是 `parts`（不是 `framework_parts`），与 A2.2 相同位置。同样需将 `cross_dimension_claims` 纳入 `parts` 初始化条件。

```python
# B2.4: Inject cross-dimension claims
# 同 A2.2，需将 cross_dimension_claims 也纳入 parts 初始化判断
# 修改 line 4183: if core_question or role_in_report or sibling_str or sub_aspects:
# 改为: if core_question or role_in_report or sibling_str or sub_aspects or cross_dimension_claims:
# 然后在 causal_hypotheses 注入之后注入：
if cross_dimension_claims:
    parts.append("\n### 其他维度已确认发现（必须纳入分析考量）")
    for claim in cross_dimension_claims:
        parts.append(
            f"  - [{claim.get('source_aspect','?')}] {claim.get('statement','')}"
            f" (置信度: {claim.get('confidence','?')}, "
            f"前提: {claim.get('前提条件','?')})"
        )
    parts.append(
        "\n**要求**：如果其他维度的结论影响你的分析，必须说明如何影响；"
        "如果发现矛盾，必须指出并解释。"
    )
```

**B2.5 `write_canonical()` 冲突检测调整**

文件：`src/core/communication.py`  
位置：`write_canonical()` 冲突检测逻辑（line 218）

当前只对 `int/float` 值做冲突检测。claim 的 value 是 dict，不会触发冲突检测——这恰好是我们想要的（claim 不需要数值冲突检测）。

无需修改，现有逻辑已兼容。

**B2.6 实时 claim 注入（复用现有模式）**

文件：`src/core/agents/generic_agent.py`
位置：实时规范数据注入（line 693-698）

当前已注入其他 agent 的 canonical 数字（通过 `_canonical_registry`）。扩展为也注入 claim：

> **注意**：`_sm_latest` 来自 `self._shared_memory.get("_canonical_registry", {})`，其 key 格式是 `market_size_CNY_2024`，不包含 `write_canonical()` 写入的 claim 数据。claim 数据存储在 `self._shared_memory._data` 中（key 格式 `canonical:claim:...`），需通过 `get_all_canonical()` 读取。

```python
# B2.6: Also inject cross-dimension claims as real-time updates
if self._shared_memory and hasattr(self._shared_memory, 'get_all_canonical'):
    _all_canon = self._shared_memory.get_all_canonical()
    _claim_entries = {k: v for k, v in _all_canon.items() if k.startswith("claim:")}
    if _claim_entries:
        _cs = "\n".join([
            f"- [{v.get('value',{}).get('source_aspect','?')}] {v.get('value',{}).get('statement','')}"
            for k, v in _claim_entries.items()
            if v.get('value',{}).get('source_aspect','') != aspect
        ])
        if _cs.strip():
            prompt += f"\n\n## 其他维度最新结论\n{_cs}\n"
```

#### B3. 实施步骤

| 步骤 | 改动 | 文件 | 工作量 |
|------|------|------|--------|
| 1 | 分析后写入 claim | `generic_agent.py:699+` | 1h |
| 2 | `_extract_claims_from_analysis()` 方法 | `generic_agent.py` 新增 | 45min |
| 3 | 分析前读取 claim | `generic_agent.py:648-655` | 20min |
| 4 | prompt 注入 claim | `generic_agent.py:4182-4195` | 30min |
| 5 | 实时 claim 注入 | `generic_agent.py:693-698` | 20min |
| 6 | 调用点传参修改 | `generic_agent.py:658,733` | 15min |

#### B4. 风险与缓解

| 风险 | 缓解 |
|------|------|
| claim 提取增加 1 次 LLM 调用 | 只提取 ≤5 个 claim；prompt 短（~300 token） |
| claim 可能不准确 | 标注 caliber="llm_inference"，优先级最低；其他 agent 可选择忽略 |
| claim 数量过多导致 prompt 膨胀 | 限制每个维度 ≤5 个 claim，注入时只取其他维度（不含自身）的 claim |

---

### 方向 D：修复搜索查询的"自截杀"问题

#### D1. 设计原理

系统已有完整的搜索架构（`DomainRoleInferrer` → `_generate_search_queries()` → `_generate_smart_queries_with_llm()` → 搜索循环 → 去重 → 质量过滤），**问题不是架构缺失，而是两个"截杀点"让 LLM 扩展产出的高价值查询被丢弃**。

这是方向 A 的前置条件——如果搜索查询连"券商研报"都搜不到，因果假设驱动的精准查询更不可能通过。

#### D2. 两个截杀点

**截杀点 1：LLM prompt 告诉 LLM "禁止使用报告/分析"**

文件：`src/core/agents/generic_agent.py`  
位置：`_generate_smart_queries_with_llm()` 的 system_prompt（line 3813-3821）

```python
# 当前（截杀版）
system_prompt = f"""你是一位{role}，擅长：{', '.join(expertise)}。
你的任务是生成搜索原始数据的查询词，用于收集：{', '.join(data_focus)}。

**核心原则**：
1. 搜索原始数据（新闻、公告、统计数据、政策文件），而非现成报告
2. 禁止使用：报告、分析、研究、预测、趋势分析
3. 应该搜索：销量、产量、数据、统计、新闻、公告、政策、融资、企业动态
```

**效果**：LLM 只能生成 `"新能源汽车 销量 2025"` 这种泛查询，不能生成 `"新能源汽车 券商研报 市场份额 2025"` 这种精准查询。

**截杀点 2：`_validate_query()` 过滤掉含禁忌词的查询**

文件：`src/core/agents/generic_agent.py`  
位置：`_validate_query()`（line 3717-3723）

```python
forbidden_words = [
    "报告", "分析", "研究", "预测", "趋势分析",
    "report", "analysis", "research", "forecast"
]
if any(fw in query.lower() for fw in forbidden_words):
    return False
```

**双重截杀**：即使 LLM 无视 prompt 禁止（temperature=0.7 有概率），生成的查询也会被 `_validate_query()` 丢弃。

**被截杀的高价值查询示例**：

| LLM 可能生成的查询 | 含禁忌词？ | 能通过 _validate_query？ | 数据价值 |
|---|---|---|---|
| 新能源汽车 销量 2025 | 否 | ✅ | 低（泛） |
| 新能源汽车 行业分析报告 2025 | "分析"、"报告" | ❌ | 高 |
| McKinsey 中国电动汽车行业报告 2024 | "报告" | ❌ | 极高 |
| Gartner technology trends analysis | "analysis" | ❌ | 极高（英文） |

#### D3. 代码改动

**D3.1 修复截杀点 1：修改 LLM prompt**

文件：`src/core/agents/generic_agent.py`  
位置：`_generate_smart_queries_with_llm()` 的 system_prompt（line 3813-3821）

```python
# 修改后
system_prompt = f"""你是一位{role}，擅长：{', '.join(expertise)}。
你的任务是生成精准的搜索查询词，用于收集：{', '.join(data_focus)}。

**查询设计原则**：
1. 精准优于泛泛：
   - 差：新能源汽车 数据
   - 好：新能源汽车 渗透率 2025 乘联会
2. 指定来源类型提高精度：
   - 新能源汽车 销量 中汽协 2025
   - 比亚迪 年报 营收 2024
   - 新能源汽车 券商研报 市场份额 2025
3. 优先搜索原始数据源（新闻、公告、统计），也搜索高质量报告（券商研报、咨询报告、行业协会报告）
4. 中英文分别设计查询

**输出格式**：每行一个查询词，不要编号，不要说明文字。"""
```

**改动量**：只改 prompt 文本，不改代码逻辑。

**D3.2 修复截杀点 2：删除 `_validate_query()` 中的禁忌词过滤**

文件：`src/core/agents/generic_agent.py`  
位置：`_validate_query()`（line 3717-3723）

```python
# 删除以下 7 行：
forbidden_words = [
    "报告", "分析", "研究", "预测", "趋势分析",
    "report", "analysis", "research", "forecast"
]
if any(fw in query.lower() for fw in forbidden_words):
    return False
```

保留其他校验（长度、纯符号、重复），只删禁忌词。

**为什么不担心删除禁忌词后的风险**：
- 泛查询问题由 prompt 引导解决（D3.1），不再需要代码强制过滤
- `SearchQualityFilter` 已在搜索层面过滤低质量结果
- `_evaluate_data_quality()` 和停止条件保证搜索不会无限继续
- 即使 LLM 生成了泛查询，搜索结果的质量评分会低 → 触发 LLM 再扩展 → 自然收敛

#### D4. 次要搜索优化（非截杀，但影响质量）

**D4.1 硬编码分支与 LLM 扩展的优先级倒置**

文件：`src/core/agents/generic_agent.py`  
位置：`_generate_search_queries()` 的硬编码分支条件（line 3326）

```python
# 修改前
if is_generic_data_focus or is_data_focus_irrelevant_to_aspect or not queries:

# 修改后
if not queries:  # 只在完全没有查询时走兜底
```

**原因**：当 `DomainRoleInferrer` 返回默认模板（`data_focus = ["核心数据", "关键指标", "最新动态"]`）→ `is_generic_data_focus = True` → 走硬编码分支 → 硬编码的泛查询提前占据查询池。修改后，让 `_generate_smart_queries_with_llm()` 在初始扩展时补足精准查询，硬编码降为 fallback。

**D4.2 搜索结果无 URL 去重导致 `total_sources` 虚高**

文件：`src/core/agents/generic_agent.py`  
位置：搜索循环结果收集（line 2427-2432）

```python
# 修改前
all_results["searches"].append({
    "query": query,
    "results": results_to_store,
})
all_results["total_sources"] += len(results_to_store)  # 含重复 URL

# 修改后：在 while True 之前维护 seen_urls
seen_urls = set()

# 在结果处理时
unique_results = []
for r in results_to_store:
    url = r.get("href", "") or r.get("url", "")
    if url and url in seen_urls:
        continue
    if url:
        seen_urls.add(url)
    unique_results.append(r)

all_results["searches"].append({"query": query, "results": unique_results})
all_results["total_sources"] = len(seen_urls)
```

**影响**：`total_sources` 虚高 → `_count_high_quality_sources()` 可能在重复 URL 上重复计数 → 搜索过早满足 `MIN_SOURCES` 停止。

**D4.3 `_evaluate_data_quality()` 简单平均，不区分权威度**

文件：`src/core/agents/generic_agent.py`  
位置：`_evaluate_data_quality()`（line 3863-3885）

10 条 tier4 新闻（quality_score≈50）和 2 条 tier1 政府（quality_score≈90）混合平均 = 56.7，但不加权的真实质量感知应该是"有了权威数据，质量已够"。

```python
# 修改后：权威度加权平均
def _evaluate_data_quality(self, results: Dict[str, Any]) -> float:
    CREDIBILITY_WEIGHT = {
        "tier1_authority": 4.0,
        "tier2_professional": 3.0,
        "tier3_reputable": 2.0,
        "tier4_general": 1.0,
        "tier5_low_quality": 0.2,
    }
    weighted_sum = 0.0
    weight_sum = 0.0
    for search in results.get("searches", []):
        for result in search.get("results", []):
            quality_score = result.get("quality_score", 30)
            credibility = result.get("credibility", "tier4_general")
            weight = CREDIBILITY_WEIGHT.get(credibility, 1.0)
            weighted_sum += quality_score * weight
            weight_sum += weight
    return weighted_sum / weight_sum if weight_sum > 0 else 0.0
```

**D4.4 `_supplementary_search_for_gaps()` 只搜英文**

文件：`src/core/agents/generic_agent.py`  
位置：`_supplementary_search_for_gaps()`（line 2956-3046）

gap 描述是英文（来自 `_detect_knowledge_gaps()`），但查询只生成英文——对中国行业研究效果差。

**修复**：中英文双语生成查询，按语言路由到对应搜索引擎（已有 `_is_english_query()` 路由逻辑）。

#### D5. 实施步骤

| 步骤 | 改动 | 文件 | 工作量 | 风险 |
|------|------|------|--------|------|
| 1 | 修改 LLM prompt（D3.1） | `generic_agent.py:3813-3821` | 10min | 低 |
| 2 | 删除禁忌词过滤（D3.2） | `generic_agent.py:3717-3723` | 5min | 低 |
| 3 | 硬编码分支条件放宽（D4.1） | `generic_agent.py:3326` | 2min | 中 |
| 4 | 搜索循环 URL 去重（D4.2） | `generic_agent.py:2427-2432` | 15min | 低 |
| 5 | 质量评分加权（D4.3） | `generic_agent.py:3863-3885` | 15min | 低 |
| 6 | 补充搜索中英双语（D4.4） | `generic_agent.py:2956-3046` | 15min | 低 |

**步骤 1+2 是核心**：2 处改动（改 7 行 prompt + 删 7 行代码），让已有的 LLM 扩展真正发挥作用。其余是辅助优化。

**总工作量：~1h**

#### D6. 与方向 A 的关系

方向 D 是方向 A 的前置条件：
- **没有 D**：A 的因果假设即使注入到 `_generate_smart_queries_with_llm()`，生成的精准查询仍会被禁忌词过滤截杀
- **有了 D**：A 的因果假设可以生成"新能源汽车 补贴退坡 市场化转型 证据"这种因果验证查询，且不会被截杀

但 D 可以独立实施且**应该最先实施**——它是投入产出比最高的改动（1h 工作量，效果立竿见影）。

---

## 三、四个方向的依赖关系

```
方向 D（修复搜索截杀）← 最先实施，1h 工作量，效果立竿见影
    ↓ 解除搜索限制
方向 B（跨维度 claim 共享）
    ↓ 提供基础设施
方向 C（战略意图推断维度）← 依赖 B 读取其他维度 claim
    ↓ 产出战略意图理解
方向 A（因果假设驱动搜索）← 有了意图理解，假设才有据可依；有了 D，假设查询不被截杀
```

**每个方向都可以独立实施**：
- D 可以独立实施且应最先实施——它是 A 的前置条件
- C 不依赖 B：没有 B 时，C 用前序分析文本（与现有合成逻辑一致）替代结构化 claim
- A 不依赖 C：没有 C 时，A 的因果假设基于数据生成（而非意图推断），仍然有效
- B 可以独立实施：即使没有 A/C，维度间共享 claim 也能提升分析质量

---

## 四、实施优先级与时间估算

| 阶段 | 方向 | 工作量 | 前置依赖 |
|------|------|--------|---------|
| P0 | D3.1-D3.2（修复搜索截杀，核心2步） | ~15min | 无 |
| P0+ | D4.1-D4.4（搜索辅助优化） | ~45min | 无 |
| P1 | C2.1-C2.5（战略意图维度基础） | ~40min | 无 |
| P2 | B2.1-B2.6（跨维度 claim 共享） | ~3h | 无 |
| P3 | C2.6（战略意图维度 + claim 注入） | ~30min | P2 |
| P4 | A2.1-A2.6（因果假设驱动搜索） | ~3h | P0（需要 D 解除搜索限制） |
| P5 | 集成测试 | ~2h | P0-P4 |

**总计：~10h**

P0（15min）投入产出比最高——2 处改动让已有 LLM 扩展真正发挥作用。

---

## 五、验证标准

| 方向 | 验证方法 | 通过标准 |
|------|---------|---------|
| D | 搜索查询包含"券商研报"、"咨询报告"等关键词 | 之前被禁忌词截杀的查询现在能通过 |
| D | `_validate_query()` 不再因禁忌词拒绝查询 | 含"报告/分析"的查询返回 True |
| D | `total_sources` 不再虚高 | 同一 URL 只计数一次 |
| C | 生成报告包含"战略意图推断"章节 | 章节内容不是描述现象，而是推断动机 |
| C | 战略意图维度在 SYNTHESIS 阶段执行 | 确认 dependencies 包含所有 DEEP_ANALYSIS agents |
| A | 搜索查询包含因果假设相关关键词 | 对比有/无假设时的查询差异 |
| A | 分析输出包含"验证/修正/推翻假设"的判断 | 不是简单复述假设 |
| B | SharedMemory 中出现 `claim:*` key | `get_all_canonical()` 包含 claim 条目 |
| B | 分析 prompt 包含"其他维度已确认发现" | `_build_analysis_prompt_with_data()` 输出包含注入的 claim |

---

## 六、不做的事

| 不做 | 原因 |
|------|------|
| 增加更多正则/域名硬编码 | 治标不治本，方向 D 用 prompt 引导替代代码过滤 |
| 加权平均合成 | 不解决因果深度问题，只是平均化 |
| 修改合成阶段为多步推理 | 改动太大（1次→多次LLM调用），风险高，收益不确定 |
| 硬编码行业特定规则 | 违反通用性原则，且不可扩展 |
