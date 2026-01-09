# MCP Browser Use Development Guide

> For LLM agents and human developers

MCP server wrapping [browser-use](https://github.com/browser-use/browser-use) for AI browser automation. HTTP transport only (stdio times out on 60-120s browser tasks).

## Quick Reference

```bash
# Before committing (mandatory)
uv sync && uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest

# Or use: just check
```

## Repository Map

```
mcp-server-browser-use/
├── src/mcp_server_browser_use/
│   ├── server.py          # FastMCP server, MCP tools, REST API, SSE (1556 lines)
│   ├── cli.py             # Typer CLI for daemon management (771 lines)
│   ├── config.py          # Pydantic settings - all config here (259 lines)
│   ├── providers.py       # LLM factory (12 providers)
│   ├── observability/     # Task tracking
│   │   ├── models.py      # TaskRecord, TaskStatus, TaskStage
│   │   ├── store.py       # SQLite persistence, SSE streaming
│   │   └── logging.py     # Structured logging setup
│   ├── recipes/           # Learned API shortcuts (was "skills")
│   │   ├── models.py      # Recipe, RecipeRequest, RecipeHints (600 lines)
│   │   ├── store.py       # YAML persistence in ~/.config/browser-recipes/
│   │   ├── recorder.py    # CDP network capture during agent runs
│   │   ├── analyzer.py    # LLM analysis to extract API patterns
│   │   ├── runner.py      # Direct execution via CDP fetch (661 lines)
│   │   ├── executor.py    # Hint injection for fallback mode
│   │   ├── manifest.py    # Recipe discovery and metadata
│   │   └── prompts.py     # LLM prompts for recipe analysis
│   └── research/          # Deep research workflow
│       ├── models.py      # ResearchState, ResearchResult
│       └── machine.py     # Multi-search state machine
├── tests/                 # 275+ tests (unit, integration, e2e, dashboard)
├── todos/                 # Issue tracking (P1-P3 priorities)
├── docs/                  # Design documents
└── examples/              # Usage examples
```

## Key Concepts

### Terminology

| Term | Meaning |
|------|---------|
| **Recipe** | Learned API shortcut from browser session. Stored as YAML. Executes in ~2s vs ~60s for full browser automation. NOT the same as "agent skills" (Codex/Claude SKILL.md files). |
| **Task** | Browser automation job. Tracked in SQLite with status/stage/progress. |
| **MCP Tool** | Function exposed to AI clients via Model Context Protocol. |

### Recipes System (Alpha)

Recipes are machine-learned API patterns extracted from browser sessions:

1. **Recording**: CDP captures network traffic during `run_browser_agent`
2. **Analysis**: LLM identifies the "money request" (API call returning desired data)
3. **Storage**: Recipe saved as YAML with URL template, headers, body, extract path
4. **Execution**: Two modes:
   - **Direct** (~2s): HTTP request via CDP fetch, bypass browser-use
   - **Hint-based** (~60s): Falls back to browser-use with navigation hints

```yaml
# ~/.config/browser-recipes/example.yaml
name: example-search
request:
  url: "https://api.example.com/search?q={query}"
  method: GET
  headers: { "Accept": "application/json" }
  response_type: json
  extract_path: "results[*].title"
parameters:
  - name: query
    required: true
success_count: 5
failure_count: 1
status: verified
```

### MCP Tools

| Tool | Purpose | Duration |
|------|---------|----------|
| `run_browser_agent` | Browser automation with optional recipe learning | 60-120s |
| `run_deep_research` | Multi-search research across sources | 2-5 min |
| `recipe_list` | List available recipes | <1s |
| `recipe_get` | Get recipe details | <1s |
| `recipe_delete` | Delete a recipe | <1s |
| `health_check` | Server status | <1s |
| `task_list` | List tasks | <1s |
| `task_get` | Get task details | <1s |
| `task_cancel` | Cancel running task | <1s |

### File Locations

| What | Where |
|------|-------|
| Config | `~/.config/mcp-server-browser-use/config.json` |
| Tasks DB | `~/.config/mcp-server-browser-use/tasks.db` |
| Recipes | `~/.config/browser-recipes/*.yaml` |
| Server Log | `~/.local/state/mcp-server-browser-use/server.log` |

## Development Rules

### Code Style

- Python 3.11+ with full type annotations
- Line length: 150 characters
- Async/await for I/O
- Pydantic v2 for all data models
- No `Any` types, no `@ts-ignore` equivalents

### Before Committing

```bash
uv run ruff format .   # Format
uv run ruff check .    # Lint
uv run pyright         # Type check
uv run pytest          # Test
```

All must pass. Pre-commit hooks enforce this.

### Testing

```bash
uv run pytest                        # All tests
uv run pytest tests/test_recipes.py  # Specific file
uv run pytest -k "test_name"         # Single test
uv run pytest -m "not e2e"           # Skip slow tests
```

Markers: `e2e` (real API), `integration` (real browser), `slow`

### Common Patterns

```python
# Config access
from mcp_server_browser_use.config import settings
settings.browser.headless
settings.recipes.enabled

# Recipe store
from mcp_server_browser_use.recipes import RecipeStore, get_default_recipes_dir
store = RecipeStore(get_default_recipes_dir())
recipe = await store.load("recipe-name")

# Task tracking
from mcp_server_browser_use.observability import get_task_store
store = get_task_store()
await store.create_task(task_id, "tool_name", {"args": "here"})
```

### Package Management

**Only use `uv`** - never pip.

```bash
uv add package           # Add dependency
uv add --dev package     # Add dev dependency
uv sync                  # Install from lockfile
```

## CLI Reference

```bash
# Server
mcp-server-browser-use server      # Start daemon
mcp-server-browser-use server -f   # Foreground mode
mcp-server-browser-use status      # Check if running
mcp-server-browser-use stop        # Stop daemon
mcp-server-browser-use logs -f     # Tail logs

# Config
mcp-server-browser-use config view
mcp-server-browser-use config set -k browser.headless -v false

# Recipes
mcp-server-browser-use recipe list
mcp-server-browser-use recipe get <name>
mcp-server-browser-use recipe delete <name>

# Tasks
mcp-server-browser-use tasks
mcp-server-browser-use task <id>
mcp-server-browser-use health
```

## Security

### Recipes

- Sensitive headers (Authorization, Cookie) redacted before storage
- SSRF protection: private IPs blocked in direct execution
- URL validation before fetch

### CDP

- CDP URLs restricted to localhost only
- Never expose CDP port to network

### API Keys

- Use environment variables: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Never commit keys

## Supported LLM Providers

anthropic, openai, google, azure_openai, groq, deepseek, cerebras, ollama, bedrock, browser_use, openrouter, vercel

## Troubleshooting

### Server Won't Start

1. `mcp-server-browser-use status` - check if already running
2. `mcp-server-browser-use logs` - check errors
3. `pkill -f mcp-server-browser-use` - kill orphans

### Browser Issues

1. `uv run playwright install chromium` - reinstall browser
2. Set `browser.headless: false` to debug visually
3. Check CDP connection if using external browser

### Test Failures

1. Set API key for e2e tests
2. `uv run pytest -v --tb=long` for verbose output
3. Check port 8383 not in use

## Architecture Summary

```
MCP Clients (Claude Desktop, CLI)
        │
        │ HTTP / SSE
        ▼
┌────────────────────────────────┐
│   FastMCP Server (server.py)   │
│   - MCP tools                  │
│   - REST API                   │
│   - Web dashboard              │
│   - SSE task streaming         │
└───────┬────────────────────────┘
        │
   ┌────┴────┬──────────┬────────────┐
   ▼         ▼          ▼            ▼
Config    LLM       Recipes      Observability
Pydantic  Factory   CDP+YAML     SQLite+SSE
          12 provs  ~2s exec     Task tracking
                        │
                        ▼
                  browser-use
                (Agent + Playwright)
```

## Open Issues

Check `todos/` for current issues:
- P1: Critical (auth)
- P2: Medium (8 issues)
- P3: Low (7 issues)

### Recent Progress (2025-01-09)

**Phase 0 Fixes (Complete):**
- ✅ URL encoding bug fixed: `runner.py` now uses `request.build_url()` consistently (standalone `build_url()` deprecated)
- ✅ Response size cap verified: `MAX_RESPONSE_SIZE = 1_000_000` (1MB) already implemented

**E2E Recipe Learning Tests (tests/test_e2e_recipe_learning.py):**
- ✅ 10 tests pass, 3 skipped (need API key + browser)
- Tests cover: GitHub repo search, npm package search, RemoteOK job search
- Manifest format matches `plans/skills-library-150-services.md` with `example_params`
- Tests validate: URL encoding consistency, response size cap, manifest format

**Watchtower Integration Blockers:**
- Transport defaults still inconsistent (see issue atl.1)
- Pre-existing test failures in dashboard API routes (404 errors)
- Tool count mismatch in test_mcp_tools.py (expects 9, has 10)

## browser-use Library Reference

See embedded `<browser_use_docs>` section below for upstream library documentation.

<browser_use_docs>
Browser-Use is an AI agent that autonomously interacts with the web. It takes a user-defined task, navigates web pages using Chromium via CDP, processes HTML, and repeatedly queries a language model to decide the next action.

Recommended model: `ChatBrowserUse` (fastest, lowest cost, built for browser automation).

For cloud browsers with captcha bypass: `Browser(use_cloud=True)` with `BROWSER_USE_API_KEY`.

Full docs: https://docs.browser-use.com
</browser_use_docs>
