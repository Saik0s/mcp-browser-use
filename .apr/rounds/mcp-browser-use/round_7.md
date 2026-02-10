> Scope: Review the current PLAN_TO_SHIP_MCP_BROWSER_USE.md and AGENTS.md guidance, then propose concrete plan edits that increase reliability, performance, security, testability, and shipping clarity. 
> Confidence score: 0.78
> Perspective: “Ship a local-first MCP server that is hostile-web safe, predictable under load, and debuggable when learning fails.”
> Assumptions: Single-user/localhost is still the primary mode; recipes are intended to be portable artifacts eventually (library + sharing); direct execution is the product’s differentiator, so it should get disproportionate rigor.

Below are proposed plan revisions.
For each, I explain why it helps and provide a git-diff style patch against the plan text.

---

### 1) Put verification metadata in recipe YAML (without moving mutable stats out of SQLite)

Why this makes the plan better:
Right now the plan says baseline fingerprint lives in SQLite stats and “NOT in YAML”. That’s fine for a single machine, but it weakens portability and makes shipped/library recipes harder to validate after install. Adding a `verification` block in YAML (fingerprint/version/transport hint/verified_at) improves reproducibility, enables “import then verify” workflows, and prevents silent drift when SQLite is absent or reset. This is almost certainly beneficial and low risk because fingerprints aren’t secrets.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-BASELINE (new, required for v1):
-- Compute a `baseline_shape_fingerprint` from the selected candidate's CAPTURED response after applying the analyzer's extract spec.
-- Store baseline fingerprint (and fingerprint_version) as an artifact + in SQLite stats (NOT in YAML).
-- All subsequent replay/minimization/verification compares against this baseline, not against agent final text.
+BASELINE (new, required for v1):
+- Compute a `baseline_shape_fingerprint` from the selected candidate's CAPTURED response after applying the analyzer's extract spec.
+- Store baseline fingerprint (and fingerprint_version) as:
+  1) an artifact (portable, resumable)
+  2) SQLite stats (mutable/operational)
+  3) OPTIONAL: a read-only `verification:` block in recipe YAML (portable recipe metadata; no mutable counters).
+- All subsequent replay/minimization/verification compares against this baseline, not against agent final text.
@@
 class Recipe:
@@
     status: str                       # draft, verified, deprecated
     # + category, subcategory, tags, difficulty, auth fields
+    verification: RecipeVerification | None  # portable verification metadata (no counters)
+
+class RecipeVerification:
+    fingerprint_sha256: str
+    fingerprint_version: int
+    verified_at: datetime | None
+    transport_hint: str | None        # httpx_public | context_request | in_page_fetch
+    requires_session: bool | None
```

---

### 2) Promotion to `verified` must demonstrate generalization (two distinct parameter sets, when params exist)

Why this makes the plan better:
“Two consecutive successful replays” can still overfit to a single captured parameterization (especially for GET endpoints where the analyzer bakes values). Requiring two distinct parameter sets (when the recipe has parameters) is a strong anti-footgun: it turns “works once” into “template likely correct”. This almost certainly reduces false-verified recipes and improves long-term reliability.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-Promotion rule: 2 consecutive successful replays that match the baseline fingerprint + no auth recovery triggered
+Promotion rule (v1):
+- If recipe has zero parameters: 2 consecutive successful replays that match the baseline fingerprint + no auth recovery triggered.
+- If recipe has >=1 parameters: MUST pass fingerprint match on >=2 DISTINCT parameter sets:
+  - Set A: original task/example params (from recording/manifest)
+  - Set B: second example params (manifest/corpus) OR interactive user-provided params
+  - If no Set B exists, recipe stays `draft` and returns error_code=NEEDS_SECOND_EXAMPLE_FOR_VERIFY.
@@
-Transport inference (new, verifier responsibility):
+Transport inference (new, verifier responsibility):
 - Verifier MUST try transports in ascending risk order:
@@
 - First transport that matches baseline fingerprint becomes `transport_hint`.
 - If no transport matches, recipe stays draft and returns an interactive CandidateSet instead of writing YAML.
+ - Verification MUST run on both parameter sets (if required) before locking `transport_hint`.
```

---

### 3) Make parameterization explicit: add `ParameterSource` + constraints, and forbid “LLM-made” param names from skipping validation

