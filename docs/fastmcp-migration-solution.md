# FastMCP Migration Solution Guide

## Executive Summary

This document captures the working solution for migrating from the MCP SDK to FastMCP, focusing on the key dependency injection patterns and testing approaches that enable native background task support with progress reporting.

---

## Part 1: Root Cause Analysis

### The Problem

The migration from `mcp` SDK's FastMCP to `fastmcp` (jlowin's package) revealed critical differences in how dependency injection works between the two frameworks.

### Key Differences

#### 1. Context Dependency Injection

**MCP SDK Pattern:**
```python
from mcp.server.fastmcp import Context, FastMCP

@app.tool()
async def my_tool(ctx: Context = None) -> str:
    # Context was optional, defaulted to None
    pass
```

**FastMCP Pattern (Correct):**
```python
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

@server.tool()
async def my_tool(ctx: Context = CurrentContext()) -> str:
    # MUST use CurrentContext() as the default, not Context()
    pass
```

**Why it matters:** FastMCP uses a dependency marker pattern. `CurrentContext()` tells FastMCP's dependency injection system to inject the current request context. Using `Context()` directly doesn't work because it tries to instantiate an empty context without request data.

#### 2. Progress Dependency Injection

**MCP SDK Pattern:**
```python
@app.tool(task=True)
async def long_task(progress: Progress = None) -> str:
    if progress:
        await progress.increment()
    pass
```

**FastMCP Pattern (Correct):**
```python
from fastmcp.dependencies import Progress

@server.tool(task=TaskConfig(mode="optional"))
async def long_task(progress: Progress = Progress()) -> str:
    # MUST use Progress() as default, not None
    if progress:
        await progress.increment()
    pass
```

**Why it matters:** FastMCP's Progress is a dependency-injected class. When a client doesn't request background task execution, FastMCP injects a no-op Progress instance. When background tasks are enabled, it injects the real progress tracker. Always use `Progress()` as the default—FastMCP handles the runtime substitution.

#### 3. Testing Framework

**MCP SDK Pattern:**
```python
from mcp.testing import create_connected_server_and_client_session

async def test_tool():
    async with create_connected_server_and_client_session(server) as (ctx, client):
        result = await client.call_tool("tool_name", {})
```

**FastMCP Pattern (Correct):**
```python
from fastmcp import Client

@pytest.fixture
async def client():
    from mcp_server_browser_use.server import serve
    app = serve()
    async with Client(app) as client:
        yield client

async def test_tool(client: Client):
    result = await client.call_tool("run_browser_agent", {"task": "..."})
    # FastMCP returns CallToolResult with .content list
    assert len(result.content) > 0
    assert "expected text" in result.content[0].text
```

**Why it matters:** FastMCP's `Client` class provides in-memory testing without requiring separate server/client sessions. The API is simpler and more intuitive.

---

## Part 2: Solution Implementation

### Step 1: Update Dependencies

**File: `pyproject.toml`**

```toml
dependencies = [
  "browser-use>=0.10.1",
  "fastmcp @ git+https://github.com/jlowin/fastmcp.git@main",  # Use jlowin's repo
  "pydantic-settings>=2.0.0",
  "typer>=0.12.0",
  "uvicorn>=0.30.0",
  "starlette>=0.38.0",
]

[dependency-groups]
dev = [
  "pyright>=1.1.378",
  "pytest>=8.3.3",
  "pytest-asyncio>=0.24.0",  # For async test support
  "ruff>=0.6.9",
]
```

**Installation:**
```bash
uv sync --dev
uv run playwright install
```

### Step 2: Server Implementation

**File: `src/mcp_server_browser_use/server.py`**

