# Oracle Prompt: Recipe System Architecture Review

## Context

I'm building an MCP (Model Context Protocol) server that wraps browser-use for AI browser automation. The killer feature is **Recipes**: learned API shortcuts extracted from browser sessions that bypass the UI entirely for 30x speedup (2s vs 60s).

**Current state**: 20% auto-learning success rate. Target: 60%+. The system works end-to-end but the LLM analysis step frequently fails to extract usable recipes from captured network traffic.

## What I Need From You

Review my recipe system architecture and tell me:
1. What's the best way to improve the auto-learning success rate from 20% to 60%+?
2. What patterns from the reference projects should I adopt?
3. What should I simplify vs what should I keep complex?
4. Where are the biggest architectural risks?
5. What's the optimal implementation order for the next 3 phases?

For each proposed change, give detailed analysis and rationale along with git-diff style changes relative to the current architecture.

---

## System Architecture

```
MCP Client (Claude Desktop, Cursor, etc.)
       │
       │  HTTP (streamable-http on :8383)
       ▼
┌──────────────────────────────────────────┐
│   FastMCP Server (daemon)                │
│                                          │
│   MCP Tools:                             │
│   - run_browser_agent (60-120s)          │
│   - run_deep_research (2-5 min)          │
│   - recipe_list/get/delete/run_direct    │
│   - health_check, task_list/get/cancel   │
│                                          │
│   REST API + Web Dashboard + SSE         │
└──────────┬───────────────────────────────┘
           │
  ┌────────┼────────┬──────────┬────────────┐
  ▼        ▼        ▼          ▼            ▼
Config   LLM     Recipes    Research    Observability
Pydantic Factory CDP+YAML   State Mach  SQLite+SSE
         12 provs                       Task tracking
```

### Recipe Pipeline (Current)

```
LEARN                    ANALYZE                  STORE              EXECUTE

Agent runs task         LLM identifies            YAML written       Two paths:
while CDP recorder      "money request"           to ~/.config/
captures network        from captured             browser-recipes/   ├─ Direct: CDP fetch() ~2s
traffic                 traffic                                      │  (recipe.request exists)
                                                                     └─ Hint-based: agent ~60s
recorder.py ──────────> analyzer.py ──────────> store.py ────────>       (fallback)
```

### Planned 8-Stage Pipeline (from plan v2.8)

```
record → signals → candidates → analyze → validate → baseline → minimize → verify
```

---

## Current Implementation (Key Files, ~3000 LOC)

### models.py (~700 lines) - Core Data Model

```python
class RecipeRequest(BaseModel):
    """HTTP request template for direct execution."""
    url: str                    # URL with {param} placeholders
    method: str = "GET"
    headers: dict[str, str] = {}
    body_template: str | None = None
    response_type: str = "json"  # json | html | text
    extract_path: str | None = None  # JMESPath for JSON
    html_selectors: dict[str, str] = {}  # CSS selectors for HTML
    allowed_domains: list[str] = []

    def build_url(self, params: dict) -> str:
        """Build URL with parameter substitution and proper encoding."""
        # Uses urllib.parse for canonical encoding

class RecipeParameter(BaseModel):
    name: str
    source: str = "query"       # url | query | body | header
    required: bool = False
    default: str | None = None
    description: str = ""

class RecipeHints(BaseModel):
    """Navigation hints for fallback agent execution."""
    target_url: str | None = None
    navigation_steps: list[str] = []
    success_indicators: list[str] = []

class Recipe(BaseModel):
    name: str
    description: str = ""
    original_task: str = ""
    request: RecipeRequest | None = None    # For direct execution
    hints: RecipeHints = RecipeHints()      # For agent fallback
    parameters: list[RecipeParameter] = []
    category: str = "other"
    status: str = "draft"          # draft | verified | deprecated
    success_count: int = 0
    failure_count: int = 0

    @property
    def supports_direct_execution(self) -> bool:
        return self.request is not None and bool(self.request.url)
```

### recorder.py (~437 lines) - CDP Network Capture

```python
class RecipeRecorder:
    """Records network traffic during browser-use agent execution via CDP."""

    def __init__(self, page):
        self.page = page
        self.api_calls: list[dict] = []
        self.final_url: str | None = None
        self.page_html: str | None = None

    async def start_recording(self):
        """Hook into CDP Network domain to capture XHR/Fetch requests."""
        # Listens for Network.requestWillBeSent + Network.responseReceived
        # Filters: only XHR/Fetch, skips images/css/fonts
        # Captures: url, method, headers, status, content_type, response_body
        # Strips sensitive headers (Authorization, Cookie, X-Api-Key)

    async def stop_recording(self):
        """Stop recording, capture final page state."""
        self.final_url = self.page.url
        # Captures page HTML snippet for HTML-based recipes

    def get_api_calls(self) -> list[dict]:
        """Return recorded API calls, sorted by relevance."""
        # Prioritizes JSON responses, larger payloads, non-navigation requests
```

