Meta-Block
Scope: Revise the plan doc to be more reliable, faster in practice, safer under hostile inputs, and easier to execute as a real MCP server project (with emphasis on recipes).
Confidence score: 0.78 (probable). I’m confident about the engineering gaps/patterns; I’m not validating runtime behavior from code here.
Perspective: Production-minded MCP server reviewer; assumes single-user localhost is the default, but treats “non-localhost access” as hostile-by-default because it’s explicitly on the roadmap. 

---

## 1) Add deterministic candidate ranking + replay verification gating to the recipe learning pipeline

Why this makes the plan better
Right now the pipeline is “record → LLM picks money request → store → execute”, and you already observed the LLM struggles on simple GETs (20% success). 
A deterministic ranker reduces LLM load, improves repeatability, and makes “simple GET” cases easier because the model sees fewer, better candidates.
A replay verifier turns recipe creation into a gated process: recipes don’t become “real” until they re-run successfully (same browser context, same params shape). That prevents low-quality recipes from polluting the library and reduces long-term maintenance.

Proposed diff

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.3 Recipes System (Alpha, Active Development)
 
-The recipes pipeline has 4 stages:
+The recipes pipeline has 6 stages (with hard gating between each stage):
 
```

## -LEARN                    ANALYZE                  STORE               EXECUTE

* Agent runs task         LLM identifies           YAML written        Two paths:
* while CDP recorder      "money request"          to ~/.config/
* captures all            from captured            browser-recipes/    ┌─ Direct: CDP fetch() ~2s
* network traffic         traffic                                      │  (if recipe.request exists)
* ```
                                                                   │
  ```
* recorder.py ──────────> analyzer.py ───────────> store.py ──────────>├─ Hint-based: browser-use ~60s
* ```
                                                                   │  (fallback with navigation hints)
  ```
* ```
                                                                   │
  ```
* ```
                                                                   └─ Auth recovery: re-auth on 401/403
  ```

+RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             VERIFY+PROMOTE                 EXECUTE
+

* Agent runs task       Recorder produces         LLM selects best             Replay recipe immediately      Two paths (AUTO):
* while CDP recorder    redacted, normalized      candidate + parameters       in same browser context       ┌─ Direct: fast path (verified)
* captures network      request/response set      + extract spec               and compares output           │
* traffic               + heuristic top_k list                                  to expected shape             ├─ Hint-based: browser-use fallback
* ```
                                                                                                         │
  ```
* recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> verifier.py ──> store.py ──> runner.py/executor.py

```

| Component | Status | Notes |
|-----------|--------|-------|
| CDP network recorder | ✅ Working | Captures XHR/Fetch + JSON documents |
+| Candidate ranker (heuristic) | ❌ Not started | Scores requests to generate top_k candidates for LLM (fixes simple GET failures) |
| LLM recipe analyzer | ⚠️ Partial | Works for complex APIs (Algolia), struggles with simple GETs |
+| Recipe validator (schema+safety) | ❌ Not started | Rejects unsafe schemes/ports/redirects, enforces parameter typing, sets allowed_domains deterministically |
| YAML recipe store | ✅ Working | CRUD + usage tracking |
| Direct execution (CDP fetch) | ✅ Working | SSRF protection, 1MB cap, domain allowlist |
| HTML extraction (CSS selectors) | ✅ Working | @attr suffix support, selector validation |
| Hint-based fallback | ✅ Working | Injects navigation hints into agent prompt |
| Recipe manifest (batch learning) | ✅ Schema done | Used for E2E tests, not yet for batch pipeline |
| Batch learning pipeline | ❌ Not started | Need resume capability, rate limiting |
-| Recipe verification | ❌ Not started | Need replay-based verification |
+| Recipe verification | ❌ Not started | Replay-based verification + promotion (draft → verified) to prevent junk recipes |
```

---

## 2) Make recipe execution an explicit “AUTO strategy” with a single API surface (`recipe_run`), not a growing set of tools

Why this makes the plan better
You already have tool-count drift (“expects 9, has 10”) and a new `recipe_run_direct` mentioned. 
A single `recipe_run` tool with `strategy: auto|direct|hint` avoids API sprawl, reduces client-side confusion, and simplifies testing (one contract).
It also makes performance work easier: you can improve “auto” internally without breaking clients.

Proposed diff

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 │  │   MCP Tools:                            │   REST API:                │
 │  │   - run_browser_agent                   │   GET  /api/health         │
 │  │   - run_deep_research                   │   GET  /api/tasks          │
-│  │   - recipe_list/get/delete/run_direct   │   POST /api/learn          │
+│  │   - recipe_list/get/delete/run          │   POST /api/learn          │
 │  │   - health_check, task_list/get/cancel  │   SSE  /api/events         │
@@
 ## 1.5 Test Coverage
@@
 | MCP tools protocol | `test_mcp_tools.py` | 15+ | ⚠️ Tool count mismatch |
@@
 ### Test Debt
@@
-- [ ] `test_mcp_tools.py` expects 9 tools, server has 10 (recipe_run_direct added)
+- [ ] `test_mcp_tools.py` expects 9 tools, server has 10 (replace recipe_run_direct with recipe_run(strategy=...))
```

