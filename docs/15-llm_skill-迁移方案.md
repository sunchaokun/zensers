# llm_skill → call_llm 迁移方案

## 1. 问题概述

系统中存在两套并行的 LLM 调用机制：

| 机制 | 位置 | 特性 |
|------|------|------|
| `LLMSkill` (llm_skill) | `src/skills/llm_skill.py` (委托模式) | Skill 接口，**已委托到 `call_llm()`**，DEPRECATED |
| `call_llm()` | `src/core/llm_client.py` (384行) | 独立工具函数，支持 profile 路由、fallback、streaming、vision、sync wrapper |

**核心矛盾**：`LLMSkill` 是早期将 LLM 能力建模为"外部技能"的设计产物。实际上 LLM 是 Agent 的内在能力，不应经过 Skill 注册表。`call_llm()` 已是更完善、更底层的实现。

**当前状态**：迁移已完成，`llm_skill.py` 保留为向后兼容委托（DEPRECATED），所有 `execute()` 内部转发到 `call_llm()`。

## 2. 迁移完成状态

### 2.1 已迁移到 call_llm() 的模块 ✅

| 模块 | 位置 | 说明 |
|------|------|------|
| GenericAgent | `src/core/agents/generic_agent.py` | `ACTION_TO_SKILL` 中 LLM 映射改为 `None`，走内在 `call_llm()` 路径 |
| ChapterWriter | `src/skills/builtin/chapter_writer.py` | 移除 `llm_skill=None` 参数，内部用 `call_llm()` |
| ChapterReviewer | `src/skills/builtin/chapter_reviewer.py` | 同上 |
| GlobalReviewer | `src/skills/builtin/global_reviewer.py` | 同上 |
| DataRepair | `src/agents/fixed_agents/report_upgrade/data_repair.py` | 移除 `llm_skill=None` 参数 |
| ConflictResolver | `src/agents/fixed_agents/report_upgrade/data_repair.py` | 同上 |
| ResearchAPI | `src/api/research_api.py` | 直接 `call_llm()` / `call_llm_stream()` |
| SemanticIntent | `src/core/semantic_intent.py` | 移除 `_llm_skill` 属性和 `_get_llm_skill()` 方法 |
| AnnualReportParser | `src/skills/analysis/annual_report_parser.py` | 直接 `call_llm()` / `call_llm_vision()` |
| data_analysis | `src/skills/analysis/data_analysis.py` | `reg.get("llm_skill")` → `call_llm()` |
| market_analysis | `src/skills/analysis/market_analysis.py` | 同上 |
| policy_analysis | `src/skills/analysis/policy_analysis.py` | 同上 |
| risk_analysis | `src/skills/analysis/risk_analysis.py` | 同上 |
| stock_analysis | `src/skills/analysis/stock_analysis.py` | 移除 `_get_llm()`，5 处 → `call_llm()` |
| tech_trend | `src/skills/analysis/tech_trend.py` | `reg.get("llm_skill")` → `call_llm()` |
| persona_generation_agent | `src/agents/fixed_agents/persona_generation_agent.py` | 移除 `llm_skill` 参数，`call_llm()` |
| survey_optimization_agent | `src/agents/fixed_agents/survey_optimization_agent.py` | 同上 |
| cross_synthesis_agent | `src/agents/fixed_agents/cross_synthesis_agent.py` | 完全重写，`call_llm()` |
| document_generation_agent | `src/agents/fixed_agents/document_generation_agent.py` | 移除 `set_llm_skill`，`_handle_adjust_content` 改 async + `call_llm()` |
| focus_group | `src/survey/engine/focus_group.py` | 移除 `llm_skill` 参数，`call_llm()` |
| persona_generator | `src/survey/engine/persona_generator.py` | 同上 |
| simulation_engine (engine) | `src/survey/engine/simulation_engine.py` | 同上 |
| simulation_engine (services) | `src/survey/services/simulation_engine.py` | 移除 `is_available()`，`call_llm()` |
| sentiment | `src/survey/engine/sentiment.py` | 移除 `llm_skill` 参数，`call_llm_sync()` |
| persona_factory | `src/survey/services/persona_factory.py` | 移除 `llm_skill` 参数（死代码） |
| survey_analysis_agent | `src/agents/fixed_agents/survey_analysis_agent.py` | 同上 |
| survey_integration_agent | `src/agents/fixed_agents/survey_integration_agent.py` | 移除 `llm_skill` 参数 + 6 处透传 |
| task_api | `src/survey/api/task_api.py` | 移除 `reg.get("llm_skill")` |
| simulated_response_agent | `src/agents/fixed_agents/simulated_response_agent.py` | 移除 `llm_skill` 参数 + 透传 |
| ai_simulation | `src/survey/backends/ai_simulation.py` | 移除 `self._llm_skill` |
| persona_skill | `src/skills/builtin/persona_skill.py` | `llm_skill` 参数标记 deprecated/ignored |
| simulation_skill | `src/skills/builtin/simulation_skill.py` | 同上 |
| report_upgrade/orchestrator | `src/agents/fixed_agents/report_upgrade/orchestrator.py` | 移除 `llm_skill=None` 参数 |

