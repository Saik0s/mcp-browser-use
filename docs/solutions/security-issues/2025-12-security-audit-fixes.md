---
title: "Security Audit Fixes - December 2025"
category: security-issues
date: 2025-12-21
severity: critical
components:
  - skills/runner.py
  - observability/store.py
  - server.py
commits:
  - f3eeb19
  - faa3f10
  - e6cc929
tags:
  - ssrf
  - sql-injection
  - memory-leak
  - toctou
---

# Security Audit Fixes - December 2025

Three critical security and reliability issues identified and fixed during code audit.

## Fix 1: SSRF via DNS Rebinding (TOCTOU)

**Component:** `skills/runner.py:449-459`
**Severity:** Critical
**Commit:** `f3eeb19`

### Problem

DNS rebinding attack window existed between URL validation and fetch:
- Initial validation resolves domain to public IP
- Attacker rebinds DNS to private IP (127.0.0.1, 192.168.x.x)
- Fetch executes against internal resources

### Solution

Re-validate URL immediately before fetch to close TOCTOU window:

```python
# Before: Single validation at request time
url = request.build_url(params)
options = request.to_fetch_options(params)

# After: Re-validate immediately before fetch
url = request.build_url(params)
try:
    await validate_url_safe(url)  # Re-validate at fetch time
except ValueError as e:
    return SkillRunResult(success=False, error=f"SSRF blocked: {e}")
options = request.to_fetch_options(params)
```

### Prevention

- **Best Practice:** Validate URL at check-time AND immediately before network operations
- **Review Checklist:** All external network calls preceded by `validate_url_safe()` immediately before fetch
- **Test Strategy:** Mock `socket.getaddrinfo()` to return localhost on second call; test obfuscated IPs

---

## Fix 2: SQL Injection via F-string

**Component:** `observability/store.py:133-177`
**Severity:** High
**Commit:** `faa3f10`

### Problem

Dynamic SQL UPDATE building via f-string without validation:

```python
# Vulnerable
await db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
```

### Solution

Whitelist allowed columns and validate before query execution:

```python
ALLOWED_UPDATES = {"status = ?", "result = ?", "error = ?", ...}

for update in updates:
    if update not in ALLOWED_UPDATES:
        raise ValueError(f"Invalid update: {update}")

query = "UPDATE tasks SET " + ", ".join(updates) + " WHERE id = ?"
await db.execute(query, params)
```

### Prevention

- **Best Practice:** Always use `?` placeholders; whitelist dynamic column names
- **Review Checklist:** No string interpolation in SQL; all dynamic components validated
- **Test Strategy:** Inject SQL metacharacters (`'; DROP TABLE--`); verify whitelist rejects unknowns

---

## Fix 3: Memory Leak from CDP Listeners

**Component:** `server.py:345-489`
**Severity:** High
**Commit:** `e6cc929`

### Problem

CDP listener cleanup only in try/except blocks, missed on exceptions:

```python
# Cleanup scattered, easily missed
except Exception as e:
    if recorder:
        try:
            await recorder.detach()
        except: pass  # Swallowed
```

### Solution

Track attachment state and use `finally` block for guaranteed cleanup:

```python
recorder_attached = False
try:
    await recorder.attach(...)
    recorder_attached = True
    # ... work ...
finally:
    if recorder and recorder_attached:
        await recorder.detach()  # Always runs
```

### Prevention

- **Best Practice:** Track resource state with boolean; move cleanup to `finally`
- **Review Checklist:** All long-lived resources have attachment flag; no cleanup in except-only
- **Test Strategy:** Raise exceptions at different points; verify cleanup runs exactly once

---

## Cross-References

- **Test Suite:** `tests/test_skills_security.py` - comprehensive SSRF protection tests
- **Guidelines:** `CLAUDE.md` Security Considerations section
- **Architecture:** `docs/skills-design.md`

## Verification

All fixes verified with:
```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```
