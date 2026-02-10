```text
META
Scope: Revisions to PLAN_TO_SHIP_MCP_BROWSER_USE.md (v2.6) to improve robustness, execution speed, security posture, testability, and day‑to‑day DX for a real Python MCP server.
Confidence: 78/100 (probable these changes reduce flakiness + close real gaps; exact sizing/priority depends on current code hotspots and client usage patterns).
Perspective: Security- and performance-minded maintainer optimizing for “works reliably on real sites” and “easy to debug when it doesn’t”.
Assumptions:
- Single-user, localhost-first daemon over HTTP; stdio is only a compatibility proxy. :contentReference[oaicite:0]{index=0}
- Recipes are primarily an acceleration path; correctness and safety dominate over aggressiveness in learning. :contentReference[oaicite:1]{index=1}
- Direct execution must remain safe even if the LLM output is hostile or the visited site is malicious. :contentReference[oaicite:2]{index=2}
```

Below are the plan revisions I’d make.
Each item includes (1) why it’s better and (2) a git-diff style patch against the current plan text. 

---

## 1) Add an explicit Session/Profile model (closes a major execution gap for “session-required” recipes)

Why this makes the plan better:

Right now, the plan implicitly assumes direct execution always has access to the right “browser_session” (cookies/session state).
That’s true inside a single `run_browser_agent(..., learn=True)` call, but it breaks down for:

* `recipe_run_direct` / `recipe_run(...)` invoked standalone (no existing logged-in context).
* reusing a logged-in session across multiple tasks (the main real-world use case for “fast path”).
* debugging auth expiry (401/403) and deciding whether to recover via agent, re-login, or demote.

Adding a first-class `session_id` (ephemeral by default, optionally persistent “profile slots”) makes recipe execution deterministic and debuggable, and prevents hidden cross-task state bleed.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ## 0.1 Non-Negotiables
@@
-5. **Per-task isolation.** Each task executes in an isolated browser context by default (separate cookies/storage), unless explicitly configured otherwise.
+5. **Per-task isolation.** Each task executes in an isolated browser context by default (separate cookies/storage), unless explicitly configured otherwise.
+5a. **Explicit sessions (required).** Any execution that depends on cookies/session MUST run against an explicit `session_id` managed by the server.
+    - Default: every `run(...)` / `run_browser_agent(...)` creates an ephemeral session and returns `session_id` in `meta`.
+    - TTL: sessions auto-expire after `server.session_ttl_minutes` (default 20) and are GC’d (contexts closed).
+    - Direct recipe runs:
+      - if `recipe.requires_session=false`: allowed without `session_id` (httpx_public).
+      - if `recipe.requires_session=true`: MUST provide `session_id` OR use `strategy="agent"` to establish one.
+5b. **Persistent profiles are expert-mode.** Optional named profiles (persistent user-data-dir) are allowed only with explicit enable + warnings.
+    - Profiles live under `~/.config/mcp-server-browser-use/profiles/<name>/` (0700).
+    - Never stored in artifacts; never shown in logs; never sent to LLMs.
@@
 ## 2.1 Server Execution Model
