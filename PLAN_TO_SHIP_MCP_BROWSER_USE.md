---
project: mcp-browser-use
version: "3.0"
status: reviewed
oracle_rounds: 7
dialectical_rounds: 0
premortem_done: true
last_reviewed: 2026-02-10
definition_of_ready: true
beads_created: true
---

# PLAN_TO_SHIP_MCP_BROWSER_USE

**Version 3.0** — 2026-02-10
**Status**: Active Development (feat/fastmcp-3-recipes)
**Owner**: Igor Tarasenko

---

## 0. Executive Blueprint

MCP Browser Use is a Model Context Protocol server that wraps [browser-use](https://github.com/browser-use/browser-use)
for AI-powered browser automation. An AI client (Claude Desktop, Cursor, any MCP client) connects to the server over HTTP,
calls MCP tools, and the server orchestrates a real Chromium browser via Playwright/CDP to execute tasks autonomously.

The key innovation is **recipes**: the server can learn API shortcuts from browser sessions, then replay them
in a few seconds instead of ~60 seconds for full browser automation (site-dependent; measure p50/p95). A recipe captures the "money request" (the API call
that returns the actual data) and replays it directly via CDP fetch, inheriting the browser's cookies and session state.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         HOW IT WORKS                                    │
│                                                                         │
│  Claude Desktop / Cursor / Any MCP Client                               │
│         │                                                               │
│         │  HTTP (streamable-http or SSE)                                 │
│         ▼                                                               │
│  ┌─────────────────────────────────────────┐                            │
│  │   FastMCP Server (daemon on :8383)       │                            │
│  │                                         │                            │
│  │   MCP Tools:                            │   REST API:                │
│  │   - run_browser_agent                   │   GET  /api/health         │
│  │   - run_deep_research                   │   GET  /api/tasks          │
│  │   - recipe_list/get/delete/run          │   POST /api/learn          │
│  │   - health_check, task_list/get/cancel  │   SSE  /api/events         │
│  │                                         │                            │
│  │   Web Dashboard:                        │                            │
│  │   GET / (viewer) GET /dashboard         │                            │
│  └──────────┬──────────────────────────────┘                            │
│             │                                                           │
│    ┌────────┼────────┬─────────────┬──────────────┐                     │
│    ▼        ▼        ▼             ▼              ▼                     │
│  Config   LLM     Recipes      Research      Observability             │
│  Pydantic Factory  CDP+YAML    State Machine  SQLite+SSE               │
│           12 provs                             Task tracking            │
│                      │                                                  │
│             ┌────────┴────────┐                                         │
│             ▼                 ▼                                         │
│        Direct Exec       browser-use                                   │
│        CDP fetch()       Agent + Playwright                            │
│        fast path         ~60 seconds                                   │
│             │                 │                                         │
│             └────────┬────────┘                                         │
│                      ▼                                                  │
│                  Chromium                                               │
│              (headless or headed)                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Non-Goals
- Not a general-purpose web scraping framework (use Scrapy, Crawlee for that)
- Not a testing tool (use Playwright Test directly)
- Not multi-tenant or cloud-hosted (single-user, localhost)

### Definition of Done (v1.0)
- [ ] Server starts as daemon, clients connect over HTTP
- [ ] `run_browser_agent` works end-to-end with recipe learning
- [ ] Direct recipe execution delivers 30x speedup over browser path
- [ ] 20+ verified recipes across 4+ categories
- [ ] Auth defaults hardened (v1 gate)
  - MUST refuse `host=0.0.0.0` (or any non-loopback bind) unless `auth_token` is set
  - MUST refuse all state-changing requests (POST/PUT/PATCH/DELETE) without token by default (even on loopback)
  - MUST avoid logging tokens and redact from errors
  - Dashboard must be disabled by default on non-loopback binds (explicit enable required)
- [ ] All P1 and P2 issues resolved
- [ ] CI pipeline running on PRs
- [ ] Published to PyPI

---

## 0.1 Non-Negotiables

0. **Loopback-first binding.** Default bind is `127.0.0.1`. Any non-loopback bind requires explicit config + auth token.
0a. **Authenticated writes by default.** All state-changing endpoints require auth unless explicitly opted out for local dev.
1. **HTTP transport only.** Stdio is blocked with a migration message. Browser tasks take 60-120s; stdio timeouts kill them.
2. **Secrets are redacted end-to-end.** Sensitive headers, cookies, query params, and request bodies are redacted before:
   - writing YAML
   - writing task results to SQLite
   - emitting SSE events
   - logging (structured logs)
   - sending any content to LLMs (analyzer prompts)
   - storing any response headers in artifacts (Set-Cookie, Location must be redacted)
2a. **Query/body secret detector (required).**
    - Deterministic redaction for common key patterns: token, key, secret, auth, session, bearer, jwt, api_key, access_token, refresh_token
    - Entropy-based heuristic redaction for high-entropy values above a small length threshold (with allowlist escapes for known safe params)
    - Apply to URLs, JSON bodies, form bodies, and any "evidence windows" sent to LLMs.
    - Apply to response headers captured in recordings and artifacts:
      - Always redact Set-Cookie entirely
      - Redact Location query params using the same key+entropy rules
    - Detector thresholds (v1):
      - Key pattern match: case-insensitive regex against ~15 known key names (see list above)
      - Entropy threshold: Shannon entropy > 3.5 bits/char for values >= 16 chars
      - Allowlist: known safe high-entropy params (e.g., base64-encoded pagination cursors) configured per recipe
      - Action: replace value with [REDACTED:key_name] (preserves debuggability)
2b. **Task input secret guard (required).**
    - Apply the same detector to:
      - MCP tool inputs (task strings, params)
      - REST request bodies
    - Default behavior: if probable secret detected in `task`, refuse with error_code=SECRET_IN_TASK
      unless `server.allow_task_secrets=true` (explicit opt-in).
    - If opted in, task text stored/logged/artifacted MUST be redacted; original used only in-memory.
3. **SSRF protection on all direct execution.** Private IPs, loopback, link-local addresses blocked. DNS resolution checked for rebinding. Validated twice (before navigation AND before fetch).
3a. **Browser-wide egress policy (required).** Attach a Playwright route handler per context that blocks any request to:
    - non-http(s) schemes
    - loopback/link-local/private IP ranges (IPv4+IPv6), including numeric-IP hosts
    - forbidden "special" URLs (chrome://, about:, file://, view-source:)
   Default mode SHOULD be "lite" (fast checks); "strict" mode MAY resolve DNS for all requests with bounded caching.
3b. **Single EgressPolicy module (required).** Implement one shared `EgressPolicy` used by:
    - Playwright route handler (page subresources + navigation)
    - httpx_public transport
    - context_request transport (manual redirects + per-hop validation)
    - in_page_fetch transport (pre-validated URL; redirects disabled by default)
    Tests MUST prove every transport invokes the same validation logic and blocks the same forbidden targets.
3c. **DNS pinning + bounded cache (required).**
    - For each execution attempt, resolve host once and pin the allowed IP set for that request chain (including redirects).
    - Re-resolve on each retry attempt (prevents "wait out TTL then rebind").
    - Implement bounded LRU cache for DNS answers:
      - max_entries: 256
      - ttl_seconds: 5 (default)
      - negative caching: 2s
    - If any A/AAAA answer is private/link-local/loopback => block (unchanged).
4. **CDP restricted to localhost.** Remote CDP connections are rejected at config validation time.
4a. **Server-owned browser by default.** Default mode MUST launch a fresh Playwright-managed Chromium instance (no external CDP).
4a.1 **No exposed debug port by default.** Server MUST ensure the Playwright-launched browser is not listening on a non-loopback debug port; fail-fast if detected.
4a.2 **No extensions by default.** Playwright-launched Chromium MUST disable extensions and component extensions unless explicitly enabled in expert mode.
4a.3 **Pipe-first control.** Prefer pipe-based browser control where supported; treat any debug-port mode as expert-only with extra validation and warnings.
4a.4 **Launch-arg allowlist (required).** Chromium launch args MUST be generated from an allowlist; user-provided raw args are rejected by default.
4a.5 **Explicitly forbidden flags (required).** Reject (fail-fast) any configuration that would enable:
     - `--no-sandbox`
     - remote debugging bound to non-loopback
     - loading arbitrary extensions unless `browser.allow_extensions=true` (expert-mode)
4a.6 **Disable downloads + dangerous permissions by default (required).**
     - Downloads disabled by default; enabling requires explicit `browser.allow_downloads=true`
       and forces download dir under `~/.local/state/mcp-server-browser-use/downloads/` (0700).
     - Deny-by-default for permission prompts (geolocation, notifications, clipboard, midi, camera, microphone).
     - Block file chooser interactions unless explicitly enabled in expert mode.
4b. **External CDP is "expert mode".** Requires explicit flag + strong warnings + additional checks:
    - only loopback host
    - explicit port allowlist
    - disallow ws URLs unless explicitly supported and validated
    - require isolated user-data-dir unless explicitly overridden
    - require `browser.external_cdp_ack_risk=true` (explicit acknowledgement gate)
5. **Per-task isolation.** Each task executes in an isolated browser context by default (separate cookies/storage), unless explicitly configured otherwise.
5a. **Explicit sessions (required).** Any execution that depends on cookies/session MUST run against an explicit `session_id` managed by the server.
    - Default: every `run(...)` / `run_browser_agent(...)` creates an ephemeral session and returns `session_id` in `meta`.
    - TTL: sessions auto-expire after `server.session_ttl_minutes` (default 20) and are GC'd (contexts closed).
    - Direct recipe runs:
      - if `recipe.requires_session=false`: allowed without `session_id` (httpx_public).
      - if `recipe.requires_session=true`: MUST provide `session_id` OR use `strategy="agent"` to establish one.
5b. **Persistent profiles are expert-mode.** Optional named profiles (persistent user-data-dir) are allowed only with explicit enable + warnings.
    - Profiles live under `~/.config/mcp-server-browser-use/profiles/<name>/` (0700).
    - Never stored in artifacts; never shown in logs; never sent to LLMs.
6. **Constrained Runtime.evaluate.** Only allow a fixed set of internal JS snippets (no recipe-provided JS). Recipe fields may only influence data inputs (URL, selectors, extract paths) after validation.
6a. **LLM output is untrusted input.** Analyzer output MUST be treated like user input:
    - schema validated
    - safety validated (URLs/ports/headers/methods)
    - size bounded (token and bytes)
    - never allowed to disable guardrails (no "confidence overrides")

7. **Deterministic domain allowlists.** `allowed_domains` MUST be derived and canonicalized by the validator:
   - canonical host (punycode)
   - eTLD+1 (public suffix rules) stored separately as `allowed_sites` (future-proofing)
   - explicit subdomain expansion only when required (no wildcards in v1)

8. **Redirect policy is explicit.** Default: allow redirects only within the same canonical host; cross-host redirects require explicit validator approval (and are re-validated hop-by-hop).
8a. **Redirects are manual everywhere.** All transports MUST disable auto-follow and implement validated redirect loops:
    - cap redirect count
    - validate every Location (scheme/host/port) before the next request
    - block scheme changes (http<->https) unless explicitly allowed

9. **No `Any` types.** Full type annotations everywhere. Pyright enforced via pre-commit.

10. **Method + header allowlists.** v1 defaults:
    - Methods allowed by default: GET, POST
    - PUT/PATCH/DELETE require explicit config `recipes.allow_unsafe_methods=true` AND recipe.status=verified
    - Header allowlist enforced by validator; forbidden headers include Host, Connection, Transfer-Encoding, Content-Length, Proxy-*, Cookie, Authorization

11. **TLS + proxy hardening.**
    - Playwright contexts MUST NOT set ignore_https_errors unless explicit expert-mode flag is enabled.
    - Proxy configuration is disabled by default for direct execution; explicit opt-in required and logged as risk.

---

## 0.2 Invariants (Testable)

| Invariant | Test |
|-----------|------|
| Recipes never contain Authorization/Cookie headers | `test_recipes_security.py` |
| Recorder output never contains secrets (headers/query/body) | `test_recorder_redaction.py` |
| Analyzer prompts never contain secrets (headers/query/body) | `test_analyzer_redaction.py` |
| SSE payloads never contain secrets | `test_sse_redaction.py` |
| Verified recipes demote after N consecutive failures | `test_recipe_health.py::test_auto_demote` |
| AUTO strategy never uses direct path for unverified/demoted recipes | `test_recipe_health.py::test_auto_strategy_gating` |
| Direct execution blocks private IPs | `test_recipes_security.py::test_ssrf_*` |
| CDP URL must be localhost | `test_config.py::test_cdp_url_validation` |
| Response bodies capped at 1MB | `test_recipes.py::TestMaxResponseSize` |
| Task results truncated to 10KB in SQLite | `test_observability.py::TestTaskStore` |
| URL parameters are properly encoded | `test_e2e_recipe_learning.py::TestURLEncodingConsistency` |
| Artifact dirs are 0700 + files 0600 | `test_artifacts_security.py::test_permissions` |
| Artifact writes are atomic (no partial files) | `test_artifacts_security.py::test_atomic_write` |
| Recipe YAML writes are atomic and non-following | `test_recipe_store_security.py::test_atomic_write_no_symlink` |
| Artifacts never contain Set-Cookie or unredacted Location query tokens | `test_artifacts_redaction.py` |
| Analyzer evidence windows respect byte budgets post-redaction | `test_analyzer_budgets.py` |

---

## 0.3 Explicit Exclusions (and Why)

- **Multi-user / multi-tenant** — single-user tool, localhost only. Adding user isolation is a different product.
- **Remote browser pools** — cloud browsers are handled by browser-use's `use_cloud=True`. We don't manage pools.
- **Recipe marketplace / sharing** — future possibility. v1 is local YAML files only.
- **Stdio transport** — deprecated and blocked. The timeout math doesn't work.
- **Automated recipe verification scheduler** — manual verification via tests for v1.
- **GraphQL recipe support** — POST body template handles this implicitly, no special GraphQL mode needed.
- **ddmin (delta debugging) minimization** — single-pass header/query elimination is sufficient for v1 [Oracle R1].
- **Learned ranker (ML-based candidate scoring)** — no labeled data yet; deterministic heuristics first [Oracle R1].
- **Tier 2 transport (context_request)** — adds policy-parity complexity; start with httpx_public + in_page_fetch [Oracle R1].
- **Multi-run "verify with different params"** — requires domain knowledge and corpus; deferred until Phase 1.5 [Oracle R1].
- **Multi-example parameter diffs** — parameterization from single trace is sufficient for v1 conservative defaults [Oracle R1].

---

## 1. Current State (What's Built)

### 1.1 Server Core (Complete)

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| FastMCP server + MCP tools + REST API + SSE | `server.py` | 1825 | ✅ Working |
| Typer CLI (daemon, config, recipes, tasks) | `cli.py` | 771 | ✅ Working |
| Pydantic settings (env vars + config file) | `config.py` | 281 | ✅ Working |
| LLM provider factory (12 providers) | `providers.py` | 130 | ✅ Working |
| Task tracking (SQLite + SSE streaming) | `observability/` | 501 | ✅ Working |
| Deep research (multi-search state machine) | `research/` | 298 | ✅ Working |
| Structured logging (structlog + contextvars) | `observability/logging.py` | 92 | ✅ Working |

**Total production code**: ~7,000 lines
**Total test code**: ~4,300 lines (297 tests across 18 files)

### 1.2 Transport Architecture (Complete)

```
Connection Methods:

1. Native HTTP (preferred):
   Client ──HTTP──> http://localhost:8383/mcp

2. mcp-remote bridge (works with any client):
   Client ──stdio──> npx mcp-remote ──HTTP──> localhost:8383/mcp

3. Stdio proxy (backward compat):
   Client ──stdio──> mcp-server-browser-use ──HTTP──> localhost:8383/mcp
   (auto-starts server if not running)
```

**Daemon lifecycle**: `server` command spawns background process, writes PID to `~/.local/state/mcp-server-browser-use/server.json`. Managed via `start`/`stop`/`status`/`logs` commands.

### 1.3 Recipes System (Alpha, Active Development)

The recipes pipeline has 8 stages (with hard gating between each stage):

```
RECORD                NORMALIZE+RANK            ANALYZE+VALIDATE             BASELINE (new)                 MINIMIZE+PARAMETERIZE          VERIFY+PROMOTE                 EXECUTE

 Agent runs task       Recorder produces         LLM selects best             Replay recipe immediately      Two paths (AUTO):
 while CDP recorder    redacted, normalized      candidate + parameters       in same browser context       ┌─ Direct: fast path (verified)
 captures network      request/response set      + extract spec               and compares output           │
 traffic               + heuristic top_k list                                  to expected shape             ├─ Hint-based: browser-use fallback
                                                                                                            │
 recorder.py ──> signals.py ──> candidates.py ──> heuristic_analyzer.py ──> analyzer.py ──> validator.py ──> fingerprint.py ──> minimizer.py ──> verifier.py ──> store.py ──> runner.py/executor.py

SIGNALS (new, required for v1):
- Deterministically compute a compact per-request feature vector from the recording (no LLM).
- Emit a sanitized CandidateSummary that is safe to send to the LLM (no raw bodies by default).

Signal features per request (v1):
  - content_type_score: float (1.0=json, 0.7=html, 0.3=text, 0.0=binary/image)
  - status_bucket: str (2xx/3xx/4xx/5xx)
  - body_size_bucket: str (empty/<200B/200B-1KB/1KB-32KB/>32KB)
  - has_array_root: bool (top-level JSON is array or contains common list keys)
  - url_task_overlap: float (token overlap between URL+query and task description, normalized 0-1)
  - url_result_overlap: float (token overlap between URL+query and agent final answer)
  - body_task_overlap: float (token overlap between response body snippet [first 4KB] and task text; catches search APIs) [Oracle R1]
  - resource_type: str (xhr/fetch/document)
  - initiator_type: str (parser/script/preload/other)
  - has_initiator_stack: bool (CDP initiator stack present; often correlates with app API calls vs browser noise)
  - same_site_as_page: bool (request eTLD+1 == current page eTLD+1)
  - is_likely_telemetry: bool (URL matches common analytics/tracking patterns)
  - url_api_path_hint: bool (URL contains /api/, /graphql, /v[0-9]+/, /search, /query) [Oracle R1]
  - url_tracker_path_hint: bool (URL contains /collect, /pixel, /beacon, /telemetry, /events) [Oracle R1]
  - json_richness: float (number of keys / nesting depth bucket; penalizes trivial {success:true} responses) [Oracle R1]
  - has_cache_buster: bool (query params matching _t, ts, cb, cacheBust, nonce patterns; soft downrank) [Oracle R1]
  - latency_ms: int
  - near_final_step: bool (request timestamp within 5s of agent's last action)

CANDIDATES (new, required for v1):
- Takes signal feature vectors from SIGNALS stage and applies ranking heuristics (weighted sum, no ML).
- Produces top_k=8 ranked candidates with composite scores + per-feature breakdown.
- Pure functions only, no LLM calls, no network I/O.
- MUST de-duplicate by canonical endpoint key before selecting top_k:
  - endpoint_key = (method, canonical_host, canonical_path, sorted(query_param_names))
  - keep the single best-scoring exemplar per endpoint_key
  - ensures top_k covers diversity rather than repeats
- Output: CandidateSet artifact (02_candidate_set.json) containing ranked list of
  { request_id, rank, composite_score, feature_scores: dict[str, float], url_summary, method, content_type }.

HEURISTIC_ANALYZER (new, required for v1):
- If the top candidate score is "high confidence" (thresholded + explainable), produce a minimal RecipeDraft
  for simple JSON/GET endpoints without invoking the LLM.
- Otherwise, fall back to LLM analyzer using CandidateSummary (not raw recording).
- LLM receives ONLY top K candidates (not raw recording). Each candidate includes: URL, method, status,
  content-type, response size, and a short response snippet or JSON structural summary.
- LLM output MUST include `chosen_candidate_id` referencing the ranked list. [Oracle R1]

Heuristic confidence scoring:
  - Sum weighted signal features for top candidate (weights tunable, stored in config)
  - High confidence threshold: composite_score >= 0.85 AND top candidate score is >= 0.3 above second-best
  - Required for heuristic path: content_type_score >= 0.7 AND status_bucket == "2xx" AND body_size_bucket in ("200B-1KB", "1KB-32KB")
  - If threshold met: produce RecipeDraft directly (no LLM cost)
  - If not met: pass CandidateSummary to LLM analyzer

Extraction path relaxation (v1) [Oracle R1]:
  - extract_path is OPTIONAL for a recipe to be considered "successful" in v1.
  - "Endpoint correct + response_type parse succeeds" = valid draft recipe.
  - Recipes without extract_path return truncated raw JSON (clearly labeled).
  - Extraction is an enhancement step, not a gate for recipe creation.
  - This prevents the common failure mode of "correct API endpoint but bad JMESPath".

Extraction assist (v1) [Oracle R1]:
  - When extract_path is needed, programmatically compute candidate JMESPaths from the JSON structure
    (paths to arrays of objects, common key sets like results/data/items).
  - Present top N options to LLM and ask it to SELECT one (classification, not generation).
  - LLM may also return "none" if no candidate path matches the task intent.
  - This converts a generative error into a classification problem.

BASELINE (new, required for v1):
- Compute a `baseline_shape_fingerprint` from the selected candidate's CAPTURED response after applying the analyzer's extract spec.
- Store baseline fingerprint (and fingerprint_version) as:
  1) an artifact (portable, resumable)
  2) SQLite stats (mutable/operational)
  3) OPTIONAL: a read-only `verification:` block in recipe YAML (portable recipe metadata; no mutable counters).
- All subsequent replay/minimization/verification compares against this baseline, not against agent final text.

MINIMIZE+PARAMETERIZE (new, required for v1):
- Remove volatile/query noise (cache-busters, timestamps, tracking params) using deterministic rules + replay checks.
- Attempt request "minimization": drop headers/body fields one-by-one to find the minimal subset that preserves the expected shape.
- Convert detected dynamic fields into typed RecipeParameters (instead of baking values into the template).
- Output a stable RecipeDraft that is meaningfully replayable, not just "captured".

Minimization algorithm (v1) [simplified per Oracle R1 — ddmin deferred]:
  Phase A - Volatility detection (deterministic, no network):
    - Flag query params matching: _t, timestamp, ts, nonce, cache, cb, rand, _=*
    - Flag headers matching: X-Request-Id, X-Trace-*, If-None-Match, If-Modified-Since
    - Flag body fields with ISO timestamps or UUIDs

  Phase B - Header minimization (requires replay) [Oracle R1: single-pass, not ddmin]:
    - Start from an aggressively filtered header set (denylist: sec-fetch-*, sec-ch-ua*,
      accept-encoding, connection, host, and other browser noise headers).
    - Single-pass elimination: try removing each remaining header one at a time.
    - Keep the removal if: status remains 2xx AND fingerprint similarity >= threshold.
    - The "necessary" set is usually small (Accept, Content-Type, maybe X-Requested-With,
      sometimes CSRF headers). This gives most of the benefit at a fraction of ddmin complexity.
    - Cache replay outcomes by request_signature_sha256 to avoid duplicate calls.
    - Budget: max_attempts=24 total replays OR 30s wall-clock (whichever first).
    - Per-host pacing (default 250ms) during minimization to reduce 429s.
    - Note: ddmin can be added later as an optimization if single-pass proves insufficient.

  Phase C - Query param minimization (requires replay):
    - Same single-pass strategy + replay cache.
    - Budget: max_attempts=24 total replays OR 30s wall-clock (whichever first).
    - Per-host pacing (default 250ms) during minimization to reduce 429s.

  Phase D - Parameterization:
    - Detected dynamic values become typed RecipeParameters with explicit `source`.
      - task_input: provided by caller (safe default)
      - session: derived from cookies/session state (never caller-provided)
      - dom: requires DOM access (forces in_page_fetch unless verifier proves otherwise)
      - constant: baked in, non-templated
    - Parameter constraints enforced BEFORE substitution (CR/LF blocking, length caps, regex if present).
    - LLM-suggested parameter names are treated as untrusted: validator may rename to canonical safe identifiers.
```

### 1.3.1 Pipeline Artifacts (Deterministic + Resumable)

Each stage MUST emit a versioned artifact to disk so failures are reproducible and the pipeline can resume.
Artifacts are not "ad-hoc JSON": they MUST be schema-validated Pydantic models on write AND on read (resume).
Every artifact MUST include:
  - `artifact_version`
  - `schema_hash` (sha256 of canonicalized Pydantic JSON schema for the model)
  - `payload_sha256` (sha256 of the serialized payload)
Resume rules (v1):
  - If `schema_hash` mismatches current code, resume MUST stop with error_code=ARTIFACT_SCHEMA_MISMATCH (actionable).
  - Provide `mcp-server-browser-use artifacts migrate --task-id ...` for best-effort migrations when safe.

Artifact storage layout (v1, explicit):
- Root: `~/.config/mcp-server-browser-use/artifacts/`
- Per task: `~/.config/mcp-server-browser-use/artifacts/<task_id>/`
- Files are stage-named JSON with stable suffixes:
  - `01_session_recording.json`
  - `02_candidate_set.json`
  - `02a_candidate_summary.json`
  - `03_recipe_analysis.json`
  - `04_recipe_draft.json`
  - `05_baseline_fingerprint.json`
  - `06_minimization_report.json`
  - `07_recipe_draft_minimized.json`
  - `08_verification_report.json`

Permissions (v1, required):
- artifacts dir MUST be `0700`
- artifact files MUST be `0600`
- writes MUST be atomic (temp + fsync + rename)

Retention/GC (v1):
- Config: `artifacts.retention_days` (default 7)
- GC trigger: on server startup + daily timer (asyncio background task, 24h interval)
- GC algorithm: scan artifact dirs, delete where mtime > retention_days
- CLI: `mcp-server-browser-use artifacts prune [--days N]` (also prunes orphan task dirs with no matching SQLite record)
- CI harness MUST prune after tests to avoid disk growth
- GC MUST NOT delete artifacts for in-progress tasks (check SQLite status before deletion)

Artifacts (all redacted; never store secrets):
- `SessionRecording` (from recorder): normalized JSONL of network events + minimal page context
- `CandidateSet` (from ranker): top_k candidate request IDs with scores + feature breakdown
- `CandidateSummary` (from signals): compact, bounded, LLM-safe summaries per candidate (no raw bodies by default)
- `RecipeAnalysis` (from analyzer): strict JSON output from LLM (schema-validated)
- `RecipeDraft` (from validator): safe, canonical recipe ready for replay
- `BaselineFingerprint` (from fingerprint): baseline_shape_fingerprint + fingerprint_version for the selected candidate
- `MinimizationReport` (from minimizer): dropped fields + volatility flags + "minimal sufficient" proof
- `RecipeDraftMinimized` (from minimizer): minimized, parameterized recipe ready for verification replay
- `VerificationReport` (from verifier): replay results + extracted shape fingerprint + promotion decision

All artifacts include:
- `artifact_version`
- `task_id`
- `source_url` (public only, redacted)
- `created_at`
- `sha256` of the artifact payload (integrity + dedupe)

Analyzer input budgets (v1, required):
- The analyzer MUST only receive CandidateSummary + a bounded "evidence window" (small snippets) when explicitly needed.
- Hard caps:
  - max candidates to LLM: 8
  - max bytes per candidate summary: 4KB
  - max total analyzer prompt bytes: 32KB (post-redaction)
- Analyzer results SHOULD be cached by sha256(task + candidate_summary + prompt_version) to avoid repeat spend and reduce variance.

CLI support (v1 requirement):
- `mcp-server-browser-use recipe learn --resume-from <stage>`
- `mcp-server-browser-use recipe debug --task-id <id>` (opens artifacts + prints stage diffs)

| Component | Status | Notes |
|-----------|--------|-------|
| CDP network recorder | ✅ Working | Captures XHR/Fetch + JSON documents |
| Candidate ranker (heuristic) | ❌ Not started | MUST deliver top_k=8 with feature scores; optimized for simple GET APIs |
| LLM recipe analyzer | ⚠️ Partial | Works for complex APIs (Algolia), struggles with simple GETs |
| Recipe validator (schema+safety) | ❌ Not started | Rejects unsafe schemes/ports/redirects, enforces parameter typing, sets allowed_domains deterministically |
| YAML recipe store | ✅ Working | CRUD + usage tracking |
| Direct execution (CDP fetch) | ✅ Working | SSRF protection, 1MB cap, domain allowlist |
| HTML extraction (CSS selectors) | ✅ Working | @attr suffix support, selector validation |
| Hint-based fallback | ✅ Working | Injects navigation hints into agent prompt |
| Recipe manifest (batch learning) | ✅ Schema done | Used for E2E tests, not yet for batch pipeline |
| Batch learning pipeline | ❌ Not started | Need resume capability, rate limiting |
| Recipe verification | ❌ Not started | Replay-based verification + promotion (draft → verified) to prevent junk recipes |

Verification spec (v1) [updated per Oracle R1]:
- Compute `shape_fingerprint` on extracted output (see Shape fingerprint algorithm below):
  - for JSON: typed JSON path sets up to depth 6 + Jaccard comparison >= 0.85 [Oracle R1]
  - for HTML: selector hit counts + extracted field presence map
- Store baseline fingerprint + fingerprint_version in SQLite stats table (not in YAML)
- Validation-before-save (closed-loop) [Oracle R1]:
  - After LLM/heuristic outputs a recipe draft, execute it in the SAME browser context immediately.
  - Require: 2xx response + response_type parse success.
  - extract_path match is optional for v1 (see Extraction path relaxation above).
  - If validation fails: try next-best candidate OR ask LLM a second pass with failure reasons.
  - Only save recipe to store if validation passes at least once.
- Promotion rule (v1):
  - If recipe has zero parameters: 2 consecutive successful replays that match the baseline fingerprint + no auth recovery triggered.
  - If recipe has >=1 parameters: MUST pass fingerprint match on >=2 DISTINCT parameter sets:
    - Set A: original task/example params (from recording/manifest)
    - Set B: second example params (manifest/corpus) OR interactive user-provided params
    - If no Set B exists, recipe stays `draft` and returns error_code=NEEDS_SECOND_EXAMPLE_FOR_VERIFY.
- Demotion rule: existing rule (5 consecutive failures) + any "shape drift" (fingerprint mismatch) demotes immediately

Shape fingerprint algorithm (v1) [updated per Oracle R1]:
  Input: extracted JSON/HTML output from recipe execution

  For JSON:
    1. Walk JSON tree up to depth 6 (increased from 3 per Oracle R1; captures nested API structures)
    2. Collect typed JSON paths: "$.results[]:list", "$.results[].title:str", "$.meta.page:int"
    3. For arrays: normalize by sampling first 3 elements (union shapes, avoid O(n))
    4. Store: path_set = set of all typed paths
    5. Fingerprint = sha256(sorted(path_set) joined by newline)
    6. Optionally store the actual path_set (truncated) for debugging

  Comparison [Oracle R1]:
    - Use Jaccard similarity over path sets; require >= 0.85 to "match" baseline.
    - This is more robust than exact sha256 equality: tolerant of minor API changes
      (e.g., new optional fields) while detecting structural drift.
    - If baseline includes list paths that are empty in current result (empty query),
      allow a lower Jaccard threshold (configurable).

  For HTML:
    1. For each selector: record (selector, match_count_bucket, has_text: bool)
    2. Sort by selector name
    3. Fingerprint = sha256(canonical JSON of sorted selector results)
    4. Optionally store DOM host + path of target page for debugging

  fingerprint_version = 1 (bumped when algorithm changes; old fingerprints invalidated)

Transport inference (new, verifier responsibility) [updated per Oracle R1]:
- v1 starts with 2 tiers only [Oracle R1: defer context_request]:
  1) httpx_public (no browser/session) — cheap verification probe: "does this work publicly?"
  2) in_page_fetch (DOM/CSRF/sessionStorage parity) — solves hardest class (CSRF/session-bound)