---

## 3) Fix the biggest real-world perf trap: eliminate “full navigation” as a prerequisite for fast JSON recipes

Why this makes the plan better
Your “direct exec ~2 seconds” claim is undermined by measured 8–24s (and 97s) direct exec results. 
The likely culprit is origin navigation + load waiting. If you must navigate to set same-origin before fetch, “direct” stops being direct.
A more performant architecture is to use a browser-context HTTP client that shares cookies/session but is not blocked by CORS. In Playwright terms this is typically an API request context associated with the BrowserContext. If that works reliably, you get true “no navigation” fast path. If it fails for a site, fall back to in-page fetch.

Proposed diff (plan-level change: describe multi-transport direct execution)

````diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
 
 ```python
-# runner.py: How a recipe executes in ~2 seconds
+# runner.py: How a recipe executes fast (target p50 < 3s) without mandatory page navigation
 
 async def run(recipe, params, browser_session):
     url = recipe.request.build_url(params)        # Template substitution
 
     await validate_url_safe(url)                    # SSRF check + DNS rebinding
     await validate_domain_allowed(url, recipe.request.allowed_domains)
 
-    cdp_session = await self._get_cdp_session(browser_session)  # Enable Page + Runtime
+    # Prefer a browser-context HTTP client (shares cookies/session, avoids CORS + avoids full navigation).
+    # Fallback to in-page fetch only when required by a site.
+    transport = self._select_transport(recipe, browser_session)  # "context_request" | "in_page_fetch"
 
     if recipe.request.response_type == "html" and recipe.request.html_selectors:
         # HTML mode: navigate to page, run CSS selectors via Runtime.evaluate
-        await cdp_session.send("Page.navigate", {"url": url})
+        cdp_session = await self._get_cdp_session(browser_session)  # Enable Page + Runtime
+        await cdp_session.send("Page.navigate", {"url": url})
         result = await cdp_session.send("Runtime.evaluate", {
             "expression": js_selector_code,  # querySelectorAll + @attr extraction
             "awaitPromise": True
         })
     else:
-        # JSON mode: navigate to domain (for cookies), then fetch() via JS
-        await self._navigate_to_domain(browser_session, cdp_session, url)
-        await validate_url_safe(url)  # Re-validate (TOCTOU protection)
-        result = await cdp_session.send("Runtime.evaluate", {
-            "expression": fetch_js_code,  # fetch() + JSON parse + size cap
-            "awaitPromise": True
-        })
+        # JSON mode:
+        # (1) context_request: no navigation, fastest path
+        # (2) in_page_fetch: only if site requires in-page execution
+        result = await self._execute_json_request(transport, url, recipe, browser_session)
 
     return RecipeRunResult(success=True, data=extracted_data)
````

````

---

## 4) Expand SSRF defenses to cover redirects, ports, IPv6, URL edge cases, and “agent path” SSRF (not just recipes)

Why this makes the plan better  
The current threat model assumes direct execution is the main SSRF surface. In reality, `run_browser_agent` can be used as an SSRF primitive too if the server is reachable remotely (even with auth).  
Also, modern SSRF bypasses often rely on redirect chains, IPv6 literals, unusual encodings, and non-http(s) schemes. The plan doesn’t enumerate these, so you’ll miss tests and regressions.

Proposed diff (threat model + invariants)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 4. Threat Model
 
 ### Failure Modes
 
 | Threat | Impact | Guardrail | Test |
 |--------|--------|-----------|------|
 | SSRF via recipe URL | Internal network access | `validate_url_safe()` blocks private IPs + DNS rebinding | `test_recipes_security.py` |
+| SSRF via redirects | Internal network access via 30x chains | Re-validate every redirect hop; cap redirect count; block scheme changes | `test_recipes_security.py::test_ssrf_redirect_*` |
+| SSRF via IPv6/encoded IP | Private net access via parsing ambiguity | Normalize/parse host strictly; block IPv6 private ranges; reject non-canonical IP encodings | `test_recipes_security.py::test_ssrf_ip_parsing_*` |
+| SSRF via non-http(s) schemes | Local file / browser weirdness | Reject `file:`, `data:`, `blob:`, `ftp:`; allow only `http`/`https` | `test_recipes_security.py::test_scheme_allowlist` |
+| SSRF via agent navigation | Internal network reachability through full browser automation | Apply the same URL safety checks to navigation targets (not only recipe runner) | `test_security_agent_navigation.py` |
 | Credential leakage in YAML | API keys exposed in recipe files | `strip_sensitive_headers()` removes Auth/Cookie headers | `test_recipes_security.py` |
 | Remote CDP connection | RCE via remote browser control | Config validator rejects non-localhost CDP URLs | `test_config.py` |
@@
 ### Safety Invariants
 
 1. No recipe YAML file ever contains a value for Authorization, Cookie, or X-Api-Key headers
-2. Direct execution never reaches private IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x, ::1)
+2. All outbound HTTP(S) (direct OR agent navigation) never reaches private IP ranges (IPv4 + IPv6), including via redirects
 3. CDP connections are localhost-only
 4. Response bodies cannot exceed 1MB
 5. Task results in SQLite cannot exceed 10KB
````

---

## 5) Treat secret leakage as a full data-lifecycle problem (recording → prompts → YAML → logs → SQLite → SSE), not just “strip headers in YAML”

Why this makes the plan better
Stripping headers before YAML persistence is necessary but not sufficient. Secrets can leak through:

1. captured request bodies (GraphQL variables, auth tokens),
2. query params (`?token=`),
3. LLM prompts (sending raw headers/bodies),
4. logs / task DB / SSE events.
   The plan should explicitly declare where redaction occurs, and add invariants/tests for those channels.

Proposed diff (Non-Negotiables + Invariants)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
 
@@
-2. **Recipes never store secrets.** Authorization, Cookie, X-Api-Key headers are stripped before YAML persistence.
+2. **Secrets are redacted end-to-end.** Sensitive headers, cookies, query params, and request bodies are redacted before:
+   - writing YAML
+   - writing task results to SQLite
+   - emitting SSE events
+   - logging (structured logs)
+   - sending any content to LLMs (analyzer prompts)
@@
 ## 0.2 Invariants (Testable)
 
 | Invariant | Test |
 |-----------|------|
 | Recipes never contain Authorization/Cookie headers | `test_recipes_security.py` |
+| Recorder output never contains secrets (headers/query/body) | `test_recorder_redaction.py` |
+| Analyzer prompts never contain secrets (headers/query/body) | `test_analyzer_redaction.py` |
+| SSE payloads never contain secrets | `test_sse_redaction.py` |
 | Direct execution blocks private IPs | `test_recipes_security.py::test_ssrf_*` |
```