```python
"""MCP server exposing browser-use as tools with native background task support."""

import logging
from typing import Optional

from browser_use import Agent, BrowserProfile
from browser_use.browser.profile import ProxySettings
from fastmcp import FastMCP, TaskConfig
from fastmcp.dependencies import CurrentContext, Progress  # ← Key imports
from fastmcp.server.context import Context  # ← Correct import

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm
from .research.machine import ResearchMachine

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.server.logging_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_server_browser_use")


def serve() -> FastMCP:
    """Create and configure MCP server with background task support."""
    server = FastMCP("mcp_server_browser_use")

    def _get_llm_and_profile():
        """Helper to get LLM instance and browser profile."""
        llm = get_llm(
            provider=settings.llm.provider,
            model=settings.llm.model_name,
            api_key=settings.llm.get_api_key_for_provider(),
            base_url=settings.llm.base_url,
            azure_endpoint=settings.llm.azure_endpoint,
            azure_api_version=settings.llm.azure_api_version,
            aws_region=settings.llm.aws_region,
        )
        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(
                server=settings.browser.proxy_server,
                bypass=settings.browser.proxy_bypass,
            )
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
        return llm, profile

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_browser_agent(
        task: str,
        max_steps: Optional[int] = None,
        ctx: Context = CurrentContext(),  # ✓ Use CurrentContext() marker
        progress: Progress = Progress(),  # ✓ Use Progress() default
    ) -> str:
        """
        Execute a browser automation task using AI.

        Supports background execution with progress tracking when client requests it.

        Args:
            task: Natural language description of what to do in the browser
            max_steps: Maximum number of agent steps (default from settings)

        Returns:
            Result of the browser automation task
        """
        logger.info(f"Starting browser agent task: {task[:100]}...")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        steps = max_steps if max_steps is not None else settings.agent.max_steps

        if progress:
            await progress.set_total(steps)
            await progress.set_message("Starting browser agent...")

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
            )

            result = await agent.run()

            # Mark as complete
            if progress:
                await progress.set_total(1)
                await progress.increment()

            final = result.final_result() or "Task completed without explicit result."
            logger.info(f"Agent completed: {final[:100]}...")
            return final

        except Exception as e:
            logger.error(f"Browser agent failed: {e}")
            raise BrowserError(f"Browser automation failed: {e}") from e

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_deep_research(
        topic: str,
        max_searches: Optional[int] = None,
        save_to_file: Optional[str] = None,
        ctx: Context = CurrentContext(),  # ✓ Use CurrentContext() marker
        progress: Progress = Progress(),  # ✓ Use Progress() default
    ) -> str:
        """
        Execute deep research on a topic with progress tracking.

        Runs as a background task if client requests it, otherwise synchronous.
        Progress updates are streamed via the MCP task protocol.

        Args:
            topic: The research topic or question to investigate
            max_searches: Maximum number of web searches (default from settings)
            save_to_file: Optional file path to save the report

        Returns:
            The research report as markdown
        """
        logger.info(f"Starting deep research on: {topic}")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        searches = (
            max_searches
            if max_searches is not None
            else settings.research.max_searches
        )
        save_path = save_to_file or (
            f"{settings.research.save_directory}/{topic[:50].replace(' ', '_')}.md"
            if settings.research.save_directory
            else None
        )

        # Execute research with progress tracking
        machine = ResearchMachine(
            topic=topic,
            max_searches=searches,
            save_path=save_path,
            llm=llm,
            browser_profile=profile,
            progress=progress,  # ← Pass Progress to research machine
        )

        report = await machine.run()
        return report

    return server


server_instance = serve()


def main() -> None:
    """Entry point for MCP server."""
    transport = settings.server.transport
    logger.info(
        f"Starting MCP browser-use server (provider: {settings.llm.provider}, transport: {transport})"
    )

    if transport == "stdio":
        server_instance.run()
    elif transport in ("streamable-http", "sse"):
        logger.info(f"HTTP server at http://{settings.server.host}:{settings.server.port}/mcp")
        server_instance.run(transport=transport, host=settings.server.host, port=settings.server.port)
    else:
        raise ValueError(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()
```

**Key patterns:**
- Use `CurrentContext()` as default for `ctx` parameter
- Use `Progress()` as default for `progress` parameter
- Always check `if progress:` before calling progress methods (it may be a no-op)
- Use `TaskConfig(mode="optional")` to support both background and synchronous execution

### Step 3: Research Machine Integration

**File: `src/mcp_server_browser_use/research/machine.py` (excerpt)**

