"""Shared fixtures for integration tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastmcp import Client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def temp_skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory for test isolation."""
    skills_dir = tmp_path / "browser-skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path for test isolation."""
    return tmp_path / "test_tasks.db"


@pytest.fixture
async def mcp_client(monkeypatch, temp_skills_dir: Path, temp_db: Path) -> AsyncGenerator[Client, None]:
    """Create an in-memory FastMCP client with isolated storage.

    This fixture:
    - Sets up test environment variables
    - Uses temporary directories for skills and task DB
    - Yields a connected client for testing MCP tools
    """
    # Configure test environment
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("MCP_SKILLS_ENABLED", "true")  # Enable skills for testing
    monkeypatch.setenv("MCP_SKILLS_DIRECTORY", str(temp_skills_dir))

    # Reload config module to pick up new env vars, then reload server
    import importlib

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    import mcp_server_browser_use.server

    importlib.reload(mcp_server_browser_use.server)

    from mcp_server_browser_use.server import serve

    app = serve()

    async with Client(app) as client:
        yield client
