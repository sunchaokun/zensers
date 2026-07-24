# "Select Template" 误触发修复方案

> 日期: 2026-07-21
> 状态: 待实施
> 严重性: P1 — 用户可见的状态错乱
> 前置文档: `docs/2026-07-03-chat-async-search-state-loss-fix.md`

---

## 1. 问题描述

用户在 Chat 模式下提问后，UI 显示 **"Select Template"** 或 **"Select Output Type"** 面板，而非正常的聊天回复。该问题在以下场景中出现：

1. 页面刷新后恢复会话
2. 从历史记录切换回已完成的研究会话
3. Chat 模式下发送消息后，后台异步搜索完成时

---

## 2. 已实施修复回顾

`2026-07-03` 文档中提出的 6 个 Fix **已全部实施**：

| Fix | 描述 | 实施状态 | 代码位置 |
|-----|------|---------|---------|
| Fix 1 | `onChatResponse` 补全 `action`/`mode` 处理 | ✅ 已实施 | `ChatPanel.tsx:197-225` |
| Fix 2 | 后端 `response_data` 补全 `mode`/`step` | ✅ 已实施 | `research_api.py:1562-1563`, `progress_streamer.py:657-658`, `session_streamer.py:191-192,205-206` |
| Fix 3 | `useResearchStore` 订阅精细化 | ✅ 已实施 | `useResearchStore.ts:136-146` |
| Fix 4 | `streamingDoneRef` else 分支遗漏 | ✅ 已实施 | `ChatPanel.tsx:194` |
| Fix 5 | `enter_framework` API 补偿 | ✅ 已实施 | `ChatPanel.tsx:202-206,213-217` |
| Fix 6 | 后端 `enter_framework` 处理 | ✅ 已实施 | `research_api.py:1578-1593` |

**但 "Select Template" 仍然出现**，说明存在未被上述 Fix 覆盖的根因路径。

---

## 3. 根因分析

### 3.1 渲染条件

`ChatPanel.tsx` 中 "Select Template" 的渲染条件链：

```
currentStep !== null && currentStep !== 0
  → isChatMode = false
  → stepOptions 存在 && currentStep ∉ {3, 4}
  → 渲染 OptionSelector title="Select Template" (currentStep=2/6) 或 "Select Output Type" (currentStep=1)
```

关键代码：
- `ChatPanel.tsx:393` — `const isChatMode = currentStep === null || currentStep === 0;`
- `ChatPanel.tsx:659` — `if (stepOptions && !stepOptions.some(o => o.required !== undefined) && currentStep !== 3 && currentStep !== 4)`
- `ChatPanel.tsx:673` — `title={currentStep === 1 ? 'Select Output Type' : 'Select Template'}`
- `ChatPanel.tsx:783` — `{currentStep !== null && ( <div> {renderStepContent()} </div> )}`

### 3.2 根因路径（3 条）

#### 根因 A: `restoreSession()` 为已完成/运行中会话设置 `currentStep: 6`

**文件**: `useSessionStore.ts:110, 135`

```typescript
// 已完成会话
if (status === 'completed') {
  syncActive({ ..., currentStep: 6, ... });  // ← 问题
}

// 运行中会话
if (status === 'running' || status === 'reporting') {
  syncActive({ ..., currentStep: 6, ... });  // ← 问题
}
```

**触发场景**: 用户从历史记录点击一个已完成的研究会话 → `Sidebar.tsx:43-45` 调用 `reset()` + `restoreSession(id)` → `restoreSession` 调用 `syncActive({currentStep: 6})` → `useResearchStore` 订阅检测到 `sessionId` 变化 → `stateFromCache` 恢复 `currentStep: 6` → `isChatMode = false` → 如果 `stepOptions` 非空则显示 "Select Template"。

**竞态细节**: `Sidebar.tsx:43` 先调用 `reset()`（设置 `currentStep: null`），然后 `restoreSession(id)` 异步获取后端数据后调用 `syncActive({currentStep: 6})`。由于 `reset()` 会创建新 session（`useResearchStore.ts:231`），`sessionId` 从旧值变为新值再变为恢复的 ID，订阅多次触发，最终 `currentStep: 6` 被恢复。

