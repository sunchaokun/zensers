# 研究 Pause 后 LLM 上下文丢失问题修复方案

> 日期: 2026-07-21
> 状态: 已实施
> 严重性: P1 — 用户可见的研究中断 + LLM 失忆
> 关联文档: `docs/2026-07-21-select-template-bug-fix.md`

---

## 1. 问题描述

用户在研究执行期间遇到以下问题：

1. 研究被自动暂停后，用户说"继续任务"，**LLM 回复"请问您想研究什么主题"**，完全忘记了正在执行的研究任务
2. 前端**创建了新会话**而非 resume 原会话，导致研究上下文彻底丢失
3. 后端即使收到原会话的消息，LLM 也**缺乏足够的 paused 上下文**来判断应执行 `resume_research`

---

## 2. 事件时间线（ses_b6c6312f）

| 时间 | 事件 | 影响 |
|------|------|------|
| 12:22 | 会话创建 | — |
| 12:35 | 框架确认，12 章节，后台工具链完成 | — |
| 12:36 | 研究执行开始，Phase 1 (data_collection) 启动 12 Agent | — |
| **12:41:28** | **SSE 断连** → 后端调度 30s 延迟暂停 | 前端失去实时连接 |
| 12:41:28-12:42:12 | 所有 12 Agent 的 `search_skill` 超时 (60s)，但标记 `success=True` | 数据质量极差 |
| 12:42:00 | Playwright 浏览器崩溃 (`TargetClosedError`, `net::ERR_ABORTED`) | 爬虫无法继续 |
| **12:42:00** | **PAUSE 生效** (`cancel_manager.pause`) | 研究引擎卡在 `_execute_batch: paused, waiting...` |
| 12:42:12 | 质量检查: score=32/70, **未通过**；12 Agent 全部 Harness 约束失败 | 触发 retry 2/3 |
| 12:42:12 | retry 2/3 被 paused 阻塞 | `_execute_batch: paused before dispatching, waiting...` |
| 12:42-13:31 | 任务卡死在 paused 状态，仅 history_compressor 每 ~4 分钟运行 | 用户看到研究停滞 |
| **13:31:30** | **前端创建新会话 `ses_e15cc297`** | 用户说"继续任务"但走了新会话路径 |
| 13:31:32 | 新会话 LLM 调用 → 无上下文 → 回复"请问您想研究什么" | **LLM 失忆** |
| ~13:42 | 引擎内部自动恢复（非前端触发），Phase 1 retry 3/3 继续执行 | 后端研究继续，但前端已脱离 |
| 13:47:47 | Phase 1 质量检查放弃 (score=32/70)，直接进入 Phase 2 | — |
| 13:59:52 | Phase 2 完成，质量检查通过 (12/12 agents, 1072 data_points) | 研究完成，但用户不知道 |

---

## 3. 根因分析

### 3.1 根因 A（前端）：SSE 断连后 sessionId 丢失，创建新会话

**完整路径**:

```
SSE 断连
  → 后端 _on_sse_disconnect → 30s 后 cancel_manager.pause()
  → 前端 EventSource 关闭
  → 前端 useProgress/useSessionStream 失去连接
  → useResearchStore.status 变为 'paused'
  → 但前端 currentStep 状态可能错乱（Select Template bug 同源）
  → 用户输入"继续任务"
  → ChatPanel.handleSend() → useResearch.sendMessage()
  → sendMessage 检查: if (!sessionId) → startResearch(text)  ← 创建新会话！
```

**关键代码**: `useResearch.ts:440-443`

```typescript
const sendMessage = useCallback(async (text: string) => {
  if (!sessionId) {
    return startResearch(text);  // ← sessionId 丢失时走这里
  }
  // ...
}, [sessionId, /* ... */]);
```

**sessionId 丢失的原因**（已验证，按可能性排序）:

1. **`stateFromCache` 的 `__pending__` 重置**：`useResearchStore.ts:103` 中 `sessionId: c.id === '__pending__' ? null : c.id`。SSE 断连后 `useResearchStore` 订阅触发 `stateFromCache`，若此时 `activeId` 指向 `__pending__`（例如 `reset()` 被调用或 `syncActive` 在无 `activeId` 时创建了 `__pending__`），`sessionId` 被重置为 `null`。

2. **`useSessionStore` 的 `partialize` 丢弃 `activeId`**：`useSessionStore.ts:252-256` 的持久化配置中，只有 `running` 或 `paused` 状态的会话才持久化 `activeId`：
   ```typescript
   activeId: (!state.activeId || state.activeId === '__pending__')
     ? null
     : (state.sessions[state.activeId]?.status === 'running' || state.sessions[state.activeId]?.status === 'paused')
       ? state.activeId
       : null,
   ```
   如果研究暂停后前端状态被意外重置为非 `running`/`paused`（如 `'idle'`），页面刷新后 `activeId` 恢复为 `null`，导致 `sessionId` 丢失。

3. **`reset()` 被意外调用**：`useResearchStore.ts:220-232` 的 `reset()` 清空 `sessionId` 并创建新的 `__pending__` 会话。可能在 Header 的 `handleNewResearch` 或其他组件中被触发。

### 3.2 根因 B（后端）：`_llm_converse` 的 paused 上下文信息不足 + PAUSED/RUNNING 状态冲突

**文件**: `research_api.py:1162-1170` + `research_api.py:1044-1118`

