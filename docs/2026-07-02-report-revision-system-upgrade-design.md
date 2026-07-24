# 报告修订系统升级设计方案 — 对接 ReportOrchestrator 主Agent

> 日期：2026-07-02
> 状态：设计方案 v2（增加阶段门控 + 简化架构：直连 ReportOrchestrator）
> 范围：报告修订全流程升级——从用户提出修订需求到报告重新生成的完整链路改造
> 核心原则：**修订即重写，主Agent主导，阶段门控，数据可溯源**

---

## 0. 背景与动机

### 0.1 系统架构重大升级

系统已完成以下关键升级：

| 升级项 | 说明 | 影响 |
|--------|------|------|
| **ReportOrchestrator** | 框架驱动·逐章生成·独立审查·全局审查的报告生成主Agent | 报告生成从"机械组装"升级为"研究员撰写" |
| **ChapterWriter/ChapterReviewAgent** | 逐章撰写+审查闭环 | 每章内容有框架约束、数据锚定、逻辑连贯 |
| **GlobalReviewAgent** | 全局审查（数据一致性/去重/逻辑连贯/叙事完整/风格统一） | 跨章节数据矛盾和内容重复被主动检测 |
| **DataRegistry** | 全局数据注册表，跟踪所有已使用数据点 | 数据冲突可检测、可裁决、可追溯 |
| **DataRepairAgent/ConflictResolver** | 缺失数据定向补充 + 数据冲突裁决 | 报告中的数据问题可主动修复 |
| **StructuredDataRepairAgent** | 结构化数据修补（表格/图表数据） | 支持表格类数据的精准修补 |
| **QualityCheckAgent** | 分章节质检 + 稳定issue ID | 质检问题可追踪、可关联修订 |

### 0.2 修订系统的现状问题

当前修订系统仍然停留在早期版本，存在以下核心问题：

#### 问题一：修订系统与 ReportOrchestrator 完全断裂

```
当前修订流程:
  用户提出修订 → _handle_v2_revision() → RevisionExecutor → ContentManipulator
  → ReportTree.sync_to_report() → SessionReportAdapter → session dict

ReportOrchestrator 完全不参与修订：
  - 修订后不经过 ChapterWriter 重写 → 修订内容缺乏框架约束
  - 修订后不经过 ChapterReviewAgent 审查 → 修订可能引入新的数据矛盾/逻辑断裂
  - 修订后不经过 GlobalReviewAgent 全局审查 → 跨章节数据一致性无人保障
  - 修订后不经过 DataRegistry 注册 → 新数据点无法被追踪
```

**后果**：修订后的报告质量反而下降——修订解决了局部问题，但可能引入全局问题（数据矛盾、内容重复、逻辑断裂），且这些新问题无法被现有系统检测。

#### 问题二：修订系统只操作文本层，不理解数据层

```
当前修订:
  ContentManipulator.replace_content(section_id, new_content, report_tree)
  → 仅替换 section.content 字符串（需传入 ReportTree 参数）
  → DataRegistry 不更新 → DataRepairAgent 不参与 → ConflictResolver 不触发

ReportOrchestrator 生成:
  ChapterWriter.write() → data_points_used → DataRegistry.register()
  → 逐章注册数据点 → 检测冲突 → 触发裁决 → 修补缺失数据
```

**后果**：修订引入的新数据不在 DataRegistry 中，后续的冲突检测和质量审查无法覆盖修订后的内容。

#### 问题三：修订后文档重新生成走 DocumentGenerationAgent 的 V1 路径

```
当前修订后重新生成:
  _confirm_v2_revision(accept=True)
  → _generate_documents_from_cache()
  → _document_agent.execute({action: 'produce_document'})
  → ContentOrchestrator.transform_to_html()
  → 纯排版层转换，不经过任何内容审查

理想流程:
  _confirm_v2_revision(accept=True)
  → ReportOrchestrator 重新生成受影响的章节
  → ChapterWriter + ChapterReviewAgent 闭环
  → GlobalReviewAgent 全局审查
  → DataRegistry 一致性验证
  → DocumentGenerationAgent 输出
```

**后果**：修订后的内容直接进入排版输出，没有经过任何质量审查，修订质量完全取决于 RevisionExecutor 的 LLM 单次生成质量。

#### 问题四：质检反馈修订与 ReportOrchestrator 的质量体系脱节

```
现有质检修订:
  QualityCheckAgent 检出 issue → 用户点击 issue → ChatInput 预填
  → _llm_converse() → _handle_v2_revision() → RevisionExecutor
  → 纯文本层修订 → _post_revision_recheck()

ReportOrchestrator 的质量体系:
  ChapterWriter 自审 → ChapterReviewAgent 独立审查 → GlobalReviewAgent 全局审查
  → DataRepairAgent 补数据 → ConflictResolver 裁决 → 质量收敛循环
```

**后果**：质检系统发现的问题，修订后只能通过简单的 `_post_revision_recheck` 重检，无法利用 ReportOrchestrator 的多轮审查闭环来确保修订质量。

#### 问题五：两个并行的修订路径造成维护负担

```
V1 路径 (DocumentGenerationAgent._handle_adjust_content，通过 action=ADJUST_CONTENT 分发):
  SectionLocator → LLM修订 → ContentApplier → 文件系统

V2 路径 (_handle_v2_revision → RevisionExecutor):
  SectionLocatorV2 → RevisionPlan → AtomicOperations → ContentManipulator → ReportTree

两条路径:
  - 共享 SectionLocator/ContentApplier 的逻辑不同
  - 对 session 数据结构的理解不同
  - 快照/回滚机制不同
```

#### 问题六（关键）：修订缺乏阶段门控，可能在错误阶段执行

当前 `revise_report` 动作只受 LLM 返回的 action 判断控制，**没有状态门控**。系统状态机有8个状态：

```
UNDERSTANDING → CLARIFYING → FRAMEWORK_CONFIRM → EXECUTING → PAUSED → CANCELLED → PREVIEWING → COMPLETED
```

但 `revise_report` 在任何状态下都可能被 LLM 误判触发：

| 当前阶段 | 用户说 | LLM可能误判为 | 后果 |
|----------|--------|---------------|------|
| UNDERSTANDING | "帮我改一下市场规模的分析" | `revise_report` | 没有报告，session 中无 sections，修订无目标 |
| EXECUTING（数据采集中） | "竞争格局应该加个对比表" | `revise_report` | 报告未成型，改的是半成品数据 |
| EXECUTING（报告撰写中） | "第三章的数据不对" | `revise_report` | ChapterWriter 正在工作，数据层并发冲突 |
| PREVIEWING | "修改第三章的结论" | `revise_report` | 合法，但当前无前置检查 |

**现有防护的不足**：
- LLM prompt 中有 `post_research_hint`，但只在"研究完成后"才注入，且 LLM 可能不遵守
- `_handle_v2_revision` 内部检查 `research_result.report.sections` 是否存在，但只返回空响应，不纠正状态
- 没有硬性的状态门控——`revise_report` 可以在任何 `ConversationState` 下被调用

---

## 1. 设计目标

| 目标 | 说明 | 验收标准 |
|------|------|----------|
| **主Agent主导修订** | 所有修订操作通过 ReportOrchestrator 执行 | 修订后的章节经过 ChapterWriter + ChapterReviewAgent 闭环 |
| **阶段门控** | 修订只能在合法阶段执行，错误阶段自动降级 | 非 PREVIEWING/COMPLETED 状态下 revise_report 被拦截或降级 |
| **数据层一致性** | 修订引入的新数据注册到 DataRegistry | DataRegistry 覆盖修订后所有数据点，冲突可检测 |
| **全局质量保障** | 修订触发 GlobalReviewAgent 全局审查 | 跨章节数据一致性、逻辑连贯性被验证 |
| **流程统一** | 消除 V1/V2 双路径，统一到主Agent路径 | 只有一条修订执行路径 |
| **可追溯** | 修订操作与数据变更可溯源 | 每次修订记录变更的数据点、受影响的章节、审查结果 |
| **向后兼容** | 现有 API 接口不变 | `/api/v1/research/interact` 行为兼容 |

