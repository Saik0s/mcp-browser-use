# feat: Add Client-Visible Status Updates via Context

**Date:** 2025-12-09
**Type:** Enhancement
**Detail Level:** MINIMAL

---

## Overview

Activate the unused FastMCP Context to send status messages to MCP clients. Currently Context is injected but never used - add ~15 lines to make long operations visible to clients.

## Problem

Clients have no visibility during 30s-10min browser automation tasks. They only see the final result.

## Solution

Use `ctx.info()` for client-facing status messages at key milestones only. Keep existing Python logging for server-side debugging.

**Principle:** Log **page transitions**, not every action. Signal, not noise.

## Acceptance Criteria

- [ ] `run_browser_agent`: logs start, page changes, completion
- [ ] `run_deep_research`: logs phase transitions (planning → searching → synthesizing)
- [ ] Step callback wired for progress updates (already have Progress)
- [ ] No new abstractions, no helper methods

## MVP Implementation

### server.py (~15 lines added)

```python
# src/mcp_server_browser_use/server.py

@server.tool(task=TaskConfig(mode="optional"))
async def run_browser_agent(
    task: str,
    max_steps: Optional[int] = None,
    ctx: Context = CurrentContext(),
    progress: Progress = Progress(),
) -> str:
    """Execute a browser automation task using AI."""
    await ctx.info(f"Starting: {task}")
    logger.info(f"Starting browser agent task: {task[:100]}...")

    try:
        llm, profile = _get_llm_and_profile()
    except LLMProviderError as e:
        logger.error(f"LLM initialization failed: {e}")
        return f"Error: {e}"

    steps = max_steps if max_steps is not None else settings.agent.max_steps
    await progress.set_total(steps)

    # Track page changes only (not every step)
    last_url: str | None = None

    async def step_callback(
        state: BrowserStateSummary,
        output: AgentOutput,
        step_num: int,
    ) -> None:
        nonlocal last_url
        if state.url != last_url:
            await ctx.info(f"→ {state.title or state.url}")
            last_url = state.url
        await progress.increment()

    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser_profile=profile,
            max_steps=steps,
            register_new_step_callback=step_callback,
        )

        result = await agent.run()
        final = result.final_result() if result else "No result"

        await ctx.info(f"Completed: {final[:100]}")
        logger.info(f"Agent completed: {final[:100]}...")
        return final

    except Exception as e:
        logger.error(f"Browser agent failed: {e}")
        raise BrowserError(f"Browser automation failed: {e}") from e
```

### research/machine.py (~6 lines added)

```python
# In ResearchMachine.__init__, add ctx parameter:
ctx: Context | None = None,

# In ResearchMachine.run(), add 3 status messages:
async def run(self) -> str:
    if self.ctx:
        await self.ctx.info(f"Planning: {self.topic}")
    # ... existing planning code ...

    for i, query in enumerate(queries):
        if self.ctx:
            await self.ctx.info(f"Searching ({i + 1}/{len(queries)})")
        # ... existing search code ...

    if self.ctx:
        await self.ctx.info("Synthesizing report")
    # ... existing synthesis code ...
```

### server.py - pass ctx to ResearchMachine

```python
# In run_deep_research:
machine = ResearchMachine(
    topic=topic,
    max_searches=max_searches,
    save_path=save_path,
    llm=llm,
    browser_profile=profile,
    progress=progress,
    ctx=ctx,  # Add this
)
```

## Files to Modify

| File | Changes |
|------|---------|
| `src/mcp_server_browser_use/server.py` | Add step callback, 3 ctx.info() calls |
| `src/mcp_server_browser_use/research/machine.py` | Add ctx param, 3 ctx.info() calls |

## What NOT to Do

- ❌ No dual logging helper methods
- ❌ No logging taxonomy tables
- ❌ No try/except around ctx calls (let it fail loudly)
- ❌ No truncation ceremony (`[:50]`, `[:100]` everywhere)
- ❌ No `ctx.debug()` for every step
- ❌ No `ctx.error()` before raising exceptions
- ❌ No tests that "can't actually verify what they test"

## Review Feedback Applied

**DHH:** "Pick one logging system. This is a 10-line change, not 280-line architecture."
→ Reduced to ~20 lines total

**Simplicity:** "Log only page transitions, not every action. YAGNI on the helper methods."
→ Removed `_log()` helper, only log on URL change

**Python Review:** "Add type hints to step callback, import BrowserStateSummary/AgentOutput"
→ Added proper types

## References

- `src/mcp_server_browser_use/server.py:50-100`
- `src/mcp_server_browser_use/research/machine.py:35-95`
- [FastMCP Context](https://gofastmcp.com/servers/context)