#### 根因 B: localStorage 持久化陈旧 `currentStep`

**文件**: `useSessionStore.ts:248-293` (persist middleware), `useResearchStore.ts:124-147` (subscription)

**触发场景**:
1. 用户在研究向导 step 2（"Select Template"）时，`setStep(2, options)` 被调用
2. `setStep` 内部调用 `syncActive({currentStep: 2, stepOptions: options})`，写入 session cache
3. Zustand persist 将 session cache（含 `currentStep: 2`）写入 localStorage
4. 用户刷新页面 → Zustand 从 localStorage 恢复 → `useResearchStore` 订阅触发 → `stateFromCache` 读取 `c.currentStep = 2` → `sessionId` 变化 → `set(next)` 恢复 `currentStep: 2`

**关键**: Fix 3 只解决了**同一会话内** `status` 变化不覆盖 `currentStep` 的问题，但**会话切换**（`sessionId` 变化）时仍然全量恢复，包括陈旧的 `currentStep`。

#### 根因 C: `SessionTabs.tsx` 切换前同步陈旧 `currentStep`

**文件**: `SessionTabs.tsx:48-51`

```typescript
syncActive({
  status,
  currentStep,        // ← 将当前会话的 currentStep 写入 cache
  messages: useChatStore.getState().messages,
});
switchTo(id);
```

**触发场景**: 用户在研究向导 step 2 时点击另一个 tab → 当前会话的 `currentStep: 2` 被写入 cache → 切换回来时从 cache 恢复 `currentStep: 2`。

### 3.3 根因汇总

| 根因 | 触发路径 | currentStep 值 | 频率 |
|------|---------|---------------|------|
| A | `restoreSession()` 为 completed/running 会话设 `currentStep: 6` | 6 | **高** — 每次从历史恢复已完成会话 |
| B | localStorage 持久化 + 页面刷新恢复陈旧 `currentStep` | 1-6 | **中** — 需要用户在研究向导中途刷新 |
| C | `SessionTabs` 切换前同步陈旧 `currentStep` | 1-6 | **中** — 需要多 tab 切换 |

**核心问题**: `currentStep` 是研究向导的**瞬态 UI 状态**，不应被持久化或在会话恢复时盲目还原。当会话处于 `idle`/`completed`/`error` 状态时，`currentStep` 应始终为 `null` 或 `0`。

---

## 4. 修复方案

### Fix A: `stateFromCache` 中根据 `status` 校正 `currentStep` [P1]

**文件**: `web/src/store/useResearchStore.ts:94-119`

**原理**: 在从 session cache 恢复状态时，如果会话状态为 `idle`/`completed`/`error`，强制 `currentStep` 为 `null`，同时清空 `stepOptions` 和 `parameterConfig`。这些是研究向导的瞬态 UI 数据，仅在研究流程进行中（`running`/`paused`）才有意义。

```typescript
function stateFromCache(c: SessionCache | undefined): Partial<ResearchState> {
  if (!c) return {
    taskId: null, sessionId: null, progress: 0, phases: [], status: 'idle' as ResearchStatus,
    currentStep: null, stepOptions: null, parameterConfig: null, summary: null, statistics: null,
    framework: null,
    ...DEFAULT_NEW_FIELDS,
  };

  // 研究向导瞬态 UI 状态：仅在研究进行中保留，idle/completed/error 时重置
  const isResearchActive = c.status === 'running' || c.status === 'paused';
  const safeStep = isResearchActive ? c.currentStep : null;
  const safeStepOptions = isResearchActive ? c.stepOptions : null;
  const safeParameterConfig = isResearchActive ? c.parameterConfig : null;

  return {
    taskId: c.taskId,
    sessionId: c.id === '__pending__' ? null : c.id,
    progress: c.progress,
    phases: c.phases,
    status: c.status,
    currentStep: safeStep,
    stepOptions: safeStepOptions,
    parameterConfig: safeParameterConfig,
    summary: c.summary,
    statistics: c.statistics,
    framework: c.framework ?? null,
    agentMessages: c.agentMessages || [],
    previewUrl: c.previewUrl || null,
    downloadUrl: c.downloadUrl || null,
    result: c.result || null,
    interrupted: c.interrupted || false,
  };
}
```

