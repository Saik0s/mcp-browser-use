> **Scope:** Review and revise the shipping plan (v2.2) and dev guide to improve robustness, security, performance, testability, and DX/API shape for a real Python MCP server project.  
> **Confidence:** 0.8 (probable).
> **Perspective:** Practical “ship-it” engineering review: prioritize safety invariants + deterministic execution first, then speed and ergonomics.

Assumptions

* The plan text is the authoritative roadmap and already reflects the current architecture (FastMCP daemon over HTTP, Playwright/Chromium, recipes as YAML + stats in SQLite).  
* “Recipes” are intended to be a fast, replayable API shortcut learned from captured browser network traffic, with a direct execution fast path and browser-agent fallback.  
* Security non‑negotiables already include redaction, SSRF protections, and localhost-only CDP by default; these should remain hard gates. 

---

## Proposed Change 1: Add a “Minimize + Parameterize” stage to the recipe learning pipeline (reduces brittleness + leakage, increases learn success)

Why this makes the plan better
Right now the pipeline jumps from “analyze/validate” to “verify/promote” and then stores/executes the recipe. 
In practice, captured “money requests” almost always include noise: cache-busters, timestamps, telemetry params, superfluous headers, and semi-random body fields. If you store and replay those verbatim you get: fragile recipes (shape drift / random 400s), accidental secret-ish material in artifacts, and lower auto-learning success on simple GETs (because the request looks “unique” every run).

A dedicated minimization step makes recipes:

* More reliable: removes volatile fields and stabilizes templates.
* More secure: reduces attack surface and reduces odds of persisting sensitive-ish tokens in artifacts (even post-redaction).
* More performant: smaller requests, fewer unnecessary headers, fewer redirects.

This is also the easiest lever to move auto-learning success rate up without overfitting prompts. Prompts can select the right request; minimization makes it replayable.

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-### 1.3 Recipes System (Alpha, Active Development)
+### 1.3 Recipes System (Alpha, Active Development)
@@
-The recipes pipeline has 6 stages (with hard gating between each stage):
+The recipes pipeline has 7 stages (with hard gating between each stage):
@@
-RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             VERIFY+PROMOTE                 EXECUTE
+RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             MINIMIZE+PARAMETERIZE          VERIFY+PROMOTE                 EXECUTE
@@
-recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+
+MINIMIZE+PARAMETERIZE (new, required for v1):
+- Remove volatile/query noise (cache-busters, timestamps, tracking params) using deterministic rules + replay checks.
+- Attempt request “minimization”: drop headers/body fields one-by-one to find the minimal subset that preserves the expected shape.
+- Convert detected dynamic fields into typed RecipeParameters (instead of baking values into the template).
+- Output a stable RecipeDraft that is meaningfully replayable, not just “captured”.
@@
 ### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
@@
 Artifacts (all redacted; never store secrets):
 - `SessionRecording` (from recorder): normalized JSONL of network events + minimal page context
 - `CandidateSet` (from ranker): top_k candidate request IDs with scores + feature breakdown
 - `RecipeAnalysis` (from analyzer): strict JSON output from LLM (schema-validated)
 - `RecipeDraft` (from validator): safe, canonical recipe ready for replay
+- `MinimizationReport` (from minimizer): dropped fields + volatility flags + “minimal sufficient” proof
+- `RecipeDraftMinimized` (from minimizer): minimized, parameterized recipe ready for verification replay
 - `VerificationReport` (from verifier): replay results + extracted shape fingerprint + promotion decision
@@
 #### Phase 1 deliverables (make modules real)
 - [ ] Add `recipes/candidates.py` (pure functions + unit tests; no LLM calls)
 - [ ] Add `recipes/validator.py` (schema + safety canonicalization; no network I/O)