---

## 6) Harden CDP usage by isolating per-task browser contexts and narrowing what `Runtime.evaluate` can do

Why this makes the plan better
“CDP restricted to localhost” is necessary, but the bigger risk is that CDP is effectively “code exec in the browser”. Your runner uses `Runtime.evaluate`, and recipe fields influence what JS is evaluated (selectors, fetch URL, extraction). Even if you validate selectors, you want explicit constraints and isolation boundaries.
Per-task isolated BrowserContexts reduce cross-task cookie/session leakage and lower blast radius if a task goes wrong.

Proposed diff (Non-Negotiables + Threat table entry)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
@@
 4. **CDP restricted to localhost.** Remote CDP connections are rejected at config validation time.
+5. **Per-task isolation.** Each task executes in an isolated browser context by default (separate cookies/storage), unless explicitly configured otherwise.
+6. **Constrained Runtime.evaluate.** Only allow a fixed set of internal JS snippets (no recipe-provided JS). Recipe fields may only influence data inputs (URL, selectors, extract paths) after validation.
-5. **No `Any` types.** Full type annotations everywhere. Pyright enforced via pre-commit.
+7. **No `Any` types.** Full type annotations everywhere. Pyright enforced via pre-commit.
@@
 ## 4. Threat Model
@@
 | Remote CDP connection | RCE via remote browser control | Config validator rejects non-localhost CDP URLs | `test_config.py` |
