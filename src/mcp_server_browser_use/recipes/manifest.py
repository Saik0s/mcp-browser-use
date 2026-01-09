"""Recipe manifest schema for batch recipe learning.

The manifest defines recipes to be learned and their metadata. Used by the
batch learner to systematically discover and create recipes from known sites.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from mcp_server_browser_use.recipes.models import RecipeCategory, RecipeDifficulty


class RecipeManifestEntry(BaseModel):
    """A single recipe definition in the manifest."""

    name: str = Field(..., description="Unique recipe identifier (e.g., 'npm-search')")
    description: str = Field(..., description="What this recipe does")
    learning_task: str = Field(..., description="Task prompt for the agent to learn this recipe")
    example_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Example parameters for unattended batch learning",
    )

    category: RecipeCategory = "other"
    subcategory: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: RecipeDifficulty = "medium"

    requires_auth: bool = False
    auth_env_var: str | None = None
    rate_limit_delay_ms: int = 0
    max_response_size_bytes: int = 1_000_000

    enabled: bool = True
    priority: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("name must be alphanumeric with dashes/underscores")
        return v.lower()


class CategoryDefinition(BaseModel):
    """Category metadata for organizing recipes."""

    name: RecipeCategory
    display_name: str = ""
    description: str = ""
    subcategories: list[str] = Field(default_factory=list)
    icon: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.display_name:
            self.display_name = self.name.title()


class RecipeManifest(BaseModel):
    """Complete recipe manifest with categories and entries."""

    version: str = "1.0"
    name: str = "default"
    description: str = ""

    categories: list[CategoryDefinition] = Field(default_factory=list)
    recipes: list[RecipeManifestEntry] = Field(default_factory=list)

    @field_validator("recipes")
    @classmethod
    def validate_unique_names(cls, v: list[RecipeManifestEntry]) -> list[RecipeManifestEntry]:
        names = [r.name for r in v]
        if len(names) != len(set(names)):
            duplicates = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate recipe names: {set(duplicates)}")
        return v

    def iter_recipes(self) -> Iterator[RecipeManifestEntry]:
        for recipe in self.recipes:
            if recipe.enabled:
                yield recipe

    def iter_by_category(self, category: RecipeCategory) -> Iterator[RecipeManifestEntry]:
        for recipe in self.iter_recipes():
            if recipe.category == category:
                yield recipe

    def iter_by_difficulty(self, difficulty: RecipeDifficulty) -> Iterator[RecipeManifestEntry]:
        for recipe in self.iter_recipes():
            if recipe.difficulty == difficulty:
                yield recipe

    def iter_requiring_auth(self) -> Iterator[RecipeManifestEntry]:
        for recipe in self.iter_recipes():
            if recipe.requires_auth:
                yield recipe

    def iter_no_auth(self) -> Iterator[RecipeManifestEntry]:
        for recipe in self.iter_recipes():
            if not recipe.requires_auth:
                yield recipe

    def filter(
        self,
        category: RecipeCategory | None = None,
        difficulty: RecipeDifficulty | None = None,
        requires_auth: bool | None = None,
        tags: list[str] | None = None,
    ) -> list[RecipeManifestEntry]:
        results = []
        for recipe in self.iter_recipes():
            if category and recipe.category != category:
                continue
            if difficulty and recipe.difficulty != difficulty:
                continue
            if requires_auth is not None and recipe.requires_auth != requires_auth:
                continue
            if tags and not any(t in recipe.tags for t in tags):
                continue
            results.append(recipe)
        return results

    def get_recipe(self, name: str) -> RecipeManifestEntry | None:
        for recipe in self.recipes:
            if recipe.name == name:
                return recipe
        return None

    def recipe_count(self) -> int:
        return len([r for r in self.recipes if r.enabled])


def load_manifest(path: Path | str) -> RecipeManifest:
    """Load and validate a recipe manifest from YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    return RecipeManifest.model_validate(data)


def load_manifest_from_string(content: str) -> RecipeManifest:
    """Load and validate a recipe manifest from YAML string."""
    data = yaml.safe_load(content)
    return RecipeManifest.model_validate(data)


ManifestFormat = Literal["yaml", "json"]


def save_manifest(manifest: RecipeManifest, path: Path | str, fmt: ManifestFormat = "yaml") -> None:
    """Save manifest to file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "yaml":
        with path.open("w") as f:
            yaml.safe_dump(manifest.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
    else:
        path.write_text(manifest.model_dump_json(indent=2))
