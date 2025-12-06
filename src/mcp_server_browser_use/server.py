"""MCP server exposing browser-use as tools."""

import logging
from typing import Optional

from browser_use import Agent, BrowserProfile
from browser_use.browser.profile import ProxySettings
from mcp.server.fastmcp import Context, FastMCP

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm

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
            llm = get_llm(
                provider=settings.llm.provider,
                model=settings.llm.model_name,
                api_key=settings.llm.get_api_key(),
                base_url=settings.llm.base_url,
            )
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(server=settings.browser.proxy_server, bypass=settings.browser.proxy_bypass)
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
        steps = max_steps if max_steps is not None else settings.agent.max_steps

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
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
