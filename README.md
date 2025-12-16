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
| `skill_list` | List all learned browser skills |
| `skill_get` | Get details of a specific skill |
| `skill_delete` | Delete a learned skill |

Both tools support optional background execution via the MCP task protocol. When a client requests background execution, progress updates are streamed in real-time.

## Skills (Learn & Replay)

The Skills feature enables learning browser tasks once and replaying them efficiently. Skills are **machine-generated** from successful learning sessions.

### Learning Mode

```python
# Learn a new skill - agent discovers API endpoints
result = await run_browser_agent(
    task="Find new iOS developer jobs on Upwork",
    learn=True,                     # Enable API discovery mode
    save_skill_as="upwork-ios-jobs" # Save extracted skill
)
```

### Execution Mode

```python
# Use learned skill with hints for efficient execution
result = await run_browser_agent(
    task="Find new Python developer jobs",
    skill_name="upwork-ios-jobs",
    skill_params='{"keywords": "Python"}'
)
```

Skills are stored in `~/.config/browser-skills/` as YAML files. See [docs/skills-design.md](docs/skills-design.md) for full documentation.

## CLI

Single unified command: `mcp-server-browser-use`

```bash
# Start HTTP MCP server
mcp-server-browser-use server
mcp-server-browser-use server --port 8080

# Connect to server via stdio proxy (for Claude Desktop)
mcp-server-browser-use connect
mcp-server-browser-use connect --url http://localhost:8383/mcp

# Run browser task directly
mcp-server-browser-use run "Go to example.com and get the title"

# Run deep research
mcp-server-browser-use research "Latest AI developments"

# Install to Claude Desktop (configures connect command)
mcp-server-browser-use install

# View configuration
mcp-server-browser-use config view

# Update configuration
mcp-server-browser-use config set --key llm.provider --value openai
mcp-server-browser-use config set --key browser.headless --value false

# Save current config to file
mcp-server-browser-use config save
```

### Architecture

```
┌─────────────────┐     stdio      ┌─────────────────┐     HTTP      ┌─────────────────┐
│  Claude Desktop │ ◄────────────► │     connect     │ ◄───────────► │     server      │
└─────────────────┘                └─────────────────┘               └─────────────────┘
```

1. `server` - Runs persistent HTTP server (default: `http://127.0.0.1:8383/mcp`)
2. `connect` - stdio proxy that forwards to the HTTP server

### Persistent Configuration

Config file location: `~/.config/mcp-server-browser-use/config.json`

Results auto-save to: `~/Documents/mcp-browser-results/` (when `server.results_dir` is set)

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
