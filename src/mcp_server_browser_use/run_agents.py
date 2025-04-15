import logging
import os
import asyncio

from browser_use.agent.service import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContextConfig, BrowserContextWindowSize

from mcp_server_browser_use.agent.custom_agent import CustomAgent
from mcp_server_browser_use.agent.custom_prompts import (
    CustomAgentMessagePrompt,
    CustomSystemPrompt,
)
from mcp_server_browser_use.browser.custom_browser import CustomBrowser
from mcp_server_browser_use.controller.custom_controller import CustomController
from mcp_server_browser_use.utils import utils
from mcp_server_browser_use.utils.agent_state import AgentState
from mcp_server_browser_use.utils.utils import MissingAPIKeyError, get_latest_files, RateLimiter

logger = logging.getLogger(__name__)

# Global variables for persistence
_global_browser = None
_global_browser_context = None
_global_agent = None

# Create the global agent state instance
_global_agent_state = AgentState()


async def stop_agent():
    """Request the agent to stop and update UI with enhanced feedback"""
    global _global_agent

    try:
        if _global_agent is not None:
            # Request stop
            _global_agent.stop()
        # Update UI immediately
        message = "Stop requested - the agent will halt at the next safe point"
        logger.info(f"🛑 {message}")

    except Exception as e:
        error_msg = f"Error during stop: {str(e)}"
        logger.error(error_msg)


async def stop_research_agent():
    """Request the agent to stop and update UI with enhanced feedback"""
    global _global_agent_state

    try:
        # Request stop
        _global_agent_state.request_stop()

        # Update UI immediately
        message = "Stop requested - the agent will halt at the next safe point"
        logger.info(f"🛑 {message}")

    except Exception as e:
        error_msg = f"Error during stop: {str(e)}"
        logger.error(error_msg)


async def run_browser_agent(
    agent_type,
    llm_provider,
    llm_model_name,
    llm_num_ctx,
    llm_temperature,
    llm_base_url,
    llm_api_key,
    use_own_browser,
    keep_browser_open,
    headless,
    disable_security,
    window_w,
    window_h,
    save_recording_path,
    save_agent_history_path,
    save_trace_path,
    enable_recording,
    task,
    add_infos,
    max_steps,
    use_vision,
    max_actions_per_step,
    tool_calling_method,
    chrome_cdp,
    max_input_tokens,
):
    # Initialize the rate limiter
    rate_limiter = RateLimiter()
    await rate_limiter.acquire()
    logger.info("Rate limit check passed, initializing browser agent")
    
    try:
        # Disable recording if the checkbox is unchecked
        if not enable_recording:
            save_recording_path = None

        # Ensure the recording directory exists if recording is enabled
        if save_recording_path:
            os.makedirs(save_recording_path, exist_ok=True)
            
        global _global_browser, _global_browser_context, _global_agent
        llm = utils.get_llm_model(
            provider=llm_provider,
            model_name=llm_model_name,
            num_ctx=llm_num_ctx,
            temperature=llm_temperature,
            base_url=llm_base_url,
            api_key=llm_api_key,
            tool_calling_method=tool_calling_method,
            max_input_tokens=max_input_tokens,
        )

        if agent_type == "org":
            (
                final_result,
                errors,
                model_actions,
                model_thoughts,
                gif_path,
                trace_file,
                history_file,
            ) = await run_org_agent(
                llm,
                use_own_browser,
                keep_browser_open,
                headless,
                disable_security,
                window_w,
                window_h,
                save_recording_path,
                save_agent_history_path,
                save_trace_path,
                task,
                add_infos,
                max_steps,
                use_vision,
                max_actions_per_step,
                chrome_cdp,
            )
        else:
            (
                final_result,
                errors,
                model_actions,
                model_thoughts,
                gif_path,
                trace_file,
                history_file,
            ) = await run_custom_agent(
                llm,
                use_own_browser,
                keep_browser_open,
                headless,
                disable_security,
                window_w,
                window_h,
                save_recording_path,
                save_agent_history_path,
                save_trace_path,
                task,
                add_infos,
                max_steps,
                use_vision,
                max_actions_per_step,
                tool_calling_method,
                chrome_cdp,
                max_input_tokens,
            )

        return (
            final_result,
            errors,
            model_actions,
            model_thoughts,
            gif_path,
            trace_file,
            history_file,
        )
    except MissingAPIKeyError as e:
        logger.error(str(e))
        raise e
    except Exception as e:
        import traceback

        error_msg = f"Error during browser agent run: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return (
            "Error: Task failed due to a system error. Please try again later.",
            [str(e)],
            [],
            [],
            None,
            None,
            None,
        )