**影响范围**: 所有通过 `useResearchStore` 订阅恢复状态的路径（会话切换、页面刷新、`restoreSession`）。

**风险**: 低 — `idle`/`completed`/`error` 状态下，研究向导 UI 不应显示，重置 `currentStep` 是正确行为。唯一需确认的是 `completed` 状态下 `currentStep: 6` 是否有其他用途（如显示研究完成状态栏）。经检查，研究完成状态由 `status: 'completed'` + `result` 控制，不依赖 `currentStep`。

### Fix B: `restoreSession()` 不再为已完成会话设置 `currentStep: 6` [P1]

**文件**: `web/src/store/useSessionStore.ts:104-159`

**原理**: `restoreSession` 从后端 API 获取会话详情后，根据状态设置 `currentStep`。已完成/空闲会话应设 `currentStep: 0`（chat mode），而非 `6`。

```typescript
if (status === 'completed') {
  useSessionStore.getState().syncActive({
    title: detail.title || detail.topic || 'Untitled',
    taskId: id,
    messages: msgs,
    status: 'completed',
    currentStep: 0,          // ← 改为 0（chat mode），而非 6
    phases: detail.phases || [],
    progress: detail.progress || 100,
    previewUrl: detail.preview_url || null,
    downloadUrl: detail.download_url || null,
    result: detail.result || null,
    agentMessages: detail.agent_messages || [],
    language: detail.language || 'zh',
    mode: detail.mode || 'chat',
    summary: detail.topic ? {
      topic: detail.topic,
      title: detail.title || detail.topic,
      output_type: detail.output_type || 'report',
      template: 'consulting',
      sections: [],
      parameters: {},
    } : undefined,
  });
} else if (status === 'running' || status === 'reporting') {
  // 运行中会话保留 currentStep: 6（研究进行中）
  const interrupted = detail.interrupted;
  useSessionStore.getState().syncActive({
    title: detail.title || detail.topic || 'Untitled',
    taskId: id,
    messages: msgs,
    status: interrupted ? 'paused' : 'running',
    currentStep: 6,           // ← 运行中保留 6
    phases: detail.phases || [],
    progress: detail.progress || 0,
    agentMessages: detail.agent_messages || [],
    interrupted: !!interrupted,
    language: detail.language || 'zh',
    mode: detail.mode || 'research',
  });
} else {
  // paused / analyzing / idle
  useSessionStore.getState().syncActive({
    title: detail.title || detail.topic || 'Untitled',
    taskId: id,
    messages: msgs,
    status: 'idle',
    currentStep: 0,           // ← 已是 0，保持不变
    phases: detail.phases || [],
    progress: detail.progress || 0,
    agentMessages: detail.agent_messages || [],
    previewUrl: detail.preview_url || null,
    result: detail.result || null,
    language: detail.language || 'zh',
    mode: detail.mode || 'chat',
  });
}
```

**影响范围**: 从历史记录恢复会话、页面刷新后恢复会话。

**风险**: 低 — 已完成会话的 `currentStep: 6` 没有实际 UI 用途。研究完成状态由 `status: 'completed'` 驱动。

### Fix C: `SessionTabs` 切换前不同步 `currentStep` [P2]

**文件**: `web/src/components/chat/SessionTabs.tsx:48-51`

**原理**: 切换 tab 前同步当前会话状态到 cache 是合理的，但 `currentStep` 是瞬态 UI 状态，同步它会导致陈旧值被保留。改为仅同步持久化有意义的状态。

