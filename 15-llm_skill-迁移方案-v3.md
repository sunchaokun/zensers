# llm_skill → call_llm 迁移状态报告（v4 — 委托模式）

> 本文档记录 `llm_skill` → `call_llm()` 迁移的最终状态。所有功能迁移、字符串清理和 Bug 修复均已完成。`llm_skill.py` 保留为**向后兼容委托**（DEPRECATED），所有 `execute()` 调用内部转发到 `call_llm()`。

## 1. 迁移总结

**状态：已完成 ✅**

- `src/skills/llm_skill.py` 保留为委托模式（DEPRECATED），`execute()` 全部委托到 `call_llm()`
- 项目中 0 处直接使用 `AsyncOpenAI` 的 `llm_skill` 代码（已委托到 `call_llm`）
- 项目中 0 处 `llm_skill.execute()` 调用保留功能性使用（已全部改为 `call_llm()` 或 `call_llm_sync()`）
- 项目中 0 处 `reg.get("llm_skill")` 后再 `.execute()` 的调用
- 84 个迁移专项测试全部通过
- 所有 src/ Python 文件语法检查通过
- 所有修改模块 import 验证通过

### 委托模式说明

`llm_skill.py` 不再直接调用 OpenAI API，而是将所有 `execute()` 调用委托到 `call_llm()`：

```
旧路径: reg.get("llm_skill").execute(prompt=...) → AsyncOpenAI → API
新路径: reg.get("llm_skill").execute(prompt=...) → call_llm() → _call_llm_api() → API
推荐:   直接 call_llm(prompt=...)                → _call_llm_api() → API
```

保留 `llm_skill.py` 的理由：
1. 项目未完成最终全面验证，删除模块过于激进
2. 任何残留的 `reg.get("llm_skill").execute(...)` 调用仍然能正常工作
3. `registry.py` 的 `register_core_skills()` 仍自动注册 `llm_skill`
4. `skills/__init__.py` 仍导出 `LLMSkill`

## 2. 已完成的迁移

### 2.1 Bug 修复（4 个）

| Bug | 文件 | 修复内容 |
|-----|------|---------|
| Bug 1: 导入不存在的 `src.core.llm` | `intelligent_routing_adapter.py:521` | 改为 `from src.core.llm_client import call_llm` |
| Bug 2: `asyncio.run()` 在 async 上下文必崩 | `document_generation_agent.py:1714` | `_handle_adjust_content()` 改为 async，`action_handlers` 调度支持 async handler，替换为 `await call_llm()` |
| Bug 3: `asyncio.run()` 条件性风险 | `sentiment.py:284` | 移除 `llm_skill` 参数，替换为 `call_llm_sync()` |
| Bug 4: `.is_available()` 不存在 | `simulation_engine.py:176-177` | 移除 `is_available()` 检查 |

### 2.2 分析 Skill 迁移（6 个）

| 模块 | 迁移内容 |
|------|---------|
| data_analysis | `reg.get("llm_skill")` → `call_llm()`；保留 `get_skill_registry` 给 `lc_python_repl` |
| market_analysis | 同上 |
| policy_analysis | `reg.get("llm_skill")` → `call_llm()` |
| risk_analysis | 同上 |
| stock_analysis | 移除 `_get_llm()` 辅助，5 处 `llm.execute()` → `call_llm()`；保留 `get_skill_registry` |
| tech_trend | `reg.get("llm_skill")` → `call_llm()` |

### 2.3 Survey/Simulation 子系统迁移（19 个模块）

**底层引擎（8 个）**：

| 模块 | 迁移内容 |
|------|---------|
| persona_generation_agent | 移除 `llm_skill` 参数，`self.llm_skill.execute()` → `call_llm()` |
| survey_optimization_agent | 同上 |
| cross_synthesis_agent | 完全重写：移除 `llm_skill`，`self._llm_skill.execute()` → `call_llm()`，保留 `asyncio.wait_for(timeout=60)` |
| document_generation_agent | 移除 `set_llm_skill` / `self._llm_skill`，`_handle_adjust_content` 改 async + `await call_llm()` |
| focus_group | 移除 `llm_skill` 参数，`call_llm()`，保留 `wait_for(timeout=15)` |
| persona_generator | 同上，保留 `wait_for(timeout=30)` |
| simulation_engine (engine/) | 移除 `llm_skill` 参数，`call_llm()`，保留 `wait_for` 超时 |
| sentiment | 移除 `llm_skill` 参数，`call_llm_sync()` |

**中间层（7 个）**：

| 模块 | 迁移内容 |
|------|---------|
| persona_factory | 移除 `llm_skill` 参数（死代码） |
| survey_analysis_agent | 移除 `llm_skill` 参数（死代码） |
| survey_integration_agent | 移除 `llm_skill` 参数 + 6 处透传 |
| task_api | 移除 `reg.get("llm_skill")` |
| simulated_response_agent | 移除 `llm_skill` 参数 + 透传 |
| persona_skill | `llm_skill` 参数标记为 deprecated/ignored，不再透传 |
| simulation_skill | 同上 |

**Agent 层**：

