"""CLI interface for browser-use MCP server."""

import asyncio

import typer

from .config import settings
from .exceptions import BrowserError, LLMProviderError
from .providers import get_llm

app = typer.Typer(help="Browser automation CLI powered by browser-use")


@app.command()
def run(
    task: str = typer.Argument(..., help="Task to execute in the browser"),
    max_steps: int = typer.Option(None, "--max-steps", "-m", help="Maximum agent steps"),
) -> None:
    """Execute a browser automation task."""
    from browser_use import Agent, BrowserProfile

    async def _run() -> str:
        try:
            llm = get_llm(
                provider=settings.llm.provider,
                model=settings.llm.model_name,
                api_key=settings.llm.get_api_key(),
            )
        except LLMProviderError as e:
            return f"Error: {e}"

        profile = BrowserProfile(headless=settings.browser.headless)
        steps = max_steps if max_steps is not None else settings.agent.max_steps

        try:
            agent = Agent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_steps=steps,
            )

            result = await agent.run()
            return result.final_result() or "Task completed without explicit result."

        except Exception as e:
            raise BrowserError(f"Browser automation failed: {e}") from e

    result = asyncio.run(_run())
    print(result)


@app.command()
def config() -> None:
    """Show current configuration."""
    print(f"Provider: {settings.llm.provider}")
    print(f"Model: {settings.llm.model_name}")
    print(f"Headless: {settings.browser.headless}")
    print(f"Max Steps: {settings.agent.max_steps}")


if __name__ == "__main__":
    app()