```typescript
// 修改前
syncActive({
  status,
  currentStep,
  messages: useChatStore.getState().messages,
});

// 修改后
syncActive({
  status,
  // currentStep 不同步 — 研究向导瞬态 UI 状态，由 setStep 在研究流程中管理
  messages: useChatStore.getState().messages,
});
```

**注意**: 如果 Fix A 已实施，此 Fix 变为防御性措施（belt-and-suspenders），因为即使 cache 中有陈旧 `currentStep`，`stateFromCache` 也会根据 `status` 校正。但仍然建议实施，避免写入无意义的陈旧数据。

### Fix D: `emptyCache()` 默认 `currentStep: null` [P2]

**文件**: `web/src/store/useSessionStore.ts:181`

**原理**: 新会话的 `currentStep` 应为 `null`（表示"未进入任何步骤"），而非 `0`（表示"在 chat mode 的 step 0"）。虽然 `isChatMode` 对 `null` 和 `0` 都返回 `true`，语义上 `null` 更准确。

```typescript
// 修改前
currentStep: 0,

// 修改后
currentStep: null,
```

**风险**: 极低 — `null` 和 `0` 在 `isChatMode` 判断中行为一致。

### Fix E: `useResearchStore` 订阅中为会话切换增加 `currentStep` 校正 [防御性]

**文件**: `web/src/store/useResearchStore.ts:136-137`

**原理**: 即使 Fix A 在 `stateFromCache` 中做了校正，在订阅的会话切换分支中再次确认是防御性编程。

```typescript
if (current.sessionId !== next.sessionId) {
  // 会话切换：全量恢复，但校正 currentStep
  if (next.status !== 'running' && next.status !== 'paused') {
    next.currentStep = null;
    next.stepOptions = null;
    next.parameterConfig = null;
  }
  set(next);
}
```

**注意**: 如果 Fix A 已实施，此 Fix 是冗余的。但作为 defense-in-depth，建议保留。

---

## 5. 修复优先级与依赖关系

```
Fix A (stateFromCache 校正) ← 核心修复，解决根因 A + B
  ↑
Fix B (restoreSession currentStep: 0) ← 解决根因 A 的源头
  ↑
Fix C (SessionTabs 不同步 currentStep) ← 防御性，减少陈旧数据写入
Fix D (emptyCache currentStep: null) ← 语义修正，极低风险
Fix E (订阅校正) ← defense-in-depth，与 Fix A 冗余
```

**建议实施顺序**: Fix A → Fix B → Fix C → Fix D → Fix E

Fix A 和 Fix B 是必须的，Fix C/D/E 是防御性加固。

---

## 6. 测试要点

### 6.1 核心场景

| 场景 | 预期结果 | 验证点 |
|------|---------|--------|
| Chat 模式提问触发搜索 | 搜索完成后正常显示回复 + suggestions | `currentStep` 保持 0/null，无 "Select Template" |
| 从历史恢复已完成会话 | 显示聊天记录 + 研究结果，无 "Select Template" | `currentStep` 为 0/null |
| 页面刷新后恢复 | 恢复正确的 UI 状态 | `currentStep` 根据 `status` 校正 |
| 研究向导 step 2 时刷新页面 | 回到 chat mode，不显示 "Select Template" | `currentStep` 被重置为 null |
| 多 tab 切换 | 切换回的会话不显示陈旧 "Select Template" | cache 中 `currentStep` 不含陈旧值 |
| 运行中研究刷新页面 | 恢复研究进度 UI | `currentStep: 6` 被保留（`status: running`） |

### 6.2 回归测试

- [ ] 正常研究流程 (step 1→2→3→4→5→6) 不受影响
- [ ] 框架确认模式正常工作
- [ ] 研究执行中的 agent_message 正常显示
- [ ] 暂停/取消/恢复功能正常
- [ ] 研究完成后 `currentStep` 被重置
- [ ] `useProgress` 中 `setStatus('completed')` 不覆盖 `currentStep`（Fix 3 回归）

### 6.3 单元测试补充

在 `web/src/components/chat/__tests__/chat-async-search-state.test.ts` 中增加：