@@
-async def run_browser_agent(task: str, ..., recipe_name: str | None = None,
-                            learn: bool = False, save_recipe_as: str | None = None):
+async def run_browser_agent(task: str, ..., recipe_name: str | None = None,
+                            learn: bool = False, save_recipe_as: str | None = None,
+                            session_id: str | None = None):
@@
-    # 2. Try recipe fast path (if recipe_name provided)
+    # 2. Acquire session (explicit) or create ephemeral
+    session = await session_manager.get_or_create(session_id=session_id)
+    # 3. Try recipe fast path (if recipe_name provided)
@@
-            result = await RecipeRunner().run(recipe, params, browser_session)
+            result = await RecipeRunner().run(recipe, params, session)
@@
-    agent = Agent(task=task, llm=llm, browser=browser, ...)
+    agent = Agent(task=task, llm=llm, browser=session.browser, ...)
@@
-    return result
+    return {"ok": True, "data": result, "meta": {"task_id": task_record.task_id, "session_id": session.id}}
```

---

## 2) Make pipeline artifacts schema-validated Pydantic models (prevents “resume drift” and improves reliability)

Why this makes the plan better:

The plan already mandates deterministic artifacts, but it doesn’t explicitly require schema validation on read/write or controlled evolution (versioning + migrations).
Without that, resume-from-stage becomes fragile and regressions become silent (an artifact shape changes and a later stage misinterprets it).

Add a lightweight “Artifact Contract” layer: each stage reads/writes a Pydantic model, validates bounds, and includes a `schema_hash` so a resume run can fail fast with a clear error instead of producing junk recipes.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)
@@
-Each stage MUST emit a versioned artifact to disk so failures are reproducible and the pipeline can resume.
+Each stage MUST emit a versioned artifact to disk so failures are reproducible and the pipeline can resume.
+Artifacts are not “ad-hoc JSON”: they MUST be schema-validated Pydantic models on write AND on read (resume).
+Every artifact MUST include:
+  - `artifact_version`
+  - `schema_hash` (sha256 of canonicalized Pydantic JSON schema for the model)
+  - `payload_sha256` (sha256 of the serialized payload)
+Resume rules (v1):
+  - If `schema_hash` mismatches current code, resume MUST stop with error_code=ARTIFACT_SCHEMA_MISMATCH (actionable).
+  - Provide `mcp-server-browser-use artifacts migrate --task-id ...` for best-effort migrations when safe.
@@
 #### Phase 1 deliverables (make modules real)
@@
 - [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
+ - [ ] Add `recipes/artifacts/models.py` (Pydantic models for all stage artifacts + schemas + bounds)
+ - [ ] Add `recipes/artifacts/store.py` (atomic write/read, schema_hash checks, permission enforcement, non-following opens)
```

---

## 3) Add a “no-network replay mode” for corpus + unit tests (massively reduces flakiness and speeds iteration)

Why this makes the plan better:

Phase 1.5 introduces a learning corpus, but the pipeline still implicitly relies on live replay for minimization/verification.
You’ll move faster if you can run most of the pipeline deterministically offline:

* Candidate scoring + heuristic analyzer + validator + fingerprinting can run entirely offline.
* Verification logic can be tested against recorded response stubs without hitting sites (especially for extract/fingerprint stability).
* You can regression-test LLM prompt + output parsing without paying network and without site drift.

This doesn’t replace live E2E; it complements it and makes success-rate improvements measurable.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 1.5: Learning Corpus + Offline Evaluation (NEW, REQUIRED)
@@
 - [ ] Add `mcp-server-browser-use eval --corpus recipes/corpus --ci`:
-  - runs the pipeline deterministically (LLM optional; stubbed modes supported)
+  - runs the pipeline deterministically (LLM optional; stubbed modes supported)
+  - supports `--no-network`:
+    - all transports replaced with corpus-provided ResponseStubs (bounded, redacted)
+    - minimizer/verifier operate on stubs for extract+fingerprint validation
+    - any attempt to do live network in this mode fails fast (error_code=NETWORK_DISABLED)
   - reports success rate, failure reasons, and regression diffs by stage
@@
   Corpus file layout:
@@
-    │   ├── expected_fingerprint.json  # baseline shape fingerprint
+    │   ├── expected_fingerprint.json  # baseline shape fingerprint
+    │   ├── response_stub.json         # bounded response stub for offline extract+fingerprint validation
@@
   Corpus entry metadata.yaml:
@@
     expected_transport: httpx_public | context_request | in_page_fetch
```

---

## 4) Improve candidate ranking robustness with dedup + request graph signals (reduces “wrong money request” picks)

Why this makes the plan better:

Heuristic ranking often fails for two reasons:

1. The “money request” repeats (same endpoint called with slightly different params); naive top-k returns duplicates.
2. Telemetry endpoints can look “task-related” by URL text overlap.

Fix both by (a) canonical dedup and (b) adding request-graph and initiator features (CDP provides initiator + timing relationships).
This raises success rate without touching the LLM.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 Signal features per request (v1):
@@
   - resource_type: str (xhr/fetch/document)
+  - initiator_type: str (parser/script/preload/other)
+  - has_initiator_stack: bool (CDP initiator stack present; often correlates with app API calls vs browser noise)
+  - same_site_as_page: bool (request eTLD+1 == current page eTLD+1)
   - is_likely_telemetry: bool (URL matches common analytics/tracking patterns)
@@
 CANDIDATES (new, required for v1):
 - Takes signal feature vectors from SIGNALS stage and applies ranking heuristics (weighted sum, no ML).
 - Produces top_k=8 ranked candidates with composite scores + per-feature breakdown.
 - Pure functions only, no LLM calls, no network I/O.
+ - MUST de-duplicate by canonical endpoint key before selecting top_k:
+   - endpoint_key = (method, canonical_host, canonical_path, sorted(query_param_names))
+   - keep the single best-scoring exemplar per endpoint_key
+   - ensures top_k covers diversity rather than repeats
```

