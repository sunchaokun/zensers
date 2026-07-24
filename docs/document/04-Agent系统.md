# 04 — Agent 系统

> 章节定位：理解系统的执行实体——固定 Agent 团队、动态 Agent 工厂、生命周期管理、通信机制。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                       Master Agent V2                            │
│                    (OrchestratorV2 - 只编排不执行)                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Fixed Agent Team (核心能力)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ 需求分析Agent │  │ 数据采集Agent │  │ 报告生成Agent │          │
│  │ 意图识别     │  │  Web搜索    │  │  章节生成    │          │
│  │ 实体提取     │  │  新闻搜索   │  │  内容整合    │          │
│  │ 框架推荐     │  │  网页抓取   │  │  Markdown   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │ 版式设计Agent │  │ 质量检查Agent │                              │
│  │ Word生成     │  │  完整度检查  │                              │
│  │ 样式应用     │  │  一致性检查  │                              │
│  │ 图表插入     │  │  质量评分    │                              │
│  └──────────────┘  └──────────────┘                              │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │文档生成Agent │  │ 跨章综合Agent│  │ 数据校准Agent │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │问卷分析Agent │  │ 问卷集成Agent│  │ 问卷优化Agent │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐                              │
│  │人设生成Agent │  │ 模拟应答Agent │                              │
│  └──────────────┘  └──────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (复杂任务)
┌─────────────────────────────────────────────────────────────────┐
│                    Dynamic Agent Factory                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  领域专家Agent  │  │  分析Agent      │  │  研究Agent      │  │
│  │  - 行业专家     │  │  - 竞争分析     │  │  - 技术研究     │  │
│  │  - 金融专家     │  │  - 财务分析     │  │  - 市场研究     │  │
│  │  - 政策专家     │  │  - 政策分析     │  │  - 用户研究     │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  特点：按需创建、任务完成后销毁或回收                               │
└─────────────────────────────────────────────────────────────────┘
```

## 2. 核心设计原则

### 原则 1：Master 不执行

编排器只负责调度和协调，不直接执行分析、生成等任务。优势：
- 降低编排器复杂度，避免逻辑膨胀
- 职责清晰，出现问题易定位
- 编排逻辑可独立测试

### 原则 2：固定 + 动态

| 类型 | 用途 | 生命周期 |
|------|------|----------|
| **固定 Agent** | 通用核心能力 | 长期存在，持续优化 |
| **动态 Agent** | 特定任务需求 | 按需创建，用完销毁 |

### 原则 3：单一职责

| Agent | 职责 | 不做什么 |
|-------|------|----------|
| RequirementAnalysisAgent | 分析需求 | 不采集数据、不生成报告 |
| DataCollectionAgent | 采集数据 | 不分析数据、不做判断 |
| ReportGenerationAgent | 生成内容 | 不排版、不检查质量 |
| LayoutDesignAgent | 排版设计 | 不生成内容 |
| QualityCheckAgent | 质量检查 | 不修改内容 |
| DocumentGenerationAgent | 文档输出 | 不生成内容逻辑 |
| CrossSynthesisAgent | 跨章综合 | 不采集原始数据 |
| ResultCalibrationAgent | 数据校准 | 不生成分析结论 |
| SurveyAnalysisAgent | 问卷分析 | 不做市场分析 |
| SurveyIntegrationAgent | 问卷集成 | 不做非问卷数据采集 |
| SurveyOptimizationAgent | 问卷优化 | 不修改问卷题目 |
| PersonaGenerationAgent | 人设生成 | 不执行问卷模拟 |
| SimulatedResponseAgent | 模拟应答 | 不创建问卷 |

## 3. 固定 Agent 团队

### 3.1 需求分析 Agent (RequirementAnalysisAgent)

```
输入: 用户原始文本 + 上下文
处理: 意图识别 → 实体提取 → 框架推荐 → 复杂度评估
输出: ResearchIntent + Entity[] + ResearchFramework
```

### 3.2 数据采集 Agent (DataCollectionAgent)

```
输入: 查询词 + 数据源列表 + 数量限制
处理: Web搜索 + 新闻搜索 + 数据清洗
输出: DataItem[] + Source[]
```

### 3.3 报告生成 Agent (ReportGenerationAgent)

```
输入: 章节配置 + 数据 + 风格
处理: 逐章生成 → 内容整合
输出: Section[] + Markdown
```

### 3.4 版式设计 Agent (LayoutDesignAgent)

```
输入: Markdown内容 + 模板 + 格式
处理: Markdown解析 → 模板应用 → 文件生成
输出: 文件路径 + 格式 + 页数
```

### 3.5 质量检查 Agent (QualityCheckAgent)

```
输入: 报告 + 需求列表
处理: 完整度→一致性→格式→评分
输出: 质量分 + Issue[] + 是否通过
```

### 3.6 文档生成 Agent (DocumentGenerationAgent)

```
输入: 最终内容 + 格式 + 模板
处理: Markdown→目标格式转换
输出: DOCX / PPTX / PDF 文件路径
```

### 3.7 跨章综合 Agent (CrossSynthesisAgent)

```
输入: 各章节结果
处理: 交叉引用、逻辑整合、矛盾消解
输出: 综合分析章节
```

### 3.8 数据校准 Agent (ResultCalibrationAgent)

```
输入: 采集数据 + 规范
处理: 数据验证、一致性校正
输出: 校准后数据
```

### 3.9~3.13 问卷相关 Agent

| Agent | 职责 |
|-------|------|
| SurveyAnalysisAgent | 问卷数据分析 |
| SurveyIntegrationAgent | 问卷数据集成到报告 |
| SurveyOptimizationAgent | 问卷题目优化 |
| PersonaGenerationAgent | 受访者人设生成 |
| SimulatedResponseAgent | 模拟受访者回答 |

## 4. 通用 Agent 技术原理（GenericAgent）

GenericAgent 是动态执行的核心（`src/core/agents/generic_agent.py`，6019 行），采用 Mixin 组合 + 多阶段路由实现两阶段研究流程。

### 4.1 类结构

```python
class GenericAgent(StateManagementMixin, CommunicationMixin):
    # Mixin 提供：异步状态管理 + MessageBus/SharedMemory 注入
    agent_type: str = "dynamic"
    _lifecycle_state: AgentLifecycleState = CREATED
    _available_skills: List[str]  # 由 config["skills"] 决定
    _role, _goal, _backstory: str  # 从 config 提取的角色设定
