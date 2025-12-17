# mcp-server-browser-use

MCP server that gives AI assistants the power to control a web browser.

[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [What is this?](#what-is-this)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [MCP Tools](#mcp-tools)
- [Deep Research](#deep-research)
- [Observability](#observability)
- [Skills System](#skills-system-super-alpha)
- [Architecture](#architecture)
- [License](#license)

---

## What is this?

This wraps [browser-use](https://github.com/browser-use/browser-use) as an MCP server, letting Claude (or any MCP client) automate a real browser—navigate pages, fill forms, click buttons, extract data, and more.

### Why HTTP instead of stdio?

Browser automation tasks take 30-120+ seconds. The standard MCP stdio transport has timeout issues with long-running operations—connections drop mid-task. **HTTP transport solves this** by running as a persistent daemon that handles requests reliably regardless of duration.

---

## Installation

```bash
# Install and start the server
uvx mcp-server-browser-use server

# Install browser (first time only)
uvx --from mcp-server-browser-use playwright install chromium
```

---

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

For MCP clients that don't support HTTP transport, use `mcp-remote` as a proxy:

```json
{
  "mcpServers": {
    "browser-use": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

**3. Set your API key** (the browser agent needs an LLM to decide actions):

```bash
mcp-server-browser-use config set -k llm.api_key -v your-key-here
```

**4. Ask Claude to browse!** Claude can now use the `run_browser_agent` tool.

---

## Configuration

Settings are stored in `~/.config/mcp-server-browser-use/config.json`.

**View current config:**

```bash
mcp-server-browser-use config view
```

**Change settings:**

```bash
mcp-server-browser-use config set -k llm.provider -v openai
mcp-server-browser-use config set -k llm.model_name -v gpt-4o
mcp-server-browser-use config set -k llm.api_key -v sk-...
mcp-server-browser-use config set -k browser.headless -v false
mcp-server-browser-use config set -k agent.max_steps -v 30
```

### Settings Reference

| Key | Default | Description |
|-----|---------|-------------|
| `llm.provider` | `anthropic` | LLM provider (anthropic, openai, google, groq, openrouter) |
| `llm.model_name` | `claude-sonnet-4` | Model for the browser agent |
| `llm.api_key` | - | API key for the provider |
| `browser.headless` | `true` | Run browser without GUI |
| `agent.max_steps` | `20` | Max steps per browser task |
| `research.max_searches` | `5` | Max searches per research task |
| `server.host` | `127.0.0.1` | Server bind address |
| `server.port` | `8000` | Server port |

### Config Priority

```
Environment Variables > Config File > Defaults
```

Environment variables use prefix `MCP_` + section + `_` + key (e.g., `MCP_LLM_PROVIDER`).

### Using Your Own Browser

Connect to an existing Chrome instance (useful for staying logged into sites):

```bash
# Launch Chrome with debugging enabled
google-chrome --remote-debugging-port=9222

# Configure the server to use it
mcp-server-browser-use config set -k browser.use_own_browser -v true
mcp-server-browser-use config set -k browser.cdp_url -v http://localhost:9222
```

---

## CLI Reference

### Server Management

```bash
mcp-server-browser-use server          # Start as background daemon
mcp-server-browser-use server -f       # Start in foreground (for debugging)
mcp-server-browser-use status          # Check if running
mcp-server-browser-use stop            # Stop the daemon
mcp-server-browser-use logs -f         # Tail server logs
```

### Calling Tools

```bash
mcp-server-browser-use tools           # List all available MCP tools
mcp-server-browser-use call run_browser_agent task="Go to google.com"
mcp-server-browser-use call run_deep_research topic="quantum computing"
```

### Configuration

```bash
mcp-server-browser-use config view     # Show all settings
mcp-server-browser-use config set -k <key> -v <value>
mcp-server-browser-use config path     # Show config file location
```

### Observability

```bash
mcp-server-browser-use tasks           # List recent tasks
mcp-server-browser-use tasks --status running
mcp-server-browser-use task <id>       # Get task details
mcp-server-browser-use health          # Server health + stats
```

### Skills Management

```bash
mcp-server-browser-use call skill_list
mcp-server-browser-use call skill_get name="my-skill"
mcp-server-browser-use call skill_delete name="my-skill"
```

---

## MCP Tools

These tools are exposed via MCP for AI clients:

| Tool | Description | Typical Duration |
|------|-------------|------------------|
| `run_browser_agent` | Execute browser automation tasks | 60-120s |
| `run_deep_research` | Multi-search research with synthesis | 2-5 min |
| `skill_list` | List learned skills | <1s |
| `skill_get` | Get skill definition | <1s |
| `skill_delete` | Delete a skill | <1s |
| `health_check` | Server status and running tasks | <1s |
| `task_list` | Query task history | <1s |
| `task_get` | Get full task details | <1s |

### run_browser_agent

The main tool. Tell it what you want in plain English:

```bash
mcp-server-browser-use call run_browser_agent \
  task="Find the price of iPhone 16 Pro on Apple's website"
```

The agent launches a browser, navigates to apple.com, finds the product, and returns the price.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `task` | string | What to do (required) |
| `max_steps` | int | Override default max steps |
| `skill_name` | string | Use a learned skill |
| `skill_params` | JSON | Parameters for the skill |
| `learn` | bool | Enable learning mode |
| `save_skill_as` | string | Name for the learned skill |

### run_deep_research

Multi-step web research with automatic synthesis:

```bash
mcp-server-browser-use call run_deep_research \
  topic="Latest developments in quantum computing" \
  max_searches=5
```

The agent searches multiple sources, extracts key findings, and compiles a markdown report.

---

## Deep Research

Deep research executes a 3-phase workflow:

```
┌─────────────────────────────────────────────────────────┐
│  Phase 1: PLANNING                                       │
│  LLM generates 3-5 focused search queries from topic     │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│  Phase 2: SEARCHING                                      │
│  For each query:                                         │
│    • Browser agent executes search                       │
│    • Extracts URL + summary from results                 │
│    • Stores findings                                     │
└─────────────────────────────┬───────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────┐
│  Phase 3: SYNTHESIS                                      │
│  LLM creates markdown report:                            │
│    1. Executive Summary                                  │
│    2. Key Findings (by theme)                            │
│    3. Analysis and Insights                              │
│    4. Gaps and Limitations                               │
│    5. Conclusion with Sources                            │
└─────────────────────────────────────────────────────────┘
```

Reports can be auto-saved by configuring `research.save_directory`.

---

## Observability

All tool executions are tracked in SQLite for debugging and monitoring.

### Task Lifecycle

```
PENDING ──► RUNNING ──► COMPLETED
               │
               ├──► FAILED
               └──► CANCELLED
```

### Task Stages

During execution, tasks progress through granular stages:

```
INITIALIZING → PLANNING → NAVIGATING → EXTRACTING → SYNTHESIZING
```

### Querying Tasks

**List recent tasks:**

```bash
mcp-server-browser-use tasks
```

```
┌──────────────┬───────────────────┬───────────┬──────────┬──────────┐
│ ID           │ Tool              │ Status    │ Progress │ Duration │
├──────────────┼───────────────────┼───────────┼──────────┼──────────┤
│ a1b2c3d4     │ run_browser_agent │ completed │ 15/15    │ 45s      │
│ e5f6g7h8     │ run_deep_research │ running   │ 3/7      │ 2m 15s   │
└──────────────┴───────────────────┴───────────┴──────────┴──────────┘
```

**Get task details:**

```bash
mcp-server-browser-use task a1b2c3d4
```

**Server health:**

```bash
mcp-server-browser-use health
```

Shows uptime, memory usage, and currently running tasks.

### MCP Tools for Observability

AI clients can query task status directly:

- `health_check` - Server status + list of running tasks
- `task_list` - Recent tasks with optional status filter
- `task_get` - Full details of a specific task

### Storage

- **Database:** `~/.config/mcp-server-browser-use/tasks.db`
- **Retention:** Completed tasks auto-deleted after 7 days
- **Format:** SQLite with WAL mode for concurrency

---

## Skills System (Super Alpha)

> **Warning:** This feature is experimental and under active development. Expect rough edges.

Skills let you "teach" the agent a task once, then replay it **50x faster** by reusing discovered API endpoints instead of full browser automation.

### The Problem

Browser automation is slow (60-120 seconds per task). But most websites have APIs behind their UI. If we can discover those APIs, we can call them directly.

### The Solution

Skills capture the API calls made during a browser session and replay them directly via CDP (Chrome DevTools Protocol).

```
Without Skills:  Browser navigation → 60-120 seconds
With Skills:     Direct API call    → 1-3 seconds
```

### Learning a Skill

```bash
mcp-server-browser-use call run_browser_agent \
  task="Find React packages on npmjs.com" \
  learn=true \
  save_skill_as="npm-search"
```

What happens:

1. **Recording:** CDP captures all network traffic during execution
2. **Analysis:** LLM identifies the "money request"—the API call that returns the data
3. **Extraction:** URL patterns, headers, and response parsing rules are saved
4. **Storage:** Skill saved as YAML to `~/.config/browser-skills/npm-search.yaml`

### Using a Skill

```bash
mcp-server-browser-use call run_browser_agent \
  skill_name="npm-search" \
  skill_params='{"query": "vue"}'
```

### Two Execution Modes

Every skill supports two execution paths:

#### 1. Direct Execution (Fast Path) ~2 seconds

If the skill captured an API endpoint (`SkillRequest`):

```
Initialize CDP session
    ↓
Navigate to domain (establish cookies)
    ↓
Execute fetch() via Runtime.evaluate
    ↓
Parse response with JSONPath
    ↓
Return data
```

#### 2. Hint-Based Execution (Fallback) ~60-120 seconds

If direct execution fails or no API was found:

```
Inject navigation hints into task prompt
    ↓
Agent uses hints as guidance
    ↓
Agent discovers and calls API
    ↓
Return data
```

### Skill File Format

Skills are stored as YAML in `~/.config/browser-skills/`:

```yaml
name: npm-search
description: Search for packages on npmjs.com
version: "1.0"

# For direct execution (fast path)
request:
  url: "https://www.npmjs.com/search?q={query}"
  method: GET
  headers:
    Accept: application/json
  response_type: json
  extract_path: "objects[*].package"

# For hint-based execution (fallback)
hints:
  navigation:
    - step: "Go to npmjs.com"
      url: "https://www.npmjs.com"
  money_request:
    url_pattern: "/search"
    method: GET

# Auth recovery (if API returns 401/403)
auth_recovery:
  trigger_on_status: [401, 403]
  recovery_page: "https://www.npmjs.com/login"

# Usage stats
success_count: 12
failure_count: 1
last_used: "2024-01-15T10:30:00Z"
```

### Parameters

Skills support parameterized URLs and request bodies:

```yaml
request:
  url: "https://api.example.com/search?q={query}&limit={limit}"
  body_template: '{"filters": {"category": "{category}"}}'
```

Parameters are substituted at execution time from `skill_params`.

### Auth Recovery

If an API returns 401/403, skills can trigger auth recovery:

```yaml
auth_recovery:
  trigger_on_status: [401, 403]
  recovery_page: "https://example.com/login"
  max_retries: 2
```

The system will navigate to the recovery page (letting you log in) and retry.

### Limitations

- **API Discovery:** Only works if the site has an API. Sites that render everything server-side won't yield useful skills.
- **Auth State:** Skills rely on browser cookies. If you're logged out, they may fail.
- **API Changes:** If a site changes their API, the skill breaks. Falls back to hint-based execution.
- **Complex Flows:** Multi-step workflows (login → navigate → search) may not capture cleanly.

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MCP CLIENTS                                    │
│              (Claude Desktop, mcp-remote, CLI call)                      │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTP POST /mcp
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         FastMCP SERVER                                   │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      MCP TOOLS                                    │   │
│  │  • run_browser_agent    • skill_list/get/delete                  │   │
│  │  • run_deep_research    • health_check/task_list/task_get        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────┬──────────────┬─────────────────┬────────────────┬──────────────┘
         │              │                 │                │
         ▼              ▼                 ▼                ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐
│   CONFIG    │  │  PROVIDERS  │  │   SKILLS    │  │    OBSERVABILITY    │
│  Pydantic   │  │ 12 LLMs     │  │  Learn+Run  │  │   Task Tracking     │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘
                                         │
                                         ▼
                              ┌─────────────────────────┐
                              │      browser-use        │
                              │   (Agent + Playwright)  │
                              └─────────────────────────┘
```

### Module Structure

```
src/mcp_server_browser_use/
├── server.py            # FastMCP server + MCP tools
├── cli.py               # Typer CLI for daemon management
├── config.py            # Pydantic settings
├── providers.py         # LLM factory (12 providers)
│
├── observability/       # Task tracking
│   ├── models.py        # TaskRecord, TaskStatus, TaskStage
│   ├── store.py         # SQLite persistence
│   └── logging.py       # Structured logging
│
├── skills/              # Machine-learned browser skills
│   ├── models.py        # Skill, SkillRequest, AuthRecovery
│   ├── store.py         # YAML persistence
│   ├── recorder.py      # CDP network capture
│   ├── analyzer.py      # LLM skill extraction
│   ├── runner.py        # Direct fetch() execution
│   └── executor.py      # Hint injection
│
└── research/            # Deep research workflow
    ├── models.py        # SearchResult, ResearchSource
    └── machine.py       # Plan → Search → Synthesize
```

### File Locations

| What | Where |
|------|-------|
| Config | `~/.config/mcp-server-browser-use/config.json` |
| Tasks DB | `~/.config/mcp-server-browser-use/tasks.db` |
| Skills | `~/.config/browser-skills/*.yaml` |
| Server Log | `~/.local/state/mcp-server-browser-use/server.log` |
| Server PID | `~/.local/state/mcp-server-browser-use/server.json` |

### Supported LLM Providers

- OpenAI
- Anthropic
- Google Gemini
- Azure OpenAI
- Groq
- DeepSeek
- Cerebras
- Ollama (local)
- AWS Bedrock
- OpenRouter
- Vercel AI

---

## License

MIT
