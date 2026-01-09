---
status: pending
priority: p3
issue_id: "012"
tags: [code-review, quality]
dependencies: []
---

# Strengthen recipe execution result validation

## Problem Statement

Recipe validation only checks for non-empty output. Outdated hints or incorrect results can still be marked as success and skew usage stats.

## Findings

- Validation is a non-empty string check. `src/mcp_server_browser_use/recipes/executor.py:49-71`
- `settings.recipes.validate_results` defaults to true but has weak logic. `src/mcp_server_browser_use/config.py:213-215`

## Proposed Solutions

### Option 1: Validate against extract_path/schema

**Approach:** If `recipe.request.extract_path` exists, require extracted data to be non-empty and valid.

**Pros:** Better signal; minimal change.

**Cons:** Only applies to direct execution recipes.

**Effort:** Small

**Risk:** Low

---

### Option 2: Support custom validation rules

**Approach:** Add optional regex or JSON schema to Recipe definitions.

**Pros:** Flexible; works for legacy hints.

**Cons:** More schema/UX work.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/executor.py:49`
- `src/mcp_server_browser_use/config.py:213`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Validation rejects obviously incorrect results
- [ ] Usage stats reflect actual success

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed validation logic and settings

**Learnings:**
- Validation does not check content shape

## Notes

- Keep validation lightweight to avoid false negatives.
