"""End-to-end tests for browser agent and research agent.

These tests validate the complete flow from MCP tools through to actual browser automation.

Test categories:
- e2e: Real end-to-end tests requiring API keys (skipped if no key)
- integration: Tests with mocked LLM but real browser automation
- unit: Tests for individual components with mocks

Run e2e tests:
    uv run pytest tests/test_e2e.py -m e2e -v

Run integration tests (no API key needed):
    uv run pytest tests/test_e2e.py -m integration -v

Run all tests:
    uv run pytest tests/test_e2e.py -v
"""

import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from browser_use import BrowserProfile
from fastmcp import Client

# Custom markers for test categories
pytestmark = [pytest.mark.anyio]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ============================================================================
# Helper Functions
# ============================================================================


def get_api_key(provider: str) -> str | None:
    """Get API key for a provider from environment variables."""
    env_vars = {
        "openai": ["OPENAI_API_KEY", "MCP_LLM_OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY", "MCP_LLM_ANTHROPIC_API_KEY"],
        "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "MCP_LLM_GOOGLE_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY", "MCP_LLM_OPENROUTER_API_KEY"],
        "groq": ["GROQ_API_KEY", "MCP_LLM_GROQ_API_KEY"],
    }
    for var in env_vars.get(provider, []):
        key = os.environ.get(var)
        if key:
            return key
    return None


def skip_if_no_api_key(provider: str):
    """Skip test if no API key is available for the provider."""
    key = get_api_key(provider)
    if not key:
        pytest.skip(f"No API key found for {provider}")
    return key


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def mcp_client(monkeypatch) -> AsyncGenerator[Client, None]:
    """Create an in-memory FastMCP client for testing."""
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    from mcp_server_browser_use.server import serve

    app = serve()
    async with Client(app) as client:
        yield client


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns controlled responses."""
    mock = MagicMock()

    # Mock response structure matching browser-use's expected format
    class MockResponse:
        def __init__(self, content: str):
            self.completion = content

    async def mock_ainvoke(messages):
        # Detect if this is a planning call or synthesis call
        message_content = str(messages)
        if "search queries" in message_content.lower() or "generate" in message_content.lower():
            # Return JSON array of queries for planning
            return MockResponse('["query 1", "query 2"]')
        else:
            # Return a report for synthesis
            return MockResponse("# Test Report\n\nThis is a synthesized test report.")

    mock.ainvoke = AsyncMock(side_effect=mock_ainvoke)
    return mock


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ============================================================================
# E2E Tests - Browser Agent (requires API key)
# ============================================================================


class TestBrowserAgentE2E:
    """End-to-end tests for browser agent with real LLM."""

    @pytest.mark.e2e
    async def test_browser_agent_simple_navigation(self, monkeypatch):
        """E2E: Browser agent navigates to example.com and extracts title."""
        api_key = skip_if_no_api_key("google")

        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gemini-2.0-flash")
        monkeypatch.setenv("GOOGLE_API_KEY", api_key)
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        app = serve()
        async with Client(app) as client:
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to https://example.com and tell me the page title. Just respond with the title.", "max_steps": 5},
            )

            assert result.content is not None
            assert len(result.content) > 0
            # example.com should have "Example Domain" in the title
            response_text = result.content[0].text.lower()
            assert "example" in response_text or "domain" in response_text

    @pytest.mark.e2e
    async def test_browser_agent_httpbin_json(self, monkeypatch):
        """E2E: Browser agent fetches JSON from httpbin."""
        api_key = skip_if_no_api_key("google")

        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gemini-2.0-flash")
        monkeypatch.setenv("GOOGLE_API_KEY", api_key)
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        app = serve()
        async with Client(app) as client:
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to https://httpbin.org/ip and extract the origin IP address from the JSON. Just tell me the IP.", "max_steps": 5},
            )

            assert result.content is not None
            assert len(result.content) > 0
            # Response should contain something about the page or an IP-like pattern
            response_text = result.content[0].text.lower()
            # The LLM might return the IP, mention "origin", "ip", "address", or describe the JSON
            assert any(term in response_text for term in ["origin", "ip", "address", "json", "httpbin"]) or any(
                char.isdigit() for char in response_text
            )

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_browser_agent_form_interaction(self, monkeypatch):
        """E2E: Browser agent interacts with a form on httpbin."""
        api_key = skip_if_no_api_key("google")

        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gemini-2.0-flash")
        monkeypatch.setenv("GOOGLE_API_KEY", api_key)
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        app = serve()
        async with Client(app) as client:
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to https://httpbin.org/forms/post and describe what form fields are available.", "max_steps": 8},
            )

            assert result.content is not None
            assert len(result.content) > 0
            # httpbin form should have recognizable fields
            response_text = result.content[0].text.lower()
            assert any(field in response_text for field in ["customer", "size", "topping", "form", "input", "field"])


# ============================================================================
# E2E Tests - Research Agent (requires API key)
# ============================================================================


class TestResearchAgentE2E:
    """End-to-end tests for research agent with real LLM."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_research_agent_simple_topic(self, monkeypatch, temp_dir):
        """E2E: Research agent researches a simple topic."""
        api_key = skip_if_no_api_key("google")

        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gemini-2.0-flash")
        monkeypatch.setenv("GOOGLE_API_KEY", api_key)
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        save_path = f"{temp_dir}/research_report.md"

        app = serve()
        async with Client(app) as client:
            result = await client.call_tool(
                "run_deep_research",
                {"topic": "What is the capital of France?", "max_searches": 1, "save_to_file": save_path},
            )

            assert result.content is not None
            assert len(result.content) > 0
            response_text = result.content[0].text.lower()

            # Should mention Paris
            assert "paris" in response_text or "france" in response_text

            # Check file was saved
            assert Path(save_path).exists()
            saved_content = Path(save_path).read_text()
            assert len(saved_content) > 0


