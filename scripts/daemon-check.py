#!/usr/bin/env python3
"""Daemon check script - ensures HTTP daemon is running before Claude Code uses MCP tools."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def get_state_dir() -> Path:
    """Get the state directory for runtime files."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/state")).expanduser()
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()

    path = base / "mcp-server-browser-use"
    return path


def read_server_info() -> dict | None:
    """Read server info from file, return None if not exists or invalid."""
    server_info_file = get_state_dir() / "server.json"
    if not server_info_file.exists():
        return None
    try:
        info = json.loads(server_info_file.read_text())
        required = {"pid", "host", "port", "transport"}
        if not required.issubset(info.keys()):
            return None
        return info
    except (json.JSONDecodeError, OSError):
        return None


def is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def check_daemon_health() -> bool:
    """Check if daemon is running and healthy."""
    info = read_server_info()
    if info is None:
        return False
    return is_process_running(info["pid"])


def start_daemon() -> bool:
    """Start the HTTP daemon in background using the CLI."""
    try:
        # Use uv to run the CLI command
        subprocess.run(
            ["uv", "run", "mcp-server-browser-use", "server"],
            cwd=Path(__file__).parent.parent,  # Project root
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # Don't raise on non-zero exit
        )

        # Wait a bit for the daemon to start
        time.sleep(2)

        # Verify it started
        return check_daemon_health()
    except Exception as e:
        print(f"Error starting daemon: {e}", file=sys.stderr)
        return False


def main() -> None:
    """Main entry point for daemon check hook."""
    if check_daemon_health():
        message = "Browser automation daemon already running"
    else:
        if start_daemon():
            message = "Browser automation daemon started successfully"
        else:
            message = "Failed to start browser automation daemon"

    # Get server info for output
    info = read_server_info()
    if info:
        url = f"http://{info['host']}:{info['port']}/mcp"
        additional_context = f"{message} at {url}"
    else:
        additional_context = message

    # Return hook response in required format
    response = {
        "continue": True,
        "suppressOutput": False,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        },
    }

    print(json.dumps(response))


if __name__ == "__main__":
    main()
