---
status: pending
priority: p3
issue_id: "014"
tags: [code-review, quality]
dependencies: []
---

# Preserve raw body on fetch parse errors

## Problem Statement

When JSON parsing fails in the browser fetch helper, the code tries to clone the response after it has already been read. This can return an empty body and hide useful error context.

## Findings

- `response.json()` runs before `response.clone().text()`, so the body may already be consumed. `src/mcp_server_browser_use/recipes/runner.py:554-566`

## Proposed Solutions

### Option 1: Read text once and parse

**Approach:** Call `response.text()` once, then `JSON.parse` inside try/catch.

**Pros:** Single read; preserves raw body.

**Cons:** Slightly more JS logic.

**Effort:** Small

**Risk:** Low

---

### Option 2: Clone before parsing

**Approach:** `const clone = response.clone();` before calling `response.json()`.

**Pros:** Minimal change.

**Cons:** Still does two reads.

**Effort:** Small

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/runner.py:554`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Raw body is available when JSON parsing fails
- [ ] Error messages include response context

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed fetch error path in JS helper

**Learnings:**
- Response body may be consumed before clone

## Notes

- Keep response size limits in mind if adding raw body to errors.