---

## 5) Unify SSRF/egress enforcement across ALL transports with a single EgressPolicy (closes real bypasses)

Why this makes the plan better:

The plan requires a Playwright route handler for egress policy, but route interception covers page/network traffic, not necessarily every programmatic request path equally (notably `context.request` vs in-page fetch vs httpx).
Security becomes reliable when one shared policy module is used everywhere and tests assert “every outbound hop calls the same validator”.

Also: explicitly banning redirects in `in_page_fetch` (or requiring strict allowlist) shrinks the highest-risk surface.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 3a. **Browser-wide egress policy (required).** Attach a Playwright route handler per context that blocks any request to:
@@
    Default mode SHOULD be "lite" (fast checks); "strict" mode MAY resolve DNS for all requests with bounded caching.
+3b. **Single EgressPolicy module (required).** Implement one shared `EgressPolicy` used by:
+    - Playwright route handler (page subresources + navigation)
+    - httpx_public transport
+    - context_request transport (manual redirects + per-hop validation)
+    - in_page_fetch transport (pre-validated URL; redirects disabled by default)
+    Tests MUST prove every transport invokes the same validation logic and blocks the same forbidden targets.
@@
 Transport caps MUST be uniform (v1, required):
@@
 - MAX_RESPONSE_SIZE applies after decompression for ALL transports (httpx_public, context_request, in_page_fetch).
 - MAX_HEADER_BYTES and MAX_REDIRECTS apply for ALL transports.
+ - in_page_fetch MUST default to `redirect: "error"` semantics (treat any redirect as failure) unless recipe explicitly opts in and verifier proves safety hop-by-hop.
```

---

## 6) Expand secret redaction to include response headers + Set-Cookie + Location, and add “redaction budget” tests

Why this makes the plan better:

Most systems redact request headers but accidentally leak secrets via:

* `Set-Cookie` in response headers (especially in artifacts or task logs)
* `Location` headers containing tokens in query strings
* error messages that echo full URLs or headers
* analyzer “evidence windows” that include raw headers

Make redaction end-to-end truly end-to-end.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 2. **Secrets are redacted end-to-end.** Sensitive headers, cookies, query params, and request bodies are redacted before:
@@
    - sending any content to LLMs (analyzer prompts)
+   - storing any response headers in artifacts (Set-Cookie, Location must be redacted)
@@
 2a. **Query/body secret detector (required).**
@@
     - Apply to URLs, JSON bodies, form bodies, and any "evidence windows" sent to LLMs.
+    - Apply to response headers captured in recordings and artifacts:
+      - Always redact Set-Cookie entirely
+      - Redact Location query params using the same key+entropy rules
@@
 ## 0.2 Invariants (Testable)
@@
 | Invariant | Test |
@@
+| Artifacts never contain Set-Cookie or unredacted Location query tokens | `test_artifacts_redaction.py` |
+| Analyzer evidence windows respect byte budgets post-redaction | `test_analyzer_budgets.py` |
```

---

## 7) Harden CDP/Chromium launch with an allowlisted arg set, and explicitly forbid “no-sandbox” + risky debug modes

Why this makes the plan better:

CDP hardening is already emphasized, but the plan doesn’t explicitly require:

* launch-arg allowlisting (prevent accidental enabling of insecure features)
* explicit forbids (`--no-sandbox`, non-loopback debugging)
* verifying that the actual launched browser matches the expected security posture (extensions disabled, debug port not exposed)

