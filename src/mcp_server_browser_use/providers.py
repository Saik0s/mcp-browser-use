"""LLM provider factory using browser-use native providers."""

from typing import TYPE_CHECKING

from browser_use import ChatAnthropic, ChatGoogle, ChatOllama, ChatOpenAI

from .exceptions import LLMProviderError

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel


def get_llm(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> "BaseChatModel":
    """
    Create LLM instance using browser-use native providers.

    Args:
        provider: LLM provider name (openai, anthropic, google, ollama)
        model: Model name/identifier
        api_key: API key for the provider (not required for ollama or when base_url is set)
        base_url: Custom base URL for OpenAI-compatible APIs (e.g., vllm, local servers)

    Returns:
        Configured BaseChatModel instance

    Raises:
        LLMProviderError: If provider is unsupported or API key is missing when required
    """
    # API key not required for ollama or when using custom base_url (self-hosted)
    requires_api_key = provider not in ("ollama",) and not base_url
    if requires_api_key and not api_key:
        raise LLMProviderError(f"API key required for provider '{provider}'. Set MCP_LLM_API_KEY environment variable.")

    try:
        if provider == "openai":
            return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)
        elif provider == "anthropic":
            return ChatAnthropic(model=model, api_key=api_key)
        elif provider == "google":
            return ChatGoogle(model=model, api_key=api_key)
        elif provider == "ollama":
            return ChatOllama(model=model)
        else:
            raise LLMProviderError(f"Unsupported provider: {provider}")
    except LLMProviderError:
        raise
    except Exception as e:
        raise LLMProviderError(f"Failed to initialize {provider} LLM: {e}") from e
