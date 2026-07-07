# llm_skill → call_llm 迁移方案（v2 — 基于代码审计修订）

> 本文档基于对项目源码的逐文件审计，修正了 v1 版本中的遗漏和错误，新增了 3 个遗漏模块、3 个运行时 bug、以及返回格式兼容性风险的详细分析。

## 1. 问题概述

系统中存在两套并行的 LLM 调用机制：

| 机制 | 位置 | 特性 |
|------|------|------|
| `LLMSkill` (llm_skill) | `src/skills/llm_skill.py` (173行) | Skill 接口，自用 `AsyncOpenAI` 调 API，无 profile 路由（除 routing_hint 透传分支），无 streaming |
| `call_llm()` | `src/core/llm_client.py` (384行) | 独立工具函数，支持 profile 路由、多 profile fallback、streaming、vision、sync wrapper |

**核心矛盾**：`LLMSkill` 是早期将 LLM 能力建模为"外部技能"的设计产物。实际上 LLM 是 Agent 的内在能力，不应经过 Skill 注册表。`call_llm()` 已是更完善、更底层的实现，但 `LLMSkill` 仍未完全退役。

## 2. 当前状态分类

### 2.1 已迁移到 call_llm() 的模块 ✅

| 模块 | 位置 | 说明 |
|------|------|------|
| GenericAgent | `src/core/agents/generic_agent.py` | `ACTION_TO_SKILL` 中 `llm_skill` 仅作路由标签，实际执行全部走 `call_llm()` / `_call_llm_directly()` |
| ChapterWriter | `src/agents/fixed_agents/report_upgrade/chapter_writer.py:17-18` | 构造函数接受 `llm_skill=None` 但标注 "backward compatibility"，内部用 `call_llm()` |
| ChapterReviewer | `src/agents/fixed_agents/report_upgrade/chapter_reviewer.py:15` | 同上 |
| GlobalReviewer | `src/agents/fixed_agents/report_upgrade/global_reviewer.py:17` | 同上 |
| ReportOrchestrator | `src/agents/fixed_agents/report_upgrade/orchestrator.py:159` | 构造函数标注 "backward compatibility"，内部用 `call_llm()` |
| DataRepair | `src/agents/fixed_agents/report_upgrade/data_repair.py:45` | 接受 `llm_skill=None` 但不使用（参数残留），内部直接 `call_llm()` |
| ConflictResolver | `src/agents/fixed_agents/report_upgrade/data_repair.py:124` | 同上 |
| ResearchAPI | `src/api/research_api.py` | 直接 `call_llm()` / `call_llm_stream()` |
| SemanticIntent | `src/core/semantic_intent.py:283,323` | 分析方法直接 `call_llm()`，但 `_get_llm_skill()` 方法仍存在（见 2.2.C） |
| AnnualReportParser | `src/skills/analysis/annual_report_parser.py` | 直接 `call_llm()` / `call_llm_vision()` |

### 2.2 仍依赖 llm_skill 实例的模块 ❌

#### A. 分析 Skill（通过 `reg.get("llm_skill")` 获取后调用 `.execute()`）

| 模块 | 位置 | 调用方式 | `.execute()` 次数 |
|------|------|---------|-------------------|
| data_analysis | `src/skills/analysis/data_analysis.py:308` | `llm = reg.get("llm_skill")` → `llm.execute()` | 1 |
| market_analysis | `src/skills/analysis/market_analysis.py:53` | `llm = reg.get("llm_skill")` → `llm.execute()` | 1 |
| policy_analysis | `src/skills/analysis/policy_analysis.py:43` | `llm = reg.get("llm_skill")` → `llm.execute()` | 1 |
| risk_analysis | `src/skills/analysis/risk_analysis.py:30` | `llm = reg.get("llm_skill")` → `llm.execute()` | 1 |
| stock_analysis | `src/skills/analysis/stock_analysis.py:67` | `reg.get("llm_skill")` → `llm.execute()` | 5（通过 `_get_llm()` 辅助方法） |
| tech_trend | `src/skills/analysis/tech_trend.py:42` | `llm = reg.get("llm_skill")` → `llm.execute()` | 1 |

**共 6 个分析 Skill**，统一模式：构造 prompt → `llm_skill.execute(prompt=...)` → 解析返回。均未导入 `call_llm`。

