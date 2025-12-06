"""Research state machine for executing deep research tasks."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from browser_use import Agent, BrowserProfile

from .models import ResearchSource, ResearchState, ResearchTask, SearchResult
from .prompts import (
    PLANNING_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    get_planning_prompt,
    get_synthesis_prompt,
)

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

logger = logging.getLogger(__name__)


class ResearchMachine:
    """Custom state machine for deep research workflow."""

    def __init__(
        self,
        task: ResearchTask,
        llm: "BaseChatModel",
        browser_profile: BrowserProfile,
    ):
        self.task = task
        self.llm = llm
        self.browser_profile = browser_profile

    async def run(self) -> None:
        """Execute the research state machine."""
        try:
            # Initialize cancel event
            self.task._cancel_event = asyncio.Event()

            # PLANNING
            self.task.state = ResearchState.PLANNING
            self.task.progress.current_action = "Generating search queries"
            logger.info(f"[{self.task.id}] Planning: Generating queries for '{self.task.topic}'")

            queries = await self._generate_queries()
            if not queries:
                raise ValueError("Failed to generate search queries")

            logger.info(f"[{self.task.id}] Generated {len(queries)} queries")

            # EXECUTING
            self.task.state = ResearchState.EXECUTING
            self.task.progress.total_steps = len(queries)

            for i, query in enumerate(queries):
                if self.task._cancel_event and self.task._cancel_event.is_set():
                    self.task.state = ResearchState.CANCELLED
                    logger.info(f"[{self.task.id}] Cancelled during execution")
                    return

                self.task.progress.current_step = i + 1
                self.task.progress.current_action = f"Searching: {query}"
                logger.info(f"[{self.task.id}] Executing search {i + 1}/{len(queries)}: {query}")

                result = await self._execute_search(query)
                self.task.search_results.append(result)

            # SYNTHESIZING
            if self.task._cancel_event and self.task._cancel_event.is_set():
                self.task.state = ResearchState.CANCELLED
                return

            self.task.state = ResearchState.SYNTHESIZING
            self.task.progress.current_action = "Synthesizing report"
            logger.info(f"[{self.task.id}] Synthesizing report")

            self.task.report = await self._synthesize_report()

            # Save report if path specified
            if self.task.save_path:
                await self._save_report()

            # COMPLETED
            self.task.state = ResearchState.COMPLETED
            self.task.completed_at = datetime.now()
            logger.info(f"[{self.task.id}] Research completed")

        except Exception as e:
            self.task.state = ResearchState.FAILED
            self.task.error = str(e)
            logger.error(f"[{self.task.id}] Research failed: {e}")
            raise

    async def cancel(self) -> None:
        """Request cancellation of the research task."""
        if self.task._cancel_event:
            self.task._cancel_event.set()
            logger.info(f"[{self.task.id}] Cancellation requested")

    async def _generate_queries(self) -> list[str]:
        """Use LLM to generate search queries from the topic."""
        from browser_use.llm.messages import SystemMessage, UserMessage

        messages = [
            SystemMessage(content=PLANNING_SYSTEM_PROMPT),
            UserMessage(content=get_planning_prompt(self.task.topic, self.task.max_searches)),
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
                return queries[: self.task.max_searches]
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON from LLM response: {content[:200]}")

        # Fallback: split by newlines and clean up
        lines = [line.strip().strip("-").strip("*").strip('"').strip() for line in content.split("\n") if line.strip()]
        return [line for line in lines if len(line) > 10][: self.task.max_searches]

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
        findings = [r.summary for r in self.task.search_results if r.summary]
        sources = [{"title": r.source.title, "url": r.source.url, "summary": r.source.summary} for r in self.task.search_results if r.source]

        if not findings:
            return f"# Research Report: {self.task.topic}\n\nNo findings were gathered during the research process."

        messages = [
            SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
            UserMessage(content=get_synthesis_prompt(self.task.topic, findings, sources)),
        ]

        response = await self.llm.ainvoke(messages)
        return response.completion

    async def _save_report(self) -> None:
        """Save the report to a file."""
        if not self.task.save_path or not self.task.report:
            return

        try:
            path = Path(self.task.save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.task.report, encoding="utf-8")
            logger.info(f"[{self.task.id}] Report saved to {self.task.save_path}")
        except Exception as e:
            logger.error(f"[{self.task.id}] Failed to save report: {e}")