| 模块 | 迁移内容 |
|------|---------|
| ai_simulation | 移除 `self._llm_skill`，`PersonaGeneratorV2()` / `SimulationExecutor()` 不再传 `llm_skill` |

### 2.4 向后兼容参数清理（5 个）

| 模块 | 清理内容 |
|------|---------|
| chapter_writer | 移除 `llm_skill=None` 参数 |
| chapter_reviewer | 同上 |
| global_reviewer | 同上 |
| report_upgrade/orchestrator | 移除 `llm_skill=None` 参数 |
| data_repair (DataRepairAgent + ConflictResolver) | 移除 `llm_skill=None` 参数 |

### 2.5 核心编排器注入清理（3 处）

| 位置 | 清理内容 |
|------|---------|
| orchestrator.py 注入点 A | 移除 `llm_skill` 传递给 ReportOrchestrator 及所有子代理 |
| orchestrator.py 注入点 B | 同上 |
| orchestrator.py 注入点 C | 移除 `llm_skill` 查找和传递给 SurveyIntegrationAgent |

### 2.6 直接实例化清理

| 模块 | 清理内容 |
|------|---------|
| semantic_intent.py | 移除 `self._llm_skill`（:207）和 `_get_llm_skill()` 方法（:210-220） |

### 2.7 配置/映射层清理（12 个文件，~130 处引用）

| 模块 | 清理内容 |
|------|---------|
| strategies.py | `ASPECT_SKILL_MAP` 移除所有 `"llm_skill"` 条目；`DEFAULT_ASPECT_SKILLS` 改为 `[]`；`SKILL_PRIORITY_MAP` 移除 `"llm_skill": "llm"` 条目；移除 `llm_skills` 变量和 `"llm"` tier 分支；6 处 `skills=["llm_skill"]` → `skills=[]` |
| orchestrator.py | 2 处缩进修复 + 移除 `else: raise RuntimeError("No LLM skill available")`；`recommended_skills` 和 `required_skills` 移除 `"llm_skill"` |
| generic_agent.py | `ACTION_TO_SKILL` 中 10 个 LLM 相关映射从 `"llm_skill"` 改为 `None`；重构执行逻辑：`if skill_name is None` → 内在 LLM 路径（`call_llm()`） |
| semantic_intent.py | `_infer_skills_from_intent()` 移除所有 `"llm_skill"` 字符串，移除 "分析/评估" 关键词的 llm_skill 追加逻辑 |
| skill_keywords.py | 移除 `LLM_FALLBACK_SKILL` 常量、LLM fallback 注入逻辑、`match_skills()` 不再自动追加 llm_skill；更新 docstring |
| registry.py | `CATEGORY_TO_SKILLS` 11 个分类移除 `"llm_skill"`；`load_skills_for_category()` 和 `discover_skills()` 移除 `llm_skill` 特殊分支 |
| factory.py | `_SKILL_ALIAS_MAP` 中 6 个 `"llm_skill"` 映射改为 `"data_analysis"`；fallback 注入从 `"llm_skill"` 改为 warning 日志 |
| intelligent_routing_adapter.py | 移除 `self._llm_skill`；7 个 `recommended_skills` 模板移除 `"llm_skill"` |
| task_structure.py | `skill_requirements` 默认值从 `["llm_skill"]` 改为 `[]`；`skills = {"llm_skill"}` 改为 `skills = set()` |
| prompt_manager.py | 默认返回从 `["llm_skill", "search_skill"]` 改为 `["search_skill"]` |
| discovery.py | 移除 `llm = "llm_skill"` 及其注入循环 |
| business/__init__.py | 更新 docstring 注释 |

### 2.8 缩进/语法修复（3 个文件）

| 模块 | 问题 | 修复 |
|------|------|------|
| persona_factory.py | 空 `__init__` 缺少 `pass` | 添加 `pass` |
| simulation_engine.py (services/) | 同上 | 添加 `pass` |
| focus_group.py | 同上 | 添加 `pass` |

### 2.9 llm_skill.py 重写为委托模式

| 文件 | 改动 |
|------|------|
| `src/skills/llm_skill.py` | 移除直接 `AsyncOpenAI` 调用和 `_call_llm()` 私有方法；`execute()` 改为调用 `call_llm()`；标记 `DEPRECATED` |
| `src/skills/__init__.py` | 恢复 `LLMSkill` 导入和导出 |
| `src/skills/registry.py` | 恢复 `register_core_skills()` 中的 `llm_skill` 自动注册（委托模式） |

## 3. 残留引用（安全，向后兼容）

项目内仍有以下 `llm_skill` 引用，均为向后兼容委托模式所需或已弃用参数签名：

| 位置 | 类型 | 说明 |
|------|------|------|
| `llm_skill.py` 本体 | 委托模块 | DEPRECATED，`execute()` 委托到 `call_llm()` |
| `skills/__init__.py` | 导入/导出 | 向后兼容，允许 `from src.skills import LLMSkill` |
| `registry.py` | 自动注册 | `register_core_skills()` 注册委托版 `LLMSkill` |
| `persona_skill.py:32` | 参数签名 | `llm_skill: Optional[Any] = None`（deprecated，ignored） |
| `persona_skill.py:37` | docstring | "Deprecated, ignored" |
| `simulation_skill.py:32` | 参数签名 | 同 persona_skill |
| `simulation_skill.py:37` | docstring | 同 persona_skill |
| `ai_simulation.py:29` | 参数签名 | `llm_skill=None`（deprecated，ignored） |
| `generic_agent.py:4450` | 注释 | 迁移历史说明 |

