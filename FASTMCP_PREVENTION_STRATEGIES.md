# FastMCP Prevention Strategies & Test Patterns

Based on the FastMCP migration of mcp-browser-use, this document captures lessons learned and prevention strategies to avoid future issues when working with FastMCP.

## 1. Best Practices for FastMCP Development

### 1.1 Correct Dependency Injection Patterns

#### CurrentContext Usage

**CORRECT: Use `CurrentContext()` for tool parameters**

```python
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

server = FastMCP("my_server")

@server.tool()
async def my_tool(
    task: str,
    ctx: Context = CurrentContext(),  # ✅ Correct - uses CurrentContext()
) -> str:
    """Tool that needs context."""
    # ctx is automatically injected by FastMCP runtime
    return f"Processing: {task}"
```

**INCORRECT: Using `Context()` directly as default**

```python
from fastmcp.server.context import Context

@server.tool()
async def my_tool(
    task: str,
    ctx: Context = Context(),  # ❌ WRONG - creates static instance
) -> str:
    """Tool with broken context injection."""
    # ctx is None or stale - not properly injected
    return f"Processing: {task}"
```

**Why it matters:**
- `CurrentContext()` is a sentinel that FastMCP recognizes to inject the actual request context at runtime
- `Context()` creates a static instance that won't be updated for each request
- This breaks any context-dependent operations (authentication, request metadata, etc.)

#### Progress Usage

**CORRECT: Use `Progress()` with optional checking**

```python
from fastmcp.dependencies import Progress
from typing import Optional

@server.tool(task=TaskConfig(mode="optional"))
async def long_running_task(
    topic: str,
    progress: Progress = Progress(),  # ✅ Correct - uses Progress()
) -> str:
    """Tool with progress reporting."""
    # Check if progress is available before using
    if progress:
        await progress.set_total(100)
        await progress.set_message("Starting task...")

    # Do work...

    if progress:
        await progress.increment()

    return "Complete"
```

**INCORRECT: Using None as default**

```python
from fastmcp.dependencies import Progress
from typing import Optional

@server.tool(task=TaskConfig(mode="optional"))
async def long_running_task(
    topic: str,
    progress: Optional[Progress] = None,  # ❌ WRONG - defeats FastMCP's dependency system
) -> str:
    """Tool with broken progress."""
    # FastMCP won't inject Progress if you use Optional[Progress] = None
    # You're managing the fallback yourself, which is fragile
    if progress:
        await progress.set_total(100)
    return "Complete"
```

**Why it matters:**
- FastMCP's `Progress()` default automatically handles the "optional" case
- Using `Optional[Progress] = None` bypasses FastMCP's dependency injection system
- The tool may work in synchronous mode but fail in background task mode

#### Helper Pattern for Conditional Progress

```python
from fastmcp.dependencies import Progress

class ResearchMachine:
    def __init__(self, topic: str, progress: Progress = Progress()):
        self.topic = topic
        self.progress = progress

    async def _report_progress(
        self,
        message: Optional[str] = None,
        increment: bool = False,
        total: Optional[int] = None,
    ) -> None:
        """Report progress only if available.

        This pattern allows graceful degradation:
        - Works with background task mode (Progress is injected)
        - Works with synchronous mode (Progress is empty, operations are no-ops)
        """
        if not self.progress:
            return
        if total is not None:
            await self.progress.set_total(total)
        if message:
            await self.progress.set_message(message)
        if increment:
            await self.progress.increment()
```

### 1.2 Task Configuration Patterns

**CORRECT: Optional background task mode**

```python
from fastmcp import FastMCP, TaskConfig

@server.tool(task=TaskConfig(mode="optional"))
async def my_research_tool(
    topic: str,
    ctx: Context = CurrentContext(),
    progress: Progress = Progress(),
) -> str:
    """
    Tool that supports both synchronous and background execution.

    - If client requests task=true: runs in background, progress updates stream
    - If client requests task=false: runs synchronously, returns result directly
    """
    return "Report"
```

**Required task mode (for truly background-only operations):**

```python
@server.tool(task=TaskConfig(mode="required"))
async def background_only_task(
    topic: str,
    progress: Progress = Progress(),
) -> str:
    """This tool MUST be executed as a background task."""
    return "Report"
```

