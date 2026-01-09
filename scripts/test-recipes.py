#!/usr/bin/env python3
"""
End-to-end recipe learning test.
Runs through test cases, learns recipes, validates them.
Logs results to ~/.config/browser-recipes/test-runs.log
"""

import asyncio
from datetime import datetime
from pathlib import Path

import httpx

SERVER = "http://localhost:8383"
LOG_FILE = Path.home() / ".config" / "browser-recipes" / "test-runs.log"

TEST_CASES = [
    {
        "name": "hackernews-top",
        "task": "Get the titles of top 5 stories from Hacker News",
        "validate": "Search Hacker News for 'AI'",
    },
    {
        "name": "github-trending",
        "task": "Get trending Python repositories on GitHub today",
        "validate": "Get trending Rust repositories on GitHub",
    },
]


def log(line: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now().isoformat()} {line}\n")
    print(line)


async def call_tool(client: httpx.AsyncClient, tool: str, args: dict) -> dict:
    resp = await client.post(
        f"{SERVER}/api/call",
        json={"tool": tool, "arguments": args},
        timeout=180.0,
    )
    return resp.json()


async def run_test(case: dict) -> bool:
    async with httpx.AsyncClient() as client:
        # Learn
        log(f"learning:{case['name']}:start")
        result = await call_tool(
            client,
            "run_browser_agent",
            {
                "task": case["task"],
                "save_recipe_as": case["name"],
            },
        )

        if "error" in result:
            log(f"notlearning:{case['name']}:learn_failed:{result['error'][:50]}")
            return False

        log(f"learning:{case['name']}:learned")

        # Validate
        log(f"learning:{case['name']}:validate_start")
        result = await call_tool(
            client,
            "run_browser_agent",
            {
                "task": case["validate"],
                "recipe_name": case["name"],
            },
        )

        if "error" in result:
            log(f"notlearning:{case['name']}:validate_failed:{result['error'][:50]}")
            return False

        log(f"learning:{case['name']}:validated")
        return True


async def main() -> None:
    log("=== Test run started ===")

    passed = 0
    for case in TEST_CASES:
        try:
            if await run_test(case):
                passed += 1
        except Exception as e:
            log(f"notlearning:{case['name']}:exception:{str(e)[:50]}")

    log(f"=== Done: {passed}/{len(TEST_CASES)} passed ===")


if __name__ == "__main__":
    asyncio.run(main())
