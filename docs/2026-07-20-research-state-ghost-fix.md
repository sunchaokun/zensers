# 研究任务状态幽灵化修复方案

> 日期: 2026-07-20
> 严重性: P0 — 用户无法恢复已失败的研究任务，前端显示虚假进度
> 影响: 研究失败后，前端永久显示 "Research in progress"，无法正确恢复或重试

## 1. 问题现象

用户进行"儿童游乐园行业"研究时，DeepSeek API 余额不足（402）导致研究失败。充值后尝试重试，前端显示 "Research in progress"，但后端没有任何执行日志，任务实际上处于"幽灵"状态——看起来在运行，实际已死亡。

## 2. 根因分析

### 2.1 事件时间线

| 时间 | 事件 | 影响 |
|------|------|------|
| 18:28:12 | DeepSeek 402 Payment Required | 14/14 agent 全部失败 |
| 18:28:22 | `fail_task()` 设置 `task_progress.status = "error"` | 正确标记失败 |
| 18:28:22 | `research_executor` 推送 "Research Failed" 消息 | 前端收到失败通知 |
| 18:56:10 | 用户点击 Retry，发送 "Retry the research with different parameters" | 进入 `_handle_research_msg` |
| 18:56:18 | DeepSeek 仍 402，所有 fallback 也不可用 | LLM 调用失败 |
| 18:57:10 | **用户点前端"暂停"按钮**，直接调用 `/pause` API → `pause_research()` | **`task_progress.status` 从 `"error"` 被覆盖为 `"paused"`** |
| 18:57:34 | SSE 断开，`_on_sse_disconnect` 检测到 `research_result.status == 'failed'` | 不再暂停（正确） |
| 21:32:25 | 服务重启，从磁盘恢复 session | `task_progress.status = "paused"` 被恢复 |
| 21:34:09 | 用户发 "继续执行任务" | 走了 paused 分支 |
| 21:34:14 | `_llm_converse` 的 `call_llm_stream` 返回 200 OK | **流式响应挂住，无后续日志** |
| 22:37:20 | 用户刷新页面导致 SSE 断开，`_on_sse_disconnect` 触发 PAUSE | 又一次覆盖为 paused（executor 已 dead） |

### 2.2 根因链（5 个 Bug 互相关联）

#### Bug 1: `task_progress.status` 被 PAUSE 覆盖了 ERROR

`research_executor.py:570` 调用 `fail_task()` 设置 `task_progress.status = "error"`，但 18:57:10 用户点前端"暂停"按钮时，`pause_research()` 被直接调用（不经过 `_handle_user_message` 的关键词检测），`ProgressStreamer.pause_task()` 无条件地将 `task_progress.status` 覆盖为 `"paused"`。

**代码路径**: 前端 `/pause` API → `pause_research()` → `ProgressStreamer.pause_task()` → 无条件覆盖 `task.status = "paused"`

**文件**: `src/core/progress_streamer.py:442-451`, `src/api/research_api.py:2650-2676`

#### Bug 2: `_llm_converse` 的 `call_llm_stream` 无超时保护，且 `asyncio.wait_for` 无法取消 async generator

`call_llm_stream()` 没有任何超时机制。当 DeepSeek 返回 200 OK 但流式内容极慢或挂住时，`async for token in call_llm_stream(...)` 会无限等待。

更严重的是，虽然 `_handle_research_msg:536` 对 `_llm_converse` 设置了 60 秒 `asyncio.wait_for` 超时，但 `asyncio.wait_for` 在取消 async generator 时存在已知问题——如果 generator 的 `aclose()` 被阻塞（如网络 I/O 等待），取消操作不会生效。这解释了为什么 21:34:14 的请求在 60 秒后（21:35:14）仍无超时日志。

**代码路径**: `research_api.py:536` (wait_for 60s) → `_llm_converse` → `call_llm_stream` (async generator, 无超时)

```python
# research_api.py:534-536 — 外层有 60s 超时，但对 async generator 无效
if cm.is_paused(session_id):
    try:
        conv_result = await asyncio.wait_for(self._llm_converse(session_id, user_input), timeout=60)
```

```python
# research_api.py:1205-1210 — 内层 async for 无超时
async for token in call_llm_stream(
    prompt=user_prompt, system_prompt=system_prompt,
    model=_model, max_tokens=_max_tokens, temperature=_temperature,
    api_key=_api_key, base_url=_base_url,
):
    full_content += token  # ← 如果流挂住，这里永远等待，wait_for 无法取消
```

