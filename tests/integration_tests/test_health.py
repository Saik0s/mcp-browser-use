"""Integration tests for health_check MCP tool."""

import json

import pytest
from fastmcp import Client


class TestHealthCheck:
    """Tests for the health_check tool."""

    @pytest.mark.anyio
    async def test_health_check_returns_healthy_status(self, mcp_client: Client):
        """health_check should return healthy status."""
        result = await mcp_client.call_tool("health_check", {})

        assert result.content is not None
        assert len(result.content) > 0

        data = json.loads(result.content[0].text)
        assert data["status"] == "healthy"

    @pytest.mark.anyio
    async def test_health_check_includes_uptime(self, mcp_client: Client):
        """health_check should include uptime_seconds."""
        result = await mcp_client.call_tool("health_check", {})

        data = json.loads(result.content[0].text)
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], float)
        assert data["uptime_seconds"] >= 0

    @pytest.mark.anyio
    async def test_health_check_includes_memory_info(self, mcp_client: Client):
        """health_check should include memory usage."""
        result = await mcp_client.call_tool("health_check", {})

        data = json.loads(result.content[0].text)
        assert "memory_mb" in data
        assert isinstance(data["memory_mb"], float)
        assert data["memory_mb"] > 0

    @pytest.mark.anyio
    async def test_health_check_includes_running_tasks_count(self, mcp_client: Client):
        """health_check should include running_tasks count."""
        result = await mcp_client.call_tool("health_check", {})

        data = json.loads(result.content[0].text)
        assert "running_tasks" in data
        assert isinstance(data["running_tasks"], int)
        assert data["running_tasks"] >= 0

    @pytest.mark.anyio
    async def test_health_check_includes_stats(self, mcp_client: Client):
        """health_check should include aggregate stats."""
        result = await mcp_client.call_tool("health_check", {})

        data = json.loads(result.content[0].text)
        assert "stats" in data
        assert isinstance(data["stats"], dict)