- Tier 2 (context_request) deferred: adds policy-parity surface area (headers, redirects, cookie jars,
  SSRF enforcement consistency) that isn't worth the complexity until Tier 1 + 3 are proven.
  The "cookie needed but no DOM context needed" sweet spot is acceptable to miss early.
- Verifier MUST try transports in ascending risk order.
- First transport that matches baseline fingerprint becomes `transport_hint`.
- If no transport matches, recipe stays draft and returns an interactive CandidateSet instead of writing YAML.
- Verification MUST run on both parameter sets (if required) before locking `transport_hint`.

### 1.4 Recipe Learning Results (2026-01-09 Testing)

| Recipe | Source | Learning | Direct Exec |
|--------|--------|----------|-------------|
| remoteok-job-search | Auto-learned | ✅ 139.6s | ⚠️ 97.8s (slow) |
| hackernews-search | Manual | N/A | ✅ 24.6s |
| coingecko-btc-price | Manual | N/A | ✅ 21.1s |
| npm-package-search | Manual | N/A | ✅ 8.3s |
| pypi-package-info | Manual | N/A | ✅ 6.8s |

**Auto-learning success rate: 20%** (1 of 5 attempts). The analyzer handles complex POST APIs well (Algolia) but struggles with simple GET APIs. Prompt engineering needed.

