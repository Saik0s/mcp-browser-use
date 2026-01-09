"""Tests for the recipes module."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_server_browser_use.recipes.models import AuthRecovery, Recipe, RecipeRequest
from mcp_server_browser_use.recipes.runner import MAX_RESPONSE_SIZE, RecipeRunner

# --- Fixtures ---


@pytest.fixture
def recipe_with_direct_execution() -> Recipe:
    """Create a recipe that supports direct execution.

    Uses example.com which is a real resolvable domain (93.184.216.34).
    """
    return Recipe(
        name="test-recipe",
        description="Test recipe for unit tests",
        original_task="Search for test query",
        request=RecipeRequest(
            url="https://example.com/search?q={query}",
            method="GET",
            headers={"Accept": "application/json"},
            response_type="json",
            extract_path="results[*].name",
        ),
        auth_recovery=AuthRecovery(
            trigger_on_status=[401, 403],
            recovery_page="https://example.com/login",
        ),
    )


@pytest.fixture
def recipe_without_direct_execution() -> Recipe:
    """Create a legacy recipe without direct execution."""
    return Recipe(
        name="legacy-recipe",
        description="Legacy recipe without direct execution",
        original_task="Do something manually",
    )


@dataclass
class MockCDPSession:
    """Mock CDP session for testing."""

    session_id: str = "test-session-123"


@pytest.fixture
def mock_browser_session() -> MagicMock:
    """Create a mock browser session."""
    session = MagicMock()
    session.cdp_client = MagicMock()

    # Mock CDP session creation
    mock_cdp_session = MockCDPSession()
    session.get_or_create_cdp_session = AsyncMock(return_value=mock_cdp_session)

    # Mock CDP domain enable
    session.cdp_client.send = MagicMock()
    session.cdp_client.send.Page = MagicMock()
    session.cdp_client.send.Page.enable = AsyncMock()
    session.cdp_client.send.Page.navigate = AsyncMock(return_value={})
    session.cdp_client.send.Page.getFrameTree = AsyncMock(return_value={"frameTree": {"frame": {"url": "about:blank"}}})

    session.cdp_client.send.Runtime = MagicMock()
    session.cdp_client.send.Runtime.enable = AsyncMock()

    return session


# --- RecipeRequest Tests ---


class TestRecipeRequest:
    """Tests for RecipeRequest model."""

    def test_build_url_substitutes_params(self):
        request = RecipeRequest(url="https://api.example.com/search?q={query}&limit={limit}")
        result = request.build_url({"query": "test", "limit": "10"})
        assert result == "https://api.example.com/search?q=test&limit=10"

    def test_build_url_handles_missing_params(self):
        request = RecipeRequest(url="https://api.example.com/search?q={query}")
        result = request.build_url({})
        assert result == "https://api.example.com/search?q=%7Bquery%7D"

    def test_build_url_encodes_path_params_with_spaces(self):
        request = RecipeRequest(url="https://api.example.com/users/{user_id}/posts")
        result = request.build_url({"user_id": "a b"})
        assert result == "https://api.example.com/users/a%20b/posts"

    def test_build_url_encodes_special_chars(self):
        request = RecipeRequest(url="https://api.example.com/search/{query}")
        result = request.build_url({"query": "foo&bar=baz"})
        assert result == "https://api.example.com/search/foo%26bar%3Dbaz"

    def test_build_url_encodes_unicode(self):
        request = RecipeRequest(url="https://api.example.com/search/{query}")
        result = request.build_url({"query": "日本語"})
        assert "%E6%97%A5%E6%9C%AC%E8%AA%9E" in result

    def test_build_url_encodes_hash_in_path(self):
        request = RecipeRequest(url="https://api.example.com/tags/{tag}")
        result = request.build_url({"tag": "#python"})
        assert result == "https://api.example.com/tags/%23python"

    def test_build_body_substitutes_params(self):
        request = RecipeRequest(
            url="https://api.example.com/search",
            body_template='{"query": "{query}", "limit": {limit}}',
        )
        result = request.build_body({"query": "test", "limit": "10"})
        assert result == '{"query": "test", "limit": 10}'

    def test_build_body_returns_none_if_no_template(self):
        request = RecipeRequest(url="https://api.example.com/search")
        result = request.build_body({"query": "test"})
        assert result is None

    def test_to_fetch_options_includes_credentials(self):
        request = RecipeRequest(url="https://api.example.com/search")
        options = request.to_fetch_options({})
        assert options["credentials"] == "include"
        assert options["method"] == "GET"

    def test_to_fetch_options_includes_headers(self):
        request = RecipeRequest(
            url="https://api.example.com/search",
            headers={"Accept": "application/json", "X-Custom": "value"},
        )
        options = request.to_fetch_options({})
        assert options["headers"]["Accept"] == "application/json"
        assert options["headers"]["X-Custom"] == "value"

    def test_to_fetch_options_includes_body_for_post(self):
        request = RecipeRequest(
            url="https://api.example.com/search",
            method="POST",
            body_template='{"query": "{query}"}',
        )
        options = request.to_fetch_options({"query": "test"})
        assert options["method"] == "POST"
        assert options["body"] == '{"query": "test"}'


# --- Recipe Tests ---


class TestRecipe:
    """Tests for Recipe model."""

    def test_supports_direct_execution_true_with_request(self, recipe_with_direct_execution: Recipe):
        assert recipe_with_direct_execution.supports_direct_execution is True

    def test_supports_direct_execution_false_without_request(self, recipe_without_direct_execution: Recipe):
        assert recipe_without_direct_execution.supports_direct_execution is False


# --- RecipeRunner Tests ---


class TestRecipeRunner:
    """Tests for RecipeRunner."""

    @pytest.fixture
    def runner(self) -> RecipeRunner:
        return RecipeRunner(timeout=10.0)

    async def test_run_returns_error_for_recipe_without_request(
        self,
        runner: RecipeRunner,
        recipe_without_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        result = await runner.run(recipe_without_direct_execution, {}, mock_browser_session)
        assert result.success is False
        assert result.error is not None
        assert "no request config" in result.error.lower()

    async def test_run_gets_cdp_session(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock successful fetch response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": True,
                        "status": 200,
                        "body": '{"results": [{"name": "item1"}, {"name": "item2"}]}',
                    }
                }
            }
        )

        await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify CDP session was created
        mock_browser_session.get_or_create_cdp_session.assert_called_once()

        # Verify Page domain was enabled with session_id
        mock_browser_session.cdp_client.send.Page.enable.assert_called()
        enable_call = mock_browser_session.cdp_client.send.Page.enable.call_args
        assert enable_call.kwargs.get("session_id") == "test-session-123"

    async def test_run_navigates_with_session_id(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock successful fetch response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": True,
                        "status": 200,
                        "body": '{"results": [{"name": "item1"}]}',
                    }
                }
            }
        )

        await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify Page.navigate was called with session_id
        mock_browser_session.cdp_client.send.Page.navigate.assert_called()
        nav_call = mock_browser_session.cdp_client.send.Page.navigate.call_args
        assert nav_call.kwargs.get("session_id") == "test-session-123"
        assert "https://example.com" in nav_call.kwargs["params"]["url"]

    async def test_run_executes_fetch_with_session_id(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock successful fetch response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": True,
                        "status": 200,
                        "body": '{"results": [{"name": "item1"}]}',
                    }
                }
            }
        )

        await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify Runtime.evaluate was called with session_id
        mock_browser_session.cdp_client.send.Runtime.evaluate.assert_called()
        eval_call = mock_browser_session.cdp_client.send.Runtime.evaluate.call_args
        assert eval_call.kwargs.get("session_id") == "test-session-123"

    async def test_run_returns_success_with_extracted_data(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock successful fetch response with JSON data
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": True,
                        "status": 200,
                        "body": '{"results": [{"name": "item1"}, {"name": "item2"}]}',
                    }
                }
            }
        )

        result = await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is True
        assert result.status_code == 200
        # extract_path is "results[*].name"
        assert result.data == ["item1", "item2"]

    async def test_run_handles_http_error(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock 500 error response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": False,
                        "status": 500,
                        "body": "Internal Server Error",
                    }
                }
            }
        )

        result = await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is False
        assert result.status_code == 500
        assert result.error is not None
        assert "HTTP 500" in result.error

    async def test_run_triggers_auth_recovery_on_401(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock 401 response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": False,
                        "status": 401,
                        "body": "Unauthorized",
                    }
                }
            }
        )

        result = await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is False
        assert result.auth_recovery_triggered is True
        assert result.error is not None
        assert "recovery page" in result.error.lower()
        assert "https://example.com/login" in result.error

    async def test_run_skips_navigation_if_same_domain(
        self,
        runner: RecipeRunner,
        recipe_with_direct_execution: Recipe,
        mock_browser_session: MagicMock,
    ):
        # Mock current URL on same domain (example.com)
        mock_browser_session.cdp_client.send.Page.getFrameTree = AsyncMock(
            return_value={"frameTree": {"frame": {"url": "https://example.com/other"}}}
        )

        # Mock successful fetch response
        mock_browser_session.cdp_client.send.Runtime.evaluate = AsyncMock(
            return_value={
                "result": {
                    "value": {
                        "ok": True,
                        "status": 200,
                        "body": '{"results": []}',
                    }
                }
            }
        )

        await runner.run(recipe_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Page.navigate should NOT be called since we're already on the domain
        mock_browser_session.cdp_client.send.Page.navigate.assert_not_called()


# --- JMESPath Extraction Tests ---


class TestJMESPathExtraction:
    """Tests for JMESPath data extraction (uses runner.extract_data)."""

    def test_extract_simple_path(self):
        from mcp_server_browser_use.recipes.runner import extract_data

        data = {"foo": {"bar": "value"}}
        result = extract_data(data, "foo.bar")
        assert result == "value"

    def test_extract_array_expansion(self):
        from mcp_server_browser_use.recipes.runner import extract_data

        data = {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
        result = extract_data(data, "items[*].name")
        assert result == ["a", "b", "c"]

    def test_extract_nested_array(self):
        from mcp_server_browser_use.recipes.runner import extract_data

        data = {"results": [{"package": {"name": "pkg1"}}, {"package": {"name": "pkg2"}}]}
        result = extract_data(data, "results[*].package.name")
        assert result == ["pkg1", "pkg2"]

    def test_extract_missing_path_returns_none(self):
        from mcp_server_browser_use.recipes.runner import extract_data

        data = {"foo": "bar"}
        result = extract_data(data, "missing.path")
        assert result is None

    def test_extract_index_access(self):
        from mcp_server_browser_use.recipes.runner import extract_data

        data = {"items": ["first", "second", "third"]}
        # JMESPath uses [0] syntax for array index access
        result = extract_data(data, "items[0]")
        assert result == "first"


class TestMaxResponseSize:
    """Tests for MAX_RESPONSE_SIZE constant."""

    def test_max_response_size_is_1mb(self):
        assert MAX_RESPONSE_SIZE == 1_000_000

    def test_build_fetch_js_includes_max_size(self):
        runner = RecipeRunner()
        request = RecipeRequest(url="https://example.com/api")
        js_code = runner._build_fetch_js("https://example.com/api", {}, request.response_type)
        assert f"const MAX_SIZE = {MAX_RESPONSE_SIZE}" in js_code
        assert "bodyStr.slice(0, MAX_SIZE)" in js_code
        assert "truncated: truncated" in js_code


class TestRecipeCategorization:
    """Tests for recipe categorization and metadata fields."""

    def test_recipe_default_category(self):
        recipe = Recipe(name="test", description="", original_task="")
        assert recipe.category == "other"
        assert recipe.difficulty == "medium"
        assert recipe.tags == []

    def test_recipe_to_dict_includes_categorization(self):
        recipe = Recipe(
            name="github-repos",
            description="Search repos",
            original_task="Find repos",
            category="developer",
            subcategory="vcs",
            tags=["github", "api"],
            difficulty="easy",
            rate_limit_delay_ms=1000,
            max_response_size_bytes=500_000,
        )
        data = recipe.to_dict()
        assert data["category"] == "developer"
        assert data["subcategory"] == "vcs"
        assert data["tags"] == ["github", "api"]
        assert data["difficulty"] == "easy"
        assert data["rate_limit_delay_ms"] == 1000
        assert data["max_response_size_bytes"] == 500_000

    def test_recipe_from_dict_parses_categorization(self):
        data = {
            "name": "npm-search",
            "category": "developer",
            "subcategory": "packages",
            "tags": ["npm", "nodejs"],
            "difficulty": "trivial",
            "rate_limit_delay_ms": 500,
            "max_response_size_bytes": 2_000_000,
        }
        recipe = Recipe.from_dict(data)
        assert recipe.category == "developer"
        assert recipe.subcategory == "packages"
        assert recipe.tags == ["npm", "nodejs"]
        assert recipe.difficulty == "trivial"
        assert recipe.rate_limit_delay_ms == 500
        assert recipe.max_response_size_bytes == 2_000_000

    def test_recipe_auth_serialization(self):
        from mcp_server_browser_use.recipes.models import RecipeAuth

        recipe = Recipe(
            name="github-api",
            description="GitHub API",
            original_task="",
            recipe_auth=RecipeAuth(auth_type="bearer", key_name="Authorization", env_var="GITHUB_TOKEN"),
        )
        data = recipe.to_dict()
        assert data["recipe_auth"]["auth_type"] == "bearer"
        assert data["recipe_auth"]["env_var"] == "GITHUB_TOKEN"

        parsed = Recipe.from_dict(data)
        assert parsed.recipe_auth is not None
        assert parsed.recipe_auth.auth_type == "bearer"
        assert parsed.recipe_auth.env_var == "GITHUB_TOKEN"
