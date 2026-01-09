---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, security, api]
dependencies: []
---

# Enforce auth_token on recipes HTTP endpoints

## Problem Statement

ServerSettings exposes `auth_token` for non-localhost access, but recipes HTTP routes do not enforce it. If the server binds beyond localhost, remote callers can list/delete/run recipes and trigger learning with local browser cookies.

## Findings

- `src/mcp_server_browser_use/config.py:185-195` defines `auth_token`, but no route guards exist.
- `/api/recipes/*` and `/api/learn` handlers accept requests without authentication. `src/mcp_server_browser_use/server.py:950` `src/mcp_server_browser_use/server.py:1148`

## Proposed Solutions

### Option 1: Add auth middleware for HTTP routes

**Approach:** Add a shared auth check for all HTTP routes when `settings.server.auth_token` is set.

**Pros:** Centralized enforcement, consistent behavior.

**Cons:** Touches routing setup; needs testing for all endpoints.

**Effort:** Medium

**Risk:** Medium

---

### Option 2: Add per-route auth checks

**Approach:** Add Authorization header checks in each recipes/learn route.

**Pros:** Small, isolated changes.

**Cons:** Duplication; easier to miss future routes.

**Effort:** Small

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `src/mcp_server_browser_use/config.py:185`
- `src/mcp_server_browser_use/server.py:950`
- `src/mcp_server_browser_use/server.py:1148`

## Resources

- `docs/recipes-design.md`

## Acceptance Criteria

- [ ] Unauthorized requests to `/api/recipes` and `/api/learn` return 401/403 when `auth_token` is set
- [ ] Authorized requests succeed
- [ ] Tests cover authenticated and unauthenticated cases

## Work Log

### 2026-01-04 - Initial Discovery

**By:** Codex

**Actions:**
- Reviewed server config and recipes HTTP routes
- Confirmed missing auth enforcement

**Learnings:**
- Risk only manifests when HTTP transport binds beyond localhost

## Notes

- Consider whether auth should apply to all HTTP routes, not just recipes.