#### B. Survey/Simulation 子系统（通过构造函数注入 + `.execute()` 调用）

##### B1. 直接调用 `.execute()` 的模块（8 个）

| 模块 | 位置 | `.execute()` 行号 | 特殊问题 |
|------|------|-------------------|---------|
| persona_generation_agent | `src/agents/fixed_agents/persona_generation_agent.py` | :341 | — |
| survey_optimization_agent | `src/agents/fixed_agents/survey_optimization_agent.py` | :329 | — |
| cross_synthesis_agent | `src/agents/fixed_agents/cross_synthesis_agent.py` | :45 | `asyncio.wait_for` 包裹，timeout=60s |
| document_generation_agent | `src/agents/fixed_agents/document_generation_agent.py` | :1714 | **⚠️ `asyncio.run()` 包裹——运行时 bug**（见第5节） |
| focus_group | `src/survey/engine/focus_group.py` | :362 | `asyncio.wait_for` 包裹，timeout=15s |
| persona_generator | `src/survey/engine/persona_generator.py` | :89 | `asyncio.wait_for` 包裹，timeout=30s |
| simulation_engine (engine) | `src/survey/engine/simulation_engine.py` | :357 | `asyncio.wait_for` 包裹 + 调用 `.is_available()` |
| simulation_engine (services) | `src/survey/services/simulation_engine.py` | :132 | `hasattr(self.llm_skill, 'execute')` 防御性检查 |
| **sentiment** | **`src/survey/analysis/sentiment.py`** | **:284** | **⚠️ v1 遗漏！`asyncio.run()` 包裹——运行时 bug**（见第5节） |

##### B2. 透传 llm_skill 的中间层（7 个）

| 模块 | 位置 | 透传目标 |
|------|------|---------|
| survey_integration_agent | `src/agents/fixed_agents/survey_integration_agent.py:483,533,550,571,980,1004` | → PersonaGenerationAgent / SimulatedResponseAgent / SurveyAnalysisAgent / SurveyOptimizationAgent |
| simulated_response_agent | `src/agents/fixed_agents/simulated_response_agent.py:82` | → SimulationEngine |
| persona_skill | `src/skills/builtin/persona_skill.py:57` | → PersonaGenerationAgent |
| simulation_skill | `src/skills/builtin/simulation_skill.py:57` | → SimulatedResponseAgent |
| ai_simulation | `src/survey/backends/ai_simulation.py:35,98` | → PersonaGeneratorV2 / SimulationExecutor |
| **task_api** | **`src/survey/task_api.py:147-148`** | **⚠️ v1 遗漏！`reg.get("llm_skill")` → SimulationExecutor** |
| persona_factory | `src/survey/services/persona_factory.py:92` | 存储 `self.llm_skill` 但从未使用（死代码） |

##### B3. 仅存储不使用的模块（2 个）

| 模块 | 位置 | 说明 |
|------|------|------|
| survey_analysis_agent | `src/agents/fixed_agents/survey_analysis_agent.py:66,71` | 存储 `self.llm_skill` 但从未调用 `.execute()` 或透传——**死代码** |
| persona_factory | `src/survey/services/persona_factory.py:91-92` | 存储 `self.llm_skill` 但从未使用——**死代码** |

#### C. 直接实例化 LLMSkill 的模块（3 个，删除 `llm_skill.py` 后会崩溃）

| 模块 | 位置 | 调用方式 |
|------|------|---------|
| **registry.py** | `src/skills/registry.py:328` | `from .llm_skill import LLMSkill` → `self.register(LLMSkill())` |
| **semantic_intent.py** | `src/core/semantic_intent.py:218-219` | `from src.skills.llm_skill import LLMSkill` → `self._llm_skill = LLMSkill()` |
| **__init__.py** | `src/skills/__init__.py:28` | `from src.skills.llm_skill import LLMSkill` （顶层导出） |

#### D. 配置/映射层面（字符串引用 "llm_skill"）