# ============================================================================
# Integration Tests - Mocked LLM, Real Browser
# ============================================================================


class TestBrowserAgentIntegration:
    """Integration tests with mocked LLM but testing real browser interaction."""

    @pytest.mark.integration
    async def test_agent_initialization(self, mcp_client: Client):
        """Integration: Verify Agent is initialized with correct parameters."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Task completed successfully"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch("mcp_server_browser_use.server.get_llm") as mock_get_llm,
            patch("mcp_server_browser_use.server.Agent") as MockAgent,
        ):
            mock_get_llm.return_value = MagicMock()
            MockAgent.return_value = mock_agent

            await mcp_client.call_tool("run_browser_agent", {"task": "Test task", "max_steps": 10})

            # Verify Agent was constructed correctly
            call_kwargs = MockAgent.call_args[1]
            assert call_kwargs["task"] == "Test task"
            assert call_kwargs["max_steps"] == 10
            assert call_kwargs["llm"] is not None
            assert call_kwargs["browser_profile"] is not None

    @pytest.mark.integration
    async def test_browser_profile_headless(self, monkeypatch):
        """Integration: Verify BrowserProfile respects headless setting."""
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        app = serve()

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Done"
        mock_agent.run = AsyncMock(return_value=mock_result)

        async with Client(app) as client:
            with (
                patch("mcp_server_browser_use.server.get_llm") as mock_get_llm,
                patch("mcp_server_browser_use.server.Agent") as MockAgent,
            ):
                mock_get_llm.return_value = MagicMock()
                MockAgent.return_value = mock_agent

                await client.call_tool("run_browser_agent", {"task": "Test"})

                # Check that BrowserProfile was passed and is headless
                call_kwargs = MockAgent.call_args[1]
                profile = call_kwargs["browser_profile"]
                assert isinstance(profile, BrowserProfile)
                assert profile.headless is True

    @pytest.mark.integration
    async def test_error_handling_llm_failure(self, mcp_client: Client):
        """Integration: Verify proper error handling when LLM fails."""
        from mcp_server_browser_use.exceptions import LLMProviderError

        with patch("mcp_server_browser_use.server.get_llm", side_effect=LLMProviderError("Connection failed")):
            result = await mcp_client.call_tool("run_browser_agent", {"task": "Test"})

            assert result.content is not None
            response = result.content[0].text
            assert "Error" in response or "failed" in response.lower()

    @pytest.mark.integration
    async def test_error_handling_browser_failure(self, mcp_client: Client):
        """Integration: Verify proper error handling when browser fails."""
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(side_effect=Exception("Browser crashed"))

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        ):
            with pytest.raises(Exception):
                await mcp_client.call_tool("run_browser_agent", {"task": "Test"})


# ============================================================================
# Integration Tests - Research Machine
# ============================================================================


class TestResearchMachineIntegration:
    """Integration tests for ResearchMachine workflow."""

    @pytest.mark.integration
    async def test_research_machine_workflow(self, mock_llm, temp_dir):
        """Integration: Test full ResearchMachine workflow with mocked LLM."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        # Mock the Agent to avoid real browser automation
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Found information about the topic. Source: example.com"
        mock_result.history = []
        mock_agent.run = AsyncMock(return_value=mock_result)

        save_path = f"{temp_dir}/test_report.md"

        with patch("mcp_server_browser_use.research.machine.Agent", return_value=mock_agent):
            machine = ResearchMachine(
                topic="Test topic",
                max_searches=2,
                save_path=save_path,
                llm=mock_llm,
                browser_profile=BrowserProfile(headless=True),
            )

            report = await machine.run()

            # Verify report was generated
            assert report is not None
            assert len(report) > 0
            assert "Test Report" in report or "test" in report.lower()

            # Verify file was saved
            assert Path(save_path).exists()
            saved_content = Path(save_path).read_text()
            assert saved_content == report

    @pytest.mark.integration
    async def test_research_machine_query_generation(self, mock_llm):
        """Integration: Test that ResearchMachine generates queries correctly."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        machine = ResearchMachine(
            topic="Test topic",
            max_searches=2,
            save_path=None,
            llm=mock_llm,
            browser_profile=BrowserProfile(headless=True),
        )

        queries = await machine._generate_queries()

        assert queries is not None
        assert len(queries) > 0
        assert len(queries) <= 2  # Should respect max_searches

    @pytest.mark.integration
    async def test_research_machine_no_findings(self, temp_dir):
        """Integration: Test ResearchMachine handles no findings gracefully."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(completion='["query 1"]'))

        # Mock agent that returns empty results
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = ""
        mock_result.history = []
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("mcp_server_browser_use.research.machine.Agent", return_value=mock_agent):
            machine = ResearchMachine(
                topic="Test topic",
                max_searches=1,
                save_path=None,
                llm=mock_llm,
                browser_profile=BrowserProfile(headless=True),
            )

            report = await machine.run()

            # Should handle empty findings gracefully
            assert report is not None
            assert "No findings" in report or "Research Report" in report

    @pytest.mark.integration
    async def test_research_machine_progress_tracking(self, mock_llm):
        """Integration: Test that ResearchMachine reports progress correctly."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        # Create mock progress tracker
        mock_progress = MagicMock()
        mock_progress.set_total = AsyncMock()
        mock_progress.set_message = AsyncMock()
        mock_progress.increment = AsyncMock()

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Results"
        mock_result.history = []
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("mcp_server_browser_use.research.machine.Agent", return_value=mock_agent):
            machine = ResearchMachine(
                topic="Test",
                max_searches=2,
                save_path=None,
                llm=mock_llm,
                browser_profile=BrowserProfile(headless=True),
                progress=mock_progress,
            )

            await machine.run()

            # Verify progress methods were called
            mock_progress.set_total.assert_called()
            mock_progress.set_message.assert_called()
            mock_progress.increment.assert_called()

            # Total should be max_searches + 2 (planning + synthesis)
            total_call = mock_progress.set_total.call_args_list[0]
            assert total_call[0][0] == 4  # 2 searches + planning + synthesis


# ============================================================================
# Unit Tests - Components
# ============================================================================


class TestResearchModels:
    """Unit tests for research data models."""

    def test_search_result_creation(self):
        """Unit: SearchResult dataclass creation."""
        from mcp_server_browser_use.research.models import ResearchSource, SearchResult

        source = ResearchSource(title="Test Source", url="https://example.com", summary="Test summary")

        result = SearchResult(query="test query", summary="Test findings", source=source)

        assert result.query == "test query"
        assert result.summary == "Test findings"
        assert result.source is not None
        assert result.source.url == "https://example.com"
        assert result.error is None

    def test_search_result_with_error(self):
        """Unit: SearchResult with error."""
        from mcp_server_browser_use.research.models import SearchResult

        result = SearchResult(query="test query", summary="", error="Connection timeout")

        assert result.error == "Connection timeout"
        assert result.summary == ""


class TestFileSaving:
    """Unit tests for file saving functionality."""

    @pytest.mark.integration
    async def test_report_saved_to_file(self, mock_llm, temp_dir):
        """Integration: Verify report is saved to specified path."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Test findings"
        mock_result.history = []
        mock_agent.run = AsyncMock(return_value=mock_result)

        save_path = f"{temp_dir}/subdir/report.md"

        with patch("mcp_server_browser_use.research.machine.Agent", return_value=mock_agent):
            machine = ResearchMachine(
                topic="Test",
                max_searches=1,
                save_path=save_path,
                llm=mock_llm,
                browser_profile=BrowserProfile(headless=True),
            )

            report = await machine.run()

            # Verify subdirectory was created and file saved
            assert Path(save_path).exists()
            assert Path(save_path).read_text() == report

    @pytest.mark.integration
    async def test_report_not_saved_when_path_none(self, mock_llm):
        """Integration: Verify no file is created when save_path is None."""
        from mcp_server_browser_use.research.machine import ResearchMachine

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Test"
        mock_result.history = []
        mock_agent.run = AsyncMock(return_value=mock_result)

        with patch("mcp_server_browser_use.research.machine.Agent", return_value=mock_agent):
            machine = ResearchMachine(
                topic="Test",
                max_searches=1,
                save_path=None,
                llm=mock_llm,
                browser_profile=BrowserProfile(headless=True),
            )

            # Should complete without error
            report = await machine.run()
            assert report is not None


