# 暂停/取消快速响应架构修复方案

## 问题

用户点击「停止」或「暂停」后，前端状态长时间不更新（5-15 分钟），原因：

1. 后端暂停是**协作式**的，只在批次间检查标志
2. 一个批次可能持续 5-15 分钟（LLM 调用 + 搜索 + 报告生成），期间不检查暂停标志
3. 前端点暂停后立即设 `status='paused'`，但 SSE progress 事件又覆盖回 `running`
4. 聊天模式下 `_llm_converse` 完全不检查 `CancelManager.is_paused()`

---

## 根因分析（数据流追踪）

### 场景1：研究执行模式（Engine 批次执行）

```
用户点暂停
  → 前端 handleCancel()
    → api.pauseResearch(taskId)    ← HTTP POST /api/v1/research/{id}/pause
    → setStatus('paused')           ← 前端立即设为 paused
    → setIsWaitingForReply(false)

后端 pause_research()
  → cm.pause(task_id)              ← 只设标志位
  → ProgressStreamer.pause_task()   ← SSE 推送 paused
  → return {'status': 'paused'}

但 Engine 此刻正在：
  _execute_batch()                  ← await 阻塞，不检查标志
    → _coordinator.dispatch_task()  ← 并行分发 Agent
    → wait_for_completion()         ← 等待所有 Agent 完成（可能几分钟）

Engine 批次完成后才检查：
  if cm.is_paused(session_id):     ← 终于检查到暂停标志
    await cm.wait_for_resume_or_cancel()

期间 SSE 持续推送 progress 事件 → 前端 useProgress 收到后 setStatus('running') → 覆盖了 paused
```

**关键矛盾：前端以为已暂停，后端 Engine 实际还在跑，SSE 事件把前端状态覆盖回去。**

### 场景2：聊天模式（_llm_converse）

```
用户发消息 → _llm_converse() 同步运行在 HTTP handler 内
  → LLM 流式调用（可能 30-60s）
  → JSON 解析 → 工具调用（web_search 等，可能 60-120s）
  → 循环多次

_llm_converse 只检查 _loop_cancel_flags（新消息到达时取消旧循环）
不检查 CancelManager.is_paused()
```

**聊天模式下根本没有暂停机制，只有取消（通过发送新消息或 api.cancelResearch）。**

---

## 修改方案

### 方案 A：后端快速暂停（根本修复）

#### A1: Engine._execute_batch 内添加暂停检查

**文件：** `src/core/orchestrator/execution/engine.py`

**位置：** `_execute_batch` 方法（约 line 2045），在 for 循环分发每个 Agent 之前检查暂停标志

**当前代码（line 2045-2048）：**
```python
for agent in agents:
    try:
        # **关键修复**：根据Agent类型构建不同的任务
        agent_category = self.classify_agent(agent)
```

**修改为：**
```python
session_id_for_pause = requirement.get("session_id") or requirement.get("task_id", "")
for agent in agents:
    if self._cancel_manager.is_paused(session_id_for_pause):
        logger.info(f"[_execute_batch] Paused mid-batch, skipping remaining {len(agents) - len(task_ids)} agents")
        break
    if self._cancel_manager.is_cancelled(session_id_for_pause):
        logger.info(f"[_execute_batch] Cancelled mid-batch, skipping remaining agents")
        break
    try:
        agent_category = self.classify_agent(agent)
```

**效果：** 暂停后最多等当前正在运行的 Agent 完成（而非等整个批次），已分发但未开始的 Agent 被跳过。

#### A2: Engine._execute_batch 的 wait_for_completion 前添加暂停中断

**位置：** `_execute_batch` 方法（约 line 2342-2343），在等待所有任务完成前，添加周期性暂停检查

**当前代码（line 2342-2343）：**
```python
# 等待完成
results = await self._coordinator.wait_for_completion(task_ids)
```

**修改为：**
```python
# 等待完成（支持暂停中断）
results = await self._wait_for_completion_with_pause_check(task_ids, session_id_for_pause)
```