| 模块 | 位置 | 引用数 | 说明 |
|------|------|--------|------|
| strategies.py | `src/core/decomposition/strategies.py` | 37 | `ASPECT_SKILL_MAP` (25项) / `SKILL_PRIORITY_MAP` / `DEFAULT_ASPECT_SKILLS` / AgentSpec skills |
| orchestrator.py | `src/core/orchestrator/orchestrator.py` | 22 | 3处获取实例 + 注入 + 技能列表 |
| generic_agent.py | `src/core/agents/generic_agent.py` | 14 | `ACTION_TO_SKILL` (10项) + 执行分支判断 |
| semantic_intent.py | `src/core/semantic_intent.py` | 13 | 意图→技能映射 + `_get_llm_skill()` |
| skill_keywords.py | `src/skills/skill_keywords.py` | 8 | `LLM_FALLBACK_SKILL` 常量 + 描述 + 文档 |
| registry.py | `src/skills/registry.py` | 11 | `CATEGORY_TO_SKILLS` (9项) + 特殊分支 |
| factory.py | `src/core/agents/factory.py` | 9 | `_SKILL_ALIAS_MAP` (6项) + fallback 注入 |
| intelligent_routing_adapter.py | `src/core/intelligent_routing_adapter.py` | 9 | `recommended_skills` 模板 (7项) |
| task_structure.py | `src/core/task_structure.py` | 2 | 默认技能需求 |
| prompt_manager.py | `src/core/prompt_manager.py` | 1 | 默认返回 `["llm_skill", "search_skill"]` |
| discovery.py | `src/skills/discovery.py` | 1 | `llm = "llm_skill"` |
| **business/__init__.py** | **`src/skills/business/__init__.py`** | **2** | **⚠️ v1 遗漏！docstring 中引用 `llm_skill`** |

## 3. 功能差异对比

| 特性 | `LLMSkill.execute()` | `call_llm()` |
|------|---------------------|-------------|
| OpenAI 兼容 API | ✅ | ✅ |
| 主/备模型 fallback | ✅ | ✅ |
| Profile 路由（LLMProfileRegistry） | ⚠️ 仅 `routing_hint` 透传分支 | ✅ 完整支持（多 profile 遍历 + fallback_profile） |
| Client 连接池 | ❌ 每次新建 `AsyncOpenAI` | ❌ 同样每次新建 `AsyncOpenAI` |
| Streaming | ❌ | ✅ `call_llm_stream()` |
| Vision/Multimodal | ❌ | ✅ `call_llm_vision()` |
| 同步包装 | ❌ | ✅ `call_llm_sync()` |
| Cost limit 检查 | ✅ 全局 `cost_limit_per_report` | ✅ Profile 级 + 全局 |
| `fallback_profile` 追踪 | ❌ | ✅ 返回 `fallback_profile` 字段 |
| 返回格式 | `{success, message, **data}` | `{success, content, model, usage, message}` |

## 4. 返回格式兼容性分析（关键）

### 4.1 成功路径

```python
# LLMSkill._parse_response() → Skill._success(data, message)
# _success 实现: return {"success": True, "message": message, **data}
# 因此 LLMSkill 返回:
{"success": True, "message": "LLM call successful", "content": "...", "model": "...", "usage": {...}}

# call_llm._parse_response() 直接构造:
{"success": True, "content": "...", "model": "...", "usage": {...}, "message": "LLM call successful"}
```

**结论**：成功路径的 key 集合完全一致，仅顺序不同。Python dict 不区分顺序，**迁移无需改动成功路径的返回值解析逻辑**。

### 4.2 失败路径 ⚠️

```python
# Skill._failure() 签名: _failure(error, message)
# 实际实现: return {"success": False, "message": message, "error": error}

# LLMSkill 调用示例:
self._failure("prompt cannot be empty")
# → {"success": False, "message": "Execution failed", "error": "prompt cannot be empty"}

self._failure(f"Estimated cost...", "Cost limit triggered")
# → {"success": False, "message": "Cost limit triggered", "error": "Estimated cost..."}

# call_llm 失败返回:
{"success": False, "message": "prompt cannot be empty", "error": "empty_prompt"}
{"success": False, "message": f"Estimated cost...", "error": "cost_limit"}
{"success": False, "message": f"Primary: {err}; Fallback: {err2}", "error": "llm_call_failed"}
```

**差异**：
- `error` 字段：LLMSkill 存放**用户可读信息**（如 "prompt cannot be empty"），call_llm 存放**错误码**（如 "empty_prompt"）
- `message` 字段：LLMSkill 存放**默认值或简短描述**（如 "Execution failed"），call_llm 存放**用户可读信息**

