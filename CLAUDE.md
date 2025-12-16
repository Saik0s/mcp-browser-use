# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP server exposing browser-use as tools for AI-driven browser automation. Implements the Model Context Protocol for natural language browser control and web research.

## Common Commands

```bash
# Install dependencies
uv sync --dev

# Install Playwright browsers (required for automation)
uv run playwright install

# Run MCP server (stdio - default)
uv run mcp-server-browser-use

# Run MCP server (HTTP - stateful)
MCP_SERVER_TRANSPORT=streamable-http MCP_SERVER_PORT=8000 uv run mcp-server-browser-use
# Server runs at http://localhost:8000/mcp

# Run MCP server (SSE transport)
MCP_SERVER_TRANSPORT=sse MCP_SERVER_PORT=8000 uv run mcp-server-browser-use

# Run CLI
uv run mcp-browser-cli -e .env run-browser-agent "Go to example.com"
uv run mcp-browser-cli -e .env run-deep-research "Research topic"

# Testing
uv run pytest                           # Run all tests
uv run pytest tests/test_mcp_tools.py   # Run specific test file
uv run pytest -k "test_name"            # Run single test by name
uv run pytest -v --tb=short             # Verbose with short traceback

# Code quality
uv run ruff format .                    # Format code
uv run ruff check .                     # Lint check
uv run ruff check . --fix               # Auto-fix lint issues
uv run pyright                          # Type checking

# Debug with MCP Inspector
npx @modelcontextprotocol/inspector@latest \
  -e MCP_LLM_PROVIDER=google \
  -e MCP_LLM_MODEL_NAME=gemini-2.5-flash-preview-04-17 \
  -e GOOGLE_API_KEY=$GOOGLE_API_KEY \
  uv --directory . run mcp-server-browser-use
```

## Architecture

```
src/mcp_server_browser_use/
├── server.py       # FastMCP server - defines MCP tools (run_browser_agent, run_deep_research, skill_*)
├── config.py       # Pydantic settings - all MCP_* env vars parsed here
├── providers.py    # LLM factory - get_llm() creates LLM instances for different providers
├── cli.py          # Typer CLI - mcp-browser-cli entrypoint
├── exceptions.py   # Custom exceptions (LLMProviderError, BrowserError)
├── research/       # Deep research subsystem
│   ├── models.py   # ResearchSource, SearchResult dataclasses
│   ├── machine.py  # ResearchMachine - executes research workflow with progress tracking
│   └── prompts.py  # Prompt templates for research queries
└── skills/         # Skills learning and replay subsystem
    ├── __init__.py # Public API exports
    ├── models.py   # Skill, MoneyRequest, SessionRecording dataclasses
    ├── store.py    # SkillStore - YAML persistence (~/.config/browser-skills/)
    ├── executor.py # SkillExecutor - hint injection + learning mode instructions
    ├── analyzer.py # SkillAnalyzer - LLM extraction of money request from recording
    ├── recorder.py # SkillRecorder - CDP network event capture during learning
    └── prompts.py  # API discovery and analysis prompts
```

**Key Patterns:**
- `server.py` uses FastMCP decorator `@server.tool(task=TaskConfig(mode="optional"))` to expose MCP tools with optional background execution
- Config uses `pydantic_settings` with env var prefixes: `MCP_LLM_*`, `MCP_BROWSER_*`, `MCP_AGENT_TOOL_*`
- API key resolution: Standard env vars (e.g., `OPENAI_API_KEY`) take priority over `MCP_LLM_*` prefixed ones
- Background tasks use FastMCP's native task protocol with Progress dependency for status updates
- Tests use FastMCP's `Client` class for in-memory testing
- Skills use CDP network recording via `browser_session.cdp_client` for API discovery during learning mode

## Development Rules

### Package Management
- ONLY use uv, NEVER pip
- Install: `uv add package`
- Dev install: `uv add --dev package`
- FORBIDDEN: `uv pip install`, `@latest` syntax

### Code Quality
- Type hints required for all code
- Public APIs must have docstrings
- Line length: 150 chars maximum
- Async testing: use anyio, not asyncio

### Testing
- Framework: pytest with pytest-asyncio
- MCP tools tested via FastMCP's `Client` class for in-memory testing
- New features require tests
- Bug fixes require regression tests

### CI Fix Order
1. Formatting (`uv run ruff format .`)
2. Type errors (`uv run pyright`)
3. Linting (`uv run ruff check .`)

## API Key Configuration

Standard env vars take priority (for compatibility with other tools):
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`, etc.
- Fallback: `MCP_LLM_<PROVIDER>_API_KEY` (e.g., `MCP_LLM_OPENAI_API_KEY`)
- Generic override: `MCP_LLM_API_KEY` takes highest priority

Providers without API keys: `ollama`, `bedrock` (uses AWS credentials)

## Server Transport Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `MCP_SERVER_TRANSPORT` | `stdio` | Transport type: `stdio`, `streamable-http`, or `sse` |
| `MCP_SERVER_HOST` | `127.0.0.1` | Host for HTTP transports |
| `MCP_SERVER_PORT` | `8000` | Port for HTTP transports |

**Connecting Claude Code to HTTP server:**

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
