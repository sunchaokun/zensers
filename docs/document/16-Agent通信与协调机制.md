# 16 — Agent 通信与协调机制

> 章节定位：理解 Agent 之间如何传递数据、如何同步状态、如何协同完成研究任务——从底层通信原语到上层协调模式的全链路设计。

---

## 1. 概述

Zensers 中 Agent 不是孤立的执行单元——一个研究任务通常需要多个 Agent 按阶段、分批次协同完成。系统设计了**四层通信机制**和**四级协调架构**：

```
通信层（数据/事件如何流动）           协调层（谁控制执行流程）
┌──────────────────────┐            ┌──────────────────────┐
│  MessageBus          │            │  ResearchOrchestrator │
│  事件发布/订阅        │            │  阶段编排（宏观）     │
├──────────────────────┤            ├──────────────────────┤
│  SharedMemory        │            │  ExecutionEngine     │
│  共享状态 + 规范化数据 │           │  批次调度+控制（中观）│
├──────────────────────┤            ├──────────────────────┤
│  ResultCollector     │            │  AgentCoordinator    │
│  事件驱动结果收集     │            │  任务分发/监控（微观）│
├──────────────────────┤            ├──────────────────────┤
│  SessionStreamer     │            │  [Agent 自协调]      │
│  前端实时推送         │            │  直接调用/SharedMemory│
└──────────────────────┘            └──────────────────────┘
```

**核心原则**：
- **数据与事件分离**：MessageBus 只做通知，实际数据走 SharedMemory
- **来源优先级驱动**：结构化数据 > 搜索结果 > LLM 推理，低优先级不能覆盖高优先级
- **编排器不执行**：Orchestrator 只编排不执行，Agent 只执行不编排
- **事件驱动结果收集**：Master 通过 ResultCollector 异步等待子 Agent 完成

---

## 2. 通信机制

### 2.1 MessageBus（事件总线）

**文件**: `src/core/communication.py:35`（112 行）

异步发布/订阅模式，所有 Agent 共享同一个 MessageBus 实例：

```python
# 核心 API
class MessageBus:
    async def subscribe(topic, handler)        # 订阅事件频道
    async def unsubscribe(topic, handler)      # 取消订阅
    async def publish(topic, event)            # 发布事件
```

#### 频道规划

| 频道 | 发布者 | 订阅者 | 用途 |
|------|--------|--------|------|
| `data.canonical.updated` | SharedMemory | DataCollector | 规范化数据更新通知 |
| `data.conflict.detected` | SharedMemory | DataCollector | 数据冲突告警 |
| `data.search.completed` | 搜索 Agent | 分析 Agent | 搜索任务完成 |
| `data.analysis.ready` | 分析 Agent | Orchestrator | 分析结果就绪 |
| `session.{parent_id}.agent.completed` | Agent 执行体 | ResultCollector | Agent 完成通知 |
| `session.{parent_id}.agent.progress` | Agent 执行体 | ResultCollector | 进度更新 |
| `session.{parent_id}.agent.failed` | Agent 执行体 | ResultCollector | 失败通知 |
| `agent.progress` | Agent | AgentCoordinator | 集中进度追踪 |
| `agent.heartbeat` | Agent | AgentCoordinator | 存活监控 |

#### 事件格式

```python
@dataclass
class Event:
    type: str              # 事件类型
    data: Any              # 事件数据
    source: Optional[str]  # 发布者标识
    timestamp: float       # 时间戳（自动设置）
```

#### 设计要点

- **异步分发**：publish() 使用 `asyncio.gather` 并发调用所有 handler
- **线程安全**：`asyncio.Lock` 保护订阅者列表
- **Topic 隔离**：不同频道互不干扰
- **轻量通知**：MessageBus 不存储数据、不保证持久化——纯粹的事件通知通道

---

### 2.2 SharedMemory（共享状态存储）

**文件**: `src/core/communication.py:126`（240 行）

跨 Agent 数据共享的键值存储，支持两级访问模式。

#### 通用层

```python
async write(key, value)    # 写入任意数据
async read(key) → value    # 读取
async delete(key) → bool   # 删除
async keys() → List[str]   # 获取所有键
```