**新增辅助方法（在 Engine 类中添加）：**
```python
async def _wait_for_completion_with_pause_check(self, task_ids, session_id, poll_interval=2.0):
    """等待任务完成，期间周期性检查暂停/取消标志。

    正常情况：等所有任务完成，返回完整结果。
    暂停检测到：收集已完成任务的结果，不等待未完成任务，立即返回。
      外层批次循环会在下一批次前进入 wait_for_resume_or_cancel。
      未完成的 Agent 在后台继续运行，其结果被丢弃（暂停后不收集）。
    取消检测到：主动取消运行中的任务，收集已完成的结果，立即返回。
    """
    if not task_ids:
        return {}

    wait_task = safe_create_task(
        self._coordinator.wait_for_completion(task_ids),
        name="wait_for_completion_with_pause"
    )

    interrupted = False
    while not wait_task.done():
        if self._cancel_manager.is_cancelled(session_id):
            logger.info(f"[PAUSE-CHECK] Cancelled detected, cancelling running tasks")
            for tid in task_ids:
                active = self._coordinator._active_tasks.get(tid)
                if active and active._async_task and not active._async_task.done():
                    active._async_task.cancel()
            interrupted = True
            break
        if self._cancel_manager.is_paused(session_id):
            logger.info(f"[PAUSE-CHECK] Paused detected, returning completed results only")
            interrupted = True
            break
        await asyncio.sleep(poll_interval)

    if not interrupted:
        # 正常完成
        return await wait_task

    # 被中断：收集已完成任务的结果，不等待未完成的
    # wait_task 仍在后台运行，但我们不 await 它
    # 注意：需要给 cancel 一小段时间让 asyncio.CancelledError 传播
    if self._cancel_manager.is_cancelled(session_id):
        await asyncio.sleep(0.1)

    completed_results = {}
    for tid in task_ids:
        active = self._coordinator._active_tasks.get(tid)
        if active and active.result is not None:
            completed_results[tid] = active.result
        elif active and active.error:
            completed_results[tid] = {"success": False, "error": active.error,
                                      "agent_id": active.agent.agent_id}
    logger.info(f"[PAUSE-CHECK] Returning {len(completed_results)}/{len(task_ids)} completed results")
    return completed_results
```

**效果：** `wait_for_completion` 期间每 2 秒检查暂停/取消标志。暂停时立即返回已完成 Agent 的结果（不等未完成的），外层批次循环会在下一批次前进入 `wait_for_resume_or_cancel`。取消时主动 cancel 运行中的任务后返回。

#### A3: _llm_converse 添加暂停检查

**文件：** `src/api/research_api.py`

**位置：** `_llm_converse` 方法的 for 循环开头（约 line 969）

**当前代码（line 969-972）：**
```python
for iteration in range(MAX_ITERATIONS):
    if self._loop_cancel_flags.get(session_id, 0) != cancel_flag:
        logger.info(f"Cancelling loop iteration {iteration} — new message detected")
        break
```

**修改为：**
```python
for iteration in range(MAX_ITERATIONS):
    if self._loop_cancel_flags.get(session_id, 0) != cancel_flag:
        logger.info(f"Cancelling loop iteration {iteration} — new message detected")
        break
    try:
        from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
        if get_cancel_manager().is_cancelled(session_id):
            logger.info(f"Cancel detected in _llm_converse iteration {iteration}")
            break
        if get_cancel_manager().is_paused(session_id):
            logger.info(f"Pause detected in _llm_converse iteration {iteration}, waiting...")
            pause_result = await get_cancel_manager().wait_for_resume_or_cancel(session_id)
            if pause_result == 'cancelled':
                break
    except ImportError:
        pass
```

**效果：** 聊天模式下也能响应暂停/取消，每次工具调用迭代前检查标志。

**局限性：** 如果 LLM 正在流式输出（`call_llm_stream` / `call_llm`），需要等当前 LLM 调用完成后（最多 60s 超时），才能在下一迭代检查到暂停标志。这是 `call_llm_stream` 不支持取消的固有限制，暂不解决。

#### A4: pause_research 立即反馈 + SSE 推送

**文件：** `src/api/research_api.py`

**位置：** `pause_research` 方法（约 line 2235）

**当前代码已经正确**：调用 `ProgressStreamer.pause_task()` 推送 SSE 暂停事件。无需修改。

---

### 方案 B：前端防覆盖（防御性修复）

#### B1: useProgress 添加 paused/resumed SSE 事件处理 + 忽略覆盖 paused 的事件

**文件：** `web/src/hooks/useProgress.ts`

**位置：** `handleMessage` 函数（约 line 82-131）

**问题1：** 前端 `useProgress` 的 SSE 事件 switch 中没有 `paused` 和 `resumed` case。后端 `ProgressStreamer.pause_task()` 推送 `event: paused`，但前端不处理，导致 SSE 暂停事件丢失。前端暂停状态完全依赖 `handleCancel` 的乐观更新，而非 SSE 事件。

**问题2：** 即使前端已设 `status='paused'`，后端 Engine 仍在运行，SSE 持续推送 progress/phase_start 事件，这些事件调用 `setStatus('running')` 覆盖了前端的 paused 状态。

**当前代码（line 90-94, 96-103, 108-113, 115-124）：**
```typescript
case 'progress': {
  const d = message.data as ProgressData;
  setProgress(d.progress);
  updatePhase(d.phase_id, { progress: d.progress });
  break;
}
case 'phase_start': {
  const d = message.data as PhaseData;
  updatePhase(d.phase_id, {
    status: 'running',
    name: d.phase_name || d.phase_id,
    description: d.description || '',
  });
  break;
}
case 'complete': {
  const d = message.data as CompleteData;
  setStatus('completed');
  setProgress(100);
  setStatistics(d.statistics);
  break;
}
case 'error':
  if (useResearchStore.getState().status !== 'idle') {
    setStatus('error');
  }
  break;
case 'cancelled':
  setStatus('idle');
  break;
```

