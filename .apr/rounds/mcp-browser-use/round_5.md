Meta
Assumptions: The project is a single-user, localhost-first MCP HTTP daemon; “recipes” are meant to become the dominant fast path; the plan text is the authoritative roadmap as provided in `plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md` and the dev rules in `AGENTS.md`. 
Scope: Revise the plan to (1) raise recipe auto-learning reliability, (2) close realistic security gaps (SSRF/CDP/dashboard), (3) improve direct-exec performance + determinism, (4) harden failure-mode coverage and tests, and (5) make the API/DX easier to ship as a real MCP server.
Confidence: 0.74 (probable these changes improve ship-ability; exact priority depends on your current implementation details, but the plan-level gaps are clear).
Perspective: Skeptical “ship it safely” review: optimize for predictable behavior, testable invariants, and hard-to-misuse defaults.

---

## 1) Add a deterministic “Signals + Heuristic First” lane before LLM analysis

Why this makes the plan better
Right now the plan acknowledges the key problem: auto-learning is 20% and “struggles with simple GET APIs.” The highest-leverage fix is to stop asking the LLM to do the first, easiest part (candidate selection) unless ambiguity remains. A deterministic signals layer plus a heuristic “good enough” analyzer for simple GET/JSON endpoints will (a) materially raise success rate, (b) reduce cost/latency, and (c) reduce prompt-injection exposure because the LLM sees less raw data and fewer candidates.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
- recorder.py ──> candidates.py ──> analyzer.py ──> validator.py ──> fingerprint.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+ recorder.py ──> signals.py ──> candidates.py ──> heuristic_analyzer.py ──> analyzer.py ──> validator.py ──> fingerprint.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py
+
+SIGNALS (new, required for v1):
+- Deterministically compute a compact per-request feature vector from the recording (no LLM).
+- Emit a sanitized CandidateSummary that is safe to send to the LLM (no raw bodies by default).
+
+HEURISTIC_ANALYZER (new, required for v1):
+- If the top candidate score is “high confidence” (thresholded + explainable), produce a minimal RecipeDraft
+  for simple JSON/GET endpoints without invoking the LLM.
+- Otherwise, fall back to LLM analyzer using CandidateSummary (not raw recording).
@@
 #### Phase 1 deliverables (make modules real)
 - [ ] Add `recipes/candidates.py` (pure functions + unit tests; no LLM calls)
+- [ ] Add `recipes/signals.py` (pure functions; turns recordings into per-request features + safe summaries)
+- [ ] Add `recipes/heuristic_analyzer.py` (pure functions; handles simple GET/JSON recipe drafts w/o LLM)
 - [ ] Add `recipes/validator.py` (schema + safety canonicalization; no network I/O)
```

---

## 2) Introduce an explicit “LLM input budget + caching” rule for recipe analysis

Why this makes the plan better
You already treat LLM output as hostile input, but the other direction matters too: captured web data is hostile input to the LLM (prompt injection, accidental secret/PII exposure, huge tokens). The plan should hard-cap what the analyzer ever sees, and cache analyzer results keyed by a deterministic hash of the sanitized CandidateSummary + task. This improves reliability (reproducibility), performance (dedupe repeated learning), and privacy.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
@@
   - `02_candidate_set.json`
+  - `02a_candidate_summary.json`
   - `03_recipe_analysis.json`
@@
 Artifacts (all redacted; never store secrets):
@@
 - `CandidateSet` (from ranker): top_k candidate request IDs with scores + feature breakdown
+- `CandidateSummary` (from signals): compact, bounded, LLM-safe summaries per candidate (no raw bodies by default)
 - `RecipeAnalysis` (from analyzer): strict JSON output from LLM (schema-validated)
@@
 All artifacts include:
@@
   - `sha256` of the artifact payload (integrity + dedupe)
+
+Analyzer input budgets (v1, required):
+- The analyzer MUST only receive CandidateSummary + a bounded “evidence window” (small snippets) when explicitly needed.
+- Hard caps:
+  - max candidates to LLM: 8
+  - max bytes per candidate summary: 4KB
+  - max total analyzer prompt bytes: 32KB (post-redaction)
+- Analyzer results SHOULD be cached by sha256(task + candidate_summary + prompt_version) to avoid repeat spend and reduce variance.
```

