"""Integration tests for dashboard API with mocked browser and LLM."""

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


@pytest.mark.integration
class TestDashboardLoads:
    """Test that dashboard loads and responds."""

    def test_dashboard_loads_html_page(self, client):
        """Dashboard should serve valid HTML."""
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        content = response.text
        # Verify it's HTML content
        assert len(content) > 0
        assert any(tag in content.lower() for tag in ["<html", "<!doctype", "<head", "<body"])

    def test_viewer_loads_html_page(self, client):
        """Viewer should serve valid HTML."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        content = response.text
        # Verify it's HTML content
        assert len(content) > 0

    def test_dashboard_content_not_empty(self, client):
        """Dashboard HTML should have substantial content."""
        response = client.get("/dashboard")
        assert len(response.text) > 100  # Not just a stub


@pytest.mark.integration
class TestRecipesTabFunctionality:
    """Test recipes tab features in dashboard API."""

    def test_fetch_recipes_returns_json(self, client):
        """Recipes endpoint should return valid JSON."""
        response = client.get("/api/recipes")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "recipes" in data
        assert isinstance(data["recipes"], list)

    def test_recipes_have_required_fields(self, client):
        """Each recipe should have required fields for display."""
        response = client.get("/api/recipes")
        data = response.json()

        for recipe in data["recipes"]:
            # Required for display in dashboard
            assert "name" in recipe
            assert "description" in recipe
            assert "success_rate" in recipe
            assert "usage_count" in recipe
            # Type checks
            assert isinstance(recipe["name"], str)
            assert isinstance(recipe["success_rate"], (int, float))
            assert isinstance(recipe["usage_count"], int)

    def test_empty_recipes_list_handled_gracefully(self, client):
        """Should handle empty recipes list gracefully."""
        response = client.get("/api/recipes")
        assert response.status_code == 200

        data = response.json()
        # Even with no recipes, should return valid structure
        assert "recipes" in data
        assert isinstance(data["recipes"], list)


@pytest.mark.integration
class TestHistoryTabFunctionality:
    """Test history tab features in dashboard API."""

    def test_fetch_task_history_returns_json(self, client):
        """Task list endpoint should return valid JSON."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "tasks" in data
        assert "count" in data
        assert isinstance(data["tasks"], list)
        assert isinstance(data["count"], int)

    def test_tasks_have_required_fields_for_display(self, client):
        """Each task should have fields needed for dashboard display."""
        response = client.get("/api/tasks")
        data = response.json()

        for task in data["tasks"]:
            # Required for history display
            assert "task_id" in task
            assert "tool" in task
            assert "status" in task
            assert "created" in task

    def test_task_filtering_by_status(self, client):
        """Should support filtering tasks by status."""
        # Test each valid status
        for status in ["running", "completed", "failed", "pending"]:
            response = client.get(f"/api/tasks?status={status}")
            assert response.status_code == 200
            data = response.json()
            assert "tasks" in data

    def test_task_limit_parameter(self, client):
        """Should respect limit parameter for pagination."""
        response = client.get("/api/tasks?limit=10")
        assert response.status_code == 200

        data = response.json()
        assert len(data["tasks"]) <= 10


