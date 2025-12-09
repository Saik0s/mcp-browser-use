"""Tests for configuration and API key resolution."""

import os

import pytest

from mcp_server_browser_use.config import (
    NO_KEY_PROVIDERS,
    STANDARD_ENV_VAR_NAMES,
    LLMSettings,
)


class TestStandardEnvVarNames:
    """Test that standard env var names are correctly defined."""

    def test_all_providers_have_standard_names(self):
        """All providers that need keys should have standard names defined."""
        expected_providers = {
            "openai",
            "anthropic",
            "google",
            "azure_openai",
            "groq",
            "deepseek",
            "cerebras",
            "browser_use",
            "openrouter",
            "vercel",
        }
        assert set(STANDARD_ENV_VAR_NAMES.keys()) == expected_providers

    def test_standard_names_format(self):
        """Standard names should follow PROVIDER_API_KEY format."""
        for provider, env_vars in STANDARD_ENV_VAR_NAMES.items():
            # Handle both single string and list of strings
            vars_to_check = env_vars if isinstance(env_vars, list) else [env_vars]
            for env_var in vars_to_check:
                assert env_var.endswith("_API_KEY"), f"{provider} env var {env_var} should end with _API_KEY"
                assert env_var.isupper(), f"{provider} env var {env_var} should be uppercase"


class TestNoKeyProviders:
    """Test providers that don't require API keys."""

    def test_ollama_no_key(self):
        """Ollama should not require an API key."""
        assert "ollama" in NO_KEY_PROVIDERS

    def test_bedrock_no_key(self):
        """Bedrock should not require an API key (uses AWS credentials)."""
        assert "bedrock" in NO_KEY_PROVIDERS


class TestApiKeyResolution:
    """Test API key resolution priority logic."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        """Clean environment variables before each test."""
        # Remove any existing API key env vars
        for var in list(os.environ.keys()):
            if "API_KEY" in var or var.startswith("MCP_LLM_"):
                monkeypatch.delenv(var, raising=False)

    def test_generic_override_takes_priority(self, monkeypatch):
        """MCP_LLM_API_KEY should override all other sources."""
        monkeypatch.setenv("MCP_LLM_API_KEY", "generic-key")
        monkeypatch.setenv("OPENAI_API_KEY", "standard-key")
        monkeypatch.setenv("MCP_LLM_OPENAI_API_KEY", "mcp-key")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "generic-key"

    def test_standard_name_over_mcp_prefix(self, monkeypatch):
        """Standard env var should take priority over MCP-prefixed."""
        monkeypatch.setenv("OPENAI_API_KEY", "standard-key")
        monkeypatch.setenv("MCP_LLM_OPENAI_API_KEY", "mcp-key")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "standard-key"

    def test_mcp_prefix_fallback(self, monkeypatch):
        """MCP-prefixed should work when standard not set (backward compat)."""
        monkeypatch.setenv("MCP_LLM_OPENAI_API_KEY", "mcp-key")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "mcp-key"

    def test_ollama_no_key_required(self, monkeypatch):
        """Ollama should work without any API key."""
        monkeypatch.setenv("MCP_LLM_PROVIDER", "ollama")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() is None
        assert not settings.requires_api_key()

    def test_bedrock_no_key_required(self, monkeypatch):
        """Bedrock should work without API key (uses AWS credentials)."""
        monkeypatch.setenv("MCP_LLM_PROVIDER", "bedrock")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() is None
        assert not settings.requires_api_key()

    def test_anthropic_standard_key(self, monkeypatch):
        """Anthropic should work with ANTHROPIC_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "anthropic")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "sk-ant-test"
        assert settings.requires_api_key()

    def test_google_standard_key(self, monkeypatch):
        """Google should work with GOOGLE_API_KEY."""
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "google")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "google-test-key"

    def test_groq_standard_key(self, monkeypatch):
        """Groq should work with GROQ_API_KEY."""
        monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "groq")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "gsk-test"

    def test_openrouter_standard_key(self, monkeypatch):
        """OpenRouter should work with OPENROUTER_API_KEY."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openrouter")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() == "sk-or-test"

    def test_no_key_returns_none(self, monkeypatch):
        """Should return None when no key is set for a provider that needs one."""
        monkeypatch.setenv("MCP_LLM_PROVIDER", "openai")

        settings = LLMSettings()
        assert settings.get_api_key_for_provider() is None
        assert settings.requires_api_key()


class TestLLMSettingsDefaults:
    """Test default values for LLM settings."""

    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        """Clean environment variables before each test."""
        # Remove any existing LLM env vars that would override defaults
        for var in list(os.environ.keys()):
            if var.startswith("MCP_LLM_"):
                monkeypatch.delenv(var, raising=False)

    def test_default_provider(self, monkeypatch):
        """Default provider should be anthropic."""
        # Ensure no env vars override the default
        monkeypatch.delenv("MCP_LLM_PROVIDER", raising=False)
        settings = LLMSettings()
        assert settings.provider == "anthropic"

    def test_default_model(self, monkeypatch):
        """Default model should be claude-sonnet-4."""
        monkeypatch.delenv("MCP_LLM_MODEL_NAME", raising=False)
        settings = LLMSettings()
        assert "claude" in settings.model_name.lower()

    def test_azure_defaults(self, monkeypatch):
        """Azure should have sensible defaults."""
        monkeypatch.delenv("MCP_LLM_AZURE_API_VERSION", raising=False)
        monkeypatch.delenv("MCP_LLM_AZURE_ENDPOINT", raising=False)
        settings = LLMSettings()
        assert settings.azure_api_version == "2024-02-01"
        assert settings.azure_endpoint is None

    def test_aws_defaults(self, monkeypatch):
        """AWS region should default to None."""
        monkeypatch.delenv("MCP_LLM_AWS_REGION", raising=False)
        settings = LLMSettings()
        assert settings.aws_region is None


class TestProviderTypeValidation:
    """Test that provider type validation works."""

    def test_valid_providers(self, monkeypatch):
        """All valid providers should be accepted."""
        valid_providers = [
            "openai",
            "anthropic",
            "google",
            "azure_openai",
            "groq",
            "deepseek",
            "cerebras",
            "ollama",
            "bedrock",
            "browser_use",
            "openrouter",
            "vercel",
        ]
        for provider in valid_providers:
            monkeypatch.setenv("MCP_LLM_PROVIDER", provider)
            settings = LLMSettings()
            assert settings.provider == provider
