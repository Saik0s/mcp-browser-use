"""Custom exceptions for MCP browser-use server."""


class MCPBrowserUseError(Exception):
    """Base exception for MCP browser-use errors."""

    pass


class LLMProviderError(MCPBrowserUseError):
    """Raised when LLM provider configuration is invalid."""

    pass


class BrowserError(MCPBrowserUseError):
    """Raised when browser operations fail."""

    pass