### 1.3 Import Organization

**CORRECT: Import structure for FastMCP tools**

```python
# ✅ Correct import pattern
from fastmcp import FastMCP, TaskConfig
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context

# Create server with optional task support
server = FastMCP("server_name")

# Dependencies are properly typed and injected
@server.tool(task=TaskConfig(mode="optional"))
async def tool_name(
    param: str,
    ctx: Context = CurrentContext(),
    progress: Progress = Progress(),
) -> str:
    """Tool description."""
    return "result"
```

**INCORRECT: Old MCP SDK imports**

```python
# ❌ WRONG - These are from old MCP SDK, not FastMCP
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp import Progress

# This will fail with modern FastMCP
```

---

## 2. Common Pitfalls & Prevention

### 2.1 Pitfall: Using MCP SDK Testing with FastMCP

**PROBLEM:** Attempting to use old MCP SDK testing utilities with FastMCP server

```python
# ❌ WRONG - Won't work with FastMCP
from mcp.testing import setup_test_server, Client
from mcp_server_browser_use.server import serve

def test_tool():
    server = serve()
    # This won't work! setup_test_server is for old MCP SDK
    # FastMCP has different testing patterns
```

**SOLUTION:** Use FastMCP's Client directly

```python
# ✅ CORRECT - FastMCP testing pattern
from fastmcp import Client
from mcp_server_browser_use.server import serve
import pytest

@pytest.fixture
async def client():
    app = serve()
    async with Client(app) as client:
        yield client

@pytest.mark.anyio
async def test_tool(client: Client):
    result = await client.call_tool("run_browser_agent", {"task": "Go to example.com"})
    assert result.content is not None
```

### 2.2 Pitfall: Confusing `Context()` with `CurrentContext()`

**PROBLEM:** Using static Context instance instead of injection sentinel

| Aspect | `Context()` | `CurrentContext()` |
|--------|-------------|-------------------|
| **Type** | Creates instance | Sentinel/marker |
| **FastMCP behavior** | Static (not injected) | Recognized, triggers DI |
| **Use case** | ❌ Don't use as default | ✅ Use as default |
| **Runtime value** | May be None or stale | Injected at tool call time |

### 2.3 Pitfall: Not Checking Progress Availability

**PROBLEM:** Assuming Progress is always available

```python
# ❌ WRONG - May crash if Progress is None
@server.tool()
async def task(progress: Progress = Progress()) -> str:
    await progress.set_total(100)  # Crashes if progress is None!
    await progress.increment()
    return "done"
```

**SOLUTION:** Always guard Progress operations

```python
# ✅ CORRECT - Safe handling of optional Progress
@server.tool()
async def task(progress: Progress = Progress()) -> str:
    if progress:
        await progress.set_total(100)

    # Do work...

    if progress:
        await progress.increment()
    return "done"
```

### 2.4 Pitfall: Forgetting TaskConfig Import

**PROBLEM:** Using task=True instead of TaskConfig

```python
# ❌ WRONG - task parameter is not boolean
@server.tool(task=True)  # What is this? Not recognized
async def my_tool() -> str:
    return "result"
```

**SOLUTION:** Always import and use TaskConfig

```python
# ✅ CORRECT
from fastmcp import TaskConfig

@server.tool(task=TaskConfig(mode="optional"))
async def my_tool(progress: Progress = Progress()) -> str:
    return "result"
```

### 2.5 Pitfall: Progress Operations Without Await

**PROBLEM:** Forgetting async/await on Progress methods

```python
# ❌ WRONG - Progress methods are async
@server.tool()
async def task(progress: Progress = Progress()) -> str:
    if progress:
        progress.set_message("Starting...")  # Missing await!
        progress.set_total(100)  # Missing await!
    return "done"
```

**SOLUTION:** Always await Progress operations

```python
# ✅ CORRECT
@server.tool()
async def task(progress: Progress = Progress()) -> str:
    if progress:
        await progress.set_message("Starting...")
        await progress.set_total(100)
    return "done"
```

---

## 3. Test Patterns for FastMCP Servers

### 3.1 Basic FastMCP Client Fixture

