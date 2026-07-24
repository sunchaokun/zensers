# CLI 模块更新实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构和增强 Zensers CLI 模块，建立独立会话区（对话窗口 + 会话记录），统一架构风格，补充缺失功能，提升用户体验。

**Architecture:** 以 typer + rich 为基础框架，建立 `session` 作为核心会话区概念——CLI 用户通过 `session start` 进入持久化对话窗口，所有交互（research/chat/revise）都在会话上下文中进行，对话历史可查询回溯。将 main.py 中的巨型函数拆分为独立模块，统一所有命令使用 ZensersClient 进行 API 通信，添加配置持久化、shell 补全等能力。

**Tech Stack:** Python 3.10+, typer, rich, httpx, questionary

---

## 现状分析

### 已识别问题

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| P1 | `main.py` 的 `_research_async` 函数长达 320 行，交互回调逻辑与命令逻辑混杂 | 高 | `src/cli/main.py:98-487` |
| P2 | `session.py` 中部分命令直接用 httpx 调 API，部分用 Orchestrator 本地调用，风格不统一 | 高 | `src/cli/commands/session.py` |
| P3 | `main.py` 中的 `status`/`download` 命令直接用 httpx 而非 ZensersClient | 高 | `src/cli/main.py:490-612` |
| P4 | `chat.py` 仅是空壳 scaffold，无实际 LLM 对话功能 | 中 | `src/cli/commands/chat.py` |
| P5 | 错误处理不一致：有的 raise typer.Exit(1)，有的仅 print，有的吞掉异常 | 中 | 全局 |
| P6 | `utils.py` 中 API_BASE_URL 用全局变量，非线程安全 | 低 | `src/cli/utils.py:41-48` |
| P7 | 缺少 `--api-url` 全局选项，只能通过环境变量设置 API 地址 | 中 | `src/cli/main.py` |
| P8 | 缺少 shell 自动补全支持 | 低 | - |
| P9 | `config` 命令配置文件与实际使用脱节（写了配置但没地方读） | 中 | `src/cli/main.py:617-643` |
| P10 | 测试文件引用了不存在的 `_format_markdown_report` 函数和 `TaskStorage` | 高 | `tests/unit/cli/test_cli.py` |
| P11 | 帮助文本中英文混杂 | 低 | 全局 |
| P12 | 缺少 `--no-color` / `--json` 输出选项 | 低 | - |
| P13 | **无独立会话区**：CLI 没有持久化对话窗口，每次 research 是一次性执行，无法查看/回溯对话历史，无法在会话上下文中持续交互 | 高 | 全局 |
| P14 | **session 命令定位错乱**：现有 session 子命令（list/show/resume/pause/cancel）混合了"会话管理"和"任务控制"，没有"进入对话窗口"的概念 | 高 | `src/cli/commands/session.py` |
| P15 | **chat 与 session 割裂**：chat 是独立空壳，session 是任务管理，两者没有统一到"会话区"概念下 | 中 | `src/cli/commands/chat.py`, `session.py` |

### 更新范围

1. **会话区建设** — 建立独立对话窗口和会话记录体系，这是本次更新的核心
2. **架构重构** — 拆分 main.py 巨型函数，统一 API 调用风格
3. **功能增强** — 全局选项、配置持久化、JSON 输出、llm set-config
4. **质量修复** — 错误处理统一化、测试修复
5. **体验提升** — shell 补全、进度条优化、输出格式化

---

## 会话区设计

### 核心概念

当前 CLI 的根本问题是**没有会话区**。Web UI 用户可以在一个会话窗口中持续对话，但 CLI 用户每次运行 `research` 都是一次性执行，无法：

- 查看和回溯对话历史
- 在同一个会话中连续交互（修改、修订、确认）
- 暂停后回到同一个对话窗口继续

### 会话区模型

```
┌─────────────────────────────────────────────┐
│              CLI 会话区 (Session)             │
│                                              │
│  session start ──→ 进入交互式对话窗口        │
│       │                                      │
│       ├── 用户输入 ──→ API interact           │
│       ├── /history  ──→ 查看对话记录          │
│       ├── /status   ──→ 查看当前状态          │
│       ├── /revise   ──→ 修订报告              │
│       ├── /confirm  ──→ 确认生成              │
│       ├── /export   ──→ 导出文档              │
│       ├── /quit     ──→ 退出对话窗口          │
│       └── 普通消息  ──→ LLM 对话/研究交互     │
│                                              │
│  session list   ──→ 列出所有会话              │
│  session show   ──→ 查看会话详情              │
│  session attach ──→ 重新进入已有会话          │
│  session history──→ 查看某会话对话记录        │
│  session delete ──→ 删除会话                  │
│                                              │
│  对话记录持久化: data/sessions/{id}.json      │
│  (复用服务端 SessionManager 已有的持久化)      │
└─────────────────────────────────────────────┘
```

### 命令重规划

| 原命令 | 新归属 | 说明 |
|--------|--------|------|
| `session list` | `session list` | 保留，列出所有会话 |
| `session show` | `session show` | 保留，查看会话详情 |
| `session resume` | `session attach` | 重命名，更准确表达"重新进入对话窗口" |
| `session pause` | `task pause` | 移到新 task 子组 |
| `session cancel` | `task cancel` | 移到新 task 子组 |
| `session status` | `session status` | 保留，查看会话状态 |
| `session modify` | `session modify` | 保留，修改研究需求 |
| `session confirm` | `session confirm` | 保留，确认生成 |
| `session revise` | `session revise` | 保留，修订 |
| (新增) | `session start` | **核心**：开启新会话并进入交互式对话窗口 |
| (新增) | `session attach` | 重新进入已有会话的对话窗口 |
| (新增) | `session history` | 查看某会话的对话记录 |
| (新增) | `session delete` | 删除会话 |
| (新增) | `task pause/cancel/status` | 任务控制子组 |
| `chat start` | 合并到 `session start` | chat 不再独立，统一为会话模式 |

### 交互式对话窗口

`session start` 和 `session attach` 会进入一个交互式对话循环（REPL），支持：

- **普通文本** → 发送到 `/api/v1/research/interact` 进行对话
- **`/history`** → 显示当前会话的对话历史（从 `/api/v1/research/{task_id}/messages` 获取）
- **`/status`** → 显示当前会话状态和进度
- **`/revise <section>`** → 修订指定章节
- **`/confirm`** → 确认预览并生成文档
- **`/export [format]`** → 导出文档
- **`/help`** → 显示帮助
- **`/quit`** → 退出对话窗口

### 与服务端的关系

服务端已有完整的会话管理（`SessionManager` + `data/sessions/`），CLI 会话区通过 API 桥接：

```
CLI session start ──→ POST /api/v1/research/start ──→ 服务端创建 session
CLI 用户输入     ──→ POST /api/v1/research/interact → 服务端处理消息
CLI /history     ──→ GET  /api/v1/research/{id}/messages → 服务端返回历史
CLI /status      ──→ GET  /api/v1/research/{id}/status  → 服务端返回状态
```

---

## 文件结构

```
src/cli/
├── __init__.py              # 保持不变
├── __main__.py              # 保持不变
├── main.py                  # 精简：仅全局选项 + 命令注册 + 入口
├── client.py                # 增强：添加上下文管理器、重试、错误映射、interact/messages API
├── utils.py                 # 增强：配置管理、JSON 输出、全局状态
├── interaction.py           # 新建：从 main.py 提取的交互回调逻辑（research 交互式确认）
├── repl.py                  # 新建：会话区交互式对话窗口（REPL 循环）
├── commands/
│   ├── __init__.py          # 更新：注册新模块
│   ├── session.py           # 重构：会话区核心（start/attach/history/delete + 交互窗口）
│   ├── task.py              # 新建：任务控制子组（pause/cancel/status），从 session.py 拆出
│   ├── knowledge.py         # 保持不变（本地调用合理）
│   ├── chat.py              # 删除：功能合并到 session start
│   ├── survey.py            # 保持不变
│   ├── mcp.py               # 保持不变
│   ├── llm.py               # 增强：添加 set-config 命令
│   ├── prompt.py            # 保持不变
│   ├── document.py          # 保持不变
│   └── upload.py            # 保持不变
tests/unit/cli/
├── test_cli.py              # 重写：修复过时引用，覆盖新功能
├── test_interaction.py      # 新建：交互回调单元测试
├── test_client.py           # 新建：ZensersClient 增强测试
├── test_repl.py             # 新建：REPL 对话窗口测试
└── test_session_commands.py # 新建：会话区命令测试
```

---

## Task 1: 提取交互回调到独立模块

**Files:**
- Create: `src/cli/interaction.py`
- Modify: `src/cli/main.py`

**目标：** 将 `_research_async` 中 320 行的 `interaction_callback` 内联函数提取为独立模块，使 main.py 的 research 命令精简到 ~80 行。

