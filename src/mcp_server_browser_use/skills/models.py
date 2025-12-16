"""Data models for browser skills.

Skills are MACHINE-GENERATED from learning sessions, not manually authored.
The agent discovers API endpoints during learning mode, and the analyzer
extracts the "money request" (the API call that returns the desired data).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# --- Recording Models (captured during learning) ---


@dataclass
class NetworkRequest:
    """A captured network request during recording."""

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    post_data: Optional[str] = None
    resource_type: str = ""  # XHR, Fetch, Document, etc.
    timestamp: float = 0.0
    request_id: str = ""


@dataclass
class NetworkResponse:
    """A captured network response during recording."""

    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None  # Response body (if captured)
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
    end_time: Optional[datetime] = None

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
    """

    endpoint: str  # URL path (without domain)
    method: str = "GET"
    content_type: str = "application/json"
    request_template: Optional[str] = None  # Template for request body (with {param} placeholders)
    response_path: Optional[str] = None  # JSONPath to the data in response (e.g., "data.jobs")
    identifies_by: Optional[str] = None  # How to identify this request (e.g., "operationName: searchJobs")
    sample_response_schema: Optional[dict] = None  # Simplified schema of expected response


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
    default: Optional[str] = None
    description: str = ""
    source: str = ""  # Where this param was found: "url", "body", "query"


@dataclass
class SkillHints:
    """Hints for the agent to execute the skill efficiently."""

    navigation: list[NavigationStep] = field(default_factory=list)
    money_request: Optional[MoneyRequest] = None

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
    """

    name: str
    description: str
    original_task: str  # The task that created this skill

    # Machine-generated from recording analysis
    hints: SkillHints = field(default_factory=SkillHints)
    parameters: list[SkillParameter] = field(default_factory=list)

    # Metadata
    version: int = 1
    created: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    fallback: FallbackConfig = field(default_factory=FallbackConfig)

    @property
    def success_rate(self) -> float:
        """Calculate success rate from usage statistics."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert skill to dictionary for serialization."""
        result = {
            "name": self.name,
            "description": self.description,
            "original_task": self.original_task,
            "version": self.version,
            "created": self.created.isoformat() if self.created else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
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
            "hints": {
                "navigation": [{"url_pattern": n.url_pattern, "description": n.description, "required": n.required} for n in self.hints.navigation],
            },
            "fallback": {
                "strategy": self.fallback.strategy,
                "max_retries": self.fallback.max_retries,
            },
        }

        # Add money_request if present
        if self.hints.money_request:
            mr = self.hints.money_request
            result["hints"]["money_request"] = {
                "endpoint": mr.endpoint,
                "method": mr.method,
                "content_type": mr.content_type,
                "request_template": mr.request_template,
                "response_path": mr.response_path,
                "identifies_by": mr.identifies_by,
                "sample_response_schema": mr.sample_response_schema,
            }

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

        # Parse hints
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

        # Parse money_request
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
            parameters=parameters,
            hints=hints,
            fallback=fallback,
        )
