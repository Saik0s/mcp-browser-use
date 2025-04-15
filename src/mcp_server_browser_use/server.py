import logging
import os
import traceback
from typing import Optional

from mcp.server.fastmcp import Context, FastMCP

log_file = os.getenv("LOG_FILE", "mcp_server_browser_use.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename=log_file,
    filemode="a",
)
logging.getLogger().addHandler(logging.NullHandler())
logging.getLogger().propagate = False


logger = logging.getLogger("mcp_server_browser_use")


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean value from environment variable."""
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


def serve() -> FastMCP:
    from mcp_server_browser_use.run_agents import (
        run_browser_agent as _run_browser_agent,
    )
    from mcp_server_browser_use.run_agents import run_deep_search as _run_deep_search
    from mcp_server_browser_use.utils import utils

    server = FastMCP("mcp_server_browser_use")

    @server.tool()
    async def run_browser_agent(ctx: Context, task: str, add_infos: str = "") -> str:
        """Runs a browser agent task synchronously and waits for the result."""

        try:
            (
                final_result,
                errors,
                model_actions,
                model_thoughts,
                gif_path,
                trace_file,
                history_file,
            ) = await _run_browser_agent(
                agent_type=os.getenv("MCP_AGENT_TYPE", "org"),
                llm_provider=os.getenv("MCP_MODEL_PROVIDER", "anthropic"),
                llm_model_name=os.getenv("MCP_MODEL_NAME", "claude-3-7-sonnet-20250219"),
                llm_num_ctx=16000,
                llm_temperature=float(os.getenv("MCP_TEMPERATURE", "0")),
                llm_base_url=os.getenv("MCP_BASE_URL"),
                llm_api_key=os.getenv("MCP_API_KEY"),
                use_own_browser=get_env_bool("MCP_USE_OWN_BROWSER", False),
                keep_browser_open=get_env_bool("MCP_KEEP_BROWSER_OPEN", False),
                headless=get_env_bool("MCP_HEADLESS", True),
                disable_security=get_env_bool("MCP_DISABLE_SECURITY", True),
                window_w=int(os.getenv("BROWSER_WINDOW_WIDTH", "1280")),
                window_h=int(os.getenv("BROWSER_WINDOW_HEIGHT", "720")),
                save_recording_path=os.getenv("MCP_SAVE_RECORDING_PATH"),
                save_agent_history_path=os.getenv("MCP_AGENT_HISTORY_PATH", "./tmp/agent_history"),
                save_trace_path=os.getenv("BROWSER_TRACE_PATH", "./tmp/trace"),
                enable_recording=get_env_bool("MCP_ENABLE_RECORDING", False),
                task=task,
                add_infos=add_infos,
                max_steps=int(os.getenv("MCP_MAX_STEPS", "100")),
                use_vision=get_env_bool("MCP_USE_VISION", True),
                max_actions_per_step=int(os.getenv("MCP_MAX_ACTIONS_PER_STEP", "5")),
                tool_calling_method=os.getenv("MCP_TOOL_CALLING_METHOD", "auto"),
                chrome_cdp=os.getenv("CHROME_CDP"),
                max_input_tokens=int(os.getenv("MCP_MAX_INPUT_TOKENS", "128000")),
            )

            if any(error is not None for error in errors):
                logger.error(f"Synchronous browser task '{task}' failed: {errors}")
                return f"Task failed: {errors}\n\nResult: {final_result}"
            else:
                logger.info(f"Synchronous browser task '{task}' completed.")
                return final_result

        except utils.MissingAPIKeyError as e:
            logger.error(f"Cannot run browser agent task '{task}': {e}")
            return f"Configuration Error: {str(e)}"
        except Exception as e:
            logger.error(f"Error running sync browser agent task '{task}': {e}\n{traceback.format_exc()}")
            return f"Error during task execution: {str(e)}"

    @server.tool()
    async def run_deep_search(
        ctx: Context,
        research_task: str,
        max_search_iteration_input: Optional[int] = 10,
        max_query_per_iter_input: Optional[int] = 3,
    ) -> str:
        """Performs deep search synchronously and waits for the report."""

        try:
            (
                markdown_content,
                file_path,
            ) = await _run_deep_search(
                research_task=research_task,
                max_search_iteration_input=max_search_iteration_input,
                max_query_per_iter_input=max_query_per_iter_input,
                llm_provider=os.getenv("MCP_MODEL_PROVIDER", "anthropic"),
                llm_model_name=os.getenv("MCP_MODEL_NAME", "claude-3-7-sonnet-20250219"),
                llm_num_ctx=16000,
                llm_temperature=float(os.getenv("MCP_TEMPERATURE", "0")),
                llm_base_url=os.getenv("MCP_BASE_URL"),
                llm_api_key=os.getenv("MCP_API_KEY"),
                use_vision=get_env_bool("MCP_USE_VISION", True),
                use_own_browser=get_env_bool("MCP_USE_OWN_BROWSER", False),
                headless=get_env_bool("BROWSER_HEADLESS", True),
                chrome_cdp=os.getenv("CHROME_CDP"),
            )

            return f"Deep research report generated successfully at {file_path}\n\n{markdown_content}"

        except utils.MissingAPIKeyError as e:
            logger.error(f"Cannot run deep research task '{research_task}': {e}")
            return f"Configuration Error: {str(e)}"
        except Exception as e:
            logger.error(f"Error running sync deep research task '{research_task}': {e}\n{traceback.format_exc()}")
            return f"Error during deep research execution: {str(e)}"

    return server


server = serve()


def main():
    server.run()


if __name__ == "__main__":
    main()
