"""Prompts for skill learning and execution.

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
- This means the task cannot be learned as a skill
"""


# --- Skill Analysis Prompt ---
# LLM analyzes recorded network traffic to extract a skill

ANALYSIS_SYSTEM_PROMPT = """You are a browser automation expert analyzing network traffic to extract reusable skills.

Your task is to identify the "money request" - the single API call that returns the data the user asked for.

A good money request:
- Returns JSON data that matches what the user asked for
- Is a single endpoint (not multiple calls)
- Has clear parameters that can be templated
- Returns structured data (not HTML)

Output a JSON object with:
{
    "success": true/false,
    "reason": "Why this succeeded or failed",
    "money_request": {
        "endpoint": "/api/path",
        "method": "GET or POST",
        "content_type": "application/json",
        "identifies_by": "How to identify this request (e.g., operationName, URL pattern)",
        "response_path": "JSONPath to the data (e.g., data.jobs.edges)",
        "parameters": [
            {"name": "param_name", "source": "url|body|query", "required": true/false}
        ]
    },
    "navigation_steps": [
        {"url_pattern": "example.com/path", "description": "What this page is"}
    ],
    "skill_name_suggestion": "suggested-skill-name",
    "skill_description": "What this skill does"
}

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
        Formatted prompt for skill analysis
    """
    # Format API calls for the prompt
    api_calls_text = ""
    for i, call in enumerate(api_calls, 1):
        api_calls_text += f"""
{i}. {call['method']} {call['url']}
   Status: {call['status']}
   Content-Type: {call['content_type']}
   Has Response Body: {call['has_body']}
"""
        if call.get("post_data"):
            api_calls_text += f"   Request Body: {call['post_data'][:500]}...\n"
        if call.get("response_body"):
            api_calls_text += f"   Response Body (truncated): {call['response_body'][:1000]}...\n"

    return f"""Analyze this browser session to extract a reusable skill.

ORIGINAL TASK:
{task}

AGENT RESULT:
{result}

API CALLS RECORDED (XHR/Fetch only):
{api_calls_text}

Identify the "money request" - the API call that returned the data the user asked for.
Consider which endpoint returned data most relevant to the task.

Return your analysis as JSON.
"""


# --- Hint Injection Prompt ---
# This is PREPENDED to the user's task when executing with a skill

def get_execution_hints(skill_name: str, hints_text: str) -> str:
    """Generate execution hints from a skill.

    Args:
        skill_name: Name of the skill being used
        hints_text: Formatted hints from SkillHints.to_prompt()

    Returns:
        Formatted hints to prepend to task
    """
    return f"""SKILL HINTS (from previous successful execution of "{skill_name}"):

{hints_text}

Use these hints to navigate efficiently. If the hints don't match
what you see (API changed, page restructured), fall back to normal exploration.

YOUR TASK:
"""
