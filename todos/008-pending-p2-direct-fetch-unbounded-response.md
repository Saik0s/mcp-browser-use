---
status: pending
priority: p2
issue_id: "008"
tags: [code-review, performance]
dependencies: []
---

# Cap direct fetch response size

## Problem Statement

Direct fetch returns the full response body from the browser with no size limit. Large responses can spike memory and slow the CDP transfer.

## Findings

- `_execute_fetch` returns `raw_body` without size checks. `src/mcp_server_browser_use/recipes/runner.py:500-512`
- Recorder enforces `MAX_BODY_SIZE`, but direct execution does not. `src/mcp_server_browser_use/recipes/recorder.py:56-57`

## Proposed Solutions

### Option 1: Truncate response in JS

**Approach:** After `response.text()` or `response.json()`, truncate to `MAX_BODY_SIZE` before returning to Python.

**Pros:** Limits memory and transfer size.

**Cons:** Partial data for large payloads.

**Effort:** Small

**Risk:** Low

---

### Option 2: Add configurable response limit

**Approach:** Introduce `max_response_bytes` in settings or RecipeRequest.

**Pros:** Flexible per skill/environment.

**Cons:** Requires config wiring.

**Effort:** Medium

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/runner.py:500`
- `src/mcp_server_browser_use/recipes/recorder.py:56`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Direct execution enforces a response size limit
- [ ] Oversized responses are truncated or rejected with clear errors

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Compared recorder vs direct execution body handling

**Learnings:**
- Direct path has no size guard

## Notes

- Consider logging when truncation occurs.
