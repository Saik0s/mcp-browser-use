"""Recipe analyzer for extracting recipes from session recordings.

Analyzes recorded sessions to create replayable recipes:
- API-based: Direct HTTP calls when XHR/Fetch captured
- HTML-based: CSS selectors when data was scraped from page
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import AuthRecovery, FallbackConfig, MoneyRequest, NavigationStep, Recipe, RecipeHints, RecipeParameter, RecipeRequest, SessionRecording
from .prompts import ANALYSIS_SYSTEM_PROMPT, get_analysis_prompt

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

logger = logging.getLogger(__name__)

_PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")
_ResponseType = Literal["json", "html", "text"]
_PUBLIC_PARAMETER_ALLOWLIST = frozenset({"q", "query", "term", "search", "page", "limit"})


class _AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    url: str = Field(min_length=1)
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    response_type: str = "json"
    extract_path: str | None = None
    html_selectors: dict[str, str] | None = None


class _AnalysisParameter(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    name: str = Field(min_length=1)
    source: str = ""
    required: bool = False
    default: str | None = None
    description: str = ""


class _AnalysisAuthRecovery(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    trigger_on_status: list[int] = Field(default_factory=lambda: [401, 403])
    trigger_on_body: str | None = None
    recovery_page: str = Field(min_length=1)
    success_indicator: str | None = None


class _AnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    success: bool = True
    reason: str = ""
    recipe_type: str = "api"
    request: _AnalysisRequest | None = None
    parameters: list[_AnalysisParameter] = Field(default_factory=list)
    auth_recovery: _AnalysisAuthRecovery | None = None
    recipe_name_suggestion: str = ""
    recipe_description: str = ""


def _validate_placeholder_name(name: str) -> bool:
    # Valid Python identifier: starts with letter/underscore, contains alphanumeric/underscore.
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))


def _extract_placeholders(text: str) -> list[str]:
    return _PLACEHOLDER_PATTERN.findall(text)


def _apply_public_parameter_allowlist(
    url: str,
    body_template: str | None,
    parameters: list[RecipeParameter],
) -> tuple[str, str | None, list[RecipeParameter]]:
    """Drop non-obvious public parameters, and inline their defaults into templates.

    The analyzer LLM can over-parameterize query params (session ids, tracking, cache-busters)
    which causes wrong query terms at runtime. v1 policy:
    - Keep only a small allowlist of "obvious" public params.
    - For removed params, inline their `default` values into URL/body templates if provided.
    - If a removed param has no default but is referenced by a placeholder, keep it to avoid breaking execution.
    """

    kept: list[RecipeParameter] = []
    for p in parameters:
        if p.name in _PUBLIC_PARAMETER_ALLOWLIST:
            kept.append(p)
            continue

        placeholder = f"{{{p.name}}}"
        referenced = placeholder in url or (body_template is not None and placeholder in body_template)
        if p.default is not None:
            url = url.replace(placeholder, p.default)
            if body_template is not None:
                body_template = body_template.replace(placeholder, p.default)
            continue

        if referenced:
            kept.append(p)

    return url, body_template, kept


def _normalize_response_type(value: str) -> _ResponseType:
    normalized = value.lower().strip()
    if normalized in ("json", "html", "text"):
        return normalized
    raise ValueError(f"Invalid response_type: {value}. Must be one of ['html', 'json', 'text']")


class RecipeAnalyzer:
    """Analyzes session recordings to extract reusable recipes.

    The analyzer uses an LLM to identify which API call (the "money request")
    returned the data the user asked for, and extracts parameters that can
    be templated for future executions.
    """

    def __init__(self, llm: "BaseChatModel"):
        """Initialize analyzer.

        Args:
            llm: LLM instance to use for analysis
        """
        self.llm = llm

    async def analyze(
        self,
        recording: SessionRecording,
        final_url: str | None = None,
        page_html_snippet: str | None = None,
    ) -> Recipe | None:
        """Analyze a recording to extract a recipe.

        Args:
            recording: Session recording with network events
            final_url: The final page URL where data was found
            page_html_snippet: Snippet of page HTML for CSS selector extraction

        Returns:
            Extracted Recipe if successful, None if extraction failed
        """
        # Get API calls summary (may be empty for HTML-based recipes)
        api_calls = recording.get_api_calls()

        # Format API calls for analysis
        api_calls_data = []
        for req, resp in api_calls:
            call_data = {
                "url": req.url,
                "method": req.method,
                "status": resp.status,
                "content_type": resp.mime_type,
                "has_body": resp.body is not None,
                "post_data": req.post_data[:500] if req.post_data else None,
                "response_body": resp.body[:2000] if resp.body else None,
            }
            api_calls_data.append(call_data)

        # Use final navigation URL if not provided
        if not final_url and recording.navigation_urls:
            final_url = recording.navigation_urls[-1]

        # Build prompt with page info
        prompt = get_analysis_prompt(
            recording.task,
            recording.result,
            api_calls_data,
            final_url=final_url,
            page_html_snippet=page_html_snippet,
        )

        # Call LLM
        try:
            from browser_use.llm.messages import SystemMessage, UserMessage

            response = await self.llm.ainvoke([SystemMessage(content=ANALYSIS_SYSTEM_PROMPT), UserMessage(content=prompt)])

            # Parse response - browser-use returns ChatInvokeCompletion with .completion
            result = self._parse_analysis_response(response.completion)

            if not result or not result.get("success"):
                reason = result.get("reason", "Unknown") if result else "Failed to parse response"
                logger.info(f"Recipe analysis failed: {reason}")
                return None

            try:
                analysis = self._validate_and_normalize_analysis_output(result)
            except ValueError as ve:
                logger.warning(f"LLM output validation failed: {ve}")
                return None

            # Build recipe from analysis
            recipe = self._build_recipe(analysis, recording)
            return recipe

        except Exception as e:
            logger.error(f"Error during recipe analysis: {e}")
            return None

    def _parse_analysis_response(self, content: str) -> dict | None:
        """Parse the LLM's analysis response.

        Args:
            content: Raw LLM response content

        Returns:
            Parsed JSON dict or None
        """
        try:
            # Try to extract JSON from the response
            content = str(content).strip()

            # Handle markdown code blocks
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            try:
                parsed = json.JSONDecoder().decode(content)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse analysis response: {e}")
                return None

            return parsed

        except Exception as e:
            logger.warning(f"Failed to parse analysis response: {e}")
            return None

    def _validate_analysis_output(self, analysis: dict) -> tuple[bool, str]:
        """Backward-compatible validator wrapper.

        Older tests/callers expect a (bool, error) result. Newer code uses
        `_validate_and_normalize_analysis_output()` which raises ValueError on invalid output.
        """
        # If analysis explicitly failed, that's "valid" in the sense that analyze() returns None.
        if not analysis.get("success", True):
            return True, ""

        try:
            self._validate_and_normalize_analysis_output(analysis)
        except ValueError as ve:
            return False, str(ve)

        return True, ""

    def _validate_and_normalize_analysis_output(self, raw: dict) -> _AnalysisOutput:
        """Validate analyzer output before building or saving a recipe.

        Analyzer output is untrusted input. We validate and normalize it up-front
        so broken outputs do not get serialized into YAML.
        """
        try:
            analysis = _AnalysisOutput.model_validate(raw)
        except ValidationError as ve:
            raise ValueError(str(ve)) from ve

        if not analysis.success:
            raise ValueError(f"Analysis marked as failure: {analysis.reason or 'Unknown'}")

        if not analysis.request:
            raise ValueError("Missing or invalid 'request' section")

        # Normalize for downstream code.
        analysis.request.method = analysis.request.method.upper().strip()
        analysis.request.response_type = analysis.request.response_type.lower().strip()

        valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        if analysis.request.method not in valid_methods:
            raise ValueError(f"Invalid HTTP method: {analysis.request.method}. Must be one of {sorted(valid_methods)}")

        _normalize_response_type(analysis.request.response_type)

        url_lower = analysis.request.url.lower()
        if not url_lower.startswith("http://") and not url_lower.startswith("https://"):
            raise ValueError(f"URL must start with http:// or https://, got: {analysis.request.url[:50]}")

        parsed = urlparse(analysis.request.url)
        if not parsed.hostname:
            raise ValueError("Request URL must include a hostname")

        for placeholder in _extract_placeholders(analysis.request.url):
            if not _validate_placeholder_name(placeholder):
                raise ValueError(f"Invalid URL parameter placeholder: {{{placeholder}}}. Must be valid identifier.")

        if analysis.request.body_template is not None:
            for placeholder in _extract_placeholders(analysis.request.body_template):
                if not _validate_placeholder_name(placeholder):
                    raise ValueError(f"Invalid body_template placeholder: {{{placeholder}}}. Must be valid identifier.")

        if analysis.request.response_type == "html" and not analysis.request.html_selectors:
            raise ValueError("HTML recipes must include non-empty html_selectors")

        for p in analysis.parameters:
            if not _validate_placeholder_name(p.name):
                raise ValueError(f"Parameter name '{p.name}' is not a valid identifier")

        return analysis

    def _build_recipe(self, analysis: _AnalysisOutput, recording: SessionRecording) -> Recipe:
        """Build a Recipe object from analysis results.

        Args:
            analysis: Parsed analysis response
            recording: Original recording

        Returns:
            Recipe object with direct execution support if possible
        """
        # NEW: Build AuthRecovery if provided
        auth_data = analysis.auth_recovery
        auth_recovery = None
        if auth_data and auth_data.recovery_page:
            auth_recovery = AuthRecovery(
                trigger_on_status=auth_data.trigger_on_status,
                trigger_on_body=auth_data.trigger_on_body,
                recovery_page=auth_data.recovery_page,
                success_indicator=auth_data.success_indicator,
            )

        # Build parameters from analysis output.
        parameters_data = analysis.parameters
        parameters: list[RecipeParameter] = []
        for p in parameters_data:
            parameters.append(
                RecipeParameter(
                    name=p.name,
                    source=p.source or "query",
                    required=p.required,
                    default=p.default,
                    description=p.description,
                )
            )

        # Build RecipeRequest for direct execution (post-process templates/params first).
        request_data = analysis.request
        recipe_request = None
        if request_data and request_data.url:
            url, body_template, parameters = _apply_public_parameter_allowlist(
                request_data.url,
                request_data.body_template,
                parameters,
            )
            host = urlparse(url).hostname
            allowed = [host] if host else []
            recipe_request = RecipeRequest(
                url=url,
                method=request_data.method,
                headers=request_data.headers,
                body_template=body_template,
                response_type=_normalize_response_type(request_data.response_type),
                extract_path=request_data.extract_path,
                html_selectors=request_data.html_selectors,
                allowed_domains=allowed,
            )
            logger.info(f"Built RecipeRequest for direct execution: {recipe_request.url}")

        # LEGACY: Build money_request for backward compatibility
        money_request_data = {}  # Analyzer prompt no longer emits this field.
        money_request = None
        if money_request_data.get("endpoint"):
            money_request = MoneyRequest(
                endpoint=money_request_data.get("endpoint", ""),
                method=money_request_data.get("method", "GET"),
                content_type=money_request_data.get("content_type", "application/json"),
                response_path=money_request_data.get("response_path"),
                identifies_by=money_request_data.get("identifies_by"),
            )

        # LEGACY: Build navigation steps
        navigation_data: list[dict] = []
        navigation = []
        for n in navigation_data:
            if n and isinstance(n, dict):
                navigation.append(NavigationStep(url_pattern=n.get("url_pattern", ""), description=n.get("description", "")))

        # Build hints (legacy)
        hints = RecipeHints(navigation=navigation, money_request=money_request)

        # Generate recipe name if not provided
        recipe_name = analysis.recipe_name_suggestion
        if not recipe_name:
            # Generate from task
            recipe_name = recording.task[:30].lower().replace(" ", "-").replace("'", "").replace('"', "")

        return Recipe(
            name=recipe_name,
            description=analysis.recipe_description or recording.task,
            original_task=recording.task,
            request=recipe_request,  # Direct execution
            auth_recovery=auth_recovery,  # Auth recovery
            hints=hints,
            parameters=parameters,
            fallback=FallbackConfig(),
        )


class RecipeAnalysisResult:
    """Result of recipe analysis."""

    def __init__(
        self,
        success: bool,
        recipe: Recipe | None = None,
        reason: str = "",
    ):
        self.success = success
        self.recipe = recipe
        self.reason = reason

    def __bool__(self) -> bool:
        return self.success
