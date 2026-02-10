"""Recipe verifier.

Given a minimized request spec and a baseline response fingerprint, replay the request and decide
whether the recipe can be promoted from "draft" to "verified".

This module is transport-agnostic. Callers provide an async `replay()` function that executes the
request (httpx, in-page fetch via CDP, etc) and returns the raw response body + status.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .artifacts.models import BaselineFingerprint, MinimizationResult, RecipeRequestSpec, VerificationAttempt, VerificationReport, VerificationStatus
from .fingerprint import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_SIMILARITY_THRESHOLD,
    Fingerprint,
    JSONValue,
    JsonValueType,
    TypedJsonPath,
    fingerprint,
    fingerprint_similarity,
)
from .runner import extract_data

_PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    http_status: int
    body_text: str
    error: str | None = None


ReplayFn = Callable[[RecipeRequestSpec], Awaitable[ReplayOutcome]]


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    required_consecutive_successes: int = 2
    max_attempts: int = 6
    max_wall_seconds: float = 30.0
    pacing_ms: int = 250


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _is_2xx(status: int) -> bool:
    return 200 <= status < 300


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


def request_has_placeholders(spec: RecipeRequestSpec) -> bool:
    if _PLACEHOLDER_PATTERN.search(spec.url):
        return True
    if spec.body_template and _PLACEHOLDER_PATTERN.search(spec.body_template):
        return True
    return False


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


class RecipeVerifier:
    def __init__(self, replay: ReplayFn, *, config: VerifierConfig | None = None) -> None:
        self._replay = replay
        self._config = config or VerifierConfig()
        self._cache: dict[str, tuple[bool, int, float | None, str | None]] = {}
        self._attempts: int = 0
        self._start_monotonic: float = time.monotonic()

    def _budget_exhausted(self) -> bool:
        if self._attempts >= self._config.max_attempts:
            return True
        if (time.monotonic() - self._start_monotonic) >= self._config.max_wall_seconds:
            return True
        return False

    async def _evaluate(self, spec: RecipeRequestSpec, *, baseline_fp: Fingerprint, max_depth: int) -> tuple[bool, int, float | None, str | None]:
        sig = _request_signature(spec)
        cached = self._cache.get(sig)
        if cached is not None:
            return cached

        if self._budget_exhausted():
            evaluation = (False, 0, None, "budget_exhausted")
            self._cache[sig] = evaluation
            return evaluation

        if self._attempts > 0 and self._config.pacing_ms > 0:
            await asyncio.sleep(self._config.pacing_ms / 1000.0)

        self._attempts += 1
        outcome = await self._replay(spec)
        if not _is_2xx(outcome.http_status):
            evaluation = (False, outcome.http_status, 0.0, outcome.error)
            self._cache[sig] = evaluation
            return evaluation

        if spec.response_type != "json":
            evaluation = (True, outcome.http_status, 1.0, None)
            self._cache[sig] = evaluation
            return evaluation

        try:
            data_obj = _parse_json(outcome.body_text)
        except Exception as e:  # boundary: untrusted server response
            evaluation = (False, outcome.http_status, 0.0, f"json_parse_failed: {e}")
            self._cache[sig] = evaluation
            return evaluation

        if spec.extract_path:
            try:
                data_obj = extract_data(data_obj, spec.extract_path)
            except ValueError:
                # Extract mismatch should not crash verification. Compare the full body fingerprint instead.
                pass

        try:
            data_obj = _validate_json_value(data_obj)
        except Exception as e:  # boundary: unexpected extract output
            evaluation = (False, outcome.http_status, 0.0, f"extracted_not_json: {e}")
            self._cache[sig] = evaluation
            return evaluation

        current_fp = fingerprint(data_obj, max_depth=max_depth)
        similarity = fingerprint_similarity(baseline_fp, current_fp)
        evaluation = (similarity >= self._config.similarity_threshold, outcome.http_status, similarity, None)
        self._cache[sig] = evaluation
        return evaluation

    async def verify(
        self,
        minimization: MinimizationResult,
        *,
        parameter_sets: list[RecipeRequestSpec] | None = None,
    ) -> VerificationReport:
        baseline = minimization.baseline
        baseline_fp = _baseline_fingerprint(baseline)
        max_depth = baseline.max_depth if baseline.max_depth >= 0 else DEFAULT_MAX_DEPTH

        attempts: list[VerificationAttempt] = []
        notes: list[str] = []

        primary = minimization.minimized_request
        parameterized = request_has_placeholders(primary)

        concrete_sets: list[RecipeRequestSpec]
        if parameter_sets is None:
            concrete_sets = [primary]
        else:
            concrete_sets = list(parameter_sets)

        # Promotion rules:
        # - no placeholders: require N consecutive successes on the primary spec
        # - placeholders: require >=2 distinct concrete specs, one successful attempt per set
        if parameterized:
            # If the minimized request is a template, we need concrete instantiations to replay.
            distinct_sigs = {_request_signature(spec) for spec in concrete_sets if not request_has_placeholders(spec)}
            replay_sets = [spec for spec in concrete_sets if not request_has_placeholders(spec)]

            if len(distinct_sigs) < 2:
                notes.append("error_code=NEEDS_SECOND_EXAMPLE_FOR_VERIFY")
            if not replay_sets:
                return VerificationReport(
                    schema_hash=VerificationReport.schema_hash_value(),
                    minimization=minimization,
                    status=VerificationStatus.PARTIAL,
                    attempts=[],
                    notes="; ".join(notes) if notes else "missing concrete parameter sets",
                )

            all_ok = True
            for spec in replay_sets:
                ok, status, similarity, error = await self._evaluate(spec, baseline_fp=baseline_fp, max_depth=max_depth)
                attempts.append(
                    VerificationAttempt(
                        timestamp=_now_utc(),
                        ok=ok,
                        http_status=status if status != 0 else None,
                        similarity=similarity,
                        error=error,
                        output_excerpt="",
                    )
                )
                if not ok:
                    all_ok = False
                    break

            if all_ok and len(distinct_sigs) >= 2 and not notes:
                status = VerificationStatus.PASSED
            elif all_ok:
                status = VerificationStatus.PARTIAL
            else:
                status = VerificationStatus.FAILED

            return VerificationReport(
                schema_hash=VerificationReport.schema_hash_value(),
                minimization=minimization,
                status=status,
                attempts=attempts,
                notes="; ".join(notes),
            )

        consecutive_ok = 0
        while consecutive_ok < self._config.required_consecutive_successes and not self._budget_exhausted():
            ok, http_status, similarity, error = await self._evaluate(primary, baseline_fp=baseline_fp, max_depth=max_depth)
            attempts.append(
                VerificationAttempt(
                    timestamp=_now_utc(),
                    ok=ok,
                    http_status=http_status if http_status != 0 else None,
                    similarity=similarity,
                    error=error,
                    output_excerpt="",
                )
            )
            if ok:
                consecutive_ok += 1
            else:
                consecutive_ok = 0

        if consecutive_ok >= self._config.required_consecutive_successes:
            final_status = VerificationStatus.PASSED
        else:
            final_status = VerificationStatus.FAILED
            if self._budget_exhausted():
                notes.append("budget exhausted before reaching consecutive success threshold")

        return VerificationReport(
            schema_hash=VerificationReport.schema_hash_value(),
            minimization=minimization,
            status=final_status,
            attempts=attempts,
            notes="; ".join(notes),
        )