+| Cross-task session bleed | Data leak across tasks | Default isolated browser contexts; explicit opt-in shared profile | `test_isolation.py` |
```

---

## 7) Decide now: split “recipe definitions” (YAML) from “usage/health stats” (SQLite) to fix concurrency and improve reliability

Why this makes the plan better
ADR-2 already admits the YAML read-modify-write race and leaves it as a “maybe move stats to SQLite”. 
If you want batch learning + concurrent tasks, you should not keep mutable counters inside YAML. Split the concerns:

* YAML: immutable-ish definition (human readable, versionable)
* SQLite: usage counters, health, last_used, failure streak, verification status transitions
  This also simplifies atomicity and allows richer analytics (p50 per recipe, failure modes).

Proposed diff (ADR-2 + Open Questions)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### ADR-2: Recipes as YAML Files
@@
 #### Consequences
 - Easy to inspect, edit, share, version control
-- No concurrent write safety (see TODO-003)
-- Usage counters stored in the same file (read-modify-write race)
-- Future: may split usage stats to SQLite (TODO-003 Option 2)
+- Recipe definitions stay in YAML (portable), but mutable stats move to SQLite (concurrent-safe)
+- YAML becomes atomic-write-only (temp file + fsync + rename), eliminating partial writes
@@
 ## 11. Open Questions
@@
-| Should usage stats move to SQLite? | Probably, avoids YAML read-modify-write race (TODO-003 Option 2) | TBD |
+| Should usage stats move to SQLite? | Yes (decision): YAML for definitions, SQLite for mutable stats/health | Decided |
```

---

## 8) Add explicit “recipe health” mechanics: failure streaks, auto-deprecation, and forced re-verification

Why this makes the plan better
Recipes rot (API changes, auth expires, anti-bot). Without health rules, you’ll accumulate slow failures and degrade UX.
You already asked “auto-expire after N failures?” but left it TBD. 
Make it explicit and testable: consecutive failure streaks trigger demotion to “draft” and require re-verification before using direct path again.

Proposed diff (Open Questions → decision + new invariants)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 11. Open Questions
@@
-| Should recipes auto-expire after N failures? | Yes, deprecate after 5 consecutive failures | TBD |
+| Should recipes auto-expire after N failures? | Yes (decision): after 5 consecutive failures, demote to draft and require re-verification | Decided |
@@
 ## 0.2 Invariants (Testable)
@@
 | Invariant | Test |
 |-----------|------|
@@
+| Verified recipes demote after N consecutive failures | `test_recipe_health.py::test_auto_demote` |
+| AUTO strategy never uses direct path for unverified/demoted recipes | `test_recipe_health.py::test_auto_strategy_gating` |
```

---

## 9) Upgrade performance planning: add p95 budgets, stage timings, and a benchmark harness that runs in CI (no real web)

Why this makes the plan better
p50-only budgets hide regressions. You want stage timings: validation, transport selection, request time, extraction time.
Also, relying on live websites for perf baselines is noisy. Add a local benchmark server and deterministic benchmarks.

Proposed diff (Performance Budgets section)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 7. Performance Budgets
 
 | Metric | Target | Current |
 |--------|--------|---------|
-| Direct recipe execution | p50 < 3s | ~2-8s depending on site |
+| Direct recipe execution | p50 < 3s, p95 < 8s | ~2-8s depending on site |
 | Browser agent execution | p50 < 60s | ~60-120s |
@@
 | Auto-learning success rate | > 60% | 20% (needs improvement) |
+
+Additional perf requirements (measured and logged per task):
+- runner stage timings: validate_url, transport_select, request, extract, postprocess
+- benchmark harness against a local deterministic test server (CI-safe)
```

---

