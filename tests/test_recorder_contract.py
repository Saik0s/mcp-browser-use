from collections.abc import Callable, Mapping

import pytest

from mcp_server_browser_use.recipes.recorder import MAX_BODY_SIZE, RecipeRecorder


class _DummyNetworkRegister:
    def __init__(self) -> None:
        self.request_will_be_sent: Callable[[Mapping[str, object], str | None], None] | None = None
        self.response_received: Callable[[Mapping[str, object], str | None], None] | None = None
        self.loading_failed: Callable[[Mapping[str, object], str | None], None] | None = None
        self.loading_finished: Callable[[Mapping[str, object], str | None], None] | None = None

    def requestWillBeSent(self, cb: Callable[[Mapping[str, object], str | None], None]) -> None:
        self.request_will_be_sent = cb

    def responseReceived(self, cb: Callable[[Mapping[str, object], str | None], None]) -> None:
        self.response_received = cb

    def loadingFailed(self, cb: Callable[[Mapping[str, object], str | None], None]) -> None:
        self.loading_failed = cb

    def loadingFinished(self, cb: Callable[[Mapping[str, object], str | None], None]) -> None:
        self.loading_finished = cb


class _DummyRegister:
    def __init__(self) -> None:
        self.Network = _DummyNetworkRegister()


class _DummyNetworkSender:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result

    async def enable(self) -> dict[str, object]:
        return {}

    async def getResponseBody(self, *, params: dict[str, str], session_id: str | None = None) -> dict[str, object]:
        _ = params
        _ = session_id
        return self._result


class _DummySender:
    def __init__(self, result: dict[str, object]) -> None:
        self.Network = _DummyNetworkSender(result)


class _DummyCDPClient:
    def __init__(self, result: dict[str, object]) -> None:
        self.register = _DummyRegister()
        self.send = _DummySender(result)


class _DummyBrowserSession:
    def __init__(self, result: dict[str, object]) -> None:
        self.cdp_client = _DummyCDPClient(result)


@pytest.mark.asyncio
async def test_recorder_contract_captures_required_fields_for_json_api() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": '{"a":1,"b":{"c":2},"items":[{"id":1,"name":"x"}]}', "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {
            "requestId": "1",
            "type": "XHR",
            "documentURL": "https://example.com/page",
            "request": {"url": "https://api.example.com/v1/search?q=x", "method": "GET", "headers": {}},
        },
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {
                "url": "https://api.example.com/v1/search?q=x",
                "status": 200,
                "headers": {"Content-Type": "application/json; charset=utf-8"},
                "mimeType": "application/json",
            },
        },
        session_id=None,
    )
    recorder._on_loading_finished({"requestId": "1", "encodedDataLength": 1234}, session_id=None)

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")

    assert len(recording.requests) == 1
    assert len(recording.responses) == 1

    req = recording.requests[0]
    resp = recording.responses[0]

    assert req.initiator_url == "https://example.com/page"
    assert req.resource_type == "xhr"

    assert resp.status == 200
    assert resp.content_type is not None
    assert "application/json" in resp.content_type
    assert resp.byte_length == 1234

    assert resp.json_key_sample is not None
    assert len(resp.json_key_sample) <= 200
    assert "a" in resp.json_key_sample

    assert resp.ttfb_ms is not None
    assert resp.ttfb_ms >= 0.0
    assert resp.total_ms is not None
    assert resp.total_ms >= 0.0