当前 paused 时给 LLM 的上下文：

```python
paused_context = f"""
## Paused Research Context
The previous research on '{context.get('topic', '')}' was interrupted.
Collected data is cached ({section_count} sections available).
The user may want to:
- Resume → resume_research
- Modify framework → modify_research
- Regenerate from cache → regenerate_report
- New question → continue_chat
"""
```

**缺失的关键信息**:

| 缺失信息 | 影响 | 来源 |
|---------|------|------|
| 当前 Phase（Phase 1 数据采集 vs Phase 2 深度分析） | LLM 不知道研究进行到哪一步 | `_build_research_running_context` 可提供 |
| 已完成/进行中的 Agent 列表 | LLM 不知道哪些章节已处理 | `ResearchResultStore.completed_agents` |
| 已采集数据点数量 | LLM 不知道数据收集进度 | `ResearchResultStore.data_points` |
| 进度百分比 | LLM 不知道整体进度 | `session.task_progress.progress` |
| 暂停原因 | LLM 不知道是自动暂停还是用户暂停 | 需新增字段 |
| 暂停时长 | LLM 不知道暂停了多久 | 需新增字段 |

**PAUSED/RUNNING 状态冲突（关键发现）**：`_llm_converse` 在构建 prompt 时（`research_api.py:1209-1211`），同时使用了 `paused_context` 和 `_build_research_running_context` 的输出 `rrc`：

```python
rrc = self._build_research_running_context(session, session_id)
user_prompt = self._build_initial_prompt(..., paused_context, ..., rrc)
```

`_build_initial_prompt`（`research_api.py:1345-1348`）将两者拼接在同一个 prompt 中：

```
{paused_context}
{sections_context}
{post_research_hint}
{research_running_ctx}
```

当 `mode === 'research'` 且 CancelManager 标记为 paused 时：
- `paused_context`（第 1162-1166 行）说 "The previous research on X was **interrupted**"
- `rrc`（`_build_research_running_context` 第 1108 行）说 "Research Status: **RUNNING**"

LLM 收到两个**矛盾的状态信号**——一个说研究已中断，另一个说研究正在运行。这是 LLM 失忆的最直接原因之一：LLM 被 RUNNING 信号误导，认为研究仍在正常执行，对"继续"这类模糊输入倾向于选择 `continue_chat`（继续聊天）而非 `resume_research`（恢复研究）。

### 3.3 根因 C（后端）：`_build_research_running_context` 在 mode 被改为非 research 时返回空（防御性）

**文件**: `research_api.py:1044-1048`

```python
def _build_research_running_context(self, session, session_id=None):
    mode = session.get('mode', 'chat')
    if mode != 'research':    # ← mode 不是 'research' 时返回空
        return ''
```

**代码验证结论**：经逐一检查 `pause_research`（`research_api.py:2679-2705`）、`_on_sse_disconnect`（`research_api.py:2988-3031`）和 `_handle_research_msg` 的 paused 分支（`research_api.py:556-587`），**暂停流程中没有任何代码修改 `session['mode']`**，`mode` 始终保持 `'research'`。因此，在正常暂停流程中 `_build_research_running_context` **不会**返回空。

**但仍需防御的场景**：`_handle_research_msg` 中 LLM 返回 `enter_framework` 时（`research_api.py:567-571`），会执行 `session['mode'] = 'chat'`。此后如果研究仍被 CancelManager 标记为 paused，`_build_research_running_context` 会返回空字符串，导致 LLM 完全丢失研究上下文——`rrc` 为空意味着 LLM 看不到 Phase 进度、数据点等详情（`paused_context` 仍会生成，因为其条件是 `_cm5.is_paused(session_id) and session.get('research_result')`，`research_result` 可能仍存在）。

此外，`_paused_research_context` 字段（`research_api.py:1167`）的第二条 `paused_context` 赋值路径——经 grep 搜索确认**无任何生产代码设置 `_paused_research_context = True`**（仅在 `tests/test_phase1_fixes.py:242` 中赋值），该路径为死代码。

### 3.4 根因 D（后端）：`_on_sse_disconnect` 的延迟暂停不通知前端

**文件**: `research_api.py:2988-3031`

```python
def _on_sse_disconnect(self, task_id):
    # ...
    async def _delayed_pause():
        await asyncio.sleep(30)  # ← 30 秒后才暂停
        # ... 检查状态 ...
        get_cancel_manager().pause(task_id)  # ← 暂停
```

**问题**:
1. SSE 断连后，后端等 30 秒才暂停。这 30 秒内前端可能已经失去连接状态
2. 暂停后没有主动通知前端（SSE 已断连，无法推送 `paused` 事件）
3. 前端只能通过轮询 `getResearchStatus` 发现暂停，但轮询可能未启动或间隔太长
4. **ProgressStreamer TaskState 不一致**：`pause_research`（用户主动暂停，`research_api.py:2704`）调用了 `ProgressStreamer.pause_task(task_id, ...)`，但 `_on_sse_disconnect`（SSE 断连自动暂停）仅调用 `get_cancel_manager().pause(task_id)`，**未调用 `ProgressStreamer.pause_task`**。这导致 SSE 断连暂停后 ProgressStreamer 的 TaskState 仍为 `running`，前端重连时 `ProgressStreamer.subscribe()` 的 replay（`progress_streamer.py:495-505` — `if task.status == "running"` 分支）推送的是 `running` 状态而非 `paused`，与 CancelManager 的实际状态不一致

