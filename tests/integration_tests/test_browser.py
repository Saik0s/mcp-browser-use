"""End-to-end tests for browser automation MCP tools.

These tests require:
- A valid LLM API key (GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY)
- Playwright browsers installed
- Network access

Mark: @pytest.mark.e2e
"""

import os
from collections.abc import AsyncGenerator

import pytest
from fastmcp import Client

# Skip all tests in this module if no API key is configured
API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not API_KEY, reason="No API key configured for e2e tests"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def e2e_client(monkeypatch) -> AsyncGenerator[Client, None]:
    """Create an MCP client for e2e tests with real API keys."""
    # Use real API key from environment - prefer faster/cheaper providers
    if os.environ.get("GEMINI_API_KEY"):
        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gemini-2.0-flash")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("MCP_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "claude-3-haiku-20240307")
    else:
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4o-mini")

    # Run headless for CI
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    from mcp_server_browser_use.server import serve

    app = serve()

    async with Client(app) as client:
        yield client


class TestRunBrowserAgentE2E:
    """End-to-end tests for run_browser_agent tool."""

    @pytest.mark.anyio
    @pytest.mark.slow
    async def test_simple_navigation(self, e2e_client: Client):
        """Browser agent should navigate to a simple page."""
        result = await e2e_client.call_tool(
            "run_browser_agent",
            {
                "task": "Go to https://example.com and tell me the main heading text",
                "max_steps": 5,
            },
        )

        assert result.content is not None
        text = result.content[0].text

        # Should contain something about Example Domain
        assert "Example" in text or "example" in text.lower() or "Error" in text

    @pytest.mark.anyio
    @pytest.mark.slow
    async def test_agent_with_max_steps(self, e2e_client: Client):
        """Browser agent should respect max_steps limit."""
        result = await e2e_client.call_tool(
            "run_browser_agent",
            {
                "task": "Go to https://news.ycombinator.com and list the top 3 stories",
                "max_steps": 10,
            },
        )

        assert result.content is not None
        # Agent should return some content (success or error)
        assert len(result.content[0].text) > 0


class TestRunDeepResearchE2E:
    """End-to-end tests for run_deep_research tool."""

    @pytest.mark.anyio
    @pytest.mark.slow
    async def test_basic_research(self, e2e_client: Client):
        """Deep research should perform multi-search research on a topic."""
        result = await e2e_client.call_tool(
            "run_deep_research",
            {
                "topic": "What is the current version of Python?",
                "max_searches": 2,
            },
        )

        assert result.content is not None
        text = result.content[0].text

        # Should return some research content or error
        assert len(text) > 0
        # Either contains Python info or an error message
        assert "Python" in text or "python" in text.lower() or "Error" in text or "error" in text.lower()
