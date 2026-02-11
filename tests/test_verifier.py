from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from mcp_server_browser_use.recipes.artifacts.models import (
    AnalysisResult,
    BaselineFingerprint,
    CandidateSet,
    MinimizationResult,
    RecipeRequestSpec,
    SessionRecording,
    SignalSet,
    ValidationResult,
)
from mcp_server_browser_use.recipes.fingerprint import TypedJsonPath, fingerprint
from mcp_server_browser_use.recipes.verifier import RecipeVerifier, ReplayOutcome, VerifierConfig


def _validate_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_validate_json_value(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("JSON object keys must be strings")
            out[k] = _validate_json_value(v)
        return out
    raise ValueError(f"Unsupported JSON value type: {type(value)!r}")


def _fingerprint_entries(fp: frozenset[TypedJsonPath]) -> list[dict[str, object]]:
    return [{"path": tp.path, "value_type": tp.value_type.value} for tp in sorted(fp, key=lambda x: (x.path, x.value_type.value))]


def _make_baseline(*, request_spec: dict[str, object], entries: list[dict[str, object]], max_depth: int = 6) -> BaselineFingerprint:
    recording = SessionRecording(
        task="t",
        result="r",
        requests=[],
        responses=[],
        navigation_urls=["https://example.com"],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )
    signals = SignalSet(
        recording=recording,
        signals=[
            {
                "url": str(request_spec["url"]),
                "method": str(request_spec.get("method", "GET")),
                "status": 200,
                "content_type": "application/json",
                "response_size_bytes": 123,
                "structural_summary": "object(keys=items)",
                "duration_ms": 1.0,
                "request_timestamp": 1.0,
                "response_timestamp": 1.1,
                "initiator_page_url": "https://example.com",
                "resource_type": "xhr",
            }
        ],
    )
    candidates = CandidateSet(
        signals=signals,
        candidates=[
            {
                "rank": 1,
                "score": 0.9,
                "notes": "test",
                "signal": signals.signals[0],
            }
        ],
    )
    analysis = AnalysisResult(
        candidates=candidates,
        selected_rank=1,
        request_spec=request_spec,
        recipe_name_suggestion="test",
        raw_llm_output="{}",
    )
    validation = ValidationResult(analysis=analysis, ok=True, errors=[], warnings=[])
    return BaselineFingerprint(validation=validation, max_depth=max_depth, entries=entries, sample_count=1)


@dataclass(frozen=True, slots=True)
class _Server:
    base_url: str
    httpd: ThreadingHTTPServer
    thread: threading.Thread


@pytest.fixture
def local_api_server() -> Iterator[_Server]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/search":
                self.send_response(404)
                self.end_headers()
                return

            qs = parse_qs(parsed.query, keep_blank_values=True)
            q = (qs.get("q") or [""])[0]
            payload = {"items": [{"id": 1, "q": q}], "meta": {"count": 1}}
            body = json.dumps(payload).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        yield _Server(base_url=f"http://127.0.0.1:{port}", httpd=httpd, thread=thread)
    finally:
        httpd.shutdown()
        httpd.server_close()


async def _replay_httpx(spec: RecipeRequestSpec) -> ReplayOutcome:
    async with httpx.AsyncClient(timeout=2.0) as client:
        resp = await client.get(spec.url, headers=spec.headers)
        return ReplayOutcome(http_status=resp.status_code, body_text=resp.text, error=None)


@pytest.mark.asyncio
async def test_verifier_promotes_non_parameterized_with_two_consecutive_successes(local_api_server: _Server) -> None:
    url = f"{local_api_server.base_url}/search?q=hello"
    request_spec = {
        "url": url,
        "method": "GET",
        "headers": {"Accept": "application/json"},
        "response_type": "json",
        "extract_path": None,
        "allowed_domains": [],
    }

    baseline_spec_opt = _make_baseline(request_spec=request_spec, entries=[]).validation.analysis.request_spec
    assert baseline_spec_opt is not None
    baseline_spec: RecipeRequestSpec = baseline_spec_opt
    baseline_resp = await _replay_httpx(baseline_spec)
    baseline_json = _validate_json_value(json.loads(baseline_resp.body_text))
    baseline_fp = fingerprint(baseline_json, max_depth=6)
    baseline = _make_baseline(request_spec=request_spec, entries=_fingerprint_entries(baseline_fp), max_depth=6)

    original = baseline.validation.analysis.request_spec
    assert original is not None
    minimization = MinimizationResult(
        baseline=baseline,
        original_request=original,
        minimized_request=original,
        steps=[],
        notes="",
    )

    verifier = RecipeVerifier(_replay_httpx, config=VerifierConfig(required_consecutive_successes=2, max_attempts=4, pacing_ms=0))
    report = await verifier.verify(minimization)

    assert report.status == "passed"
    assert len(report.attempts) == 2
    assert all(a.ok for a in report.attempts)


@pytest.mark.asyncio
async def test_verifier_parameterized_requires_two_distinct_sets(local_api_server: _Server) -> None:
    template_spec = RecipeRequestSpec(
        url=f"{local_api_server.base_url}/search?q={{q}}",
        method="GET",
        headers={"Accept": "application/json"},
        response_type="json",
        extract_path=None,
        allowed_domains=[],
    )
    concrete_a = template_spec.model_copy(update={"url": f"{local_api_server.base_url}/search?q=hello"})

    baseline_resp = await _replay_httpx(concrete_a)
    baseline_json = _validate_json_value(json.loads(baseline_resp.body_text))
    baseline_fp = fingerprint(baseline_json, max_depth=6)

    baseline = _make_baseline(
        request_spec={
            "url": template_spec.url,
            "method": "GET",
            "headers": {"Accept": "application/json"},
            "response_type": "json",
            "extract_path": None,
            "allowed_domains": [],
        },
        entries=_fingerprint_entries(baseline_fp),
        max_depth=6,
    )

    minimization = MinimizationResult(
        baseline=baseline,
        original_request=template_spec,
        minimized_request=template_spec,
        steps=[],
        notes="",
    )

    verifier = RecipeVerifier(_replay_httpx, config=VerifierConfig(max_attempts=4, pacing_ms=0))
    report = await verifier.verify(minimization, parameter_sets=[concrete_a])

    assert report.status == "partial"
    assert "NEEDS_SECOND_EXAMPLE_FOR_VERIFY" in report.notes
    assert len(report.attempts) == 1
    assert report.attempts[0].ok


@pytest.mark.asyncio
async def test_verifier_parameterized_passes_with_two_distinct_sets(local_api_server: _Server) -> None:
    template_spec = RecipeRequestSpec(
        url=f"{local_api_server.base_url}/search?q={{q}}",
        method="GET",
        headers={"Accept": "application/json"},
        response_type="json",
        extract_path=None,
        allowed_domains=[],
    )
    concrete_a = template_spec.model_copy(update={"url": f"{local_api_server.base_url}/search?q=hello"})
    concrete_b = template_spec.model_copy(update={"url": f"{local_api_server.base_url}/search?q=world"})

    baseline_resp = await _replay_httpx(concrete_a)
    baseline_json = _validate_json_value(json.loads(baseline_resp.body_text))
    baseline_fp = fingerprint(baseline_json, max_depth=6)

    baseline = _make_baseline(
        request_spec={
            "url": template_spec.url,
            "method": "GET",
            "headers": {"Accept": "application/json"},
            "response_type": "json",
            "extract_path": None,
            "allowed_domains": [],
        },
        entries=_fingerprint_entries(baseline_fp),
        max_depth=6,
    )

    minimization = MinimizationResult(
        baseline=baseline,
        original_request=template_spec,
        minimized_request=template_spec,
        steps=[],
        notes="",
    )

    verifier = RecipeVerifier(_replay_httpx, config=VerifierConfig(max_attempts=4, pacing_ms=0))
    report = await verifier.verify(minimization, parameter_sets=[concrete_a, concrete_b])

    assert report.status == "passed"
    assert len(report.attempts) == 2
    assert all(a.ok for a in report.attempts)


@pytest.mark.asyncio
async def test_verifier_fails_on_non_2xx(local_api_server: _Server) -> None:
    url = f"{local_api_server.base_url}/nope"
    request_spec = {
        "url": url,
        "method": "GET",
        "headers": {},
        "response_type": "json",
        "extract_path": None,
        "allowed_domains": [],
    }

    baseline = _make_baseline(request_spec=request_spec, entries=[], max_depth=6)
    original = baseline.validation.analysis.request_spec
    assert original is not None
    minimization = MinimizationResult(
        baseline=baseline,
        original_request=original,
        minimized_request=original,
        steps=[],
        notes="",
    )

    verifier = RecipeVerifier(_replay_httpx, config=VerifierConfig(required_consecutive_successes=2, max_attempts=2, pacing_ms=0))
    report = await verifier.verify(minimization)

    assert report.status == "failed"
    assert report.attempts