### 1.5 Test Coverage

| Test Area | File | Tests | Status |
|-----------|------|-------|--------|
| Task tracking | `test_observability.py` | 20+ | ✅ Passing |
| Recipe models + runner | `test_recipes.py` | 40+ | ✅ Passing |
| Recipe security (SSRF) | `test_recipes_security.py` | 15+ | ✅ Passing |
| Dashboard REST API | `test_dashboard_api.py` | 30+ | ⚠️ Some 404s |
| MCP tools protocol | `test_mcp_tools.py` | 15+ | ⚠️ Tool count mismatch |
| E2E recipe learning | `test_e2e_recipe_learning.py` | 10 pass, 3 skip | ✅ Passing (10/13) |
| Integration tasks | `integration_tests/` | 20+ | ✅ Passing |

### 1.6 Testing Strategy Additions (Needed for v1.0 reliability)

- Deterministic local test server for recipes:
  - redirects (incl. private IP redirect attempts)
  - large bodies + chunked encoding + slow responses
  - auth flows (401/403) and rate limits (429 + Retry-After)
  - compressed responses (gzip/br) + decompression bomb simulation
  - deep JSON payloads + pathological-but-valid JSON structures
- Add "malicious web" scenarios:
  - IDN/punycode hostnames that look like allowlisted domains
  - credential-in-URL attempts
  - `Location:` redirects to `file://` and `chrome://` (must be blocked)
  - DNS rebinding simulation hooks (where possible)
  - localhost CSRF attempts (cross-origin POST/DELETE that should be rejected)
- Property-based/fuzz tests for URL parsing + template substitution (SSRF bypass defense-in-depth)
- Transport parity suite (new, required):
  - run identical hostile-server scenarios through httpx_public, context_request, in_page_fetch
  - assert: URL validation decisions, redirect handling, decompression caps, and error_codes match
  - ensures "one transport" cannot silently weaken the security model
- Golden fixtures for recorder output and analyzer structured JSON output (prevents prompt/schema regressions)
- Golden fixtures for pipeline artifacts (SessionRecording/CandidateSet/RecipeDraft/MinimizationReport/VerificationReport)
  - Include permission and atomic-write assertions as part of the golden suite where possible.
- Chaos tests for cancellation + cleanup:
  - start N tasks, cancel mid-flight, assert browser contexts closed and `_running_tasks` empty
  - repeat in a loop to catch leaks (CI-safe bounds)
- MCP tool contract tests:
  - tool names + JSONSchema signatures are pinned
  - stable error envelope (code, message, retryable, stage, task_id)
  - explicit deprecation policy for tool changes

Testing suites (new, required for v1):
1) Hostile Web Harness (integration):
   - local deterministic server scenarios (redirect/SSRF/decompression/depth/rate-limit)
   - validates runner + agent navigation share the same URL safety gate
2) Pipeline Golden Suite (unit-ish):
   - frozen JSON fixtures for each artifact stage
   - asserts stable fingerprint_version behavior and stable validator output
3) Fuzz/Property Suite (unit):
   - Hypothesis tests for URL canonicalization, IDN/punycode equivalence, IP encoding edge cases, template substitution, header CRLF blocking
   - bounded runtime suitable for CI
4) Secret Detector Suite (unit/property):
   - property tests for entropy/key-pattern detector across URL/query/json/form
   - regression fixtures for known-safe high-entropy params (pagination cursors)
   - tests for SECRET_IN_TASK default refusal
5) Browser Hardening Suite (integration, CI-safe):
   - downloads disabled (attempted download yields deterministic error_code=DOWNLOAD_BLOCKED)
   - permission prompts denied
   - file chooser blocked by default

---

## 2. Architecture Deep Dive

### 2.1 Server Execution Model

```python
# server.py: How a tool call flows through the system

@mcp.tool()
async def run_browser_agent(task: str, ..., recipe_name: str | None = None,
                            learn: bool = False, save_recipe_as: str | None = None,
                            session_id: str | None = None):
    # 1. Create task record in SQLite
    task_record = TaskRecord(task_id=uuid4(), tool_name="run_browser_agent", ...)
    await task_store.create_task(task_record)

    # 2. Acquire session (explicit) or create ephemeral
    session = await session_manager.get_or_create(session_id=session_id)

    # 3. Try recipe fast path (if recipe_name provided)
    if recipe_name and recipe_store:
        recipe = recipe_store.load(recipe_name)
        if recipe and recipe.supports_direct_execution:
            result = await RecipeRunner().run(recipe, params, session)
            if result.success:
                return result.data  # fast path, done!

    # 4. Fall back to browser-use agent
    agent = Agent(task=task, llm=llm, browser=session.browser, ...)

    # 5. If learning mode, attach CDP recorder
    if learn:
        recorder = RecipeRecorder()
        await recorder.attach(browser_session)

    # 6. Run agent (60-120s)
    result = await agent.run(max_steps=max_steps)

    # 7. If learning, analyze recording and save recipe
    if learn and recorder:
        recording = recorder.get_recording(result)
        recipe = await RecipeAnalyzer(llm).analyze(recording)
        if recipe:
            recipe_store.save(recipe)

    return {"ok": True, "data": result, "meta": {"task_id": task_record.task_id, "session_id": session.id}}
```

### 2.1.1 Concurrency + Resource Budgets (v1)

- Global limits:
  - max concurrent browser-agent tasks (default 1)
  - max concurrent direct recipe runs (default 4)
  - per-host concurrent direct runs (default 2 per canonical host)
  - per-host token bucket (default 20/min burst 5) for direct exec to reduce 429s
  - max queued tasks (default 50; reject beyond with stable error_code=QUEUE_FULL)
  - max SSE connections (default 5; reject beyond with 429)
  - max HTTP request body size (default 256KB; reject beyond with 413)
- Per-task limits:
  - hard timeout for direct exec (default 15s)
  - hard timeout for agent run (configurable; default aligns with client expectations)
  - retry budget for direct exec: max_attempts=2 for retryable errors (429/5xx/network timeout)
    - backoff: exponential base 1s, max 8s, with +/-25% jitter
    - if Retry-After header present: use it (bounded to max 60s, reject if > 60s)
    - retry MUST re-validate URL (prevents DNS rebinding between attempts)
    - retries MUST consume per-host budget (prevents retry storms on a single host)
- Cancellation:
  - `task_cancel` MUST cancel underlying asyncio task AND close browser context
  - `_running_tasks` MUST be cleaned up on completion/cancel (TODO-006 becomes a hard gate)

### 2.2 Recipe Direct Execution (The Fast Path)

