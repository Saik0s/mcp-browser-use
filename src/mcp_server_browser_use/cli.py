"""mcp-server-browser-use: Unified CLI for Browser Use MCP Server.

Commands:
- server: Start HTTP MCP server (default: background daemon, -f for foreground)
- stop: Stop the running server daemon
- status: Check if server is running
- logs: View server logs
- install: Install to Claude Desktop config
- config: View or modify configuration
- skill: Manage browser skills (list, get, delete)
"""

import json
import os
import signal
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import APP_NAME, CONFIG_FILE, get_default_results_dir, load_config_file, save_config_file, settings
from .skills import SkillStore


def get_state_dir() -> Path:
    """Get the state directory for runtime files (e.g. ~/.local/state/mcp-server-browser-use)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/state")).expanduser()
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


SERVER_INFO_FILE = get_state_dir() / "server.json"
LOG_FILE = get_state_dir() / "server.log"

app = typer.Typer(
    name="mcp-server-browser-use",
    help="Browser automation MCP server & CLI",
    no_args_is_help=False,  # Show deprecation message instead of help
)
console = Console()


def _read_server_info() -> dict | None:
    """Read server info from file, return None if not exists or invalid."""
    if not SERVER_INFO_FILE.exists():
        return None
    try:
        info = json.loads(SERVER_INFO_FILE.read_text())
        # Validate required keys
        required = {"pid", "host", "port", "transport"}
        if not required.issubset(info.keys()):
            return None
        return info
    except (json.JSONDecodeError, OSError):
        return None


def _is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_server_info(pid: int, host: str, port: int, transport: str) -> None:
    """Write server info to file."""
    info = {"pid": pid, "host": host, "port": port, "transport": transport}
    SERVER_INFO_FILE.write_text(json.dumps(info, indent=2))


def _remove_server_info() -> None:
    """Remove server info file if exists."""
    if SERVER_INFO_FILE.exists():
        SERVER_INFO_FILE.unlink()


@app.command()
def server(
    host: str = typer.Option(None, "--host", "-H", help="Host to bind to"),
    port: int = typer.Option(None, "--port", "-p", help="Port to bind to"),
    transport: str = typer.Option(
        "streamable-http",
        "--transport",
        "-t",
        help="HTTP transport: streamable-http (default) or sse",
        callback=lambda v: v if v in ("streamable-http", "sse") else typer.BadParameter(f"Invalid transport: {v}"),
    ),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (don't daemonize)"),
) -> None:
    """Start the HTTP MCP server as a background daemon."""
    import subprocess

    h = host or settings.server.host
    p = port or settings.server.port

    # Check if already running
    info = _read_server_info()
    if info and _is_process_running(info["pid"]):
        console.print(f"[yellow]Server already running (PID {info['pid']})[/yellow]")
        console.print(f"  URL: http://{info['host']}:{info['port']}/mcp")
        console.print("[dim]Use 'mcp-server-browser-use stop' to stop it[/dim]")
        raise typer.Exit(1)

    if foreground:
        # Run in foreground (useful for debugging)
        from .server import server_instance

        console.print("[bold green]Starting HTTP MCP server (foreground)[/bold green]")
        console.print(f"  Provider: {settings.llm.provider}")
        console.print(f"  Model: {settings.llm.model_name}")
        console.print(f"  URL: http://{h}:{p}/mcp")
        _write_server_info(os.getpid(), h, p, transport)
        try:
            server_instance.run(transport=transport, host=h, port=p)  # type: ignore[arg-type]
        finally:
            _remove_server_info()
        return

    # Daemonize: spawn subprocess and detach
    cmd = [
        sys.executable,
        "-m",
        "mcp_server_browser_use.cli",
        "server",
        "--host",
        h,
        "--port",
        str(p),
        "--transport",
        transport,
        "--foreground",
    ]

    # Open log file for output
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fd = open(LOG_FILE, "a")

    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=os.getcwd(),
        env=os.environ.copy(),
    )

    console.print("[bold green]Started HTTP MCP server (background)[/bold green]")
    console.print(f"  PID: {proc.pid}")
    console.print(f"  Provider: {settings.llm.provider}")
    console.print(f"  Model: {settings.llm.model_name}")
    console.print(f"  URL: http://{h}:{p}/mcp")
    console.print(f"  Log: {LOG_FILE}")
    console.print(f"  Info: {SERVER_INFO_FILE}")


@app.command()
def stop() -> None:
    """Stop the running server daemon."""
    info = _read_server_info()
    if info is None:
        console.print("[yellow]No server info file found[/yellow]")
        raise typer.Exit(1)

    pid = info["pid"]
    if not _is_process_running(pid):
        console.print(f"[yellow]Server process (PID {pid}) not running, cleaning up[/yellow]")
        _remove_server_info()
        raise typer.Exit(0)

    console.print(f"[bold]Stopping server (PID {pid})...[/bold]")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for graceful shutdown
        import time

        for _ in range(10):
            if not _is_process_running(pid):
                break
            time.sleep(0.5)
        else:
            # Force kill if still running
            console.print("[yellow]Forcing shutdown...[/yellow]")
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        console.print(f"[red]Failed to stop server: {e}[/red]")
        raise typer.Exit(1)

    _remove_server_info()
    console.print("[green]Server stopped[/green]")


@app.command()
def status() -> None:
    """Check if server is running."""
    info = _read_server_info()
    if info is None:
        console.print("[dim]Server not running (no info file)[/dim]")
        raise typer.Exit(1)

    pid = info["pid"]
    if _is_process_running(pid):
        console.print(f"[green]Server running (PID {pid})[/green]")
        console.print(f"  URL: http://{info['host']}:{info['port']}/mcp")
        console.print(f"  Transport: {info['transport']}")
        console.print(f"  Log: {LOG_FILE}")
    else:
        console.print(f"[yellow]Server not running (stale PID {pid})[/yellow]")
        _remove_server_info()
        raise typer.Exit(1)


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """View server logs."""
    if not LOG_FILE.exists():
        console.print("[yellow]No log file found[/yellow]")
        raise typer.Exit(1)

    if follow:
        import subprocess

        subprocess.run(["tail", "-f", str(LOG_FILE)], check=False)
    else:
        import subprocess

        subprocess.run(["tail", "-n", str(lines), str(LOG_FILE)], check=False)


# --- MCP Client Commands ---


def _get_server_url() -> str:
    """Get the URL of the running server."""
    info = _read_server_info()
    if not info or not _is_process_running(info["pid"]):
        console.print("[red]Server is not running[/red]")
        console.print("[dim]Start it with: mcp-server-browser-use server[/dim]")
        raise typer.Exit(1)
    return f"http://{info['host']}:{info['port']}/mcp"


async def _async_list_tools() -> list[dict]:
    """List tools from the MCP server."""
    from fastmcp import Client

    url = _get_server_url()
    async with Client(url) as client:
        tools = await client.list_tools()
        return [{"name": t.name, "description": t.description or ""} for t in tools]


async def _async_call_tool(tool_name: str, arguments: dict) -> tuple[list, bool]:
    """Call a tool on the MCP server."""
    from fastmcp import Client

    url = _get_server_url()
    async with Client(url) as client:
        result = await client.call_tool(tool_name, arguments)
        return result.content, result.is_error


@app.command()
def tools() -> None:
    """List available tools from the running server."""
    import asyncio

    try:
        tools_list = asyncio.run(_async_list_tools())
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not tools_list:
        console.print("[yellow]No tools available[/yellow]")
        return

    table = Table(title="Available MCP Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description", style="white")

    for tool in tools_list:
        name = tool.get("name", "")
        desc = tool.get("description", "")[:80]
        table.add_row(name, desc)

    console.print(table)
    console.print("\n[dim]Use 'mcp-server-browser-use call <tool> [args]' to run a tool[/dim]")


@app.command()
def call(
    tool_name: str = typer.Argument(..., help="Name of the tool to call"),
    args: list[str] = typer.Argument(None, help="Tool arguments as key=value pairs"),
) -> None:
    """Call a tool on the running server.

    Examples:
        mcp-server-browser-use call skill_list
        mcp-server-browser-use call run_browser_agent task="Go to google.com"
        mcp-server-browser-use call run_deep_research topic="AI trends 2025"
    """
    import asyncio

    # Parse key=value arguments
    tool_args = {}
    if args:
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                # Try to parse as JSON for complex types
                try:
                    import json as json_module

                    tool_args[key] = json_module.loads(value)
                except json.JSONDecodeError:
                    tool_args[key] = value
            else:
                # Positional arg - assume it's the first required param
                # For convenience: `call run_browser_agent "Go to google.com"`
                tool_args["task"] = arg

    console.print(f"[bold blue]Calling {tool_name}...[/bold blue]")
    if tool_args:
        console.print(f"[dim]Arguments: {tool_args}[/dim]")

    try:
        content, is_error = asyncio.run(_async_call_tool(tool_name, tool_args))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Display result content
    for item in content:
        if hasattr(item, "text"):
            text = item.text
            # Try to pretty-print JSON
            try:
                import json as json_module

                parsed = json_module.loads(text)
                console.print_json(data=parsed)
            except (json.JSONDecodeError, TypeError):
                console.print(text)

    if is_error:
        console.print("[red]Tool returned an error[/red]")
        raise typer.Exit(1)

    console.print("[green]Done[/green]")


@app.command()
def install() -> None:
    """Install the MCP server to Claude Desktop configuration.

    Configures Claude Desktop to run mcp-server-browser-use via stdio transport.
    """
    console.print("[bold blue]Installing to Claude Desktop...[/bold blue]")

    # Detect config file location
    if sys.platform == "darwin":
        config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    elif sys.platform == "win32":
        config_path = Path(os.environ.get("APPDATA", "")) / "Claude/claude_desktop_config.json"
    else:
        config_path = Path.home() / ".config/Claude/claude_desktop_config.json"

    if not config_path.exists():
        console.print(f"[yellow]Config not found at {config_path}[/yellow]")
        if typer.confirm("Create config file?"):
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}")
        else:
            raise typer.Exit(1)

    # Read existing config
    data = json.loads(config_path.read_text())
    mcp_servers = data.get("mcpServers", {})

    cwd = Path.cwd()

    server_config = {
        "command": "uv",
        "args": ["run", "mcp-server-browser-use"],
        "cwd": str(cwd),
    }

    mcp_servers["browser-use"] = server_config
    data["mcpServers"] = mcp_servers

    config_path.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Configured 'browser-use' server in {config_path}[/green]")
    console.print("[yellow]Restart Claude Desktop to apply changes.[/yellow]")


@app.command("config")
def config_cmd(
    action: str = typer.Argument("view", help="Action: view, set, path, save"),
    key: str | None = typer.Option(None, "--key", "-k", help="Config key (e.g., llm.provider)"),
    value: str | None = typer.Option(None, "--value", "-v", help="Value to set"),
) -> None:
    """View or modify configuration."""
    if action == "path":
        console.print(str(CONFIG_FILE))
        return

    if action == "view":
        table = Table(title="Current Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("JSON Key", style="dim")

        table.add_row("Config File", str(CONFIG_FILE), "-")
        table.add_row("Results Dir", str(settings.server.results_dir or get_default_results_dir()), "server.results_dir")
        table.add_row("LLM Provider", settings.llm.provider, "llm.provider")
        table.add_row("LLM Model", settings.llm.model_name, "llm.model_name")
        table.add_row("LLM Base URL", settings.llm.base_url or "(default)", "llm.base_url")
        table.add_row("Browser Headless", str(settings.browser.headless), "browser.headless")
        table.add_row("Browser Proxy", settings.browser.proxy_server or "(none)", "browser.proxy_server")
        table.add_row("Max Steps", str(settings.agent.max_steps), "agent.max_steps")
        table.add_row("Max Searches", str(settings.research.max_searches), "research.max_searches")
        table.add_row("Server Transport", settings.server.transport, "server.transport")
        table.add_row("Server Host", settings.server.host, "server.host")
        table.add_row("Server Port", str(settings.server.port), "server.port")

        console.print(table)
        return

    if action == "save":
        path = settings.save()
        console.print(f"[green]Configuration saved to {path}[/green]")
        return

    if action == "set":
        if not key or value is None:
            console.print("[red]--key and --value required for 'set' action[/red]")
            raise typer.Exit(1)

        # Load current file config
        current = load_config_file()

        # Parse key path
        parts = key.split(".")
        target = current
        for part in parts[:-1]:
            target = target.setdefault(part, {})

        # Parse value type
        if value.lower() == "true":
            parsed_value = True
        elif value.lower() == "false":
            parsed_value = False
        elif value.isdigit():
            parsed_value = int(value)
        else:
            parsed_value = value

        target[parts[-1]] = parsed_value
        save_config_file(current)
        console.print(f"[green]Set {key} = {parsed_value}[/green]")
        console.print(f"[dim]Saved to {CONFIG_FILE}[/dim]")
        return

    console.print(f"[red]Unknown action: {action}. Use: view, set, path, save[/red]")


# --- Skill Management Commands ---

skill_app = typer.Typer(help="Manage browser skills")
app.add_typer(skill_app, name="skill")


@skill_app.command("list")
def skill_list() -> None:
    """List all available skills."""
    store = SkillStore(directory=settings.skills.directory)
    skills = store.list_all()

    if not skills:
        console.print(f"[yellow]No skills found in {store.directory}[/yellow]")
        console.print("\n[dim]Create skills manually or copy examples from:[/dim]")
        console.print("[dim]  examples/skills/[/dim]")
        return

    table = Table(title=f"Browser Skills ({store.directory})")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Success Rate", style="green")
    table.add_column("Usage", style="dim")
    table.add_column("Last Used", style="dim")

    for s in skills:
        usage = s.success_count + s.failure_count
        rate = f"{s.success_rate * 100:.0f}%" if usage > 0 else "-"
        last = s.last_used.strftime("%Y-%m-%d") if s.last_used else "-"
        table.add_row(s.name, s.description[:40], rate, str(usage), last)

    console.print(table)


@skill_app.command("get")
def skill_get(
    name: str = typer.Argument(..., help="Skill name"),
) -> None:
    """Show full details of a skill."""
    store = SkillStore(directory=settings.skills.directory)
    skill = store.load(name)

    if not skill:
        console.print(f"[red]Skill not found: {name}[/red]")
        console.print(f"[dim]Skills directory: {store.directory}[/dim]")
        raise typer.Exit(1)

    console.print(Panel(store.to_yaml(skill), title=f"Skill: {name}", expand=False))


@skill_app.command("delete")
def skill_delete(
    name: str = typer.Argument(..., help="Skill name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a skill."""
    store = SkillStore(directory=settings.skills.directory)

    if not store.exists(name):
        console.print(f"[red]Skill not found: {name}[/red]")
        raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Delete skill '{name}'?"):
            console.print("[dim]Cancelled[/dim]")
            return

    store.delete(name)
    console.print(f"[green]Skill '{name}' deleted[/green]")