## 10) Fill key testing gaps: redirect SSRF, fuzzing URL parsing, deterministic recorder/analyzer fixtures, and contract tests for tool schemas

Why this makes the plan better
Current tests cover a lot, but the missing ones are exactly where production breaks happen: parsing edge cases, redirect SSRF, and schema drift. 
A local deterministic test server is the fastest way to test: redirects, chunked responses, oversized bodies, slow responses, auth challenges, and “looks like JSON but isn’t”.

Proposed diff (add a Testing Strategy subsection)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.5 Test Coverage
@@
 | Integration tasks | `integration_tests/` | 20+ | ✅ Passing |
 
+### 1.6 Testing Strategy Additions (Needed for v1.0 reliability)
+
+- Deterministic local test server for recipes:
+  - redirects (incl. private IP redirect attempts)
+  - large bodies + chunked encoding + slow responses
+  - auth flows (401/403) and rate limits (429 + Retry-After)
+- Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
+- Golden fixtures for recorder output and analyzer structured JSON output (prevents prompt/schema regressions)
+- MCP tool contract tests: stable schemas + stable error envelope (prevents tool-count / shape drift)
```

---

## 11) Add missing implementation phases/tasks: verifier, ranker, benchmarks, and “CI early” (not only in Phase 4)

Why this makes the plan better
Right now the plan postpones CI to Phase 4, but you already have known failures (dashboard 404s, tool mismatch). 
Moving CI earlier forces fast feedback and prevents “works on my machine” drift, especially for MCP protocol compatibility and security invariants.

Proposed diff (Implementation Phases)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 6. Implementation Phases
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Improve analyzer prompts for simple GET APIs
+- [ ] Implement candidate ranker (heuristics + top_k) to reduce analyzer burden
+- [ ] Add validator stage (schema + safety + deterministic allowed_domains)
 - [ ] Better handling of pagination parameters
@@
 ### Phase 2: Hardening (PLANNED)
@@
 - [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
 - [ ] **P2**: Atomic RecipeStore writes (TODO-003)
@@
 - [ ] **P2**: Direct execution in REST `/api/recipes/{name}/run` (TODO-016)
+- [ ] **P2**: Add deterministic local test server + CI-safe benchmark harness
@@
 ### Phase 3: Recipe Library Scale-Up (PLANNED)
@@
 - [ ] Batch learning pipeline with resume capability
-- [ ] Replay-based recipe verification (not VCR)
+- [ ] Replay-based recipe verification + promotion gate (draft → verified)
@@
 ### Phase 4: Polish & Release (PLANNED)
@@
-- [ ] GitHub Actions CI (lint, typecheck, test on PRs)
+- [ ] GitHub Actions CI (lint, typecheck, unit+integration on PRs) — move initial CI setup to Phase 2
```

---

## 12) Fix plan inconsistencies: remove `Any` from the data model and stop overstating “~2 seconds” as a blanket claim

Why this makes the plan better
AGENTS.md says “No `Any` types”, and the plan repeats that as a non-negotiable, but the Data Model still uses `Any`. 
Also, the plan claims “~2 seconds” while current measurements show higher and inconsistent timings. 
These inconsistencies cause engineering churn because they break your stated invariants.

Proposed diff (Data Model + Executive Blueprint wording)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 The key innovation is **recipes**: the server can learn API shortcuts from browser sessions, then replay them
-in ~2 seconds instead of ~60 seconds for full browser automation. A recipe captures the "money request" (the API call
+in a few seconds instead of ~60 seconds for full browser automation (site-dependent; measure p50/p95). A recipe captures the "money request" (the API call
 that returns the actual data) and replays it directly via CDP fetch, inheriting the browser's cookies and session state.
@@
 class RecipeRunResult:
     success: bool
-    data: Any                         # Extracted data
+    data: JSONValue                   # Extracted data (no Any)
     raw_response: str | None
     status_code: int | None
     error: str | None
     auth_recovery_triggered: bool     # True if 401/403 detected
+
+# Shared type alias (used across recipes + MCP responses)
+JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
```

---

If you only implement three of these, the highest leverage ones are: (1) candidate ranker + verifier gating, (3) remove “navigate to origin” as the default JSON recipe strategy, and (4) SSRF redirect/URL-edge-case hardening.
