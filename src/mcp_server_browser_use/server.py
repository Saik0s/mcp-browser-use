"""MCP server exposing browser-use as tools with native background task support."""

import asyncio
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING


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
from fastmcp.server.tasks.config import TaskConfig

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .observability import TaskRecord, TaskStage, TaskStatus, bind_task_context, clear_task_context, get_task_logger, setup_structured_logging
from .observability.store import get_task_store
from .providers import get_llm
from .research.machine import ResearchMachine
from .skills import SkillAnalyzer, SkillExecutor, SkillRecorder, SkillRunner, SkillStore
from .utils import save_execution_result

if TYPE_CHECKING:
    from browser_use.agent.views import AgentOutput
    from browser_use.browser.views import BrowserStateSummary

# Apply configured log level (may override the default WARNING)
logger = logging.getLogger("mcp_server_browser_use")
logger.setLevel(getattr(logging, settings.server.logging_level.upper()))

# Global registry of running asyncio tasks for cancellation support
_running_tasks: dict[str, asyncio.Task] = {}


def serve() -> FastMCP:
    """Create and configure MCP server with background task support."""
    # Set up structured logging first
    setup_structured_logging()

    server = FastMCP("mcp_server_browser_use")

    # Initialize skill components (only when skills feature is enabled)
    skill_store: SkillStore | None = None
    skill_executor: SkillExecutor | None = None
    if settings.skills.enabled:
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
        profile = BrowserProfile(
            headless=settings.browser.headless,
            proxy=proxy,
            cdp_url=settings.browser.cdp_url,
            user_data_dir=settings.browser.user_data_dir,
            chromium_sandbox=settings.browser.chromium_sandbox,
        )
        if settings.browser.cdp_url:
            logger.info(f"Using external browser via CDP: {settings.browser.cdp_url}")
        return llm, profile

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_browser_agent(
        task: str,
        max_steps: int | None = None,
        skill_name: str | None = None,
        skill_params: str | dict | None = None,
        learn: bool = False,
        save_skill_as: str | None = None,
        ctx: Context = CurrentContext(),
        progress: Progress = Progress(),
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
            skill_params: Optional parameters for the skill (JSON string or dict)
            learn: Enable learning mode - agent focuses on API discovery
            save_skill_as: Name to save the learned skill (requires learn=True)

        Returns:
            Result of the browser automation task. In learning mode, includes
            skill extraction status.
        """
        # --- Task Tracking Setup ---
        task_id = str(uuid.uuid4())
        task_store = get_task_store()
        task_record = TaskRecord(
            task_id=task_id,
            tool_name="run_browser_agent",
            status=TaskStatus.PENDING,
            input_params={"task": task, "max_steps": max_steps, "skill_name": skill_name, "learn": learn},
        )
        await task_store.create_task(task_record)
        bind_task_context(task_id, "run_browser_agent")
        task_logger = get_task_logger()

        await ctx.info(f"Starting: {task}")
        logger.info(f"Starting browser agent task: {task[:100]}...")
        task_logger.info("task_created", task_preview=task[:100])

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
            clear_task_context()
            return f"Error: {e}"

        # Mark task as running
        await task_store.update_status(task_id, TaskStatus.RUNNING)
        await task_store.update_progress(task_id, 0, 0, "Initializing...", TaskStage.INITIALIZING)
        task_logger.info("task_running")

        # Determine execution mode
        skill = None
        augmented_task = task
        params_dict: dict = {}

        if learn and skill_name:
            # Can't use both learning and existing skill
            logger.warning("learn=True ignores skill_name - running in learning mode")
            skill_name = None

        if learn and skill_executor:
            # LEARNING MODE: Inject API discovery instructions
            await ctx.info("Learning mode: Agent will discover APIs")
            augmented_task = skill_executor.inject_learning_mode(task)
            logger.info("Learning mode enabled - API discovery instructions injected")
        elif learn:
            # Skills disabled - warn and continue without learning
            await ctx.info("Skills feature disabled - learn parameter ignored")
            logger.warning("learn=True ignored - skills.enabled is False")
            learn = False  # Disable learning for rest of execution

        elif skill_name and settings.skills.enabled and skill_store and skill_executor:
            # EXECUTION MODE: Load skill
            skill = skill_store.load(skill_name)
            if skill:
                # Parse skill params (accepts dict or JSON string)
                if skill_params:
                    if isinstance(skill_params, dict):
                        params_dict = skill_params
                    elif isinstance(skill_params, str):
                        import json

                        try:
                            parsed = json.loads(skill_params)
                            if isinstance(parsed, dict):
                                params_dict = parsed
                            else:
                                logger.warning(f"skill_params must be an object, got {type(parsed).__name__}")
                                params_dict = {}
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid skill_params JSON: {skill_params}")
                            params_dict = {}
                    else:
                        logger.warning(f"skill_params must be dict or JSON string, got {type(skill_params).__name__}")
                        params_dict = {}

                # Merge user params with skill parameter defaults
                merged_params = skill.merge_params(params_dict)

                # NEW: Try direct execution if skill supports it
                if skill.supports_direct_execution:
                    await ctx.info(f"Direct execution: {skill.name}")
                    logger.info(f"Attempting direct execution for skill: {skill.name}")

                    try:
                        # Create browser session for fetch execution
                        from browser_use.browser.session import BrowserSession

                        browser_session = BrowserSession(browser_profile=profile)
                        await browser_session.start()

                        try:
                            runner = SkillRunner()
                            run_result = await runner.run(skill, merged_params, browser_session)

                            if run_result.success:
                                # Direct execution succeeded!
                                skill_store.record_usage(skill.name, success=True)
                                await ctx.info("Direct execution completed")
                                logger.info(f"Skill direct execution succeeded: {skill.name}")

                                # Format result
                                import json

                                if isinstance(run_result.data, (dict, list)):
                                    final_result = json.dumps(run_result.data, indent=2)
                                else:
                                    final_result = str(run_result.data)

                                # Auto-save result if configured
                                if settings.server.results_dir:
                                    saved_path = save_execution_result(
                                        final_result,
                                        prefix=f"skill_{skill.name}",
                                        metadata={"skill": skill.name, "params": params_dict, "direct": True},
                                    )
                                    await ctx.info(f"Saved to: {saved_path.name}")

                                # Mark task as completed before returning
                                await task_store.update_status(task_id, TaskStatus.COMPLETED, result=final_result)
                                task_logger.info("task_completed", result_length=len(final_result), direct=True)
                                clear_task_context()
                                return final_result

                            elif run_result.auth_recovery_triggered:
                                # Auth failed - fall back to agent for re-auth
                                await ctx.info("Auth required, falling back to agent...")
                                logger.info("Direct execution needs auth recovery, falling back to agent")
                                # Continue to agent execution below

                            else:
                                # Direct execution failed - fall back to agent
                                await ctx.info(f"Direct failed: {run_result.error}, trying agent...")
                                logger.warning(f"Direct execution failed: {run_result.error}")
                                # Continue to agent execution below

                        finally:
                            await browser_session.stop()

                    except Exception as e:
                        logger.error(f"Direct execution error: {e}")
                        await ctx.info("Direct execution error, trying agent...")
                        # Continue to agent execution below

                # Inject hints for agent execution (fallback or non-direct skills)
                augmented_task = skill_executor.inject_hints(task, skill, merged_params)
                await ctx.info(f"Using skill hints: {skill.name}")
                logger.info(f"Skill hints injected for: {skill.name}")
            else:
                await ctx.info(f"Skill not found: {skill_name}")
                logger.warning(f"Skill not found: {skill_name}")
        elif skill_name:
            # Skills disabled - warn and continue without skill
            await ctx.info("Skills feature disabled - skill_name parameter ignored")
            logger.warning(f"skill_name='{skill_name}' ignored - skills.enabled is False")

        steps = max_steps if max_steps is not None else settings.agent.max_steps
        await progress.set_total(steps)

        # Track page changes and navigation for potential skill extraction
        last_url: str | None = None
        navigation_urls: list[str] = []
        last_db_update: float = 0.0  # Throttle DB writes to once per second

        async def step_callback(
            state: "BrowserStateSummary",
            output: "AgentOutput",
            step_num: int,
        ) -> None:
            nonlocal last_url, last_db_update
            url_changed = state.url != last_url
            if url_changed:
                await ctx.info(f"→ {state.title or state.url}")
                navigation_urls.append(state.url)
                last_url = state.url
            await progress.increment()

            # Throttle DB updates: only write once per second or on URL change
            now = time.monotonic()
            if url_changed or (now - last_db_update) >= 1.0:
                stage = TaskStage.NAVIGATING if state.url else TaskStage.EXTRACTING
                message = state.title or state.url or f"Step {step_num}"
                await task_store.update_progress(task_id, step_num, steps, message[:100], stage)
                last_db_update = now
            task_logger.debug("step_completed", step=step_num, url=state.url)

        # Initialize recorder for learning mode
        recorder: SkillRecorder | None = None
        if learn:
            recorder = SkillRecorder(task=task)

        # Track recorder attachment for cleanup
        recorder_attached = False

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
                recorder_attached = True
                logger.info("SkillRecorder attached via CDP for network capture")

            # Register task for cancellation support
            agent_task = asyncio.create_task(agent.run())
            _running_tasks[task_id] = agent_task
            try:
                result = await agent_task
            finally:
                _running_tasks.pop(task_id, None)

            final = result.final_result() or "Task completed without explicit result."

            # Validate result if skill was used (execution mode)
            is_valid = True
            if skill and skill_executor and settings.skills.validate_results:
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
            if skill and skill_store:
                skill_store.record_usage(skill.name, success=is_valid)

            # LEARNING MODE: Attempt to extract skill from execution
            skill_extraction_result = ""
            if learn and final and save_skill_as:
                await ctx.info("Analyzing execution for skill extraction...")

                try:
                    # Finalize recorder and get full CDP recording
                    if recorder and recorder_attached:
                        await recorder.finalize()
                        await recorder.detach()
                        recorder_attached = False  # Mark as detached
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

                    if extracted_skill and skill_store:
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

            # Mark task as completed
            final_result = final + skill_extraction_result
            await task_store.update_status(task_id, TaskStatus.COMPLETED, result=final_result)
            task_logger.info("task_completed", result_length=len(final_result))
            clear_task_context()
            return final_result

        except asyncio.CancelledError:
            # Task was cancelled - record failure
            if skill and skill_store:
                skill_store.record_usage(skill.name, success=False)

            await task_store.update_status(task_id, TaskStatus.CANCELLED, error="Cancelled by user")
            task_logger.info("task_cancelled")
            clear_task_context()
            raise

        except Exception as e:
            # Record failure if skill was used
            if skill and skill_store:
                skill_store.record_usage(skill.name, success=False)

            # Mark task as failed
            await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
            task_logger.error("task_failed", error=str(e))
            clear_task_context()

            logger.error(f"Browser agent failed: {e}")
            raise BrowserError(f"Browser automation failed: {e}") from e

        finally:
            # Ensure CDP listeners are always detached, even if exceptions occurred
            if recorder and recorder_attached:
                try:
                    await recorder.detach()
                    logger.info("CDP listeners detached successfully in finally block")
                except Exception as cleanup_error:
                    # Log exception but don't mask the original error
                    logger.exception(f"Critical: Failed to detach CDP listeners in finally block: {cleanup_error}")

    @server.tool(task=TaskConfig(mode="optional"))
    async def run_deep_research(
        topic: str,
        max_searches: int | None = None,
        save_to_file: str | None = None,
        ctx: Context = CurrentContext(),
        progress: Progress = Progress(),
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
        # --- Task Tracking Setup ---
        task_id = str(uuid.uuid4())
        task_store = get_task_store()
        task_record = TaskRecord(
            task_id=task_id,
            tool_name="run_deep_research",
            status=TaskStatus.PENDING,
            input_params={"topic": topic, "max_searches": max_searches, "save_to_file": save_to_file},
        )
        await task_store.create_task(task_record)
        bind_task_context(task_id, "run_deep_research")
        task_logger = get_task_logger()

        logger.info(f"Starting deep research on: {topic}")
        task_logger.info("task_created", topic=topic[:100])

        try:
            llm, profile = _get_llm_and_profile()
        except LLMProviderError as e:
            logger.error(f"LLM initialization failed: {e}")
            await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
            clear_task_context()
            return f"Error: {e}"

        # Mark task as running
        await task_store.update_status(task_id, TaskStatus.RUNNING)
        task_logger.info("task_running")

        searches = max_searches if max_searches is not None else settings.research.max_searches
        # Sanitize topic for safe filename
        safe_topic = re.sub(r"[^\w\s-]", "", topic[:50]).strip().replace(" ", "_")
        save_path = save_to_file or (f"{settings.research.save_directory}/{safe_topic}.md" if settings.research.save_directory else None)

        try:
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

            # Register task for cancellation support
            research_task = asyncio.create_task(machine.run())
            _running_tasks[task_id] = research_task
            try:
                report = await research_task
            finally:
                _running_tasks.pop(task_id, None)

            # Auto-save result if results_dir is configured and no explicit save path
            if settings.server.results_dir and not save_to_file:
                saved_path = save_execution_result(
                    report,
                    prefix=f"research_{topic[:20]}",
                    metadata={"topic": topic, "max_searches": searches},
                )
                await ctx.info(f"Saved to: {saved_path.name}")

            # Mark task as completed
            await task_store.update_status(task_id, TaskStatus.COMPLETED, result=report)
            task_logger.info("task_completed", result_length=len(report))
            clear_task_context()
            return report

        except asyncio.CancelledError:
            # Task was cancelled
            await task_store.update_status(task_id, TaskStatus.CANCELLED, error="Cancelled by user")
            task_logger.info("task_cancelled")
            clear_task_context()
            raise

        except Exception as e:
            await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
            task_logger.error("task_failed", error=str(e))
            clear_task_context()
            raise

    # --- Skill Management Tools (only registered when skills.enabled) ---
    if settings.skills.enabled and skill_store:

        @server.tool()
        async def skill_list() -> str:
            """
            List all available browser skills.

            Returns:
                JSON list of skill summaries with name, description, and usage stats
            """
            import json

            assert skill_store is not None  # Type narrowing for mypy
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
            assert skill_store is not None  # Type narrowing for mypy
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
            assert skill_store is not None  # Type narrowing for mypy
            if skill_store.delete(skill_name):
                return f"Skill '{skill_name}' deleted successfully"
            return f"Error: Skill '{skill_name}' not found"

    # --- Observability Tools ---

    # Define tool functions
    async def _health_check_impl() -> str:
        """Implementation of health check."""
        import json

        import psutil

        task_store = get_task_store()
        running_tasks = await task_store.get_running_tasks()
        stats = await task_store.get_stats()

        # Get process stats
        process = psutil.Process()
        memory_info = process.memory_info()

        return json.dumps(
            {
                "status": "healthy",
                "uptime_seconds": round(time.time() - _server_start_time, 1),
                "memory_mb": round(memory_info.rss / 1024 / 1024, 1),
                "running_tasks": len(running_tasks),
                "tasks": [
                    {
                        "task_id": t.task_id[:8],
                        "tool": t.tool_name,
                        "stage": t.stage.value if t.stage else None,
                        "progress": f"{t.progress_current}/{t.progress_total}",
                        "message": t.progress_message,
                    }
                    for t in running_tasks
                ],
                "stats": stats,
            },
            indent=2,
        )

    async def _task_list_impl(limit: int = 20, status_filter: str | None = None) -> str:
        """Implementation of task list."""
        import json

        task_store = get_task_store()

        status = None
        if status_filter:
            try:
                status = TaskStatus(status_filter)
            except ValueError:
                return f"Error: Invalid status '{status_filter}'. Use: running, completed, failed, pending"

        tasks = await task_store.get_task_history(limit=limit, status=status)

        return json.dumps(
            {
                "tasks": [
                    {
                        "task_id": t.task_id[:8],
                        "tool": t.tool_name,
                        "status": t.status.value,
                        "progress": f"{t.progress_current}/{t.progress_total}",
                        "created": t.created_at.isoformat(),
                        "duration_sec": round(t.duration_seconds, 1) if t.duration_seconds else None,
                    }
                    for t in tasks
                ],
                "count": len(tasks),
            },
            indent=2,
        )

    async def _task_get_impl(task_id: str) -> str:
        """Implementation of task get."""
        import json

        task_store = get_task_store()

        # Try exact match first, then prefix match
        task = await task_store.get_task(task_id)
        if not task:
            # Try prefix match
            tasks = await task_store.get_task_history(limit=100)
            for t in tasks:
                if t.task_id.startswith(task_id):
                    task = t
                    break

        if not task:
            return f"Error: Task '{task_id}' not found"

        return json.dumps(
            {
                "task_id": task.task_id,
                "tool": task.tool_name,
                "status": task.status.value,
                "stage": task.stage.value if task.stage else None,
                "progress": {
                    "current": task.progress_current,
                    "total": task.progress_total,
                    "message": task.progress_message,
                    "percent": task.progress_percent,
                },
                "timestamps": {
                    "created": task.created_at.isoformat(),
                    "started": task.started_at.isoformat() if task.started_at else None,
                    "completed": task.completed_at.isoformat() if task.completed_at else None,
                    "duration_sec": round(task.duration_seconds, 1) if task.duration_seconds else None,
                },
                "input": task.input_params,
                "result": task.result[:500] if task.result else None,
                "error": task.error,
            },
            indent=2,
        )

    @server.tool()
    async def health_check() -> str:
        """
        Health check endpoint with system stats and running task information.

        Returns:
            JSON object with server health status, running tasks, and statistics
        """
        return await _health_check_impl()

    @server.tool()
    async def task_list(
        limit: int = 20,
        status_filter: str | None = None,
    ) -> str:
        """
        List recent tasks with optional filtering.

        Args:
            limit: Maximum number of tasks to return (default 20)
            status_filter: Optional status filter (running, completed, failed)

        Returns:
            JSON list of recent tasks
        """
        return await _task_list_impl(limit, status_filter)

    @server.tool()
    async def task_get(task_id: str) -> str:
        """
        Get full details of a specific task.

        Args:
            task_id: Task ID (full or prefix)

        Returns:
            JSON object with task details, input, and result/error
        """
        return await _task_get_impl(task_id)

    @server.tool()
    async def task_cancel(task_id: str) -> str:
        """
        Cancel a running browser agent or research task.

        Args:
            task_id: Task ID (full or prefix match)

        Returns:
            JSON with success status and message
        """
        import json

        task_store = get_task_store()

        # Find by prefix match
        matched_id = None
        for full_id in _running_tasks:
            if full_id.startswith(task_id) or full_id == task_id:
                matched_id = full_id
                break

        if not matched_id:
            return json.dumps({"success": False, "error": f"Task '{task_id}' not found or not running"})

        # Cancel the asyncio task
        task = _running_tasks[matched_id]
        task.cancel()

        # Update status in store
        await task_store.update_status(matched_id, TaskStatus.CANCELLED, error="Cancelled by user")

        return json.dumps({"success": True, "task_id": matched_id[:8], "message": "Task cancelled"})

    # --- Web Viewer UI ---
    @server.custom_route(path="/", methods=["GET"])
    async def serve_viewer(request):
        """Serve the web viewer UI for task monitoring."""
        from starlette.responses import FileResponse

        # Get the path to the viewer.html file
        viewer_path = Path(__file__).parent / "ui" / "viewer.html"

        if not viewer_path.exists():
            from starlette.responses import Response

            return Response(
                content="Web viewer not found. Make sure ui/viewer.html exists.",
                status_code=404,
                media_type="text/plain",
            )

        return FileResponse(viewer_path, media_type="text/html")

    @server.custom_route(path="/dashboard", methods=["GET"])
    async def serve_dashboard(request):
        """Serve the dashboard UI for task/skill management."""
        from starlette.responses import FileResponse

        dashboard_path = Path(__file__).parent / "ui" / "dashboard.html"

        if not dashboard_path.exists():
            from starlette.responses import Response

            return Response(
                content="Dashboard not found. Make sure ui/dashboard.html exists.",
                status_code=404,
                media_type="text/plain",
            )

        return FileResponse(dashboard_path, media_type="text/html")

    # REST API endpoints for the web viewer (simpler than JSON-RPC for browser)
    @server.custom_route(path="/api/health", methods=["GET"])
    async def api_health(request):
        """REST endpoint for health check."""
        import json

        from starlette.responses import JSONResponse

        result = await _health_check_impl()
        return JSONResponse(json.loads(result))

    @server.custom_route(path="/api/tasks", methods=["GET"])
    async def api_tasks(request):
        """REST endpoint for task list."""
        import json

        from starlette.responses import JSONResponse

        limit = int(request.query_params.get("limit", "20"))
        status_filter = request.query_params.get("status", None)

        result = await _task_list_impl(limit=limit, status_filter=status_filter)
        return JSONResponse(json.loads(result))

    @server.custom_route(path="/api/tasks/{task_id}", methods=["GET"])
    async def api_task_get(request):
        """REST endpoint for task details."""
        import json

        from starlette.responses import JSONResponse

        task_id = request.path_params["task_id"]
        result = await _task_get_impl(task_id)

        # Check if it's an error message
        if result.startswith("Error:"):
            return JSONResponse({"error": result}, status_code=404)

        return JSONResponse(json.loads(result))

    # REST API endpoints for skills
    def _get_skill_store() -> SkillStore | None:
        """Get skill store instance if skills are enabled."""
        if settings.skills.enabled:
            return SkillStore(directory=settings.skills.directory)
        return None

    @server.custom_route(path="/api/skills", methods=["GET"])
    async def api_skills(request):
        """REST endpoint for skills list."""

        from starlette.responses import JSONResponse

        store = _get_skill_store()
        if not store:
            return JSONResponse({"error": "Skills feature is disabled"}, status_code=503)

        try:
            skills = store.list_all()
            return JSONResponse(
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
                    "count": len(skills),
                    "skills_directory": str(store.directory),
                }
            )
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @server.custom_route(path="/api/skills/{name}", methods=["GET"])
    async def api_skill_get(request):
        """REST endpoint for skill details."""

        from starlette.responses import JSONResponse

        store = _get_skill_store()
        if not store:
            return JSONResponse({"error": "Skills feature is disabled"}, status_code=503)

        skill_name = request.path_params["name"]

        try:
            skill = store.load(skill_name)
            if not skill:
                return JSONResponse({"error": f"Skill '{skill_name}' not found"}, status_code=404)

            # Return skill as JSON (convert from dict representation)
            skill_dict = skill.to_dict()
            return JSONResponse(skill_dict)
        except Exception as e:
            logger.error(f"Failed to get skill {skill_name}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @server.custom_route(path="/api/skills/{name}", methods=["DELETE"])
    async def api_skill_delete(request):
        """REST endpoint for skill deletion."""
        from starlette.responses import JSONResponse

        store = _get_skill_store()
        if not store:
            return JSONResponse({"error": "Skills feature is disabled"}, status_code=503)

        skill_name = request.path_params["name"]

        try:
            if store.delete(skill_name):
                return JSONResponse({"success": True, "message": f"Skill '{skill_name}' deleted successfully"})
            return JSONResponse({"error": f"Skill '{skill_name}' not found"}, status_code=404)
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_name}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    @server.custom_route(path="/api/skills/{name}/run", methods=["POST"])
    async def api_skill_run(request):
        """REST endpoint for skill execution.

        Request body:
        {
            "url": "https://example.com",  # Optional - can be part of task description
            "params": {...}                 # Optional skill parameters
        }

        Returns:
        {
            "task_id": "abc123...",
            "message": "Skill execution started"
        }
        """
        from starlette.responses import JSONResponse

        if not settings.skills.enabled:
            return JSONResponse({"error": "Skills feature is disabled"}, status_code=503)

        skill_name = request.path_params["name"]

        try:
            body = await request.json()
        except Exception as e:
            return JSONResponse({"error": f"Invalid JSON body: {e}"}, status_code=400)

        url = body.get("url", "")
        params = body.get("params", {})

        # Build task description
        task_desc = f"Use the {skill_name} skill"
        if url:
            task_desc += f" at {url}"

        # Create task ID for tracking
        task_id = str(uuid.uuid4())
        task_store = get_task_store()
        task_record = TaskRecord(
            task_id=task_id,
            tool_name=f"skill_run:{skill_name}",
            status=TaskStatus.PENDING,
            input_params={"skill_name": skill_name, "url": url, "params": params},
        )
        await task_store.create_task(task_record)

        # Start execution in background
        async def execute_skill() -> None:
            """Background task to execute the skill."""
            bind_task_context(task_id, f"skill_run:{skill_name}")
            task_logger = get_task_logger()

            try:
                llm, profile = _get_llm_and_profile()
            except LLMProviderError as e:
                logger.error(f"LLM initialization failed: {e}")
                await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
                clear_task_context()
                return

            await task_store.update_status(task_id, TaskStatus.RUNNING)
            task_logger.info("task_running")

            try:
                # Build agent with skill hints
                augmented_task = task_desc
                if skill_store:
                    skill = skill_store.load(skill_name)
                    if skill and skill_executor:
                        merged_params = skill.merge_params(params)
                        augmented_task = skill_executor.inject_hints(task_desc, skill, merged_params)

                agent = Agent(
                    task=augmented_task,
                    llm=llm,
                    browser_profile=profile,
                    max_steps=settings.agent.max_steps,
                )

                # Register for cancellation
                agent_task = asyncio.create_task(agent.run())
                _running_tasks[task_id] = agent_task

                try:
                    result = await agent_task
                finally:
                    _running_tasks.pop(task_id, None)

                final = result.final_result() or "Task completed without explicit result."

                # Record usage
                if skill_store:
                    skill_store.record_usage(skill_name, success=True)

                await task_store.update_status(task_id, TaskStatus.COMPLETED, result=final)
                task_logger.info("task_completed", result_length=len(final))

            except Exception as e:
                if skill_store:
                    skill_store.record_usage(skill_name, success=False)
                await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
                task_logger.error("task_failed", error=str(e))
                logger.error(f"Skill {skill_name} execution failed: {e}")

            finally:
                clear_task_context()

        # Start background task and keep reference to prevent garbage collection
        bg_task = asyncio.create_task(execute_skill())
        # Store task reference to prevent GC
        _running_tasks[f"{task_id}_bg"] = bg_task

        return JSONResponse(
            {
                "task_id": task_id,
                "skill_name": skill_name,
                "message": "Skill execution started",
                "status_url": f"/api/tasks/{task_id}",
            },
            status_code=202,
        )

    @server.custom_route(path="/api/learn", methods=["POST"])
    async def api_learn(request):
        """REST endpoint for learning mode.

        Request body:
        {
            "task": "Learn how to search on GitHub",
            "skill_name": "github_search"  # Optional - name to save learned skill
        }

        Returns:
        {
            "task_id": "abc123...",
            "message": "Learning session started"
        }
        """
        from starlette.responses import JSONResponse

        if not settings.skills.enabled:
            return JSONResponse({"error": "Skills feature is disabled"}, status_code=503)

        try:
            body = await request.json()
        except Exception as e:
            return JSONResponse({"error": f"Invalid JSON body: {e}"}, status_code=400)

        task_description = body.get("task")
        if not task_description:
            return JSONResponse({"error": "Missing required field: task"}, status_code=400)

        skill_name = body.get("skill_name")

        # Create task ID for tracking
        task_id = str(uuid.uuid4())
        task_store = get_task_store()
        task_record = TaskRecord(
            task_id=task_id,
            tool_name="learn",
            status=TaskStatus.PENDING,
            input_params={"task": task_description, "skill_name": skill_name},
        )
        await task_store.create_task(task_record)

        # Start learning in background
        async def execute_learn() -> None:
            """Background task to execute learning mode."""
            bind_task_context(task_id, "learn")
            task_logger = get_task_logger()

            try:
                llm, profile = _get_llm_and_profile()
            except LLMProviderError as e:
                logger.error(f"LLM initialization failed: {e}")
                await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
                clear_task_context()
                return

            await task_store.update_status(task_id, TaskStatus.RUNNING)
            task_logger.info("task_running")

            try:
                # Inject learning mode instructions
                augmented_task = task_description
                if skill_executor:
                    augmented_task = skill_executor.inject_learning_mode(task_description)

                # Initialize recorder for learning mode
                recorder = SkillRecorder(task=task_description)

                agent = Agent(
                    task=augmented_task,
                    llm=llm,
                    browser_profile=profile,
                    max_steps=settings.agent.max_steps,
                )

                # Attach recorder to CDP
                await agent.browser_session.start()
                await recorder.attach(agent.browser_session)
                recorder_attached = True

                # Register for cancellation
                agent_task = asyncio.create_task(agent.run())
                _running_tasks[task_id] = agent_task

                try:
                    result = await agent_task
                finally:
                    _running_tasks.pop(task_id, None)

                final = result.final_result() or "Task completed without explicit result."

                # Extract skill from execution
                skill_extraction_result = ""
                if final and skill_name and skill_store:
                    try:
                        await recorder.finalize()
                        await recorder.detach()
                        recorder_attached = False

                        recording = recorder.get_recording(result=final)

                        # Analyze with LLM
                        analyzer = SkillAnalyzer(llm)
                        extracted_skill = await analyzer.analyze(recording)

                        if extracted_skill:
                            extracted_skill.name = skill_name
                            skill_store.save(extracted_skill)
                            skill_extraction_result = f"\n\n[SKILL LEARNED] Saved as '{skill_name}'"
                            logger.info(f"Skill extracted and saved: {skill_name}")
                        else:
                            skill_extraction_result = "\n\n[SKILL NOT LEARNED] Could not extract API from execution"

                    except Exception as e:
                        logger.error(f"Skill extraction failed: {e}")
                        skill_extraction_result = f"\n\n[SKILL EXTRACTION ERROR] {e}"
                    finally:
                        if recorder_attached:
                            await recorder.detach()

                final_result = final + skill_extraction_result
                await task_store.update_status(task_id, TaskStatus.COMPLETED, result=final_result)
                task_logger.info("task_completed", result_length=len(final_result))

            except Exception as e:
                await task_store.update_status(task_id, TaskStatus.FAILED, error=str(e))
                task_logger.error("task_failed", error=str(e))
                logger.error(f"Learning session failed: {e}")

            finally:
                clear_task_context()

        # Start background task and keep reference to prevent garbage collection
        bg_task = asyncio.create_task(execute_learn())
        # Store task reference to prevent GC
        _running_tasks[f"{task_id}_bg"] = bg_task

        return JSONResponse(
            {
                "task_id": task_id,
                "learning_task": task_description,
                "skill_name": skill_name,
                "message": "Learning session started",
                "status_url": f"/api/tasks/{task_id}",
            },
            status_code=202,
        )

    # --- Server-Sent Events (SSE) Endpoints ---

    @server.custom_route(path="/api/events", methods=["GET"])
    async def api_events(request):
        """SSE stream for real-time task updates.

        Streams task status changes and progress updates in real-time.
        Clients should connect once and listen for events.

        Event format:
        data: {"task_id": "...", "status": "...", "progress": {...}, "message": "..."}

        Heartbeat:
        : heartbeat

        Returns:
            StreamingResponse with text/event-stream content type
        """
        import json

        from starlette.responses import StreamingResponse

        task_store = get_task_store()

        async def event_generator():
            """Generate SSE events for task updates."""
            try:
                last_task_states: dict[str, tuple[str, int, str]] = {}  # task_id -> (status, progress_current, message)

                while True:
                    # Get current running tasks
                    running_tasks = await task_store.get_running_tasks()

                    # Stream updates for tasks that changed
                    for task in running_tasks:
                        current_state = (
                            task.status.value,
                            task.progress_current,
                            task.progress_message or "",
                        )

                        # Only send if state changed
                        if task.task_id not in last_task_states or last_task_states[task.task_id] != current_state:
                            event_data = {
                                "task_id": task.task_id[:8],
                                "full_task_id": task.task_id,
                                "tool": task.tool_name,
                                "status": task.status.value,
                                "stage": task.stage.value if task.stage else None,
                                "progress": {
                                    "current": task.progress_current,
                                    "total": task.progress_total,
                                    "percent": task.progress_percent,
                                    "message": task.progress_message,
                                },
                            }
                            yield f"data: {json.dumps(event_data)}\n\n"
                            last_task_states[task.task_id] = current_state

                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"

                    # Wait before next update
                    await asyncio.sleep(2)

            except asyncio.CancelledError:
                # Client disconnected
                logger.debug("SSE client disconnected from /api/events")
                raise

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @server.custom_route(path="/api/tasks/{task_id}/logs", methods=["GET"])
    async def api_task_logs(request):
        """SSE stream for individual task logs.

        Streams real-time updates for a specific task.
        Useful for monitoring long-running tasks in detail.

        Event format:
        data: {"status": "...", "progress": {...}, "stage": "...", "timestamp": "..."}

        Returns:
            StreamingResponse with text/event-stream content type
        """
        import json

        from starlette.responses import StreamingResponse

        task_id = request.path_params["task_id"]
        task_store = get_task_store()

        # Find task by ID (exact or prefix match)
        task = await task_store.get_task(task_id)
        if not task:
            # Try prefix match
            tasks = await task_store.get_task_history(limit=100)
            for t in tasks:
                if t.task_id.startswith(task_id):
                    task = t
                    break

        if not task:
            from starlette.responses import JSONResponse

            return JSONResponse({"error": f"Task '{task_id}' not found"}, status_code=404)

        full_task_id = task.task_id

        async def log_generator():
            """Generate SSE events for task-specific updates."""
            try:
                last_state: tuple[str, int, str, str | None] | None = None  # (status, progress_current, message, stage)

                while True:
                    # Fetch latest task state
                    current_task = await task_store.get_task(full_task_id)
                    if not current_task:
                        # Task was deleted or disappeared
                        yield f"data: {json.dumps({'event': 'task_deleted'})}\n\n"
                        break

                    current_state = (
                        current_task.status.value,
                        current_task.progress_current,
                        current_task.progress_message or "",
                        current_task.stage.value if current_task.stage else None,
                    )

                    # Send update if state changed
                    if current_state != last_state:
                        # Use the most recent timestamp available
                        timestamp = current_task.completed_at or current_task.started_at or current_task.created_at
                        event_data = {
                            "status": current_task.status.value,
                            "stage": current_task.stage.value if current_task.stage else None,
                            "progress": {
                                "current": current_task.progress_current,
                                "total": current_task.progress_total,
                                "percent": current_task.progress_percent,
                                "message": current_task.progress_message,
                            },
                            "timestamp": timestamp.isoformat(),
                        }

                        # Include result/error if task completed/failed
                        if current_task.status == TaskStatus.COMPLETED and current_task.result:
                            event_data["result"] = current_task.result[:200]  # Truncate for SSE
                        elif current_task.status == TaskStatus.FAILED and current_task.error:
                            event_data["error"] = current_task.error

                        yield f"data: {json.dumps(event_data)}\n\n"
                        last_state = current_state

                        # Stop streaming if task reached terminal state
                        if current_task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                            yield f"data: {json.dumps({'event': 'task_ended', 'status': current_task.status.value})}\n\n"
                            break

                    # Send heartbeat
                    yield ": heartbeat\n\n"

                    # Wait before next update
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                # Client disconnected
                logger.debug(f"SSE client disconnected from /api/tasks/{task_id}/logs")
                raise

        return StreamingResponse(
            log_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    return server


# Track server start time for uptime calculation
_server_start_time = time.time()


server_instance = serve()


STDIO_DEPRECATION_MESSAGE = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  STDIO TRANSPORT DEPRECATED                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Browser automation tasks take 60-120+ seconds, which causes timeouts        ║
║  with stdio transport. HTTP mode is now required for reliable operation.     ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  HOW TO MIGRATE                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. START THE HTTP SERVER (run this in terminal):                            ║
║                                                                              ║
║     uvx mcp-server-browser-use server                                        ║
║                                                                              ║
║  2. UPDATE YOUR CLAUDE DESKTOP CONFIG:                                       ║
║                                                                              ║
║     Option A - Native HTTP (if your client supports it):                     ║
║     {                                                                        ║
║       "mcpServers": {                                                        ║
║         "browser-use": {                                                     ║
║           "type": "streamable-http",                                         ║
║           "url": "http://localhost:8000/mcp"                                 ║
║         }                                                                    ║
║       }                                                                      ║
║     }                                                                        ║
║                                                                              ║
║     Option B - Use mcp-remote bridge (works with any MCP client):            ║
║     {                                                                        ║
║       "mcpServers": {                                                        ║
║         "browser-use": {                                                     ║
║           "command": "npx",                                                  ║
║           "args": ["mcp-remote", "http://localhost:8000/mcp"]                ║
║         }                                                                    ║
║       }                                                                      ║
║     }                                                                        ║
║                                                                              ║
║  DOCUMENTATION: https://github.com/AiAscendant/mcp-browser-use              ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    """Entry point for MCP server."""
    transport = settings.server.transport

    if transport == "stdio":
        # stdio is deprecated - print migration guide and exit
        print(STDIO_DEPRECATION_MESSAGE, file=sys.stderr)
        sys.exit(1)
    elif transport in ("streamable-http", "sse"):
        logger.info(f"Starting MCP browser-use server (provider: {settings.llm.provider}, transport: {transport})")
        logger.info(f"HTTP server at http://{settings.server.host}:{settings.server.port}/mcp")
        server_instance.run(transport=transport, host=settings.server.host, port=settings.server.port)
    else:
        raise ValueError(f"Unknown transport: {transport}")


if __name__ == "__main__":
    main()
