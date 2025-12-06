# Modernize MCP Browser-Use

## What

- Update browser-use 0.1.41 → 0.10.1
- Delete all custom wrappers in `_internal/`
- Use browser-use's native LLM providers
- Remove LangChain ecosystem entirely
- Remove deep research feature

## Why

We're maintaining 3000+ lines of custom code that wraps functionality browser-use already provides natively. browser-use 0.10.1 ships with:
- Native `ChatOpenAI`, `ChatAnthropic`, `ChatGoogle`, `ChatMistral`, `ChatOllama`
- New `BrowserSession` replacing `BrowserContext`
- New `Tools` replacing `Controller`
- Fallback LLM support, flash mode, judgment features

## Target State

```
src/mcp_server_browser_use/
├── __init__.py
├── __main__.py
├── server.py (~120 lines)
├── config.py (~80 lines)
├── providers.py (~60 lines)
└── exceptions.py (~20 lines)

Total: ~280 lines (down from ~3200 = 91% reduction)
```

**Dependencies** (4 instead of 9+):
```toml
dependencies = [
    "browser-use>=0.10.1",
    "mcp>=1.10.1",
    "pydantic-settings>=2.0.0",
    "typer>=0.12.0",
]
```

---

## Phase 1: Delete + Update Dependencies

### Delete These Files

```bash
trash src/mcp_server_browser_use/_internal/
```

| File | LOC | Reason |
|------|-----|--------|
| `_internal/agent/deep_research/deep_research_agent.py` | 1015 | YAGNI - native Agent handles research tasks |
| `_internal/agent/browser_use/browser_use_agent.py` | 177 | Thin wrapper, use native Agent |
| `_internal/browser/custom_browser.py` | 130 | Deprecated API, use native Browser |
| `_internal/browser/custom_context.py` | 116 | Deprecated API, use BrowserSession |
| `_internal/controller/custom_controller.py` | 178 | Deprecated API, use Tools |
| `_internal/utils/llm_provider.py` | 327 | Use native Chat* models |
| `_internal/utils/mcp_client.py` | 267 | Unused meta-feature |
| `_internal/utils/*.py` | ~100 | Consolidate into main config |

### Update pyproject.toml

```toml
[project]
name = "mcp_server_browser_use"
version = "0.2.0"
requires-python = ">=3.11"

dependencies = [
    "browser-use>=0.10.1",
    "mcp>=1.10.1",
    "pydantic-settings>=2.0.0",
    "typer>=0.12.0",
]
```

---

## Phase 2: Rewrite Core Files

### exceptions.py (~20 lines)

```python
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
```

### providers.py (~60 lines)

```python
"""LLM provider factory using browser-use native providers."""

from typing import Literal

from browser_use import ChatOpenAI, ChatAnthropic, ChatGoogle, ChatOllama
from browser_use.llm.base import BaseChatModel

from .config import settings
from .exceptions import LLMProviderError

ProviderType = Literal["openai", "anthropic", "google", "ollama"]

def get_llm() -> BaseChatModel:
    """
    Create LLM instance from settings using browser-use native providers.

    Returns:
        Configured BaseChatModel instance

    Raises:
        LLMProviderError: If provider is unsupported or API key is missing
    """
    provider = settings.llm.provider
    model = settings.llm.model_name
    api_key = settings.llm.api_key

    if provider not in ("ollama",) and not api_key:
        raise LLMProviderError(
            f"API key required for provider '{provider}'. "
            f"Set MCP_LLM_API_KEY environment variable."
        )

    try:
        if provider == "openai":
            return ChatOpenAI(model=model, api_key=api_key)
        elif provider == "anthropic":
            return ChatAnthropic(model=model, api_key=api_key)
        elif provider == "google":
            return ChatGoogle(model=model, api_key=api_key)
        elif provider == "ollama":
            return ChatOllama(model=model)
        else:
            raise LLMProviderError(f"Unsupported provider: {provider}")
    except Exception as e:
        raise LLMProviderError(f"Failed to initialize {provider} LLM: {e}") from e
```

### config.py (~80 lines)

