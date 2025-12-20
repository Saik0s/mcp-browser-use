---
name: browser-use
description: AI-driven browser automation via Model Context Protocol
---

# Browser Use

AI-powered browser automation for web interactions, research, and data extraction powered by the browser-use library.

## When to Use

- Automate web interactions (fill forms, click buttons, navigate pages)
- Perform deep research across multiple web sources
- Extract structured data from web pages
- Learn and replay browser workflows as reusable skills
- Monitor and manage long-running browser automation tasks

## Core Tools

### run_browser_agent

Execute a browser automation task using AI. Supports skill-based execution, learning mode, and background task execution.

**Parameters:**
- `task` (string, required) - Natural language description of what to do in the browser
- `max_steps` (integer, optional) - Maximum number of agent steps (default: from settings)
- `skill_name` (string, optional) - Name of a learned skill to use for hints
- `skill_params` (string or dict, optional) - Parameters for the skill (JSON string or dict)
- `learn` (boolean, optional) - Enable learning mode to discover and extract APIs
- `save_skill_as` (string, optional) - Name to save learned skill (requires learn=True)

**Returns:** Result of the browser automation task. In learning mode, includes skill extraction status.

**Examples:**

```
# Basic usage
Search for "Claude Code plugins" on Google and summarize the top 3 results

# With max steps
Fill out the contact form at https://example.com/contact with my information
max_steps: 20

# Learning mode - discover and save a skill
Go to GitHub trending page and extract the top 5 repositories
learn: true
save_skill_as: github_trending

# Using a learned skill
task: Get trending Python repositories
skill_name: github_trending
skill_params: {"language": "python", "limit": 10}
```

### run_deep_research

Perform multi-source research on a topic with AI-guided search and synthesis.

**Parameters:**
- `topic` (string, required) - The research topic or question to investigate
- `max_searches` (integer, optional) - Maximum number of web searches (default: from settings)
- `save_to_file` (string, optional) - Optional file path to save the research report

**Returns:** A comprehensive research report in markdown format

**Examples:**

```
# Basic research
What are the latest developments in AI-powered browser automation?

# With search limit
Research the security implications of CDP-based browser automation
max_searches: 10

# Save to file
Compare Playwright, Puppeteer, and Selenium for 2025
save_to_file: /path/to/research/browser-automation-comparison.md
```

## Skill Management Tools

### skill_list

List all available learned browser skills with usage statistics.

**Parameters:** None

**Returns:** JSON list of skill summaries with name, description, success rate, usage count, and last used timestamp

**Example:**

```json
{
  "skills": [
    {
      "name": "github_trending",
      "description": "Extract trending repositories from GitHub",
      "success_rate": 95.0,
      "usage_count": 20,
      "last_used": "2025-12-20T18:00:00"
    }
  ],
  "skills_directory": "/Users/user/.config/browser-skills"
}
```

### skill_get

Get full details of a specific skill including API endpoints, parameters, and execution hints.

**Parameters:**
- `skill_name` (string, required) - Name of the skill to retrieve

**Returns:** Full skill definition in YAML format

**Example:**

```
skill_name: github_trending
```

### skill_delete

Delete a learned skill by name.

**Parameters:**
- `skill_name` (string, required) - Name of the skill to delete

**Returns:** Success or error message

**Example:**

```
skill_name: outdated_skill
```

## Task Management Tools

### health_check

Check if the browser automation server is running and get system statistics.

**Parameters:** None

**Returns:** JSON with server health status, uptime, memory usage, and running tasks

**Example Response:**

```json
{
  "status": "healthy",
  "uptime_seconds": 3600.5,
  "memory_mb": 256.3,
  "running_tasks": 2,
  "tasks": [
    {
      "task_id": "a1b2c3d4",
      "tool": "run_browser_agent",
      "stage": "navigating",
      "progress": "5/100",
      "message": "Searching Google..."
    }
  ],
  "stats": {
    "total_completed": 45,
    "total_failed": 2,
    "avg_duration_sec": 32.1
  }
}
```

### task_list

List recent browser automation and research tasks with filtering.

**Parameters:**
- `limit` (integer, optional) - Maximum number of tasks to return (default: 20)
- `status_filter` (string, optional) - Filter by status: "running", "completed", "failed", "pending"

**Returns:** JSON list of recent tasks

**Example:**

```
# List recent tasks
limit: 10

# List only running tasks
status_filter: running
limit: 5

# List failed tasks
status_filter: failed
```

### task_get

Get detailed information about a specific task including input, output, and progress.

**Parameters:**
- `task_id` (string, required) - Task ID (full UUID or prefix match)

**Returns:** JSON with complete task details, timestamps, and result/error

**Example:**

```
task_id: a1b2c3d4
```

### task_cancel

Cancel a running browser agent or research task.

**Parameters:**
- `task_id` (string, required) - Task ID (full UUID or prefix match)

**Returns:** JSON with success status and message

