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
) -> "BaseChatModel":
    """
    Create LLM instance using browser-use native providers.

    Args:
        provider: LLM provider name (openai, anthropic, google, ollama)
        model: Model name/identifier
        api_key: API key for the provider (not required for ollama)

    Returns:
        Configured BaseChatModel instance

    Raises:
        LLMProviderError: If provider is unsupported or API key is missing
    """
    if provider not in ("ollama",) and not api_key:
        raise LLMProviderError(f"API key required for provider '{provider}'. Set MCP_LLM_API_KEY environment variable.")

    try:
        if provider == "openai":
            return ChatOpenAI(model=model, api_key=api_key)
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
