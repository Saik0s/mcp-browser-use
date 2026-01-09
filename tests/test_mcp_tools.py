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
    """Create an in-memory FastMCP client for testing with recipes enabled."""
    # Set environment variables for testing
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("MCP_RECIPES_ENABLED", "true")  # Enable recipes for testing

    # Reload config module to pick up new env vars
    import importlib

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    # Update settings reference in server module before reloading
    import mcp_server_browser_use.server

    mcp_server_browser_use.server.settings = mcp_server_browser_use.config.settings
    importlib.reload(mcp_server_browser_use.server)

    from mcp_server_browser_use.server import serve

    app = serve()

    async with Client(app) as client:
        yield client


@pytest.fixture
async def client_recipes_disabled(monkeypatch) -> AsyncGenerator[Client, None]:
    """Create an in-memory FastMCP client with recipes disabled (default behavior)."""
    # Set environment variables for testing
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # Reload config module to pick up new env vars
    import importlib

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    # Directly disable recipes in the loaded settings (overrides config file)
    mcp_server_browser_use.config.settings.recipes.enabled = False

    # Update settings reference in server module before reloading
    import mcp_server_browser_use.server

    mcp_server_browser_use.server.settings = mcp_server_browser_use.config.settings
    importlib.reload(mcp_server_browser_use.server)

    from mcp_server_browser_use.server import serve

    app = serve()

    async with Client(app) as client:
        yield client


class TestListTools:
    """Test that all expected tools are registered."""

    @pytest.mark.anyio
    async def test_list_tools(self, client: Client):
        """Should list all available tools when recipes are enabled."""
        tools = await client.list_tools()
        tool_names = [tool.name for tool in tools]

        # Core browser automation tools
        assert "run_browser_agent" in tool_names
        assert "run_deep_research" in tool_names
        # Recipe management tools (only present when recipes.enabled=true)
        assert "recipe_list" in tool_names
        assert "recipe_get" in tool_names
        assert "recipe_delete" in tool_names
        # Observability tools
        assert "health_check" in tool_names
        assert "task_list" in tool_names
        assert "task_get" in tool_names
        assert "task_cancel" in tool_names
        assert len(tool_names) == 9

    @pytest.mark.anyio
    async def test_list_tools_recipes_disabled(self, client_recipes_disabled: Client):
        """Should not list recipe tools when recipes are disabled."""
        tools = await client_recipes_disabled.list_tools()
        tool_names = [tool.name for tool in tools]

        # Core browser automation tools should be present
        assert "run_browser_agent" in tool_names
        assert "run_deep_research" in tool_names
        # Observability tools should be present
        assert "health_check" in tool_names
        assert "task_list" in tool_names
        assert "task_get" in tool_names
        assert "task_cancel" in tool_names
        # Recipe management tools should NOT be present when recipes disabled
        assert "recipe_list" not in tool_names
        assert "recipe_get" not in tool_names
        assert "recipe_delete" not in tool_names
        assert len(tool_names) == 6

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
            result = await client.call_tool("run_browser_agent", {"task": "Go to example.com"})

            # FastMCP returns a CallToolResult with content list
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
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent) as agent_class,
        ):
            await client.call_tool("run_browser_agent", {"task": "Test task", "max_steps": 5})

            # Verify Agent was called with max_steps=5
            call_kwargs = agent_class.call_args[1]
            assert call_kwargs["max_steps"] == 5

    @pytest.mark.anyio
    async def test_run_browser_agent_llm_error(self, client: Client):
        """Should handle LLM initialization errors gracefully."""
        from mcp_server_browser_use.exceptions import LLMProviderError

        with patch("mcp_server_browser_use.server.get_llm", side_effect=LLMProviderError("API key missing")):
            result = await client.call_tool("run_browser_agent", {"task": "Test"})

            assert result.content is not None
            assert len(result.content) > 0
            assert "Error" in result.content[0].text or "API key" in result.content[0].text


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
            patch("mcp_server_browser_use.server.ResearchMachine", return_value=mock_machine),
        ):
            result = await client.call_tool("run_deep_research", {"topic": "AI safety"})

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
            patch("mcp_server_browser_use.server.ResearchMachine", return_value=mock_machine) as machine_class,
        ):
            await client.call_tool(
                "run_deep_research",
                {"topic": "Machine learning", "max_searches": 10, "save_to_file": "/tmp/report.md"},
            )

            # Verify ResearchMachine was called with correct args
            call_kwargs = machine_class.call_args[1]
            assert call_kwargs["topic"] == "Machine learning"
            assert call_kwargs["max_searches"] == 10
            assert call_kwargs["save_path"] == "/tmp/report.md"

    @pytest.mark.anyio
    async def test_run_deep_research_llm_error(self, client: Client):
        """Should handle LLM initialization errors gracefully."""
        from mcp_server_browser_use.exceptions import LLMProviderError

        with patch("mcp_server_browser_use.server.get_llm", side_effect=LLMProviderError("API key missing")):
            result = await client.call_tool("run_deep_research", {"topic": "Test topic"})

            assert result.content is not None
            assert len(result.content) > 0
            assert "Error" in result.content[0].text or "API key" in result.content[0].text

    @pytest.mark.anyio
    async def test_run_deep_research_default_max_searches(self, client: Client):
        """Should use default max_searches from settings when not specified."""
        mock_machine = MagicMock()
        mock_machine.run = AsyncMock(return_value="Report")

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.ResearchMachine", return_value=mock_machine) as machine_class,
        ):
            await client.call_tool("run_deep_research", {"topic": "Test"})

            # Should use settings.research.max_searches (default 5)
            call_kwargs = machine_class.call_args[1]
            assert call_kwargs["max_searches"] >= 1  # At least 1 search
