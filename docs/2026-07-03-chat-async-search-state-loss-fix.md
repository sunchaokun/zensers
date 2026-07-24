# Chat 模式异步搜索后前端状态丢失修复方案

> 日期: 2026-07-03
> 状态: 待实施
> 影响: Chat 模式异步工具链 (status=processing) → SSE 推送 chat_response 路径
> 严重性: P1 — 用户可见的状态错乱

---

## 1. 问题描述

用户在 Chat 模式下提问（如"查一下比亚迪近年毛利率和净利率"），后端启动异步搜索工具链（`status: 'processing'`），通过 SSE 逐步推送 `agent_message`（搜索中/完成）和最终 `chat_response`。

**现象**: 后台仍在搜索或搜索刚完成时，前端显示 **"Select Template"** 等研究流程步骤 UI，而非搜索状态指示器或聊天回复，表现为前端状态丢失/错乱。

---

## 2. 根因分析

> **测试验证**: 前端 27 项 + 后端 13 项测试全部通过，详见第 9 节。
> - Bug A ✅ 确认
> - Bug B ✅ 确认（含 `streamingDoneRef` 遗漏）
> - Bug C ✅ 确认（含 localStorage 恢复路径）
> - Bug D ✅ 确认

### Bug A（✅ 测试确认）: SSE `onChatResponse` 不处理 `action`/`mode` 字段

**文件**: `web/src/components/chat/ChatPanel.tsx:141-200`

**问题**: 前端 `useSessionStream` 的 `onChatResponse` 回调只处理了 `suggestions`，完全忽略了 `action` 和 `mode` 字段。

对比同步路径 (`useResearch.ts` `sendMessage`) 的处理：

```typescript
// sendMessage（同步路径）— 正确处理 mode/action
const mode = data.mode || 'chat';
if (mode === 'framework') {
  setStep(0, data.suggestions || data.options);
  if (data.framework) { setFrameworkAction(data.framework); }
} else if (mode === 'research' && data.step === 6) {
  setTaskId(data.session_id);
  setStatus('running');
  setStep(6, undefined);
} else {
  setStep(0, data.suggestions || data.options);
}
```

```typescript
// onChatResponse（SSE 异步路径）— 缺少 mode/action 处理
if (data.suggestions && data.suggestions.length > 0) {
  useResearchStore.getState().setStep(0, data.suggestions); // 仅此一行
}
```

**后果**: 当后台工具链的 LLM 返回 `action: 'enter_framework'` 或 `action: 'start_research'` 时，SSE 路径不会执行模式切换，导致：
- 框架模式不生效（`framework` store 不更新）
- 研究模式不启动（`status` 不变为 `running`）
- 用户看到的 suggestions 点击后可能走入错误的分支

### Bug B（✅ 测试确认）: SSE `chat_response` 重放导致重复处理

**文件**: `src/core/session_streamer.py:355-391`, `web/src/components/chat/ChatPanel.tsx:141-200`

**问题**: `SessionStreamer.subscribe()` 在新连接/重连时重放最近 20 条事件。前端 `onChatResponse` 没有检查 `streamingDoneRef`，也没有对重放事件做去重。

验证：`onChatToken`（第 82 行）有 `streamingDoneRef` 保护，但 `onChatResponse`（第 141 行）没有。SSE 重连时 EventSource 自动重建，`SessionStreamer.subscribe()` 会将缓存的 `chat_response` 事件重新放入队列，导致 `onChatResponse` 重复触发。

后果：
1. 添加重复的 assistant 消息到聊天列表
2. 重复调用 `setStep(0, suggestions)` 导致 UI 闪烁
3. `setSearchState('completed')` 被重复调用

### Bug C（✅ 测试确认）: 后台工具链推送的 `chat_response` 缺少 `mode`/`step` 信息

**文件**: `src/api/research_api.py:1317-1349`

**问题**: `_continue_tool_chain_body` 构建的 `response_data` 不包含 `mode` 和 `step`，而同步路径 `_handle_chat_mode` 返回的 `InteractResponse` 包含这两个字段：

```python
# _handle_chat_mode 同步返回 (line 663)
return {'session_id': session_id, 'step': 0, 'mode': 'chat', 'status': 'processing', ...}

# _continue_tool_chain_body 异步推送 (line 1317-1323)
response_data = {
    'message': parsed.get('message', ''),
    'action': parsed.get('action', 'continue_chat'),
    'topic': parsed.get('topic'),
    'directions': parsed.get('directions', []),
    'suggestions': parsed.get('suggestions', []),
    # ← 缺少 mode 和 step
}
```