- [ ] **Step 1: 创建 `src/cli/interaction.py`，提取交互回调**

```python
"""CLI interactive callback handlers for research workflow."""
import logging
from typing import Dict, Any, Optional, Callable, Awaitable

from rich.console import Console

from src.cli.utils import console as default_console

logger = logging.getLogger(__name__)


async def build_interaction_callback(
    console: Console = default_console,
) -> Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]:
    """Build the interaction callback for CLI research mode."""
    try:
        import questionary
    except ImportError:
        console.print("[red]Interactive mode requires questionary library. Run: pip install questionary[/red]")
        raise SystemExit(1)

    async def interaction_callback(step_data: dict) -> dict:
        step_type = step_data.get("step", "unknown")
        next_step = step_data.get("next_step", "")
        step_type_str = str(step_type)
        options = step_data.get("options", [])
        instruction = step_data.get("instruction", step_data.get("message", "Please select:"))

        if options:
            return await _handle_options(questionary, console, step_data, options, instruction, next_step)

        framework_options = step_data.get("framework_options", [])
        if framework_options:
            return await _handle_framework(questionary, console, step_data, framework_options, instruction)

        sections_detail = step_data.get("sections_detail", [])
        if sections_detail:
            return await _handle_sections(questionary, console, step_data, sections_detail, instruction, interaction_callback)

        parameters = step_data.get("parameters", {})
        if parameters:
            return await _handle_parameters(questionary, console, step_data, parameters, instruction)

        summary = step_data.get("summary", {})
        if summary or step_data.get("next_step") == "confirm_research":
            return await _handle_summary(questionary, console, step_data, summary, instruction)

        if step_type_str == "preview":
            return await _handle_preview(questionary, console, step_data, instruction)

        return await _handle_fallback(questionary, console, step_data)

    return interaction_callback


async def _handle_options(questionary, console, step_data, options, instruction, next_step):
    console.print(f"\n[cyan]{instruction}[/cyan]")
    choices = []
    for opt in options:
        if isinstance(opt, dict):
            label = opt.get("label", opt.get("value", str(opt)))
            desc = opt.get("desc", opt.get("description", ""))
            choices.append(f"{label} - {desc}" if desc else label)
        else:
            choices.append(str(opt))

    selected = await questionary.select(
        "Please select:",
        choices=choices,
        style=questionary.Style([
            ('selected', 'fg:green bold'),
            ('pointer', 'fg:green bold'),
            ('question', 'fg:cyan bold'),
        ])
    ).ask_async()

    if selected is None:
        return {"confirmed": False, "cancelled": True}

    selected_idx = choices.index(selected)
    if selected_idx < len(options) and isinstance(options[selected_idx], dict):
        selected_value = options[selected_idx].get("value", selected)
    else:
        selected_value = selected

    if next_step == "select_output_type":
        return {"output_type": selected_value}
    elif next_step == "select_template":
        return {"template_id": selected_value}
    return {"selected": selected_value, "answer": selected_value}


async def _handle_framework(questionary, console, step_data, framework_options, instruction):
    console.print(f"\n[cyan]{instruction}[/cyan]")
    choices = []
    for fw in framework_options:
        name = fw.get("name", fw.get("id", "Unknown option"))
        desc = fw.get("description", "")
        pages = fw.get("estimated_pages", "")
        sections = fw.get("section_names", [])
        choice_text = f"{name} - {desc}"
        if pages:
            choice_text += f" ({pages})"
        choices.append(choice_text)
        if sections:
            console.print(f"  [dim]{name} includes: {', '.join(sections[:5])}{'...' if len(sections) > 5 else ''}[/dim]")

    selected = await questionary.select("Please select research framework:", choices=choices).ask_async()
    if selected is None:
        return {"confirmed": False}
    selected_idx = choices.index(selected)
    framework_id = framework_options[selected_idx].get("id", "standard") if selected_idx < len(framework_options) else "standard"
    return {"framework_id": framework_id}


async def _handle_sections(questionary, console, step_data, sections_detail, instruction, interaction_callback):
    console.print(f"\n[cyan]{instruction}[/cyan]")
    console.print(f"\n[bold]Research Section List:[/bold]")
    for i, section in enumerate(sections_detail, 1):
        name = section.get("name", section.get("id", "Unknown section"))
        content = section.get("content", "Content to be confirmed")
        console.print(f"  [green]{i}. {name}[/green]")
        console.print(f"     [dim]Research content: {content}[/dim]")

    action = await questionary.select(
        "\nPlease confirm section content:",
        choices=["Confirm, proceed to next step", "Need to adjust sections", "Go back to previous step (re-select framework)", "Cancel research"],
    ).ask_async()

    if action == "Confirm, proceed to next step":
        return {"confirmed": True}
    elif action == "Need to adjust sections":
        section_names = [s.get("name", s.get("id", "")) for s in sections_detail]
        kept_sections = await questionary.checkbox(
            "Please select sections to keep (space to select, enter to confirm, ESC to cancel):",
            choices=section_names,
        ).ask_async()
        if kept_sections is None:
            return await interaction_callback(step_data)
        kept_sections = [s for s in kept_sections if s in section_names]
        if not kept_sections:
            kept_sections = section_names
        adjustments = [{"id": s.get("id", s.get("name", "")), "keep": s.get("name", s.get("id", "")) in kept_sections} for s in sections_detail]
        return {"confirmed": True, "adjustments": adjustments}
    elif action == "Go back to previous step (re-select framework)":
        return {"go_back": True}
    return {"confirmed": False}


async def _handle_parameters(questionary, console, step_data, parameters, instruction):
    console.print(f"\n[cyan]{instruction}[/cyan]")
    result = {}
    param_list = []
    if isinstance(parameters, dict):
        param_list = parameters.get("parameters", [])
        if not param_list:
            for legacy_key in ("region", "time_range", "depth"):
                legacy_param = parameters.get(legacy_key)
                if isinstance(legacy_param, dict):
                    param_list.append({"id": legacy_key, "type": "select", "label": legacy_param.get("label", legacy_key), "default": legacy_param.get("default", ""), "options": [{"value": o, "label": o} for o in legacy_param.get("options", [])]})
    elif isinstance(parameters, list):
        param_list = parameters

    for param in param_list:
        param_id = param.get("id", "")
        param_type = param.get("type", "select")
        param_label = param.get("label", param_id)
        param_default = param.get("default")
        param_options = param.get("options", [])
        param_placeholder = param.get("placeholder", "")

        if param_type == "text":
            prompt_text = f"{param_label}:"
            if param_placeholder:
                prompt_text += f" ({param_placeholder})"
            value = await questionary.text(prompt_text, default=str(param_default) if param_default else "").ask_async()
            result[param_id] = value if value else param_default
        elif param_type in ("select",):
            option_labels = [opt.get("label", opt.get("value", "")) for opt in param_options]
            if len(option_labels) > 1 or param.get("required", False):
                selected = await questionary.select(param_label, choices=option_labels).ask_async()
                if selected:
                    selected_idx = option_labels.index(selected)
                    result[param_id] = param_options[selected_idx].get("value", selected)
                else:
                    result[param_id] = param_default
            else:
                result[param_id] = param_default
        elif param_type == "multi_select":
            option_labels = [opt.get("label", opt.get("value", "")) for opt in param_options]
            selected = await questionary.checkbox(f"{param_label} (space to select, enter to confirm):", choices=option_labels).ask_async()
            if selected:
                result[param_id] = [param_options[option_labels.index(sel)].get("value", sel) for sel in selected]
            else:
                result[param_id] = param_default if param_default else []
        elif param_type == "date":
            value = await questionary.text(f"{param_label} (YYYY-MM-DD):", default=str(param_default) if param_default else "").ask_async()
            result[param_id] = value or param_default
        else:
            value = await questionary.text(f"{param_label}:", default=str(param_default) if param_default else "").ask_async()
            result[param_id] = value or param_default
    return result


async def _handle_summary(questionary, console, step_data, summary, instruction):
    console.print(f"\n[cyan]{instruction}[/cyan]")
    if summary:
        console.print(f"  [bold]Research Topic:[/bold] {summary.get('topic', 'N/A')}")
        console.print(f"  [bold]Report Type:[/bold] {summary.get('output_type', 'N/A')}")
        console.print(f"  [bold]Region:[/bold] {summary.get('region', 'N/A')}")
        console.print(f"  [bold]Time Range:[/bold] {summary.get('time_range', 'N/A')}")
        console.print(f"  [bold]Sections:[/bold] {', '.join(summary.get('sections', []))}")
    action = await questionary.select("Confirm to start research?", choices=["Confirm and start", "Cancel"]).ask_async()
    return {"confirmed": action == "Confirm and start"}


async def _handle_preview(questionary, console, step_data, instruction):
    preview_url = step_data.get("preview_url", "")
    actions = step_data.get("actions", ["confirm", "revise", "cancel"])
    console.print(f"\n[cyan]{instruction}[/cyan]")
    if preview_url:
        console.print(f"  [dim]Preview file: {preview_url}[/dim]")

    action_choices = []
    action_map = {}
    if "confirm" in actions:
        action_choices.append("Confirm and finalize")
        action_map["Confirm and finalize"] = "confirm"
    if "revise" in actions:
        action_choices.append("Needs revision")
        action_map["Needs revision"] = "revise"
    if "cancel" in actions:
        action_choices.append("Cancel")
        action_map["Cancel"] = "cancel"
    if not action_choices:
        action_choices = ["Confirm and finalize", "Needs revision", "Cancel"]
        action_map = {"Confirm and finalize": "confirm", "Needs revision": "revise", "Cancel": "cancel"}

    selected = await questionary.select("Please select action:", choices=action_choices).ask_async()
    action_value = action_map.get(selected, "confirm")
    if action_value == "revise":
        revision_input = await questionary.text("Please enter revision suggestion (e.g., add market size data):").ask_async()
        return {"action": "revise", "adjustment": revision_input or "Please improve content quality"}
    return {"action": action_value}


async def _handle_fallback(questionary, console, step_data):
    console.print(f"[dim]Step data: {step_data}[/dim]")
    action = await questionary.select("Please select action:", choices=["Continue", "Cancel"]).ask_async()
    return {"confirmed": action == "Continue"}
```

