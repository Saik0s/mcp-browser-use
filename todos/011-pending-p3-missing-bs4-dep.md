---
status: pending
priority: p3
issue_id: "011"
tags: [code-review, quality]
dependencies: []
---

# Declare BeautifulSoup dependency for HTML extraction

## Problem Statement

HTML response extraction relies on BeautifulSoup, but the dependency is not declared. Runtime falls back to raw HTML, making `html_selectors` ineffective.

## Findings

- HTML parsing uses BeautifulSoup. `src/mcp_server_browser_use/recipes/runner.py:606-623`
- `bs4` is not in `pyproject.toml` dependencies. `pyproject.toml:18-33`

## Proposed Solutions

### Option 1: Add optional dependency

**Approach:** Add `beautifulsoup4` under optional dependencies and document when required.

**Pros:** Explicit; does not force install for all users.

**Cons:** Requires user opt-in.

**Effort:** Small

**Risk:** Low

---

### Option 2: Remove HTML selector feature

**Approach:** Drop `html_selectors` support until dependency is added.

**Pros:** Avoids hidden failures.

**Cons:** Reduces functionality.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/runner.py:606`
- `pyproject.toml:18`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] HTML extraction works when `html_selectors` is provided
- [ ] Dependency requirements are documented

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Checked runtime import and dependency list

**Learnings:**
- HTML extraction silently degrades

## Notes

- Ask before adding dependency (per project rules).