即使前端 `onChatResponse` 加了 `mode`/`step` 处理逻辑，也无法获取到这两个字段。

### Bug D（✅ 测试确认）: `onChatResponse` 不防重入，SSE 重连时可能重复触发

与 Bug B 同源，单独列出以强调影响范围。

**文件**: `web/src/components/chat/ChatPanel.tsx:141-200`

`onChatResponse` 没有使用 `streamingDoneRef` 做保护（而 `onChatToken` 第 82 行有），且没有消息去重机制。

### Bug E（✅ 测试确认，关键发现）: `streamingDoneRef` 未在 `else` 分支设置

**文件**: `web/src/components/chat/ChatPanel.tsx:171-187`

**问题**: `onChatResponse` 中，`streamingDoneRef.current = true` 仅在 `if (streamingMsgIdRef.current)` 分支设置（第 178 行）。异步搜索场景走 `else` 分支（第 179-186 行），`streamingDoneRef` 保持 `false`，导致防重入保护完全失效。

测试验证：
- `async search: streamingDoneRef stays false after onChatResponse` → ✅ 确认 bug 存在
- `replayed chat_response is NOT blocked when streamingDoneRef is false` → ✅ 确认重放不被阻止
- `with fix: streamingDoneRef=true blocks replay` → ✅ 确认修复方案有效

### Bug F（✅ 测试确认）: `currentStep` 被缓存恢复为旧值

**文件**: `web/src/store/useResearchStore.ts:124-138`

**场景 1 — `status` 变化触发订阅恢复旧 `currentStep`**:

测试 `stale cache overwrite: status change triggers subscription → currentStep=2 restored` 确认：当 `useResearchStore` 订阅条件满足（`status` 从 `idle` 变为 `completed`），缓存中旧的 `currentStep: 2` 会覆盖前端刚设置的 `currentStep: 0`，导致显示 "Select Template"。

测试 `with fine-grained fix: status change does NOT restore stale currentStep` 确认：精细化订阅（仅更新 `status`/`progress`/`phases`，不覆盖 `currentStep`）可修复此场景。

**场景 2 — 页面刷新后 localStorage 恢复旧 `currentStep`**:

测试 `page refresh from localStorage restores stale currentStep=2` 确认：`useSessionStore` 持久化包含 `currentStep: 2` 的会话数据，刷新后恢复，`useResearchStore` 订阅触发（`sessionId` 从 `null` 变为 `ses-001`），`currentStep: 2` 被恢复，直接导致 "Select Template"。

---

## 3. 修复方案

### Fix 1: SSE `onChatResponse` 补全 `action`/`mode` 处理 [P1]

**文件**: `web/src/components/chat/ChatPanel.tsx`

在 `onChatResponse` 回调中，参照 `sendMessage` 的逻辑，增加 `action`/`mode` 分支处理：

```typescript
onChatResponse: (data) => {
  const storeSessionId = useSessionStore.getState().activeId;
  const matches = data.session_id === sessionId
    || data.session_id === taskId
    || data.session_id === storeSessionId;
  if (!matches) return;

  // Fix 1+4: 防重入 — 如果已经处理过最终的 chat_response，忽略重放
  if (streamingDoneRef.current) return;

  // Fix 4: 去重 — 检查是否已有相同 timestamp 的 assistant 消息
  const existingMsg = useChatStore.getState().messages.find(
    m => m.role === 'assistant' && m.timestamp === data.timestamp
  );
  if (existingMsg) return;

  // ... 现有的 finalContent / finalThinking / 消息更新逻辑保持不变 ...

  // Fix 1: 根据 action/mode 更新前端状态（与 sendMessage 保持一致）
  const mode = data.mode || 'chat';
  const action = data.action || 'continue_chat';

  if (mode === 'framework') {
    useResearchStore.getState().setStep(0, data.suggestions || []);
    // framework 数据可能不在 SSE 中，需要 API 补偿获取（见 Fix 5）
  } else if (mode === 'research' && data.step === 6) {
    useResearchStore.getState().setTaskId(data.session_id);
    useResearchStore.getState().setStatus('running');
    useResearchStore.getState().setStep(6, undefined);
  } else if (action === 'enter_framework') {
    useResearchStore.getState().setStep(0, data.suggestions || []);
    // 需要获取 framework 详情（见 Fix 5）
  } else if (action === 'start_execution' || action === 'start_research') {
    useResearchStore.getState().setStatus('running');
    useResearchStore.getState().setStep(6, undefined);
  } else {
    // continue_chat / 其他
    if (data.suggestions && data.suggestions.length > 0) {
      useResearchStore.getState().setStep(0, data.suggestions);
    }
  }

  useResearchStore.getState().setSearchState('completed');
  const rs = useResearchStore.getState();
  if (rs.status !== 'running') {
    setIsWaitingForReply(false);
    clearTimeout(waitingTimeoutRef.current);
  }
  clearTimeout(searchStateTimerRef.current);
  searchStateTimerRef.current = setTimeout(() => {
    useResearchStore.getState().setSearchState('idle');
  }, 2000);
},
```

