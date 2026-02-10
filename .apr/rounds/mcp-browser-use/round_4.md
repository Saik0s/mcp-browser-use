## Meta-Block

Scope: Review the current PLAN_TO_SHIP_MCP_BROWSER_USE.md and propose concrete plan-text revisions that improve execution reliability, performance, security, testing, and DX/API clarity. 
Confidence score: 0.78
Perspective: Ship v1 safely for a single-user localhost daemon by treating every learned artifact (and every LLM output) as hostile input, and by making the learning→verification→execution loop deterministic and benchmarkable.

Assumptions:

1. The repo already matches the module map and constraints in AGENTS.md, especially “HTTP transport only” and the recipes fast-path goals. 
2. “Recipes” must remain human-editable YAML definitions, with mutable health/stats in SQLite. 
3. v1 prioritizes “reliable replay” over “maximally clever learning”; interactive fallback is acceptable if it’s deterministic and debuggable. 

---

### Change 1 — Make verification deterministic by introducing a baseline oracle + transport inference matrix (architecture gap)

Why this makes the plan better:
Right now, verification references an “expected shape” but doesn’t fully define where that oracle comes from, and it risks quietly coupling success to the agent’s final textual answer or to a fragile extraction guess. A deterministic baseline (computed from the captured candidate response after applying the extraction spec) gives you a stable “truth” for minimization and replay, and makes “promotion” measurable and reproducible.

Also, explicitly inferring the lowest-risk transport that still matches the baseline (httpx_public → context_request → in_page_fetch) turns ADR-3 from a principle into an executable, testable algorithm. That directly improves performance, reduces SSRF surface area, and raises auto-learning success rate without relying on better prompts.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-### 1.3 Recipes System (Alpha, Active Development)
+### 1.3 Recipes System (Alpha, Active Development)
@@
-The recipes pipeline has 7 stages (with hard gating between each stage):
+The recipes pipeline has 8 stages (with hard gating between each stage):
@@
-RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             MINIMIZE+PARAMETERIZE          VERIFY+PROMOTE                 EXECUTE
+RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             BASELINE (new)                 MINIMIZE+PARAMETERIZE          VERIFY+PROMOTE                 EXECUTE
@@
-                                                                                                            │
- recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+                                                                                                            │
+ recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> fingerprint.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+
+BASELINE (new, required for v1):
+- Compute a `baseline_shape_fingerprint` from the selected candidate's CAPTURED response after applying the analyzer's extract spec.
+- Store baseline fingerprint (and fingerprint_version) as an artifact + in SQLite stats (NOT in YAML).
+- All subsequent replay/minimization/verification compares against this baseline, not against agent final text.
@@
 ### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
@@
 Artifacts (all redacted; never store secrets):
 - `SessionRecording` (from recorder): normalized JSONL of network events + minimal page context
 - `CandidateSet` (from ranker): top_k candidate request IDs with scores + feature breakdown
 - `RecipeAnalysis` (from analyzer): strict JSON output from LLM (schema-validated)
 - `RecipeDraft` (from validator): safe, canonical recipe ready for replay
+- `BaselineFingerprint` (from fingerprint): baseline_shape_fingerprint + fingerprint_version for the selected candidate
 - `MinimizationReport` (from minimizer): dropped fields + volatility flags + "minimal sufficient" proof
 - `RecipeDraftMinimized` (from minimizer): minimized, parameterized recipe ready for verification replay
 - `VerificationReport` (from verifier): replay results + extracted shape fingerprint + promotion decision
@@
-Verification spec (v1):
+Verification spec (v1):
 - Compute `shape_fingerprint` on extracted output:
   - for JSON: sorted key paths up to depth 3 + type tags + array length buckets (0/1/2-10/10+)
   - for HTML: selector hit counts + extracted field presence map
-- Store fingerprint in SQLite stats table (not in YAML)
-- Promotion rule: 2 consecutive successful replays with matching fingerprint + no auth recovery triggered
+- Store baseline fingerprint + fingerprint_version in SQLite stats table (not in YAML)
+- Promotion rule: 2 consecutive successful replays that match the baseline fingerprint + no auth recovery triggered
 - Demotion rule: existing rule (5 consecutive failures) + any "shape drift" (fingerprint mismatch) demotes immediately
