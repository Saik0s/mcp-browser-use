# feat: Add Background Service Installation (Simplified)

## Overview

Add minimal CLI commands to install mcp-browser-use as a persistent background service. **Single file implementation, no abstractions, no new dependencies.**

## Problem Statement

Users must manually start the MCP server each time. Need: auto-start on boot, auto-restart on crash.

## Proposed Solution (Minimal)

**One file:** `src/mcp_server_browser_use/service.py` (~140 lines)

**Commands:**
- `mcp-browser-cli service install` - Generate and install service file
- `mcp-browser-cli service uninstall` - Remove service
- `mcp-browser-cli service start` / `stop` - Manual control
- `mcp-browser-cli service status` - Show status (pass-through to systemctl/launchctl)

**No:**
- ABC/interface abstractions
- Jinja2 templates (use f-strings)
- Health endpoint
- logs wrapper (document native commands)
- New dependencies

## Technical Approach

### Single File Implementation

`src/mcp_server_browser_use/service.py`:

```python
"""Background service management for mcp-browser-use."""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "mcp-browser-use"

SYSTEMD_TEMPLATE = """[Unit]
Description=MCP Browser Use Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exe}
Environment="MCP_SERVER_TRANSPORT=streamable-http"
Environment="MCP_SERVER_HOST={host}"
Environment="MCP_SERVER_PORT={port}"
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=default.target
"""

LAUNCHD_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mcp.browser-use</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>MCP_SERVER_TRANSPORT</key>
        <string>streamable-http</string>
        <key>MCP_SERVER_HOST</key>
        <string>{host}</string>
        <key>MCP_SERVER_PORT</key>
        <string>{port}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>{home}/Library/Logs/mcp-browser-use.log</string>
    <key>StandardErrorPath</key>
    <string>{home}/Library/Logs/mcp-browser-use-error.log</string>
</dict>
</plist>
"""


def get_executable() -> str:
    """Find mcp-server-browser-use executable."""
    exe = shutil.which("mcp-server-browser-use")
    if not exe:
        raise FileNotFoundError(
            "mcp-server-browser-use not found. "
            "Install with: uv tool install mcp-server-browser-use"
        )
    return exe


def install(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Install service for current platform."""
    exe = get_executable()
    system = platform.system()

    if system == "Linux":
        _install_systemd(exe, host, port)
    elif system == "Darwin":
        _install_launchd(exe, host, port)
    else:
        raise RuntimeError("Windows not supported. Use WSL.")


def _install_systemd(exe: str, host: str, port: int) -> None:
    service_dir = Path.home() / ".config/systemd/user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / f"{SERVICE_NAME}.service"

    content = SYSTEMD_TEMPLATE.format(exe=exe, host=host, port=port)
    service_file.write_text(content)

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True)
    print(f"Service installed: {service_file}")
    print(f"Start with: mcp-browser-cli service start")


def _install_launchd(exe: str, host: str, port: int) -> None:
    home = Path.home()
    plist_dir = home / "Library/LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_file = plist_dir / "com.mcp.browser-use.plist"

    # Create log directory
    log_dir = home / "Library/Logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    content = LAUNCHD_TEMPLATE.format(exe=exe, host=host, port=str(port), home=home)
    plist_file.write_text(content)

    subprocess.run(["launchctl", "load", str(plist_file)], check=True)
    print(f"Service installed: {plist_file}")
    print(f"Service will start automatically on login.")


def uninstall() -> None:
    """Remove service for current platform."""
    system = platform.system()

    if system == "Linux":
        subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], check=False)
        service_file = Path.home() / ".config/systemd/user" / f"{SERVICE_NAME}.service"
        if service_file.exists():
            service_file.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        print("Service removed.")
    elif system == "Darwin":
        plist_file = Path.home() / "Library/LaunchAgents/com.mcp.browser-use.plist"
        if plist_file.exists():
            subprocess.run(["launchctl", "unload", str(plist_file)], check=False)
            plist_file.unlink()
        print("Service removed.")


def start() -> None:
    """Start the service."""
    system = platform.system()
    if system == "Linux":
        subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=True)
    elif system == "Darwin":
        subprocess.run(["launchctl", "start", "com.mcp.browser-use"], check=True)
    print("Service started.")


def stop() -> None:
    """Stop the service."""
    system = platform.system()
    if system == "Linux":
        subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=True)
    elif system == "Darwin":
        subprocess.run(["launchctl", "stop", "com.mcp.browser-use"], check=True)
    print("Service stopped.")


def status() -> None:
    """Show service status (pass-through to native tools)."""
    system = platform.system()
    if system == "Linux":
        subprocess.run(["systemctl", "--user", "status", SERVICE_NAME])
    elif system == "Darwin":
        subprocess.run(["launchctl", "list", "com.mcp.browser-use"])
        print(f"\nLogs: tail -f ~/Library/Logs/mcp-browser-use.log")
```

