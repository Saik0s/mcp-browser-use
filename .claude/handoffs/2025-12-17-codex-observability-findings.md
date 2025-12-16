# Session Handoff: Codex Review Findings for Observability Stack

## 1. Primary Request and Intent
The user implemented a comprehensive observability stack for mcp-browser-use MCP server. After implementation, Codex was run to review the code and found multiple issues. Two critical bugs were fixed before merging, but several other findings remain as technical debt for future improvement.

The purpose of this handoff is to document all Codex findings so the next agent can work on addressing them.

## 2. Key Technical Concepts
- **TaskStore**: SQLite-based async task persistence using aiosqlite
- **TaskRecord**: Pydantic model for task state (status, stage, progress, timestamps)
- **structlog + contextvars**: Per-task logging context that propagates through async calls
- **MCP Tools**: FastMCP tools for health_check, task_list, task_get
- **CLI Commands**: Typer commands for tasks, task, health
- **Skills Direct Execution**: CDP-based fetch() execution that bypasses browser-use agent

## 3. Files and Code Sections

### src/mcp_server_browser_use/observability/store.py
- **Why important**: Core SQLite storage for task tracking - has multiple Codex findings
- **Issues to fix**:
  1. Line 133-138: `update_status(RUNNING)` overwrites `started_at` on repeated calls
  2. Line 228-244: Success rate uses `created_at` instead of `completed_at`
  3. Line 74: INSERT without column names
  4. Line 258: Uses deprecated `datetime.utcnow()`
  5. No WAL mode or busy_timeout for concurrent access

```python
# Issue: started_at gets overwritten on repeated RUNNING calls
if status == TaskStatus.RUNNING:
    updates.append("started_at = ?")
    params.append(datetime.utcnow().isoformat())  # Should only set if NULL

# Issue: success rate based on created_at, not completed_at
yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
# Should use completed_at for accurate completion-based success rate
```

### src/mcp_server_browser_use/observability/logging.py
- **Why important**: Structured logging setup - never actually called
- **Issue**: `setup_structured_logging()` is defined but never invoked during server startup

```python
def setup_structured_logging(level: str = "INFO") -> None:
    """Configure structlog with JSON output and per-task context."""
    # This function exists but is never called in server.py
```

### src/mcp_server_browser_use/server.py
- **Why important**: Main MCP server with task tracking integration
- **Issues to fix**:
  1. Line 57: TaskConfig imported from wrong module (pyright warning)
  2. Line 476: run_deep_research file path uses unsanitized topic (path traversal risk)
  3. Line 274-289: step_callback does DB write on every step (performance)

```python
# Issue: Import from wrong module
from fastmcp.server.server import TaskConfig  # Should be from fastmcp.server.tasks.config

# Issue: Unsanitized filename
save_path = f"{settings.research.save_directory}/{topic[:50].replace(' ', '_')}.md"
# Can contain /, .., : etc. - needs sanitization
```

### src/mcp_server_browser_use/cli.py
- **Why important**: CLI with new observability commands
- **Issues to fix**:
  1. Line 84: `-h` for `--host` conflicts with help convention
  2. Line 52: `_read_server_info()` has no key validation
  3. Line 119: Transport type issue (pyright warning)

```python
# Issue: -h commonly means --help
host: str = typer.Option(None, "--host", "-h", help="Host to bind to")
# Consider using -H for host

# Issue: No validation of server info dict
def _read_server_info() -> dict | None:
    # Assumes pid/host/port/transport exist, KeyError if corrupted
```

### src/mcp_server_browser_use/observability/models.py
- **Why important**: Data models for task tracking
- **Issue**: Line 43 uses naive UTC datetimes

```python
# Issue: Deprecated datetime.utcnow()
created_at: datetime = Field(default_factory=datetime.utcnow)
# Should use: datetime.now(timezone.utc)
```

## 4. Problem Solving

**Fixed before merge:**
1. ✅ Direct skill execution path now properly completes task tracking
2. ✅ skill_params JSON parsing validates it's a dict

**Still pending (from Codex review):**
- High-impact: structlog not initialized, success rate calculation, started_at overwrite
- Type-safety: TaskConfig import, transport type, untyped containers, naive datetimes
- Security: attack surface of introspection tools, prompt/result persistence, path traversal
- Performance: SQLite write on every step, no WAL mode, INSERT without columns

## 5. Pending Tasks
Address the Codex review findings in priority order:

### High Priority (Correctness)
1. Call `setup_structured_logging()` during server startup
2. Fix success rate calculation to use `completed_at`
3. Only set `started_at` if currently NULL
4. Ensure `utils.py` is committed

### Medium Priority (Type Safety)
5. Fix TaskConfig import path
6. Fix transport type in CLI
7. Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`

### Medium Priority (Security)
8. Sanitize topic for filename in run_deep_research
9. Consider gating introspection tools or redacting sensitive fields

### Lower Priority (Performance/Quality)
10. Enable SQLite WAL mode + busy_timeout
11. Throttle step_callback DB writes (once per second or on change)
12. Use explicit column names in INSERT
13. Change `-h` to `-H` for host option
14. Add key validation to `_read_server_info()`
15. Use tokens for contextvars restoration instead of clearing all

## 6. Current Work
The observability stack has been merged to main. Documentation (CLAUDE.md, README.md) was updated to include the new observability module but changes are unstaged.

## 7. Next Step
Commit the documentation updates, then start addressing Codex findings in priority order, beginning with calling `setup_structured_logging()` during server startup.
