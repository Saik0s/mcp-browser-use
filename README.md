# mcp-server-browser-use

MCP server that gives AI assistants the power to control a web browser.

[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [What is this?](#what-is-this)
- [Installation](#installation)
- [Web UI](#web-ui)
- [Web Dashboard](#web-dashboard)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [MCP Tools](#mcp-tools)
- [Deep Research](#deep-research)
- [Observability](#observability)
- [Skills System](#skills-system-super-alpha)
- [REST API Reference](#rest-api-reference)
- [Architecture](#architecture)
- [License](#license)

---

## What is this?

This wraps [browser-use](https://github.com/browser-use/browser-use) as an MCP server, letting Claude (or any MCP client) automate a real browser—navigate pages, fill forms, click buttons, extract data, and more.

### Why HTTP instead of stdio?

Browser automation tasks take 30-120+ seconds. The standard MCP stdio transport has timeout issues with long-running operations—connections drop mid-task. **HTTP transport solves this** by running as a persistent daemon that handles requests reliably regardless of duration.

---

## Installation

### Claude Code Plugin (Recommended)

Install as a Claude Code plugin for automatic setup:

```bash
# Install the plugin
/plugin install browser-use/mcp-browser-use
```

The plugin automatically:
- Installs Playwright browsers on first run
- Starts the HTTP daemon when Claude Code starts
- Registers the MCP server with Claude

**Set your API key** (the browser agent needs an LLM to decide actions):

```bash
# Set API key (environment variable - recommended)
export GEMINI_API_KEY=your-key-here

# Or use config file
mcp-server-browser-use config set -k llm.api_key -v your-key-here
```

That's it! Claude can now use browser automation tools.

### Manual Installation

For other MCP clients or standalone use:

```bash
# Clone and install
git clone https://github.com/Saik0s/mcp-browser-use.git
cd mcp-server-browser-use
uv sync

# Install browser
uv run playwright install chromium

# Start the server
uv run mcp-server-browser-use server
```

**Add to Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "browser-use": {
      "type": "streamable-http",
      "url": "http://localhost:8383/mcp"
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
      "args": ["mcp-remote", "http://localhost:8383/mcp"]
    }
  }
}
```

---

## Web UI

Access the task viewer at http://localhost:8383 when the daemon is running.

**Features:**
- Real-time task list with status and progress
- Task details with execution logs
- Server health status and uptime
- Running tasks monitoring

The web UI provides visibility into browser automation tasks without requiring CLI commands.

---

## Web Dashboard

Access the full-featured dashboard at http://localhost:8383/dashboard when the daemon is running.

**Features:**
- **Tasks Tab:** Complete task history with filtering, real-time status updates, and detailed execution logs
- **Skills Tab:** Browse, inspect, and manage learned skills with usage statistics
- **History Tab:** Historical view of all completed tasks with filtering by status and time

**Key Capabilities:**
- Run existing skills directly from the dashboard with custom parameters
- Start learning sessions to capture new skills
- Delete outdated or invalid skills
- Monitor running tasks with live progress updates
- View full task results and error details

The dashboard provides a comprehensive web interface for managing all aspects of browser automation without CLI commands.

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
# Note: Set API keys via environment variables (e.g., ANTHROPIC_API_KEY) for better security
# mcp-server-browser-use config set -k llm.api_key -v sk-...
mcp-server-browser-use config set -k browser.headless -v false
mcp-server-browser-use config set -k agent.max_steps -v 30
```

### Settings Reference

| Key | Default | Description |
|-----|---------|-------------|
| `llm.provider` | `google` | LLM provider (anthropic, openai, google, azure_openai, groq, deepseek, cerebras, ollama, bedrock, browser_use, openrouter, vercel) |
| `llm.model_name` | `gemini-3-flash-preview` | Model for the browser agent |
| `llm.api_key` | - | API key for the provider (prefer env vars: GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.) |
| `browser.headless` | `true` | Run browser without GUI |
| `browser.cdp_url` | - | Connect to existing Chrome (e.g., http://localhost:9222) |
| `browser.user_data_dir` | - | Chrome profile directory for persistent logins/cookies |
| `browser.chromium_sandbox` | `true` | Enable Chromium sandboxing for security |
| `agent.max_steps` | `20` | Max steps per browser task |
| `agent.use_vision` | `true` | Enable vision capabilities for the agent |
| `research.max_searches` | `5` | Max searches per research task |
| `research.search_timeout` | - | Timeout for individual searches |
| `server.host` | `127.0.0.1` | Server bind address |
| `server.port` | `8383` | Server port |
| `server.results_dir` | - | Directory to save results |
| `server.auth_token` | - | Auth token for non-localhost connections |
| `skills.enabled` | `false` | Enable skills system (beta - disabled by default) |
| `skills.directory` | `~/.config/browser-skills` | Skills storage location |
| `skills.validate_results` | `true` | Validate skill execution results |

### Config Priority

```
Environment Variables > Config File > Defaults
```

Environment variables use prefix `MCP_` + section + `_` + key (e.g., `MCP_LLM_PROVIDER`).

### Using Your Own Browser

**Option 1: Persistent Profile (Recommended)**

Use a dedicated Chrome profile to preserve logins and cookies:

```bash
# Set user data directory
mcp-server-browser-use config set -k browser.user_data_dir -v ~/.chrome-browser-use
```

**Option 2: Connect to Existing Chrome**

Connect to an existing Chrome instance (useful for advanced debugging):

```bash
# Launch Chrome with debugging enabled
google-chrome --remote-debugging-port=9222

# Configure CDP connection (localhost only for security)
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
mcp-server-browser-use task cancel <id> # Cancel a running task
mcp-server-browser-use health          # Server health + stats
```

### Skills Management

```bash
mcp-server-browser-use call skill_list
mcp-server-browser-use call skill_get name="my-skill"
mcp-server-browser-use call skill_delete name="my-skill"
```

**Tip:** Skills can also be managed through the web dashboard at http://localhost:8383/dashboard for a visual interface with one-click execution and learning sessions.

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

**Skills are disabled by default.** Enable them first:

```bash
mcp-server-browser-use config set -k skills.enabled -v true
```

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

## REST API Reference

The server exposes REST endpoints for direct HTTP access. All endpoints return JSON unless otherwise specified.

### Base URL

```
http://localhost:8383
```

### Health & Status

**GET /api/health**

Server health check with running task information.

```bash
curl http://localhost:8383/api/health
```

Response:
```json
{
  "status": "healthy",
  "uptime_seconds": 1234.5,
  "memory_mb": 256.7,
  "running_tasks": 2,
  "tasks": [...],
  "stats": {...}
}
```

### Tasks

**GET /api/tasks**

List recent tasks with optional filtering.

```bash
# List all tasks
curl http://localhost:8383/api/tasks

# Filter by status
curl http://localhost:8383/api/tasks?status=running

# Limit results
curl http://localhost:8383/api/tasks?limit=50
```

**GET /api/tasks/{task_id}**

Get full details of a specific task.

```bash
curl http://localhost:8383/api/tasks/abc123
```

**GET /api/tasks/{task_id}/logs** (SSE)

Real-time task progress stream via Server-Sent Events.

```javascript
const events = new EventSource('/api/tasks/abc123/logs');
events.onmessage = (e) => console.log(JSON.parse(e.data));
```

### Skills

**GET /api/skills**

List all available skills.

```bash
curl http://localhost:8383/api/skills
```

Response:
```json
{
  "skills": [
    {
      "name": "npm-search",
      "description": "Search for packages on npmjs.com",
      "success_rate": 92.5,
      "usage_count": 15,
      "last_used": "2024-01-15T10:30:00Z"
    }
  ],
  "count": 1,
  "skills_directory": "/Users/you/.config/browser-skills"
}
```

**GET /api/skills/{name}**

Get full skill definition as JSON.

```bash
curl http://localhost:8383/api/skills/npm-search
```

**DELETE /api/skills/{name}**

Delete a skill.

```bash
curl -X DELETE http://localhost:8383/api/skills/npm-search
```

**POST /api/skills/{name}/run**

Execute a skill with parameters (starts background task).

```bash
curl -X POST http://localhost:8383/api/skills/npm-search/run \
  -H "Content-Type: application/json" \
  -d '{"params": {"query": "react"}}'
```

Response:
```json
{
  "task_id": "abc123...",
  "skill_name": "npm-search",
  "message": "Skill execution started",
  "status_url": "/api/tasks/abc123..."
}
```

**POST /api/learn**

Start a learning session to capture a new skill (starts background task).

```bash
curl -X POST http://localhost:8383/api/learn \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Search for TypeScript packages on npmjs.com",
    "skill_name": "npm-search"
  }'
```

Response:
```json
{
  "task_id": "def456...",
  "learning_task": "Search for TypeScript packages on npmjs.com",
  "skill_name": "npm-search",
  "message": "Learning session started",
  "status_url": "/api/tasks/def456..."
}
```

### Real-Time Updates

**GET /api/events** (SSE)

Server-Sent Events stream for all task updates.

```javascript
const events = new EventSource('/api/events');
events.onmessage = (e) => {
  const data = JSON.parse(e.data);
  console.log(`Task ${data.task_id}: ${data.status}`);
};
```

Event format:
```json
{
  "task_id": "abc123",
  "full_task_id": "abc123-full-uuid...",
  "tool": "run_browser_agent",
  "status": "running",
  "stage": "navigating",
  "progress": {
    "current": 5,
    "total": 15,
    "percent": 33.3,
    "message": "Loading page..."
  }
}
```

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

---

# Project Specification

> The following sections document the full project specification including architecture decisions, roadmap, user stories, and known issues.

---

## Vision & Goals

### Project Vision

Make browser automation accessible to AI agents through a simple, reliable MCP interface. Enable Claude (and any MCP client) to control real browsers for tasks that require web interaction—without requiring users to understand browser automation internals.

### Core Principles

1. **Reliability over Speed** - HTTP transport for long-running tasks; never drop connections mid-automation
2. **Simplicity over Features** - Minimal configuration; sensible defaults; progressive disclosure of complexity
3. **Safety First** - Skills disabled by default; SSRF protection; auth header redaction; localhost-only CDP
4. **Observable by Default** - All tasks tracked in SQLite; real-time progress via SSE; CLI visibility

### Non-Goals

- Not a general browser testing framework (use Playwright directly)
- Not a web scraping library (use dedicated scrapers)
- Not a replacement for browser-use library (we wrap it)

---

## User Stories

### Primary User Stories

| ID | As a... | I want to... | So that... | Status |
|----|---------|--------------|------------|--------|
| US-1 | Claude user | Ask Claude to browse the web for me | I can get information from sites without leaving the conversation | ✅ Done |
| US-2 | Developer | Install the MCP server with one command | I can start using browser automation quickly | ✅ Done |
| US-3 | Power user | Connect to my existing Chrome profile | The agent can access my logged-in sessions | ✅ Done |
| US-4 | Researcher | Run deep multi-source research | I get synthesized reports from multiple web searches | ✅ Done |
| US-5 | Automation user | Teach the agent a task once | It can replay that task 50x faster using discovered APIs | 🔬 Alpha |

### Planned User Stories

| ID | As a... | I want to... | So that... | Priority |
|----|---------|--------------|------------|----------|
| US-6 | Ops engineer | Install as a system service | The server auto-starts on boot and restarts on crash | P1 |
| US-7 | Claude user | See real-time progress | I know what the agent is doing during long tasks | P1 |
| US-8 | Skill user | Validate skills before using | I know they'll work before relying on them | P2 |
| US-9 | Team lead | Share skills across team | We don't re-learn the same tasks | P3 |

---

## Acceptance Criteria

### Core Functionality

- [x] `run_browser_agent` executes arbitrary browser tasks via natural language
- [x] `run_deep_research` executes multi-search research with markdown synthesis
- [x] HTTP transport handles 2+ minute tasks without timeout
- [x] Task history persisted to SQLite with 7-day retention
- [x] 12 LLM providers supported (OpenAI, Anthropic, Google, etc.)
- [x] Web UI shows real-time task list and details
- [x] CLI provides full server management (start/stop/logs/status)

### Skills System (Alpha)

- [x] Learning mode captures network traffic via CDP
- [x] LLM analyzer identifies "money request" API endpoints
- [x] Skills saved as YAML with parameterized URLs
- [x] Direct execution via CDP fetch() (~2s vs ~60s)
- [x] Hint-based fallback when direct execution fails
- [ ] Skill validation before first use
- [ ] Skill versioning and migration
- [ ] Auth recovery when sessions expire

### Security

- [x] SSRF protection blocks private IPs, localhost, IPv6 link-local
- [x] Sensitive headers (Authorization, Cookie) redacted before skill storage
- [x] CDP URL restricted to localhost only
- [x] SQL injection prevented via parameterized queries + column whitelist
- [x] DNS rebinding protected via re-validation before fetch

### Observability

- [x] All tool executions tracked with task ID
- [x] Task stages: INITIALIZING → PLANNING → NAVIGATING → EXTRACTING → SYNTHESIZING
- [x] Progress updates via SSE stream
- [x] Health endpoint with uptime, memory, running tasks
- [ ] Metrics export (Prometheus format)

---

## Architecture Decisions

### ADR-001: HTTP Transport over stdio

**Context:** Browser automation tasks take 30-120+ seconds. MCP stdio transport has timeout issues with long-running operations.

**Decision:** Use HTTP (streamable-http) as the primary transport. Run as a persistent daemon.

**Consequences:**
- ✅ Reliable for long-running tasks
- ✅ Supports SSE for real-time progress
- ✅ Can serve web dashboard
- ⚠️ Requires daemon management
- ⚠️ Port conflicts possible

### ADR-002: FastMCP over MCP SDK

**Context:** Need native background task support with progress reporting. jlowin's FastMCP provides this via MCP task protocol (SEP-1686).

**Decision:** Migrate from `mcp` SDK to `fastmcp>=2.14.0`.

**Consequences:**
- ✅ Native progress reporting via `Progress` dependency
- ✅ Background task mode via `TaskConfig`
- ✅ Simpler testing with in-memory `Client`
- ⚠️ Different dependency injection patterns (CurrentContext vs Context)
- ⚠️ Breaking API for old clients

### ADR-003: Skills as API Discovery (not DOM Scraping)

**Context:** Browser automation is slow (~60s). Most sites have APIs behind their UI.

**Decision:** Skills capture discovered API endpoints, not DOM selectors. Execute via direct fetch() calls.

**Consequences:**
- ✅ 50x faster execution (2s vs 60s)
- ✅ More reliable (APIs change less than UI)
- ✅ Structured JSON responses
- ⚠️ Only works for sites with APIs
- ⚠️ Auth state required (browser cookies)
- ⚠️ API changes break skills (fallback to hints)

### ADR-004: Disabled by Default for Alpha Features

**Context:** Skills system is experimental. Security and correctness issues exist.

**Decision:** Skills disabled by default. Enable via `skills.enabled=true` in config.

**Consequences:**
- ✅ Safe default for new users
- ✅ Explicit opt-in for alpha features
- ⚠️ Extra configuration step for power users

### ADR-005: SQLite for Task Persistence

**Context:** Need to track task history for debugging and observability.

**Decision:** Use SQLite with WAL mode. Auto-delete after 7 days.

**Consequences:**
- ✅ Zero configuration (file-based)
- ✅ Concurrent reads with WAL
- ✅ Portable (single file backup)
- ⚠️ Not suitable for distributed deployments

---

## Known Issues & Limitations

### Current Limitations

| Issue | Impact | Workaround |
|-------|--------|------------|
| Skills only work with API-backed sites | Can't skill server-rendered pages | Use regular browser automation |
| Auth sessions expire | Skills fail after logout | Re-authenticate in browser |
| API changes break skills | Direct execution fails | Fallback to hint-based execution |
| Single browser instance | Can't parallelize tasks | Run multiple server instances |
| No Windows native support | Service install fails | Use WSL |

### Known Bugs

| ID | Description | Severity | Status |
|----|-------------|----------|--------|
| BUG-1 | CDP listeners not cleaned up on exception | High | Fixed (e6cc929) |
| BUG-2 | DNS rebinding TOCTOU window | Critical | Fixed (f3eeb19) |
| BUG-3 | SQL injection via f-string in store.py | High | Fixed (faa3f10) |

### Security Considerations

1. **CDP URLs** - Only localhost allowed. Never expose CDP port to network.
2. **Skills Storage** - Sensitive headers redacted. Files stored in `~/.config/browser-skills/`.
3. **Private IPs** - SSRF protection blocks 127.0.0.1, 192.168.x.x, 10.x.x.x, fc00::/7, fe80::/10.
4. **API Keys** - Prefer environment variables over config file.

---

## Roadmap

### Phase 1: Foundation ✅ Complete

- [x] FastMCP server with HTTP transport
- [x] `run_browser_agent` tool
- [x] `run_deep_research` tool
- [x] Task observability (SQLite + SSE)
- [x] Web dashboard
- [x] CLI management

### Phase 2: Skills System 🔬 Alpha

- [x] CDP network capture via SkillRecorder
- [x] LLM skill extraction via SkillAnalyzer
- [x] YAML persistence via SkillStore
- [x] Direct execution via SkillRunner
- [x] Hint-based fallback via SkillExecutor
- [ ] Security hardening (SSRF, header redaction) - partial
- [ ] Skill validation and status tracking
- [ ] JMESPath for response extraction

### Phase 3: Production Readiness (Planned)

- [ ] Background service installation (systemd/launchd)
- [ ] Client-visible status updates via Context
- [ ] Skill versioning and migration
- [ ] Auth recovery workflow
- [ ] Skill sharing/marketplace

### Phase 4: Scale (Future)

- [ ] Multi-browser instance support
- [ ] Distributed task queue
- [ ] Metrics export (Prometheus)
- [ ] Skill confidence scoring
- [ ] Multi-step skill chains

---

## Development Guidelines

### Code Standards

- Python 3.11+ with full type annotations
- Line length: 150 characters
- Async/await for all I/O operations
- Pydantic models for all config and data structures
- No `any` types or type suppressions

### Required Workflow

```bash
uv sync                    # Install dependencies
uv run ruff format .       # Format code
uv run ruff check .        # Lint check
uv run pyright             # Type checking
uv run pytest              # Run tests
```

All checks must pass before commit (enforced by pre-commit hooks).

### Test Markers

- `e2e` - End-to-end tests requiring real API keys
- `integration` - Integration tests with real browser
- `slow` - Tests that take longer to run

### FastMCP Patterns (Critical)

```python
# ✅ CORRECT - Use CurrentContext() as default
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context

@server.tool(task=TaskConfig(mode="optional"))
async def my_tool(
    task: str,
    ctx: Context = CurrentContext(),  # NOT Context()
    progress: Progress = Progress(),   # NOT None
) -> str:
    if progress:  # Always check before using
        await progress.set_total(10)
    ...
```

---

## Glossary

| Term | Definition |
|------|------------|
| **MCP** | Model Context Protocol - standard for AI tool integration |
| **FastMCP** | jlowin's Python MCP framework with native background tasks |
| **CDP** | Chrome DevTools Protocol - low-level browser control |
| **Money Request** | The API call that returns the data the user asked for |
| **Skill** | Machine-generated recipe for replaying a browser task via API |
| **Hint-based Execution** | Fallback mode using navigation hints instead of direct API |
| **SSRF** | Server-Side Request Forgery - security vulnerability |
| **TOCTOU** | Time-of-Check to Time-of-Use - race condition vulnerability |

---

## References

- [browser-use Documentation](https://github.com/browser-use/browser-use)
- [FastMCP Documentation](https://gofastmcp.com)
- [MCP Specification](https://modelcontextprotocol.io)
- [MCP Task Protocol SEP-1686](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
