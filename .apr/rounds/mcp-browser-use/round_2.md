> Meta-Block
> Scope: Revise `plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md` to improve reliability, performance, security, testing, and developer experience, with emphasis on the recipes learning/execution pipeline and threat model. 
> Confidence score: 0.78 (high confidence on engineering/process changes; medium confidence on exact “best” recipe-learning heuristics because success is site/LLM dependent). 
> Perspective: Treat this as a localhost-first developer tool that is still security-sensitive because it can drive a real browser and make arbitrary outbound requests. Optimize for deterministic artifacts, strict contracts, and fast-path execution that fails safely. 
> Assumptions: (1) The plan is meant to drive real implementation work, not just describe an ideal architecture. (2) Recipes are expected to execute inside a logged-in browser context and must not persist secrets. (3) You want learning to become *repeatable* (debuggable + resumable) and execution to be *predictably fast* at p50/p95, not just “sometimes fast.” 

---

## Change 1 — Make the recipe learning pipeline artifact-based and resumable (debuggable by default)

Why this makes the plan better:

Right now the pipeline is conceptually staged, but it’s still easy for it to be “one long flow” where failures are hard to reproduce (LLM nondeterminism, network variability, recorder variability). Making each stage emit a versioned artifact (recording → candidates → analysis JSON → validated recipe) gives you deterministic replay, enables caching, and lets you add “resume from stage N” CLI commands. This is the single biggest reliability lever for getting from 20% → 60% learning success without drowning in “works on my machine” debugging. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 1.3 Recipes System (Alpha, Active Development)
 
 The recipes pipeline has 6 stages (with hard gating between each stage):
@@
 recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+
+### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
+
+Each stage MUST emit a versioned artifact to disk (or SQLite) so failures are reproducible and the pipeline can resume.
+
+Artifacts (all redacted; never store secrets):
+- `SessionRecording` (from recorder): normalized JSONL of network events + minimal page context
+- `CandidateSet` (from ranker): top_k candidate request IDs with scores + feature breakdown
+- `RecipeAnalysis` (from analyzer): strict JSON output from LLM (schema-validated)
+- `RecipeDraft` (from validator): safe, canonical recipe ready for replay
+- `VerificationReport` (from verifier): replay results + extracted shape fingerprint + promotion decision
+
+All artifacts include:
+- `artifact_version`
+- `task_id`
+- `source_url` (public only, redacted)
+- `created_at`
+- `sha256` of the artifact payload (integrity + dedupe)
+
+CLI support (v1 requirement):
+- `mcp-server-browser-use recipe learn --resume-from <stage>`
+- `mcp-server-browser-use recipe debug --task-id <id>` (opens artifacts + prints stage diffs)
```

---

## Change 2 — Define “minimal sufficient recording” to avoid bloating the recorder and confusing the analyzer

Why this makes the plan better:

Your analyzer currently struggles with “simple GETs.” A common reason is that recordings are either too sparse (missing initiator context like current page URL / action) or too noisy (tons of irrelevant calls). Define the *minimum* useful context that must be captured (initiator URL, frame, top-level navigation URL, response content-type, response size, parsed JSON keys sample), and explicitly cap everything else. That improves both learning success rate and analyzer token efficiency. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Support non-JSON content types in recorder (TODO-010)
+
+#### Recorder contract (new)
+- [ ] Recorder MUST capture per request:
+  - initiator page URL (sanitized)
+  - resource type (xhr/fetch/document)
+  - response `content-type`, status code, byte length
+  - JSON key sample (top-level keys only; cap at 200 chars)
+  - timing (start/end) for latency ranking
+- [ ] Recorder MUST NOT capture:
+  - full HTML documents by default
+  - more than 32KB of any response body (separate from runner 1MB cap)
+  - raw binary bodies (store metadata only)
```

---

## Change 3 — Make `candidates.py`, `validator.py`, `verifier.py` explicit deliverables (currently “ghost modules”)

Why this makes the plan better:

The plan already references `candidates.py`, `validator.py`, `verifier.py`, but the repo map in the development guide doesn’t list them as existing modules. That mismatch tends to produce implementation drift and half-built “inline logic” in random files. Call these modules out as first-class, with crisp interfaces, and you’ll reduce later refactors and test pain. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Implement candidate ranker (heuristics + top_k) to reduce analyzer burden
 - [ ] Add validator stage (schema + safety + deterministic allowed_domains)
@@
 - [ ] Fix parameter passing (wrong query terms in some cases)
+
+#### Phase 1 deliverables (make modules real)
+- [ ] Add `recipes/candidates.py` (pure functions + unit tests; no LLM calls)
+- [ ] Add `recipes/validator.py` (schema + safety canonicalization; no network I/O)
+- [ ] Add `recipes/verifier.py` (replay + shape fingerprint + promotion rules)
+- [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
```

---

## Change 4 — Candidate ranker: define scoring features and the “simple GET” fast path

Why this makes the plan better:

“LLM picks the money request” is expensive and brittle when the candidate set is large and noisy. The highest ROI improvement is a ranker that reliably surfaces the correct GET request in the top 5–8. You need to specify features now (otherwise the ranker becomes hand-wavy and never lands). Also: simple GET APIs often have obvious signals (query params include the user’s query term, JSON response has list-like structure, etc.). 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 | Component | Status | Notes |
 |-----------|--------|-------|
 | CDP network recorder | ✅ Working | Captures XHR/Fetch + JSON documents |
-| Candidate ranker (heuristic) | ❌ Not started | Scores requests to generate top_k candidates for LLM (fixes simple GET failures) |
+| Candidate ranker (heuristic) | ❌ Not started | MUST deliver top_k=8 with feature scores; optimized for simple GET APIs |
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Implement candidate ranker (heuristics + top_k) to reduce analyzer burden
+
+Candidate ranking features (v1):
+- +URL/query similarity to task + agent final answer (token overlap, normalized)
+- +Response content-type preference: JSON > HTML > text
+- +Response “list likelihood”: JSON contains array at top-level or common keys (items/results/data)
+- +Status preference: 2xx > 3xx > 4xx
+- +Latency preference: avoid extreme tail calls
+- -Penalty for likely telemetry/ads endpoints
+- -Penalty for very small bodies (< 200 bytes) and very large recorder-captured bodies (> 32KB)
+- +Bonus if request initiated near the final agent step timestamp (if available)
```

---

## Change 5 — Validator must canonicalize URL + domains using eTLD+1 rules (and lock down redirects)

Why this makes the plan better:

`allowed_domains` is currently partially populated and loosely described. You want deterministic, conservative allowlists (or you will either break recipes or accidentally widen SSRF surface). “Same host” vs “same site” is subtle (subdomains, IDNs, punycode). Canonicalization must be a *validator responsibility* with explicit rules and tests. Also: redirect policy needs to be declared. “Revalidate every hop” is necessary but not sufficient; you want to *also* restrict cross-site redirects unless explicitly allowed. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 0.1 Non-Negotiables
@@
 3. **SSRF protection on all direct execution.** Private IPs, loopback, link-local addresses blocked. DNS resolution checked for rebinding. Validated twice (before navigation AND before fetch).
@@
 6. **Constrained Runtime.evaluate.** Only allow a fixed set of internal JS snippets (no recipe-provided JS). Recipe fields may only influence data inputs (URL, selectors, extract paths) after validation.
+
+7. **Deterministic domain allowlists.** `allowed_domains` MUST be derived and canonicalized by the validator:
+   - canonical host (punycode)
+   - eTLD+1 (public suffix rules) stored separately as `allowed_sites` (future-proofing)
+   - explicit subdomain expansion only when required (no wildcards in v1)
+
+8. **Redirect policy is explicit.** Default: allow redirects only within the same canonical host; cross-host redirects require explicit validator approval (and are re-validated hop-by-hop).
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Add validator stage (schema + safety + deterministic allowed_domains)
+
+Validator requirements (v1):
+- URL canonicalization: scheme, host punycode, strip fragments, normalize default ports
+- Reject credentials-in-URL (`http://user:pass@host`)
+- Reject non-default ports unless explicitly allowlisted (80/443 by default)
+- Redirect policy enforced at execution time (host lock unless recipe explicitly allows a small set)
```

---

## Change 6 — Verifier must compute and store a “shape fingerprint” for gating and regression detection

Why this makes the plan better:

Today verification is described as “replay immediately and compare output to expected shape,” but “expected shape” isn’t defined. You need a stable, low-cost signature for “did we extract the same kind of thing?” Without that, promotion/demotion becomes subjective and fragile. A shape fingerprint (keys + array lengths bucketed + presence of required paths) lets you gate AUTO execution and detect regressions. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.3 Recipes System (Alpha, Active Development)
@@
 | Recipe verification | ❌ Not started | Replay-based verification + promotion (draft → verified) to prevent junk recipes |
+
+Verification spec (v1):
+- Compute `shape_fingerprint` on extracted output:
+  - for JSON: sorted key paths up to depth 3 + type tags + array length buckets (0/1/2-10/10+)
+  - for HTML: selector hit counts + extracted field presence map
+- Store fingerprint in SQLite stats table (not in YAML)
+- Promotion rule: 2 consecutive successful replays with matching fingerprint + no auth recovery triggered
+- Demotion rule: existing rule (5 consecutive failures) + any “shape drift” (fingerprint mismatch) demotes immediately
```

---

## Change 7 — Add an explicit “interactive learn fallback” when analysis confidence is low

Why this makes the plan better:

If the analyzer struggles with simple GETs, you need a deterministic escape hatch that doesn’t involve prompt flailing. The most practical: when ranker confidence is low or analyzer output fails validation, return a short list of top candidates (sanitized) to the MCP client so the *agent* can choose (or the user can). This often turns “learning failed” into “learning succeeded with one selection step,” and it’s still automatable. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### ADR-4: LLM-Based Recipe Analysis
@@
 #### Options
 A) Heuristic rules — Match URL patterns, response sizes
 B) LLM analysis — Understand task context, identify "money request"