### CLI Integration

Add to `cli.py`:

```python
service_app = typer.Typer(help="Manage background service")
app.add_typer(service_app, name="service")


@service_app.command("install")
def cmd_service_install(
    port: int = typer.Option(8000, help="HTTP port"),
    host: str = typer.Option("127.0.0.1", help="Bind address"),
):
    """Install MCP server as a background service."""
    from .service import install
    try:
        install(host=host, port=port)
    except (FileNotFoundError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)


@service_app.command("uninstall")
def cmd_service_uninstall():
    """Remove the background service."""
    from .service import uninstall
    if typer.confirm("Remove the service?"):
        uninstall()


@service_app.command("start")
def cmd_service_start():
    """Start the background service."""
    from .service import start
    start()


@service_app.command("stop")
def cmd_service_stop():
    """Stop the background service."""
    from .service import stop
    stop()


@service_app.command("status")
def cmd_service_status():
    """Show service status."""
    from .service import status
    status()
```

## Acceptance Criteria

- [ ] `mcp-browser-cli service install` creates platform-specific service file
- [ ] Service auto-starts on login (systemd user service / launchd LaunchAgent)
- [ ] Service auto-restarts on crash (with 10s backoff)
- [ ] `service start/stop` controls service state
- [ ] `service status` shows native service manager output
- [ ] `service uninstall` cleanly removes service
- [ ] Error on Windows with clear "use WSL" message

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/mcp_server_browser_use/service.py` | Create (~140 lines) |
| `src/mcp_server_browser_use/cli.py` | Add service subcommand group |
| `tests/test_service.py` | Add basic tests |
| `README.md` | Document service commands |

## No New Dependencies

- Use f-strings instead of Jinja2
- Use native systemctl/launchctl status instead of health endpoint
- No httpx needed

## Testing

```python
# tests/test_service.py
from unittest.mock import patch
import pytest

def test_get_executable_found():
    with patch("shutil.which", return_value="/usr/bin/mcp-server-browser-use"):
        from mcp_server_browser_use.service import get_executable
        assert get_executable() == "/usr/bin/mcp-server-browser-use"

def test_get_executable_not_found():
    with patch("shutil.which", return_value=None):
        from mcp_server_browser_use.service import get_executable
        with pytest.raises(FileNotFoundError, match="uv tool install"):
            get_executable()

def test_install_linux(tmp_path):
    with patch("platform.system", return_value="Linux"):
        with patch("subprocess.run") as mock_run:
            with patch("pathlib.Path.home", return_value=tmp_path):
                from mcp_server_browser_use.service import _install_systemd
                _install_systemd("/usr/bin/test", "127.0.0.1", 8000)

    service_file = tmp_path / ".config/systemd/user/mcp-browser-use.service"
    assert service_file.exists()
    content = service_file.read_text()
    assert "ExecStart=/usr/bin/test" in content
```

## References

- `src/mcp_server_browser_use/cli.py:1` - Existing Typer CLI
- [systemd User Services](https://wiki.archlinux.org/title/Systemd/User)
- [launchd Tutorial](https://www.launchd.info/)
