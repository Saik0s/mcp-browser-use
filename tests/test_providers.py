"""Tests for LLM provider factory."""

from unittest.mock import MagicMock, patch

import pytest

from mcp_server_browser_use.exceptions import LLMProviderError
from mcp_server_browser_use.providers import get_llm


class TestGetLLM:
    """Test the get_llm factory function."""

    def test_openai_provider(self):
        """OpenAI provider should create ChatOpenAI instance."""
        with patch("mcp_server_browser_use.providers.ChatOpenAI") as mock:
            mock.return_value = MagicMock()
            get_llm("openai", "gpt-4", api_key="test-key")
            mock.assert_called_once_with(model="gpt-4", api_key="test-key", base_url=None)

    def test_openai_with_base_url(self):
        """OpenAI provider should accept custom base_url."""
        with patch("mcp_server_browser_use.providers.ChatOpenAI") as mock:
            mock.return_value = MagicMock()
            get_llm("openai", "gpt-4", api_key="test-key", base_url="http://localhost:8000")
            mock.assert_called_once_with(model="gpt-4", api_key="test-key", base_url="http://localhost:8000")

    def test_anthropic_provider(self):
        """Anthropic provider should create ChatAnthropic instance."""
        with patch("mcp_server_browser_use.providers.ChatAnthropic") as mock:
            mock.return_value = MagicMock()
            get_llm("anthropic", "claude-3-opus", api_key="test-key")
            mock.assert_called_once_with(model="claude-3-opus", api_key="test-key")

    def test_google_provider(self):
        """Google provider should create ChatGoogle instance."""
        with patch("mcp_server_browser_use.providers.ChatGoogle") as mock:
            mock.return_value = MagicMock()
            get_llm("google", "gemini-pro", api_key="test-key")
            mock.assert_called_once_with(model="gemini-pro", api_key="test-key")

    def test_groq_provider(self):
        """Groq provider should create ChatGroq instance."""
        with patch("mcp_server_browser_use.providers.ChatGroq") as mock:
            mock.return_value = MagicMock()
            get_llm("groq", "mixtral-8x7b", api_key="test-key")
            mock.assert_called_once_with(model="mixtral-8x7b", api_key="test-key")

    def test_deepseek_provider(self):
        """DeepSeek provider should create ChatDeepSeek instance."""
        with patch("mcp_server_browser_use.providers.ChatDeepSeek") as mock:
            mock.return_value = MagicMock()
            get_llm("deepseek", "deepseek-chat", api_key="test-key")
            mock.assert_called_once_with(model="deepseek-chat", api_key="test-key")

    def test_cerebras_provider(self):
        """Cerebras provider should create ChatCerebras instance."""
        with patch("mcp_server_browser_use.providers.ChatCerebras") as mock:
            mock.return_value = MagicMock()
            get_llm("cerebras", "llama-70b", api_key="test-key")
            mock.assert_called_once_with(model="llama-70b", api_key="test-key")

    def test_ollama_no_key_required(self):
        """Ollama should work without API key."""
        with patch("mcp_server_browser_use.providers.ChatOllama") as mock:
            mock.return_value = MagicMock()
            get_llm("ollama", "llama2")
            mock.assert_called_once_with(model="llama2", host=None)

    def test_ollama_with_base_url(self):
        """Ollama should accept custom base_url (passed as host)."""
        with patch("mcp_server_browser_use.providers.ChatOllama") as mock:
            mock.return_value = MagicMock()
            get_llm("ollama", "llama2", base_url="http://localhost:11434")
            mock.assert_called_once_with(model="llama2", host="http://localhost:11434")

    def test_bedrock_provider(self):
        """Bedrock provider should create ChatAWSBedrock instance."""
        with patch("mcp_server_browser_use.providers.ChatAWSBedrock") as mock:
            mock.return_value = MagicMock()
            get_llm("bedrock", "anthropic.claude-v2", aws_region="us-east-1")
            mock.assert_called_once_with(model="anthropic.claude-v2", aws_region="us-east-1")

    def test_browser_use_provider(self):
        """Browser Use provider should create ChatBrowserUse instance."""
        with patch("mcp_server_browser_use.providers.ChatBrowserUse") as mock:
            mock.return_value = MagicMock()
            get_llm("browser_use", "bu-latest", api_key="test-key")
            mock.assert_called_once_with(model="bu-latest", api_key="test-key")

    def test_openrouter_provider(self):
        """OpenRouter provider should create ChatOpenRouter instance."""
        with patch("mcp_server_browser_use.providers.ChatOpenRouter") as mock:
            mock.return_value = MagicMock()
            get_llm("openrouter", "openai/gpt-4", api_key="test-key")
            mock.assert_called_once_with(model="openai/gpt-4", api_key="test-key")

    def test_vercel_provider(self):
        """Vercel provider should create ChatVercel instance."""
        with patch("mcp_server_browser_use.providers.ChatVercel") as mock:
            mock.return_value = MagicMock()
            get_llm("vercel", "gpt-4", api_key="test-key")
            mock.assert_called_once_with(model="gpt-4", api_key="test-key")


class TestAzureOpenAI:
    """Test Azure OpenAI provider configuration."""

    def test_azure_requires_endpoint(self):
        """Azure OpenAI should require endpoint to be set."""
        with pytest.raises(LLMProviderError, match="AZURE_OPENAI_ENDPOINT"):
            get_llm("azure_openai", "gpt-4", api_key="test-key")

    def test_azure_with_endpoint(self):
        """Azure OpenAI should work with endpoint provided."""
        with patch("mcp_server_browser_use.providers.ChatAzureOpenAI") as mock:
            mock.return_value = MagicMock()
            get_llm(
                "azure_openai",
                "gpt-4",
                api_key="test-key",
                azure_endpoint="https://test.openai.azure.com",
            )
            mock.assert_called_once_with(
                model="gpt-4",
                api_key="test-key",
                azure_endpoint="https://test.openai.azure.com",
                api_version="2024-02-01",
            )

    def test_azure_custom_api_version(self):
        """Azure OpenAI should accept custom API version."""
        with patch("mcp_server_browser_use.providers.ChatAzureOpenAI") as mock:
            mock.return_value = MagicMock()
            get_llm(
                "azure_openai",
                "gpt-4",
                api_key="test-key",
                azure_endpoint="https://test.openai.azure.com",
                azure_api_version="2024-06-01",
            )
            mock.assert_called_once_with(
                model="gpt-4",
                api_key="test-key",
                azure_endpoint="https://test.openai.azure.com",
                api_version="2024-06-01",
            )


class TestErrorHandling:
    """Test error handling in get_llm."""

    def test_missing_api_key_error(self):
        """Should raise error when API key is required but missing."""
        with pytest.raises(LLMProviderError, match="API key required"):
            get_llm("openai", "gpt-4")

    def test_missing_api_key_error_message_includes_env_var(self):
        """Error message should include the standard env var name."""
        with pytest.raises(LLMProviderError, match="OPENAI_API_KEY"):
            get_llm("openai", "gpt-4")

    def test_unsupported_provider_error(self):
        """Should raise error for unsupported provider."""
        with pytest.raises(LLMProviderError, match="Unsupported provider"):
            get_llm("invalid_provider", "model", api_key="key")

    def test_base_url_bypasses_api_key_check(self):
        """Custom base_url should allow no API key (self-hosted)."""
        with patch("mcp_server_browser_use.providers.ChatOpenAI") as mock:
            mock.return_value = MagicMock()
            # Should not raise even without API key
            get_llm("openai", "gpt-4", base_url="http://localhost:8000")
            mock.assert_called_once()
