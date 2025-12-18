"""Tests for the skills module."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_server_browser_use.skills.models import AuthRecovery, Skill, SkillRequest
from mcp_server_browser_use.skills.runner import SkillRunner

# --- Fixtures ---


@pytest.fixture
def skill_with_direct_execution() -> Skill:
    """Create a skill that supports direct execution.

    Uses example.com which is a real resolvable domain (93.184.216.34).
    """
    return Skill(
        name="test-skill",
        description="Test skill for unit tests",
        original_task="Search for test query",
        request=SkillRequest(
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
def skill_without_direct_execution() -> Skill:
    """Create a legacy skill without direct execution."""
    return Skill(
        name="legacy-skill",
        description="Legacy skill without direct execution",
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


# --- SkillRequest Tests ---


class TestSkillRequest:
    """Tests for SkillRequest model."""

    def test_build_url_substitutes_params(self):
        request = SkillRequest(url="https://api.example.com/search?q={query}&limit={limit}")
        result = request.build_url({"query": "test", "limit": "10"})
        assert result == "https://api.example.com/search?q=test&limit=10"

    def test_build_url_handles_missing_params(self):
        request = SkillRequest(url="https://api.example.com/search?q={query}")
        result = request.build_url({})
        assert result == "https://api.example.com/search?q={query}"

    def test_build_body_substitutes_params(self):
        request = SkillRequest(
            url="https://api.example.com/search",
            body_template='{"query": "{query}", "limit": {limit}}',
        )
        result = request.build_body({"query": "test", "limit": "10"})
        assert result == '{"query": "test", "limit": 10}'

    def test_build_body_returns_none_if_no_template(self):
        request = SkillRequest(url="https://api.example.com/search")
        result = request.build_body({"query": "test"})
        assert result is None

    def test_to_fetch_options_includes_credentials(self):
        request = SkillRequest(url="https://api.example.com/search")
        options = request.to_fetch_options({})
        assert options["credentials"] == "include"
        assert options["method"] == "GET"

    def test_to_fetch_options_includes_headers(self):
        request = SkillRequest(
            url="https://api.example.com/search",
            headers={"Accept": "application/json", "X-Custom": "value"},
        )
        options = request.to_fetch_options({})
        assert options["headers"]["Accept"] == "application/json"
        assert options["headers"]["X-Custom"] == "value"

    def test_to_fetch_options_includes_body_for_post(self):
        request = SkillRequest(
            url="https://api.example.com/search",
            method="POST",
            body_template='{"query": "{query}"}',
        )
        options = request.to_fetch_options({"query": "test"})
        assert options["method"] == "POST"
        assert options["body"] == '{"query": "test"}'


# --- Skill Tests ---


class TestSkill:
    """Tests for Skill model."""

    def test_supports_direct_execution_true_with_request(self, skill_with_direct_execution: Skill):
        assert skill_with_direct_execution.supports_direct_execution is True

    def test_supports_direct_execution_false_without_request(self, skill_without_direct_execution: Skill):
        assert skill_without_direct_execution.supports_direct_execution is False


# --- SkillRunner Tests ---


class TestSkillRunner:
    """Tests for SkillRunner."""

    @pytest.fixture
    def runner(self) -> SkillRunner:
        return SkillRunner(timeout=10.0)

    async def test_run_returns_error_for_skill_without_request(
        self,
        runner: SkillRunner,
        skill_without_direct_execution: Skill,
        mock_browser_session: MagicMock,
    ):
        result = await runner.run(skill_without_direct_execution, {}, mock_browser_session)
        assert result.success is False
        assert "no request config" in result.error.lower()

    async def test_run_gets_cdp_session(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify CDP session was created
        mock_browser_session.get_or_create_cdp_session.assert_called_once()

        # Verify Page domain was enabled with session_id
        mock_browser_session.cdp_client.send.Page.enable.assert_called()
        enable_call = mock_browser_session.cdp_client.send.Page.enable.call_args
        assert enable_call.kwargs.get("session_id") == "test-session-123"

    async def test_run_navigates_with_session_id(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify Page.navigate was called with session_id
        mock_browser_session.cdp_client.send.Page.navigate.assert_called()
        nav_call = mock_browser_session.cdp_client.send.Page.navigate.call_args
        assert nav_call.kwargs.get("session_id") == "test-session-123"
        assert "https://example.com" in nav_call.kwargs["params"]["url"]

    async def test_run_executes_fetch_with_session_id(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Verify Runtime.evaluate was called with session_id
        mock_browser_session.cdp_client.send.Runtime.evaluate.assert_called()
        eval_call = mock_browser_session.cdp_client.send.Runtime.evaluate.call_args
        assert eval_call.kwargs.get("session_id") == "test-session-123"

    async def test_run_returns_success_with_extracted_data(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        result = await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is True
        assert result.status_code == 200
        # extract_path is "results[*].name"
        assert result.data == ["item1", "item2"]

    async def test_run_handles_http_error(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        result = await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is False
        assert result.status_code == 500
        assert "HTTP 500" in result.error

    async def test_run_triggers_auth_recovery_on_401(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        result = await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        assert result.success is False
        assert result.auth_recovery_triggered is True
        assert "recovery page" in result.error.lower()
        assert "https://example.com/login" in result.error

    async def test_run_skips_navigation_if_same_domain(
        self,
        runner: SkillRunner,
        skill_with_direct_execution: Skill,
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

        await runner.run(skill_with_direct_execution, {"query": "test"}, mock_browser_session)

        # Page.navigate should NOT be called since we're already on the domain
        mock_browser_session.cdp_client.send.Page.navigate.assert_not_called()


# --- JMESPath Extraction Tests ---


class TestJMESPathExtraction:
    """Tests for JMESPath data extraction (uses runner.extract_data)."""

    def test_extract_simple_path(self):
        from mcp_server_browser_use.skills.runner import extract_data

        data = {"foo": {"bar": "value"}}
        result = extract_data(data, "foo.bar")
        assert result == "value"

    def test_extract_array_expansion(self):
        from mcp_server_browser_use.skills.runner import extract_data

        data = {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
        result = extract_data(data, "items[*].name")
        assert result == ["a", "b", "c"]

    def test_extract_nested_array(self):
        from mcp_server_browser_use.skills.runner import extract_data

        data = {"results": [{"package": {"name": "pkg1"}}, {"package": {"name": "pkg2"}}]}
        result = extract_data(data, "results[*].package.name")
        assert result == ["pkg1", "pkg2"]

    def test_extract_missing_path_returns_none(self):
        from mcp_server_browser_use.skills.runner import extract_data

        data = {"foo": "bar"}
        result = extract_data(data, "missing.path")
        assert result is None

    def test_extract_index_access(self):
        from mcp_server_browser_use.skills.runner import extract_data

        data = {"items": ["first", "second", "third"]}
        # JMESPath uses [0] syntax for array index access
        result = extract_data(data, "items[0]")
        assert result == "first"