Why this makes the plan better:
Parameterization is currently bundled into minimization, and the data model doesn’t express where a parameter comes from or what constraints it must satisfy. That becomes a security and correctness problem: a “query” param is not equivalent to a “csrf token from DOM” param. Adding `source` and `constraints` makes transport selection more deterministic, prevents unsafe templating, and improves user ergonomics (better error messages and input validation).

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 class Recipe:
@@
     parameters: list[RecipeParameter] # Input parameters with types
@@
+class RecipeParameter:
+    name: str
+    type: str                         # str|int|float|bool|json (v1)
+    required: bool
+    source: str                       # task_input | session | dom | constant
+    constraints: dict | None          # max_len, regex, enum, min/max, forbid_chars (CR/LF)
+    examples: list[str] | None
@@
-MINIMIZE+PARAMETERIZE (new, required for v1):
+MINIMIZE+PARAMETERIZE (new, required for v1):
@@
-  Phase D - Parameterization:
-    - Detected dynamic values (from task params) become {param_name} placeholders
-    - Static values stay hardcoded in template
+  Phase D - Parameterization:
+    - Detected dynamic values become typed RecipeParameters with explicit `source`.
+      - task_input: provided by caller (safe default)
+      - session: derived from cookies/session state (never caller-provided)
+      - dom: requires DOM access (forces in_page_fetch unless verifier proves otherwise)
+      - constant: baked in, non-templated
+    - Parameter constraints enforced BEFORE substitution (CR/LF blocking, length caps, regex if present).
+    - LLM-suggested parameter names are treated as untrusted: validator may rename to canonical safe identifiers.
```

---

### 4) Replace O(n²) “drop-one header/param at a time” with delta debugging (ddmin) + replay result caching

Why this makes the plan better:
The current minimizer can be too slow and too flaky on real sites: `2 * len(headers)` + `2 * len(params)` replays is expensive and likely to trigger rate limits. ddmin reduces attempts dramatically for larger sets, and caching prevents re-running identical request shapes. This is a probable win for both performance and reliability.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
-Minimization algorithm (v1):
+Minimization algorithm (v1):
@@
-  Phase B - Header minimization (requires replay):
-    - Start with full header set from recording
-    - Drop one header at a time, replay, check shape fingerprint matches baseline
-    - Keep minimal set that preserves fingerprint match
-    - Max attempts: 2 * len(headers), hard timeout 30s total
+  Phase B - Header minimization (requires replay):
+    - Use delta debugging (ddmin) over the header set to find a minimal sufficient subset.
+    - Cache replay outcomes by request_signature_sha256 to avoid duplicate calls.
+    - Budget: max_attempts=24 total replays OR 30s wall-clock (whichever first).
@@
-  Phase C - Query param minimization (requires replay):
-    - Same drop-one-at-a-time strategy for query parameters
-    - Max attempts: 2 * len(params), hard timeout 30s total
+  Phase C - Query param minimization (requires replay):
+    - Same ddmin strategy + replay cache.
+    - Budget: max_attempts=24 total replays OR 30s wall-clock (whichever first).
+    - Add per-host pacing (default 250ms) during minimization to reduce 429s.
```

---

### 5) Add “DNS pinning per request chain” plus bounded DNS caching (perf) without weakening rebinding defenses (security)

Why this makes the plan better:
You’re already doing DNS rebinding checks and hop-by-hop validation, which is correct. The missing piece is making that efficient and less TOCTOU-prone: pin resolution results for the duration of a single request chain (including redirects), and cache DNS answers briefly with tight TTL bounds to avoid repeated lookups in hot paths. This is a probable performance win and can be done without reducing security if you still re-resolve on retries and treat mixed answers as block.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 3b. **Single EgressPolicy module (required).** Implement one shared `EgressPolicy` used by:
@@
     Tests MUST prove every transport invokes the same validation logic and blocks the same forbidden targets.
+3c. **DNS pinning + bounded cache (required).**
+    - For each execution attempt, resolve host once and pin the allowed IP set for that request chain (including redirects).
+    - Re-resolve on each retry attempt (prevents “wait out TTL then rebind”).
+    - Implement bounded LRU cache for DNS answers:
+      - max_entries: 256
+      - ttl_seconds: 5 (default)
+      - negative caching: 2s
+    - If any A/AAAA answer is private/link-local/loopback => block (unchanged).
```

---

### 6) Add per-host concurrency + rate-limit budget to direct execution (prevents self-induced bans and improves tail latency)

Why this makes the plan better:
Global “max concurrent direct recipe runs” is useful, but it doesn’t protect you from hitting one host too hard (common in batch learning or repeated calls). A per-host semaphore plus a simple token bucket reduces 429s and makes p95 more stable. This is very likely to improve real-world reliability.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### 2.1.1 Concurrency + Resource Budgets (v1)
@@
 - Global limits:
@@
   - max concurrent direct recipe runs (default 4)
+  - per-host concurrent direct runs (default 2 per canonical host)
+  - per-host token bucket (default 20/min burst 5) for direct exec to reduce 429s
@@
 - Per-task limits:
@@
     - retry MUST re-validate URL (prevents DNS rebinding between attempts)
+    - retries MUST consume per-host budget (prevents retry storms on a single host)
```

