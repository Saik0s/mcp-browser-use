# MCP Browser Use Development Guidelines

> **Audience**: LLM-driven engineering agents and human developers

MCP server that wraps [browser-use](https://github.com/browser-use/browser-use) for AI-driven browser automation. HTTP-only transport (stdio deprecated due to timeout issues with long-running browser tasks).

## Required Development Workflow

**CRITICAL**: Always run these commands before committing:

```bash
uv sync                    # Install dependencies
uv run ruff format .       # Format code
uv run ruff check .        # Lint check
uv run pyright             # Type checking
uv run pytest              # Run tests
```

**All checks must pass** - this is enforced by pre-commit hooks. Alternative: `just check`

## Repository Structure

| Path | Purpose |
|------|---------|
| `src/mcp_server_browser_use/` | Library source code |
| `├─ server.py` | FastMCP server + MCP tools |
| `├─ cli.py` | Typer CLI for daemon management |
| `├─ config.py` | Pydantic settings |
| `├─ providers.py` | LLM factory (12 providers) |
| `├─ observability/` | Task tracking (SQLite persistence) |
| `├─ research/` | Deep research workflow |
| `└─ skills/` | Machine-learned browser skills |
| `tests/` | Pytest test suite |
| `docs/` | Design documents |
| `examples/` | Example usage |

## Core MCP Tools

| Tool | Purpose | Duration |
|------|---------|----------|
| `run_browser_agent` | Execute browser automation | 60-120s |
| `run_deep_research` | Multi-search research | 2-5 min |
| `skill_list/get/delete` | Skill management | <1s |
| `health_check` | Server status | <1s |
| `task_list/get/cancel` | Task management | <1s |

## Writing Code

### Style Guidelines

- Python 3.11+ with full type annotations
- Line length: 150 characters
- Use async/await for I/O operations
- Follow existing patterns - check similar code first
- Prioritize clarity over cleverness

### Code Standards

- **Type hints required** for all functions
- **Docstrings** for public APIs
- **No `any` types** - use specific types
- **Async testing** with anyio/pytest-asyncio

### Common Patterns

**Config access:**
```python
from mcp_server_browser_use.config import settings
settings.browser.headless  # Access config values
```

**MCP tool definition:**
```python
@server.tool()
async def my_tool(param: str) -> str:
    """Tool description shown to LLM clients."""
    return result
```

**Task tracking:**
```python
from mcp_server_browser_use.observability import get_task_store
task_store = get_task_store()
await task_store.create_task(task_id, "tool_name", {"args": "here"})
```

## Testing

### Test Standards

- Every test: atomic, self-contained, single functionality
- Use parameterization for multiple examples
- **NEVER** add `@pytest.mark.asyncio` - it's configured globally
- Put imports at top of file, not in test body

### Running Tests

```bash
uv run pytest                           # All tests
uv run pytest tests/test_mcp_tools.py   # Specific file
uv run pytest -k "test_name"            # Single test
uv run pytest -m "not e2e"              # Skip slow tests
```

### Test Markers

- `e2e`: End-to-end tests requiring real API keys
- `integration`: Integration tests with real browser
- `slow`: Tests that take longer to run

### FastMCP Client Testing

Use FastMCP's in-memory transport for testing:

```python
from fastmcp import Client
from mcp_server_browser_use.server import create_server

async def test_tool():
    server = create_server()
    async with Client(server) as client:
        result = await client.call_tool("health_check", {})
        assert result.data["status"] == "ok"
```

## Development Rules

### Git & Commits

- Never force-push to main
- Run pre-commit hooks before pushing
- Keep commit messages brief - focus on what changed
- Only commit when explicitly asked

### Package Management

- **ONLY use uv** - never pip
- Install: `uv add package`
- Dev install: `uv add --dev package`

### CI Fix Order

When CI fails, fix in this order:
1. `uv run ruff format .`
2. `uv run ruff check . --fix`
3. `uv run pyright`
4. `uv run pytest`

### Documentation

- Update README when features change
- Update CLAUDE.md for development guidance
- Keep config tables in sync with code

## Security Considerations

### CDP Connections

- CDP URLs restricted to localhost only (validated in config)
- Never expose CDP port to network
- Use dedicated browser profile for automation

### Skills System

- Sensitive headers (auth, cookies) are redacted before storage
- Private IPs blocked in direct execution (SSRF protection)
- Skills stored in `~/.config/browser-skills/`

### API Keys

- Prefer environment variables over config file
- Standard names: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
- Never commit API keys

## File Locations

| What | Where |
|------|-------|
| Config | `~/.config/mcp-server-browser-use/config.json` |
| Tasks DB | `~/.config/mcp-server-browser-use/tasks.db` |
| Skills | `~/.config/browser-skills/*.yaml` |
| Server Log | `~/.local/state/mcp-server-browser-use/server.log` |

## Supported LLM Providers

- anthropic, openai, google, azure_openai
- groq, deepseek, cerebras, ollama
- bedrock, browser_use, openrouter, vercel

## Key Commands Reference

```bash
# Server management
mcp-server-browser-use server          # Start daemon
mcp-server-browser-use server -f       # Foreground (debug)
mcp-server-browser-use status          # Check status
mcp-server-browser-use stop            # Stop daemon
mcp-server-browser-use logs -f         # Tail logs

# MCP tools
mcp-server-browser-use tools           # List tools
mcp-server-browser-use call <tool>     # Call tool

# Config
mcp-server-browser-use config view     # Show config
mcp-server-browser-use config set -k <key> -v <value>

# Observability
mcp-server-browser-use tasks           # List tasks
mcp-server-browser-use task <id>       # Task details
mcp-server-browser-use health          # Server health
```

## Troubleshooting

### Server Won't Start

1. Check if already running: `mcp-server-browser-use status`
2. Check logs: `mcp-server-browser-use logs`
3. Kill orphan processes: `pkill -f mcp-server-browser-use`

### Browser Issues

1. Reinstall Playwright: `uv run playwright install chromium`
2. Check headless mode: `mcp-server-browser-use config set -k browser.headless -v false`
3. Check CDP connection if using external browser

### Test Failures

1. Ensure API key is set for e2e tests
2. Run with verbose: `uv run pytest -v --tb=long`
3. Check for port conflicts (default: 8383)
