"""MCP server exposing browser-use as tools."""

import logging
from typing import Optional

from browser_use import Agent, BrowserProfile
from browser_use.browser.profile import ProxySettings
from mcp.server.fastmcp import Context, FastMCP

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm
from .research import ResearchState, cancel_task, create_task, get_task, start_task

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

    # Helper function to get LLM and browser profile
    def _get_llm_and_profile():
        llm = get_llm(
            provider=settings.llm.provider,
            model=settings.llm.model_name,
            api_key=settings.llm.get_api_key(),
            base_url=settings.llm.base_url,
        )
        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(server=settings.browser.proxy_server, bypass=settings.browser.proxy_bypass)
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
        return llm, profile

    @server.tool()
    async def start_deep_research(
        ctx: Context,
        topic: str,
        max_searches: Optional[int] = None,
        save_to_file: Optional[str] = None,
    ) -> dict:
        """
        Start a background deep research task on a topic.

        The research runs asynchronously. Use get_research_status to monitor progress
        and get_research_result to retrieve the final report.

        Args:
            topic: The research topic or question to investigate
            max_searches: Maximum number of web searches (default from settings)
            save_to_file: Optional file path to save the report

        Returns:
            Dict with task_id and status
        """
        logger.info(f"Starting deep research on: {topic}")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            return {"error": str(e)}

        searches = max_searches if max_searches is not None else settings.research.max_searches
        save_path = save_to_file or (
            f"{settings.research.save_directory}/{topic[:50].replace(' ', '_')}.md" if settings.research.save_directory else None
        )

        task = create_task(topic=topic, max_searches=searches, save_path=save_path)
        await start_task(task, llm, profile)

        return {
            "task_id": task.id,
            "status": "started",
            "topic": topic,
            "message": f"Research started. Use get_research_status('{task.id}') to check progress.",
        }

    @server.tool()
    async def get_research_status(ctx: Context, task_id: str) -> dict:
        """
        Check the status of a running research task.

        Args:
            task_id: The ID returned by start_deep_research

        Returns:
            Dict with task status, progress, and partial results
        """
        task = get_task(task_id)
        if not task:
            return {"error": f"Task '{task_id}' not found"}

        return task.to_status_dict()

    @server.tool()
    async def get_research_result(ctx: Context, task_id: str) -> dict:
        """
        Get the final result of a completed research task.

        Args:
            task_id: The ID returned by start_deep_research

        Returns:
            Dict with the research report, sources, and metadata
        """
        task = get_task(task_id)
        if not task:
            return {"error": f"Task '{task_id}' not found"}

        if task.state not in (ResearchState.COMPLETED, ResearchState.FAILED, ResearchState.CANCELLED):
            return {
                "error": f"Task not finished. Current state: {task.state.value}",
                "status": task.to_status_dict(),
            }

        return task.to_result_dict()

    @server.tool()
    async def cancel_deep_research(ctx: Context, task_id: str) -> dict:
        """
        Cancel a running research task.

        Args:
            task_id: The ID returned by start_deep_research

        Returns:
            Dict confirming cancellation
        """
        task = get_task(task_id)
        if not task:
            return {"error": f"Task '{task_id}' not found"}

        if task.state in (ResearchState.COMPLETED, ResearchState.FAILED, ResearchState.CANCELLED):
            return {"error": f"Task already finished with state: {task.state.value}"}

        await cancel_task(task_id)
        return {"task_id": task_id, "status": "cancellation_requested"}

    return server


server_instance = serve()


def main() -> None:
    """Entry point for MCP server."""
    logger.info(f"Starting MCP browser-use server (provider: {settings.llm.provider})")
    server_instance.run()


if __name__ == "__main__":
    main()