-C) User selection — Present captured calls, let user pick
+C) Interactive selection — Present top_k sanitized calls, let client choose (human or LLM)
@@
 #### Decision
 LLM analysis with structured JSON output. The analyzer receives the task description, agent result, and captured API calls, then identifies the optimal recipe structure.
+
+Fallback (v1 requirement):
+If analyzer output fails schema/validator OR confidence is low, return `CandidateSet` (top_k=8) to client via:
+- MCP tool response field `learn_candidates`
+- REST endpoint `GET /api/learn/{task_id}/candidates`
+Client can then call `recipe_create_from_candidate(candidate_id, ...)`.
```

---

## Change 8 — Threat model: add missing SSRF/egress and local-file style failure modes

Why this makes the plan better:

The threat model covers classic SSRF, redirects, and encoded IPs, but misses several practical bypass avenues in browser-driven systems: proxy environment variables, WebSocket schemes, “special” browser URLs (`chrome://`, `view-source:`), credential-in-URL, IDN homographs/punycode confusion, and symlink/path traversal attacks on the YAML store. These are the ones that tend to bite MCP servers specifically. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 4. Threat Model
@@
 | Threat | Impact | Guardrail | Test |
@@
 | SSRF via non-http(s) schemes | Local file / browser weirdness | Reject `file:`, `data:`, `blob:`, `ftp:`; allow only `http`/`https` | `test_recipes_security.py::test_scheme_allowlist` |
