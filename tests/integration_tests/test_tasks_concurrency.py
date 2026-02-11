"""Integration tests for concurrent task execution and cancellation isolation."""

import asyncio
import importlib
import json

import httpx
import pytest
from fastmcp import Client
from mcp.types import TextContent

from mcp_server_browser_use.observability.store import TaskStore


def _tool_result_text(result) -> str:
    assert result.content is not None
    assert len(result.content) > 0
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


class _DummyBrowserSession:
    async def start(self) -> None:
        return None


class _DummyAgent:
    def __init__(self, **_kwargs):
        self.browser_session = _DummyBrowserSession()

    async def run(self):
        # Wait forever until cancelled by the task wrapper.
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


def _fake_get_llm(*_args: object, **_kwargs: object) -> object:
    return object()


@pytest.mark.anyio
async def test_concurrent_task_cancellation_isolated(monkeypatch, tmp_path):
    """Canceling one background task must not affect another."""
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("MCP_RECIPES_ENABLED", "true")
    monkeypatch.setenv("MCP_RECIPES_DIRECTORY", str(tmp_path / "browser-recipes"))
    (tmp_path / "browser-recipes").mkdir(parents=True, exist_ok=True)

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    import mcp_server_browser_use.server

    importlib.reload(mcp_server_browser_use.server)

    # Isolate task DB per test.
    import mcp_server_browser_use.observability.store as store_mod

    store_mod._task_store = TaskStore(db_path=tmp_path / "tasks.db")

    from unittest.mock import patch

    from mcp_server_browser_use.server import serve

    server = serve()
    http_app = server.http_app()
    transport = httpx.ASGITransport(app=http_app)

    with (
        patch("mcp_server_browser_use.server.Agent", _DummyAgent),
        patch("mcp_server_browser_use.server.RecipeRecorder", _DummyRecorder),
        patch("mcp_server_browser_use.server.get_llm", new=_fake_get_llm),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            # Start two learn tasks concurrently.
            resp1, resp2 = await asyncio.gather(
                http_client.post("/api/learn", json={"task": "concurrency-1"}),
                http_client.post("/api/learn", json={"task": "concurrency-2"}),
            )
            assert resp1.status_code == 202
            assert resp2.status_code == 202
            task_id_1 = resp1.json()["task_id"]
            task_id_2 = resp2.json()["task_id"]
            assert task_id_1 != task_id_2

            # Wait for both tasks to report running.
            async def wait_status(task_id: str, want: str, attempts: int = 200) -> None:
                for _ in range(attempts):
                    get_resp = await http_client.get(f"/api/tasks/{task_id}")
                    assert get_resp.status_code == 200
                    status = get_resp.json().get("status")
                    if status == want:
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError(f"Timed out waiting for {task_id} to reach {want}")

            await asyncio.gather(wait_status(task_id_1, "running"), wait_status(task_id_2, "running"))

            async with Client(server) as mcp:
                # Cancel only the first task.
                cancelled = False
                for _ in range(100):
                    result = await mcp.call_tool("task_cancel", {"task_id": task_id_1})
                    payload = json.loads(_tool_result_text(result))
                    if payload.get("success"):
                        cancelled = True
                        break
                    await asyncio.sleep(0.01)
                assert cancelled is True

            # First task should reach cancelled, second stays running.
            await wait_status(task_id_1, "cancelled")
            still_running = await http_client.get(f"/api/tasks/{task_id_2}")
            assert still_running.status_code == 200
            assert still_running.json().get("status") == "running"

            # Cleanup: cancel second task too.
            async with Client(server) as mcp:
                cancelled_2 = False
                for _ in range(100):
                    result = await mcp.call_tool("task_cancel", {"task_id": task_id_2})
                    payload = json.loads(_tool_result_text(result))
                    if payload.get("success"):
                        cancelled_2 = True
                        break
                    await asyncio.sleep(0.01)
                assert cancelled_2 is True

            await wait_status(task_id_2, "cancelled")
