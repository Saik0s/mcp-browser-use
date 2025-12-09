"""Pytest configuration and fixtures for mcp-browser-use tests."""


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring real API keys and browser")
    config.addinivalue_line("markers", "integration: Integration tests with mocked LLM but real browser automation")
    config.addinivalue_line("markers", "slow: Tests that take longer to run")