- [ ] **Step 2: 重构 `src/cli/main.py` 的 research 命令，使用提取的交互模块**

将 `_research_async` 中的内联 `interaction_callback` 替换为调用 `build_interaction_callback()`。重构后 `_research_async` 应从 320 行缩减到 ~80 行：

```python
async def _research_async(
    requirement: str,
    output: Optional[str],
    format: str,
    verbose: bool,
    interactive: bool,
    aspects: Optional[List[str]] = None,
    framework: Optional[str] = None,
    template: Optional[str] = None,
    output_type: Optional[str] = None,
):
    from src.core.orchestrator import ResearchOrchestrator as Orchestrator
    from src.cli.interaction import build_interaction_callback

    console.print(Panel.fit(
        f"[bold blue]Zensers[/bold blue] - Starting Research Task\n"
        f"[dim]Requirement: {requirement[:50]}{'...' if len(requirement) > 50 else ''}[/dim]"
    ))

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Initializing research system...", total=None)
        orchestrator = Orchestrator()
        progress.update(task, description="System ready")
        progress.update(task, description="Executing research workflow...")
        try:
            callback = await build_interaction_callback(console) if interactive else None
            result = await orchestrator.research(
                requirement,
                output_dir=output,
                interaction_mode=interactive,
                interaction_callback=callback,
                output_type=output_type,
                custom_aspects=aspects,
                framework=framework,
                template_name=template,
                output_format=format,
            )
            progress.update(task, description="Research complete")
        except Exception as e:
            logger.error(f"Research execution failed: {e}", exc_info=True)
            console.print(f"[red]Research execution failed: {e}[/red]")
            raise typer.Exit(1)

    _print_research_result(result, output)


def _print_research_result(result, output: Optional[str]):
    """Print research result summary."""
    if result.status == "completed":
        console.print("\n[green]✓ Research task completed![/green]")
        table = Table(title="Report Information")
        table.add_column("Item", style="cyan")
        table.add_column("Content", style="green")
        table.add_row("Task ID", result.task_id)
        table.add_row("Topic", result.topic)
        table.add_row("Status", result.status)
        table.add_row("Output Path", str(result.output_path))
        table.add_row("Used Agents", ", ".join(result.agents_used))
        console.print(table)

        if output and result.document_path:
            import shutil
            src_path = Path(result.document_path)
            dst_path = Path(output)
            if src_path.exists():
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dst_path)
                console.print(f"\n[green]Report saved: {output}[/green]")
            else:
                console.print(f"\n[yellow]Warning: Document path does not exist {result.document_path}[/yellow]")
        elif output and not result.document_path:
            console.print(f"\n[yellow]Warning: Research complete but no document generated, cannot save to {output}[/yellow]")

        if result.document_path:
            console.print(f"\n[green]Report generated: {result.document_path}[/green]")
        console.print("[dim]Use python -m src.cli.main session list to view historical tasks[/dim]")
        console.print("[dim]Use python -m src.cli.main session resume <task_id> to resume task[/dim]")
    else:
        console.print(f"\n[red]Research failed: {result.status}[/red]")
        raise typer.Exit(1)
```

- [ ] **Step 3: 验证重构后 CLI 正常工作**

Run: `python -m src.cli.main --help`
Expected: 输出帮助信息，包含 research/status/download/config/version/changelog 及所有子命令组

- [ ] **Step 4: Commit**

```bash
git add src/cli/interaction.py src/cli/main.py
git commit -m "refactor: extract interaction callback from main.py to interaction.py"
```

---

## Task 2: 统一 session.py 使用 ZensersClient

**Files:**
- Modify: `src/cli/commands/session.py`
- Modify: `src/cli/client.py`

**目标：** 消除 session.py 中直接使用 httpx 的代码，统一通过 ZensersClient 调用 API；同时为 ZensersClient 添加 `research_interact` 等缺失的方法。

- [ ] **Step 1: 在 `src/cli/client.py` 添加缺失的 API 方法**

在 `ZensersClient` 类中添加以下方法（在 `research_feedback` 方法之后）：

```python
    async def research_interact(self, session_id: str, user_message: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        data: Dict[str, str] = {"session_id": session_id, "user_message": user_message}
        if user_id:
            data["user_id"] = user_id
        r = await self._http.post(f"{self._base_url}/api/v1/research/interact", data=data)
        r.raise_for_status()
        return r.json()

    async def research_quality_action(self, session_id: str, action: str, **kwargs) -> Dict[str, Any]:
        data: Dict[str, str] = {"session_id": session_id, "action": action}
        for k, v in kwargs.items():
            if v is not None:
                data[k] = str(v) if not isinstance(v, str) else v
        r = await self._http.post(f"{self._base_url}/api/v1/research/quality/action", data=data)
        r.raise_for_status()
        return r.json()

    async def research_quality(self, session_id: str) -> Dict[str, Any]:
        r = await self._http.get(f"{self._base_url}/api/v1/research/quality/{session_id}")
        r.raise_for_status()
        return r.json()

    async def research_preview(self, task_id: str) -> Dict[str, Any]:
        r = await self._http.get(f"{self._base_url}/api/v1/research/preview/{task_id}")
        r.raise_for_status()
        return r.json()

    async def research_sections(self, task_id: str) -> Dict[str, Any]:
        r = await self._http.get(f"{self._base_url}/api/v1/research/sections/{task_id}")
        r.raise_for_status()
        return r.json()

    async def research_messages(self, task_id: str) -> Dict[str, Any]:
        r = await self._http.get(f"{self._base_url}/api/v1/research/{task_id}/messages")
        r.raise_for_status()
        return r.json()

    async def llm_set_config(self, provider: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None, api_endpoint: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if api_key:
            payload["apiKey"] = api_key
        if api_endpoint:
            payload["apiEndpoint"] = api_endpoint
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["maxTokens"] = max_tokens
        r = await self._http.post(f"{self._base_url}/api/v1/llm/config", json=payload)
        r.raise_for_status()
        return r.json()

    async def llm_reset_config(self) -> Dict[str, Any]:
        r = await self._http.post(f"{self._base_url}/api/v1/llm/config/reset")
        r.raise_for_status()
        return r.json()
```

同时为 `ZensersClient` 添加上下文管理器支持：

```python
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

- [ ] **Step 2: 重构 `session.py` 中所有 `_session_pause`/`_session_cancel`/`_session_status`/`_session_modify` 函数，替换 httpx 为 ZensersClient**

将 `_session_pause` 改为：

```python
async def _session_pause(task_id: str):
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        try:
            result = await client.research_pause(task_id)
        except Exception as e:
            console.print(f"[red]Pause failed: {e}[/red]")
            return
    if result.get("status") == "paused":
        console.print(f"[green]✓ Task paused: {task_id}[/green]")
    else:
        console.print(f"[yellow]Pause result: {result.get('message', 'unknown')}[/yellow]")
