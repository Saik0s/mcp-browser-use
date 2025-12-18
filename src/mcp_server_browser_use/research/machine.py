"""Research state machine for executing deep research tasks with progress tracking."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from browser_use import Agent, BrowserProfile

from .models import ResearchSource, SearchResult
from .prompts import (
    PLANNING_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    get_planning_prompt,
    get_synthesis_prompt,
)

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel
    from fastmcp.dependencies import Progress
    from fastmcp.server.context import Context

logger = logging.getLogger(__name__)


class ResearchMachine:
    """Research workflow with native MCP progress reporting."""

    def __init__(
        self,
        topic: str,
        max_searches: int,
        save_path: str | None,
        llm: "BaseChatModel",
        browser_profile: BrowserProfile,
        progress: Optional["Progress"] = None,
        ctx: Optional["Context"] = None,
    ):
        self.topic = topic
        self.max_searches = max_searches
        self.save_path = save_path
        self.llm = llm
        self.browser_profile = browser_profile
        self.progress = progress
        self.ctx = ctx
        self.search_results: list[SearchResult] = []

    async def _report_progress(self, message: str | None = None, increment: bool = False, total: int | None = None) -> None:
        """Report progress if progress tracker is available."""
        if not self.progress:
            return
        if total is not None:
            await self.progress.set_total(total)
        if message:
            await self.progress.set_message(message)
        if increment:
            await self.progress.increment()

    async def run(self) -> str:
        """Execute the research workflow and return the report."""
        # Total steps: planning (1) + searches (max_searches) + synthesis (1)
        total_steps = self.max_searches + 2
        await self._report_progress(total=total_steps)

        # Phase 1: Planning
        if self.ctx:
            await self.ctx.info(f"Planning: {self.topic}")
        await self._report_progress(message="Planning research approach...")
        logger.info(f"Planning: Generating queries for '{self.topic}'")

        queries = await self._generate_queries()
        if not queries:
            raise ValueError("Failed to generate search queries")

        logger.info(f"Generated {len(queries)} queries")
        await self._report_progress(increment=True)

        # Phase 2: Executing searches
        for i, query in enumerate(queries):
            if self.ctx:
                await self.ctx.info(f"Searching ({i + 1}/{len(queries)})")
            await self._report_progress(message=f"Searching ({i + 1}/{len(queries)}): {query}")
            logger.info(f"Executing search {i + 1}/{len(queries)}: {query}")

            result = await self._execute_search(query)
            self.search_results.append(result)
            await self._report_progress(increment=True)

        # Phase 3: Synthesizing
        if self.ctx:
            await self.ctx.info("Synthesizing report")
        await self._report_progress(message="Synthesizing findings into report...")
        logger.info("Synthesizing report")

        report = await self._synthesize_report()

        # Save report if path specified
        if self.save_path:
            await self._save_report(report)

        await self._report_progress(increment=True)
        logger.info("Research completed")

        return report

    async def _generate_queries(self) -> list[str]:
        """Use LLM to generate search queries from the topic."""
        from browser_use.llm.messages import SystemMessage, UserMessage

        messages = [
            SystemMessage(content=PLANNING_SYSTEM_PROMPT),
            UserMessage(content=get_planning_prompt(self.topic, self.max_searches)),
        ]

        response = await self.llm.ainvoke(messages)
        content = response.completion

        # Parse JSON array from response
        try:
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            queries = json.loads(content)
            if isinstance(queries, list):
                return queries[: self.max_searches]
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON from LLM response: {content[:200]}")

        # Fallback: split by newlines and clean up
        lines = [line.strip().strip("-").strip("*").strip('"').strip() for line in content.split("\n") if line.strip()]
        return [line for line in lines if len(line) > 10][: self.max_searches]

    async def _execute_search(self, query: str) -> SearchResult:
        """Execute a browser search for a single query."""
        search_prompt = f"""Research task: {query}

Instructions:
1. Search the web for information about this topic
2. Find and read relevant pages
3. Extract key information and facts
4. Note the source URLs and titles

Provide a concise summary of what you found, including:
- Key facts and information
- Source title and URL for the most relevant source

End your response with: DONE"""

        try:
            agent = Agent(
                task=search_prompt,
                llm=self.llm,
                browser_profile=self.browser_profile,
                max_steps=15,
            )

            result = await agent.run()
            final_result = result.final_result() or ""

            # Extract source info if available from the agent's history
            source = None
            if result.history:
                for step in reversed(result.history):
                    if hasattr(step, "state") and hasattr(step.state, "url"):
                        url = step.state.url
                        title = getattr(step.state, "title", url)
                        if url and "http" in url:
                            source = ResearchSource(title=title or url, url=url, summary=final_result[:200])
                            break

            return SearchResult(query=query, summary=final_result, source=source)

        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return SearchResult(query=query, summary="", error=str(e))

    async def _synthesize_report(self) -> str:
        """Use LLM to synthesize findings into a report."""
        from browser_use.llm.messages import SystemMessage, UserMessage

        # Collect findings and sources
        findings = [r.summary for r in self.search_results if r.summary]
        sources = [{"title": r.source.title, "url": r.source.url, "summary": r.source.summary} for r in self.search_results if r.source]

        if not findings:
            return f"# Research Report: {self.topic}\n\nNo findings were gathered during the research process."

        messages = [
            SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
            UserMessage(content=get_synthesis_prompt(self.topic, findings, sources)),
        ]

        response = await self.llm.ainvoke(messages)
        return response.completion

    async def _save_report(self, report: str) -> None:
        """Save the report to a file."""
        if not self.save_path:
            return

        try:
            path = Path(self.save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
            logger.info(f"Report saved to {self.save_path}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")