### 3.5 根因 E（后端+前端）：引擎 pause 后 retry 逻辑仍触发

**时间线证据**:
- `12:42:00` PAUSE 生效
- `12:42:12` retry 2/3 触发（但被 paused 阻塞）
- `13:45:06` retry 3/3 触发（引擎内部自动恢复后继续）
- `13:47:47` Phase 1 质量检查放弃，进入 Phase 2

**问题**: 引擎的 `_execute_batch` 在 pause 时阻塞等待（`_cm.wait_for_resume_or_cancel`），`cancel_manager.py:126` 的超时为 **3600 秒**（1 小时），超时后自动恢复：

```python
# cancel_manager.py:120-130
async with cond:
    while self._paused.get(task_id, False):
        if self._cancelled.get(task_id, False):
            return "cancelled"
        try:
            await asyncio.wait_for(cond.wait(), timeout=3600)  # ← 3600s，非 30s
        except asyncio.TimeoutError:
            self._paused[task_id] = False
            logger.warning(f"[CTRL] PAUSE_TIMEOUT task={task_id}, auto-resuming")
            return "resumed"
```

时间线验证：`12:42` PAUSE 生效 → `12:42 + 3600s ≈ 13:42` 自动恢复，与时间线中 `~13:42` 引擎内部自动恢复完全吻合。这意味着研究引擎在暂停约 1 小时后会自动恢复执行，而前端对此一无所知。

---

## 4. 修复方案

### Fix A（前端 P1）：paused 状态下 sendMessage 走 resume 路径

**文件**: `web/src/hooks/useResearch.ts`

**原理**: 当研究处于 `paused` 状态且用户发送消息时，应先尝试 resume 原研究会话，而非创建新会话。

**前提条件缺失**：`api.resumeResearch` 方法虽存在于 `api.ts:586-588`，但**前端从未调用过**（全局搜索 `api.resumeResearch` 仅在 `api.ts` 定义处出现，`.tsx` 文件中无任何调用）。Fix A 需要新增前端对 `api.resumeResearch` 的调用路径。

**闭包陷阱**：`sendMessage` 的 `useCallback` 闭包捕获了 `sessionId`（`useResearch.ts:520` 的依赖数组包含 `sessionId`）。即使在 Fix A 中通过 `useResearchStore.getState().setSessionId(taskId)` 恢复了 `sessionId`，闭包中的 `sessionId` 仍是旧值（`null`）。必须使用 `useResearchStore.getState().sessionId` 动态获取最新值，否则逻辑仍走 `if (!sessionId)` 分支。

```typescript
const sendMessage = useCallback(async (text: string) => {
  // Fix A: 动态获取最新 sessionId，避免闭包陷阱
  const currentSessionId = useResearchStore.getState().sessionId;
  const { status, taskId } = useResearchStore.getState();

  if (!currentSessionId) {
    // Fix A: 即使 sessionId 丢失，如果有 taskId，尝试 resume 并恢复 sessionId
    if (taskId) {
      try {
        const resumeResult = await api.resumeResearch(taskId);
        if (resumeResult.status === 'resumed') {
          useResearchStore.getState().setStatus('running');
          useResearchStore.getState().setSessionId(taskId);
        }
      } catch (e) {
        console.error('Failed to resume by taskId:', e);
      }
      // resume 后重新获取 sessionId（可能已通过 setSessionId 恢复）
      const recoveredSessionId = useResearchStore.getState().sessionId || taskId;
      if (recoveredSessionId) {
        try {
          setIsNetworkBusy(true);
          const llmConfig = { /* 同原有 sendMessage 中的 llmConfig 构建 */ };
          const data = await api.sendChatMessage(recoveredSessionId, text, llmConfig);
          // ... 处理响应（同原有 sendMessage 逻辑，使用 recoveredSessionId 替代 sessionId）...
          return data;
        } catch (e) {
          setError(e as ApiError);
        } finally {
          setIsNetworkBusy(false);
        }
      }
    }
    return startResearch(text);
  }

  // Fix A: sessionId 存在但研究 paused，先 resume 再发送
  if (status === 'paused' && taskId) {
    try {
      await api.resumeResearch(taskId);
      useResearchStore.getState().setStatus('running');
    } catch (e) {
      console.error('Failed to resume research:', e);
      // resume 失败仍继续发送消息，由后端 _handle_research_msg 处理
    }
  }

  // ... 原有 sessionId 存在时的发送逻辑（使用 currentSessionId 替代闭包 sessionId）
}, [sessionId, /* ... */]);
```

**风险**: 低 — resume 失败时 fallback 到原有逻辑。注意避免递归调用 `sendMessage(text)`，否则会导致用户消息重复发送。

### Fix B（前端 P1）：ChatPanel 在 paused 状态下显示 Resume 按钮

**文件**: `web/src/components/chat/ChatPanel.tsx`

**原理**: 当研究 paused 时，在聊天区域显示明确的 Resume 按钮，引导用户恢复研究而非输入新消息。