---

## 2. 核心设计：修订即重写

### 2.1 设计理念

```
旧模式：修订 = 文本替换（排版工改错字）
  ContentManipulator.replace_content(section_id, new_text, report_tree)

新模式：修订 = 定向重写（研究员修改论文）
  ReportOrchestrator.revision(user_request)
  → 内部定位 + ChapterWriter.rewrite() + ChapterReviewAgent.review() 闭环
  → DataRegistry 更新 + ConflictResolver 冲突检测
  → GlobalReviewAgent 全局审查
```

**架构简化原则**：用户需求直连 ReportOrchestrator，不需要外部中间层做意图翻译。
ReportOrchestrator 已拥有完整上下文（框架、数据、章节、前文脉络），只需补上"从用户描述定位到章节"的一次 LLM 调用。

### 2.2 新流程总览

```
用户提出修订需求
        │
        ▼
┌─────────────────────────────────────┐
│ Gate: 阶段门控                       │
│ - 检查 ConversationState             │
│ - 非 PREVIEWING/COMPLETED → 降级处理 │
│   UNDERSTANDING/CLARIFYING → chat    │
│   FRAMEWORK_CONFIRM → framework_mode │
│   EXECUTING → inject_requirement     │
│   PAUSED → continue_chat(提示恢复)   │
│   CANCELLED → continue_chat(提示取消)│
│ - 合法阶段 → 进入修订流程            │
└──────────────┬──────────────────────┘
               │ (合法)
               ▼
┌─────────────────────────────────────┐
│ ReportOrchestrator.revision()        │
│                                      │
│ Step 1: 定位（内部一次LLM调用）       │
│   利用已有上下文：                    │
│   - TaskStructure → 章节角色         │
│   - DataRegistry → 数据点索引        │
│   - chapters → 章节内容              │
│   - quality_issues → 质检问题        │
│   → 定位到具体章节/数据点            │
│                                      │
│ Step 2: 定向重写                     │
│   ChapterWriter.rewrite() 逐章重写   │
│   ChapterReviewAgent.review() 审查      │
│   审查不通过 → 重写（最多2轮）       │
│   DataRegistry.register() 注册新数据 │
│   DataRepairAgent 补充缺失数据       │
│   ConflictResolver 裁决数据冲突      │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Step 3: 全局审查与验证              │
│ - GlobalReviewAgent.review()         │
│ - 两步审查：摘要审查 → 原文验证      │
│ - 全局审查不通过 → 定向修正 + 重审   │
│ - DataRegistry 一致性验证            │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Step 4: 报告重新生成与质检联动      │
│ - 重新生成 HTML 预览                 │
│ - QualityCheckAgent 重检             │
│ - SSE 推送质量更新                   │
│ - 版本栈管理                         │
└─────────────────────────────────────┘
```

### 2.3 阶段门控：修订的前置条件检查（关键设计）

这是本方案最关键的安全设计。修订操作必须在正确的阶段执行，否则会导致数据混乱。

#### 2.3.1 修订合法性矩阵

| ConversationState | 修订合法性 | 处理策略 | 原因 |
|-------------------|-----------|----------|------|
| `UNDERSTANDING` | **非法** | → `continue_chat` | 用户意图尚未明确，不存在报告 |
| `CLARIFYING` | **非法** | → `continue_chat` | 需求细节未确定，不存在报告 |
| `FRAMEWORK_CONFIRM` | **非法** | → `enter_framework_mode` | 框架确认中，修改需求应注入框架 |
| `EXECUTING` | **非法** | → `inject_requirement` | 数据采集中，修订会与执行流程冲突 |
| `PAUSED` | **非法** | → `continue_chat`（提示恢复研究） | 应先恢复研究完成报告 |
| `CANCELLED` | **非法** | → `continue_chat`（提示研究已取消） | 研究已取消，无报告可修订 |
| `PREVIEWING` | **合法** | → 进入修订流程 | 报告已生成，可以修订 |
| `COMPLETED` | **合法** | → 进入修订流程 | 报告已完成，可以修订 |

#### 2.3.2 门控实现

```python
# src/api/research_api.py 中 _handle_v2_revision 方法的门控逻辑

# 在 action == 'revise_report' 的处理中，增加状态门控
if action == 'revise_report':
    conv_machine = self._get_or_create_conv_machine(session)
    current_state = conv_machine.current_state
    user_input = conv_result.get('user_input', conv_result.get('message', ''))

    # 阶段门控：只在 PREVIEWING 和 COMPLETED 状态下允许修订
    if current_state not in (ConversationState.PREVIEWING, ConversationState.COMPLETED):
        # 根据当前状态自动降级到合适的动作
        if current_state in (ConversationState.UNDERSTANDING, ConversationState.CLARIFYING):
            logger.info(f"[{session_id}] revise_report blocked in {current_state.value}, redirecting to continue_chat")
            return self._chat_response(session_id, conv_result.get('message', '请先完成研究后再提出修订需求。'))
        elif current_state == ConversationState.EXECUTING:
            # EXECUTING 降级为 inject_requirement：从 conv_result 提取 inject_ops
            logger.info(f"[{session_id}] revise_report blocked in EXECUTING, redirecting to inject_requirement")
            inject_ops = conv_result.get('inject_ops', [])
            if not inject_ops:
                # 如果没有结构化 inject_ops，构造一个 add_section 操作
                inject_ops = [{'op': 'add_section', 'description': user_input}]
            return await self._handle_inject_requirement(session_id, inject_ops, user_input)
        elif current_state == ConversationState.FRAMEWORK_CONFIRM:
            logger.info(f"[{session_id}] revise_report blocked in FRAMEWORK_CONFIRM, redirecting to framework confirmation mode")
            return await self._enter_framework_mode(session_id, user_input)
        elif current_state == ConversationState.PAUSED:
            logger.info(f"[{session_id}] revise_report blocked in PAUSED, suggesting resume")
            return self._chat_response(session_id, '研究尚未完成，请先恢复研究以完成报告生成。')
        elif current_state == ConversationState.CANCELLED:
            logger.info(f"[{session_id}] revise_report blocked in CANCELLED, research was cancelled")
            return self._chat_response(session_id, '研究已取消，无法修订报告。请发起新的研究。')
        else:
            logger.info(f"[{session_id}] revise_report blocked in {current_state.value}, falling back to continue_chat")
            return self._chat_response(session_id, conv_result.get('message', ''))

    # 通过门控，执行修订
    logger.info(f"[{session_id}] revise_report allowed in {current_state.value}")
    return await self._handle_v2_revision(session_id, conv_result)
```

#### 2.3.3 前置条件检查（双重保障）

即使通过了状态门控，进入 `_handle_v2_revision` 后仍需验证：

```python
async def _handle_v2_revision(self, session_id, conv_result):
    """v2 修订入口（改造版）"""

    session = session_manager.get(session_id)
    if not session:
        return {'error': 'Session not found', 'error_code': 'SESSION_NOT_FOUND'}

    # ===== 前置条件检查（双重保障） =====
    # 条件1: 研究结果必须存在
    research_result = session.get('research_result', {})
    if not research_result or research_result.get('status') not in ('completed', 'completed_with_warnings'):
        return self._chat_response(session_id, '报告尚未生成完成，请等待研究完成后再提出修订需求。')

    # 条件2: 报告章节必须存在且非空
    sections = research_result.get('report', {}).get('sections', [])
    if not sections:
        return self._chat_response(session_id, '报告内容为空，无法执行修订。请尝试重新生成报告。')

    # 条件3: HTML预览必须存在
    from src.core.preview_storage import PreviewStorage
    if not PreviewStorage.path(session_id).exists():
        return self._chat_response(session_id, '报告预览不存在，请先重新生成报告。')

    # 条件4: 没有正在执行的修订任务
    # 注意：现有代码使用 self._revision_task（单任务引用）来跟踪修订任务，
    # 同时 self._executor_tasks 也注册了任务。两者都需检查。
    existing_task = self._executor_tasks.get(f"rev_{session_id}")
    revision_task = getattr(self, '_revision_task', None)
    if (existing_task and not existing_task.done()) or (revision_task and not revision_task.done()):
        return self._chat_response(session_id, '已有修订任务正在执行中，请等待完成后再发起新的修订。')

    # ... 继续修订流程
```

