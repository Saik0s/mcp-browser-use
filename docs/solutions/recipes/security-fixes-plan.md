# Recipes System Security & Correctness Fixes

**Type:** `fix` | **Priority:** P0 | **Complexity:** Low-Medium
**Created:** 2025-12-17 | **Revised:** 2025-12-18

## Overview

Targeted fixes for critical security vulnerabilities and correctness issues in the browser automation recipes system. This revision prioritizes minimal, focused changes over architectural redesign.

**Estimated Changes:** ~150 lines (down from 1,180 in original plan)

---

## Problem Statement

### Critical Security Issues (P0)
1. **SSRF Protection Bypasses** - IPv6, numeric IPs, empty hostnames, DNS rebinding
2. **Sensitive Headers Saved** - Auth headers stored in YAML files
3. **Domain Allowlist Not Enforced** - Field exists but never checked

### Correctness Issues (P1)
4. **Limited JSONPath** - Custom implementation fails on complex expressions
5. **Naive URL Encoding** - Parameters can break URLs

### Deferred (Not in Scope)
- Pydantic migration (dataclasses work fine)
- verifier.py (add status field instead)
- templating.py (inline in runner.py)
- Phase 3 UX features (auth recovery, staleness detection)

---

## Solution

### Phase 1: SSRF Hardening (~60 lines)

**File:** `src/mcp_server_browser_use/recipes/runner.py`

```python
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

# Blocked hostnames (case-insensitive)
_BLOCKED_HOSTS = frozenset({
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "[::1]", "[::]", "[0:0:0:0:0:0:0:0]", "[0:0:0:0:0:0:0:1]"
})

def _normalize_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse IP from various formats (decimal, octal, hex, bracketed IPv6)."""
    clean = host.strip("[]")

    # Handle decimal notation: 2130706433 -> 127.0.0.1
    if clean.isdigit():
        try:
            return ipaddress.IPv4Address(int(clean))
        except ValueError:
            pass

    # Handle standard notation
    try:
        return ipaddress.ip_address(clean)
    except ValueError:
        return None

def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is private, loopback, link-local, or reserved."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )

async def validate_url_safe(url: str) -> None:
    """
    Validate URL is safe from SSRF attacks.

    Raises ValueError if URL is unsafe.
    """
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Scheme '{parsed.scheme}' not allowed")

    # Reject URLs with credentials (user:pass@host bypass)
    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must have a hostname")

    # Strip IPv6 zone ID (%eth0)
    if "%" in hostname:
        hostname = hostname.split("%")[0]

    # Check blocked hostnames
    if hostname.lower() in _BLOCKED_HOSTS:
        raise ValueError(f"Hostname '{hostname}' is blocked")

    # Check if it's an IP address
    ip = _normalize_ip(hostname)
    if ip is not None:
        if _is_ip_blocked(ip):
            raise ValueError(f"IP '{ip}' is blocked (private/reserved)")
        return  # Valid public IP

    # DNS resolution - run in thread to avoid blocking event loop
    try:
        loop = asyncio.get_event_loop()
        addr_info = await loop.run_in_executor(
            None, socket.getaddrinfo, hostname, None
        )
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname '{hostname}': {e}")

    # Check ALL resolved IPs (DNS rebinding protection)
    for family, type_, proto, canonname, sockaddr in addr_info:
        resolved_ip = ipaddress.ip_address(sockaddr[0])
        if _is_ip_blocked(resolved_ip):
            raise ValueError(
                f"Hostname '{hostname}' resolves to blocked IP '{resolved_ip}'"
            )
```

**Integration points:**
- Call `validate_url_safe()` in `RecipeRunner.run()` before execution
- Call during recipe analysis before saving

**Acceptance Criteria:**
- [ ] Blocks IPv6 private ranges (::1, fc00::/7, fe80::/10)
- [ ] Blocks numeric IPs (decimal: 2130706433, octal: 0177.0.0.1)
- [ ] Blocks IPv6 zone IDs (fe80::1%eth0)
- [ ] Blocks URLs with credentials (user:pass@host)
- [ ] Resolves DNS and checks ALL A/AAAA records
- [ ] Uses async DNS resolution (no event loop blocking)
- [ ] Validates at both learning and execution time

---

### Phase 2: Header Redaction (~15 lines)

