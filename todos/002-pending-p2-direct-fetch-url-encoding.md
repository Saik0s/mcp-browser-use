---
status: pending
priority: p2
issue_id: "002"
tags: [code-review, correctness, security]
dependencies: []
---

# Fix URL encoding mismatch in direct fetch

## Problem Statement

Direct execution builds the fetch URL using naive string replacement, while the SSRF validation path uses a URL-encoding helper. Parameters with spaces or special characters can generate invalid or inconsistent URLs.

## Findings

- `SkillRequest.build_url` uses plain `str.replace` with no encoding. `src/mcp_server_browser_use/skills/models.py:146-151`
- `_execute_fetch` uses `request.build_url`, bypassing the encoder in `skills.runner.build_url`. `src/mcp_server_browser_use/skills/runner.py:451`
- `skills.runner.build_url` already implements proper encoding and is covered by tests. `src/mcp_server_browser_use/skills/runner.py:156-187`

## Proposed Solutions

### Option 1: Use the encoded helper everywhere

**Approach:** Replace `request.build_url` usage with `skills.runner.build_url` in `_execute_fetch` and/or update `SkillRequest.build_url` to call the helper.

**Pros:** Consistent URL handling; aligns with tests.

**Cons:** Behavior change for existing skills with unencoded placeholders.

**Effort:** Small

**Risk:** Low

---

### Option 2: Remove `SkillRequest.build_url`

**Approach:** Remove or deprecate the method to force use of the shared encoder.

**Pros:** One canonical URL path.

**Cons:** Wider refactor; API change.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/skills/models.py:146`
- `src/mcp_server_browser_use/skills/runner.py:451`
- `src/mcp_server_browser_use/skills/runner.py:156`

## Resources

- `tests/test_skills_security.py` (URL encoding tests)

## Acceptance Criteria

- [ ] Direct execution uses URL-encoded params
- [ ] Tests cover direct execution URL construction

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Compared URL builders and direct fetch path
- Mapped test coverage gaps

**Learnings:**
- Validation and execution use different URL builders

## Notes

- Consider adding a unit test for `SkillRequest.build_url` or removing it.
