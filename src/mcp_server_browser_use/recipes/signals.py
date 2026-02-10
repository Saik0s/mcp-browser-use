"""Signals for turning raw session recordings into safe, bounded request features.

This module is intentionally "pure":
- No I/O, no logging, no global state.
- Inputs are recipe recording models.
- Outputs are safe summaries suitable for candidate ranking + LLM analysis prompts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from .models import NetworkRequest, NetworkResponse, SessionRecording

_TRUNC_MARKER = "...[TRUNC]"

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "apikey",
        "api_key",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "csrf",
        "id_token",
        "password",
        "refresh_token",
        "secret",
        "session",
        "signature",
        "sig",
        "token",
        "xsrf",
    }
)

_CONDITIONAL_SENSITIVE_QUERY_KEYS = frozenset({"code", "key"})

_SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "session",
    "csrf",
    "xsrf",
    "api_key",
    "apikey",
)

_JWT_PREFIX_RE = re.compile(r"^eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}$")
_LONG_BASE64ISH_RE = re.compile(r"^[a-zA-Z0-9+/=_-]{60,}$")
_LONG_BASE64URLISH_RE = re.compile(r"^[a-zA-Z0-9_-]{32,}={0,2}$")
_LONG_HEX_RE = re.compile(r"^[a-fA-F0-9]{32,}$")
_PATH_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_-]{24,}$")
_SLACK_TOKEN_RE = re.compile(r"^xox[a-z]-[0-9a-zA-Z-]{10,}$", flags=re.IGNORECASE)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", flags=re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RequestSignals:
    """Per-request features derived from a recording, sanitized for downstream use."""

    url: str
    method: str
    status: int
    content_type: str
    response_size_bytes: int
    structural_summary: str
    duration_ms: float | None
    request_timestamp: float
    response_timestamp: float
    initiator_page_url: str
    resource_type: str


ContentKind = Literal["json", "html", "text", "unknown", "no_body"]


def extract_request_signals(
    recording: SessionRecording,
    *,
    max_calls: int = 200,
    max_url_len: int = 2048,
    max_structural_summary_len: int = 500,
) -> list[RequestSignals]:
    """Extract sanitized per-request features for API calls in a SessionRecording."""
    initiator_by_request_id = _build_initiator_url_map(recording)

    pairs = recording.get_api_calls()
    pairs = sorted(pairs, key=lambda p: p[0].timestamp)
    if max_calls > 0:
        pairs = pairs[:max_calls]

    out: list[RequestSignals] = []
    for req, resp in pairs:
        url_s = sanitize_url(req.url, max_len=max_url_len)
        initiator = initiator_by_request_id.get(req.request_id, "")
        initiator_s = sanitize_url(initiator, max_len=max_url_len) if initiator else ""

        content_type = _extract_content_type(resp)
        size = _extract_response_size_bytes(resp)
        duration_ms = _compute_duration_ms(req, resp)

        structural_summary = summarize_response_structure(
            content_type=content_type,
            body=resp.body,
            max_len=max_structural_summary_len,
        )

        out.append(
            RequestSignals(
                url=url_s,
                method=req.method.upper() if req.method else "GET",
                status=int(resp.status),
                content_type=content_type,
                response_size_bytes=size,
                structural_summary=structural_summary,
                duration_ms=duration_ms,
                request_timestamp=float(req.timestamp),
                response_timestamp=float(resp.timestamp),
                initiator_page_url=initiator_s,
                resource_type=(req.resource_type or "").lower(),
            )
        )

    return out


def sanitize_url(url: str, *, max_len: int = 2048) -> str:
    """Sanitize URL by removing fragments and redacting obvious secrets.

    - Drops fragment (`#...`).
    - Redacts userinfo (`user:pass@`) from netloc.
    - Redacts sensitive query values and obvious secret-like query values.
    - Redacts obviously token-like path segments.
    - Bounds output length via `_truncate()`.
    """
    if not url:
        return ""

    parsed = urlparse(url)
    safe_netloc = _sanitize_netloc(parsed.netloc, hostname=parsed.hostname, port=parsed.port)
    safe_path = _redact_path_secrets(parsed.path)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    safe_items: list[tuple[str, str]] = []
    for key, value in query_items:
        key_l = key.lower()
        if key_l in _SENSITIVE_QUERY_KEYS:
            safe_items.append((key, "[REDACTED]"))
            continue
        if key_l in _CONDITIONAL_SENSITIVE_QUERY_KEYS and _looks_like_code_or_key_secret(value):
            safe_items.append((key, "[REDACTED]"))
            continue
        if _looks_like_secret_query_value(value):
            safe_items.append((key, "[REDACTED]"))
            continue
        safe_items.append((key, _truncate(value, 128)))

    safe_query = urlencode(safe_items, doseq=True, safe=":/@")
    safe_url = urlunparse((parsed.scheme, safe_netloc, safe_path, parsed.params, safe_query, ""))  # drop fragment

    return _truncate(safe_url, max_len)


def summarize_response_structure(*, content_type: str, body: str | None, max_len: int = 500) -> str:
    """Return a bounded, secret-safe structural summary of the response body.

    Important: never returns raw body content.
    """
    if body is None or body == "":
        return _truncate("no_body", max_len)

    kind = _classify_content_kind(content_type=content_type, body=body)
    if kind == "json":
        summary = _summarize_json_body(body)
        return _truncate(summary, max_len)

    if kind == "html":
        summary = _summarize_html_body(body)
        return _truncate(summary, max_len)

    if kind == "text":
        summary = _summarize_text_body(body)
        return _truncate(summary, max_len)

    return _truncate(f"unknown chars={len(body)}", max_len)


def to_safe_summary_dict(sig: RequestSignals) -> dict[str, str | int | float | None]:
    """Convert RequestSignals to a dict suitable for JSON serialization or prompts."""
    return {
        "url": sig.url,
        "method": sig.method,
        "status": sig.status,
        "content_type": sig.content_type,
        "response_size_bytes": sig.response_size_bytes,
        "duration_ms": sig.duration_ms,
        "initiator_page_url": sig.initiator_page_url,
        "resource_type": sig.resource_type,
        "structural_summary": sig.structural_summary,
    }


def _extract_content_type(resp: NetworkResponse) -> str:
    if resp.mime_type:
        return _truncate(resp.mime_type.lower(), 200)
    for k, v in resp.headers.items():
        if k.lower() == "content-type":
            return _truncate(v.lower(), 200)
    return ""


def _extract_response_size_bytes(resp: NetworkResponse) -> int:
    # Prefer Content-Length if present, fall back to captured body length.
    for k, v in resp.headers.items():
        if k.lower() == "content-length":
            try:
                n = int(v.strip())
                if n >= 0:
                    return n
            except ValueError:
                pass
    if resp.body is None:
        return 0
    return len(resp.body.encode("utf-8", errors="replace"))


def _compute_duration_ms(req: NetworkRequest, resp: NetworkResponse) -> float | None:
    if req.timestamp <= 0.0 or resp.timestamp <= 0.0:
        return None
    if resp.timestamp < req.timestamp:
        return None
    return (resp.timestamp - req.timestamp) * 1000.0


def _build_initiator_url_map(recording: SessionRecording) -> dict[str, str]:
    # Best-effort initiator: last seen Document URL before request timestamp.
    # CDP has "initiator" fields, but we do not capture them yet.
    reqs = sorted(recording.requests, key=lambda r: r.timestamp)
    current_doc = ""
    initiator_by_id: dict[str, str] = {}
    for req in reqs:
        if (req.resource_type or "").lower() == "document" and req.url:
            current_doc = req.url
        if req.request_id:
            initiator_by_id[req.request_id] = current_doc
    return initiator_by_id


def _fallback_initiator(recording: SessionRecording) -> str:
    # We intentionally do not guess the initiator URL, since it is easy to be wrong.
    # Prefer empty over misleading (e.g., using "last navigation" for an older request).
    return ""


def _classify_content_kind(*, content_type: str, body: str) -> ContentKind:
    ct = (content_type or "").lower()
    body_l = body.lstrip()[:200].lower()

    if "json" in ct or body_l.startswith("{") or body_l.startswith("["):
        return "json"
    if "html" in ct or "<html" in body_l or "<!doctype html" in body_l:
        return "html"
    if ct.startswith("text/") or "\n" in body[:4000]:
        return "text"
    return "unknown"


def _summarize_json_body(body: str) -> str:
    # Avoid parsing huge bodies, and avoid accidentally summarizing appended truncation markers.
    if len(body) > 50_000:
        return f"json chars={len(body)} (not_parsed)"

    try:
        value: object = json.loads(body)
    except json.JSONDecodeError:
        return f"json chars={len(body)} (parse_error)"

    return _summarize_json_value(value=value, depth=0, max_depth=3, max_keys=25, max_items=25)


def _summarize_json_value(*, value: object, depth: int, max_depth: int, max_keys: int, max_items: int) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return f"string(len={len(value)})"

    if isinstance(value, list):
        if depth >= max_depth:
            return f"array(len={len(value)})"
        elem_kinds: list[str] = []
        for item in value[:max_items]:
            elem_kinds.append(_summarize_json_value(value=item, depth=depth + 1, max_depth=max_depth, max_keys=max_keys, max_items=max_items))
        uniq = _unique_preserve_order(elem_kinds)[:5]
        return f"array(len={len(value)}) elems={uniq}"

    if isinstance(value, dict):
        if depth >= max_depth:
            return f"object(keys={min(len(value), max_keys)})"

        keys = sorted(str(k) for k in value)
        safe_keys = [_sanitize_key_name(k) for k in keys[:max_keys]]
        # Summarize nested shapes for a few keys only, without values.
        nested_parts: list[str] = []
        for k in keys[: min(len(keys), 8)]:
            v = value.get(k)
            nested_parts.append(
                f"{_sanitize_key_name(k)}:{_summarize_json_value(value=v, depth=depth + 1, max_depth=max_depth, max_keys=max_keys, max_items=max_items)}"
            )
        nested = ", ".join(nested_parts)
        return f"object(keys={safe_keys}) sample={{ {nested} }}"

    return "unknown"


def _summarize_html_body(body: str) -> str:
    # Summarize by tag frequency on a bounded prefix.
    prefix = body[:20_000]
    tags = re.findall(r"<\s*([a-zA-Z0-9]+)(?:\\s|>)", prefix)
    counts: dict[str, int] = {}
    for t in tags:
        tl = t.lower()
        counts[tl] = counts.get(tl, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    top_str = ",".join(f"{k}:{v}" for k, v in top)
    return f"html chars={len(body)} tags={len(counts)} top=[{top_str}]"


def _summarize_text_body(body: str) -> str:
    # Do not echo content. Only count.
    prefix = body[:20_000]
    lines = prefix.splitlines()
    return f"text chars={len(body)} lines~{len(lines)}"


def _sanitize_key_name(key: str) -> str:
    kl = key.lower()
    for sub in _SENSITIVE_KEY_SUBSTRINGS:
        if sub in kl:
            return "[REDACTED_KEY]"
    return _truncate(key, 64)


def _looks_like_secret(value: str) -> bool:
    # Back-compat alias, prefer _looks_like_secret_query_value / _looks_like_path_secret_segment.
    return _looks_like_secret_query_value(value)


def _looks_like_secret_query_value(value: str) -> bool:
    """Heuristic for query param values.

    Query strings often contain OAuth state/nonce, API keys, and other opaque tokens even when the key name
    is non-sensitive ("q", "state", "nonce", etc). Prefer false positives over leaks.
    """
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    if _SLACK_TOKEN_RE.match(v):
        return True
    if _JWT_PREFIX_RE.match(v):
        return True
    if _LONG_HEX_RE.match(v):
        return True
    if _LONG_BASE64URLISH_RE.match(v):
        return True
    if _LONG_BASE64ISH_RE.match(v):
        return True
    return False


def _looks_like_code_or_key_secret(value: str) -> bool:
    """Heuristic for query params that are sometimes non-secret (e.g. code, key).

    Goal: avoid redacting obvious non-secrets like "code=foo", while still redacting
    OAuth codes / API keys that tend to be opaque, mixed, or long.
    """
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    if v.isalpha() and len(v) <= 12:
        return False
    if _looks_like_secret_query_value(v):
        return True
    if _LONG_HEX_RE.match(v):
        return True
    # Anything non-alpha is treated as likely opaque (digits, punctuation, etc).
    return True


def _sanitize_netloc(netloc: str, *, hostname: str | None, port: int | None) -> str:
    # Strip userinfo deterministically. Prefer parsed hostname/port when available.
    if not netloc:
        return ""
    if "@" not in netloc:
        return netloc
    if not hostname:
        # If parsing failed, fall back to dropping everything up to the last '@'.
        return netloc.rsplit("@", 1)[-1]

    host = hostname
    if ":" in host and not host.startswith("["):
        # IPv6 needs brackets in netloc form.
        host = f"[{host}]"
    return f"{host}:{port}" if port is not None else host


def _redact_path_secrets(path: str) -> str:
    if not path:
        return ""
    # Bound work: split only, do not do expensive decoding/normalization.
    parts = path.split("/")
    if len(parts) > 200:
        parts = parts[:200]
    out: list[str] = []
    for seg in parts:
        # Percent-encoded tokens (e.g. "%2F" for "/") are common in URLs, unquote before checking.
        # Preserve the original encoding in the returned URL.
        decoded = unquote(seg)
        if _looks_like_path_secret(decoded):
            out.append("[REDACTED]")
        else:
            out.append(seg)
    return "/".join(out)


def _looks_like_path_secret(segment: str) -> bool:
    if not segment:
        return False
    s = segment.strip()
    if not s:
        return False
    if _UUID_RE.match(s):
        return True
    if _looks_like_secret_path_segment(s):
        return True
    if _LONG_HEX_RE.match(s):
        return True
    if _PATH_TOKEN_RE.match(s):
        # Avoid redacting long natural-language segments by requiring digits+letters.
        has_alpha = any(ch.isalpha() for ch in s)
        has_digit = any(ch.isdigit() for ch in s)
        return has_alpha and has_digit
    if _looks_like_human_slug(s):
        # "Slug exemption" is last, it must not bypass generic token heuristics.
        return False
    return False


def _looks_like_secret_path_segment(segment: str) -> bool:
    """Heuristic for path segments.

    More conservative than query heuristics, to avoid redacting long natural-language segments in paths.
    """
    if not segment:
        return False
    s = segment.strip()
    if not s:
        return False
    if _SLACK_TOKEN_RE.match(s):
        return True
    if _JWT_PREFIX_RE.match(s):
        return True
    if _LONG_HEX_RE.match(s):
        return True

    # Base64url-ish tokens in path should include some non-letter signal (digits or URL-safe separators),
    # otherwise we risk redacting long natural-language segments.
    if len(s) >= 32 and _LONG_BASE64URLISH_RE.match(s):
        has_digit = any(ch.isdigit() for ch in s)
        has_sep = ("_" in s) or ("-" in s)
        return has_digit or has_sep

    # Standard base64-ish is usually longer and less likely to be natural language.
    if _LONG_BASE64ISH_RE.match(s):
        return True
    return False


def _looks_like_human_slug(segment: str) -> bool:
    """Best-effort exclusion for "human slugs" in paths.

    Examples we do NOT want to redact:
    - release-20240115-production
    - mcp-browser-use-1q0-follow-up
    """
    if "-" not in segment:
        return False
    if any(ch.isupper() for ch in segment):
        return False
    if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in segment):
        return False

    core = segment.replace("-", "")
    if not core:
        return False
    if len(core) < 12:
        return False

    parts = segment.split("-")
    if len(parts) < 2 or len(parts) > 10:
        return False
    if any((not p) or (len(p) > 24) or (not p.isalnum()) for p in parts):
        return False

    alpha_parts = sum(1 for p in parts if p.isalpha())
    if alpha_parts < 2:
        return False

    digit_ratio = sum(1 for ch in core if ch.isdigit()) / len(core)
    return digit_ratio <= 0.55


def _truncate(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    if max_len <= len(_TRUNC_MARKER):
        return _TRUNC_MARKER[:max_len]
    keep = max_len - len(_TRUNC_MARKER)
    return s[:keep] + _TRUNC_MARKER


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out
