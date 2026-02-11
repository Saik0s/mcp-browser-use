"""Concurrency-focused tests for task tracking, logging context, and result persistence."""

import asyncio

import pytest

from mcp_server_browser_use.observability import TaskRecord, TaskStage, TaskStatus
from mcp_server_browser_use.observability.logging import bind_task_context, clear_task_context, get_current_task_id
from mcp_server_browser_use.observability.store import TaskStore


@pytest.mark.anyio
async def test_concurrent_task_store_progress_isolated(tmp_path):
    """Progress/status updates for different tasks must not cross-contaminate."""
    store = TaskStore(db_path=tmp_path / "tasks.db")
    await store.initialize()

    task_a = TaskRecord(task_id="task-a", tool_name="tool-a", status=TaskStatus.PENDING)
    task_b = TaskRecord(task_id="task-b", tool_name="tool-b", status=TaskStatus.PENDING)

    await asyncio.gather(store.create_task(task_a), store.create_task(task_b))

    await asyncio.gather(
        store.update_progress("task-a", 1, 3, "a1", TaskStage.NAVIGATING),
        store.update_progress("task-b", 2, 5, "b2", TaskStage.EXTRACTING),
    )

    await asyncio.gather(
        store.update_status("task-a", TaskStatus.COMPLETED, result="result-a"),
        store.update_status("task-b", TaskStatus.FAILED, error="error-b"),
    )

    loaded_a = await store.get_task("task-a")
    loaded_b = await store.get_task("task-b")

    assert loaded_a is not None
    assert loaded_b is not None

    assert loaded_a.status == TaskStatus.COMPLETED
    assert loaded_a.progress_current == 1
    assert loaded_a.progress_total == 3
    assert loaded_a.progress_message == "a1"
    assert loaded_a.stage == TaskStage.NAVIGATING
    assert loaded_a.result == "result-a"
    assert loaded_a.error is None

    assert loaded_b.status == TaskStatus.FAILED
    assert loaded_b.progress_current == 2
    assert loaded_b.progress_total == 5
    assert loaded_b.progress_message == "b2"
    assert loaded_b.stage == TaskStage.EXTRACTING
    assert loaded_b.result is None
    assert loaded_b.error == "error-b"


@pytest.mark.anyio
async def test_task_logging_context_isolation():
    """Each async task should see only its own bound task_id."""

    async def worker(task_id: str) -> None:
        bind_task_context(task_id, tool_name="test-tool")
        await asyncio.sleep(0)
        assert get_current_task_id() == task_id
        clear_task_context()
        await asyncio.sleep(0)
        assert get_current_task_id() is None

    await asyncio.gather(worker("t1"), worker("t2"))


def test_save_execution_result_is_unique_under_concurrency(tmp_path, monkeypatch):
    """Saving multiple results quickly should never overwrite due to filename collisions."""
    monkeypatch.setenv("MCP_SERVER_RESULTS_DIR", str(tmp_path))

    import mcp_server_browser_use.config as config_mod

    # Ensure env changes take effect for settings proxy.
    config_mod.get_settings.cache_clear()
    try:
        from mcp_server_browser_use.utils import save_execution_result

        p1 = save_execution_result("one", prefix="agent")
        p2 = save_execution_result("two", prefix="agent")

        assert p1.name != p2.name
        assert p1.read_text(encoding="utf-8") == "one"
        assert p2.read_text(encoding="utf-8") == "two"
    finally:
        # Avoid leaking cached settings into subsequent tests.
        config_mod.get_settings.cache_clear()
