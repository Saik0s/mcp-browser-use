"""Tests for dashboard REST API endpoints using Starlette TestClient."""

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def client(monkeypatch):
    """Create a synchronous HTTP client for the FastMCP server."""
    # Set environment variables for testing
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")
    monkeypatch.setenv("MCP_RECIPES_ENABLED", "true")

    # Reload config module to pick up new env vars
    import importlib

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    # Update settings reference in server module before reloading
    import mcp_server_browser_use.server

    mcp_server_browser_use.server.settings = mcp_server_browser_use.config.settings
    importlib.reload(mcp_server_browser_use.server)

    from mcp_server_browser_use.server import serve

    server = serve()
    # Create Starlette TestClient for the ASGI app
    return TestClient(server.http_app())


@pytest.fixture
def client_recipes_disabled(monkeypatch):
    """Create a synchronous HTTP client with recipes disabled."""
    # Set environment variables for testing
    monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("MCP_LLM_MODEL_NAME", "gpt-4")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MCP_BROWSER_HEADLESS", "true")

    # Reload config module to pick up new env vars
    import importlib

    import mcp_server_browser_use.config

    importlib.reload(mcp_server_browser_use.config)

    # Directly disable recipes in the loaded settings
    mcp_server_browser_use.config.settings.recipes.enabled = False

    # Update settings reference in server module before reloading
    import mcp_server_browser_use.server

    mcp_server_browser_use.server.settings = mcp_server_browser_use.config.settings
    importlib.reload(mcp_server_browser_use.server)

    from mcp_server_browser_use.server import serve

    server = serve()
    # Create Starlette TestClient for the ASGI app
    return TestClient(server.http_app())


class TestHealthEndpoint:
    """Test /api/health endpoint."""

    def test_health_check_returns_ok(self, client):
        """Should return healthy status with server stats."""
        response = client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "memory_mb" in data
        assert "running_tasks" in data
        assert "stats" in data

    def test_health_check_response_structure(self, client):
        """Should have proper response structure."""
        response = client.get("/api/health")
        data = response.json()

        assert isinstance(data["uptime_seconds"], (int, float))
        assert isinstance(data["memory_mb"], (int, float))
        assert isinstance(data["running_tasks"], int)
        assert isinstance(data["tasks"], list)
        assert data["uptime_seconds"] >= 0
        assert data["memory_mb"] > 0


class TestTaskListEndpoint:
    """Test /api/tasks endpoint."""

    def test_task_list_returns_empty_initially(self, client):
        """Should return empty task list initially."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        assert "tasks" in data
        assert "count" in data
        assert isinstance(data["tasks"], list)

    def test_task_list_with_limit_parameter(self, client):
        """Should accept limit parameter."""
        response = client.get("/api/tasks?limit=5")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data["tasks"], list)
        assert len(data["tasks"]) <= 5

    def test_task_list_with_status_filter_valid(self, client):
        """Should filter by valid status."""
        response = client.get("/api/tasks?status=running")
        assert response.status_code == 200
        assert "tasks" in response.json()

    @pytest.mark.parametrize("status", ["running", "completed", "failed", "pending"])
    def test_task_list_all_valid_statuses(self, client, status):
        """Should accept all valid status values."""
        response = client.get(f"/api/tasks?status={status}")
        assert response.status_code == 200
        assert "tasks" in response.json()


class TestTaskGetEndpoint:
    """Test /api/tasks/{task_id} endpoint."""

    def test_task_get_not_found(self, client):
        """Should return 404 for non-existent task."""
        response = client.get("/api/tasks/nonexistent")
        assert response.status_code == 404


class TestDashboardHtmlEndpoint:
    """Test /dashboard endpoint."""

    def test_dashboard_serves_html(self, client):
        """Should serve dashboard HTML file."""
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert response.text  # Should have content

    def test_dashboard_html_is_valid(self, client):
        """Dashboard HTML should be valid markup."""
        response = client.get("/dashboard")
        content = response.text
        # Basic checks for HTML structure
        assert "<html" in content.lower() or "<!doctype" in content.lower()


class TestViewerHtmlEndpoint:
    """Test / endpoint."""

    def test_viewer_serves_html(self, client):
        """Should serve viewer HTML from root."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert response.text  # Should have content

    def test_viewer_html_is_valid(self, client):
        """Viewer HTML should be valid markup."""
        response = client.get("/")
        content = response.text
        # Basic checks for HTML structure
        assert "<html" in content.lower() or "<!doctype" in content.lower()


class TestRecipesListEndpoint:
    """Test /api/recipes endpoint."""

    def test_recipes_list_when_enabled(self, client):
        """Should return recipes list when feature is enabled."""
        response = client.get("/api/recipes")
        assert response.status_code == 200

        data = response.json()
        assert "recipes" in data
        assert "count" in data
        assert "recipes_directory" in data
        assert isinstance(data["recipes"], list)

    def test_recipes_list_disabled_returns_error(self, client_recipes_disabled):
        """Should return error when recipes feature is disabled."""
        response = client_recipes_disabled.get("/api/recipes")
        assert response.status_code == 503

    def test_recipes_list_structure(self, client):
        """Recipes list should have proper structure."""
        response = client.get("/api/recipes")
        data = response.json()

        for recipe in data["recipes"]:
            assert "name" in recipe
            assert "description" in recipe
            assert "success_rate" in recipe
            assert "usage_count" in recipe


