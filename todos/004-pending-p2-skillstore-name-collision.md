---
status: pending
priority: p2
issue_id: "004"
tags: [code-review, reliability]
dependencies: []
---

# Prevent skill name collisions from filename sanitization

## Problem Statement

Skill filenames are derived from sanitized names. Different names can map to the same filename, causing silent overwrite.

## Findings

- `_skill_path` lowercases and replaces non-alnum with `-`. `src/mcp_server_browser_use/skills/store.py:42-46`
- No collision check before save. `src/mcp_server_browser_use/skills/store.py:91-99`

## Proposed Solutions

### Option 1: Add collision-resistant suffix

**Approach:** Append a short hash of the original name when the sanitized filename already exists.

**Pros:** Prevents overwrites; keeps readable filenames.

**Cons:** Requires mapping name to filename on load.

**Effort:** Medium

**Risk:** Low

---

### Option 2: Reject duplicates explicitly

**Approach:** If sanitized filename exists and stored name differs, raise error on save.

**Pros:** Simple; avoids silent data loss.

**Cons:** Can block legitimate updates unless user renames.

**Effort:** Small

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/skills/store.py:42`
- `src/mcp_server_browser_use/skills/store.py:91`

## Resources

- `docs/skills-design.md`

## Acceptance Criteria

- [ ] Distinct skill names never overwrite each other
- [ ] Collision handling is explicit and test-covered

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed filename sanitization path

**Learnings:**
- Sanitization is lossy and unguarded

## Notes

- Consider storing a name->path index in store if collisions become common.