```python
"""Configuration management using Pydantic settings."""

from typing import Literal, Optional
from pydantic import SecretStr
from pydantic_settings import BaseSettings

class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    provider: Literal["openai", "anthropic", "google", "ollama"] = "anthropic"
    model_name: str = "claude-sonnet-4-20250514"
    api_key: Optional[SecretStr] = None

    model_config = {"env_prefix": "MCP_LLM_"}

    def get_api_key(self) -> Optional[str]:
        """Extract API key value from SecretStr."""
        return self.api_key.get_secret_value() if self.api_key else None

class BrowserSettings(BaseSettings):
    """Browser configuration."""

    headless: bool = True

    model_config = {"env_prefix": "MCP_BROWSER_"}

class AgentSettings(BaseSettings):
    """Agent behavior configuration."""

    max_steps: int = 20
    use_vision: bool = True

    model_config = {"env_prefix": "MCP_AGENT_"}

class ServerSettings(BaseSettings):
    """Server configuration."""

    logging_level: str = "INFO"

    model_config = {"env_prefix": "MCP_SERVER_"}

class AppSettings(BaseSettings):
    """Root application settings."""

    llm: LLMSettings = LLMSettings()
    browser: BrowserSettings = BrowserSettings()
    agent: AgentSettings = AgentSettings()
    server: ServerSettings = ServerSettings()

settings = AppSettings()
```

### server.py (~120 lines)

```python
"""MCP server exposing browser-use as tools."""

import logging
from typing import Optional

from browser_use import Agent, BrowserProfile
from mcp.server.fastmcp import Context, FastMCP

from .config import settings
from .providers import get_llm
from .exceptions import BrowserError, LLMProviderError

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.server.logging_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_server_browser_use")

def serve() -> FastMCP:
    """Create and configure MCP server."""

    server = FastMCP("mcp_server_browser_use")

    @server.tool()
    async def run_browser_agent(
        ctx: Context,
        task: str,
        max_steps: Optional[int] = None,
    ) -> str:
        """
        Execute a browser automation task using AI.

        Args:
            task: Natural language description of what to do in the browser
            max_steps: Maximum number of agent steps (default from settings)

        Returns:
            Result of the browser automation task
        """
        logger.info(f"Starting browser agent task: {task[:100]}...")

        try:
            llm = get_llm()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        profile = BrowserProfile(
            headless=settings.browser.headless,
        )

        steps = max_steps if max_steps is not None else settings.agent.max_steps

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
                use_vision=settings.agent.use_vision,
            )

            result = await agent.run()
            final = result.final_result() or "Task completed without explicit result."
            logger.info(f"Agent completed: {final[:100]}...")
            return final

        except Exception as e:
            logger.error(f"Browser agent failed: {e}")
            raise BrowserError(f"Browser automation failed: {e}") from e

    return server

server_instance = serve()

def main() -> None:
    """Entry point for MCP server."""
    logger.info(f"Starting MCP browser-use server (provider: {settings.llm.provider})")
    server_instance.run()

if __name__ == "__main__":
    main()
```

### cli.py (~50 lines)

```python
"""CLI interface for browser-use MCP server."""

import asyncio
import typer

from .server import run_browser_agent
from .config import settings

app = typer.Typer(help="Browser automation CLI powered by browser-use")

@app.command()
def run(
    task: str = typer.Argument(..., help="Task to execute in the browser"),
    max_steps: int = typer.Option(None, "--max-steps", "-m", help="Maximum agent steps"),
) -> None:
    """Execute a browser automation task."""

    async def _run() -> str:
        # Create a mock context for CLI usage
        return await run_browser_agent(None, task, max_steps)

    result = asyncio.run(_run())
    print(result)

@app.command()
def config() -> None:
    """Show current configuration."""
    print(f"Provider: {settings.llm.provider}")
    print(f"Model: {settings.llm.model_name}")
    print(f"Headless: {settings.browser.headless}")
    print(f"Max Steps: {settings.agent.max_steps}")
    print(f"Use Vision: {settings.agent.use_vision}")

if __name__ == "__main__":
    app()
```

---

## Features Removed