```

### 4.2 execute() 路由总览

```
GenericAgent.execute({action, parameters})
    │
    ├── action == "mcp" ──────▶ _execute_mcp(parameters)
    │
    ├── ACTION_TO_SKILL 映射 ──▶ skill_name = 查表(action)
    │   ┌───────────────────────────────────────────────┐
    │   │ action          → skill_name                  │
    │   │ search           → search_skill               │
    │   │ news_search      → news_search                │
    │   │ llm/analyze/...  → llm_skill                  │
    │   │ web_search       → lc_tavily_search           │
    │   │ arxiv_search     → lc_arxiv                   │
    │   │ generate_docx    → docx_skill                  │
    │   └───────────────────────────────────────────────┘
    │
    └── skill_name == "llm_skill" ──▶ 按 agent_category 分支
        │
        ├── DATA_COLLECTION 路径  (§5.3)
        ├── DATA_VALIDATION 路径  (§5.4)
        ├── DEEP_ANALYSIS 路径    (§5.5)
        └── 其他路径              (REPORT_GENERATION 等)
```

### 4.3 DATA_COLLECTION 路径（数据采集）

```
GenericAgent.execute → agent_category="research"
    │
    ├── ① 预加载数据检查
    │   ├── context.get("preloaded") → SharedMemory.get("annual_report_data")
    │   └── 可选法证模式：仅筛选与 hypothesis 相关的数据
    │
    ├── ② 分层技能执行（Tier 优先级）
    │   ├── Tier 1: structured_db（stock_data / xueqiu / wind / bloomberg）
    │   │   ├── 查询结构化数据源
    │   │   ├── write_canonical(metric, value, "structured_source")
    │   │   └── Tier 1 成功 → depth="basic"（减少搜索量）
    │   ├── Tier 2: web_search（search_skill）
    │   │   ├── Tier 1 无结果 → depth="deep"
    │   │   └── 迭代搜索：MAX_QUERIES × MAX_ITERATIONS
    │   └── Tier 3: news_search（补充新闻）
    │
    ├── ③ 规范化数据写入
    │   ├── 正则提取关键指标：净利润/营收/销量/研发投入/毛利率
    │   ├── write_canonical(metric, value, caliber, source, publisher)
    │   │   ├── 优先级检查：structured_source(100) > search_result(50)
    │   │   │                 > llm_inference_factual(15) > llm_inference(10)
    │   │   │                 > llm_inference_speculative(5)
    │   │   ├── 冲突 → 自动发布 data.conflict.detected 到 MessageBus
    │   │   └── 无冲突 → 自动发布 data.canonical.updated 到 MessageBus
    │   └── DataCollector 实时聚合所有 Agent 的规范化数据
    │
    └── ④ 返回 {success, data_points, sources, total_sources, quality_stats}