```python
# runner.py: How a recipe executes fast (target p50 < 3s) without mandatory page navigation

async def run(recipe, params, browser_session):
    # v1 perf requirement: compile once into a RecipeIR and reuse via LRU cache
    # RecipeIR includes: parsed+validated URL template, compiled JMESPath, compiled CSS selectors, normalized header allowlist,
    # and precomputed allowed_domains canonical forms.
    #
    # @dataclass(frozen=True)
    # class RecipeIR:
    #     """Compiled, immutable recipe for fast execution."""
    #     url_template: ParsedURLTemplate     # pre-parsed segments + param slots
    #     jmespath_expr: jmespath.Expression | None  # pre-compiled JMESPath
    #     css_selectors: dict[str, CompiledSelector]  # field -> parsed selector + attr
    #     header_allowlist: frozenset[str]     # normalized lowercase header names
    #     allowed_domains_canonical: frozenset[str]  # punycode, lowercase
    #     response_type: Literal["json", "html", "text"]
    #     method: str
    #     body_template: dict | None
    #     source_sha256: str                   # hash of source YAML for invalidation
    #     compiled_at: float                   # time.monotonic() for staleness check
    #
    compiled = recipe_cache.get_or_compile_ir(recipe)  # RecipeIR (LRU, metrics: hit_rate, compile_ms)
    # v1 reliability requirement:
    # - Invalidate compiled IR when underlying YAML changes (sha256 or mtime+size).
    # - Expose cache stats + invalidation events in observability.
    url = compiled.build_url(params)                # Template substitution

    await validate_url_safe(url)                    # SSRF check + DNS rebinding
    await validate_domain_allowed(url, recipe.request.allowed_domains)

    # Transport priority (v1):
    # 1) Playwright context.request (fastest, controllable, shares cookies)
    # 2) In-page fetch (only if required: CSRF token in DOM, strict CORS behavior, sessionStorage dependence)
    transport = self._select_transport(recipe, session)  # "httpx_public" | "context_request" | "in_page_fetch"
    # Transport selection at runtime:
    #   1. If recipe has transport_hint (set by verifier): use it directly
    #   2. If recipe.request.requires_session is False: use httpx_public
    #   3. If recipe.request.requires_session is True:
    #      a. If recipe needs DOM/CSRF/sessionStorage: use in_page_fetch
    #      b. Otherwise: use context_request (default for session-dependent)
    #   4. Fallback on transport failure: try next tier up (httpx -> context_request -> in_page_fetch)
    #      but do NOT retry across more than one fallback tier per execution

    if compiled.response_type == "html" and compiled.html_selectors:
        # HTML mode (v1): fetch HTML via context.request, parse selectors in Python with a fast parser.
        # Navigation is fallback-only for JS-rendered pages.
        html = await self._request_text(transport, url, compiled, browser_session)
        extracted = compiled.extract_html(html)  # REQUIRED: selectolax (or equivalent) for speed + robustness
    else:
        # JSON mode:
        # (1) context_request: no navigation, fastest path
        # (2) in_page_fetch: only if site requires in-page execution
        result = await self._execute_json_request(transport, url, compiled, browser_session)

Transport caps MUST be uniform (v1, required):
- MAX_RESPONSE_SIZE applies after decompression for ALL transports (httpx_public, context_request, in_page_fetch).
- MAX_HEADER_BYTES and MAX_REDIRECTS apply for ALL transports.
- JSON parsing SHOULD use orjson with explicit depth limits + safe fallbacks.
- in_page_fetch MUST default to `redirect: "error"` semantics (treat any redirect as failure) unless recipe explicitly opts in and verifier proves safety hop-by-hop.

Transport implementation requirements (v1, required):
- httpx_public MUST use a process-global pooled `httpx.AsyncClient` with:
  - keep-alive enabled
  - HTTP/2 enabled when available
  - strict connect/read timeouts (configurable)
  - proxy env vars ignored by default
- context_request MUST reuse a per-session `APIRequestContext` where possible (avoid recreating per call).
- warmup:
  - `mcp-server-browser-use recipes warmup` precompiles verified recipes and primes transport objects
  - warmup reports cache stats and per-recipe compile_ms

    return RecipeRunResult(success=True, data=extracted_data)
```

### 2.3 Config Hierarchy

```
Environment Variables (highest priority)
    MCP_LLM_PROVIDER=openrouter
    MCP_LLM_MODEL_NAME=moonshotai/kimi-k2.5
    MCP_BROWSER_HEADLESS=true
    MCP_SERVER_PORT=8383
    MCP_RECIPES_ENABLED=true
         │
         ▼
Config File (~/.config/mcp-server-browser-use/config.json)
    {"llm": {"provider": "openrouter"}, "browser": {"headless": true}, ...}
         │
         ▼
Pydantic Defaults (lowest priority)
    provider: openrouter, model: moonshotai/kimi-k2.5, port: 8383
```

### 2.4 Module Dependency Graph

```
server.py ─────────────────────────────────────────────────────────┐
    │                                                               │
    ├── config.py (settings singleton)                              │
    ├── providers.py (LLM factory)                                  │
    ├── observability/ (task tracking)                              │
    │     ├── models.py (TaskRecord, TaskStatus, TaskStage)         │
    │     ├── store.py (SQLite persistence)                         │
    │     └── logging.py (structlog + contextvars)                  │
    ├── recipes/ (API shortcut learning)                            │
    │     ├── models.py (Recipe, RecipeRequest, SessionRecording)   │
    │     ├── store.py (YAML persistence)                           │
    │     ├── recorder.py (CDP network capture)                     │
    │     ├── analyzer.py (LLM recipe extraction)                   │
    │     ├── runner.py (direct CDP fetch execution)                │
    │     ├── executor.py (hint injection for fallback)             │
    │     ├── manifest.py (batch learning schema)                   │
    │     └── prompts.py (LLM prompts)                              │
    └── research/ (deep research)                                   │
          ├── models.py (ResearchSource, SearchResult)              │
          ├── machine.py (multi-search state machine)               │
          └── prompts.py (planning + synthesis)                     │
                                                                    │
cli.py ─── server.py (imports serve())                              │
    └── All modules above (for CLI commands)                        │
```

---

## 3. ADRs (Architectural Decision Records)

### ADR-1: HTTP Transport Only

#### Problem
Browser automation tasks take 60-120 seconds. MCP stdio transport has a 2-minute timeout in most clients. Tasks were being killed mid-execution.

#### Options
A) Keep stdio, increase timeout — Requires client-side changes, not portable
B) HTTP transport with daemon — Server runs persistently, clients connect/disconnect freely
C) WebSocket — More complex, not supported by FastMCP

#### Decision
HTTP transport with daemon mode. Stdio blocked with migration message.

#### Consequences
- Server must be started separately (`mcp-server-browser-use server`)
- Backward compat via stdio-to-HTTP proxy (auto-starts server)
- mcp-remote bridge needed for clients that only support stdio
- Progress streaming via SSE endpoints

#### Tests
- `test_mcp_tools.py` validates tool registration works over FastMCP client
- Stdio mode shows migration message and exits

### ADR-2: Recipes as YAML Files

#### Problem
Learned API shortcuts need to be persisted, human-readable, and portable.

#### Options
A) SQLite — Structured queries, but not human-editable
B) YAML files — Human-readable, git-friendly, editable
C) JSON files — Less readable than YAML

#### Decision
YAML files in `~/.config/browser-recipes/`. One file per recipe.

#### Consequences
- Easy to inspect, edit, share, version control
- Recipe definitions stay in YAML (portable), but mutable stats move to SQLite (concurrent-safe)
- YAML becomes atomic-write-only (temp file + fsync + rename), eliminating partial writes

#### Tests
- `test_recipes.py::TestRecipeStore` validates CRUD operations

### ADR-3: CDP Fetch for Direct Execution

#### Problem
Re-running the full browser-use agent (60s) for a known API call is wasteful.

#### Options
A) Python `httpx` — Fast, but loses browser cookies/session state
B) CDP `fetch()` — Runs in browser context, inherits cookies, no CORS issues
C) Playwright `request` context — Shares some state, but not full page context

#### Decision (revised)
Direct execution uses a 3-tier transport strategy (explicitly modeled per recipe):
1) `httpx_public` (new): sessionless, safest default for public APIs (no browser cookies; easiest to harden + benchmark).
2) `context_request` (default when session is required): Playwright `context.request` for cookie/session dependent APIs.
3) `in_page_fetch` (fallback-only): CDP in-page `fetch()` only when recipe requires page context (DOM/CSRF/sessionStorage/CORS parity).

Recipes MUST declare (or verifier MUST infer) `requires_session` and `transport_hint`. AUTO uses the lowest-risk transport that passes verification.

#### Consequences
- 30x faster than agent path (a few seconds vs ~60s, site-dependent)
- Multi-transport strategy: context_request (no navigation, fastest) or in_page_fetch (when site requires it)
- SSRF protection required (browser can reach internal network)
- DNS rebinding protection required (TOCTOU between validation and fetch)

#### Tests
- `test_recipes.py::TestRecipeRunner` validates CDP execution
- `test_recipes_security.py` validates SSRF + DNS rebinding protection

### ADR-4: LLM-Based Recipe Analysis

#### Problem
Given a recording of network traffic, identify which API call returns the desired data.

#### Options
A) Heuristic rules — Match URL patterns, response sizes
B) LLM analysis — Understand task context, identify "money request"
C) Interactive selection — Present top_k sanitized calls, let client choose (human or LLM)

#### Decision
LLM analysis with structured JSON output. The analyzer receives the task description, agent result, and captured API calls, then identifies the optimal recipe structure.

Fallback (v1 requirement):
If analyzer output fails schema/validator OR confidence is low, return `CandidateSet` (top_k=8) to client via:
- MCP tool response field `learn_candidates`
- REST endpoint `GET /api/learn/{task_id}/candidates`
Client can then call `recipe_create_from_candidate(candidate_id, ...)`.

#### Consequences
- Works for complex multi-step APIs (e.g., Algolia POST with body template)
- Struggles with simple GET APIs (20% auto-learning success rate)
- Depends on LLM quality (currently using moonshotai/kimi-k2.5 via OpenRouter)
- Prompt engineering needed to improve success rate (see Phase 1)
- [Oracle R1] LLM now receives only top K candidates (not raw recording), reducing noise dramatically
- [Oracle R1] Validation-before-save prevents broken recipes from entering store
- [Oracle R1] extract_path optional for v1 success, increasing viable recipe count

#### Tests
- `test_e2e_recipe_learning.py` validates end-to-end learning flow

### ADR-5: Recipe Architecture Oracle Review (v2.9) [Oracle R1]

#### Problem
Auto-learning success rate is 20%. The system captures all network traffic (20-50 requests per page)
but the LLM often picks the wrong request, generates incorrect JMESPaths, and misidentifies parameters.
No verification before save means broken recipes pollute the store.

#### Options
A) Prompt engineering only — improve LLM prompts to better identify "money requests"
B) Heuristic pre-filtering + LLM — deterministically reduce candidates, then LLM chooses among top K
C) Full ML pipeline — trained ranker + learned extraction

#### Decision
We choose B: deterministic candidate ranking + compressed LLM input + closed-loop validation.
Specifically (in priority order):
1. Signal-based candidate ranking reduces noise before LLM sees anything
2. LLM chooses among top K candidates (classification, not fishing in noise)
3. Validate-before-save with retry on next candidate or second LLM pass
4. extract_path is optional for v1 success (endpoint correct + parse correct = working recipe)
5. JMESPath extraction assist: LLM selects from programmatic candidates, not invents

#### Consequences
- Candidate filtering eliminates most false positives (wrong request chosen)
- Validation-before-save prevents broken recipes from entering the store
- Relaxing extract_path requirement increases success rate significantly
- Learning mode becomes slower (validation + retry), acceptable for expensive path
- Learned ranker and ddmin minimization deferred until corpus provides training data
- Transport discipline tightened: prefer `context_request` for session-bound APIs that do not require DOM/page JS; reserve `in_page_fetch` for DOM/CSRF/sessionStorage/CORS parity only.

#### Tests
- `test_candidates.py` validates deterministic ranking with golden fixtures
- `test_fingerprint.py` validates typed JSON path sets + Jaccard similarity
- `test_validator.py` validates closed-loop validation + retry behavior
- `test_extraction_assist.py` validates programmatic JMESPath candidate generation

#### Source
Oracle: GPT-5.2 Pro (heavy thinking), `.apr/rounds/recipe-architecture/round_1.md`

### ADR-6: v1 Recipe Shipping Strategy (EV-Weighted) (v3.0)

#### Problem
We need v1 recipes to reliably deliver seconds-fast repeats without:
1) polluting the recipe store with broken drafts, or
2) shipping a localhost SSRF cannon via policy drift across transports.

Signal: auto-learning success rate is ~20% (small N). Failures cluster around candidate selection + schema discipline (noise), not fundamental impossibility.

#### Options
A) Full pipeline early (Signals -> Candidates -> LLM -> Validator -> Baseline -> Minimize -> Verify -> Promote)
B) Interactive-first (always return top-K CandidateSet, user/LLM chooses, then validate+save)
C) Library-first (curated verified recipes + manual authoring tools, auto-learn later)
E) Lean hybrid floor (recommended): Signals+Candidates + validation-before-save + interactive fallback for low-confidence or failed validation, then iterate up

#### Decision
We choose E (lean hybrid floor) as the v1 product promise.

Learning outcome is tri-state (explicit, no ambiguity):
- `saved_draft`: validated once, written as draft
- `needs_selection`: return CandidateSet (top K) for interactive selection, no write
- `non_recipeable`: explicit reason, fall back to agent

Correctness gate:
- Validation-before-save is the only hard gate for learning. Minimization/promotion/multi-example diffs are quality iteration, not correctness.

Transport strategy:
- Use the 3-tier design from ADR-3, enforced by parity tests, and always select lowest-risk first:
  - `httpx_public` -> `context_request` -> `in_page_fetch` (fallback-only)

