# mcp-server-browser-use

MCP server that gives AI assistants the power to control a web browser.

[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## What is this?

This wraps [browser-use](https://github.com/browser-use/browser-use) as an MCP server, letting Claude (or any MCP client) automate a real browser - navigate pages, fill forms, click buttons, extract data, and more.

### Why HTTP instead of stdio?

Browser automation tasks can take 30-120+ seconds. The standard MCP stdio transport has timeout issues with long-running operations - the connection would drop mid-task. **HTTP transport solves this** by running the server as a persistent daemon that handles requests reliably regardless of duration.

## Installation

```bash
# Install and start the server
uvx mcp-server-browser-use server

# Install browser (first time only)
uvx --from mcp-server-browser-use playwright install chromium
```

## Quick Start

**1. Start the server:**

```bash
mcp-server-browser-use server
```

**2. Add to Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

**3. Set your API key** (the browser agent needs an LLM to decide what to do):

```bash
export ANTHROPIC_API_KEY=your-key-here
```

**4. Ask Claude to browse!** Claude can now use the `run_browser_agent` tool.

## What Can It Do?

### Browser Automation

Tell the agent what you want in plain English:

```bash
# Via CLI (for testing)
mcp-server-browser-use call run_browser_agent task="Find the price of iPhone 16 Pro on Apple's website"
```

The agent will launch a browser, navigate to apple.com, find the product, and return the price.

### Deep Research

Multi-step web research with automatic source synthesis:

```bash
mcp-server-browser-use call run_deep_research topic="Latest developments in quantum computing"
```

The agent searches multiple sources, extracts key findings, and compiles a research report.

## Skills System (⚠️ Super Alpha)

> **Warning:** This feature is experimental and under active development. Expect rough edges.

Skills let you "teach" the agent a task once, then replay it faster by reusing discovered API endpoints instead of full browser automation.

**Learn a skill:**

```bash
mcp-server-browser-use call run_browser_agent \
  task="Find iOS developer jobs on Upwork" \
  learn=true \
  save_skill_as="upwork-ios-jobs"
```

**Replay with different parameters:**

```bash
mcp-server-browser-use call run_browser_agent \
  skill_name="upwork-ios-jobs" \
  skill_params='{"keywords": "Python"}'
```

Skills are saved as YAML in `~/.config/browser-skills/`. Direct execution (when the skill has captured an API endpoint) takes ~2 seconds vs 60-120 seconds for full browser automation.

## CLI Reference

```bash
# Server management
mcp-server-browser-use server          # Start as background daemon
mcp-server-browser-use server -f       # Start in foreground (for debugging)
mcp-server-browser-use status          # Check if running
mcp-server-browser-use stop            # Stop the daemon
mcp-server-browser-use logs -f         # Tail server logs

# Calling tools directly
mcp-server-browser-use call run_browser_agent task="..."
mcp-server-browser-use call run_deep_research topic="..."
mcp-server-browser-use tools           # List all available MCP tools

# Skills
mcp-server-browser-use call skill_list
mcp-server-browser-use call skill_get name="skill-name"

# Observability
mcp-server-browser-use tasks           # List recent tasks
mcp-server-browser-use task <id>       # Get task details
mcp-server-browser-use health          # Server health + stats
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_LLM_PROVIDER` | `anthropic` | LLM provider (anthropic, openai, google, groq, openrouter) |
| `MCP_LLM_MODEL_NAME` | `claude-sonnet-4` | Model for the browser agent |
| `MCP_BROWSER_HEADLESS` | `true` | Run browser without GUI |
| `MCP_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `MCP_SERVER_PORT` | `8000` | Server port |

API keys (use standard env vars):

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `OPENROUTER_API_KEY`
- `GROQ_API_KEY`

### Using Your Own Browser

Connect to an existing Chrome instance (useful for staying logged into sites):

```bash
# Launch Chrome with debugging enabled
google-chrome --remote-debugging-port=9222

# Configure the server to use it
export MCP_BROWSER_USE_OWN_BROWSER=true
export MCP_BROWSER_CDP_URL=http://localhost:9222
```

## License

MIT