```

**迭代搜索深度配置**：

| 深度 | MAX_QUERIES | MAX_ITERATIONS | 适用场景 |
|------|------------|----------------|---------|
| basic | 10 | 5 | Tier 1 有数据 |
| deep | 50 | 20 | Tier 1 无数据 |

### 4.4 DATA_VALIDATION 路径（数据校准）

```
GenericAgent.execute → agent_category="quality-check"
    │
    ├── ① _validate_collected_data()
    │   └── 校验采集数据的完整性和一致性
    │
    ├── ② _resolve_numerical_conflicts()
    │   └── 自动消解数值冲突（同一指标不同来源）
    │
    └── ③ 定向补采（最多 1 轮）
        ├── _generate_recollection_queries() → 针对低质量区域生成补采查询
        └── 重新搜索 + 写入规范化数据
```

### 4.5 DEEP_ANALYSIS 路径（深度分析）

```
GenericAgent.execute → agent_category in ("market-analysis", "analysis", "financial-analysis")
    │
    ├── ① 数据回退：无上游数据 → 降级执行搜索
    │
    ├── ② 规范化数据注入
    │   ├── SharedMemory.get("_canonical_registry") → 前序批次的规范化数据
    │   ├── SharedMemory.get_all_canonical() → 跨维度 claim/hypothesis
    │   └── 按目标货币过滤
    │
    ├── ③ 认知类型推断：infer_cognitive_type()
    │   └── fact_driven / inference_driven / forward_looking / assessment_driven
    │
    ├── ④ 因果假设生成（L4）
    │   └── 基于认知策略生成可验证的因果假设
    │
    ├── ⑤ Prompt 构建
    │   ├── 系统提示：角色/目标/背景
    │   ├── 数据注入：文档上下文 + 规范化数据 + SharedMemory 实时数据
    │   └── 质量标准注入：quality_rubric.md
    │
    ├── ⑥ LLM 调用 → call_llm(prompt, system_prompt)
    │
    └── ⑦ 后处理管道
        ├── M3: 规范化强制 (_enforce_canonical_values)
        │   └── LLM 输出中的数值必须与 canonical 数据一致
        ├── 日期校验 (_validate_output_dates)
        ├── L4: 假设验证解析
        ├── L5: 跨维度 claim 提取 + 矛盾检测
        │   ├── write_canonical("claim:{aspect}:...", ...)
        │   └── write_canonical("conflict:{key}", ...)
        ├── 迭代深化：知识缺口检测 → 补充搜索
        └── 自评估 (self-evaluation)
