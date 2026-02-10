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
from mcp_server_browser_use.recipes.minimizer import MinimizerConfig, RecipeRequestMinimizer, ReplayOutcome


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
            q = (qs.get("q") or [None])[0]
            accept = self.headers.get("Accept", "")
            xrw = self.headers.get("X-Requested-With", "")

            if accept != "application/json" or xrw != "XMLHttpRequest":
                payload = {"error": "missing_required_headers"}
            elif not q:
                payload = {"error": "missing_q"}
            else:
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


@pytest.mark.asyncio
async def test_minimizer_drops_noise_and_irrelevant_params(local_api_server: _Server) -> None:
    url = f"{local_api_server.base_url}/search?q=hello&ts=1700000000&debug=1&_t=1"
    request_spec = {
        "url": url,
        "method": "GET",
        "headers": {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Extra": "1",
            "If-None-Match": "abc",
            "Sec-Fetch-Site": "same-origin",
        },
        "response_type": "json",
        "extract_path": None,
        "allowed_domains": [],
    }

    async def replay(spec) -> ReplayOutcome:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(spec.url, headers=spec.headers)
            return ReplayOutcome(http_status=resp.status_code, body_text=resp.text, error=None)

    # Baseline fingerprint from the expected successful response.
    baseline_spec_opt = _make_baseline(request_spec=request_spec, entries=[]).validation.analysis.request_spec
    assert baseline_spec_opt is not None
    baseline_spec: RecipeRequestSpec = baseline_spec_opt
    baseline_resp = await replay(baseline_spec)
    baseline_json = _validate_json_value(json.loads(baseline_resp.body_text))
    baseline_fp = fingerprint(baseline_json, max_depth=6)
    baseline = _make_baseline(request_spec=request_spec, entries=_fingerprint_entries(baseline_fp), max_depth=6)

    minimizer = RecipeRequestMinimizer(replay, config=MinimizerConfig(max_attempts=32, max_wall_seconds=10.0, pacing_ms=0))
    request_model = baseline.validation.analysis.request_spec
    assert request_model is not None
    result = await minimizer.minimize(baseline=baseline, request=request_model)
    assert isinstance(result, MinimizationResult)

    minimized = result.minimized_request
    parsed = urlparse(minimized.url)
    qs = parse_qs(parsed.query, keep_blank_values=True)

    assert "q" in qs
    assert "ts" not in qs
    assert "_t" not in qs
    assert "debug" not in qs

    # Must keep required headers.
    assert minimized.headers.get("Accept") == "application/json"
    assert minimized.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Should remove noise header and an irrelevant extra header.
    assert "If-None-Match" not in minimized.headers
    assert "Sec-Fetch-Site" not in minimized.headers
    assert "X-Extra" not in minimized.headers


@pytest.mark.asyncio
async def test_minimizer_respects_attempt_budget(local_api_server: _Server) -> None:
    url = f"{local_api_server.base_url}/search?q=hello&debug=1"
    request_spec = {
        "url": url,
        "method": "GET",
        "headers": {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "A-Remove-1": "1",
            "A-Remove-2": "2",
            "A-Remove-3": "3",
        },
        "response_type": "json",
        "extract_path": None,
        "allowed_domains": [],
    }

    call_count = 0

    async def replay(spec) -> ReplayOutcome:
        nonlocal call_count
        call_count += 1
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(spec.url, headers=spec.headers)
            return ReplayOutcome(http_status=resp.status_code, body_text=resp.text, error=None)

    baseline_spec_opt = _make_baseline(request_spec=request_spec, entries=[]).validation.analysis.request_spec
    assert baseline_spec_opt is not None
    baseline_spec: RecipeRequestSpec = baseline_spec_opt
    baseline_resp = await replay(baseline_spec)
    baseline_json = _validate_json_value(json.loads(baseline_resp.body_text))
    baseline_fp = fingerprint(baseline_json, max_depth=6)
    baseline = _make_baseline(request_spec=request_spec, entries=_fingerprint_entries(baseline_fp), max_depth=6)

    call_count = 0
    minimizer = RecipeRequestMinimizer(replay, config=MinimizerConfig(max_attempts=1, max_wall_seconds=10.0, pacing_ms=0))
    request_model = baseline.validation.analysis.request_spec
    assert request_model is not None
    result = await minimizer.minimize(baseline=baseline, request=request_model)

    assert call_count == 1
    assert "budget" in result.notes.lower() or result.notes == ""
