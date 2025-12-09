<img src="./assets/header.png" alt="Browser Use Web UI" width="full"/>

# browser-use MCP server & CLI

[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

AI-driven browser automation via [Model Context Protocol](https://modelcontextprotocol.io). Natural language browser control and web research.

<a href="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use"><img width="380" height="200" src="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use/badge" alt="Browser-Use MCP server" /></a>

## Quick Start

```bash
# Install Playwright browsers
uvx --from mcp-server-browser-use@latest python -m playwright install
```

Add to your MCP client (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["mcp-server-browser-use@latest"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here",
        "MCP_BROWSER_HEADLESS": "true"
      }
    }
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `run_browser_agent` | Execute browser automation via natural language |
| `run_deep_research` | Deep web research with progress tracking (supports background execution) |

Both tools support optional background execution via the MCP task protocol. When a client requests background execution, progress updates are streamed in real-time.

## CLI

```bash
mcp-browser-cli -e .env run-browser-agent "Go to example.com and get the title"
mcp-browser-cli -e .env run-deep-research "Latest AI developments"
```

## Configuration

Uses standard environment variables with fallback to `MCP_LLM_*` prefixed versions:

| Provider | Standard Env Var | MCP Fallback |
|----------|------------------|--------------|
| OpenAI | `OPENAI_API_KEY` | `MCP_LLM_OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` | `MCP_LLM_ANTHROPIC_API_KEY` |
| Google | `GOOGLE_API_KEY` | `MCP_LLM_GOOGLE_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` | `MCP_LLM_OPENROUTER_API_KEY` |
| Groq | `GROQ_API_KEY` | `MCP_LLM_GROQ_API_KEY` |

**Key Settings:**

```bash
# LLM
MCP_LLM_PROVIDER=anthropic          # openai, anthropic, google, openrouter, groq, ollama, bedrock, etc.
MCP_LLM_MODEL_NAME=claude-sonnet-4  # Model name for the provider

# Browser
MCP_BROWSER_HEADLESS=true           # Run headless
MCP_BROWSER_CDP_URL=http://localhost:9222  # Connect to existing Chrome

# Research
MCP_RESEARCH_MAX_SEARCHES=5         # Max searches per research task

# Background Tasks (FastMCP)
FASTMCP_ENABLE_TASKS=true           # Enable background task support
FASTMCP_DOCKET_URL=memory://        # Task queue: memory:// or redis://host:port
```

See `.env.example` for all options.

## Connect to Your Browser (CDP)

```bash
# 1. Launch Chrome with debugging
google-chrome --remote-debugging-port=9222

# 2. Configure
MCP_BROWSER_USE_OWN_BROWSER=true
MCP_BROWSER_CDP_URL=http://localhost:9222
```

## Development

```bash
uv sync --dev
uv run playwright install
uv run pytest                    # Run tests
uv run ruff format . && uv run ruff check .  # Format & lint
```

## License

MIT
