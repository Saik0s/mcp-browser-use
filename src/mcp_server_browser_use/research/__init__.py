"""Deep research module with native MCP background task support."""

from .machine import ResearchMachine
from .models import ResearchSource, SearchResult

__all__ = [
    "ResearchMachine",
    "ResearchSource",
    "SearchResult",
]