---

### 7) Fail fast on “probable secrets in task input” unless explicitly opted in (prevents accidental credential leakage to LLM providers)

Why this makes the plan better:
The plan is rigorous about redacting secrets in recordings, YAML, logs, SSE, analyzer prompts. The biggest remaining leak vector is the user’s own task string (or tool params) getting sent into browser-use prompts and then to external LLM APIs. Adding a default refusal when the secret detector triggers in `task` is a strong, practical protection. Users can still opt in explicitly if they really need credentialed flows.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 2. **Secrets are redacted end-to-end.** Sensitive headers, cookies, query params, and request bodies are redacted before:
@@
    - sending any content to LLMs (analyzer prompts)
@@
 2a. **Query/body secret detector (required).**
@@
     - Action: replace value with [REDACTED:key_name] (preserves debuggability)
+2b. **Task input secret guard (required).**
+    - Apply the same detector to:
+      - MCP tool inputs (task strings, params)
+      - REST request bodies
+    - Default behavior: if probable secret detected in `task`, refuse with error_code=SECRET_IN_TASK
+      unless `server.allow_task_secrets=true` (explicit opt-in).
+    - If opted in, task text stored/logged/artifacted MUST be redacted; original used only in-memory.
```

---

### 8) Browser hardening: disable downloads, file chooser, and dangerous permissions by default

Why this makes the plan better:
A hostile page can trigger downloads, permission prompts, or attempt to coerce file upload flows. Even if that doesn’t immediately become RCE, it increases the chance of local data exposure and messy state. Disabling downloads and restricting permissions is a straightforward hardening step with high leverage.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 4a. **Server-owned browser by default.** Default mode MUST launch a fresh Playwright-managed Chromium instance (no external CDP).
@@
 4a.5 **Explicitly forbidden flags (required).** Reject (fail-fast) any configuration that would enable:
@@
      - `--no-sandbox`
@@
      - loading arbitrary extensions unless `browser.allow_extensions=true` (expert-mode)
+4a.6 **Disable downloads + dangerous permissions by default (required).**
+     - Downloads disabled by default; enabling requires explicit `browser.allow_downloads=true`
+       and forces download dir under `~/.local/state/mcp-server-browser-use/downloads/` (0700).
+     - Deny-by-default for permission prompts (geolocation, notifications, clipboard, midi, camera, microphone).
+     - Block file chooser interactions unless explicitly enabled in expert mode.
```

---

### 9) Threat model: add several SSRF/URL-ambiguity and local-exposure edge cases that are currently missing