线程安全（`asyncio.Lock`），适用于：注入上下文、传递临时状态。

#### 规范化数据层（核心机制）

```python
async write_canonical(metric, value, caliber, source, publisher)
    → Optional[ConflictRecord]

get_canonical_sync(metric) → Optional[Dict]   # 同步读取（无锁）
get_all_canonical() → Dict[str, Dict]         # 获取全部规范化数据
```

**写入流程**：

```
write_canonical("revenue", 100亿, "structured_source", "wind")
    │
    ├─ 1. 冲突检测
    │     如果已存在同 key 值，比较偏差：
    │       |existing - new| / max(|new|, 0.01) > 5% → 标记冲突
    │
    ├─ 2. 优先级比较
    │     来源优先级表：
    │       structured_source(100) > search_result(50)
    │       > llm_inference_factual(15) > llm_inference(10)
    │       > llm_inference_speculative(5)
    │     低优先级来源不能覆盖高优先级值
    │     同 caliber 同 source → 静默跳过（幂等）
    │     同 caliber 不同 source → 标记冲突，保留原值
    │
    ├─ 3. 写入（仅当优先级更高或新 key）
    │     key = f"canonical:{metric}"
    │     value = {value, caliber, source, publisher, version, timestamp}
    │
    └─ 4. 自动发布到 MessageBus
         无冲突 → data.canonical.updated
         有冲突 → data.conflict.detected
```

**规范化数据的作用**：
- 采集 Agent 写入市场数据 → 分析 Agent 直接读取
- 多个来源冲突时，自动保留高优先级数据
- 版本号递增，可追踪数据变更历史

#### 同步访问层（性能路径）

```python
get(key, default)       # 无锁同步读取（性能关键路径用）
set(key, value)         # 无锁同步写入
get_all() → Dict        # 获取全部数据快照
```

用于：提示词构建时读取规范化数据、批量数据注入。

---

### 2.3 ResultCollector（事件驱动结果收集器）

**文件**: `src/core/agents/result_collector.py:29`（406 行）

Master Agent 通过 ResultCollector 异步收集子 Agent 的执行结果，基于 MessageBus 的事件驱动模式。

#### 核心 API

```python
class ResultCollector:
    async setup()                                 # 订阅完成/进度/失败事件
    async wait_for_agent(session_id, timeout?)    # 等待单个 Agent
    async wait_for_all(session_ids, timeout?)     # 等待全部（并发等待）
    async wait_for_any(session_ids, timeout?)     # 等待任意一个先完成
    close()                                       # 取消订阅、清理资源
```

订阅的频道（按 parent_session_id 隔离）：
- `session.{parent_id}.agent.completed` — 处理完成事件，存储结果，触发 asyncio.Event
- `session.{parent_id}.agent.progress` — 更新进度，调用已注册的 progress handler
- `session.{parent_id}.agent.failed` — 记录失败信息，同样触发完成 Event（失败也算完成）

#### 内部机制

```python
_results: Dict[str, Dict]                     # session_id → 结果
_completion_events: Dict[str, asyncio.Event]  # session_id → 等待事件
_progress_handlers: Dict[str, Callable]       # session_id → 进度回调
```

- 每个 Agent session 对应一个 `asyncio.Event`
- `wait_for_agent` → await event.wait() → 拿到结果后返回
- `wait_for_all` → `asyncio.gather` 并发等所有 Event
- `wait_for_any` → `asyncio.wait(FIRST_COMPLETED)` → 拿到第一个完成的

#### 使用模式

```python
# Master Agent 中
collector = ResultCollector(
    parent_session_id="research_001",
    message_bus=message_bus,
    shared_memory=shared_memory,
)
await collector.setup()

# 分发任务到子 Agent 后
results = await collector.wait_for_all(
    ["agent_001", "agent_002", "agent_003"],
    timeout=60.0
)

# 检查结果
if collector.count_failed() > 0:
    # 处理失败
await collector.close()
```

---

### 2.4 SessionStreamer（前端实时推送）

