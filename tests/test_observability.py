"""Tests for observability module (TaskStore, TaskRecord, etc.)."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mcp_server_browser_use.observability import TaskRecord, TaskStage, TaskStatus
from mcp_server_browser_use.observability.store import TaskStore


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_tasks.db"


@pytest.fixture
async def task_store(temp_db):
    """Create and initialize a TaskStore with temporary database."""
    store = TaskStore(db_path=temp_db)
    await store.initialize()
    return store


class TestTaskRecord:
    """Tests for TaskRecord model."""

    def test_default_values(self):
        """Test TaskRecord default values."""
        record = TaskRecord(task_id="test-123", tool_name="run_browser_agent")
        assert record.status == TaskStatus.PENDING
        assert record.stage is None
        assert record.progress_current == 0
        assert record.progress_total == 0
        assert record.result is None
        assert record.error is None

    def test_duration_calculation(self):
        """Test duration calculation for completed task."""
        start = datetime.now(timezone.utc) - timedelta(seconds=30)
        end = datetime.now(timezone.utc)
        record = TaskRecord(
            task_id="test-123",
            tool_name="run_browser_agent",
            started_at=start,
            completed_at=end,
        )
        assert record.duration_seconds is not None
        assert 29 <= record.duration_seconds <= 31

    def test_duration_none_when_not_started(self):
        """Test duration is None when task not started."""
        record = TaskRecord(task_id="test-123", tool_name="run_browser_agent")
        assert record.duration_seconds is None

    def test_progress_percent(self):
        """Test progress percentage calculation."""
        record = TaskRecord(
            task_id="test-123",
            tool_name="run_browser_agent",
            progress_current=5,
            progress_total=20,
        )
        assert record.progress_percent == 25.0

    def test_progress_percent_zero_total(self):
        """Test progress percentage with zero total."""
        record = TaskRecord(task_id="test-123", tool_name="run_browser_agent")
        assert record.progress_percent == 0.0

    def test_is_terminal(self):
        """Test terminal state detection."""
        completed = TaskRecord(task_id="t1", tool_name="test", status=TaskStatus.COMPLETED)
        failed = TaskRecord(task_id="t2", tool_name="test", status=TaskStatus.FAILED)
        running = TaskRecord(task_id="t3", tool_name="test", status=TaskStatus.RUNNING)
        pending = TaskRecord(task_id="t4", tool_name="test", status=TaskStatus.PENDING)

        assert completed.is_terminal is True
        assert failed.is_terminal is True
        assert running.is_terminal is False
        assert pending.is_terminal is False


class TestTaskStore:
    """Tests for TaskStore."""

    async def test_create_and_get_task(self, task_store):
        """Test creating and retrieving a task."""
        record = TaskRecord(
            task_id="test-abc-123",
            tool_name="run_browser_agent",
            input_params={"task": "Go to google.com"},
        )
        await task_store.create_task(record)

        retrieved = await task_store.get_task("test-abc-123")
        assert retrieved is not None
        assert retrieved.task_id == "test-abc-123"
        assert retrieved.tool_name == "run_browser_agent"
        assert retrieved.input_params["task"] == "Go to google.com"

    async def test_update_status_to_running(self, task_store):
        """Test updating task status to running sets started_at."""
        record = TaskRecord(task_id="test-456", tool_name="run_browser_agent")
        await task_store.create_task(record)

        await task_store.update_status("test-456", TaskStatus.RUNNING)

        retrieved = await task_store.get_task("test-456")
        assert retrieved.status == TaskStatus.RUNNING
        assert retrieved.started_at is not None

    async def test_update_status_to_completed(self, task_store):
        """Test updating task status to completed sets completed_at and result."""
        record = TaskRecord(task_id="test-789", tool_name="run_browser_agent")
        await task_store.create_task(record)
        await task_store.update_status("test-789", TaskStatus.RUNNING)

        await task_store.update_status("test-789", TaskStatus.COMPLETED, result="Task done!")

        retrieved = await task_store.get_task("test-789")
        assert retrieved.status == TaskStatus.COMPLETED
        assert retrieved.completed_at is not None
        assert retrieved.result == "Task done!"

    async def test_update_status_to_failed(self, task_store):
        """Test updating task status to failed sets error."""
        record = TaskRecord(task_id="test-fail", tool_name="run_browser_agent")
        await task_store.create_task(record)

        await task_store.update_status("test-fail", TaskStatus.FAILED, error="Something went wrong")

        retrieved = await task_store.get_task("test-fail")
        assert retrieved.status == TaskStatus.FAILED
        assert retrieved.error == "Something went wrong"

    async def test_update_progress(self, task_store):
        """Test updating task progress."""
        record = TaskRecord(task_id="test-prog", tool_name="run_browser_agent")
        await task_store.create_task(record)

        await task_store.update_progress("test-prog", 5, 20, "Navigating...", TaskStage.NAVIGATING)

        retrieved = await task_store.get_task("test-prog")
        assert retrieved.progress_current == 5
        assert retrieved.progress_total == 20
        assert retrieved.progress_message == "Navigating..."
        assert retrieved.stage == TaskStage.NAVIGATING

    async def test_get_running_tasks(self, task_store):
        """Test getting all running tasks."""
        # Create some tasks with different statuses
        for i, status in enumerate([TaskStatus.RUNNING, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.PENDING]):
            record = TaskRecord(task_id=f"task-{i}", tool_name="test", status=status)
            await task_store.create_task(record)

        running = await task_store.get_running_tasks()
        assert len(running) == 2
        assert all(t.status == TaskStatus.RUNNING for t in running)

    async def test_get_task_history(self, task_store):
        """Test getting task history with filters."""
        # Create tasks with different tools
        for i in range(5):
            record = TaskRecord(
                task_id=f"agent-{i}",
                tool_name="run_browser_agent",
                status=TaskStatus.COMPLETED,
            )
            await task_store.create_task(record)

        for i in range(3):
            record = TaskRecord(
                task_id=f"research-{i}",
                tool_name="run_deep_research",
                status=TaskStatus.COMPLETED,
            )
            await task_store.create_task(record)

        # Test limit
        all_tasks = await task_store.get_task_history(limit=100)
        assert len(all_tasks) == 8

        # Test tool filter
        agent_tasks = await task_store.get_task_history(tool_name="run_browser_agent")
        assert len(agent_tasks) == 5

        # Test status filter
        completed = await task_store.get_task_history(status=TaskStatus.COMPLETED)
        assert len(completed) == 8

    async def test_get_stats(self, task_store):
        """Test getting aggregate statistics."""
        # Create tasks with different statuses
        for i, status in enumerate([TaskStatus.COMPLETED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.RUNNING]):
            record = TaskRecord(task_id=f"stat-{i}", tool_name="run_browser_agent", status=status)
            await task_store.create_task(record)

        stats = await task_store.get_stats()
        assert stats["total_tasks"] == 4
        assert stats["running_count"] == 1
        assert stats["by_status"]["completed"] == 2
        assert stats["by_status"]["failed"] == 1
        assert stats["by_tool"]["run_browser_agent"] == 4

    async def test_cleanup_old_tasks(self, task_store):
        """Test cleanup of old tasks."""
        # Create old completed task
        old_record = TaskRecord(
            task_id="old-task",
            tool_name="test",
            status=TaskStatus.COMPLETED,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        await task_store.create_task(old_record)

        # Create recent completed task
        recent_record = TaskRecord(
            task_id="recent-task",
            tool_name="test",
            status=TaskStatus.COMPLETED,
        )
        await task_store.create_task(recent_record)

        # Create old running task (should NOT be deleted)
        old_running = TaskRecord(
            task_id="old-running",
            tool_name="test",
            status=TaskStatus.RUNNING,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        await task_store.create_task(old_running)

        # Cleanup tasks older than 7 days
        deleted = await task_store.cleanup_old_tasks(days=7)
        assert deleted == 1  # Only old completed task

        # Verify
        all_tasks = await task_store.get_task_history(limit=100)
        task_ids = [t.task_id for t in all_tasks]
        assert "old-task" not in task_ids
        assert "recent-task" in task_ids
        assert "old-running" in task_ids  # Running tasks not deleted

    async def test_result_truncation(self, task_store):
        """Test that very long results are truncated."""
        record = TaskRecord(task_id="long-result", tool_name="test")
        await task_store.create_task(record)

        # Create a very long result
        long_result = "x" * 20000
        await task_store.update_status("long-result", TaskStatus.COMPLETED, result=long_result)

        retrieved = await task_store.get_task("long-result")
        assert len(retrieved.result) == 10000  # Truncated to 10000 chars