**变更要点**:
- 增加 `streamingDoneRef` 保护 + timestamp 去重，防止 SSE 重放重复处理
- 增加 `mode`/`action` 分支判断，与 `sendMessage` 同步路径对齐
- `enter_framework` 场景需要额外处理（见 Fix 5）

### Fix 2: 后台工具链 `chat_response` 补全 `mode`/`step` 信息 [P1]

**文件**: `src/api/research_api.py`

在 `_continue_tool_chain_body` 构建 `response_data` 时，增加 `mode` 和 `step` 字段：

```python
# 现有代码 (line 1317-1323)
response_data = {
    'message': parsed.get('message', ''),
    'action': parsed.get('action', 'continue_chat'),
    'topic': parsed.get('topic'),
    'directions': parsed.get('directions', []),
    'suggestions': parsed.get('suggestions', []),
}

# 修改后
response_data = {
    'message': parsed.get('message', ''),
    'action': parsed.get('action', 'continue_chat'),
    'topic': parsed.get('topic'),
    'directions': parsed.get('directions', []),
    'suggestions': parsed.get('suggestions', []),
    'mode': parsed.get('mode', 'chat'),
    'step': parsed.get('step', 0),
}
```

同时在 `ProgressStreamer.push_chat_response` 和 `SessionStreamer.push_chat_response` 中透传这些字段。

**文件**: `src/core/progress_streamer.py:637-646`

```python
# 在 _notify_subscribers 的 data 中增加
"mode": response_data.get("mode", "chat"),
"step": response_data.get("step", 0),
```

**文件**: `src/core/session_streamer.py:183-192`

```python
# 在 event_data 中增加
"mode": response_data.get("mode", "chat"),
"step": response_data.get("step", 0),
```

**文件**: `web/src/types/api.ts`

在 `ChatResponseData` 接口中增加字段：

```typescript
export interface ChatResponseData {
  session_id: string;
  message: string;
  action: string;
  topic?: string;
  directions?: string[];
  suggestions?: Array<{ id: string; label: string; example: string }>;
  timestamp: string;
  thinking_content?: string;
  mode?: 'chat' | 'framework' | 'research';  // 新增
  step?: number;                                // 新增
}
```

### Fix 3: `useResearchStore` 订阅精细化，避免 `currentStep` 被缓存覆盖 [P1]

**文件**: `web/src/store/useResearchStore.ts`

当前订阅在 `sessionId` 或 `status` 变化时全量恢复，会覆盖前端主动设置的 `currentStep`。修改为精细化更新：

```typescript
// 现有代码 (line 136)
if (current.sessionId !== next.sessionId || current.status !== next.status) {
  set(next);
}

// 修改后
if (current.sessionId !== next.sessionId) {
  // 会话切换：全量恢复（用户主动切换到另一个会话，需要完整状态）
  set(next);
} else if (current.status !== next.status) {
  // 同一会话内仅 status 变化：只更新 status 相关字段，保留前端当前 currentStep/stepOptions
  set({
    status: next.status,
    progress: next.progress,
    phases: next.phases,
    statistics: next.statistics,
    summary: next.summary,
  });
}
```

**设计理由**:
- `currentStep` 和 `stepOptions` 由前端主动 `setStep` 控制，不应被缓存中的旧值覆盖
- 会话切换时需要全量恢复，因为要呈现目标会话的完整 UI 状态
- `useProgress` 中 `setStatus('completed')` 触发的订阅更新不再覆盖 `currentStep`，避免研究完成后 `currentStep` 被旧值替换

**风险**: 需要确保会话切换（`switchTo`）确实导致 `sessionId` 变化。当前 `switchTo` 只设置 `activeId`，`useResearchStore` 通过 `stateFromCache` 检测 `sessionId` 变化来触发恢复。需要验证切换回已有会话时 `sessionId` 是否正确变化。