见 [`15-会话持久流.md`](15-会话持久流.md)。简要来说，Agent 的执行进度通过 10 种 SSE 事件类型实时推送前端，11 个模块共 85 处调用点。

---

### 2.5 Direct Call（直接调用）

同步方法调用，适用于明确的父子 Agent 关系：

```python
result = await sub_agent.execute(task_data)
```

优点：简单直接、类型安全。缺点：调用方必须等待返回，不适合长时间任务。

---

## 3. 协调架构

### 3.1 四级协调体系

```
Level 1: ResearchOrchestrator（宏观—阶段编排）
          编排阶段序列，不直接执行
              │
Level 2: ExecutionEngine（中观—批次调度）
          将 Agent 分类、分批、调度执行
          组合控制机制：ConcurrencyManager + RetryManager
          + TimeoutController + BackgroundExecutor
              │
Level 3: AgentCoordinator（微观—任务管理）
          任务分发 + 进度追踪 + 心跳监控
          + 超时处理 + 取消管理
              │
Level 4: Agent 自协调（对等—数据驱动）
          通过 SharedMemory 直接读写数据
          MessageBus 事件通知
```

---

### 3.2 ResearchOrchestrator（阶段编排）

**文件**: `src/core/orchestrator/orchestrator.py:180`

宏观层面的阶段编排器，职责：

1. 接收执行计划（ExecutionPlan）
2. 按 PHASE_ORDER 依次启动阶段
3. 每个阶段交给 ExecutionEngine 执行
4. 阶段间传递上下文（SharedMemory 中的数据）

典型阶段序列：

```
Phase 1: 需求分析
  → 意图分析 → 任务分解 → 框架生成

Phase 2: 数据采集
  → ExecutionEngine 并行调度多个采集 Agent
  → 写入 SharedMemory

Phase 3: 深度分析
  → ExecutionEngine 读取 SharedMemory 数据
  → 分析 Agent 执行

Phase 4: 报告生成
  → 生成各章节 → 组装完整报告

Phase 5: 质量检查
  → 逐章节质量评估 → 自动修复 → 最终确认
```

编排器**不直接执行**任何分析任务——它只判断"什么时候该做什么"，具体执行交给 Engine → Agent。

---

### 3.3 ExecutionEngine（批次调度）

**文件**: `src/core/orchestrator/execution/engine.py:170`（3311 行）

中观层面的执行调度器，是系统中最复杂的协调组件。

#### 3.3.1 Agent 分类

Engine 使用多层策略对 Agent 自动分类（`classify_agent()`）：

| AgentCategory | 说明 | 示例 action |
|--------------|------|------------|
| DATA_COLLECTION | 数据采集 | search, fetch, scrape |
| ANALYSIS | 深度分析 | analyze, evaluate |
| SYNTHESIS | 综合提炼 | summary, conclusion |
| REPORT_GENERATION | 报告生成 | generate, write |
| QUALITY_CHECK | 质量检查 | check, validate |
| DOCUMENT_GENERATION | 文档导出 | docx, pptx, pdf |

分类优先级：显式配置 > capabilities 匹配 > 名称/描述关键词 > skills 匹配

#### 3.3.2 控制机制组合

```python
self.concurrency = ConcurrencyManager(max_concurrent=20)  # 并发控制
self.retry = RetryManager(max_retries=3)                   # 重试管理
self.timeout = TimeoutController(default_timeout=300)       # 超时控制
self.background = BackgroundExecutor(...)                   # 后台执行
self.validator = ResultValidator(...)                       # 结果验证
```

#### 3.3.3 批次执行流程

```
execute_with_scheduler(agents, requirement)
    │
    ├─ 1. Scheduler 生成执行批次
    │      schedule_from_decomposition(plan, agents)
    │      → List[List[agent_id]]  （依赖拓扑排序）
    │
    ├─ 2. 逐批次执行
    │      for batch_index, batch_agent_ids in enumerate(execution_batches):
    │          │
    │          ├─ 缓存检测：检查 aspect 是否已有缓存结果
    │          ├─ 内容锁检测：章节是否被锁定
    │          ├─ 并发执行：asyncio.gather 启动所有 Agent
    │          ├─ 质量控制：检查器验证批次结果
    │          └─ 失败重试：失败 Agent 重新执行（最多 3 次）
    │
    ├─ 3. 数据对账与补充
    │      对 DATA_COLLECTION 批次，检查是否缺少必要数据
    │      自动发起补充搜索
    │
    └─ 4. 结果聚合
        批量后处理 → MetricExtractor → CanonicalDataRegistry
        → SharedMemory.set("_canonical_registry", ...)
```

