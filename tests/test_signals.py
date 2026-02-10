"""Unit tests for recipes.signals."""

from __future__ import annotations

import random
import string
from datetime import datetime
from urllib.parse import urlparse

from mcp_server_browser_use.recipes.models import NetworkRequest, NetworkResponse, SessionRecording
from mcp_server_browser_use.recipes.signals import extract_request_signals, sanitize_url, summarize_response_structure


class TestSanitizeUrl:
    def test_redacts_sensitive_query_keys(self) -> None:
        url = "https://example.com/search?q=hello&token=sekret&access_token=abc#frag"
        out = sanitize_url(url)
        assert out.startswith("https://example.com/search?")
        assert "q=hello" in out
        assert "token=%5BREDACTED%5D" in out or "token=[REDACTED]" in out
        assert "access_token=%5BREDACTED%5D" in out or "access_token=[REDACTED]" in out
        assert "#frag" not in out

    def test_redacts_secret_like_values_even_for_non_sensitive_key(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbb"
        url = f"https://example.com/callback?state={jwt}"
        out = sanitize_url(url)
        assert "state=%5BREDACTED%5D" in out or "state=[REDACTED]" in out

    def test_redacts_state_like_value_even_for_non_sensitive_key(self) -> None:
        opaque = "0123456789abcdef0123456789abcdef"
        url = f"https://example.com/callback?q={opaque}"
        out = sanitize_url(url)
        assert "q=%5BREDACTED%5D" in out or "q=[REDACTED]" in out

    def test_redacts_base64urlish_value_even_for_non_sensitive_key(self) -> None:
        opaque = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
        url = f"https://example.com/callback?q={opaque}"
        out = sanitize_url(url)
        assert "q=%5BREDACTED%5D" in out or "q=[REDACTED]" in out

    def test_redacts_base64ish_value_even_when_shorter_than_80_chars(self) -> None:
        # Regression: base64-ish redaction uses the regex threshold ({60,}), not an additional len>=80 gate.
        opaque = "A" * 60
        url = f"https://example.com/callback?q={opaque}"
        out = sanitize_url(url)
        assert "q=%5BREDACTED%5D" in out or "q=[REDACTED]" in out

    def test_does_not_always_redact_code_or_key_when_value_is_short_alphabetic(self) -> None:
        url = "https://example.com/callback?code=abc&key=blue"
        out = sanitize_url(url)
        assert "code=abc" in out
        assert "key=blue" in out

    def test_redacts_code_or_key_when_value_is_opaque(self) -> None:
        url = "https://example.com/callback?code=abc123&key=sk_live_1234567890abcdef"
        out = sanitize_url(url)
        assert "code=%5BREDACTED%5D" in out or "code=[REDACTED]" in out
        assert "key=%5BREDACTED%5D" in out or "key=[REDACTED]" in out

    def test_truncates_long_urls(self) -> None:
        # Use many small params to force length without triggering secret heuristics.
        qs = "&".join([f"k{i}=v{i}" for i in range(200)])
        url = f"https://example.com/search?{qs}"
        out = sanitize_url(url, max_len=200)
        assert len(out) <= 200
        assert out.endswith("...[TRUNC]")

    def test_strips_userinfo(self) -> None:
        url = "https://user:pass@example.com:8443/path?q=1"
        out = sanitize_url(url)
        parsed = urlparse(out)
        assert parsed.netloc == "example.com:8443"
        assert "user:pass@" not in out

    def test_redacts_token_like_path_segments(self) -> None:
        token = "abcDEF0123456789abcDEF0123456789"
        url = f"https://example.com/reset/{token}/confirm?q=1"
        out = sanitize_url(url)
        assert "/reset/[REDACTED]/confirm" in out
        assert token not in out

    def test_redacts_slack_token_path_segments_even_if_sluggy(self) -> None:
        rng = random.Random(0)
        digits1 = "".join(str(rng.randrange(10)) for _ in range(12))
        digits2 = "".join(str(rng.randrange(10)) for _ in range(12))
        tail = "".join(rng.choice(string.ascii_lowercase) for _ in range(32))
        prefix = bytes((120, 111, 120, 98, 45)).decode("ascii")
        token = f"{prefix}{digits1}-{digits2}-{tail}"
        url = f"https://example.com/reset/{token}/confirm?q=1"
        out = sanitize_url(url)
        assert "/reset/[REDACTED]/confirm" in out
        assert token not in out

    def test_redacts_slug_like_path_segments_when_tokenish(self) -> None:
        # Slug exemption must not bypass generic token heuristics.
        seg = "release-20240115-production"
        url = f"https://example.com/build/{seg}/details?q=1"
        out = sanitize_url(url)
        assert "/build/[REDACTED]/details" in out
        assert seg not in out

    def test_redacts_percent_encoded_path_segments_after_unquote(self) -> None:
        # Regression: secrets can be percent-encoded to bypass redaction (e.g. "%2F" for "/").
        decoded = ("A" * 59) + "/"
        encoded = ("A" * 59) + "%2F"
        url = f"https://example.com/reset/{encoded}/confirm?q=1"
        out = sanitize_url(url)
        assert "/reset/[REDACTED]/confirm" in out
        assert decoded not in out
        assert encoded not in out

    def test_redacts_uuid_path_segments(self) -> None:
        seg = "123e4567-e89b-12d3-a456-426614174000"
        url = f"https://example.com/items/{seg}?q=1"
        out = sanitize_url(url)
        assert "/items/[REDACTED]" in out
        assert seg not in out

    def test_does_not_redact_long_letter_path_segments(self) -> None:
        seg = "thisisaveryverylongsegmentwithonlyletters"
        url = f"https://example.com/docs/{seg}/index.html"
        out = sanitize_url(url)
        assert f"/docs/{seg}/index.html" in out
        assert "[REDACTED]" not in out

    def test_truncation_never_exceeds_max_len_when_tiny(self) -> None:
        qs = "&".join([f"k{i}=v{i}" for i in range(50)])
        url = f"https://example.com/search?{qs}"
        out = sanitize_url(url, max_len=5)
        assert len(out) <= 5

    def test_max_len_zero_returns_empty_string(self) -> None:
        url = "https://example.com/search?q=hello"
        out = sanitize_url(url, max_len=0)
        assert out == ""


class TestSummaries:
    def test_json_summary_has_no_raw_values_and_redacts_sensitive_keys(self) -> None:
        body = '{"token":"supersecret","items":[{"id":1,"name":"x"}]}'
        summary = summarize_response_structure(content_type="application/json", body=body, max_len=500)
        assert "supersecret" not in summary
        assert 'name":"x' not in summary
        assert "[REDACTED_KEY]" in summary
        assert "array(" in summary or "object(" in summary

    def test_summary_truncation_never_exceeds_max_len_when_tiny(self) -> None:
        body = '{"items":[{"id":1,"name":"x"}]}'
        summary = summarize_response_structure(content_type="application/json", body=body, max_len=5)
        assert len(summary) <= 5

    def test_no_body_summary_truncation_never_exceeds_max_len_when_tiny(self) -> None:
        summary = summarize_response_structure(content_type="application/json", body=None, max_len=3)
        assert len(summary) <= 3
        summary2 = summarize_response_structure(content_type="text/plain", body="", max_len=1)
        assert len(summary2) <= 1


class TestExtractRequestSignals:
    def test_extracts_initiator_duration_and_size(self) -> None:
        # Document navigation (initiator)
        doc_req = NetworkRequest(
            url="https://example.com/page",
            method="GET",
            resource_type="document",
            timestamp=10.0,
            request_id="doc-1",
        )
        api_req = NetworkRequest(
            url="https://api.example.com/items?token=sekret",
            method="GET",
            resource_type="xhr",
            timestamp=12.0,
            request_id="api-1",
        )
        api_resp = NetworkResponse(
            url="https://api.example.com/items?token=sekret",
            status=200,
            headers={"Content-Length": "123"},
            body=None,
            mime_type="application/json",
            timestamp=12.25,
            request_id="api-1",
        )

        recording = SessionRecording(
            task="t",
            result="r",
            requests=[api_req, doc_req],
            responses=[api_resp],
            navigation_urls=["https://example.com/page"],
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        signals = extract_request_signals(recording)
        assert len(signals) == 1
        sig = signals[0]

        assert sig.method == "GET"
        assert sig.status == 200
        assert sig.content_type == "application/json"
        assert sig.response_size_bytes == 123
        assert sig.initiator_page_url == "https://example.com/page"
        assert sig.duration_ms is not None
        assert 200.0 <= sig.duration_ms <= 300.0
        assert sig.url.startswith("https://api.example.com/items?")
        assert "token=%5BREDACTED%5D" in sig.url or "token=[REDACTED]" in sig.url

    def test_initiator_fallback_does_not_guess_from_navigation_urls(self) -> None:
        api_req = NetworkRequest(
            url="https://api.example.com/items",
            method="GET",
            resource_type="xhr",
            timestamp=12.0,
            request_id="api-1",
        )
        api_resp = NetworkResponse(
            url="https://api.example.com/items",
            status=200,
            headers={"Content-Length": "2"},
            body="{}",
            mime_type="application/json",
            timestamp=12.25,
            request_id="api-1",
        )

        recording = SessionRecording(
            task="t",
            result="r",
            requests=[api_req],
            responses=[api_resp],
            navigation_urls=["https://example.com/page"],
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        signals = extract_request_signals(recording)
        assert len(signals) == 1
        assert signals[0].initiator_page_url == ""
