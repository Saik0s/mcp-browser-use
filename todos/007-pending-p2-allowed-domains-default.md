---
status: pending
priority: p2
issue_id: "007"
tags: [code-review, security]
dependencies: []
---

# Default allowed_domains for direct execution skills

## Problem Statement

`SkillRequest.allowed_domains` exists but is never populated by the analyzer. Domain allowlisting is effectively disabled for learned skills.

## Findings

- `SkillRequest.allowed_domains` defaults to empty (allow all). `src/mcp_server_browser_use/skills/models.py:143-144`
- Analyzer does not set allowed_domains from the request URL. `src/mcp_server_browser_use/skills/analyzer.py:130-142`
- `validate_domain_allowed` is a no-op when allowlist is empty. `src/mcp_server_browser_use/skills/runner.py:133-140`

## Proposed Solutions

### Option 1: Set allowed_domains from request URL

**Approach:** Parse request URL host in analyzer and set `allowed_domains=[host]` (or parent domain).

**Pros:** Immediate safety gain; low effort.

**Cons:** Might block legitimate cross-domain APIs.

**Effort:** Small

**Risk:** Low

---

### Option 2: Extend analysis prompt to return allowed_domains

**Approach:** Add `allowed_domains` to analysis output and fill it when present; fallback to request host.

**Pros:** More flexible; explicit in skill file.

**Cons:** Requires prompt update and validation.

**Effort:** Medium

**Risk:** Medium

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/skills/models.py:143`
- `src/mcp_server_browser_use/skills/analyzer.py:130`
- `src/mcp_server_browser_use/skills/runner.py:133`

## Resources

- `docs/skills-design.md`

## Acceptance Criteria

- [ ] Learned skills include a non-empty allowlist by default
- [ ] Direct execution rejects domains outside the allowlist

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Verified allowlist enforcement path

**Learnings:**
- Allowlist not populated in analyzer

## Notes

- Consider opt-out flag for advanced users.
