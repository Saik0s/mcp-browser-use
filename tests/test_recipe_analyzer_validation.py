from collections.abc import Awaitable

import pytest

from mcp_server_browser_use.recipes.analyzer import RecipeAnalyzer
from mcp_server_browser_use.recipes.models import Recipe, RecipeRequest
from mcp_server_browser_use.recipes.store import RecipeStore


class _DummyLLM:
    name: str = "dummy"

    def ainvoke(self, messages: list[object], output_format: type[object] | None = None, **kwargs: object) -> Awaitable[object]:  # pragma: no cover
        raise AssertionError("Tests should not call the LLM")


def _analyzer() -> RecipeAnalyzer:
    # RecipeAnalyzer only needs llm for analyze(); validation helpers do not use it.
    return RecipeAnalyzer(_DummyLLM())


def test_analyzer_validation_rejects_non_dict_headers() -> None:
    analyzer = _analyzer()
    raw = {
        "success": True,
        "request": {
            "url": "https://example.com/search?q={query}",
            "method": "GET",
            "headers": [["Accept", "application/json"]],
            "response_type": "json",
        },
        "parameters": [{"name": "query", "source": "query", "required": True}],
    }

    with pytest.raises(ValueError, match="headers"):
        analyzer._validate_and_normalize_analysis_output(raw)


def test_analyzer_validation_rejects_body_template_non_string() -> None:
    analyzer = _analyzer()
    raw = {
        "success": True,
        "request": {
            "url": "https://example.com/search?q={query}",
            "method": "POST",
            "headers": {"Accept": "application/json"},
            "body_template": {"q": "{query}"},
            "response_type": "json",
        },
        "parameters": [{"name": "query", "source": "query", "required": True}],
    }

    with pytest.raises(ValueError, match="body_template"):
        analyzer._validate_and_normalize_analysis_output(raw)


def test_analyzer_validation_rejects_invalid_placeholder_names() -> None:
    analyzer = _analyzer()
    raw = {
        "success": True,
        "request": {
            "url": "https://example.com/search?q={not-valid}",
            "method": "GET",
            "headers": {},
            "response_type": "json",
        },
        "parameters": [{"name": "query", "source": "query", "required": True}],
    }

    with pytest.raises(ValueError, match="placeholder"):
        analyzer._validate_and_normalize_analysis_output(raw)


def test_analyzer_validation_normalizes_method_and_response_type() -> None:
    analyzer = _analyzer()
    raw = {
        "success": True,
        "request": {
            "url": "https://example.com/search?q={query}",
            "method": "post",
            "headers": {"Accept": "application/json"},
            "response_type": "JSON",
            "extract_path": "items[*].name",
        },
        "parameters": [{"name": "query", "source": "query", "required": True}],
        "recipe_name_suggestion": "example-search",
        "recipe_description": "Search example.com",
    }

    analysis = analyzer._validate_and_normalize_analysis_output(raw)
    assert analysis.request is not None
    assert analysis.request.method == "POST"
    assert analysis.request.response_type == "json"


def test_analyzer_validation_html_requires_selectors() -> None:
    analyzer = _analyzer()
    raw = {
        "success": True,
        "request": {
            "url": "https://example.com/search?q={query}",
            "method": "GET",
            "headers": {},
            "response_type": "html",
        },
        "parameters": [{"name": "query", "source": "query", "required": True}],
    }

    with pytest.raises(ValueError, match="html_selectors"):
        analyzer._validate_and_normalize_analysis_output(raw)


def test_store_save_rejects_invalid_request_types(tmp_path) -> None:
    store = RecipeStore(str(tmp_path))
    recipe = Recipe(
        name="example",
        description="desc",
        original_task="task",
        request=RecipeRequest(
            url="https://example.com/search?q={query}",
            method="GET",
            headers={"Accept": "application/json"},
            response_type="json",
        ),
    )

    # Inject an invalid runtime type without breaking static typing of the constructor.
    request_obj: object = recipe.request
    field_name = "body_template"
    setattr(request_obj, field_name, {"q": "{query}"})

    with pytest.raises(ValueError, match="body_template"):
        store.save(recipe)


def test_store_save_accepts_valid_recipe(tmp_path) -> None:
    store = RecipeStore(str(tmp_path))
    recipe = Recipe(
        name="example",
        description="desc",
        original_task="task",
        request=RecipeRequest(
            url="https://example.com/search?q={query}",
            method="get",
            headers={"Accept": "application/json"},
            response_type="JSON",
            allowed_domains=["example.com"],
        ),
    )

    path = store.save(recipe)
    loaded = store.load("example")
    assert path.exists()
    assert loaded is not None
    assert loaded.request is not None
    assert loaded.request.method == "GET"
    assert loaded.request.response_type == "json"


def test_store_save_is_atomic_on_replace_failure(tmp_path, monkeypatch) -> None:
    store = RecipeStore(str(tmp_path))
    recipe_v1 = Recipe(
        name="example",
        description="v1",
        original_task="task",
        request=RecipeRequest(
            url="https://example.com/search?q={query}",
            method="GET",
            headers={"Accept": "application/json"},
            response_type="json",
        ),
    )
    store.save(recipe_v1)

    path = tmp_path / "example.yaml"
    before = path.read_text(encoding="utf-8")

    import mcp_server_browser_use.recipes.store as store_module

    def _boom(src: object, dst: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(store_module.os, "replace", _boom)

    recipe_v2 = Recipe(
        name="example",
        description="v2",
        original_task="task",
        request=RecipeRequest(
            url="https://example.com/search?q={query}",
            method="GET",
            headers={"Accept": "application/json"},
            response_type="json",
        ),
    )

    with pytest.raises(OSError, match="boom"):
        store.save(recipe_v2)

    after = path.read_text(encoding="utf-8")
    assert after == before
    loaded = store.load("example")
    assert loaded is not None
    assert loaded.description == "v1"
    assert not list(tmp_path.glob(".example.yaml.tmp.*"))


def test_store_save_slugifies_and_suffixes_on_collision(tmp_path) -> None:
    store = RecipeStore(str(tmp_path))

    recipe_1 = Recipe(
        name="My Recipe!",
        description="v1",
        original_task="task",
        request=RecipeRequest(url="https://example.com/search?q={query}", method="GET", headers={"Accept": "application/json"}, response_type="json"),
    )
    path_1 = store.save(recipe_1)
    assert recipe_1.name == "my-recipe"
    assert path_1.name == "my-recipe.yaml"

    recipe_2 = Recipe(
        name="My Recipe",
        description="v2",
        original_task="task",
        request=RecipeRequest(url="https://example.com/search?q={query}", method="GET", headers={"Accept": "application/json"}, response_type="json"),
    )
    path_2 = store.save(recipe_2)
    assert recipe_2.name == "my-recipe-2"
    assert path_2.name == "my-recipe-2.yaml"


def test_store_record_usage_overwrites_existing_recipe(tmp_path) -> None:
    store = RecipeStore(str(tmp_path))
    recipe = Recipe(
        name="my-recipe",
        description="v1",
        original_task="task",
        request=RecipeRequest(url="https://example.com/search?q={query}", method="GET", headers={"Accept": "application/json"}, response_type="json"),
    )
    store.save(recipe, overwrite=True)
    store.record_usage("my-recipe", success=True)
    loaded = store.load("my-recipe")
    assert loaded is not None
    assert loaded.success_count == 1
