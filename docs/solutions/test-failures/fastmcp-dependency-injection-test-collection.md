---
title: FastMCP Dependency Injection Causing Test Collection Failures
slug: fastmcp-dependency-injection-test-collection
category: test-failures
tags:
  - fastmcp
  - mcp-protocol
  - dependency-injection
  - pytest
  - testing
  - pydantic
  - migration
component:
  - server.py
  - tests/test_mcp_tools.py
severity: high
symptoms:
  - "PydanticSchemaGenerationError: Unable to generate pydantic-core schema for Progress"
  - "TypeError: Context.__init__() missing 1 required positional argument: 'fastmcp'"
  - "AttributeError: 'FastMCP' object has no attribute 'create_initialization_options'"
  - Tests fail during collection, not execution
  - All test files fail to load
root_cause: |
  FastMCP uses a different dependency injection pattern than MCP SDK. Context and Progress
  are special dependency markers that FastMCP injects at runtime, not regular defaults.
  Using Context() or Progress=None causes Pydantic schema generation failures during
  test collection. Additionally, MCP SDK's testing utilities are incompatible with FastMCP.
related_files:
  - plans/feat-fastmcp-background-tasks.md
  - CLAUDE.md
  - README.md
---

# FastMCP Dependency Injection Causing Test Collection Failures

## Problem Summary

After migrating from MCP SDK's FastMCP to jlowin's `fastmcp` package, tests fail during pytest collection with Pydantic schema generation errors. The server module cannot be imported because FastMCP's dependency injection markers are not properly configured.

## Symptoms

### Error 1: Pydantic Schema Generation
```
PydanticSchemaGenerationError: Unable to generate pydantic-core schema for
<class 'fastmcp.server.dependencies.Progress'>. Set `arbitrary_types_allowed=True`
in the model_config to ignore this error or implement `__get_pydantic_core_schema__`
on your type to fully support it.
```

### Error 2: Context Missing Argument
```
TypeError: Context.__init__() missing 1 required positional argument: 'fastmcp'
```

### Error 3: Incompatible Testing Utilities
```
AttributeError: 'FastMCP' object has no attribute 'create_initialization_options'
```

## Root Cause Analysis

### 1. Context Dependency Injection

FastMCP's `Context` is not meant to be instantiated directly. It requires `CurrentContext()` as a sentinel marker that tells FastMCP to inject the actual context at runtime.

**Wrong:**
```python
async def my_tool(task: str, ctx: Context = None) -> str:  # Won't work
async def my_tool(task: str, ctx: Context = Context()) -> str:  # Fails - needs 'fastmcp' arg
```

**Correct:**
```python
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

async def my_tool(task: str, ctx: Context = CurrentContext()) -> str:  # Works!
```

### 2. Progress Dependency Injection

Similarly, `Progress` needs `Progress()` as a default (which creates a sentinel), not `None`.

**Wrong:**
```python
async def my_tool(task: str, progress: Progress = None) -> str:  # Pydantic error
```

**Correct:**
```python
from fastmcp.dependencies import Progress

async def my_tool(task: str, progress: Progress = Progress()) -> str:  # Works!
```

### 3. Testing Framework Incompatibility

MCP SDK's `create_connected_server_and_client_session` is incompatible with FastMCP. FastMCP servers must be tested using FastMCP's own `Client` class.

**Wrong:**
```python
from mcp.shared.memory import create_connected_server_and_client_session

async with create_connected_server_and_client_session(app) as session:
    # Fails: FastMCP doesn't have create_initialization_options
```

**Correct:**
```python
from fastmcp import Client

async with Client(app) as client:
    result = await client.call_tool("my_tool", {"param": "value"})
```

## Solution

### Step 1: Update Imports in server.py

```python
# Before (MCP SDK)
from mcp.server.fastmcp import Context, FastMCP

# After (FastMCP package)
from fastmcp import FastMCP, TaskConfig
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context
```