| Feature | Reason | Alternative |
|---------|--------|-------------|
| Deep research agent | 1015 lines for what native Agent does | Use detailed task prompts |
| keep_open mode | Adds state complexity | Fresh browser per request |
| CDP connection | Power user feature, unverified usage | File issue if needed |
| MCP client integration | Meta-feature, unused | File issue if needed |
| IBM Watson support | Requires LangChain | File issue if needed |
| 8+ LLM providers | Maintenance burden | 4 core providers (OpenAI, Anthropic, Google, Ollama) |
| Recording/tracing | Browser-use handles internally | Use browser-use native features |
| Agent history saving | Over-engineering | Log to stdout if needed |

---

## Error Handling Strategy

1. **LLM initialization failures** → `LLMProviderError` with actionable message
2. **Browser failures** → `BrowserError` wrapping underlying exception
3. **Missing API keys** → Clear error message with env var name
4. **Agent runtime errors** → Logged + re-raised as `BrowserError`

All errors include:
- What failed
- Why it failed (if known)
- How to fix it (env var to set, config to change)

---

## Testing Strategy

### Unit Tests

```python
# tests/test_providers.py
import pytest
from mcp_server_browser_use.providers import get_llm
from mcp_server_browser_use.exceptions import LLMProviderError

def test_get_llm_missing_api_key(monkeypatch):
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.delenv("MCP_LLM_API_KEY", raising=False)

    with pytest.raises(LLMProviderError, match="API key required"):
        get_llm()

def test_get_llm_unsupported_provider(monkeypatch):
    monkeypatch.setenv("MCP_LLM_PROVIDER", "invalid")

    with pytest.raises(LLMProviderError, match="Unsupported provider"):
        get_llm()
```

### Integration Tests

```python
# tests/test_server.py
import pytest
from mcp_server_browser_use.server import run_browser_agent

@pytest.mark.asyncio
async def test_run_browser_agent_basic(monkeypatch):
    monkeypatch.setenv("MCP_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MCP_LLM_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # This will fail without valid API key, but tests the flow
    result = await run_browser_agent(None, "Navigate to example.com", 1)
    assert isinstance(result, str)
```

### Manual Test Checklist

- [ ] `MCP_LLM_PROVIDER=anthropic MCP_LLM_API_KEY=xxx mcp-server-browser-use` starts
- [ ] Claude Desktop can call `run_browser_agent` tool
- [ ] Browser opens in headed mode when `MCP_BROWSER_HEADLESS=false`
- [ ] Agent completes simple task (e.g., "Go to google.com and search for 'hello'")
- [ ] CLI `mcp-browser-cli run "Navigate to example.com"` works

---

## Migration for Existing Users

### Environment Variables

| Old | New | Notes |
|-----|-----|-------|
| `MCP_LLM_PROVIDER` | Same | Now only: openai, anthropic, google, ollama |
| `MCP_LLM_MODEL_NAME` | Same | |
| `MCP_LLM_*_API_KEY` | `MCP_LLM_API_KEY` | Single key, not per-provider |
| `MCP_BROWSER_HEADLESS` | Same | |
| `MCP_BROWSER_KEEP_OPEN` | REMOVED | Each request gets fresh browser |
| `MCP_BROWSER_CDP_URL` | REMOVED | File issue if needed |
| `MCP_RESEARCH_*` | REMOVED | Use native agent with detailed prompts |

### Breaking Changes

1. **Deep research tool removed** - Use `run_browser_agent` with detailed task prompts
2. **CDP connection removed** - File issue if you need this
3. **keep_open mode removed** - Each MCP call gets fresh browser session
4. **LLM providers reduced** - Only OpenAI, Anthropic, Google, Ollama supported

---

## Acceptance Criteria

- [ ] `run_browser_agent` tool works via MCP
- [ ] 4 LLM providers work (OpenAI, Anthropic, Google, Ollama)
- [ ] CLI `mcp-browser-cli run "task"` works
- [ ] `uv run ruff check .` passes
- [ ] `uv run pyright` passes
- [ ] Total codebase < 300 lines

---

## References

### Internal
- Current implementation: `src/mcp_server_browser_use/server.py`
- Current config: `src/mcp_server_browser_use/config.py`

### External
- browser-use 0.10.1: `/Users/igortarasenko/Projects/browser-use`
- browser-use Agent: `browser_use/agent/service.py`
- browser-use native LLMs: `browser_use/__init__.py`