**File:** `src/mcp_server_browser_use/recipes/models.py`

```python
# Add to module level
SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "x-api-key", "x-auth-token",
    "x-csrf-token", "x-session-id", "bearer", "api-key"
})

def strip_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove sensitive headers before saving recipe."""
    return {
        k: v for k, v in headers.items()
        if k.lower() not in SENSITIVE_HEADERS
    }
```

**Integration points:**
- Call in `RecipeStore.save()` before writing YAML
- Call in `RecipeAnalyzer` before creating recipe spec

**Acceptance Criteria:**
- [ ] Sensitive headers never saved to YAML
- [ ] No `***REDACTED***` strings appear anywhere
- [ ] Header list is configurable (module constant)

---

### Phase 3: Domain Allowlist Enforcement (~20 lines)

**File:** `src/mcp_server_browser_use/recipes/runner.py`

```python
from urllib.parse import urlparse

def validate_domain_allowed(url: str, allowed_domains: list[str]) -> None:
    """
    Validate URL domain is in allowlist.

    Empty allowlist means all domains allowed (for backwards compatibility).
    """
    if not allowed_domains:
        return  # No restrictions

    hostname = urlparse(url).hostname
    if not hostname:
        raise ValueError("URL must have a hostname")

    hostname_lower = hostname.lower()
    for allowed in allowed_domains:
        allowed_lower = allowed.lower()
        # Exact match or subdomain match
        if hostname_lower == allowed_lower or hostname_lower.endswith(f".{allowed_lower}"):
            return

    raise ValueError(
        f"Domain '{hostname}' not in allowlist: {allowed_domains}"
    )
```

**Integration points:**
- Call in `RecipeRunner.run()` after SSRF check
- `allowed_domains` already exists in `RecipeRequest` model

**Acceptance Criteria:**
- [ ] Enforces domain allowlist if non-empty
- [ ] Supports subdomain matching (api.example.com matches example.com)
- [ ] Empty list allows all domains (backwards compatible)

---

### Phase 4: JMESPath Migration (~10 lines)

**Dependency:** `uv add jmespath`

**File:** `src/mcp_server_browser_use/recipes/runner.py`

```python
import jmespath

def extract_data(data: Any, expression: str | None) -> Any:
    """Extract data using JMESPath expression."""
    if not expression:
        return data

    try:
        return jmespath.search(expression, data)
    except jmespath.exceptions.JMESPathError as e:
        raise ValueError(f"JMESPath extraction failed: {e}")
```

**Migration:**
- Replace `_extract_json_path()` with `extract_data()`
- Update analyzer prompt to specify JMESPath syntax

**Acceptance Criteria:**
- [ ] Supports filters: `items[?active==\`true\`].name`
- [ ] Supports functions: `length(items)`, `sort_by(@, &name)`
- [ ] Existing simple paths continue to work

---

### Phase 5: URL Encoding Fix (~15 lines)

**File:** `src/mcp_server_browser_use/recipes/runner.py`

```python
from urllib.parse import urlparse, urlencode, quote, parse_qs, urlunparse

def build_url(template: str, params: dict[str, Any]) -> str:
    """Build URL from template with proper encoding."""
    parsed = urlparse(template)

    # Substitute path parameters with URL encoding
    path = parsed.path
    for key, value in params.items():
        placeholder = f"{{{key}}}"
        if placeholder in path:
            path = path.replace(placeholder, quote(str(value), safe=""))

    # Substitute query parameters
    query_dict = parse_qs(parsed.query, keep_blank_values=True)
    for key, values in query_dict.items():
        query_dict[key] = [
            v.replace(f"{{{pk}}}", str(pv))
            for v in values
            for pk, pv in params.items()
            if f"{{{pk}}}" in v
        ] or values

    new_query = urlencode(
        [(k, v) for k, vals in query_dict.items() for v in vals],
        safe=""
    )

    return urlunparse((
        parsed.scheme, parsed.netloc, path,
        parsed.params, new_query, parsed.fragment
    ))
```

**Acceptance Criteria:**
- [ ] Path params URL-encoded (`/users/{id}` with `id="a b"` → `/users/a%20b`)
- [ ] Query params properly escaped
- [ ] Special chars in values don't break URL structure

---

