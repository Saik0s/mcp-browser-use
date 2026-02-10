"""Pytest configuration and fixtures for mcp-browser-use tests."""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring real API keys and browser")
    config.addinivalue_line("markers", "integration: Integration tests with mocked LLM but real browser automation")
    config.addinivalue_line("markers", "slow: Tests that take longer to run")


@pytest.fixture(autouse=True)
def _isolate_from_local_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # Developers may have ~/.config/mcp-server-browser-use/config.json set with
    # an external CDP URL. Force tests to use the built-in Playwright browser.
    monkeypatch.setenv("MCP_BROWSER_CDP_URL", "")