### Fix 4: SSE 重放防护 [P2]

**文件**: `web/src/components/chat/ChatPanel.tsx`

已在 Fix 1 中合并实现（`streamingDoneRef` 保护 + timestamp 去重）。

额外加固：在 `handleSend` 开头重置 `streamingDoneRef` 时，确保异步搜索完成后 `streamingDoneRef` 正确设置：

```typescript
// handleSend 开头（现有代码 line 355-356）
streamingMsgIdRef.current = null;
streamingDoneRef.current = false;
```

这部分已存在，无需修改。但需确认：当 `status: 'processing'` 时，没有 `chat_token` 事件，因此 `streamingMsgIdRef` 保持 `null`。当 `onChatResponse` 触发时，走第 179-186 行的 `else` 分支（添加新消息），并设置 `streamingDoneRef.current = true`（仅在 `streamingMsgIdRef.current` 存在时设置——**这是一个遗漏**！）。

**发现问题**: 第 171-178 行只在 `streamingMsgIdRef.current` 存在时设置 `streamingDoneRef.current = true`。如果 `streamingMsgIdRef.current` 为 `null`（异步搜索场景），`streamingDoneRef` 不会被设置为 `true`，导致防重入保护失效！

```typescript
// 现有代码 (line 171-187)
if (streamingMsgIdRef.current) {
  updateMessage(streamingMsgIdRef.current, { ... });
  streamingMsgIdRef.current = null;
  streamingDoneRef.current = true;  // ← 只在这里设置
} else {
  addMessage({ ... });              // ← 异步搜索走这里，streamingDoneRef 不变！
}
```

**修复**: 在 `else` 分支末尾也设置 `streamingDoneRef.current = true`：

```typescript
if (streamingMsgIdRef.current) {
  updateMessage(streamingMsgIdRef.current, {
    content: finalContent,
    ...(finalThinking !== undefined ? { thinkingContent: finalThinking } : {}),
    metadata: { status: 'done' },
  });
  streamingMsgIdRef.current = null;
  streamingDoneRef.current = true;
} else {
  addMessage({
    id: nanoid(),
    role: 'assistant',
    content: finalContent,
    ...(finalThinking !== undefined ? { thinkingContent: finalThinking } : {}),
    timestamp: data.timestamp || new Date().toISOString(),
  });
  streamingDoneRef.current = true;  // ← 新增：异步搜索完成后也标记 done
}
```

### Fix 5: `enter_framework` 场景的 SSE → API 补偿机制 [P2]

**文件**: `web/src/components/chat/ChatPanel.tsx`

当 SSE `chat_response` 的 `action` 为 `enter_framework` 时，SSE 不携带完整 framework 数据，需要额外调用 API 获取：

```typescript
if (mode === 'framework' || action === 'enter_framework') {
  useResearchStore.getState().setStep(0, data.suggestions || []);
  // SSE 不携带完整 framework 数据，需要 API 补偿获取
  try {
    const detail = await api.getResearchDetail(sessionId!);
    if (detail.framework) {
      useResearchStore.getState().setFramework(detail.framework);
    }
  } catch (e) {
    console.error('Failed to fetch framework details:', e);
  }
}
```

**注意**: `onChatResponse` 是同步回调，不能直接 `await`。需要改为异步处理或使用 `.then()`：

```typescript
if (mode === 'framework' || action === 'enter_framework') {
  useResearchStore.getState().setStep(0, data.suggestions || []);
  api.getResearchDetail(sessionId!).then(detail => {
    if (detail.framework) {
      useResearchStore.getState().setFramework(detail.framework);
    }
  }).catch(e => {
    console.error('Failed to fetch framework details:', e);
  });
}
```

### Fix 6: 后台工具链对 `enter_framework` action 的后端侧处理 [P2]

**文件**: `src/api/research_api.py`

在 `_continue_tool_chain_body` 中，当 LLM 返回 `action: 'enter_framework'` 时，后端应更新 session 状态，确保前端 API 补偿调用能获取到 framework：