```python
"""Research state machine for executing deep research tasks with progress tracking."""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel
    from fastmcp.dependencies import Progress


class ResearchMachine:
    """Research workflow with native MCP progress reporting."""

    def __init__(
        self,
        topic: str,
        max_searches: int,
        save_path: Optional[str],
        llm: "BaseChatModel",
        browser_profile: "BrowserProfile",
        progress: Optional["Progress"] = None,  # ← Accept Progress
    ):
        self.topic = topic
        self.max_searches = max_searches
        self.save_path = save_path
        self.llm = llm
        self.browser_profile = browser_profile
        self.progress = progress

    async def _report_progress(
        self,
        message: Optional[str] = None,
        increment: bool = False,
        total: Optional[int] = None,
    ) -> None:
        """Report progress if progress tracker is available."""
        if not self.progress:  # ← Always check if progress exists
            return
        if total is not None:
            await self.progress.set_total(total)
        if message:
            await self.progress.set_message(message)
        if increment:
            await self.progress.increment()

    async def run(self) -> str:
        """Execute the research workflow and return the report."""
        # Total steps: planning (1) + searches (max_searches) + synthesis (1)
        total_steps = self.max_searches + 2
        await self._report_progress(total=total_steps)

        # Phase 1: Planning
        await self._report_progress(message="Planning research approach...")
        queries = await self._generate_queries()
        if not queries:
            raise ValueError("Failed to generate search queries")
        await self._report_progress(increment=True)

        # Phase 2: Executing searches
        for i, query in enumerate(queries):
            await self._report_progress(
                message=f"Searching ({i + 1}/{len(queries)}): {query}"
            )
            result = await self._execute_search(query)
            self.search_results.append(result)
            await self._report_progress(increment=True)

        # Phase 3: Synthesizing
        await self._report_progress(message="Synthesizing findings into report...")
        report = await self._synthesize_report()

        if self.save_path:
            await self._save_report(report)

        await self._report_progress(increment=True)
        return report
```

**Key patterns:**
- Use `Optional["Progress"]` for type hints (avoid circular imports)
- Always check `if not self.progress:` before using it
- Call `_report_progress()` at each significant step

### Step 4: Testing Implementation

**File: `tests/test_mcp_tools.py`**

```python
"""Tests for MCP server tools using FastMCP in-memory testing."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for pytest-asyncio."""
    return "asyncio"


@pytest.fixture
async def client(monkeypatch) -> AsyncGenerator[Client, None]:
    """Create an in-memory FastMCP client for testing."""
    # Set environment variables for testing
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # Import server after setting env vars to ensure config picks them up
    from mcp_server_browser_use.server import serve

    app = serve()

    # ✓ Use FastMCP's Client class for in-memory testing
    async with Client(app) as client:
        yield client


class TestListTools:
    """Test that all expected tools are registered."""

    @pytest.mark.anyio
    async def test_list_tools(self, client: Client):
        """Should list all available tools."""
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "run_browser_agent" in tool_names
        assert "run_deep_research" in tool_names
        assert len(tool_names) == 2

    @pytest.mark.anyio
    async def test_run_browser_agent_tool_schema(self, client: Client):
        """run_browser_agent tool should have correct schema."""
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "run_browser_agent")

        assert tool.description is not None
        assert "task" in str(tool.inputSchema)

    @pytest.mark.anyio
    async def test_run_deep_research_tool_schema(self, client: Client):
        """run_deep_research tool should have correct schema."""
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "run_deep_research")

        assert tool.description is not None
        assert "topic" in str(tool.inputSchema)


class TestRunBrowserAgent:
    """Test the run_browser_agent tool."""

    @pytest.mark.anyio
    async def test_run_browser_agent_success(self, client: Client):
        """Should successfully run browser agent with mocked dependencies."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Task completed: Found 10 results"
        mock_agent.run = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=mock_llm),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        ):
            # ✓ Call tool and get CallToolResult with .content list
            result = await client.call_tool(
                "run_browser_agent", {"task": "Go to example.com"}
            )

            # FastMCP returns result.content as a list of TextContent
            assert result.content is not None
            assert len(result.content) > 0
            assert "Task completed" in result.content[0].text

    @pytest.mark.anyio
    async def test_run_browser_agent_with_max_steps(self, client: Client):
        """Should accept max_steps parameter."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Done"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch(
                "mcp_server_browser_use.server.Agent", return_value=mock_agent
            ) as agent_class,
        ):
            await client.call_tool(
                "run_browser_agent", {"task": "Test task", "max_steps": 5}
            )

            # Verify Agent was called with max_steps=5
            call_kwargs = agent_class.call_args[1]
            assert call_kwargs["max_steps"] == 5


class TestRunDeepResearch:
    """Test the run_deep_research tool."""

    @pytest.mark.anyio
    async def test_run_deep_research_success(self, client: Client):
        """Should successfully run deep research with mocked dependencies."""
        mock_machine = MagicMock()
        mock_machine.run = AsyncMock(return_value="# Research Report\n\nFindings here...")

        mock_llm = MagicMock()

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=mock_llm),
            patch(
                "mcp_server_browser_use.server.ResearchMachine",
                return_value=mock_machine,
            ),
        ):
            result = await client.call_tool(
                "run_deep_research", {"topic": "AI safety"}
            )

            assert result.content is not None
            assert len(result.content) > 0
            assert "Research Report" in result.content[0].text or "Findings" in result.content[0].text

    @pytest.mark.anyio
    async def test_run_deep_research_with_options(self, client: Client):
        """Should accept optional parameters."""
        mock_machine = MagicMock()
        mock_machine.run = AsyncMock(return_value="Report content")

        mock_llm = MagicMock()

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=mock_llm),
            patch(
                "mcp_server_browser_use.server.ResearchMachine",
                return_value=mock_machine,
            ) as machine_class,
        ):
            await client.call_tool(
                "run_deep_research",
                {
                    "topic": "Machine learning",
                    "max_searches": 10,
                    "save_to_file": "/tmp/report.md",
                },
            )

            # Verify ResearchMachine was called with correct args
            call_kwargs = machine_class.call_args[1]
            assert call_kwargs["topic"] == "Machine learning"
            assert call_kwargs["max_searches"] == 10
            assert call_kwargs["save_path"] == "/tmp/report.md"
```

