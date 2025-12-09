"""MCP server exposing browser-use as tools with native background task support."""

import logging
from typing import TYPE_CHECKING, Optional

from browser_use import Agent, BrowserProfile
from browser_use.browser.profile import ProxySettings

if TYPE_CHECKING:
    from browser_use.agent.views import AgentOutput
    from browser_use.browser.views import BrowserStateSummary
from fastmcp import FastMCP, TaskConfig
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm
from .research.machine import ResearchMachine

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.server.logging_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_server_browser_use")


def serve() -> FastMCP:
    """Create and configure MCP server with background task support."""
    server = FastMCP("mcp_server_browser_use")

    def _get_llm_and_profile():
        """Helper to get LLM instance and browser profile."""
        llm = get_llm(
            provider=settings.llm.provider,
            model=settings.llm.model_name,
            api_key=settings.llm.get_api_key_for_provider(),
            base_url=settings.llm.base_url,
            azure_endpoint=settings.llm.azure_endpoint,
            azure_api_version=settings.llm.azure_api_version,
            aws_region=settings.llm.aws_region,
        )
        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(server=settings.browser.proxy_server, bypass=settings.browser.proxy_bypass)
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
        return llm, profile

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_browser_agent(
        task: str,
        max_steps: Optional[int] = None,
        ctx: Context = CurrentContext(),  # noqa: B008
        progress: Progress = Progress(),  # noqa: B008
    ) -> str:
        """
        Execute a browser automation task using AI.

        Supports background execution with progress tracking when client requests it.

        Args:
            task: Natural language description of what to do in the browser
            max_steps: Maximum number of agent steps (default from settings)

        Returns:
            Result of the browser automation task
        """
        await ctx.info(f"Starting: {task}")
        logger.info(f"Starting browser agent task: {task[:100]}...")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        steps = max_steps if max_steps is not None else settings.agent.max_steps
        await progress.set_total(steps)

        # Track page changes only (not every step)
        last_url: str | None = None

        async def step_callback(
            state: "BrowserStateSummary",
            output: "AgentOutput",
            step_num: int,
        ) -> None:
            nonlocal last_url
            if state.url != last_url:
                await ctx.info(f"→ {state.title or state.url}")
                last_url = state.url
            await progress.increment()

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
                register_new_step_callback=step_callback,
            )

            result = await agent.run()
            final = result.final_result() or "Task completed without explicit result."

            await ctx.info(f"Completed: {final[:100]}")
            logger.info(f"Agent completed: {final[:100]}...")
            return final

        except Exception as e:
            logger.error(f"Browser agent failed: {e}")
            raise BrowserError(f"Browser automation failed: {e}") from e

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_deep_research(
        topic: str,
        max_searches: Optional[int] = None,
        save_to_file: Optional[str] = None,
        ctx: Context = CurrentContext(),  # noqa: B008
        progress: Progress = Progress(),  # noqa: B008
    ) -> str:
        """
        Execute deep research on a topic with progress tracking.

        Runs as a background task if client requests it, otherwise synchronous.
        Progress updates are streamed via the MCP task protocol.

        Args:
            topic: The research topic or question to investigate
            max_searches: Maximum number of web searches (default from settings)
            save_to_file: Optional file path to save the report

        Returns:
            The research report as markdown
        """
        logger.info(f"Starting deep research on: {topic}")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        searches = max_searches if max_searches is not None else settings.research.max_searches
        save_path = save_to_file or (
            f"{settings.research.save_directory}/{topic[:50].replace(' ', '_')}.md" if settings.research.save_directory else None
        )

        # Execute research with progress tracking
        machine = ResearchMachine(
            topic=topic,
            max_searches=searches,
            save_path=save_path,
            llm=llm,
            browser_profile=profile,
            progress=progress,
            ctx=ctx,
        )

        report = await machine.run()
        return report

    return server


server_instance = serve()


def main() -> None:
    """Entry point for MCP server."""
    transport = settings.server.transport
    logger.info(f"Starting MCP browser-use server (provider: {settings.llm.provider}, transport: {transport})")

    if transport == "stdio":
        server_instance.run()
    elif transport in ("streamable-http", "sse"):
        logger.info(f"HTTP server at http://{settings.server.host}:{settings.server.port}/mcp")
        server_instance.run(transport=transport, host=settings.server.host, port=settings.server.port)
    else:
        raise ValueError(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()
