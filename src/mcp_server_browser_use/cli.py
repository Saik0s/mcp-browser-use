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
    from browser_use.browser.profile import ProxySettings

    async def _run() -> str:
        try:
            llm = get_llm(
                provider=settings.llm.provider,
                model=settings.llm.model_name,
                api_key=settings.llm.get_api_key(),
                base_url=settings.llm.base_url,
            )
        except LLMProviderError as e:
            return f"Error: {e}"

        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(server=settings.browser.proxy_server, bypass=settings.browser.proxy_bypass)
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
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
def research(
    topic: str = typer.Argument(..., help="Topic to research"),
    max_searches: int = typer.Option(None, "--max-searches", "-n", help="Maximum number of searches"),
    save_to: str = typer.Option(None, "--save", "-s", help="File path to save the report"),
) -> None:
    """Execute a deep research task on a topic."""
    from browser_use import BrowserProfile
    from browser_use.browser.profile import ProxySettings

    from .research.machine import ResearchMachine

    async def _research() -> str:
        try:
            llm = get_llm(
                provider=settings.llm.provider,
                model=settings.llm.model_name,
                api_key=settings.llm.get_api_key_for_provider(),
                base_url=settings.llm.base_url,
            )
        except LLMProviderError as e:
            return f"Error: {e}"

        proxy = None
        if settings.browser.proxy_server:
            proxy = ProxySettings(server=settings.browser.proxy_server, bypass=settings.browser.proxy_bypass)
        profile = BrowserProfile(headless=settings.browser.headless, proxy=proxy)
        searches = max_searches if max_searches is not None else settings.research.max_searches

        try:
            machine = ResearchMachine(
                topic=topic,
                max_searches=searches,
                save_path=save_to,
                llm=llm,
                browser_profile=profile,
            )

            return await machine.run()

        except Exception as e:
            raise BrowserError(f"Research failed: {e}") from e

    result = asyncio.run(_research())
    print(result)


@app.command()
def config() -> None:
    """Show current configuration."""
    print(f"Provider: {settings.llm.provider}")
    print(f"Model: {settings.llm.model_name}")
    print(f"Base URL: {settings.llm.base_url or '(default)'}")
    print(f"Headless: {settings.browser.headless}")
    print(f"Proxy: {settings.browser.proxy_server or '(none)'}")
    print(f"Max Steps: {settings.agent.max_steps}")
    print(f"Max Searches: {settings.research.max_searches}")


if __name__ == "__main__":
    app()