**Key problem**: The recorder captures ALL network traffic, including analytics, tracking pixels, font loads, etc. The signal-to-noise ratio is low. Currently ~20-50 requests per page load, of which 1-3 are "money requests" (the actual data APIs).

### analyzer.py (~314 lines) - LLM Recipe Extraction

```python
class RecipeAnalyzer:
    """Uses LLM to analyze recorded session and extract a recipe."""

    def __init__(self, llm):
        self.llm = llm

    async def analyze(self, task, result, api_calls, final_url, page_html) -> Recipe | None:
        """Send recorded session to LLM for recipe extraction."""
        # 1. Format the prompt with task, result, API calls, page info
        # 2. Call LLM with ANALYSIS_SYSTEM_PROMPT
        # 3. Parse JSON response
        # 4. Validate output (URL scheme, placeholder format, etc.)
        # 5. Build Recipe from validated output

    def _validate_analysis_output(self, data: dict) -> tuple[bool, str]:
        """Validate LLM output before creating recipe."""
        # Checks: URL scheme (http/https only), valid placeholders ({name} format),
        # required fields present, method is GET/POST/PUT/DELETE
```

**Key problems**:
1. LLM often picks the wrong request (analytics tracker instead of data API)
2. LLM generates incorrect JMESPath expressions
3. LLM misidentifies parameters (hardcodes values that should be params)
4. No heuristic pre-filtering before LLM analysis
5. No validation that extracted recipe actually works

### runner.py (~809 lines) - Direct Execution via CDP

```python
class RecipeRunner:
    """Executes recipes via CDP fetch() in browser context."""

    async def run(self, recipe, params, page) -> str:
        """Execute recipe directly via CDP."""
        # 1. Validate URL against SSRF protections
        # 2. Build URL with parameter substitution
        # 3. Execute via CDP page.evaluate() with fetch()
        # 4. Extract data using JMESPath (JSON) or CSS selectors (HTML)
        # 5. Return formatted result

    async def _execute_fetch(self, url, method, headers, body, page) -> dict:
        """Run fetch() in browser context via CDP evaluate."""
        # Generates JavaScript fetch() call
        # Inherits cookies/session from browser context
        # 1MB response size cap enforced in JS

    def _extract_html_data(self, html, selectors) -> list[dict]:
        """Extract data from HTML using CSS selectors."""
        # Supports @attr suffix for attribute extraction (e.g., "a@href")
        # Returns list of dicts with field values
```

### store.py - YAML Persistence

```python
class RecipeStore:
    """Persists recipes as YAML files in ~/.config/browser-recipes/."""

    def save(self, recipe: Recipe) -> Path
    def load(self, name: str) -> Recipe | None
    def list_recipes(self) -> list[Recipe]
    def delete(self, name: str) -> bool
    def update_stats(self, name: str, success: bool) -> None
```

**Known issues**: Non-atomic writes, sync I/O in async context, no name collision handling.

### prompts.py (~260 lines) - LLM Prompts

Two main prompts:
1. **LEARNING_MODE_SUFFIX**: Appended to user's task when learn=True. Instructs the agent to find and test CSS selectors using JavaScript evaluate().
2. **ANALYSIS_SYSTEM_PROMPT**: Instructs LLM to analyze recorded session and output structured JSON with recipe type (api/html/hints), request details, parameters, etc.

---

## Reference Projects Analysis

### 1. mitmproxy2swagger (closest to our recorder→analyzer)
- Parses HAR/mitmproxy traffic → OpenAPI specs
- **Key patterns we should adopt**:
  - Path parameterization: detects numeric/UUID segments and replaces with `{id}`
  - URL-to-params extraction with type inference (number vs string)
  - Heuristic file format detection
  - Incremental schema merging

### 2. Workflow Use (browser-use team's record & replay)
- Records screen interactions → LLM converts to deterministic workflows
- **Key patterns**:
  - Variable detection with regex patterns + confidence scoring
  - Semantic converter: CSS selectors → visible text targets
  - Agentic fallback when deterministic replay fails
  - YAML/JSON file storage with UUID per workflow

### 3. Skyvern (browser automation + workflow caching)
- Vision LLM + browser automation with action caching
- **Key patterns**:
  - TTLCache for compiled workflow scripts (128 max, 1hr TTL)
  - Element hash matching for cached action replay
  - Pydantic Settings with env file hierarchy
  - Task/WorkflowRun schemas with status tracking

### 4. Agent Workflow Memory (AWM) - ICML 2025
- Extracts reusable "workflow routines" from agent trajectories
- 24.6% improvement on Mind2Web, 51.1% on WebArena
- **Key insight**: Low-level precise replay + high-level generalized summaries

### 5. AgentRR - Record & Replay (arxiv 2505.17716)
- Multi-level experience design for agent replay
- Check functions as trusted computing base for replay integrity

