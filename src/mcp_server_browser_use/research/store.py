"""In-memory task store for research tasks."""

import asyncio
import logging
from typing import Optional
from uuid import uuid4

from browser_use import BrowserProfile

from .machine import ResearchMachine
from .models import ResearchState, ResearchTask

logger = logging.getLogger(__name__)

# Global task store
_tasks: dict[str, ResearchTask] = {}
_machines: dict[str, ResearchMachine] = {}


def create_task(topic: str, max_searches: int = 5, save_path: Optional[str] = None) -> ResearchTask:
    """Create a new research task."""
    task_id = str(uuid4())[:8]  # Short ID for convenience
    task = ResearchTask(
        id=task_id,
        topic=topic,
        max_searches=max_searches,
        save_path=save_path,
    )
    _tasks[task_id] = task
    logger.info(f"Created research task {task_id} for topic: {topic}")
    return task


def get_task(task_id: str) -> Optional[ResearchTask]:
    """Get a task by ID."""
    return _tasks.get(task_id)


def list_tasks() -> list[ResearchTask]:
    """List all tasks."""
    return list(_tasks.values())


def delete_task(task_id: str) -> bool:
    """Delete a task and cancel if running."""
    task = _tasks.get(task_id)
    if not task:
        return False

    # Cancel if running
    if task._asyncio_task and not task._asyncio_task.done():
        task._asyncio_task.cancel()

    # Clean up
    if task_id in _machines:
        del _machines[task_id]
    del _tasks[task_id]

    logger.info(f"Deleted research task {task_id}")
    return True


async def start_task(task: ResearchTask, llm, browser_profile: BrowserProfile) -> None:
    """Start executing a research task in the background."""
    if task.state != ResearchState.PENDING:
        raise ValueError(f"Task {task.id} is not in PENDING state (current: {task.state})")

    # Create and store the machine
    machine = ResearchMachine(task, llm, browser_profile)
    _machines[task.id] = machine

    # Create background task
    async def run_with_cleanup():
        try:
            await machine.run()
        except asyncio.CancelledError:
            task.state = ResearchState.CANCELLED
            logger.info(f"Task {task.id} was cancelled")
        except Exception as e:
            task.state = ResearchState.FAILED
            task.error = str(e)
            logger.error(f"Task {task.id} failed: {e}")
        finally:
            if task.id in _machines:
                del _machines[task.id]

    task._asyncio_task = asyncio.create_task(run_with_cleanup())
    logger.info(f"Started research task {task.id}")


async def cancel_task(task_id: str) -> bool:
    """Cancel a running research task."""
    task = _tasks.get(task_id)
    if not task:
        return False

    machine = _machines.get(task_id)
    if machine:
        await machine.cancel()

    if task._asyncio_task and not task._asyncio_task.done():
        task._asyncio_task.cancel()

    logger.info(f"Cancelled research task {task_id}")
    return True