**当前 paused 状态的 UI 完全空白**（已验证）：
1. `ResearchStatusBar` 仅在 `status === 'running'` 时显示（`ResearchStatusBar.tsx:12` — `if (status !== 'running') return null`），paused 时返回 `null`
2. `renderStepContent` 仅在 `currentStep !== null` 时渲染（`ChatPanel.tsx:783`），paused 时 `currentStep` 可能为 `null`
3. `ChatInput` 的 `isRunning` prop 为 `status === 'running'`（`ChatPanel.tsx:812`），paused 时为 `false`，`showStop` 为 `false`，用户可以正常输入文字并按发送——但发送走的是 `handleSend → sendMessage`，而 `sendMessage` 没有 paused 分支处理
4. 用户看到的界面就像一个空白聊天框，没有任何暂停状态提示或恢复操作入口

**关键问题**：`renderStepContent` 仅在 `currentStep !== null` 时渲染（`ChatPanel.tsx:783-787`）。但 paused 状态下 `currentStep` 可能为 `null`（如 `stateFromCache` 恢复时），此时 Resume 按钮不会显示。因此必须在 `renderStepContent` **之外**也添加 paused 状态 UI。

**方案 1**：在消息列表区域（`ChatPanel.tsx:783` 附近）独立渲染 paused 横幅：

```typescript
{/* Fix B: paused 横幅 — 不依赖 currentStep，始终显示 */}
{status === 'paused' && taskId && (
  <div className="space-y-3 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl">
    <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
      研究已暂停
    </p>
    <p className="text-xs text-amber-600 dark:text-amber-400">
      研究任务已暂停，已采集的数据已缓存。您可以恢复研究或取消。
    </p>
    <div className="flex gap-2">
      <button
        onClick={handleResume}
        className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90"
      >
        恢复研究
      </button>
      <button
        onClick={handleCancel}
        className="px-4 py-2 bg-secondary text-secondary-foreground rounded-lg text-sm font-medium hover:bg-secondary/90"
      >
        取消
      </button>
    </div>
  </div>
)}
```

**方案 2**：在 `renderStepContent` 内部也保留 paused 判断（作为 `currentStep !== null` 时的补充）：

```typescript
const renderStepContent = () => {
  // Fix B: paused 状态显示 Resume 按钮（currentStep !== null 时）
  if (status === 'paused' && taskId) {
    return (
      <div className="space-y-3 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl">
        {/* ... 同上 ... */}
      </div>
    );
  }
  // ... 原有逻辑
};
```

**推荐**：方案 1 + 方案 2 同时实施，确保无论 `currentStep` 是否为 `null`，paused 横幅都能显示。

新增 `handleResume` 回调：

```typescript
const handleResume = async () => {
  if (!taskId) return;
  try {
    const result = await api.resumeResearch(taskId);
    if (result.status === 'resumed') {
      useResearchStore.getState().setStatus('running');
      // 恢复 sessionId（如果丢失）
      if (!sessionId) {
        useResearchStore.getState().setSessionId(taskId);
      }
    }
  } catch (e) {
    console.error('Failed to resume research:', e);
  }
};
```

### Fix C（后端 P1）：增强 `_llm_converse` 的 paused 上下文 + 消除 PAUSED/RUNNING 状态冲突

**文件**: `src/api/research_api.py:1162-1170` + `src/api/research_api.py:1044-1118`

**原理**: 在 paused 上下文中补充研究进度详情，让 LLM 能准确判断应执行 `resume_research`。同时消除 `_build_research_running_context` 输出的 RUNNING 状态与 `paused_context` 的 PAUSED 状态之间的冲突。

**冗余分析**：`_build_research_running_context`（`research_api.py:1077-1118`）在 `mode === 'research'` 时已返回包含 Phase 进度、数据点数量、进度百分比的上下文。经根因 C 验证，暂停时 `mode` 仍为 `'research'`，因此 `_build_research_running_context` 的输出（`rrc`）已包含这些信息。Fix C 在 `paused_context` 中重复提供相同信息是冗余的。

**Fix C 的真正价值**：`_build_research_running_context` 的输出标记为 `Research Status: RUNNING`，而 paused 状态需要明确标记为 `PAUSED` 并强调 resume 优先级。因此 Fix C 应聚焦于**状态标记和行动指引**，而非重复进度数据。

**PAUSED/RUNNING 冲突修复**：当 CancelManager 标记为 paused 时，`_build_research_running_context` 应将状态标记从 `RUNNING` 改为 `PAUSED`，而非在 prompt 中同时出现两个矛盾的状态信号。这是 LLM 失忆的最直接原因——LLM 被 RUNNING 信号误导，对"继续"倾向于选择 `continue_chat` 而非 `resume_research`。

**修改 1**：`_llm_converse` 中的 `paused_context`（`research_api.py:1162-1170`）