---

## Current Problems (Why 20% Success Rate)

### Problem 1: Signal-to-Noise in Network Capture
The recorder captures 20-50 requests per page. The "money request" (actual data API) is buried among analytics, tracking, fonts, images. Currently no pre-filtering.

### Problem 2: LLM Picks Wrong Request
Without pre-filtering, the LLM often selects a tracking pixel or analytics call as the "API endpoint" instead of the actual data response.

### Problem 3: Parameter Detection Failures
The LLM hardcodes values that should be parameters (e.g., hardcodes "react" instead of using `{query}`), or creates invalid JMESPath expressions.

### Problem 4: No Verification
Extracted recipes are never validated by actually running them. A recipe could be saved with a broken URL or wrong extract_path and only fails at execution time.

### Problem 5: HTML vs API Classification
The system struggles to decide when to create an API-based recipe vs HTML-based recipe. Sometimes it creates an API recipe when the data only comes from rendered HTML.

---

## Planned 8-Stage Pipeline (from plan v2.8)

```
1. RECORD      - CDP network capture during agent run
2. SIGNALS     - Compute signal features per request (10-feature vector)
3. CANDIDATES  - Rank and filter to top-k candidate requests
4. ANALYZE     - LLM extracts recipe from top candidates (with heuristic fast-path)
5. VALIDATE    - Verify URL, parameters, extract_path
6. BASELINE    - Execute recipe and capture "shape fingerprint" of response
7. MINIMIZE    - Delta-debug to remove unnecessary headers/params
8. VERIFY      - Replay with different params to confirm generalization
```

Signal features (planned):
```python
signal_vector = [
    content_type_score,      # json=1.0, html=0.5, other=0.0
    response_size_score,     # normalized 0-1
    is_xhr_or_fetch,         # 1.0 or 0.0
    has_json_body,           # 1.0 or 0.0
    url_path_depth,          # normalized
    has_query_params,        # 1.0 or 0.0
    not_tracking_domain,     # 0.0 for known trackers
    status_2xx,              # 1.0 for 200-299
    initiator_type_score,    # fetch=1.0, xhr=0.8, other=0.3
    same_site_as_page,       # 1.0 if same eTLD+1
]
```

### 3-Tier Transport Strategy

```
Tier 1: httpx_public     - Safest. No cookies. For public APIs.
Tier 2: context_request  - Playwright's request API. Inherits cookies.
Tier 3: in_page_fetch    - CDP evaluate(fetch). Full DOM/CSRF context.
```

---

## Config (for context)

```python
class RecipesSettings(BaseSettings):
    enabled: bool = False          # Beta, disabled by default
    directory: str | None = None   # Default: ~/.config/browser-recipes
    validate_results: bool = True
```

## Test Coverage

- 297 tests total (unit, integration, e2e, dashboard)
- Recipe-specific tests: ~120 tests across 3 files
- E2E recipe learning: 10 pass, 3 skip (need browser setup)
- Test services: GitHub API, npm registry, RemoteOK

---

## Specific Questions for Oracle

1. **Heuristic-first vs LLM-first**: The plan calls for a "heuristic fast-path" that can extract recipes from simple GET JSON APIs without LLM. How sophisticated should this be? Should it handle most cases and only fall back to LLM for complex patterns?

2. **Signal vector design**: The 10-feature signal vector for ranking candidates seems reasonable. Are there features I'm missing? Should I use a learned ranker or keep it as weighted heuristics?

3. **Verification strategy**: The plan calls for "shape fingerprint" verification (executing the recipe and comparing response structure). What's the right fingerprint algorithm? JSON path sets? Response schema hash?

4. **Minimization**: The plan uses delta debugging (ddmin) to remove unnecessary headers/params. Is this overkill for v1? Would a simpler "try without each header" approach suffice?

5. **Transport selection**: The 3-tier transport (httpx → context_request → in_page_fetch) adds complexity. Should I start with just httpx_public + in_page_fetch and add the middle tier later?

6. **Recipe storage**: Currently YAML files. The plan calls for SQLite stats + YAML definitions. Should I just move everything to SQLite?

7. **The 20% → 60% gap**: What's the single highest-impact change to improve success rate? My hypothesis: adding the signal-based candidate filtering (stages 2-3) before LLM analysis would eliminate most false positives.

8. **Scope for v1**: The plan is very comprehensive (8 stages, 3 transports, 5 quality gates, 25+ threat model entries). What's the minimum viable slice that gets recipes working reliably?

---

## Constraints

- Personal project, single developer
- Python 3.11+, FastMCP 3.0, browser-use, Pydantic v2
- Must remain an MCP server (HTTP transport)
- No production infra (localhost only for now)
- Default LLM: moonshotai/kimi-k2.5 via OpenRouter (cheap, fast)
- Must not break existing 297 tests
