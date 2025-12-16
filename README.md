# mcp-server-browser-use

AI-driven browser automation via Model Context Protocol.

[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## Installation

Install the package:

```bash
uvx mcp-server-browser-use server
```

Install Playwright browsers:

```bash
uvx --from mcp-server-browser-use python -m playwright install
```

## Quick Start

Add to your MCP client configuration:

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

Set your API key:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Run browser automation:

```python
await run_browser_agent(task="Go to google.com and search for AI")
```

## Usage

### Browser Agent

Automate browser tasks with natural language:

```python
await run_browser_agent(task="Find the latest iPhone price on Apple")
```

### Deep Research

Conduct web research with progress tracking:

```python
await run_deep_research(topic="Latest developments in quantum computing")
```

### Skills System

Learn a task once:

```python
await run_browser_agent(
  task="Find iOS developer jobs on Upwork",
  learn=True,
  save_skill_as="upwork-ios-jobs"
)
```

Replay with custom parameters:

```python
await run_browser_agent(
  skill_name="upwork-ios-jobs",
  skill_params='{"keywords": "Python"}'
)
```

Skills save to `~/.config/browser-skills/` as YAML.

### CLI Commands

Start server in background:

```bash
mcp-server-browser-use server
```

Start server in foreground:

```bash
mcp-server-browser-use server -f
```

Check server status:

```bash
mcp-server-browser-use status
```

Call tools directly:

```bash
mcp-server-browser-use call run_browser_agent task="Search Google"
```

List available skills:

```bash
mcp-server-browser-use skill list
```

View current configuration:

```bash
mcp-server-browser-use config view
```

List recent tasks:

```bash
mcp-server-browser-use tasks
```

Check server health:

```bash
mcp-server-browser-use health
```

## Options

Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_LLM_PROVIDER` | `anthropic` | LLM provider (anthropic, openai, google, etc.) |
| `MCP_LLM_MODEL_NAME` | `claude-sonnet-4` | Model name |
| `MCP_BROWSER_HEADLESS` | `true` | Run browser in headless mode |
| `MCP_SERVER_HOST` | `127.0.0.1` | Server host address |
| `MCP_SERVER_PORT` | `8000` | Server port number |
| `MCP_BROWSER_CDP_URL` | - | Connect to existing Chrome instance |
| `MCP_RESEARCH_MAX_SEARCHES` | `5` | Maximum searches per research task |

API keys use standard environment variables:

| Provider | Variable |
|----------|----------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Groq | `GROQ_API_KEY` |

### Connect to Existing Browser

Launch Chrome with remote debugging enabled:

```bash
google-chrome --remote-debugging-port=9222
```

Set CDP connection environment variables:

```bash
export MCP_BROWSER_USE_OWN_BROWSER=true
export MCP_BROWSER_CDP_URL=http://localhost:9222
```

## Contributing

Pull requests welcome. Report issues on GitHub.

## License

MIT
