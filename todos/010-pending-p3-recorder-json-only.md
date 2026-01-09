---
status: pending
priority: p3
issue_id: "010"
tags: [code-review, reliability]
dependencies: []
---

# Capture non-JSON API responses during learning

## Problem Statement

Recorder only captures response bodies for JSON content types. Recipes cannot be learned for APIs that return JSON with `text/plain` or HTML responses needed for extraction.

## Findings

- JSON-only filter in recorder. `src/mcp_server_browser_use/recipes/recorder.py:46-53`
- Body capture only happens for JSON content types. `src/mcp_server_browser_use/recipes/recorder.py:219-227`

## Proposed Solutions

### Option 1: Expand content type allowlist

**Approach:** Include `text/plain`, `text/html`, and vendor JSON types in `JSON_CONTENT_TYPES`.

**Pros:** Better coverage; small change.

**Cons:** More data captured; potential noise.

**Effort:** Small

**Risk:** Low

---

### Option 2: Capture all XHR/Fetch bodies with size cap

**Approach:** Remove content-type filter and rely on `MAX_BODY_SIZE`.

**Pros:** Most reliable for learning.

**Cons:** Higher overhead; more noise for analyzer.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/recorder.py:46`
- `src/mcp_server_browser_use/recipes/recorder.py:219`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Learning can capture non-JSON API responses
- [ ] Analyzer receives response bodies for targeted APIs

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed recorder content-type filters

**Learnings:**
- Non-JSON APIs are ignored

## Notes

- Consider gating with a config flag.
