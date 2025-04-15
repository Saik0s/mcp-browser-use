<img src="./assets/web-ui.png" alt="Browser Use Web UI" width="full"/>

<br/>

# browser-use MCP server
[![Documentation](https://img.shields.io/badge/Documentation-📕-blue)](https://docs.browser-use.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> **Project Note**: This MCP server implementation builds upon the [browser-use/web-ui](https://github.com/browser-use/web-ui) foundation. Core browser automation logic and configuration patterns are adapted from the original project.

AI-driven browser automation server implementing the Model Context Protocol (MCP) for natural language browser control and web research.

<a href="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use"><img width="380" height="200" src="https://glama.ai/mcp/servers/@Saik0s/mcp-browser-use/badge" alt="Browser-Use MCP server" /></a>

## Features

-   🧠 **MCP Integration** - Full protocol implementation for AI agent communication.
-   🌐 **Browser Automation** - Page navigation, form filling, element interaction via natural language (`run_browser_agent` tool).
-   👁️ **Visual Understanding** - Optional screenshot analysis for vision-capable LLMs.
-   🔄 **State Persistence** - Option to manage a browser session across multiple MCP calls or connect to user's browser.
-   🔌 **Multi-LLM Support** - Integrates with OpenAI, Anthropic, Azure, DeepSeek, Google, Mistral, Ollama, OpenRouter, Alibaba, Moonshot, Unbound AI.
-   🔍 **Deep Research Tool** - Dedicated tool for multi-step web research and report generation (`run_deep_search` tool).
-   ⚙️ **Environment Variable Configuration** - Fully configurable via environment variables.
-   🔗 **CDP Connection** - Ability to connect to and control a user-launched Chrome/Chromium instance via Chrome DevTools Protocol.

## Quick Start

### Prerequisites

-   Python 3.11 or higher
-   `uv` (fast Python package installer): `pip install uv`
-   Chrome/Chromium browser installed
-   Install Playwright browsers: `uv sync` and then `uv run playwright install`

### Integration with MCP Clients (e.g., Claude Desktop)

You can configure clients like Claude Desktop to connect to this server. Add the following structure to the client's configuration (e.g., `claude_desktop_config.json`), adjusting the path and environment variables as needed:

```json
// Example for Claude Desktop config
"mcpServers": {
    "browser-use": {
      // Option 1: Run installed package
      // "command": "uvx",
      // "args": ["mcp-server-browser-use"],

      // Option 2: Run from local development source
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-server-browser-use",
        "run",
        "mcp-server-browser-use"
      ],
      "env": {
        // --- CRITICAL: Add required API keys here ---
        "OPENROUTER_API_KEY": "YOUR_OPENROUTER_API_KEY",
        // "OPENAI_API_KEY": "YOUR_KEY_HERE_IF_USING_OPENAI",
        // "ANTHROPIC_API_KEY": "YOUR_KEY_HERE_IF_USING_ANTHROPIC",
        // ... add other keys based on MCP_MODEL_PROVIDER ...

        // --- Optional Overrides (defaults are usually fine) ---
        "MCP_MODEL_PROVIDER": "openrouter", // Use OpenRouter as provider
        "MCP_MODEL_NAME": "google/gemini-2.5-pro-exp-03-25:free", // Example OpenRouter model
        "BROWSER_HEADLESS": "true",    // Default: run browser without UI
        "BROWSER_USE_LOGGING_LEVEL": "INFO",

        // --- Example for connecting to your own browser ---
        // "MCP_USE_OWN_BROWSER": "true",
        // "CHROME_CDP": "http://localhost:9222",

        // Ensure Python uses UTF-8
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1"
      }
    }
}
```

**Important:** Ensure the `command` and `args` correctly point to how you want to run the server (either the installed package or from the source directory). Set the necessary API keys in the `env` section.

## MCP Tools

This server exposes the following tools via the Model Context Protocol:

### Synchronous Tools (Wait for Completion)

1.  **`run_browser_agent`**
    *   **Description:** Executes a browser automation task based on natural language instructions and waits for it to complete. Uses settings prefixed with `MCP_` (e.g., `MCP_HEADLESS`, `MCP_MAX_STEPS`).
    *   **Arguments:**
        *   `task` (string, required): The primary task or objective.
        *   `add_infos` (string, optional): Additional context or hints for the agent (used by `custom` agent type).
    *   **Returns:** (string) The final result extracted by the agent or an error message.

2.  **`run_deep_search`**
    *   **Description:** Performs in-depth web research on a topic, generates a report, and waits for completion. Uses settings prefixed with `MCP_RESEARCH_` and general `BROWSER_` settings (e.g., `BROWSER_HEADLESS`).
    *   **Arguments:**
        *   `research_task` (string, required): The topic or question for the research.
        *   `max_search_iterations` (integer, optional, default: 10): Max search cycles.
        *   `max_query_per_iteration` (integer, optional, default: 3): Max search queries per cycle.
    *   **Returns:** (string) The generated research report in Markdown format, including the file path, or an error message.

## Configuration (Environment Variables)

Configure the server using environment variables. You can set these in your system or place them in a `.env` file in the project root.

| Variable                        | Description                                                                                             | Required?                      | Default Value                     | Example Value                     |
| :------------------------------ | :------------------------------------------------------------------------------------------------------ | :----------------------------- | :-------------------------------- | :-------------------------------- |
| **LLM Settings**                |                                                                                                         |                                |                                   |                                   |
| `MCP_MODEL_PROVIDER`            | LLM provider to use. See options below.                                                                 | **Yes**                        | `anthropic`                       | `openrouter`                      |
| `MCP_MODEL_NAME`                | Specific model name for the chosen provider.                                                            | No                             | `claude-3-7-sonnet-20250219`      | `anthropic/claude-3.7-sonnet` |
| `MCP_TEMPERATURE`               | LLM temperature (0.0-2.0). Controls randomness.                                                         | No                             | `0.0`                             | `0.7`                             |
| `MCP_TOOL_CALLING_METHOD`       | Method for tool invocation ('auto', 'json_schema', 'function_calling'). Affects `run_browser_agent`.    | No                             | `auto`                            | `json_schema`                     |
| `MCP_MAX_INPUT_TOKENS`          | Max input tokens for LLM context for `run_browser_agent`.                                               | No                             | `128000`                          | `64000`                           |
| `MCP_BASE_URL`                  | Optional: Generic override for the LLM provider's base URL.                                             | No                             | Provider-specific                 | `http://localhost:8080/v1`        |
| `MCP_API_KEY`                   | Optional: Generic override for the LLM provider's API key (takes precedence over provider-specific keys). | No                             | -                                 | `sk-...`                          |
| **Provider API Keys**           | **Required based on `MCP_MODEL_PROVIDER` unless `MCP_API_KEY` is set.**                                 |                                |                                   |                                   |
| `OPENAI_API_KEY`                | API Key for OpenAI.                                                                                     | If Used                        | -                                 | `sk-...`                          |
| `ANTHROPIC_API_KEY`             | API Key for Anthropic.                                                                                  | If Used                        | -                                 | `sk-ant-...`                      |
| `GOOGLE_API_KEY`                | API Key for Google AI (Gemini).                                                                         | If Used                        | -                                 | `AIza...`                         |
| `AZURE_OPENAI_API_KEY`          | API Key for Azure OpenAI.                                                                               | If Used                        | -                                 | `...`                             |
| `DEEPSEEK_API_KEY`              | API Key for DeepSeek.                                                                                   | If Used                        | -                                 | `sk-...`                          |
| `MISTRAL_API_KEY`               | API Key for Mistral AI.                                                                                 | If Used                        | -                                 | `...`                             |
| `OPENROUTER_API_KEY`            | API Key for OpenRouter.                                                                                 | If Used                        | -                                 | `sk-or-...`                       |
| `ALIBABA_API_KEY`               | API Key for Alibaba Cloud (DashScope).                                                                  | If Used                        | -                                 | `sk-...`                          |
| `MOONSHOT_API_KEY`              | API Key for Moonshot AI.                                                                                | If Used                        | -                                 | `sk-...`                          |
| `UNBOUND_API_KEY`               | API Key for Unbound AI.                                                                                 | If Used                        | -                                 | `...`                             |
| **Provider Endpoints**          | Optional: Override default API endpoints.                                                               |                                |                                   |                                   |
| `OPENAI_ENDPOINT`               | OpenAI API endpoint URL.                                                                                | No                             | `https://api.openai.com/v1`       |                                   |
| `ANTHROPIC_ENDPOINT`            | Anthropic API endpoint URL.                                                                             | No                             | `https://api.anthropic.com`       |                                   |
| `AZURE_OPENAI_ENDPOINT`         | **Required if using Azure.** Your Azure resource endpoint.                                              | If Used                        | -                                 | `https://res.openai.azure.com/` |
| `AZURE_OPENAI_API_VERSION`      | Azure API version.                                                                                      | No                             | `2025-01-01-preview`              | `2023-12-01-preview`              |
| `DEEPSEEK_ENDPOINT`             | DeepSeek API endpoint URL.                                                                              | No                             | `https://api.deepseek.com`        |                                   |
| `MISTRAL_ENDPOINT`              | Mistral API endpoint URL.                                                                               | No                             | `https://api.mistral.ai/v1`       |                                   |
| `OLLAMA_ENDPOINT`               | Ollama API endpoint URL.                                                                                | No                             | `http://localhost:11434`          | `http://ollama.local:11434`       |
| `OPENROUTER_ENDPOINT`           | OpenRouter API endpoint URL.                                                                            | No                             | `https://openrouter.ai/api/v1`    |                                   |
| `ALIBABA_ENDPOINT`              | Alibaba (DashScope) API endpoint URL.                                                                   | No                             | `https://dashscope...v1`          |                                   |
| `MOONSHOT_ENDPOINT`             | Moonshot API endpoint URL.                                                                              | No                             | `https://api.moonshot.cn/v1`      |                                   |
| `UNBOUND_ENDPOINT`              | Unbound AI API endpoint URL.                                                                            | No                             | `https://api.getunbound.ai`       |                                   |
| **Ollama Specific**             |                                                                                                         |                                |                                   |                                   |
| `OLLAMA_NUM_CTX`                | Context window size for Ollama models.                                                                  | No                             | `32000`                           | `8192`                            |
| `OLLAMA_NUM_PREDICT`            | Max tokens to predict for Ollama models.                                                                | No                             | `1024`                            | `2048`                            |
| **Agent Settings (`run_browser_agent`)** |                                                                                                 |                                |                                   |                                   |
| `MCP_AGENT_TYPE`                | Agent implementation for `run_browser_agent` ('org' or 'custom').                                       | No                             | `org`                             | `custom`                          |
| `MCP_MAX_STEPS`                 | Max steps per agent run.                                                                                | No                             | `100`                             | `50`                              |
| `MCP_USE_VISION`                | Enable vision capabilities (screenshot analysis).                                                       | No                             | `true`                            | `false`                           |
| `MCP_MAX_ACTIONS_PER_STEP`      | Max actions per agent step.                                                                             | No                             | `5`                               | `10`                              |
| `MCP_KEEP_BROWSER_OPEN`         | Keep browser managed by server open between `run_browser_agent` calls (if `MCP_USE_OWN_BROWSER=false`). | No                             | `false`                           | `true`                            |
| `MCP_ENABLE_RECORDING`          | Enable Playwright video recording for `run_browser_agent`.                                              | No                             | `false`                           | `true`                            |
| `MCP_SAVE_RECORDING_PATH`       | Path to save agent run video recordings (Required if `MCP_ENABLE_RECORDING=true`).                      | If Recording                   | -                                 | `./tmp/recordings`                |
| `MCP_AGENT_HISTORY_PATH`        | Directory to save agent history JSON files.                                                             | No                             | `./tmp/agent_history`             | `./agent_runs`                    |
| `MCP_HEADLESS`                  | Run browser without UI specifically for `run_browser_agent` tool.                                       | No                             | `true`                            | `false`                           |
| `MCP_DISABLE_SECURITY`          | Disable browser security features specifically for `run_browser_agent` tool (use cautiously).           | No                             | `true`                            | `false`                           |
| **Deep Research Settings (`run_deep_search`)** |                                                                                         |                                |                                   |                                   |
| `MCP_RESEARCH_MAX_ITERATIONS`   | Max search iterations for deep research.                                                                | No                             | `10`                              | `5`                               |
| `MCP_RESEARCH_MAX_QUERY`        | Max search queries per iteration.                                                                       | No                             | `3`                               | `5`                               |
| `MCP_RESEARCH_USE_OWN_BROWSER`  | Use a separate browser instance for research (requires `CHROME_CDP` if `MCP_USE_OWN_BROWSER=true`).     | No                             | `false`                           | `true`                            |
| `MCP_RESEARCH_SAVE_DIR`         | Directory to save research artifacts (report, results).                                                 | No                             | `./tmp/deep_research/{task_id}`   | `./research_output`               |
| `MCP_RESEARCH_AGENT_MAX_STEPS`  | Max steps for sub-agents within deep research.                                                          | No                             | `10`                              | `15`                              |
| **Browser Settings (General & Specific Tool Overrides)** |                                                                                |                                |                                   |                                   |
| `MCP_USE_OWN_BROWSER`           | Set to true to connect to user's browser via `CHROME_CDP` instead of launching a new one.               | No                             | `false`                           | `true`                            |
| `CHROME_CDP`                    | Connect to existing Chrome via DevTools Protocol URL. Required if `MCP_USE_OWN_BROWSER=true`.           | If `MCP_USE_OWN_BROWSER=true`  | -                                 | `http://localhost:9222`           |
| `BROWSER_HEADLESS`              | Run browser without visible UI. Primarily affects `run_deep_search`. See also `MCP_HEADLESS`.           | No                             | `true`                            | `false`                           |
| `BROWSER_DISABLE_SECURITY`      | General browser security setting. See also `MCP_DISABLE_SECURITY`.                                      | No                             | `false`                           | `true`                            |
| `CHROME_PATH`                   | Path to Chrome/Chromium executable.                                                                     | No                             | -                                 | `/usr/bin/chromium-browser`       |
| `CHROME_USER_DATA`              | Path to Chrome user data directory (for persistent sessions, useful with `CHROME_CDP`).                 | No                             | -                                 | `~/.config/google-chrome/Profile 1` |
| `BROWSER_TRACE_PATH`            | Directory to save Playwright trace files (useful for debugging).                                        | No                             | `./tmp/trace`                     | `./traces`                        |
| `BROWSER_WINDOW_WIDTH`          | Browser window width (pixels).                                                                          | No                             | `1280`                            | `1920`                            |
| `BROWSER_WINDOW_HEIGHT`         | Browser window height (pixels).                                                                         | No                             | `720`                             | `1080`                            |
| **Server & Logging**            |                                                                                                         |                                |                                   |                                   |
| `LOG_FILE`                      | Path for the server log file.                                                                           | No                             | `mcp_server_browser_use.log`      | `/var/log/mcp_browser.log`        |
| `BROWSER_USE_LOGGING_LEVEL`     | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`).                                        | No                             | `INFO`                            | `DEBUG`                           |
| `ANONYMIZED_TELEMETRY`          | Enable/disable anonymized telemetry (`true`/`false`).                                                   | No                             | `true`                            | `false`                           |
| `REQUESTS_PER_MINUTE`           | Maximum number of requests to allow per minute (rate limiting).                                         | No                             | `15`                              | `30`                              |

**Supported LLM Providers (`MCP_MODEL_PROVIDER`):**

`openai`, `azure_openai`, `anthropic`, `google`, `mistral`, `ollama`, `deepseek`, `openrouter`, `alibaba`, `moonshot`, `unbound`

## Connecting to Your Own Browser (CDP)

Instead of having the server launch and manage its own browser instance, you can connect it to a Chrome/Chromium browser that you launch and manage yourself. This is useful for:

*   Using your existing browser profile (cookies, logins, extensions).
*   Observing the automation directly in your own browser window.
*   Debugging complex scenarios.

**Steps:**

1.  **Launch Chrome/Chromium with Remote Debugging Enabled:**
    Open your terminal or command prompt and run the command appropriate for your operating system. This tells Chrome to listen for connections on a specific port (e.g., 9222).

    *   **macOS:**
        ```bash
        /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
        ```
        *(Adjust the path if Chrome is installed elsewhere)*

    *   **Linux:**
        ```bash
        google-chrome --remote-debugging-port=9222
        # or
        chromium-browser --remote-debugging-port=9222
        ```

    *   **Windows (Command Prompt):**
        ```cmd
        "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
        ```
        *(Adjust the path to your Chrome installation if necessary)*

    *   **Windows (PowerShell):**
        ```powershell
        & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
        ```
        *(Adjust the path to your Chrome installation if necessary)*

    **Note:** If port 9222 is already in use, choose a different port (e.g., 9223) and use that same port in the `CHROME_CDP` environment variable.

2.  **Configure Environment Variables:**
    Set the following environment variables in your `.env` file or system environment before starting the MCP server:

    ```dotenv
    MCP_USE_OWN_BROWSER=true
    CHROME_CDP=http://localhost:9222 # Use the same port you launched Chrome with
    ```
    *   `MCP_USE_OWN_BROWSER=true`: Tells the server to connect to an existing browser instead of launching one.
    *   `CHROME_CDP`: Specifies the URL where the server can connect to your browser's DevTools Protocol endpoint.

3.  **Run the MCP Server:**
    Start the server as usual:
    ```bash
    uv run mcp-server-browser-use
    ```

Now, when you use the `run_browser_agent` or `run_deep_search` tools, the server will connect to your running Chrome instance instead of creating a new one.

**Important Considerations:**

*   The browser launched with `--remote-debugging-port` must remain open while the MCP server is running and needs to interact with it.
*   Ensure the `CHROME_CDP` URL is accessible from where the MCP server is running (usually `http://localhost:PORT` if running on the same machine).
*   Using your own browser means the server inherits its state (open tabs, logged-in sessions). Be mindful of this during automation.
*   Settings like `MCP_HEADLESS`, `BROWSER_HEADLESS`, `MCP_KEEP_BROWSER_OPEN` are ignored when `MCP_USE_OWN_BROWSER=true`. Window size is determined by your browser window.

## Development

```bash
# Install dev dependencies and sync project deps
uv sync --dev

# Install playwright browsers
uv run playwright install

# Run with debugger (Example connecting to own browser via CDP)
# 1. Launch Chrome: google-chrome --remote-debugging-port=9222
# 2. Run inspector command:
npx @modelcontextprotocol/inspector@latest \
  -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
  -e MCP_MODEL_PROVIDER=openrouter \
  -e MCP_MODEL_NAME=anthropic/claude-3.7-sonnet \
  -e MCP_USE_OWN_BROWSER=true \
  -e CHROME_CDP=http://localhost:9222 \
  uv --directory . run mcp run src/mcp_server_browser_use/server.py
# Note: Change timeout in inspector's config panel if needed (default is 10 seconds)
```

## Troubleshooting

-   **Browser Conflicts**: If *not* using `CHROME_CDP` (`MCP_USE_OWN_BROWSER=false`), ensure no other conflicting Chrome instances are running with the same user data directory if `CHROME_USER_DATA` is specified.
-   **CDP Connection Issues**: If using `MCP_USE_OWN_BROWSER=true`:
    *   Verify Chrome was launched with the `--remote-debugging-port` flag.
    *   Ensure the port in `CHROME_CDP` matches the port used when launching Chrome.
    *   Check for firewall issues blocking the connection to the specified port.
    *   Make sure the browser is still running.
-   **API Errors**: Double-check that the correct API key environment variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) is set for your chosen `MCP_MODEL_PROVIDER`, or that `MCP_API_KEY` is set. Verify keys and endpoints (`AZURE_OPENAI_ENDPOINT` is required for Azure).
-   **Vision Issues**: Ensure `MCP_USE_VISION=true` if using vision features and that your selected LLM model supports vision.
-   **Dependency Problems**: Run `uv sync` to ensure all dependencies are correctly installed. Check `pyproject.toml`.
-   **Logging**: Check the log file specified by `LOG_FILE` (default: `mcp_server_browser_use.log`) for detailed error messages. Increase `BROWSER_USE_LOGGING_LEVEL` to `DEBUG` for more verbose output.

## License

MIT - See [LICENSE](LICENSE) for details.