```python
"""Test fixture for FastMCP in-memory testing."""

import pytest
from collections.abc import AsyncGenerator
from fastmcp import Client
from mcp_server_browser_use.server import serve


@pytest.fixture
def anyio_backend():
    """Use asyncio for async tests."""
    return "asyncio"


@pytest.fixture
async def client(monkeypatch) -> AsyncGenerator[Client, None]:
    """
    Create an in-memory FastMCP client for testing.

    - Sets environment variables before importing server
    - Creates server instance
    - Yields client for tests
    - Cleans up automatically
    """
    # Set environment variables BEFORE importing server (config reads them)
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-12345")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # Import server AFTER env vars are set
    from mcp_server_browser_use.server import serve

    app = serve()

    # Create client connection
    async with Client(app) as client:
        yield client
```

### 3.2 Tool Testing Pattern

```python
"""Test MCP tools with mocking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastmcp import Client


class TestRunBrowserAgent:
    """Test the run_browser_agent tool."""

    @pytest.mark.anyio
    async def test_run_browser_agent_success(self, client: Client):
        """Should successfully run browser agent with mocked dependencies."""
        # Mock the agent
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Task completed: Found 10 results"
        mock_agent.run = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()

        # Patch dependencies before calling tool
        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=mock_llm),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        ):
            # Call tool through FastMCP client
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to example.com"}
            )

            # FastMCP returns CallToolResult with content list
            assert result.content is not None
            assert len(result.content) > 0
            assert "Task completed" in result.content[0].text

    @pytest.mark.anyio
    async def test_run_browser_agent_with_optional_params(self, client: Client):
        """Should accept optional parameters."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Done"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent) as agent_class,
        ):
            # Call with optional max_steps parameter
            await client.call_tool(
                "run_browser_agent",
                {"task": "Test task", "max_steps": 5}
            )

            # Verify Agent was instantiated with correct max_steps
            call_kwargs = agent_class.call_args[1]
            assert call_kwargs["max_steps"] == 5

    @pytest.mark.anyio
    async def test_run_browser_agent_error_handling(self, client: Client):
        """Should handle initialization errors gracefully."""
        from mcp_server_browser_use.exceptions import LLMProviderError

        with patch("mcp_server_browser_use.server.get_llm") as mock_get_llm:
            mock_get_llm.side_effect = LLMProviderError("API key missing")

            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Test"}
            )

            # Tool should return error message, not raise
            assert result.content is not None
            assert len(result.content) > 0
            assert "Error" in result.content[0].text
```

### 3.3 Tool List Verification

```python
@pytest.mark.anyio
async def test_list_all_tools(client: Client):
    """Verify all expected tools are registered."""
    tools = await client.list_tools()
    tool_names = [tool.name for tool in tools]

    # Verify expected tools exist
    assert "run_browser_agent" in tool_names
    assert "run_deep_research" in tool_names

    # Verify tool schema
    agent_tool = next(t for t in tools if t.name == "run_browser_agent")
    assert agent_tool.description is not None
    assert "task" in str(agent_tool.inputSchema)
```

### 3.4 Parametrized Testing

```python
@pytest.mark.parametrize("max_steps,expected_calls", [
    (None, 1),        # Default max_steps used
    (5, 1),           # Explicit max_steps used
    (10, 1),          # Different explicit value
])
@pytest.mark.anyio
async def test_agent_max_steps_variants(client: Client, max_steps, expected_calls):
    """Test various max_steps configurations."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=MagicMock(final_result=lambda: "Done"))

    with patch("mcp_server_browser_use.server.Agent", return_value=mock_agent):
        params = {"task": "Test"}
        if max_steps is not None:
            params["max_steps"] = max_steps

        await client.call_tool("run_browser_agent", params)

        # Verify Agent was called with correct parameters
        assert mock_agent.run.call_count == expected_calls
```

### 3.5 Mocking Patterns for Complex Dependencies