#### 3.3.4 批次间的数据传递

```
Batch N (采集 Agent):
  Agent A: write_canonical("revenue", "100亿", "search_result")
  Agent B: write_canonical("profit", "20亿", "search_result")
    │
    ▼
批次后处理:
  MetricExtractor 提取 data_points
  CanonicalDataRegistry 注册
  SharedMemory.set("_canonical_registry", canonical_data)
    │
    ▼
Batch N+1 (分析 Agent):
  get_all_canonical() → 读取前序批次全部规范化数据
  write_canonical("claim:competition", "...", "llm_inference")
```

#### 3.3.5 暂停/恢复/取消

```python
# CancelManager（全局单例）
class CancelManager:
    request_cancel(task_id)          # 请求取消
    is_cancelled(task_id) → bool     # Agent 检查点查询
    pause(task_id)                   # 暂停
    resume(task_id)                  # 恢复

# Agent 执行中的检查点
async def execute(self, ...):
    for step in steps:
        if self._cancel_manager.is_cancelled(self.task_id):
            return  # 优雅退出，完成当前步骤
        # ... 执行下一步
```

暂停/恢复使用 `asyncio.Condition` 实现——Agent 等待条件变量而非轮询，CPU 开销为零。

---

### 3.4 AgentCoordinator（任务协调器）

**文件**: `src/core/orchestrator/execution/coordinator/agent_coordinator.py:83`（860 行）

最细粒度的任务协调组件，管理单个 Agent 的完整生命周期。

#### 3.4.1 架构

```
AgentCoordinator
  ├── TaskDispatcher      ← 任务准备、校验、分发
  ├── ProgressTracker     ← 进度追踪与查询
  ├── HeartbeatMonitor    ← 心跳接收 + 超时回调
  └── CancelManager       ← 取消 + 暂停/恢复（全局单例）
```

**配置**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_concurrent | 20 | 最大并发任务数 |
| default_timeout | 300s | 默认超时 |
| max_retries | 3 | 最大重试次数 |
| heartbeat_interval | 5s | 心跳发送间隔 |
| heartbeat_timeout | 60s | 心跳超时判定 |
| progress_update_interval | 5s | 进度更新间隔 |

#### 3.4.2 任务分发流程

```
dispatch_task(agent, task, options)
    │
    ├─ 1. TaskDispatcher.prepare_task()
    │      校验任务合法性 → 生成 task_id → 记录分发统计
    │
    ├─ 2. ProgressTracker.start_tracking()
    │      注册进度跟踪 → 初始 status="dispatched"
    │
    ├─ 3. HeartbeatMonitor.start_tracking()
    │      开始心跳追踪 → 设置超时回调
    │
    └─ 4. _execute_with_monitoring()
           │
           ├─ 发送心跳 → 定期 receive_heartbeat
           ├─ 等待 Agent.execute() 完成
           ├─ 成功 → 发布 session.{id}.agent.completed
           ├─ 取消 → 发布 cancelled
           └─ 失败 → 记录失败 → 发布 session.{id}.agent.failed
```

#### 3.4.3 心跳与超时

```
Agent ——(每 3s 发心跳)——▶ HeartbeatMonitor
                              │
              如果 60s 未收到心跳
                              │
                              ▼
                    _handle_task_timeout(task_id)
                      → CancelManager.cancel(task_id)
                      → 取消异步任务
                      → 标记 Agent 失败
```

心跳间隔为超时时间的 60%（默认 5s × 60% = 3s），确保在超时前有足够的心跳窗口。

#### 3.4.4 结果收集

`wait_for_completion(task_ids, timeout?)` 等待任务全部完成：

