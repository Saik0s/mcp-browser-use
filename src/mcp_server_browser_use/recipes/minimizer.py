"""Recipe request minimizer.

Goal: given a baseline response fingerprint, reduce a captured request spec to the smallest
header/query set that still produces a similar-shaped response.

Algorithm (v1):
- Volatility detection (deterministic): identify volatile headers/query params.
- Header minimization (single-pass): try removing each header once, keep removal if replay stays 2xx and fingerprint similarity >= threshold.
- Query minimization (single-pass): same for query params.

This module is transport-agnostic: callers provide an async `replay()` function that can execute
the request (httpx, browser fetch via CDP, etc).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .artifacts.models import BaselineFingerprint, MinimizationResult, MinimizationStep, RecipeRequestSpec
from .fingerprint import DEFAULT_SIMILARITY_THRESHOLD, Fingerprint, JSONValue, JsonValueType, TypedJsonPath, fingerprint, fingerprint_similarity
from .runner import extract_data

VOLATILE_QUERY_PARAM_NAMES: Final[frozenset[str]] = frozenset({"_t", "timestamp", "ts", "nonce", "cache", "cb", "rand", "_"})

VOLATILE_HEADER_NAMES: Final[frozenset[str]] = frozenset({"if-none-match", "if-modified-since", "x-request-id"})

NOISE_HEADER_PREFIXES: Final[tuple[str, ...]] = ("sec-fetch-", "sec-ch-ua")

NOISE_HEADER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "accept-encoding",
        "connection",
        "host",
        "content-length",
        "pragma",
        "cache-control",
        "user-agent",
        "origin",
        "referer",
    }
)


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    http_status: int
    body_text: str
    error: str | None = None


ReplayFn = Callable[[RecipeRequestSpec], Awaitable[ReplayOutcome]]


@dataclass(frozen=True, slots=True)
class MinimizerConfig:
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    max_attempts: int = 24
    max_wall_seconds: float = 30.0
    pacing_ms: int = 250


@dataclass(frozen=True, slots=True)
class _ReplayEvaluation:
    ok: bool
    http_status: int
    similarity: float | None
    error: str | None = None


def _canonical_header_name(name: str) -> str:
    return "-".join(name.strip().lower().replace("_", "-").split())


def _is_2xx(status: int) -> bool:
    return 200 <= status < 300


def _is_noise_header(name: str) -> bool:
    canonical = _canonical_header_name(name)
    if canonical in NOISE_HEADER_NAMES:
        return True
    return any(canonical.startswith(prefix) for prefix in NOISE_HEADER_PREFIXES)


def _is_volatile_header(name: str) -> bool:
    canonical = _canonical_header_name(name)
    if canonical in VOLATILE_HEADER_NAMES:
        return True
    return canonical.startswith("x-trace-")


def _is_volatile_query_param(name: str) -> bool:
    n = name.strip().lower()
    if n in VOLATILE_QUERY_PARAM_NAMES:
        return True
    # Common cache-busters like "_=123".
    if n == "_":
        return True
    # Conservative token matching, avoids making this a sprawling ruleset.
    return False


def _split_query(url: str) -> tuple[list[tuple[str, str]], str]:
    parsed = urlparse(url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
    return query_pairs, base_url


def _set_query(url: str, query_pairs: list[tuple[str, str]]) -> str:
    parsed = urlparse(url)
    new_query = urlencode(query_pairs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _drop_query_keys(url: str, keys_to_drop: set[str]) -> tuple[str, bool]:
    pairs, _base = _split_query(url)
    if not pairs:
        return url, False
    filtered = [(k, v) for (k, v) in pairs if k not in keys_to_drop]
    if filtered == pairs:
        return url, False
    return _set_query(url, filtered), True


def _query_keys(url: str) -> list[str]:
    pairs, _base = _split_query(url)
    out: list[str] = []
    seen: set[str] = set()
    for k, _v in pairs:
        if k not in seen:
            out.append(k)
            seen.add(k)
    return out


def _request_signature(spec: RecipeRequestSpec) -> str:
    payload = {
        "url": spec.url,
        "method": spec.method,
        "headers": {k: spec.headers[k] for k in sorted(spec.headers)},
        "body_template": spec.body_template,
        "response_type": spec.response_type,
        "extract_path": spec.extract_path,
        "html_selectors": spec.html_selectors,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _baseline_fingerprint(baseline: BaselineFingerprint) -> Fingerprint:
    out: set[TypedJsonPath] = set()
    for entry in baseline.entries:
        value_type = JsonValueType(entry.value_type.value)
        out.add(TypedJsonPath(path=entry.path, value_type=value_type))
    return frozenset(out)


def _validate_json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_validate_json_value(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, JSONValue] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("JSON object keys must be strings")
            out[k] = _validate_json_value(v)
        return out
    raise ValueError(f"Unsupported JSON value type: {type(value)!r}")


def _parse_json(body_text: str) -> JSONValue:
    parsed = json.loads(body_text)
    return _validate_json_value(parsed)


class RecipeRequestMinimizer:
    def __init__(self, replay: ReplayFn, *, config: MinimizerConfig | None = None) -> None:
        self._replay = replay
        self._config = config or MinimizerConfig()
        self._cache: dict[str, _ReplayEvaluation] = {}
        self._attempts: int = 0
        self._start_monotonic: float = time.monotonic()

    def _budget_exhausted(self) -> bool:
        if self._attempts >= self._config.max_attempts:
            return True
        if (time.monotonic() - self._start_monotonic) >= self._config.max_wall_seconds:
            return True
        return False

    async def _evaluate(self, spec: RecipeRequestSpec, *, baseline_fp: Fingerprint, max_depth: int) -> _ReplayEvaluation:
        sig = _request_signature(spec)
        cached = self._cache.get(sig)
        if cached is not None:
            return cached

        if self._budget_exhausted():
            evaluation = _ReplayEvaluation(ok=False, http_status=0, similarity=None, error="budget_exhausted")
            self._cache[sig] = evaluation
            return evaluation

        if self._attempts > 0 and self._config.pacing_ms > 0:
            await asyncio.sleep(self._config.pacing_ms / 1000.0)

        self._attempts += 1
        outcome = await self._replay(spec)
        if not _is_2xx(outcome.http_status):
            evaluation = _ReplayEvaluation(ok=False, http_status=outcome.http_status, similarity=0.0, error=outcome.error)
            self._cache[sig] = evaluation
            return evaluation

        if spec.response_type != "json":
            evaluation = _ReplayEvaluation(ok=True, http_status=outcome.http_status, similarity=1.0, error=None)
            self._cache[sig] = evaluation
            return evaluation

        try:
            data_obj = _parse_json(outcome.body_text)
        except Exception as e:  # boundary: replay returned malformed JSON
            evaluation = _ReplayEvaluation(ok=False, http_status=outcome.http_status, similarity=0.0, error=f"json_parse_failed: {e}")
            self._cache[sig] = evaluation
            return evaluation

        if spec.extract_path:
            try:
                data_obj = extract_data(data_obj, spec.extract_path)
            except ValueError:
                # Minimization compares against baseline shape. If extraction fails, fall back to full body.
                pass

        try:
            data_obj = _validate_json_value(data_obj)
        except Exception as e:  # boundary: unexpected JMESPath result
            evaluation = _ReplayEvaluation(ok=False, http_status=outcome.http_status, similarity=0.0, error=f"extracted_not_json: {e}")
            self._cache[sig] = evaluation
            return evaluation

        current_fp = fingerprint(data_obj, max_depth=max_depth)
        similarity = fingerprint_similarity(baseline_fp, current_fp)
        evaluation = _ReplayEvaluation(
            ok=similarity >= self._config.similarity_threshold, http_status=outcome.http_status, similarity=similarity, error=None
        )
        self._cache[sig] = evaluation
        return evaluation

    async def minimize(self, *, baseline: BaselineFingerprint, request: RecipeRequestSpec) -> MinimizationResult:
        steps: list[MinimizationStep] = []

        baseline_fp = _baseline_fingerprint(baseline)
        max_depth = baseline.max_depth

        working = request

        # Phase A: deterministic volatility/noise filtering.
        volatile_headers = {k for k in working.headers if _is_volatile_header(k)}
        noise_headers = {k for k in working.headers if _is_noise_header(k)}
        drop_headers = volatile_headers | noise_headers
        if drop_headers:
            new_headers = {k: v for k, v in working.headers.items() if k not in drop_headers}
            working = working.model_copy(update={"headers": new_headers})
            steps.append(MinimizationStep(description=f"dropped {len(drop_headers)} volatile/noise headers", changed=True))
        else:
            steps.append(MinimizationStep(description="no volatile/noise headers to drop", changed=False))

        # Phase B: header minimization via single-pass elimination.
        for header_name in sorted(working.headers):
            if self._budget_exhausted():
                break
            candidate_headers = dict(working.headers)
            candidate_headers.pop(header_name, None)
            candidate = working.model_copy(update={"headers": candidate_headers})

            evaluation = await self._evaluate(candidate, baseline_fp=baseline_fp, max_depth=max_depth)
            if evaluation.ok:
                working = candidate
                steps.append(MinimizationStep(description=f"removed header {header_name!r}", changed=True))
            else:
                steps.append(MinimizationStep(description=f"kept header {header_name!r}", changed=False))

        # Phase C: query param minimization via single-pass elimination.
        keys = _query_keys(working.url)
        volatile_keys = [k for k in keys if _is_volatile_query_param(k)]
        stable_keys = [k for k in keys if k not in set(volatile_keys)]
        for key in volatile_keys + stable_keys:
            if self._budget_exhausted():
                break
            candidate_url, changed = _drop_query_keys(working.url, {key})
            if not changed:
                continue
            candidate = working.model_copy(update={"url": candidate_url})

            evaluation = await self._evaluate(candidate, baseline_fp=baseline_fp, max_depth=max_depth)
            if evaluation.ok:
                working = candidate
                steps.append(MinimizationStep(description=f"removed query param {key!r}", changed=True))
            else:
                steps.append(MinimizationStep(description=f"kept query param {key!r}", changed=False))

        notes_parts: list[str] = []
        if self._budget_exhausted():
            notes_parts.append("budget exhausted before full minimization pass")
        if request.response_type != "json":
            notes_parts.append("non-json response_type, similarity checks are status-only")

        notes = "; ".join(notes_parts)
        return MinimizationResult(
            schema_hash=MinimizationResult.schema_hash_value(),
            baseline=baseline,
            original_request=request,
            minimized_request=working,
            steps=steps,
            notes=notes,
        )


def detect_volatile_query_params(url: str) -> set[str]:
    return {k for k in _query_keys(url) if _is_volatile_query_param(k)}


def detect_volatile_headers(headers: Mapping[str, str]) -> set[str]:
    return {k for k in headers if _is_volatile_header(k)}


def detect_noise_headers(headers: Mapping[str, str]) -> set[str]:
    return {k for k in headers if _is_noise_header(k)}


def volatility_hints(request: RecipeRequestSpec) -> dict[str, set[str]]:
    """Return deterministic volatility detection hints for a captured request spec."""
    return {
        "volatile_query_params": detect_volatile_query_params(request.url),
        "volatile_headers": detect_volatile_headers(request.headers),
        "noise_headers": detect_noise_headers(request.headers),
    }


def redact_volatility_hints(hints: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    """Stabilize hint output for logging/tests (sort for determinism)."""
    return {k: sorted(set(v)) for k, v in hints.items()}
