"""Candidate ranker for recipe learning.

Pure functions, no I/O:
- Input: SessionRecording (captured network traffic)
- Output: top-K ranked request candidates likely to be the "money request"

The ranker is intentionally heuristic, not ML. It aims to reliably push obvious trackers,
telemetry, and tiny/no-body responses down the list while boosting endpoints that look like
data APIs (JSON, list-like, search/query paths, task token overlap).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlparse

from .models import NetworkRequest, NetworkResponse, SessionRecording
from .signals import RequestSignals, sanitize_url, summarize_response_structure

DEFAULT_TOP_K = 8
DEFAULT_MAX_CALLS = 200

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_API_PATH_HINT_RE = re.compile(r"/(api|graphql|gql|query|search)(/|$)", flags=re.IGNORECASE)
_API_VERSION_HINT_RE = re.compile(r"/v[0-9]+(/|$)", flags=re.IGNORECASE)

_TRACKER_PATH_HINT_RE = re.compile(r"/(collect|pixel|beacon|telemetry|events|event|track|tracking)(/|$)", flags=re.IGNORECASE)

_TELEMETRY_HOST_SUBSTRINGS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "segment",
    "mixpanel",
    "amplitude",
    "sentry",
    "hotjar",
    "datadog",
    "newrelic",
    "intercom",
    "snowplow",
    "facebook",
    "fbcdn",
)

_CACHE_BUSTER_KEYS = frozenset(
    {
        "_",
        "_t",
        "t",
        "ts",
        "time",
        "timestamp",
        "cb",
        "cachebust",
        "cache_bust",
        "cache_buster",
        "cacheBust",
        "nonce",
        "rnd",
        "random",
    }
)

_LIST_CONTAINER_KEYS = frozenset(
    {
        "items",
        "results",
        "data",
        "hits",
        "documents",
        "rows",
        "records",
        "entries",
        "elements",
        "values",
        "value",
        "list",
        "edges",
        "nodes",
    }
)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    rank: int
    score: float  # [0,1]
    signal: RequestSignals
    feature_values: dict[str, float]


def rank_candidates(
    recording: SessionRecording,
    *,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> list[RankedCandidate]:
    """Rank likely money-request candidates from a session recording.

    Contract:
    - Deterministic ordering (stable tie-breaks).
    - Soft scoring, no hard filters.
    - Returns at most `top_k` items.
    """
    if top_k <= 0:
        raise ValueError("top_k must be > 0")
    if max_calls < 0:
        raise ValueError("max_calls must be >= 0")

    pairs = sorted(recording.get_api_calls(), key=lambda p: p[0].timestamp)
    if max_calls:
        pairs = pairs[:max_calls]

    # Token set for similarity features.
    context_tokens = _tokenize_text(f"{recording.task} {recording.result}", max_tokens=120)

    # Page host for same-host bonus (soft).
    page_host = ""
    if recording.navigation_urls:
        page_host = (urlparse(recording.navigation_urls[-1]).hostname or "").lower()

    # Timing window for recency bonus.
    resp_ts = [float(resp.timestamp) for _, resp in pairs if resp.timestamp > 0.0]
    min_resp_ts = min(resp_ts) if resp_ts else 0.0
    max_resp_ts = max(resp_ts) if resp_ts else 0.0
    ts_span = max(0.0, max_resp_ts - min_resp_ts)

    scored: list[tuple[float, str, str, RequestSignals, dict[str, float]]] = []
    for req, resp in pairs:
        signal = _build_signal(recording=recording, req=req, resp=resp)
        feature_values = _score_features(
            req=req,
            resp=resp,
            signal=signal,
            context_tokens=context_tokens,
            page_host=page_host,
            min_resp_ts=min_resp_ts,
            ts_span=ts_span,
        )
        raw_score = _weighted_sum(feature_values)
        score = _squash_score(raw_score)
        scored.append((score, signal.url, signal.method, signal, feature_values))

    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    out: list[RankedCandidate] = []
    for i, (score, _url, _method, signal, feats) in enumerate(scored[:top_k]):
        out.append(RankedCandidate(rank=i + 1, score=score, signal=signal, feature_values=feats))
    return out


def _build_signal(*, recording: SessionRecording, req: NetworkRequest, resp: NetworkResponse) -> RequestSignals:
    url_s = sanitize_url(req.url, max_len=2048)
    initiator = ""
    if req.initiator_url:
        initiator = sanitize_url(req.initiator_url, max_len=2048)

    content_type = _extract_content_type(resp)
    response_size_bytes = _extract_response_size_bytes(resp)
    duration_ms = _duration_ms(req_ts=req.timestamp, resp_ts=resp.timestamp)
    structural_summary = summarize_response_structure(content_type=content_type, body=resp.body, max_len=500)

    return RequestSignals(
        url=url_s,
        method=req.method.upper() if req.method else "GET",
        status=int(resp.status),
        content_type=content_type,
        response_size_bytes=response_size_bytes,
        structural_summary=structural_summary,
        duration_ms=duration_ms,
        request_timestamp=float(req.timestamp),
        response_timestamp=float(resp.timestamp),
        initiator_page_url=initiator,
        resource_type=(req.resource_type or "").lower(),
    )


def _extract_content_type(resp: NetworkResponse) -> str:
    # Prefer captured content_type; fallback to mime_type; fallback to header.
    if resp.content_type:
        return str(resp.content_type).split(";", 1)[0].strip().lower()[:200]
    if resp.mime_type:
        return str(resp.mime_type).split(";", 1)[0].strip().lower()[:200]
    for k, v in resp.headers.items():
        if k.lower() == "content-type":
            return str(v).split(";", 1)[0].strip().lower()[:200]
    return ""


def _extract_response_size_bytes(resp: NetworkResponse) -> int:
    # Prefer explicit byte_length (from loadingFinished), then Content-Length, then body bytes.
    if isinstance(resp.byte_length, int) and resp.byte_length >= 0:
        return resp.byte_length
    for k, v in resp.headers.items():
        if k.lower() == "content-length":
            try:
                n = int(str(v).strip())
                if n >= 0:
                    return n
            except ValueError:
                pass
    if resp.body is None:
        return 0
    return len(resp.body.encode("utf-8", errors="replace"))


def _duration_ms(*, req_ts: float, resp_ts: float) -> float | None:
    if req_ts <= 0.0 or resp_ts <= 0.0:
        return None
    if resp_ts < req_ts:
        return None
    return (resp_ts - req_ts) * 1000.0


def _tokenize_text(text: str, *, max_tokens: int) -> frozenset[str]:
    if not text or max_tokens <= 0:
        return frozenset()
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return frozenset()
    # Drop very short tokens to avoid overweighting "a", "to", etc.
    filtered = [t for t in tokens if len(t) >= 3]
    if not filtered:
        return frozenset()
    return frozenset(filtered[:max_tokens])


def _tokenize_url(url: str) -> frozenset[str]:
    if not url:
        return frozenset()
    try:
        parsed = urlparse(url)
    except ValueError:
        return _tokenize_text(url, max_tokens=120)

    path = unquote(parsed.path or "")
    tokens = _TOKEN_RE.findall((parsed.hostname or "").lower() + " " + path.lower())

    # Query: include keys and (short) values, skip redacted values.
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        tokens.extend(_TOKEN_RE.findall(k.lower()))
        if v and v != "[REDACTED]" and len(v) <= 80:
            tokens.extend(_TOKEN_RE.findall(v.lower()))

    filtered = [t for t in tokens if len(t) >= 3]
    return frozenset(filtered[:140])


def _overlap_ratio(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    denom = max(1, min(len(a), len(b)))
    return min(1.0, len(inter) / denom)


def _body_overlap_score(*, body: str | None, context_tokens: frozenset[str]) -> float:
    if not body or not context_tokens:
        return 0.0
    snippet = body[:4096]
    body_tokens = _tokenize_text(snippet, max_tokens=240)
    return _overlap_ratio(body_tokens, context_tokens)


def _is_jsonish_content_type(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return ("json" in ct) or ("graphql" in ct)


def _parse_json_body(body: str) -> object | None:
    # Bound cost: align with signals.py behavior.
    if len(body) > 50_000:
        return None
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return None


def _list_likelihood(*, json_value: object | None, structural_summary: str) -> float:
    if isinstance(json_value, list):
        return 1.0 if len(json_value) >= 1 else 0.6
    if isinstance(json_value, dict):
        for k, v in json_value.items():
            if str(k).lower() in _LIST_CONTAINER_KEYS and isinstance(v, list):
                return 0.9 if len(v) >= 1 else 0.65
        return 0.2

    summary_l = (structural_summary or "").lower()
    if summary_l.startswith("array("):
        return 0.85
    # Cheap key hint extraction from the summary string.
    for key in _LIST_CONTAINER_KEYS:
        if key in summary_l:
            return 0.55
    return 0.0


def _json_richness(*, json_value: object | None, structural_summary: str) -> float:
    # Prefer actual JSON stats when available; fallback to coarse structural string.
    if isinstance(json_value, (list, dict)):
        stats = _json_stats(json_value, max_nodes=900, max_depth=8)
        # Penalize trivial payloads.
        if stats.total_nodes <= 3 and stats.unique_keys <= 2 and stats.max_depth <= 1:
            return 0.0
        key_score = min(1.0, stats.unique_keys / 30.0)
        depth_score = min(1.0, stats.max_depth / 6.0)
        list_score = 0.4 if stats.list_nodes >= 1 else 0.0
        return min(1.0, key_score * 0.55 + depth_score * 0.35 + list_score)

    s = (structural_summary or "").lower()
    if "object(" in s and "keys=" in s:
        return 0.35
    if s.startswith("array("):
        return 0.35
    if "json" in s:
        return 0.2
    return 0.0


@dataclass(frozen=True, slots=True)
class _JsonStats:
    total_nodes: int
    unique_keys: int
    max_depth: int
    dict_nodes: int
    list_nodes: int


def _json_stats(value: object, *, max_nodes: int, max_depth: int) -> _JsonStats:
    seen_keys: set[str] = set()
    total_nodes = 0
    dict_nodes = 0
    list_nodes = 0
    max_seen_depth = 0

    stack: list[tuple[object, int]] = [(value, 0)]
    while stack and total_nodes < max_nodes:
        node, depth = stack.pop()
        total_nodes += 1
        max_seen_depth = max(max_seen_depth, depth)
        if depth >= max_depth:
            continue

        if isinstance(node, dict):
            dict_nodes += 1
            for k, v in node.items():
                seen_keys.add(str(k).lower())
                if isinstance(v, (dict, list)):
                    stack.append((v, depth + 1))
            continue

        if isinstance(node, list):
            list_nodes += 1
            for child in node[:12]:
                if isinstance(child, (dict, list)):
                    stack.append((child, depth + 1))
            continue

    return _JsonStats(
        total_nodes=total_nodes,
        unique_keys=len(seen_keys),
        max_depth=max_seen_depth,
        dict_nodes=dict_nodes,
        list_nodes=list_nodes,
    )


def _status_score(status: int) -> float:
    if 200 <= status <= 299:
        return 1.0
    if 300 <= status <= 399:
        return 0.25
    if 400 <= status <= 499:
        return -0.75
    if 500 <= status <= 599:
        return -0.95
    return -0.2


def _api_path_hint(url: str) -> float:
    try:
        path = urlparse(url).path or ""
    except ValueError:
        path = url
    if _TRACKER_PATH_HINT_RE.search(path):
        return 0.0
    if _API_PATH_HINT_RE.search(path):
        return 1.0
    if _API_VERSION_HINT_RE.search(path):
        return 0.6
    # Common API-ish nouns even without "/api/" prefix.
    path_l = path.lower()
    if "/search" in path_l or "/query" in path_l:
        return 0.7
    return 0.0


def _tracker_path_penalty(url: str) -> float:
    try:
        path = urlparse(url).path or ""
    except ValueError:
        path = url
    return 1.0 if _TRACKER_PATH_HINT_RE.search(path) else 0.0


def _telemetry_host_penalty(url: str) -> float:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = url.lower()
    for sub in _TELEMETRY_HOST_SUBSTRINGS:
        if sub in host:
            return 1.0
    return 0.0


def _cache_buster_penalty(url: str) -> float:
    try:
        query = urlparse(url).query or ""
    except ValueError:
        return 0.0
    for k, _v in parse_qsl(query, keep_blank_values=True):
        if k in _CACHE_BUSTER_KEYS or k.lower() in _CACHE_BUSTER_KEYS:
            return 1.0
    return 0.0


def _same_host_bonus(*, url: str, page_host: str, initiator_url: str) -> float:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    if not host:
        return 0.0
    if page_host and host == page_host:
        return 1.0
    if initiator_url:
        try:
            init_host = (urlparse(initiator_url).hostname or "").lower()
        except ValueError:
            init_host = ""
        if init_host and host == init_host:
            return 0.8
    return 0.0


def _recency_bonus(*, response_timestamp: float, min_resp_ts: float, ts_span: float) -> float:
    if response_timestamp <= 0.0 or ts_span <= 0.0:
        return 0.0
    x = (response_timestamp - min_resp_ts) / ts_span
    return min(1.0, max(0.0, x))


def _content_type_score(content_type: str) -> float:
    ct = (content_type or "").lower()
    if "json" in ct or "graphql" in ct:
        return 1.0
    if "html" in ct:
        return -0.4
    if ct.startswith("text/"):
        return 0.0
    if ct.startswith("image/"):
        return -0.5
    if ct:
        return -0.1
    return -0.2


def _size_small_penalty(size_bytes: int) -> float:
    if size_bytes <= 0:
        return 0.6
    if size_bytes < 200:
        return 1.0
    if size_bytes < 600:
        return 0.5
    return 0.0


def _size_large_penalty(size_bytes: int) -> float:
    if size_bytes > 32 * 1024:
        return 1.0
    if size_bytes > 16 * 1024:
        return 0.5
    return 0.0


def _resource_type_bonus(resource_type: str) -> float:
    rt = (resource_type or "").lower()
    if rt in ("xhr", "fetch"):
        return 1.0
    if rt == "document":
        return 0.3
    return 0.0


def _score_features(
    *,
    req: NetworkRequest,
    resp: NetworkResponse,
    signal: RequestSignals,
    context_tokens: frozenset[str],
    page_host: str,
    min_resp_ts: float,
    ts_span: float,
) -> dict[str, float]:
    url_tokens = _tokenize_url(signal.url)
    url_similarity = _overlap_ratio(url_tokens, context_tokens)
    body_overlap = _body_overlap_score(body=resp.body, context_tokens=context_tokens)

    json_value: object | None = None
    if resp.body and (_is_jsonish_content_type(signal.content_type) or resp.body.lstrip().startswith(("{", "["))):
        parsed = _parse_json_body(resp.body)
        if isinstance(parsed, (dict, list)) or parsed is None:
            json_value = parsed

    list_likelihood = _list_likelihood(json_value=json_value, structural_summary=signal.structural_summary)
    json_richness = _json_richness(json_value=json_value, structural_summary=signal.structural_summary)

    feats: dict[str, float] = {
        "url_similarity": url_similarity,
        "body_overlap": body_overlap,
        "content_type": _content_type_score(signal.content_type),
        "list_likelihood": list_likelihood,
        "json_richness": json_richness,
        "status": _status_score(signal.status),
        "api_path_hint": _api_path_hint(signal.url),
        "tracker_path_penalty": _tracker_path_penalty(signal.url),
        "telemetry_host_penalty": _telemetry_host_penalty(signal.url),
        "size_small_penalty": _size_small_penalty(signal.response_size_bytes),
        "size_large_penalty": _size_large_penalty(signal.response_size_bytes),
        "cache_buster_penalty": _cache_buster_penalty(signal.url),
        "recency_bonus": _recency_bonus(response_timestamp=signal.response_timestamp, min_resp_ts=min_resp_ts, ts_span=ts_span),
        "same_host_bonus": _same_host_bonus(url=signal.url, page_host=page_host, initiator_url=signal.initiator_page_url),
        "resource_type_bonus": _resource_type_bonus(signal.resource_type),
    }

    # Defensive normalization for comparisons.
    if not req.method or req.method.upper() == "GET":
        feats["method_get_bonus"] = 1.0
    else:
        feats["method_get_bonus"] = 0.0

    return feats


_FEATURE_WEIGHTS: dict[str, float] = {
    "url_similarity": 1.7,
    "body_overlap": 1.2,
    "content_type": 1.0,
    "list_likelihood": 0.9,
    "json_richness": 0.7,
    "status": 0.9,
    "api_path_hint": 0.55,
    "tracker_path_penalty": -1.4,
    "telemetry_host_penalty": -1.6,
    "size_small_penalty": -1.0,
    "size_large_penalty": -0.55,
    "cache_buster_penalty": -0.35,
    "recency_bonus": 0.35,
    "same_host_bonus": 0.35,
    "resource_type_bonus": 0.25,
    "method_get_bonus": 0.15,
}


def _weighted_sum(feature_values: dict[str, float]) -> float:
    total = 0.0
    for name, value in feature_values.items():
        weight = _FEATURE_WEIGHTS.get(name)
        if weight is None:
            continue
        total += weight * float(value)
    return total


def _squash_score(raw_score: float) -> float:
    # Map unbounded raw score to [0,1] deterministically.
    # Clamp exponent range for numeric stability.
    x = max(-20.0, min(20.0, raw_score))
    return 1.0 / (1.0 + math.exp(-x))
