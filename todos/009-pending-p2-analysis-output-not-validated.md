---
status: pending
priority: p2
issue_id: "009"
tags: [code-review, reliability]
dependencies: []
---

# Validate LLM analysis output before persisting recipes

## Problem Statement

Analyzer accepts LLM JSON without schema validation. Invalid parameter names or malformed request fields can create broken recipes that fail at runtime.

## Findings

- `_parse_analysis_response` only JSON-decodes content. `src/mcp_server_browser_use/recipes/analyzer.py:91-118`
- `_build_recipe` uses fields without validation (empty param names, missing URL). `src/mcp_server_browser_use/recipes/analyzer.py:130-166`

## Proposed Solutions

### Option 1: Add Pydantic model validation

**Approach:** Define a strict Pydantic model for analyzer output and reject invalid responses with a retry prompt.

**Pros:** Strong validation; clearer errors.

**Cons:** More code and LLM retry logic.

**Effort:** Medium

**Risk:** Medium

---

### Option 2: Add lightweight validation guards

**Approach:** Validate URL, parameter names, and response_type before saving.

**Pros:** Small change; improves robustness.

**Cons:** Less comprehensive than full schema.

**Effort:** Small

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/analyzer.py:91`
- `src/mcp_server_browser_use/recipes/analyzer.py:130`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Analyzer rejects invalid output with clear errors
- [ ] Valid output consistently produces runnable recipes

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed analyzer parsing and build logic

**Learnings:**
- No schema validation for LLM output

## Notes

- Consider logging invalid outputs for debugging.
