#!/usr/bin/env python3
"""Stdio MCP wrapper that forwards to HTTP daemon.

This script provides stdio-based MCP transport (required by Claude Code plugins)
while forwarding all tool calls to the HTTP daemon running at localhost:8383.

The HTTP daemon must be started separately with:
    mcp-server-browser-use server
"""

import asyncio
import json
import sys
from typing import Any

import httpx
from fastmcp import FastMCP

# HTTP daemon endpoint
DAEMON_URL = "http://127.0.0.1:8383"
TIMEOUT = 300.0  # 5 minutes for long-running browser tasks

mcp = FastMCP("browser-use")


async def _check_daemon_health() -> bool:
    """Check if HTTP daemon is running and healthy."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"{DAEMON_URL}/mcp/tools/health_check", json={})
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "healthy":
                    return True
    except Exception as e:
        print(f"Failed to connect to daemon: {e}", file=sys.stderr)
    return False


async def _forward_tool_call(tool_name: str, arguments: dict[str, Any]) -> str:
    """Forward tool call to HTTP daemon."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{DAEMON_URL}/mcp/tools/{tool_name}",
            json=arguments,
        )
        response.raise_for_status()

        # Handle both string results and JSON objects
        result = response.json()
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2)


# --- Browser Automation Tools ---


@mcp.tool()
async def run_browser_agent(
    task: str,
    max_steps: int | None = None,
    skill_name: str | None = None,
    skill_params: str | dict | None = None,
    learn: bool = False,
    save_skill_as: str | None = None,
) -> str:
    """
    Execute a browser automation task using AI.

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
        Result of the browser automation task
    """
    return await _forward_tool_call(
        "run_browser_agent",
        {
            "task": task,
            "max_steps": max_steps,
            "skill_name": skill_name,
            "skill_params": skill_params,
            "learn": learn,
            "save_skill_as": save_skill_as,
        },
    )


@mcp.tool()
async def run_deep_research(
    topic: str,
    max_searches: int | None = None,
    save_to_file: str | None = None,
) -> str:
    """
    Execute deep research on a topic with progress tracking.

    Args:
        topic: The research topic or question to investigate
        max_searches: Maximum number of web searches (default from settings)
        save_to_file: Optional file path to save the report

    Returns:
        The research report as markdown
    """
    return await _forward_tool_call(
        "run_deep_research",
        {
            "topic": topic,
            "max_searches": max_searches,
            "save_to_file": save_to_file,
        },
    )


# --- Skill Management Tools ---


@mcp.tool()
async def skill_list() -> str:
    """
    List all available browser skills.

    Returns:
        JSON list of skill summaries with name, description, and usage stats
    """
    return await _forward_tool_call("skill_list", {})


@mcp.tool()
async def skill_get(skill_name: str) -> str:
    """
    Get full details of a specific skill.

    Args:
        skill_name: Name of the skill to retrieve

    Returns:
        Full skill definition as YAML
    """
    return await _forward_tool_call("skill_get", {"skill_name": skill_name})


@mcp.tool()
async def skill_delete(skill_name: str) -> str:
    """
    Delete a skill by name.

    Args:
        skill_name: Name of the skill to delete

    Returns:
        Success or error message
    """
    return await _forward_tool_call("skill_delete", {"skill_name": skill_name})


# --- Observability Tools ---


@mcp.tool()
async def health_check() -> str:
    """
    Health check endpoint with system stats and running task information.

    Returns:
        JSON object with server health status, running tasks, and statistics
    """
    return await _forward_tool_call("health_check", {})


@mcp.tool()
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
    return await _forward_tool_call("task_list", {"limit": limit, "status_filter": status_filter})


@mcp.tool()
async def task_get(task_id: str) -> str:
    """
    Get full details of a specific task.

    Args:
        task_id: Task ID (full or prefix)

    Returns:
        JSON object with task details, input, and result/error
    """
    return await _forward_tool_call("task_get", {"task_id": task_id})


@mcp.tool()
async def task_cancel(task_id: str) -> str:
    """
    Cancel a running browser agent or research task.

    Args:
        task_id: Task ID (full or prefix match)

    Returns:
        JSON with success status and message
    """
    return await _forward_tool_call("task_cancel", {"task_id": task_id})


async def _startup_check():
    """Check daemon health on startup."""
    print("Checking HTTP daemon health...", file=sys.stderr)
    healthy = await _check_daemon_health()

    if not healthy:
        print("\n" + "="*80, file=sys.stderr)
        print("ERROR: HTTP daemon is not running or unhealthy", file=sys.stderr)
        print("="*80, file=sys.stderr)
        print("\nPlease start the daemon with:", file=sys.stderr)
        print("    mcp-server-browser-use server", file=sys.stderr)
        print("\nOr check the logs with:", file=sys.stderr)
        print("    mcp-server-browser-use logs -f", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
        sys.exit(1)

    print(f"✓ HTTP daemon is healthy at {DAEMON_URL}", file=sys.stderr)


if __name__ == "__main__":
    # Check daemon health before starting
    asyncio.run(_startup_check())

    # Run stdio server
    mcp.run(transport="stdio")