```python
"""Mocking patterns for browser-use specific components."""

@pytest.fixture
def mock_browser_profile():
    """Mock BrowserProfile for testing."""
    profile = MagicMock()
    profile.headless = True
    return profile


@pytest.fixture
def mock_llm():
    """Mock LLM for testing."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(completion="Test response"))
    return llm


@pytest.fixture
def mock_agent():
    """Mock Agent for testing."""
    agent = MagicMock()
    result = MagicMock()
    result.final_result.return_value = "Agent completed"
    result.history = []
    agent.run = AsyncMock(return_value=result)
    return agent


@pytest.mark.anyio
async def test_with_mocked_dependencies(
    client: Client,
    mock_agent,
    mock_llm,
    mock_browser_profile,
):
    """Test with all dependencies mocked."""
    with (
        patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        patch("mcp_server_browser_use.server.get_llm", return_value=mock_llm),
        patch("mcp_server_browser_use.server.BrowserProfile", return_value=mock_browser_profile),
    ):
        result = await client.call_tool(
            "run_browser_agent",
            {"task": "Go to example.com"}
        )
        assert result.content is not None
```

---

## 4. Documentation Consultation Guide

### When to Check FastMCP Context7 Documentation

Check [Context7 FastMCP Documentation](https://context7.com) when:

1. **Dependency Injection Issues**
   - "How do I inject request context?"
   - "What dependencies are available?"
   - Search: `CurrentContext`, `Progress`, `Context`

2. **Tool Configuration**
   - "How do I make a tool run in background?"
   - "What does task=True vs task=False mean?"
   - Search: `TaskConfig`, `task mode`, `background execution`

3. **Progress Reporting**
   - "How do I report progress to clients?"
   - "What methods are available on Progress?"
   - Search: `Progress`, `set_message`, `set_total`, `increment`

4. **Error Handling**
   - "What exceptions should tools raise?"
   - "How do I handle validation errors?"
   - Search: `exceptions`, `error handling`, `validation`

5. **Testing**
   - "How do I test FastMCP tools?"
   - "What's the FastMCP test client?"
   - Search: `testing`, `Client`, `test fixtures`

### Quick Reference URLs

- **Dependencies:** Context7 > FastMCP > Execution > Dependencies
- **Tasks:** Context7 > FastMCP > Execution > Tasks
- **Progress:** Context7 > FastMCP > Execution > Progress
- **Testing:** Context7 > FastMCP > Testing

---

## 5. Migration Checklist for Old Projects

When migrating from old MCP SDK to FastMCP:

- [ ] **Update imports**
  - Replace `from mcp.server.fastmcp import` with `from fastmcp import`
  - Add `from fastmcp.dependencies import CurrentContext, Progress`

- [ ] **Fix Context injection**
  - Replace `ctx: Context = Context()` with `ctx: Context = CurrentContext()`
  - Verify all tools using context have this pattern

- [ ] **Fix Progress handling**
  - Change `progress: Optional[Progress] = None` to `progress: Progress = Progress()`
  - Add guards: `if progress:` before operations

- [ ] **Update tool decorators**
  - Add `task=TaskConfig(mode="optional")` for async operations
  - Verify decorator import: `from fastmcp import TaskConfig`

- [ ] **Update tests**
  - Replace MCP SDK test utilities with `from fastmcp import Client`
  - Use `@pytest.mark.anyio` and `async with Client(app)`
  - Update mock patches to FastMCP module paths

- [ ] **Update documentation**
  - Update API docs showing tool signatures
  - Document which tools support background execution
  - Update examples with new import statements

---

## 6. Key Takeaways

| Issue | Prevention |
|-------|-----------|
| Static Context instances | Always use `CurrentContext()` as default |
| Missing Progress checks | Always guard Progress ops with `if progress:` |
| Broken test setup | Use `Client(app)` not MCP SDK test utilities |
| Task config confusion | Import and use `TaskConfig(mode="...")` |
| Async/await mistakes | Remember Progress methods are async |
| Stale configuration | Set env vars BEFORE importing server |
| Import confusion | Keep FastMCP imports consistent across codebase |

---

## Summary

The FastMCP migration of mcp-browser-use revealed these core patterns:

1. **Dependency Injection Correctness**: Use `CurrentContext()` and `Progress()` as sentinels, not instances
2. **Defensive Progress Handling**: Always check if Progress exists before using
3. **FastMCP-Native Testing**: Replace old MCP SDK patterns with FastMCP's Client-based approach
4. **Task Configuration**: Use `TaskConfig` for background-capable tools
5. **Configuration Timing**: Load environment variables before importing server module

Following these strategies prevents common FastMCP pitfalls and ensures reliable, maintainable MCP servers.