+- [ ] Add `recipes/minimizer.py` (replay-based minimization + volatility detection; bounded attempts; emits reports)
 - [ ] Add `recipes/verifier.py` (replay + shape fingerprint + promotion rules)
 - [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
```

---

## Proposed Change 2: Make direct recipe execution explicitly “engineered”: transport tiers, compiled extractors, retries/backoff, and realistic perf budgets

Why this makes the plan better
The plan already targets p50 < 3s for direct execution, but your current “manual recipe” timings include 6–25s for real external services.  
That mismatch matters: it will cause endless thrash (“why is direct still slow?”) unless you separate (a) runner overhead from (b) network + remote service latency.

Also, direct execution is currently framed as two transports: Playwright `context.request` and in-page fetch. 
In practice, you want three tiers:

1. **Sessionless safe HTTP client** for public APIs that do not require browser cookies/session (fast, safest SSRF posture).
2. **Playwright context.request** for cookie/session dependent APIs without page JS requirements.
3. **In-page fetch** only when you truly need DOM/JS/sessionStorage/CSRF extracted from a live page.

Separately: compile/caching matters. Parsing YAML, compiling JMESPath, and setting up selector machinery on every run is pointless overhead in an always-on daemon.

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### ADR-3: CDP Fetch for Direct Execution
@@
-#### Decision (revised)
-Default to Playwright `context.request` for direct execution (cookies + controllable redirects/timeouts/body caps).
-Use CDP in-page `fetch()` only when recipe explicitly requires page context.
+#### Decision (revised)
+Direct execution uses a 3-tier transport strategy (explicitly modeled per recipe):
+1) `httpx_public` (new): sessionless, safest default for public APIs (no browser cookies; easiest to harden + benchmark).
+2) `context_request` (default when session is required): Playwright `context.request` for cookie/session dependent APIs.
+3) `in_page_fetch` (fallback-only): CDP in-page `fetch()` only when recipe requires page context (DOM/CSRF/sessionStorage/CORS parity).
+
+Recipes MUST declare (or verifier MUST infer) `requires_session` and `transport_hint`. AUTO uses the lowest-risk transport that passes verification.
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-async def run(recipe, params, browser_session):
-    url = recipe.request.build_url(params)        # Template substitution
+async def run(recipe, params, browser_session):
+    compiled = recipe_cache.get_or_compile(recipe)  # compile JMESPath/selectors + validate templates once
+    url = compiled.build_url(params)                # Template substitution
@@
-    transport = self._select_transport(recipe, browser_session)  # "context_request" (default) | "in_page_fetch" (fallback)
+    transport = self._select_transport(recipe, browser_session)  # "httpx_public" | "context_request" | "in_page_fetch"
@@
-    if recipe.request.response_type == "html" and recipe.request.html_selectors:
+    if compiled.response_type == "html" and compiled.html_selectors:
         # HTML mode (v1): fetch HTML via context.request, parse selectors in Python.
         # Navigation is fallback-only for JS-rendered pages.
-        html = await self._context_request_text(url, recipe, browser_session)
-        extracted = self._extract_html_selectors_python(html, recipe.request.html_selectors)
+        html = await self._request_text(transport, url, compiled, browser_session)
+        extracted = compiled.extract_html(html)  # compiled selectors
     else:
         # JSON mode:
         # (1) context_request: no navigation, fastest path
         # (2) in_page_fetch: only if site requires in-page execution
-        result = await self._execute_json_request(transport, url, recipe, browser_session)
+        result = await self._execute_json_request(transport, url, compiled, browser_session)
@@
 ## 7. Performance Budgets
@@
-| Direct recipe execution | p50 < 3s, p95 < 8s | ~2-8s depending on site |
+| Direct recipe execution (runner overhead on local test server) | p50 < 250ms, p95 < 800ms | (new metric; benchmark harness) |
+| Direct recipe execution (end-to-end on real sites) | target: “best effort”; log p50/p95 | currently 6-25s for some public APIs |
@@
 Additional perf requirements (measured and logged per task):
 - runner stage timings: validate_url, transport_select, request, extract, postprocess
+- network vs runner overhead MUST be split (TTFB, download, parse/extract, postprocess)
+- cache hit-rate for compiled recipes MUST be logged (to prove caching works)
```

---

## Proposed Change 3: Expand the threat model with the missing “realistic attacker” cases (localhost CSRF, response bombs, template/header injection, multi-A DNS)

Why this makes the plan better
Your threat model is already strong on classic SSRF vectors (redirects, schemes, IDN/punycode, proxy env vars, special URLs, symlink attacks). 
The missing cases are the ones that reliably bite local automation servers in the real world:

1. **Localhost CSRF / drive-by requests:** A malicious website can often trigger state-changing requests to a localhost service even if it cannot read responses (browser form POSTs / fetch with blocked CORS still performs the action). This matters because your server can launch a real browser and make outbound requests (a powerful primitive).
2. **Response bombs:** gzip/br deflate bombs and “deep JSON” can be <1MB on the wire but enormous / expensive to parse after decompression. Your 1MB cap is good, but it needs to apply *post-decompression* and parsing needs depth/complexity limits. 
3. **Template injection beyond URLs:** The plan currently focuses on URL template substitution. If parameters can be used in headers/body templates (common for GraphQL or auth-ish flows), you need CRLF and size limits.
4. **Multi-A/AAAA DNS + mixed private/public answers:** A rebinding defense that checks “one resolution” can still be bypassed if DNS returns both private and public addresses or changes between lookups.

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 4. Threat Model
@@
 ### Failure Modes
@@
 | Threat | Impact | Guardrail | Test |
 |--------|--------|-----------|------|
+| Localhost CSRF (drive-by POST/DELETE to server) | Attacker triggers browser tasks / outbound fetches | Require auth for all state-changing endpoints by default; strict Origin/Host checks for dashboard; CORS disabled | `test_http_auth.py::test_write_endpoints_require_token` |
+| Response decompression bomb (gzip/br) | OOM / CPU spike despite 1MB wire cap | Apply MAX_RESPONSE_SIZE after decompression; disable compression or cap decompressed bytes; streaming read with hard stop | `test_recipes_security.py::test_decompression_cap` |
+| Deep JSON / parser bomb | CPU spike / recursion errors | JSON depth + token count limits; reject overly nested structures; fallback to raw_body (truncated) | `test_recipes.py::test_json_depth_limit` |
+| Template injection into headers/body | Request smuggling / invalid requests | Validate parameter values: no CR/LF, max length, strict type coercion; never allow templating into Host header | `test_recipes_security.py::test_crlf_blocked` |
+| DNS multi-answer / mixed private+public | SSRF bypass via rebinding edge cases | Resolve all A/AAAA; if any private/link-local/loopback present -> block; re-check on redirects | `test_recipes_security.py::test_dns_multi_answer_block` |
@@
 ### Safety Invariants
@@
 5. Task results in SQLite cannot exceed 10KB
+6. State-changing HTTP endpoints (POST/PUT/PATCH/DELETE) are authenticated by default, even on loopback
+7. MAX_RESPONSE_SIZE is enforced on decompressed bytes, not only on wire bytes
```

---

## Proposed Change 4: Security hardening tasks need to be moved from “nice-to-have” into hard gates (auth defaults, dashboard exposure, CDP launch constraints)

Why this makes the plan better
The plan acknowledges a critical P1: auth token enforcement for non-localhost. 
But the plan still implicitly treats unauthenticated localhost as acceptable for state-changing endpoints. That’s a common footgun for localhost automation servers because browsers can be induced to hit localhost.

Also, CDP “expert mode” is described well, but hardening should include one more explicit constraint: ensure the default Playwright-managed Chromium is not exposing a remote debugging port on non-loopback (and fail fast if it is). 

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0. Executive Blueprint
@@
 ### Definition of Done (v1.0)
@@
-- [ ] Auth token enforcement for non-localhost access
-  - MUST refuse `host=0.0.0.0` unless `auth_token` is set
-  - MUST refuse requests without token when not loopback
-  - MUST avoid logging tokens and redact from errors
+- [ ] Auth defaults hardened (v1 gate)
+  - MUST refuse `host=0.0.0.0` (or any non-loopback bind) unless `auth_token` is set
+  - MUST refuse all state-changing requests (POST/PUT/PATCH/DELETE) without token by default (even on loopback)
+  - MUST avoid logging tokens and redact from errors
+  - Dashboard must be disabled by default on non-loopback binds (explicit enable required)
@@
 ## 0.1 Non-Negotiables
@@
 0. **Loopback-first binding.** Default bind is `127.0.0.1`. Any non-loopback bind requires explicit config + auth token.
+0a. **Authenticated writes by default.** All state-changing endpoints require auth unless explicitly opted out for local dev.
@@
 4a. **Server-owned browser by default.** Default mode MUST launch a fresh Playwright-managed Chromium instance (no external CDP).
+4a.1 **No exposed debug port by default.** Server MUST ensure the Playwright-launched browser is not listening on a non-loopback debug port; fail-fast if detected.
@@
 ### Phase 2: Hardening (PLANNED)
@@
 - [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
-  - Add `Origin`/`Host` validation for dashboard + SSE endpoints (basic CSRF mitigation)
+  - Require auth for all write endpoints by default (even loopback); configurable dev override
+  - Add strict `Origin`/`Host` validation for dashboard + SSE endpoints (CSRF mitigation)
+  - Explicitly disable dashboard when bound to non-loopback unless `server.dashboard_enabled=true`
   - Add per-IP rate limiting (token bucket) for REST + MCP endpoints
```

---

## Proposed Change 5: Close the testing gap with a “hostile local web” harness + artifact/golden tests + cancellation chaos tests (this is where reliability actually comes from)

Why this makes the plan better
You already call out the need for a deterministic local test server and malicious web scenarios, plus fuzzing and contract tests. 
What’s missing is making these a first-class harness with explicit coverage goals, and adding the two reliability killers for daemon-style async systems:

* **Cancellation/cleanup chaos tests:** `_running_tasks` cleanup is already called out as a P2, but without repeated cancel/timeout testing it will regress. 
* **Golden tests for artifacts + analyzer JSON:** Your pipeline is artifact-based and resumable; you should lock down artifact schemas and analyzer outputs with fixtures so “prompt tweaks” don’t silently break resume/verification.

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.6 Testing Strategy Additions (Needed for v1.0 reliability)
@@
 - Deterministic local test server for recipes:
   - redirects (incl. private IP redirect attempts)
   - large bodies + chunked encoding + slow responses
   - auth flows (401/403) and rate limits (429 + Retry-After)
+  - compressed responses (gzip/br) + decompression bomb simulation
+  - deep JSON payloads + pathological-but-valid JSON structures
@@
 - Add "malicious web" scenarios:
@@
   - DNS rebinding simulation hooks (where possible)
+  - localhost CSRF attempts (cross-origin POST/DELETE that should be rejected)
@@
 - Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
 - Golden fixtures for recorder output and analyzer structured JSON output (prevents prompt/schema regressions)
+- Golden fixtures for pipeline artifacts (SessionRecording/CandidateSet/RecipeDraft/MinimizationReport/VerificationReport)
+- Chaos tests for cancellation + cleanup:
+  - start N tasks, cancel mid-flight, assert browser contexts closed and `_running_tasks` empty
+  - repeat in a loop to catch leaks (CI-safe bounds)
@@
 ## 8. Quality Gates
@@
 ### Gate 2: Pre-Merge (Manual, future CI)
@@
 **Response**: All 297 tests must pass
+
+### Gate 2a: Hostile Web Harness (Automated, CI-safe)
+**Trigger**: PR to main
+**Checks**: deterministic server suite (redirect/SSRF/decompression/depth/rate-limit) + chaos cancellation tests
+**Response**: must pass or merge blocked
```

---

## Proposed Change 6: DX/API design: stabilize a minimal tool surface, add OpenAPI for REST, and split the monolith server module

Why this makes the plan better
The plan already introduces Phase 3.5 (contract stabilization) and notes tool-count mismatch / schema pinning.  
To make this easier to execute and maintain:

1. Make the tool surface minimal and obviously orthogonal:

* One “run” tool (agent/recipe/auto), not multiple near-duplicates.
* One “learn” tool with explicit outputs (artifacts, candidates).

2. Add OpenAPI for REST endpoints:

* This makes dashboard/API work less fragile and gives you an easy way to generate a typed client for tests and contract pinning.

3. Split `server.py` (currently very large per AGENTS) into modules:

* It reduces merge conflicts, makes security review narrower, and makes it easier to test pieces in isolation. 

Git diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 3.5: Contract Stabilization (NEW, REQUIRED)
@@
 - [ ] MCP tool schemas pinned + contract tests in CI
 - [ ] Error envelope standardized across tools + REST
 - [ ] Deprecation policy documented (remove only in minor/major)
 - [ ] Version reporting endpoint: `/api/version` + `health_check` includes version + git sha (if available)
+- [ ] REST OpenAPI published at `/api/openapi.json` (or equivalent) and pinned in CI
+- [ ] Generated typed REST client used in dashboard + contract tests (reduces drift)
@@
 ### Phase 2: Hardening (PLANNED)
@@
  - [ ] Tool surface stabilization:
    - Replace `recipe_run_direct` with `recipe_run(strategy="auto"|"direct"|"hint")`
    - Add `recipe_learn(task_id=..., strategy="auto"|"interactive")` (returns candidates/artifacts when needed)
+   - Add `run(task, strategy="auto"|"agent"|"recipe")` (single entry-point; `run_browser_agent` becomes alias/deprecated)
@@
 ### Phase 4: Polish & Release (PLANNED)
@@
 - [ ] README with usage examples and Claude Desktop config
 - [ ] Changelog
+- [ ] Server module split (DX + reviewability):
+  - `server/mcp_tools.py`, `server/rest_api.py`, `server/sse.py`, `server/dashboard.py`
+  - keep `server.py` as thin composition root
```

---
