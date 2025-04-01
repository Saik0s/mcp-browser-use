<img src="./assets/web-ui.png" alt="Browser Use Web UI" width="full"/>

<br/>

# browser-use MCP server
[![Documentation](https://img.shields.io/badge/Documentation-📕-blue)](https://docs.browser-use.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

> **Project Note**: This MCP server implementation builds upon the [browser-use/web-ui](https://github.com/browser-use/web-ui) foundation. Core browser automation logic and configuration patterns are adapted from the original project.

AI-driven browser automation server implementing the Model Context Protocol (MCP) for natural language browser control.

<a href="https://glama.ai/mcp/servers/dz6dy5hw59"><img width="380" height="200" src="https://glama.ai/mcp/servers/dz6dy5hw59/badge" alt="Browser-Use Server MCP server" /></a>

## Features

- 🧠 **MCP Integration** - Full protocol implementation for AI agent communication
- 🌐 **Browser Automation** - Page navigation, form filling, and element interaction
- 👁️ **Visual Understanding** - Screenshot analysis and vision-based interactions
- 🔄 **State Persistence** - Maintain browser sessions between tasks
- 🔌 **Multi-LLM Support** - OpenAI, Anthropic, Azure, DeepSeek integration

## Quick Start

### Prerequisites

- Python 3.11 or higher
- uv (fast Python package installer)
- Chrome/Chromium browser

### Installation

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`
On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

```json
"mcpServers": {
    "browser-use": {
      "command": "uvx",
      "args": [
        "mcp-server-browser-use",
      ],
      "env": {
        "OPENROUTER_API_KEY": "",
        "OPENROUTER_ENDPOINT": "https://openrouter.ai/api/v1",
        "OPENAI_ENDPOINT": "https://api.openai.com/v1",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_ENDPOINT": "https://api.anthropic.com",
        "ANTHROPIC_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_API_KEY": "",
        "DEEPSEEK_ENDPOINT": "https://api.deepseek.com",
        "DEEPSEEK_API_KEY": "",
        "MISTRAL_API_KEY": "",
        "MISTRAL_ENDPOINT": "https://api.mistral.ai/v1",
        "OLLAMA_ENDPOINT": "http://localhost:11434",
        "ANONYMIZED_TELEMETRY": "true",
        "BROWSER_USE_LOGGING_LEVEL": "info",
        "CHROME_PATH": "",
        "CHROME_USER_DATA": "",
        "CHROME_DEBUGGING_PORT": "9222",
        "CHROME_DEBUGGING_HOST": "localhost",
        "CHROME_PERSISTENT_SESSION": "false",
        "BROWSER_HEADLESS": "false",
        "BROWSER_CHROME_INSTANCE_PATH" : "",
        "BROWSER_DISABLE_SECURITY": "false",
        "BROWSER_WINDOW_WIDTH": "1280",
        "BROWSER_WINDOW_HEIGHT": "720",
        "BROWSER_TRACE_PATH": "trace.json",
        "BROWSER_RECORDING_PATH": "recording.mp4",
        "RESOLUTION": "1920x1080x24",
        "RESOLUTION_WIDTH": "1920",
        "RESOLUTION_HEIGHT": "1080",
        "VNC_PASSWORD": "youvncpassword",
        "MCP_MODEL_PROVIDER": "anthropic",
        "MCP_MODEL_NAME": "claude-3-5-sonnet-20241022",
        "MCP_TEMPERATURE": "0.3",
        "MCP_MAX_STEPS": "30",
        "MCP_USE_VISION": "true",
        "MCP_MAX_ACTIONS_PER_STEP": "5",
        "MCP_TOOL_CALL_IN_CONTENT": "true",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1"
    }
}
```

### Local Development

```json
"browser-use": {
  "command": "uv",
  "args": [
    "--directory",
    "/path/to/mcp-browser-use",
    "run",
    "mcp-server-browser-use"
  ],
  "env": {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
    "PYTHONUTF8": "1"
  }
}
```

## Development

```bash
# Install dev dependencies
uv sync

# Run with debugger
npx @modelcontextprotocol/inspector uv --directory . run mcp-server-browser-use
```

## Troubleshooting

-   **Browser Conflicts**: Close all Chrome instances before starting.
-   **API Errors**: Verify API keys in environment variables match your LLM provider.
-   **Vision Support**: Ensure `MCP_USE_VISION=true` for screenshot analysis.

## Provider Configuration

The server supports multiple LLM providers through environment variables. Here are the available options for `MCP_MODEL_PROVIDER`:

| Provider | Value | Required Env Variables |
|----------|--------|----------------------|
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`<br>`ANTHROPIC_ENDPOINT` (optional) |
| OpenAI | `openai` | `OPENAI_API_KEY`<br>`OPENAI_ENDPOINT` (optional) |
| Azure OpenAI | `azure_openai` | `AZURE_OPENAI_API_KEY`<br>`AZURE_OPENAI_ENDPOINT` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY`<br>`DEEPSEEK_ENDPOINT` (optional) |
| Gemini | `gemini` | `GOOGLE_API_KEY` |
| Mistral | `mistral` | `MISTRAL_API_KEY`<br>`MISTRAL_ENDPOINT` (optional) |
| Ollama | `ollama` | `OLLAMA_ENDPOINT` (optional, defaults to localhost:11434) |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY`<br>`OPENROUTER_ENDPOINT` (optional) |

### Notes:
- For endpoints marked as optional, default values will be used if not specified
- Temperature can be configured using `MCP_TEMPERATURE` (default: 0.3)
- Model can be specified using `MCP_MODEL_NAME`
- For Ollama models, additional context settings like `num_ctx` and `num_predict` are configurable

## Credits

This project extends the [browser-use/web-ui](https://github.com/browser-use/web-ui) under MIT License. Special thanks to the original authors for their browser automation framework.

## License

MIT - See [LICENSE](LICENSE) for details.
