# Deep Research with Background Execution

## Overview
Implement deep research as a background task that LLM can start, monitor, and retrieve results from.

**Architecture**: Custom state machine (no LangChain/LangGraph)

## MCP Tools Design

### 1. `start_deep_research`
```python
async def start_deep_research(
    topic: str,
    max_searches: int = 5,
    save_to_file: Optional[str] = None
) -> dict:
    """
    Start a background deep research task.

    Returns:
        {"task_id": str, "status": "started", "topic": str}
    """
```

### 2. `get_research_status`
```python
async def get_research_status(task_id: str) -> dict:
    """
    Check status of a research task.

    Returns:
        {
            "task_id": str,
            "status": "running" | "completed" | "failed",
            "progress": {"current_step": int, "total_steps": int, "current_action": str},
            "partial_results": list[str]  # Results found so far
        }
    """
```

### 3. `get_research_result`
```python
async def get_research_result(task_id: str) -> dict:
    """
    Get final research result.

    Returns:
        {
            "task_id": str,
            "status": "completed",
            "report": str,  # Markdown report
            "sources": list[{"title": str, "url": str, "summary": str}],
            "file_path": Optional[str]  # If saved to file
        }
    """
```

### 4. `cancel_research`
```python
async def cancel_research(task_id: str) -> dict:
    """Cancel a running research task."""
```

## Research Workflow

```
1. Generate Queries
   - LLM generates 3-5 search queries from topic

2. Execute Searches (parallel or sequential)
   - For each query:
     - Browser agent searches and extracts info
     - Store partial results
     - Update progress

3. Synthesize Report
   - LLM combines all findings
   - Generate markdown report with sources

4. Save & Return
   - Optionally save to file
   - Mark task completed
```

## Implementation Structure

### New file: `src/mcp_server_browser_use/research.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4
import asyncio

class ResearchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ResearchProgress:
    current_step: int = 0
    total_steps: int = 0
    current_action: str = ""

@dataclass
class ResearchSource:
    title: str
    url: str
    summary: str

@dataclass
class ResearchTask:
    id: str
    topic: str
    status: ResearchStatus = ResearchStatus.PENDING
    progress: ResearchProgress = field(default_factory=ResearchProgress)
    partial_results: list[str] = field(default_factory=list)
    sources: list[ResearchSource] = field(default_factory=list)
    report: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

# In-memory task store
_tasks: dict[str, ResearchTask] = {}

async def run_research(task_id: str, topic: str, max_searches: int, llm, browser_profile):
    """Execute the research workflow."""
    task = _tasks[task_id]
    task.status = ResearchStatus.RUNNING

    try:
        # Step 1: Generate search queries
        task.progress.current_action = "Generating search queries"
        queries = await generate_search_queries(topic, max_searches, llm)
        task.progress.total_steps = len(queries) + 1  # +1 for synthesis

        # Step 2: Execute searches
        for i, query in enumerate(queries):
            if task.status == ResearchStatus.CANCELLED:
                return

            task.progress.current_step = i + 1
            task.progress.current_action = f"Searching: {query}"

            result = await execute_search(query, llm, browser_profile)
            task.partial_results.append(result["summary"])
            if result.get("source"):
                task.sources.append(ResearchSource(**result["source"]))

        # Step 3: Synthesize report
        task.progress.current_action = "Synthesizing report"
        task.report = await synthesize_report(topic, task.partial_results, task.sources, llm)

        task.status = ResearchStatus.COMPLETED
        task.completed_at = datetime.now()

    except Exception as e:
        task.status = ResearchStatus.FAILED
        task.error = str(e)
```

## Changes to server.py

Add the 4 new tools that use the research module.

## Configuration Additions

```python
class ResearchSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_RESEARCH_")

    max_searches: int = Field(default=5)
    save_directory: Optional[str] = Field(default=None)
    search_timeout: int = Field(default=120)  # seconds per search
```

## File Structure After Implementation

```
src/mcp_server_browser_use/
├── __init__.py
├── cli.py
├── config.py          # Add ResearchSettings
├── exceptions.py
├── providers.py
├── research.py        # NEW: Research task management
└── server.py          # Add 4 new tools
```

## Custom State Machine Design

Based on browser-use-web-ui patterns, simplified without LangChain:

### States
```python
class ResearchState(str, Enum):
    PLANNING = "planning"           # Generating search queries
    EXECUTING = "executing"         # Running browser searches
    SYNTHESIZING = "synthesizing"   # Creating final report
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### State Machine Flow
```
START → PLANNING → EXECUTING → SYNTHESIZING → COMPLETED
            ↓          ↓            ↓
         FAILED     FAILED       FAILED
            ↓          ↓            ↓
        CANCELLED  CANCELLED   CANCELLED
```

### Research Machine Class
```python
class ResearchMachine:
    """Custom state machine for deep research workflow."""

    def __init__(self, task: ResearchTask, llm, browser_profile):
        self.task = task
        self.llm = llm
        self.browser_profile = browser_profile
        self._cancel_event = asyncio.Event()

    async def run(self):
        """Execute the state machine."""
        try:
            # PLANNING
            self.task.state = ResearchState.PLANNING
            self.task.progress.current_action = "Generating search plan"
            queries = await self._generate_queries()

            # EXECUTING
            self.task.state = ResearchState.EXECUTING
            self.task.progress.total_steps = len(queries)
            for i, query in enumerate(queries):
                if self._cancel_event.is_set():
                    self.task.state = ResearchState.CANCELLED
                    return

                self.task.progress.current_step = i + 1
                self.task.progress.current_action = f"Searching: {query}"
                result = await self._execute_search(query)
                self.task.partial_results.append(result)

            # SYNTHESIZING
            self.task.state = ResearchState.SYNTHESIZING
            self.task.progress.current_action = "Synthesizing report"
            self.task.report = await self._synthesize_report()

            # COMPLETED
            self.task.state = ResearchState.COMPLETED

        except Exception as e:
            self.task.state = ResearchState.FAILED
            self.task.error = str(e)

    async def cancel(self):
        """Request cancellation."""
        self._cancel_event.set()

    async def _generate_queries(self) -> list[str]:
        """Use LLM to generate search queries from topic."""
        # Use browser-use's LLM directly
        pass

    async def _execute_search(self, query: str) -> dict:
        """Execute browser search for a single query."""
        # Use browser-use Agent
        pass

    async def _synthesize_report(self) -> str:
        """Use LLM to synthesize findings into report."""
        pass
```

## File Structure

```
src/mcp_server_browser_use/
├── __init__.py
├── cli.py
├── config.py          # Add ResearchSettings
├── exceptions.py
├── providers.py
├── research/          # NEW: Research module
│   ├── __init__.py
│   ├── models.py      # ResearchTask, ResearchState, etc.
│   ├── machine.py     # ResearchMachine state machine
│   ├── prompts.py     # LLM prompts for planning/synthesis
│   └── store.py       # In-memory task store
└── server.py          # Add 4 new tools
```

## Dependencies

No new dependencies needed - uses existing:
- browser-use Agent for searches
- asyncio for background tasks
- LLM (via browser-use providers) for query generation and synthesis
