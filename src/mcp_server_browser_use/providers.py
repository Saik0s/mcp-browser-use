"""LLM provider factory using browser-use native providers."""

from typing import TYPE_CHECKING

# Import available chat models from browser-use
from browser_use import (
    ChatAnthropic,
    ChatAzureOpenAI,
    ChatBrowserUse,
    ChatGoogle,
    ChatGroq,
    ChatOllama,
    ChatOpenAI,
    ChatVercel,
)

# These are available via direct import but not in __all__
from browser_use.llm.aws.chat_bedrock import ChatAWSBedrock
from browser_use.llm.cerebras.chat import ChatCerebras
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.openrouter.chat import ChatOpenRouter

from .config import NO_KEY_PROVIDERS, STANDARD_ENV_VAR_NAMES
from .exceptions import LLMProviderError

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel


def get_llm(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> "BaseChatModel":
    """Create LLM instance using browser-use native providers.

    Supports 12 providers:
    - openai: OpenAI GPT models
    - anthropic: Claude models
    - google: Gemini models
    - azure_openai: Azure-hosted OpenAI models
    - groq: Groq-hosted models
    - deepseek: DeepSeek models
    - cerebras: Cerebras models
    - ollama: Local Ollama models (no API key required)
    - bedrock: AWS Bedrock models (uses AWS credentials)
    - browser_use: Browser Use Cloud API
    - openrouter: OpenRouter API
    - vercel: Vercel AI Gateway

    Args:
        provider: LLM provider name
        model: Model name/identifier
        api_key: API key for the provider (not required for ollama/bedrock)
        base_url: Custom base URL for OpenAI-compatible APIs
        **kwargs: Provider-specific options:
            - azure_endpoint: Azure OpenAI endpoint URL
            - azure_api_version: Azure OpenAI API version (default: 2024-02-01)
            - aws_region: AWS region for Bedrock

    Returns:
        Configured BaseChatModel instance

    Raises:
        LLMProviderError: If provider is unsupported or API key is missing
    """
    # Check if API key is required
    requires_api_key = provider not in NO_KEY_PROVIDERS and not base_url
    if requires_api_key and not api_key:
        standard_var = STANDARD_ENV_VAR_NAMES.get(provider, "API key")
        raise LLMProviderError(f"API key required for provider '{provider}'. Set {standard_var} or MCP_LLM_API_KEY environment variable.")

    try:
        match provider:
            case "openai":
                return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)

            case "anthropic":
                return ChatAnthropic(model=model, api_key=api_key)

            case "google":
                return ChatGoogle(model=model, api_key=api_key)

            case "azure_openai":
                azure_endpoint = kwargs.get("azure_endpoint")
                azure_api_version = kwargs.get("azure_api_version", "2024-02-01")
                if not azure_endpoint:
                    raise LLMProviderError("Azure OpenAI requires AZURE_OPENAI_ENDPOINT or MCP_LLM_AZURE_ENDPOINT to be set.")
                return ChatAzureOpenAI(
                    model=model,
                    api_key=api_key,
                    azure_endpoint=azure_endpoint,
                    api_version=azure_api_version,
                )

            case "groq":
                return ChatGroq(model=model, api_key=api_key)

            case "deepseek":
                return ChatDeepSeek(model=model, api_key=api_key)

            case "cerebras":
                return ChatCerebras(model=model, api_key=api_key)

            case "ollama":
                return ChatOllama(model=model, base_url=base_url)

            case "bedrock":
                aws_region = kwargs.get("aws_region")
                return ChatAWSBedrock(model_id=model, region=aws_region)

            case "browser_use":
                return ChatBrowserUse(model=model, api_key=api_key)

            case "openrouter":
                return ChatOpenRouter(model=model, api_key=api_key)

            case "vercel":
                return ChatVercel(model=model, api_key=api_key)

            case _:
                raise LLMProviderError(f"Unsupported provider: {provider}")

    except LLMProviderError:
        raise
    except Exception as e:
        raise LLMProviderError(f"Failed to initialize {provider} LLM: {e}") from e