#### 2.3.4 LLM Prompt 层面的预防

除了代码层门控，还在 LLM prompt 中强化阶段约束，减少误判：

```python
# 在 _build_dialogue_context 中，为各阶段添加修订约束提示

state_guidance = {
    ConversationState.EXECUTING: """## Current Dialogue Phase: Research Executing
Research is actively running with professional agents working.
CRITICAL RULES for action selection:
- Default action: "continue_chat"
- "inject_requirement" — ONLY when user clearly asks to add/remove/supplement sections.
- NEVER use "revise_report" — the report has NOT been generated yet. 
  Even if the user says "修改/修订/改一下", use "inject_requirement" instead.
- "enter_framework" — ONLY when user explicitly requests redesign.
""",
    ConversationState.PREVIEWING: """## Current Dialogue Phase: Report Preview
Report has been generated and is being previewed.
- "revise_report" — when user asks to modify specific content in the report.
- "regenerate_report" — when user asks to regenerate the entire report.
- "continue_chat" — for general questions about the report.
""",
    ConversationState.COMPLETED: """## Current Dialogue Phase: Research Completed
Research is complete. The full report is available.
- "revise_report" — when user asks to modify specific content.
- "regenerate_report" — when user asks to regenerate the entire report.
- "enter_framework" — when user wants to start a completely new research.
""",
    ConversationState.CANCELLED: """## Current Dialogue Phase: Research Cancelled
Research has been cancelled. No report is available.
- "continue_chat" — for general conversation.
- "enter_framework" — if user wants to start a new research.
- NEVER use "revise_report" — there is no report to revise.
""",
}
```

#### 2.3.5 EXECUTING 阶段的特殊处理

`EXECUTING` 阶段是最容易出问题的场景——用户看到中间结果后想修改，但此时数据采集和报告生成可能正在并发执行。

处理策略：**将修订意图转化为需求注入**

```
EXECUTING 阶段用户说："第三章的市场规模数据不对"
    │
    ▼ 门控拦截 revise_report
    │
    ▼ 转化为 inject_requirement
    │
    ▼ 注入到研究执行流程中
    │
    ├─ 如果该章节尚未生成 → 修正生成参数（搜素关键词、数据源偏好）
    └─ 如果该章节已生成 → 标记该章节需要重生成
```

这样做的优势：
- 不破坏正在执行的研究流程
- 用户的反馈被正确传递给生成流程
- 避免数据层并发冲突

---

## 3. 详细设计

### 3.1 新增数据结构

```python
# src/agents/fixed_agents/report_upgrade/revision_models.py

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class RevisionComplexity(Enum):
    LIGHTWEIGHT = "lightweight"    # 标题/措辞/格式修改，无需重写
    STANDARD = "standard"         # 单章节内容修改，需 ChapterWriter 重写
    COMPLEX = "complex"           # 多章节关联修改，需协调重写
    FULL = "full"                 # 全局重构，需完整重生成


@dataclass
class RevisionTarget:
    """修订定位结果中的单个目标"""
    chapter_id: str
    chapter_title: str
    revision_type: str                   # modify / rewrite / patch_data / delete
    revision_description: str            # 具体修订描述
    data_patches: List[str] = field(default_factory=list)  # 数据修补指令


@dataclass
class RevisionLocation:
    """修订定位结果（由 _locate_revision_target 返回）"""
    complexity: RevisionComplexity = RevisionComplexity.STANDARD
    targets: List[RevisionTarget] = field(default_factory=list)
    data_gaps: List[Dict[str, Any]] = field(default_factory=list)
    data_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    preceding_summary: str = ""


@dataclass
class ChapterRewriteResult:
    """章节重写结果"""
    chapter_id: str
    original_content: str
    revised_content: str
    review_passed: bool
    review_score: float
    data_points_changed: List[Dict[str, Any]] = field(default_factory=list)
    data_points_added: List[Dict[str, Any]] = field(default_factory=list)
    data_points_removed: List[Dict[str, Any]] = field(default_factory=list)
    rewrite_rounds: int = 1
```

### 3.2 ReportOrchestrator.revision()：修订主入口

核心设计：直接在 ReportOrchestrator 上新增 `revision()` 方法，用户需求直连，无需外部中间层：

> **⚠️ 注意**：当前 `ReportOrchestrator.__init__` 初始化了 `_task_structure={}` 和 `_data_registry=DataRegistry()`，但**没有** `_chapters` 和 `_framework_config` 属性。`generate_report()` 内部构建 chapters 列表但未持久化到 `self`。此外，prompt_manager 存储为 `self._prompts`（非 `self._prompt_manager`）。
>
> **解决方案**：
> 1. 在 `__init__` 中新增 `self._chapters: List[ChapterWriteOutput] = []` 和 `self._framework_config: Dict[str, Any] = {}` 属性
> 2. 在 `_generate_report_impl` 中将局部变量 `chapters` 和参数 `framework_config` 赋值给 `self._chapters` 和 `self._framework_config`
> 3. 当从 session 恢复时，由 `_handle_v2_revision` 通过 `ro._chapters = ...` 注入

