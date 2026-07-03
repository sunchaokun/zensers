"""Zensers CLI - Command Line Interface.

Provides research task submission, status query, report download and other functions.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.cli.utils import console, setup_cli_logging, set_api_base_url, get_api_base_url
from src.cli.commands import session, knowledge, chat, survey, mcp, llm, prompt, document, upload
from src.cli.interaction import build_interaction_callback

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="zensers",
    help="Zensers - Automated Industry Research System",
    no_args_is_help=True,
)

# Register all subcommand groups
session.register(app)
knowledge.register(app)
chat.register(app)
survey.register(app)
mcp.register(app)
llm.register(app)
prompt.register(app)
document.register(app)
upload.register(app)


# ===== Top-level command: research =====

@app.command()
def research(
    requirement: str = typer.Argument(..., help="Research requirement description"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file path"
    ),
    format: str = typer.Option(
        "docx", "--format", "-f", help="Output format: docx, pdf, html, markdown"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show verbose logs"
    ),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", "-i/-n", help="Enable interactive mode"
    ),
    # === Custom options ===
    aspects: Optional[str] = typer.Option(
        None, "--aspects", "-a", help="Custom sections, comma-separated: market size,competitive landscape,industry chain"
    ),
    framework: Optional[str] = typer.Option(
        None, "--framework", "--fw", help="Research framework: detailed/standard/brief"
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-t", help="Output template: research_report(default)/default"
    ),
    output_type: Optional[str] = typer.Option(
        None, "--type", "--output-type", help="Report type: industry_report/company_research/market_brief"
    ),
    language: Optional[str] = typer.Option(
        None, "--language", "-l", help="Language: zh/en/ja/ko"
    ),
):
    """Submit research requirement and generate report."""
    if verbose:
        setup_cli_logging(verbose=True)

    if language:
        try:
            from src.core.i18n import set_language, Language
            set_language(Language(language))
            logger.info(f"CLI language set to: {language}")
        except Exception:
            logger.warning(f"Unsupported language: {language}")

    asyncio.run(_research_async(
        requirement, output, format, verbose, interactive,
        aspects=aspects.split(",") if aspects else None,
        framework=framework, template=template, output_type=output_type,
    ))


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
    """Execute research task asynchronously."""
    from src.core.orchestrator import ResearchOrchestrator as Orchestrator

    console.print(Panel.fit(
        f"[bold blue]Zensers[/bold blue] - Starting Research Task\n"
        f"[dim]Requirement: {requirement[:50]}{'...' if len(requirement) > 50 else ''}[/dim]"
    ))

    callback = await build_interaction_callback(console) if interactive else None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing research system...", total=None)
        orchestrator = Orchestrator()
        progress.update(task, description="System ready")

        progress.update(task, description="Executing research workflow...")
        try:
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
        console.print("[dim]Web UI for conversational interaction will be available later[/dim]")

    else:
        console.print(f"\n[red]Research failed: {result.status}[/red]")
        raise typer.Exit(1)


# ===== Top-level command: status =====

@app.command()
def status(
    task_id: Optional[str] = typer.Argument(None, help="Task ID"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuously monitor status"),
):
    """Query research task status."""
    if task_id:
        asyncio.run(_get_task_status_remote(task_id, watch))
    else:
        asyncio.run(_list_active_tasks_remote())


async def _get_task_status_remote(task_id: str, watch: bool):
    from src.cli.client import ZensersClient, ZensersError
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
            try:
                result = await client.research_status(task_id)
            except ZensersError as e:
                console.print(f"[red]Failed to get task status: {e.message}[/red]")
                raise typer.Exit(1)
            console.print(f"Status: {result.get('status', 'unknown')}")
            if result.get("topic"):
                console.print(f"Topic: {result['topic']}")
            if result.get("progress"):
                console.print(f"Progress: {result['progress']}")


async def _list_active_tasks_remote():
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            result = await client.research_sessions(limit=50)
    except ZensersError as e:
        console.print(f"[red]Failed to list active tasks: {e.message}[/red]")
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


# ===== Top-level command: download =====

@app.command()
def download(
    task_id: str = typer.Argument(..., help="Task ID"),
    output: str = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option(
        "markdown", "--format", "-f",
        help="Format is auto-detected from Content-Type header; kept for backward compatibility."
    ),
):
    """Download research report."""
    asyncio.run(_download_report(task_id, output, format))


async def _download_report(task_id: str, output: str, format: str):
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            content, content_type = await client.download(task_id)
    except FileNotFoundError:
        console.print(f"[red]Report not found: {task_id}[/red]")
        raise typer.Exit(1)
    except ZensersError as e:
        console.print(f"[red]Download failed: {e.message}[/red]")
        raise typer.Exit(1)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    console.print(f"[green]Report downloaded: {output_path} ({len(content)} bytes)[/green]")


# ===== Top-level command: config =====

@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    reset: bool = typer.Option(False, "--reset", help="Reset to default configuration"),
):
    """Manage CLI configuration."""
    config_path = Path.home() / ".zensers" / "config.json"

    if show:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            console.print_json(json.dumps(config))
        else:
            console.print("[dim]Configuration file not yet created[/dim]")

    elif reset:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        default_config = {
            "default_output_format": "markdown",
            "auto_save_reports": True,
            "max_concurrent_tasks": 3,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        console.print("[green]Configuration reset to defaults[/green]")


# ===== Top-level command: version =====

@app.command()
def version():
    """Show version information."""
    from src.core.version import get_local_version, get_build_date
    ver = get_local_version()
    build_date = get_build_date()
    console.print(Panel.fit(
        f"[bold blue]Zensers[/bold blue]\n"
        f"[dim]Version: {ver}[/dim]\n"
        f"[dim]Build: {build_date}[/dim]\n"
        f"[dim]Automated Industry Research System[/dim]"
    ))


# ===== Top-level command: changelog =====

@app.command()
def changelog(
    format: str = typer.Option("text", "--format", "-f", help="Output format: text, json"),
    max_lines: int = typer.Option(50, "--max-lines", "-n", help="Max lines to display"),
):
    """Show system changelog."""
    asyncio.run(_changelog_async(format, max_lines))


async def _changelog_async(format: str, max_lines: int):
    from src.cli.client import ZensersClient, ZensersError
    try:
        async with ZensersClient() as client:
            result = await client.changelog(format, max_lines)
    except ZensersError as e:
        console.print(f"[red]Failed to fetch changelog: {e.message}[/red]")
        raise typer.Exit(1)
    content = result.get("changelog", "")
    if isinstance(content, list):
        for entry in content:
            console.print(Panel.fit(entry.get("body", ""), title=entry.get("header", "")))
    else:
        console.print(Panel.fit(str(content)[:4000], title="Changelog"))


# ===== Entry point =====

def main():
    """CLI entry point."""
    setup_cli_logging(verbose=False)
    api_url = get_api_base_url()
    set_api_base_url(api_url)
    app()


if __name__ == "__main__":
    main()