### 2.2 配置/映射层已清理 ✅

| 模块 | 清理内容 |
|------|---------|
| strategies.py | `ASPECT_SKILL_MAP` 移除所有 `"llm_skill"`；`DEFAULT_ASPECT_SKILLS` → `[]`；`SKILL_PRIORITY_MAP` 移除 `"llm_skill": "llm"`；6 处 `skills=["llm_skill"]` → `skills=[]` |
| generic_agent.py | `ACTION_TO_SKILL` 中 LLM 映射改为 `None`；内在 LLM 路径走 `call_llm()` |
| semantic_intent.py | 移除所有 `"llm_skill"` 字符串和追加逻辑 |
| skill_keywords.py | 移除 `LLM_FALLBACK_SKILL` 和 fallback 注入 |
| registry.py | `CATEGORY_TO_SKILLS` 移除 `"llm_skill"`；移除 `llm_skill` 特殊分支；**保留 `llm_skill` 自动注册（委托模式）** |
| factory.py | `_SKILL_ALIAS_MAP` 中 `"llm_skill"` → `"data_analysis"`；fallback 改为 warning |
| intelligent_routing_adapter.py | 移除 `self._llm_skill`；7 个 `recommended_skills` 移除 `"llm_skill"` |
| task_structure.py | 默认技能从 `["llm_skill"]` → `[]`；初始集合从 `{"llm_skill"}` → `set()` |
| prompt_manager.py | 默认返回从 `["llm_skill", "search_skill"]` → `["search_skill"]` |
| discovery.py | 移除 `llm = "llm_skill"` 注入 |
| orchestrator.py | 移除 `llm_skill` 传递和 `RuntimeError` |

### 2.3 Bug 修复 ✅

| Bug | 文件 | 修复 |
|-----|------|------|
| 导入不存在的 `src.core.llm` | `intelligent_routing_adapter.py` | → `from src.core.llm_client import call_llm` |
| `asyncio.run()` 在 async 上下文 | `document_generation_agent.py` | 改 async + `await call_llm()` |
| `asyncio.run()` 条件性风险 | `sentiment.py` | → `call_llm_sync()` |
| `.is_available()` 不存在 | `simulation_engine.py` | 移除检查 |

### 2.4 llm_skill.py 委托模式 ✅

`llm_skill.py` 已重写为委托模式：
- 移除直接 `AsyncOpenAI` 调用和 `_call_llm()` 私有方法
- `execute()` 全部委托到 `call_llm()`
- 标记 `DEPRECATED`
- `skills/__init__.py` 保留 `LLMSkill` 导出
- `registry.py` 保留 `llm_skill` 自动注册

## 3. 功能差异对比

| 特性 | `LLMSkill.execute()` (旧) | `call_llm()` | `LLMSkill.execute()` (委托) |
|------|--------------------------|-------------|---------------------------|
| OpenAI 兼容 API | ✅ 直接调用 | ✅ | ✅ 委托到 call_llm |
| 主/备模型 fallback | ✅ 自行实现 | ✅ | ✅ 继承 call_llm |
| Profile 路由 | ❌ | ✅ | ✅ 继承 call_llm |
| Streaming | ❌ | ✅ | ❌ (execute 不支持) |
| Vision/Multimodal | ❌ | ✅ | ❌ (execute 不支持) |
| 同步包装 | ❌ | ✅ | ❌ (execute 是 async) |
| Cost limit 检查 | ✅ 简单估算 | ✅ | ✅ 继承 call_llm |

## 4. 测试验证

- **84 个迁移专项测试全部通过**（`tests/unit/test_llm_skill_migration.py`）
- 所有 src/ Python 文件语法检查通过
- 所有修改模块 import 验证通过

## 5. 后续步骤（项目全面验证后）

1. 删除 `llm_skill.py`
2. 移除 `skills/__init__.py` 中的 `LLMSkill` 导出
3. 移除 `registry.py` 中的 `llm_skill` 自动注册
4. 清理 3 个向后兼容参数签名（persona_skill, simulation_skill, ai_simulation）
