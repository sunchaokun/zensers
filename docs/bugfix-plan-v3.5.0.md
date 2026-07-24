# 修订方案 v3.5.0 — 消息顺序 / 框架确认 / Skill路由

> 日期: 2026-07-20
> 基于版本: v3.4.0（上一轮修复后）
> 审查状态: 已自审，修正方案B关键遗漏

---

## 〇、自审修正记录

### 审查发现1：方案B遗漏选中章节传递

**问题**：原方案B在 `_handle_chat_mode` 检测到"确认开始研究"后直接启动研究，但 `final_plan` 中的章节只能从 `context['framework']['sections']` 取**全部**章节，无法知道用户在 SectionSelector 中**选了哪些**章节。

**原因**：`handleFrameworkSectionConfirm` 只将选中章节名拼接成文本 `exampleText`，后端无法可靠解析。

**修正方案**：修改前端 `handleFrameworkSectionConfirm`，在 exampleText 中用结构化格式编码选中章节（JSON行），后端解析：

```
前端 exampleText: 确认开始研究，包含章节：市场规模、现状、竞争\n__SELECTED_SECTIONS__:["市场规模","现状","竞争"]
```

后端检测到 `__SELECTED_SECTIONS__:` 标记后解析 JSON 数组，取用户选中的章节而非全部。

### 审查发现2：方案B需处理 framework.sections_tree

**问题**：框架可能有 `sections_tree`（层级结构），方案B只处理了 flat 的 `sections`。

**修正**：优先使用 `sections_tree` 构建 `section_details`，与 `_enter_framework_mode` 中的逻辑保持一致。

---

## 一、问题总览

| # | 问题 | 严重度 | 根因 | 状态 |
|---|------|--------|------|------|
| Bug11 | 消息顺序错乱：用户消息出现在assistant回复之后 | P0 | `_handle_chat_mode` processing路径移除了手动append，但初始assistant消息（"好的，我帮你查"）仍通过HTTP返回给前端，未写入conversation_history；刷新后该消息丢失，导致前后消息顺序看起来错乱 | 待修 |
| Bug12 | 框架确认（Confirm Selection）多次点击无效 | P0 | `handleFrameworkSectionConfirm` 调用 `handleOptionSelect('confirm_start', exampleText)` → `clickSuggestion` → 后端 `_handle_user_message`，LLM收到"确认开始研究"但不知道框架细节，反复返回"I understand you'd like to adjust the framework" | 待修 |
| Bug13 | LLM重复回复"I understand you'd like to adjust the framework" | P0 | Bug12的直接表现：LLM收到"确认开始研究"但没有框架上下文，无法理解这是确认操作 | 待修 |
| Bug14 | `_chat_response` / `_framework_response` 中的手动append可能导致双写 | P1 | 这两个同步方法直接append到conversation_history，但如果同一条消息也通过SSE推送则双写。当前不会双写（它们不推送SSE），但架构脆弱 | 观察暂不修 |
| Bug15 | `tool_display_names` 只包含4个内置工具 | P2 | xueqiu/stock_data等新注册skill没有显示名，SSE推送的agent_message显示为"Agent (xueqiu)" | 待修 |

---

## 二、Bug11 详细分析与修复方案

### 根因

在 v3.4.0 修复中，我们移除了 `_handle_chat_mode` 第746-748行的手动 `conversation_history.append()`，以消除与 `_persist_event` 的双写。

但移除后产生了一个新问题：**processing 路径的初始 assistant 消息（"好的，我马上帮你查一下"）不再写入 conversation_history**。

流程：
1. 用户发消息 → `send_message` → `_handle_chat_mode`
2. `_llm_converse` 返回 `{status: 'processing', message: '好的，我马上帮你查一下'}`
3. HTTP 响应返回给前端 → 前端 `addMessage` 显示该消息 ✅
4. 但 `conversation_history` 中**没有**这条 assistant 消息 ❌
5. 后台 `_continue_tool_chain` 完成 → `push_chat_response` → `_persist_event` 写入**最终**assistant消息
6. 刷新页面 → `getResearchDetail` 返回 `conversation_history` → 初始 assistant 消息丢失
7. 用户看到：user消息 → 最终assistant消息，中间缺少了初始回复，顺序显得混乱

### 修复方案