```python
# src/agents/fixed_agents/report_upgrade/orchestrator.py 中新增

from src.core.llm_client import call_llm  # 已有导入

class ReportOrchestrator:
    # ... 已有代码 ...

    # __init__ 中新增属性（在现有 self._task_structure 之后添加）:
    #   self._chapters: List[ChapterWriteOutput] = []
    #   self._framework_config: Dict[str, Any] = {}
    # 这些属性在 generate_report() 执行期间被赋值，在 revision() 中被使用。
    # 当从 session 恢复时，由 _handle_v2_revision 通过 ro._chapters = ... 注入。

    # ⚠️ 注意：现有 __init__ 中 prompt_manager 存储为 self._prompts（非 self._prompt_manager）

    # ⚠️ 重要：ReportOrchestrator 已有 _append_preceding_summary(self, existing: str, chapter: ChapterWriteOutput) -> str
    # 方法（orchestrator.py line 1180）。修订场景需要接收 ChapterRewriteResult 参数，
    # 不能直接覆盖同名方法（Python 不支持方法签名重载）。
    # 解决方案：新增方法命名为 _append_revision_preceding_summary，避免与现有方法冲突。

    # ⚠️ 重要：需在 orchestrator.py 的 import 块（line 10-15）中添加 FixSuggestion 的导入，
    # 因为 _fix_global_issues 方法的类型注解使用了 List["FixSuggestion"]。
    # 当前 orchestrator.py 未导入 FixSuggestion（虽在 models.py 中定义），
    # 字符串形式的类型注解在运行时不会报错，但类型检查器会标记。

    async def revision(
        self,
        user_request: str,
        quality_issues: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        修订入口：用户需求直接传入

        ReportOrchestrator 已拥有完整上下文：
        - self._chapters → 所有章节内容
        - self._data_registry → 全局数据注册表
        - self._task_structure → 任务结构（章节角色/依赖）
        - self._framework_config → 研究框架
        - self._chapter_writer / _chapter_reviewer / _global_reviewer → 内部组件
        - self._data_repair_agent / _conflict_resolver → 数据修复组件

        只需补上"定位"能力：一次 LLM 调用，利用已有上下文定位到章节/数据点
        """
        # Step 1: 定位（一次LLM调用）
        location = await self._locate_revision_target(
            user_request, quality_issues
        )

        # Step 2: 根据复杂度选择路径
        if location.complexity == RevisionComplexity.LIGHTWEIGHT:
            return await self._apply_lightweight_revision(location)

        # Step 3: 定向重写 + 审查闭环
        preceding_summary = ""  # 逐章更新
        chapter_results = []
        for target in location.targets:
            result = await self._execute_chapter_revision(
                target, preceding_summary
            )
            chapter_results.append(result)
            if result.review_passed:
                preceding_summary = self._append_revision_preceding_summary(
                    preceding_summary, result
                )

        # Step 4: 全局审查
        global_review = await self._global_reviewer.review(
            ReviewInput(
                framework_config=self._framework_config,
                report_summary=serialize_report_for_review(
                    self._chapters, self._data_registry
                ),
                conflicts_summary=self._data_registry.serialize_conflicts(),
            )
        )
        verified_issues = await self._global_reviewer.verify_issues(
            global_review.issues, self._chapters
        )

        # Step 5: 全局审查不通过时的定向修正
        # 注意：ReviewOutput 没有 passed 字段，用 overall_score < 80 判断
        if global_review.overall_score < 80 and verified_issues:
            await self._fix_global_issues(verified_issues, global_review.fix_suggestions)

        return {
            "chapter_results": chapter_results,
            "global_review_score": global_review.overall_score,
            "global_review_passed": global_review.overall_score >= 80,
            "data_registry_snapshot": self._data_registry.to_snapshot(),
        }

    async def _locate_revision_target(
        self,
        user_request: str,
        quality_issues: Optional[List[Dict]],
    ) -> "RevisionLocation":
        """
        定位修订目标——ReportOrchestrator 内部的一次 LLM 调用

        利用已有上下文，不需要外部组件：
        - chapters → 章节索引
        - data_registry → 数据点索引
        - quality_issues → 质检问题
        - task_structure → 章节角色/依赖
        """
        chapter_index = "\n".join(
            f"- [{c.chapter_id}] {c.title}"
            for c in self._chapters
        )
        data_index = self._data_registry.serialize_used_metrics()
        issues_context = ""
        if quality_issues:
            issues_context = "\n".join(
                f"- [{iss.get('severity', '')}] {iss.get('section', '')}: {iss.get('message', '')}"
                for iss in quality_issues[:20]
            )

        prompt = f"""# 修订定位

## 研究主题
{self._task_structure.get('topic', '')}

## 章节索引
{chapter_index}

## 已使用的数据指标
{data_index}

## 质检问题
{issues_context or '无'}

## 用户修订请求
{user_request}

## 输出格式（严格JSON，包裹在 ```json ``` 中）
```json
{{
  "complexity": "lightweight|standard|complex",
  "targets": [
    {{
      "chapter_id": "章节ID",
      "chapter_title": "章节标题",
      "revision_type": "modify|rewrite|patch_data|delete",
      "revision_description": "具体修订描述",
      "data_patches": ["数据修补指令"]
    }}
  ],
  "preceding_summary": "前文核心结论摘要（用于后续章节的上下文衔接）",
  "data_gaps": [{{"chapter_id": "", "metric": "缺失指标", "context": "上下文"}}],
  "data_conflicts": [{{"metric": "冲突指标", "entries": []}}]
}}
```"""

        result = await call_llm(prompt=prompt, max_tokens=4096, temperature=0.3)
        # 注意：现有 ReportOrchestrator 内部使用 _call_llm_tracked() 来追踪 token 用量。
        # 此处直接使用 call_llm() 是因为 revision() 是新增方法，后续可改为 _call_llm_tracked()
        # 以统一 token 追踪。当前优先保证功能正确性。
        if not result.get("success"):
            return RevisionLocation(complexity=RevisionComplexity.STANDARD)
        return self._parse_location_result(result["content"], user_request)

    def _parse_location_result(self, raw: str, fallback_request: str) -> RevisionLocation:
        """解析 LLM 返回的修订定位结果"""
        import re, json
        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                targets = [
                    RevisionTarget(
                        chapter_id=t.get("chapter_id", ""),
                        chapter_title=t.get("chapter_title", ""),
                        revision_type=t.get("revision_type", "modify"),
                        revision_description=t.get("revision_description", fallback_request),
                        data_patches=t.get("data_patches", []),
                    )
                    for t in data.get("targets", [])
                ]
                return RevisionLocation(
                    complexity=RevisionComplexity(data.get("complexity", "standard")),
                    targets=targets,
                    data_gaps=data.get("data_gaps", []),
                    data_conflicts=data.get("data_conflicts", []),
                    preceding_summary=data.get("preceding_summary", ""),
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse revision location: {e}")
        return RevisionLocation(
            complexity=RevisionComplexity.STANDARD,
            targets=[RevisionTarget(
                chapter_id="", chapter_title="",
                revision_type="modify",
                revision_description=fallback_request,
            )],
        )

    async def _execute_chapter_revision(
        self,
        target: "RevisionTarget",
        preceding_summary: str,
    ) -> "ChapterRewriteResult":
        """执行单章节修订——复用内部 ChapterWriter + ChapterReviewAgent"""

        target_chapter = next(
            (c for c in self._chapters if c.chapter_id == target.chapter_id), None
        )
        if not target_chapter:
            return ChapterRewriteResult(
                chapter_id=target.chapter_id,
                original_content="", revised_content="",
                review_passed=False, review_score=0.0,
            )

        original_content = target_chapter.content

        # 构建审查反馈（将用户需求+质检issue作为审查输入）
        # 注意：ChapterIssue 需要5个必填字段：category, severity, location, description, suggestion
        review_feedback = ChapterReviewOutput(
            passed=False, score=0.0,
            issues=[
                ChapterIssue(
                    category="user_revision", severity="HIGH",
                    location=f"chapter:{target.chapter_id}",
                    description=target.revision_description,
                    suggestion=target.revision_description,
                )
            ],
        )

        # 调用 ChapterWriter.rewrite()——复用已有重写能力
        # 注意：rewrite() 签名包含 chapter_data: Dict = None 参数
        rewritten = await self._chapter_writer.rewrite(
            original_chapter=target_chapter,
            review_feedback=review_feedback,
            framework_config=self._framework_config,
            chapter_spec={"section_id": target.chapter_id, "section_name": target.chapter_title},
            preceding_summary=preceding_summary,
            chapter_data={"data_points": [dp.__dict__ for dp in target_chapter.data_points_used]}
            if target_chapter.data_points_used else None,
        )

        # 审查闭环——复用已有审查能力（ChapterReviewAgent）
        best_chapter = rewritten
        best_score = 0.0

        # 构建审查输入的公共数据
        review_chapter_data = {"data_points": [dp.__dict__ for dp in target_chapter.data_points_used]} \
            if target_chapter.data_points_used else {}

        for review_round in range(2):
            review = await self._chapter_reviewer.review(
                ChapterReviewInput(
                    framework_config=self._framework_config,
                    chapter_spec={"section_id": target.chapter_id, "section_name": target.chapter_title},
                    chapter_content=best_chapter.content,
                    preceding_summary=preceding_summary,
                    used_metrics_summary=self._data_registry.serialize_used_metrics(),
                    topic=self._task_structure.get('topic', ''),
                    writer_self_check_issues=best_chapter.self_check_issues,
                    chapter_data=review_chapter_data,
                )
            )
            if review.passed:
                best_score = review.score
                break
            if review.score > best_score:
                best_score = review.score
            rewritten = await self._chapter_writer.rewrite(
                original_chapter=best_chapter,
                review_feedback=review,
                framework_config=self._framework_config,
                chapter_spec={"section_id": target.chapter_id, "section_name": target.chapter_title},
                preceding_summary=preceding_summary,
                chapter_data={"data_points": [dp.__dict__ for dp in target_chapter.data_points_used]}
                if target_chapter.data_points_used else None,
            )
            if rewritten.content:
                best_chapter = rewritten

        # 更新 DataRegistry
        # 注意：_extract_and_validate_data_points 是 @staticmethod，通过 self 调用语法合法
        validated_dps = self._extract_and_validate_data_points(best_chapter)
        # 将验证后的数据点列表赋值回章节对象，保持一致性
        best_chapter.data_points_used = validated_dps
        for dp in validated_dps:
            self._data_registry.register(
                metric=dp.metric, value=dp.value, unit=dp.unit,
                chapter_id=best_chapter.chapter_id, source=dp.source,
            )

        # 更新内部 chapters
        idx = next(
            (i for i, c in enumerate(self._chapters) if c.chapter_id == target.chapter_id), None
        )
        if idx is not None:
            self._chapters[idx] = best_chapter

        return ChapterRewriteResult(
            chapter_id=target.chapter_id,
            original_content=original_content,
            revised_content=best_chapter.content,
            review_passed=best_score >= 60,
            review_score=best_score,
            rewrite_rounds=review_round + 1,
        )

    def _append_revision_preceding_summary(self, current: str, result: ChapterRewriteResult) -> str:
        """修订场景的前文摘要更新

        注意：ReportOrchestrator 已有 _append_preceding_summary(self, existing: str, chapter: ChapterWriteOutput) -> str
        方法（orchestrator.py line 1180）。此方法不能与之同名，否则会覆盖现有方法导致
        _generate_report_impl 中的调用（line 390）失败。
        因此命名为 _append_revision_preceding_summary 以避免冲突。
        """
        conclusions = ""
        if result.revised_content:
            # 从修订内容中截取摘要（最多500字符），受 _MAX_PRECEDING_SUMMARY_LENGTH 约束
            conclusions = result.revised_content[:500]
        if current and conclusions:
            # 保留前文摘要的最后部分 + 新结论
            max_len = self._MAX_PRECEDING_SUMMARY_LENGTH if hasattr(self, '_MAX_PRECEDING_SUMMARY_LENGTH') else 3000
            return current[-(max_len - 500):] + "\n" + conclusions
        return conclusions or current

    async def _fix_global_issues(self, issues: List["ReviewIssue"], fix_suggestions: List["FixSuggestion"]):
        """全局审查不通过时的定向修正

        注意：ReviewIssue 有5个字段：dimension, severity, description, location, evidence
        不能直接将 ReviewIssue 作为 ChapterIssue 传入 ChapterReviewOutput，
        需要转换为 ChapterIssue 格式。
        """
        for issue in issues[:5]:  # 限制修正数量，避免无限循环
            chapter_id = issue.location.split(":")[-1] if ":" in issue.location else ""
            target_chapter = next(
                (c for c in self._chapters if c.chapter_id == chapter_id), None
            )
            if not target_chapter:
                continue
            # 将 ReviewIssue 转换为 ChapterIssue 格式
            review_feedback = ChapterReviewOutput(
                passed=False, score=0.0,
                issues=[
                    ChapterIssue(
                        category=issue.dimension, severity=issue.severity,
                        location=issue.location, description=issue.description,
                        suggestion=issue.evidence,
                    )
                ],
            )
            rewritten = await self._chapter_writer.rewrite(
                original_chapter=target_chapter,
                review_feedback=review_feedback,
                framework_config=self._framework_config,
                chapter_spec={"section_id": target_chapter.chapter_id, "section_name": target_chapter.title},
                preceding_summary="",
            )
            if rewritten.content:
                idx = next(
                    (i for i, c in enumerate(self._chapters) if c.chapter_id == chapter_id), None
                )
                if idx is not None:
                    self._chapters[idx] = rewritten
```

