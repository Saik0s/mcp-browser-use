"""Integration tests for task management MCP tools (task_list, task_get, task_cancel)."""

import json
import uuid

import pytest
from fastmcp import Client

from mcp_server_browser_use.observability import TaskRecord, TaskStatus
from mcp_server_browser_use.observability.store import get_task_store


def unique_id(prefix: str = "test") -> str:
    """Generate a unique task ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestTaskList:
    """Tests for the task_list tool."""

    @pytest.mark.anyio
    async def test_task_list_empty(self, mcp_client: Client):
        """task_list should return empty list when no tasks exist."""
        result = await mcp_client.call_tool("task_list", {})

        assert result.content is not None
        data = json.loads(result.content[0].text)
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        assert "count" in data

    @pytest.mark.anyio
    async def test_task_list_with_limit(self, mcp_client: Client):
        """task_list should respect limit parameter."""
        # Create some tasks in the store
        task_store = get_task_store()
        await task_store.initialize()

        for i in range(5):
            record = TaskRecord(task_id=unique_id(f"limit-test-{i}"), tool_name="run_browser_agent", status=TaskStatus.COMPLETED)
            await task_store.create_task(record)

        result = await mcp_client.call_tool("task_list", {"limit": 3})

        data = json.loads(result.content[0].text)
        assert len(data["tasks"]) <= 3

    @pytest.mark.anyio
    async def test_task_list_with_status_filter(self, mcp_client: Client):
        """task_list should filter by status."""
        task_store = get_task_store()
        await task_store.initialize()

        # Create tasks with different statuses
        completed = TaskRecord(task_id=unique_id("completed"), tool_name="test", status=TaskStatus.COMPLETED)
        running = TaskRecord(task_id=unique_id("running"), tool_name="test", status=TaskStatus.RUNNING)
        await task_store.create_task(completed)
        await task_store.create_task(running)

        result = await mcp_client.call_tool("task_list", {"status_filter": "running"})

        data = json.loads(result.content[0].text)
        for task in data["tasks"]:
            assert task["status"] == "running"

    @pytest.mark.anyio
    async def test_task_list_invalid_status_filter(self, mcp_client: Client):
        """task_list should return error for invalid status filter."""
        result = await mcp_client.call_tool("task_list", {"status_filter": "invalid"})

        assert "Error" in result.content[0].text
        assert "Invalid status" in result.content[0].text


class TestTaskGet:
    """Tests for the task_get tool."""

    @pytest.mark.anyio
    async def test_task_get_not_found(self, mcp_client: Client):
        """task_get should return error for non-existent task."""
        result = await mcp_client.call_tool("task_get", {"task_id": "nonexistent-task"})

        assert "Error" in result.content[0].text
        assert "not found" in result.content[0].text

    @pytest.mark.anyio
    async def test_task_get_existing_task(self, mcp_client: Client):
        """task_get should return full task details."""
        task_store = get_task_store()
        await task_store.initialize()

        task_id = unique_id("get-task")
        record = TaskRecord(
            task_id=task_id,
            tool_name="run_browser_agent",
            status=TaskStatus.COMPLETED,
            input_params={"task": "Go to example.com"},
            result="Task completed successfully",
        )
        await task_store.create_task(record)

        result = await mcp_client.call_tool("task_get", {"task_id": task_id})

        data = json.loads(result.content[0].text)
        assert data["task_id"] == task_id
        assert data["tool"] == "run_browser_agent"
        assert data["status"] == "completed"
        assert data["input"]["task"] == "Go to example.com"

    @pytest.mark.anyio
    async def test_task_get_by_prefix(self, mcp_client: Client):
        """task_get should find task by prefix match."""
        task_store = get_task_store()
        await task_store.initialize()

        # Use a unique prefix that's unlikely to match existing tasks
        unique_prefix = f"prefix-{uuid.uuid4().hex[:6]}"
        task_id = f"{unique_prefix}-full-id"
        record = TaskRecord(task_id=task_id, tool_name="test", status=TaskStatus.COMPLETED)
        await task_store.create_task(record)

        result = await mcp_client.call_tool("task_get", {"task_id": unique_prefix})

        data = json.loads(result.content[0].text)
        assert data["task_id"] == task_id


class TestTaskCancel:
    """Tests for the task_cancel tool."""

    @pytest.mark.anyio
    async def test_task_cancel_not_running(self, mcp_client: Client):
        """task_cancel should return error for non-running task."""
        result = await mcp_client.call_tool("task_cancel", {"task_id": "nonexistent"})

        data = json.loads(result.content[0].text)
        assert data["success"] is False
        assert "not found or not running" in data["error"]

    @pytest.mark.anyio
    async def test_task_cancel_completed_task(self, mcp_client: Client):
        """task_cancel should not cancel already completed tasks."""
        # A completed task is not in _running_tasks, so it should fail
        task_store = get_task_store()
        await task_store.initialize()

        task_id = unique_id("completed-cancel")
        record = TaskRecord(task_id=task_id, tool_name="test", status=TaskStatus.COMPLETED)
        await task_store.create_task(record)

        result = await mcp_client.call_tool("task_cancel", {"task_id": task_id})

        data = json.loads(result.content[0].text)
        assert data["success"] is False