+
+Transport inference (new, verifier responsibility):
+- Verifier MUST try transports in ascending risk order:
+  1) httpx_public (no browser/session)
+  2) context_request (browser cookies, no DOM)
+  3) in_page_fetch (DOM/CSRF/sessionStorage parity)
+- First transport that matches baseline fingerprint becomes `transport_hint`.
+- If no transport matches, recipe stays draft and returns an interactive CandidateSet instead of writing YAML.
@@
 #### Phase 1 deliverables (make modules real)
 - [ ] Add `recipes/candidates.py` (pure functions + unit tests; no LLM calls)
 - [ ] Add `recipes/validator.py` (schema + safety canonicalization; no network I/O)
+- [ ] Add `recipes/fingerprint.py` (shape fingerprinting + versioning; pure functions + golden tests)
 - [ ] Add `recipes/minimizer.py` (replay-based minimization + volatility detection; bounded attempts; emits reports)
 - [ ] Add `recipes/verifier.py` (replay + shape fingerprint + promotion rules)
 - [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
```

---

### Change 2 — Specify artifact storage layout, permissions, and retention/GC (missing reliability + privacy + DX tasks)

Why this makes the plan better:
You already require “versioned artifacts so failures are reproducible,” but the plan leaves storage mechanics ambiguous (“disk or SQLite”). That ambiguity becomes operational debt immediately: disk bloat, unclear permissions, and hard-to-script debugging. A concrete artifact layout + retention policy makes the pipeline actually usable by humans, and prevents “my ~/.config is 10GB” incidents. It also improves security posture by ensuring sensitive-ish outputs (even if redacted) aren’t world-readable.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
@@
-Each stage MUST emit a versioned artifact to disk (or SQLite) so failures are reproducible and the pipeline can resume.
+Each stage MUST emit a versioned artifact to disk so failures are reproducible and the pipeline can resume.
+
+Artifact storage layout (v1, explicit):
+- Root: `~/.config/mcp-server-browser-use/artifacts/`
+- Per task: `~/.config/mcp-server-browser-use/artifacts/<task_id>/`
+- Files are stage-named JSON with stable suffixes:
+  - `01_session_recording.json`
+  - `02_candidate_set.json`
+  - `03_recipe_analysis.json`
+  - `04_recipe_draft.json`
+  - `05_baseline_fingerprint.json`
+  - `06_minimization_report.json`
+  - `07_recipe_draft_minimized.json`
+  - `08_verification_report.json`
+
+Permissions (v1, required):
+- artifacts dir MUST be `0700`
+- artifact files MUST be `0600`
+- writes MUST be atomic (temp + fsync + rename)
+
+Retention/GC (v1):
+- Config: `artifacts.retention_days` (default 7)
+- CLI: `mcp-server-browser-use artifacts prune [--days N]` (also prunes orphan task dirs)
+- CI harness MUST prune after tests to avoid disk growth
@@
 ## File Locations Quick Reference
@@
 | Results (if enabled) | `~/Documents/mcp-browser-results/` |
+| Pipeline artifacts | `~/.config/mcp-server-browser-use/artifacts/<task_id>/` |
```

---

### Change 3 — Turn performance into an engineering loop: RecipeIR + fast parsers + CI-safe perf regression gate (performance opportunities)

Why this makes the plan better:
Your performance budget calls out “runner overhead” but the plan doesn’t yet force the codebase to separate “network time” from “CPU overhead” in a way that becomes regression-proof. Introducing an explicit compilation step (RecipeIR) plus choosing fast JSON/HTML parsers is the simplest leverage. Then add a CI-safe perf gate based on the deterministic local server so performance doesn’t degrade silently as features land.

This is especially important because real-site times (6–25s) are dominated by network; the only part you can reliably improve is overhead and transport choice.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-async def run(recipe, params, browser_session):
-    compiled = recipe_cache.get_or_compile(recipe)  # compile JMESPath/selectors + validate templates once
+async def run(recipe, params, browser_session):
+    # v1 perf requirement: compile once into a RecipeIR and reuse via LRU cache
+    # RecipeIR includes: parsed+validated URL template, compiled JMESPath, compiled CSS selectors, normalized header allowlist,
+    # and precomputed allowed_domains canonical forms.
+    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate)
@@
-    if compiled.response_type == "html" and compiled.html_selectors:
-        # HTML mode (v1): fetch HTML via context.request, parse selectors in Python.
+    if compiled.response_type == "html" and compiled.html_selectors:
+        # HTML mode (v1): fetch HTML via context.request, parse selectors in Python with a fast parser.
         # Navigation is fallback-only for JS-rendered pages.
         html = await self._request_text(transport, url, compiled, browser_session)