### 3.3 修改 `_handle_v2_revision`：直连 ReportOrchestrator.revision()

```python
# src/api/research_api.py 中 _handle_v2_revision 方法的改造

async def _handle_v2_revision(self, session_id, conv_result):
    """v2 修订入口（改造版）：直连 ReportOrchestrator.revision()"""

    session = session_manager.get(session_id)
    if not session:
        return {'error': 'Session not found', 'error_code': 'SESSION_NOT_FOUND'}

    # ===== 前置条件检查（双重保障，见 2.3.3） =====
    research_result = session.get('research_result', {})
    if not research_result or research_result.get('status') not in ('completed', 'completed_with_warnings'):
        return self._chat_response(session_id, '报告尚未生成完成，请等待研究完成后再提出修订需求。')

    sections = research_result.get('report', {}).get('sections', [])
    if not sections:
        return self._chat_response(session_id, '报告内容为空，无法执行修订。')

    adjustment = conv_result.get('adjustment') or conv_result.get('user_input', '')

    # ===== 修订前准备（快照 + issue 标记） =====
    quality_lock = self._get_quality_lock(session_id)
    async with quality_lock:
        quality_state_data = session.get("quality_state", {})
        if quality_state_data:
            import copy
            quality_state_data = copy.deepcopy(quality_state_data)
            if quality_state_data.get("phase") in ("reviewing", "revising"):
                quality_state_data["phase"] = "revising"
            session["quality_state"] = quality_state_data

            # 创建版本快照
            version_id = f"v{int(time.time())}"
            snapshot_copy = copy.deepcopy(
                {k: v for k, v in quality_state_data.items() if k != "version_stack"}
            )
            quality_state_data.setdefault("version_stack", []).append({
                "id": version_id,
                "created_at": datetime.now().isoformat(),
                "html_path": f"data/snapshots/{session_id}/{version_id}.html",
                "md_path": f"data/snapshots/{session_id}/{version_id}.md",
                "quality_state_snapshot": snapshot_copy,
                "overall_score": quality_state_data.get("overall_score", 0),
                "label": f"修订前快照 v{len(quality_state_data.get('version_stack', []))}",
            })
            session["quality_state"] = quality_state_data

        # 标记 issue 为 revising
        modified_sections = conv_result.get("aspects", [])
        for sec_name, sec_data in quality_state_data.get("section_scores", {}).items():
            for issue in sec_data.get("issues", []):
                if issue.get("state") == "open" and (
                    not modified_sections or issue.get("section") in modified_sections
                ):
                    if issue.get("revision_count", 0) >= 3:
                        issue["state"] = "max_retries_reached"
                    else:
                        issue["state"] = "revising"
                        issue["revision_count"] = issue.get("revision_count", 0) + 1
                        issue["revising_since"] = time.time()
        session["quality_state"] = quality_state_data

    # ===== 构建 ReportOrchestrator 实例 =====
    try:
        from src.agents.fixed_agents.report_upgrade.orchestrator import ReportOrchestrator
        from src.agents.fixed_agents.report_upgrade.chapter_writer import ChapterWriter
        from src.agents.fixed_agents.report_upgrade.chapter_reviewer import ChapterReviewAgent
        from src.agents.fixed_agents.report_upgrade.global_reviewer import GlobalReviewAgent
        from src.agents.fixed_agents.report_upgrade.data_repair import DataRepairAgent, ConflictResolver
        from src.agents.fixed_agents.report_upgrade.data_registry import DataRegistry
        from src.agents.fixed_agents.report_upgrade.prompt_manager import PromptManager
    except ImportError as e:
        logger.warning(f"ReportOrchestrator import failed: {e}, falling back to V2 executor")
        return await self._run_v2_revision_fallback(session_id, conv_result, session, adjustment, quality_state_data)

    # 注意：llm_skill 参数在所有组件中已被弃用（保留仅为向后兼容），
    # 所有 LLM 调用均通过 call_llm() 直接执行。但仍需从 skill_registry 获取
    # search_skill 和 web_scraper_skill 以支持 DataRepairAgent 和 ConflictResolver。
    skill_registry = self._orchestrator._skill_registry
    search_skill = skill_registry.get("search_skill") if skill_registry else None
    web_scraper_skill = skill_registry.get("web_scraper") if skill_registry else None

    pm = PromptManager()
    ro = ReportOrchestrator(
        chapter_writer=ChapterWriter(prompt_manager=pm),
        chapter_reviewer=ChapterReviewAgent(prompt_manager=pm),
        global_reviewer=GlobalReviewAgent(prompt_manager=pm),
        data_repair_agent=DataRepairAgent(
            search_skill=search_skill, web_scraper_skill=web_scraper_skill,
            prompt_manager=pm,
        ),
        conflict_resolver=ConflictResolver(
            search_skill=search_skill,
            web_scraper_skill=web_scraper_skill, prompt_manager=pm,
        ),
        prompt_manager=pm,
        skill_registry=skill_registry,
    )

    # 从 session 恢复上下文
    chapters = self._sections_to_chapters(sections)
    data_registry = self._restore_data_registry(session)
    framework_config = self._get_framework_config(session)
    task_structure = self._get_task_structure(session)
    topic = research_result.get("topic", "")

    # 初始化 ReportOrchestrator 内部状态
    ro._chapters = chapters
    ro._data_registry = data_registry
    ro._framework_config = framework_config
    ro._task_structure = task_structure

    # 收集质检 issues
    quality_issues = []
    for sec_name, sec_data in quality_state_data.get("section_scores", {}).items():
        for issue in sec_data.get("issues", []):
            if issue.get("state") in ("revising", "open"):
                quality_issues.append(issue)

    # ===== 直连 ReportOrchestrator.revision() =====
    try:
        result = await ro.revision(
            user_request=adjustment,
            quality_issues=quality_issues if quality_issues else None,
        )
    except Exception as e:
        logger.error(f"ReportOrchestrator.revision() failed: {e}", exc_info=True)
        self._rollback_revising_issues(session)
        return self._chat_response(session_id, f"修订执行失败: {e}")

    # ===== 将修订结果写回 session =====
    self._apply_revision_to_session(session, result, ro._chapters, ro._data_registry)

    # ===== 报告重新生成 =====
    await self._regenerate_from_revision(session_id, session, ro._chapters)

    # ===== 质检联动 =====
    if quality_state_data:
        await self._post_revision_recheck(session)

    return self._chat_response(session_id)
```

