"""Recipe runner for direct execution via browser fetch().

Executes recipes directly by running fetch() from within the browser context.
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
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import jmespath
from jmespath.exceptions import JMESPathError

from .models import AuthRecovery, Recipe, RecipeRequest

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession, CDPSession

logger = logging.getLogger(__name__)

MAX_RESPONSE_SIZE = 1_000_000  # 1MB cap to prevent OOM on huge API responses

# Blocked hostnames (case-insensitive) - comprehensive localhost variants
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "[::1]",
        "[::]",
        "[0:0:0:0:0:0:0:0]",
        "[0:0:0:0:0:0:0:1]",
    }
)


def _normalize_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse IP from various formats (decimal, octal, hex, bracketed IPv6).

    Handles:
    - Standard IPv4: 127.0.0.1
    - Decimal IPv4: 2130706433 (= 127.0.0.1)
    - IPv6: ::1, fe80::1
    - Bracketed IPv6: [::1], [fe80::1]
    """
    clean = host.strip("[]")

    # Handle decimal notation: 2130706433 -> 127.0.0.1
    if clean.isdigit():
        try:
            return ipaddress.IPv4Address(int(clean))
        except ValueError:
            pass

    # Handle standard notation (IPv4 or IPv6)
    try:
        return ipaddress.ip_address(clean)
    except ValueError:
        return None


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is private, loopback, link-local, or reserved."""
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


async def validate_url_safe(url: str) -> None:
    """Validate URL is safe from SSRF attacks.

    Raises ValueError if URL is unsafe. Checks:
    - Scheme is http/https
    - No credentials in URL (user:pass@host bypass)
    - Hostname exists and is not blocked
    - IP addresses are not private/reserved
    - DNS resolution returns only public IPs (DNS rebinding protection)
    """
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Scheme '{parsed.scheme}' not allowed, use http/https")

    # Reject URLs with credentials (user:pass@host bypass)
    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must have a hostname")

    # Strip IPv6 zone ID (%eth0) - these can bypass some checks
    if "%" in hostname:
        hostname = hostname.split("%")[0]

    # Check blocked hostnames
    if hostname.lower() in _BLOCKED_HOSTS:
        raise ValueError(f"Hostname '{hostname}' is blocked")

    # Check if it's an IP address (various formats)
    ip = _normalize_ip(hostname)
    if ip is not None:
        if _is_ip_blocked(ip):
            raise ValueError(f"IP '{ip}' is blocked (private/reserved)")
        return  # Valid public IP

    # DNS resolution - run in thread to avoid blocking event loop
    try:
        loop = asyncio.get_running_loop()
        addr_info = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve hostname '{hostname}': {e}") from e

    # Check ALL resolved IPs (DNS rebinding protection)
    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        resolved_ip = ipaddress.ip_address(sockaddr[0])
        if _is_ip_blocked(resolved_ip):
            raise ValueError(f"Hostname '{hostname}' resolves to blocked IP '{resolved_ip}'")


def validate_domain_allowed(url: str, allowed_domains: list[str]) -> None:
    """Validate URL domain is in allowlist.

    Empty allowlist means all domains allowed (for backwards compatibility).
    Supports subdomain matching: api.example.com matches allowlist entry example.com.
    """
    if not allowed_domains:
        return  # No restrictions

    hostname = urlparse(url).hostname
    if not hostname:
        raise ValueError("URL must have a hostname")

    hostname_lower = hostname.lower()
    for allowed in allowed_domains:
        allowed_lower = allowed.lower()
        # Exact match or subdomain match
        if hostname_lower == allowed_lower or hostname_lower.endswith(f".{allowed_lower}"):
            return

    raise ValueError(f"Domain '{hostname}' not in allowlist: {allowed_domains}")


def build_url(template: str, params: dict[str, Any]) -> str:
    """Build URL from template with proper encoding.

    DEPRECATED: Use RecipeRequest.build_url() instead for consistency.

    Handles:
    - Path parameters with URL encoding: /users/{id} -> /users/a%20b
    - Query parameters with proper escaping
    """
    parsed = urlparse(template)

    # Substitute path parameters with URL encoding
    path = parsed.path
    for key, value in params.items():
        placeholder = f"{{{key}}}"
        if placeholder in path:
            path = path.replace(placeholder, quote(str(value), safe=""))

    # Substitute query parameters
    query_dict = parse_qs(parsed.query, keep_blank_values=True)
    new_query_items: list[tuple[str, str]] = []

    for key, values in query_dict.items():
        for val in values:
            new_val = val
            for pk, pv in params.items():
                placeholder = f"{{{pk}}}"
                if placeholder in new_val:
                    new_val = new_val.replace(placeholder, str(pv))
            new_query_items.append((key, new_val))

    new_query = urlencode(new_query_items, safe="")

    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, new_query, parsed.fragment))


def extract_data(data: Any, expression: str | None) -> Any:
    """Extract data using JMESPath expression.

    Supports:
    - Simple paths: data.items
    - Filters: items[?active==`true`].name
    - Functions: length(items), sort_by(@, &name)
    """
    if not expression:
        return data

    try:
        return jmespath.search(expression, data)
    except JMESPathError as e:
        raise ValueError(f"JMESPath extraction failed: {e}") from e


# Legacy function for backwards compatibility - will be removed
def is_private_url(url: str) -> bool:
    """Check if URL resolves to private IP. DEPRECATED: Use validate_url_safe() instead."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        ip = _normalize_ip(hostname)
        if ip is not None:
            return _is_ip_blocked(ip)
        # Resolve hostname (blocking - legacy behavior)
        resolved = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved)
        return _is_ip_blocked(ip)
    except Exception:
        return False


