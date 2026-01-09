---
status: pending
priority: p3
issue_id: "013"
tags: [code-review, docs]
dependencies: []
---

# Align recipes documentation with CLI guidance

## Problem Statement

Docs state recipes are machine-generated, while CLI suggests manual creation or copying examples. This creates confusion about supported workflows.

## Findings

- Docs: recipes are machine-generated only. `docs/recipes-design.md:3-10`
- CLI suggests manual creation. `src/mcp_server_browser_use/cli.py:493-496`

## Proposed Solutions

### Option 1: Update CLI messaging

**Approach:** Replace manual creation suggestion with guidance to use `learn=True` and `save_recipe_as`.

**Pros:** Aligns with design docs.

**Cons:** Removes manual power-user guidance.

**Effort:** Small

**Risk:** Low

---

### Option 2: Update docs to allow manual recipes

**Approach:** Document manual recipe authoring as advanced feature.

**Pros:** Supports power users.

**Cons:** Requires validation and support commitment.

**Effort:** Medium

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `docs/recipes-design.md:3`
- `src/mcp_server_browser_use/cli.py:493`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Docs and CLI guidance are consistent

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Compared design docs with CLI output

**Learnings:**
- User guidance conflicts between sources

## Notes

- Decide if manual recipes are officially supported.