#### Probability-Weighted Decision Tree (6 month horizon, relative utility)
Definitions:
- “recipe-able task”: stable API shortcut exists; session/cookies handled safely.
- Utility is relative (0-100) and only used for comparing strategies under uncertainty.

| Strategy | Outcome | Prob | Value | Cost | Net |
|----------|---------|------|-------|------|-----|
| E (lean hybrid) | High (>=70% validated drafts on recipe-able) | 0.60 | 90 | 40 | 50 |
| E (lean hybrid) | Medium (40-70%) | 0.30 | 70 | 40 | 30 |
| E (lean hybrid) | Low (<40%) | 0.10 | 50 | 40 | 10 |
| A (full pipeline) | High (>=60% auto-learn, stable store) | 0.55 | 100 | 55 | 45 |
| A (full pipeline) | Medium (30-60%) | 0.30 | 70 | 55 | 15 |
| A (full pipeline) | Low (~20-30%) | 0.15 | 40 | 55 | -15 |
| B (interactive-first) | Accepted by users | 0.60 | 80 | 35 | 45 |
| B (interactive-first) | Friction too high | 0.40 | 50 | 35 | 15 |
| C (library-first) | Coverage good | 0.40 | 75 | 40 | 35 |
| C (library-first) | Coverage poor | 0.60 | 45 | 40 | 5 |

Expected net utility:
- EV(E) = 40
- EV(B) = 33
- EV(A) = 27
- EV(C) = 17

#### Scenario Optimization
- Personal/power users: E or B, optimize for correctness + speed, tolerate some interaction during learning.
- Broad OSS users: E plus verified starter library, reduce “learning failed” UX until credibility exists.
- Sensitive accounts/shared networks: E, but ship auth defaults + parity tests before expanding scope.

#### Consequences
- Store hygiene is guaranteed: drafts only exist if they worked at least once.
- Escape hatch is bounded: low-confidence returns CandidateSet or non-recipeable, no silent “LLM failed”.
- Pipeline stays shippable: correctness gate first, optimizations later.

#### Tests
- `test_validator.py`: validation-before-save + tri-state learn outcome + “no write unless validated”
- `test_transport_parity.py`: same hostile scenarios across `httpx_public`, `context_request`, `in_page_fetch`

---

## 4. Threat Model

### Failure Modes

| Threat | Impact | Guardrail | Test |
|--------|--------|-----------|------|
| SSRF via recipe URL | Internal network access | `validate_url_safe()` blocks private IPs + DNS rebinding | `test_recipes_security.py` |
| SSRF via redirects | Internal network access via 30x chains | Re-validate every redirect hop; cap redirect count; block scheme changes | `test_recipes_security.py::test_ssrf_redirect_*` |
| SSRF via IPv6/encoded IP | Private net access via parsing ambiguity | Normalize/parse host strictly; block IPv6 private ranges; reject non-canonical IP encodings | `test_recipes_security.py::test_ssrf_ip_parsing_*` |
| SSRF via IPv4-mapped IPv6 | Private net access via ::ffff:127.0.0.1 style hosts | Treat IPv4-mapped IPv6 as IPv4 and block private/loopback | `test_recipes_security.py::test_ssrf_ipv4_mapped_ipv6` |
| SSRF via relative Location redirects | Bypass hop validation by resolving against a different base | Resolve Location relative to current URL, then validate | `test_recipes_security.py::test_redirect_relative_location` |
| SSRF via whitespace/control chars in URL | Parser differential across transports | Reject any URL containing ASCII control chars or spaces post-normalization | `test_recipes_security.py::test_url_control_chars_blocked` |
| SSRF via non-http(s) schemes | Local file / browser weirdness | Reject `file:`, `data:`, `blob:`, `ftp:`; allow only `http`/`https` | `test_recipes_security.py::test_scheme_allowlist` |
| SSRF via proxy env vars | Internal egress via HTTP_PROXY/HTTPS_PROXY | Ignore proxy env vars by default for all outbound in direct exec; explicit opt-in only | `test_recipes_security.py::test_proxy_env_ignored` |
| SSRF via websocket schemes | Internal access via ws/wss | Explicitly reject ws/wss in URL validator | `test_recipes_security.py::test_scheme_allowlist` |
| Browser special URLs | Local data exfil / privileged pages | Block `chrome://`, `about:`, `view-source:` navigation + fetch targets | `test_security_agent_navigation.py::test_block_special_urls` |
| Credentials in URL | Secret leakage + weird parsing | Reject `user:pass@host` in validator | `test_recipes_security.py::test_reject_userinfo_in_url` |
| IDN / punycode confusion | Allowlist bypass | Validator canonicalizes punycode; compare canonical host only | `test_recipes_security.py::test_idn_canonicalization` |
| Recipe store symlink attack | Write outside recipes dir | Atomic write + `O_NOFOLLOW` (where supported) + path canonicalization | `test_recipe_store_security.py` |
| SSRF via agent navigation | Internal network reachability through full browser automation | Apply the same URL safety checks to navigation targets (not only recipe runner) | `test_security_agent_navigation.py` |
| SSRF via subresource requests (img/script/fetch) | Internal side effects / scanning via hostile pages | Playwright route-level network policy on ALL requests in the context | `test_security_browser_network_policy.py` |
| Credential leakage in YAML | API keys exposed in recipe files | `strip_sensitive_headers()` removes Auth/Cookie headers | `test_recipes_security.py` |
| Remote CDP connection | RCE via remote browser control | Config validator rejects non-localhost CDP URLs | `test_config.py` |
| Hostile local CDP browser | Data exfil / unexpected extensions | External CDP requires explicit enable + isolated profile recommendation | `test_config.py::test_external_cdp_requires_explicit_enable` |
| Extension-based exfiltration | Credential/session theft via loaded extensions | Launch args disable extensions by default; external CDP requires explicit "allow_extensions=true" | `test_browser_launch_security.py` |
| Accidental remote-debug port exposure | Remote control of browser | Detect debug port binding; fail-fast unless expert mode | `test_browser_launch_security.py::test_debug_port_not_exposed` |
| Cross-task session bleed | Data leak across tasks | Default isolated browser contexts; explicit opt-in shared profile | `test_isolation.py` |
| Unbounded response body | OOM from large API responses | `MAX_RESPONSE_SIZE = 1MB` enforced in JS fetch | `test_recipes.py::TestMaxResponseSize` |
| SQL injection in task queries | Data exfiltration | Parameterized queries + whitelisted update clauses | `test_observability.py` |
| Recipe URL template injection | SSRF via crafted parameters | URL re-validated after parameter substitution | `test_recipes_security.py` |
| DNS rebinding (TOCTOU) | SSRF bypass | URL validated twice: before nav AND before fetch | `runner.py:_execute_fetch()` |
| Localhost CSRF (drive-by POST/DELETE to server) | Attacker triggers browser tasks / outbound fetches | Require auth for all state-changing endpoints by default; strict Origin/Host checks for dashboard; CORS disabled | `test_http_auth.py::test_write_endpoints_require_token` |
| Credential leakage via secrets in task input | Secrets sent to LLM provider or logs | SECRET_IN_TASK default refusal + redaction | `test_secret_in_task.py` |
| Dashboard XSS via task result rendering | Token theft / arbitrary requests from localhost origin | Strict escaping, never render raw HTML; CSP + security headers; truncate + encode output | `test_dashboard_security_headers.py` |
| SSE injection into UI | Script injection via event payload display | Treat SSE text as data; escape; never innerHTML | `test_dashboard_security_headers.py::test_sse_payload_escaped` |
| Response decompression bomb (gzip/br) | OOM / CPU spike despite 1MB wire cap | Apply MAX_RESPONSE_SIZE after decompression; disable compression or cap decompressed bytes; streaming read with hard stop | `test_recipes_security.py::test_decompression_cap` |
| Deep JSON / parser bomb | CPU spike / recursion errors | JSON depth + token count limits; reject overly nested structures; fallback to raw_body (truncated) | `test_recipes.py::test_json_depth_limit` |
| Template injection into headers/body | Request smuggling / invalid requests | Validate parameter values: no CR/LF, max length, strict type coercion; never allow templating into Host header | `test_recipes_security.py::test_crlf_blocked` |
| DNS multi-answer / mixed private+public | SSRF bypass via rebinding edge cases | Resolve all A/AAAA; if any private/link-local/loopback present -> block; re-check on redirects | `test_recipes_security.py::test_dns_multi_answer_block` |
| Request smuggling via crafted headers | Unexpected proxy/backend behavior | Header allowlist; block Host/TE/CL/Connection; CRLF checks | `test_recipes_security.py::test_header_allowlist` |
| Unsafe remote mutations (PUT/PATCH/DELETE) | Data loss / account actions | Default method allowlist; unsafe methods require explicit config + verified status | `test_recipes_security.py::test_unsafe_methods_gated` |
| LLM prompt injection in captured responses | Malicious recipe attempt | Treat LLM output as hostile; validator rejects unsafe; minimize response snippets sent to analyzer | `test_analyzer_prompt_injection.py` |
| `ignore_https_errors` misconfig | MITM risk / data tamper | Default false, expert-mode only, loudly logged | `test_config.py::test_ignore_https_errors_gated` |
| Auto-follow redirects bypasses hop validation | SSRF via Location chain | Manual redirects in every transport | `test_recipes_security.py::test_redirects_manual` |
| Service worker / cache returns stale or poisoned data | Wrong baselines + false "verified" recipes | Disable service workers in server-owned contexts by default; bypass caches for verifier replays | `test_service_worker_cache.py` |
| HTTP cache poisoning on httpx_public | Wrong data / persistence across runs | Send conservative cache headers; optionally disable caching; never persist httpx cache | `test_http_cache_behavior.py` |
| Log injection via control chars/newlines | Corrupted logs + misleading audit trails | Sanitize log fields; strip control chars from untrusted strings | `test_logging_sanitization.py` |
| YAML unicode confusables / odd scalars | Recipe name collisions / policy bypass | Normalize recipe names to NFC + strict charset; reject confusables in identifiers | `test_recipe_name_normalization.py` |
| DoS via unbounded task queue | Memory/disk growth, degraded UX | Hard cap queued tasks + bounded retention | `test_limits.py::test_queue_cap` |
| DoS via SSE connection flood | File descriptor exhaustion | Limit SSE clients; enforce keepalive timeouts | `test_limits.py::test_sse_connection_cap` |
| DoS via huge request bodies/headers | Memory spike / slow parsing | ASGI limits + explicit max body size | `test_limits.py::test_request_size_limits` |

### Premortem (Most Likely Ways This Fails In 6 Months)
1. Auth defaults ship soft (TODO-001), server becomes remotely triggerable via non-loopback bind, or dashboard allows drive-by writes.
2. Transport parity drift, one tier becomes a weaker SSRF filter than others, exploited via redirect/DNS edge cases.
3. Candidate selection stays weak on common sites, “success rate” changes are unmeasurable without corpus/eval.
4. Over-redaction treats public high-entropy keys as secrets, silently breaking replay correctness (success rate stalls).
5. `in_page_fetch` becomes the default path due to weak/absent `context_request`, causing flakier runs (origin/CORS) and worse p95.
6. Store pollution if validation-before-save is bypassed anywhere in learn path (broken recipes accumulate, trust collapses).
7. Multi-call tasks are misclassified as recipe-able, causing repeated learning churn instead of an explicit non-recipeable result.

### Safety Invariants

1. No recipe YAML file ever contains a value for Authorization, Cookie, or X-Api-Key headers
2. All outbound HTTP(S) (direct OR agent navigation) never reaches private IP ranges (IPv4 + IPv6), including via redirects
3. CDP connections are localhost-only
4. Response bodies cannot exceed 1MB
5. Task results in SQLite cannot exceed 10KB
6. State-changing HTTP endpoints (POST/PUT/PATCH/DELETE) are authenticated by default, even on loopback
7. MAX_RESPONSE_SIZE is enforced on decompressed bytes, not only on wire bytes

---

## 5. Data Model

### Core Types

