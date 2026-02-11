"""Recipe storage and persistence using YAML files."""

import logging
import os
import re
import tempfile
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import yaml
from anyio import to_thread

from .models import Recipe

logger = logging.getLogger(__name__)

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_RESPONSE_TYPES = {"json", "html", "text"}


def _slugify_name(name: str) -> str:
    """Convert an arbitrary recipe name into a stable filesystem-safe slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "recipe"


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text to `path` using temp + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


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
        """Get path for a recipe file (name is slugified)."""
        return self.directory / f"{_slugify_name(name)}.yaml"

    def _next_available_slug(self, base_slug: str) -> str:
        """Find an unused slug, using numeric suffixes (-2, -3, ...)."""
        for i in range(1, 10_000):
            slug = base_slug if i == 1 else f"{base_slug}-{i}"
            if not (self.directory / f"{slug}.yaml").exists():
                return slug
        raise RuntimeError(f"Failed to find available recipe name for base slug {base_slug!r}")

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

    async def load_async(self, name: str) -> Recipe | None:
        """Async wrapper for load() to avoid blocking the event loop."""
        return await to_thread.run_sync(self.load, name)

    def save(self, recipe: Recipe, *, overwrite: bool = False) -> Path:
        """Save a recipe to file.

        Args:
            recipe: Recipe to save
            overwrite: When true, replace any existing recipe file. When false, pick a unique name on collision.

        Returns:
            Path to saved file
        """
        base_slug = _slugify_name(recipe.name)
        if overwrite:
            slug = base_slug
        else:
            slug = base_slug if not (self.directory / f"{base_slug}.yaml").exists() else self._next_available_slug(base_slug)
        recipe.name = slug
        _validate_recipe_for_storage(recipe)
        path = self._recipe_path(slug)

        data = recipe.to_dict()
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        if not content.endswith("\n"):
            content += "\n"
        _atomic_write_text(path, content)

        logger.info(f"Saved recipe: {recipe.name} to {path}")
        return path

    async def save_async(self, recipe: Recipe, *, overwrite: bool = False) -> Path:
        """Async wrapper for save() to avoid blocking the event loop."""
        return await to_thread.run_sync(partial(self.save, recipe, overwrite=overwrite))

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

    async def delete_async(self, name: str) -> bool:
        """Async wrapper for delete() to avoid blocking the event loop."""
        return await to_thread.run_sync(self.delete, name)

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

    async def list_all_async(self) -> list[Recipe]:
        """Async wrapper for list_all() to avoid blocking the event loop."""
        return await to_thread.run_sync(self.list_all)

    def exists(self, name: str) -> bool:
        """Check if a recipe exists.

        Args:
            name: Recipe name to check

        Returns:
            True if recipe exists
        """
        return self._recipe_path(name).exists()

    async def exists_async(self, name: str) -> bool:
        """Async wrapper for exists() to avoid blocking the event loop."""
        return await to_thread.run_sync(self.exists, name)

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

        self.save(recipe, overwrite=True)

    async def record_usage_async(self, name: str, success: bool) -> None:
        """Async wrapper for record_usage() to avoid blocking the event loop."""
        await to_thread.run_sync(self.record_usage, name, success)

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