-        extracted = compiled.extract_html(html)  # compiled selectors
+        extracted = compiled.extract_html(html)  # compiled selectors (prefer selectolax/parsel over bs4 for speed)
     else:
         # JSON mode:
@@
 ## 7. Performance Budgets
@@
-| Direct recipe execution (runner overhead on local test server) | p50 < 250ms, p95 < 800ms | (new metric; benchmark harness) |
+| Direct recipe execution (runner CPU overhead on local test server, warm cache) | p50 < 50ms, p95 < 150ms | (new metric; benchmark harness) |
+| Direct recipe execution (runner end-to-end on local test server) | p50 < 250ms, p95 < 800ms | (new metric; benchmark harness) |
@@
 Additional perf requirements (measured and logged per task):
 - runner stage timings: validate_url, transport_select, request, extract, postprocess
 - network vs runner overhead MUST be split (TTFB, download, parse/extract, postprocess)
 - cache hit-rate for compiled recipes MUST be logged (to prove caching works)
 - benchmark harness against a local deterministic test server (CI-safe)
+
+CI perf regression gate (new, required for v1):
+- Add `mcp-server-browser-use bench --ci` that runs N=200 local-server direct exec calls.
+- Gate on: p95 end-to-end and p95 CPU overhead (warm cache).
+- Store baseline JSON in repo and fail CI on >20% regression unless explicitly updated.
```

---

### Change 4 — Add execution reliability primitives: explicit timeouts, limited retries, and structured error codes (missing failure modes + easier ops)

Why this makes the plan better:
The plan is already strong on security invariants, but “reliability under real APIs” is where these projects usually feel flaky: 429s, transient 5xx, slow TLS handshakes, and ambiguous parse failures. If you standardize error codes + retry semantics now, the MCP tools and dashboard become predictable, and testing becomes straightforward (you can assert error_code instead of brittle message matching). This also makes recipe health/demotion decisions more defensible.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 class RecipeRunResult:
     success: bool
     data: JSONValue                   # Extracted data (no Any)
     raw_response: str | None
     status_code: int | None
-    error: str | None
+    error: str | None
+    error_code: str | None            # stable enum-like strings, e.g. URL_BLOCKED, DNS_BLOCKED, REDIRECT_BLOCKED, TIMEOUT, RATE_LIMITED, PARSE_ERROR
+    retryable: bool                   # computed by runner (never by LLM), used by AUTO strategy + UI
+    retry_after_sec: int | None       # from Retry-After header (validated + bounded)
     auth_recovery_triggered: bool     # True if 401/403 detected
+    transport_used: str | None        # httpx_public | context_request | in_page_fetch
+    redirect_hops: int                # explicit, since redirects are manual+validated hop-by-hop
+    timings_ms: dict[str, int]        # validate_url/request/extract/postprocess + total
@@
 ### 2.1.1 Concurrency + Resource Budgets (v1)
@@
 - Per-task limits:
   - hard timeout for direct exec (default 15s)
   - hard timeout for agent run (configurable; default aligns with client expectations)
+  - retry budget for direct exec (new): max_attempts=2 for retryable errors only (429/5xx/timeouts), with bounded backoff + jitter
@@
 ## 7. Performance Budgets
@@
 Additional perf requirements (measured and logged per task):
@@
 - AUTO decision trace persisted in task record:
   - selected strategy + reason codes (unverified, demoted, auth_recovery, validator_reject, fingerprint_mismatch)
+  - standardized runner error_code + retry decision (attempt, backoff_ms, retry_after_sec)
   - per-stage timings + redirect hop count
```

---

### Change 5 — Tighten security posture in places the plan currently leaves “implicit” (SSRF, credential leakage, CDP/browser security)

Why this makes the plan better:
You already list many security threats, but a few high-leverage items are still “described” rather than turned into enforceable constraints:

1. Redirect handling must be manual in every transport; otherwise hop-by-hop validation is easy to accidentally bypass.
2. Header and method allowlists prevent request smuggling, dangerous mutations, and “recipe as a generic HTTP client” drift.
3. LLM output must be explicitly treated as hostile input in the plan (not just “schema validated”).
4. Browser launch/config must explicitly forbid risky options (`ignore_https_errors`, proxies by default, remote debugging exposure), because that’s where CDP security tends to get compromised in practice.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
@@
 6. **Constrained Runtime.evaluate.** Only allow a fixed set of internal JS snippets (no recipe-provided JS). Recipe fields may only influence data inputs (URL, selectors, extract paths) after validation.
+6a. **LLM output is untrusted input.** Analyzer output MUST be treated like user input:
+    - schema validated
+    - safety validated (URLs/ports/headers/methods)
+    - size bounded (token and bytes)
+    - never allowed to disable guardrails (no "confidence overrides")
@@
 8. **Redirect policy is explicit.** Default: allow redirects only within the same canonical host; cross-host redirects require explicit validator approval (and are re-validated hop-by-hop).
+8a. **Redirects are manual everywhere.** All transports MUST disable auto-follow and implement validated redirect loops:
+    - cap redirect count
+    - validate every Location (scheme/host/port) before the next request
+    - block scheme changes (http<->https) unless explicitly allowed
+
+10. **Method + header allowlists.** v1 defaults:
+    - Methods allowed by default: GET, POST
+    - PUT/PATCH/DELETE require explicit config `recipes.allow_unsafe_methods=true` AND recipe.status=verified
+    - Header allowlist enforced by validator; forbidden headers include Host, Connection, Transfer-Encoding, Content-Length, Proxy-*, Cookie, Authorization
+
+11. **TLS + proxy hardening.**
+    - Playwright contexts MUST NOT set ignore_https_errors unless explicit expert-mode flag is enabled.
+    - Proxy configuration is disabled by default for direct execution; explicit opt-in required and logged as risk.
@@
 ## 4. Threat Model
@@
 | Threat | Impact | Guardrail | Test |
@@
+| Request smuggling via crafted headers | Unexpected proxy/backend behavior | Header allowlist; block Host/TE/CL/Connection; CRLF checks | `test_recipes_security.py::test_header_allowlist` |
+| Unsafe remote mutations (PUT/PATCH/DELETE) | Data loss / account actions | Default method allowlist; unsafe methods require explicit config + verified status | `test_recipes_security.py::test_unsafe_methods_gated` |
+| LLM prompt injection in captured responses | Malicious recipe attempt | Treat LLM output as hostile; validator rejects unsafe; minimize response snippets sent to analyzer | `test_analyzer_prompt_injection.py` |
+| `ignore_https_errors` misconfig | MITM risk / data tamper | Default false, expert-mode only, loudly logged | `test_config.py::test_ignore_https_errors_gated` |
+| Auto-follow redirects bypasses hop validation | SSRF via Location chain | Manual redirects in every transport | `test_recipes_security.py::test_redirects_manual` |
```

---

### Change 6 — Expand testing into three concrete suites: hostile-web, pipeline-golden, and fuzz/property (testing gaps)

Why this makes the plan better:
You already list excellent test ideas, but they’re mostly phrased as additions rather than as suites with acceptance criteria and CI wiring. Breaking them into three suites makes implementation linear and reduces the chance they languish as “great ideas.”

Also: property-based tests are disproportionately effective for SSRF bypass defense, URL canonicalization, and template substitution, because attackers live in edge cases. This makes the threat model defendable.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.6 Testing Strategy Additions (Needed for v1.0 reliability)
@@
 - Deterministic local test server for recipes:
@@
 - Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
 - Golden fixtures for recorder output and analyzer structured JSON output (prevents prompt/schema regressions)
 - Golden fixtures for pipeline artifacts (SessionRecording/CandidateSet/RecipeDraft/MinimizationReport/VerificationReport)
@@
 - MCP tool contract tests:
@@
   - explicit deprecation policy for tool changes
+
+Testing suites (new, required for v1):
+1) Hostile Web Harness (integration):
+   - local deterministic server scenarios (redirect/SSRF/decompression/depth/rate-limit)
+   - validates runner + agent navigation share the same URL safety gate
+2) Pipeline Golden Suite (unit-ish):
+   - frozen JSON fixtures for each artifact stage
+   - asserts stable fingerprint_version behavior and stable validator output
+3) Fuzz/Property Suite (unit):
+   - Hypothesis tests for URL canonicalization, IDN/punycode equivalence, IP encoding edge cases, template substitution, header CRLF blocking
+   - bounded runtime suitable for CI
@@
 ## 8. Quality Gates
@@
 ### Gate 2a: Hostile Web Harness (Automated, CI-safe)
@@
 **Response**: must pass or merge blocked
+
+### Gate 2b: Pipeline Golden + Fuzz (Automated, CI-safe)
+**Trigger**: PR to main
+**Checks**: golden artifact fixtures + Hypothesis property suite (bounded)
+**Response**: must pass or merge blocked
+
+### Gate 2c: Perf Regression (Automated, CI-safe)
+**Trigger**: PR to main
+**Checks**: `mcp-server-browser-use bench --ci` on deterministic server
+**Response**: regression beyond threshold blocks merge unless baseline explicitly updated
```