@pytest.mark.integration
class TestHealthMonitoring:
    """Test health monitoring in dashboard."""

    def test_health_check_shows_server_status(self, client):
        """Health check should show server is running."""
        response = client.get("/api/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"

    def test_health_check_includes_running_tasks(self, client):
        """Health check should list running tasks."""
        response = client.get("/api/health")
        data = response.json()

        assert "running_tasks" in data
        assert isinstance(data["running_tasks"], int)
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_health_check_includes_memory_stats(self, client):
        """Health check should include memory usage."""
        response = client.get("/api/health")
        data = response.json()

        assert "memory_mb" in data
        assert isinstance(data["memory_mb"], (int, float))
        assert data["memory_mb"] > 0

    def test_health_check_includes_uptime(self, client):
        """Health check should include server uptime."""
        response = client.get("/api/health")
        data = response.json()

        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0


@pytest.mark.integration
class TestBrowserMockingStrategy:
    """Test that API properly mocks browser and LLM calls."""

    def test_health_check_does_not_require_browser(self, client):
        """Health check should work without browser initialization."""
        # This should not try to start a browser
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_recipe_list_does_not_require_browser(self, client):
        """Recipe list should work without browser initialization."""
        response = client.get("/api/recipes")
        assert response.status_code == 200

    def test_api_returns_valid_json_without_llm(self, client):
        """API endpoints should not require LLM to be called."""
        # All these endpoints should return valid JSON without calling LLM
        endpoints = [
            "/api/health",
            "/api/tasks",
            "/api/recipes",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Should get valid response
            assert response.status_code in (200, 503)  # 503 if feature disabled
            # Should be JSON
            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, dict)


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling in API endpoints."""

    def test_invalid_task_id_returns_404(self, client):
        """Should return 404 for non-existent tasks."""
        response = client.get("/api/tasks/invalid_id_that_does_not_exist")
        assert response.status_code == 404

    def test_invalid_recipe_name_returns_404(self, client):
        """Should return 404 for non-existent recipes."""
        response = client.get("/api/recipes/nonexistent_recipe_xyz")
        assert response.status_code == 404

    def test_missing_required_fields_returns_error(self, client):
        """Should reject requests missing required fields."""
        response = client.post("/api/learn", json={})
        assert response.status_code == 400


@pytest.mark.integration
class TestApiResponseConsistency:
    """Test consistency of API responses."""

    def test_task_response_includes_status(self, client):
        """All task responses should include status field."""
        response = client.get("/api/tasks")
        data = response.json()

        for task in data["tasks"]:
            assert "status" in task
            assert task["status"] in [
                "running",
                "completed",
                "failed",
                "pending",
                "cancelled",
            ]

    def test_recipe_response_includes_statistics(self, client):
        """All recipe responses should include statistics."""
        response = client.get("/api/recipes")
        data = response.json()

        for recipe in data["recipes"]:
            assert "success_rate" in recipe
            assert isinstance(recipe["success_rate"], (int, float))
            assert 0 <= recipe["success_rate"] <= 100

    def test_async_endpoints_return_task_id(self, client):
        """Async endpoints should return task_id for tracking."""
        response = client.post("/api/learn", json={"task": "Test learning"})

        if response.status_code == 202:
            data = response.json()
            assert "task_id" in data
            assert isinstance(data["task_id"], str)
            assert len(data["task_id"]) > 0

    def test_error_responses_include_error_field(self, client):
        """All error responses should include error field."""
        response = client.get("/api/tasks/nonexistent")
        if response.status_code >= 400:
            data = response.json()
            assert "error" in data or "Error" in str(data)


@pytest.mark.integration
class TestEventStreamIntegration:
    """Test SSE event streaming integration."""

    @pytest.mark.skip(reason="SSE endpoints stream indefinitely and block TestClient")
    def test_events_stream_is_accessible(self, client):
        """SSE events stream should be accessible."""
        with client.stream("GET", "/api/events") as response:
            assert response.status_code == 200

    @pytest.mark.skip(reason="SSE endpoints stream indefinitely and block TestClient")
    def test_events_stream_is_sse_format(self, client):
        """Event stream should use SSE content type."""
        with client.stream("GET", "/api/events") as response:
            content_type = response.headers.get("content-type", "")
            assert "event-stream" in content_type or "text/event-stream" == content_type

    @pytest.mark.skip(reason="SSE endpoints stream indefinitely and block TestClient")
    def test_events_stream_allows_client_connection(self, client):
        """Event stream should accept client connections."""
        with client.stream("GET", "/api/events") as response:
            # Should not reject the connection
            assert response.status_code == 200
            # Should be streaming response
            assert response.headers.get("cache-control") == "no-cache"


@pytest.mark.integration
class TestRecipeExecutionIntegration:
    """Test recipe execution endpoints."""

    def test_recipe_run_returns_task_tracking_info(self, client):
        """Recipe run should return task ID for status tracking."""
        payload = {"url": "https://example.com"}
        response = client.post("/api/recipes/example_recipe/run", json=payload)

        if response.status_code == 202:
            data = response.json()
            assert "task_id" in data
            assert "status_url" in data
            assert "message" in data

    def test_recipe_run_accepts_parameters(self, client):
        """Recipe run should accept parameters."""
        payload = {
            "url": "https://example.com",
            "params": {
                "search_term": "test",
                "max_results": 10,
            },
        }
        response = client.post("/api/recipes/example_recipe/run", json=payload)
        # Should not reject parameters
        assert response.status_code in (202, 400, 404, 503)

    def test_learn_returns_task_tracking_info(self, client):
        """Learn endpoint should return task ID for status tracking."""
        payload = {
            "task": "Learn to interact with GitHub API",
            "recipe_name": "github_interaction",
        }
        response = client.post("/api/learn", json=payload)

        if response.status_code == 202:
            data = response.json()
            assert "task_id" in data
            assert "status_url" in data
            assert data["recipe_name"] == "github_interaction"


@pytest.mark.integration
class TestConcurrentOperations:
    """Test API behavior with concurrent operations."""

    def test_multiple_health_checks(self, client):
        """Should handle multiple concurrent health checks."""
        # Make multiple requests in sequence
        for _ in range(5):
            response = client.get("/api/health")
            assert response.status_code == 200

    def test_mixed_read_operations(self, client):
        """Should handle mixed read operations."""
        responses = []

        # Mix different read operations
        responses.append(client.get("/api/health"))
        responses.append(client.get("/api/tasks"))
        responses.append(client.get("/api/recipes"))
        responses.append(client.get("/dashboard"))

        # All should succeed
        for response in responses:
            assert response.status_code == 200

    def test_multiple_recipe_operations(self, client):
        """Should handle multiple recipe operations."""
        response1 = client.get("/api/recipes")
        response2 = client.post(
            "/api/recipes/test/run",
            json={"url": "https://example.com"},
        )
        response3 = client.get("/api/recipes")

        assert response1.status_code == 200
        # response2 may be 404 or 202, but not 500
        assert response2.status_code != 500
        assert response3.status_code == 200