```python
# 现有代码 (research_api.py:1162-1170)
paused_context = ''
if _cm5.is_paused(session_id) and session.get('research_result'):
    report = session['research_result'].get('report', {})
    section_count = len(report.get('sections', []))
    paused_context = f"""
## Paused Research Context
The previous research on '{context.get('topic', '')}' was interrupted.
Collected data is cached ({section_count} sections available).
The user may want to:
- Resume → resume_research
- Modify framework → modify_research
- Regenerate from cache → regenerate_report
- New question → continue_chat
"""
if session.get('_paused_research_context'):
    # 死代码：无任何生产代码设置 _paused_research_context = True
    # （仅在 tests/test_phase1_fixes.py:242 中赋值）
    rr = session.get('research_result', {})
    sc = len(rr.get('report', {}).get('sections', [])) if rr else 0
    paused_context = f"""
## Paused Research Context
Research on '{context.get('topic', '')}' is paused.
Cached: {sc} sections.
- Resume → resume_research
- Modify → modify_research
- Regenerate → regenerate_report
- Chat → continue_chat
"""

# 修改后
paused_context = ''
if _cm5.is_paused(session_id) and session.get('research_result'):
    report = session['research_result'].get('report', {})
    section_count = len(report.get('sections', []))
    topic = context.get('topic', '')
    task_progress = session.get('task_progress', {})
    progress_pct = task_progress.get('progress', 0)

    paused_context = f"""
## Paused Research Context
Research on '{topic}' is PAUSED (progress: {progress_pct:.0%}, {section_count} sections cached).
The research was interrupted but data is preserved.

ACTION PRIORITY (CRITICAL):
1. If the user's message implies continuing/resuming the paused research
   (e.g., 继续/继续任务/继续研究/continue/resume/go on/keep going), you MUST use action="resume_research".
2. If the user explicitly asks to modify the framework → action="modify_research"
3. If the user explicitly asks to regenerate the report → action="regenerate_report"
4. If the user asks a completely new, unrelated question → action="continue_chat"

IMPORTANT: The DEFAULT action for ambiguous messages like "继续" is resume_research, NOT continue_chat.
"""
# 删除 _paused_research_context 死代码分支
```

**修改 2**：`_build_research_running_context` 在 CancelManager paused 时将状态标记改为 PAUSED（`research_api.py:1044-1118`）

```python
# 现有代码 (research_api.py:1107-1118)
        return (
            f"\n## Research Status: RUNNING ({progress_pct:.0%})\n"
            f"Topic: {topic}\n"
            f"Framework sections: {sections_str}{inject_hint}\n"
            f"Current phase: {current_phase_desc}\n"
            f"{completed_hint}\n"
            f"Research is actively running. Agents are working on the above sections.\n"
            f"Rules for changes during research:\n"
            f"- New section, supplement, cancellation → `inject_requirement` (lightweight, no pause)\n"
            f"- User EXPLICITLY says 修改/调整/修订 → `modify_research` (pause + re-plan)\n"
            f"- User EXPLICITLY says 重新规划/重新开始/换个方向 → `enter_framework`\n"
            f"- Simple messages (继续/好的/ok/等) → `continue_chat`\n"
        )

# 修改后：检查 CancelManager 状态，paused 时标记为 PAUSED 并调整行动指引
        from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
        _cm = get_cancel_manager()
        is_paused = session_id and _cm.is_paused(session_id)
        status_label = "PAUSED" if is_paused else "RUNNING"
        status_hint = (
            "Research is PAUSED. Agents are waiting for resume.\n"
            "Rules for changes during pause:\n"
            "- 继续/继续任务/continue/resume → `resume_research` (DEFAULT for ambiguous messages)\n"
            "- User EXPLICITLY says 修改/调整/修订 → `modify_research`\n"
            "- User EXPLICITLY says 重新规划/重新开始/换个方向 → `enter_framework`\n"
            "- Completely new, unrelated question → `continue_chat`\n"
            if is_paused else
            "Research is actively running. Agents are working on the above sections.\n"
            "Rules for changes during research:\n"
            "- New section, supplement, cancellation → `inject_requirement` (lightweight, no pause)\n"
            "- User EXPLICITLY says 修改/调整/修订 → `modify_research` (pause + re-plan)\n"
            "- User EXPLICITLY says 重新规划/重新开始/换个方向 → `enter_framework`\n"
            "- Simple messages (继续/好的/ok/等) → `continue_chat`\n"
        )
        return (
            f"\n## Research Status: {status_label} ({progress_pct:.0%})\n"
            f"Topic: {topic}\n"
            f"Framework sections: {sections_str}{inject_hint}\n"
            f"Current phase: {current_phase_desc}\n"
            f"{completed_hint}\n"
            f"{status_hint}"
        )
```

**关键改进**:
1. 明确标记状态为 `PAUSED`（而非 `interrupted`），与 `_build_research_running_context` 的 `RUNNING` 区分
2. **消除 PAUSED/RUNNING 冲突**：`_build_research_running_context` 在 CancelManager paused 时输出 `PAUSED` 状态，不再与 `paused_context` 矛盾
3. **行动优先级排序**：paused 时 resume 为第一优先，并明确"继续"的默认 action 是 `resume_research`
4. 删除 `_paused_research_context` 死代码分支
5. 不重复 `_build_research_running_context` 已提供的进度详情（Phase/数据点），避免 prompt 冗余

### Fix D（后端 P2）：`_build_research_running_context` 在 mode 被意外修改时仍返回上下文

**文件**: `src/api/research_api.py:1044-1048`

**原方案问题**：原方案将 `if mode != 'research'` 改为 `if mode not in ('research', 'paused')`，但经代码验证，**`session['mode']` 从不被设为 `'paused'`**（grep 搜索 `session['mode'] =` 确认无 `'paused'` 赋值），因此原方案不会产生任何效果。

**正确方案**：检查 CancelManager 的暂停状态，而非检查 mode 值。防御 `_handle_research_msg` 中 LLM 返回 `enter_framework` 后 `session['mode']` 被改为 `'chat'`（`research_api.py:571`）但研究仍被 CancelManager 标记为 paused 的场景。