---

## 3) Close the SSRF gap in the browser path: enforce a Playwright-wide network policy (not just navigation/direct-exec)

Why this makes the plan better
Your threat model covers “SSRF via agent navigation,” but a hostile page can trigger subresource requests (images, scripts, fetches) to private IPs without changing the main navigation. Even if the attacker can’t read responses due to SOP/CORS, they can still hit internal services for side effects (classic SSRF). A route-level guard is the only practical application-layer defense here.

This also makes the system easier to reason about: “no private network egress” becomes true for all browser-originated traffic under default settings.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
@@
 3. **SSRF protection on all direct execution.** Private IPs, loopback, link-local addresses blocked. DNS resolution checked for rebinding. Validated twice (before navigation AND before fetch).
+3a. **Browser-wide egress policy (required).** Attach a Playwright route handler per context that blocks any request to:
+    - non-http(s) schemes
+    - loopback/link-local/private IP ranges (IPv4+IPv6), including numeric-IP hosts
+    - forbidden “special” URLs (chrome://, about:, file://, view-source:)
+   Default mode SHOULD be “lite” (fast checks); “strict” mode MAY resolve DNS for all requests with bounded caching.
@@
 ## 4. Threat Model
@@
 | Threat | Impact | Guardrail | Test |
@@
 | SSRF via agent navigation | Internal network reachability through full browser automation | Apply the same URL safety checks to navigation targets (not only recipe runner) | `test_security_agent_navigation.py` |
+| SSRF via subresource requests (img/script/fetch) | Internal side effects / scanning via hostile pages | Playwright route-level network policy on ALL requests in the context | `test_security_browser_network_policy.py` |
```

---

## 4) Harden CDP/Chromium launch posture: disable extensions, enforce pipe-based control, and detect accidental debug ports

Why this makes the plan better
You already have strong “CDP restricted to localhost” language, but the more important default is: don’t expose a debugging port at all, and don’t allow extensions (they’re a huge “unknown unknown” surface). Also: “external CDP is expert mode” should be paired with explicit “profile isolation required” and “extensions disabled” defaults.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 4a.1 **No exposed debug port by default.** Server MUST ensure the Playwright-launched browser is not listening on a non-loopback debug port; fail-fast if detected.
+4a.2 **No extensions by default.** Playwright-launched Chromium MUST disable extensions and component extensions unless explicitly enabled in expert mode.
+4a.3 **Pipe-first control.** Prefer pipe-based browser control where supported; treat any debug-port mode as expert-only with extra validation and warnings.
@@
 ### Failure Modes
@@
 | Hostile local CDP browser | Data exfil / unexpected extensions | External CDP requires explicit enable + isolated profile recommendation | `test_config.py::test_external_cdp_requires_explicit_enable` |
+| Extension-based exfiltration | Credential/session theft via loaded extensions | Launch args disable extensions by default; external CDP requires explicit “allow_extensions=true” | `test_browser_launch_security.py` |
+| Accidental remote-debug port exposure | Remote control of browser | Detect debug port binding; fail-fast unless expert mode | `test_browser_launch_security.py::test_debug_port_not_exposed` |
```

---

## 5) Add dashboard/XSS and “result rendering” to the threat model + hard requirements (CSP, escaping, safe truncation)

Why this makes the plan better
The dashboard is a classic “soft underbelly.” You display task results that can contain arbitrary HTML/text from hostile sites. If you ever render that unsafely, you’ve built a local XSS delivery mechanism (including token theft if you add auth headers or store tokens anywhere in the browser). Even if you don’t think you render HTML, templating mistakes happen. The plan should explicitly require output escaping and security headers.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Failure Modes
@@
 | Localhost CSRF (drive-by POST/DELETE to server) | Attacker triggers browser tasks / outbound fetches | Require auth for all state-changing endpoints by default; strict Origin/Host checks for dashboard; CORS disabled | `test_http_auth.py::test_write_endpoints_require_token` |
+| Dashboard XSS via task result rendering | Token theft / arbitrary requests from localhost origin | Strict escaping, never render raw HTML; CSP + security headers; truncate + encode output | `test_dashboard_security_headers.py` |
+| SSE injection into UI | Script injection via event payload display | Treat SSE text as data; escape; never innerHTML | `test_dashboard_security_headers.py::test_sse_payload_escaped` |
@@
 ### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
 - [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
@@
   - Add strict `Origin`/`Host` validation for dashboard + SSE endpoints (CSRF mitigation)
+  - Add security headers for all dashboard routes:
+    - Content-Security-Policy (default-src 'self'; no inline scripts)
+    - X-Content-Type-Options: nosniff
+    - X-Frame-Options: DENY (or CSP frame-ancestors 'none')
+    - Cache-Control: no-store for sensitive pages
+  - Dashboard must HTML-escape all task outputs and artifacts; no raw HTML rendering.
```

---

## 6) Add explicit DoS/resource-exhaustion failure modes + enforce caps (SSE clients, request sizes, task queue)

Why this makes the plan better
Right now you have concurrency limits for tasks, but not for: number of connected SSE clients, HTTP request body sizes, number of queued tasks, artifact growth beyond retention (if prune fails), or “slowloris” style connections. These aren’t theoretical; local services get wedged by “harmless” UIs surprisingly often. The plan should specify caps and tests so reliability is measurable.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.1.1 Concurrency + Resource Budgets (v1)
@@
 - Global limits:
   - max concurrent browser-agent tasks (default 1)
   - max concurrent direct recipe runs (default 4)
+  - max queued tasks (default 50; reject beyond with stable error_code=QUEUE_FULL)
+  - max SSE connections (default 5; reject beyond with 429)
+  - max HTTP request body size (default 256KB; reject beyond with 413)
@@
 ### Failure Modes
@@
+| DoS via unbounded task queue | Memory/disk growth, degraded UX | Hard cap queued tasks + bounded retention | `test_limits.py::test_queue_cap` |
+| DoS via SSE connection flood | File descriptor exhaustion | Limit SSE clients; enforce keepalive timeouts | `test_limits.py::test_sse_connection_cap` |
+| DoS via huge request bodies/headers | Memory spike / slow parsing | ASGI limits + explicit max body size | `test_limits.py::test_request_size_limits` |
```

---

## 7) Make direct execution actually fast in practice: standardize on fast parsers (orjson/selectolax) and unify caps across transports

Why this makes the plan better
Your “runner CPU overhead” targets are aggressive (p95 < 150ms), but the plan currently leaves room for accidentally slow primitives (stdlib json, bs4). Also, the 1MB response cap is described for JS fetch; it must apply identically to `httpx_public` and `context_request` too, otherwise the safest transport becomes the easiest to DoS.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-        extracted = compiled.extract_html(html)  # compiled selectors (prefer selectolax/parsel over bs4 for speed)
+        extracted = compiled.extract_html(html)  # REQUIRED: selectolax (or equivalent) for speed + robustness
@@
     else:
@@
         result = await self._execute_json_request(transport, url, compiled, browser_session)
+
+Transport caps MUST be uniform (v1, required):
+- MAX_RESPONSE_SIZE applies after decompression for ALL transports (httpx_public, context_request, in_page_fetch).
+- MAX_HEADER_BYTES and MAX_REDIRECTS apply for ALL transports.
+- JSON parsing SHOULD use orjson with explicit depth limits + safe fallbacks.
@@
 ### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
 - [ ] **P3**: Missing bs4 dependency (TODO-011)
+- [ ] Replace bs4 usage with selectolax (or remove dependency entirely); reserve bs4 only if absolutely necessary and benchmarked.
+- [ ] Standardize JSON parsing on orjson in runner + verifier paths; keep stdlib json only for small internal fixtures.
```

---

## 8) Define cache invalidation rules for RecipeIR (avoid “stale compiled” bugs) and add a warm-up path

Why this makes the plan better
“Compile once + LRU” is correct, but stale caches become a real reliability bug once users edit YAML by hand (or automated learning updates it). The plan should specify invalidation keyed by file mtime/sha, and a warm-up option to precompile verified recipes on startup to avoid cold p95 spikes.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate)
+    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate)
+    # v1 reliability requirement:
+    # - Invalidate compiled IR when underlying YAML changes (sha256 or mtime+size).
+    # - Expose cache stats + invalidation events in observability.
@@
 ### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
 - [ ] CLI DX:
@@
    - `mcp-server-browser-use bench` (CI-safe perf harness against local deterministic server)
+ - [ ] Runner DX:
+   - `mcp-server-browser-use recipes warmup` (precompile verified recipes; prints cache hit/miss stats)
+   - Add `recipe_cache` metrics to task trace (hit/miss, compile_ms)
```

---

## 9) Add a missing phase: “Phase 1.5 — Learning Corpus + Offline Evaluation” (this is how you get from 20% → 60% without guessing)

Why this makes the plan better
The plan has good modules listed, but it lacks the mechanism to iteratively raise learning success rate without constantly hitting the live web. You need a corpus of sanitized recordings + expected outcomes and a repeatable offline “learn → verify” evaluation run. Otherwise improvements will be anecdotal and regression-prone.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 6. Implementation Phases
@@
 ### Phase 1: Recipe Learning Improvement (IN PROGRESS)
@@
 - [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
+
+### Phase 1.5: Learning Corpus + Offline Evaluation (NEW, REQUIRED)
+
+**Goal**: Make “auto-learning success rate” measurable and improvable without live-site flakiness.
+
+- [ ] Add `recipes/corpus/` format:
+  - sanitized SessionRecording + CandidateSummary
+  - expected baseline fingerprint + extraction expectations
+  - provenance metadata (site category, auth required, volatility flags)
+- [ ] Add `mcp-server-browser-use eval --corpus recipes/corpus --ci`:
+  - runs the pipeline deterministically (LLM optional; stubbed modes supported)
+  - reports success rate, failure reasons, and regression diffs by stage
+- [ ] CI gate (soft at first, hard before v1):
+  - “no regressions in corpus success rate” unless baseline updated intentionally
```

---

## 10) Add missing tests for atomic writes + permissions + artifact integrity (and make them gating)

Why this makes the plan better
The plan mandates atomic writes and permissions (0700/0600), but doesn’t force them via tests. Those are exactly the kinds of guarantees that silently break over time. Make them invariant tests and add a small suite that runs on all platforms you support (with conditional skips where `O_NOFOLLOW` isn’t available).

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.2 Invariants (Testable)
@@
 | Invariant | Test |
@@
 | Task results truncated to 10KB in SQLite | `test_observability.py::TestTaskStore` |
+| Artifact dirs are 0700 + files 0600 | `test_artifacts_security.py::test_permissions` |
+| Artifact writes are atomic (no partial files) | `test_artifacts_security.py::test_atomic_write` |
+| Recipe YAML writes are atomic and non-following | `test_recipe_store_security.py::test_atomic_write_no_symlink` |
@@
 ### Gate 2b: Pipeline Golden + Fuzz (Automated, CI-safe)
@@
 - Golden fixtures for pipeline artifacts (SessionRecording/CandidateSet/RecipeDraft/MinimizationReport/VerificationReport)
+  - Include permission and atomic-write assertions as part of the golden suite where possible.
```

---

## 11) Strengthen “secrets never leak” beyond headers: add query/body secret detectors + repo-level secret scanning gate

Why this makes the plan better
Header stripping is necessary but not sufficient. Tokens frequently appear in query params (`access_token=...`) or JSON bodies. You already redact “query params and request bodies” in narrative form, but make it concrete: define a deterministic “secret detector” (keyword + entropy heuristic + allowlist exceptions), apply it to query/body before storage/logging/LLM, and add a repo gate (gitleaks/trufflehog) to reduce human error.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
@@
 2. **Secrets are redacted end-to-end.** Sensitive headers, cookies, query params, and request bodies are redacted before:
@@
    - sending any content to LLMs (analyzer prompts)
+2a. **Query/body secret detector (required).**
+    - Deterministic redaction for common key patterns: token, key, secret, auth, session, bearer, jwt, api_key, access_token, refresh_token
+    - Entropy-based heuristic redaction for high-entropy values above a small length threshold (with allowlist escapes for known safe params)
+    - Apply to URLs, JSON bodies, form bodies, and any “evidence windows” sent to LLMs.
@@
 ## 8. Quality Gates
@@
 ### Gate 1: Pre-Commit (Automated)
@@
 **Checks**: validate-pyproject, prettier, ruff-format, ruff-check, uv-lock-check, pyright, no-commit-to-branch, codespell.
+Add (v1 requirement): secret scan (gitleaks or trufflehog) over repo + test artifacts directory in CI.
```

---

## 12) Make the API/tool surface more “ship-ready”: define the interactive learning tool explicitly and standardize result envelopes

Why this makes the plan better
You mention interactive selection (CandidateSet) and a `recipe_create_from_candidate(...)` concept, but it’s not concretely specified in the Phase 2 “tool surface stabilization” list. If you want learning to be useful (and not block on LLM quality), you need a first-class “interactive learn” flow with stable schemas and predictable error envelopes. This also resolves the current “tool count mismatch” problem cleanly: you’ll have intentional tools with pinned schemas, not incidental ones.

Git-diff (plan text)

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
  - [ ] Tool surface stabilization:
    - Replace `recipe_run_direct` with `recipe_run(strategy="auto"|"direct"|"hint")`
    - Add `recipe_learn(task_id=..., strategy="auto"|"interactive")` (returns candidates/artifacts when needed)
    - Add `run(task, strategy="auto"|"agent"|"recipe")` (single entry-point; `run_browser_agent` becomes alias/deprecated)
+   - Add `recipe_create_from_candidate(task_id, candidate_id, name, params_schema, extract_spec)`:
+     - server validates candidate + produces RecipeDraft via validator (no LLM required)
+     - returns VerificationReport + saved recipe name on success
+   - Add `recipe_validate(draft_or_name, params)`:
+     - runs validator + dry-run compilation, returns structured warnings/errors (no network)
@@
 Contract stabilization is part of Phase 2 (v1 requirement, not optional):
 - [ ] MCP tool schemas pinned + contract tests in CI (Gate 2 pre-merge)
 - [ ] Error envelope standardized across tools + REST (includes error_code/retryable/retry_after_sec/task_id)
+  - Add “stage” and “reason_codes[]” fields to all errors (deterministic, enumerable)
+  - Ensure all tools return either:
+    - { ok: true, data: ..., meta: ... } OR
+    - { ok: false, error: { error_code, message, retryable, stage, reason_codes, task_id } }
```

---

### Summary of what I’d prioritize first (if you’re trying to ship v1 quickly)

1. Change 3 (browser-wide egress policy) + Change 5 (dashboard escaping/CSP): these close real security holes that are painful to retrofit later.
2. Change 1 + Change 9: these are the most direct path from “cool demo” to “reliable product,” because they turn recipe learning into an engineering loop rather than prompt luck.
3. Change 7 + Change 8: these make the “recipes are fast” claim consistently true and measurable.
