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
    setattr(request_obj, "body_template", {"q": "{query}"})

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
    assert sorted(p.name for p in tmp_path.iterdir()) == ["example.yaml"]
    assert loaded is not None
    assert loaded.request is not None
    assert loaded.request.method == "GET"
    assert loaded.request.response_type == "json"