async def run_org_agent(
    llm,
    use_own_browser,
    keep_browser_open,
    headless,
    disable_security,
    window_w,
    window_h,
    save_recording_path,
    save_agent_history_path,
    save_trace_path,
    task,
    max_steps,
    use_vision,
    max_actions_per_step,
    tool_calling_method,
    chrome_cdp,
    max_input_tokens,
):
    try:
        global _global_browser, _global_browser_context, _global_agent

        extra_chromium_args = [f"--window-size={window_w},{window_h}"]
        cdp_url = chrome_cdp

        if use_own_browser:
            cdp_url = os.getenv("CHROME_CDP", chrome_cdp)
            chrome_path = os.getenv("CHROME_PATH", None)
            if chrome_path == "":
                chrome_path = None
            chrome_user_data = os.getenv("CHROME_USER_DATA", None)
            if chrome_user_data:
                extra_chromium_args += [f"--user-data-dir={chrome_user_data}"]
        else:
            chrome_path = None

        if _global_browser is None:
            _global_browser = Browser(
                config=BrowserConfig(
                    headless=headless,
                    cdp_url=cdp_url,
                    disable_security=disable_security,
                    chrome_instance_path=chrome_path,
                    extra_chromium_args=extra_chromium_args,
                )
            )

        if _global_browser_context is None:
            _global_browser_context = await _global_browser.new_context(
                config=BrowserContextConfig(
                    trace_path=save_trace_path if save_trace_path else None,
                    save_recording_path=(save_recording_path if save_recording_path else None),
                    no_viewport=False,
                    browser_window_size=BrowserContextWindowSize(width=window_w, height=window_h),
                )
            )

        if _global_agent is None:
            _global_agent = Agent(
                task=task,
                llm=llm,
                use_vision=use_vision,
                browser=_global_browser,
                browser_context=_global_browser_context,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method,
                max_input_tokens=max_input_tokens,
                generate_gif=True,
            )
        history = await _global_agent.run(max_steps=max_steps)

        history_file = os.path.join(save_agent_history_path, f"{_global_agent.state.agent_id}.json")
        _global_agent.save_history(history_file)

        final_result = history.final_result()
        errors = history.errors()
        model_actions = history.model_actions()
        model_thoughts = history.model_thoughts()

        trace_file = get_latest_files(save_trace_path)

        gif_path = os.path.join(os.path.dirname(__file__), "agent_history.gif")

        return (
            final_result,
            errors,
            model_actions,
            model_thoughts,
            gif_path,
            trace_file.get(".zip"),
            history_file,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        errors = str(e) + "\n" + traceback.format_exc()
        return "", errors, "", "", None, None
    finally:
        _global_agent = None
        # Handle cleanup based on persistence configuration
        if not keep_browser_open:
            if _global_browser_context:
                await _global_browser_context.close()
                _global_browser_context = None

            if _global_browser:
                await _global_browser.close()
                _global_browser = None


async def run_custom_agent(
    llm,
    use_own_browser,
    keep_browser_open,
    headless,
    disable_security,
    window_w,
    window_h,
    save_recording_path,
    save_agent_history_path,
    save_trace_path,
    task,
    add_infos,
    max_steps,
    use_vision,
    max_actions_per_step,
    tool_calling_method,
    chrome_cdp,
    max_input_tokens,
):
    try:
        global _global_browser, _global_browser_context, _global_agent

        extra_chromium_args = [f"--window-size={window_w},{window_h}"]
        cdp_url = chrome_cdp
        if use_own_browser:
            cdp_url = os.getenv("CHROME_CDP", chrome_cdp)

            chrome_path = os.getenv("CHROME_PATH", None)
            if chrome_path == "":
                chrome_path = None
            chrome_user_data = os.getenv("CHROME_USER_DATA", None)
            if chrome_user_data:
                extra_chromium_args += [f"--user-data-dir={chrome_user_data}"]
        else:
            chrome_path = None

        controller = CustomController()

        # Initialize global browser if needed
        # if chrome_cdp not empty string nor None
        if (_global_browser is None) or (cdp_url and cdp_url != "" and cdp_url != None):  # noqa: E711
            _global_browser = CustomBrowser(
                config=BrowserConfig(
                    headless=headless,
                    disable_security=disable_security,
                    cdp_url=cdp_url,
                    chrome_instance_path=chrome_path,
                    extra_chromium_args=extra_chromium_args,
                )
            )

        if _global_browser_context is None or (chrome_cdp and cdp_url != "" and cdp_url != None):  # noqa: E711
            _global_browser_context = await _global_browser.new_context(
                config=BrowserContextConfig(
                    trace_path=save_trace_path if save_trace_path else None,
                    save_recording_path=(save_recording_path if save_recording_path else None),
                    no_viewport=False,
                    browser_window_size=BrowserContextWindowSize(width=window_w, height=window_h),
                )
            )

        # Create and run agent
        if _global_agent is None:
            _global_agent = CustomAgent(
                task=task,
                add_infos=add_infos,
                use_vision=use_vision,
                llm=llm,
                browser=_global_browser,
                browser_context=_global_browser_context,
                controller=controller,
                system_prompt_class=CustomSystemPrompt,
                agent_prompt_class=CustomAgentMessagePrompt,
                max_actions_per_step=max_actions_per_step,
                tool_calling_method=tool_calling_method,
                max_input_tokens=max_input_tokens,
                generate_gif=True,
            )
        history = await _global_agent.run(max_steps=max_steps)

        history_file = os.path.join(save_agent_history_path, f"{_global_agent.state.agent_id}.json")
        _global_agent.save_history(history_file)

        final_result = history.final_result()
        errors = history.errors()
        model_actions = history.model_actions()
        model_thoughts = history.model_thoughts()

        trace_file = get_latest_files(save_trace_path)

        gif_path = os.path.join(os.path.dirname(__file__), "agent_history.gif")

        return (
            final_result,
            errors,
            model_actions,
            model_thoughts,
            gif_path,
            trace_file.get(".zip"),
            history_file,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        errors = str(e) + "\n" + traceback.format_exc()
        return "", errors, "", "", None, None
    finally:
        _global_agent = None
        # Handle cleanup based on persistence configuration
        if not keep_browser_open:
            if _global_browser_context:
                await _global_browser_context.close()
                _global_browser_context = None

            if _global_browser:
                await _global_browser.close()
                _global_browser = None


async def close_global_browser():
    global _global_browser, _global_browser_context

    if _global_browser_context:
        await _global_browser_context.close()
        _global_browser_context = None

    if _global_browser:
        await _global_browser.close()
        _global_browser = None


async def run_deep_search(
    research_task,
    max_search_iteration_input,
    max_query_per_iter_input,
    llm_provider,
    llm_model_name,
    llm_num_ctx,
    llm_temperature,
    llm_base_url,
    llm_api_key,
    use_vision,
    use_own_browser,
    headless,
    chrome_cdp,
):
    from mcp_server_browser_use.utils.deep_research import deep_research

    # Initialize the rate limiter
    rate_limiter = RateLimiter()
    await rate_limiter.acquire()
    logger.info("Rate limit check passed, initializing deep research")

    try:
        global _global_agent_state

        # Clear any previous stop requests
        _global_agent_state.clear_stop()

        llm = utils.get_llm_model(
            provider=llm_provider,
            model_name=llm_model_name,
            num_ctx=llm_num_ctx,
            temperature=llm_temperature,
            base_url=llm_base_url,
            api_key=llm_api_key,
        )

        # Get max duration from env or default to 240 seconds (4 minutes)
        max_duration_seconds = int(os.getenv("MCP_MAX_DURATION_SECONDS", "240"))
        
        # Run the deep research
        markdown_content, file_path = await deep_research(
            task=research_task,
            llm=llm,
            agent_state=_global_agent_state,
            max_search_iterations=max_search_iteration_input,
            max_query_num=max_query_per_iter_input,
            max_duration_seconds=max_duration_seconds,
            use_vision=use_vision,
            use_own_browser=use_own_browser,
            headless=headless,
            chrome_cdp=chrome_cdp,
        )

        return markdown_content, file_path
    except MissingAPIKeyError as e:
        logger.error(str(e))
        raise e
    except Exception as e:
        import traceback

        logger.error(f"Error during deep search: {str(e)}\n{traceback.format_exc()}")
        raise e