**Key testing patterns:**
- Use `@pytest.mark.anyio` for async tests
- Use `Client(app)` for in-memory testing (no separate server/client sessions)
- Results have `.content` as a list of text objects
- Access text via `result.content[0].text`

---

## Part 3: Common Pitfalls and Solutions

### Pitfall 1: Using `Context()` Instead of `CurrentContext()`

**❌ WRONG:**
```python
from fastmcp.server.context import Context

@server.tool()
async def my_tool(ctx: Context = Context()):  # No dependency marker!
    pass
```

**✓ CORRECT:**
```python
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context

@server.tool()
async def my_tool(ctx: Context = CurrentContext()):  # Dependency marker
    pass
```

### Pitfall 2: Using `None` Instead of `Progress()`

**❌ WRONG:**
```python
from fastmcp.dependencies import Progress

@server.tool(task=TaskConfig(mode="optional"))
async def my_task(progress: Progress = None):  # Defeats dependency injection
    if progress:
        await progress.increment()
```

**✓ CORRECT:**
```python
from fastmcp.dependencies import Progress
from fastmcp import TaskConfig

@server.tool(task=TaskConfig(mode="optional"))
async def my_task(progress: Progress = Progress()):  # FastMCP swaps implementation
    if progress:
        await progress.increment()
```

### Pitfall 3: Not Checking for Progress

**❌ WRONG:**
```python
@server.tool(task=TaskConfig(mode="optional"))
async def my_task(progress: Progress = Progress()):
    await progress.set_total(10)  # May fail if not injected properly
    await progress.increment()
```

**✓ CORRECT:**
```python
@server.tool(task=TaskConfig(mode="optional"))
async def my_task(progress: Progress = Progress()):
    if progress:  # Always check first
        await progress.set_total(10)
        await progress.increment()
```

### Pitfall 4: Importing from Wrong Modules

**❌ WRONG:**
```python
from mcp.server.fastmcp import Context, FastMCP  # Old MCP SDK
from fastmcp import Context  # Doesn't exist in fastmcp package
```

**✓ CORRECT:**
```python
from fastmcp import FastMCP, TaskConfig  # Main fastmcp imports
from fastmcp.dependencies import CurrentContext, Progress  # Dependency markers
from fastmcp.server.context import Context  # Context type
```

### Pitfall 5: Wrong Test Setup

**❌ WRONG:**
```python
from mcp.testing import create_connected_server_and_client_session

@pytest.fixture
async def client():
    from mcp_server_browser_use.server import server_instance
    async with create_connected_server_and_client_session(server_instance) as (ctx, client):
        yield client
```

