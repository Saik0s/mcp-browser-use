#!/usr/bin/env python3
"""SessionStart hook - ensures HTTP daemon is running when Claude Code session starts."""

import json
import logging
import os
import subprocess
import time
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


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


def wait_for_daemon_health(max_attempts: int = 10, initial_delay: float = 0.2) -> bool:
    """Wait for daemon to become healthy with exponential backoff.

    Args:
        max_attempts: Maximum number of health check attempts
        initial_delay: Initial delay between attempts in seconds

    Returns:
        True if daemon becomes healthy, False otherwise
    """
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        if check_daemon_health():
            logger.info(f"Daemon health check passed on attempt {attempt}")
            return True

        logger.debug(f"Daemon health check attempt {attempt}/{max_attempts} failed, waiting {delay:.2f}s")
        time.sleep(delay)
        delay = min(delay * 1.5, 2.0)  # Cap at 2 seconds

    logger.warning(f"Daemon failed to become healthy after {max_attempts} attempts")
    return False


def get_project_root() -> Path:
    """Get the project root directory (where this script lives)."""
    # Hook is in .claude-plugin/hooks/, so go up 2 levels
    return Path(__file__).parent.parent.parent


def start_daemon() -> bool:
    """Start the HTTP daemon in background using the CLI."""
    try:
        project_root = get_project_root()
        # Use uv to run the CLI command from project root
        subprocess.run(
            ["uv", "run", "mcp-server-browser-use", "server"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # Don't raise on non-zero exit
        )

        # Wait for daemon to become healthy with exponential backoff
        return wait_for_daemon_health()
    except Exception as e:
        logger.error(f"Error starting daemon: {e}")
        return False


def main() -> None:
    """Main entry point for SessionStart hook."""
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