@pytest.mark.asyncio
async def test_recorder_body_cap_32kb() -> None:
    recorder = RecipeRecorder(task="t")

    huge_value = "a" * (MAX_BODY_SIZE + 10_000)
    await recorder.attach(_DummyBrowserSession({"body": '{"k":"' + huge_value + '"}', "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {
            "requestId": "1",
            "type": "Fetch",
            "documentURL": "https://example.com/page",
            "request": {"url": "https://x", "method": "GET", "headers": {}},
        },
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "Fetch",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]

    assert resp.body is not None
    assert len(resp.body.encode("utf-8", errors="replace")) <= MAX_BODY_SIZE
    assert resp.json_key_sample is not None
    assert resp.json_key_sample.startswith("k")


@pytest.mark.asyncio
async def test_recorder_body_cap_32kb_is_bytes_not_chars() -> None:
    recorder = RecipeRecorder(task="t")

    # "€" is a 3-byte UTF-8 sequence, this ensures byte-length capping is exercised.
    huge_value = "€" * (MAX_BODY_SIZE + 10_000)
    await recorder.attach(_DummyBrowserSession({"body": '{"k":"' + huge_value + '"}', "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {
            "requestId": "1",
            "type": "Fetch",
            "documentURL": "https://example.com/page",
            "request": {"url": "https://x", "method": "GET", "headers": {}},
        },
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "Fetch",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]

    assert resp.body is not None
    assert len(resp.body.encode("utf-8", errors="replace")) <= MAX_BODY_SIZE
    assert resp.json_key_sample is not None
    assert resp.json_key_sample.startswith("k")


@pytest.mark.asyncio
async def test_recorder_does_not_persist_html_even_if_mime_is_json() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": "<!doctype html><html><body>nope</body></html>", "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {"requestId": "1", "type": "XHR", "documentURL": "https://example.com/page", "request": {"url": "https://x", "method": "GET", "headers": {}}},
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]
    assert resp.body is None
    assert resp.json_key_sample is None


@pytest.mark.asyncio
async def test_recorder_does_not_persist_html_detected_by_common_tag_prefix() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": "<div>nope</div>", "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {"requestId": "1", "type": "XHR", "documentURL": "https://example.com/page", "request": {"url": "https://x", "method": "GET", "headers": {}}},
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]
    assert resp.body is None
    assert resp.json_key_sample is None


@pytest.mark.asyncio
async def test_recorder_does_not_persist_base64_encoded_body() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": "AAECAwQ=", "base64Encoded": True}))

    recorder._on_request_will_be_sent(
        {"requestId": "1", "type": "XHR", "documentURL": "https://example.com/page", "request": {"url": "https://x", "method": "GET", "headers": {}}},
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]
    assert resp.body is None
    assert resp.json_key_sample is None


@pytest.mark.asyncio
async def test_recorder_capture_gate_uses_response_content_type_header() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": '{"a": 1}', "base64Encoded": False}))

    recorder._on_request_will_be_sent(
        {"requestId": "1", "type": "XHR", "documentURL": "https://example.com/page", "request": {"url": "https://x", "method": "GET", "headers": {}}},
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {"url": "https://x", "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "text/plain"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")
    resp = recording.responses[0]
    assert resp.body is not None
    assert resp.json_key_sample is not None


@pytest.mark.asyncio
async def test_recorder_sanitizes_url_and_redacts_post_data() -> None:
    recorder = RecipeRecorder(task="t")
    await recorder.attach(_DummyBrowserSession({"body": '{"ok": true}', "base64Encoded": False}))

    raw_url = "https://api.example.com/v1/search?q=x&access_token=supersecret"
    raw_post = '{"username":"u","password":"supersecret","token":"abc","nested":{"x":1}}'

    recorder._on_request_will_be_sent(
        {
            "requestId": "1",
            "type": "XHR",
            "documentURL": "https://example.com/page",
            "request": {"url": raw_url, "method": "POST", "headers": {"Content-Type": "application/json"}, "postData": raw_post},
        },
        session_id=None,
    )
    recorder._on_response_received(
        {
            "requestId": "1",
            "type": "XHR",
            "response": {"url": raw_url, "status": 200, "headers": {"Content-Type": "application/json"}, "mimeType": "application/json"},
        },
        session_id=None,
    )

    await recorder.finalize()
    recording = recorder.get_recording(result="ok")

    req = recording.requests[0]
    assert "access_token" in req.url
    assert "REDACTED" in req.url
    assert "supersecret" not in req.url

    assert req.post_data is not None
    assert req.post_data != raw_post
    assert "supersecret" not in req.post_data
    assert "password" not in req.post_data.lower()
    assert len(req.post_data.encode("utf-8", errors="replace")) <= 1024