```python
# 在 _continue_tool_chain_body 中，构建 response_data 之前
if parsed.get('action') == 'enter_framework':
    session['mode'] = 'framework'
    context = session.get('research_context', {})
    if parsed.get('topic'):
        context['topic'] = parsed['topic']
    if parsed.get('framework_sections'):
        context['_suggested_sections'] = parsed['framework_sections']
    if parsed.get('framework_tree'):
        context['_framework_tree'] = parsed['framework_tree']
    session['research_context'] = context
    # 同步 _sync_state_machine_to_framework 确保状态机一致
    self._sync_state_machine_to_framework(session, session_id)
    # 调用 _enter_framework_mode 生成完整框架
    try:
        framework_result = await self._enter_framework_mode(session_id, parsed.get('message', ''))
        if isinstance(framework_result, dict) and framework_result.get('framework'):
            # framework 已写入 session，前端通过 API 补偿可以获取
            pass
    except Exception as e:
        logger.warning(f"Failed to enter framework mode from background chain: {e}")
    response_data['mode'] = 'framework'
    response_data['step'] = 0
```

---

## 4. "Select Template" 直接触发路径排查

以上 Fix 解决的是 SSE 异步路径与同步路径的行为不一致问题。但 "Select Template"（`currentStep` 为 1/2/6 且 `isChatMode` 为 false）的直接触发路径尚未完全确认。

**最可能的触发场景**:

1. **页面刷新后 localStorage 恢复旧状态**: `useSessionStore` 持久化了 `currentStep: 2` 的会话数据。刷新后恢复，如果 `status` 值触发 `useResearchStore` 订阅，`currentStep: 2` 被恢复。
2. **`useProgress` 接收到研究任务完成事件**: 如果聊天会话同时关联了研究任务，`setStatus('completed')` 触发订阅，恢复缓存的 `currentStep`。
3. **多次 SSE chat_response 竞态**: 第一条消息的后台工具链完成后推送 `chat_response`，但此时 `streamingDoneRef` 未正确设置（Bug D 中的遗漏），第二条消息的 SSE 事件被重复处理。

**建议排查手段**:
- 在 `useResearchStore` 的 `setStep` 中增加 `console.trace()`，记录每次 `currentStep` 变化的调用栈
- 在 `renderStepContent` 入口增加 `currentStep` 值的日志
- 在 `useResearchStore` 订阅回调中增加日志，记录何时从缓存恢复 `currentStep`

---

## 5. 实施优先级

| 优先级 | Fix | 影响范围 | 风险 | 工作量 |
|--------|-----|---------|------|--------|
| P1 | Fix 1: onChatResponse 补全 action/mode 处理 | 前端 ChatPanel.tsx | 低 | S |
| P1 | Fix 2: 后端补全 mode/step 信息 | 后端 + 前端 api.ts | 低 | S |
| P1 | Fix 3: useResearchStore 订阅精细化 | 前端 useResearchStore.ts | 中 — 需要测试会话切换场景 | S |
| P1 | Fix 4: streamingDoneRef 遗漏修复 | 前端 ChatPanel.tsx | 低 | S |
| P2 | Fix 5: enter_framework API 补偿 | 前端 ChatPanel.tsx | 低 | M |
| P2 | Fix 6: 后端 enter_framework 处理 | 后端 research_api.py | 中 | M |

**建议实施顺序**: Fix 4 → Fix 2 → Fix 1 → Fix 3 → Fix 5 → Fix 6

Fix 4 最小改动且解决最明确的 bug（`streamingDoneRef` 遗漏），应优先实施。Fix 2 是 Fix 1 的数据前提。

---

## 6. 测试要点

### 6.1 核心场景测试

| 场景 | 预期结果 | 验证点 |
|------|---------|--------|
| Chat 模式提问触发搜索 | 搜索完成后正常显示回复 + suggestions | `currentStep` 保持 0，无 "Select Template" |
| 搜索中 LLM 返回 enter_framework | 显示框架确认 UI | `currentStep = 0`，`framework` 有值 |
| 多轮搜索（搜索 → 回复 → 再搜索） | 每轮搜索状态正确切换 | 无状态错乱 |
| SSE 重连后 | 不重复处理已完成的 chat_response | `streamingDoneRef` 正确生效 |
| 会话切换 | 正确恢复目标会话状态 | `currentStep` 与目标会话一致 |
| 页面刷新后恢复 | 恢复正确的 UI 状态 | 无 "Select Template" 闪烁 |

### 6.2 回归测试

- [ ] 正常研究流程 (step 1-6) 不受影响
- [ ] 框架确认模式正常工作
- [ ] 研究执行中的 agent_message 正常显示
- [ ] 暂停/取消/恢复功能正常
- [ ] 页面刷新后会话状态正确恢复
- [ ] 历史会话切换正常