# --- Observability Commands ---


@app.command()
def tasks(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of tasks to show"),
    status_filter: str | None = typer.Option(None, "--status", "-s", help="Filter by status: running, completed, failed"),
    tool_filter: str | None = typer.Option(None, "--tool", "-t", help="Filter by tool name"),
) -> None:
    """List recent tasks with status and progress."""
    import asyncio

    from .observability import TaskStatus
    from .observability.store import TaskStore

    async def _list_tasks():
        store = TaskStore()
        await store.initialize()

        status = None
        if status_filter:
            try:
                status = TaskStatus(status_filter)
            except ValueError:
                console.print(f"[red]Invalid status: {status_filter}. Use: running, completed, failed, pending[/red]")
                raise typer.Exit(1)

        return await store.get_task_history(limit=limit, status=status, tool_name=tool_filter)

    try:
        tasks_list = asyncio.run(_list_tasks())
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not tasks_list:
        console.print("[yellow]No tasks found[/yellow]")
        return

    table = Table(title=f"Recent Tasks (limit={limit})")
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Tool", style="white")
    table.add_column("Status", style="green")
    table.add_column("Progress", style="yellow")
    table.add_column("Message", style="dim", max_width=30)
    table.add_column("Duration", style="dim")
    table.add_column("Created", style="dim")

    for t in tasks_list:
        # Format status with color
        status_style = {
            "running": "[blue]running[/blue]",
            "completed": "[green]completed[/green]",
            "failed": "[red]failed[/red]",
            "pending": "[yellow]pending[/yellow]",
        }.get(t.status.value, t.status.value)

        progress = f"{t.progress_current}/{t.progress_total}" if t.progress_total > 0 else "-"
        duration = f"{t.duration_seconds:.1f}s" if t.duration_seconds else "-"
        created = t.created_at.strftime("%H:%M:%S") if t.created_at else "-"
        message = (t.progress_message[:27] + "...") if t.progress_message and len(t.progress_message) > 30 else (t.progress_message or "-")

        table.add_row(t.task_id[:8], t.tool_name, status_style, progress, message, duration, created)

    console.print(table)