**影响**：如果消费方检查 `result["error"]` 的具体内容做分支判断（如 `if "not available" in result["error"]`），迁移后逻辑会不同。经验证，6 个分析 Skill 均只检查 `result.get("success")`，不解析 `error` 内容，**但 survey 子系统中有检查 `error` 的代码需逐一确认**。

### 4.3 `fallback_used` 字段

- LLMSkill：在 `_parse_response()` 返回后追加 `result["fallback_used"] = True`，无 `fallback_profile`
- call_llm：在 profile fallback 路径追加 `result["fallback_used"] = True` + `result["fallback_profile"] = "profile_name"`

**影响**：新增的 `fallback_profile` 字段不会破坏现有代码（Python dict 忽略多余 key），但消费方不会获得此信息。

## 5. 已发现的运行时 Bug（与迁移相关）

### Bug 1：`intelligent_routing_adapter.py:521` 导入不存在的模块 🔴

```python
from src.core.llm import call_llm  # ← 不存在！
```

项目中不存在 `src/core/llm.py`。正确的导入路径是 `src.core.llm_client`。其他 32 处 `call_llm` 导入均使用正确路径。

**影响**：当 `_generate_hypotheses_with_llm()` 被调用时，触发 `ImportError`，功能静默失败。虽然这是 fallback 路径，但属于运行时 bug。

**修复**：改为 `from src.core.llm_client import call_llm`。

### Bug 2：`document_generation_agent.py:1714` 在 async 上下文中使用 `asyncio.run()` 🔴

```python
llm_result = asyncio.run(self._llm_skill.execute(...))
```

`asyncio.run()` 会创建新的事件循环。如果 `document_generation_agent` 的调用方已在 async 上下文中运行（这在当前系统中极可能），将抛出 `RuntimeError("This event loop is already running")`。

**影响**：`_apply_adjustment()` 方法的 LLM 辅助修订功能可能完全不可用。

**迁移修复**：改为 `result = await call_llm(...)` 即可同时解决 bug 和完成迁移。

### Bug 3：`sentiment.py:283-292` 同样使用 `asyncio.run()` 包裹 `.execute()` 🔴

```python
llm_result = asyncio.run(
    self.llm_skill.execute(prompt=..., temperature=0.3, max_tokens=10)
)
```

与 Bug 2 相同的问题。`sentiment.py` 的 `_llm_enhance()` 方法是同步方法，使用 `asyncio.run()` 调用异步的 `llm_skill.execute()`，在已有事件循环时会崩溃。

**迁移修复**：改用 `call_llm_sync()`（`call_llm` 的同步包装器），或将 `_llm_enhance()` 改为 async 方法后用 `await call_llm()`。

### Bug 4：`simulation_engine.py:176-177` 调用 `is_available()` 但 Skill 基类无此方法 🟡

```python
if hasattr(self._llm_skill, "is_available"):
    if not self._llm_skill.is_available():
```

`Skill` 基类（`src/skills/base.py`）没有 `is_available()` 方法，只有 `is_enabled()`。`hasattr` 检查使其不会崩溃，但逻辑上永远不会触发 `LLMConfigurationError`。

**迁移修复**：移除此检查，`call_llm()` 内部已包含可用性验证。

## 6. 迁移方案

### 6.1 分析 Skill 迁移（6个，简单）

**模式**：`reg.get("llm_skill")` → `llm.execute(prompt=...)` → 解析 `result["content"]`

**目标模式**：`from src.core.llm_client import call_llm` → `result = await call_llm(prompt=...)` → 解析 `result["content"]`

**逐文件改动**：

| 文件 | 改动 |
|------|------|
| `data_analysis.py` | 移除 `from src.skills.registry import get_skill_registry`（:22），移除 `reg.get("llm_skill")`（:308），添加 `from src.core.llm_client import call_llm`，将 `await llm.execute(prompt=...)`（:316）改为 `await call_llm(prompt=...)` |
| `market_analysis.py` | 同上。移除 :51, :53 的 registry 导入和获取，改为 `call_llm`。移除 :55 的 `_failure("llm_skill not available")` 替换为直接 `call_llm`（无需 null 检查） |
| `policy_analysis.py` | 同上。移除 :41, :43, :45 |
| `risk_analysis.py` | 同上。移除 :28, :30, :32 |
| `stock_analysis.py` | 移除 `_get_llm()` 辅助方法（:65-67），5 处 `llm.execute()`（:201,:237,:273,:311,:356）全部改为 `call_llm()`，移除 :47-49 的 null 检查 |
| `tech_trend.py` | 同上。移除 :40, :42, :44 |

