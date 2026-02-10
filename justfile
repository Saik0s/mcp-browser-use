# mcp-server-browser-use development tasks

# Default recipe - show available commands
default:
    @just --list

# Install all dependencies
install:
    uv sync --dev

# Install Playwright browsers
install-browsers:
    uv run playwright install chromium

# Full setup for new developers
setup: install install-browsers
    @echo "Setup complete! Run 'just server' to start."

# Format code with ruff
format:
    uv run ruff format .

# Lint code with ruff
lint:
    uv run ruff check .

# Fix linting issues
lint-fix:
    uv run ruff check . --fix

# Type check with pyright
typecheck:
    uv run pyright

# Run all tests
test:
    uv run pytest

# Run tests with coverage
test-cov:
    uv run pytest --cov=src --cov-report=html

# Run tests excluding slow/e2e
test-fast:
    uv run pytest -m "not e2e and not slow"

# Run a specific test file
test-file FILE:
    uv run pytest {{FILE}} -v

# Run all checks (format, lint, typecheck, test-fast)
check: format lint typecheck test-fast

# Quick check (no tests)
check-quick: format lint typecheck

# Start server in background (daemon mode)
server:
    mcp-server-browser-use server

# Start server in foreground (for debugging)
server-fg:
    mcp-server-browser-use server -f

# Stop the server daemon
stop:
    mcp-server-browser-use stop

# Check server status
status:
    mcp-server-browser-use status

# Tail server logs
logs:
    mcp-server-browser-use logs -f

# Show server health
health:
    mcp-server-browser-use health

# List recent tasks
tasks:
    mcp-server-browser-use tasks

# List available MCP tools
tools:
    mcp-server-browser-use tools

# View current config
config:
    mcp-server-browser-use config view

# Clean build artifacts
clean:
    rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache htmlcov/
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Build package
build: clean
    uv build

# Run pre-commit hooks on all files
pre-commit:
    uv run pre-commit run --all-files

# Install pre-commit hooks
pre-commit-install:
    uv run pre-commit install