This turns “guidance” into enforceable invariants.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 4a.1 **No exposed debug port by default.** Server MUST ensure the Playwright-launched browser is not listening on a non-loopback debug port; fail-fast if detected.
 4a.2 **No extensions by default.** Playwright-launched Chromium MUST disable extensions and component extensions unless explicitly enabled in expert mode.
 4a.3 **Pipe-first control.** Prefer pipe-based browser control where supported; treat any debug-port mode as expert-only with extra validation and warnings.
+4a.4 **Launch-arg allowlist (required).** Chromium launch args MUST be generated from an allowlist; user-provided raw args are rejected by default.
+4a.5 **Explicitly forbidden flags (required).** Reject (fail-fast) any configuration that would enable:
+     - `--no-sandbox`
+     - remote debugging bound to non-loopback
+     - loading arbitrary extensions unless `browser.allow_extensions=true` (expert-mode)
@@
 4b. **External CDP is "expert mode".** Requires explicit flag + strong warnings + additional checks:
@@
     - require isolated user-data-dir unless explicitly overridden
+    - require `browser.external_cdp_ack_risk=true` (explicit acknowledgement gate)
```

---

## 8) Recipe execution performance: add pooled clients + warmup + deterministic per-stage timing with a strict “runner overhead” budget

Why this makes the plan better:

You already set p50/p95 CPU overhead targets, but to actually hit them you need:

* a single shared `httpx.AsyncClient` (keep-alive, HTTP/2) for httpx_public
* reuse Playwright `APIRequestContext` per session for context_request
* a “warmup” path that precompiles RecipeIR and pre-initializes transports
* hard separation of “runner CPU overhead” vs “network” so regressions are diagnosable

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.2 Recipe Direct Execution (The Fast Path)
@@
-    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate)
+    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate, compile_ms)
@@
-    transport = self._select_transport(recipe, browser_session)  # "httpx_public" | "context_request" | "in_page_fetch"
+    transport = self._select_transport(recipe, session)  # "httpx_public" | "context_request" | "in_page_fetch"
@@
+Transport implementation requirements (v1, required):
+- httpx_public MUST use a process-global pooled `httpx.AsyncClient` with:
+  - keep-alive enabled
+  - HTTP/2 enabled when available
+  - strict connect/read timeouts (configurable)
+  - proxy env vars ignored by default
+- context_request MUST reuse a per-session `APIRequestContext` where possible (avoid recreating per call).
+- warmup:
+  - `mcp-server-browser-use recipes warmup` precompiles verified recipes and primes transport objects
+  - warmup reports cache stats and per-recipe compile_ms
@@
 ## 7. Performance Budgets
@@
 - runner stage timings: validate_url, transport_select, request, extract, postprocess
+ - runner stage timings MUST split:
+   - pure CPU time (parse/validate/compile/extract) vs network time (connect/TTFB/download)
+   - include `dns_ms` and `redirect_validate_ms` explicitly (security cost is measurable)
```

---

## 9) Threat model: add missing real-world failure modes (cache poisoning, service-worker weirdness, log injection, YAML edge cases)

Why this makes the plan better:

The existing threat model is strong on SSRF and web nastiness, but it’s missing several “death by a thousand cuts” issues that show up in real automation servers:

* service worker / cache interference (stale responses used as “baseline”)
* HTTP cache poisoning / intermediary caching when using httpx_public
* log injection (newlines/control chars in task input or remote headers)
* YAML parsing ambiguities and unicode confusables affecting allowlists/recipe names

Add explicit guardrails and tests so these don’t become production incidents.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Failure Modes
@@
 | Threat | Impact | Guardrail | Test |