在 `_handle_chat_mode` 的 processing 分支中，恢复初始 assistant 消息的写入，但**使用 `_persist_event` 而非手动 append**，确保写入路径统一：

```python
# research_api.py, _handle_chat_mode, processing 分支
if conv_result.get('status') == 'processing':
    # ... existing context updates ...
    session['research_context'] = context

    # 持久化初始 assistant 消息（用户可见的"好的，我帮你查"）
    # 使用 SessionStreamer._persist_event 统一写入路径，避免双写
    msg = conv_result.get('message', '')
    if msg and SessionStreamer:
        SessionStreamer._persist_event(session_id, 'chat_response', {
            'message': msg,
            'timestamp': datetime.now().isoformat(),
        })

    return {'session_id': session_id, ...}
```

**关键**：`_persist_event` 写入 `conversation_history` 并记录到 `recent_events`，但**不推送 SSE**（不调用 `put_nowait`），因为前端已经通过 HTTP 响应收到了这条消息。如果也推送 SSE，前端会收到两次（HTTP + SSE），导致重复。

但等等——`_persist_event` 本身不推送 SSE，它只写 `conversation_history` 和 `recent_events`。SSE 推送是在 `SessionStreamer.push_chat_response` 中做的。所以用 `_persist_event` 是安全的。

**更优方案**：不调用 `_persist_event`（它是内部方法），而是直接 append 到 `conversation_history`，因为 processing 路径的初始消息**不会**通过 SSE 推送，所以不会与 `_persist_event` 双写。双写只发生在：同一条消息既手动 append 又通过 `_persist_event` 写入。但 processing 路径的初始消息（"好的，我帮你查"）和最终消息（搜索结果）是**不同**的消息，不会双写。

```python
if conv_result.get('status') == 'processing':
    # ... context updates ...
    session['research_context'] = context
    # 持久化初始 assistant 消息（仅写入 conversation_history，不推送 SSE）
    # 后台工具链完成后 push_chat_response 会写入最终回复，这是不同的消息，不会双写
    msg = conv_result.get('message', '')
    if msg:
        history = session.get('conversation_history', [])
        history.append({'role': 'assistant', 'content': msg, 'timestamp': datetime.now().isoformat()})
        session['conversation_history'] = history
    return {...}
```

**与之前删除的代码完全一致，但这次我们确认它不会导致双写**：
- 初始消息（processing）→ 手动 append → conversation_history
- 最终消息（tool chain 完成）→ `push_chat_response` → `_persist_event` → conversation_history
- 这两条是**不同**的消息，不会重复

### 之前的分析错误

之前我们认为 `_continue_tool_chain_body` 中的手动 append 和 `_persist_event` 会双写同一条消息，所以删除了。但实际上：

1. `_handle_chat_mode` processing 路径的手动 append → 写入的是**初始**消息
2. `_continue_tool_chain_body` 的手动 append → 写入的是**最终**消息
3. `_persist_event` → 也写入**最终**消息

所以**第2和第3才是双写**（同一条最终消息写了两次），而**第1不是双写**（不同的消息）。

我们正确删除了第2处（`_continue_tool_chain_body` 中的手动 append），但**错误地也删除了第1处**（`_handle_chat_mode` 中的手动 append）。

---

## 三、Bug12/13 详细分析与修复方案

### 根因

`handleFrameworkSectionConfirm` 的流程：

```
用户点击 Confirm Selection
→ handleFrameworkSectionConfirm(selectedIds)
→ handleOptionSelect('confirm_start', exampleText)
→ clickSuggestion(sessionId, 'confirm_start', '确认开始研究，包含章节：...')
→ POST /api/v1/research/interact {step:0, response:{suggestion_id:'confirm_start', text:'确认开始研究...'}}
→ _handle_user_message(session_id, '确认开始研究，包含章节：...')
→ _handle_chat_mode
→ _llm_converse  ← LLM收到消息但没有框架上下文！
```

**核心问题**：`_llm_converse` 收到的只是用户文本"确认开始研究"，**没有框架数据**（哪些章节被选中、框架结构等）。LLM 不知道用户已经确认了框架，以为用户在请求调整框架，所以反复返回 "I understand you'd like to adjust the framework"。

### 修复方案

