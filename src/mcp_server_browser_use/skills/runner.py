"""Skill runner for direct execution via browser fetch().

Executes skills directly by running fetch() from within the browser context.
This leverages the browser's cookie jar and auth state for:
- Automatic session handling
- No CORS issues (request from page context)
- Preserved authentication

Much faster than agent navigation (~1-3s vs ~60-120s).

Key implementation detail: Uses session-scoped CDP commands with `session_id`
to bypass browser-use's watchdog system and avoid hangs. The Page and Runtime
domains must be enabled on the CDP session before use.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from .models import AuthRecovery, Skill, SkillRequest

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession, CDPSession

logger = logging.getLogger(__name__)


@dataclass
class SkillRunResult:
    """Result of skill execution."""

    success: bool
    data: Any = None  # Parsed response data
    raw_response: Optional[str] = None  # Raw response body
    status_code: int = 0
    error: Optional[str] = None
    auth_recovery_triggered: bool = False


class SkillRunner:
    """Executes skills directly via browser fetch().

    Usage:
        runner = SkillRunner()

        # Run with existing browser session
        result = await runner.run(skill, params, browser_session)

        # Or let runner manage browser
        result = await runner.run_standalone(skill, params, browser_profile)
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize runner.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

    async def run(
        self,
        skill: Skill,
        params: dict[str, Any],
        browser_session: "BrowserSession",
    ) -> SkillRunResult:
        """Execute a skill using an existing browser session.

        Args:
            skill: Skill with request configuration
            params: Parameters to substitute in request
            browser_session: Active browser session

        Returns:
            SkillRunResult with parsed data or error
        """
        if not skill.request:
            return SkillRunResult(
                success=False,
                error="Skill does not support direct execution (no request config)",
            )

        request = skill.request
        auth_recovery = skill.auth_recovery

        # Build the fetch URL
        url = request.build_url(params)
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        logger.info(f"SkillRunner executing: {request.method} {url}")

        # Get or create a CDP session with domains enabled
        # This is critical: using session_id bypasses browser-use watchdogs
        try:
            cdp_session = await self._get_cdp_session(browser_session)
        except Exception as e:
            logger.error(f"Failed to initialize CDP session: {e}")
            return SkillRunResult(success=False, error=f"CDP session failed: {e}")

        # Navigate to the domain first to establish cookie context
        try:
            await self._navigate_to_domain(browser_session, cdp_session, base_url)
        except Exception as e:
            logger.error(f"Failed to navigate to domain {base_url}: {e}")
            return SkillRunResult(success=False, error=f"Navigation failed: {e}")

        # Execute the fetch
        result = await self._execute_fetch(request, params, browser_session, cdp_session)

        # Check if auth recovery is needed
        if not result.success and auth_recovery and self._should_recover_auth(result, auth_recovery):
            logger.info(f"Auth recovery triggered, navigating to: {auth_recovery.recovery_page}")
            result.auth_recovery_triggered = True

            # Return with auth_recovery_triggered flag - caller should handle recovery
            # We don't do recovery here because it requires agent interaction
            result.error = f"Auth required - recovery page: {auth_recovery.recovery_page}"

        return result

    async def _get_cdp_session(self, browser_session: "BrowserSession") -> "CDPSession":
        """Get or create a CDP session with required domains enabled.

        Uses session-scoped CDP commands to bypass watchdog interference.
        Enables Page and Runtime domains needed for navigation and fetch execution.

        Args:
            browser_session: Browser session

        Returns:
            CDPSession with domains enabled
        """
        # Get the active target ID (current tab)
        cdp_session = await browser_session.get_or_create_cdp_session()

        # Enable Page domain (required for navigation)
        try:
            await browser_session.cdp_client.send.Page.enable(session_id=cdp_session.session_id)
            logger.debug(f"Enabled Page domain for session {cdp_session.session_id[-8:]}")
        except Exception as e:
            # May already be enabled by session manager
            logger.debug(f"Page.enable: {e}")

        # Enable Runtime domain (required for evaluate)
        try:
            await browser_session.cdp_client.send.Runtime.enable(session_id=cdp_session.session_id)
            logger.debug(f"Enabled Runtime domain for session {cdp_session.session_id[-8:]}")
        except Exception as e:
            logger.debug(f"Runtime.enable: {e}")

        return cdp_session

    async def _navigate_to_domain(
        self,
        browser_session: "BrowserSession",
        cdp_session: "CDPSession",
        base_url: str,
    ) -> None:
        """Navigate to the target domain to establish cookie context.

        Uses session-scoped CDP Page.navigate to avoid watchdog interference.

        Args:
            browser_session: Browser session
            cdp_session: CDP session with Page domain enabled
            base_url: Base URL of the target domain
        """
        # Get current URL
        try:
            current_url = await self._get_current_url(browser_session, cdp_session)
            current_parsed = urlparse(current_url) if current_url else None

            # Only navigate if we're not already on the same domain
            target_parsed = urlparse(base_url)
            if current_parsed and current_parsed.netloc == target_parsed.netloc:
                logger.debug(f"Already on domain {target_parsed.netloc}, skipping navigation")
                return

        except Exception as e:
            logger.debug(f"Could not get current URL: {e}, continuing with navigation")

        # Navigate using CDP Page.navigate with session_id (bypasses watchdogs)
        logger.debug(f"Navigating to domain: {base_url}")
        nav_result = await browser_session.cdp_client.send.Page.navigate(
            params={"url": base_url, "transitionType": "address_bar"},
            session_id=cdp_session.session_id,
        )

        # Check for navigation errors
        if nav_result.get("errorText"):
            raise RuntimeError(f"Navigation failed: {nav_result['errorText']}")

        # Wait for page to stabilize using lifecycle event or simple delay
        # A brief wait is needed for cookies to be established
        await asyncio.sleep(1.0)

    async def _get_current_url(
        self,
        browser_session: "BrowserSession",
        cdp_session: "CDPSession",
    ) -> Optional[str]:
        """Get the current page URL.

        Args:
            browser_session: Browser session
            cdp_session: CDP session with Page domain enabled

        Returns:
            Current URL or None
        """
        try:
            # Get the current frame tree to find the URL (using session_id)
            result = await browser_session.cdp_client.send.Page.getFrameTree(session_id=cdp_session.session_id)
            frame = result.get("frameTree", {}).get("frame", {})
            return frame.get("url")
        except Exception as e:
            logger.debug(f"Could not get frame tree: {e}")
            return None

    async def _execute_fetch(
        self,
        request: SkillRequest,
        params: dict[str, Any],
        browser_session: "BrowserSession",
        cdp_session: "CDPSession",
    ) -> SkillRunResult:
        """Execute fetch() via CDP Runtime.evaluate.

        Uses session-scoped Runtime.evaluate to execute fetch in browser context.

        Args:
            request: Skill request configuration
            params: Parameters to substitute
            browser_session: Browser session
            cdp_session: CDP session with Runtime domain enabled

        Returns:
            SkillRunResult with response data
        """
        url = request.build_url(params)
        options = request.to_fetch_options(params)

        # Build JavaScript fetch code
        js_code = self._build_fetch_js(url, options, request.response_type)

        logger.debug(f"Executing fetch: {request.method} {url}")

        try:
            # Execute in browser context using session_id
            result = await browser_session.cdp_client.send.Runtime.evaluate(
                params={
                    "expression": js_code,
                    "awaitPromise": True,
                    "returnByValue": True,
                    "timeout": int(self.timeout * 1000),
                },
                session_id=cdp_session.session_id,
            )

            # Parse the result
            if result.get("exceptionDetails"):
                error = result["exceptionDetails"].get("text", "Unknown error")
                logger.error(f"Fetch failed with exception: {error}")
                return SkillRunResult(success=False, error=error)

            value = result.get("result", {}).get("value", {})

            if not value.get("ok"):
                status = value.get("status", 0)
                error_text = value.get("error") or value.get("body", "Request failed")
                logger.warning(f"Fetch returned status {status}: {error_text}")
                return SkillRunResult(
                    success=False,
                    status_code=status,
                    raw_response=value.get("body"),
                    error=f"HTTP {status}: {error_text[:100]}",
                )

            # Success - extract data
            raw_body = value.get("body", "")
            status_code = value.get("status", 200)

            # Parse response based on type
            parsed_data = self._parse_response(raw_body, request)

            logger.info(f"Fetch succeeded: {status_code}, data extracted")
            return SkillRunResult(
                success=True,
                data=parsed_data,
                raw_response=raw_body,
                status_code=status_code,
            )

        except Exception as e:
            logger.error(f"Fetch execution failed: {e}")
            return SkillRunResult(success=False, error=str(e))

    def _build_fetch_js(self, url: str, options: dict[str, Any], response_type: str) -> str:
        """Build JavaScript code for fetch execution.

        Args:
            url: Request URL
            options: Fetch options
            response_type: Expected response type (json, html, text)

        Returns:
            JavaScript code string
        """
        options_json = json.dumps(options)

        # Build response handling based on type
        if response_type == "json":
            response_handler = "response.json()"
        else:
            response_handler = "response.text()"

        return f"""
(async () => {{
    try {{
        const response = await fetch({json.dumps(url)}, {options_json});
        const body = await {response_handler};
        return {{
            ok: response.ok,
            status: response.status,
            body: typeof body === 'string' ? body : JSON.stringify(body),
        }};
    }} catch (error) {{
        return {{
            ok: false,
            status: 0,
            error: error.message || String(error),
        }};
    }}
}})()
"""

    def _parse_response(self, raw_body: str, request: SkillRequest) -> Any:
        """Parse response according to skill configuration.

        Args:
            raw_body: Raw response body
            request: Skill request with parsing config

        Returns:
            Parsed/extracted data
        """
        if request.response_type == "json":
            try:
                data = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

                # Extract using path if specified
                if request.extract_path:
                    return self._extract_json_path(data, request.extract_path)

                return data

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed: {e}")
                return raw_body

        elif request.response_type == "html" and request.html_selectors:
            # HTML parsing would require BeautifulSoup or similar
            # For now, return raw HTML
            logger.debug("HTML parsing not yet implemented, returning raw")
            return raw_body

        return raw_body

    def _extract_json_path(self, data: Any, path: str) -> Any:
        """Extract data using a simple JSON path.

        Supports:
        - "key.nested.value" - nested access
        - "items[*].name" - array access (returns list of values)

        Args:
            data: JSON data
            path: Path expression

        Returns:
            Extracted value(s)
        """
        parts = path.replace("[*]", ".[*]").split(".")
        current = data

        for part in parts:
            if not part:
                continue

            if part == "[*]":
                # Array expansion - collect from all items
                if isinstance(current, list):
                    # Continue collecting from remaining path
                    remaining = ".".join(parts[parts.index(part) + 1 :])
                    if remaining:
                        return [self._extract_json_path(item, remaining) for item in current]
                    return current
            elif isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                return None

            if current is None:
                return None

        return current

    def _should_recover_auth(self, result: SkillRunResult, auth_recovery: AuthRecovery) -> bool:
        """Check if auth recovery should be triggered.

        Args:
            result: Failed result
            auth_recovery: Recovery configuration

        Returns:
            True if recovery should be triggered
        """
        # Check status code
        if result.status_code in auth_recovery.trigger_on_status:
            return True

        # Check response body for auth error text
        if auth_recovery.trigger_on_body and result.raw_response:
            if auth_recovery.trigger_on_body.lower() in result.raw_response.lower():
                return True

        return False
