"""Data models for deep research tasks."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ResearchState(str, Enum):
    """States in the research state machine."""

    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ResearchProgress:
    """Progress tracking for a research task."""

    current_step: int = 0
    total_steps: int = 0
    current_action: str = ""


@dataclass
class ResearchSource:
    """A source found during research."""

    title: str
    url: str
    summary: str


@dataclass
class SearchResult:
    """Result from a single search query."""

    query: str
    summary: str
    source: Optional[ResearchSource] = None
    error: Optional[str] = None


@dataclass
class ResearchTask:
    """A deep research task that runs in the background."""

    id: str
    topic: str
    max_searches: int = 5
    state: ResearchState = ResearchState.PENDING
    progress: ResearchProgress = field(default_factory=ResearchProgress)
    search_results: list[SearchResult] = field(default_factory=list)
    report: Optional[str] = None
    save_path: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    _cancel_event: Optional[asyncio.Event] = field(default=None, repr=False, compare=False)

    def to_status_dict(self) -> dict:
        """Convert to status dict for MCP response."""
        return {
            "task_id": self.id,
            "topic": self.topic,
            "state": self.state.value,
            "progress": {
                "current_step": self.progress.current_step,
                "total_steps": self.progress.total_steps,
                "current_action": self.progress.current_action,
            },
            "partial_results": [r.summary for r in self.search_results if r.summary],
            "error": self.error,
        }

    def to_result_dict(self) -> dict:
        """Convert to result dict for MCP response."""
        return {
            "task_id": self.id,
            "topic": self.topic,
            "state": self.state.value,
            "report": self.report,
            "sources": [{"title": r.source.title, "url": r.source.url, "summary": r.source.summary} for r in self.search_results if r.source],
            "save_path": self.save_path,
            "error": self.error,
        }