### 6.3 竞态条件测试

- [ ] 搜索进行中发送新消息 → 旧搜索被取消，`streamingDoneRef` 正确重置
- [ ] 搜索完成瞬间切换会话 → 不影响新会话
- [ ] SSE 重连与 chat_response 到达的竞态 → 无重复处理
- [ ] 后台工具链推送 chat_response 时 `mode='framework'` → 前端正确进入框架模式

---

## 7. 相关文件清单

| 文件 | 变更类型 | Fix |
|------|---------|-----|
| `web/src/components/chat/ChatPanel.tsx` | 修改 | 1, 4, 5 |
| `web/src/store/useResearchStore.ts` | 修改 | 3 |
| `web/src/types/api.ts` | 修改 | 2 |
| `src/api/research_api.py` | 修改 | 2, 6 |
| `src/core/progress_streamer.py` | 修改 | 2 |
| `src/core/session_streamer.py` | 修改 | 2 |

---

## 8. 历史参考

- `docs/2026-06-25-research-state-loss-fix.md` — 研究执行阶段状态丢失修复（不同场景，但相关）
- 本次修复针对 **Chat 模式异步搜索** 路径的状态丢失，与上次 **Research 执行阶段** 的状态丢失是不同触发路径

---

## 9. 测试验证结果

### 前端测试（27/27 通过）

**文件**: `web/src/components/chat/__tests__/chat-async-search-state.test.ts`

| 测试用例 | Bug | 结果 |
|----------|-----|------|
| action=enter_framework is ignored — framework not set | A | ✅ |
| action=start_research is ignored — status stays idle | A | ✅ |
| mode=framework is ignored — stays in chat mode | A | ✅ |
| compare: sync sendMessage would handle mode=framework correctly | A | ✅ |
| async search: streamingDoneRef stays false after onChatResponse | E | ✅ |
| streaming search: streamingDoneRef becomes true after onChatResponse | E | ✅ |
| replayed chat_response is NOT blocked when streamingDoneRef is false | B+E | ✅ |
| with fix: streamingDoneRef=true blocks replay | B+E | ✅ |
| status change alone triggers subscription with current code | F | ✅ |
| with fine-grained subscription: status change alone does NOT restore currentStep | F | ✅ |
| page refresh from localStorage restores stale currentStep=2 | F | ✅ |
| sync response includes mode and step | C | ✅ |
| background tool chain response_data lacks mode and step | C | ✅ |
| ProgressStreamer.push_chat_response SSE data lacks mode and step | C | ✅ |
| with fix: response_data includes mode and step | C | ✅ |
| renderStepContent shows "Select Template" when currentStep=2 | E | ✅ |
| renderStepContent shows "Select Template" when currentStep=6 | E | ✅ |
| renderStepContent shows chat mode when currentStep=0 | — | ✅ |
| renderStepContent shows chat mode when currentStep=null | — | ✅ |
| sendMessage setStep(0,undefined) → currentStep stays 0 | — | ✅ |
| onChatResponse with suggestions → setStep(0,suggestions) | — | ✅ |
| stale cache overwrite: currentStep=2 restored | F | ✅ |
| fine-grained fix: currentStep=0 preserved | F | ✅ |
| full happy path: sendMessage → processing → SSE chat_response | — | ✅ |
| SSE replay after search completion: creates duplicate message | B | ✅ |
| enter_framework from background: framework not set | A | ✅ |
| multiple searches in sequence: status accumulates correctly | — | ✅ |

### 后端测试（13/13 通过）

**文件**: `tests/unit/test_chat_async_search_state.py`

| 测试用例 | Bug | 结果 |
|----------|-----|------|
| sync_processing_response_has_mode_and_step | C | ✅ |
| background_tool_chain_response_data_lacks_mode | C | ✅ |
| enter_framework_action_not_handled_in_background_chain | A | ✅ |
| push_chat_response_sse_data_has_no_mode | C | ✅ |
| push_chat_response_with_mode_fix | C | ✅ |
| subscribe_replays_recent_messages | B | ✅ |
| replay_delivers_same_event_twice | B | ✅ |
| replay_with_stale_framework_suggestions | B | ✅ |
| dual_write_creates_session_subscriber_event | C | ✅ |
| set_search_state_is_local_only | F | ✅ |
| current_schema_lacks_mode_and_step | C | ✅ |
| extended_schema_includes_mode_and_step | C | ✅ |
| framework_mode_in_extended_schema | C | ✅ |