**与 Fix C 的关系**：Fix C 修改 2 已在 `_build_research_running_context` 的返回值逻辑中增加了 CancelManager paused 检查。Fix D 是对**入口守卫**的补充——确保即使 `mode` 不是 `'research'`，只要 CancelManager 标记为 paused 且研究未终态，仍进入后续逻辑。

```python
# 现有代码
def _build_research_running_context(self, session, session_id=None):
    mode = session.get('mode', 'chat')
    if mode != 'research':
        return ''

# 修改后
def _build_research_running_context(self, session, session_id=None):
    mode = session.get('mode', 'chat')
    if mode != 'research':
        # Fix D: 即使 mode 不是 research，如果 CancelManager 标记为 paused
        # 且 research_result 存在且非终态，仍返回上下文
        if session_id:
            from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
            _cm = get_cancel_manager()
            if _cm.is_paused(session_id):
                research_result = session.get('research_result')
                if research_result and research_result.get('status') not in ('completed', 'completed_with_warnings', 'failed', 'cancelled', 'error'):
                    pass  # 继续执行后续逻辑（Fix C 修改 2 会将状态标记为 PAUSED）
                else:
                    return ''
            else:
                return ''
        else:
            return ''
    # ... 后续逻辑不变
```

### Fix E（后端 P2）：`_on_sse_disconnect` 暂停后通过 ProgressStreamer + SessionStreamer 通知前端

**文件**: `src/api/research_api.py:2999-3028`

**ProgressStreamer TaskState 不一致**（根因 D 第 4 点）：`pause_research`（用户主动暂停，`research_api.py:2704`）调用了 `ProgressStreamer.pause_task(task_id, ...)`，但 `_on_sse_disconnect`（SSE 断连自动暂停）仅调用 `get_cancel_manager().pause(task_id)`，**未调用 `ProgressStreamer.pause_task`**。这导致：
- ProgressStreamer 的 TaskState 仍为 `running`
- 前端重连时 `ProgressStreamer.subscribe()` 的 replay（`progress_streamer.py:495-505` — `if task.status == "running"` 分支）推送 `running` 状态而非 `paused`
- 与 CancelManager 的实际 paused 状态不一致

```python
async def _delayed_pause():
    await asyncio.sleep(30)
    s2 = session_manager.get(task_id)
    if not s2:
        return
    rs2 = s2.get('research_result', {})
    if rs2.get('status') in _terminal:
        return
    exec_task = self._executor_tasks.get(task_id)
    if exec_task is None or exec_task.done():
        # ... 现有的 failed 处理 ...
        return
    from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
    get_cancel_manager().pause(task_id)

    # Fix E-1: 通过 ProgressStreamer 推送 paused 事件 + 同步 TaskState
    # 与 pause_research (research_api.py:2704) 保持一致
    try:
        from src.core.progress_streamer import ProgressStreamer
        ProgressStreamer.pause_task(task_id, 'Research paused due to SSE disconnect')
    except Exception:
        pass

    # Fix E-2: 通过 SessionStreamer 写入 recent_events（前端重连时 replay 可见）
    try:
        from src.core.session_streamer import SessionStreamer
        SessionStreamer.push_agent_message(task_id, {
            'agent_id': 'system',
            'agent_name': 'System',
            'action': 'paused',
            'content': f"Research paused due to SSE disconnect. Progress: {s2.get('task_progress', {}).get('progress', 0):.0%}. Say '继续' to resume.",
        })
    except Exception:
        pass
```

**原理**:
1. **Fix E-1（ProgressStreamer）**：`useProgress.ts:129-131` 已处理 `case 'paused': setStatus('paused')`，这是前端识别暂停状态的主要通道。SSE 断连时 ProgressStreamer 的事件无法实时推送（前端 EventSource 已关闭），但 `ProgressStreamer.pause_task` 会将 TaskState 更新为 `paused`（`progress_streamer.py:448`），前端重连时 `ProgressStreamer.subscribe()` 的 replay（`progress_streamer.py:532-540`）会推送 `paused` 事件。**这是 Fix E-1 的核心价值——不是实时推送，而是确保重连后 replay 的状态正确**。
2. **Fix E-2（SessionStreamer）**：`push_agent_message` 会写入 `recent_events`（`session_streamer.py:157-176`），前端重连时通过 `SessionStreamer.subscribe()` 的 replay 机制可收到。但需注意：前端 `ChatPanel.tsx` 的 `onAgentMessage` 回调**没有处理 `action === 'paused'` 的逻辑**，该消息仅作为聊天记录显示，不会触发状态变更。因此 Fix E-2 是补充性的，真正驱动状态恢复的是 Fix E-1 + 前端 polling。

### Fix F（前端 P2）：前端 SSE 断连后对 paused 状态的轮询恢复

**文件**: `web/src/hooks/useProgress.ts`

**现状分析**：`useProgress.ts:157-182` 的 polling fallback 已在 SSE 断连时对 `running` 和 `paused` 状态进行轮询（line 165: `if (store.status !== 'running' && store.status !== 'paused') return`），轮询间隔 5 秒。这意味着 **paused 状态的轮询恢复机制已存在**。