```

同理替换 `_session_cancel`、`_session_status`、`_session_modify` 中的 httpx 调用。

- [ ] **Step 3: 验证 session 命令**

Run: `python -m src.cli.main session --help`
Expected: 列出所有 session 子命令

- [ ] **Step 4: Commit**

```bash
git add src/cli/client.py src/cli/commands/session.py
git commit -m "refactor: unify session commands to use ZensersClient, add missing API methods"
```

---

## Task 3: 统一 main.py 顶层命令使用 ZensersClient

**Files:**
- Modify: `src/cli/main.py`

**目标：** 将 `status`、`download` 命令中的直接 httpx 调用替换为 ZensersClient。

- [ ] **Step 1: 重构 `_get_task_status_remote` 和 `_list_active_tasks_remote`**

```python
async def _get_task_status_remote(task_id: str, watch: bool):
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        if watch:
            console.print(f"[dim]Monitoring task {task_id} (press Ctrl+C to stop)...[/dim]\n")
            try:
                while True:
                    result = await client.research_status(task_id)
                    console.print(f"[dim]Status: {result.get('status', 'unknown')}[/dim]")
                    if result.get("status") in ("completed", "failed", "cancelled"):
                        break
                    await asyncio.sleep(2)
            except KeyboardInterrupt:
                console.print("\n[dim]Monitoring stopped[/dim]")
        else:
            result = await client.research_status(task_id)
            console.print(f"Status: {result.get('status', 'unknown')}")
            if result.get("topic"):
                console.print(f"Topic: {result['topic']}")
            if result.get("progress"):
                console.print(f"Progress: {result['progress']}")


async def _list_active_tasks_remote():
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        try:
            result = await client.research_sessions(limit=50)
        except Exception as e:
            console.print(f"[red]Failed to list active tasks: {e}[/red]")
            raise typer.Exit(1)

    sessions = result.get("sessions", [])
    active = [s for s in sessions if s.get("status") in ("analyzing", "reporting", "paused")]
    if not active:
        console.print("[dim]No active tasks[/dim]")
        return

    table = Table(title=f"Active Tasks ({len(active)} total)")
    table.add_column("Task ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Topic", style="yellow")
    table.add_column("Created At", style="dim")
    for s in active:
        table.add_row(s.get("task_id", "N/A")[:12], s.get("status", "unknown"), s.get("topic", "")[:30], s.get("created_at", "")[:19])
    console.print(table)
```

- [ ] **Step 2: 重构 `_download_report`**

```python
async def _download_report(task_id: str, output: str, format: str):
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        try:
            content, content_type = await client.download(task_id)
        except FileNotFoundError:
            console.print(f"[red]Report not found: {task_id}[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Download failed: {e}[/red]")
            raise typer.Exit(1)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    console.print(f"[green]Report downloaded: {output_path} ({len(content)} bytes)[/green]")
