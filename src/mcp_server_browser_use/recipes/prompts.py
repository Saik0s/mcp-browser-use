"""Prompts for recipe learning and execution.

Learning Mode: Agent is instructed to discover and use APIs, not DOM scraping.
Analysis Mode: LLM identifies the "money request" from recorded network traffic.
"""

# --- Learning Mode Prompt ---
# This is APPENDED to the user's task when learn=True

LEARNING_MODE_SUFFIX = """

IMPORTANT - API DISCOVERY MODE:
Your goal is to complete this task BY DISCOVERING AND USING THE UNDERLYING API.

Instructions:
1. Navigate to the relevant page(s) as needed
2. OBSERVE the network requests being made (XHR/Fetch calls)
3. IDENTIFY the API endpoint that returns the data you need
4. The data you need will come from an API response, NOT from DOM scraping
5. Report the API endpoint you found and the data structure

What to look for:
- GraphQL endpoints (often /graphql or /api/graphql)
- REST API endpoints (often /api/v1/... or similar)
- JSON responses that contain the requested data

What NOT to do:
- Do NOT extract data by reading DOM elements
- Do NOT rely on CSS selectors for data extraction
- The page DOM is just for navigation, not data extraction

Success criteria:
- You found an API endpoint that returns the requested data
- You can describe the endpoint (URL, method, parameters)
- The response contains structured data (JSON)

If you cannot find an API (data is rendered server-side with no API):
- Report that no suitable API was found
- This means the task cannot be learned as a recipe
"""


# --- Recipe Analysis Prompt ---
# LLM analyzes recorded network traffic to extract a recipe

ANALYSIS_SYSTEM_PROMPT = """You are a browser automation expert analyzing network traffic to extract reusable recipes.

Your task is to identify the "money request" - the single API call that returns the data the user asked for.
This request will be executed DIRECTLY via browser fetch() for fast recipe replay.

A good money request:
- Returns JSON data that matches what the user asked for
- Is a single endpoint (not multiple calls)
- Has clear parameters that can be templated (use {param_name} placeholders)
- Returns structured data (JSON preferred, HTML accepted)

Output a JSON object with:
{
    "success": true/false,
    "reason": "Why this succeeded or failed",
    "request": {
        "url": "Full URL with {param} placeholders, e.g., https://npmjs.com/search?q={query}",
        "method": "GET or POST",
        "headers": {"Content-Type": "application/json"},  // Only include essential headers
        "body_template": "Request body with {param} placeholders (for POST)",
        "response_type": "json or html or text",
        "extract_path": "JSONPath to extract data, e.g., objects[*].package.name"
    },
    "parameters": [
        {"name": "query", "source": "url|body|query", "required": true, "default": null}
    ],
    "auth_recovery": {
        "trigger_on_status": [401, 403],
        "recovery_page": "URL to navigate if auth fails (e.g., login page)"
    },
    "recipe_name_suggestion": "suggested-recipe-name",
    "recipe_description": "What this recipe does"
}

IMPORTANT:
- The "url" must be the FULL URL including domain (https://...)
- Use {param_name} placeholders for values that change between invocations
- The extract_path uses simple dot notation: "data.items" or "objects[*].name" for arrays
- If authentication might expire, include auth_recovery with the login page URL

USER-REQUESTED PARAMETERS (CRITICAL):
The user's task description often specifies what parameters the recipe should accept.
ALWAYS extract parameters mentioned in the task, even if the API URL doesn't show them yet.

Common patterns in task descriptions:
- "it takes X and Y" → X and Y are parameters
- "with X parameter" → X is a parameter
- "accepts X" → X is a parameter
- "configurable X" → X is a parameter
- "limit", "count", "per_page" → pagination parameter
- "page", "page number", "offset" → pagination parameter
- "username", "user" → user identifier parameter

If the user mentions parameters but the discovered URL doesn't include them:
1. Research the API to find the correct query parameter name
2. Add the parameter to the URL template
3. Map user terms to API terms (limit→per_page, count→per_page, page→page)

URL PARAMETERIZATION RULES:
When extracting parameters from URLs, follow these conventions:

1. Search queries: Extract search terms as {query} or {search} parameters
   - Look for q=, query=, search=, keyword= in query strings
   - The actual search term becomes the parameter, not the field name

2. Pagination: Extract count and page parameters
   - Use {per_page} or {limit} for items-per-page (default usually 10-50)
   - Use {page} for page number (default usually 1 or 0)
   - Look for: per_page=, limit=, count=, page=, offset=
   - IMPORTANT: If user mentions "limit" or "page", ensure URL includes these params!

3. Date filters: Extract date-based filters
   - Use {date}, {since}, {created_after}, or {updated_after} as appropriate
   - Keep the date format from the original URL

4. Sort/order: Keep sort and order parameters if relevant to the task
   - Usually these should stay as literal values, not parameters
   - Only parameterize if the user might want different sort orders

5. Complex query syntax: For APIs with query language (like GitHub):
   - Keep static filters (stars:>1000, language:python) as literals
   - Only extract the variable part as a parameter

EXAMPLE 1 - GitHub Search API:
Original URL:
  https://api.github.com/search/repositories?q=python+stars:>1000&sort=stars&per_page=50

Parameterized URL:
  https://api.github.com/search/repositories?q={query}+stars:>1000&sort=stars&per_page={count}

Parameters:
  [
    {"name": "query", "source": "query", "required": true, "default": null},
    {"name": "count", "source": "query", "required": false, "default": "50"}
  ]

Note: "stars:>1000" stays literal because it's a static filter, not user input.
      "sort=stars" stays literal because sorting is part of the recipe behavior.

EXAMPLE 2 - User-requested parameters (GitHub User Stars):
Task: "get starred repos for a GitHub user, it takes limit and page number"
Original URL discovered: https://api.github.com/users/octocat/starred

The user explicitly requested "limit" and "page number" parameters!
Parameterized URL:
  https://api.github.com/users/{username}/starred?per_page={limit}&page={page}

Parameters:
  [
    {"name": "username", "source": "url", "required": true, "default": null, "description": "GitHub username"},
    {"name": "limit", "source": "query", "required": false, "default": "30", "description": "Number of repos per page"},
    {"name": "page", "source": "query", "required": false, "default": "1", "description": "Page number"}
  ]

Note: Even though the discovered URL didn't have ?per_page=&page=, we ADD them because
      the user explicitly said "it takes limit and page number". Map user terms to API terms.

If no suitable API was found, return:
{
    "success": false,
    "reason": "Explanation of why no API was found"
}
"""


def get_analysis_prompt(task: str, result: str, api_calls: list[dict]) -> str:
    """Generate the analysis prompt with recorded data.

    Args:
        task: Original user task
        result: Agent's final result
        api_calls: List of API call summaries from recorder

    Returns:
        Formatted prompt for recipe analysis
    """
    # Format API calls for the prompt
    api_calls_text = ""
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

    return f"""Analyze this browser session to extract a reusable recipe.

ORIGINAL TASK:
{task}

AGENT RESULT:
{result}

API CALLS RECORDED (XHR/Fetch only):
{api_calls_text}

Identify the "money request" - the API call that returned the data the user asked for.
Consider which endpoint returned data most relevant to the task.

CRITICAL - EXTRACT PARAMETERS FROM THE TASK:
Read the ORIGINAL TASK carefully. The user often specifies what parameters the recipe should accept.
Look for phrases like "it takes X", "with X parameter", "accepts X and Y", etc.
These MUST become recipe parameters, even if the discovered URL doesn't include them yet.
Research the API docs mentally to map user terms (limit, count, page) to API params (per_page, page).

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
