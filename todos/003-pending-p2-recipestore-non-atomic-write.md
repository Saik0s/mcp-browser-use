---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, reliability]
dependencies: []
---

# Make RecipeStore writes atomic and concurrency-safe

## Problem Statement

Recipe YAML files are written directly with no atomic rename or locking. Concurrent save/record_usage calls can corrupt files or drop usage counts.

## Findings

- Direct write to final path. `src/mcp_server_browser_use/recipes/store.py:95-99`
- `record_usage` is read-modify-write with no lock. `src/mcp_server_browser_use/recipes/store.py:152-169`

## Proposed Solutions

### Option 1: Atomic write + file lock

**Approach:** Write to temp file, fsync, and atomic rename; use a cross-platform lock for updates.

**Pros:** Prevents corruption; safe under concurrency.

**Cons:** Adds locking dependency or custom logic.

**Effort:** Medium

**Risk:** Medium

---

### Option 2: Move usage stats to task store/SQLite

**Approach:** Store usage counters in SQLite and keep YAML immutable.

**Pros:** Avoids file contention; structured analytics.

**Cons:** Larger refactor and migration.

**Effort:** Large

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/recipes/store.py:95`
- `src/mcp_server_browser_use/recipes/store.py:152`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Concurrent writes do not corrupt YAML files
- [ ] Usage counters are consistent under parallel access

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed RecipeStore read/write flows
- Identified read-modify-write race

**Learnings:**
- Current store assumes single writer

## Notes

- Lock scope should cover load+save for counters.