**Example:**

```
task_id: a1b2c3d4
```

## Common Workflows

### Web Research Workflow

1. Use `run_deep_research` with your research question
2. Review the synthesized markdown report
3. Use `run_browser_agent` for follow-up exploration of specific sources
4. Check `task_list` to monitor progress

```
# Step 1: Deep research
run_deep_research
topic: What are the best practices for MCP server development in 2025?
max_searches: 8

# Step 2: Follow-up investigation
run_browser_agent
task: Go to the top-ranked article and extract code examples
```

### Form Automation Workflow

1. Use `run_browser_agent` with task describing the form
2. Include URL if known, or let agent search for it
3. Agent navigates, fills fields, and submits
4. Use `task_get` to verify completion

```
run_browser_agent
task: Fill out the contact form at https://example.com/contact with name "John Doe", email "john@example.com", and message "Request for demo"
max_steps: 30
```

### Learning and Reusing Skills

1. Run `run_browser_agent` with `learn: true` to discover APIs
2. Agent records network calls and extracts patterns
3. Save skill with `save_skill_as`
4. Use `skill_list` to see learned skills
5. Reuse with `skill_name` parameter for faster execution

```
# Step 1: Learn a skill
run_browser_agent
task: Go to Hacker News and extract the top 10 stories with titles, URLs, and scores
learn: true
save_skill_as: hackernews_top_stories

# Step 2: List learned skills
skill_list

# Step 3: Reuse the skill (faster direct execution)
run_browser_agent
task: Get current top stories from Hacker News
skill_name: hackernews_top_stories
skill_params: {"limit": 5}
```

### Long-Running Task Management

1. Start a browser automation task (runs in background)
2. Use `task_list` to check status
3. Use `task_get` for detailed progress
4. Use `task_cancel` if needed

```
# Step 1: Start task
run_browser_agent
task: Research all articles on example.com blog and create a summary
max_steps: 200

# Step 2: Check progress
task_list
status_filter: running

# Step 3: Get details
task_get
task_id: a1b2c3d4

# Step 4: Cancel if needed
task_cancel
task_id: a1b2c3d4
```

## Advanced Features

### Skill-Based Execution

When a skill is learned with API endpoints, it supports **direct execution** which bypasses the AI agent for much faster performance:

- First run: Agent explores the website (60-120 seconds)
- Skill learned: API patterns extracted and saved
- Subsequent runs: Direct API calls (2-5 seconds)

**Fallback behavior:** If direct execution fails (auth required, API changed), automatically falls back to agent-based execution.

### Progress Tracking

Both `run_browser_agent` and `run_deep_research` support real-time progress tracking:

- Step-by-step navigation updates
- Progress percentage (current step / total steps)
- Current stage (initializing, navigating, extracting, analyzing)
- Task message (current action description)

### Background Task Support

Long-running tasks automatically run in background when requested by the MCP client:

- Tasks tracked in SQLite database
- Persistent across server restarts
- Query status anytime with `task_list` and `task_get`
- Cancel with `task_cancel`

## Configuration

The browser-use MCP server can be configured via `~/.config/mcp-server-browser-use/config.json` or environment variables. Key settings:

- `browser.headless` - Run browser in headless mode (default: true)
- `browser.cdp_url` - Connect to external Chrome via CDP (optional)
- `agent.max_steps` - Default maximum steps (default: 100)
- `research.max_searches` - Default research searches (default: 5)
- `skills.enabled` - Enable skill learning and execution (default: true)
- `skills.directory` - Where to store learned skills (default: ~/.config/browser-skills/)

## Troubleshooting

### Server Not Responding

```
# Check server health
health_check

# Check if server is running
# In terminal: mcp-server-browser-use status
```

### Task Stuck or Failing

```
# List running tasks
task_list
status_filter: running

# Get task details
task_get
task_id: <task_id>

# Cancel if stuck
task_cancel
task_id: <task_id>
```

### Skill Execution Fails

```
# Get skill details to verify parameters
skill_get
skill_name: my_skill

# Try without skill to re-learn
run_browser_agent
task: <original task>
learn: true
save_skill_as: my_skill_v2
```

## Best Practices

1. **Start with health_check** - Verify server is ready before running tasks
2. **Use descriptive task names** - Help the AI understand your intent clearly
3. **Set reasonable max_steps** - 30-50 for simple tasks, 100-200 for complex research
4. **Learn frequently-used workflows** - Save time with skill-based execution
5. **Monitor long tasks** - Use task_list and task_get to track progress
6. **Clean up failed tasks** - Use task_cancel to free resources
7. **Save research to files** - Use save_to_file to preserve research reports

## Limitations

- Browser automation requires the MCP server to be running as a daemon
- CDP-based browsers must be on localhost (security restriction)
- Some websites may block automation (respect robots.txt and rate limits)
- Skill learning requires successful task completion and API discovery
- Task cancellation may take a few seconds to complete gracefully
