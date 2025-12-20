#!/usr/bin/env python3
"""Smart install script - runs on SessionStart to ensure dependencies."""
import json
import os
import subprocess
import sys
from pathlib import Path


def check_playwright() -> None:
    """Check if Playwright browsers are installed, install if needed."""
    # Check if playwright is available
    try:
        # Try to run playwright install chromium
        # This is idempotent - if chromium is already installed, it skips download
        result = subprocess.run(
            ["uv", "run", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for first-time install
        )

        if result.returncode != 0:
            raise RuntimeError(f"Playwright install failed: {result.stderr}")

    except FileNotFoundError:
        raise RuntimeError("uv not found - please install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Playwright install timed out - network issues?")


def check_config() -> None:
    """Ensure config directory and default config exist."""
    # Determine config directory (cross-platform)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / ".config")).expanduser()
    else:
        base = Path("~/.config").expanduser()

    config_dir = base / "mcp-server-browser-use"
    config_file = config_dir / "config.json"

    # Create directory if missing
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create default config if missing
    if not config_file.exists():
        default_config = {
            "llm": {
                "provider": "google",
                "model_name": "gemini-2.0-flash-exp"
            },
            "browser": {
                "headless": True
            },
            "agent": {
                "max_steps": 20,
                "use_vision": True
            },
            "server": {
                "logging_level": "INFO",
                "transport": "streamable-http",
                "host": "127.0.0.1",
                "port": 8383
            },
            "research": {
                "max_searches": 5,
                "search_timeout": 120
            },
            "skills": {
                "enabled": False,
                "validate_results": True
            }
        }

        config_file.write_text(json.dumps(default_config, indent=2), encoding="utf-8")


def main():
    """Run all checks, install if needed."""
    checks = [
        ("Configuration", check_config),
        ("Playwright browsers", check_playwright),
    ]

    for name, check_fn in checks:
        try:
            check_fn()
            print(f"✓ {name}", file=sys.stderr)
        except Exception as e:
            print(f"✗ {name}: {e}", file=sys.stderr)
            # Return hook error response
            print(json.dumps({
                "continue": False,
                "error": f"Setup failed: {name} - {e}"
            }))
            sys.exit(1)

    # Return hook success response
    print(json.dumps({
        "continue": True,
        "suppressOutput": True
    }))


if __name__ == "__main__":
    main()