**✓ CORRECT:**
```python
from fastmcp import Client

@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from mcp_server_browser_use.server import serve
    app = serve()

    async with Client(app) as client:
        yield client
```

---

## Part 4: Validation Checklist

### Server Implementation

- [ ] `CurrentContext()` used as default for `ctx: Context` parameters
- [ ] `Progress()` used as default for `progress: Progress` parameters
- [ ] All tool parameters are optional with proper defaults
- [ ] `@server.tool(task=TaskConfig(mode="optional"))` decorator on background tasks
- [ ] Progress methods wrapped in `if progress:` checks
- [ ] Logging configured and working
- [ ] No circular imports in type hints (use `TYPE_CHECKING` blocks)

### Research Machine

- [ ] Accepts `Optional["Progress"]` parameter
- [ ] All progress updates wrapped in `if self.progress:` checks
- [ ] Calls `set_total()` before starting work
- [ ] Calls `set_message()` for status updates
- [ ] Calls `increment()` after completing steps

### Testing

- [ ] Tests use `@pytest.mark.anyio` decorator
- [ ] Fixture uses `Client(app)` for in-memory testing
- [ ] Tests check `result.content[0].text` for results
- [ ] Environment variables set in fixture before importing server
- [ ] Mocks properly applied with `patch()`

### CLI

- [ ] Environment variables properly initialized before serving
- [ ] Transport selection works (stdio, http, sse)
- [ ] Server starts without errors

---

## Part 5: Running and Testing

### Installation

```bash
# Install dependencies
uv sync --dev

# Install Playwright browsers (required for automation)
uv run playwright install
```

### Running the Server

```bash
# Run MCP server (stdio - default)
uv run mcp-server-browser-use

# Run MCP server (HTTP - stateful)
MCP_SERVER_TRANSPORT=streamable-http MCP_SERVER_PORT=8000 uv run mcp-server-browser-use
# Server runs at http://localhost:8000/mcp

# Run MCP server (SSE transport)
MCP_SERVER_TRANSPORT=sse MCP_SERVER_PORT=8000 uv run mcp-server-browser-use

# Run CLI
uv run mcp-browser-cli -e .env run-browser-agent "Go to example.com"
uv run mcp-browser-cli -e .env run-deep-research "Research topic"
```

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_mcp_tools.py

# Run single test by name
uv run pytest -k "test_run_browser_agent_success"

# Verbose output with short traceback
uv run pytest -v --tb=short

# Watch mode (requires pytest-watch)
uv run ptw
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint check
uv run ruff check .

# Auto-fix lint issues
uv run ruff check . --fix

# Type checking
uv run pyright
```

---

## Part 6: Architecture Reference

### Dependency Injection Flow

```
User calls tool via MCP client
    ↓
FastMCP receives request
    ↓
FastMCP inspects tool function signature
    ↓
For ctx: Context = CurrentContext():
    ✓ Inject current request Context
For progress: Progress = Progress():
    ✓ If task mode: inject real Progress tracker
    ✓ Otherwise: inject no-op Progress
    ↓
Tool function executes with injected dependencies
    ↓
Tool returns result to client
```

### Progress Tracking Flow

```
Client requests background task execution (task=True)
    ↓
FastMCP creates Progress tracker
    ↓
Tool receives injected Progress instance
    ↓
Tool calls progress.set_total(N)
    ↓
Tool calls progress.set_message("status")
    ↓
Tool calls progress.increment()
    ↓
Client receives progress updates via MCP protocol
```

---

## References

- [FastMCP Documentation](https://gofastmcp.com)
- [FastMCP GitHub Repository](https://github.com/jlowin/fastmcp)
- [MCP Specification - Tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [browser-use Documentation](https://github.com/browser-use/browser-use)
- [pydantic-settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

---

## Summary

The FastMCP migration success depends on three key insights:

1. **Dependency Injection Markers**: Use `CurrentContext()` and `Progress()` as defaults, not actual values
2. **Optional Progress**: Always check `if progress:` before calling progress methods
3. **Testing Pattern**: Use FastMCP's `Client` class for in-memory testing, not MCP SDK's patterns

With these patterns in place, the system gains native MCP protocol support for background tasks with full progress tracking, while maintaining backward compatibility with synchronous tool execution.
