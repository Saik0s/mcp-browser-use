---
status: pending
priority: p3
issue_id: "015"
tags: [code-review, security]
dependencies: []
---

# Unify sensitive header allowlist/denylist handling

## Problem Statement

Recorder redacts a different set of sensitive headers than RecipeRequest strips on save. This inconsistency can leave tokens in recipe files or reduce redaction coverage.

## Findings

- Recorder redaction list includes `x-xsrf-token` and `x-access-token`. `src/mcp_server_browser_use/recipes/recorder.py:31-43`
- Recipe saving strip list differs. `src/mcp_server_browser_use/recipes/models.py:17-29`

## Proposed Solutions

### Option 1: Single shared constant

**Approach:** Move header set to a shared module and use it in both recorder and models.

**Pros:** Consistent behavior; easier to audit.

**Cons:** Small refactor across files.

**Effort:** Small

**Risk:** Low

---

### Option 2: Expand and document both lists

**Approach:** Keep separate lists but ensure they are aligned and documented.

**Pros:** Minimal code change.

**Cons:** Risk of drift returns.

**Effort:** Small

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/recorder.py:31`
- `src/mcp_server_browser_use/recipes/models.py:17`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Sensitive headers are handled consistently across recording and persistence
- [ ] Redaction/stripping list documented

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Compared header lists in recorder and models

**Learnings:**
- Lists diverged and can drift further

## Notes

- Consider covering with a unit test for expected headers.