### Phase 6: Recipe Status Field (~5 lines)

**File:** `src/mcp_server_browser_use/recipes/models.py`

```python
from typing import Literal

@dataclass
class Recipe:
    # ... existing fields ...
    status: Literal["draft", "verified", "failed"] = "draft"
```

**Usage:**
- New recipes created as `"draft"`
- Set to `"verified"` on first successful execution
- Set to `"failed"` after 3 consecutive failures

**Acceptance Criteria:**
- [ ] Status persisted in YAML
- [ ] Can filter recipes by status in `recipe_list` tool

---

## Test Plan

### SSRF Tests (20+ cases)

```python
@pytest.mark.parametrize("url,should_block", [
    # IPv4 private
    ("http://127.0.0.1/", True),
    ("http://192.168.1.1/", True),
    ("http://10.0.0.1/", True),

    # IPv4 numeric formats
    ("http://2130706433/", True),  # decimal for 127.0.0.1
    ("http://0x7f000001/", True),  # hex for 127.0.0.1

    # IPv6
    ("http://[::1]/", True),
    ("http://[fe80::1]/", True),
    ("http://[::ffff:127.0.0.1]/", True),

    # IPv6 zone ID
    ("http://[fe80::1%25eth0]/", True),

    # Credentials bypass
    ("http://user:pass@localhost/", True),
    ("http://evil.com@127.0.0.1/", True),

    # Empty/missing
    ("http:///path", True),
    ("http://", True),

    # Valid public
    ("https://example.com/", False),
    ("https://api.github.com/", False),
])
async def test_ssrf_validation(url: str, should_block: bool):
    if should_block:
        with pytest.raises(ValueError):
            await validate_url_safe(url)
    else:
        await validate_url_safe(url)  # Should not raise
```

### Header Redaction Tests

```python
def test_strip_sensitive_headers():
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret",
        "Cookie": "session=abc",
        "X-Custom": "allowed",
    }
    result = strip_sensitive_headers(headers)
    assert result == {"Content-Type": "application/json", "X-Custom": "allowed"}
```

### Domain Allowlist Tests

```python
@pytest.mark.parametrize("url,allowlist,should_allow", [
    ("https://api.example.com/v1", ["example.com"], True),
    ("https://example.com/", ["example.com"], True),
    ("https://evil.com/", ["example.com"], False),
    ("https://example.com.evil.com/", ["example.com"], False),
    ("https://anything.com/", [], True),  # Empty = allow all
])
def test_domain_allowlist(url: str, allowlist: list[str], should_allow: bool):
    if should_allow:
        validate_domain_allowed(url, allowlist)
    else:
        with pytest.raises(ValueError):
            validate_domain_allowed(url, allowlist)
```

---

## File Changes Summary

| File | Action | Lines |
|------|--------|-------|
| `recipes/runner.py` | Modify | ~100 |
| `recipes/models.py` | Modify | ~20 |
| `tests/test_recipes_security.py` | Create | ~80 |
| `pyproject.toml` | Add jmespath | ~1 |

**Total:** ~200 lines (vs 1,180 original)

---

## Migration Notes

- No breaking changes to MCP tool interface
- No breaking changes to recipe YAML format
- Existing recipes work unchanged (allowlist empty = allow all)
- `jmespath` is superset of current JSONPath subset

---

## Deferred Items (Future Work)

These items from the original plan are deferred until actually needed:

1. **Pydantic Migration** - Dataclasses work fine, migrate only if validation becomes a real problem
2. **verifier.py** - Status field + success/failure tracking is sufficient
3. **templating.py** - URL builder inline in runner.py is adequate
4. **Browser-Managed Headers** - Stripping headers is simpler than runtime fetching
5. **MoneyRequest Migration** - Manual migration if needed, not auto-migration code
6. **HTML Extraction** - Not currently used, remove dead code instead
7. **Auth Recovery** - Complex feature with no clear requirement
8. **Staleness Detection** - Nice-to-have, not blocking any issues

---

## References

- [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [JMESPath Tutorial](https://jmespath.org/tutorial.html)
- [Python ipaddress Module](https://docs.python.org/3/library/ipaddress.html)
- Review feedback: Code Simplicity, Kieran Python, Security Sentinel, Architecture Strategist
- `docs/recipes-design.md`