@@
+| Service worker / cache returns stale or poisoned data | Wrong baselines + false “verified” recipes | Disable service workers in server-owned contexts by default; bypass caches for verifier replays | `test_service_worker_cache.py` |
+| HTTP cache poisoning on httpx_public | Wrong data / persistence across runs | Send conservative cache headers; optionally disable caching; never persist httpx cache | `test_http_cache_behavior.py` |
+| Log injection via control chars/newlines | Corrupted logs + misleading audit trails | Sanitize log fields; strip control chars from untrusted strings | `test_logging_sanitization.py` |
+| YAML unicode confusables / odd scalars | Recipe name collisions / policy bypass | Normalize recipe names to NFC + strict charset; reject confusables in identifiers | `test_recipe_name_normalization.py` |
```

---

## 10) Testing: add transport-parity tests and a dedicated “egress policy parity” suite (prevents regressions across httpx/context_request/in_page_fetch)

Why this makes the plan better:

You already plan hostile web + fuzz + perf gates, but the single biggest long-term regression risk is “one transport drifts from the others”:

* httpx_public blocks something that context_request accidentally allows
* redirects are manual in one transport but auto-follow sneaks back in another
* response size caps apply pre-decompression in one path but post-decompression in another

Add a parity harness that runs the same scenario against all transports and asserts identical safety outcomes.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 1.6 Testing Strategy Additions (Needed for v1.0 reliability)
@@
 - Deterministic local test server for recipes:
@@
 - Add "malicious web" scenarios:
@@
 - Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
+ - Transport parity suite (new, required):
+   - run identical hostile-server scenarios through httpx_public, context_request, in_page_fetch
+   - assert: URL validation decisions, redirect handling, decompression caps, and error_codes match
+   - ensures “one transport” cannot silently weaken the security model
@@
 ## 8. Quality Gates
@@
 ### Gate 2a: Hostile Web Harness (Automated, CI-safe)
@@
 **Response**: must pass or merge blocked
+### Gate 2aa: Transport Parity (Automated, CI-safe)
+**Trigger**: PR to main
+**Checks**: same scenario matrix across all transports; parity assertions on safety + caps + error envelope
+**Response**: must pass or merge blocked
```

---

## 11) API/DX: introduce idempotency keys + stable task creation semantics (reduces accidental duplicate runs and simplifies clients)

Why this makes the plan better:

When MCP clients or dashboards retry on network hiccups, you can accidentally start duplicate tasks.
For expensive browser tasks, idempotency is a big usability win and also reduces DoS risk.

Also: standardizing “task created” responses across MCP and REST improves client implementation and contract tests.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
--- a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
+++ b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
  - [ ] Error envelope standardized across tools + REST (includes error_code/retryable/retry_after_sec/task_id)
@@
 class ResponseMeta(TypedDict, total=False):
     transport_used: str
     timings_ms: dict[str, int]
     cache_hit: bool
     redirect_hops: int
     fingerprint_match: bool | None
+    session_id: str | None
+    idempotency_key: str | None
+
+Idempotency (v1, required):
+- REST: accept `Idempotency-Key` header on task-creating endpoints and tool-equivalent REST calls.
+- MCP: accept `idempotency_key` field on tools that create tasks (`run`, `run_browser_agent`, `run_deep_research`).
+- Server behavior:
+  - if same key + same normalized input arrives within TTL, return the original task_id (no duplicate run).
+  - idempotency keys are never logged verbatim and are redacted like secrets.
```

---

## 12) Add a missing phase: “Phase 1.2 Runner + Policy Parity Hardening” (keeps Phase 2 from becoming a dumping ground)

Why this makes the plan better:

Phase 2 currently contains a mix of auth hardening, contract stabilization, runner DX, perf harness, and assorted P2 issues.
That’s a lot of surface area, and it increases the chance Phase 2 slips.

Introduce a small Phase 1.2 focused only on:

* EgressPolicy unification + transport parity tests
* pooled clients + warmup + benchmarks (CI-safe)
* artifact schema contracts (so resume isn’t brittle)

This makes Phase 2 more purely “auth + public contract + release hardening”.

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
+### Phase 1.2: Runner + Policy Parity Hardening (NEW, REQUIRED)
+**Goal**: Make direct execution fast, consistent across transports, and security-invariant before expanding scope.
+- [ ] Implement shared `EgressPolicy` and enforce it in all transports + agent navigation
+- [ ] Add Transport Parity Suite (CI-safe)
+- [ ] Add pooled clients (httpx_public) + per-session APIRequestContext reuse (context_request)
+- [ ] Implement `recipes warmup` + `bench --ci` and wire perf gate
+- [ ] Add artifact schema_hash + resume fail-fast behavior
@@
 ### Phase 1.5: Learning Corpus + Offline Evaluation (NEW, REQUIRED)
```

---

If you apply only a subset, the highest leverage sequence (probable fastest success-rate + reliability improvement) is: (1) explicit sessions, (2) artifact schema contracts, (3) no-network replay mode, (4) EgressPolicy + transport parity tests, (5) pooled clients + warmup/bench.
