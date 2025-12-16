"""MCP server exposing browser-use as tools with native background task support."""

import logging
import os
import sys
from typing import TYPE_CHECKING, Optional


def _configure_stdio_logging() -> None:
    """Configure logging for stdio MCP mode - all logs MUST go to stderr.

    In stdio mode, stdout is reserved exclusively for JSON-RPC messages.
    Any logging or print() to stdout corrupts the protocol stream.
    """
    # Suppress noisy loggers from dependencies BEFORE they're imported
    os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")

    # Force all logging to stderr
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    # Configure root logger
    root = logging.getLogger()
    root.handlers = [stderr_handler]
    root.setLevel(logging.WARNING)

    # Suppress verbose loggers from dependencies
    for logger_name in [
        "httpx",
        "httpcore",
        "urllib3",
        "asyncio",
        "playwright",
        "browser_use",
        "langchain",
        "langchain_core",
        "openai",
        "anthropic",
    ]:
        dep_logger = logging.getLogger(logger_name)
        dep_logger.setLevel(logging.WARNING)
        dep_logger.handlers = [stderr_handler]
        dep_logger.propagate = False


# Configure logging BEFORE importing browser_use and other noisy dependencies
_configure_stdio_logging()

# ruff: noqa: E402 - Intentional late imports after logging configuration
from browser_use import Agent, BrowserProfile
from browser_use.browser.profile import ProxySettings
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext, Progress
from fastmcp.server.context import Context
from fastmcp.server.server import TaskConfig

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm
from .research.machine import ResearchMachine
from .skills import SkillAnalyzer, SkillExecutor, SkillRecorder, SkillStore
from .utils import save_execution_result

if TYPE_CHECKING:
    from browser_use.agent.views import AgentOutput
    from browser_use.browser.views import BrowserStateSummary

# Apply configured log level (may override the default WARNING)
logger = logging.getLogger("mcp_server_browser_use")
logger.setLevel(getattr(logging, settings.server.logging_level.upper()))