+| SSRF via proxy env vars | Internal egress via HTTP_PROXY/HTTPS_PROXY | Ignore proxy env vars by default for all outbound in direct exec; explicit opt-in only | `test_recipes_security.py::test_proxy_env_ignored` |
+| SSRF via websocket schemes | Internal access via ws/wss | Explicitly reject ws/wss in URL validator | `test_recipes_security.py::test_scheme_allowlist` |
+| Browser special URLs | Local data exfil / privileged pages | Block `chrome://`, `about:`, `view-source:` navigation + fetch targets | `test_security_agent_navigation.py::test_block_special_urls` |
+| Credentials in URL | Secret leakage + weird parsing | Reject `user:pass@host` in validator | `test_recipes_security.py::test_reject_userinfo_in_url` |
+| IDN / punycode confusion | Allowlist bypass | Validator canonicalizes punycode; compare canonical host only | `test_recipes_security.py::test_idn_canonicalization` |
+| Recipe store symlink attack | Write outside recipes dir | Atomic write + `O_NOFOLLOW` (where supported) + path canonicalization | `test_recipe_store_security.py` |
```

---

## Change 9 — Security hardening: treat HTTP exposure as hostile-by-default (auth + origin + rate limits)

Why this makes the plan better:

The plan already flags missing auth enforcement for non-localhost as P1. I’d tighten this into a default posture: bind to loopback by default, refuse non-loopback unless an auth token is set, and implement basic origin checks for browser-accessed endpoints (dashboard/SSE). Add rate limiting to reduce accidental self-DoS and make “remote exposure” less catastrophic. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Definition of Done (v1.0)
@@
 - [ ] Auth token enforcement for non-localhost access
+  - MUST refuse `host=0.0.0.0` unless `auth_token` is set
+  - MUST refuse requests without token when not loopback
+  - MUST avoid logging tokens and redact from errors
@@
 ## 0.1 Non-Negotiables
@@
 1. **HTTP transport only.** Stdio is blocked with a migration message. Browser tasks take 60-120s; stdio timeouts kill them.
+0. **Loopback-first binding.** Default bind is `127.0.0.1`. Any non-loopback bind requires explicit config + auth token.
@@
 ### Phase 2: Hardening (PLANNED)
@@
 - [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
+  - Add `Origin`/`Host` validation for dashboard + SSE endpoints (basic CSRF mitigation)
+  - Add per-IP rate limiting (token bucket) for REST + MCP endpoints
```

---

## Change 10 — CDP security: explicitly prevent “connect to a hostile browser” and reduce accidental debug-port exposure

Why this makes the plan better:

“CDP restricted to localhost” is necessary, but it’s not the whole story. If a user connects to an already-running browser with a debugging port, that browser might have a shared profile, dangerous extensions, or other contexts. Also, Chrome debugging can be exposed beyond localhost if launched incorrectly. The plan should explicitly define (a) safest default (server launches its own Chromium), (b) what’s allowed for external CDP, and (c) warnings + tests. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 0.1 Non-Negotiables
@@
 4. **CDP restricted to localhost.** Remote CDP connections are rejected at config validation time.
+4a. **Server-owned browser by default.** Default mode MUST launch a fresh Playwright-managed Chromium instance (no external CDP).
+4b. **External CDP is “expert mode”.** Requires explicit flag + strong warnings + additional checks:
+    - only loopback host
+    - explicit port allowlist
+    - disallow ws URLs unless explicitly supported and validated
+    - require isolated user-data-dir unless explicitly overridden
@@
 ## 4. Threat Model
@@
 | Remote CDP connection | RCE via remote browser control | Config validator rejects non-localhost CDP URLs | `test_config.py` |