### 3.4 辅助方法（待实现）

以下方法需要在 `src/api/research_api.py` 中新增实现。当前代码中不存在这些方法。

```python
# src/api/research_api.py 中新增的辅助方法

def _sections_to_chapters(self, sections: List[Dict]) -> List[ChapterWriteOutput]:
    """将 session 中的 sections 转换为 ChapterWriteOutput 列表

    ⚠️ 重要：当前 _assemble_final_report 生成的 section dict 不包含 key_conclusions 字段
    （仅包含 id, title, content, subsections, charts, data_points, sources）。
    因此 sec.get("key_conclusions", []) 始终返回 []。

    解决方案有两种：
    A) 在 _assemble_final_report 中添加 "key_conclusions": ch.key_conclusions 到 section dict
    B) 在此处从 content 中提取 key_conclusions（使用 ChapterWriter._extract_conclusions）

    推荐方案 A（在 _assemble_final_report 中修复源头），此处同时实现 B 作为 fallback。
    """
    from src.agents.fixed_agents.report_upgrade.models import ChapterWriteOutput
    from src.agents.fixed_agents.report_upgrade.chapter_writer import ChapterWriter
    chapters = []
    for sec in sections:
        # key_conclusions: 先尝试从 section dict 获取（方案 A 修复后可用），
        # 如果不存在则从 content 中提取（方案 B fallback）
        key_conclusions = sec.get("key_conclusions", [])
        if not key_conclusions and sec.get("content"):
            key_conclusions = ChapterWriter._extract_conclusions(sec.get("content", ""))
        chapters.append(ChapterWriteOutput(
            chapter_id=sec.get("id", ""),
            title=sec.get("title", sec.get("name", "")),
            content=sec.get("content", ""),
            data_points_used=[],  # 从 content 中提取或从 session 缓存恢复
            key_conclusions=key_conclusions,
        ))
    return chapters

def _restore_data_registry(self, session) -> "DataRegistry":
    """从 session 恢复 DataRegistry"""
    from src.agents.fixed_agents.report_upgrade.data_registry import DataRegistry
    snapshot = session.get("_data_registry_snapshot")
    if snapshot:
        return DataRegistry.from_snapshot(snapshot)
    return DataRegistry()

def _get_framework_config(self, session) -> Dict:
    """从 session 获取 framework config

    注意：ResearchFrameworkConfig 包含 name, description, agent_config,
    section_weights, interaction_parameters 等字段。返回完整配置以支持
    ChapterWriter 重写时的框架约束。
    """
    cached = session.get("_framework_config")
    if cached:
        return cached
    try:
        from src.core.research_framework_manager import get_framework_config
        output_type = session.get("output_type") or session.get("research_context", {}).get("framework", {}).get("output_type", "industry_report")
        fc_obj = get_framework_config(output_type)
        return {
            "name": fc_obj.name,
            "description": fc_obj.description,
            "section_weights": fc_obj.section_weights,
            "interaction_parameters": fc_obj.interaction_parameters,
        }
    except Exception:
        return {"name": "通用研究报告", "description": "通用研究"}

def _get_task_structure(self, session) -> Dict:
    """从 session 获取 task_structure"""
    cached = session.get("_task_structure")
    if cached:
        return cached
    # 从 research_context 或 research_result 中提取
    research_context = session.get("research_context", {})
    return {
        "topic": research_context.get("topic", ""),
        "directions": research_context.get("directions", []),
        "framework": research_context.get("framework"),
    }

def _apply_revision_to_session(self, session, result, chapters, data_registry):
    """将修订执行结果写回 session"""
    report = session.setdefault("research_result", {}).setdefault("report", {})

    updated_sections = []
    for ch in chapters:
        updated_sections.append({
            "id": ch.chapter_id,
            "name": ch.title,
            "title": ch.title,
            "content": ch.content,
            "key_conclusions": ch.key_conclusions,
        })
    report["sections"] = updated_sections

    session["_data_registry_snapshot"] = data_registry.to_snapshot()

    revision_record = {
        "timestamp": datetime.now().isoformat(),
        "chapters_revised": len(result.get("chapter_results", [])),
        "global_review_score": result.get("global_review_score", 0),
        "global_review_passed": result.get("global_review_passed", False),
    }
    session.setdefault("_revision_history", []).append(revision_record)

async def _regenerate_from_revision(self, session_id, session, chapters):
    """修订后重新生成 HTML 预览

    复用现有 _generate_documents_from_cache 的逻辑，
    但仅生成 HTML 预览（不需要同时生成 DOCX）。
    """
    research_result_data = self._convert_session_to_cache_format(
        session.get("research_result", {})
    )
    output_dir = Path('data') / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        preview_input = {
            'action': 'produce_document',
            'research_result': research_result_data,
            'output_format': 'html',
            'output_dir': str(output_dir),
            'task_id': session_id,
        }
        preview_result = await self._orchestrator._document_agent.execute(preview_input)
        if isinstance(preview_result, dict) and preview_result.get('document_path'):
            from src.core.preview_storage import PreviewStorage
            PreviewStorage.copy_file(session_id, Path(preview_result['document_path']))
    except Exception as e:
        logger.warning(f"Post-revision preview regeneration failed: {e}")

async def _run_v2_revision_fallback(self, session_id, conv_result, session, adjustment, quality_state_data):
    """V2 executor 降级路径：当 ReportOrchestrator 不可用时使用原有 RevisionExecutor

    封装现有 _handle_v2_revision 中的 RevisionExecutor 调用逻辑，
    作为 ReportOrchestrator 路径的 fallback。
    """
    from src.core.adjustment.report_adapter import SessionReportAdapter
    from src.core.adjustment.revision_executor import RevisionExecutor, ProgressNotifier

    adapter = SessionReportAdapter(session)
    if not hasattr(self, '_v2_lock_manager'):
        from src.core.adjustment.report_lock_manager import ReportLockManager
        self._v2_lock_manager = ReportLockManager()

    notifier = ProgressNotifier()
    executor = RevisionExecutor(lock_manager=self._v2_lock_manager, notifier=notifier)
    revision_task = safe_create_task(
        executor.handle_feedback(adjustment, adapter),
        name=f"rev_{session_id}"
    )
    self._executor_tasks[f"rev_{session_id}"] = revision_task
    # ... 后续处理与现有 _handle_v2_revision 逻辑一致
```

