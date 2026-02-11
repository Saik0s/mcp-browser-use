"""SQLite-based task store for persistence and history."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from .models import TaskRecord, TaskStage, TaskStatus


class TaskStore:
    """Async SQLite store for task state with automatic cleanup.

    Stores task records in SQLite for:
    - Persistence across server restarts
    - History of past executions
    - Real-time status queries
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize TaskStore.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.config/mcp-server-browser-use/tasks.db
        """
        if db_path is None:
            from ..config import get_config_dir

            db_path = get_config_dir() / "tasks.db"
        self.db_path = db_path
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create schema if not exists."""
        if self._initialized:
            return

        # Concurrent callers (multiple background tasks) can race and lock the DB on PRAGMAs/DDL.
        async with self._init_lock:
            if self._initialized:
                return

            async with aiosqlite.connect(self.db_path) as db:
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode = WAL")
                await db.execute("PRAGMA busy_timeout = 5000")

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        tool_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        stage TEXT,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        progress_current INTEGER DEFAULT 0,
                        progress_total INTEGER DEFAULT 0,
                        progress_message TEXT,
                        input_params TEXT NOT NULL,
                        result TEXT,
                        error TEXT,
                        session_id TEXT
                    )
                """)

                # Indexes for common queries
                await db.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON tasks(created_at)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_tool_name ON tasks(tool_name)")
                await db.commit()

            self._initialized = True

    async def create_task(self, task: TaskRecord) -> None:
        """Insert new task record."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks (
                    task_id, tool_name, status, stage, created_at, started_at, completed_at,
                    progress_current, progress_total, progress_message, input_params,
                    result, error, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    task.task_id,
                    task.tool_name,
                    task.status.value,
                    task.stage.value if task.stage else None,
                    task.created_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.completed_at.isoformat() if task.completed_at else None,
                    task.progress_current,
                    task.progress_total,
                    task.progress_message,
                    json.dumps(task.input_params),
                    task.result,
                    task.error,
                    task.session_id,
                ),
            )
            await db.commit()

    async def update_progress(
        self,
        task_id: str,
        current: int,
        total: int,
        message: str | None = None,
        stage: TaskStage | None = None,
    ) -> None:
        """Update task progress."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE tasks
                SET progress_current = ?, progress_total = ?,
                    progress_message = ?, stage = ?
                WHERE task_id = ?
            """,
                (current, total, message, stage.value if stage else None, task_id),
            )
            await db.commit()

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update task status and optionally result/error."""
        await self.initialize()

        started_at: str | None = None
        completed_at: str | None = None
        if status == TaskStatus.RUNNING:
            started_at = datetime.now(UTC).isoformat()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            completed_at = datetime.now(UTC).isoformat()

        truncated_result: str | None = None
        if result is not None:
            truncated_result = result[:10000] if result else None

        truncated_error: str | None = None
        if error is not None:
            truncated_error = error[:2000] if error else None

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE tasks
                SET status = ?,
                    started_at = COALESCE(started_at, ?),
                    completed_at = COALESCE(completed_at, ?),
                    result = COALESCE(?, result),
                    error = COALESCE(?, error)
                WHERE task_id = ?
            """,
                (status.value, started_at, completed_at, truncated_result, truncated_error, task_id),
            )
            await db.commit()

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """Get a single task by ID."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_task(row)
        return None

    async def get_running_tasks(self) -> list[TaskRecord]:
        """Get all currently running tasks."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC",
                (TaskStatus.RUNNING.value,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_task(row) for row in rows]

    async def get_task_history(
        self,
        limit: int = 100,
        tool_name: str | None = None,
        status: TaskStatus | None = None,
    ) -> list[TaskRecord]:
        """Get task history with optional filtering."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            query = "SELECT * FROM tasks"
            params: list = []
            conditions = []

            if tool_name:
                conditions.append("tool_name = ?")
                params.append(tool_name)

            if status:
                conditions.append("status = ?")
                params.append(status.value)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_task(row) for row in rows]

    async def get_stats(self) -> dict:
        """Get aggregate statistics."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Count by status
            async with db.execute("""
                SELECT status, COUNT(*) as count FROM tasks GROUP BY status
            """) as cursor:
                status_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # Count by tool
            async with db.execute("""
                SELECT tool_name, COUNT(*) as count FROM tasks GROUP BY tool_name
            """) as cursor:
                tool_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # Recent success rate (last 24h)
            yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            async with db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as success
                FROM tasks WHERE completed_at > ? AND completed_at IS NOT NULL
            """,
                (TaskStatus.COMPLETED.value, yesterday),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    total, success = row[0] or 0, row[1] or 0
                else:
                    total, success = 0, 0
                success_rate = (success / total * 100) if total > 0 else 0

            return {
                "by_status": status_counts,
                "by_tool": tool_counts,
                "total_tasks": sum(status_counts.values()),
                "running_count": status_counts.get(TaskStatus.RUNNING.value, 0),
                "success_rate_24h": round(success_rate, 1),
            }

    async def cleanup_old_tasks(self, days: int = 7) -> int:
        """Delete tasks older than N days. Returns count deleted."""
        await self.initialize()

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM tasks
                WHERE created_at < ? AND status IN (?, ?, ?)
            """,
                (cutoff, TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value),
            )
            await db.commit()
            return cursor.rowcount

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> TaskRecord:
        """Convert DB row to TaskRecord."""
        input_params_raw = row["input_params"]
        try:
            loaded = json.JSONDecoder().decode(input_params_raw)
        except json.JSONDecodeError:
            loaded = {}
        input_params = loaded if isinstance(loaded, dict) else {}

        return TaskRecord(
            task_id=row["task_id"],
            tool_name=row["tool_name"],
            status=TaskStatus(row["status"]),
            stage=TaskStage(row["stage"]) if row["stage"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            progress_current=row["progress_current"],
            progress_total=row["progress_total"],
            progress_message=row["progress_message"],
            input_params=input_params,
            result=row["result"],
            error=row["error"],
            session_id=row["session_id"],
        )


# Singleton instance for server use
_task_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """Get the singleton TaskStore instance."""
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store