在 `_handle_user_message` 或 `_handle_chat_mode` 中，检测到 `suggestion_id='confirm_start'` 时，直接进入研究执行流程，而不是再走 LLM 对话：

**方案 A（推荐）：前端直接调用 confirmResearch**

修改 `handleFrameworkSectionConfirm`，不走 `clickSuggestion`，而是：
1. 调用后端 API 设置 selected_sections
2. 调用 `confirmResearch(true)` 启动研究

```typescript
// ChatPanel.tsx
const handleFrameworkSectionConfirm = async (selectedIds: string[]) => {
  if (!framework || !sessionId) return;
  const sectionMap = new Map(framework.sections.map((s, i) => [`section-${i}`, s]));
  const selectedLabels = selectedIds
    .map(id => sectionMap.get(id))
    .filter((label): label is string => label !== undefined);
  if (selectedLabels.length === 0) return;

  try {
    // 1. 通过 interact API 设置框架章节，跳过参数步骤
    await api.selectSections(sessionId, selectedIds);

    // 2. 直接确认启动研究
    const data = await api.confirmResearch(sessionId, true);
    if (data.step === 6 && data.status === 'running') {
      setTaskId(data.session_id);
      setStatus('running');
    }
    setStep(data.step, undefined);
    if (data.message) {
      addMessage({ id: nanoid(), role: 'assistant', content: data.message, timestamp: new Date().toISOString() });
    }
    // 清除框架状态
    setFrameworkAction(null);
  } catch (error) {
    console.error('Failed to confirm framework:', error);
  }
};
```

**但** `api.selectSections` 调用的是 `interact(step=3)`，而后端 step 流程需要 session 在 step 3 状态。聊天模式下的 session 可能不在 step 3。

**方案 B（更简单）：后端识别 confirm_start 意图，直接启动研究**

在 `_handle_chat_mode` 中，检测到用户消息包含"确认开始研究"且 `research_context` 中有框架时，跳过 LLM 对话，直接启动研究：

```python
# research_api.py, _handle_chat_mode 开头
context = session.get('research_context', {})
framework = context.get('framework')

# 检测框架确认意图
if framework and ('确认开始研究' in user_input or 'confirm_start' in user_input.lower() or 'confirm and start research' in user_input.lower()):
    # 直接启动研究，不再走 LLM 对话
    sections = [s for s in framework.get('sections', []) if s]  # 所有章节
    if framework.get('sections_tree'):
        # 用户可能选择了子集，但简化处理：用所有章节
        pass
    session['selected_sections'] = sections
    session['final_plan'] = {
        'topic': context.get('topic', ''),
        'output_type': 'industry_report',
        'aspects': sections,
    }
    from src.api.research_executor import get_executor
    executor = get_executor()
    safe_create_task(executor.execute(session_id, session['final_plan'], session_manager), name=f"exec_confirm_{session_id}")
    return {'session_id': session_id, 'task_id': session_id, 'step': 6, 'mode': 'research', 'status': 'running', 'message': '研究任务已启动', 'next_step': 'execute'}
```

**方案 C（最优雅）：新增专用API端点**

前端框架确认不走 `clickSuggestion`，而是调用新的 `/api/v1/research/{session_id}/confirm-framework` API，后端直接启动研究。

### 推荐方案

**方案 B** — 最小改动，不需要新增 API，不需要修改前端架构。在 `_handle_chat_mode` 开头添加意图检测，当检测到框架确认意图时直接启动研究。

---

## 四、Bug15 详细分析与修复方案

### 根因

`_llm_converse` 和 `_continue_tool_chain_body` 中 `tool_display_names` 只有4个内置工具：

```python
tool_display_names = {'web_search': 'Web Search Agent', 'news_search': 'News Search Agent',
                      'scrape_url': 'Content Scraper Agent', 'get_current_datetime': 'Date/Time Agent'}
```

### 修复

扩展 `tool_display_names`，为所有动态注册的 skill 提供显示名：

```python
tool_display_names = {
    'web_search': 'Web Search Agent',
    'news_search': 'News Search Agent',
    'scrape_url': 'Content Scraper Agent',
    'get_current_datetime': 'Date/Time Agent',
    'xueqiu': 'Xueqiu Stock Data',
    'stock_data': 'Stock Financial Data',
    'annual_report_parser': 'Annual Report Parser',
}
```

