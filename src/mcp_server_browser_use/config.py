"""Configuration management using Pydantic settings."""

from typing import Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderType = Literal["openai", "anthropic", "google", "ollama"]


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_LLM_")

    provider: ProviderType = Field(default="anthropic")
    model_name: str = Field(default="claude-sonnet-4-20250514")
    api_key: Optional[SecretStr] = Field(default=None)

    def get_api_key(self) -> Optional[str]:
        """Extract API key value from SecretStr."""
        return self.api_key.get_secret_value() if self.api_key else None


class BrowserSettings(BaseSettings):
    """Browser configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_BROWSER_")

    headless: bool = Field(default=True)


class AgentSettings(BaseSettings):
    """Agent behavior configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_AGENT_")

    max_steps: int = Field(default=20)
    use_vision: bool = Field(default=True)


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_SERVER_")

    logging_level: str = Field(default="INFO")


class AppSettings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


settings = AppSettings()