**风险**：低。所有 Skill 仅检查 `result.get("success")` 和 `result.get("content")`，不依赖 `error` 字段内容。

**注意事项**：
- `stock_analysis.py` 内部有 5 个子方法各调用 `llm.execute()`，需逐一替换
- 3 个 Skill（data_analysis, market_analysis, stock_analysis）同时使用 `reg.get("lc_python_repl")`，迁移后仍需保留 `get_skill_registry` 导入给 Python REPL 用

### 6.2 Survey/Simulation 子系统迁移（19个，中等）

> v1 文档列出 17 个模块，v2 新增 `sentiment.py` 和 `task_api.py`。

#### Layer 0：修复运行时 Bug（优先）

| 文件 | Bug | 修复 |
|------|-----|------|
| `document_generation_agent.py:1714` | `asyncio.run()` 在已有事件循环时崩溃 | 改为 `result = await call_llm(prompt=...)` |
| `sentiment.py:283-292` | `asyncio.run()` 同上 | 改用 `call_llm_sync()` 或将方法改为 async + `await call_llm()` |

#### Layer 1：底层引擎（直接 `.execute()` 调用者，8 个）

| 文件 | `.execute()` 行 | 改动 | 超时保护 |
|------|-----------------|------|---------|
| `persona_generator.py` | :89 | `self.llm_skill` → 可选，内部 `call_llm()` | 原有 `wait_for(timeout=30)`，需保留 |
| `simulation_engine.py` (engine/) | :357 | 同上 | 原有 `wait_for(timeout=RetryHandler.TIMEOUT)`，需保留 |
| `simulation_engine.py` (services/) | :132 | 同上 | 无超时，迁移后建议添加 |
| `focus_group.py` | :362 | 同上 | 原有 `wait_for(timeout=15)`，需保留 |
| `persona_generation_agent.py` | :341 | 同上 | 无超时 |
| `survey_optimization_agent.py` | :329 | 同上 | 无超时 |
| `cross_synthesis_agent.py` | :45 | 同上 | 原有 `wait_for(timeout=60)`，需保留 |
| `sentiment.py` | :284 | 同上 | 无超时，改用 `call_llm_sync()` |

**关键**：`call_llm()` 本身不设超时，迁移时必须保留原有的 `asyncio.wait_for()` 包裹，否则可能无限等待。

#### Layer 2：中间层（透传者，7 个）

| 文件 | 改动 |
|------|------|
| `persona_factory.py` | 删除 `llm_skill` 参数（存储但从未使用——死代码） |
| `ai_simulation.py` | 不再透传 `llm_skill`，删除该参数 |
| `persona_skill.py` | 不再透传 `llm_skill`，删除该参数 |
| `simulation_skill.py` | 不再透传 `llm_skill`，删除该参数 |
| `survey_integration_agent.py` | 移除 6 处 `llm_skill=self.llm_skill` 透传 |
| `simulated_response_agent.py` | 移除 `SimulationEngine(llm_skill=...)` 中的 `llm_skill` 参数 |
| **`task_api.py`** | **⚠️ v1 遗漏！移除 :147 的 `reg.get("llm_skill")` 和 :148 的 `llm_skill=llm_skill`** |

#### Layer 3：Agent 层

| 文件 | 改动 |
|------|------|
| `persona_generation_agent.py` | 移除 `llm_skill` 构造参数（:69），内部用 `call_llm()` |
| `simulated_response_agent.py` | 移除 `llm_skill` 构造参数（:64） |
| `survey_analysis_agent.py` | 移除 `llm_skill` 构造参数（:66）——**死代码，存储但从未使用** |
| `survey_integration_agent.py` | 移除 `llm_skill` 构造参数（:88） |
| `survey_optimization_agent.py` | 移除 `llm_skill` 构造参数（:89），内部用 `call_llm()` |
| `cross_synthesis_agent.py` | 移除 `llm_skill` 构造参数（:12），内部用 `call_llm()` |
| `document_generation_agent.py` | 移除 `set_llm_skill()` 方法（:139-146），移除 `self._llm_skill`（:116），内部用 `call_llm()` |

#### Layer 4：已迁移但参数残留的模块

