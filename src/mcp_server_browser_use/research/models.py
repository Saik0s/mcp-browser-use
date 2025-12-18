"""Data models for deep research tasks."""

from dataclasses import dataclass


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
    source: ResearchSource | None = None
    error: str | None = None
