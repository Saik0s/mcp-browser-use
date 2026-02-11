"""Unit tests for recipes.heuristic_analyzer."""

from __future__ import annotations

from datetime import datetime

from mcp_server_browser_use.recipes.candidates import rank_candidates
from mcp_server_browser_use.recipes.heuristic_analyzer import (
    try_build_heuristic_draft,
    try_build_heuristic_draft_from_candidates,
)
from mcp_server_browser_use.recipes.models import NetworkRequest, NetworkResponse, SessionRecording


def test_heuristic_analyzer_builds_minimal_get_json_recipe() -> None:
    nav_url = "https://example.com/jobs"
    api_url = "https://api.example.com/search?q=python+jobs&limit=20"

    search_req = NetworkRequest(
        url=api_url,
        method="GET",
        resource_type="xhr",
        timestamp=2.0,
        request_id="r1",
        initiator_url=nav_url,
    )
    # Ensure response body size is comfortably above the heuristic minimum.
    search_body = '{"results":[' + ",".join([f'{{"title":"Python Engineer {i}","company":"Acme","id":{i}}}' for i in range(25)]) + '],"count":25}'
    search_resp = NetworkResponse(
        url=api_url,
        status=200,
        headers={"Content-Length": str(len(search_body)), "Content-Type": "application/json"},
        body=search_body,
        mime_type="application/json",
        timestamp=2.2,
        request_id="r1",
        content_type="application/json",
        byte_length=len(search_body),
    )

    analytics_req = NetworkRequest(
        url="https://www.google-analytics.com/collect?v=1&t=event&tid=UA-123&cid=abc",
        method="POST",
        resource_type="fetch",
        timestamp=2.1,
        request_id="r2",
        initiator_url=nav_url,
    )
    analytics_resp = NetworkResponse(
        url=analytics_req.url,
        status=204,
        headers={"Content-Length": "0", "Content-Type": "image/gif"},
        body=None,
        mime_type="image/gif",
        timestamp=2.15,
        request_id="r2",
        content_type="image/gif",
        byte_length=0,
    )

    recording = SessionRecording(
        task="Find python jobs",
        result="Found jobs matching python query",
        requests=[search_req, analytics_req],
        responses=[search_resp, analytics_resp],
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 2),
    )

    draft = try_build_heuristic_draft(recording)
    assert draft is not None
    recipe = draft.recipe
    assert recipe.request is not None
    assert recipe.request.method == "GET"
    assert recipe.request.response_type == "json"
    assert recipe.request.allowed_domains == ["api.example.com"]

    merged = recipe.merge_params({})
    built_url = recipe.request.build_url(merged)
    assert built_url.startswith("https://api.example.com/search?")
    assert "q=python+jobs" in built_url

    assert len(recipe.parameters) == 1
    assert recipe.parameters[0].name == "query"
    assert recipe.parameters[0].default == "python jobs"


def test_heuristic_analyzer_requires_score_gap() -> None:
    nav_url = "https://example.com/page"
    url = "https://api.example.com/search?q=python"

    # Two identical "good" calls, gap should be ~0 (ties).
    req1 = NetworkRequest(url=url, method="GET", resource_type="xhr", timestamp=1.0, request_id="r1", initiator_url=nav_url)
    req2 = NetworkRequest(url=url, method="GET", resource_type="xhr", timestamp=1.1, request_id="r2", initiator_url=nav_url)

    body = '{"results":[' + ",".join([f'{{"id":{i},"name":"python"}}' for i in range(40)]) + "]}"
    resp1 = NetworkResponse(
        url=url,
        status=200,
        headers={"Content-Length": str(len(body)), "Content-Type": "application/json"},
        body=body,
        mime_type="application/json",
        timestamp=1.2,
        request_id="r1",
        content_type="application/json",
        byte_length=len(body),
    )
    resp2 = NetworkResponse(
        url=url,
        status=200,
        headers={"Content-Length": str(len(body)), "Content-Type": "application/json"},
        body=body,
        mime_type="application/json",
        timestamp=1.3,
        request_id="r2",
        content_type="application/json",
        byte_length=len(body),
    )

    recording = SessionRecording(
        task="python search",
        result="python",
        requests=[req1, req2],
        responses=[resp1, resp2],
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 1),
    )

    candidates = rank_candidates(recording, top_k=2)
    assert len(candidates) == 2
    draft = try_build_heuristic_draft_from_candidates(recording, candidates=candidates)
    assert draft is None


def test_heuristic_analyzer_drops_sensitive_query_params() -> None:
    nav_url = "https://example.com/page"
    url = "https://api.example.com/search?q=python&access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.bad.bad"

    req = NetworkRequest(url=url, method="GET", resource_type="xhr", timestamp=5.0, request_id="r1", initiator_url=nav_url)
    body = '{"results":[' + ",".join([f'{{"id":{i},"name":"python"}}' for i in range(50)]) + "]}"
    resp = NetworkResponse(
        url=url,
        status=200,
        headers={"Content-Length": str(len(body)), "Content-Type": "application/json"},
        body=body,
        mime_type="application/json",
        timestamp=5.2,
        request_id="r1",
        content_type="application/json",
        byte_length=len(body),
    )

    recording = SessionRecording(
        task="python search",
        result="python",
        requests=[req],
        responses=[resp],
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 1),
    )

    draft = try_build_heuristic_draft(recording, min_gap=0.0)
    assert draft is not None
    assert draft.recipe.request is not None
    assert "access_token" not in draft.recipe.request.url