@dataclass
class RecipeRunResult:
    """Result of recipe execution."""

    success: bool
    data: Any = None  # Parsed response data
    raw_response: str | None = None  # Raw response body
    status_code: int = 0
    error: str | None = None
    auth_recovery_triggered: bool = False


class RecipeRunner:
    """Executes recipes directly via browser fetch().

    Usage:
        runner = RecipeRunner()

        # Run with existing browser session
        result = await runner.run(recipe, params, browser_session)

        # Or let runner manage browser
        result = await runner.run_standalone(recipe, params, browser_profile)
    """

    def __init__(self, timeout: float = 30.0):
        """Initialize runner.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout

    async def run(
        self,
        recipe: Recipe,
        params: dict[str, Any],
        browser_session: "BrowserSession",
    ) -> RecipeRunResult:
        """Execute a recipe using an existing browser session.

        Args:
            recipe: Recipe with request configuration
            params: Parameters to substitute in request
            browser_session: Active browser session

        Returns:
            RecipeRunResult with parsed data or error
        """
        if not recipe.request:
            return RecipeRunResult(
                success=False,
                error="Recipe does not support direct execution (no request config)",
            )

        request = recipe.request
        auth_recovery = recipe.auth_recovery

        # Build the fetch URL with proper encoding
        url = request.build_url(params)

        # SSRF protection - comprehensive async check
        try:
            await validate_url_safe(url)
        except ValueError as e:
            return RecipeRunResult(success=False, error=f"SSRF blocked: {e}")

        # Domain allowlist enforcement (if configured)
        allowed_domains = getattr(request, "allowed_domains", [])
        try:
            validate_domain_allowed(url, allowed_domains)
        except ValueError as e:
            return RecipeRunResult(success=False, error=f"Domain not allowed: {e}")

        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        logger.info(f"RecipeRunner executing: {request.method} {url}")

        # Get or create a CDP session with domains enabled
        # This is critical: using session_id bypasses browser-use watchdogs
        try:
            cdp_session = await self._get_cdp_session(browser_session)
        except Exception as e:
            logger.error(f"Failed to initialize CDP session: {e}")
            return RecipeRunResult(success=False, error=f"CDP session failed: {e}")

        # For HTML pages with selectors, navigate to full URL and extract from rendered DOM
        # This handles JavaScript-rendered pages (like GitHub)
        if request.response_type == "html" and request.html_selectors:
            result = await self._execute_html_extraction(request, params, url, browser_session, cdp_session)
        else:
            # For JSON/text, navigate to domain for cookies, then fetch
            try:
                await self._navigate_to_domain(browser_session, cdp_session, base_url)
            except Exception as e:
                logger.error(f"Failed to navigate to domain {base_url}: {e}")
                return RecipeRunResult(success=False, error=f"Navigation failed: {e}")

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
    ) -> str | None:
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

    async def _execute_html_extraction(
        self,
        request: RecipeRequest,
        params: dict[str, Any],
        url: str,
        browser_session: "BrowserSession",
        cdp_session: "CDPSession",
    ) -> RecipeRunResult:
        """Navigate to page and extract content using CSS selectors.

        For JavaScript-rendered pages, we navigate to the full URL, wait for
        content to load, then extract data using CSS selectors in the browser.

        Args:
            request: Recipe request configuration
            params: Parameters (unused, URL already built)
            url: Full URL to navigate to
            browser_session: Browser session
            cdp_session: CDP session with Runtime domain enabled

        Returns:
            RecipeRunResult with extracted data
        """
        logger.debug(f"HTML extraction: navigating to {url}")

        # Navigate to the full URL
        nav_result = await browser_session.cdp_client.send.Page.navigate(
            params={"url": url, "transitionType": "address_bar"},
            session_id=cdp_session.session_id,
        )

        if nav_result.get("errorText"):
            return RecipeRunResult(success=False, error=f"Navigation failed: {nav_result['errorText']}")

        # Wait for page to load (networkIdle or timeout)
        await asyncio.sleep(3.0)  # Allow JS to render

        # Build JavaScript to extract data using CSS selectors with validation
        selectors = request.html_selectors or {}
        js_code = """
        (function() {
            const selectors = %s;
            const result = {_meta: {tested: {}, total_matches: 0}};

            for (const [name, selector] of Object.entries(selectors)) {
                try {
                    const elements = document.querySelectorAll(selector);
                    const values = Array.from(elements).map(el => el.textContent.trim()).filter(t => t);
                    result[name] = values;
                    result._meta.tested[name] = {selector, count: elements.length, hasData: values.length > 0};
                    result._meta.total_matches += values.length;
                } catch (e) {
                    result[name] = [];
                    result._meta.tested[name] = {selector, error: e.message};
                }
            }

            // If all selectors failed, try to find common list patterns
            if (result._meta.total_matches === 0) {
                const fallbackSelectors = [
                    'article a', 'li a', '.list-item a', '[role="listitem"] a',
                    'h3 a', 'h4 a', '.card a', '.item a'
                ];
                for (const sel of fallbackSelectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 3) {
                        result._meta.suggested_selector = sel;
                        result._meta.suggested_count = els.length;
                        break;
                    }
                }
            }

            return JSON.stringify(result);
        })()
        """ % json.dumps(selectors)

        try:
            eval_result = await browser_session.cdp_client.send.Runtime.evaluate(
                params={
                    "expression": js_code,
                    "returnByValue": True,
                    "awaitPromise": False,
                },
                session_id=cdp_session.session_id,
            )

            if eval_result.get("exceptionDetails"):
                error = eval_result["exceptionDetails"].get("text", "Unknown error")
                return RecipeRunResult(success=False, error=f"Selector extraction failed: {error}")

            result_value = eval_result.get("result", {}).get("value", "{}")
            extracted = json.loads(result_value)

            # Check selector validation results
            meta = extracted.pop("_meta", {})
            total_matches = meta.get("total_matches", 0)

            if total_matches == 0:
                # Log warning about empty selectors
                tested = meta.get("tested", {})
                logger.warning(f"HTML selectors returned no data: {tested}")
                if meta.get("suggested_selector"):
                    logger.info(f"Suggested selector: {meta['suggested_selector']} ({meta['suggested_count']} matches)")
                # Return with warning but still "success" - let caller decide
                return RecipeRunResult(
                    success=True,
                    data=extracted,
                    status_code=200,
                    raw_response=f"Warning: selectors matched no elements. Suggested: {meta.get('suggested_selector', 'none')}",
                )

            logger.debug(f"HTML extraction completed: {len(extracted)} fields, {total_matches} total matches")
            return RecipeRunResult(
                success=True,
                data=extracted,
                status_code=200,
            )

        except Exception as e:
            logger.error(f"HTML extraction failed: {e}")
            return RecipeRunResult(success=False, error=f"Extraction failed: {e}")

    async def _execute_fetch(
        self,
        request: RecipeRequest,
        params: dict[str, Any],
        browser_session: "BrowserSession",
        cdp_session: "CDPSession",
    ) -> RecipeRunResult:
        """Execute fetch() via CDP Runtime.evaluate.

        Uses session-scoped Runtime.evaluate to execute fetch in browser context.

        Args:
            request: Recipe request configuration
            params: Parameters to substitute
            browser_session: Browser session
            cdp_session: CDP session with Runtime domain enabled

        Returns:
            RecipeRunResult with response data
        """
        url = request.build_url(params)

        # CRITICAL: Re-validate URL immediately before fetch to prevent DNS rebinding (TOCTOU)
        # DNS could have been rebound from public to private IP since initial validation
        try:
            await validate_url_safe(url)
        except ValueError as e:
            logger.error(f"SSRF protection: URL validation failed at fetch time: {e}")
            return RecipeRunResult(success=False, error=f"SSRF blocked at fetch time: {e}")

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
                return RecipeRunResult(success=False, error=error)

            value = result.get("result", {}).get("value", {})

            if not value.get("ok"):
                status = value.get("status", 0)
                error_text = value.get("error") or value.get("body", "Request failed")
                logger.warning(f"Fetch returned status {status}: {error_text}")
                return RecipeRunResult(
                    success=False,
                    status_code=status,
                    raw_response=value.get("body"),
                    error=f"HTTP {status}: {error_text[:100]}",
                )

            raw_body = value.get("body", "")
            status_code = value.get("status", 200)
            truncated = value.get("truncated", False)

            if truncated:
                logger.warning(f"Response truncated to {MAX_RESPONSE_SIZE} bytes")

            parsed_data = self._parse_response(raw_body, request)

            logger.info(f"Fetch succeeded: {status_code}, data extracted")
            return RecipeRunResult(
                success=True,
                data=parsed_data,
                raw_response=raw_body,
                status_code=status_code,
            )

        except Exception as e:
            logger.error(f"Fetch execution failed: {e}")
            return RecipeRunResult(success=False, error=str(e))

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

        if response_type == "json":
            response_handler = "response.json()"
        else:
            response_handler = "response.text()"

        return f"""
