"""Recipe analyzer for extracting recipes from session recordings.

Uses an LLM to identify the "money request" (the API call that returns
the desired data) from recorded network traffic.
"""

import json
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .models import AuthRecovery, FallbackConfig, MoneyRequest, NavigationStep, Recipe, RecipeHints, RecipeParameter, RecipeRequest, SessionRecording
from .prompts import ANALYSIS_SYSTEM_PROMPT, get_analysis_prompt

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

logger = logging.getLogger(__name__)


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

    async def analyze(self, recording: SessionRecording) -> Recipe | None:
        """Analyze a recording to extract a recipe.

        Args:
            recording: Session recording with network events

        Returns:
            Extracted Recipe if successful, None if no API found
        """
        # Get API calls summary
        api_calls = recording.get_api_calls()

        if not api_calls:
            logger.warning("No API calls found in recording")
            return None

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

        # Build prompt
        prompt = get_analysis_prompt(recording.task, recording.result, api_calls_data)

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

            # Validate LLM output before building recipe
            is_valid, validation_error = self._validate_analysis_output(result)
            if not is_valid:
                logger.warning(f"LLM output validation failed: {validation_error}")
                return None

            # Build recipe from analysis
            recipe = self._build_recipe(result, recording)
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

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse analysis response: {e}")
            return None

    def _validate_analysis_output(self, analysis: dict) -> tuple[bool, str]:
        """Validate LLM analysis output before building recipe.

        Args:
            analysis: Parsed analysis response from LLM

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is empty.
        """
        # If analysis explicitly failed, that's valid (we return None in analyze())
        if not analysis.get("success", True):
            return True, ""

        # Validate request section
        request_data = analysis.get("request")
        if not request_data or not isinstance(request_data, dict):
            return False, "Missing or invalid 'request' section"

        # Validate URL exists and has valid scheme
        url = request_data.get("url")
        if not url or not isinstance(url, str):
            return False, "Missing or invalid 'url' in request"

        url_lower = url.lower()
        if not url_lower.startswith("http://") and not url_lower.startswith("https://"):
            return False, f"URL must start with http:// or https://, got: {url[:50]}"

        # Validate URL parameter placeholders are valid identifiers
        # Matches {param_name} patterns
        placeholder_pattern = re.compile(r"\{([^}]+)\}")
        placeholders = placeholder_pattern.findall(url)
        for placeholder in placeholders:
            # Valid Python identifier: starts with letter/underscore, contains alphanumeric/underscore
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", placeholder):
                return False, f"Invalid URL parameter placeholder: {{{placeholder}}}. Must be valid identifier."

        # Validate HTTP method
        method = request_data.get("method", "GET")
        valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        if not isinstance(method, str) or method.upper() not in valid_methods:
            return False, f"Invalid HTTP method: {method}. Must be one of {valid_methods}"

        # Validate response_type
        response_type = request_data.get("response_type", "json")
        valid_response_types = {"json", "html", "text"}
        if not isinstance(response_type, str) or response_type.lower() not in valid_response_types:
            return False, f"Invalid response_type: {response_type}. Must be one of {valid_response_types}"

        # Validate parameters list
        parameters = analysis.get("parameters", [])
        if parameters and isinstance(parameters, list):
            for i, param in enumerate(parameters):
                if not isinstance(param, dict):
                    return False, f"Parameter at index {i} must be a dict"
                param_name = param.get("name")
                if not param_name or not isinstance(param_name, str) or not param_name.strip():
                    return False, f"Parameter at index {i} has missing or empty 'name'"
                # Validate param name is valid identifier
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", param_name):
                    return False, f"Parameter name '{param_name}' is not a valid identifier"

        return True, ""

    def _build_recipe(self, analysis: dict, recording: SessionRecording) -> Recipe:
        """Build a Recipe object from analysis results.

        Args:
            analysis: Parsed analysis response
            recording: Original recording

        Returns:
            Recipe object with direct execution support if possible
        """
        # Build RecipeRequest for direct execution
        request_data = analysis.get("request", {})
        recipe_request = None
        if request_data.get("url"):
            url = request_data.get("url", "")
            host = urlparse(url).hostname
            allowed = [host] if host else []
            recipe_request = RecipeRequest(
                url=url,
                method=request_data.get("method", "GET"),
                headers=request_data.get("headers", {}),
                body_template=request_data.get("body_template"),
                response_type=request_data.get("response_type", "json"),
                extract_path=request_data.get("extract_path"),
                html_selectors=request_data.get("html_selectors"),
                allowed_domains=allowed,
            )
            logger.info(f"Built RecipeRequest for direct execution: {recipe_request.url}")

        # NEW: Build AuthRecovery if provided
        auth_data = analysis.get("auth_recovery") or {}
        auth_recovery = None
        if isinstance(auth_data, dict) and auth_data.get("recovery_page"):
            auth_recovery = AuthRecovery(
                trigger_on_status=auth_data.get("trigger_on_status", [401, 403]),
                trigger_on_body=auth_data.get("trigger_on_body"),
                recovery_page=auth_data.get("recovery_page", ""),
                success_indicator=auth_data.get("success_indicator"),
            )

        # Build parameters from top-level or nested in request
        parameters_data = analysis.get("parameters") or []
        parameters = []
        for p in parameters_data:
            if p and isinstance(p, dict):
                parameters.append(
                    RecipeParameter(
                        name=p.get("name", ""),
                        source=p.get("source", "query"),
                        required=p.get("required", False),
                        default=p.get("default"),
                    )
                )

        # LEGACY: Build money_request for backward compatibility
        money_request_data = analysis.get("money_request", {})
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
        navigation_data = analysis.get("navigation_steps") or []
        navigation = []
        for n in navigation_data:
            if n and isinstance(n, dict):
                navigation.append(NavigationStep(url_pattern=n.get("url_pattern", ""), description=n.get("description", "")))

        # Build hints (legacy)
        hints = RecipeHints(navigation=navigation, money_request=money_request)

        # Generate recipe name if not provided
        recipe_name = analysis.get("recipe_name_suggestion", "")
        if not recipe_name:
            # Generate from task
            recipe_name = recording.task[:30].lower().replace(" ", "-").replace("'", "").replace('"', "")

        return Recipe(
            name=recipe_name,
            description=analysis.get("recipe_description", recording.task),
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
