"""Security tests for the recipes system.

Tests SSRF protection, header stripping, domain allowlisting, and URL encoding.
"""

import pytest

from mcp_server_browser_use.recipes.models import (
    PUBLIC_HEADER_ALLOWLIST,
    SENSITIVE_HEADER_SUBSTRINGS,
    Recipe,
    RecipeRequest,
    is_sensitive_header_name,
    strip_sensitive_headers,
)
from mcp_server_browser_use.recipes.recorder import RecipeRecorder
from mcp_server_browser_use.recipes.runner import (
    _is_ip_blocked,
    _normalize_ip,
    build_url,
    extract_data,
    validate_domain_allowed,
    validate_url_safe,
)

# --- SSRF Protection Tests ---


@pytest.mark.parametrize(
    "url,should_block",
    [
        # IPv4 private ranges
        ("http://127.0.0.1/", True),
        ("http://127.0.0.1:8080/api", True),
        ("http://192.168.1.1/", True),
        ("http://192.168.0.1/", True),
        ("http://10.0.0.1/", True),
        ("http://10.255.255.255/", True),
        ("http://172.16.0.1/", True),
        ("http://172.31.255.255/", True),
        # IPv4 numeric formats (decimal)
        ("http://2130706433/", True),  # decimal for 127.0.0.1
        ("http://3232235521/", True),  # decimal for 192.168.0.1
        # IPv6 loopback
        ("http://[::1]/", True),
        ("http://[::1]:8080/", True),
        # IPv6 link-local
        ("http://[fe80::1]/", True),
        ("http://[fe80::1%25eth0]/", True),  # with zone ID
        # IPv6 mapped IPv4
        ("http://[::ffff:127.0.0.1]/", True),
        ("http://[::ffff:192.168.1.1]/", True),
        # Credentials bypass attempts
        ("http://user:pass@localhost/", True),
        ("http://admin:secret@127.0.0.1/", True),
        # Empty/missing hostname
        ("http:///path", True),
        ("http://", True),
        # Invalid schemes
        ("ftp://example.com/", True),
        ("file:///etc/passwd", True),
        ("javascript:alert(1)", True),
        # Valid public URLs (should NOT block)
        ("https://example.com/", False),
        ("https://api.github.com/", False),
        ("http://google.com/", False),
        ("https://1.1.1.1/", False),  # Cloudflare DNS
        ("https://8.8.8.8/", False),  # Google DNS
    ],
)
async def test_ssrf_validation(url: str, should_block: bool) -> None:
    """Test SSRF protection blocks private IPs and allows public ones."""
    if should_block:
        with pytest.raises(ValueError):
            await validate_url_safe(url)
    else:
        await validate_url_safe(url)  # Should not raise


def test_normalize_ip_decimal() -> None:
    """Test decimal IP format is normalized correctly."""
    # 2130706433 = 127.0.0.1
    ip = _normalize_ip("2130706433")
    assert ip is not None
    assert str(ip) == "127.0.0.1"


def test_normalize_ip_ipv6_brackets() -> None:
    """Test bracketed IPv6 is normalized correctly."""
    ip = _normalize_ip("[::1]")
    assert ip is not None
    assert str(ip) == "::1"


def test_normalize_ip_invalid() -> None:
    """Test invalid IP returns None."""
    assert _normalize_ip("not-an-ip") is None
    assert _normalize_ip("example.com") is None


def test_is_ip_blocked_private() -> None:
    """Test private IPs are blocked."""
    import ipaddress

    assert _is_ip_blocked(ipaddress.ip_address("127.0.0.1")) is True
    assert _is_ip_blocked(ipaddress.ip_address("192.168.1.1")) is True
    assert _is_ip_blocked(ipaddress.ip_address("10.0.0.1")) is True
    assert _is_ip_blocked(ipaddress.ip_address("::1")) is True


def test_is_ip_blocked_public() -> None:
    """Test public IPs are not blocked."""
    import ipaddress

    assert _is_ip_blocked(ipaddress.ip_address("1.1.1.1")) is False
    assert _is_ip_blocked(ipaddress.ip_address("8.8.8.8")) is False
    assert _is_ip_blocked(ipaddress.ip_address("93.184.216.34")) is False  # example.com


# --- Header Stripping Tests ---