```

## 5. 动态 Agent 工厂技术原理

### 5.1 创建流程

```
DynamicAgentFactory.create_agent_with_session(config, parent_session)
    │
    ├── 1. 创建 Agent 实例
    │   └── agent = GenericAgent(agent_id, config, skill_registry)
    │
    ├── 2. 注入通信组件
    │   ├── agent._message_bus = self._message_bus  # 共享单例
    │   └── agent._shared_memory = self._shared_memory  # 共享单例
    │
    ├── 3. 创建子 Session
    │   ├── session = AgentSession(parent_id=parent_session.session_id)
    │   ├── session.register_agent(agent)
    │   └── parent_session.register_child(session)
    │
    ├── 4. 技能注入
    │   └── agent._available_skills = config["skills"] 列表
    │
    └── 5. 生命周期注册
        └── agent._lifecycle_state = INITIALIZING → READY
```

### 5.2 Session 层级

```
ParentSession (研究主 Session)
    ├── session_id, state, conversation_history
    ├── research_context: { requirement, research_type, framework, ... }
    ├── AgentSessionRegistry: child_sessions[]
    ├── ResultCollector: await agents with timeout
    │       ├── 订阅 session.{id}.agent.completed
    │       ├── 订阅 session.{id}.agent.progress
    │       └── 订阅 session.{id}.agent.failed
    └── MessageBus: 事件广播

    ┌──────────┼──────────┐
    ▼          ▼          ▼
ChildSession ChildSession ChildSession
 parent_id    parent_id    parent_id
 agent_id     agent_id     agent_id
 status       status       status
 progress     progress     progress
 result       result       result
```

### 5.3 Agent 池与回收

```python
AgentLifecycleManager:
    _active_agents: Dict[str, GenericAgent]  # 运行中
    _agent_pool: List[GenericAgent]           # 待回收

    register(agent) → agent_id
    destroy(agent_id) → cleanup resources
    recycle(agent) → reset state + return to pool
```

回收流程：重置 `_status`, `_data`, `_lifecycle_state`，保留 `_skill_registry`, `_message_bus`, `_shared_memory` 注入。

## 6. 执行引擎调度原理

执行引擎的完整协调机制已拆分为独立章节，详见 [`16-Agent通信与协调机制.md`](16-Agent通信与协调机制.md)。本节仅保留概要。

**四级协调体系**：

| 层级 | 组件 | 职责 |
|------|------|------|
| Level 1 宏观 | ResearchOrchestrator | 阶段编排（采集→分析→报告→质检） |
| Level 2 中观 | ExecutionEngine | Agent 分类、批次调度、并发/重试/超时控制 |
| Level 3 微观 | AgentCoordinator | 任务分发、心跳监控、进度追踪 |
| Level 4 对等 | Agent 自协调 | SharedMemory 数据驱动 + MessageBus 事件通知 |

**关键组件**：
- `ExecutionEngine`（`engine.py:170`，3311 行）— 批次调度 + 质量控制 + 失败重试
- `AgentCoordinator`（`agent_coordinator.py:83`，860 行）— 任务分发 + 心跳/超时/取消
- `ResultCollector`（`result_collector.py:29`，406 行）— 事件驱动结果收集
- `CancelManager`（全局单例）— 暂停/恢复/取消
- `Scheduler`（`scheduler.py:52`）— 依赖拓扑排序生成执行批次

**批次执行示意**：

```
ExecutionEngine.execute_with_scheduler(agents, requirement)
  → Scheduler 生成批次 (依赖拓扑排序)
  → 逐批次: asyncio.gather 并发执行 → 质量控制 → 失败重试
  → 批次后处理: MetricExtractor → CanonicalDataRegistry → SharedMemory