**文件**: `src/api/research_api.py:536, 1205-1210`, `src/core/llm_client.py:35-81`

#### Bug 3: `progress_streamer.subscribe()` 不处理 `paused` 状态的 replay

当 SSE 客户端重新连接时，`subscribe()` 方法对 `running`/`completed`/`error` 都有 replay 逻辑，但对 `paused` 状态没有任何处理。前端收不到明确的暂停事件，只能从历史 agent_message 中恢复出 "Research in progress" 的显示。

**文件**: `src/core/progress_streamer.py:484-541`

#### Bug 4: `_on_sse_disconnect` 延迟暂停不检查 executor task 是否还活着

`_on_sse_disconnect` 只检查 `research_result.status`，不检查 executor task 是否仍在运行。当 executor 已 dead（`_executor_tasks` 中没有对应 task）时，暂停一个已死亡的任务会产生僵尸状态。

**文件**: `src/api/research_api.py:2959-2978`

#### Bug 5: `_handle_research_msg` 不检查 executor task 是否还活着

`_handle_research_msg` 在 `cm.is_paused()` 为 true 时走了 paused 分支，但没有检查 executor task 是否还存在。对于已失败且 executor 已 dead 的任务，不应该走 paused 恢复流程，而应该走 snapshot 恢复或提示用户新建任务。

**文件**: `src/api/research_api.py:515-565`

### 2.3 状态矛盾示意图

```
session.status           = "failed"
session.mode             = "research"     ← 应该是 "chat"
research_result.status   = "failed"
task_progress.status     = "paused"       ← 应该是 "error"
task_phases[0].status    = "running"      ← 应该是 "error"
task_phases[1].status    = "running"      ← 应该是 "error"
cancel_manager.is_paused = True           ← 应该被清理
executor_task            = None (dead)    ← 但系统以为还在运行
```

## 3. 修复方案

### 3.1 Bug 1: 保护 terminal 状态不被 PAUSE 覆盖

**文件**: `src/core/progress_streamer.py`

**修改**: `pause_task()` 方法检查当前状态，如果是 terminal（error/completed/cancelled），不允许覆盖。

```python
# progress_streamer.py — pause_task() 开头添加
@classmethod
def pause_task(cls, task_id: str, message: str = "Task paused") -> None:
    task = cls.get_or_create_task(task_id)
    # FIX: 不允许从 terminal 状态回退到 paused
    if task.status in ("error", "completed", "cancelled"):
        logger.warning(f"Ignoring pause for task {task_id} in terminal state: {task.status}")
        return
    task.status = "paused"
    cls._notify_subscribers(task_id, SSEEventType.PAUSED, {
        "task_id": task_id,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })
    cls._persist_to_session(task_id)
```

### 3.2 Bug 2: `call_llm_stream` 添加超时保护

**文件**: `src/api/research_api.py`

**修改**: 对 `call_llm_stream` 的 `async for` 循环添加整体超时。

```python
# research_api.py — _llm_converse 中 iteration == 0 的流式调用
if SessionStreamer and iteration == 0:
    full_content = ""
    try:
        async def _collect_stream():
            nonlocal full_content
            async for token in call_llm_stream(
                prompt=user_prompt, system_prompt=system_prompt,
                model=_model, max_tokens=_max_tokens, temperature=_temperature,
                api_key=_api_key, base_url=_base_url,
            ):
                full_content += token

        await asyncio.wait_for(_collect_stream(), timeout=120)  # 2 分钟整体超时
    except asyncio.TimeoutError:
        logger.warning(f"Stream timed out (iteration {iteration}), degrading to non-stream")
        result = await asyncio.wait_for(
            call_llm(prompt=user_prompt, system_prompt=system_prompt,
                     model=_model, max_tokens=_max_tokens, temperature=_temperature,
                     api_key=_api_key, base_url=_base_url),
            timeout=60)
        if not result.get('success'):
            raise ValueError(f"LLM call failed: {result.get('error', 'Unknown error')}")
        full_content = result.get('content', '')
    except Exception as stream_err:
        logger.warning(f"Stream failed (iteration {iteration}), degrading: {stream_err}")
        result = await asyncio.wait_for(
            call_llm(prompt=user_prompt, system_prompt=system_prompt,
                     model=_model, max_tokens=_max_tokens, temperature=_temperature,
                     api_key=_api_key, base_url=_base_url),
            timeout=60)
        if not result.get('success'):
            raise ValueError(f"LLM call failed: {result.get('error', 'Unknown error')}")
        full_content = result.get('content', '')
```

