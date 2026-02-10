"""Configuration management using Pydantic settings with optional file persistence."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias, TypeGuard
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import InitSettingsSource, PydanticBaseSettingsSource

# json.loads() returns untyped data. Validate it into JSON-safe types before
# passing into Pydantic settings. This avoids `Any` and makes failures explicit.
JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class ConfigFileError(RuntimeError):
    """Raised when the on-disk config exists but cannot be read or parsed."""


def _is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict) and _is_json_value(value)


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


def load_config_file() -> JsonObject:
    """Load settings from the JSON config file if it exists.

    Missing or empty config file is treated as "no config" (returns {}).
    A present-but-invalid config file is a hard error (ConfigFileError).
    """
    if not CONFIG_FILE.exists():
        return {}

    try:
        text = CONFIG_FILE.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigFileError(f"Failed to read config file {CONFIG_FILE}: {e}") from e

    if not text.strip():
        return {}

    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigFileError(f"Invalid JSON in config file {CONFIG_FILE} (line {e.lineno}, column {e.colno}): {e.msg}") from e

    if not _is_json_object(raw):
        raise ConfigFileError(f"Config file {CONFIG_FILE} must contain a JSON object at the top level")

    return raw


def save_config_file(config_data: JsonObject) -> None:
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


class MCPBaseSettings(BaseSettings):
    """Base settings where environment variables override init values.

    This matches the documented priority: env > config file > defaults.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (env_settings, init_settings, dotenv_settings, file_secret_settings)


class LLMSettings(MCPBaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_LLM_")

    provider: ProviderType = Field(default="openrouter")
    model_name: str = Field(default="moonshotai/kimi-k2.5")
    api_key: SecretStr | None = Field(default=None, description="Generic API key override (highest priority)")
    base_url: str | None = Field(default=None, description="Custom base URL for OpenAI-compatible APIs")

    # Azure OpenAI specific
    azure_endpoint: str | None = Field(default=None, description="Azure OpenAI endpoint URL")
    azure_api_version: str | None = Field(default="2024-02-01", description="Azure OpenAI API version")

    # AWS Bedrock specific
    aws_region: str | None = Field(default=None, description="AWS region for Bedrock")

    def get_api_key(self) -> str | None:
        """Extract API key value from SecretStr (legacy method for backward compat)."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_api_key_for_provider(self) -> str | None:
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


class BrowserSettings(MCPBaseSettings):
    """Browser configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_BROWSER_")

    headless: bool = Field(default=True)
    proxy_server: str | None = Field(default=None, description="Proxy server URL (e.g., http://host:8080)")
    proxy_bypass: str | None = Field(default=None, description="Comma-separated hosts to bypass proxy")
    cdp_url: str | None = Field(default=None, description="CDP URL for external browser (e.g., http://localhost:9222)")
    user_data_dir: str | None = Field(default=None, description="Path to Chrome user data directory for persistent profile")

    @field_validator("cdp_url", mode="before")
    @classmethod
    def normalize_cdp_url(cls, value: object) -> object:
        # Allow env override with empty string to force "no external browser".
        # This avoids test flakiness when a developer's ~/.config sets a CDP URL.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_cdp_url(self) -> "BrowserSettings":
        """Ensure CDP URL is localhost-only for security."""
        if self.cdp_url:
            parsed = urlparse(self.cdp_url)
            if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("CDP URL must be localhost for security")
        return self


class AgentSettings(MCPBaseSettings):
    """Agent behavior configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_AGENT_")

    max_steps: int = Field(default=20)
    use_vision: bool = Field(default=True)


TransportType = Literal["stdio", "streamable-http", "sse"]


class ServerSettings(MCPBaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_SERVER_")

    logging_level: str = Field(default="INFO")
    transport: TransportType = Field(default="stdio", description="MCP transport: stdio, streamable-http, or sse")
    host: str = Field(default="127.0.0.1", description="Host for HTTP transports")
    port: int = Field(default=8383, description="Port for HTTP transports")
    results_dir: str | None = Field(default=None, description="Directory to save execution results")
    auth_token: SecretStr | None = Field(default=None, description="Bearer token for non-localhost access")


class ResearchSettings(MCPBaseSettings):
    """Deep research configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_RESEARCH_")

    max_searches: int = Field(default=5, description="Maximum number of searches per research task")
    save_directory: str | None = Field(default=None, description="Directory to save research reports")
    search_timeout: int = Field(default=120, description="Timeout per search in seconds")


class RecipesSettings(MCPBaseSettings):
    """Browser recipes configuration."""

    model_config = SettingsConfigDict(env_prefix="MCP_RECIPES_")

    enabled: bool = Field(default=False, description="Enable recipes feature (beta - disabled by default)")
    directory: str | None = Field(default=None, description="Directory containing recipe YAML files (default: ~/.config/browser-recipes)")
    validate_results: bool = Field(default=True, description="Validate execution results against recipe success indicators")


class AppSettings(MCPBaseSettings):
    """Root application settings.

    Priority: Environment Variables > Config File > Defaults
    """

    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # We use our own loader to ensure consistent behavior:
        # - empty-but-present file => no config ({}), not JSONDecodeError
        # - invalid JSON => ConfigFileError (fail loudly)
        # - non-object top-level => ConfigFileError (fail loudly)
        file_settings = InitSettingsSource(settings_cls, load_config_file())

        return (
            env_settings,
            file_settings,
            init_settings,
            dotenv_settings,
            file_secret_settings,
        )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    recipes: RecipesSettings = Field(default_factory=RecipesSettings)

    def save(self) -> Path:
        """Save current configuration to file (excluding secrets)."""
        raw: object = self.model_dump(mode="json", exclude_none=True)
        if not _is_json_object(raw):
            raise RuntimeError("AppSettings.model_dump produced non-JSON-safe output")
        data: JsonObject = raw
        # Remove secret values from saved config
        llm_val = data.get("llm")
        if isinstance(llm_val, dict):
            llm_val.pop("api_key", None)
        server_val = data.get("server")
        if isinstance(server_val, dict):
            server_val.pop("auth_token", None)
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


class AppSettingsEnvOnly(MCPBaseSettings):
    """App settings without config file source.

    Used for CLI repair paths that must work even when the JSON file is broken.
    """

    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    recipes: RecipesSettings = Field(default_factory=RecipesSettings)

    def save(self) -> Path:
        """Save current configuration to file (excluding secrets)."""
        raw: object = self.model_dump(mode="json", exclude_none=True)
        if not _is_json_object(raw):
            raise RuntimeError("AppSettingsEnvOnly.model_dump produced non-JSON-safe output")
        data: JsonObject = raw
        llm_val = data.get("llm")
        if isinstance(llm_val, dict):
            llm_val.pop("api_key", None)
        server_val = data.get("server")
        if isinstance(server_val, dict):
            server_val.pop("auth_token", None)
        save_config_file(data)
        return CONFIG_FILE


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load strict settings (env > config file > defaults).

    Raises ConfigFileError when the config file is present but invalid.
    """
    return AppSettings()


def get_settings_env_only() -> AppSettingsEnvOnly:
    """Load settings from env+defaults only (never reads config file)."""
    return AppSettingsEnvOnly()


class _SettingsProxy:
    """Lazy settings accessor.

    Import-time must not hard-fail for the CLI repair path.
    Accessing attributes triggers strict load and can raise ConfigFileError.
    """

    def __getattr__(self, name: str) -> object:
        return getattr(get_settings(), name)


if TYPE_CHECKING:
    settings: AppSettings
else:
    settings = _SettingsProxy()