class TestRecipeGetEndpoint:
    """Test /api/recipes/{name} GET endpoint."""

    def test_recipe_get_not_found(self, client):
        """Should return 404 for non-existent recipe."""
        response = client.get("/api/recipes/nonexistent_recipe")
        assert response.status_code == 404

    def test_recipe_get_disabled_returns_error(self, client_recipes_disabled):
        """Should return error when recipes feature is disabled."""
        response = client_recipes_disabled.get("/api/recipes/any_recipe")
        assert response.status_code == 503


class TestRecipeDeleteEndpoint:
    """Test /api/recipes/{name} DELETE endpoint."""

    def test_recipe_delete_not_found(self, client):
        """Should return 404 when recipe doesn't exist."""
        response = client.delete("/api/recipes/nonexistent_recipe")
        assert response.status_code == 404

    def test_recipe_delete_disabled_returns_error(self, client_recipes_disabled):
        """Should return error when recipes feature is disabled."""
        response = client_recipes_disabled.delete("/api/recipes/any_recipe")
        assert response.status_code == 503


class TestRecipeRunEndpoint:
    """Test /api/recipes/{name}/run POST endpoint."""

    def test_recipe_run_success_with_minimal_params(self, client):
        """Should successfully start recipe execution with minimal params."""
        response = client.post("/api/recipes/test_recipe/run", json={})
        # Should return 202 (Accepted) for async task or 404 if recipe not found
        assert response.status_code in (202, 404)

        if response.status_code == 202:
            data = response.json()
            assert "task_id" in data
            assert "message" in data

    def test_recipe_run_with_url_and_params(self, client):
        """Should accept URL and params in request body."""
        payload = {
            "url": "https://example.com",
            "params": {"param1": "value1"},
        }
        response = client.post("/api/recipes/test_recipe/run", json=payload)
        assert response.status_code in (202, 404)

    def test_recipe_run_disabled_returns_error(self, client_recipes_disabled):
        """Should return error when recipes feature is disabled."""
        response = client_recipes_disabled.post("/api/recipes/test_recipe/run", json={})
        assert response.status_code == 503


class TestLearnEndpoint:
    """Test /api/learn POST endpoint."""

    def test_learn_missing_task(self, client):
        """Should require task field in request."""
        response = client.post("/api/learn", json={})
        assert response.status_code == 400

    def test_learn_success_with_task_only(self, client):
        """Should successfully start learning session with task only."""
        payload = {"task": "Learn to search GitHub"}
        response = client.post("/api/learn", json=payload)
        assert response.status_code == 202

        data = response.json()
        assert "task_id" in data
        assert "learning_task" in data

    def test_learn_success_with_recipe_name(self, client):
        """Should accept optional recipe_name parameter."""
        payload = {
            "task": "Learn to search GitHub",
            "recipe_name": "github_search",
        }
        response = client.post("/api/learn", json=payload)
        assert response.status_code == 202

        data = response.json()
        assert "task_id" in data
        assert data["recipe_name"] == "github_search"

    def test_learn_disabled_returns_error(self, client_recipes_disabled):
        """Should return error when recipes feature is disabled."""
        payload = {"task": "Test task"}
        response = client_recipes_disabled.post("/api/learn", json=payload)
        assert response.status_code == 503


class TestEventsStreamEndpoint:
    """Test /api/events SSE endpoint."""

    @pytest.mark.skip(reason="SSE endpoints stream indefinitely and block TestClient")
    def test_events_stream_connection(self, client):
        """Should establish SSE connection and return event stream."""
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            assert response.headers.get("content-type") == "text/event-stream"

    @pytest.mark.skip(reason="SSE endpoints stream indefinitely and block TestClient")
    def test_events_stream_headers(self, client):
        """Should have proper SSE headers."""
        with client.stream("GET", "/api/events") as response:
            headers = response.headers
            assert headers.get("content-type") == "text/event-stream"
            assert headers.get("cache-control") == "no-cache"
            assert headers.get("connection") == "keep-alive"


class TestTaskLogsStreamEndpoint:
    """Test /api/tasks/{task_id}/logs SSE endpoint."""

    def test_task_logs_stream_not_found(self, client):
        """Should return 404 for non-existent task."""
        response = client.get("/api/tasks/nonexistent/logs")
        assert response.status_code == 404


class TestApiResponseConsistency:
    """Test consistency of API responses."""

    def test_json_response_format(self, client):
        """API endpoints should return valid JSON."""
        response = client.get("/api/health")
        assert response.status_code == 200
        # Should be parseable as JSON
        data = response.json()
        assert isinstance(data, dict)

    def test_error_response_format(self, client):
        """Error responses should be consistent."""
        response = client.get("/api/tasks/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    def test_api_endpoints_exist(self, client):
        """Core API endpoints should exist."""
        endpoints = [
            ("/api/health", "get"),
            ("/api/tasks", "get"),
            ("/api/recipes", "get"),
            ("/dashboard", "get"),
            ("/", "get"),
        ]

        for path, method in endpoints:
            if method == "get":
                response = client.get(path)
                # Should not be 404 (Not Found) - endpoint should exist
                assert response.status_code != 404, f"{path} endpoint not found"

        # Note: /api/events is SSE streaming endpoint, tested separately in TestEventsStreamEndpoint
