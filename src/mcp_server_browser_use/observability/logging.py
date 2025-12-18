"""Structured logging with per-task context using structlog and contextvars."""

import logging
from contextvars import ContextVar

import structlog

# Context variables for current task
current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)
current_tool_name: ContextVar[str | None] = ContextVar("current_tool_name", default=None)

_configured = False


def setup_structured_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON output and per-task context.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    global _configured
    if _configured:
        return

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # Inject task context
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
    )

    _configured = True


def bind_task_context(task_id: str, tool_name: str) -> None:
    """Bind task context for all subsequent logs in this async context.

    Args:
        task_id: Unique task identifier
        tool_name: Name of the tool being executed
    """
    current_task_id.set(task_id)
    current_tool_name.set(tool_name)
    structlog.contextvars.bind_contextvars(task_id=task_id, tool_name=tool_name)


def clear_task_context() -> None:
    """Clear task context after task completes."""
    current_task_id.set(None)
    current_tool_name.set(None)
    structlog.contextvars.clear_contextvars()


def get_task_logger(name: str = "mcp_server_browser_use") -> structlog.stdlib.BoundLogger:
    """Get a structlog logger with task context.

    Args:
        name: Logger name

    Returns:
        Bound logger with task context
    """
    return structlog.get_logger(name)


def get_current_task_id() -> str | None:
    """Get the current task ID from context."""
    return current_task_id.get()


def get_current_tool_name() -> str | None:
    """Get the current tool name from context."""
    return current_tool_name.get()
