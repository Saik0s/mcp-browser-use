"""Configuration management using Pydantic settings with optional file persistence."""

import json
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Paths ---

APP_NAME = "mcp-server-browser-use"


def get_config_dir() -> Path:
    """Get the configuration directory (e.g. ~/.config/mcp-server-browser-use)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / ".config")).expanduser()
    else:
        base = Path("~/.config").expanduser()

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_results_dir() -> Path:
    """Get the default directory for saving results."""
    base = Path("~/Documents").expanduser()
    if not base.exists():
        base = Path.home()

    path = base / "mcp-browser-results"
    return path


CONFIG_FILE = get_config_dir() / "config.json"


def load_config_file() -> dict[str, Any]:
    """Load settings from the JSON config file if it exists."""
    if not CONFIG_FILE.exists():
        return {}

    try:
        text = CONFIG_FILE.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        return json.loads(text)
    except Exception:
        return {}


def save_config_file(config_data: dict[str, Any]) -> None:
    """Save settings to the JSON config file."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config_data, indent=2), encoding="utf-8")


# Standard environment variable names for API keys (industry convention)
# For providers with multiple common env var names, use a list (first match wins)
STANDARD_ENV_VAR_NAMES: dict[str, str | list[str]] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],  # GEMINI_API_KEY takes priority
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "browser_use": "BROWSER_USE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "vercel": "VERCEL_API_KEY",
}

# Providers that don't require an API key
NO_KEY_PROVIDERS = frozenset({"ollama", "bedrock"})

ProviderType = Literal[
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


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_LLM_")

    provider: ProviderType = Field(default="anthropic")
    model_name: str = Field(default="claude-sonnet-4-20250514")
    api_key: Optional[SecretStr] = Field(default=None, description="Generic API key override (highest priority)")
    base_url: Optional[str] = Field(default=None, description="Custom base URL for OpenAI-compatible APIs")

    # Azure OpenAI specific
    azure_endpoint: Optional[str] = Field(default=None, description="Azure OpenAI endpoint URL")
    azure_api_version: Optional[str] = Field(default="2024-02-01", description="Azure OpenAI API version")

    # AWS Bedrock specific
    aws_region: Optional[str] = Field(default=None, description="AWS region for Bedrock")

    def get_api_key(self) -> Optional[str]:
        """Extract API key value from SecretStr (legacy method for backward compat)."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_api_key_for_provider(self) -> Optional[str]:
        """Resolve API key with priority: generic > standard > MCP-prefixed.

        Priority order:
        1. MCP_LLM_API_KEY (generic override, applies to any provider)
        2. <PROVIDER>_API_KEY (standard name, e.g., OPENAI_API_KEY, GEMINI_API_KEY)
        3. MCP_LLM_<PROVIDER>_API_KEY (legacy MCP-prefixed, backward compat)

        Returns:
            The resolved API key or None if not found.
        """
        # 1. Generic override (highest priority)
        if self.api_key:
            return self.api_key.get_secret_value()

        # 2. Standard env var name(s) (industry convention)
        standard_vars = STANDARD_ENV_VAR_NAMES.get(self.provider)
        if standard_vars:
            # Handle both single string and list of strings
            if isinstance(standard_vars, str):
                standard_vars = [standard_vars]
            for var_name in standard_vars:
                key = os.environ.get(var_name)
                if key:
                    return key

        # 3. MCP-prefixed fallback (backward compatibility)
        mcp_var = f"MCP_LLM_{self.provider.upper()}_API_KEY"
        return os.environ.get(mcp_var)

    def requires_api_key(self) -> bool:
        """Check if the current provider requires an API key."""
        return self.provider not in NO_KEY_PROVIDERS


class BrowserSettings(BaseSettings):
    """Browser configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_BROWSER_")

    headless: bool = Field(default=True)
    proxy_server: Optional[str] = Field(default=None, description="Proxy server URL (e.g., http://host:8080)")
    proxy_bypass: Optional[str] = Field(default=None, description="Comma-separated hosts to bypass proxy")


class AgentSettings(BaseSettings):
    """Agent behavior configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_AGENT_")

    max_steps: int = Field(default=20)
    use_vision: bool = Field(default=True)


TransportType = Literal["stdio", "streamable-http", "sse"]


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_SERVER_")

    logging_level: str = Field(default="INFO")
    transport: TransportType = Field(default="stdio", description="MCP transport: stdio, streamable-http, or sse")
    host: str = Field(default="127.0.0.1", description="Host for HTTP transports")
    port: int = Field(default=8383, description="Port for HTTP transports")
    results_dir: Optional[str] = Field(default=None, description="Directory to save execution results")


class ResearchSettings(BaseSettings):
    """Deep research configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESEARCH_")

    max_searches: int = Field(default=5, description="Maximum number of searches per research task")
    save_directory: Optional[str] = Field(default=None, description="Directory to save research reports")
    search_timeout: int = Field(default=120, description="Timeout per search in seconds")


class SkillsSettings(BaseSettings):
    """Browser skills configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_SKILLS_")

    enabled: bool = Field(default=True, description="Enable skills feature")
    directory: Optional[str] = Field(default=None, description="Directory containing skill YAML files (default: ~/.config/browser-skills)")
    validate_results: bool = Field(default=True, description="Validate execution results against skill success indicators")


class AppSettings(BaseSettings):
    """Root application settings.

    Priority: Environment Variables > Config File > Defaults
    """

    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)

    def save(self) -> Path:
        """Save current configuration to file (excluding secrets)."""
        data = self.model_dump(mode="json", exclude_none=True)
        # Remove secret values from saved config
        if "llm" in data and "api_key" in data["llm"]:
            del data["llm"]["api_key"]
        save_config_file(data)
        return CONFIG_FILE

    def get_results_dir(self) -> Path:
        """Get the results directory, creating if needed."""
        if self.server.results_dir:
            path = Path(self.server.results_dir).expanduser()
        else:
            path = get_default_results_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path


def _load_settings() -> AppSettings:
    """Load settings with file config as base, env vars overlay."""
    file_data = load_config_file()
    # Pydantic will overlay env vars on top
    return AppSettings(**file_data)


settings = _load_settings()
