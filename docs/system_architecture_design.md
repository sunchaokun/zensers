# Zensers 系统架构设计方案

> 版本：1.4.2 | 自动化行业研究系统 | 最后更新：2026-06-30

---

## 目录

1. [系统概述](#1-系统概述)
2. [整体架构](#2-整体架构)
3. [会话管理子系统](#3-会话管理子系统)
4. [意图分析子系统](#4-意图分析子系统)
5. [智能路由子系统](#5-智能路由子系统)
6. [数据收集子系统](#6-数据收集子系统)
7. [数据分析子系统](#7-数据分析子系统)
8. [报告生成子系统](#8-报告生成子系统)
9. [知识管理与记忆子系统](#9-知识管理与记忆子系统)
10. [质量保障体系](#10-质量保障体系)
11. [技能插件体系](#11-技能插件体系)
12. [数据存储与持久化](#12-数据存储与持久化)
13. [API 与通信设计](#13-api-与通信设计)
14. [配置体系](#14-配置体系)
15. [前端架构](#15-前端架构)
16. [跨域关注点](#16-跨域关注点)

---

## 1. 系统概述

### 1.1 产品定位

Zensers 是一个 AI 驱动的市场研究平台，通过自然语言对话引导用户完成从需求理解到专业行业研究报告生成的完整流程。系统融合了大语言模型（LLM）、多源数据采集、智能任务分解、自动化报告生成等技术，将传统需要数天的人工研究过程压缩至分钟级。

### 1.2 核心能力

| 能力 | 描述 |
|------|------|
| 对话式需求理解 | 通过多轮对话逐步明确研究需求，自动识别隐含意图 |
| 语义意图分析 | 基于LLM的深层语义解析，支持复合意图、子意图拆分 |
| 智能任务路由 | 根据意图自动匹配研究类型、技能集、执行阶段 |
| 多源数据采集 | 集成6个搜索后端、网页抓取、PDF解析、问卷系统 |
| 并行研究执行 | 多Agent并行执行，支持暂停/恢复/取消/中间修改 |
| 自动报告生成 | 支持HTML预览、Word/PPT/PDF多格式导出 |
| 质量自动评估 | 内置质量检查Agent，支持自动修复循环 |
| 知识沉淀复用 | 研究成果自动存入知识库，支持跨会话知识检索 |

### 1.3 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.10+ / FastAPI / Pydantic v2 |
| 前端框架 | Next.js (App Router) / TypeScript / Zustand / shadcn/ui |
| LLM | OpenAI / DeepSeek |
| 数据库 | SQLite (默认) / PostgreSQL (可选) / Redis (可选) |
| 文档生成 | python-docx / python-pptx / reportlab |
| 数据可视化 | matplotlib / seaborn / plotly |
| 网页抓取 | Scrapling (自适应) / Playwright (JS渲染) / BeautifulSoup (解析) / pdfplumber (PDF) |
| 搜索 | Baidu SERP API / Bing / Google / Tavily / DuckDuckGo |

---

## 2. 整体架构

### 2.1 分层架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                      表示层 (Presentation)                       │
│  Next.js App Router + Zustand + SSE Client + Tailwind/shadcn    │
├─────────────────────────────────────────────────────────────────┤
│                       接口层 (API Gateway)                       │
│  FastAPI + CORS + SSE + ResearchAPI + SurveyAPI + DocumentAPI   │
├─────────────────────────────────────────────────────────────────┤
│                     对话管理层 (Dialogue)                         │
│  会话管理 + 状态机 + 意图状态追踪 + LLM对话循环 + 工具调用       │
├─────────────────────────────────────────────────────────────────┤
│                    智能路由层 (Intelligent Routing)               │
│  语义意图分析 + 任务结构分析 + 动态阶段编排 + 智慧推荐          │
├─────────────────────────────────────────────────────────────────┤
│                    编排执行层 (Orchestration)                     │
│  研究编排器 + 动态Agent工厂 + 执行引擎 + 调度器 + 聚合器       │
├─────────────────────────────────────────────────────────────────┤
│                    Agent执行层 (Agent Execution)                  │
│  通用Agent + 搜索技能 + 网页抓取 + LLM深度分析 + 数据分析      │
├─────────────────────────────────────────────────────────────────┤
│                    报告生成层 (Report Generation)                 │
│  文档生成Agent + 质量检查Agent + 预览修订工作流 + 模板引擎     │
├─────────────────────────────────────────────────────────────────┤
│                    基础设施层 (Infrastructure)                    │
│  数据存储 + 知识管理 + 技能注册 + 配置中心 + 进度推送           │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
用户输入
  │
  ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  会话管理     │───▶│  对话状态机       │───▶│  LLM对话循环      │
│  SessionMgr  │    │  StateMachine    │    │  + 工具调用       │
└──────────────┘    └──────────────────┘    └──────────────────┘
                                                      │
                                              意图明确 │
                                                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  智能路由     │───▶│  任务分解         │───▶│  Agent编排执行    │
│  RoutingAdpt │    │  Decomposition   │    │  ExecutionEngine │
└──────────────┘    └──────────────────┘    └──────────────────┘
                                                      │
                                              执行完成 │
                                                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  结果聚合     │───▶│  预览生成         │───▶│  质量检查+修复    │
│  Aggregator  │    │  PreviewGen      │    │  QualityCheck    │
└──────────────┘    └──────────────────┘    └──────────────────┘
                                                      │
                                              用户确认 │
                                                      ▼
                                            ┌──────────────────┐
                                            │  文档导出+知识沉淀 │
                                            │  Export+Knowledge │
                                            └──────────────────┘
```

### 2.3 模块依赖关系图

```
Frontend (Next.js)
    │
    │ HTTP/SSE
    ▼
FastAPI (src/api/main.py)
    │
    ├── ResearchAPI ──────────┬── SessionManager (会话持久化)
    │                         ├── ConversationStateMachine (状态机)
    │                         ├── DialogueIntentState (意图状态)
    │                         ├── ConversationToolSet (对话工具)
    │                         └── ResearchExecutor (后台执行)
    │                               │
    │                               └── ResearchOrchestrator (研究编排)
    │                                     │
    │                                     ├── IntelligentRoutingAdapter
    │                                     │     ├── SemanticIntentAnalyzer
    │                                     │     ├── TaskStructureAnalyzer
    │                                     │     └── DynamicPhaseOrchestrator
    │                                     │
    │                                     ├── DynamicAgentFactory
    │                                     │     └── GenericAgent × N (每章节)
    │                                     │           ├── SkillRegistry
    │                                     │           │     ├── SearchSkill
    │                                     │           │     ├── WebScraperSkill
    │                                     │           │     ├── LLMSkill
    │                                     │           │     └── LangChain Tools
    │                                     │           └── call_llm()
    │                                     │
    │                                     ├── ExecutionEngine + Scheduler
    │                                     ├── ResultAggregator
    │                                     ├── QualityCheckAgent
    │                                     ├── DocumentGenerationAgent
    │                                     └── PreviewRevisionWorkflow
    │
    ├── KnowledgeManager ──── UserKnowledgeBank / CoreMemory / DreamMode
    ├── SurveySubsystem ──── 问卷创建 / 模拟 / 分析
    ├── DocumentAPIRouter ─── 文档导出
    └── PromptAPIRouter ───── Prompt管理
```

---

## 3. 会话管理子系统

### 3.1 设计目标

- 支持长时间运行的研究会话（数十分钟到数小时）
- 会话状态自动持久化，进程崩溃可恢复
- 对话历史不可篡改（追加式保护），支持压缩
- 支持多会话并行

### 3.2 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    SessionManager (Singleton)            │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │          PersistentSessionDict                   │    │
│  │  ┌───────────┐  ┌───────────┐  ┌────────────┐  │    │
│  │  │ session_1 │  │ session_2 │  │ session_N  │  │    │
│  │  │ .json     │  │ .json     │  │ .json      │  │    │
│  │  └───────────┘  └───────────┘  └────────────┘  │    │
│  │       │自动写入（原子写：temp + rename）          │    │
│  │       ▼                                         │    │
│  │  data/sessions/{session_id}.json                 │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  SessionHistoryCompressor (可选)                 │    │
│  │  长对话压缩 → 保留关键上下文                      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  恢复策略：启动时预加载最近5个会话，其余懒加载            │
│  写入策略：2秒防抖，避免频繁I/O                          │
└─────────────────────────────────────────────────────────┘
```

### 3.3 核心数据结构

**Session 对象**：

```json
{
  "session_id": "uuid",
  "created_at": "2026-06-30T10:00:00Z",
  "updated_at": "2026-06-30T10:30:00Z",
  "state": "EXECUTING",
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "display_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "research_context": {
    "requirement": "原始需求文本",
    "research_type": "INDUSTRY_RESEARCH",
    "framework": {...},
    "_dialogue_intent_state": {...},
    "confirmed_aspects": [...],
    "pending_questions": [...]
  },
  "task_id": "后台任务ID",
  "metadata": {}
}
```

### 3.4 对话状态机

系统定义了严格的有限状态机（FSM）来管理对话生命周期：

```
                          ┌──────────────┐
                          │ UNDERSTANDING │ ◄── 初始状态
                          └──────┬───────┘
                                 │ 意图初步识别
                                 ▼
                          ┌──────────────┐
                    ┌─────│  CLARIFYING  │─────┐
                    │     └──────┬───────┘     │
                    │ 需要更多信息  │ 信息充分     │ 不需澄清
                    │              ▼             │
                    │     ┌────────────────┐    │
                    │     │FRAMEWORK_CONFIRM│◄───┘
                    │     └───────┬────────┘
                    │             │ 用户确认框架
                    │             ▼
                    │     ┌──────────────┐
                    │     │  EXECUTING   │◄──────┐
                    │     └──┬───┬───┬───┘       │
                    │        │   │   │            │
                    │   暂停 │   │   │ 重新设计    │ 恢复
                    │        ▼   │   │ 框架       │
                    │  ┌────────┐│   ▼            │
                    │  │PAUSED  ││  FRAMEWORK_    │
                    │  └───┬────┘│  CONFIRM       │
                    │      └─────┘               │
                    │                            │
                    │ 取消                       │
                    ▼                            │
             ┌─────────────┐                    │
             │  CANCELLED  │                    │
             └─────────────┘                    │
                                              │
                    执行完成 ──▶ ┌──────────────┐
                                │  PREVIEWING  │
                                └──────┬───────┘
                                       │ 用户确认
                                       ▼
                                ┌──────────────┐
                                │  COMPLETED   │
                                └──────────────┘
```

**关键状态转换规则**：
- `UNDERSTANDING → CLARIFYING`：LLM判断需要更多信息
- `CLARIFYING → FRAMEWORK_CONFIRM`：readiness_score达到SUFFICIENT
- `FRAMEWORK_CONFIRM → EXECUTING`：用户确认研究框架
- `EXECUTING → PAUSED → EXECUTING`：暂停/恢复循环
- `EXECUTING → FRAMEWORK_CONFIRM`：执行中重新设计框架
- `PREVIEWING → COMPLETED`：用户确认报告终稿

**状态感知动作约束**：在EXECUTING状态中，重型操作（如修改研究框架）需要明确的用户关键词触发，否则被降级处理（如 `modify_research → inject_requirement`）。

### 3.5 对话意图状态追踪

`DialogueIntentState` 在多轮对话中持续积累和更新意图信息：

```python
class DialogueIntentState:
    topic_hint: str                    # 主题提示
    confirmed_aspects: List[str]       # 已确认的方面
    pending_questions: List[str]       # 待澄清问题
    hidden_requirements: List[str]     # 隐含需求
    domain_context: Dict[str, Any]     # 领域上下文
    is_composite: bool                 # 是否为复合意图
    sub_intents: List[SubIntent]       # 子意图列表
    orchestration_strategy: str        # 编排策略 (默认"sequential")
    readiness_score: float             # 就绪度分数 (0.0-1.0)
    readiness_level: ReadinessLevel    # INSUFFICIENT / PARTIAL / SUFFICIENT
    clarification_count: int           # 澄清次数
    research_turns: int                # 研究对话轮次
    user_aspects: List[str]            # 用户提及的方面
    framework_aspects: List[str]       # 框架确认的方面
```

**更新机制**：
- `update_from_response()`：从LLM对话结果中提取更新
- `merge_from_analysis()`：与DeepIntentResult进行合并，采用置信度融合策略（新分析置信度低时保留原有意图）

---

## 4. 意图分析子系统

### 4.1 设计目标

- 从用户自然语言输入中精确提取研究意图
- 识别隐含需求、复合意图、歧义点
- 为后续路由提供结构化的意图描述

### 4.2 意图分类体系

```
IntentType (意图类型)
├── RESEARCH        # 市场分析、数据收集
├── IMPLEMENTATION  # 报告生成、内容产出
├── INVESTIGATION   # 问题诊断、根因分析
├── EVALUATION      # 质量检查、对比评估
├── FIX             # 错误修正、内容修订
├── OPEN_ENDED      # 开放性探索研究
└── CLARIFICATION   # 需要用户进一步输入

TaskComplexity (任务复杂度)
├── TRIVIAL  # 简单查询
├── SINGLE   # 单一任务
├── MULTI    # 多任务组合
└── COMPLEX  # 复杂研究项目
```

### 4.3 研究类型体系

系统支持15种可组合的研究类型：

```
ResearchType
├── 基础研究
│   ├── INDUSTRY_RESEARCH        # 行业研究
│   ├── BRAND_RESEARCH           # 品牌研究
│   ├── COMPANY_RESEARCH         # 企业研究
│   ├── CONSUMER_RESEARCH        # 消费者研究
│   └── COMPETITIVE_ANALYSIS     # 竞争分析
├── 专项研究
│   ├── MARKET_SIZING            # 市场规模测算
│   ├── POLICY_ANALYSIS          # 政策分析
│   └── TECHNOLOGY_RESEARCH      # 技术研究
├── 数据采集
│   ├── SURVEY                   # 问卷调查
│   ├── INTERVIEW                # 深度访谈
│   └── OBSERVATION              # 实地观察
└── 分析框架
    ├── DATA_ANALYSIS            # 数据分析
    ├── SWOT_ANALYSIS            # SWOT分析
    ├── PESTEL_ANALYSIS          # PESTEL分析
    └── PORTER_ANALYSIS          # 波特五力分析

### 4.4 语义意图分析流程

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────────────┐
│            SemanticIntentAnalyzer                     │
│                                                      │
│  ① 首选方案：LLM深度语义分析                          │
│     ┌─────────────────────────────────────────────┐  │
│     │  LLM调用 (intent_analysis_system prompt)     │  │
│     │  分析5个维度：                                │  │
│     │  • 显式意图 - 用户明确表达的需求              │  │
│     │  • 隐式意图 - 未明说但必要的步骤              │  │
│     │  • 复合意图 - 多个独立子任务                  │  │
│     │  • 歧义检测 - 是否需要进一步澄清              │  │
│     │  • 复杂度评估 - 基于数据需求和推理深度        │  │
│     └─────────────────────────────────────────────┘  │
│     │                                                │
│     │ 自一致性模式 (可选)                             │
│     │ ┌───────────────────────────────────────────┐  │
│     │ │ 多次LLM采样 (不同温度) → 多数投票           │  │
│     │ └───────────────────────────────────────────┘  │
│     │                                                │
│  ② 降级方案：关键词匹配                               │
│     ┌─────────────────────────────────────────────┐  │
│     │  keyword_mappings.yaml → 关键词匹配          │  │
│     │  当LLM不可用时自动降级                        │  │
│     │  └─────────────────────────────────────────────┘  │
│                                                      │
│  输出：DeepIntentResult                               │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  DeepIntentResult (结构化意图结果, 28个字段)           │
│                                                      │
│  ── 核心意图 ──                                       │
│  primary_intent: IntentType           主意图          │
│  intent_confidence: float             置信度          │
│  intent_reasoning: str                推理过程        │
│                                                      │
│  ── 研究类型 ──                                       │
│  research_types: List[ResearchType]   研究类型列表    │
│  primary_research_type: Optional      主研究类型      │
│  secondary_research_types: List       辅助研究类型    │
│                                                      │
│  ── 任务范围 ──                                       │
│  task_scope: str                      任务范围        │
│  requires_primary_data: bool          是否需一手数据  │
│  requires_secondary_data: bool        是否需二手数据  │
│  complexity: TaskComplexity           任务复杂度      │
│  aspect_count: int                    方面数量        │
│  estimated_effort: str                预估工作量      │
│  execution_preference: str            执行偏好        │
│  output_mode: str                     输出模式        │
│                                                      │
│  ── 上下文与需求 ──                                   │
│  domain_context: Dict[str, Any]       领域上下文      │
│  hidden_requirements: List[str]       隐含需求        │
│  needs_clarification: bool            是否需澄清      │
│  clarification_questions: List[str]   澄清问题        │
│  core_question: str                   核心问题        │
│                                                      │
│  ── 复合意图 ──                                       │
│  is_composite: bool                   是否复合意图    │
│  sub_intents: List[SubIntent]         子意图列表      │
│  orchestration_strategy: str          编排策略        │
│                                                      │
│  ── 执行规格 ──                                       │
│  section_data_specs: List             章节数据规格    │
│  recommended_skills: List[str]        推荐技能        │
│                                                      │
│  ── 元数据 ──                                         │
│  llm_model_used: str                  使用的LLM模型   │
│  analysis_timestamp: datetime         分析时间戳      │
│  raw_llm_response: str                原始LLM响应     │
│  used_fallback: bool                  是否使用降级    │
└──────────────────────────────────────────────────────┘
```

### 4.5 增量分析机制

系统支持增量意图分析（`analyze_incremental()`），适用于对话过程中用户追加信息或修改需求的场景：

- **意图融合**：新分析结果与已有意图合并，置信度低时保留原有判断
- **跳过阶段判定**：根据已有意图状态决定哪些执行阶段可以跳过
- **内容锁管理**：`ContentLockManager` 防止对共享章节的并发冲突编辑

---

## 5. 智能路由子系统

### 5.1 设计目标

- 根据意图分析结果自动匹配最优执行路径
- 动态编排执行阶段，避免不必要的步骤
- 复用历史研究经验（智慧推荐）

### 5.2 三步路由流水线

```
┌─────────────────────────────────────────────────────────────┐
│              IntelligentRoutingAdapter                       │
│                                                             │
│  Step 1: 语义意图分析                                       │
│  ┌───────────────────────┐                                  │
│  │ SemanticIntentAnalyzer │ ──▶ DeepIntentResult             │
│  └───────────────────────┘         │                        │
│                                    ▼                        │
│  Step 2: 任务结构分析                                       │
│  ┌───────────────────────┐                                  │
│  │ TaskStructureAnalyzer  │ ──▶ TaskStructure                │
│  └───────────────────────┘         │   + SectionSpec[]       │
│                                    ▼                        │
│  Step 3: 动态阶段编排                                       │
│  ┌──────────────────────────┐                               │
│  │ DynamicPhaseOrchestrator │ ──▶ ExecutionPlan              │
│  └──────────────────────────┘         + ExecutionPhase[]    │
│                                                             │
│  辅助：WisdomStore.get_recommended_skills()                 │
│  为每个aspect推荐历史验证有效的技能组合                       │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 能力模板映射

每种意图类型映射到推荐的能力集和模型偏好：

| 意图类型 | 主能力 | 辅助能力 | 推荐技能 | 模型偏好 |
|---------|--------|---------|---------|---------|
| RESEARCH | research | data_collection, analysis | search_skill, web_scraper, llm_skill | reasoning |
| IMPLEMENTATION | implementation | coding, generation | llm_skill, docx_skill | coding |
| INVESTIGATION | investigation | debugging, verification | search_skill, llm_skill | reasoning |
| EVALUATION | evaluation | comparison, assessment | llm_skill, search_skill | reasoning |
| FIX | fix | debugging, correction | llm_skill | coding |
| OPEN_ENDED | exploration | research, analysis | search_skill, llm_skill | reasoning |
| CLARIFICATION | clarification | questioning | llm_skill | chat |

### 5.4 任务分解策略

根据研究类型选择不同的分解策略（`src/core/decomposition/`）：

```
DecompositionStrategy
├── IndustryResearchStrategy      # 行业研究：市场规模→竞争格局→趋势→政策
├── CompanyResearchStrategy       # 企业研究：公司概况→财务→竞争→战略
├── ConsumerResearchStrategy      # 消费者研究：人群画像→需求→行为→满意度
├── CompetitiveAnalysisStrategy   # 竞争分析：格局→SWOT→策略
├── MarketSizingStrategy          # 市场规模：定义→TAM→SAM→SOM
└── ... (每类研究有专属策略)
```

**DecompositionPlan** 输出：
```json
{
  "sections": [
    {
      "section_id": "market_overview",
      "title": "市场概览",
      "description": "行业规模、增长率、发展阶段",
      "data_specs": {
        "data_needs": ["市场规模数据", "增长率数据"],
        "source_type": "both"
      },
      "depends_on": [],
      "category": "DATA_COLLECTION"
    },
    {
      "section_id": "competitive_landscape",
      "title": "竞争格局",
      "depends_on": ["market_overview"],
      "category": "ANALYSIS"
    }
  ],
  "execution_order": [["market_overview"], ["competitive_landscape"]]
}
```

### 5.5 执行阶段编排

`DynamicPhaseOrchestrator` 将任务结构转化为执行计划：

```
ExecutionPlan (PHASE_ORDER)
├── Phase 1: DATA_COLLECTION       # 数据采集阶段
│   └── Agent: market_overview, policy_scan, ...
├── Phase 2: DATA_VALIDATION       # 数据验证阶段
│   └── 验证采集数据的完整性和准确性
├── Phase 3: DEEP_ANALYSIS         # 深度分析阶段
│   └── Agent: competitive_landscape, trend_analysis, ...
├── Phase 4: SYNTHESIS             # 跨章节综合
│   └── Agent: cross_section_synthesis
└── Phase 5: REPORT_GENERATION     # 报告生成阶段
    └── 整合各章节内容为完整报告

注：CALIBRATION/QUALITY_CHECK/DOCUMENT_GENERATION 是AgentCategory，
在批量执行逻辑中单独处理，不在PHASE_ORDER中。
```

同一阶段内的Agent可并行执行；阶段间存在依赖关系按序执行。

---

## 6. 数据收集子系统

### 6.1 设计目标

- 多引擎、多策略的数据采集能力
- 支持结构化搜索、网页抓取、PDF解析、问卷数据
- 自动适配不同网站的技术特性

### 6.2 搜索引擎集成

```
┌─────────────────────────────────────────────────────────┐
│              SearchSkill (多引擎搜索)                     │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ DuckDuckGo│  │  Baidu    │  │ Bing CN  │              │
│  │ DDGS库    │  │ SERP API  │  │web_fetch │              │
│  │ 最先执行  │  │ 优先级:1  │  │ 优先级:2 │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │Bing Intl │  │  Google   │  │Google HK │              │
│  │web_fetch │  │Scrapling  │  │Scrapling │              │
│  │ 优先级:3 │  │ 优先级:10 │  │ 优先级:11 │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│                                                         │
│  共6个搜索后端 (5个在SEARCH_ENGINES字典 + DuckDuckGo)    │
│  变体：NewsSearchSkill (新闻专用, DDGS news())           │
│       MultiSearchSkill (多引擎并行, 主类)                │
│       SearchSkill = WebSearchSkill = MultiSearchSkill    │
│                                                         │
│  LangChain 工具：Tavily / DuckDuckGo                    │
└─────────────────────────────────────────────────────────┘
```

### 6.3 网页内容抓取

```
┌─────────────────────────────────────────────────────────┐
│           WebScraperSkill (多策略抓取)                    │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 策略1: 静态/自适应页面                             │   │
│  │ Scrapling AsyncFetcher (adaptive=True)            │   │
│  │ 适用：普通HTML页面及轻度JS页面                     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 策略2: JS渲染页面                                  │   │
│  │ Playwright (Headless Chromium)                    │   │
│  │ 适用：eastmoney.com, xueqiu.com, 36kr.com 等     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 策略3: PDF文档                                     │   │
│  │ pdfplumber                                        │   │
│  │ 适用：研究报告、白皮书等PDF文件                     │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 策略4: 百度跳转解析                                │   │
│  │ 解析百度搜索结果的真实URL → 重新分类处理           │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  自适应分类：URL → 判断内容类型 → 选择最优抓取策略       │
└─────────────────────────────────────────────────────────┘
```

### 6.4 问卷数据采集

```
┌─────────────────────────────────────────────────────────┐
│              Survey Subsystem                            │
│                                                         │
│  问卷创建 → 模拟引擎 → 回答质量评估 → 数据分析          │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ PersonaGen   │  │ Simulation   │  │ Calibration  │  │
│  │ 人设生成器    │  │ 模拟引擎     │  │ 数据校准     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│  分析能力：                                              │
│  ├── 情感分析 (Sentiment)                               │
│  ├── 交叉分析 (Crosstab)                                │
│  ├── 词云生成 (WordCloud)                               │
│  └── 统计分析 (Statistics)                              │
│                                                         │
│  基准校准：WVS (World Values Survey) 基准数据            │
└─────────────────────────────────────────────────────────┘
```

### 6.5 技能注册体系

```
SkillRegistry
├── 核心技能 (register_core_skills)
│   ├── search_skill / web_search    # 多引擎搜索
│   ├── news_search                  # 新闻搜索
│   ├── file_skill                   # 文件操作
│   ├── http_skill                   # HTTP请求
│   ├── docx_skill                   # Word生成
│   ├── llm_skill                    # LLM调用
│   ├── web_scraper                  # 网页抓取
│   └── knowledge_query              # 知识库查询
│
├── LangChain工具 (自动发现)
│   ├── Tavily                       # 搜索API
│   ├── Arxiv                        # 学术论文
│   ├── Wikipedia                    # 百科知识
│   └── Python REPL                  # 代码执行
│
└── 专业分析技能 (工厂注册)
    ├── MarketAnalysis               # 市场分析
    ├── DataAnalysis                 # 数据分析
    ├── StockData / StockAnalysis    # 股票数据/分析
    ├── PolicyAnalysis               # 政策分析
    ├── TechTrend                    # 技术趋势
    └── RiskAnalysis                 # 风险分析
```

---

## 7. 数据分析子系统

### 7.1 设计目标

- 两阶段研究：先采集数据，再深度分析
- 多Agent并行分析不同章节
- 权威度加权的信源评估

### 7.2 Agent执行模型

```
┌─────────────────────────────────────────────────────────────┐
│                  GenericAgent (通用研究Agent)                 │
│                                                             │
│  组成：Mixin 模式                                           │
│  ├── StateManagementMixin    异步状态管理                    │
│  ├── CommunicationMixin      消息总线/共享内存               │
│  └── 核心研究逻辑                                           │
│                                                             │
│  生命周期：CREATED → INITIALIZING → READY → RUNNING → COMPLETED/     │
│           FAILED (+ PAUSED/HIBERNATING/HIBERNATED/RESUMING/         │
│           TERMINATED 资源管理)                                       │
│                                                             │
│  两阶段研究流程：                                            │
│  ┌───────────────────────────────────────────────────┐      │
│  │ Phase 1: 数据采集                                  │      │
│  │ • 迭代搜索 (按深度配置):                          │      │
│  │   basic: MAX_QUERIES=10, MAX_ITERATIONS=5         │      │
│  │   deep:  MAX_QUERIES=50, MAX_ITERATIONS=20        │      │
│  │ • 多源搜索 + 网页抓取 + PDF解析                    │      │
│  │ • 权威度评分：gov.cn:0.95, mckinsey.com:0.88, ...│      │
│  └───────────────────────────────────────────────────┘      │
│                         │                                    │
│                         ▼                                    │
│  ┌───────────────────────────────────────────────────┐      │
│  │ Phase 2: 深度分析                                  │      │
│  │ • LLM驱动的综合分析                                │      │
│  │ • 注入质量评分标准 (quality_rubric.md)             │      │
│  │ • 规范化数据验证 (CanonicalDataRegistry)           │      │
│  │ • 生成结构化章节内容                                │      │
│  └───────────────────────────────────────────────────┘      │
│                                                             │
│  输出：结构化的章节内容 + 数据来源 + 置信度                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Agent分类与执行顺序

```
AgentCategory (Agent分类，决定Agent角色)
│
├── DATA_COLLECTION     数据采集Agent
│   └── 搜索、抓取、问卷等原始数据获取
│
├── ANALYSIS            深度分析Agent
│   └── 基于采集数据的分析推理
│
├── SYNTHESIS           跨章节综合Agent
│   └── 依赖其他章节的综合分析
│
├── CALIBRATION         数据校准Agent
│   └── 数据一致性和准确性校正
│
├── REPORT_GENERATION   报告组装Agent
│   └── 各章节内容整合为完整报告
│
├── QUALITY_CHECK       质量检查Agent
│   └── 内容质量评估与修复建议
│
├── DOCUMENT_GENERATION 文档输出Agent
│   └── HTML/Word/PPT/PDF格式化输出
│
└── UNKNOWN             未分类Agent

ResearchPhase (研究阶段，决定执行顺序)
│
├── 1. DATA_COLLECTION      数据采集阶段
├── 2. DATA_VALIDATION      数据验证阶段
├── 3. DEEP_ANALYSIS        深度分析阶段
├── 4. SYNTHESIS            综合分析阶段
└── 5. REPORT_GENERATION    报告生成阶段

执行流程 (PHASE_ORDER)：
DATA_COLLECTION → DATA_VALIDATION → DEEP_ANALYSIS → SYNTHESIS → REPORT_GENERATION

注：CALIBRATION/QUALITY_CHECK/DOCUMENT_GENERATION 是AgentCategory，
在批量执行逻辑中单独处理，不在PHASE_ORDER中。
```

### 7.4 执行引擎与调度器

```
┌─────────────────────────────────────────────────────────────┐
│                   ExecutionEngine                            │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ExecutionScheduler                                  │    │
│  │  • 同一阶段内的Agent并行执行                          │    │
│  │  • 阶段间按依赖关系顺序执行                           │    │
│  │  • 支持暂停/恢复/取消                                 │    │
│  │  • 心跳监控 (协调器30秒超时, 进度15秒间隔)        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  CancelManager                                       │    │
│  │  • 基于Condition的等待机制 (非轮询)                   │    │
│  │  • 优雅取消：完成当前步骤后停止                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  PendingSectionInjects                               │    │
│  │  • 运行中修改：add_section / cancel_section          │    │
│  │  • 需求合并：merge_requirement                       │    │
│  │  • 内容修订：revise                                  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 7.5 结果聚合

```
ResultAggregator
│
├── 输入：各Agent的结构化输出
│
├── 聚合策略：
│   ├── 按section_details合并（尊重章节结构）
│   ├── 去重：跨Agent的重复数据源
│   ├── 矛盾处理：以高权威度来源为准
│   └── 规范化数据验证：CanonicalDataRegistry.validate_section()
│
├── 输出：统一的研究结果结构
│
├── 后处理：
    ├── KnowledgeCompiler → 知识库条目
    ├── WisdomRecorder → 经验记录（用于未来路由推荐）
    └── ContentQuality → 内容质量评估
```

---

## 8. 报告生成子系统

### 8.1 设计目标

- 多格式输出（HTML预览 + Word/PPT/PDF导出）
- 支持交互式预览和迭代修订
- 基于模板的专业排版

### 8.2 完整报告生成流程

```
Agent执行完成
    │
    ▼
┌──────────────┐
│ ResultAggregator │ ── 聚合各Agent结果
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ ReportOrchestrator│ ── 报告升级整合
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│DocumentGeneration │ ── HTML预览生成
│     Agent         │    使用 config/document_templates/ 模板
└──────┬───────────┘
       │
       ▼
┌──────────────┐
│QualityCheckAgent│ ── 质量评估 + 自动修复 (max 2 attempts)
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│ PreviewRevision  │ ── 预览+修订工作流 (交互模式)
│    Workflow       │    用户反馈 → 局部修订 → 重新预览
└──────┬───────────┘
       │
       ▼ 用户确认终稿
┌──────────────────┐
│ DocumentGeneration│ ── 正式文档导出
│     Agent         │    DOCX / PPTX / PDF
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ KnowledgeDeposit │ ── 研究成果存入知识库
└──────────────────┘
```

### 8.3 报告模板体系

系统预置12种报告模板（另有1个模板Schema定义文件），每种模板定义了专属的章节结构、搜索深度、分析深度：

| 模板类型 | 用途 | 典型章节数 |
|---------|------|-----------|
| industry_report | 行业研究报告 | 8-12 |
| industry_weekly | 行业周报 | 4-6 |
| company_research | 企业研究报告 | 6-10 |
| quarterly_commentary | 季度点评 | 3-5 |
| annual_analysis | 年度分析 | 8-12 |
| conference_call | 电话会议纪要 | 3-4 |
| commercial_plan | 商业计划书 | 10-15 |
| pitch_deck | 路演PPT | 8-12 |
| investment_memo | 投资备忘录 | 6-8 |
| competitor_analysis | 竞品分析 | 5-8 |
| policy_brief | 政策简报 | 3-5 |
| market_brief | 市场简报 | 3-5 |

**模板结构定义** (`config/templates/template_schema.yaml`)：
```yaml
template:
  id: industry_report
  name: 行业研究报告
  sections:
    - id: market_overview
      title: 市场概览
      required: true
      data_priority: high
    - id: competitive_landscape
      title: 竞争格局
      required: true
      data_priority: high
    ...
  search_depth: deep
  analysis_depth: comprehensive
  quality_threshold: 0.8
```

### 8.4 预览修订工作流

```
PreviewRevisionWorkflow
│
├── 初始预览生成 → HTML推送到前端
│
├── 修订循环 (最多10轮)：
│   ├── 用户提交修订请求
│   │   ├── 整体反馈："加强竞争分析部分"
│   │   ├── 章节修订："修改第三章的数据"
│   │   ├── 新增章节："增加ESG分析"
│   │   └── 删除章节："移除附录"
│   │
│   ├── 意图分析 → RevisionIntentAnalysis
│   │   └── 理解修订意图，定位影响范围
│   │
│   ├── 修订传播 → AdjustmentCascade
│   │   └── 级联更新：修订一个章节可能影响其他章节
│   │
│   ├── 章节定位 → SectionLocator
│   │   └── 精确定位需要修改的内容位置
│   │
│   ├── 执行修订 → 调用Agent重新生成受影响章节
│   │
│   └── 重新预览 → 更新HTML
│
└── 用户确认终稿 → 触发正式文档导出
```

### 8.5 文档导出

```
DocumentGenerationAgent
│
├── produce_document (完整文档)
│   ├── HTML → 直接预览
│   ├── DOCX → python-docx + HTML模板
│   ├── PPTX → python-pptx + 模板
│   └── PDF  → reportlab
│
├── generate_section (单章节)
│   └── 按需重新生成特定章节
│
└── 样式管理
    └── StyleManager → 统一样式配置
        ├── config/document_templates/*.html
        └── 图表、表格、排版的统一规范
```

---

## 9. 知识管理与记忆子系统

### 9.1 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                 KnowledgeManager                         │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────────────┐    │
│  │ UserKnowledgeBank │  │     CoreMemory           │    │
│  │ 用户专属知识库    │  │  系统核心记忆             │    │
│  │ SQLite存储       │  │  方法论、框架、基准数据    │    │
│  └──────────────────┘  └──────────────────────────┘    │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────────────┐    │
│  │  WisdomStore     │  │  DreamModeScheduler      │    │
│  │  智慧经验存储    │  │  梦境模式调度器           │    │
│  │  路由推荐依据    │  │  空闲时知识整理与整合     │    │
│  └──────────────────┘  └──────────────────────────┘    │
│                                                         │
│  数据源：                                               │
│  ├── data/knowledge/    方法论知识库                     │
│  ├── data/knowledge_bank.db  知识库SQLite               │
│  ├── data/benchmarks/   WVS基准数据                     │
│  └── data/users/{uid}/  用户专属知识                     │
└─────────────────────────────────────────────────────────┘
```

### 9.2 知识生命周期

```
研究完成 → KnowledgeCompiler → 结构化知识条目
    │
    ├── 存入 UserKnowledgeBank (用户可检索)
    ├── 存入 CoreMemory (系统级知识)
    └── 记录到 WisdomStore (经验教训)
         │
         └── 下次研究时 → WisdomStore.get_recommended_skills()
                         → 为每个aspect推荐历史验证有效的技能组合

DreamMode (梦境模式)：
    └── 空闲时段 → 自动整理知识库
                  → 去重、关联、索引优化
                  → 方法论更新
```

---

## 10. 质量保障体系

### 10.1 质量检查流程

```
┌──────────────────────────────────────────────────────────┐
│                  QualityCheckAgent                        │
│                                                          │
│  评估维度 (来自 prompts/_shared/quality_rubric.md)：      │
│  ├── 数据准确性     数据来源是否可靠、数值是否可验证       │
│  ├── 逻辑连贯性     章节间论证是否自洽                     │
│  ├── 内容完整性     是否覆盖所有要求的方面                 │
│  ├── 来源权威性     是否引用高质量数据源                   │
│  └── 表述专业性     语言是否符合行业规范                   │
│                                                          │
│  自动修复循环 (最多2次尝试)：                              │
│  ├── 评分 < 阈值 → 生成修复建议                          │
│  ├── 重新生成受影响章节                                   │
│  ├── 重新评分                                            │
│  └── 重复直到达标或达到最大修复轮次                       │
│                                                          │
│  质量配置：config/content_quality.yaml                    │
│  └── 不同报告类型有不同的质量阈值                         │
└──────────────────────────────────────────────────────────┘
```

### 10.2 规范化数据验证

```
CanonicalDataRegistry
│
├── 作用：验证报告中使用的数据是否符合规范
│
├── validate_section(section_id, data)
│   ├── 数值范围检查
│   ├── 单位一致性检查
│   ├── 时效性检查（数据是否过时）
│   └── 交叉引用一致性
│
└── 规范来源：config/research_frameworks.yaml
    └── 每种研究类型定义了数据规范和验证规则
```

---

## 11. 技能插件体系

### 11.1 设计目标

- 可插拔的技能架构，支持热加载
- 统一的技能接口，兼容LangChain工具
- 领域特定技能的工厂注册

### 11.2 技能架构

```
┌─────────────────────────────────────────────────────────┐
│                    SkillRegistry                         │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 技能发现                                         │    │
│  │ ├── 内置技能: register_core_skills()             │    │
│  │ ├── LangChain工具: 自动发现 (Tavily, Arxiv...)   │    │
│  │ ├── 专业分析: 工厂注册 (Market, Stock, Policy...) │    │
│  │ └── 自定义技能: 热加载 (watchdog监控)             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 技能适配器                                       │    │
│  │ └── LangChainToolAdapter                        │    │
│  │     └── 统一LangChain工具到系统技能接口           │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  技能分类：                                              │
│  ├── src/skills/adapters/     适配器                    │
│  ├── src/skills/analysis/     分析技能                  │
│  ├── src/skills/builtin/      内置技能                  │
│  └── src/skills/business/     业务技能                  │
└─────────────────────────────────────────────────────────┘
```

### 11.3 技能热加载

通过 `watchdog` 库监控技能目录变化，检测到新文件或修改时自动重新加载，无需重启服务。

---

## 12. 数据存储与持久化

### 12.1 存储架构

```
┌─────────────────────────────────────────────────────────┐
│                    存储层                                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ SQLite (默认, 开箱即用)                          │    │
│  │ ├── data/zensers.db          主数据库             │    │
│  │ ├── data/knowledge_bank.db   知识库               │    │
│  │ └── 无需额外配置                                │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ PostgreSQL (可选, 生产环境推荐)                   │    │
│  │ ├── 连接池: pool_size=10                         │    │
│  │ └── 配置: settings.yaml                          │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Redis (可选, 缓存与消息队列)                      │    │
│  │ ├── 缓存: default_ttl=3600                       │    │
│  │ └── 消息队列: Agent间通信                        │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 文件存储                                         │    │
│  │ ├── data/sessions/     会话JSON文件              │    │
│  │ ├── data/reports/      生成的报告文档            │    │
│  │ ├── data/backups/     报告备份                   │    │
│  │ ├── data/html_reports/ HTML预览文件              │    │
│  │ ├── data/users/       用户数据                   │    │
│  │ └── data/knowledge/   方法论知识                 │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 12.2 写前日志 (WAL)

`src/core/storage/` 实现了WAL（Write-Ahead Logging）机制，确保数据操作的原子性和可恢复性：

```
操作请求 → WAL记录 → 实际执行 → WAL标记完成
                │
                └── 崩溃恢复：重放未完成的WAL记录
```

---

## 13. API 与通信设计

### 13.1 RESTful API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/research/start` | POST | 启动研究（对话模式） |
| `/api/v1/research/quick-start` | POST | 快速启动（模板模式） |
| `/api/v1/research/interact` | POST | 多步对话交互 |
| `/api/v1/research/{task_id}/pause` | POST | 暂停研究 |
| `/api/v1/research/{task_id}/resume` | POST | 恢复研究 |
| `/api/v1/research/{task_id}/cancel` | POST | 取消研究 |
| `/api/v1/research/{task_id}/modify` | POST | 运行中修改需求 |
| `/api/v1/research/{task_id}/status` | GET | 任务状态+心跳 |
| `/api/v1/research/{task_id}` | GET | 完整研究详情 |
| `/api/v1/research/{task_id}/messages` | GET | 分页消息历史 |
| `/api/v1/research/sessions` | GET | 会话列表 |
| `/api/v1/research/completed` | GET | 已完成研究列表 |
| `/api/v1/research/preview/{task_id}` | GET | HTML预览 |
| `/api/v1/research/sections/{task_id}` | GET | 章节结构 |
| `/api/v1/research/revise` | POST | 修订章节 |
| `/api/v1/research/feedback` | POST | 质量反馈 |
| `/api/v1/research/quality/{session_id}` | GET | 质量状态 |
| `/api/v1/research/quality/action` | POST | 质量操作 |
| `/api/v1/stream/{task_id}` | GET(SSE) | 进度事件流 |
| `/api/v1/session-stream/{session_id}` | GET(SSE) | 会话SSE流 |
| `/api/v1/download/{task_id}` | GET | 文档下载 |
| `/api/v1/upload` | POST | 文件上传 |
| `/api/v1/upload/{file_id}` | DELETE | 删除已上传文件 |
| `/api/v1/llm/models` | GET | 支持的LLM模型 |
| `/api/v1/llm/config` | GET/POST | LLM配置 |
| `/api/v1/llm/config/reset` | POST | 重置LLM配置 |
| `/api/v1/llm/health` | GET | LLM健康检查 |
| `/api/v1/changelog` | GET | 变更日志 |
| `/api/v1/version` | GET | 版本信息 |
| `/api/v1/health` | GET | 健康检查 |

### 13.2 SSE 事件流设计

```
两种SSE通道：

1. 任务进度流 (/api/v1/stream/{task_id})
   └── 生命周期：任务开始 → 任务结束（终止性流）
   └── 事件类型 (SSEEventType枚举)：
       ├── PROGRESS        进度更新
       ├── PHASE_START     阶段开始
       ├── PHASE_COMPLETE  阶段完成
       ├── ERROR           错误事件
       ├── COMPLETE        任务完成
       ├── CANCELLED       任务取消
       ├── PAUSED          任务暂停
       └── RESUMED         任务恢复
   └── 非枚举事件 (直接字符串发送)：
       ├── connected       连接建立
       └── heartbeat       心跳保活

2. 会话持久流 (/api/v1/session-stream/{session_id})
   └── 生命周期：会话创建 → 会话销毁（持久性流）
   └── 事件类型：
       ├── chat_response    对话回复
       ├── agent_message    Agent消息
       ├── quality_result   质量结果
       └── preview_refresh  预览刷新
```

### 13.3 对话工具集

LLM在对话过程中可调用的工具：

| 工具 | 描述 | 超时 |
|------|------|------|
| `get_current_datetime` | 获取当前时间 | 5s |
| `web_search` | 互联网搜索 | 30s |
| `news_search` | 新闻搜索 | 30s |
| `scrape_url` | 网页内容提取 | 20s |

对话工具调用循环最多10轮迭代，确保对话不会无限循环。

---

## 14. 配置体系

### 14.1 配置优先级

```
settings.yaml > system.yaml > .env > 代码默认值
```

### 14.2 配置文件体系

```
config/
├── settings.yaml              # 主运行配置 (LLM、数据库、搜索等)
├── system.yaml                # 系统级配置 (性能参数、限制等)
├── agents.yaml                # Agent专属配置 (每Agent的LLM和能力)
├── keyword_mappings.yaml      # 关键词→技能映射
├── research_frameworks.yaml   # 报告类型框架配置 (521行)
│   └── 每种类型的搜索深度、分析深度、指标定义
├── content_quality.yaml       # 质量阈值配置
├── templates/                 # 报告模板定义 (12种 + 1个Schema)
│   ├── template_schema.yaml   # 模板Schema
│   └── *.yaml                 # 各类型模板
└── document_templates/        # 文档样式模板
    └── *.html                 # HTML/Word/PPT样式

prompts/                       # 外部化LLM Prompt
├── agents/                    # 每Agent的系统和用户Prompt
├── tasks/                     # 每任务阶段的Prompt
├── phases/                    # 阶段级Prompt
└── _shared/                   # 共享Prompt片段
    ├── quality_rubric.md      # 质量评分标准
    └── output_spec.md         # 输出格式规范
```

---

## 15. 前端架构

### 15.1 技术选型

```
Next.js (App Router) + TypeScript
├── 状态管理: Zustand
├── UI框架: shadcn/ui + Tailwind CSS
├── HTTP客户端: Axios
├── 实时通信: SSE (EventSource)
└── 图表: 内置组件
```

### 15.2 前端模块结构

```
web/src/
├── app/                    # Next.js App Router 页面
│   └── [路由页面]
├── components/             # UI组件
│   ├── chat/               # 对话相关组件
│   ├── preview/            # 报告预览组件
│   └── quality/            # 质量展示组件
├── hooks/                  # React Hooks
│   ├── useResearch         # 研究流程Hook
│   └── useProgress         # 进度追踪Hook
├── lib/                    # 工具库
│   ├── api-client          # API客户端
│   └── sse                 # SSE客户端封装
├── store/                  # Zustand状态管理
│   ├── chatStore           # 对话状态
│   ├── sessionStore        # 会话状态
│   └── researchStore       # 研究状态
└── types/                  # TypeScript类型定义
```

### 15.3 前后端交互流程

```
┌──────────┐                          ┌──────────┐
│  Browser  │                          │  FastAPI  │
└─────┬─────┘                          └─────┬─────┘
      │                                      │
      │  POST /research/start                │
      │ ──────────────────────────────────▶  │
      │                                      │ 创建会话
      │  SSE: session-stream                 │ 启动对话
      │ ◀──────────────────────────────────  │
      │                                      │
      │  POST /research/interact             │
      │ ──────────────────────────────────▶  │
      │                                      │ LLM对话
      │  SSE: chat_response                  │
      │ ◀──────────────────────────────────  │
      │                                      │
      │  ...多轮对话...                       │
      │                                      │
      │  POST /research/confirm              │
      │ ──────────────────────────────────▶  │
      │                                      │ 启动研究执行
      │  SSE: stream (进度)                  │
      │ ◀──────────────────────────────────  │
      │  SSE: PROGRESS / PHASE_START / ...   │
      │ ◀──────────────────────────────────  │
      │                                      │
      │  GET /research/preview/{task_id}     │
      │ ──────────────────────────────────▶  │
      │  ◀── HTML预览内容                    │
      │                                      │
      │  POST /research/revise               │
      │ ──────────────────────────────────▶  │
      │                                      │ 修订循环
      │  SSE: preview_refresh                │
      │ ◀──────────────────────────────────  │
      │                                      │
      │  GET /download/{task_id}             │
      │ ──────────────────────────────────▶  │
      │  ◀── 文档文件                        │
      │                                      │
```

---

## 16. 跨域关注点

### 16.1 并发与资源管理

```
├── Agent生命周期管理
│   ├── HIBERNATED状态：空闲Agent释放资源
│   └── 最大并行Agent数限制
│
├── 执行引擎
│   ├── 同阶段Agent并行执行
│   ├── Condition-based等待（非轮询）
│   └── 心跳监控（协调器30秒超时，进度15秒间隔推送）
│
└── 会话写入
    ├── 2秒防抖
    └── 原子写入（temp + rename）
```

### 16.2 错误处理与恢复

```
├── 会话恢复
│   ├── 启动时预加载最近5个会话
│   ├── 懒加载其余会话
│   └── force_set_state() 强制状态恢复
│
├── 任务恢复
│   ├── PAUSED状态可恢复
│   ├── WAL重放保证数据一致性
│   └── Agent失败不阻塞其他Agent
│
├── 降级策略
│   ├── LLM不可用 → 关键词匹配降级
│   ├── 搜索引擎故障 → 降级到备用引擎
│   └── 数据库故障 → 文件存储降级
│
└── 自动修复
    └── 质量检查循环：评分不达标 → 自动修复 → 重新评分
```

### 16.3 安全设计

```
├── 凭证管理
│   ├── cryptography + keyring 安全存储
│   └── .env 文件不入版本控制
│
├── API安全
│   ├── CORS中间件
│   └── 输入验证 (Pydantic v2)
│
├── 数据安全
│   ├── 会话数据本地持久化
│   ├── 报告备份机制
│   └── 对话历史追加式保护（防篡改）
│
└── 操作安全
    ├── 状态感知动作约束
    └── 内容锁防止并发冲突
```

### 16.4 可扩展性

```
├── 技能扩展
│   ├── 技能热加载 (watchdog)
│   ├── LangChain工具自动发现
│   └── 自定义技能目录
│
├── 模板扩展
│   ├── 新增报告模板 (YAML配置)
│   └── 自定义文档样式
│
├── LLM扩展
│   ├── 支持OpenAI / DeepSeek / 其他
│   └── 每Agent可配置不同模型
│
├── 存储扩展
│   ├── SQLite → PostgreSQL 升级路径
│   └── Redis缓存可选启用
│
└── 研究类型扩展
    ├── 新增ResearchType枚举
    ├── 新增DecompositionStrategy
    └── 新增研究框架配置
```

---

## 附录 A：完整端到端流程示例

以"中国新能源汽车行业研究报告"为例，展示完整系统流程：

```
1. 用户输入："帮我做一份中国新能源汽车行业研究报告"
   │
   ▼
2. 会话管理：SessionManager.create() → 会话创建，状态=UNDERSTANDING
   │
   ▼
3. LLM对话循环：
   ├── 系统分析用户意图 → RESEARCH / INDUSTRY_RESEARCH
   ├── 识别隐含需求：市场规模、竞争格局、政策环境、技术趋势
   ├── 生成澄清问题："是否需要包含充电基础设施分析？"
   └── 用户补充 → 更新DialogueIntentState
   │
   ▼
4. 状态转换：UNDERSTANDING → CLARIFYING → FRAMEWORK_CONFIRM
   │
   ▼
5. 框架确认：
   ├── 展示研究框架（章节结构、数据来源、预计时长）
   └── 用户确认 → 状态转EXECUTING
   │
   ▼
6. 智能路由：
   ├── SemanticIntentAnalyzer → DeepIntentResult
   ├── TaskStructureAnalyzer → 8个章节的SectionSpec
   ├── DynamicPhaseOrchestrator → 4阶段ExecutionPlan
   └── WisdomStore推荐：搜索技能+市场分析+政策分析
   │
   ▼
7. Agent创建：DynamicAgentFactory为每个章节创建GenericAgent
   ├── Agent 1: 市场概览 (DATA_COLLECTION)
   ├── Agent 2: 政策环境 (DATA_COLLECTION)
   ├── Agent 3: 竞争格局 (ANALYSIS, 依赖1,2)
   ├── Agent 4: 技术趋势 (DATA_COLLECTION)
   ├── Agent 5: 消费者洞察 (ANALYSIS, 依赖1)
   ├── Agent 6: 供应链分析 (ANALYSIS, 依赖1,4)
   ├── Agent 7: 投资机会 (SYNTHESIS, 依赖3,5,6)
   └── Agent 8: 风险与展望 (SYNTHESIS, 依赖7)
   │
   ▼
8. 并行执行：
   ├── Phase 1: Agent 1,2,4 并行数据采集 (DATA_COLLECTION)
   │   └── 搜索引擎 → 网页抓取 → PDF解析 → 数据提取
   ├── Phase 2: 数据验证 (DATA_VALIDATION)
   ├── Phase 3: Agent 3,5,6 并行深度分析 (DEEP_ANALYSIS)
   │   └── 基于Phase 1数据 + LLM推理 → 结构化章节
   ├── Phase 4: Agent 7,8 综合分析 (SYNTHESIS)
   │   └── 跨章节综合 → 投资建议 → 风险评估
   └── Phase 5: 报告生成 (REPORT_GENERATION)
   │
   ▼
9. 结果聚合：ResultAggregator → 统一报告结构
   │
   ▼
10. 报告升级：ReportOrchestrator → 整合优化
   │
   ▼
11. 预览生成：DocumentGenerationAgent → HTML报告 → SSE推送到前端
   │
   ▼
12. 质量检查：QualityCheckAgent → 评分0.85 > 阈值0.8 → 通过 (max 2 attempts)
   │
   ▼
13. 修订循环：
    ├── 用户："补充换电模式分析" → 新增章节
    ├── RevisionIntentAnalysis → 定位影响范围
    ├── 创建新Agent执行 → 更新报告
    └── 重新预览
   │
   ▼
14. 用户确认 → 文档导出 (DOCX/PPT/PDF)
   │
   ▼
15. 知识沉淀：
    ├── 研究结果 → KnowledgeBank
    ├── 执行经验 → WisdomStore
    └── 方法论更新 → CoreMemory
```

---

## 附录 B：关键源码索引

| 模块 | 路径 | 核心行数 |
|------|------|---------|
| 会话管理 | `src/core/session_manager.py` | L32-103 (持久化), L154-506 (管理器) |
| 会话压缩 | `src/core/compress_adapter.py` | L25 (SessionHistoryCompressor) |
| 对话状态机 | `src/core/dialogue/state_machine.py` | L45-92 (状态转换) |
| 意图状态 | `src/core/dialogue/dialogue_intent_state.py` | 全文 |
| 子意图/就绪度 | `src/core/dialogue/sub_intent.py` | L15-18 (ReadinessLevel) |
| 意图类型 | `src/core/intent_types.py` | L33-49 |
| 语义意图分析 | `src/core/semantic_intent.py` | L32-62 (DeepIntentResult, 28字段) |
| 研究类型 | `src/core/research_type.py` | 全文 |
| 智能路由 | `src/core/intelligent_routing_adapter.py` | L624-667 (能力模板) |
| 研究编排器 | `src/core/orchestrator/orchestrator.py` | L424-1500+ (核心流程) |
| 执行引擎 | `src/core/orchestrator/execution/engine.py` | 全文 |
| 结果聚合 | `src/core/orchestrator/aggregation/` | 全文 |
| 通用Agent | `src/core/agents/generic_agent.py` | 全文 (5216行) |
| 搜索技能 | `src/skills/search_skill.py` | 全文 |
| 网页抓取 | `src/skills/web_scraper_skill.py` | 全文 |
| 技能注册 | `src/skills/registry.py` | L269-347 |
| 研究API | `src/api/research_api.py` | L60-168 (工具集), L538-569 (动作约束) |
| API主入口 | `src/api/main.py` | 全文 |
| 执行器 | `src/api/research_executor.py` | 全文 |
| 进度推送 | `src/core/progress_streamer.py` | 全文 |
| 知识管理 | `src/core/memory/` | 全文 |
| 问卷系统 | `src/survey/` | 全文 |
| 文档生成 | `src/agents/fixed_agents/document_generation_agent.py` | 全文 |
| 配置中心 | `config/settings.yaml` | 全文 |
| 框架配置 | `config/research_frameworks.yaml` | 全文 |
| 意图Prompt | `prompts/agents/intent_analysis_system.md` | 全文 |
| 质量标准 | `prompts/_shared/quality_rubric.md` | 全文 |