```

- [ ] **Step 3: 从 main.py 移除对 httpx 的直接依赖**

确认 main.py 顶部不再 import httpx。

- [ ] **Step 4: 验证命令**

Run: `python -m src.cli.main status --help && python -m src.cli.main download --help`
Expected: 两个命令帮助正常输出

- [ ] **Step 5: Commit**

```bash
git add src/cli/main.py
git commit -m "refactor: replace direct httpx calls in main.py with ZensersClient"
```

---

## Task 4: 增强 ZensersClient — 错误处理和重试

**Files:**
- Modify: `src/cli/client.py`

**目标：** 为 ZensersClient 添加统一错误映射和可选重试机制，使上层命令代码更简洁。

- [ ] **Step 1: 在 `client.py` 顶部添加自定义异常类**

```python
class ZensersError(Exception):
    """Base exception for Zensers CLI errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ZensersConnectionError(ZensersError):
    """Server unreachable."""
    pass


class ZensersNotFoundError(ZensersError):
    """Resource not found (404)."""
    pass


class ZensersServerError(ZensersError):
    """Server-side error (5xx)."""
    pass
```

- [ ] **Step 2: 添加 `_request` 辅助方法统一错误处理**

在 `ZensersClient` 类中添加：

```python
    async def _request(self, method: str, url: str, *, raise_on_404: bool = True, **kwargs) -> httpx.Response:
        try:
            r = await self._http.request(method, url, **kwargs)
        except httpx.ConnectError:
            raise ZensersConnectionError("Connection refused: server not running")
        except httpx.TimeoutException:
            raise ZensersConnectionError("Request timed out")
        if r.status_code == 404 and raise_on_404:
            raise ZensersNotFoundError(f"Resource not found: {url}", status_code=404)
        if r.status_code >= 500:
            raise ZensersServerError(f"Server error: HTTP {r.status_code}", status_code=r.status_code)
        r.raise_for_status()
        return r
```

- [ ] **Step 3: 逐步替换现有方法中的 `r = await self._http.xxx` 为 `r = await self._request(...)`**

注意：这是一个渐进式改动，每个方法改一行。例如 `research_pause`：

```python
    async def research_pause(self, task_id: str) -> Dict[str, Any]:
        r = await self._request("POST", f"{self._base_url}/api/v1/research/{task_id}/pause")
        return r.json()
```

对所有方法逐一替换。

- [ ] **Step 4: 验证**

Run: `python -c "from src.cli.client import ZensersClient, ZensersError; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add src/cli/client.py
git commit -m "feat: add ZensersError hierarchy and unified _request method to ZensersClient"
```

---

## Task 5: 增强全局选项和配置管理

**Files:**
- Modify: `src/cli/main.py`
- Modify: `src/cli/utils.py`

**目标：** 添加 `--api-url`、`--no-color`、`--json` 全局选项；增强配置管理使其真正生效。

- [ ] **Step 1: 在 `utils.py` 中添加配置管理类**

```python
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class CLIConfig:
    default_output_format: str = "markdown"
    auto_save_reports: bool = True
    max_concurrent_tasks: int = 3
    api_base_url: str = ""
    default_language: str = "zh"

    @classmethod
    def load(cls) -> "CLIConfig":
        config_path = Path.home() / ".zensers" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        config_path = Path.home() / ".zensers" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @staticmethod
    def config_path() -> Path:
        return Path.home() / ".zensers" / "config.json"


_output_json: bool = False

def set_output_json(value: bool) -> None:
    global _output_json
    _output_json = value

def is_output_json() -> bool:
    return _output_json
```

- [ ] **Step 2: 在 `main.py` 中添加 typer callback 处理全局选项**

```python
@app.callback()
def global_options(
    api_url: Optional[str] = typer.Option(None, "--api-url", envvar="ZENSERS_API_URL", help="API server base URL"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    json_output: bool = typer.Option(False, "--json", help="Output in JSON format"),
):
    """Zensers - Automated Industry Research System."""
    if api_url:
        set_api_base_url(api_url)
    if no_color:
        console.no_color = True
    if json_output:
        from src.cli.utils import set_output_json
        set_output_json(True)
```

- [ ] **Step 3: 重写 `config` 命令使用新的 CLIConfig 类**

```python
@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    reset: bool = typer.Option(False, "--reset", help="Reset to default configuration"),
    set_key: Optional[str] = typer.Option(None, "--set", help="Set config key=value (e.g. --set default_output_format=docx)"),
):
    """Manage CLI configuration."""
    from src.cli.utils import CLIConfig

    if set_key:
        if "=" not in set_key:
            console.print("[red]Invalid format. Use: --set key=value[/red]")
            raise typer.Exit(1)
        key, value = set_key.split("=", 1)
        cfg = CLIConfig.load()
        if key not in CLIConfig.__dataclass_fields__:
            console.print(f"[red]Unknown config key: {key}[/red]")
            console.print(f"[dim]Available keys: {', '.join(CLIConfig.__dataclass_fields__.keys())}[/dim]")
            raise typer.Exit(1)
        setattr(cfg, key, value)
        cfg.save()
        console.print(f"[green]✓ Set {key} = {value}[/green]")
    elif show:
        cfg = CLIConfig.load()
        console.print_json(json.dumps(asdict(cfg)))
    elif reset:
        cfg = CLIConfig()
        cfg.save()
        console.print("[green]Configuration reset to defaults[/green]")
    else:
        console.print("[dim]Use --show to view config, --reset to reset, or --set key=value to update[/dim]")
```

- [ ] **Step 4: 验证**

Run: `python -m src.cli.main --api-url http://localhost:9000 config --show`
Expected: 显示配置 JSON

- [ ] **Step 5: Commit**

```bash
git add src/cli/main.py src/cli/utils.py
git commit -m "feat: add global options (--api-url, --no-color, --json) and CLIConfig management"
```

---

## Task 6: 建设会话区 — REPL 对话窗口

**Files:**
- Create: `src/cli/repl.py`
- Modify: `src/cli/client.py`

**目标：** 实现会话区的核心——交互式对话窗口（REPL），支持 `session start` 和 `session attach` 进入。这是本次更新的最核心任务。

- [ ] **Step 1: 在 `src/cli/client.py` 添加 interact 和 messages API 方法**

在 `ZensersClient` 类中添加（如果 Task 4 已添加则跳过）：

```python
    async def research_interact(self, session_id: str, user_message: str, step: int = 0, response: Optional[Dict] = None, llm_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {"session_id": session_id, "step": str(step)}
        if response:
            data["response"] = json.dumps(response, ensure_ascii=False)
        else:
            data["response"] = json.dumps({"user_message": user_message}, ensure_ascii=False)
        if llm_config:
            for k, v in llm_config.items():
                data[f"llm_{k}"] = v
        r = await self._request("POST", f"{self._base_url}/api/v1/research/interact", data=data)
        return r.json()

    async def research_messages(self, task_id: str, offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        r = await self._request("GET", f"{self._base_url}/api/v1/research/{task_id}/messages", params={"offset": offset, "limit": limit})
        return r.json()
```

- [ ] **Step 2: 创建 `src/cli/repl.py` — 交互式对话窗口**

```python
"""Interactive REPL for Zensers CLI session area."""
import asyncio
import logging
from typing import Optional, Dict, Any, List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from src.cli.utils import console as default_console

logger = logging.getLogger(__name__)

REPL_COMMANDS = {
    "/help": "Show available commands",
    "/history": "Show conversation history",
    "/status": "Show current session status",
    "/revise": "Revise a section (/revise <section>)",
    "/confirm": "Confirm preview and generate document",
    "/export": "Export document (/export [docx|pdf|html])",
    "/quit": "Exit the session",
}


class SessionREPL:
    """Interactive session REPL — the core of the session area."""

    def __init__(
        self,
        session_id: str,
        console: Console = default_console,
        api_base_url: Optional[str] = None,
    ):
        self.session_id = session_id
        self.console = console
        self._api_base_url = api_base_url

    async def run(self) -> None:
        """Main REPL loop."""
        self.console.print(Panel.fit(
            f"[bold blue]Zensers Session[/bold blue] — {self.session_id}\n"
            f"[dim]Type your message or /help for commands. /quit to exit.[/dim]"
        ))

        while True:
            try:
                user_input = self.console.input("[bold green]You>[/bold green] ").strip()
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]Session paused. Use 'session attach' to resume.[/dim]")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                should_continue = await self._handle_command(user_input)
                if not should_continue:
                    break
                continue

            await self._handle_message(user_input)

    async def _handle_message(self, message: str) -> None:
        """Send user message to the research interact API."""
        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                result = await client.research_interact(
                    session_id=self.session_id,
                    user_message=message,
                )
        except ZensersError as e:
            self.console.print(f"[red]Error: {e.message}[/red]")
            return
        except Exception as e:
            self.console.print(f"[red]Unexpected error: {e}[/red]")
            return

        response = result.get("response", result.get("message", ""))
        if response:
            self.console.print(f"[bold blue]Assistant:[/bold blue]")
            self.console.print(Markdown(str(response)[:2000]))
        else:
            self.console.print("[dim](No response)[/dim]")

        state = result.get("state", result.get("mode", ""))
        if state:
            self.console.print(f"[dim]State: {state}[/dim]")

        step_info = result.get("step_info", {})
        if step_info:
            self._display_step_info(step_info)

    def _display_step_info(self, step_info: Dict[str, Any]) -> None:
        """Display interactive step information (framework options, parameters, etc.)."""
        options = step_info.get("options", [])
        if options:
            for i, opt in enumerate(options, 1):
                if isinstance(opt, dict):
                    label = opt.get("label", opt.get("value", ""))
                    desc = opt.get("description", opt.get("desc", ""))
                    self.console.print(f"  [cyan]{i}.[/cyan] {label}" + (f" — {desc}" if desc else ""))

        framework_options = step_info.get("framework_options", [])
        if framework_options:
            for fw in framework_options:
                name = fw.get("name", "")
                desc = fw.get("description", "")
                self.console.print(f"  [cyan]•[/cyan] {name}" + (f" — {desc}" if desc else ""))

    async def _handle_command(self, command_line: str) -> bool:
        """Handle REPL command. Returns False to exit."""
        parts = command_line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            self.console.print("[dim]Exiting session. Use 'session attach' to resume.[/dim]")
            return False

        if cmd == "/help":
            self._cmd_help()
        elif cmd == "/history":
            await self._cmd_history()
        elif cmd == "/status":
            await self._cmd_status()
        elif cmd == "/revise":
            await self._cmd_revise(arg)
        elif cmd == "/confirm":
            await self._cmd_confirm()
        elif cmd == "/export":
            await self._cmd_export(arg)
        else:
            self.console.print(f"[yellow]Unknown command: {cmd}. Type /help for available commands.[/yellow]")

        return True

    def _cmd_help(self) -> None:
        """Show help."""
        table = Table(title="Session Commands")
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        for cmd, desc in REPL_COMMANDS.items():
            table.add_row(cmd, desc)
        self.console.print(table)

    async def _cmd_history(self) -> None:
        """Show conversation history."""
        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                result = await client.research_messages(self.session_id, limit=50)
        except ZensersError as e:
            self.console.print(f"[red]Failed to load history: {e.message}[/red]")
            return

        messages = result.get("messages", [])
        if not messages:
            self.console.print("[dim]No conversation history[/dim]")
            return

        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")

            role_style = {"user": "green", "assistant": "blue"}.get(role, "white")
            role_label = {"user": "You", "assistant": "Assistant"}.get(role, role)

            self.console.print(f"[{role_style}]{role_label}[/{role_style}] [dim]{timestamp}[/dim]")
            self.console.print(f"  {str(content)[:200]}")
            self.console.print("")

        if result.get("has_more"):
            self.console.print(f"[dim]... {result['total'] - len(messages)} more messages[/dim]")

    async def _cmd_status(self) -> None:
        """Show session status."""
        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                result = await client.research_status(self.session_id)
        except ZensersError as e:
            self.console.print(f"[red]Failed to get status: {e.message}[/red]")
            return

        table = Table(title=f"Session Status: {self.session_id[:12]}")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Status", result.get("status", "unknown"))
        table.add_row("Progress", f"{result.get('progress', 0) * 100:.0f}%")
        if result.get("topic"):
            table.add_row("Topic", result["topic"])
        if result.get("current_phase"):
            table.add_row("Current Phase", result["current_phase"])
        self.console.print(table)

    async def _cmd_revise(self, section: str) -> None:
        """Revise a section."""
        if not section:
            self.console.print("[yellow]Usage: /revise <section_name>[/yellow]")
            return

        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                result = await client.research_revise(self.session_id, [section])
        except ZensersError as e:
            self.console.print(f"[red]Revise failed: {e.message}[/red]")
            return

        status = result.get("status", "")
        self.console.print(f"[green]Revision submitted. Status: {status}[/green]")

    async def _cmd_confirm(self) -> None:
        """Confirm preview and generate document."""
        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                result = await client.research_feedback(
                    self.session_id, action="confirm"
                )
        except ZensersError as e:
            self.console.print(f"[red]Confirm failed: {e.message}[/red]")
            return

        self.console.print(f"[green]Confirmed. {result.get('message', 'Processing...')}[/green]")

    async def _cmd_export(self, format_arg: str) -> None:
        """Export document."""
        fmt = format_arg.strip() or "docx"
        from src.cli.client import ZensersClient, ZensersError

        try:
            async with ZensersClient(base_url=self._api_base_url) as client:
                content, content_type = await client.document_export(
                    self.session_id, output_format=fmt
                )
        except ZensersError as e:
            self.console.print(f"[red]Export failed: {e.message}[/red]")
            return

        from pathlib import Path
        ext = {"docx": ".docx", "pdf": ".pdf", "html": ".html"}.get(fmt, ".bin")
        out_path = Path(f"{self.session_id}_export{ext}")
        out_path.write_bytes(content)
        self.console.print(f"[green]Exported: {out_path} ({len(content)} bytes)[/green]")
```

- [ ] **Step 2: 验证 REPL 可导入**

Run: `python -c "from src.cli.repl import SessionREPL; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/cli/repl.py src/cli/client.py
git commit -m "feat: add SessionREPL interactive dialog window and interact/messages API"
```

---

## Task 7: 重构 session 命令 — 会话区核心

**Files:**
- Modify: `src/cli/commands/session.py`
- Create: `src/cli/commands/task.py`
- Modify: `src/cli/commands/__init__.py`
- Modify: `src/cli/main.py`

**目标：** 将 session 命令重构为会话区核心，添加 `start`/`attach`/`history`/`delete` 命令，将任务控制命令（pause/cancel）拆到 `task` 子组，移除 chat 独立命令。

- [ ] **Step 1: 创建 `src/cli/commands/task.py` — 任务控制子组**

从 session.py 中拆出 pause/cancel/status：

```python
"""Task control commands (pause/cancel/status)."""
import asyncio
import logging
from typing import Optional

import typer
from rich.table import Table

from src.cli.utils import console

logger = logging.getLogger(__name__)


def register(parent: typer.Typer) -> None:
    task_app = typer.Typer(help="Task control (pause/cancel/status)")
    parent.add_typer(task_app, name="task")

    @task_app.command("pause")
    def task_pause(task_id: str = typer.Argument(..., help="Task ID")):
        """Pause a running research task."""
        asyncio.run(_task_pause(task_id))

    @task_app.command("cancel")
    def task_cancel(task_id: str = typer.Argument(..., help="Task ID")):
        """Cancel a research task."""
        asyncio.run(_task_cancel(task_id))

    @task_app.command("status")
    def task_status(task_id: str = typer.Argument(..., help="Task ID")):
        """View task status and progress."""
        asyncio.run(_task_status(task_id))


async def _task_pause(task_id: str):
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            result = await client.research_pause(task_id)
    except ZensersError as e:
        console.print(f"[red]Pause failed: {e.message}[/red]")
        return
    if result.get("status") == "paused":
        console.print(f"[green]✓ Task paused: {task_id}[/green]")
    else:
        console.print(f"[yellow]Pause result: {result.get('message', 'unknown')}[/yellow]")


async def _task_cancel(task_id: str):
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            result = await client.research_cancel(task_id)
    except ZensersError as e:
        console.print(f"[red]Cancel failed: {e.message}[/red]")
        return
    if result.get("status") == "cancelled":
        console.print(f"[green]✓ Task cancelled: {task_id}[/green]")
    else:
        console.print(f"[yellow]Cancel result: {result.get('message', 'unknown')}[/yellow]")


async def _task_status(task_id: str):
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            result = await client.research_status(task_id)
    except ZensersError as e:
        console.print(f"[red]Status query failed: {e.message}[/red]")
        return
    console.print(f"\n[bold]Task: {task_id}[/bold]")
    console.print(f"  Status: {result.get('status', 'unknown')}")
    console.print(f"  Progress: {result.get('progress', 0) * 100:.0f}%")
    if result.get('current_phase'):
        console.print(f"  Current Phase: {result['current_phase']}")
    if result.get('phases'):
        console.print("  Phases:")
        for p in result['phases']:
            status_icon = {"completed": "✅", "running": "⏳", "pending": "⬜", "error": "❌"}.get(p.get('status', ''), '⬜')
            console.print(f"    {status_icon} {p.get('name', 'unknown')} ({p.get('progress', 0)*100:.0f}%)")
```

- [ ] **Step 2: 重构 `src/cli/commands/session.py` — 会话区核心**

```python
"""Session area commands — the core of CLI session management."""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, List

import typer
from rich.table import Table
from rich.panel import Panel

from src.cli.utils import console, get_api_base_url

logger = logging.getLogger(__name__)


def register(parent: typer.Typer) -> None:
    session_app = typer.Typer(help="Session area (start/attach/history/list/delete)")

    @session_app.command("start")
    def session_start(
        requirement: str = typer.Argument(..., help="Research requirement or topic"),
        user_id: str = typer.Option("default", "--user-id", "-u", help="User ID"),
        interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i/-n", help="Enter interactive dialog after start"),
    ):
        """Start a new session and optionally enter interactive dialog."""
        asyncio.run(_session_start(requirement, user_id, interactive))

    @session_app.command("attach")
    def session_attach(
        session_id: str = typer.Argument(..., help="Session ID to attach to"),
    ):
        """Attach to an existing session and enter interactive dialog."""
        asyncio.run(_session_attach(session_id))

    @session_app.command("list")
    def session_list():
        """List all sessions."""
        asyncio.run(_session_list())

    @session_app.command("show")
    def session_show(
        session_id: str = typer.Argument(..., help="Session ID"),
    ):
        """Show session details."""
        asyncio.run(_session_show(session_id))

    @session_app.command("history")
    def session_history(
        session_id: str = typer.Argument(..., help="Session ID"),
        limit: int = typer.Option(50, "--limit", "-l", help="Max messages to show"),
    ):
        """View conversation history for a session."""
        asyncio.run(_session_history(session_id, limit))

    @session_app.command("modify")
    def session_modify(
        session_id: str = typer.Argument(..., help="Session ID"),
        aspects: str = typer.Option("", "--aspects", "-a", help="New sections, comma-separated"),
        topic: Optional[str] = typer.Option(None, "--topic", "-t", help="New topic"),
    ):
        """Modify research requirements in a session."""
        aspects_list = [a.strip() for a in aspects.split(",") if a.strip()] if aspects else []
        if not aspects_list and not topic:
            console.print("[red]Please specify --aspects or --topic[/red]")
            raise typer.Exit(1)
        asyncio.run(_session_modify(session_id, aspects_list, topic))

    @session_app.command("confirm")
    def session_confirm(
        session_id: str = typer.Argument(..., help="Session ID"),
        format: str = typer.Option("docx", "--format", "-f", help="Output format: docx, pdf, pptx"),
        output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    ):
        """Confirm HTML preview and generate final document."""
        asyncio.run(_session_confirm(session_id, format, output))

    @session_app.command("revise")
    def session_revise(
        session_id: str = typer.Argument(..., help="Session ID"),
        aspects: str = typer.Option("", "--aspects", "-a", help="Sections to revise, comma-separated"),
    ):
        """Partially revise specified sections."""
        aspects_list = [a.strip() for a in aspects.split(",") if a.strip()] if aspects else []
        if not aspects_list:
            console.print("[red]Please specify sections to revise[/red]")
            raise typer.Exit(1)
        asyncio.run(_session_revise(session_id, aspects_list))

    @session_app.command("delete")
    def session_delete(
        session_id: str = typer.Argument(..., help="Session ID"),
        force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    ):
        """Delete a session and its data."""
        asyncio.run(_session_delete(session_id, force))

    parent.add_typer(session_app, name="session")


async def _session_start(requirement: str, user_id: str, interactive: bool):
    """Start a new session via API and optionally enter REPL."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_start(requirement, user_id=user_id)
    except ZensersError as e:
        console.print(f"[red]Failed to start session: {e.message}[/red]")
        raise typer.Exit(1)

    session_id = result.get("session_id", "")
    if not session_id:
        console.print(f"[red]No session ID returned[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓ Session started: {session_id}[/green]")

    response = result.get("response", result.get("message", ""))
    if response:
        from rich.markdown import Markdown
        console.print(f"[bold blue]Assistant:[/bold blue]")
        console.print(Markdown(str(response)[:2000]))

    if interactive:
        from src.cli.repl import SessionREPL
        repl = SessionREPL(session_id)
        await repl.run()
    else:
        console.print(f"[dim]Use 'session attach {session_id}' to enter interactive dialog[/dim]")


