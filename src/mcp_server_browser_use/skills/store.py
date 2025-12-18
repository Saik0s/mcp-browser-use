"""Skill storage and persistence using YAML files."""

import logging
import os
from datetime import datetime
from pathlib import Path

import yaml

from .models import Skill

logger = logging.getLogger(__name__)


def get_default_skills_dir() -> Path:
    """Get the default skills directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / ".config")).expanduser()
    else:
        base = Path("~/.config").expanduser()

    return base / "browser-skills"


class SkillStore:
    """Manages skill storage in YAML files."""

    def __init__(self, directory: str | None = None):
        """Initialize skill store.

        Args:
            directory: Path to skills directory. If None, uses default.
        """
        if directory:
            self.directory = Path(directory).expanduser()
        else:
            self.directory = get_default_skills_dir()

        self.directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Skills directory: {self.directory}")

    def _skill_path(self, name: str) -> Path:
        """Get path for a skill file."""
        # Sanitize name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())
        return self.directory / f"{safe_name}.yaml"

    def load(self, name: str) -> Skill | None:
        """Load a skill by name.

        Args:
            name: Skill name (used as filename base)

        Returns:
            Skill if found, None otherwise
        """
        path = self._skill_path(name)

        if not path.exists():
            logger.warning(f"Skill not found: {name} (expected at {path})")
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                logger.warning(f"Empty skill file: {path}")
                return None

            skill = Skill.from_dict(data)
            logger.debug(f"Loaded skill: {skill.name}")
            return skill

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in skill file {path}: {e}")
            return None
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Invalid skill definition in {path}: {e}")
            return None

    def save(self, skill: Skill) -> Path:
        """Save a skill to file.

        Args:
            skill: Skill to save

        Returns:
            Path to saved file
        """
        path = self._skill_path(skill.name)

        data = skill.to_dict()

        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        logger.info(f"Saved skill: {skill.name} to {path}")
        return path

    def delete(self, name: str) -> bool:
        """Delete a skill by name.

        Args:
            name: Skill name to delete

        Returns:
            True if deleted, False if not found
        """
        path = self._skill_path(name)

        if not path.exists():
            return False

        path.unlink()
        logger.info(f"Deleted skill: {name}")
        return True

    def list_all(self) -> list[Skill]:
        """List all available skills.

        Returns:
            List of all skills in the store
        """
        skills = []

        for path in self.directory.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if data:
                    skill = Skill.from_dict(data)
                    skills.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load skill from {path}: {e}")
                continue

        return sorted(skills, key=lambda s: s.name)

    def exists(self, name: str) -> bool:
        """Check if a skill exists.

        Args:
            name: Skill name to check

        Returns:
            True if skill exists
        """
        return self._skill_path(name).exists()

    def record_usage(self, name: str, success: bool) -> None:
        """Record skill usage statistics.

        Args:
            name: Skill name
            success: Whether execution was successful
        """
        skill = self.load(name)
        if not skill:
            return

        skill.last_used = datetime.now()
        if success:
            skill.success_count += 1
        else:
            skill.failure_count += 1

        self.save(skill)

    def to_yaml(self, skill: Skill) -> str:
        """Convert skill to YAML string.

        Args:
            skill: Skill to convert

        Returns:
            YAML string representation
        """
        return yaml.dump(skill.to_dict(), default_flow_style=False, sort_keys=False, allow_unicode=True)

    def from_yaml(self, yaml_content: str) -> Skill:
        """Parse skill from YAML string.

        Args:
            yaml_content: YAML string

        Returns:
            Parsed Skill

        Raises:
            ValueError: If YAML is invalid or missing required fields
        """
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from e

        if not data:
            raise ValueError("Empty YAML content")

        if "name" not in data:
            raise ValueError("Missing required field: name")

        return Skill.from_dict(data)
