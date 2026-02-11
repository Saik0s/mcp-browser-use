"""Heuristic analyzer for simple recipe drafts.

Pure functions only:
- No I/O, no logging, no network.
- Uses ranked candidates to decide whether we can build a minimal direct-exec Recipe
  without invoking an LLM.

This is intentionally conservative. If we are not confident, return None and let the
LLM-based analyzer handle the case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .candidates import DEFAULT_MAX_CALLS, DEFAULT_TOP_K, RankedCandidate, rank_candidates
from .models import NetworkRequest, Recipe, RecipeParameter, RecipeRequest, SessionRecording, strip_sensitive_headers
from .signals import sanitize_url

HIGH_CONFIDENCE_MIN_SCORE = 0.85
HIGH_CONFIDENCE_MIN_GAP = 0.30

_MIN_BODY_SIZE_BYTES = 200
_MAX_BODY_SIZE_BYTES = 32 * 1024

_QUERY_KEYS_TO_TEMPLATE: tuple[str, ...] = ("q", "query", "term", "search", "keyword", "keywords")

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "code",
        "cookie",
        "csrf",
        "id_token",
        "key",
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

_JWT_RE = re.compile(r"^eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}$")
_LONG_HEX_RE = re.compile(r"^[a-fA-F0-9]{32,}$")
_LONG_BASE64URLISH_RE = re.compile(r"^[a-zA-Z0-9_-]{32,}={0,2}$")

_SLUG_SAFE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class HeuristicDraft:
    """Heuristic draft output (for pipeline/debugging)."""

    recipe: Recipe
    chosen: RankedCandidate
    score_gap: float


def try_build_heuristic_draft(
    recording: SessionRecording,
    *,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
    min_score: float = HIGH_CONFIDENCE_MIN_SCORE,
    min_gap: float = HIGH_CONFIDENCE_MIN_GAP,
) -> HeuristicDraft | None:
    """Try to build a minimal direct-execution recipe draft without an LLM.

    Returns:
        HeuristicDraft when confidence checks pass, else None.
    """
    candidates = rank_candidates(recording, top_k=top_k, max_calls=max_calls)
    return try_build_heuristic_draft_from_candidates(recording, candidates=candidates, min_score=min_score, min_gap=min_gap)


def try_build_heuristic_draft_from_candidates(
    recording: SessionRecording,
    *,
    candidates: list[RankedCandidate],
    min_score: float = HIGH_CONFIDENCE_MIN_SCORE,
    min_gap: float = HIGH_CONFIDENCE_MIN_GAP,
) -> HeuristicDraft | None:
    if not candidates:
        return None

    top = candidates[0]
    second_score = candidates[1].score if len(candidates) >= 2 else 0.0
    gap = float(top.score) - float(second_score)

    if float(top.score) < float(min_score):
        return None
    if gap < float(min_gap):
        return None
    if top.signal.method.upper() != "GET":
        return None
    if not _is_jsonish_content_type(top.signal.content_type):
        return None
    if not _body_size_ok(top.signal.response_size_bytes):
        return None
    if not (200 <= int(top.signal.status) <= 299):
        return None

    req = _find_original_request(recording, top)
    if req is None:
        return None

    built = _build_recipe_request_from_request(req.url, req.headers)
    if built is None:
        return None
    recipe_request, params = built

    recipe = Recipe(
        name=_suggest_recipe_name(recording=recording, url=recipe_request.url),
        description=recording.task,
        original_task=recording.task,
        request=recipe_request,
        parameters=params,
    )
    return HeuristicDraft(recipe=recipe, chosen=top, score_gap=gap)


def _find_original_request(recording: SessionRecording, chosen: RankedCandidate) -> NetworkRequest | None:
    """Find the original NetworkRequest matching the chosen candidate signal.

    We match on (method, sanitized_url). This is deterministic and avoids
    depending on request_id plumbing (not guaranteed yet).
    """
    method = chosen.signal.method.upper()
    target_url = chosen.signal.url
    for req, _resp in sorted(recording.get_api_calls(), key=lambda p: p[0].timestamp):
        if (req.method or "").upper() != method:
            continue
        if sanitize_url(req.url, max_len=2048) == target_url:
            return req
    return None


def _build_recipe_request_from_request(url: str, headers: dict[str, str]) -> tuple[RecipeRequest, list[RecipeParameter]] | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None

    host = parsed.hostname or ""

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    templated_key, templated_value = _pick_query_key_to_template(query_items)

    out_query: list[tuple[str, str]] = []
    params: list[RecipeParameter] = []
    for k, v in query_items:
        k_l = k.lower()
        if k_l in _SENSITIVE_QUERY_KEYS:
            continue
        if _looks_like_secret_value(v):
            continue
        if templated_key and k_l == templated_key:
            out_query.append((k, "{query}"))
            continue
        out_query.append((k, v))

    if templated_key and templated_value is not None:
        params.append(
            RecipeParameter(
                name="query",
                type="string",
                required=False,
                default=templated_value,
                description=f"Search query ({templated_key})",
                source="query",
            )
        )

    safe_url = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(out_query, doseq=True, safe=""),
            "",  # drop fragment
        )
    )
    if "[REDACTED]" in safe_url:
        return None
    if len(safe_url) > 2048:
        return None

    safe_headers = strip_sensitive_headers(headers)
    filtered_headers = _select_request_headers(safe_headers)

    return (
        RecipeRequest(
            url=safe_url,
            method="GET",
            headers=filtered_headers,
            response_type="json",
            extract_path=None,
            html_selectors=None,
            allowed_domains=[host] if host else [],
        ),
        params,
    )


def _select_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep a tiny, conservative header subset for deterministic drafts."""
    allow = {"accept", "accept-language", "content-type", "x-requested-with"}
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in allow:
            out[k] = v
    return out


def _pick_query_key_to_template(query_items: list[tuple[str, str]]) -> tuple[str | None, str | None]:
    # Preserve original order but bias toward well-known search keys.
    by_key: dict[str, str] = {}
    for k, v in query_items:
        k_l = k.lower()
        if k_l in by_key:
            continue
        if not v:
            continue
        by_key[k_l] = v

    for key in _QUERY_KEYS_TO_TEMPLATE:
        v = by_key.get(key)
        if v is None:
            continue
        if _looks_like_secret_value(v):
            continue
        return key, v
    return None, None


def _looks_like_secret_value(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if len(v) >= 120:
        return True
    if _JWT_RE.match(v):
        return True
    if _LONG_HEX_RE.match(v):
        return True
    # Pagination cursors can look base64url-ish, so we treat only very long strings as suspicious.
    if len(v) >= 80 and _LONG_BASE64URLISH_RE.match(v):
        return True
    return False


def _is_jsonish_content_type(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return ("json" in ct) or ("graphql" in ct)


def _body_size_ok(size_bytes: int) -> bool:
    return _MIN_BODY_SIZE_BYTES <= int(size_bytes) <= _MAX_BODY_SIZE_BYTES


def _suggest_recipe_name(*, recording: SessionRecording, url: str) -> str:
    # Stable-ish, readable, ASCII.
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    raw = f"{host}{path}".strip()
    if not raw:
        raw = recording.task.lower()
    slug = _SLUG_SAFE_RE.sub("-", raw).strip("-")
    if not slug:
        slug = "recipe"
    return slug[:60]