def serve() -> FastMCP:
    """Create and configure MCP server with background task support."""
    server = FastMCP("mcp_server_browser_use")

    # Initialize skill components
    skill_store = SkillStore(directory=settings.skills.directory)
    skill_executor = SkillExecutor()

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
        skill_name: Optional[str] = None,
        skill_params: Optional[str] = None,
        learn: bool = False,
        save_skill_as: Optional[str] = None,
        ctx: Context = CurrentContext(),  # noqa: B008
        progress: Progress = Progress(),  # noqa: B008
    ) -> str:
        """
        Execute a browser automation task using AI.

        Supports background execution with progress tracking when client requests it.

        EXECUTION MODE (default):
        - When skill_name is provided, hints are injected for efficient navigation.

        LEARNING MODE (learn=True):
        - Agent executes with API discovery instructions
        - On success, attempts to extract a reusable skill from the execution
        - If save_skill_as is provided, saves the learned skill

        Args:
            task: Natural language description of what to do in the browser
            max_steps: Maximum number of agent steps (default from settings)
            skill_name: Optional skill name to use for hints (execution mode)
            skill_params: Optional JSON string of parameters to pass to the skill
            learn: Enable learning mode - agent focuses on API discovery
            save_skill_as: Name to save the learned skill (requires learn=True)

        Returns:
            Result of the browser automation task. In learning mode, includes
            skill extraction status.
        """
        await ctx.info(f"Starting: {task}")
        logger.info(f"Starting browser agent task: {task[:100]}...")

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            return f"Error: {e}"

        # Determine execution mode
        skill = None
        augmented_task = task
        params_dict: dict = {}

        if learn and skill_name:
            # Can't use both learning and existing skill
            logger.warning("learn=True ignores skill_name - running in learning mode")
            skill_name = None

        if learn:
            # LEARNING MODE: Inject API discovery instructions
            await ctx.info("Learning mode: Agent will discover APIs")
            augmented_task = skill_executor.inject_learning_mode(task)
            logger.info("Learning mode enabled - API discovery instructions injected")

        elif skill_name and settings.skills.enabled:
            # EXECUTION MODE: Load skill and inject hints
            skill = skill_store.load(skill_name)
            if skill:
                # Parse skill params from JSON string
                if skill_params:
                    import json

                    try:
                        params_dict = json.loads(skill_params)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid skill_params JSON: {skill_params}")
                        params_dict = {}

                augmented_task = skill_executor.inject_hints(task, skill, params_dict)
                await ctx.info(f"Using skill: {skill.name}")
                logger.info(f"Skill hints injected for: {skill.name}")
            else:
                await ctx.info(f"Skill not found: {skill_name}")
                logger.warning(f"Skill not found: {skill_name}")

        steps = max_steps if max_steps is not None else settings.agent.max_steps
        await progress.set_total(steps)

        # Track page changes and navigation for potential skill extraction
        last_url: str | None = None
        navigation_urls: list[str] = []

        async def step_callback(
            state: "BrowserStateSummary",
            output: "AgentOutput",
            step_num: int,
        ) -> None:
            nonlocal last_url
            if state.url != last_url:
                await ctx.info(f"→ {state.title or state.url}")
                navigation_urls.append(state.url)
                last_url = state.url
            await progress.increment()

        # Initialize recorder for learning mode
        recorder: SkillRecorder | None = None
        if learn:
            recorder = SkillRecorder(task=task)

        try:
            agent = Agent(
                task=augmented_task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
                register_new_step_callback=step_callback,
            )

            # In learning mode, start browser early and attach recorder to CDP
            if recorder:
                await ctx.info("Attaching network recorder...")
                await agent.browser_session.start()
                await recorder.attach(agent.browser_session)
                logger.info("SkillRecorder attached via CDP for network capture")

            result = await agent.run()
            final = result.final_result() or "Task completed without explicit result."

            # Validate result if skill was used (execution mode)
            is_valid = True
            if skill and settings.skills.validate_results:
                is_valid = skill_executor.validate_result(final, skill)
                if not is_valid:
                    await ctx.info("Skill validation failed - hints may be outdated")
                    logger.warning(f"Skill validation failed for: {skill.name}")

                    # Handle fallback based on skill config
                    if skill.fallback.strategy == "explore_full":
                        await ctx.info("Falling back to exploration without hints...")
                        # Re-run without hints
                        agent = Agent(
                            task=task,  # Original task without hints
                            llm=llm,
                            browser_profile=profile,
                            max_steps=steps,
                            register_new_step_callback=step_callback,
                        )
                        result = await agent.run()
                        final = result.final_result() or "Task completed without explicit result."
                        is_valid = True  # Fallback execution is considered valid

            # Record skill usage statistics (execution mode)
            if skill:
                skill_store.record_usage(skill.name, success=is_valid)

            # LEARNING MODE: Attempt to extract skill from execution
            skill_extraction_result = ""
            if learn and final and save_skill_as:
                await ctx.info("Analyzing execution for skill extraction...")

                try:
                    # Finalize recorder and get full CDP recording
                    if recorder:
                        await recorder.finalize()
                        await recorder.detach()
                        recording = recorder.get_recording(result=final)
                        api_count = recorder.api_call_count
                        await ctx.info(f"Captured {api_count} API calls for analysis")
                        logger.info(f"Recording captured: {recorder.request_count} requests, {api_count} API calls")
                    else:
                        # Fallback to simplified recording (shouldn't happen in learn mode)
                        from .skills import SessionRecording

                        recording = SessionRecording(
                            task=task,
                            result=final,
                            navigation_urls=navigation_urls,
                        )
                        logger.warning("Using simplified recording - recorder was not attached")

                    # Analyze with LLM
                    analyzer = SkillAnalyzer(llm)
                    extracted_skill = await analyzer.analyze(recording)

                    if extracted_skill:
                        extracted_skill.name = save_skill_as
                        skill_store.save(extracted_skill)
                        skill_extraction_result = f"\n\n[SKILL LEARNED] Saved as '{save_skill_as}'"
                        await ctx.info(f"Skill saved: {save_skill_as}")
                        logger.info(f"Skill extracted and saved: {save_skill_as}")
                    else:
                        skill_extraction_result = "\n\n[SKILL NOT LEARNED] Could not extract API from execution"
                        await ctx.info("Could not extract skill - no suitable API found")
                        logger.info("Skill extraction failed - no suitable API found")

                except Exception as e:
                    logger.error(f"Skill extraction failed: {e}")
                    skill_extraction_result = f"\n\n[SKILL EXTRACTION ERROR] {e}"

            # Auto-save result if results_dir is configured
            if settings.server.results_dir:
                saved_path = save_execution_result(
                    final,
                    prefix=f"agent_{task[:20]}",
                    metadata={"task": task, "max_steps": steps, "skill": skill_name, "learn": learn},
                )
                await ctx.info(f"Saved to: {saved_path.name}")

            await ctx.info(f"Completed: {final[:100]}")
            logger.info(f"Agent completed: {final[:100]}...")
            return final + skill_extraction_result

        except Exception as e:
            # Clean up recorder if attached
            if recorder:
                try:
                    await recorder.detach()
                except Exception:
                    pass  # Ignore cleanup errors

            # Record failure if skill was used
            if skill:
                skill_store.record_usage(skill.name, success=False)
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

        # Auto-save result if results_dir is configured and no explicit save path
        if settings.server.results_dir and not save_to_file:
            saved_path = save_execution_result(
                report,
                prefix=f"research_{topic[:20]}",
                metadata={"topic": topic, "max_searches": searches},
            )
            await ctx.info(f"Saved to: {saved_path.name}")

        return report

    # --- Skill Management Tools ---

    @server.tool()
    async def skill_list() -> str:
        """
        List all available browser skills.

        Returns:
            JSON list of skill summaries with name, description, and usage stats
        """
        import json

        skills = skill_store.list_all()

        if not skills:
            return json.dumps({"skills": [], "message": "No skills found. Use learn=True with save_skill_as to learn new skills."})

        return json.dumps(
            {
                "skills": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "success_rate": round(s.success_rate * 100, 1),
                        "usage_count": s.success_count + s.failure_count,
                        "last_used": s.last_used.isoformat() if s.last_used else None,
                    }
                    for s in skills
                ],
                "skills_directory": str(skill_store.directory),
            },
            indent=2,
        )

    @server.tool()
    async def skill_get(skill_name: str) -> str:
        """
        Get full details of a specific skill.

        Args:
            skill_name: Name of the skill to retrieve

        Returns:
            Full skill definition as YAML
        """
        skill = skill_store.load(skill_name)

        if not skill:
            return f"Error: Skill '{skill_name}' not found in {skill_store.directory}"

        return skill_store.to_yaml(skill)

    @server.tool()
    async def skill_delete(skill_name: str) -> str:
        """
        Delete a skill by name.

        Args:
            skill_name: Name of the skill to delete

        Returns:
            Success or error message
        """
        if skill_store.delete(skill_name):
            return f"Skill '{skill_name}' deleted successfully"
        return f"Error: Skill '{skill_name}' not found"

    return server


server_instance = serve()


def main() -> None:
    """Entry point for MCP server."""
    transport = settings.server.transport
    logger.info(f"Starting MCP browser-use server (provider: {settings.llm.provider}, transport: {transport})")

    if transport == "stdio":
        # CRITICAL: show_banner=False prevents FastMCP from printing to stdout
        # which would corrupt the JSON-RPC stream
        server_instance.run(transport="stdio", show_banner=False)
    elif transport in ("streamable-http", "sse"):
        logger.info(f"HTTP server at http://{settings.server.host}:{settings.server.port}/mcp")
        server_instance.run(transport=transport, host=settings.server.host, port=settings.server.port)
    else:
        raise ValueError(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()
