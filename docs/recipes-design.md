# Recipes Feature Design

## Overview

The Recipes feature enables mcp-browser-use to **learn browser tasks once and replay them efficiently with hints**. Recipes are **machine-generated** from successful learning sessions - NOT manually authored.

**Core Principle:** Recipes are API extraction templates, not DOM scrapers. The agent discovers API endpoints during learning mode.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Browser Recipes Engine                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LEARNING MODE (learn=True):                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Agent +    │───▶│   Analyzer   │───▶│    Store     │   │
│  │  API Focus   │    │  (LLM finds  │    │ (YAML recipe │   │
│  │  Instructions│    │  money req)  │    │   files)     │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                              │
│  EXECUTION MODE (recipe_name provided):                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │    Store     │───▶│   Executor   │───▶│    Agent +   │   │
│  │ (load recipe)│    │ (inject hints)│   │   Hints      │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## File Structure

```
src/mcp_server_browser_use/recipes/
├── __init__.py          # Public API exports
├── models.py            # Recipe, MoneyRequest, SessionRecording dataclasses
├── store.py             # RecipeStore - YAML persistence
├── executor.py          # RecipeExecutor - hint injection + learning mode
├── analyzer.py          # RecipeAnalyzer - LLM extraction of money request
├── recorder.py          # RecipeRecorder - CDP network event capture
└── prompts.py           # API discovery and analysis prompts
```

## Usage

### Learning Mode

```python
# Learn a new recipe
result = await run_browser_agent(
    task="Find new iOS developer jobs on Upwork",
    learn=True,                      # Enable API discovery mode
    save_recipe_as="upwork-ios-jobs" # Save extracted recipe
)
```

The agent executes with modified instructions:
1. Navigate to relevant pages
2. **Discover the API endpoint** that returns the data
3. Report the endpoint, parameters, and response structure

If successful, the analyzer:
1. Identifies the "money request" (API call that returned the data)
2. Extracts parameters that can be templated
3. Saves as a machine-generated recipe file

### Execution Mode

```python
# Use learned recipe
result = await run_browser_agent(
    task="Find new Python developer jobs",
    recipe_name="upwork-ios-jobs",
    recipe_params='{"keywords": "Python"}'
)
```

The agent receives hints:
- Navigation steps to reach the right state
- Target API endpoint to call
- Expected data location in response

## Key Concepts

### Money Request

The **money request** is THE API call that returns the data the user asked for:

```yaml
money_request:
  endpoint: "/api/graphql/v1"
  method: POST
  identifies_by: "operationName: searchJobs"
  response_path: "data.searchJobs.edges"
```

### Learning Mode Instructions

When `learn=True`, the agent receives API discovery instructions:

```
Your goal is to complete this task BY DISCOVERING AND USING THE UNDERLYING API.

Instructions:
1. Navigate to the relevant page(s)
2. OBSERVE the network requests being made (XHR/Fetch calls)
3. IDENTIFY the API endpoint that returns the data you need
4. The data comes from an API response, NOT from DOM scraping

What NOT to do:
- Do NOT extract data by reading DOM elements
- The page DOM is just for navigation, not data extraction
```

### Recipe File Structure (Machine-Generated)

```yaml
name: upwork-job-search
description: Search for jobs on Upwork
original_task: "Find new iOS developer jobs on Upwork"
version: 1
created: 2025-12-16T10:30:00

hints:
  navigation:
    - url_pattern: "upwork.com/nx/search/jobs"
      description: Job search results page

  money_request:
    endpoint: "/api/graphql/v1"
    method: POST
    content_type: "application/json"
    identifies_by: "operationName: searchJobs"
    response_path: "data.searchJobs.edges"

parameters:
  - name: keywords
    type: string
    source: body

fallback:
  strategy: explore_full
  max_retries: 2
```

## MCP Tools

### run_browser_agent (Modified)

New parameters:
- `learn: bool = False` - Enable learning mode
- `save_recipe_as: Optional[str]` - Name to save learned recipe

### recipe_list

List all available recipes (machine-generated).

### recipe_get

Get full details of a specific recipe.

### recipe_delete

Delete a recipe by name.

## Why This Design?

### Why Browser + Hints (not Pure API)?

1. **Avoids detection** - Still looks like normal browsing
2. **Handles auth** - Uses browser's existing session/cookies
3. **Adapts to changes** - Falls back to exploration if API changes
4. **Respects ToS** - Not reverse-engineering private APIs

### Why Machine-Generated Recipes?

1. **No human expertise needed** - Agent discovers the API
2. **Accurate extraction** - LLM identifies relevant parameters
3. **Complex structure** - Recipes capture API details humans wouldn't write
4. **Self-correcting** - Re-learn if API changes

### Why API Focus (not DOM)?

1. **Faster execution** - API call vs. DOM navigation
2. **Structured data** - JSON response vs. parsing HTML
3. **More reliable** - APIs change less than UI
4. **Cleaner results** - Direct data access

## Limitations

### Learning Fails If:

- Task is too vague ("extract all data from website")
- No API exists (server-side rendering only)
- Task requires multiple unrelated API calls
- Authentication prevents API access

### Learning Succeeds If:

- Agent finds a single API endpoint returning the data
- Parameters can be extracted from URL/body
- Response contains structured JSON data

## Implementation Status

### Phase 1: MVP ✅
- Learning mode with API discovery instructions
- Recipe extraction via LLM analysis
- YAML persistence and hint injection
- Basic fallback handling

### Phase 2: Full CDP Recording ✅ (Completed 2025-12-16)
- CDP network event capture via browser-use's `cdp_client`
- Handlers for `Network.requestWillBeSent`, `Network.responseReceived`, `Network.loadingFailed`
- Response body capture via `Network.getResponseBody` for JSON APIs
- Async task tracking with concurrency limits
- Header redaction for security (cookies, auth tokens)

### Phase 3: Advanced Features (Future)
- Recipe validation against expected response schema
- Recipe versioning and migration
- Recipe sharing/marketplace
- Confidence scoring
- Multi-step recipe chains