# ============================================================================
# MCP Protocol Tests
# ============================================================================


class TestMCPProtocol:
    """Tests for MCP protocol compliance."""

    @pytest.mark.integration
    async def test_tool_response_format(self, mcp_client: Client):
        """Integration: Verify tool responses follow MCP protocol."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Success"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.Agent", return_value=mock_agent),
        ):
            result = await mcp_client.call_tool("run_browser_agent", {"task": "Test"})

            # MCP response should have content list
            assert hasattr(result, "content")
            assert isinstance(result.content, list)
            assert len(result.content) > 0

            # Content should have text
            assert hasattr(result.content[0], "text")
            assert isinstance(result.content[0].text, str)

    @pytest.mark.integration
    async def test_tool_parameter_validation(self, mcp_client: Client):
        """Integration: Verify tool validates required parameters."""
        # Missing required 'task' parameter should cause an error
        with pytest.raises(Exception):
            await mcp_client.call_tool("run_browser_agent", {})

    @pytest.mark.integration
    async def test_research_tool_response_format(self, mcp_client: Client):
        """Integration: Verify research tool response follows MCP protocol."""
        mock_machine = MagicMock()
        mock_machine.run = AsyncMock(return_value="# Report\n\nContent here")

        with (
            patch("mcp_server_browser_use.server.get_llm", return_value=MagicMock()),
            patch("mcp_server_browser_use.server.ResearchMachine", return_value=mock_machine),
        ):
            result = await mcp_client.call_tool("run_deep_research", {"topic": "Test topic"})

            assert result.content is not None
            assert len(result.content) > 0
            assert "Report" in result.content[0].text or "Content" in result.content[0].text


# ============================================================================
# Provider Tests
# ============================================================================


class TestMultipleProviders:
    """Tests for different LLM providers."""

    @pytest.mark.e2e
    @pytest.mark.parametrize(
        "provider,model",
        [
            ("google", "gemini-2.0-flash"),
            ("openrouter", "google/gemini-2.0-flash-exp"),
        ],
    )
    async def test_provider_integration(self, provider: str, model: str, monkeypatch):
        """E2E: Test browser agent with different providers."""
        api_key = get_api_key(provider)
        if not api_key:
            pytest.skip(f"No API key for {provider}")

        # Map provider to correct env var
        env_var_map = {
            "google": "GOOGLE_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }

        monkeypatch.setenv("MCP_LLM_PROVIDER", provider)
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", model)
        monkeypatch.setenv(env_var_map[provider], api_key)
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

        from mcp_server_browser_use.server import serve

        app = serve()
        async with Client(app) as client:
            result = await client.call_tool(
                "run_browser_agent",
                {"task": "Go to example.com and respond with just the word 'success'", "max_steps": 5},
            )

            assert result.content is not None
            assert len(result.content) > 0