def test_strip_sensitive_headers() -> None:
    """Test sensitive headers are stripped, not redacted."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret-token",
        "Cookie": "session=abc123",
        "X-Session-Id": "session-id",
        "X-Custom": "allowed-value",
        "X-API-Key": "secret-api-key",
    }
    result = strip_sensitive_headers(headers)

    # Only non-sensitive headers remain
    assert result == {"Content-Type": "application/json", "X-Custom": "allowed-value"}

    # No redacted values
    assert "***REDACTED***" not in str(result)


def test_strip_sensitive_headers_case_insensitive() -> None:
    """Test header stripping is case-insensitive."""
    headers = {
        "AUTHORIZATION": "Bearer token",
        "Cookie": "session=xyz",
        "x-api-key": "key",
        "Content-Type": "text/plain",
    }
    result = strip_sensitive_headers(headers)
    assert result == {"Content-Type": "text/plain"}


def test_recipe_request_get_safe_headers() -> None:
    """Test RecipeRequest.get_safe_headers() strips sensitive headers."""
    request = RecipeRequest(
        url="https://api.example.com/data",
        headers={
            "Authorization": "Bearer token",
            "Content-Type": "application/json",
            "X-Request-ID": "12345",
        },
    )
    safe = request.get_safe_headers()

    assert "Authorization" not in safe
    assert safe == {"Content-Type": "application/json", "X-Request-ID": "12345"}


def test_recipe_to_dict_strips_headers() -> None:
    """Test Recipe.to_dict() uses stripped headers, not redacted."""
    recipe = Recipe(
        name="test-recipe",
        description="A test recipe",
        original_task="Test task",
        request=RecipeRequest(
            url="https://api.example.com/data",
            headers={
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
        ),
    )
    data = recipe.to_dict()

    # Headers should be stripped, not redacted
    assert "Authorization" not in data["request"]["headers"]
    assert "***REDACTED***" not in str(data)
    assert data["request"]["headers"] == {"Content-Type": "application/json"}


def test_strip_sensitive_headers_substring_matching() -> None:
    """Test stripping uses token/segment matching, not exact names only."""
    headers = {
        "X-Auth-Request-Access-Token": "secret",
        "X-CSRFToken": "secret",
        "X_API_KEY": "secret",
        "X-Custom": "ok",
    }
    result = strip_sensitive_headers(headers)
    assert result == {"X-Custom": "ok"}


def test_strip_sensitive_headers_session_and_xsrf_variants() -> None:
    """Regression: session identifiers and XSRF variants must be treated as sensitive."""
    headers = {
        ":authority": "example.com",
        "Author": "not-a-secret",
        "X-Session-Id": "sess_123",
        "X-XSRF": "xsrf_1",
        "X-XSRF-TOKEN": "xsrf_2",
        "XSRF-TOKEN": "xsrf_3",
        "X-CSRFToken": "csrf_1",
        "X-Custom": "ok",
    }
    result = strip_sensitive_headers(headers)
    assert result == {":authority": "example.com", "Author": "not-a-secret", "X-Custom": "ok"}


def test_strip_sensitive_headers_allowlist_override() -> None:
    """Test allowlisted headers are kept even if they match sensitive substrings."""
    headers = {
        "X-CSRF-Protection": "1",
        "X-CSRF-Token": "secret",
        "Content-Type": "application/json",
    }
    result = strip_sensitive_headers(headers)
    assert result == {"X-CSRF-Protection": "1", "Content-Type": "application/json"}


def test_is_sensitive_header_name_respects_allowlist() -> None:
    """Sanity check the predicate and allowlist are aligned."""
    assert "x-csrf-protection" in PUBLIC_HEADER_ALLOWLIST
    assert is_sensitive_header_name("X-CSRF-Protection") is False
    assert is_sensitive_header_name("X-CSRF-Token") is True


def test_is_sensitive_header_name_avoids_false_positives() -> None:
    """Regression: avoid naive substring matches like 'auth' in ':authority' or 'author'."""
    assert is_sensitive_header_name(":authority") is False
    assert is_sensitive_header_name("Author") is False
    assert is_sensitive_header_name("X-Author") is False
    assert is_sensitive_header_name("Authorization") is True
    assert is_sensitive_header_name("X-Auth-Token") is True


def test_recorder_redacts_sensitive_headers_by_pattern() -> None:
    """Recorder should redact (not strip) values based on token/segment matching."""
    recorder = RecipeRecorder(task="test")
    headers = {
        ":authority": "example.com",
        "Author": "not-a-secret",
        "Authorization": "Bearer secret",
        "X-Auth-Token": "secret",
        "X-CSRFToken": "secret",
        "X_API_KEY": "secret",
        "X-Session-Id": "session-id",
        "X-XSRF": "xsrf_1",
        "X-Custom": "ok",
        "X-CSRF-Protection": "1",  # allowlisted
    }
    redacted = recorder._redact_headers(headers)

    assert redacted[":authority"] == "example.com"
    assert redacted["Author"] == "not-a-secret"
    assert redacted["X-Custom"] == "ok"
    assert redacted["X-CSRF-Protection"] == "1"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["X-Auth-Token"] == "[REDACTED]"
    assert redacted["X-CSRFToken"] == "[REDACTED]"
    assert redacted["X_API_KEY"] == "[REDACTED]"
    assert redacted["X-Session-Id"] == "[REDACTED]"
    assert redacted["X-XSRF"] == "[REDACTED]"


# --- Domain Allowlist Tests ---


@pytest.mark.parametrize(
    "url,allowlist,should_allow",
    [
        # Exact match
        ("https://example.com/", ["example.com"], True),
        ("https://example.com/api/v1", ["example.com"], True),
        # Subdomain match
        ("https://api.example.com/v1", ["example.com"], True),
        ("https://www.example.com/", ["example.com"], True),
        ("https://deep.sub.example.com/", ["example.com"], True),
        # Not in allowlist
        ("https://evil.com/", ["example.com"], False),
        ("https://notexample.com/", ["example.com"], False),
        # Suffix attack (should NOT match)
        ("https://example.com.evil.com/", ["example.com"], False),
        ("https://fakeexample.com/", ["example.com"], False),
        # Empty allowlist = allow all
        ("https://anything.com/", [], True),
        ("https://evil.com/malware", [], True),
        # Multiple allowed domains
        ("https://api.github.com/", ["github.com", "gitlab.com"], True),
        ("https://gitlab.com/", ["github.com", "gitlab.com"], True),
        ("https://bitbucket.com/", ["github.com", "gitlab.com"], False),
    ],
)
def test_domain_allowlist(url: str, allowlist: list[str], should_allow: bool) -> None:
    """Test domain allowlist enforcement."""
    if should_allow:
        validate_domain_allowed(url, allowlist)  # Should not raise
    else:
        with pytest.raises(ValueError, match="not in allowlist"):
            validate_domain_allowed(url, allowlist)


# --- URL Encoding Tests ---


def test_build_url_path_encoding() -> None:
    """Test path parameters are URL-encoded."""
    url = build_url("https://api.example.com/users/{user_id}/posts", {"user_id": "a b"})
    assert url == "https://api.example.com/users/a%20b/posts"


def test_build_url_special_chars() -> None:
    """Test special characters are properly encoded."""
    url = build_url("https://api.example.com/search/{query}", {"query": "foo&bar=baz"})
    assert url == "https://api.example.com/search/foo%26bar%3Dbaz"


def test_build_url_query_params() -> None:
    """Test query parameters are substituted."""
    url = build_url("https://api.example.com/search?q={term}&page={page}", {"term": "hello", "page": "1"})
    assert "q=hello" in url
    assert "page=1" in url


def test_build_url_unicode() -> None:
    """Test unicode characters are encoded."""
    url = build_url("https://api.example.com/search/{query}", {"query": "日本語"})
    assert "%E6%97%A5%E6%9C%AC%E8%AA%9E" in url


# --- JMESPath Extraction Tests ---


def test_extract_data_simple_path() -> None:
    """Test simple path extraction."""
    data = {"user": {"name": "Alice", "age": 30}}
    assert extract_data(data, "user.name") == "Alice"


def test_extract_data_array() -> None:
    """Test array extraction."""
    data = {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    assert extract_data(data, "items[*].name") == ["a", "b", "c"]


def test_extract_data_filter() -> None:
    """Test JMESPath filter expressions."""
    data = {
        "items": [
            {"name": "active", "enabled": True},
            {"name": "inactive", "enabled": False},
            {"name": "also-active", "enabled": True},
        ]
    }
    result = extract_data(data, "items[?enabled==`true`].name")
    assert result == ["active", "also-active"]


def test_extract_data_function() -> None:
    """Test JMESPath functions."""
    data = {"items": [1, 2, 3, 4, 5]}
    assert extract_data(data, "length(items)") == 5


def test_extract_data_none_expression() -> None:
    """Test None expression returns original data."""
    data = {"foo": "bar"}
    assert extract_data(data, None) == data


def test_extract_data_invalid_expression() -> None:
    """Test invalid JMESPath expression raises ValueError."""
    with pytest.raises(ValueError, match="JMESPath extraction failed"):
        extract_data({}, "invalid[[[")


# --- Recipe Status Field Tests ---


def test_recipe_default_status() -> None:
    """Test new recipes have 'draft' status by default."""
    recipe = Recipe(name="test", description="test", original_task="test")
    assert recipe.status == "draft"


def test_recipe_status_serialization() -> None:
    """Test status is serialized and deserialized correctly."""
    recipe = Recipe(name="test", description="test", original_task="test", status="verified")
    data = recipe.to_dict()
    assert data["status"] == "verified"

    restored = Recipe.from_dict(data)
    assert restored.status == "verified"


def test_recipe_status_from_dict_default() -> None:
    """Test from_dict defaults to 'draft' if status missing."""
    data = {"name": "test", "description": "test", "original_task": "test"}
    recipe = Recipe.from_dict(data)
    assert recipe.status == "draft"


# --- Integration Tests ---


def test_recipe_allowed_domains_serialization() -> None:
    """Test allowed_domains is serialized and deserialized correctly."""
    recipe = Recipe(
        name="test",
        description="test",
        original_task="test",
        request=RecipeRequest(
            url="https://api.example.com/data",
            allowed_domains=["example.com", "api.example.com"],
        ),
    )

    data = recipe.to_dict()
    assert data["request"]["allowed_domains"] == ["example.com", "api.example.com"]

    restored = Recipe.from_dict(data)
    assert restored.request is not None
    assert restored.request.allowed_domains == ["example.com", "api.example.com"]


def test_sensitive_headers_constant() -> None:
    """Test sensitive header substrings contain expected patterns."""
    assert "auth" in SENSITIVE_HEADER_SUBSTRINGS
    assert "cookie" in SENSITIVE_HEADER_SUBSTRINGS
    assert "csrf" in SENSITIVE_HEADER_SUBSTRINGS
    assert "token" in SENSITIVE_HEADER_SUBSTRINGS
