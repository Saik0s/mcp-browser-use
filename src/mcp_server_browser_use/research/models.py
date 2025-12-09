"""Data models for deep research tasks."""

from dataclasses import dataclass
from typing import Optional


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
