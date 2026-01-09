"""Recipe storage and persistence using YAML files."""

import logging
import os
from datetime import datetime
from pathlib import Path

import yaml

from .models import Recipe

logger = logging.getLogger(__name__)


def get_default_recipes_dir() -> Path:
    """Get the default recipes directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / ".config")).expanduser()
    else:
        base = Path("~/.config").expanduser()

    return base / "browser-recipes"


class RecipeStore:
    """Manages recipe storage in YAML files."""

    def __init__(self, directory: str | None = None):
        """Initialize recipe store.

        Args:
            directory: Path to recipes directory. If None, uses default.
        """
        if directory:
            self.directory = Path(directory).expanduser()
        else:
            self.directory = get_default_recipes_dir()

        self.directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Recipes directory: {self.directory}")

    def _recipe_path(self, name: str) -> Path:
        """Get path for a recipe file."""
        # Sanitize name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())
        return self.directory / f"{safe_name}.yaml"

    def load(self, name: str) -> Recipe | None:
        """Load a recipe by name.

        Args:
            name: Recipe name (used as filename base)

        Returns:
            Recipe if found, None otherwise
        """
        path = self._recipe_path(name)

        if not path.exists():
            logger.warning(f"Recipe not found: {name} (expected at {path})")
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                logger.warning(f"Empty recipe file: {path}")
                return None

            recipe = Recipe.from_dict(data)
            logger.debug(f"Loaded recipe: {recipe.name}")
            return recipe

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in recipe file {path}: {e}")
            return None
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Invalid recipe definition in {path}: {e}")
            return None

    def save(self, recipe: Recipe) -> Path:
        """Save a recipe to file.

        Args:
            recipe: Recipe to save

        Returns:
            Path to saved file
        """
        path = self._recipe_path(recipe.name)

        data = recipe.to_dict()

        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        logger.info(f"Saved recipe: {recipe.name} to {path}")
        return path

    def delete(self, name: str) -> bool:
        """Delete a recipe by name.

        Args:
            name: Recipe name to delete

        Returns:
            True if deleted, False if not found
        """
        path = self._recipe_path(name)

        if not path.exists():
            return False

        path.unlink()
        logger.info(f"Deleted recipe: {name}")
        return True

    def list_all(self) -> list[Recipe]:
        """List all available recipes.

        Returns:
            List of all recipes in the store
        """
        recipes = []

        for path in self.directory.glob("*.yaml"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if data:
                    recipe = Recipe.from_dict(data)
                    recipes.append(recipe)
            except Exception as e:
                logger.warning(f"Failed to load recipe from {path}: {e}")
                continue

        return sorted(recipes, key=lambda r: r.name)

    def exists(self, name: str) -> bool:
        """Check if a recipe exists.

        Args:
            name: Recipe name to check

        Returns:
            True if recipe exists
        """
        return self._recipe_path(name).exists()

    def record_usage(self, name: str, success: bool) -> None:
        """Record recipe usage statistics.

        Args:
            name: Recipe name
            success: Whether execution was successful
        """
        recipe = self.load(name)
        if not recipe:
            return

        recipe.last_used = datetime.now()
        if success:
            recipe.success_count += 1
        else:
            recipe.failure_count += 1

        self.save(recipe)

    def to_yaml(self, recipe: Recipe) -> str:
        """Convert recipe to YAML string.

        Args:
            recipe: Recipe to convert

        Returns:
            YAML string representation
        """
        return yaml.dump(recipe.to_dict(), default_flow_style=False, sort_keys=False, allow_unicode=True)

    def from_yaml(self, yaml_content: str) -> Recipe:
        """Parse recipe from YAML string.

        Args:
            yaml_content: YAML string

        Returns:
            Parsed Recipe

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

        return Recipe.from_dict(data)
