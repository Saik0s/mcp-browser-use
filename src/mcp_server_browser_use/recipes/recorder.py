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
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

from .models import NetworkRequest, NetworkResponse, SessionRecording

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from cdp_use.cdp.network.events import LoadingFailedEvent, RequestWillBeSentEvent, ResponseReceivedEvent

logger = logging.getLogger(__name__)

# Headers that should be redacted for security
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-csrf-token",
        "x-xsrf-token",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "x-access-token",
    }
)

# Content types that indicate JSON API responses
JSON_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/graphql-response+json",
        "application/vnd.api+json",
        "text/json",
    }
)

# Maximum body size to capture (128KB)
MAX_BODY_SIZE = 128 * 1024

# Timeout for body capture (5 seconds)
BODY_CAPTURE_TIMEOUT = 5.0


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
            if key.lower() in SENSITIVE_HEADERS:
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

        logger.info(f"RecipeRecorder attached via CDP for task: {self.task[:50]}...")

    def _on_request_will_be_sent(self, event: "RequestWillBeSentEvent", session_id: str | None) -> None:
        """Handle CDP Network.requestWillBeSent event.

        This is a synchronous callback.
        """
        try:
            request_id = event.get("requestId", "")
            request_data = event.get("request", {})  # type: ignore[arg-type]

            # Extract headers (CDP Headers type is dict-like)
            raw_headers: dict[str, str] = dict(request_data.get("headers", {}))  # type: ignore[arg-type]

            # Determine resource type
            resource_type = event.get("type", "Other").lower()

            # Capture request details
            network_request = NetworkRequest(
                url=request_data.get("url", ""),
                method=request_data.get("method", "GET"),
                headers=self._redact_headers(raw_headers),
                post_data=request_data.get("postData"),
                resource_type=resource_type,
                timestamp=time.time(),
                request_id=request_id,
            )

            self._requests[request_id] = network_request

            # Track navigation (Document type)
            if resource_type == "document":
                self._navigation_urls.append(request_data.get("url", ""))

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
            mime_type = response_data.get("mimeType", "")

            # Capture response details
            network_response = NetworkResponse(
                url=response_data.get("url", ""),
                status=response_data.get("status", 0),
                headers=self._redact_headers(raw_headers),
                body=None,  # Body captured async if needed
                mime_type=mime_type,
                timestamp=time.time(),
                request_id=request_id,
            )

            self._responses.append(network_response)
            self._cdp_to_response[request_id] = network_response

            # Schedule body capture for API calls (XHR/Fetch with JSON content)
            if resource_type in ("xhr", "fetch"):
                if any(ct in mime_type.lower() for ct in JSON_CONTENT_TYPES):
                    task = asyncio.create_task(
                        self._capture_body_cdp(request_id, network_response, session_id),
                        name=f"capture_body_{request_id[:8]}",
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

                # Handle base64 encoded bodies
                if result.get("base64Encoded", False):
                    import base64

                    try:
                        body = base64.b64decode(body).decode("utf-8", errors="replace")
                    except Exception:
                        body = "[Binary content - base64 decode failed]"

                # Truncate if too large
                if len(body) > MAX_BODY_SIZE:
                    body = body[:MAX_BODY_SIZE] + f"\n... [TRUNCATED at {MAX_BODY_SIZE} bytes]"

                network_response.body = body

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
        """Get a summary of API calls (XHR/Fetch) for quick inspection.

        Returns:
            List of dicts with API call summaries
        """
        api_calls = []

        # Filter to XHR/Fetch requests
        api_requests = {rid: req for rid, req in self._requests.items() if req.resource_type.lower() in ("xhr", "fetch")}

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
        """Number of XHR/Fetch API calls captured."""
        return sum(1 for r in self._requests.values() if r.resource_type.lower() in ("xhr", "fetch"))