```

## 7. 生命周期状态机

```
CREATED ──▶ INITIALIZING ──▶ READY ──▶ RUNNING ──▶ COMPLETED
                                               └──▶ FAILED
                                                    │
          ┌─────────────────────────────────────────┘
          ▼
       PAUSED ──▶ RUNNING (恢复)
          │
          ▼
       HIBERNATING ──▶ HIBERNATED ──▶ RESUMING ──▶ RUNNING
          │
          ▼
       TERMINATED
```

| 状态 | 含义 | 触发条件 |
|------|------|----------|
| CREATED | 刚实例化 | `__init__` |
| INITIALIZING | 正在注入依赖 | Factory 开始创建 |
| READY | 可执行 | 注入完成 |
| RUNNING | 执行中 | `execute()` 开始 |
| COMPLETED | 成功结束 | `execute()` 正常返回 |
| FAILED | 执行失败 | 异常或超时 |
| PAUSED | 暂停 | 外部请求 |
| HIBERNATING | 正在休眠 | 长时间无任务 |
| HIBERNATED | 已休眠 | 休眠完成 |
| RESUMING | 正在恢复 | 从休眠唤醒 |
| TERMINATED | 已销毁 | 外部销毁或回收 |

## 8. 通信机制

完整文档见 [`16-Agent通信与协调机制.md`](16-Agent通信与协调机制.md)，本节仅简要汇总。

| 模式 | 实现 | 用途 |
|------|------|------|
| **MessageBus** | `core/communication.py` | 异步发布/订阅事件通知 |
| **SharedMemory** | `core/communication.py` | 共享键值存储 + 规范化数据 + 优先级冲突检测 |
| **ResultCollector** | `core/agents/result_collector.py` | 事件驱动的 Master 收集子 Agent 结果 |
| **SessionStreamer** | `core/session_streamer.py` | 会话级 SSE 推送（见第 15 章） |
| **Direct Call** | 方法调用 | 同步直接调用 |

核心机制——**规范化数据层**（SharedMemory.write_canonical）：

```
来源优先级: structured_source(100) > search_result(50) > llm_inference_factual(15)
           > llm_inference(10) > llm_inference_speculative(5)

写入流程:
  write_canonical("revenue", 100亿, "search_result")
    → 冲突检测 (偏差 >5% 标记 conflict)
    → 优先级比较 (低优先级不能覆盖高优先级)
    → 写入 + 版本号递增
    → 自动发布 data.canonical.updated / data.conflict.detected 到 MessageBus
```

### 8.4 跨批次数据流

```
Batch N Agents (数据采集)
  │  write_canonical("revenue", 100亿, "structured_source")
  │  → SharedMemory 存储 + MessageBus 发布 data.canonical.updated
  │  → DataCollector 聚合
  ▼
ExecutionEngine 批次后处理
  │  广播 _canonical_registry 到 SharedMemory
  ▼
Batch N+1 Agents (深度分析)
  │  get("_canonical_registry") → 读取前序批次的规范化数据
  │  get_all_canonical() → 读取跨维度 claim/hypothesis
  │  write_canonical("claim:竞争格局:...", ...) → 写入新 claim
  ▼
结果聚合
```

## 9. 已知架构问题

Agent 系统存在**双结构问题**：
- `src/agents/fixed_agents/` 存 13 个固定 Agent
- `src/core/agents/` 存 Agent 核心系统（Factory、Session、GenericAgent 等）
- 开发者不清楚该继承哪个基类
- 建议统一到 `src/core/agents/` 下

## 10. 原始文档溯源

- `AGENT_ARCHITECTURE.md` — Agent 架构完整设计
- `ARCHITECTURE.md` §3.1 — Agent 系统分析
- `AGENT_SESSION_MANAGEMENT.md` — 会话层级管理
- `AGENT_EXECUTION_PARALLELISM_ANALYSIS.md` — 并行执行分析
- `system_architecture_design.md` §7 — 数据分析子系统
- `2026-06-26-report-generation-agent-upgrade-design-v2.md` — 报告生成 Agent 升级