**修改为：**
```typescript
case 'progress': {
  const d = message.data as ProgressData;
  setProgress(d.progress);
  if (useResearchStore.getState().status !== 'paused') {
    updatePhase(d.phase_id, { progress: d.progress });
  }
  break;
}
case 'phase_start': {
  const d = message.data as PhaseData;
  if (useResearchStore.getState().status !== 'paused') {
    updatePhase(d.phase_id, {
      status: 'running',
      name: d.phase_name || d.phase_id,
      description: d.description || '',
    });
  }
  break;
}
case 'complete': {
  const d = message.data as CompleteData;
  if (useResearchStore.getState().status !== 'paused') {
    setStatus('completed');
  }
  setProgress(100);
  setStatistics(d.statistics);
  break;
}
case 'error':
  if (useResearchStore.getState().status !== 'idle') {
    setStatus('error');
  }
  break;
case 'cancelled':
  setStatus('idle');
  break;
case 'paused':
  setStatus('paused');
  break;
case 'resumed':
  setStatus('running');
  break;
```

**效果：**
1. SSE `paused` 事件正确设置前端状态（不再丢失）
2. SSE `resumed` 事件恢复 `running` 状态
3. 前端已设 `paused` 时，SSE progress/phase_start/complete 事件不会把状态覆盖回 `running`
4. 进度条仍然更新（`setProgress` 不受 paused 保护），让用户看到后台实际进度

#### B2: ChatPanel handleCancel 使用 SSE 暂停事件而非立即设状态

**文件：** `web/src/components/chat/ChatPanel.tsx`

**位置：** `handleCancel` 方法

**当前代码：**
```typescript
if (taskId && status === 'running') {
  try { await api.pauseResearch(taskId); } catch {}
  useResearchStore.getState().setStatus('paused');
  setIsWaitingForReply(false);
  clearTimeout(waitingTimeoutRef.current);
  ...
}
```

**问题：** 在 `api.pauseResearch` 返回后立即设 `paused`，但如果 SSE `pause_task` 事件也推了 `paused`，会导致双重设置。更重要的是，如果 HTTP 请求失败（超时），前端已经设了 `paused` 而后端没有暂停。

**修改为：**
```typescript
if (taskId && status === 'running') {
  try {
    await api.pauseResearch(taskId);
    // 状态由 SSE pause 事件更新，这里只做 HTTP 失败时的兜底
  } catch {
    // HTTP 失败：假设后端已收到暂停信号（乐观更新），设前端状态
    useResearchStore.getState().setStatus('paused');
  }
  setIsWaitingForReply(false);
  clearTimeout(waitingTimeoutRef.current);
  ...
}
```

等等——这引入了新的问题：如果 HTTP 成功但 SSE 事件延迟，前端在等待期间显示 `running`。

**更好的方案：保持乐观更新，但依赖 B1 的防御机制保护状态不被覆盖。** 即：

```typescript
// 保持不变：乐观更新
useResearchStore.getState().setStatus('paused');
// B1 的防御确保 SSE 事件不会覆盖 paused 回 running
```

当前代码已经是这样，不需要修改。B1 已经提供了保护。

---

## 影响范围

| 修改 | 文件 | 行号范围 | 风险 |
|------|------|----------|------|
| A1 | `engine.py` | ~2045 | 低 — 只是在循环入口加检查 |
| A2 | `engine.py` | ~2342 + 新方法 | 中 — 替换 wait_for_completion 调用，需确保结果格式一致 |
| A3 | `research_api.py` | ~969 | 低 — 在迭代入口加检查，不影响已有逻辑 |
| B1 | `useProgress.ts` | ~90-113 | 低 — 只在 paused 时跳过状态更新 |

---

## 不修改的部分

1. **`_execute_batch` 内的 Agent 执行流程** — 不中断正在运行的 Agent（LLM 调用、搜索请求），因为：
   - 中断 LLM 流式调用需要底层 `call_llm_stream` 支持取消，目前不支持
   - 中断搜索请求可能导致数据不完整
   - 让当前 Agent 自然完成，跳过未开始的 Agent，是更安全的策略

2. **`research_executor.py` 的 `_check_paused`** — 已经在执行前检查暂停，不需要修改

3. **`cancel_manager.py`** — 设计正确，不需要修改

---

## 测试计划

1. **手动测试：** 启动研究任务 → 点击暂停 → 验证：
   - 前端 2 秒内显示 `paused` 状态
   - 后端日志显示 `[_execute_batch] Paused mid-batch`
   - SSE 事件不再覆盖前端状态

2. **手动测试：** 聊天模式发送消息 → 点击取消 → 验证：
   - `_llm_converse` 在下一次迭代前检测到取消并退出
   - 前端显示取消消息

3. **单元测试：** 为 `_wait_for_completion_with_pause_check` 编写测试：
   - 正常完成（无暂停）
   - 中途暂停检测
   - 中途取消检测
   - 空任务列表
