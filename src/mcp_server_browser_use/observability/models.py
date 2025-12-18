"""Data models for task observability."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStage(str, Enum):
    """Granular progress stages for browser agents."""

    INITIALIZING = "initializing"
    PLANNING = "planning"
    NAVIGATING = "navigating"
    EXTRACTING = "extracting"
    SYNTHESIZING = "synthesizing"
    FINALIZING = "finalizing"
    # Research-specific stages
    SEARCHING = "searching"
    ANALYZING = "analyzing"


class TaskRecord(BaseModel):
    """Record of a task execution for observability."""

    task_id: str
    tool_name: str  # run_browser_agent, run_deep_research, etc.
    status: TaskStatus = TaskStatus.PENDING
    stage: TaskStage | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Progress tracking
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str | None = None

    # Input/Output
    input_params: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    error: str | None = None

    # Context
    session_id: str | None = None  # For grouping related tasks

    @property
    def duration_seconds(self) -> float | None:
        """Calculate task duration in seconds."""
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.progress_total <= 0:
            return 0.0
        return min(100.0, (self.progress_current / self.progress_total) * 100)

    @property
    def is_terminal(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