### 3.5 轻量修订快速路径

对于标题修改、措辞调整、格式修正等不需要 ChapterWriter 重写的操作，保留轻量路径：

```python
# 在 ReportOrchestrator 内部
async def _apply_lightweight_revision(self, location: RevisionLocation) -> Dict:
    """轻量修订：直接修改 sections，不经过 ChapterWriter

    注意：轻量修订仅适用于不涉及数据变更的文本修改（标题/措辞/格式）。
    如果修改涉及数据表述，应走 STANDARD 路径而非 LIGHTWEIGHT。
    轻量修订后仍需更新 DataRegistry 以保持一致性。
    """
    for target in location.targets:
        for ch in self._chapters:
            if ch.chapter_id == target.chapter_id:
                # 轻量修改通过一次 LLM 调用完成内容微调
                result = await call_llm(
                    prompt=f"对以下章节内容进行轻量修改：{target.revision_description}\n\n当前内容：\n{ch.content[:3000]}\n\n只修改涉及的部分，保持其他内容不变。",
                    max_tokens=4096, temperature=0.3,
                )
                # 注意：同 _locate_revision_target，此处直接使用 call_llm()，
                # 后续可改为 _call_llm_tracked() 统一追踪。
                if result.get("success") and result.get("content"):
                    ch.content = result["content"]
                    # 更新 DataRegistry：重新提取并注册数据点
                    validated_dps = self._extract_and_validate_data_points(ch)
                    # ⚠️ 重要：必须将 validated_dps 赋值回 ch.data_points_used，
                    # 否则后续 _extract_and_validate_data_points 调用会基于旧的
                    # data_points_used 列表，导致已删除的数据点仍然残留。
                    # 注意：_extract_and_validate_data_points 只追加新数据点，
                    # 不移除内容中已不存在的旧数据点。对于轻量修订场景，
                    # 如果修改涉及数据删除，应考虑走 STANDARD 路径。
                    ch.data_points_used = validated_dps
                    for dp in validated_dps:
                        self._data_registry.register(
                            metric=dp.metric, value=dp.value, unit=dp.unit,
                            chapter_id=ch.chapter_id, source=dp.source,
                        )
                break
    return {
        "chapter_results": [],
        "global_review_score": 0,  # 轻量修订不做全局审查，score=0 表示未评估
        "global_review_passed": True,  # 轻量修订默认通过（无全局审查）
        "data_registry_snapshot": self._data_registry.to_snapshot(),
    }
```

> **注意**：轻量修订也经过 LLM 调用，但只做单次微调，不走 ChapterWriter + ChapterReviewAgent 闭环。
> 轻量修订后仍然会触发 `_post_revision_recheck` 进行质检更新。
> `global_review_score=0` 与 `global_review_passed=True` 并不矛盾——0 表示"未执行全局审查"而非"审查不通过"，
> 轻量修订默认信任 LLM 单次微调结果。

---

## 4. ReportOrchestrator 能力充分利用

### 4.1 能力矩阵

| ReportOrchestrator 能力 | 修订场景 | 利用方式 |
|------------------------|----------|----------|
| **ChapterWriter.write()** | 新增章节 | 生成全新章节内容，有框架约束 |
| **ChapterWriter.rewrite()** | 章节内容修改 | 基于审查反馈重写，保留合理内容 |
| **ChapterWriter.patch_data()** | 数据定向修复 | 精准替换数据点，不改动无关内容 |
| **ChapterReviewAgent.review()** | 修订质量审查 | 独立审查修订后的章节质量 |
| **GlobalReviewAgent.review()** | 全局一致性审查 | 检测跨章节数据矛盾/内容重复 |
| **GlobalReviewAgent.verify_issues()** | 审查结果验证 | 两步审查避免误报 |
| **DataRegistry** | 数据追踪 | 注册修订引入的新数据点 |
| **DataRepairAgent** | 缺失数据补充 | 定向搜索并补充缺失数据 |
| **ConflictResolver** | 数据冲突裁决 | 权威性评分+LLM裁决解决冲突 |
| **StructuredDataRepairAgent** | 表格/图表修补 | 精准修补结构化数据 |

### 4.2 修订类型与能力映射

| 修订类型 | 复杂度 | 使用的 ReportOrchestrator 能力 |
|----------|--------|-------------------------------|
| 标题修改 | LIGHTWEIGHT | 直接修改 session |
| 措辞/格式调整 | LIGHTWEIGHT | 直接修改 session |
| 单章节数据修复 | STANDARD | ChapterWriter.patch_data() + ChapterReviewAgent |
| 单章节内容修改 | STANDARD | ChapterWriter.rewrite() + ChapterReviewAgent |
| 多章节关联修改 | COMPLEX | 多次 ChapterWriter.rewrite() + GlobalReviewAgent |
| 数据矛盾修复 | DATA_FIX | ConflictResolver + ChapterWriter.patch_data() |
| 缺失数据补充 | DATA_FIX | DataRepairAgent + ChapterWriter.patch_data() |
| 新增章节 | COMPLEX | ChapterWriter.write() + ChapterReviewAgent + GlobalReviewAgent |
| 删除章节 | STANDARD | 直接删除 + GlobalReviewAgent |
| 全局重构 | FULL | 完整 ReportOrchestrator.generate_report() |

---

## 5. 与现有质检系统的集成

### 5.1 质检 → 修订的增强

```
现有流程:
  QualityCheckAgent 检出 issue → 用户点击 → ChatInput 预填文本
  → _llm_converse → _handle_v2_revision → RevisionExecutor（纯文本替换）

增强后:
  QualityCheckAgent 检出 issue → 用户点击 → ChatInput 预填文本
  → _llm_converse → _handle_v2_revision → ReportOrchestrator.revision()
  → 内部定位 + 将质检 issue 作为修订输入
  → ChapterWriter + ChapterReviewAgent 闭环
  → GlobalReviewAgent 验证
  → _post_revision_recheck 更新质检评分
```

### 5.2 质检 issue 到 RevisionTarget 的映射

| 质检 issue type | RevisionType | 说明 |
|----------------|--------------|------|
| completeness | rewrite | 章节内容不完整，需重写补充 |
| accuracy | patch_data | 数据不准确，需定向修补 |
| consistency | patch_data | 数据不一致，需统一 |
| format | lightweight | 格式问题，直接修改 |
| logic | rewrite | 逻辑问题，需重写修正 |
| redundancy | rewrite | 内容重复，需重写去重 |

### 5.3 DataRegistry 与质检的联动

```
修订前:
  DataRegistry.to_snapshot() → 保存当前数据点快照

修订中:
  ChapterWriter 重写 → 注册新数据点 → 检测冲突

修订后:
  DataRegistry.to_snapshot() → 对比修订前后数据变更
  → 新增的数据点自动纳入后续质检范围
  → 冲突数据点触发 ConflictResolver
```

---

## 6. 向后兼容与迁移策略

### 6.1 渐进式迁移

```
阶段1（本次实现）:
  - 在 ReportOrchestrator 上新增 revision() 方法
  - 修改 _handle_v2_revision 增加阶段门控 + 直连 ReportOrchestrator.revision()
  - 保留 V2 executor 作为 fallback
  - 定位失败时自动降级到 V2 executor

阶段2（后续优化）:
  - 在 session 中缓存 ReportOrchestrator 实例（避免每次修订重建）
  - 优化 _regenerate_from_revision 支持增量 HTML 更新
  - 增加修订预览（修订前/修订后对比）

阶段3（最终统一）:
  - 移除 V1 修订路径（DocumentGenerationAgent._handle_adjust_content，通过 action=ADJUST_CONTENT 分发）
  - 移除 V2 executor fallback
  - 统一到 ReportOrchestrator.revision() 路径
```