## 4. 测试验证

### 4.1 迁移专项测试

- 文件：`tests/unit/test_llm_skill_migration.py`
- 测试数：84（13 个测试类）
- 结果：**84/84 passed**

### 4.2 测试覆盖

| 测试类 | 测试数 | 覆盖范围 |
|--------|--------|---------|
| TestBug1WrongImportPath | 4 | 导入路径修复 |
| TestBug2AsyncioRunInAsyncContext | 6 | asyncio.run 消除 + async handler |
| TestBug3SentimentAsyncioRun | 3 | call_llm_sync 替换 |
| TestBug4IsAvailableNotExists | 3 | is_available 移除 |
| TestAnalysisSkillsMigration | 28 | 6 个分析 Skill 迁移 |
| TestSurveyDeadCodeCleanup | 9 | Survey 子系统清理 |
| TestSurveyEngineMigration | 6 | Simulation 引擎迁移 |
| TestDirectLLMSkillInstantiationCleanup | 5 | 注册表委托验证（改为验证委托模式） |
| TestReturnFormatCompatibility | 4 | 返回格式兼容性 |
| TestCallLlmSyncAvailability | 3 | call_llm_sync 可用性 |
| TestTimeoutPreservation | 4 | 超时保护保留 |
| TestOrchestratorInjectionCleanup | 1 | 编排器注入清理 |
| TestBackwardCompatParamCleanup | 5 | 向后兼容参数清理 |
| TestLlmSkillFileDeletion | 3 | 委托模式验证（改为验证委托而非删除） |

### 4.3 全项目验证

| 验证项 | 结果 |
|--------|------|
| 所有 src/ Python 文件 py_compile | ✅ 通过（2 个 pre-existing SyntaxWarning 无关迁移） |
| 修改模块 import 测试 | ✅ 17/17 通过（4 个 pre-existing 缺失依赖无关迁移） |
| llm_skill.py 存在且为委托模式 | ✅ 无 `AsyncOpenAI` / `_call_llm` |
| 无功能性 `reg.get("llm_skill").execute()` | ✅ 0 处（所有消费方已改为 `call_llm()`） |
| 无 `from src.skills.llm_skill import`（消费方） | ✅ 0 处（仅 `__init__.py` 和 `registry.py` 为向后兼容导入） |

## 5. 关键设计决策

| 决策 | 理由 |
|------|------|
| Bug 2: `_handle_adjust_content` 改为 async + `asyncio.iscoroutinefunction(handler)` | 支持同步和异步 handler 共存 |
| Bug 3: 使用 `call_llm_sync()` 而非改 async | `analyze_batch()` 是 sync 方法，`_llm_enhance` 从 sync 上下文调用 |
| `ACTION_TO_SKILL` 中 LLM 映射改为 `None` | `None` 表示内在 LLM 能力，不经过 registry |
| `persona_skill.py`/`simulation_skill.py` 保留 `llm_skill` 参数 | 向后兼容，但标记 deprecated 且不使用 |
| 保留 `asyncio.wait_for()` 超时包裹 | `call_llm()` 无内置超时 |
| `ASPECT_SKILL_MAP` 中 `"llm_skill"` 完全移除 | LLM 能力是内在的，不需要在 skill 列表中声明 |
| `factory.py` fallback 从注入 `"llm_skill"` 改为仅 warning | 无有效 skill 时不应注入不存在的 skill |
| **保留 `llm_skill.py` 为委托模式** | 项目未完成最终全面验证，删除模块过于激进；委托模式确保向后兼容同时统一 LLM 调用路径 |

## 6. 已知限制

1. **`call_llm()` 无内置超时**：迁移后保留原有 `asyncio.wait_for()` 包裹，但新代码需自行添加
2. **返回格式 `error` 字段语义不同**：`call_llm()` 返回错误码（如 `"empty_prompt"`），`LLMSkill._failure()` 返回用户可读信息——已验证消费方不依赖 `error` 字段内容
3. **4 个 pre-existing 导入错误**：`frontmatter` 和 `tiktoken` 缺失导致 4 个模块无法 import，与迁移无关
4. **2 个 pre-existing 测试收集错误**：`test_edge_cases.py` 和 `test_semantic_matching.py` 引用已删除的函数，与迁移无关

## 7. 后续步骤（项目全面验证后）

当项目完成全面端到端验证后，可考虑：

1. **删除 `llm_skill.py`**：确认无残留调用后删除
2. **移除 `skills/__init__.py` 中的 `LLMSkill` 导出**
3. **移除 `registry.py` 中的 `llm_skill` 自动注册**
4. **清理 3 个向后兼容参数签名**（persona_skill, simulation_skill, ai_simulation）
