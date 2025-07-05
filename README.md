[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/saik0s-mcp-browser-use-badge.png)](https://mseep.ai/app/saik0s-mcp-browser-use)

<img src="./assets/header.png" alt="Browser Use Web UI" width="full"/>

<br/>

# browser-use MCP server & CLI
[![Documentation](https://img.shields.io/badge/Documentation-📕-blue)](https://docs.browser-use.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> **Project Note**: This MCP server implementation builds upon the [browser-use/web-ui](https://github.com/browser-use/web-ui) foundation. Core browser automation logic and configuration patterns are adapted from the original project.

AI-driven browser automation server implementing the Model Context Protocol (MCP) for natural language browser control and web research. Also provides CLI access to its core functionalities.

<a href="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use"><img width="380" height="200" src="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use/badge" alt="Browser-Use MCP server" /></a>

## Features

-   🧠 **MCP Integration** - Full protocol implementation for AI agent communication.
-   🌐 **Browser Automation** - Page navigation, form filling, element interaction via natural language (`run_browser_agent` tool).
-   👁️ **Visual Understanding** - Optional screenshot analysis for vision-capable LLMs.
-   🔄 **State Persistence** - Option to manage a server browser session across multiple MCP calls or connect to user's browser.
-   🔌 **Multi-LLM Support** - Integrates with OpenAI, Anthropic, Azure, DeepSeek, Google, Mistral, Ollama, OpenRouter, Alibaba, Moonshot, Unbound AI.
-   🔍 **Deep Research Tool** - Dedicated tool for multi-step web research and report generation (`run_deep_research` tool).
-   ⚙️ **Environment Variable Configuration** - Fully configurable via environment variables using a structured Pydantic model.
-   🔗 **CDP Connection** - Ability to connect to and control a user-launched Chrome/Chromium instance via Chrome DevTools Protocol.
-   ⌨️ **CLI Interface** - Access core agent functionalities (`run_browser_agent`, `run_deep_research`) directly from the command line for testing and scripting.

## Quick Start

### The Essentials

1. Install UV - the rocket-powered Python installer:
`curl -LsSf https://astral.sh/uv/install.sh | sh`

2. Get Playwright browsers (required for automation):
`uvx --from mcp-server-browser-use@latest python -m playwright install`

### Integration Patterns

For MCP clients like Claude Desktop, add a server configuration that's as simple as:

```json
// Example 1: One-Line Latest Version (Always Fresh)
"mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["mcp-server-browser-use@latest"],
      "env": {
        "MCP_LLM_GOOGLE_API_KEY": "YOUR_KEY_HERE_IF_USING_GOOGLE",
        "MCP_LLM_PROVIDER": "google",
        "MCP_LLM_MODEL_NAME": "gemini-2.5-flash-preview-04-17",
        "MCP_BROWSER_HEADLESS": "true",
      }
    }
}
```

```json
// Example 2: Advanced Configuration with CDP
"mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["mcp-server-browser-use@latest"],
      "env": {
        "MCP_LLM_OPENROUTER_API_KEY": "YOUR_KEY_HERE_IF_USING_OPENROUTER",
        "MCP_LLM_PROVIDER": "openrouter",
        "MCP_LLM_MODEL_NAME": "anthropic/claude-3.5-haiku",
        "MCP_LLM_TEMPERATURE": "0.4",

        "MCP_BROWSER_HEADLESS": "false",
        "MCP_BROWSER_WINDOW_WIDTH": "1440",
        "MCP_BROWSER_WINDOW_HEIGHT": "1080",
        "MCP_AGENT_TOOL_USE_VISION": "true",

        "MCP_RESEARCH_TOOL_SAVE_DIR": "/path/to/your/research",
        "MCP_RESEARCH_TOOL_MAX_PARALLEL_BROWSERS": "5",

        "MCP_PATHS_DOWNLOADS": "/path/to/your/downloads",

        "MCP_BROWSER_USE_OWN_BROWSER": "true",
        "MCP_BROWSER_CDP_URL": "http://localhost:9222",

        "MCP_AGENT_TOOL_HISTORY_PATH": "/path/to/your/history",

        "MCP_SERVER_LOGGING_LEVEL": "DEBUG",
        "MCP_SERVER_LOG_FILE": "/path/to/your/log/mcp_server_browser_use.log",
      }
    }
}
```

```json
// Example 3: Advanced Configuration with User Data and custom chrome path
"mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": ["mcp-server-browser-use@latest"],
      "env": {
        "MCP_LLM_OPENAI_API_KEY": "YOUR_KEY_HERE_IF_USING_OPENAI",
        "MCP_LLM_PROVIDER": "openai",
        "MCP_LLM_MODEL_NAME": "gpt-4.1-mini",
        "MCP_LLM_TEMPERATURE": "0.2",

        "MCP_BROWSER_HEADLESS": "false",

        "MCP_BROWSER_BINARY_PATH": "/path/to/your/chrome/binary",
        "MCP_BROWSER_USER_DATA_DIR": "/path/to/your/user/data",
        "MCP_BROWSER_DISABLE_SECURITY": "true",
        "MCP_BROWSER_KEEP_OPEN": "true",
        "MCP_BROWSER_TRACE_PATH": "/path/to/your/trace",

        "MCP_AGENT_TOOL_HISTORY_PATH": "/path/to/your/history",

        "MCP_SERVER_LOGGING_LEVEL": "DEBUG",
        "MCP_SERVER_LOG_FILE": "/path/to/your/log/mcp_server_browser_use.log",
      }
    }
}
```

```json
// Example 4: Local Development Flow
"mcpServers": {
    "browser-use": {
      "command": "uv",
      "args": [
        "--directory",
        "/your/dev/path",
        "run",
        "mcp-server-browser-use"
      ],
      "env": {
        "MCP_LLM_OPENROUTER_API_KEY": "YOUR_KEY_HERE_IF_USING_OPENROUTER",
        "MCP_LLM_PROVIDER": "openrouter",
        "MCP_LLM_MODEL_NAME": "openai/gpt-4o-mini",
        "MCP_BROWSER_HEADLESS": "true",
      }
    }
}
```

**Key Insight:** The best configurations emerge from starting simple (Example 1). The .env.example file contains all possible dials.

## MCP Tools

This server exposes the following tools via the Model Context Protocol:

### Synchronous Tools (Wait for Completion)

1.  **`run_browser_agent`**
    *   **Description:** Executes a browser automation task based on natural language instructions and waits for it to complete. Uses settings from `MCP_AGENT_TOOL_*`, `MCP_LLM_*`, and `MCP_BROWSER_*` environment variables.
    *   **Arguments:**
        *   `task` (string, required): The primary task or objective.
    *   **Returns:** (string) The final result extracted by the agent or an error message. Agent history (JSON, optional GIF) saved if `MCP_AGENT_TOOL_HISTORY_PATH` is set.

2.  **`run_deep_research`**
    *   **Description:** Performs in-depth web research on a topic, generates a report, and waits for completion. Uses settings from `MCP_RESEARCH_TOOL_*`, `MCP_LLM_*`, and `MCP_BROWSER_*` environment variables. If `MCP_RESEARCH_TOOL_SAVE_DIR` is set, outputs are saved to a subdirectory within it; otherwise, operates in memory-only mode.
    *   **Arguments:**
        *   `research_task` (string, required): The topic or question for the research.
        *   `max_parallel_browsers` (integer, optional): Overrides `MCP_RESEARCH_TOOL_MAX_PARALLEL_BROWSERS` from environment.
    *   **Returns:** (string) The generated research report in Markdown format, including the file path (if saved), or an error message.

## CLI Usage

This package also provides a command-line interface `mcp-browser-cli` for direct testing and scripting.

**Global Options:**
*   `--env-file PATH, -e PATH`: Path to a `.env` file to load configurations from.
*   `--log-level LEVEL, -l LEVEL`: Override the logging level (e.g., `DEBUG`, `INFO`).

**Commands:**

1.  **`mcp-browser-cli run-browser-agent [OPTIONS] TASK`**
    *   **Description:** Runs a browser agent task.
    *   **Arguments:**
        *   `TASK` (string, required): The primary task for the agent.
    *   **Example:**
        ```bash
        mcp-browser-cli run-browser-agent "Go to example.com and find the title." -e .env
        ```

2.  **`mcp-browser-cli run-deep-research [OPTIONS] RESEARCH_TASK`**
    *   **Description:** Performs deep web research.
    *   **Arguments:**
        *   `RESEARCH_TASK` (string, required): The topic or question for research.
    *   **Options:**
        *   `--max-parallel-browsers INTEGER, -p INTEGER`: Override `MCP_RESEARCH_TOOL_MAX_PARALLEL_BROWSERS`.
    *   **Example:**
        ```bash
        mcp-browser-cli run-deep-research "What are the latest advancements in AI-driven browser automation?" --max-parallel-browsers 5 -e .env
        ```

All other configurations (LLM keys, paths, browser settings) are picked up from environment variables (or the specified `.env` file) as detailed in the Configuration section.

## Configuration (Environment Variables)

Configure the server and CLI using environment variables. You can set these in your system or place them in a `.env` file in the project root (use `--env-file` for CLI). Variables are structured with prefixes.

| Variable Group (Prefix)             | Example Variable                               | Description                                                                                                | Default Value                     |
| :---------------------------------- | :--------------------------------------------- | :--------------------------------------------------------------------------------------------------------- | :-------------------------------- |
| **Main LLM (MCP_LLM_)**             |                                                | Settings for the primary LLM used by agents.                                                               |                                   |
|                                     | `MCP_LLM_PROVIDER`                             | LLM provider. Options: `openai`, `azure_openai`, `anthropic`, `google`, `mistral`, `ollama`, etc.         | `openai`                          |
|                                     | `MCP_LLM_MODEL_NAME`                           | Specific model name for the provider.                                                                      | `gpt-4.1`                         |
|                                     | `MCP_LLM_TEMPERATURE`                          | LLM temperature (0.0-2.0).                                                                                 | `0.0`                             |
|                                     | `MCP_LLM_BASE_URL`                             | Optional: Generic override for LLM provider's base URL.                                                    | Provider-specific                 |
|                                     | `MCP_LLM_API_KEY`                              | Optional: Generic LLM API key (takes precedence).                                                          | -                                 |
|                                     | `MCP_LLM_OPENAI_API_KEY`                       | API Key for OpenAI (if provider is `openai`).                                                              | -                                 |
|                                     | `MCP_LLM_ANTHROPIC_API_KEY`                    | API Key for Anthropic.                                                                                     | -                                 |
|                                     | `MCP_LLM_GOOGLE_API_KEY`                       | API Key for Google AI (Gemini).                                                                            | -                                 |
|                                     | `MCP_LLM_AZURE_OPENAI_API_KEY`                 | API Key for Azure OpenAI.                                                                                  | -                                 |
|                                     | `MCP_LLM_AZURE_OPENAI_ENDPOINT`                | **Required if using Azure.** Your Azure resource endpoint.                                                 | -                                 |
|                                     | `MCP_LLM_OLLAMA_ENDPOINT`                      | Ollama API endpoint URL.                                                                                   | `http://localhost:11434`          |
|                                     | `MCP_LLM_OLLAMA_NUM_CTX`                       | Context window size for Ollama models.                                                                     | `32000`                           |
| **Planner LLM (MCP_LLM_PLANNER_)**  |                                                | Optional: Settings for a separate LLM for agent planning. Defaults to Main LLM if not set.                |                                   |
|                                     | `MCP_LLM_PLANNER_PROVIDER`                     | Planner LLM provider.                                                                                      | Main LLM Provider                 |
|                                     | `MCP_LLM_PLANNER_MODEL_NAME`                   | Planner LLM model name.                                                                                    | Main LLM Model                    |
| **Browser (MCP_BROWSER_)**          |                                                | General browser settings.                                                                                  |                                   |
|                                     | `MCP_BROWSER_HEADLESS`                         | Run browser without UI (general setting).                                                                  | `false`                           |
|                                     | `MCP_BROWSER_DISABLE_SECURITY`                 | Disable browser security features (general setting, use cautiously).                                       | `false`                           |
|                                     | `MCP_BROWSER_BINARY_PATH`                      | Path to Chrome/Chromium executable.                                                                        | -                                 |
|                                     | `MCP_BROWSER_USER_DATA_DIR`                    | Path to Chrome user data directory.                                                                        | -                                 |
|                                     | `MCP_BROWSER_WINDOW_WIDTH`                     | Browser window width (pixels).                                                                             | `1280`                            |
|                                     | `MCP_BROWSER_WINDOW_HEIGHT`                    | Browser window height (pixels).                                                                            | `1080`                            |
|                                     | `MCP_BROWSER_USE_OWN_BROWSER`                  | Connect to user's browser via CDP URL.                                                                     | `false`                           |
|                                     | `MCP_BROWSER_CDP_URL`                          | CDP URL (e.g., `http://localhost:9222`). Required if `MCP_BROWSER_USE_OWN_BROWSER=true`.                  | -                                 |
|                                     | `MCP_BROWSER_KEEP_OPEN`                        | Keep server-managed browser open between MCP calls (if `MCP_BROWSER_USE_OWN_BROWSER=false`).               | `false`                           |
|                                     | `MCP_BROWSER_TRACE_PATH`                       | Optional: Directory to save Playwright trace files. If not set, tracing to file is disabled.               | ` ` (empty, tracing disabled)     |
| **Agent Tool (MCP_AGENT_TOOL_)**    |                                                | Settings for the `run_browser_agent` tool.                                                                 |                                   |
|                                     | `MCP_AGENT_TOOL_MAX_STEPS`                     | Max steps per agent run.                                                                                   | `100`                             |
|                                     | `MCP_AGENT_TOOL_MAX_ACTIONS_PER_STEP`          | Max actions per agent step.                                                                                | `5`                               |
|                                     | `MCP_AGENT_TOOL_TOOL_CALLING_METHOD`           | Method for tool invocation ('auto', 'json_schema', 'function_calling').                                    | `auto`                            |
|                                     | `MCP_AGENT_TOOL_MAX_INPUT_TOKENS`              | Max input tokens for LLM context.                                                                          | `128000`                          |
|                                     | `MCP_AGENT_TOOL_USE_VISION`                    | Enable vision capabilities (screenshot analysis).                                                          | `true`                            |
|                                     | `MCP_AGENT_TOOL_HEADLESS`                      | Override `MCP_BROWSER_HEADLESS` for this tool (true/false/empty).                                          | ` ` (uses general)                |
|                                     | `MCP_AGENT_TOOL_DISABLE_SECURITY`              | Override `MCP_BROWSER_DISABLE_SECURITY` for this tool (true/false/empty).                                  | ` ` (uses general)                |
|                                     | `MCP_AGENT_TOOL_ENABLE_RECORDING`              | Enable Playwright video recording.                                                                         | `false`                           |
|                                     | `MCP_AGENT_TOOL_SAVE_RECORDING_PATH`           | Optional: Path to save recordings. If not set, recording to file is disabled even if `ENABLE_RECORDING=true`. | ` ` (empty, recording disabled)   |
|                                     | `MCP_AGENT_TOOL_HISTORY_PATH`                  | Optional: Directory to save agent history JSON files. If not set, history saving is disabled.              | ` ` (empty, history saving disabled) |
| **Research Tool (MCP_RESEARCH_TOOL_)** |                                             | Settings for the `run_deep_research` tool.                                                                 |                                   |
|                                     | `MCP_RESEARCH_TOOL_MAX_PARALLEL_BROWSERS`      | Max parallel browser instances for deep research.                                                          | `3`                               |
|                                     | `MCP_RESEARCH_TOOL_SAVE_DIR`                   | Optional: Base directory to save research artifacts. Task ID will be appended. If not set, operates in memory-only mode. | `None`                           |
| **Paths (MCP_PATHS_)**              |                                                | General path settings.                                                                                     |                                   |
|                                     | `MCP_PATHS_DOWNLOADS`                          | Optional: Directory for downloaded files. If not set, persistent downloads to a specific path are disabled.  | ` ` (empty, downloads disabled)  |
| **Server (MCP_SERVER_)**            |                                                | Server-specific settings.                                                                                  |                                   |
|                                     | `MCP_SERVER_LOG_FILE`                          | Path for the server log file. Empty for stdout.                                                            | ` ` (empty, logs to stdout)       |
|                                     | `MCP_SERVER_LOGGING_LEVEL`                     | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).                                           | `ERROR`                           |
|                                     | `MCP_SERVER_ANONYMIZED_TELEMETRY`              | Enable/disable anonymized telemetry (`true`/`false`).                                                      | `true`                            |
|                                     | `MCP_SERVER_MCP_CONFIG`                        | Optional: JSON string for MCP client config used by the internal controller.                               | `null`                            |

**Supported LLM Providers (`MCP_LLM_PROVIDER`):**
`openai`, `azure_openai`, `anthropic`, `google`, `mistral`, `ollama`, `deepseek`, `openrouter`, `alibaba`, `moonshot`, `unbound`

*(Refer to `.env.example` for a comprehensive list of all supported environment variables and their specific provider keys/endpoints.)*

## Connecting to Your Own Browser (CDP)

Instead of having the server launch and manage its own browser instance, you can connect it to a Chrome/Chromium browser that you launch and manage yourself.

**Steps:**

1.  **Launch Chrome/Chromium with Remote Debugging Enabled:**
    (Commands for macOS, Linux, Windows as previously listed, e.g., `google-chrome --remote-debugging-port=9222`)

2.  **Configure Environment Variables:**
    Set the following environment variables:
    ```dotenv
    MCP_BROWSER_USE_OWN_BROWSER=true
    MCP_BROWSER_CDP_URL=http://localhost:9222 # Use the same port
    # Optional: MCP_BROWSER_USER_DATA_DIR=/path/to/your/profile
    ```

3.  **Run the MCP Server or CLI:**
    Start the server (`uv run mcp-server-browser-use`) or CLI (`mcp-browser-cli ...`) as usual.

**Important Considerations:**
*   The browser launched with `--remote-debugging-port` must remain open.
*   Settings like `MCP_BROWSER_HEADLESS` and `MCP_BROWSER_KEEP_OPEN` are ignored when `MCP_BROWSER_USE_OWN_BROWSER=true`.

## Development

```bash
# Install dev dependencies and sync project deps
uv sync --dev

# Install playwright browsers
uv run playwright install

# Run MCP server with debugger (Example connecting to own browser via CDP)
# 1. Launch Chrome: google-chrome --remote-debugging-port=9222 --user-data-dir="optional/path/to/user/profile"
# 2. Run inspector command with environment variables:
npx @modelcontextprotocol/inspector@latest \
  -e MCP_LLM_GOOGLE_API_KEY=$GOOGLE_API_KEY \
  -e MCP_LLM_PROVIDER=google \
  -e MCP_LLM_MODEL_NAME=gemini-2.5-flash-preview-04-17 \
  -e MCP_BROWSER_USE_OWN_BROWSER=true \
  -e MCP_BROWSER_CDP_URL=http://localhost:9222 \
  -e MCP_RESEARCH_TOOL_SAVE_DIR=./tmp/dev_research_output \
  uv --directory . run mcp-server-browser-use

# Note: Change timeout in inspector's config panel if needed (default is 10 seconds)

# Run CLI example
# Create a .env file with your settings (including MCP_RESEARCH_TOOL_SAVE_DIR) or use environment variables
uv run mcp-browser-cli -e .env run-browser-agent "What is the title of example.com?"
uv run mcp-browser-cli -e .env run-deep-research "What is the best material for a pan for everyday use on amateur kitchen and dishwasher?"
```

## Troubleshooting

-   **Configuration Error on Startup**: If the application fails to start with an error about a missing setting, ensure all **mandatory** environment variables (like `MCP_RESEARCH_TOOL_SAVE_DIR`) are set correctly in your environment or `.env` file.
-   **Browser Conflicts**: If *not* using CDP (`MCP_BROWSER_USE_OWN_BROWSER=false`), ensure no conflicting Chrome instances are running with the same user data directory if `MCP_BROWSER_USER_DATA_DIR` is specified.
-   **CDP Connection Issues**: If using `MCP_BROWSER_USE_OWN_BROWSER=true`:
    *   Verify Chrome was launched with `--remote-debugging-port`.
    *   Ensure the port in `MCP_BROWSER_CDP_URL` matches.
    *   Check firewalls and ensure the browser is running.
-   **API Errors**: Double-check API keys (`MCP_LLM_<PROVIDER>_API_KEY` or `MCP_LLM_API_KEY`) and endpoints (e.g., `MCP_LLM_AZURE_OPENAI_ENDPOINT` for Azure).
-   **Vision Issues**: Ensure `MCP_AGENT_TOOL_USE_VISION=true` and your LLM supports vision.
-   **Dependency Problems**: Run `uv sync` and `uv run playwright install`.
-   **File/Path Issues**:
    *   If optional features like history saving, tracing, or downloads are not working, ensure the corresponding path variables (`MCP_AGENT_TOOL_HISTORY_PATH`, `MCP_BROWSER_TRACE_PATH`, `MCP_PATHS_DOWNLOADS`) are set and the application has write permissions to those locations.
    *   For deep research, ensure `MCP_RESEARCH_TOOL_SAVE_DIR` is set to a valid, writable directory.
-   **Logging**: Check the log file (`MCP_SERVER_LOG_FILE`, if set) or console output. Increase `MCP_SERVER_LOGGING_LEVEL` to `DEBUG` for more details. For CLI, use `--log-level DEBUG`.

## License

MIT - See [LICENSE](LICENSE) for details.
