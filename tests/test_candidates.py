"""Unit tests for recipes.candidates."""

from __future__ import annotations

from datetime import datetime

import pytest

from mcp_server_browser_use.recipes.candidates import rank_candidates
from mcp_server_browser_use.recipes.models import NetworkRequest, NetworkResponse, SessionRecording


def test_rank_candidates_prefers_search_api_over_analytics() -> None:
    nav_url = "https://example.com/jobs"

    search_req = NetworkRequest(
        url="https://api.example.com/search?q=python+jobs&limit=20",
        method="GET",
        resource_type="xhr",
        timestamp=2.0,
        request_id="r1",
        initiator_url=nav_url,
    )
    search_body = '{"results":[{"title":"Python Engineer","company":"Acme"},{"title":"Backend Developer","company":"Beta"}],"count":2}'
    search_resp = NetworkResponse(
        url=search_req.url,
        status=200,
        headers={"Content-Length": str(len(search_body))},
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

    telemetry_req = NetworkRequest(
        url="https://api.example.com/telemetry/events?ts=1700",
        method="POST",
        resource_type="xhr",
        timestamp=2.3,
        request_id="r3",
        initiator_url=nav_url,
    )
    telemetry_body = '{"ok":true}'
    telemetry_resp = NetworkResponse(
        url=telemetry_req.url,
        status=200,
        headers={"Content-Length": str(len(telemetry_body))},
        body=telemetry_body,
        mime_type="application/json",
        timestamp=2.35,
        request_id="r3",
        content_type="application/json",
        byte_length=len(telemetry_body),
    )

    recording = SessionRecording(
        task="Find python jobs",
        result="Found jobs matching python query",
        requests=[search_req, analytics_req, telemetry_req],
        responses=[search_resp, analytics_resp, telemetry_resp],
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 2),
    )

    ranked = rank_candidates(recording, top_k=3)
    assert len(ranked) == 3

    top = ranked[0]
    assert "/search" in top.signal.url
    assert "api.example.com" in top.signal.url

    # Telemetry/tracker-ish endpoints should not beat the search API.
    worst = ranked[-1]
    assert "google-analytics.com" in worst.signal.url or "/telemetry/" in worst.signal.url


def test_rank_candidates_caps_top_k_and_is_deterministic() -> None:
    nav_url = "https://example.com/page"
    reqs: list[NetworkRequest] = []
    resps: list[NetworkResponse] = []
    for i in range(20):
        url = f"https://api.example.com/items?q=python&offset={i}"
        reqs.append(
            NetworkRequest(
                url=url,
                method="GET",
                resource_type="xhr",
                timestamp=10.0 + i,
                request_id=f"r{i}",
                initiator_url=nav_url,
            )
        )
        body = f'{{"items":[{{"id":1,"name":"python"}}],"offset":{i}}}'
        resps.append(
            NetworkResponse(
                url=url,
                status=200,
                headers={"Content-Length": str(len(body))},
                body=body,
                mime_type="application/json",
                timestamp=10.1 + i,
                request_id=f"r{i}",
                content_type="application/json",
                byte_length=len(body),
            )
        )

    recording = SessionRecording(
        task="python items",
        result="items",
        requests=reqs,
        responses=resps,
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 3),
    )

    a = rank_candidates(recording, top_k=8)
    b = rank_candidates(recording, top_k=8)
    assert len(a) == 8
    assert [c.signal.url for c in a] == [c.signal.url for c in b]
    assert [c.score for c in a] == [c.score for c in b]


def test_rank_candidates_cache_buster_penalty_pushes_down() -> None:
    nav_url = "https://example.com/page"
    good_url = "https://api.example.com/search?q=python"
    bad_url = "https://api.example.com/search?q=python&_t=123456"

    good_req = NetworkRequest(
        url=good_url,
        method="GET",
        resource_type="xhr",
        timestamp=9.0,
        request_id="good",
        initiator_url=nav_url,
    )
    bad_req = NetworkRequest(
        url=bad_url,
        method="GET",
        resource_type="xhr",
        timestamp=9.0,
        request_id="bad",
        initiator_url=nav_url,
    )

    body = '{"results":[{"title":"Python"}],"count":1}'
    good_resp = NetworkResponse(
        url=good_url,
        status=200,
        headers={"Content-Length": str(len(body))},
        body=body,
        mime_type="application/json",
        timestamp=10.0,
        request_id="good",
        content_type="application/json",
        byte_length=len(body),
    )
    bad_resp = NetworkResponse(
        url=bad_url,
        status=200,
        headers={"Content-Length": str(len(body))},
        body=body,
        mime_type="application/json",
        timestamp=10.0,
        request_id="bad",
        content_type="application/json",
        byte_length=len(body),
    )

    recording = SessionRecording(
        task="python search",
        result="python",
        requests=[bad_req, good_req],
        responses=[bad_resp, good_resp],
        navigation_urls=[nav_url],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 0, 1),
    )

    ranked = rank_candidates(recording, top_k=2)
    assert len(ranked) == 2
    assert ranked[0].signal.url.startswith(good_url)
    assert ranked[1].signal.url.startswith(bad_url)


def test_rank_candidates_requires_positive_top_k() -> None:
    recording = SessionRecording(
        task="t",
        result="r",
        requests=[],
        responses=[],
        navigation_urls=[],
        start_time=datetime(2026, 1, 1, 0, 0, 0),
        end_time=None,
    )
    with pytest.raises(ValueError):
        rank_candidates(recording, top_k=0)