### 3.3 Bug 3: `subscribe()` 添加 paused 状态的 replay

**文件**: `src/core/progress_streamer.py`

**修改**: 在 `subscribe()` 方法中添加对 `paused` 状态的处理。

```python
# progress_streamer.py — subscribe() 方法，在 elif task.status == "error" 之前添加
elif task.status == "paused":
    self._queue.put_nowait(SSEMessage(
        event=SSEEventType.PAUSED.value,
        data={
            "task_id": self.task_id,
            "message": task.error or "Task paused",
            "timestamp": datetime.now().isoformat(),
        }
    ))
```

### 3.4 Bug 4: `_on_sse_disconnect` 检查 executor 是否存活

**文件**: `src/api/research_api.py`

**修改**: 在 `_on_sse_disconnect` 中增加 executor task 存活检查。

```python
# research_api.py — _on_sse_disconnect
def _on_sse_disconnect(self, task_id):
    session = session_manager.get(task_id)
    if not session:
        return
    research_result = session.get('research_result', {})
    _terminal = ('completed', 'failed', 'cancelled', 'error')

    # FIX: 检查 research_result 状态
    if research_result.get('status') in _terminal:
        logger.info(f"SSE disconnected for {task_id}, research {research_result.get('status')} - not pausing")
        return

    # FIX: 检查 executor task 是否还活着
    has_executor = task_id in self._executor_tasks and not self._executor_tasks[task_id].done()
    if not has_executor:
        logger.info(f"SSE disconnected for {task_id}, executor dead - not pausing")
        return

    logger.info(f"SSE disconnected for {task_id}, scheduling delayed pause")
    # ... 后续不变
```

### 3.5 Bug 5: `_handle_research_msg` 检查 executor 存活 + 正确处理 failed 状态

**文件**: `src/api/research_api.py`

**修改**: 在进入 paused 分支前，检查研究是否已 failed 且 executor 已 dead。

```python
# research_api.py — _handle_research_msg 开头，替换现有逻辑
async def _handle_research_msg(self, session_id, user_input, session):
    from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
    research_result = session.get('research_result')
    has_executor_task = session_id in self._executor_tasks and not self._executor_tasks[session_id].done()
    cm = get_cancel_manager()

    if research_result and research_result.get('status') in ('completed', 'completed_with_warnings'):
        session['mode'] = 'chat'
        logger.info(f"Research completed, entering chat mode for {session_id}")
        return await self._handle_chat_mode(session_id, user_input)

    # FIX: 研究已失败且 executor 已 dead → 走 snapshot 恢复或提示新建
    if research_result and research_result.get('status') in ('failed', 'error') and not has_executor_task:
        logger.info(f"Research failed and executor dead for {session_id}, attempting recovery")
        # 清理残留的暂停状态
        if cm.is_paused(session_id):
            cm.cleanup(session_id)
        from src.core.progress_streamer import ProgressStreamer
        # 尝试 snapshot 恢复
        snapshot = await self._load_cancel_snapshot(session_id)
        if snapshot and snapshot.get('pending_sections'):
            return await self._resume_from_snapshot(session_id, session, snapshot)
        # 无 snapshot → 降级到 chat 模式
        session['mode'] = 'chat'
        session['current_step'] = 0
        ProgressStreamer.fail_task(session_id, research_result.get('error', 'Research failed'))
        return await self._handle_chat_mode(session_id, user_input)

    if not has_executor_task and not research_result:
        logger.warning(f"Stale research mode for {session_id}, falling back to chat")
        session['mode'] = 'chat'
        session['current_step'] = 0
        session.pop('research_result', None)
        return await self._handle_chat_mode(session_id, user_input)

    # ... 后续 paused 分支逻辑不变
```

### 3.6 附加修复: `llm_client.py` 传递 402 等认证/余额错误详情

**文件**: `src/core/llm_client.py`

**修改**: 在 `call_llm` 的异常处理中，检测 402/401 等 HTTP 错误码并传递原始错误信息。