| 文件 | 改动 |
|------|------|
| `chapter_writer.py` | 移除 `llm_skill=None` 参数（:17） |
| `chapter_reviewer.py` | 移除 `llm_skill=None` 参数（:15） |
| `global_reviewer.py` | 移除 `llm_skill=None` 参数（:17） |
| `orchestrator.py` (report_upgrade) | 移除 `llm_skill=None` 参数（:159） |
| `data_repair.py` | 移除 `DataRepairAgent` 的 `llm_skill=None`（:45）和 `ConflictResolver` 的 `llm_skill=None`（:124） |

**风险**：中。需同步修改 `orchestrator.py` 中 3 处对这些模块的实例化代码（:1064-1082, :2289-2307, :3348-3354），移除所有 `llm_skill=_llm_skill` / `llm_skill=llm_skill` 传参。

### 6.3 直接实例化 LLMSkill 的模块清理（3个）

| 文件 | 改动 |
|------|------|
| `registry.py:324-330` | 删除 `LLMSkill` 自动注册段 |
| `semantic_intent.py:207-220` | 删除 `self._llm_skill` 属性（:207）和 `_get_llm_skill()` 方法（:210-220），以及所有调用此方法的地方 |
| `skills/__init__.py:28,68` | 删除 `from src.skills.llm_skill import LLMSkill` 和 `__all__` 中的 `"LLMSkill"` |

### 6.4 配置/映射层清理（字符串引用）

**目标**：`"llm_skill"` 字符串不再代表一个真实的 Skill 实例，而是代表"需要 LLM 能力"的语义标签。

#### Phase 1：保留字符串，改变语义

`"llm_skill"` 在 `ACTION_TO_SKILL`、`ASPECT_SKILL_MAP`、`CATEGORY_SKILL_MAP` 等映射中保留，但语义从"调用 `LLMSkill.execute()`"变为"需要 LLM 能力，由 Agent 内部 `call_llm()` 履行"。`GenericAgent` 已按此模式运行。

此阶段**不需要改映射表**。

#### Phase 2：注销 LLMSkill 实例

当 6.1、6.2、6.3 完成后：

1. 从 `registry.py` 中移除 `LLMSkill` 的自动注册（已在 6.3 中处理）
2. 清理 `registry.py` 中的 `load_skills_for_category()` 中 `llm_skill` 特殊分支（:430-434）
3. 清理 `registry.py` 中的 `discover_skills()` 中 `llm_skill` 特殊分支（:483-487）
4. 删除 `src/skills/llm_skill.py`

#### Phase 3：重命名（可选）

将所有映射中的 `"llm_skill"` 重命名为 `"llm"` 或 `"intrinsic_llm"`，更准确地反映其语义。涉及文件：

| 文件 | 引用数 | 改动性质 |
|------|--------|---------|
| `generic_agent.py` | 14 | `ACTION_TO_SKILL` + 执行分支判断 |
| `strategies.py` | 37 | `ASPECT_SKILL_MAP` / `SKILL_PRIORITY_MAP` / `DEFAULT_ASPECT_SKILLS` / AgentSpec |
| `factory.py` | 9 | `_SKILL_ALIAS_MAP` + fallback |
| `semantic_intent.py` | 7 | 意图→技能映射（不含 `_get_llm_skill`，已在 6.3 清理） |
| `skill_keywords.py` | 8 | `LLM_FALLBACK_SKILL` 常量 + 描述 |
| `registry.py` | 11 | `CATEGORY_TO_SKILLS` + 特殊分支 |
| `task_structure.py` | 2 | 默认技能需求 |
| `discovery.py` | 1 | `llm = "llm_skill"` |
| `intelligent_routing_adapter.py` | 9 | `recommended_skills` 模板 |
| `prompt_manager.py` | 1 | 默认返回值 |
| `orchestrator.py` | 5 | 技能列表（不含实例注入，已在 6.2 清理） |
| `business/__init__.py` | 2 | docstring 注释 |

**总计约 106 处字符串引用**，可使用全局替换完成。

### 6.5 修复独立 Bug

