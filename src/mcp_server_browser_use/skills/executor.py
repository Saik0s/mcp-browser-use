"""Skill executor for hint injection and result validation."""

import logging

from .models import Skill
from .prompts import LEARNING_MODE_SUFFIX, get_execution_hints

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Executes skills by injecting hints into agent prompts."""

    def inject_hints(self, task: str, skill: Skill, params: dict | None = None) -> str:
        """Augment task prompt with skill hints.

        Args:
            task: Original task description
            skill: Skill with hints to inject
            params: Optional parameters to substitute in hints

        Returns:
            Augmented task prompt with hints
        """
        params = params or {}

        # Get formatted hints from skill
        hints_text = skill.hints.to_prompt(params)

        if not hints_text.strip():
            # No hints to inject, return original task
            return task

        # Build execution prompt with hints
        execution_prompt = get_execution_hints(skill.name, hints_text)
        return f"{execution_prompt}{task}"

    def inject_learning_mode(self, task: str) -> str:
        """Augment task prompt for learning/API discovery mode.

        Args:
            task: Original task description

        Returns:
            Task with API discovery instructions appended
        """
        return f"{task}\n{LEARNING_MODE_SUFFIX}"

    def validate_result(
        self,
        result: str,
        skill: Skill,
    ) -> bool:
        """Validate execution result against skill expectations.

        For now, just check that result is non-empty.
        Future: Compare against expected response schema.

        Args:
            result: Agent result string
            skill: Skill used for execution

        Returns:
            True if result appears valid
        """
        if not result or not result.strip():
            return False

        # Basic validation: result exists
        # TODO: Add schema validation when we have response schemas
        return True