async def _session_attach(session_id: str):
    """Attach to existing session and enter REPL."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_status(session_id)
    except ZensersError as e:
        console.print(f"[red]Session not found: {e.message}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Attaching to session: {session_id}[/green]")
    console.print(f"  Status: {result.get('status', 'unknown')}")

    from src.cli.repl import SessionREPL
    repl = SessionREPL(session_id)
    await repl.run()


async def _session_list():
    """List all sessions."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_sessions(limit=50)
    except ZensersError as e:
        console.print(f"[red]Failed to list sessions: {e.message}[/red]")
        raise typer.Exit(1)

    sessions = result.get("sessions", [])
    if not sessions:
        console.print("[yellow]No sessions[/yellow]")
        return

    table = Table(title="Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Topic", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Created At", style="dim")
    for s in sessions[:20]:
        table.add_row(
            s.get("session_id", s.get("task_id", "N/A"))[:16],
            (s.get("topic", "") or s.get("user_input", ""))[:30],
            s.get("status", "unknown"),
            s.get("created_at", "")[:19],
        )
    console.print(table)


async def _session_show(session_id: str):
    """Show session details."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_detail(session_id)
    except ZensersError as e:
        console.print(f"[red]Session not found: {e.message}[/red]")
        return

    console.print(f"\n[bold]Session: {session_id}[/bold]")
    console.print(f"  Status: {result.get('status', 'N/A')}")
    console.print(f"  Topic: {result.get('topic', 'N/A')}")
    console.print(f"  Created: {result.get('created_at', 'N/A')}")
    console.print(f"  Mode: {result.get('mode', 'N/A')}")
    if result.get("sections"):
        console.print(f"  Sections: {', '.join(result['sections'][:5])}{'...' if len(result['sections']) > 5 else ''}")


async def _session_history(session_id: str, limit: int):
    """View conversation history."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_messages(session_id, limit=limit)
    except ZensersError as e:
        console.print(f"[red]Failed to load history: {e.message}[/red]")
        return

    messages = result.get("messages", [])
    if not messages:
        console.print("[dim]No conversation history[/dim]")
        return

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        role_style = {"user": "green", "assistant": "blue"}.get(role, "white")
        role_label = {"user": "You", "assistant": "Assistant"}.get(role, role)
        console.print(f"[{role_style}]{role_label}[/{role_style}] [dim]{timestamp}[/dim]")
        console.print(f"  {str(content)[:200]}")
        console.print("")

    if result.get("has_more"):
        console.print(f"[dim]... {result['total'] - len(messages)} more messages. Use --limit to see more.[/dim]")


async def _session_modify(session_id: str, aspects: List[str], topic: Optional[str]):
    """Modify research requirements."""
    from src.cli.client import ZensersClient, ZensersError

    try:
        async with ZensersClient() as client:
            result = await client.research_modify(session_id, aspects, topic)
    except ZensersError as e:
        console.print(f"[red]Modify failed: {e.message}[/red]")
        return

    if result.get("status") == "requirements_updated":
        plan = result.get("plan", {})
        console.print("[green]✓ Requirements updated[/green]")
        console.print(f"  Topic: {plan.get('topic', 'N/A')}")
        console.print(f"  Sections: {', '.join(plan.get('sections', []))}")
        console.print(f"\n[dim]Use 'session attach {session_id}' to continue[/dim]")
    else:
        console.print(f"[red]Modify failed: {result.get('error', 'unknown')}[/red]")


async def _session_confirm(session_id: str, format: str, output: Optional[str]):
    """Confirm and generate document."""
    from src.core.orchestrator import ResearchOrchestrator as Orchestrator

    console.print(f"[cyan]Confirming session {session_id} and generating {format} document...[/cyan]")
    orchestrator = Orchestrator()
    try:
        result = await orchestrator.generate_document_later(task_id=session_id, output_format=format)
        if result.get("success"):
            document_path = result.get("document_path") or result.get("output_path")
            if document_path:
                console.print(f"[green]✓ Document generated: {document_path}[/green]")
                if output and document_path:
                    import shutil
                    src_path = Path(document_path)
                    dst_path = Path(output)
                    if src_path.exists():
                        shutil.copy2(src_path, dst_path)
                        console.print(f"  Copied to: {dst_path}")
            else:
                console.print("[yellow]Document generated but path not returned[/yellow]")
        else:
            console.print(f"[red]✗ Document generation failed: {result.get('error', 'Unknown error')}[/red]")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗ Document generation failed: {e}[/red]")
        raise typer.Exit(1)


async def _session_revise(session_id: str, aspects: List[str]):
    """Revise sections."""
    from src.core.orchestrator import ResearchOrchestrator

    console.print(f"[yellow]Revising sections {aspects}...[/yellow]")
    orchestrator = ResearchOrchestrator()
    try:
        result = await orchestrator.revise(session_id, aspects)
        if result.status == "completed":
            console.print(f"[green]Revision complete! Report: {result.output_path}[/green]")
        else:
            console.print(f"[red]Revision failed: {result.status}[/red]")
    except Exception as e:
        console.print(f"[red]Revision failed: {e}[/red]")


async def _session_delete(session_id: str, force: bool):
    """Delete a session."""
    if not force:
        console.print(f"[yellow]Are you sure you want to delete session {session_id}? Use --force to confirm.[/yellow]")
        return

    from src.core.session_manager import SessionManager
    sm = SessionManager.get_instance()
    sm.delete(session_id)
    console.print(f"[green]✓ Session deleted: {session_id}[/green]")
```

- [ ] **Step 3: 更新 `src/cli/commands/__init__.py`**

```python
"""CLI subcommand modules."""
from . import session
from . import task
from . import knowledge
from . import survey
from . import mcp
from . import llm
from . import prompt
from . import document
from . import upload

__all__ = [
    "session", "task", "knowledge", "survey",
    "mcp", "llm", "prompt", "document", "upload",
]
```

- [ ] **Step 4: 更新 `src/cli/main.py` — 注册 task 子组，移除 chat**

在 main.py 中：
- 将 `from src.cli.commands import session, knowledge, chat, survey, mcp, llm, prompt, document, upload` 改为 `from src.cli.commands import session, task, knowledge, survey, mcp, llm, prompt, document, upload`
- 添加 `task.register(app)`
- 移除 `chat.register(app)`

- [ ] **Step 5: 验证**

Run: `python -m src.cli.main session --help && python -m src.cli.main task --help`
Expected: session 显示 start/attach/list/show/history/modify/confirm/revise/delete；task 显示 pause/cancel/status

- [ ] **Step 6: Commit**

```bash
git add src/cli/commands/session.py src/cli/commands/task.py src/cli/commands/__init__.py src/cli/main.py
git commit -m "feat: rebuild session as session area with REPL, add task control subgroup, remove chat"
```

---

## Task 8: 增强 llm 命令 — 添加 set-config 子命令

**Files:**
- Modify: `src/cli/commands/llm.py`

**目标：** 对齐 API 端点 `/api/v1/llm/config` (POST) 和 `/api/v1/llm/config/reset` (POST)，添加 `llm set-config` 和 `llm reset-config` 命令。

- [ ] **Step 1: 在 `llm.py` 的 register 函数中添加新命令**

在 `llm_health_command` 之后添加：

```python
    @llm_app.command("set-config")
    def llm_set_config_command(
        provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider (openai/anthropic/deepseek/etc.)"),
        model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name"),
        api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API key"),
        api_endpoint: Optional[str] = typer.Option(None, "--api-endpoint", "-e", help="API endpoint URL"),
        temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Temperature (0.0-1.0)"),
        max_tokens: Optional[int] = typer.Option(None, "--max-tokens", help="Max tokens"),
    ):
        """Update LLM configuration."""
        if not any([provider, model, api_key, api_endpoint, temperature is not None, max_tokens is not None]):
            console.print("[red]Please specify at least one config option[/red]")
            raise typer.Exit(1)
        asyncio.run(_llm_set_config_async(provider, model, api_key, api_endpoint, temperature, max_tokens))

    @llm_app.command("reset-config")
    def llm_reset_config_command():
        """Reset LLM configuration to defaults."""
        asyncio.run(_llm_reset_config_async())
```

- [ ] **Step 2: 添加实现函数**

```python
async def _llm_set_config_async(provider, model, api_key, api_endpoint, temperature, max_tokens):
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        try:
            result = await client.llm_set_config(provider, model, api_key, api_endpoint, temperature, max_tokens)
        except Exception as e:
            console.print(f"[red]Failed to set LLM config: {e}[/red]")
            raise typer.Exit(1)
    console.print("[green]✓ LLM configuration updated[/green]")


async def _llm_reset_config_async():
    from src.cli.client import ZensersClient
    async with ZensersClient() as client:
        try:
            result = await client.llm_reset_config()
        except Exception as e:
            console.print(f"[red]Failed to reset LLM config: {e}[/red]")
            raise typer.Exit(1)
    console.print("[green]✓ LLM configuration reset to defaults[/green]")
```

- [ ] **Step 3: 验证**

Run: `python -m src.cli.main llm set-config --help`
Expected: 显示帮助

- [ ] **Step 4: Commit**

```bash
git add src/cli/commands/llm.py
git commit -m "feat: add llm set-config and reset-config commands"
```

---

## Task 9: 修复和重写 CLI 测试

**Files:**
- Modify: `tests/unit/cli/test_cli.py`
- Create: `tests/unit/cli/test_interaction.py`
- Create: `tests/unit/cli/test_client.py`
- Create: `tests/unit/cli/test_repl.py`
- Create: `tests/unit/cli/test_session_commands.py`

**目标：** 修复过时的测试引用，补充交互模块和客户端的单元测试。

- [ ] **Step 1: 重写 `test_cli.py`，修复过时引用**

```python
"""CLI unit tests."""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


class TestCLICommands:
    def test_cli_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Zensers" in result.output

    def test_version_command(self):
        with patch("cli.main.get_local_version", return_value="0.1.0"), \
             patch("cli.main.get_build_date", return_value="2024-01-01"):
            result = runner.invoke(app, ["version"])
            assert result.exit_code == 0
            assert "Zensers" in result.output

    def test_research_command_help(self):
        result = runner.invoke(app, ["research", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output

    def test_status_command_help(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--watch" in result.output

    def test_download_command_help(self):
        result = runner.invoke(app, ["download", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output

    def test_config_show(self):
        with patch.object(Path, "exists", return_value=False):
            result = runner.invoke(app, ["config", "--show"])
            assert result.exit_code == 0

    def test_global_api_url_option(self):
        result = runner.invoke(app, ["--api-url", "http://localhost:9000", "version"])
        assert result.exit_code == 0


class TestConfigCommand:
    def test_config_set(self):
        with patch("cli.main.CLIConfig") as mock_cfg:
            mock_instance = Mock()
            mock_instance.save = Mock()
            mock_cfg.load.return_value = mock_instance
            mock_cfg.__dataclass_fields__ = {"default_output_format": Mock()}
            result = runner.invoke(app, ["config", "--set", "default_output_format=docx"])
            assert result.exit_code == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: 创建 `test_interaction.py`**

```python
"""Interaction callback unit tests."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


class TestHandleOptions:
    @pytest.mark.asyncio
    async def test_options_select(self):
        from cli.interaction import _handle_options
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value="Option A - desc")
        mock_console = Mock()
        step_data = {"step": "select"}
        options = [{"label": "Option A", "value": "a", "desc": "desc"}]
        result = await _handle_options(mock_q, mock_console, step_data, options, "Select:", "")
        assert result["selected"] == "a"

    @pytest.mark.asyncio
    async def test_options_cancel(self):
        from cli.interaction import _handle_options
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value=None)
        mock_console = Mock()
        result = await _handle_options(mock_q, mock_console, {}, [], "Select:", "")
        assert result["cancelled"] is True


class TestHandleSummary:
    @pytest.mark.asyncio
    async def test_summary_confirm(self):
        from cli.interaction import _handle_summary
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value="Confirm and start")
        mock_console = Mock()
        result = await _handle_summary(mock_q, mock_console, {}, {"topic": "AI"}, "Confirm?")
        assert result["confirmed"] is True

    @pytest.mark.asyncio
    async def test_summary_cancel(self):
        from cli.interaction import _handle_summary
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value="Cancel")
        mock_console = Mock()
        result = await _handle_summary(mock_q, mock_console, {}, {}, "Confirm?")
        assert result["confirmed"] is False


class TestHandlePreview:
    @pytest.mark.asyncio
    async def test_preview_confirm(self):
        from cli.interaction import _handle_preview
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value="Confirm and finalize")
        mock_console = Mock()
        result = await _handle_preview(mock_q, mock_console, {"actions": ["confirm", "revise", "cancel"]}, "Preview?")
        assert result["action"] == "confirm"

    @pytest.mark.asyncio
    async def test_preview_revise(self):
        from cli.interaction import _handle_preview
        mock_q = Mock()
        mock_q.select.return_value.ask_async = AsyncMock(return_value="Needs revision")
        mock_q.text.return_value.ask_async = AsyncMock(return_value="Add more data")
        mock_console = Mock()
        result = await _handle_preview(mock_q, mock_console, {"actions": ["confirm", "revise", "cancel"]}, "Preview?")
        assert result["action"] == "revise"
        assert result["adjustment"] == "Add more data"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 3: 创建 `test_client.py`**

```python
"""ZensersClient unit tests."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


class TestZensersClientErrors:
    def test_zensers_error(self):
        from cli.client import ZensersError
        err = ZensersError("test", status_code=500)
        assert err.message == "test"
        assert err.status_code == 500

    def test_connection_error(self):
        from cli.client import ZensersConnectionError, ZensersError
        err = ZensersConnectionError("refused")
        assert isinstance(err, ZensersError)

    def test_not_found_error(self):
        from cli.client import ZensersNotFoundError, ZensersError
        err = ZensersNotFoundError("missing")
        assert isinstance(err, ZensersError)


class TestZensersClientContextManager:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        from cli.client import ZensersClient
        with patch("cli.client.get_api_base_url", return_value="http://localhost:8000"):
            async with ZensersClient() as client:
                assert client._base_url == "http://localhost:8000"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 4: 创建 `test_repl.py`**

```python
"""SessionREPL unit tests."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


class TestSessionREPLCommands:
    @pytest.mark.asyncio
    async def test_quit_command(self):
        from cli.repl import SessionREPL
        repl = SessionREPL("test-session")
        result = await repl._handle_command("/quit")
        assert result is False

    @pytest.mark.asyncio
    async def test_exit_command(self):
        from cli.repl import SessionREPL
        repl = SessionREPL("test-session")
        result = await repl._handle_command("/exit")
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        from cli.repl import SessionREPL
        repl = SessionREPL("test-session")
        result = await repl._handle_command("/unknown")
        assert result is True

    @pytest.mark.asyncio
    async def test_help_command(self):
        from cli.repl import SessionREPL
        mock_console = Mock()
        repl = SessionREPL("test-session", console=mock_console)
        result = await repl._handle_command("/help")
        assert result is True

    @pytest.mark.asyncio
    async def test_status_command(self):
        from cli.repl import SessionREPL
        from cli.client import ZensersError
        mock_console = Mock()
        repl = SessionREPL("test-session", console=mock_console)
        with patch("cli.repl.ZensersClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.research_status = AsyncMock(return_value={"status": "running", "progress": 0.5})
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await repl._handle_command("/status")
            assert result is True

    @pytest.mark.asyncio
    async def test_revise_no_arg(self):
        from cli.repl import SessionREPL
        mock_console = Mock()
        repl = SessionREPL("test-session", console=mock_console)
        result = await repl._handle_command("/revise")
        assert result is True


class TestSessionREPLMessageHandling:
    @pytest.mark.asyncio
    async def test_handle_message_success(self):
        from cli.repl import SessionREPL
        mock_console = Mock()
        repl = SessionREPL("test-session", console=mock_console)
        with patch("cli.repl.ZensersClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.research_interact = AsyncMock(return_value={"response": "Hello!", "state": "chat"})
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            await repl._handle_message("hi")
            mock_client.research_interact.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_error(self):
        from cli.repl import SessionREPL
        from cli.client import ZensersConnectionError
        mock_console = Mock()
        repl = SessionREPL("test-session", console=mock_console)
        with patch("cli.repl.ZensersClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.research_interact = AsyncMock(side_effect=ZensersConnectionError("refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            await repl._handle_message("hi")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 5: 创建 `test_session_commands.py`**

```python
"""Session area commands unit tests."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from typer.testing import CliRunner
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from cli.main import app

runner = CliRunner()


class TestSessionCommands:
    def test_session_help(self):
        result = runner.invoke(app, ["session", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "attach" in result.output
        assert "list" in result.output
        assert "history" in result.output

    def test_session_start_help(self):
        result = runner.invoke(app, ["session", "start", "--help"])
        assert result.exit_code == 0
        assert "--interactive" in result.output

    def test_session_attach_help(self):
        result = runner.invoke(app, ["session", "attach", "--help"])
        assert result.exit_code == 0

    def test_session_history_help(self):
        result = runner.invoke(app, ["session", "history", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output


class TestTaskCommands:
    def test_task_help(self):
        result = runner.invoke(app, ["task", "--help"])
        assert result.exit_code == 0
        assert "pause" in result.output
        assert "cancel" in result.output
        assert "status" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 6: 运行测试**

Run: `python -m pytest tests/unit/cli/ -v`
Expected: 所有测试通过

- [ ] **Step 7: Commit**

```bash
git add tests/unit/cli/test_cli.py tests/unit/cli/test_interaction.py tests/unit/cli/test_client.py tests/unit/cli/test_repl.py tests/unit/cli/test_session_commands.py
git commit -m "test: rewrite CLI tests, add REPL and session command test coverage"
```

---

## Task 10: 添加 shell 自动补全命令

**Files:**
- Modify: `src/cli/main.py`

**目标：** 利用 typer 内置的补全支持，添加 `completion` 命令。

- [ ] **Step 1: 在 main.py 中启用 typer 补全**

在 `app = typer.Typer(...)` 中添加 `rich_markup_mode="rich"` 并在 callback 中注册补全：

```python
app = typer.Typer(
    name="zensers",
    help="Zensers - Automated Industry Research System",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
```

Typer 0.9+ 自动提供 `--show-completion` 选项，无需额外代码。验证：

- [ ] **Step 2: 验证补全选项**

Run: `python -m src.cli.main --show-completion bash`
Expected: 输出 bash 补全脚本

- [ ] **Step 3: Commit**

```bash
git add src/cli/main.py
git commit -m "feat: enable shell completion support via typer"
```

---

## 执行顺序与依赖关系

```
Task 1 (提取交互回调)        ──┐
Task 4 (增强 ZensersClient)  ──┤  并行组 A
                               ↓
Task 2 (统一 session.py)      ──┐
Task 3 (统一 main.py)         ──┤  并行组 B（均依赖 T1）
                               ↓
Task 5 (全局选项和配置)       ──  依赖 T3
                               ↓
Task 6 (REPL 对话窗口)        ──  依赖 T4（核心！）
                               ↓
Task 7 (会话区命令重构)       ──  依赖 T6
                               ↓
Task 8 (llm set-config)       ──  依赖 T4，可与 T6/T7 并行
                               ↓
Task 9 (测试)                 ──  依赖 T1-T8 全部完成
                               ↓
Task 10 (shell 补全)          ──  依赖 T5，收尾
```

**建议并行组：**
- 组 A: Task 1 + Task 4 (互不依赖)
- 组 B: Task 2 + Task 3 (均依赖 Task 1，但互不冲突)
- 组 C: Task 5 (依赖 T3) → 然后 Task 6 + Task 8 (可并行)
- 组 D: Task 7 (依赖 T6，核心会话区建设)
- 组 E: Task 9 (最终验证)
- 组 F: Task 10 (收尾)
