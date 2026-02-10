# MCP Browser Use Development Guide

> For LLM agents and human developers

MCP server wrapping [browser-use](https://github.com/browser-use/browser-use) for AI browser automation. HTTP transport only (stdio times out on 60-120s browser tasks).

## Quick Reference

```bash
# Before committing (mandatory)
just check    # format + lint + typecheck + test

# Or manually:
uv sync && uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

## How It Works

```
MCP Client (Claude Desktop, Cursor, etc.)
       │
       │  HTTP (streamable-http on :8383)
       ▼
┌──────────────────────────────────────────┐
│   FastMCP Server (daemon)                │
│                                          │
│   MCP Tools:                             │
│   - run_browser_agent (60-120s)          │
│   - run_deep_research (2-5 min)          │
│   - recipe_list/get/delete/run_direct    │
│   - health_check, task_list/get/cancel   │
│                                          │
│   REST API:     Web Dashboard:           │
│   /api/health   GET / (viewer)           │
│   /api/tasks    GET /dashboard           │
│   /api/recipes  SSE /api/events          │
│   /api/learn                             │
└──────────┬───────────────────────────────┘
           │
  ┌────────┼────────┬──────────┬────────────┐
  ▼        ▼        ▼          ▼            ▼
Config   LLM     Recipes    Research    Observability
Pydantic Factory CDP+YAML   State Mach  SQLite+SSE
         12 provs                       Task tracking
                    │
           ┌────────┴────────┐
           ▼                 ▼
      Direct Exec       browser-use
      CDP fetch()       Agent + Playwright
      ~2 seconds        ~60 seconds
           │                 │
           └────────┬────────┘
                    ▼
                Chromium
            (headless or headed)
```

### Connection Methods

```bash
# 1. Native HTTP (preferred, if client supports streamable-http)
# Client config: {"url": "http://localhost:8383/mcp"}

# 2. mcp-remote bridge (works with any MCP client)
# Client config: {"command": "npx", "args": ["mcp-remote", "http://localhost:8383/mcp"]}

# 3. Stdio proxy (backward compat, auto-starts server)
# Client config: {"command": "uvx", "args": ["mcp-server-browser-use"]}
```

## Repository Map

```
mcp-server-browser-use/
├── src/mcp_server_browser_use/
│   ├── server.py          # FastMCP server, MCP tools, REST API, SSE (~1825 lines)
│   ├── cli.py             # Typer CLI for daemon management (771 lines)
│   ├── config.py          # Pydantic settings, env vars + config file (281 lines)
│   ├── providers.py       # LLM factory (12 providers, 130 lines)
│   ├── observability/     # Task tracking
│   │   ├── models.py      # TaskRecord, TaskStatus, TaskStage
│   │   ├── store.py       # SQLite persistence (WAL mode, async)
│   │   └── logging.py     # Structured logging (structlog + contextvars)
│   ├── recipes/           # Learned API shortcuts
│   │   ├── models.py      # Recipe, RecipeRequest, RecipeHints (~700 lines)
│   │   ├── store.py       # YAML persistence in ~/.config/browser-recipes/
│   │   ├── recorder.py    # CDP network capture during agent runs (~437 lines)
│   │   ├── analyzer.py    # LLM analysis to extract API patterns (~314 lines)
│   │   ├── runner.py      # Direct execution via CDP fetch (~809 lines)
│   │   ├── executor.py    # Hint injection for fallback mode (72 lines)
│   │   ├── manifest.py    # Recipe discovery and metadata (170 lines)
│   │   └── prompts.py     # LLM prompts for recipe analysis (260 lines)
│   └── research/          # Deep research workflow
│       ├── models.py      # ResearchSource, SearchResult
│       ├── machine.py     # Multi-search state machine (211 lines)
│       └── prompts.py     # Planning + synthesis prompts
├── tests/                 # 297 tests (unit, integration, e2e, dashboard)
├── plans/                 # Design documents and plans
│   ├── PLAN_TO_SHIP_MCP_BROWSER_USE.md  # Master plan (current state + roadmap)
│   └── skills-library-150-services.md   # Recipe library scale-up plan
├── todos/                 # Issue tracking (P1-P3 priorities, 16 issues)
└── .apr/                  # Automated Plan Reviser config
```

**Total**: ~7,000 lines production code, ~4,300 lines test code

## Key Concepts

### Terminology

| Term | Meaning |
|------|---------|
| **Recipe** | Learned API shortcut from browser session. Stored as YAML. Executes in ~2s vs ~60s for full browser automation. NOT the same as "agent skills" (Codex/Claude SKILL.md files). |
| **Task** | Browser automation job. Tracked in SQLite with status/stage/progress. |
| **MCP Tool** | Function exposed to AI clients via Model Context Protocol. |
| **Direct Execution** | Recipe fast path: CDP `fetch()` in browser context (~2s). Inherits cookies/session. |
| **Hint-Based Execution** | Recipe fallback: browser-use agent with navigation hints (~60s). |

### Recipes System (Alpha)

Recipes are machine-learned API patterns extracted from browser sessions:

```
LEARN                  ANALYZE                STORE              EXECUTE

Agent runs task       LLM identifies          YAML written       Two paths:
while CDP recorder    "money request"         to ~/.config/
captures network      from captured           browser-recipes/   ├─ Direct: CDP fetch() ~2s
traffic               traffic                                    │  (recipe.request exists)
                                                                 └─ Hint-based: agent ~60s
recorder.py ────────> analyzer.py ──────────> store.py ────────>     (fallback)
```

**Recipe YAML format:**
```yaml
# ~/.config/browser-recipes/example.yaml
name: example-search
request:
  url: "https://api.example.com/search?q={query}"
  method: GET
  headers: { "Accept": "application/json" }
  response_type: json           # json | html | text
  extract_path: "results[*].title"  # JMESPath for JSON
  html_selectors:               # CSS selectors for HTML
    title: "h3 a"
    link: "h3 a@href"          # @attr suffix extracts attribute
  allowed_domains: ["example.com"]
parameters:
  - name: query
    required: true
success_count: 5
failure_count: 1
status: verified                # draft | verified | deprecated
```

### MCP Tools (10 when recipes enabled, 6 when disabled)

| Tool | Purpose | Duration |
|------|---------|----------|
| `run_browser_agent` | Browser automation with optional recipe learning | 60-120s |
| `run_deep_research` | Multi-search research across sources | 2-5 min |
| `recipe_list` | List available recipes | <1s |
| `recipe_get` | Get recipe details | <1s |
| `recipe_delete` | Delete a recipe | <1s |
| `recipe_run_direct` | Direct API execution (~2s) | 1-8s |
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
| Server PID | `~/.local/state/mcp-server-browser-use/server.json` |
| Server Log | `~/.local/state/mcp-server-browser-use/server.log` |

## Development Rules

### Code Style

- Python 3.11+ with full type annotations
- Line length: 150 characters
- Async/await for I/O
- Pydantic v2 for all data models
- No `Any` types, no `@ts-ignore` equivalents
- Files under 500 lines preferred, split when unwieldy

### Before Committing

```bash
just check    # Runs: format + lint + typecheck + test
```

Pre-commit hooks also enforce: validate-pyproject, prettier, ruff, uv-lock-check, pyright, no-commit-to-branch, codespell.

### Testing

```bash
uv run pytest                        # All 297 tests
uv run pytest tests/test_recipes.py  # Specific file
uv run pytest -k "test_name"         # Single test
uv run pytest -m "not e2e"           # Skip slow tests
```

Markers: `e2e` (real API + browser), `integration` (real browser), `slow`

### Common Patterns

```python
# Config access
from mcp_server_browser_use.config import settings
settings.browser.headless
settings.recipes.enabled

# Recipe store
from mcp_server_browser_use.recipes import RecipeStore, get_default_recipes_dir
store = RecipeStore(get_default_recipes_dir())
recipe = store.load("recipe-name")

# Task tracking
from mcp_server_browser_use.observability import get_task_store
store = get_task_store()
await store.create_task(task_record)

# LLM provider
from mcp_server_browser_use.providers import get_llm
llm = get_llm(provider="openrouter", model="moonshotai/kimi-k2.5", api_key="...")
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
# Server lifecycle
mcp-server-browser-use server      # Start daemon (background)
mcp-server-browser-use server -f   # Foreground mode (debugging)
mcp-server-browser-use status      # Check if running
mcp-server-browser-use stop        # Stop daemon (SIGTERM, then SIGKILL)
mcp-server-browser-use logs -f     # Tail server log

# Config
mcp-server-browser-use config view
mcp-server-browser-use config set -k browser.headless -v false
mcp-server-browser-use config set -k recipes.enabled -v true

# Recipes
mcp-server-browser-use recipe list
mcp-server-browser-use recipe get <name>
mcp-server-browser-use recipe delete <name>

# Tasks
mcp-server-browser-use tasks
mcp-server-browser-use task <id>
mcp-server-browser-use health

# MCP tools (via FastMCP client)
mcp-server-browser-use tools
mcp-server-browser-use call <tool> [key=value...]
```

## Security

### Non-Negotiables

1. **HTTP transport only.** Stdio blocked with migration message.
2. **Recipes never store secrets.** Authorization, Cookie, X-Api-Key stripped before YAML storage.
3. **SSRF protection on all direct execution.** Private IPs blocked, DNS rebinding checked. URL validated twice (before nav AND before fetch).
4. **CDP restricted to localhost.** Non-localhost CDP URLs rejected at config validation.
5. **Response bodies capped at 1MB.** Enforced in JS fetch code.
6. **Task results truncated to 10KB in SQLite.** Prevents DB bloat.

### API Keys

Use environment variables: `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Never commit keys.

## Supported LLM Providers

anthropic, openai, google, azure_openai, groq, deepseek, cerebras, ollama, bedrock, browser_use, openrouter, vercel

**Default**: `openrouter` with `moonshotai/kimi-k2.5`

## Config Hierarchy

```
Environment Variables (highest priority)
  MCP_LLM_PROVIDER, MCP_LLM_MODEL_NAME, MCP_BROWSER_HEADLESS, etc.
       ▼
Config File (~/.config/mcp-server-browser-use/config.json)
       ▼
Pydantic Defaults (lowest priority)
```

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

## Open Issues

16 tracked issues in `todos/`:
- **P1** (1): Auth token not enforced for non-localhost
- **P2** (8): Atomic writes, name collisions, async I/O, bg task cleanup, allowed_domains, response caps, output validation
- **P3** (7): JSON-only recorder, missing deps, weak validation, docs mismatch, error handling, header constants, REST direct exec

See `plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md` for the full roadmap with phases, ADRs, threat model, and implementation checklist.

## Current Progress (2026-02-09)

### Completed (Phase 0)
- FastMCP 3.0 beta upgrade (HTTP transport, daemon mode)
- Stdio-to-HTTP proxy for backward compatibility
- URL encoding bug fixed (`request.build_url()` canonical)
- Response size cap (1MB in JS fetch)
- Skills renamed to Recipes throughout codebase
- HTML-based recipe extraction with CSS selectors
- Multi-field extraction with @attr suffix support
- Selector validation and fallback suggestions
- E2E recipe learning tests (10 pass, 3 skip)
- REST API + SSE endpoints for task monitoring
- Web dashboard (viewer + management)

### In Progress (Phase 1: Recipe Learning)
- Improving auto-learning success rate (currently 20%, target 60%+)
- Better analyzer prompts for simple GET APIs
- Parameter passing fixes

### Planned
- Phase 1.2: Runner + policy parity hardening (EgressPolicy, transport parity, pooled clients)
- Phase 1.5: Learning corpus + offline evaluation (measurable success rate)
- Phase 2: Hardening + contract stabilization (P1/P2 issues, tool surface freeze, OpenAPI)
- Phase 3: Recipe library scale-up (20+ verified recipes)
- Phase 4: Polish & release (CI, PyPI, docs)

### Plan Document
See `PLAN_TO_SHIP_MCP_BROWSER_USE.md` (v2.7) for the comprehensive roadmap with:
- 8-stage recipe pipeline (record → signals → candidates → analyze → validate → baseline → minimize → verify)
- 3-tier transport strategy (httpx_public → context_request → in_page_fetch)
- 25+ threat model entries with mapped tests
- 15+ non-negotiables and invariants
- Artifact-based pipeline with deterministic replay
- 5 quality gates (pre-commit, pre-merge, hostile web, golden+fuzz, perf regression)

## browser-use Library Reference

<browser_use_docs>
Browser-Use is an AI agent that autonomously interacts with the web. It takes a user-defined task, navigates web pages using Chromium via CDP, processes HTML, and repeatedly queries a language model to decide the next action.

Recommended model: `ChatBrowserUse` (fastest, lowest cost, built for browser automation).

For cloud browsers with captcha bypass: `Browser(use_cloud=True)` with `BROWSER_USE_API_KEY`.

Full docs: https://docs.browser-use.com
</browser_use_docs>
