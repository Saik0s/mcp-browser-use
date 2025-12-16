# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP server exposing browser-use as tools for AI-driven browser automation. HTTP-only server (stdio deprecated due to timeout issues with long-running browser tasks).

## Common Commands

```bash
# Install dependencies
uv sync --dev

# Install Playwright browsers
uv run playwright install

# Start HTTP server (background daemon)
mcp-server-browser-use server

# Start HTTP server (foreground, for debugging)
mcp-server-browser-use server -f

# Server management
mcp-server-browser-use status
mcp-server-browser-use stop
mcp-server-browser-use logs -f

# List available MCP tools
mcp-server-browser-use tools

# Call MCP tools directly from CLI
mcp-server-browser-use call skill_list
mcp-server-browser-use call run_browser_agent task="Go to google.com"

# Observability
mcp-server-browser-use tasks                    # List recent tasks
mcp-server-browser-use tasks --status running   # Filter by status
mcp-server-browser-use task <id>                # Task details
mcp-server-browser-use health                   # Server health + stats

# Testing
uv run pytest                           # Run all tests
uv run pytest tests/test_mcp_tools.py   # Run specific test file
uv run pytest -k "test_name"            # Run single test by name

# Code quality
uv run ruff format .                    # Format code
uv run ruff check .                     # Lint check
uv run pyright                          # Type checking
```

## Architecture

```
src/mcp_server_browser_use/
├── server.py         # FastMCP server - MCP tools (run_browser_agent, run_deep_research, skill_*, health_check, task_*)
├── config.py         # Pydantic settings - MCP_* env vars
├── providers.py      # LLM factory - get_llm() for different providers
├── cli.py            # Typer CLI - server management + MCP client commands + observability
├── observability/    # Task tracking and health monitoring
│   ├── models.py     # TaskRecord, TaskStatus, TaskStage dataclasses
│   ├── store.py      # TaskStore - SQLite persistence (~/.config/mcp-server-browser-use/tasks.db)
│   └── logging.py    # structlog + contextvars for per-task logging
├── research/         # Deep research subsystem
│   ├── models.py     # ResearchSource, SearchResult
│   ├── machine.py    # ResearchMachine - research workflow
│   └── prompts.py    # Research prompt templates
└── skills/           # Skills learning and direct execution
    ├── models.py     # Skill, SkillRequest, AuthRecovery dataclasses
    ├── store.py      # SkillStore - YAML persistence (~/.config/browser-skills/)
    ├── runner.py     # SkillRunner - direct fetch() execution via CDP
    ├── executor.py   # SkillExecutor - hint injection for agent mode
    ├── analyzer.py   # SkillAnalyzer - LLM extraction from recordings
    ├── recorder.py   # SkillRecorder - CDP network capture
    └── prompts.py    # Analysis prompts
```

**Key Patterns:**
- `server.py`: FastMCP with `@server.tool()` decorator, stdio deprecated (exits with migration message)
- `cli.py`: Typer app with `tools` and `call` commands that connect to running server via FastMCP Client
- `runner.py`: Direct skill execution via CDP `Runtime.evaluate` with `session_id` (bypasses browser-use watchdogs)
- `store.py` (observability): SQLite with aiosqlite for async task persistence
- Config: `pydantic_settings` with env var prefixes `MCP_LLM_*`, `MCP_BROWSER_*`
- Tests: FastMCP's `Client` class for in-memory testing

**Skills Two Execution Modes:**
1. **Direct execution** (~2s): If `skill.request` exists, SkillRunner executes fetch() via CDP
2. **Agent execution** (~60-120s): Falls back to browser-use agent with hints

**Observability:**
- All `run_browser_agent` and `run_deep_research` calls track task lifecycle in SQLite
- MCP tools: `health_check`, `task_list`, `task_get` for introspection
- CLI commands: `tasks`, `task <id>`, `health` for local visibility

## Development Rules

### Package Management
- ONLY use uv, NEVER pip
- Install: `uv add package`
- Dev install: `uv add --dev package`

### Code Quality
- Type hints required
- Public APIs need docstrings
- Line length: 150 chars max
- Async testing: use anyio

### CI Fix Order
1. `uv run ruff format .`
2. `uv run pyright`
3. `uv run ruff check .`

## API Keys

Standard env vars take priority:
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`
- Fallback: `MCP_LLM_<PROVIDER>_API_KEY`

## Server Configuration

Server runs HTTP only. Default: `http://localhost:8000/mcp`

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_HOST` | `127.0.0.1` | Host |
| `MCP_SERVER_PORT` | `8000` | Port |
| `MCP_LLM_PROVIDER` | `anthropic` | LLM provider |
| `MCP_BROWSER_HEADLESS` | `true` | Headless mode |

**Claude Desktop config:**
```json
{
  "mcpServers": {
    "browser-use": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```