---

### Change 7 — Move contract stabilization earlier and define the v1 MCP/REST surface precisely (DX + API design + easier execution)

Why this makes the plan better:
The plan acknowledges contract drift (tool count mismatch, dashboard 404s), but it schedules contract stabilization late (Phase 3.5). That’s backwards for a server meant to be used by multiple clients (Claude Desktop, Cursor, etc.). Freezing the contract earlier reduces churn, makes tests meaningful, and forces you to resolve the existing mismatches as part of “Hardening,” not as “Polish.”

Also: explicitly defining tool signatures (even if brief) improves contributor velocity and prevents silent breaking changes.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-### Phase 2: Hardening (PLANNED)
+### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
 - [ ] **P2**: Direct execution in REST `/api/recipes/{name}/run` (TODO-016)
  - [ ] Tool surface stabilization:
    - Replace `recipe_run_direct` with `recipe_run(strategy="auto"|"direct"|"hint")`
    - Add `recipe_learn(task_id=..., strategy="auto"|"interactive")` (returns candidates/artifacts when needed)
    - Add `run(task, strategy="auto"|"agent"|"recipe")` (single entry-point; `run_browser_agent` becomes alias/deprecated)
+   - Add `recipe_explain(name, params)` (returns transport decision trace, validator summary, allowed_domains, fingerprint_version)
+   - Add `recipe_dry_run(name, params)` (returns compiled URL + headers summary; performs validation but does NOT execute network)
  - [ ] CLI DX:
@@
-- [ ] **P2**: Add deterministic local test server + CI-safe benchmark harness
+- [ ] **P2**: Add deterministic local test server + CI-safe benchmark harness (feeds Gate 2a + Gate 2c)
@@
-### Phase 3.5: Contract Stabilization (NEW, REQUIRED)
-
-**Goal**: Freeze MCP + REST contracts so clients remain compatible across patch releases
-
-- [ ] MCP tool schemas pinned + contract tests in CI
-- [ ] Error envelope standardized across tools + REST
-- [ ] Deprecation policy documented (remove only in minor/major)
-- [ ] Version reporting endpoint: `/api/version` + `health_check` includes version + git sha (if available)
-- [ ] REST OpenAPI published at `/api/openapi.json` (or equivalent) and pinned in CI
-- [ ] Generated typed REST client used in dashboard + contract tests (reduces drift)
+Contract stabilization is part of Phase 2 (v1 requirement, not optional):
+- [ ] MCP tool schemas pinned + contract tests in CI (Gate 2 pre-merge)
+- [ ] Error envelope standardized across tools + REST (includes error_code/retryable/retry_after_sec/task_id)
+- [ ] Deprecation policy documented (remove only in minor/major)
+- [ ] Version reporting endpoint: `/api/version` + `health_check` includes version + git sha (if available)
+- [ ] REST OpenAPI published at `/api/openapi.json` and pinned in CI
+- [ ] Generated typed REST client used in dashboard + contract tests (reduces drift)
@@
 ### Test Debt
@@
-- [ ] `test_mcp_tools.py` expects 9 tools, server has 10 (replace recipe_run_direct with recipe_run(strategy=...))
- - Make this a plan change, not a lingering TODO: stabilize tool surface area for v1.
+- [ ] `test_mcp_tools.py` expects 9 tools, server has 10:
+  - resolved by Phase 2 contract stabilization (replace recipe_run_direct with recipe_run; add explicit deprecation alias)
```

---