+| Hostile local CDP browser | Data exfil / unexpected extensions | External CDP requires explicit enable + isolated profile recommendation | `test_config.py::test_external_cdp_requires_explicit_enable` |
```

---

## Change 11 — Recipe execution performance: default to `context.request` + parse HTML in Python (avoid Runtime.evaluate when possible)

Why this makes the plan better:

Your plan already gestures at a multi-transport strategy. I’d make it sharper: JS `fetch()` via CDP is the most security-sensitive (JS eval) and often slower (serialization + eval overhead) than Playwright’s `context.request`, while still not giving you strong SSRF pinning. For many APIs, cookies are sufficient and `context.request` is faster and easier to control (timeouts, redirects, max body). For HTML extraction, fetching HTML then parsing in Python avoids navigation and avoids any JS evaluation entirely. That improves p50/p95 and reduces attack surface. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-    # Prefer a browser-context HTTP client (shares cookies/session, avoids CORS + avoids full navigation).
-    # Fallback to in-page fetch only when required by a site.
-    transport = self._select_transport(recipe, browser_session)  # "context_request" | "in_page_fetch"
+    # Transport priority (v1):
+    # 1) Playwright context.request (fastest, controllable, shares cookies)
+    # 2) In-page fetch (only if required: CSRF token in DOM, strict CORS behavior, sessionStorage dependence)
+    transport = self._select_transport(recipe, browser_session)  # "context_request" (default) | "in_page_fetch" (fallback)
@@
-    if recipe.request.response_type == "html" and recipe.request.html_selectors:
-        # HTML mode: navigate to page, run CSS selectors via Runtime.evaluate
-        cdp_session = await self._get_cdp_session(browser_session)  # Enable Page + Runtime
-        await cdp_session.send("Page.navigate", {"url": url})
-        result = await cdp_session.send("Runtime.evaluate", {
-            "expression": js_selector_code,  # querySelectorAll + @attr extraction
-            "awaitPromise": True
-        })
+    if recipe.request.response_type == "html" and recipe.request.html_selectors:
+        # HTML mode (v1): fetch HTML via context.request, parse selectors in Python.
+        # Navigation is fallback-only for JS-rendered pages.
+        html = await self._context_request_text(url, recipe, browser_session)
+        extracted = self._extract_html_selectors_python(html, recipe.request.html_selectors)
@@
 ### ADR-3: CDP Fetch for Direct Execution
@@
-#### Decision
-CDP `Runtime.evaluate` executing `fetch()` in the page context. This inherits all cookies, session storage, and authentication state from the browser.
+#### Decision (revised)
+Default to Playwright `context.request` for direct execution (cookies + controllable redirects/timeouts/body caps).
+Use CDP in-page `fetch()` only when recipe explicitly requires page context.
```

---

## Change 12 — Add explicit concurrency, cancellation, and resource budgets per task

Why this makes the plan better:

A daemonized HTTP MCP server will eventually get overlapping calls (clients retry, users click twice, long tasks overlap). Without explicit concurrency controls you get p95 blowups and “why did Chromium die” bugs. You already track tasks; now add resource budgets: max concurrent browser contexts, max concurrent direct exec, per-task hard timeouts, and cancellation semantics that guarantee cleanup. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 2. Architecture Deep Dive
@@
 ### 2.1 Server Execution Model
@@
     return result
+
+### 2.1.1 Concurrency + Resource Budgets (v1)
+
+- Global limits:
+  - max concurrent browser-agent tasks (default 1)
+  - max concurrent direct recipe runs (default 4)
+- Per-task limits:
+  - hard timeout for direct exec (default 15s)
+  - hard timeout for agent run (configurable; default aligns with client expectations)
+- Cancellation:
+  - `task_cancel` MUST cancel underlying asyncio task AND close browser context
+  - `_running_tasks` MUST be cleaned up on completion/cancel (TODO-006 becomes a hard gate)
```

---

## Change 13 — Testing: add a deterministic “malicious web” test server and formal contract tests for MCP tools

Why this makes the plan better:

You already mention a deterministic server, but it needs to become a first-class testing asset with specific scenarios that map to your threat model and performance budgets. Separately, the “tool count mismatch” suggests tool contracts are drifting. You need contract tests that pin schemas and error envelopes, so clients don’t break on refactors. 

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
+- Add “malicious web” scenarios:
+  - IDN/punycode hostnames that look like allowlisted domains
+  - credential-in-URL attempts
+  - `Location:` redirects to `file://` and `chrome://` (must be blocked)
+  - DNS rebinding simulation hooks (where possible)
 - Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
 - Golden fixtures for recorder output and analyzer structured JSON output (prevents prompt/schema regressions)
