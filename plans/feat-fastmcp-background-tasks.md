# feat: Migrate to FastMCP with Background Tasks Support

## Overview

Migrate from `mcp` SDK's FastMCP to `fastmcp` (jlowin's package) to get native MCP background task support with progress reporting for long-running operations like deep research.

## Problem Statement

Current implementation uses custom async task management in `research/` module. The `fastmcp` package provides native MCP protocol background tasks (SEP-1686) with:
- `task=True` decorator for background execution
- Built-in progress reporting via `Progress` dependency
- Distributed task scheduling via Docket
- Protocol-native status polling

## Proposed Solution

1. Replace `mcp>=1.10.1` with `fastmcp>=2.14.0`
2. Update server.py to use fastmcp's FastMCP
3. Add `task=True` to `start_deep_research` tool
4. Replace custom progress tracking with `ctx.report_progress()`
5. Remove custom `research/store.py` task management

## Technical Approach

### Package Migration

**pyproject.toml changes:**
```toml
dependencies = [
  "browser-use>=0.10.1",
  "fastmcp>=2.14.0",       # Changed from mcp>=1.10.1
  "pydantic-settings>=2.0.0",
  "typer>=0.12.0",
  "uvicorn>=0.30.0",
  "starlette>=0.38.0",
]
```

### Server Migration

**Before (mcp SDK):**
```python
from mcp.server.fastmcp import Context, FastMCP
```

**After (fastmcp):**
```python
from fastmcp import FastMCP, Context
from fastmcp.dependencies import Progress
```

### Deep Research with Native Background Tasks

**Updated server.py:**
```python
from fastmcp import FastMCP, Context, TaskConfig
from fastmcp.dependencies import Progress

mcp = FastMCP(
    "mcp_server_browser_use",
    host=settings.server.host,
    port=settings.server.port,
    tasks=True,  # Enable background task support
)

@mcp.tool(task=TaskConfig(mode="optional"))
async def run_deep_research(
    topic: str,
    max_searches: int = 5,
    ctx: Context = Context(),
    progress: Progress = Progress(),
) -> str:
    """
    Deep research on a topic with progress tracking.

    Runs as background task if client requests it, otherwise synchronous.
    """
    await progress.set_total(max_searches + 2)  # searches + plan + synthesis

    # Phase 1: Planning
    await progress.set_message("Planning research approach...")
    plan = await _generate_research_plan(topic, ctx)
    await progress.increment()

    # Phase 2: Execute searches
    findings = []
    for i in range(max_searches):
        await progress.set_message(f"Searching ({i+1}/{max_searches}): {plan.queries[i]}")
        result = await _execute_search(plan.queries[i], ctx)
        findings.append(result)
        await progress.increment()

    # Phase 3: Synthesis
    await progress.set_message("Synthesizing findings into report...")
    report = await _synthesize_report(topic, findings, ctx)
    await progress.increment()

    return report
```

### Remove Custom Task Management

**Delete these files:**
- `src/mcp_server_browser_use/research/store.py` - No longer needed
- `src/mcp_server_browser_use/research/models.py` - Simplify (remove ResearchTask state machine)

**Keep:**
- `research/machine.py` - Research execution logic
- `research/prompts.py` - Prompt templates

### Simplified Research Module

**research/__init__.py:**
```python
# Just export the core functions, no task store
from .machine import execute_research
from .prompts import RESEARCH_PROMPTS
```

### Tool Consolidation

Replace the 4 separate tools with 1 or 2:

**Before:**
- `start_deep_research` → returns task_id
- `get_research_status` → poll status
- `get_research_result` → get result
- `cancel_deep_research` → cancel

**After:**
- `run_deep_research(task=True)` → MCP handles all of this natively

### Environment Configuration

**Add to .env.example:**
```bash
# FastMCP Background Tasks
FASTMCP_ENABLE_TASKS=true
FASTMCP_DOCKET_URL=memory://  # or redis://localhost:6379 for production
```

## API Changes (Breaking)

| Old API | New API |
|---------|---------|
| `start_deep_research(topic)` → `{task_id}` | `run_deep_research(topic)` with `task=True` |
| `get_research_status(task_id)` | Handled by MCP protocol |
| `get_research_result(task_id)` | Handled by MCP protocol |
| `cancel_deep_research(task_id)` | Handled by MCP protocol |

## Implementation Tasks

- [ ] Update pyproject.toml: replace `mcp` with `fastmcp>=2.14.0`
- [ ] Update server.py imports from fastmcp
- [ ] Add `tasks=True` to FastMCP constructor
- [ ] Convert `start_deep_research` to `run_deep_research` with `task=True`
- [ ] Add `Progress` dependency injection for progress reporting
- [ ] Remove `get_research_status`, `get_research_result`, `cancel_deep_research` tools
- [ ] Delete `research/store.py`
- [ ] Simplify `research/models.py`
- [ ] Update `research/machine.py` to accept Progress parameter
- [ ] Update .env.example with FASTMCP_* vars
- [ ] Update README.md documentation
- [ ] Update tests

## Acceptance Criteria

- [ ] `run_deep_research` executes as background task when client requests
- [ ] Progress updates appear in MCP clients that support task protocol
- [ ] Graceful degradation: works synchronously if client doesn't support tasks
- [ ] No custom task storage needed (Docket handles it)
- [ ] HTTP transport continues to work

## Testing

```python
import pytest
from fastmcp import FastMCP
from fastmcp.testing import MCPClient

@pytest.fixture
def client():
    from mcp_server_browser_use.server import mcp
    return MCPClient(mcp)

async def test_research_as_background_task(client):
    # Start as background task
    response = await client.call_tool(
        "run_deep_research",
        {"topic": "test topic"},
        task=True,  # Request background execution
    )

    assert response.task_id is not None

    # Poll for completion
    status = await client.get_task_status(response.task_id)
    assert status.state in ["running", "completed"]
```

## Files to Modify

| File | Action |
|------|--------|
| `pyproject.toml` | Replace mcp with fastmcp |
| `src/mcp_server_browser_use/server.py` | Rewrite with fastmcp imports |
| `src/mcp_server_browser_use/research/store.py` | Delete |
| `src/mcp_server_browser_use/research/models.py` | Simplify |
| `src/mcp_server_browser_use/research/machine.py` | Add Progress param |
| `.env.example` | Add FASTMCP_* vars |
| `README.md` | Update tool documentation |
| `CLAUDE.md` | Update architecture docs |
| `tests/test_mcp_tools.py` | Update for fastmcp |

## Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking API change | High | Document migration, bump version |
| fastmcp compatibility | Medium | Test thoroughly, pin version |
| Docket memory backend persistence | Low | Document in-memory limitations |

## References

- [FastMCP Background Tasks](https://gofastmcp.com/execution/tasks)
- [FastMCP Progress Reporting](https://gofastmcp.com/execution/progress)
- [MCP Task Protocol SEP-1686](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [Docket Documentation](https://chrisguidry.github.io/docket/)
