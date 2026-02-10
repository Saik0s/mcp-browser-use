"""MCP server for browser-use.

Import-time must be safe even if the on-disk config file is broken. The CLI entrypoint
(`mcp_server_browser_use.cli:app`) imports this package first, so avoid importing the
server or touching strict settings at module import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .exceptions import BrowserError, LLMProviderError, MCPBrowserUseError

__all__ = ["BrowserError", "LLMProviderError", "MCPBrowserUseError", "get_llm", "main", "serve", "settings"]

if TYPE_CHECKING:
    from .config import AppSettings
    from browser_use.llm.base import BaseChatModel
    from fastmcp import FastMCP

    settings: AppSettings


def get_llm(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: object,
) -> BaseChatModel:
    from .providers import get_llm as _get_llm

    return _get_llm(provider=provider, model=model, api_key=api_key, base_url=base_url, **kwargs)


def serve() -> FastMCP:
    from .server import serve as _serve

    return _serve()


def main() -> None:
    from .server import main as _main

    _main()


def __getattr__(name: str) -> object:
    if name == "settings":
        from .config import settings as _settings

        return _settings
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(__all__)