```python
# config.py
class AppSettings(BaseSettings):
    llm: LLMSettings          # provider, model_name, api_key, base_url
    browser: BrowserSettings   # headless, cdp_url, user_data_dir
    agent: AgentSettings       # max_steps (default 100)
    server: ServerSettings     # host, port, transport, auth_token
    research: ResearchSettings # max_searches (default 5)
    recipes: RecipesSettings   # enabled (default False), directory

# recipes/models.py
class Recipe:
    name: str
    description: str
    request: RecipeRequest | None     # URL template, headers, extract_path
    hints: RecipeHints | None         # Navigation hints for fallback
    parameters: list[RecipeParameter] # Input parameters with types and source
    success_indicators: list[str]     # Strings that indicate success
    success_count: int                # Usage tracking
    failure_count: int
    last_used: datetime | None
    status: str                       # draft, verified, deprecated
    # + category, subcategory, tags, difficulty, auth fields
    verification: RecipeVerification | None  # portable verification metadata (no counters)

class RecipeVerification:
    fingerprint_sha256: str
    fingerprint_version: int
    verified_at: datetime | None
    transport_hint: str | None        # httpx_public | context_request | in_page_fetch
    requires_session: bool | None

class RecipeParameter:
    name: str
    type: str                         # str|int|float|bool|json (v1)
    required: bool
    source: str                       # task_input | session | dom | constant
    constraints: dict | None          # max_len, regex, enum, min/max, forbid_chars (CR/LF)
    examples: list[str] | None

class RecipeRequest:
    url: str                          # Template: "https://api.example.com/search?q={query}"
    method: str                       # GET, POST, PUT, PATCH, DELETE
    headers: dict[str, str]
    body_template: dict | None        # For POST requests
    response_type: str                # json, html, text
    extract_path: str | None          # JMESPath for JSON responses
    html_selectors: dict[str, str]    # CSS selectors for HTML responses
    allowed_domains: list[str]        # Domain allowlist for SSRF protection

class RecipeRunResult:
    success: bool
    data: JSONValue                   # Extracted data (no Any)
    raw_response: str | None
    status_code: int | None
    error: str | None
    error_code: str | None            # stable enum-like strings, e.g. URL_BLOCKED, DNS_BLOCKED, REDIRECT_BLOCKED, TIMEOUT, RATE_LIMITED, PARSE_ERROR
    retryable: bool                   # computed by runner (never by LLM), used by AUTO strategy + UI
    retry_after_sec: int | None       # from Retry-After header (validated + bounded)
    auth_recovery_triggered: bool     # True if 401/403 detected
    transport_used: str | None        # httpx_public | context_request | in_page_fetch
    redirect_hops: int                # explicit, since redirects are manual+validated hop-by-hop
    timings_ms: dict[str, int]        # validate_url/request/extract/postprocess + total

# Shared type alias (used across recipes + MCP responses)
JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]

# observability/models.py
class TaskRecord:
    task_id: str
    tool_name: str                    # run_browser_agent, run_deep_research
    status: TaskStatus                # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    stage: TaskStage | None           # INITIALIZING, NAVIGATING, EXTRACTING, etc.
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress_current: int
    progress_total: int
    progress_message: str | None
    input_params: dict
    result: str | None                # Truncated to 10KB
    error: str | None                 # Truncated to 2KB

class TaskEvent:
    task_id: str
    event_id: int
    ts: datetime
    stage: str | None
    message: str | None               # redacted + bounded
    payload: JSONValue | None         # redacted + bounded
```

---

## 6. Implementation Phases

### Phase 0: Foundation Fixes (COMPLETE)

- [x] URL encoding bug fixed: `request.build_url()` used consistently
- [x] Response size cap: `MAX_RESPONSE_SIZE = 1MB` in JS fetch
- [x] E2E recipe learning tests (10 pass, 3 skip for API key)
- [x] Manifest format with `example_params`
- [x] Rename "skills" to "recipes" throughout codebase
- [x] FastMCP 3.0 beta upgrade
- [x] Stdio-to-HTTP proxy for backward compatibility
- [x] HTML-based recipe extraction with CSS selectors
- [x] Multi-field extraction with @attr suffix support
- [x] Selector validation and fallback suggestions
- [x] Agent instructed to test CSS selectors via evaluate action

### Phase 1: Recipe Learning Improvement (IN PROGRESS)

**Goal**: Increase auto-learning success rate from 20% to 60%+

Implementation priority order [Oracle R1 — maximize success-rate gain per unit of complexity]:

**Step 1: Candidate ranking (highest impact)**
- [ ] Implement candidate ranker (heuristics + top_k) to reduce analyzer burden
  - This eliminates the primary failure mode: "LLM picks analytics/tracker instead of data API"
  - Deterministic ranking with weighted heuristics (no ML), heavily unit-tested
  - Use soft scoring (not hard filtering) to avoid over-filtering real APIs on third-party infra (Algolia etc.)
  - See Oracle R1 code sketch: `rank_candidates()` with ~15 weighted signal features

Candidate ranking features (v1) [updated per Oracle R1]:
- +URL/query similarity to task + agent final answer (token overlap, normalized)
- +Response body snippet overlap with task text (first 4KB; catches search APIs) [Oracle R1]
- +Response content-type preference: JSON > HTML > text
- +Response "list likelihood": JSON contains array at top-level or common keys (items/results/data)
- +JSON richness: number of keys / nesting depth bucket (penalizes trivial responses) [Oracle R1]
- +Status preference: 2xx > 3xx > 4xx
- +API path hints: /api/, /graphql, /v[0-9]+/, /search, /query [Oracle R1]
- -Penalty for tracker path hints: /collect, /pixel, /beacon, /telemetry, /events [Oracle R1]
- -Penalty for likely telemetry/ads host patterns (google-analytics, doubleclick, segment, etc.)
- -Penalty for very small bodies (< 200 bytes) and very large recorder-captured bodies (> 32KB)
- -Soft penalty for cache-buster query params (_t, ts, cb, cacheBust, nonce) [Oracle R1]
- +Bonus if request initiated near the final agent step timestamp (if available)
- +Same-host soft bonus (not hard filter; third-party APIs are valid) [Oracle R1]

**Step 2: Analyzer prompt rewrite**
- [ ] Improve analyzer prompts for simple GET APIs
  - LLM receives ONLY top K candidates (not raw recording)
  - Each candidate includes: URL, method, status, content-type, response size, structural summary
  - LLM output MUST include `chosen_candidate_id` referencing the ranked list
  - Extraction assist: present programmatically computed candidate JMESPaths, LLM selects (not invents)
  - extract_path is optional for v1 success (see Extraction path relaxation)

**Step 3: Validation-before-save (closed-loop)**
- [ ] Add validator stage (schema + safety + deterministic allowed_domains)
  - After LLM/heuristic output, execute recipe in same browser context immediately
  - Require: 2xx + response_type parse success (extract_path match optional for v1)
  - On failure: try next candidate OR second LLM pass with failure reasons
  - Only persist recipe if validation passes at least once [Oracle R1]
  - Requires `run_raw()` on RecipeRunner (returns structured status/body/parsed_ok/fingerprint) [Oracle R1]

**Step 4: Storage hardening**
- [ ] Atomic YAML writes (temp + fsync + os.replace)
- [ ] Name collision handling (slugify + numeric suffix)
- [ ] Async store I/O (anyio.to_thread.run_sync)

Validator requirements (v1):
- URL canonicalization: scheme, host punycode, strip fragments, normalize default ports
- Reject credentials-in-URL (`http://user:pass@host`)
- Reject non-default ports unless explicitly allowlisted (80/443 by default)
- Redirect policy enforced at execution time (host lock unless recipe explicitly allows a small set)

- [ ] Better handling of pagination parameters
- [ ] Support non-JSON content types in recorder (TODO-010)

#### Recorder contract (new)
- [ ] Recorder MUST capture per request:
  - initiator page URL (sanitized)
  - resource type (xhr/fetch/document)
  - response `content-type`, status code, byte length
  - JSON key sample (top-level keys only; cap at 200 chars)
  - timing (start/end) for latency ranking
- [ ] Recorder MUST NOT capture:
  - full HTML documents by default
  - more than 32KB of any response body (separate from runner 1MB cap)
  - raw binary bodies (store metadata only)

- [ ] Validate analysis output structure (TODO-009, partially done)
- [ ] Set allowed_domains from request URL automatically (TODO-007, partially done)
- [ ] Fix parameter passing (wrong query terms in some cases)

#### Phase 1 deliverables (make modules real)
- [ ] Add `recipes/candidates.py` (pure functions + unit tests; no LLM calls) [Oracle R1: build FIRST]
- [ ] Add `recipes/signals.py` (pure functions; turns recordings into per-request features + safe summaries)
- [ ] Add `recipes/heuristic_analyzer.py` (pure functions; handles simple GET/JSON recipe drafts w/o LLM)
- [ ] Add `recipes/extraction_assist.py` (programmatic JMESPath candidate generation from JSON structure) [Oracle R1]
- [ ] Add `recipes/validator.py` (schema + safety canonicalization + closed-loop validation; requires runner) [Oracle R1: build THIRD]
- [ ] Add `recipes/fingerprint.py` (typed JSON path sets + Jaccard similarity; pure functions + golden tests) [Oracle R1]
- [ ] Add `recipes/minimizer.py` (single-pass header/query elimination + volatility detection; bounded attempts) [Oracle R1: simplified]
- [ ] Add `recipes/verifier.py` (replay + shape fingerprint + promotion rules)
- [ ] Add `recipes/pipeline.py` (orchestrates stages; emits artifacts; supports resume)
- [ ] Add `recipes/artifacts/models.py` (Pydantic models for all stage artifacts + schemas + bounds)
- [ ] Add `recipes/artifacts/store.py` (atomic write/read, schema_hash checks, permission enforcement, non-following opens)

#### Learning artifacts persistence [Oracle R1]
- [ ] Persist a "learning artifact" per attempt (enables offline evaluation + deterministic replay):
  - recorded calls (sanitized)
  - candidate ranking output (scores + reasons per candidate)
  - LLM prompt input (redacted)
  - LLM raw output
  - validation attempts + results (pass/fail + reason per attempt)
  - final recipe (if any)
- This makes prompt iterations measurable instead of vibe-based.
- Disk usage mitigated with size caps and configurable retention (artifacts.retention_days).

#### Recipe quality state machine [Oracle R1]
- Transitions are explicit and data-driven (not ad-hoc):
  - `draft` created ONLY if validation passes at least once (no broken recipes in store)
  - `verified` ONLY after N successes AND fingerprint stability (Jaccard >= 0.85 across runs)
  - `deprecated` after M consecutive failures OR fingerprint drift (Jaccard < threshold)
- System is self-healing: deprecated recipes can be re-verified if endpoint comes back.

#### Parameterization strategy [Oracle R1]
- v1: conservative defaults — parameterize only "obvious search params" (q, query, term, search, page, limit)
  and leave everything else constant.
- Multi-example diffs (run a second varied query to diff URL/query/body and infer variables) deferred
  until candidate filtering + validation loop is stable.
- Eventually unavoidable for 60%+ across a broad set of sites, but not v1 scope.

#### Storage split [Oracle R1]
- YAML: recipe definitions (human-editable, diffable, can be shipped as library) — source of truth for definitions
- SQLite: run stats, validation results, fingerprints, promotion state — source of truth for telemetry
  - success_count, failure_count, last_success_at, last_failure_at
  - baseline_fingerprint, last_fingerprint, minimization attempts, validation trace IDs
- Never derive definitions from SQLite. YAML is the definition source of truth.

### Phase 1.2: Runner + Policy Parity Hardening (NEW, REQUIRED)

**Goal**: Make direct execution fast, consistent across transports, and security-invariant before expanding scope.

- [ ] Implement shared `EgressPolicy` and enforce it in all transports + agent navigation
- [ ] **P1**: Auth token enforcement for non-localhost (TODO-001)
  - MUST refuse non-loopback bind unless auth_token set
  - MUST require auth for all state-changing endpoints by default (even on loopback)
  - MUST redact tokens from logs/errors/SSE
- [ ] Add Transport Parity Suite (CI-safe)
- [ ] Add pooled clients (httpx_public) + per-session APIRequestContext reuse (context_request)
- [ ] Implement `recipes warmup` + `bench --ci` and wire perf gate
- [ ] Add artifact schema_hash + resume fail-fast behavior

### Phase 1.5: Learning Corpus + Offline Evaluation (NEW, REQUIRED)

**Goal**: Make "auto-learning success rate" measurable and improvable without live-site flakiness.

- [ ] Add `recipes/corpus/` format:
  - sanitized SessionRecording + CandidateSummary
  - expected baseline fingerprint + extraction expectations
  - provenance metadata (site category, auth required, volatility flags)

  Corpus file layout:
    recipes/corpus/
    ├── manifest.yaml              # list of test cases with expected outcomes
    ├── github-repo-search/
    │   ├── recording.json         # sanitized SessionRecording (no secrets, truncated bodies)
    │   ├── candidates.json        # expected CandidateSet output
    │   ├── expected_draft.json    # expected RecipeDraft (URL template, extract_path)
    │   ├── expected_fingerprint.json  # baseline shape fingerprint
    │   ├── response_stub.json         # bounded response stub for offline extract+fingerprint validation
    │   └── metadata.yaml          # site category, auth_required, volatility flags, notes
    ├── npm-package-search/
    │   └── ...
    └── ...

  Corpus entry metadata.yaml:
    site_category: developer | financial | jobs | public_api
    auth_required: false
    volatility: low | medium | high  # how often the API changes
    expected_transport: httpx_public | context_request | in_page_fetch
    expected_recipe_type: api | html | hints
    notes: "Simple GET JSON API, should be handled by heuristic analyzer"
- [ ] Add `mcp-server-browser-use eval --corpus recipes/corpus --ci`:
  - runs the pipeline deterministically (LLM optional; stubbed modes supported)
  - supports `--no-network`:
    - all transports replaced with corpus-provided ResponseStubs (bounded, redacted)
    - minimizer/verifier operate on stubs for extract+fingerprint validation
    - any attempt to do live network in this mode fails fast (error_code=NETWORK_DISABLED)
  - reports success rate, failure reasons, and regression diffs by stage
- [ ] CI gate (soft at first, hard before v1):
  - "no regressions in corpus success rate" unless baseline updated intentionally

### Phase 2: Hardening + Contract Stabilization (PLANNED)

**Goal**: Resolve remaining P2 issues, stabilize contract, and make recipes production-ready

