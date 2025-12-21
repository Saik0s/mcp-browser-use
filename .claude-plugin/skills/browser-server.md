# Browser Server Management

Manage the mcp-server-browser-use daemon for browser automation.

## Usage

Check server status, start, stop, or view logs for the browser automation daemon.

## Commands

**Check status:**
```bash
uv run mcp-server-browser-use status
```

**Start daemon (background):**
```bash
uv run mcp-server-browser-use server
```

**Start in foreground (debug):**
```bash
uv run mcp-server-browser-use server -f
```

**Stop daemon:**
```bash
uv run mcp-server-browser-use stop
```

**View logs:**
```bash
uv run mcp-server-browser-use logs -f
```

**Health check:**
```bash
uv run mcp-server-browser-use health
```

**List available MCP tools:**
```bash
uv run mcp-server-browser-use tools
```

## Troubleshooting

**Server won't start:**
1. Check if already running: `uv run mcp-server-browser-use status`
2. Check logs: `uv run mcp-server-browser-use logs`
3. Kill orphan processes: `pkill -f mcp-server-browser-use`

**Browser issues:**
1. Reinstall Playwright: `uv run playwright install chromium`
2. Disable headless: `uv run mcp-server-browser-use config set -k browser.headless -v false`

## Server Info

- Default URL: http://127.0.0.1:8383/mcp
- Config: ~/.config/mcp-server-browser-use/config.json
- Logs: ~/.local/state/mcp-server-browser-use/server.log
- Tasks DB: ~/.config/mcp-server-browser-use/tasks.db

## Common Workflows

**Quick start:**
```bash
uv run mcp-server-browser-use server && uv run mcp-server-browser-use status
```

**Debug mode:**
```bash
uv run mcp-server-browser-use server -f
# Watch logs in real-time, Ctrl+C to stop
```

**Monitor daemon:**
```bash
watch -n 5 'uv run mcp-server-browser-use status'
```