```python
# llm_client.py — call_llm 中 routing_hint 分支的 except 块
except Exception as err:
    if first_err is None:
        first_err = str(err)
    # FIX: 提取 HTTP 错误码和消息，保留有意义的错误信息
    err_str = str(err)
    if "402" in err_str or "Insufficient Balance" in err_str:
        logger.error(f"LLM balance insufficient on profile '{profile.name}': {err}")
        first_err = f"API余额不足 (profile: {profile.name}): {err_str[:200]}"
    elif "401" in err_str or "Unauthorized" in err_str or "invalid_api_key" in err_str:
        logger.error(f"LLM auth failed on profile '{profile.name}': {err}")
        first_err = f"API认证失败 (profile: {profile.name}): {err_str[:200]}"
    else:
        logger.warning(f"LLM call failed on profile '{profile.name}' (model: {p_model}): {err}")
    # ... 后续 fallback 逻辑不变
```

同时修改 `research_executor.py` 中的失败消息，传递更具体的错误信息：

```python
# research_executor.py — 失败消息构建
_error = result.get("error", "Unknown error")
_error_detail = result.get("summary", _error)
push_chat_response(session_id, {
    "message": f"**Research Failed** ❌\n\n{_error_detail}",  # 使用更详细的错误信息
    ...
})
```

## 4. 服务重启时的状态修复

`main.py` 启动时恢复 session 后，需要检查并修复状态矛盾：

**文件**: `src/api/main.py`（或新建 `src/core/session_recovery.py`）

**修改**: 在 `startup` 事件中添加状态修复逻辑。

```python
async def _repair_ghost_sessions():
    """修复研究状态幽灵化的 session"""
    for sid in session_manager.keys():
        session = session_manager.get(sid)
        if not session:
            continue
        rr = session.get('research_result')
        tp = session.get('task_progress', {})
        if not rr or not tp:
            continue

        rr_status = rr.get('status')
        tp_status = tp.get('status')

        # 研究已失败/取消，但 task_progress 还在 running/paused → 修复
        if rr_status in ('failed', 'error', 'cancelled') and tp_status in ('running', 'paused'):
            logger.warning(f"Repairing ghost session {sid}: research={rr_status}, progress={tp_status}")
            session['mode'] = 'chat'
            session['current_step'] = 0

            # 修复 ProgressStreamer 状态
            from src.core.progress_streamer import ProgressStreamer
            task = ProgressStreamer.get_or_create_task(sid)
            task.status = 'error'
            task.error = rr.get('error', 'Research failed')
            # 修复 task_phases 状态
            for phase in task.phases:
                if phase.status in ('running', 'pending'):
                    phase.status = 'error'
            ProgressStreamer._persist_to_session(sid)

            # 清理 CancelManager 残留标记
            try:
                from src.core.orchestrator.execution.coordinator.cancel_manager import get_cancel_manager
                cm = get_cancel_manager()
                if cm.is_paused(sid) or cm.is_cancelled(sid):
                    cm.cleanup(sid)
            except Exception:
                pass
```

## 5. 修复优先级

| 优先级 | Bug | 影响 | 复杂度 |
|--------|-----|------|--------|
| P0 | Bug 1: terminal 状态保护 | 防止核心状态被覆盖 | 低 |
| P0 | Bug 5: failed + dead executor 处理 | 修复恢复流程 | 中 |
| P0 | 启动状态修复 | 修复已存在的幽灵 session | 中 |
| P1 | Bug 2: stream 超时 | 防止挂住 | 低 |
| P1 | Bug 4: disconnect 检查 executor | 防止僵尸暂停 | 低 |
| P2 | Bug 3: subscribe paused replay | 前端正确显示 | 低 |
| P2 | 附加: 错误信息传递 | 改善用户体验 | 低 |

## 6. 验证方案

1. **Bug 1 验证**: 研究失败后，调用 `pause_task()`，确认 `task_progress.status` 仍为 `"error"`
2. **Bug 2 验证**: 模拟 DeepSeek 流式响应挂住（网络限速），确认 2 分钟后超时降级
3. **Bug 3 验证**: 暂停研究后刷新页面，确认前端显示 "Paused" 而非 "Research in progress"
4. **Bug 4 验证**: 研究 executor 死亡后断开 SSE，确认不会触发 PAUSE
5. **Bug 5 验证**: 研究 failed 后发 "继续"，确认走 snapshot 恢复或降级到 chat
6. **启动修复验证**: 重启服务后确认幽灵 session 的 mode 被修复为 "chat"