或更灵活：从 `ConversationToolSet.TOOL_DEFINITIONS` 的 description 字段提取。

---

## 五、LLM连接失败问题（已修复）

### 根因

`data/llm_profiles.json` 中 DeepSeek 的 `base_url` 有前导空格：`" https://api.deepseek.com"`

### 已完成修复

1. 修正 `llm_profiles.json` 中的 base_url
2. 在 `llm_client.py` 和 `settings.py` 中添加 `.strip()` 防御

---

## 六、实施计划

### Phase 1：关键修复（P0）

| 步骤 | 文件 | 修改 |
|------|------|------|
| 1 | `src/api/research_api.py` | Bug11: 恢复 `_handle_chat_mode` processing 分支的 assistant 消息写入 conversation_history |
| 2 | `src/api/research_api.py` | Bug12/13: 在 `_handle_chat_mode` 开头添加框架确认意图检测，直接启动研究 |
| 3 | `src/api/research_api.py` | Bug15: 扩展 `tool_display_names` 包含动态注册 skill |

### Phase 2：验证

| 步骤 | 描述 |
|------|------|
| 4 | Python 语法检查 |
| 5 | 前端 96 测试 |
| 6 | 端到端功能测试（重启服务后） |

---

## 七、代码变更预览

### 变更1：Bug11 - 恢复 processing 路径 assistant 消息写入

**文件**: `src/api/research_api.py`
**位置**: `_handle_chat_mode`, processing 分支（约第755行）

```python
# 当前代码（Bug11 - 缺少初始assistant消息写入）
session['research_context'] = context
return {'session_id': session_id, ...}

# 修改后
session['research_context'] = context
msg = conv_result.get('message', '')
if msg:
    history = session.get('conversation_history', [])
    history.append({'role': 'assistant', 'content': msg, 'timestamp': datetime.now().isoformat()})
    session['conversation_history'] = history
return {'session_id': session_id, ...}
```

### 变更2：Bug12/13 - 框架确认意图检测

**文件**: `src/api/research_api.py`
**位置**: `_handle_chat_mode` 开头（约第700行后，background task guard之后）

```python
# 在 _handle_chat_mode 中，skip_lang_detect 之后、_llm_converse 之前添加：
context = session.get('research_context', {})
framework = context.get('framework')
_confirm_keywords = ('确认开始研究', '确认框架', '开始研究', 'confirm and start research', 'confirm_start')
if framework and any(kw in user_input.lower() for kw in _confirm_keywords):
    # 解析用户选中的章节（前端通过 __SELECTED_SECTIONS__ 标记传递）
    import json as _json
    selected_sections = None
    marker = '__SELECTED_SECTIONS__:'
    if marker in user_input:
        try:
            json_part = user_input[user_input.index(marker) + len(marker):]
            selected_sections = _json.loads(json_part)
        except Exception:
            selected_sections = None

    # 构建章节详情
    section_details = []
    if framework.get('sections_tree'):
        for node in framework['sections_tree']:
            node_name = node.get('name', '')
            if selected_sections and node_name not in selected_sections:
                continue
            section_details.append({
                'id': node_name, 'name': node_name,
                'points': node.get('points', []),
            })
            for sub in node.get('sub_sections', []):
                sub_name = sub.get('name', '')
                section_details.append({
                    'id': sub_name, 'name': sub_name,
                    'points': sub.get('points', []),
                })
    else:
        all_sections = framework.get('sections', [])
        target = selected_sections if selected_sections else all_sections
        section_details = [{'id': s, 'name': s} for s in target]

    final_plan = {
        'topic': context.get('topic', session.get('user_input', '')),
        'output_type': framework.get('output_type', 'industry_report'),
        'aspects': [s['name'] for s in section_details] if section_details else framework.get('sections', []),
        'section_details': section_details,
    }
    session['final_plan'] = final_plan
    conv_machine.force_set_state(ConversationState.EXECUTING)
    from src.api.research_executor import get_executor
    executor = get_executor()
    safe_create_task(executor.execute(session_id, final_plan, session_manager), name=f"exec_confirm_{session_id}")
    # 写入确认消息到 conversation_history
    history = session.get('conversation_history', [])
    history.append({'role': 'assistant', 'content': '研究任务已启动，正在按框架执行...', 'timestamp': datetime.now().isoformat()})
    session['conversation_history'] = history
    return {'session_id': session_id, 'task_id': session_id, 'step': 6, 'mode': 'research', 'status': 'running', 'message': '研究任务已启动，正在按框架执行...', 'next_step': 'execute'}
```

