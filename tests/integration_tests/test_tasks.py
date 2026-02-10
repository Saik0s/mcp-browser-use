"""Integration tests for task management MCP tools (task_list, task_get, task_cancel)."""

import asyncio
import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent

from mcp_server_browser_use.observability import TaskRecord, TaskStatus
from mcp_server_browser_use.observability.store import TaskStore, get_task_store


def unique_id(prefix: str = "test") -> str:
    """Generate a unique task ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def tool_result_text(result: CallToolResult) -> str:
    assert result.content is not None
    assert len(result.content) > 0
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


class TestTaskList:
    """Tests for the task_list tool."""

    @pytest.mark.anyio
    async def test_task_list_empty(self, mcp_client: Client):
        """task_list should return empty list when no tasks exist."""
        result = await mcp_client.call_tool("task_list", {})

        data = json.loads(tool_result_text(result))
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

        data = json.loads(tool_result_text(result))
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

        data = json.loads(tool_result_text(result))
        for task in data["tasks"]:
            assert task["status"] == "running"

    @pytest.mark.anyio
    async def test_task_list_invalid_status_filter(self, mcp_client: Client):
        """task_list should return error for invalid status filter."""
        result = await mcp_client.call_tool("task_list", {"status_filter": "invalid"})

        text = tool_result_text(result)
        assert "Error" in text
        assert "Invalid status" in text


class TestTaskGet:
    """Tests for the task_get tool."""

    @pytest.mark.anyio
    async def test_task_get_not_found(self, mcp_client: Client):
        """task_get should return error for non-existent task."""
        result = await mcp_client.call_tool("task_get", {"task_id": "nonexistent-task"})

        text = tool_result_text(result)
        assert "Error" in text
        assert "not found" in text

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

        data = json.loads(tool_result_text(result))
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

        data = json.loads(tool_result_text(result))
        assert data["task_id"] == task_id


class TestTaskCancel:
    """Tests for the task_cancel tool."""

    @pytest.mark.anyio
    async def test_task_cancel_not_running(self, mcp_client: Client):
        """task_cancel should return error for non-running task."""
        result = await mcp_client.call_tool("task_cancel", {"task_id": "nonexistent"})

        data = json.loads(tool_result_text(result))
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

        data = json.loads(tool_result_text(result))
        assert data["success"] is False


class TestTaskCancelRace:
    """Regression tests for task cancellation races in server task wrappers."""

    @pytest.mark.anyio
    async def test_task_cancel_bg_wrapper_marks_cancelled(self, monkeypatch, tmp_path):
        """Cancelling a REST-started background task should mark the base task as cancelled, not failed."""
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
        monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")
        monkeypatch.setenv("MCP_RECIPES_ENABLED", "true")
        monkeypatch.setenv("MCP_RECIPES_DIRECTORY", str(tmp_path / "browser-recipes"))
        (tmp_path / "browser-recipes").mkdir(parents=True, exist_ok=True)

        # Reload config and server for clean module-level globals (_running_tasks) per test.
        import importlib

        import mcp_server_browser_use.config

        importlib.reload(mcp_server_browser_use.config)

        import mcp_server_browser_use.server

        importlib.reload(mcp_server_browser_use.server)

        # Isolate task DB per test.
        import mcp_server_browser_use.observability.store as store_mod

        store_mod._task_store = TaskStore(db_path=tmp_path / "tasks.db")

        from mcp_server_browser_use.server import serve

        # Minimal stubs to avoid real browser/recorder work.
        class _DummyBrowserSession:
            async def start(self) -> None:
                return None

        class _DummyAgent:
            def __init__(self, **_kwargs):
                self.browser_session = _DummyBrowserSession()

            async def run(self):
                await asyncio.Event().wait()

        class _DummyRecorder:
            def __init__(self, **_kwargs):
                return None

            async def attach(self, _browser_session) -> None:
                return None

            async def detach(self) -> None:
                return None

            async def finalize(self) -> None:
                return None

        server = serve()

        http_app = server.http_app()
        transport = httpx.ASGITransport(app=http_app)

        with (
            patch("mcp_server_browser_use.server.Agent", _DummyAgent),
            patch("mcp_server_browser_use.server.RecipeRecorder", _DummyRecorder),
            patch("mcp_server_browser_use.server.get_llm", MagicMock(return_value=object())),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
                resp = await http_client.post("/api/learn", json={"task": "learn task cancellation"})
                assert resp.status_code == 202
                task_id = resp.json()["task_id"]

                async with Client(server) as mcp:
                    # Cancel immediately, often before the inner agent task is registered.
                    cancelled = False
                    for _ in range(100):
                        result = await mcp.call_tool("task_cancel", {"task_id": task_id})
                        payload = json.loads(tool_result_text(result))
                        if payload.get("success") is True:
                            cancelled = True
                            break
                        await asyncio.sleep(0.01)
                    assert cancelled is True

                # Poll the task record until it reaches terminal state.
                terminal_status = None
                for _ in range(200):
                    get_resp = await http_client.get(f"/api/tasks/{task_id}")
                    assert get_resp.status_code == 200
                    terminal_status = get_resp.json().get("status")
                    if terminal_status in ("cancelled", "failed", "completed"):
                        break
                    await asyncio.sleep(0.01)

                assert terminal_status == "cancelled"