```python
async def wait_one(task_id):
    while task_id in self._active_tasks:
        task = self._active_tasks[task_id]
        if task.status in ("completed", "failed", "cancelled"):
            return task_id, task.result
        await asyncio.sleep(0.1)  # 轮询等待
    return task_id, None
```

---

### 3.5 子组件详解

#### TaskDispatcher

**文件**: `coordinator/task_dispatcher.py:87`

| 方法 | 职责 |
|------|------|
| `prepare_task(task, agent, options)` | 校验任务、生成 task_id、绑定 Agent |
| `record_dispatch(task_id)` | 记录分发统计 |
| `get_dispatch_count()` | 获取分发总数 |

#### ProgressTracker

**文件**: `coordinator/progress_tracker.py:62`

```python
start_tracking(task_id, status)     # 开始追踪
update(task_id, progress, status)   # 更新进度
fail(task_id, error)                # 标记失败
get_progress(task_id) → TaskProgress  # 查询进度
get_all_progress() → Dict           # 获取全部进度
```

每个 TaskProgress 包含：task_id、progress(0~1)、status、started_at、completed_at。

#### HeartbeatMonitor

**文件**: `coordinator/heartbeat_monitor.py:65`

```python
start_tracking(task_id, timeout_callback)  # 开始心跳追踪
receive_heartbeat(task_id)                  # 接收心跳
stop_tracking(task_id)                      # 停止追踪
get_lag(task_id) → float                    # 获取心跳延迟
is_alive(task_id) → bool                    # 检查是否存活
```

内部维护 `_heartbeats: Dict[str, float]`（task_id → 最后心跳时间戳），后台协程定期检查超时。

---

## 4. 完整协作流程

### 4.1 研究任务的端到端流程

```
用户输入 "分析比亚迪2025财报"
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ ResearchAPI 接收请求                                         │
│ → 意图分析 (RESEARCH)                                       │
│ → 话题提取                                                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ IntelligentRoutingAdapter（三步路由流水线）                  │
│                                                             │
│ Step 1: SemanticIntentAnalyzer                               │
│   → DeepIntentResult{intent: RESEARCH, aspects: [...], ...}  │
│                                                             │
│ Step 2: TaskStructureAnalyzer                                │
│   → TaskStructure{sections: [财务, 业务, 估值]}              │
│                                                             │
│ Step 3: DynamicPhaseOrchestrator                             │
│   → ExecutionPlan{phases: [数据采集, 分析, 报告]}            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ ResearchOrchestrator                                         │
│ → Phase 1: 数据采集                                         │
│ → Phase 2: 深度分析                                         │
│ → Phase 3: 报告生成                                         │
│ → Phase 4: 质量检查                                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ ExecutionEngine 执行 Phase 1（数据采集）                     │
│                                                             │
│ 1. classify_agent() → 分类 Agent                            │
│ 2. Scheduler 生成批次                                        │
│    Batch 1: [Agent_A(利润表), Agent_B(资产负债表)]           │
│    Batch 2: [Agent_C(业务分析), Agent_D(行业对比)]          │
│                                                             │
│ 3. 执行 Batch 1（并行）                                      │
│    │                                                         │
│    ├─ AgentCoordinator.dispatch_task(Agent_A)               │
│    │   ├─ TaskDispatcher → 校验通过                         │
│    │   ├─ ProgressTracker → 开始追踪                        │
│    │   ├─ HeartbeatMonitor → 开始心跳监控                   │
│    │   └─ Agent_A.execute() → 搜索数据                      │
│    │       ├─ SessionStreamer → 前端展示进度                 │
│    │       └─ SharedMemory.write_canonical("revenue", ...)  │
│    │           └─ MessageBus → data.canonical.updated       │
│    │                                                         │
│    ├─ AgentCoordinator.dispatch_task(Agent_B) → 同上         │
│    │                                                         │
│    └─ ResultCollector.wait_for_all([A, B])                  │
│        ← 两个 Agent 完成                                     │
│                                                             │
│ 4. 批次后处理                                                │
│    ├─ MetricExtractor → 提取指标                             │
│    ├─ CanonicalDataRegistry → 注册                          │
│    └─ SharedMemory.set("_canonical_registry", ...)          │
│                                                             │
│ 5. 执行 Batch 2 → 同上                                       │
│                                                             │
│ 6. Phase 1 完成                                              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ ExecutionEngine 执行 Phase 2（深度分析 — 串行依赖采集完成）  │
│                                                             │
│ 分析 Agent 读取 SharedMemory.get_all_canonical()            │
│ → 基于规范化数据进行综合分析                                 │
│ → 写入分析结论                                              │
│ → 各 Agent 通过 SharedMemory 传递中间结果                    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ ExecutionEngine 执行 Phase 3-4（报告生成 + 质检）            │
│                                                             │
│ 报告生成 → 每完成一章 → SessionStreamer.push_section_quality│
│ 质量检查 → 全部完成 → SessionStreamer.push_quality_result   │
│ → 用户确认 → SessionStreamer.push_quality_confirmed         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
前端展示最终报告
```