Why this makes the plan better:
You already cover a lot. The missing category is URL ambiguity and “small parsing differences” across transports (relative redirects, IPv4-mapped IPv6, weird whitespace). These are common SSRF bypass sources. Also, if you add the “SECRET_IN_TASK” gate (change #7), it should be represented in the threat model with tests.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 | Threat | Impact | Guardrail | Test |
@@
 | SSRF via IPv6/encoded IP | Private net access via parsing ambiguity | Normalize/parse host strictly; block IPv6 private ranges; reject non-canonical IP encodings | `test_recipes_security.py::test_ssrf_ip_parsing_*` |
+| SSRF via IPv4-mapped IPv6 | Private net access via ::ffff:127.0.0.1 style hosts | Treat IPv4-mapped IPv6 as IPv4 and block private/loopback | `test_recipes_security.py::test_ssrf_ipv4_mapped_ipv6` |
+| SSRF via relative Location redirects | Bypass hop validation by resolving against a different base | Resolve Location relative to current URL, then validate | `test_recipes_security.py::test_redirect_relative_location` |
+| SSRF via whitespace/control chars in URL | Parser differential across transports | Reject any URL containing ASCII control chars or spaces post-normalization | `test_recipes_security.py::test_url_control_chars_blocked` |
@@
 | Localhost CSRF (drive-by POST/DELETE to server) | Attacker triggers browser tasks / outbound fetches | Require auth for all state-changing endpoints by default; strict Origin/Host checks for dashboard; CORS disabled | `test_http_auth.py::test_write_endpoints_require_token` |
+| Credential leakage via secrets in task input | Secrets sent to LLM provider or logs | SECRET_IN_TASK default refusal + redaction | `test_secret_in_task.py` |
```

---

### 10) Testing: add “transport differential” + “secret detector correctness” + “browser hardening” suites as first-class gates

Why this makes the plan better:
Your testing section is already thoughtful. The main gap is that new hardening rules (downloads/permissions/secret-in-task) need explicit tests, and the transport parity suite should include URL normalization edge cases (relative redirects, IPv4-mapped IPv6, whitespace). Also, the secret detector needs property-style tests to reduce false negatives/positives.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 Testing suites (new, required for v1):
 1) Hostile Web Harness (integration):
@@
 2) Pipeline Golden Suite (unit-ish):
@@
 3) Fuzz/Property Suite (unit):
@@
   - bounded runtime suitable for CI
+4) Secret Detector Suite (unit/property):
+  - property tests for entropy/key-pattern detector across URL/query/json/form
+  - regression fixtures for known-safe high-entropy params (pagination cursors)
+  - tests for SECRET_IN_TASK default refusal
+5) Browser Hardening Suite (integration, CI-safe):
+  - downloads disabled (attempted download yields deterministic error_code=DOWNLOAD_BLOCKED)
+  - permission prompts denied
+  - file chooser blocked by default
```

---

### 11) Move auth-token enforcement (TODO-001) earlier: before recipe learning scale-up and before “v1 feels usable”

Why this makes the plan better:
The plan labels TODO-001 as P1, but schedules it in Phase 2. If someone binds to non-loopback by accident (or dashboard is reachable), you have a serious exposure. This should land before you broaden functionality. I’d treat this as “Phase 1.2 hardening” alongside EgressPolicy and transport parity.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 ### Phase 1.2: Runner + Policy Parity Hardening (NEW, REQUIRED)
@@
 **Goal**: Make direct execution fast, consistent across transports, and security-invariant before expanding scope.
 
 - [ ] Implement shared `EgressPolicy` and enforce it in all transports + agent navigation
+- [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
+  - MUST refuse non-loopback bind unless auth_token set
+  - MUST require auth for all state-changing endpoints by default (even on loopback)
+  - MUST redact tokens from logs/errors/SSE
 - [ ] Add Transport Parity Suite (CI-safe)
@@
-### Phase 2: Hardening + Contract Stabilization (PLANNED)
+### Phase 2: Hardening + Contract Stabilization (PLANNED)
@@
-**Goal**: Resolve all P1 and P2 issues, make recipes production-ready
+**Goal**: Resolve remaining P2 issues, stabilize contract, and make recipes production-ready
@@
-- [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
+-- [ ] (moved to Phase 1.2) Auth token enforcement for non-localhost (TODO-001)
```

---

### 12) SSE reliability: add event IDs + replay (`Last-Event-ID`) and persist a bounded event log per task

Why this makes the plan better:
SSE is fragile under disconnects. Without event IDs and replay, dashboards and clients miss progress and look “stuck”. Persisting a bounded per-task event stream (SQLite table) makes the system feel reliable and dramatically improves debuggability. This is very likely to reduce support/debug time.

```diff
diff --git a/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md b/plans/PLAN_TO_SHIP_MCP_BROWSER_USE.md
@@
 Observability requirements (v1):
@@
 - SSE emits structured progress events per stage (safe + redacted)
+ - SSE MUST support reconnect + replay:
+   - events include monotonically increasing `event_id`
+   - server honors `Last-Event-ID` header to replay missed events
+   - persist a bounded event log per task in SQLite (`task_events` table, max 200 events/task)
+   - emit periodic keepalive ping events (every 15s) to keep proxies honest
@@
 class TaskRecord:
@@
     error: str | None                 # Truncated to 2KB
+
+class TaskEvent:
+    task_id: str
+    event_id: int
+    ts: datetime
+    stage: str | None
+    message: str | None               # redacted + bounded
+    payload: JSONValue | None         # redacted + bounded
```

---

If you adopt only a subset, the highest-leverage order (probable impact) is: 11 (auth earlier), 7 (secret-in-task guard), 12 (SSE replay), 2 (two-param verification), 4 (ddmin minimizer), 6 (per-host budgets), 5 (DNS pinning/cache), 8/9/10 (browser hardening + tests), 1/3 (YAML verification + param model).