**但存在缺口**：如果 SSE 断连导致 `useResearchStore.status` 被意外重置为 `'idle'`（而非 `'paused'`），轮询不会启动（因为条件是 `status === 'running' || status === 'paused'`）。此时前端无法发现后端研究已暂停。

**修复方案**：在 `useProgress.ts` 的 polling fallback 中，增加对 `taskId` 存在但 `status === 'idle'` 场景的轮询：

```typescript
// useProgress.ts:157-182 现有逻辑
useEffect(() => {
  stopPolling();
  if (!taskId) return;
  if (isConnected) return;

  const store = useResearchStore.getState();
  // Fix F: 扩展轮询条件
  // 原条件: status === 'running' || status === 'paused'
  // 新增: status === 'idle' 但 taskId 存在（可能 status 被错误重置）
  const shouldPoll = store.status === 'running'
    || store.status === 'paused'
    || (store.status === 'idle' && !!taskId);

  if (!shouldPoll) return;

  const doPoll = async (tid: string) => {
    try {
      const res = await api.getResearchStatus(tid);
      const s = useResearchStore.getState();
      if (s.taskId !== tid) return;
      applyStatusToStore(res.status, res.progress, s, res.phases);
    } catch {
      // Network Error during polling — ignore
    }
  };

  doPoll(taskId);
  pollTimerRef.current = setInterval(() => doPoll(taskId!), POLL_INTERVAL_MS);

  return stopPolling;
}, [taskId, isConnected, stopPolling]);
```

**风险**: 低 — 仅增加一个轮询条件，且 `getResearchStatus` 是轻量 API。

### Fix G（前端 P2）：ChatInput 在 paused 状态下的行为调整

**文件**: `web/src/components/chat/ChatInput.tsx`

**现状分析**：`ChatInput` 的 `isRunning` prop 为 `status === 'running'`（`ChatPanel.tsx:812`），paused 时为 `false`。此时：
- `showStop` 为 `false`（`ChatInput.tsx:137` — `isLoading || isWaitingForReply || (isRunning && !text.trim() && attachments.length === 0)`）
- `canSend` 为 `true`（用户可以正常输入并发送）
- 用户发送消息走 `handleSend → sendMessage`，但 `sendMessage` 没有 paused 分支处理

**问题**：paused 状态下用户可以自由输入并发送消息，但发送的消息可能走 `startResearch`（创建新会话）或 `sendChatMessage`（后端 `_handle_research_msg` 的 paused 分支处理），行为不可预测。

**修复方案**：在 `ChatInput` 中增加 `isPaused` prop，paused 时在输入区域显示提示文字而非普通 placeholder：

```typescript
// ChatPanel.tsx: 传递 isPaused prop
<ChatInput
  onSend={handleSend}
  onCancel={handleCancel}
  disabled={false}
  isLoading={isProcessing}
  isNetworkBusy={isNetworkBusy}
  isWaitingForReply={isWaitingForReply}
  isRunning={status === 'running'}
  isPaused={status === 'paused'}  // Fix G: 新增
  pendingInput={pendingInputText}
  placeholder="Describe research needs or /template &lt;name&gt;"
/>
```

```typescript
// ChatInput.tsx: 使用 isPaused 调整 placeholder
const placeholderText = isPaused
  ? 'Type "继续" to resume research, or ask a new question'
  : isLoading ? 'Processing...'
  : isWaitingForReply ? 'Searching... please wait for results'
  : isRunning ? 'Type query or click ■ to pause'
  : placeholder;

// 在 Textarea 中使用（替换 ChatInput.tsx:283 的内联三目表达式）
<Textarea
  placeholder={placeholderText}
  // ...
/>
```

**风险**: 低 — 仅修改 placeholder 文字，不影响发送逻辑。

---

## 5. 修复优先级与依赖

```
Fix B (前端 Resume 按钮) ← 用户最直接可见的改善，不依赖 currentStep
  ↓
Fix C (后端 paused 上下文增强 + PAUSED/RUNNING 冲突修复) ← LLM 能正确判断 resume，删除死代码
  ↓
Fix A (sendMessage resume 路径) ← 防止创建新会话，需解决闭包陷阱
  ↓
Fix D (_build_research_running_context CancelManager 检查) ← 防御 mode 被意外修改
Fix E (SSE disconnect 通知前端 + ProgressStreamer TaskState 同步) ← 双通道 + TaskState 一致性
Fix F (前端 polling 扩展) ← 修复 status 被重置为 idle 时的轮询缺口
Fix G (ChatInput paused 行为) ← 输入框提示文字调整
```

**建议实施顺序**: Fix B → Fix C → Fix A → Fix D → Fix E → Fix F → Fix G

Fix B 和 Fix C 是最关键的 — Fix B 给用户明确的 Resume 操作入口（不依赖 `currentStep`），Fix C 让 LLM 在收到"继续"时能正确执行 `resume_research`（并消除 PAUSED/RUNNING 状态冲突、删除 `_paused_research_context` 死代码）。

**Fix A 的实施前提**：`api.resumeResearch` 方法已存在于 `api.ts:586-588`，但前端从未调用过。Fix A 需要新增前端对 `api.resumeResearch` 的调用路径，并解决 `useCallback` 闭包捕获 `sessionId` 的陷阱——必须使用 `useResearchStore.getState().sessionId` 动态获取最新值。

---

## 6. 测试要点

### 6.1 核心场景

