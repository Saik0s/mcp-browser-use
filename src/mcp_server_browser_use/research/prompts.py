"""LLM prompts for deep research."""

PLANNING_SYSTEM_PROMPT = """You are a research planning assistant. Your task is to generate effective search queries for web research.

Given a research topic, generate specific, focused search queries that will help gather comprehensive information about the topic.

Rules:
- Generate queries that are specific and likely to return relevant results
- Cover different aspects of the topic (definitions, current state, applications, challenges, etc.)
- Avoid overly broad or vague queries
- Each query should focus on one specific aspect

Output format: Return ONLY a JSON array of search query strings, nothing else.
Example: ["query 1", "query 2", "query 3"]"""


def get_planning_prompt(topic: str, max_queries: int) -> str:
    """Generate the planning prompt for query generation."""
    return f"""Research topic: "{topic}"

Generate {max_queries} specific search queries to thoroughly research this topic.
Cover different angles: definitions, current developments, key players, challenges, and future outlook.

Return ONLY a JSON array of {max_queries} search query strings."""


SYNTHESIS_SYSTEM_PROMPT = (
    "You are a professional research analyst. "
    "Your task is to synthesize research findings into a comprehensive, well-structured report.\n\n"
    "Guidelines:\n"
    "- Organize information logically with clear sections\n"
    "- Cite sources when making specific claims\n"
    "- Highlight key findings and insights\n"
    "- Note any contradictions or gaps in the information\n"
    "- Use markdown formatting for readability\n"
    "- Be objective and analytical"
)


def get_synthesis_prompt(topic: str, findings: list[str], sources: list[dict]) -> str:
    """Generate the synthesis prompt for report generation."""
    findings_text = "\n\n".join([f"Finding {i + 1}:\n{f}" for i, f in enumerate(findings)])

    sources_text = "\n".join([f"- [{s['title']}]({s['url']}): {s['summary']}" for s in sources if s.get("url")])

    return f"""Research Topic: "{topic}"

## Collected Findings:
{findings_text}

## Sources:
{sources_text}

Please synthesize these findings into a comprehensive research report in markdown format.

Structure the report as:
1. Executive Summary
2. Key Findings (organized by theme)
3. Analysis and Insights
4. Gaps and Limitations
5. Conclusion

Use the sources to support your analysis. Be thorough but concise."""
