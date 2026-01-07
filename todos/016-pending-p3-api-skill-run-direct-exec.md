---
status: pending
priority: p3
issue_id: "016"
tags: [code-review, performance, api]
dependencies: []
---

# Use direct execution in /api/skills/{name}/run

## Problem Statement

REST skill execution always uses the agent path, even when a skill supports direct execution. This misses the fast-path and increases latency.

## Findings

- API skill run builds an Agent with hints only. `src/mcp_server_browser_use/server.py:1089-1103`
- Direct execution path exists in `run_browser_agent` but not in REST `api_skill_run`.

## Proposed Solutions

### Option 1: Reuse SkillRunner in api_skill_run

**Approach:** If skill supports direct execution, attempt direct fetch first; fall back to agent on failure.

**Pros:** Faster; consistent behavior with run_browser_agent.

**Cons:** Needs careful error handling in background task.

**Effort:** Medium

**Risk:** Low

---

### Option 2: Expose a query flag for direct execution

**Approach:** Add a `direct=true` request field to opt in.

**Pros:** Backward compatible.

**Cons:** Requires API change and docs update.

**Effort:** Medium

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/server.py:1089`

## Resources

- `docs/skills-design.md`

## Acceptance Criteria

- [ ] REST skill run uses direct execution when available
- [ ] Agent fallback remains functional

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Compared REST skill run vs run_browser_agent paths

**Learnings:**
- Direct execution is not used in REST path

## Notes

- Consider returning direct result vs task tracking when direct execution succeeds quickly.
