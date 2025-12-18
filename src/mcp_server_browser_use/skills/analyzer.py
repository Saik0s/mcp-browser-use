"""Skill analyzer for extracting skills from session recordings.

Uses an LLM to identify the "money request" (the API call that returns
the desired data) from recorded network traffic.
"""

import json
import logging
from typing import TYPE_CHECKING

from .models import AuthRecovery, FallbackConfig, MoneyRequest, NavigationStep, SessionRecording, Skill, SkillHints, SkillParameter, SkillRequest
from .prompts import ANALYSIS_SYSTEM_PROMPT, get_analysis_prompt

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

logger = logging.getLogger(__name__)


class SkillAnalyzer:
    """Analyzes session recordings to extract reusable skills.

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

    async def analyze(self, recording: SessionRecording) -> Skill | None:
        """Analyze a recording to extract a skill.

        Args:
            recording: Session recording with network events

        Returns:
            Extracted Skill if successful, None if no API found
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
                logger.info(f"Skill analysis failed: {reason}")
                return None

            # Build skill from analysis
            skill = self._build_skill(result, recording)
            return skill

        except Exception as e:
            logger.error(f"Error during skill analysis: {e}")
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

    def _build_skill(self, analysis: dict, recording: SessionRecording) -> Skill:
        """Build a Skill object from analysis results.

        Args:
            analysis: Parsed analysis response
            recording: Original recording

        Returns:
            Skill object with direct execution support if possible
        """
        # NEW: Build SkillRequest for direct execution
        request_data = analysis.get("request", {})
        skill_request = None
        if request_data.get("url"):
            skill_request = SkillRequest(
                url=request_data.get("url", ""),
                method=request_data.get("method", "GET"),
                headers=request_data.get("headers", {}),
                body_template=request_data.get("body_template"),
                response_type=request_data.get("response_type", "json"),
                extract_path=request_data.get("extract_path"),
                html_selectors=request_data.get("html_selectors"),
            )
            logger.info(f"Built SkillRequest for direct execution: {skill_request.url}")

        # NEW: Build AuthRecovery if provided
        auth_data = analysis.get("auth_recovery", {})
        auth_recovery = None
        if auth_data.get("recovery_page"):
            auth_recovery = AuthRecovery(
                trigger_on_status=auth_data.get("trigger_on_status", [401, 403]),
                trigger_on_body=auth_data.get("trigger_on_body"),
                recovery_page=auth_data.get("recovery_page", ""),
                success_indicator=auth_data.get("success_indicator"),
            )

        # Build parameters from top-level or nested in request
        parameters_data = analysis.get("parameters", [])
        parameters = [
            SkillParameter(
                name=p.get("name", ""),
                source=p.get("source", "query"),
                required=p.get("required", False),
                default=p.get("default"),
            )
            for p in parameters_data
        ]

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
        navigation_data = analysis.get("navigation_steps", [])
        navigation = [NavigationStep(url_pattern=n.get("url_pattern", ""), description=n.get("description", "")) for n in navigation_data]

        # Build hints (legacy)
        hints = SkillHints(navigation=navigation, money_request=money_request)

        # Generate skill name if not provided
        skill_name = analysis.get("skill_name_suggestion", "")
        if not skill_name:
            # Generate from task
            skill_name = recording.task[:30].lower().replace(" ", "-").replace("'", "").replace('"', "")

        return Skill(
            name=skill_name,
            description=analysis.get("skill_description", recording.task),
            original_task=recording.task,
            request=skill_request,  # NEW: Direct execution
            auth_recovery=auth_recovery,  # NEW: Auth recovery
            hints=hints,
            parameters=parameters,
            fallback=FallbackConfig(),
        )


class SkillAnalysisResult:
    """Result of skill analysis."""

    def __init__(
        self,
        success: bool,
        skill: Skill | None = None,
        reason: str = "",
    ):
        self.success = success
        self.skill = skill
        self.reason = reason

    def __bool__(self) -> bool:
        return self.success