-- MCP tool contract tests: stable schemas + stable error envelope (prevents tool-count / shape drift)
+- MCP tool contract tests:
+  - tool names + JSONSchema signatures are pinned
+  - stable error envelope (code, message, retryable, stage, task_id)
+  - explicit deprecation policy for tool changes
```

---

## Change 14 — Developer experience: collapse recipe run tools into one stable API, and add “doctor” + “bench” commands

Why this makes the plan better:

You already note that `test_mcp_tools.py` expects 9 tools but server has 10; that’s a classic DX footgun. Unify to a single `recipe_run` with a `strategy` enum and optional `learn` flags. Also, add two CLI commands that shorten debugging loops: `doctor` (checks Playwright/Chromium/CDP/config/auth) and `bench` (runs the deterministic benchmark harness). This makes the project easier to execute and maintain. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.5 Test Coverage
@@
 - `test_mcp_tools.py` expects 9 tools, server has 10 (replace recipe_run_direct with recipe_run(strategy=...))
+ - Make this a plan change, not a lingering TODO: stabilize tool surface area for v1.
@@
 ## 6. Implementation Phases
@@
 ### Phase 2: Hardening (PLANNED)
@@
 - [ ] **P2**: Direct execution in REST `/api/recipes/{name}/run` (TODO-016)
+ - [ ] Tool surface stabilization:
+   - Replace `recipe_run_direct` with `recipe_run(strategy="auto"|"direct"|"hint")`
+   - Add `recipe_learn(task_id=..., strategy="auto"|"interactive")` (returns candidates/artifacts when needed)
+ - [ ] CLI DX:
+   - `mcp-server-browser-use doctor` (env + playwright + browser + ports + auth)
+   - `mcp-server-browser-use bench` (CI-safe perf harness against local deterministic server)
```

---

## Change 15 — Add a missing phase: “Contract Stabilization + Backward Compatibility” before “Polish & Release”

Why this makes the plan better:

Right now Phase 4 bundles docs/CI/release, but the most expensive releases are the ones where clients break because tool schemas shift or error shapes change. A short, explicit phase that freezes tool contracts, pins schemas, and declares deprecations makes the release compelling for real users (Cursor/Claude setups don’t randomly break). 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 6. Implementation Phases
@@
 ### Phase 4: Polish & Release (PLANNED)
@@
 - [ ] README with usage examples and Claude Desktop config
 - [ ] Changelog
+
+### Phase 3.5: Contract Stabilization (NEW, REQUIRED)
+
+**Goal**: Freeze MCP + REST contracts so clients remain compatible across patch releases
+
+- [ ] MCP tool schemas pinned + contract tests in CI
+- [ ] Error envelope standardized across tools + REST
+- [ ] Deprecation policy documented (remove only in minor/major)
+- [ ] Version reporting endpoint: `/api/version` + `health_check` includes version + git sha (if available)
```

---

## Change 16 — Observability: add per-stage timing + “why did AUTO choose this path” traces

Why this makes the plan better:

You have performance budgets, but you need the instrumentation to explain misses and regressions. If AUTO chooses hint-based, you should be able to answer “why?” in one glance (unverified, demoted, auth failed, validator rejected, fingerprint drift, etc.). That’s essential both for debugging and for making the project compelling to users. 

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 7. Performance Budgets
@@
 Additional perf requirements (measured and logged per task):
 - runner stage timings: validate_url, transport_select, request, extract, postprocess
 - benchmark harness against a local deterministic test server (CI-safe)
+
+Observability requirements (v1):
+- AUTO decision trace persisted in task record:
+  - selected strategy + reason codes (unverified, demoted, auth_recovery, validator_reject, fingerprint_mismatch)
+  - per-stage timings + redirect hop count
+- SSE emits structured progress events per stage (safe + redacted)
```

---

If you apply only three changes, I’d prioritize: Change 1 (artifact-based pipeline), Change 11 (default `context.request` + Python HTML parsing), and Change 9 (hostile-by-default HTTP exposure). Those three directly improve success rate, p95 performance, and real-world safety without requiring a massive rewrite.