### Step 2: Fix Tool Signatures

```python
@server.tool(task=TaskConfig(mode="optional"))
async def run_browser_agent(
    task: str,
    max_steps: Optional[int] = None,
    ctx: Context = CurrentContext(),  # noqa: B008
    progress: Progress = Progress(),  # noqa: B008
) -> str:
    """Execute a browser automation task."""
    # Implementation...
```

The `# noqa: B008` comments suppress ruff's warning about mutable defaults - these are intentional sentinel values.

### Step 3: Update Tests to Use FastMCP Client

```python
"""Tests for MCP server tools using FastMCP in-memory testing."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(monkeypatch) -> AsyncGenerator[Client, None]:
    """Create an in-memory FastMCP client for testing."""
    # Set environment variables BEFORE importing server
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # Import server after setting env vars
    from mcp_server_browser_use.server import serve

    app = serve()

    async with Client(app) as client:
        yield client


class TestListTools:
    @pytest.mark.anyio
    async def test_list_tools(self, client: Client):
        """Should list all available tools."""
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "run_browser_agent" in tool_names
        assert "run_deep_research" in tool_names


class TestRunBrowserAgent:
    @pytest.mark.anyio
    async def test_run_browser_agent_success(self, client: Client):
        """Should successfully run browser agent with mocked dependencies."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Task completed"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        ):
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to example.com"}
            )

            # FastMCP returns CallToolResult with content list
            assert result.content is not None
            assert "Task completed" in result.content[0].text
```

### Step 4: Verify Progress Handling in Tools

When using Progress, always check if it's available before calling methods:

```python
async def run_browser_agent(
    task: str,
    progress: Progress = Progress(),
) -> str:
    # Progress is always a valid object, but check before using
    if progress:
        await progress.set_total(steps)
        await progress.set_message("Starting...")

    # ... do work ...

    if progress:
        await progress.increment()
```

## Prevention Strategies

### 1. Use Correct Import Pattern

Always import from the correct FastMCP modules:

```python
# Correct imports for FastMCP
from fastmcp import FastMCP, TaskConfig, Client
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context
```

### 2. Use CurrentContext() Not Context()

`CurrentContext()` is a sentinel that tells FastMCP to inject the actual context. `Context()` tries to instantiate the class directly and fails.

### 3. Set Environment Variables Before Import

In tests, always set environment variables **before** importing the server module:

```python
@pytest.fixture
async def client(monkeypatch):
    # 1. Set env vars FIRST
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")

    # 2. THEN import server
    from mcp_server_browser_use.server import serve

    # 3. Create client
    async with Client(serve()) as client:
        yield client
```

### 4. Consult Context7 for FastMCP Documentation

When encountering FastMCP issues, use Context7 to fetch current documentation:

```python
# Search for FastMCP patterns
mcp__plugin_compound-engineering_context7__resolve-library-id(libraryName="fastmcp")
mcp__plugin_compound-engineering_context7__get-library-docs(
    context7CompatibleLibraryID="/jlowin/fastmcp",
    topic="context progress dependency injection"
)
```

## Validation Checklist

- [ ] All tools use `ctx: Context = CurrentContext()`
- [ ] All tools use `progress: Progress = Progress()` (not `None`)
- [ ] Tests import `Client` from `fastmcp`, not MCP SDK utilities
- [ ] Tests set env vars before importing server module
- [ ] `pytest` collection succeeds without errors
- [ ] All tests pass with `uv run pytest -v`

## Related Documentation

- [FastMCP Background Tasks Plan](../../plans/feat-fastmcp-background-tasks.md)
- [FastMCP Official Docs](https://gofastmcp.com/)
- [Context7 FastMCP Reference](/jlowin/fastmcp)

## Commands

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_mcp_tools.py -v

# Run with short traceback for debugging
uv run pytest -v --tb=short
```
