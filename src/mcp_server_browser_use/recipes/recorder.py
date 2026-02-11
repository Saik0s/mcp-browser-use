"""Recipe recorder for capturing network events during agent execution.

The recorder captures all network traffic (especially XHR/Fetch API calls)
during a browser session so they can be analyzed to extract recipes.

Key design decisions (validated by GPT 5.2 Pro):
- Uses UUID for request IDs (not id(request) which can collide after GC)
- Works with browser-use's CDP-based architecture
- Tracks pending async tasks with finalize() for proper cleanup
- Redacts sensitive headers (cookies, auth tokens) for security
- Captures response bodies for JSON API calls

Note: browser-use uses CDP directly, not Playwright. This recorder integrates
with browser-use's CDP client for network event capture.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING

from .models import NetworkRequest, NetworkResponse, SessionRecording, is_sensitive_header_name

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from cdp_use.cdp.network.events import LoadingFailedEvent, LoadingFinishedEvent, RequestWillBeSentEvent, ResponseReceivedEvent

logger = logging.getLogger(__name__)

# Content types that indicate JSON API responses
JSON_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/graphql-response+json",
        "application/vnd.api+json",
        "text/json",
    }
)

# Maximum body size to capture and store (32KB).
#
# Contract:
# - MUST NOT capture >32KB response body
# - MUST NOT capture full HTML
# - MUST NOT capture raw binary
MAX_BODY_SIZE = 32 * 1024

# Timeout for body capture (5 seconds)
BODY_CAPTURE_TIMEOUT = 5.0


_JSON_KEY_RE = re.compile(r'"([^"]{1,200})"\s*:', re.MULTILINE)

_SENSITIVE_POST_KEYS = (
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "session",
    "csrf",
    "xsrf",
    "api_key",
    "apikey",
)

_MAX_POST_DATA_SUMMARY_BYTES = 1024

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "apikey",
        "api_key",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "csrf",
        "id_token",
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

_CONDITIONAL_SENSITIVE_QUERY_KEYS = frozenset({"code", "key"})

_JWT_PREFIX_RE = re.compile(r"^eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}$")
_LONG_BASE64ISH_RE = re.compile(r"^[a-zA-Z0-9+/=_-]{60,}$")
_LONG_BASE64URLISH_RE = re.compile(r"^[a-zA-Z0-9_-]{32,}={0,2}$")
_LONG_HEX_RE = re.compile(r"^[a-fA-F0-9]{32,}$")
_SLACK_TOKEN_RE = re.compile(r"^xox[a-z]-[0-9a-zA-Z-]{10,}$", flags=re.IGNORECASE)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", flags=re.IGNORECASE)


def _get_header_value(headers: dict[str, str], name: str) -> str | None:
    target = name.strip().lower()
    for k, v in headers.items():
        if k.strip().lower() == target:
            return v
    return None


def _looks_like_html(body: str) -> bool:
    # Intentionally blunt: any response body that *starts* with markup after leading whitespace
    # is treated as HTML-like and excluded from persistence (covers HTML, XML, comments, etc).
    #
    # Rationale: avoid brittle tag allowlists that can be bypassed by uncommon tags like <main>
    # or payloads like <!-- ... --> or <?xml ... ?>.
    #
    # Some endpoints send XSSI prefixes like `)]}',\n` before the actual payload. If the payload
    # is HTML, naive `<`-prefix checks are bypassed. Strip common XSSI prefixes before checking.
    if not body:
        return False

    def _strip_ws_and_bom(value: str) -> str:
        i = 0
        n = len(value)
        while i < n:
            ch = value[i]
            if ch.isspace() or ch == "\ufeff":
                i += 1
                continue
            return value[i:]
        return ""

    def _strip_one_xssi_prefix(value: str) -> str:
        # Keep this minimal and conservative: strip only known prefixes at the very start.
        prefixes = (")]}',", "while(1);", "for(;;);")
        for prefix in prefixes:
            if value.startswith(prefix):
                return _strip_ws_and_bom(value[len(prefix) :])
        return value

    s = _strip_ws_and_bom(body)
    while True:
        stripped = _strip_one_xssi_prefix(s)
        if stripped == s:
            break
        s = stripped

    return s.startswith("<")


def _truncate_utf8_bytes(value: str, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return value
    # Avoid creating invalid utf-8 sequences by decoding with ignore.
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def _normalize_content_type_token(value: str) -> str:
    # Example: "application/json; charset=utf-8" -> "application/json"
    return value.split(";", 1)[0].strip().lower()


def _truncate_str(value: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(value) <= max_len:
        return value
    return value[:max_len]


def _looks_like_secret_query_value(value: str) -> bool:
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    if _SLACK_TOKEN_RE.match(v):
        return True
    if _JWT_PREFIX_RE.match(v):
        return True
    if _LONG_HEX_RE.match(v):
        return True
    if _LONG_BASE64URLISH_RE.match(v):
        return True
    if _LONG_BASE64ISH_RE.match(v):
        return True
    return False


def _looks_like_code_or_key_secret(value: str) -> bool:
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    if v.isalpha() and len(v) <= 12:
        return False
    if _looks_like_secret_query_value(v):
        return True
    if _LONG_HEX_RE.match(v):
        return True
    return True


def _sanitize_netloc(netloc: str, *, hostname: str | None, port: int | None) -> str:
    # Strip userinfo deterministically. Prefer parsed hostname/port when available.
    if not netloc:
        return ""
    if "@" not in netloc:
        return netloc
    if not hostname:
        return netloc.rsplit("@", 1)[-1]

    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}" if port is not None else host


def _looks_like_path_secret(segment: str) -> bool:
    if not segment:
        return False
    s = segment.strip()
    if not s:
        return False
    if _UUID_RE.match(s):
        return True
    if _JWT_PREFIX_RE.match(s):
        return True
    if _LONG_HEX_RE.match(s):
        return True
    if len(s) >= 32 and _LONG_BASE64URLISH_RE.match(s):
        has_digit = any(ch.isdigit() for ch in s)
        has_sep = ("_" in s) or ("-" in s)
        return has_digit or has_sep
    if _LONG_BASE64ISH_RE.match(s):
        return True
    return False


def _redact_path_secrets(path: str) -> str:
    if not path:
        return ""
    from urllib.parse import unquote

    parts = path.split("/")
    if len(parts) > 200:
        parts = parts[:200]
    out: list[str] = []
    for seg in parts:
        decoded = unquote(seg)
        if _looks_like_path_secret(decoded):
            out.append("[REDACTED]")
        else:
            out.append(seg)
    return "/".join(out)


def _sanitize_recorded_url(url: str, *, max_len: int = 2048) -> str:
    """Sanitize recorded URLs to avoid persisting secrets in artifacts.

    - Drops fragment (`#...`).
    - Redacts userinfo (`user:pass@`) from netloc.
    - Redacts sensitive query values and obvious secret-like query values.
    - Redacts obviously token-like path segments.
    - Bounds output length.
    """
    if not url:
        return ""

    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    safe_netloc = _sanitize_netloc(parsed.netloc, hostname=parsed.hostname, port=parsed.port)
    safe_path = _redact_path_secrets(parsed.path)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    safe_items: list[tuple[str, str]] = []
    for key, value in query_items:
        key_l = key.lower()
        if key_l in _SENSITIVE_QUERY_KEYS:
            safe_items.append((key, "[REDACTED]"))
            continue
        if key_l in _CONDITIONAL_SENSITIVE_QUERY_KEYS and _looks_like_code_or_key_secret(value):
            safe_items.append((key, "[REDACTED]"))
            continue
        if _looks_like_secret_query_value(value):
            safe_items.append((key, "[REDACTED]"))
            continue
        safe_items.append((key, _truncate_str(value, 128)))

    safe_query = urlencode(safe_items, doseq=True, safe=":/@")
    safe_url = urlunparse((parsed.scheme, safe_netloc, safe_path, parsed.params, safe_query, ""))  # drop fragment

    return _truncate_str(safe_url, max_len)


def _is_jsonish_content_type(*, mime_type: str, content_type_header: str | None) -> bool:
    # Consider both CDP mimeType and response header Content-Type.
    tokens: list[str] = []
    if mime_type:
        tokens.append(_normalize_content_type_token(mime_type))
    if content_type_header:
        tokens.append(_normalize_content_type_token(content_type_header))

    for t in tokens:
        if not t:
            continue
        if t in JSON_CONTENT_TYPES:
            return True
        if t.endswith("+json"):
            return True
        if "json" in t:
            # Conservative: treat any json-ish token as JSON API.
            return True
    return False


_TEXT_CAPTURE_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
    }
)


def _is_text_capture_content_type(*, mime_type: str, content_type_header: str | None) -> bool:
    tokens: list[str] = []
    if mime_type:
        tokens.append(_normalize_content_type_token(mime_type))
    if content_type_header:
        tokens.append(_normalize_content_type_token(content_type_header))
    return any(token in _TEXT_CAPTURE_CONTENT_TYPES for token in tokens)


def _sanitize_post_key_name(key: str) -> str:
    kl = key.lower()
    for sub in _SENSITIVE_POST_KEYS:
        if sub in kl:
            return "[REDACTED_KEY]"
    # Keep it small and readable.
    return key[:64]


def _post_data_summary(post_data: str | None, *, content_type: str | None) -> str | None:
    # Contract: never persist raw post_data.
    if not post_data:
        return None

    from urllib.parse import parse_qsl

    ct = (content_type or "").lower()
    size_bytes = len(post_data.encode("utf-8", errors="replace"))

    def finish(summary: str) -> str:
        return _truncate_utf8_bytes(summary, max_bytes=_MAX_POST_DATA_SUMMARY_BYTES)

    # JSON bodies: keep only key structure.
    if "application/json" in ct or post_data.lstrip().startswith(("{", "[")):
        try:
            parsed: object = json.JSONDecoder().decode(post_data)
        except json.JSONDecodeError:
            return finish(f"json bytes={size_bytes} (parse_error)")

        if isinstance(parsed, dict):
            keys = sorted(_sanitize_post_key_name(str(k)) for k in parsed)
            keys = keys[:25]
            return finish(f"json bytes={size_bytes} keys={keys}")
        if isinstance(parsed, list):
            return finish(f"json bytes={size_bytes} kind=list len={len(parsed)}")
        return finish(f"json bytes={size_bytes} kind={type(parsed).__name__}")

    # Form bodies: keep keys only.
    if "application/x-www-form-urlencoded" in ct:
        items = parse_qsl(post_data, keep_blank_values=True)
        keys = sorted({_sanitize_post_key_name(k) for k, _ in items})
        keys = keys[:25]
        return finish(f"form bytes={size_bytes} keys={keys}")

    if "multipart/form-data" in ct:
        return finish(f"multipart bytes={size_bytes}")

    # Unknown: keep size only.
    return finish(f"bytes={size_bytes}")


def _json_key_sample(body: str, *, max_chars: int = 200) -> str | None:
    """Best-effort JSON key/path sample for analysis, capped to max_chars.

    Strategy:
    - Try json.loads and walk keys into dot paths (stable signal).
    - If that fails (partial/truncated/invalid JSON), fall back to regex `"key":` scanning.
    """

    def emit_paths(value: object, prefix: str, out: list[str], budget: int) -> None:
        if budget <= 0:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str):
                    continue
                path = f"{prefix}.{k}" if prefix else k
                out.append(path)
                if len(",".join(out)) >= budget:
                    return
                emit_paths(v, path, out, budget)
        elif isinstance(value, list):
            # Sample only first few entries to avoid blowups.
            for idx, item in enumerate(value[:3]):
                path = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
                emit_paths(item, path, out, budget)
                if len(",".join(out)) >= budget:
                    return

    try:
        parsed = json.JSONDecoder().decode(body)
        paths: list[str] = []
        emit_paths(parsed, "", paths, max_chars)
        if not paths:
            return None
        sample = ",".join(paths)
        return sample[:max_chars]
    except json.JSONDecodeError:
        keys: list[str] = []
        for m in _JSON_KEY_RE.finditer(body[:MAX_BODY_SIZE]):
            key = m.group(1)
            if key not in keys:
                keys.append(key)
            sample = ",".join(keys)
            if len(sample) >= max_chars:
                return sample[:max_chars]
        if not keys:
            return None
        return ",".join(keys)[:max_chars]


class RecipeRecorder:
    """Records browser session network events for recipe extraction.

    Works with browser-use's CDP-based architecture to capture network traffic.

    Usage:
        recorder = RecipeRecorder(task="Find jobs on Upwork")
        await recorder.attach(browser_session)  # Attach to browser-use session

        # ... agent executes ...

        await recorder.finalize()  # Wait for pending body captures
        recording = recorder.get_recording(result="Found 10 jobs")
    """

    def __init__(self, task: str, redact_headers: bool = True, max_concurrent_captures: int = 5):
        """Initialize recorder.

        Args:
            task: The task being executed (for recording metadata)
            redact_headers: Whether to redact sensitive headers (default: True)
            max_concurrent_captures: Max concurrent body capture tasks (default: 5)
        """
        self.task = task
        self.start_time = datetime.now()
        self.redact_headers = redact_headers

        # Storage for captured events
        self._requests: dict[str, NetworkRequest] = {}  # keyed by CDP requestId
        self._responses: list[NetworkResponse] = []
        self._navigation_urls: list[str] = []
        self._failed_requests: list[dict] = []  # Track failed requests

        # Mapping from CDP requestId to our stored data (for response body capture)
        self._cdp_to_response: dict[str, NetworkResponse] = {}

        # Async task tracking for body captures
        self._pending_tasks: set[asyncio.Task] = set()
        self._capture_semaphore = asyncio.Semaphore(max_concurrent_captures)

        # Browser session reference
        self._browser_session: BrowserSession | None = None
        self._attached = False

    def _redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive headers for security.

        Args:
            headers: Original headers dict

        Returns:
            Headers with sensitive values replaced by "[REDACTED]"
        """
        if not self.redact_headers:
            return headers

        result = {}
        for key, value in headers.items():
            if is_sensitive_header_name(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = value
        return result

    async def attach(self, browser_session: "BrowserSession") -> None:
        """Attach recorder to a browser-use BrowserSession.

        Registers CDP event handlers for network traffic capture.

        Args:
            browser_session: browser-use BrowserSession to record from
        """
        if self._attached:
            logger.warning("Recorder already attached")
            return

        self._browser_session = browser_session
        self._attached = True

        # Register CDP event handlers via browser-use's cdp_client
        cdp_client = browser_session.cdp_client

        # Register handlers for network events
        cdp_client.register.Network.requestWillBeSent(self._on_request_will_be_sent)
        cdp_client.register.Network.responseReceived(self._on_response_received)
        cdp_client.register.Network.loadingFailed(self._on_loading_failed)
        cdp_client.register.Network.loadingFinished(self._on_loading_finished)

        # Enable Network domain to receive events
        # Enable on browser-wide level (no session_id) to capture ALL network traffic
        try:
            await cdp_client.send.Network.enable()
            logger.debug("Network domain enabled browser-wide")
        except Exception as e:
            # If browser-wide fails, try with a session
            logger.debug(f"Browser-wide Network.enable failed: {e}, trying session-scoped")
            try:
                if hasattr(browser_session, "get_or_create_cdp_session"):
                    cdp_session = await browser_session.get_or_create_cdp_session(target_id=None, focus=False)
                    await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)
                    logger.debug(f"Network domain enabled for session: {cdp_session.session_id}")
            except Exception as e2:
                logger.warning(f"Failed to enable Network domain: {e2}")

        logger.info(f"RecipeRecorder attached via CDP for task: {self.task[:50]}...")

    def _on_request_will_be_sent(self, event: "RequestWillBeSentEvent", session_id: str | None) -> None:
        """Handle CDP Network.requestWillBeSent event.

        This is a synchronous callback.
        """
        logger.debug(f"[RECORDER] Network event received! session={session_id}")
        try:
            request_id = event.get("requestId", "")
            request_data = event.get("request", {})  # type: ignore[arg-type]

            # Extract headers (CDP Headers type is dict-like)
            raw_headers: dict[str, str] = dict(request_data.get("headers", {}))  # type: ignore[arg-type]

            # Determine resource type
            resource_type = event.get("type", "Other").lower()

            initiator_url: str | None = None
            document_url = event.get("documentURL")
            if isinstance(document_url, str) and document_url:
                initiator_url = document_url
            else:
                initiator = event.get("initiator", {})
                if isinstance(initiator, dict):
                    initiator_field = initiator.get("url")
                    if isinstance(initiator_field, str) and initiator_field:
                        initiator_url = initiator_field
            if not initiator_url and self._navigation_urls:
                initiator_url = self._navigation_urls[-1]

            raw_url = request_data.get("url", "")
            url = _sanitize_recorded_url(raw_url, max_len=2048) if isinstance(raw_url, str) else ""
            initiator_url_s = (
                _sanitize_recorded_url(initiator_url, max_len=2048) if isinstance(initiator_url, str) and initiator_url else initiator_url
            )

            post_data_raw = request_data.get("postData")
            post_data = _post_data_summary(
                post_data_raw if isinstance(post_data_raw, str) else None,
                content_type=_get_header_value(raw_headers, "content-type"),
            )

            # Capture request details
            network_request = NetworkRequest(
                url=url,
                method=request_data.get("method", "GET"),
                headers=self._redact_headers(raw_headers),
                post_data=post_data,
                resource_type=resource_type,
                timestamp=time.time(),
                request_id=request_id,
                initiator_url=initiator_url_s,
            )

            self._requests[request_id] = network_request

            # Track navigation (Document type)
            if resource_type == "document":
                self._navigation_urls.append(url)

            logger.debug(f"Recorded CDP request: {network_request.method} {network_request.url[:80]}...")

        except Exception as e:
            logger.debug(f"Error recording CDP request: {e}")

    def _on_response_received(self, event: "ResponseReceivedEvent", session_id: str | None) -> None:
        """Handle CDP Network.responseReceived event.

        This is a synchronous callback. Spawns async task for body capture.
        """
        try:
            request_id = event.get("requestId", "")
            response_data = event.get("response", {})  # type: ignore[arg-type]
            resource_type = event.get("type", "Other").lower()

            # Extract headers (CDP Headers type is dict-like)
            raw_headers: dict[str, str] = dict(response_data.get("headers", {}))  # type: ignore[arg-type]

            # Get content type
            mime_type_raw = response_data.get("mimeType", "")
            mime_type = mime_type_raw if isinstance(mime_type_raw, str) else ""
            content_type_header = _get_header_value(raw_headers, "content-type")
            content_type = content_type_header or mime_type
            is_jsonish = _is_jsonish_content_type(mime_type=mime_type, content_type_header=content_type_header)
            byte_length: int | None = None
            content_length = _get_header_value(raw_headers, "content-length")
            if isinstance(content_length, str) and content_length:
                try:
                    byte_length = int(content_length.strip())
                except Exception:
                    byte_length = None

            # Capture response details
            request_ts: float | None = None
            request_obj = self._requests.get(request_id)
            if request_obj is not None:
                request_ts = request_obj.timestamp

            now_ts = time.time()
            resp_url_raw = response_data.get("url", "")
            resp_url = _sanitize_recorded_url(resp_url_raw, max_len=2048) if isinstance(resp_url_raw, str) else ""
            network_response = NetworkResponse(
                url=resp_url,
                status=response_data.get("status", 0),
                headers=self._redact_headers(raw_headers),
                body=None,  # Body captured async if needed
                mime_type=mime_type,
                timestamp=now_ts,
                request_id=request_id,
                content_type=content_type,
                byte_length=byte_length,
                request_timestamp=request_ts,
                ttfb_ms=((now_ts - request_ts) * 1000.0) if request_ts is not None else None,
            )

            self._responses.append(network_response)
            self._cdp_to_response[request_id] = network_response

            # Schedule body capture for API calls (XHR/Fetch) and document loads used as APIs.
            # Contract: never persist raw binary, and never persist HTML bodies.
            should_consider = resource_type in ("xhr", "fetch", "document")
            is_text_capture = _is_text_capture_content_type(mime_type=mime_type, content_type_header=content_type_header)
            if should_consider and (is_jsonish or is_text_capture):
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._capture_body_cdp(request_id, network_response, session_id),
                )
                self._pending_tasks.add(task)
                task.add_done_callback(lambda t: self._pending_tasks.discard(t))

            logger.debug(f"Recorded CDP response: {network_response.status} {network_response.url[:80]}...")

        except Exception as e:
            logger.debug(f"Error recording CDP response: {e}")

    def _on_loading_failed(self, event: "LoadingFailedEvent", session_id: str | None) -> None:
        """Handle CDP Network.loadingFailed event."""
        try:
            request_id = event.get("requestId", "")
            error_text = event.get("errorText", "Unknown error")

            # Get original request info if available
            original_request = self._requests.get(request_id)

            failure_info = {
                "request_id": request_id,
                "url": original_request.url if original_request else "Unknown",
                "method": original_request.method if original_request else "Unknown",
                "resource_type": event.get("type", "Unknown"),
                "failure": error_text,
                "timestamp": time.time(),
            }
            self._failed_requests.append(failure_info)

            logger.debug(f"CDP request failed: {failure_info['url'][:80]} - {error_text}")

        except Exception as e:
            logger.debug(f"Error recording CDP loading failure: {e}")

    def _on_loading_finished(self, event: "LoadingFinishedEvent", session_id: str | None) -> None:
        """Handle CDP Network.loadingFinished event."""
        try:
            request_id = event.get("requestId", "")
            encoded_len = event.get("encodedDataLength")

            resp = self._cdp_to_response.get(request_id)
            if resp is None:
                return

            if isinstance(encoded_len, (int, float)):
                resp.byte_length = int(encoded_len)

            finished_ts = time.time()
            resp.loading_finished_timestamp = finished_ts
            if resp.request_timestamp is not None:
                resp.total_ms = (finished_ts - resp.request_timestamp) * 1000.0

        except Exception as e:
            logger.debug(f"Error recording CDP loading finished: {e}")

    async def _capture_body_cdp(self, request_id: str, network_response: NetworkResponse, session_id: str | None) -> None:
        """Capture response body via CDP Network.getResponseBody.

        Args:
            request_id: CDP request ID
            network_response: Our NetworkResponse to update with body
            session_id: CDP session ID (if any)
        """
        async with self._capture_semaphore:
            try:
                if not self._browser_session:
                    return

                # Use CDP to get response body
                result = await asyncio.wait_for(
                    self._browser_session.cdp_client.send.Network.getResponseBody(
                        params={"requestId": request_id},
                        session_id=session_id,
                    ),
                    timeout=BODY_CAPTURE_TIMEOUT,
                )

                body = result.get("body", "")
                if not isinstance(body, str):
                    body = str(body)

                # Handle base64 encoded bodies
                if result.get("base64Encoded", False):
                    # Contract: do not persist raw binary in recorder artifacts.
                    network_response.body = None
                    network_response.json_key_sample = None
                    return

                # Enforce storage caps in BYTES (strict, no marker suffix that might exceed MAX_BODY_SIZE).
                body = _truncate_utf8_bytes(body, max_bytes=MAX_BODY_SIZE)

                # Contract: never persist HTML bodies.
                if _looks_like_html(body):
                    network_response.body = None
                    network_response.json_key_sample = None
                    return

                network_response.body = body
                network_response.json_key_sample = _json_key_sample(body, max_chars=200)

            except TimeoutError:
                logger.debug(f"CDP body capture timed out for request {request_id[:8]}")
            except Exception as e:
                logger.debug(f"Error capturing CDP body: {e}")

    async def detach(self) -> None:
        """Detach recorder (cleanup)."""
        if not self._attached:
            return

        # Note: CDP handlers are registered globally on the client
        # They will be cleaned up when the browser session closes
        # We just mark ourselves as detached

        self._attached = False
        logger.debug("RecipeRecorder detached")

    async def finalize(self, timeout: float = 30.0) -> None:
        """Wait for all pending body capture tasks to complete.

        Call this before get_recording() to ensure all bodies are captured.

        Args:
            timeout: Maximum time to wait for pending tasks (default: 30s)
        """
        if not self._pending_tasks:
            return

        logger.debug(f"Finalizing: waiting for {len(self._pending_tasks)} pending body captures...")

        try:
            await asyncio.wait_for(
                asyncio.gather(*list(self._pending_tasks), return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(f"Finalize timed out after {timeout}s with {len(self._pending_tasks)} tasks remaining")
            # Cancel remaining tasks
            for task in self._pending_tasks:
                if not task.done():
                    task.cancel()

        self._pending_tasks.clear()
        logger.debug("Finalize complete")

    def get_recording(self, result: str) -> SessionRecording:
        """Get the complete recording.

        Args:
            result: The final result of the task execution

        Returns:
            SessionRecording with all captured events
        """
        return SessionRecording(
            task=self.task,
            result=result,
            requests=list(self._requests.values()),
            responses=self._responses,
            navigation_urls=self._navigation_urls,
            start_time=self.start_time,
            end_time=datetime.now(),
        )

    def get_api_calls_summary(self) -> list[dict]:
        """Get a summary of API calls (XHR/Fetch and JSON documents) for quick inspection.

        Returns:
            List of dicts with API call summaries
        """
        api_calls = []

        # Filter to XHR/Fetch requests and JSON document loads
        api_requests = {}
        for rid, req in self._requests.items():
            resource_type = req.resource_type.lower()
            if resource_type in ("xhr", "fetch"):
                api_requests[rid] = req
            elif resource_type == "document":
                # Check if this document returned JSON (by looking at response)
                resp = self._cdp_to_response.get(rid)
                if resp and any(ct in resp.mime_type.lower() for ct in JSON_CONTENT_TYPES):
                    api_requests[rid] = req

        # Match with responses
        for resp in self._responses:
            if resp.request_id in api_requests:
                req = api_requests[resp.request_id]
                api_calls.append(
                    {
                        "url": req.url,
                        "method": req.method,
                        "status": resp.status,
                        "content_type": resp.mime_type,
                        "has_body": resp.body is not None,
                    }
                )

        return api_calls

    @property
    def request_count(self) -> int:
        """Total number of requests captured."""
        return len(self._requests)

    @property
    def api_call_count(self) -> int:
        """Number of API calls captured (XHR/Fetch + JSON documents)."""
        count = 0
        for rid, req in self._requests.items():
            resource_type = req.resource_type.lower()
            if resource_type in ("xhr", "fetch"):
                count += 1
            elif resource_type == "document":
                # Count JSON document loads as API calls
                resp = self._cdp_to_response.get(rid)
                if resp and any(ct in resp.mime_type.lower() for ct in JSON_CONTENT_TYPES):
                    count += 1
        return count
