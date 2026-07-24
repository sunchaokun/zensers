# 11 — MCP 协议层

> 章节定位：理解系统如何通过标准协议与外部工具集成。

---

## 1. MCP 协议定位

MCP（Model Context Protocol）是位于 Agent 和外部工具之间的**标准协议层**，规范外部工具的发现、调用和认证。

```
GenericAgent.execute({action, parameters})
    │
    ├── action="search" -----> SkillRegistry ---> search_skill, llm_skill, ...
    │
    └── action="mcp" --------> MCP Protocol Layer --> MCP Servers
                                    │
                                    ├── wind.get_stock_data
                                    ├── slack.send_message
                                    └── github.create_pr
```

**MCP vs Skill**：
- Skills = 系统内部能力（搜索、LLM、文件操作），紧耦合
- MCP Tools = 外部能力（Wind 数据、Slack、GitHub），通过标准协议松耦合

## 2. 架构组件

| 组件 | 职责 | 文件 |
|------|------|------|
| MCPClient | MCP 服务器连接和工具调用（本地/远程模式） | `core/mcp/client.py` |
| MCPServer | 本地 MCP 服务器（工具注册、请求处理） | `core/mcp/server.py` |
| ToolRegistry | 工具注册中心 | `core/mcp/tool_registry.py` |
| CredentialManager | 三级凭证管理（会话 > 用户 > 系统） | `core/mcp/credentials.py` |
| RateLimiter | 令牌桶限流 | `core/mcp/rate_limiter.py` |
| MCPProtocolHandler | 协议路由 | `core/mcp/handler.py` |
| MCPToolMatcher | 智能路由工具匹配 | `core/decomposition/mcp_matcher.py` |

## 3. 数据流

```
Orchestrator 分解任务 → Agent 需要 Wind 数据
    → GenericAgent.execute({action: "mcp", tool: "wind.get_stock_data"})
    → MCPProtocolHandler 解析工具名 → 定位 MCP Server
    → CredentialManager 提供 API Key
    → RateLimiter 检查配额
    → MCPClient 调用远程 SSE/HTTP 端点
    → 原始数据返回 → LLM 处理 → 标准 {content, data_points, sources} 输出
    → Engine 收集 → Aggregator 合并 → 报告生成
```

**关键设计决策**：MCP 返回原始数据不做格式转换，LLM 能自然理解任何 JSON 结构。

## 4. 凭证管理

三级凭证模型：

| 级别 | 优先级 | 有效期 | 示例 |
|------|--------|--------|------|
| 会话级 Session | 最高 | 会话内 | 用户本次会话提供的临时 Key |
| 用户级 User | 中 | 用户设置 | API Key |
| 系统级 System | 最低 | 系统配置 | 默认 Key |

## 5. 完成状态

MCP 协议层已完成全部 5 个 Phases：

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 1 基础设施 | CredentialManager, RateLimiter, MCPClient | ✅ 完成 |
| Phase 2 协议层 | MCPProtocolHandler, action="mcp" 路由 | ✅ 完成 |
| Phase 3 智能路由 | MCPToolMatcher, mcp_tools 注入 | ✅ 完成 |
| Phase 4 可观测性 | MCPLogger, MCPHealthChecker, SecureCredentialStorage | ✅ 完成 |
| Phase 5 测试文档 | 合约测试 48 项通过，部署指南 | ✅ 完成 |

## 6. 原始文档溯源

- `ARCHITECTURE.md` §3.6 — MCP 协议层
- `src/core/mcp/` — MCP 全部实现
- `src/core/decomposition/mcp_matcher.py` — 工具匹配