```typescript
// Fix A 测试
describe('Fix A: stateFromCache corrects currentStep by status', () => {
  it('idle session → currentStep forced to null', () => {
    const cache = { ...mockCache, status: 'idle', currentStep: 2 };
    const state = stateFromCache(cache);
    expect(state.currentStep).toBeNull();
    expect(state.stepOptions).toBeNull();
  });

  it('completed session → currentStep forced to null', () => {
    const cache = { ...mockCache, status: 'completed', currentStep: 6 };
    const state = stateFromCache(cache);
    expect(state.currentStep).toBeNull();
  });

  it('running session → currentStep preserved', () => {
    const cache = { ...mockCache, status: 'running', currentStep: 6 };
    const state = stateFromCache(cache);
    expect(state.currentStep).toBe(6);
  });

  it('paused session → currentStep preserved', () => {
    const cache = { ...mockCache, status: 'paused', currentStep: 6 };
    const state = stateFromCache(cache);
    expect(state.currentStep).toBe(6);
  });
});

// Fix B 测试
describe('Fix B: restoreSession sets currentStep: 0 for completed', () => {
  it('completed session gets currentStep: 0, not 6', async () => {
    // mock api.getResearchDetail to return completed session
    // verify syncActive is called with currentStep: 0
  });
});
```

---

## 7. 相关文件清单

| 文件 | 变更类型 | Fix |
|------|---------|-----|
| `web/src/store/useResearchStore.ts` | 修改 | A, E |
| `web/src/store/useSessionStore.ts` | 修改 | B, D |
| `web/src/components/chat/SessionTabs.tsx` | 修改 | C |
| `web/src/components/chat/__tests__/chat-async-search-state.test.ts` | 新增测试 | A, B |

---

## 8. 设计决策说明

### Q: 为什么不在 `renderStepContent` 中加 guard？

在渲染层加 `if (status !== 'running' && status !== 'paused') return null;` 可以抑制症状，但：
1. 根因（陈旧 `currentStep` 在 store 中）仍然存在
2. 其他依赖 `currentStep` 的逻辑可能受影响
3. 违反 "fix root cause, not symptom" 原则

### Q: 为什么 `completed` 状态下 `currentStep: 6` 没有意义？

`currentStep: 6` 表示"研究正在执行中"。研究完成后，UI 通过 `status: 'completed'` + `result` + `previewUrl` 显示结果，不需要 `currentStep: 6`。保留它只会导致误渲染 "Select Template"。

### Q: Fix A 和 Fix B 是否冗余？

部分冗余，但建议都实施：
- Fix A 是**通用防护**：无论 `currentStep` 从何处进入 cache（`restoreSession`、`SessionTabs` 同步、localStorage 恢复），`stateFromCache` 都会校正
- Fix B 是**源头修正**：避免 `restoreSession` 写入错误的 `currentStep: 6`，减少 cache 中的陈旧数据

两者结合实现 defense-in-depth。

---

## 9. 与 2026-07-03 修复文档的关系

| 维度 | 2026-07-03 文档 | 本文档 |
|------|----------------|--------|
| 关注点 | SSE 异步路径 vs 同步路径的行为不一致 | `currentStep` 持久化/恢复导致的陈旧状态 |
| Fix 3 | 订阅精细化（status 变化不覆盖 currentStep） | **补充**: 会话切换时也需校正 currentStep |
| 新发现 | 未覆盖 `restoreSession` 的 `currentStep: 6` 问题 | 根因 A: `restoreSession` 为 completed 会话设 `currentStep: 6` |
| 新发现 | 未覆盖 `stateFromCache` 的盲目恢复 | 根因 B: `stateFromCache` 不根据 status 校正 currentStep |
| 新发现 | SessionTabs 同步 currentStep 未被视为问题 | 根因 C: SessionTabs 切换前同步陈旧 currentStep |

本方案是 2026-07-03 文档的**补充和深化**，而非替代。之前实施的 Fix 1-6 仍然有效且必要。
