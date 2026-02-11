from __future__ import annotations

import pytest

from mcp_server_browser_use.recipes.models import Recipe, RecipeRequest
from mcp_server_browser_use.recipes.store import RecipeStore


@pytest.mark.asyncio
async def test_recipe_store_async_wrappers(tmp_path) -> None:
    store = RecipeStore(directory=str(tmp_path))
    recipe = Recipe(
        name="example",
        description="d",
        original_task="t",
        request=RecipeRequest(
            url="https://example.com/search?q=test",
            method="GET",
            headers={"Accept": "application/json"},
            response_type="json",
        ),
    )

    saved_path = await store.save_async(recipe)
    assert saved_path.exists()

    loaded = await store.load_async("example")
    assert loaded is not None
    assert loaded.name == "example"
    assert loaded.request is not None
    assert loaded.request.url == "https://example.com/search?q=test"

    all_recipes = await store.list_all_async()
    assert [r.name for r in all_recipes] == ["example"]

    exists = await store.exists_async("example")
    assert exists is True
