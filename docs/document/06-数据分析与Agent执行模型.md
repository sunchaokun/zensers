# 06 — 数据分析与 Agent 执行模型

> 章节定位：理解两阶段研究流程、Agent 的执行模型、数据验证机制。

---

## 1. 两阶段研究流程

每个研究 Agent 按"先数据采集，再深度分析"的两阶段流程执行：

```
GenericAgent.execute
    │
    ├── Phase 1: 数据采集
    │   ├── 迭代搜索（按深度配置）
    │   │   ├── basic: MAX_QUERIES=10, MAX_ITERATIONS=5
    │   │   ├── deep:  MAX_QUERIES=50, MAX_ITERATIONS=20
    │   ├── 多源搜索 + 网页抓取 + PDF解析
    │   ├── 权威度评分
    │   └── 结构化数据获取（akshare / 雪球）
    │
    └── Phase 2: 深度分析
        ├── LLM 驱动的综合分析
        ├── 注入质量评分标准 (quality_rubric.md)
        ├── 规范化数据验证 (CanonicalDataRegistry)
        └── 生成结构化章节内容
```

**关键设计**：数据采集和深度分析是分离的阶段，同一 Agent 先采集后分析。这保证了分析是在实际数据基础上进行的，而非 LLM 凭空生成。

## 2. Agent 执行模型

GenericAgent 采用 Mixin 模式组合核心能力：

```
GenericAgent
├── StateManagementMixin    异步状态管理
├── CommunicationMixin      消息总线 / 共享内存
└── 核心研究逻辑
```

Agent 分类，决定执行角色：

| 分类 | 职责 | 执行阶段 |
|------|------|----------|
| DATA_COLLECTION | 搜索、抓取等原始数据获取 | Phase 1 |
| ANALYSIS | 基于采集数据的分析推理 | Phase 3 |
| SYNTHESIS | 依赖其他章节的综合分析 | Phase 4 |
| CALIBRATION | 数据一致性校正 | Phase 2 |
| REPORT_GENERATION | 报告组装 | Phase 5 |
| QUALITY_CHECK | 质量评估 | 后处理 |
| DOCUMENT_GENERATION | 格式输出 | 后处理 |

## 3. 并行执行与调度

```
ExecutionEngine
│
├── ExecutionScheduler
│   ├── 同阶段 Agent 并行执行
│   ├── 阶段间按依赖顺序执行
│   ├── 支持暂停/恢复/取消
│   └── 心跳监控（协调器 30s 超时，进度 15s 间隔）
│
├── CancelManager
│   └── Condition-based 等待（非轮询）
│
└── PendingSectionInjects
    ├── add_section / cancel_section
    ├── merge_requirement
    └── revise
```

**运行时修改**：在执行过程中，用户可以通过 `modify_research` → `inject_requirement` 添加/取消章节，或通过 `revise` 修订内容。对于 EXECUTING 状态的重型操作，系统会降级处理（由状态感知动作约束控制）。

## 4. 结果聚合

ResultAggregator 将各 Agent 的结构化输出合并为统一的研究结果：

```
ResultAggregator
│
├── 输入：各 Agent 的结构化输出
│
├── 聚合策略：
│   ├── 按 section_details 合并
│   ├── 去重：跨 Agent 的重复数据源
│   ├── 矛盾处理：高权威度来源优先
│   └── 规范化验证：CanonicalDataRegistry
│
├── 输出：统一的研究结果结构
│
└── 后处理：
    ├── KnowledgeCompiler → 知识库条目
    ├── WisdomRecorder → 经验记录
    └── ContentQuality → 内容质量评估
```

## 5. 规范化数据验证

CanonicalDataRegistry 提供数据质量保证：

| 验证项 | 说明 |
|--------|------|
| 数值范围检查 | 数据是否在合理范围内 |
| 单位一致性 | 避免不同单位混用 |
| 时效性检查 | 数据是否过时 |
| 交叉引用一致性 | 多处引用数据是否一致 |

## 6. 原始文档溯源

- `system_architecture_design.md` §7 — 数据分析子系统
- `system_architecture_design.md` §10 — 质量保障体系
- `AGENT_EXECUTION_PARALLELISM_ANALYSIS.md` — 并行执行分析
- `2026-06-15-query-dedup-and-data-integrity-design.md` — 数据去重
- `src/core/orchestrator/execution/engine.py` — 执行引擎
- `src/core/orchestrator/aggregation/result_aggregator.py` — 结果聚合