| 场景 | 预期结果 | 验证点 |
|------|---------|--------|
| 研究 paused 后显示 Resume 按钮 | 显示"恢复研究"和"取消"按钮 | UI 正确渲染，**不依赖 currentStep** |
| 研究 paused 且 `currentStep === null` | 仍显示 Resume 横幅 | Fix B 方案 1 生效 |
| 研究 paused 时 `ResearchStatusBar` 不显示 | 无 running 状态栏 | `status !== 'running'` 时返回 null |
| 点击 Resume 按钮 | 研究恢复执行 | `status` 变为 `running`，`sessionId` 恢复，**`api.resumeResearch` 被调用** |
| paused 状态下输入"继续" | LLM 返回 `resume_research` action | 研究恢复 |
| paused 状态下输入"继续任务" | 不创建新会话，resume 原会话 | `sessionId` 不变，**无递归调用**，**闭包中 sessionId 正确获取** |
| SSE 断连后重连 | 前端收到 paused 通知 | ProgressStreamer replay 推送 paused 事件（**TaskState 为 paused**） |
| sessionId 丢失但有 taskId | 尝试 resume 而非创建新会话 | `taskId` 驱动 resume，**使用 `getState().sessionId` 动态获取** |
| `_build_research_running_context` 在 CancelManager paused 时 | 返回 "Research Status: **PAUSED**" | **不再与 paused_context 矛盾** |
| `session['mode']` 被改为 `'chat'` 但 CancelManager 仍 paused | `_build_research_running_context` 仍返回上下文 | Fix D CancelManager 检查生效 |
| `status` 被意外重置为 `'idle'` 但 `taskId` 存在 | polling 仍启动，发现后端 paused | Fix F 生效 |
| SSE 断连自动暂停后 ProgressStreamer TaskState | TaskState 为 `paused` | Fix E-1 调用 `ProgressStreamer.pause_task` |
| paused 状态下 ChatInput placeholder | 显示"Type '继续' to resume..." | Fix G 生效 |

### 6.2 回归测试

- [ ] 正常研究流程不受影响
- [ ] 研究 paused → resume → 完成，全流程正常
- [ ] 研究 paused → 取消 → 新建研究，正常
- [ ] 多次 pause/resume 循环正常
- [ ] SSE 重连后研究状态正确恢复
- [ ] LLM 在 paused 上下文中能正确区分 resume vs 新问题
- [ ] `_paused_research_context` 死代码删除后无副作用
- [ ] Fix A 的 `sendMessage` 无递归调用（用户消息不重复发送）
- [ ] Fix A 的闭包陷阱已解决（`getState().sessionId` 动态获取）
- [ ] Fix C 修改 2 的 PAUSED 状态标记不影响正常 running 路径
- [ ] Fix D 的 CancelManager 检查不影响正常 `mode === 'research'` 路径
- [ ] Fix E-1 的 `ProgressStreamer.pause_task` 与 `pause_research` 行为一致
- [ ] Fix G 的 placeholder 变化不影响发送功能

---

## 7. 相关文件清单

| 文件 | 变更类型 | Fix |
|------|---------|-----|
| `web/src/hooks/useResearch.ts` | 修改 | A |
| `web/src/components/chat/ChatPanel.tsx` | 修改 | B |
| `web/src/components/chat/ChatInput.tsx` | 修改 | G |
| `web/src/hooks/useProgress.ts` | 修改 | F |
| `src/api/research_api.py` | 修改 | C, D, E |

---

## 8. 与 Select Template Bug 的关系

本问题与 `docs/2026-07-21-select-template-bug-fix.md` 中的 Select Template bug **同源但不同层面**：

| 维度 | Select Template Bug | 本问题 (LLM 失忆) |
|------|-------------------|------------------|
| 根因 | `currentStep` 被陈旧缓存恢复 | `sessionId` 丢失 + LLM 上下文不足 |
| 触发 | 页面刷新/会话切换 | SSE 断连 → pause → 用户操作 |
| 表现 | 显示 "Select Template" 面板 | LLM 回复"请问您想研究什么" |
| 共同点 | 前端状态管理在 SSE 断连后错乱 | 同 |

Select Template bug 的 Fix A（`stateFromCache` 校正 `currentStep`）实施后，`currentStep` 不会再被陈旧值覆盖，间接改善本问题的触发概率。但本问题的核心修复（Fix A-G）仍需独立实施。

**额外发现**：`useSessionStore.ts:252-256` 的 `partialize` 配置只持久化 `running`/`paused` 状态的 `activeId`，这是两个 bug 共享的潜在状态丢失源。如果研究暂停后前端状态被意外重置为非 `running`/`paused`，页面刷新后 `activeId` 丢失，导致 `sessionId` 和 `currentStep` 同时丢失。

**额外发现 2**：`api.resumeResearch` 方法虽存在于 `api.ts:586-588`，但前端从未调用过（全局搜索 `.tsx` 文件中 `api.resumeResearch` 无匹配）。`api.pauseResearch` 仅在 `ChatPanel.tsx:523` 被调用（`handleCancel` 中 `status === 'running'` 时暂停）。这意味着当前前端有暂停能力但无恢复能力——用户暂停研究后，只能通过后端 `_handle_research_msg` 的 paused 分支（LLM 判断 `resume_research` action）间接恢复，没有直接的前端 Resume 操作入口。