- [ ] (moved to Phase 1.2) Auth token enforcement for non-localhost (TODO-001)
  - Require auth for all write endpoints by default (even loopback); configurable dev override
  - Add strict `Origin`/`Host` validation for dashboard + SSE endpoints (CSRF mitigation)
  - Add security headers for all dashboard routes:
    - Content-Security-Policy (default-src 'self'; no inline scripts)
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY (or CSP frame-ancestors 'none')
    - Cache-Control: no-store for sensitive pages
  - Dashboard must HTML-escape all task outputs and artifacts; no raw HTML rendering.
  - Explicitly disable dashboard when bound to non-loopback unless `server.dashboard_enabled=true`
  - Add per-IP rate limiting (token bucket) for REST + MCP endpoints
    Rate limit defaults (v1):
    - MCP tool calls: 60 requests/minute per IP (burst 10)
    - REST API: 120 requests/minute per IP (burst 20)
    - Recipe direct exec: 30 requests/minute per IP (burst 5)
    - Response: 429 + Retry-After header + stable error_code=RATE_LIMITED
    - Storage: in-memory dict with IP -> TokenBucket (no persistence needed for single-user)
- [ ] **P2**: Atomic RecipeStore writes (TODO-003)
- [ ] **P2**: RecipeStore name collision handling (TODO-004)
- [ ] **P2**: Async RecipeStore I/O (TODO-005)
- [ ] **P2**: Background task cleanup in `_running_tasks` (TODO-006)
- [ ] **P2**: Direct execution in REST `/api/recipes/{name}/run` (TODO-016)
 - [ ] Tool surface stabilization:
   - Replace `recipe_run_direct` with `recipe_run(strategy="auto"|"direct"|"hint")`
   - Add `recipe_learn(task_id=..., strategy="auto"|"interactive")` (returns candidates/artifacts when needed)
   - Add `run(task, strategy="auto"|"agent"|"recipe")` (single entry-point; `run_browser_agent` becomes alias/deprecated)
   - Add `recipe_create_from_candidate(task_id, candidate_id, name, params_schema, extract_spec)`:
     - server validates candidate + produces RecipeDraft via validator (no LLM required)
     - returns VerificationReport + saved recipe name on success
   - Add `recipe_validate(draft_or_name, params)`:
     - runs validator + dry-run compilation, returns structured warnings/errors (no network)
   - Add `recipe_explain(name, params)` (returns transport decision trace, validator summary, allowed_domains, fingerprint_version)
   - Add `recipe_dry_run(name, params)` (returns compiled URL + headers summary; performs validation but does NOT execute network)
 - [ ] CLI DX:
   - `mcp-server-browser-use doctor` (env + playwright + browser + ports + auth)
   - `mcp-server-browser-use bench` (CI-safe perf harness against local deterministic server)
 - [ ] Runner DX:
   - `mcp-server-browser-use recipes warmup` (precompile verified recipes; prints cache hit/miss stats)
   - Add `recipe_cache` metrics to task trace (hit/miss, compile_ms)
- [ ] **P2**: Add deterministic local test server + CI-safe benchmark harness (feeds Gate 2a + Gate 2c)
- [ ] **P3**: Missing bs4 dependency (TODO-011)
- [ ] Replace bs4 usage with selectolax (or remove dependency entirely); reserve bs4 only if absolutely necessary and benchmarked.
- [ ] Standardize JSON parsing on orjson in runner + verifier paths; keep stdlib json only for small internal fixtures.
- [ ] **P3**: Unify sensitive headers constants (TODO-015)
- [ ] **P3**: Strengthen result validation (TODO-012)

Contract stabilization is part of Phase 2 (v1 requirement, not optional):
- [ ] MCP tool schemas pinned + contract tests in CI (Gate 2 pre-merge)
- [ ] Error envelope standardized across tools + REST (includes error_code/retryable/retry_after_sec/task_id)
  - Add "stage" and "reason_codes[]" fields to all errors (deterministic, enumerable)
  - Ensure all tools return either:
    - { ok: true, data: ..., meta: ... } OR
    - { ok: false, error: { error_code, message, retryable, stage, reason_codes, task_id } }

```python
# MCP tool / REST response envelope (v1)
class ToolResponse(TypedDict):
    ok: bool
    data: JSONValue | None          # present when ok=True
    meta: ResponseMeta | None       # timing, transport, cache info
    error: ErrorDetail | None       # present when ok=False

class ErrorDetail(TypedDict):
    error_code: str                 # URL_BLOCKED, DNS_BLOCKED, TIMEOUT, PARSE_ERROR, QUEUE_FULL, etc.
    message: str                    # human-readable
    retryable: bool
    stage: str | None               # pipeline stage where failure occurred
    reason_codes: list[str]         # machine-readable detail codes
    task_id: str | None
    retry_after_sec: int | None     # bounded, from Retry-After or backoff

class ResponseMeta(TypedDict, total=False):
    transport_used: str
    timings_ms: dict[str, int]
    cache_hit: bool
    redirect_hops: int
    fingerprint_match: bool | None
    session_id: str | None
    idempotency_key: str | None
```

Idempotency (v1, required):
- REST: accept `Idempotency-Key` header on task-creating endpoints and tool-equivalent REST calls.
- MCP: accept `idempotency_key` field on tools that create tasks (`run`, `run_browser_agent`, `run_deep_research`).
- Server behavior:
  - if same key + same normalized input arrives within TTL, return the original task_id (no duplicate run).
  - idempotency keys are never logged verbatim and are redacted like secrets.

- [ ] Deprecation policy documented (remove only in minor/major)
- [ ] Version reporting endpoint: `/api/version` + `health_check` includes version + git sha (if available)
- [ ] REST OpenAPI published at `/api/openapi.json` and pinned in CI
- [ ] Generated typed REST client used in dashboard + contract tests (reduces drift)

### Phase 3: Recipe Library Scale-Up (PLANNED)

**Goal**: 20+ verified recipes across 4+ categories

- [ ] Batch learning pipeline with resume capability
  Batch learning details:
    - Input: RecipeManifest YAML with learning_task + example_params per entry
    - State: per-recipe status file in artifacts dir (pending/recording/analyzing/verified/failed)
    - Resume: `--resume` flag skips recipes with status >= analyzing (unless --force)
    - Rate limiting: configurable delay between recipes (default 5s) to avoid site bans
    - Parallelism: sequential by default (one browser context at a time)
    - Output: summary report with per-recipe success/failure + artifact paths
    - CLI: `mcp-server-browser-use recipe learn-batch --manifest <path> [--resume] [--delay 5]`
- [ ] Replay-based recipe verification + promotion gate (draft → verified)
- [ ] Recipe categories: developer, financial, jobs, public APIs
- [ ] Dual-source registry: shipped library (read-only) + user store (writable)
  Registry merge semantics:
    - Shipped recipes: bundled in package as `recipes/library/*.yaml` (read-only, version-pinned)
    - User recipes: `~/.config/browser-recipes/*.yaml` (writable, user-created or learned)
    - Lookup order: user store first (user overrides take priority)
    - Name collision: user recipe shadows shipped recipe (logged as info)
    - recipe_list shows both sources with `source: library | user` field
    - Shipped recipes cannot be deleted via recipe_delete (returns error)
    - User can clone+modify a shipped recipe: `recipe_fork(name, new_name)`
- [ ] SkillAuth model for API-key recipes
- [ ] Rate limit handling per recipe

### Phase 4: Polish & Release (PLANNED)

**Goal**: PyPI release, CI pipeline, documentation

- [ ] GitHub Actions CI (lint, typecheck, unit+integration on PRs) -- move initial CI setup to Phase 2
- [ ] Fix remaining test failures (dashboard 404s, tool count mismatch)
- [ ] PyPI package publication
- [ ] README with usage examples and Claude Desktop config
- [ ] Changelog
- [ ] Server module split (DX + reviewability):
  - `server/mcp_tools.py`, `server/rest_api.py`, `server/sse.py`, `server/dashboard.py`
  - keep `server.py` as thin composition root

---

## 7. Performance Budgets

| Metric | Target | Current |
|--------|--------|---------|
| Direct recipe execution (runner CPU overhead on local test server, warm cache) | p50 < 50ms, p95 < 150ms | (new metric; benchmark harness) |
| Direct recipe execution (runner end-to-end on local test server) | p50 < 250ms, p95 < 800ms | (new metric; benchmark harness) |
| Direct recipe execution (end-to-end on real sites) | target: "best effort"; log p50/p95 | currently 6-25s for some public APIs |
| Browser agent execution | p50 < 60s | ~60-120s |
| Server startup (daemon) | < 3s | ~2s |
| Health check response | < 100ms | ~50ms |
| Recipe list/get | < 200ms | ~100ms |
| Deep research (5 searches) | < 5 min | ~3-5 min |
| Auto-learning success rate | > 60% | 20% (needs improvement) |

Additional perf requirements (measured and logged per task):
- runner stage timings: validate_url, transport_select, request, extract, postprocess
- runner stage timings MUST split:
  - pure CPU time (parse/validate/compile/extract) vs network time (connect/TTFB/download)
  - include `dns_ms` and `redirect_validate_ms` explicitly (security cost is measurable)
- network vs runner overhead MUST be split (TTFB, download, parse/extract, postprocess)
- cache hit-rate for compiled recipes MUST be logged (to prove caching works)
- benchmark harness against a local deterministic test server (CI-safe)

CI perf regression gate (new, required for v1):
- Add `mcp-server-browser-use bench --ci` that runs N=200 local-server direct exec calls.
- Gate on: p95 end-to-end and p95 CPU overhead (warm cache).
- Store baseline JSON in repo and fail CI on >20% regression unless explicitly updated.

Observability requirements (v1):
- AUTO decision trace persisted in task record:
  - selected strategy + reason codes (unverified, demoted, auth_recovery, validator_reject, fingerprint_mismatch)
  - standardized runner error_code + retry decision (attempt, backoff_ms, retry_after_sec)
  - per-stage timings + redirect hop count
- SSE emits structured progress events per stage (safe + redacted)
- SSE MUST support reconnect + replay:
  - events include monotonically increasing `event_id`
  - server honors `Last-Event-ID` header to replay missed events
  - persist a bounded event log per task in SQLite (`task_events` table, max 200 events/task)
  - emit periodic keepalive ping events (every 15s) to keep proxies honest

---

## 8. Quality Gates

### Gate 1: Pre-Commit (Automated)

**Trigger**: `git commit`
**Checks**: validate-pyproject, prettier, ruff-format, ruff-check, uv-lock-check, pyright, no-commit-to-branch, codespell
Add (v1 requirement): secret scan (gitleaks or trufflehog) over repo + test artifacts directory in CI.
**Response**: Commit blocked if any check fails

### Gate 2: Pre-Merge (Manual, future CI)

**Trigger**: PR to main
**Checks**: `just check` (format + lint + typecheck + pytest)
**Response**: All 297 tests must pass

### Gate 2a: Hostile Web Harness (Automated, CI-safe)
**Trigger**: PR to main
**Checks**: deterministic server suite (redirect/SSRF/decompression/depth/rate-limit) + chaos cancellation tests
**Response**: must pass or merge blocked

### Gate 2aa: Transport Parity (Automated, CI-safe)
**Trigger**: PR to main
**Checks**: same scenario matrix across all transports; parity assertions on safety + caps + error envelope
**Response**: must pass or merge blocked

### Gate 2b: Pipeline Golden + Fuzz (Automated, CI-safe)
**Trigger**: PR to main
**Checks**: golden artifact fixtures + Hypothesis property suite (bounded)
**Response**: must pass or merge blocked

### Gate 2c: Perf Regression (Automated, CI-safe)
**Trigger**: PR to main
**Checks**: `mcp-server-browser-use bench --ci` on deterministic server
**Response**: regression beyond threshold blocks merge unless baseline explicitly updated

### Gate 3: Recipe Verification (Manual)

**Trigger**: New recipe added
**Checks**: Direct execution returns expected data shape, extract_path works, domain allowlist set
**Response**: Recipe status set to `verified` only after passing

### Gate 4: Security Review

**Trigger**: Changes to `runner.py`, `recorder.py`, or `config.py`
**Checks**: SSRF protection intact, no secret leakage, CDP localhost-only
**Response**: Review `test_recipes_security.py` passes

---

## 9. Reference Projects

| Project | Location | Patterns to Adopt |
|---------|----------|-------------------|
| browser-use | `/Users/igortarasenko/Projects/browser-use/` | Agent API, CDP session management, step callbacks |
| FastMCP | PyPI `fastmcp>=3.0.0b1` | HTTP transport, tool registration, progress streaming, task execution |
| mcp-remote | npm `mcp-remote` | Stdio-to-HTTP bridge pattern |
| mitmproxy2swagger | `.reference/mitmproxy2swagger/` | Path parameterization (numeric/UUID → {id}), URL-to-params type inference, heuristic format detection |
| workflow-use | `.reference/workflow-use/` | Variable detection with regex+confidence, semantic converter (CSS → text targets), agentic fallback |
| Skyvern | `.reference/skyvern/` | TTLCache for compiled workflows, element hash matching, Pydantic Settings with env hierarchy |

Reference manifest: `.reference/manifest.json` (key paths, patterns to adopt per project)

---

## 10. Open Issues Inventory

### P1 (Critical)

- [ ] **TODO-001**: Auth token not enforced for non-localhost access

### P2 (Medium)

- [ ] **TODO-002**: Direct fetch URL encoding (fixed in request.build_url(), standalone deprecated)
- [ ] **TODO-003**: RecipeStore non-atomic writes, read-modify-write race
- [ ] **TODO-004**: RecipeStore name collision (sanitization could merge distinct names)
- [ ] **TODO-005**: Blocking RecipeStore I/O (sync file ops in async context)
- [ ] **TODO-006**: `_running_tasks` background task entries never cleaned up
- [ ] **TODO-007**: `allowed_domains` never populated by analyzer (partially fixed)
- [ ] **TODO-008**: Direct fetch unbounded response (fixed: 1MB cap in JS)
- [ ] **TODO-009**: Analysis output not validated (partially fixed)