@app.command("task")
def task_detail(
    task_id: str = typer.Argument(..., help="Task ID (full or prefix)"),
) -> None:
    """Show detailed information about a specific task."""
    import asyncio

    from .observability.store import TaskStore

    async def _get_task():
        store = TaskStore()
        await store.initialize()

        # Try exact match first
        task = await store.get_task(task_id)
        if task:
            return task

        # Try prefix match
        tasks = await store.get_task_history(limit=100)
        for t in tasks:
            if t.task_id.startswith(task_id):
                return t
        return None

    try:
        task = asyncio.run(_get_task())
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if not task:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    # Format task details
    status_style = {
        "running": "[blue]running[/blue]",
        "completed": "[green]completed[/green]",
        "failed": "[red]failed[/red]",
        "pending": "[yellow]pending[/yellow]",
    }.get(task.status.value, task.status.value)

    console.print(f"\n[bold]Task:[/bold] {task.task_id}")
    console.print(f"[bold]Tool:[/bold] {task.tool_name}")
    console.print(f"[bold]Status:[/bold] {status_style}")
    if task.stage:
        console.print(f"[bold]Stage:[/bold] {task.stage.value}")
    console.print(f"[bold]Progress:[/bold] {task.progress_current}/{task.progress_total} ({task.progress_percent:.1f}%)")
    if task.progress_message:
        console.print(f"[bold]Message:[/bold] {task.progress_message}")

    console.print(f"\n[bold]Created:[/bold] {task.created_at.isoformat()}")
    if task.started_at:
        console.print(f"[bold]Started:[/bold] {task.started_at.isoformat()}")
    if task.completed_at:
        console.print(f"[bold]Completed:[/bold] {task.completed_at.isoformat()}")
    if task.duration_seconds:
        console.print(f"[bold]Duration:[/bold] {task.duration_seconds:.1f}s")

    if task.input_params:
        console.print("\n[bold]Input:[/bold]")
        for key, value in task.input_params.items():
            val_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            console.print(f"  {key}: {val_str}")

    if task.result:
        console.print("\n[bold]Result:[/bold]")
        result_preview = task.result[:500] + "..." if len(task.result) > 500 else task.result
        console.print(Panel(result_preview, expand=False))

    if task.error:
        console.print("\n[bold red]Error:[/bold red]")
        console.print(Panel(task.error, style="red", expand=False))


