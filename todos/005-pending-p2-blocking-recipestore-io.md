---
status: pending
priority: p2
issue_id: "005"
tags: [code-review, performance]
dependencies: []
---

# Avoid blocking file I/O in async recipe endpoints

## Problem Statement

Async HTTP endpoints call synchronous RecipeStore I/O directly. Under load, YAML reads/writes block the event loop and delay other requests.

## Findings

- `api_recipes` and related routes call `store.list_all()`/`load()` in async handlers. `src/mcp_server_browser_use/server.py:956-1004`
- RecipeStore uses blocking file I/O. `src/mcp_server_browser_use/recipes/store.py:63-130`

## Proposed Solutions

### Option 1: Use threadpool for store calls

**Approach:** Wrap store operations in `asyncio.to_thread` or `anyio.to_thread.run_sync`.

**Pros:** Minimal changes; preserves API.

**Cons:** Adds threadpool overhead.

**Effort:** Small

**Risk:** Low

---

### Option 2: Implement async store

**Approach:** Use async file I/O (aiofiles) for load/save/list.

**Pros:** Better scalability; consistent async style.

**Cons:** Larger refactor.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/server.py:956`
- `src/mcp_server_browser_use/recipes/store.py:63`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Async endpoints do not perform blocking file I/O
- [ ] Response latency remains stable under concurrent requests

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed REST handlers and RecipeStore implementation

**Learnings:**
- Store I/O is synchronous in async contexts

## Notes

- Threadpool approach likely enough for current traffic.