### P3 (Low)

- [ ] **TODO-010**: Recorder captures JSON-only (misses text/plain, text/html)
- [ ] **TODO-011**: Missing bs4 dependency for HTML parsing
- [ ] **TODO-012**: Weak recipe execution result validation
- [ ] **TODO-013**: Docs/CLI mismatch
- [ ] **TODO-014**: Fetch parse error drops raw body
- [ ] **TODO-015**: Sensitive headers constant not unified
- [ ] **TODO-016**: REST `/api/recipes/{name}/run` doesn't use direct execution

### Test Debt

- [ ] Dashboard API tests have 404 errors (route registration order?)
- [ ] `test_mcp_tools.py` expects 9 tools, server has 10:
  - resolved by Phase 2 contract stabilization (replace recipe_run_direct with recipe_run; add explicit deprecation alias)
- [ ] SSE endpoint tests skipped (block TestClient)

---

## 11. Open Questions

| Question | Proposed Answer | Status |
|----------|-----------------|--------|
| Should recipes auto-expire after N failures? | Yes (decision): after 5 consecutive failures, demote to draft and require re-verification | Decided |
| Should usage stats move to SQLite? | Yes (decision): YAML for definitions, SQLite for mutable stats/health | Decided |
| Which LLM is best for recipe analysis? | Currently moonshotai/kimi-k2.5, needs benchmarking | Testing |
| Should we support recipe versioning? | Not for v1, recipes are mutable files | Decided: No |
| How to handle recipe auth (OAuth, API keys)? | SkillAuth model with env var references (see plan) | Designed, not built |
| Should extract_path be required for recipe success? | No (decision): endpoint correct + parse correct = valid draft [Oracle R1] | Decided |
| Heuristic-first or LLM-first for candidate selection? | Heuristic-first for ranking, LLM for choice among top K [Oracle R1] | Decided |
| Fingerprint comparison: exact hash or similarity? | Jaccard similarity >= 0.85 over typed path sets [Oracle R1] | Decided |
| ddmin or single-pass for minimization? | Single-pass for v1, ddmin deferred [Oracle R1] | Decided |
| 2-tier or 3-tier transport for v1? | 3-tier by design (`httpx_public` -> `context_request` -> `in_page_fetch` fallback-only), gated by transport parity tests [ADR-6] | Decided |

---

## File Locations Quick Reference

| What | Where |
|------|-------|
| Config file | `~/.config/mcp-server-browser-use/config.json` |
| Tasks database | `~/.config/mcp-server-browser-use/tasks.db` |
| Recipes | `~/.config/browser-recipes/*.yaml` |
| Server PID | `~/.local/state/mcp-server-browser-use/server.json` |
| Server log | `~/.local/state/mcp-server-browser-use/server.log` |
| Results (if enabled) | `~/Documents/mcp-browser-results/` |
| Pipeline artifacts | `~/.config/mcp-server-browser-use/artifacts/<task_id>/` |

---

## Changelog

### 2026-02-10 — Plan v3.0 (EV Decision Tree + v1 Strategy Lock)
- Added YAML frontmatter for Flywheel Plan Gate fields (oracle rounds already reflected below).
- Added ADR-6 with probability-weighted decision tree + expected value, and locked v1 strategy: lean hybrid floor + tri-state learning outcomes.
- Clarified transport discipline: prefer `context_request` when session-bound but DOM-independent, reserve `in_page_fetch` for true page-context needs.
- Added a short premortem focused on product/system failure modes (distinct from the security threat model).

### 2026-02-09 — Plan v2.9 (Recipe Architecture Oracle Review)
- Applied Oracle recipe architecture review findings (GPT-5.2 Pro, `.apr/rounds/recipe-architecture/round_1.md`):
  1. Signal vector expanded: 5 new features (body_task_overlap, url_api_path_hint, url_tracker_path_hint, json_richness, has_cache_buster)
  2. Fingerprint algorithm updated: depth 3→6, typed JSON path sets with Jaccard similarity >= 0.85 (replaces exact sha256 equality)
  3. Minimization simplified: ddmin replaced with single-pass header/query elimination for v1
  4. Transport simplified: v1 starts with 2 tiers (httpx_public + in_page_fetch), context_request deferred
  5. Extraction path relaxation: extract_path optional for v1 success ("endpoint correct + parse correct = success")
  6. Extraction assist: programmatic JMESPath candidate generation, LLM selects (classification, not generation)
  7. Validation-before-save: closed-loop execution in same browser context with retry on next candidate
  8. Learning artifacts: persistent per-attempt data for offline evaluation and deterministic replay
  9. Recipe quality state machine: explicit data-driven transitions (draft only if validation passes)
  10. Implementation priority order: candidate ranking → analyzer rewrite → validation-before-save → storage hardening
  11. Parameterization: conservative defaults for v1 (obvious search params only), multi-example diffs deferred
  12. Storage split confirmed: YAML for definitions (source of truth), SQLite for telemetry
  13. ADR-5 added for recipe architecture decisions
  14. Reference projects table expanded (mitmproxy2swagger, workflow-use, Skyvern)
  15. Explicit exclusions expanded (ddmin, learned ranker, Tier 2, multi-run verify, multi-example diffs)

### 2026-02-09 — Plan v2.8 (Oracle Round 7)
- Applied 12 Oracle review changes:
  1. Verification metadata in recipe YAML: baseline fingerprint stored in 3 places (artifact + SQLite + optional YAML verification block); RecipeVerification class added to data model
  2. Two-param promotion rule: parameterized verification (0 params: 2 replays; >=1 params: 2 distinct param sets); error_code=NEEDS_SECOND_EXAMPLE_FOR_VERIFY; transport_hint locked only after both sets pass
  3. Explicit ParameterSource + constraints: RecipeParameter class with source (task_input/session/dom/constant) and constraints; Phase D parameterization uses typed sources; LLM-suggested names treated as untrusted
  4. ddmin minimizer: replaced drop-one-at-a-time with delta debugging (ddmin) + replay result caching; budgets changed to max_attempts=24 OR 30s wall-clock; per-host pacing (250ms) during minimization
  5. DNS pinning + bounded cache: non-negotiable 3c added; pin resolved IPs per request chain; re-resolve on retries; bounded LRU cache (max 256, ttl 5s, negative 2s)
  6. Per-host concurrency + rate-limit: per-host concurrent direct runs (default 2) and per-host token bucket (20/min burst 5); retries consume per-host budget
  7. Task input secret guard: non-negotiable 2b added; SECRET_IN_TASK default refusal unless server.allow_task_secrets=true; redaction for opted-in flows
  8. Browser hardening: non-negotiable 4a.6 added; downloads disabled by default; deny-by-default permission prompts; file chooser blocked
  9. New threat model entries: IPv4-mapped IPv6, relative Location redirects, URL control chars, credential leakage via task input
  10. New testing suites: Suite 4 (Secret Detector) and Suite 5 (Browser Hardening)
  11. Auth (TODO-001) moved to Phase 1.2: earlier enforcement before recipe learning scale-up; Phase 2 goal updated
  12. SSE reliability: event IDs + Last-Event-ID replay; bounded per-task event log in SQLite; keepalive pings; TaskEvent class added to data model

### 2026-02-09 — Plan v2.7 (Oracle Round 6)
- Applied 12 Oracle review changes:
  1. Explicit Session/Profile model: session_id on run_browser_agent, ephemeral sessions with TTL, expert-mode persistent profiles
  2. Schema-validated pipeline artifacts: Pydantic models on write+read, schema_hash for resume safety, ARTIFACT_SCHEMA_MISMATCH error
  3. No-network replay mode for corpus: --no-network flag with ResponseStubs, response_stub.json in corpus layout
  4. Candidate ranking improvements: 3 new signal features (initiator_type, has_initiator_stack, same_site_as_page), dedup by endpoint_key before top_k
  5. Unified EgressPolicy module: single shared policy across all transports, in_page_fetch defaults to redirect:"error"
  6. Response header redaction: Set-Cookie/Location redaction in artifacts, 2 new invariants for artifact redaction + analyzer budgets
  7. CDP launch-arg hardening: allowlisted launch args, explicitly forbidden flags (--no-sandbox), external_cdp_ack_risk gate
  8. Transport implementation requirements: pooled httpx client, per-session APIRequestContext reuse, warmup, CPU vs network timing split
  9. New threat model entries: service worker cache, HTTP cache poisoning, log injection, YAML unicode confusables
  10. Transport parity tests: parity suite across all transports, Gate 2aa quality gate
  11. Idempotency keys: session_id + idempotency_key in ResponseMeta, REST + MCP idempotency semantics
  12. Phase 1.2 Runner + Policy Parity Hardening: new phase for EgressPolicy, transport parity, pooled clients, warmup, artifact schema_hash

### 2026-02-09 — Plan v2.6 (Ambiguity Enrichment)
- Enriched 15 ambiguous sections with concrete implementation details:
  CANDIDATES stage description, RecipeIR frozen dataclass, shape fingerprint algorithm (JSON + HTML paths),
  transport selection logic (4-step runtime decision), signal feature vector (10 features),
  heuristic analyzer thresholds (0.85 score + 0.3 gap), minimizer algorithm (4-phase: volatility/header/query/param),
  secret detector thresholds (Shannon entropy > 3.5, >= 16 chars), retry backoff (exponential 1s base, max 8s, ±25% jitter),
  error envelope TypedDict schema (ToolResponse/ErrorDetail/ResponseMeta), artifact GC mechanism (startup + daily timer),
  rate limiting defaults (60/120/30 req/min per tier), batch learning pipeline (manifest + resume + status tracking),
  dual-source registry merge semantics (user shadows shipped), corpus file layout (per-recipe dirs + metadata.yaml)

### 2026-02-09 — Plan v2.5 (Oracle Round 5)
- Applied 12 Oracle review changes: signals+heuristic-first learning lane, LLM input budgets + caching,
  browser-wide egress policy (Playwright route handler), CDP launch hardening (no extensions, pipe-first),
  dashboard XSS/CSP + SSE injection protection, DoS resource-exhaustion caps (queue/SSE/body),
  fast parsers required (selectolax/orjson) + uniform transport caps, RecipeIR cache invalidation,
  Phase 1.5 learning corpus + offline evaluation, atomic write/permissions invariant tests,
  query/body secret detector + repo secret scanning, interactive learning tools + structured result envelopes

### 2026-02-09 — Plan v2.4 (Oracle Round 4)
- Applied 7 Oracle review changes: baseline oracle + transport inference (8-stage pipeline),
  artifact storage layout with permissions and GC, RecipeIR compilation + CI perf regression gate,
  execution reliability primitives (error_code/retryable/timings), tightened security posture
  (LLM output as hostile input, method+header allowlists, manual redirects), three testing suites
  (hostile web/golden/fuzz), contract stabilization merged into Phase 2

### 2026-02-09 — Plan v2.3 (Oracle Round 3)
- Applied 6 Oracle review changes: minimize+parameterize pipeline stage, 3-tier transport strategy
  (httpx_public/context_request/in_page_fetch), expanded threat model (localhost CSRF, decompression bombs,
  deep JSON, template injection, DNS multi-answer), hardened auth defaults (write endpoints authenticated
  even on loopback), hostile web test harness + chaos cancellation tests, DX improvements (OpenAPI,
  server module split, single run() entry-point)

### 2026-02-09 — Plan v2.2 (Oracle Round 2)
- Applied 16 Oracle review changes: artifact-based pipeline, minimal sufficient recording contract,
  ghost modules as deliverables, candidate ranker features, validator canonicalization (eTLD+1),
  shape fingerprint for verification, interactive learn fallback, expanded threat model (proxy/websocket/special URLs/IDN/symlink),
  hostile-by-default HTTP exposure, CDP security hardening, context.request as default transport,
  concurrency budgets, malicious web test server, DX improvements (doctor/bench CLI),
  contract stabilization phase, observability traces

### 2026-02-09 — Plan v2.1 (Oracle Round 1)
- Applied 12 Oracle review changes: 6-stage pipeline, tool consolidation, multi-transport strategy,
  expanded SSRF defenses, end-to-end secret redaction, CDP isolation, stats split to SQLite,
  recipe health auto-demotion, p95 perf budgets, testing strategy additions, phase adjustments, JSONValue type alias
- Closed open questions: auto-expire (5 consecutive failures → demote), stats storage (YAML defs + SQLite stats)

### 2026-02-09 — Plan v2.0
- Created comprehensive plan from codebase analysis
- Documented current state, architecture, recipes pipeline
- Catalogued all 16 open issues with priorities
- Defined 4 implementation phases with checkboxes

### 2026-01-09 — Recipe Learning Tests
- E2E tests for GitHub, npm, RemoteOK recipes
- Auto-learning success rate measured at 20%
- HTML extraction with CSS selectors added
- Multi-field extraction with @attr support

### 2026-01-07 — Skills Library Plan (Oracle Review)
- Original 150+ services plan drafted
- Oracle (GPT-5.2 Pro) review identified 4 blockers
- URL encoding, VCR incompatibility, header stripping, manifest gaps

### 2025-12 — FastMCP 3.0 Migration
- Upgraded from stdio to HTTP transport
- Added daemon mode, REST API, SSE streaming
- Web dashboard for task monitoring
- Renamed "skills" to "recipes"