**前端配合修改**：

**文件**: `web/src/components/chat/ChatPanel.tsx`
**位置**: `handleFrameworkSectionConfirm`（约第711行）

```typescript
const handleFrameworkSectionConfirm = async (selectedIds: string[]) => {
  if (!framework) return;
  const sectionMap = new Map(framework.sections.map((s, i) => [`section-${i}`, s]));
  const selectedLabels = selectedIds
    .map(id => sectionMap.get(id))
    .filter((label): label is string => label !== undefined);
  if (selectedLabels.length === 0) return;
  const isZh = /[\u4e00-\u9fff]/.test(framework.topic);
  // 编码选中章节为结构化标记，后端可解析
  const sectionsJson = JSON.stringify(selectedLabels);
  const exampleText = isZh
    ? `确认开始研究，包含章节：${selectedLabels.join('、')}\n__SELECTED_SECTIONS__:${sectionsJson}`
    : `Confirm and start research with sections: ${selectedLabels.join(', ')}\n__SELECTED_SECTIONS__:${sectionsJson}`;
  try { await handleOptionSelect('confirm_start', exampleText); } catch (error) { console.error('Failed to confirm framework:', error); }
};
```

### 变更3：Bug15 - 扩展 tool_display_names

**文件**: `src/api/research_api.py`
**位置**: `_llm_converse` 和 `_continue_tool_chain_body` 中的 `tool_display_names`

```python
# 当前代码
tool_display_names = {'web_search': 'Web Search Agent', 'news_search': 'News Search Agent',
                      'scrape_url': 'Content Scraper Agent', 'get_current_datetime': 'Date/Time Agent'}

# 修改后
tool_display_names = {'web_search': 'Web Search Agent', 'news_search': 'News Search Agent',
                      'scrape_url': 'Content Scraper Agent', 'get_current_datetime': 'Date/Time Agent',
                      'xueqiu': 'Xueqiu Stock Data', 'stock_data': 'Stock Financial Data',
                      'annual_report_parser': 'Annual Report Parser'}
```

---

## 八、风险分析

| 风险 | 影响 | 缓解 |
|------|------|------|
| Bug11修复后恢复手动append，可能与_persist_event双写 | 低：初始消息和最终消息是不同的消息，不会双写 | 添加注释说明原因 |
| Bug12框架确认检测关键词不完整 | 中：用户可能用其他措辞确认 | 关键词列表可扩展；且fallback到LLM处理也不会崩溃（LLM会走enter_framework） |
| Bug12 `__SELECTED_SECTIONS__` 标记被LLM看到 | 低：LLM可能困惑 | 标记放在文本末尾，LLM主要关注前面的自然语言部分 |
| Bug12直接启动研究跳过参数设置 | 低：用户已在SectionSelector中选择了章节，参数用框架默认值 | 框架中已有 region/time_range 等默认值 |
| Bug12 `conv_machine.force_set_state(EXECUTING)` 可能与现有状态冲突 | 中：如果状态机不在 FRAMEWORK_CONFIRM 状态 | force_set_state 是强制转换，不检查前置条件；需确认这是安全的 |
| Bug15新skill显示名不够友好 | 低：显示为"Xueqiu Stock Data"比"Agent (xueqiu)"好 | 后续可从manifest自动提取 |

---

## 九、已完成的修复（v3.4.0 → v3.5.0 前置）

| 修复 | 描述 | 文件 |
|------|------|------|
| Bug7 | `_continue_tool_chain_body` 中的手动append与`_persist_event`双写 | research_api.py |
| Bug8 | `ConversationToolSet` 从SkillRegistry自动注册skill | research_api.py |
| Bug9 | `_handle_chat_mode` processing分支的手动append（**错误删除，需恢复**） | research_api.py |
| Bug10 | LLM工具选择优先级引导 | research_api.py |
| LLM连接 | base_url前导空格 + strip防御 | llm_profiles.json, llm_client.py, settings.py |
