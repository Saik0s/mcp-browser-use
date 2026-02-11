"""Recipe storage and persistence using YAML files."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .models import Recipe

logger = logging.getLogger(__name__)

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_RESPONSE_TYPES = {"json", "html", "text"}

_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_-]+")
_SLUG_DASH_RUN_RE = re.compile(r"-{2,}")


def _slugify_name(name: str) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return "recipe"
    slug = _SLUG_INVALID_CHARS_RE.sub("-", raw)
    slug = _SLUG_DASH_RUN_RE.sub("-", slug).strip("-")
    return slug or "recipe"


def _validate_recipe_for_storage(recipe: Recipe) -> None:
    if not recipe.name or not recipe.name.strip():
        raise ValueError("Recipe.name must be non-empty")

    if recipe.request is None:
        return

    req = recipe.request
    if not isinstance(req.url, str) or not req.url.strip():
        raise ValueError("Recipe.request.url must be a non-empty string")

    parsed = urlparse(req.url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Recipe.request.url must be http(s), got scheme={parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("Recipe.request.url must include a hostname")

    if not isinstance(req.method, str):
        raise ValueError("Recipe.request.method must be a string")
    req.method = req.method.upper().strip()
    if req.method not in _ALLOWED_METHODS:
        raise ValueError(f"Recipe.request.method must be one of {sorted(_ALLOWED_METHODS)}, got {req.method!r}")

    if not isinstance(req.response_type, str):
        raise ValueError("Recipe.request.response_type must be a string")
    normalized = req.response_type.lower().strip()
    if normalized not in _ALLOWED_RESPONSE_TYPES:
        raise ValueError(f"Recipe.request.response_type must be one of {sorted(_ALLOWED_RESPONSE_TYPES)}, got {normalized!r}")
    if normalized == "json":
        req.response_type = "json"
    elif normalized == "html":
        req.response_type = "html"
    else:
        req.response_type = "text"

    if req.headers is None or not isinstance(req.headers, dict):
        raise ValueError("Recipe.request.headers must be a dict")
    for k, v in req.headers.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("Recipe.request.headers must be dict[str, str]")

    if req.body_template is not None and not isinstance(req.body_template, str):
        raise ValueError("Recipe.request.body_template must be a string or None")

    if req.extract_path is not None and not isinstance(req.extract_path, str):
        raise ValueError("Recipe.request.extract_path must be a string or None")

    if req.html_selectors is not None:
        if not isinstance(req.html_selectors, dict):
            raise ValueError("Recipe.request.html_selectors must be a dict or None")
        for k, v in req.html_selectors.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("Recipe.request.html_selectors must be dict[str, str]")

    if not isinstance(req.allowed_domains, list) or any(not isinstance(d, str) for d in req.allowed_domains):
        raise ValueError("Recipe.request.allowed_domains must be list[str]")


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
        slug = _slugify_name(name)
        return self.directory / f"{slug}.yaml"

    def _find_recipe_path(self, name: str) -> Path | None:
        """Find the YAML file path for a recipe name, handling slug collisions."""
        slug = _slugify_name(name)
        base = self.directory / f"{slug}.yaml"

        def _matches(path: Path) -> bool:
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception:
                return False
            if not isinstance(data, dict):
                return False
            return str(data.get("name") or "") == name

        if base.exists() and _matches(base):
            return base

        for path in sorted(self.directory.glob(f"{slug}-*.yaml")):
            if path.is_file() and _matches(path):
                return path
        return None

    def load(self, name: str) -> Recipe | None:
        """Load a recipe by name.

        Args:
            name: Recipe name (used as filename base)

        Returns:
            Recipe if found, None otherwise
        """
        path = self._find_recipe_path(name)

        if path is None or not path.exists():
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
        _validate_recipe_for_storage(recipe)
        existing = self._find_recipe_path(recipe.name)
        if existing is not None:
            path = existing
        else:
            path = self._recipe_path(recipe.name)
            if path.exists():
                slug = _slugify_name(recipe.name)
                for i in range(2, 10_000):
                    candidate = self.directory / f"{slug}-{i}.yaml"
                    if not candidate.exists():
                        path = candidate
                        break
                else:
                    raise ValueError(f"Unable to resolve recipe name collision for slug {slug!r}")

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
        path = self._find_recipe_path(name) or self._recipe_path(name)

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
        return self._find_recipe_path(name) is not None

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
