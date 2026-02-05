"""Prompts for recipe learning and execution.

Learning Mode: Agent completes the task normally. System records the workflow.
Analysis Mode: LLM extracts a replayable recipe from the recorded session.

Recipes can be:
1. API-based: Direct HTTP calls (fastest, ~1-2s)
2. HTML-based: Navigate to URL, parse HTML with CSS selectors (~2-5s)
3. Workflow-based: Multi-step browser actions (fallback, ~30-60s)
"""

# --- Learning Mode Prompt ---
# This is APPENDED to the user's task when learn=True

LEARNING_MODE_SUFFIX = """

LEARNING MODE - Complete the task normally.

The system is recording your actions to create a reusable recipe.
Complete the task as you normally would:
1. Navigate to the relevant page
2. Use the 'extract' action to extract the requested data
3. Report what you found with the exact URL

IMPORTANT for recipe creation:
- Navigate directly to the data page (avoid unnecessary clicks)
- Use the 'extract' action to get the data
- Report the EXACT final URL where the data was found
- Describe the HTML structure (e.g., "repo names are in h3 tags inside article elements")

At the end, provide these details:
- Final URL: [exact URL where data was found, with any parameters]
- Data found: [list the first 3-5 items you extracted]
- HTML structure: [describe what HTML elements contain the data, e.g., "article > h3 > a for repo names"]
- Parameters: [values in the URL that could be customized, e.g., username]
"""


# --- Recipe Analysis Prompt ---
# LLM analyzes recorded session to extract a recipe (API or HTML-based)

ANALYSIS_SYSTEM_PROMPT = """You are a browser automation expert analyzing a recorded session to extract a reusable recipe.

RECIPE TYPES (in order of preference):
1. API-based: If an XHR/Fetch call returned the needed data as JSON
2. HTML-based: If data was scraped from a page's HTML (use CSS selectors)
3. Workflow hints: If neither works, provide navigation hints for the agent

ANALYZE THE SESSION:
Look at both the API calls AND the agent's result. The agent may have:
- Found and used an API endpoint (check API CALLS section)
- Scraped data from HTML (check AGENT RESULT for CSS selectors or DOM info)
- Navigated to a specific URL with the data

OUTPUT FORMAT:
{
    "success": true/false,
    "reason": "Why this succeeded or failed",
    "recipe_type": "api" | "html" | "hints",
    "request": {
        "url": "Full URL with {param} placeholders",
        "method": "GET or POST",
        "headers": {},
        "body_template": null,
        "response_type": "json" | "html" | "text",
        "extract_path": "JMESPath for JSON, e.g., items[*].name",
        "html_selectors": {"field_name": "CSS selector", ...}  // For HTML type
    },
    "parameters": [
        {"name": "param", "source": "url|query|body", "required": true, "default": null, "description": "..."}
    ],
    "auth_recovery": {
        "trigger_on_status": [401, 403],
        "recovery_page": "login URL"
    },
    "recipe_name_suggestion": "suggested-name",
    "recipe_description": "What this recipe does"
}

FOR HTML-BASED RECIPES:
- Set response_type to "html"
- Provide html_selectors with SIMPLE, ROBUST CSS selectors for each data field
- CRITICAL: Use SHORT selectors that won't break when the page changes:
  * GOOD: "h3 a", "article a", "a[href*='/stargazers']", "[data-id] a"
  * BAD: "div[class='d-flex col-12 py-3'] > div > a" (too specific, will break)
- Prefer element-based selectors (h3, article, li) over class-based
- Use attribute selectors for href patterns: a[href*="/repos/"], a[href$="/stars"]
- Example: {"repo_names": "h3 a[href]", "stars": "a[href$='/stargazers']"}

FOR API-BASED RECIPES:
- Set response_type to "json"
- Provide extract_path with JMESPath expression
- Example: "items[*].{name: full_name, stars: stargazers_count}"

PARAMETER EXTRACTION:
Look for parameters in:
1. The task description ("it takes X and Y", "with limit parameter")
2. The URL query string (q=, page=, per_page=, limit=)
3. Path segments that vary (/users/{username}/repos)

Common mappings: limit→per_page, count→per_page, page→page, query→q

If no recipe can be extracted:
{
    "success": false,
    "reason": "Explanation - e.g., requires multi-step interaction, CAPTCHA, etc."
}
"""


def get_analysis_prompt(
    task: str,
    result: str,
    api_calls: list[dict],
    final_url: str | None = None,
    page_html_snippet: str | None = None,
) -> str:
    """Generate the analysis prompt with recorded data.

    Args:
        task: Original user task
        result: Agent's final result
        api_calls: List of API call summaries from recorder
        final_url: The final page URL where data was found
        page_html_snippet: Snippet of the page HTML (for HTML-based recipes)

    Returns:
        Formatted prompt for recipe analysis
    """
    # Format API calls
    api_calls_text = ""
    if api_calls:
        for i, call in enumerate(api_calls, 1):
            api_calls_text += f"""
{i}. {call["method"]} {call["url"]}
   Status: {call["status"]}
   Content-Type: {call["content_type"]}
   Has Response Body: {call["has_body"]}
"""
            if call.get("post_data"):
                api_calls_text += f"   Request Body: {call['post_data'][:500]}...\n"
            if call.get("response_body"):
                api_calls_text += f"   Response Body (truncated): {call['response_body'][:1000]}...\n"
    else:
        api_calls_text = "(No API calls recorded - data likely from HTML page)"

    # Format page info
    page_info = ""
    if final_url:
        page_info += f"\nFINAL PAGE URL:\n{final_url}\n"
    if page_html_snippet:
        page_info += f"\nPAGE HTML SNIPPET (relevant section):\n{page_html_snippet[:2000]}\n"

    return f"""Analyze this browser session to extract a reusable recipe.

ORIGINAL TASK:
{task}

AGENT RESULT:
{result}
{page_info}
API CALLS RECORDED:
{api_calls_text}

INSTRUCTIONS:
1. If an API call returned the needed data as JSON → create an API-based recipe
2. If no suitable API but agent extracted from HTML → create an HTML-based recipe with CSS selectors
3. Extract parameters from the task description (limit, page, query, username, etc.)

The recipe should allow replaying this task efficiently without full browser automation.

Return your analysis as JSON.
"""


# --- Hint Injection Prompt ---
# This is PREPENDED to the user's task when executing with a recipe


def get_execution_hints(recipe_name: str, hints_text: str) -> str:
    """Generate execution hints from a recipe.

    Args:
        recipe_name: Name of the recipe being used
        hints_text: Formatted hints from RecipeHints.to_prompt()

    Returns:
        Formatted hints to prepend to task
    """
    return f"""RECIPE HINTS (from previous successful execution of "{recipe_name}"):

{hints_text}

Use these hints to navigate efficiently. If the hints don't match
what you see (API changed, page restructured), fall back to normal exploration.

YOUR TASK:
"""