### 6.2 Fallback 机制

```python
# 在 _handle_v2_revision 中
try:
    from src.agents.fixed_agents.report_upgrade.orchestrator import ReportOrchestrator
    ...
except (ImportError, AttributeError) as e:
    logger.warning(f"ReportOrchestrator unavailable: {e}, falling back to V2 executor")
    return await self._run_v2_revision_fallback(session_id, conv_result, session, adjustment, quality_state_data)
```

### 6.3 API 接口不变

| 端点 | 行为变化 | 兼容性 |
|------|----------|--------|
| `POST /api/v1/research/interact` | 修订意图走 ReportOrchestrator.revision() | 请求/响应格式不变 |
| `POST /api/v1/research/quality` | 质检联动增强 | 请求/响应格式不变 |
| SSE `quality_result` | 评分更准确 | 事件格式不变 |
| SSE `preview_refresh` | 修订后预览刷新 | 事件格式不变 |

---

## 7. 已知问题修复

本方案同时解决了 `docs/deep-audit-report-revision-quality.md` 中记录的以下问题：

| 问题 | 修复方式 |
|------|----------|
| R-1: 修订失败 issue 状态不回退 | ReportOrchestrator.revision() 失败时自动调用 `_rollback_revising_issues()` |
| R-2: 版本栈 quality_state_snapshot 递归嵌套 | 已在现有代码中修复（`snapshot_copy` 排除 `version_stack`） |
| E-1: 修订异常无 issue 回退 | 同 R-1 |
| Q-2/H-3: merge_issues_on_recheck 丢失 revision_count | 修订后重检时保留 revision_count |
| A-1: 删除章节后 section_scores 残留 | 删除章节后清理 section_scores |
| H-1: rollback 不恢复 sections 数据 | DataRegistry 快照支持完整恢复 |
| R-3: reject 路径无 SSE 推送 | _confirm_v2_revision reject 路径已有推送 |
| FE-3: 发起修订未标记 issue | ReportOrchestrator.revision() 接收 quality_issues 参数 |

---

## 8. 文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/agents/fixed_agents/report_upgrade/revision_models.py` | 修订数据结构定义 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/agents/fixed_agents/report_upgrade/orchestrator.py` | 新增 `revision()` 方法 + `_locate_revision_target()` + `_execute_chapter_revision()` + `_append_revision_preceding_summary()` + `_fix_global_issues()` + `_apply_lightweight_revision()`；`__init__` 新增 `_chapters` 和 `_framework_config` 属性；`_generate_report_impl` 中将 chapters/framework_config 赋值给 self；`_assemble_final_report` 中添加 `key_conclusions` 到 section dict；import 块添加 `FixSuggestion` |
| `src/api/research_api.py` | 改造 `_handle_v2_revision`，增加阶段门控 + 前置条件检查 + 直连 ReportOrchestrator.revision()；新增 `_sections_to_chapters` / `_restore_data_registry` / `_get_framework_config` / `_get_task_structure` / `_apply_revision_to_session` / `_regenerate_from_revision` / `_run_v2_revision_fallback` 辅助方法 |

### 不修改的文件

| 文件 | 原因 |
|------|------|
| `src/core/adjustment/revision_executor.py` | 保留作为 fallback（通过 `_run_v2_revision_fallback` 调用） |
| `src/core/adjustment/content_manipulator.py` | 保留用于轻量修订 |
| `src/core/adjustment/section_locator_v2.py` | 保留用于修订意图分析中的章节定位 |
| `src/agents/fixed_agents/document_generation_agent.py` | 继续用于文档输出（V1 修订路径 `_handle_adjust_content` 暂保留） |
| `src/agents/fixed_agents/report_upgrade/data_repair.py` | 不修改（DataRepairAgent 和 ConflictResolver 同在此文件中） |

---

## 9. 测试策略

### 9.1 单元测试

| 测试目标 | 覆盖场景 |
|----------|----------|
| 阶段门控 | 各 ConversationState（含 CANCELLED）下 revise_report 的合法性判断与降级路由 |
| 前置条件检查 | 无 sections / 无 research_result / 无 preview / 有运行中修订任务 |
| ReportOrchestrator.revision() | 单章节重写 / 多章节重写 / 数据修补 / 删除 / 轻量修改 |
| _locate_revision_target() | 用户描述→章节定位 / 质检issue→章节定位 / 模糊描述降级 |
| ChapterWriter.rewrite 集成 | 修订指令正确传入 rewrite（含 chapter_data 参数） |
| DataRegistry 更新 | 修订后数据点注册/冲突检测 |
| Fallback 机制 | ReportOrchestrator 不可用时降级到 V2 executor（_run_v2_revision_fallback） |

### 9.2 集成测试

| 测试场景 | 验证点 |
|----------|--------|
| 单章节内容修改 | ChapterWriter.rewrite → ChapterReviewAgent → DataRegistry 更新 → HTML 重新生成 |
| 多章节关联修改 | 多次 rewrite → GlobalReviewAgent → 冲突检测 |
| 数据定向修复 | patch_data → DataRegistry 更新 → 冲突裁决 |
| 质检 issue 修订 | issue → RevisionTarget → rewrite → recheck → 评分更新 |
| 修订失败回退 | 异常时 issue 状态回退 + SSE 推送 |

### 9.3 端到端测试

| 测试场景 | 验证点 |
|----------|--------|
| 完整修订流程 | 用户输入 → 意图分析 → 定向重写 → 全局审查 → 预览刷新 → 质检更新 |
| 修订后数据一致性 | 修订引入的新数据在 DataRegistry 中可查 |
| 版本回滚 | 回滚恢复 sections + DataRegistry + quality_state |

---

## 10. 风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| 阶段门控误判 | 高 | 三层防护：Prompt预防 + 状态门控 + 前置条件检查 |
| LLM 调用次数增加 | 中 | 轻量修订走快速路径；标准修订限制审查轮次（最多2轮） |
| 修订耗时增加 | 中 | 逐章重写可并行；DataRepairAgent 有并发限制（5个） |
| Fallback 路径维护负担 | 低 | 阶段3统一后移除；当前保持最小改动 |
| session 数据结构兼容性 | 低 | 新增字段不影响现有逻辑；DataRegistry 快照独立存储 |
| ReportOrchestrator 实例重建开销 | 中 | 后续优化：在 session 中缓存实例 |
| search_skill 为 None 导致 DataRepairAgent 降级 | 中 | 检查 skill_registry 返回值；DataRepairAgent 在 search_skill=None 时 repair_gap() 会失败，需在调用前检查 |

---

## 11. 总结

本方案的核心思想是**将报告修订从"文本替换"升级为"定向重写"**，并解决修订的阶段安全性问题：

**架构简化**：用户需求直连 `ReportOrchestrator.revision()`，不增加外部中间层。ReportOrchestrator 已有完整上下文，只需补上定位能力（一次 LLM 调用）。

**阶段门控**：修订只能在 `PREVIEWING` 和 `COMPLETED` 状态下执行。其他状态下 `revise_report` 动作被拦截并降级到合适的替代动作（`continue_chat` / `inject_requirement` / `enter_framework_mode`），避免在数据采集或报告生成阶段执行修订导致数据混乱。

**三层防护**：LLM Prompt 预防（减少误判）→ 代码层状态门控（硬拦截）→ 前置条件检查（数据完整性验证），确保修订不会在错误阶段执行。

**能力复用**：修订后章节经过 ChapterWriter 重写 + ChapterReviewAgent 审查 + GlobalReviewAgent 全局验证 + DataRegistry 数据追踪 + DataRepairAgent/ConflictResolver 数据修复，与首次生成享受同等质量保障。