### 4.2 通信时序（批次内部）

```
AgentCoordinator    Agent_A         ResultCollector    SharedMemory    MessageBus
    │                  │                │                  │              │
    │──dispatch_task─▶│                │                  │              │
    │                  │                │                  │              │
    │                  │──execute()───▶│                  │              │
    │                  │                │                  │              │
    │                  │──hb──────────▶│                  │              │ 心跳
    │                  │──hb──────────▶│                  │              │
    │                  │                │                  │              │
    │                  │────write_canonical(revenue)─────▶│              │
    │                  │                │                  │──publish───▶│
    │                  │                │                  │  canonical.updated
    │                  │                │◀──notify────────│              │
    │                  │                │                  │              │
    │                  │                │                  │              │
    │                  │──complete────▶│                  │              │
    │◀──event─────────│                │                  │              │
    │  completed       │                │                  │              │
    │                  │                │                  │              │
    │──wait_for_all──▶│                │                  │              │
    │◀──result────────│                │                  │              │
```

---

## 5. 协调模式总览

| 模式 | 实现者 | 适用场景 | 特点 |
|------|--------|---------|------|
| **阶段串行** | ResearchOrchestrator | 采集→分析→报告 | 阶段间有强依赖 |
| **批次并行** | ExecutionEngine + Scheduler | 同阶段多个维度 | 并发采集/分析 |
| **条件分支** | DynamicPhaseOrchestrator | 数据不足时补采 | 运行时决策 |
| **事件驱动收集** | ResultCollector | Master 等子 Agent | 异步非阻塞 |
| **任务监控** | AgentCoordinator | 心跳/超时/重试 | 自动化故障处理 |
| **数据驱动同步** | SharedMemory | 跨 Agent 数据传递 | 优先级冲突保护 |
| **直接调用** | 代码级 | 简单父子调用 | 类型安全，同步阻塞 |
| **双 SSE 流** | SessionStreamer + ProgressStreamer | 前端实时展示 | 任务级+会话级 |

---

## 6. 故障场景处理

| 场景 | 检测机制 | 处理方式 |
|------|---------|---------|
| Agent 崩溃 | HeartbeatMonitor 60s 超时 | 标记失败 → 触发 retry（最多 3 次） |
| 数据冲突 | SharedMemory 偏差 >5% 检测 | 保留高优先级值 → 发布冲突告警 |
| 结果无效 | ResultValidator | 触发重执行或降级 |
| 阶段间依赖断裂 | Orchestrator 阶段状态检查 | 跳过或触发补采 |
| 前端断连 | SessionStreamer 30s heartbeat | EventSource 自动重连 + 事件重放 |

---

> **溯源**：本章内容基于 `src/core/communication.py`（MessageBus 112 行 + SharedMemory 240 行）、`src/core/agents/result_collector.py`（406 行）、`src/core/orchestrator/execution/coordinator/agent_coordinator.py`（860 行）及子组件（TaskDispatcher、ProgressTracker、HeartbeatMonitor、CancelManager）、`src/core/orchestrator/execution/engine.py`（3311 行）、`src/core/orchestrator/orchestrator.py`。协调层涉及 6 个模块约 5200 行代码，通信层约 350 行。
