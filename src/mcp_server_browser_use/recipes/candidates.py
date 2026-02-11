"""Candidate ranking for recipe learning.

Produces a small set of best-guess API call candidates from a SessionRecording.

This is intentionally heuristic and deterministic:
- No I/O
- No LLM calls
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .models import SessionRecording
from .signals import RequestSignals, extract_request_signals

DEFAULT_TOP_K = 5
DEFAULT_MAX_CALLS = 200

_TRACKER_HOST_SUBSTRINGS = (
    "google-analytics.com",
    "doubleclick.net",
    "googletagmanager.com",
    "segment.com",
    "sentry.io",
    "datadoghq.com",
    "mixpanel.com",
    "amplitude.com",
    "hotjar.com",
)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Ranked request signal with score and notes for debugging."""

    rank: int
    score: float
    notes: str
    signal: RequestSignals


def rank_candidates(
    recording: SessionRecording,
    *,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> list[RankedCandidate]:
    """Rank candidate API calls for recipe extraction."""
    signals = extract_request_signals(recording, max_calls=max_calls)
    scored: list[tuple[float, RequestSignals, str]] = []
    for sig in signals:
        score, notes = _score_signal(sig)
        scored.append((score, sig, notes))

    scored.sort(key=lambda s: (s[0], -s[1].response_timestamp), reverse=True)

    if top_k > 0:
        scored = scored[:top_k]

    out: list[RankedCandidate] = []
    for idx, (score, sig, notes) in enumerate(scored, start=1):
        out.append(RankedCandidate(rank=idx, score=float(score), notes=notes, signal=sig))
    return out


def _score_signal(sig: RequestSignals) -> tuple[float, str]:
    notes: list[str] = []
    score = 0.0

    # Status
    if 200 <= int(sig.status) <= 299:
        score += 0.40
        notes.append("2xx")
    elif 300 <= int(sig.status) <= 399:
        score += 0.05
        notes.append("3xx")
    else:
        score -= 0.40
        notes.append("non-2xx")

    # Method
    method = (sig.method or "").upper()
    if method == "GET":
        score += 0.10
        notes.append("GET")
    elif method:
        score += 0.02
        notes.append(method)

    # Content type preference
    ct = (sig.content_type or "").lower()
    if "json" in ct or "graphql" in ct:
        score += 0.30
        notes.append("json")
    elif "html" in ct:
        score += 0.10
        notes.append("html")
    elif ct:
        score += 0.02
        notes.append("ct")

    # Resource type
    rt = (sig.resource_type or "").lower()
    if rt in ("xhr", "fetch"):
        score += 0.10
        notes.append(rt)
    elif rt:
        score += 0.01
        notes.append("rt")

    # Body size: avoid tiny/no-body and huge payloads.
    size = int(sig.response_size_bytes)
    if size < 200:
        score -= 0.20
        notes.append("tiny")
    elif size > 256 * 1024:
        score -= 0.20
        notes.append("huge")
    else:
        score += 0.05
        notes.append("size_ok")

    # Tracker/telemetry penalties.
    host = (urlparse(sig.url).hostname or "").lower()
    if host and any(substr in host for substr in _TRACKER_HOST_SUBSTRINGS):
        score -= 0.40
        notes.append("tracker")
    if "/collect" in sig.url:
        score -= 0.20
        notes.append("collect")

    # Clamp to [0, 1] for easier downstream thresholds.
    score = max(0.0, min(1.0, score))
    return score, ",".join(notes)