@app.command()
def health() -> None:
    """Show server health and running task status."""
    import asyncio

    import psutil

    from .observability.store import TaskStore

    async def _get_health():
        store = TaskStore()
        await store.initialize()
        running = await store.get_running_tasks()
        stats = await store.get_stats()
        return running, stats

    # Check if server is running
    info = _read_server_info()
    if not info or not _is_process_running(info["pid"]):
        console.print("[yellow]Server not running[/yellow]")
        console.print("[dim]Start with: mcp-server-browser-use server[/dim]")
    else:
        console.print(f"[green]Server running[/green] (PID {info['pid']})")
        console.print(f"  URL: http://{info['host']}:{info['port']}/mcp")

        # Get process memory
        try:
            proc = psutil.Process(info["pid"])
            mem = proc.memory_info().rss / 1024 / 1024
            console.print(f"  Memory: {mem:.1f} MB")
        except Exception:
            pass

    # Get task stats
    try:
        running_tasks, stats = asyncio.run(_get_health())
    except Exception as e:
        console.print(f"[red]Error reading task store: {e}[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Task Statistics:[/bold]")
    console.print(f"  Total tasks: {stats.get('total_tasks', 0)}")
    console.print(f"  Running: {stats.get('running_count', 0)}")
    console.print(f"  Success rate (24h): {stats.get('success_rate_24h', 0):.1f}%")

    if stats.get("by_tool"):
        console.print("\n[bold]By Tool:[/bold]")
        for tool, count in stats["by_tool"].items():
            console.print(f"  {tool}: {count}")

    if running_tasks:
        console.print(f"\n[bold]Running Tasks ({len(running_tasks)}):[/bold]")
        for t in running_tasks:
            progress = f"{t.progress_current}/{t.progress_total}" if t.progress_total > 0 else "-"
            stage = f" ({t.stage.value})" if t.stage else ""
            console.print(f"  [{t.task_id[:8]}] {t.tool_name}{stage} - {progress}")
            if t.progress_message:
                console.print(f"    → {t.progress_message}")


# Default command when no subcommand is given
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Browser Use MCP Server & CLI.

    Run 'server' subcommand to start the HTTP MCP server.
    """
    if ctx.invoked_subcommand is None:
        # stdio is deprecated - show migration guide
        from .server import STDIO_DEPRECATION_MESSAGE

        console.print(STDIO_DEPRECATION_MESSAGE)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
