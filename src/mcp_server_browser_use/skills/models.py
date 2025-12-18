"""Data models for browser skills.

Skills are MACHINE-GENERATED from learning sessions, not manually authored.
The agent discovers API endpoints during learning mode, and the analyzer
extracts the "money request" (the API call that returns the desired data).

Execution uses browser's fetch() via CDP for:
- Automatic cookie/session handling
- No CORS issues (request from page context)
- Preserved auth state
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# Sensitive headers that should be stripped before saving skills
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-session-id",
        "bearer",
        "api-key",
    }
)


def strip_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove sensitive headers before saving skill.

    Unlike redaction, this completely removes sensitive headers
    rather than replacing values with '***REDACTED***'.
    """
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


# --- Recording Models (captured during learning) ---


@dataclass
class NetworkRequest:
    """A captured network request during recording."""

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    post_data: str | None = None
    resource_type: str = ""  # XHR, Fetch, Document, etc.
    timestamp: float = 0.0
    request_id: str = ""


@dataclass
class NetworkResponse:
    """A captured network response during recording."""

    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None  # Response body (if captured)
    mime_type: str = ""
    timestamp: float = 0.0
    request_id: str = ""


@dataclass
class SessionRecording:
    """Complete recording of a browser session for skill extraction."""

    task: str
    result: str
    requests: list[NetworkRequest] = field(default_factory=list)
    responses: list[NetworkResponse] = field(default_factory=list)
    navigation_urls: list[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None

    def get_api_calls(self) -> list[tuple[NetworkRequest, NetworkResponse]]:
        """Get paired request/response for XHR/Fetch calls only."""
        api_requests = {r.request_id: r for r in self.requests if r.resource_type in ("XHR", "Fetch", "xhr", "fetch")}

        pairs = []
        for resp in self.responses:
            if resp.request_id in api_requests:
                pairs.append((api_requests[resp.request_id], resp))

        return pairs


# --- Skill Models (machine-generated from analysis) ---


@dataclass
class MoneyRequest:
    """The key API call that returns the desired data.

    This is identified by the analyzer as THE request that contains
    the data the user asked for.

    DEPRECATED: Use SkillRequest for new skills. Kept for backward compatibility.
    """

    endpoint: str  # URL path (without domain)
    method: str = "GET"
    content_type: str = "application/json"
    request_template: str | None = None  # Template for request body (with {param} placeholders)
    response_path: str | None = None  # JSONPath to the data in response (e.g., "data.jobs")
    identifies_by: str | None = None  # How to identify this request (e.g., "operationName: searchJobs")
    sample_response_schema: dict | None = None  # Simplified schema of expected response


# --- Direct Execution Models (new architecture) ---


@dataclass
class SkillRequest:
    """Complete request specification for direct browser execution.

    Contains everything needed to execute fetch() from within the browser:
    - Full URL with parameter placeholders
    - Method, headers, body template
    - Response parsing configuration
    """

    # Request details
    url: str  # Full URL with {param} placeholders, e.g., "https://npmjs.com/search?q={query}"
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)  # Headers to send (non-sensitive)
    body_template: str | None = None  # Request body template with {param} placeholders

    # Response handling
    response_type: Literal["json", "html", "text"] = "json"
    extract_path: str | None = None  # For JSON: JMESPath like "data.items" or "objects[*].package"

    # For HTML responses - CSS selectors
    html_selectors: dict[str, str] | None = None  # {"items": ".result-item", "title": "h3 a", ...}

    # Security: Domain allowlist (empty = allow all for backwards compatibility)
    allowed_domains: list[str] = field(default_factory=list)

    def build_url(self, params: dict[str, Any]) -> str:
        """Build URL by substituting parameter placeholders."""
        url = self.url
        for key, value in params.items():
            url = url.replace(f"{{{key}}}", str(value))
        return url

    def build_body(self, params: dict[str, Any]) -> str | None:
        """Build request body by substituting parameter placeholders."""
        if not self.body_template:
            return None
        body = self.body_template
        for key, value in params.items():
            body = body.replace(f"{{{key}}}", str(value))
        return body

    def get_safe_headers(self) -> dict[str, str]:
        """Return headers with sensitive ones removed (not redacted).

        Use this when saving skills to avoid storing auth tokens.
        """
        return strip_sensitive_headers(self.headers)

    def to_fetch_options(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate JavaScript fetch() options."""
        options: dict[str, Any] = {
            "method": self.method,
            "credentials": "include",  # Always include cookies
        }

        if self.headers:
            options["headers"] = self.headers

        body = self.build_body(params)
        if body:
            options["body"] = body

        return options


@dataclass
class AuthRecovery:
    """Configuration for handling authentication failures.

    When a skill request returns 401/403, the runner can:
    1. Navigate to the recovery page
    2. Let the agent re-authenticate
    3. Retry the original request
    """

    # When to trigger recovery
    trigger_on_status: list[int] = field(default_factory=lambda: [401, 403])
    trigger_on_body: str | None = None  # Text in response body that indicates auth failure

    # Recovery action
    recovery_page: str = ""  # URL to navigate to for re-auth (e.g., login page)
    success_indicator: str | None = None  # How to know auth succeeded (e.g., "cookie:session present")

    # Limits
    max_retries: int = 1


@dataclass
class NavigationStep:
    """A navigation step required before calling the API."""

    url_pattern: str
    description: str
    required: bool = True


@dataclass
class SkillParameter:
    """A configurable parameter extracted from the API call."""

    name: str
    type: str = "string"  # string, integer, boolean
    required: bool = False
    default: str | None = None
    description: str = ""
    source: str = ""  # Where this param was found: "url", "body", "query"


@dataclass
class SkillHints:
    """Hints for the agent to execute the skill efficiently."""

    navigation: list[NavigationStep] = field(default_factory=list)
    money_request: MoneyRequest | None = None

    def to_prompt(self, params: dict) -> str:
        """Convert hints to a prompt string for the agent."""
        lines = []

        if self.navigation:
            lines.append("NAVIGATION STEPS:")
            for step in self.navigation:
                url = step.url_pattern
                for key, val in params.items():
                    url = url.replace(f"{{{key}}}", str(val))
                lines.append(f"  1. {step.description}: {url}")
            lines.append("")

        if self.money_request:
            lines.append("TARGET API CALL:")
            lines.append(f"  - Endpoint: {self.money_request.endpoint}")
            lines.append(f"  - Method: {self.money_request.method}")
            if self.money_request.identifies_by:
                lines.append(f"  - Identify by: {self.money_request.identifies_by}")
            if self.money_request.response_path:
                lines.append(f"  - Data location: {self.money_request.response_path}")
            lines.append("")

        return "\n".join(lines)


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior when hints fail."""

    strategy: str = "explore_full"  # explore_full, error, retry_with_delay
    max_retries: int = 2


@dataclass
class Skill:
    """A machine-generated browser skill with API hints.

    Skills are created automatically when:
    1. User runs run_browser_agent with learn=True
    2. Agent successfully completes the task by discovering an API
    3. Analyzer identifies the "money request" and extracts parameters

    Two execution modes:
    - Direct execution (new): Use `request` field, execute fetch() via CDP
    - Hint-based (legacy): Use `hints` field, agent navigates with guidance
    """

    name: str
    description: str
    original_task: str  # The task that created this skill

    # NEW: Direct execution configuration
    request: SkillRequest | None = None  # If set, use direct fetch() execution
    auth_recovery: AuthRecovery | None = None  # How to handle auth failures

    # LEGACY: Hint-based execution (agent navigates with guidance)
    hints: SkillHints = field(default_factory=SkillHints)
    parameters: list[SkillParameter] = field(default_factory=list)

    # Metadata
    version: int = 1
    created: datetime = field(default_factory=datetime.now)
    last_used: datetime | None = None
    success_count: int = 0
    failure_count: int = 0
    fallback: FallbackConfig = field(default_factory=FallbackConfig)

    # Skill verification status
    status: Literal["draft", "verified", "failed"] = "draft"

    @property
    def supports_direct_execution(self) -> bool:
        """Check if this skill supports fast direct execution."""
        return self.request is not None

    @property
    def success_rate(self) -> float:
        """Calculate success rate from usage statistics."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def merge_params(self, user_params: dict[str, Any]) -> dict[str, Any]:
        """Merge user-provided params with parameter defaults.

        User params take precedence over defaults.
        """
        merged = {}
        for param in self.parameters:
            if param.name in user_params:
                merged[param.name] = user_params[param.name]
            elif param.default is not None:
                merged[param.name] = param.default
        # Also include any extra user params not in schema
        for key, value in user_params.items():
            if key not in merged:
                merged[key] = value
        return merged

    def to_dict(self) -> dict[str, Any]:
        """Convert skill to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "original_task": self.original_task,
            "version": self.version,
            "created": self.created.isoformat() if self.created else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "status": self.status,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                    "source": p.source,
                }
                for p in self.parameters
            ],
            "fallback": {
                "strategy": self.fallback.strategy,
                "max_retries": self.fallback.max_retries,
            },
        }

        # Add request for direct execution (headers stripped, not redacted)
        if self.request:
            result["request"] = {
                "url": self.request.url,
                "method": self.request.method,
                "headers": self.request.get_safe_headers(),
                "body_template": self.request.body_template,
                "response_type": self.request.response_type,
                "extract_path": self.request.extract_path,
                "html_selectors": self.request.html_selectors,
                "allowed_domains": self.request.allowed_domains,
            }

        # NEW: Add auth_recovery
        if self.auth_recovery:
            result["auth_recovery"] = {
                "trigger_on_status": self.auth_recovery.trigger_on_status,
                "trigger_on_body": self.auth_recovery.trigger_on_body,
                "recovery_page": self.auth_recovery.recovery_page,
                "success_indicator": self.auth_recovery.success_indicator,
                "max_retries": self.auth_recovery.max_retries,
            }

        # LEGACY: Add hints for backward compatibility
        hints_dict: dict[str, Any] = {
            "navigation": [{"url_pattern": n.url_pattern, "description": n.description, "required": n.required} for n in self.hints.navigation],
        }

        # Add money_request if present (legacy)
        if self.hints.money_request:
            mr = self.hints.money_request
            hints_dict["money_request"] = {
                "endpoint": mr.endpoint,
                "method": mr.method,
                "content_type": mr.content_type,
                "request_template": mr.request_template,
                "response_path": mr.response_path,
                "identifies_by": mr.identifies_by,
                "sample_response_schema": mr.sample_response_schema,
            }

        result["hints"] = hints_dict
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        """Create skill from dictionary."""
        # Parse parameters
        parameters = [
            SkillParameter(
                name=p["name"],
                type=p.get("type", "string"),
                required=p.get("required", False),
                default=p.get("default"),
                description=p.get("description", ""),
                source=p.get("source", ""),
            )
            for p in data.get("parameters", [])
        ]

        # Parse request for direct execution
        request = None
        req_data = data.get("request")
        if req_data:
            request = SkillRequest(
                url=req_data["url"],
                method=req_data.get("method", "GET"),
                headers=req_data.get("headers", {}),
                body_template=req_data.get("body_template"),
                response_type=req_data.get("response_type", "json"),
                extract_path=req_data.get("extract_path"),
                html_selectors=req_data.get("html_selectors"),
                allowed_domains=req_data.get("allowed_domains", []),
            )

        # NEW: Parse auth_recovery
        auth_recovery = None
        auth_data = data.get("auth_recovery")
        if auth_data:
            auth_recovery = AuthRecovery(
                trigger_on_status=auth_data.get("trigger_on_status", [401, 403]),
                trigger_on_body=auth_data.get("trigger_on_body"),
                recovery_page=auth_data.get("recovery_page", ""),
                success_indicator=auth_data.get("success_indicator"),
                max_retries=auth_data.get("max_retries", 1),
            )

        # LEGACY: Parse hints
        hints_data = data.get("hints", {})

        # Parse navigation steps
        navigation = [
            NavigationStep(
                url_pattern=n["url_pattern"],
                description=n.get("description", ""),
                required=n.get("required", True),
            )
            for n in hints_data.get("navigation", [])
        ]

        # Parse money_request (legacy)
        money_request = None
        mr_data = hints_data.get("money_request")
        if mr_data:
            money_request = MoneyRequest(
                endpoint=mr_data["endpoint"],
                method=mr_data.get("method", "GET"),
                content_type=mr_data.get("content_type", "application/json"),
                request_template=mr_data.get("request_template"),
                response_path=mr_data.get("response_path"),
                identifies_by=mr_data.get("identifies_by"),
                sample_response_schema=mr_data.get("sample_response_schema"),
            )

        hints = SkillHints(navigation=navigation, money_request=money_request)

        # Parse fallback
        fallback_data = data.get("fallback", {})
        fallback = FallbackConfig(
            strategy=fallback_data.get("strategy", "explore_full"),
            max_retries=fallback_data.get("max_retries", 2),
        )

        # Parse dates
        created = data.get("created")
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        elif created is None:
            created = datetime.now()

        last_used = data.get("last_used")
        if isinstance(last_used, str):
            last_used = datetime.fromisoformat(last_used)

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            original_task=data.get("original_task", ""),
            version=data.get("version", 1),
            created=created,
            last_used=last_used,
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            status=data.get("status", "draft"),
            parameters=parameters,
            request=request,
            auth_recovery=auth_recovery,
            hints=hints,
            fallback=fallback,
        )