| Bug | 文件 | 修复 | 优先级 |
|-----|------|------|--------|
| 导入不存在的 `src.core.llm` | `intelligent_routing_adapter.py:521` | 改为 `from src.core.llm_client import call_llm` | **P0** |
| `asyncio.run()` 事件循环冲突 | `document_generation_agent.py:1714` | 改为 `await call_llm()` | **P0** |
| `asyncio.run()` 事件循环冲突 | `sentiment.py:283` | 改用 `call_llm_sync()` 或改为 async | **P0** |
| `.is_available()` 方法不存在 | `simulation_engine.py:176-177` | 移除检查 | **P2** |

## 7. 执行顺序

```
Step 0: 修复独立 Bug（6.5）                     ← P0，可立即修复
Step 1: 迁移 6 个分析 Skill（6.1）              ← 最简单，无依赖
Step 2: 迁移 Survey/Simulation 子系统（6.2）     ← 中等，需同步改 Orchestrator
Step 3: 清理直接实例化 LLMSkill 的模块（6.3）     ← 删除注册 + 清理方法
Step 4: Phase 1 确认映射语义（6.4）              ← 无代码改动，仅确认
Step 5: Phase 2 注销 LLMSkill 实例（6.4）        ← 删除注册 + 清理特殊分支 + 删除文件
Step 6: Phase 3 重命名（6.4，可选）              ← 全局字符串替换
```

## 8. 影响范围

| 区域 | 涉及文件数 | 风险 | v1→v2 变化 |
|------|-----------|------|-----------|
| 分析 Skill | 6 | 低 | — |
| Survey/Simulation | 19 | 中 | +2（sentiment.py, task_api.py） |
| Orchestrator 实例化 | 1 (orchestrator.py) | 中 | — |
| 直接实例化 LLMSkill | 3 | 中 | 新增分类 |
| 配置/映射 | ~12 | 低（字符串替换） | +1（business/__init__.py） |
| Registry | 1 | 低 | — |
| llm_skill.py 本体 | 1 | 删除 | — |
| 独立 Bug 修复 | 4 | — | 新增分类 |

**总计约 47 个文件**（v1 为 42 个），大部分改动是机械性的字符串替换和参数删除。

## 9. 测试验证

每步完成后需验证：

1. **单元测试**：确认 `call_llm()` 返回格式与 `llm_skill.execute()` 在成功路径上兼容（两者 key 集合一致，仅顺序不同）
2. **失败路径测试**：确认消费方不依赖 `error` 字段的具体内容做分支判断
3. **超时保护**：确认迁移后的模块保留原有 `asyncio.wait_for()` 超时包裹
4. **集成测试**：运行完整报告生成流程，确认分析 Skill 和 Survey 子系统正常
5. **回归测试**：确认 `GenericAgent` 的 `llm_skill` 路径不受影响
6. **Profile 路由**：确认迁移后的模块能正确走 `LLMProfileRegistry` 路由
7. **asyncio.run() 消除**：确认不再有 `asyncio.run()` 包裹 LLM 调用的代码

## 10. v1 → v2 修订记录

| 项目 | v1 | v2 | 原因 |
|------|----|----|------|
| 遗漏模块 | — | `sentiment.py` | 代码审计发现 `.execute()` 调用 |
| 遗漏模块 | — | `task_api.py` | 代码审计发现 `reg.get("llm_skill")` |
| 遗漏引用 | — | `business/__init__.py` | docstring 中引用 llm_skill |
| 返回格式 | "完全一致" | 成功路径一致，失败路径 `error`/`message` 语义不同 | `_failure()` 签名分析 |
| Bug 1 | 未提及 | `intelligent_routing_adapter.py` 导入错误模块 | 代码审计 |
| Bug 2 | 未提及 | `document_generation_agent.py` 的 `asyncio.run()` | 代码审计 |
| Bug 3 | 未提及 | `sentiment.py` 的 `asyncio.run()` | 代码审计 |
| Bug 4 | 未提及 | `simulation_engine.py` 调用不存在的 `.is_available()` | 代码审计 |
| 超时保护 | 未提及 | 迁移时必须保留 `asyncio.wait_for()` | `call_llm()` 无内置超时 |
| 直接实例化 | 归入配置层 | 独立分类（6.3） | 删除 `llm_skill.py` 后会触发 ImportError |
| `SurveyAnalysisAgent` | "仅透传给子 Agent" | "存储但从未使用——死代码" | 代码审计发现无透传 |
| `PersonaFactory` | "透传者" | "存储但从未使用——死代码" | 代码审计发现无透传 |