(async () => {{
    const MAX_SIZE = {MAX_RESPONSE_SIZE};
    let response;
    try {{
        response = await fetch({json.dumps(url)}, {options_json});
    }} catch (error) {{
        return {{
            ok: false,
            status: 0,
            error: 'Fetch failed: ' + (error.message || String(error)),
        }};
    }}

    const status = response.status;
    const ok = response.ok;

    try {{
        const body = await {response_handler};
        let bodyStr = typeof body === 'string' ? body : JSON.stringify(body);
        const truncated = bodyStr.length > MAX_SIZE;
        if (truncated) {{
            bodyStr = bodyStr.slice(0, MAX_SIZE);
        }}
        return {{
            ok: ok,
            status: status,
            body: bodyStr,
            truncated: truncated,
        }};
    }} catch (parseError) {{
        let rawBody = '';
        try {{
            rawBody = await response.clone().text();
            if (rawBody.length > MAX_SIZE) {{
                rawBody = rawBody.slice(0, MAX_SIZE);
            }}
        }} catch (e) {{}}

        return {{
            ok: ok,
            status: status,
            body: rawBody,
            error: 'Body parse failed: ' + (parseError.message || String(parseError)),
        }};
    }}
}})()
"""

    def _parse_response(self, raw_body: str, request: RecipeRequest) -> Any:
        """Parse response according to recipe configuration.

        Args:
            raw_body: Raw response body
            request: Recipe request with parsing config

        Returns:
            Parsed/extracted data
        """
        if request.response_type == "json":
            try:
                data = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

                # Extract using JMESPath if specified
                if request.extract_path:
                    try:
                        return extract_data(data, request.extract_path)
                    except ValueError as e:
                        logger.warning(f"JMESPath extraction failed: {e}")
                        return data

                return data

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed: {e}")
                return raw_body

        elif request.response_type == "html" and request.html_selectors:
            # Parse HTML using BeautifulSoup
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(raw_body, "html.parser")
                extracted: dict[str, list[str]] = {}

                for name, selector in request.html_selectors.items():
                    elements = soup.select(selector)
                    extracted[name] = [el.get_text(strip=True) for el in elements if el.get_text(strip=True)]

                logger.debug(f"HTML extraction: {len(extracted)} fields extracted")
                return extracted

            except ImportError:
                logger.warning("BeautifulSoup not installed, returning raw HTML")
                return raw_body
            except Exception as e:
                logger.warning(f"HTML parsing failed: {e}")
                return raw_body

        return raw_body

    def _should_recover_auth(self, result: RecipeRunResult, auth_recovery: AuthRecovery) -> bool:
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
