---
status: pending
priority: p2
issue_id: "006"
tags: [code-review, reliability, performance]
dependencies: []
---

# Clean up background task entries in _running_tasks

## Problem Statement

Background tasks created for `/api/recipes/{name}/run` and `/api/learn` are stored under `_bg` keys and never removed. This grows unbounded over time.

## Findings

- `_running_tasks[f"{task_id}_bg"]` stored without cleanup. `src/mcp_server_browser_use/server.py:1133-1136` and `src/mcp_server_browser_use/server.py:1281-1284`

## Proposed Solutions

### Option 1: Add done callback cleanup

**Approach:** Register `bg_task.add_done_callback` to remove the `_bg` key on completion.

**Pros:** Minimal change; preserves behavior.

**Cons:** Must handle exceptions in callback.

**Effort:** Small

**Risk:** Low

---

### Option 2: Track background tasks separately

**Approach:** Use a WeakValueDictionary or scoped set with periodic cleanup.

**Pros:** Avoids manual cleanup.

**Cons:** More moving parts.

**Effort:** Medium

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/server.py:1133`
- `src/mcp_server_browser_use/server.py:1281`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] `_running_tasks` does not grow after background tasks finish
- [ ] No regression in task cancellation behavior

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed background task creation paths

**Learnings:**
- `_bg` keys are never removed

## Notes

- Ensure cleanup runs even on exceptions.
