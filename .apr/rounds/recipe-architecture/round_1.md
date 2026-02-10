> **Meta-Block**
> **Scope:** Review + concrete next-step architecture for the MCP “Recipes” learning/execution pipeline, focused on raising auto-learning success from ~20% to ~60%+ without destabilizing the existing server/tool surface. 
> **Assumptions:** (1) Current recorder output is a list of dict-like “api_calls” with at least: url, method, status/content_type, response_body (possibly truncated), initiator type. (2) You can modify analyzer prompts + code, and add small new modules under `recipes/` without changing MCP tool contracts. (3) “Validation” can reuse the same browser context immediately after the agent run. 
> **Confidence:** 0.78 (probable that candidate filtering + closed-loop validation is the biggest jump; less certain about how often token-based parameterization works across varied sites).
> **Perspective:** Reliability-first, deterministic-first. Use the LLM for semantic choice among a small, high-signal set—not for fishing in noise. 

---

## 1) Answers to the 8 specific questions

### 1. Heuristic-first vs LLM-first

You should be heuristic-first for candidate selection and (partially) heuristic-first for extraction, but not in the “try to fully infer a perfect recipe” sense.

What will actually move your success rate is: (a) deterministically reduce the candidate space to a handful of plausible “money requests”, then (b) ask the LLM to choose + parameterize + propose extraction with guardrails, and (c) validate immediately.

How sophisticated should the heuristic fast-path be?

Keep it narrowly scoped to “low-regret” automation:

1. Deterministic candidate ranking (must-have).

2. Deterministic request templating for the obvious cases (nice-to-have):

   * GET JSON
   * querystring-driven search (`q`, `query`, `term`, `search`)
   * no auth headers required (you already strip secrets; so this is implied)

3. Do not require heuristic-generated `extract_path` to succeed.
   A major portion of your failures is likely “endpoint correct, extraction wrong”. Let v1 succeed with `extract_path=None` (return truncated JSON) and treat extraction as an enhancement step.

Why this split works:

* Candidate selection is where the LLM currently fails most (wrong request chosen). Heuristics are better than LLM here because they can use structural signals (content-type, size, domain relation, tracker patterns) reliably. 
* Extraction path correctness is brittle and hard to guarantee. You’ll get more “working recipes” by allowing “raw JSON recipe” as a valid outcome, then iterating.

Tradeoffs/risks:

* You’ll store more “draft recipes” that return unshaped data. That’s acceptable if you label them clearly and only “verify/promote” those with stable extraction.

Concrete implementation guidance is in the code sketches section (“Candidate ranking”, “Heuristic templating”, “Validation loop”).

---

### 2. Signal vector design

Your 10-feature vector is a good baseline. The missing features that matter most in practice are “task relevance” and “anti-tracker” features that don’t rely solely on a domain list.

Add these (weighted heuristics, not ML ranker yet):

1. **Task-token overlap score (high value):**

   * token overlap between the user task (and/or final result snippet) and:

     * URL query values
     * response body snippet (first N chars)
       This catches “search APIs” and strongly downranks analytics.

2. **URL shape features (medium value):**

   * contains `/api/`, `/graphql`, `/v1/`, `/v2/`, `/search`, `/query` (positive)
   * contains `/collect`, `/pixel`, `/beacon`, `/events`, `/telemetry` (negative)

3. **Response JSON “richness” (medium value):**

   * parseable JSON AND has object/array with meaningful keys (not just `{success:true}`)
   * number of keys / nesting depth bucket

4. **Cache-buster detection (medium value):**

   * query params that look like timestamps/nonce (`_`, `ts`, `t`, `cb`, `cacheBust`) → downrank
     Analytics often has these; real APIs sometimes do too, so keep it soft.

Should you use a learned ranker?

Not yet. A learned ranker only helps if you have labeled data and an evaluation harness. You’re not there (yet). You’ll get most of the gain from deterministic ranking + validation outcomes that produce labels later (success/fail + which candidate was correct). After you accumulate a corpus, a simple logistic regression / gradient boosting ranker becomes plausible—but it’s a later optimization.

Tradeoffs/risks:

* Over-penalizing cross-site domains can hide real APIs hosted on third-party infra (Algolia, etc.). Keep “same_site” as a soft feature, not a hard filter.

---

### 3. Verification strategy and “shape fingerprint” algorithm

You want a fingerprint that is:

* insensitive to values (timestamps, IDs)
* stable across runs if the underlying endpoint is the same
* cheap to compute
* easy to compare (similarity score, not just equality)

Recommended fingerprint for JSON:

Compute the set of “typed JSON paths” up to a depth limit, with arrays normalized. Example entries:

* `$.results[]:array`
* `$.results[].title:string`
* `$.results[].id:number`
* `$.meta.page:number`

Then store:

* `path_set_hash = sha256(sorted(paths))`
* optionally the actual `paths` (truncated to some max) for debugging
* optionally a small set of “top-level keys” and “dominant list paths” for human inspection

Comparison:

* Jaccard similarity over the path sets; require ≥ some threshold (e.g. 0.85) to “match”.

For HTML recipes:

Use a selector-level fingerprint:

* per selector, store the count of matches and whether extracted text is non-empty
* store the DOM host + path of target page
* optionally store a stable “text signature” like sha256 of normalized first K chars of extracted text

Why this works:

* It’s robust to value noise.
* It flags endpoint drift without false positives from changing IDs.

Tradeoffs/risks:

* If a response is sparse for certain queries (empty results), path sets may shrink. Handle this by comparing against the baseline but allowing a lower threshold if the baseline includes list paths that are now empty.

---

### 4. Minimization: ddmin vs simple header dropping

ddmin is overkill for v1.

A simpler approach is enough:

1. Start from an aggressively filtered header set (denylist `sec-fetch-*`, `sec-ch-ua*`, `accept-encoding`, `connection`, `host`, etc.).
2. Then do a single-pass elimination:

   * try removing each remaining header one at a time
   * keep the removal if:

     * status remains 2xx AND
     * fingerprint similarity remains above threshold

This gives you most of the benefit at a fraction of the complexity.

Why:

* Many recorded headers are irrelevant noise.
* The “necessary” set is usually small (Accept, Content-Type, maybe X-Requested-With, sometimes CSRF headers).

Tradeoffs/risks:

* Some endpoints require a specific header only under some conditions (A/B flags). Minimization might remove it and create an intermittently failing recipe. Mitigate by only minimizing after repeated successes, or only minimizing “verified” candidates.

---

### 5. Transport selection: keep 3 tiers or start with 2

Start with 2 tiers:

* Tier 1: `httpx_public` (no cookies)
* Tier 3: `in_page_fetch` (full browser context)

Add Tier 2 (`context_request`) later.

Why:

* Tier 2 adds surface area and policy-parity work (headers, redirects, cookie jars, SSRF enforcement consistency). 
* Tier 3 already exists and solves the hardest class of endpoints (CSRF/session-bound). 
* Tier 1 is valuable as a cheap verification probe: “does this endpoint work publicly?” If yes, you can avoid in-page fetch complexity and reduce security exposure.

Tradeoffs/risks:

* You’ll miss the “cookie needed but no DOM context needed” sweet spot until Tier 2 exists. That’s acceptable early.

---

### 6. Recipe storage: YAML vs SQLite

Do not move everything to SQLite.

Keep:

* YAML for recipe definitions (human-editable, diffable, can be shipped as a library). 
  Add:
* SQLite (or reuse the existing tasks DB) for run stats, validation results, fingerprints, and promotion state.

Concrete split:

* YAML: `name`, request template, parameter definitions, extraction config, allowed_domains, status (draft/verified/deprecated)
* SQLite: `success_count`, `failure_count`, last_success_at, last_failure_at, baseline_fingerprint, last_fingerprint, minimization attempts, validation trace IDs

Why:

* YAML writes are currently non-atomic and sync; fixing them is simpler than a full migration. 
* SQLite is better for mutable counters and histories.

Tradeoffs/risks:

* Dual sources of truth. Mitigate by making YAML the “definition source of truth”, SQLite the “telemetry source of truth”. Never derive definitions from SQLite.

---

### 7. The single highest-impact change for 20% → 60%

Your hypothesis is correct and is the highest-leverage first move: implement signal-based candidate filtering (stages 2–3) before LLM analysis. 

But to hit 60%+ (not just “less wrong picks”), you should pair it with one more thing in the same step: immediate validation + retry.

The combo that most likely gets you there is:

1. Rank → top K candidates
2. LLM chooses among top K (or heuristic chooses when confidence high)
3. Validate by executing in the same browser context
4. If validation fails:

   * try next candidate (heuristic fallback) OR
   * ask LLM a second pass with the failed validation reasons + remaining candidates

Why this matters:

* Candidate filtering removes most false positives.
* Validation recovers from LLM formatting mistakes (bad JMESPath, wrong param naming) by forcing correctness before saving.

Tradeoffs/risks:

* More runtime in learning mode. That’s fine; learning is already the expensive path.

---

### 8. Scope for v1: minimum viable slice

Minimum slice that will feel “reliably useful”:

A) Record (existing)
B) Signals + Candidates (new)
C) Analyze (LLM, but only on top K + structured summaries)
D) Validate (new, mandatory before save)
E) Store (existing, but atomic writes + name collisions + async I/O)

Explicitly skip for v1:

* ddmin minimization (do one-pass header drop at most)
* learned ranker
* full 3-tier transport parity (start with 2 tiers)
* verify stage requiring “different params” replay (hard without domain knowledge)

Add one pragmatic relaxation:

* Treat “API recipe with correct endpoint and correct response_type” as success even if `extract_path` is missing or weak.

That gets you reliability without over-architecting.

---

## 2) Recommended implementation strategy: what to build first, what to skip

Order below is chosen to maximize success-rate gain per unit of complexity, while minimizing risk to your existing 297 tests/tool surface. 

### Build first

1. Candidate ranking module (Signals → Candidates)
   Why:

* Eliminates the primary failure mode (“LLM picks analytics/tracker”). 
  How:
* Add `recipes/candidates.py` that accepts recorded calls + page/task context and returns top K with scores and “reasons”.
* Keep it deterministic and heavily unit-tested.

Risks:

* Over-filtering real APIs (soft scoring, not hard filtering, mitigates this).

2. Analyzer input compression + “choose among candidates” prompt change
   Why:

* Even good LLMs fail when you hand them 30 near-random requests. 
  How:
* Provide only top K candidates.
* For each candidate include: URL, method, status, content-type, response size, and a short response snippet or JSON structural summary.
* Require LLM output to include `chosen_candidate_id` and a minimal recipe.

Risks:

* Candidate compression might hide a key detail. Keep K moderately sized (e.g., 5–8), and keep “show more” debug logging.

3. Validation-before-save (closed-loop)
   Why:

* Prevents broken recipes from entering your library. 
  How:
* After LLM output, run the recipe in the same page context and require:

  * 2xx response
  * response_type parse success
  * optional: fingerprint not “degenerate”
* If fails, try:

  * next-best candidate with heuristic templating OR
  * a second LLM pass with failure reasons

Risks:

* Makes learning mode slower. Acceptable.

4. Storage hardening (atomic writes + collision handling + async)
   Why:

* These are known issues and will bite you as soon as recipes become “real”. 
  How:
* Atomic write via temp + `os.replace`.
* Collision: slugify + suffix.
* Async: use `anyio.to_thread.run_sync()`.

Risks:

* File permission edge cases. Handle and surface errors clearly.

### Build next (after the above works)

5. Fingerprinting + baseline storage (minimal)
   Why:

* Enables regression detection and safer minimization.
  How:
* Store baseline fingerprint in SQLite telemetry or YAML metadata block.

6. “Extraction assist” (reduce JMESPath failure rate)
   Why:

* JMESPath errors are common. 
  How:
* Generate candidate JMESPaths programmatically from JSON structure.
* Ask LLM to select from options instead of inventing.

### Skip (for now)

* Full ddmin minimization
* Learned ranker
* Tier-2 transport (`context_request`)
* Multi-run “verify with different params” (do later when you have a corpus + per-site strategies)

---

## 3) Architectural insights / patterns you’re probably missing

### A. Treat “learning” as an artifact pipeline, not just an online step

Right now, the learning step is ephemeral: record → LLM → YAML. 

You should persist a “learning artifact” per attempt:

* recorded calls (sanitized)
* candidate ranking output
* LLM prompt input (redacted)
* LLM raw output
* validation attempts + results
* final recipe (if any)

Why:

* Enables offline evaluation (“what improved success rate?”).
* Enables deterministic replay for regression tests.
* Makes prompt iterations measurable instead of vibe-based.

Tradeoffs:

* Disk usage. Mitigate with size caps and optional retention setting.

### B. Don’t ask the LLM to *invent* extraction paths; ask it to *choose*

This is the single cleanest way to reduce JMESPath failure without making the system “more agentic”.

Pattern:

1. Programmatically compute plausible extraction targets (paths to arrays of objects; common key sets).
2. Present top N options to LLM.
3. LLM selects one or returns “none”.

Why:

* You turn a generative error into a classification problem.

### C. Make recipe quality state machine explicit

You already have `draft | verified | deprecated`. 

Make the transitions explicit and data-driven:

* `draft` created only if validation passes at least once
* `verified` only after N successes AND fingerprint stability
* `deprecated` after M consecutive failures OR fingerprint drift

This allows the system to be self-healing and avoids polluting your “working set”.

### D. Parameterization needs either (1) multi-example diffs, or (2) conservative defaults

With only a single trace, parameter inference is fundamentally underdetermined.

Two practical options:

* Conservative: parameterize only “obvious search params” and leave everything else constant.
* Multi-example: in learn mode, run a second slightly varied query so you can diff URL/query/body and infer variables with high confidence.

If you want 60%+ across a broad set of sites, multi-example diffs are eventually unavoidable. But they can be deferred until the candidate filtering + validation loop is stable.

---

## 4) Concrete code sketches (Python, not pseudocode)

These are written to be dropped into small new modules under `mcp_server_browser_use/recipes/`, consistent with your style constraints (typed, no `Any`, Python 3.11+). 

### 4.1 Candidate ranking (signals → candidates)

```python
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import TypeAlias
from urllib.parse import parse_qsl, urlsplit

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | dict[str, "JSONValue"] | list["JSONValue"]


_TRACKER_HOST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"google-analytics\.com$", re.IGNORECASE),
    re.compile(r"googletagmanager\.com$", re.IGNORECASE),
    re.compile(r"doubleclick\.net$", re.IGNORECASE),
    re.compile(r"segment\.com$", re.IGNORECASE),
    re.compile(r"mixpanel\.com$", re.IGNORECASE),
    re.compile(r"sentry\.io$", re.IGNORECASE),
)

_TRACKER_PATH_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/collect\b", re.IGNORECASE),
    re.compile(r"/pixel\b", re.IGNORECASE),
    re.compile(r"/beacon\b", re.IGNORECASE),
    re.compile(r"/telemetry\b", re.IGNORECASE),
    re.compile(r"/events?\b", re.IGNORECASE),
)

_API_PATH_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/api\b", re.IGNORECASE),
    re.compile(r"/graphql\b", re.IGNORECASE),
    re.compile(r"/search\b", re.IGNORECASE),
    re.compile(r"/query\b", re.IGNORECASE),
    re.compile(r"/v[0-9]+\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class RecordedCall:
    url: str
    method: str
    status: int | None
    content_type: str | None
    response_body: str | None
    initiator_type: str | None


@dataclass(frozen=True)
class Candidate:
    call: RecordedCall
    score: float
    reasons: tuple[str, ...]


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", text.lower())
    # keep it simple: de-dup and drop pure digits except years-like
    out: set[str] = set()
    for t in tokens:
        if t.isdigit() and len(t) < 4:
            continue
        out.add(t)
    return out


def _is_tracker(host: str, path: str) -> bool:
    for pat in _TRACKER_HOST_PATTERNS:
        if pat.search(host):
            return True
    for pat in _TRACKER_PATH_HINTS:
        if pat.search(path):
            return True
    return False


def _api_path_bonus(path: str) -> float:
    for pat in _API_PATH_HINTS:
        if pat.search(path):
            return 1.0
    return 0.0


def _content_type_score(content_type: str | None) -> float:
    if not content_type:
        return 0.0
    ct = content_type.lower()
    if "application/json" in ct or ct.endswith("+json"):
        return 1.0
    if "text/html" in ct:
        return 0.35
    if "text/plain" in ct:
        return 0.15
    return 0.0


def _initiator_score(initiator_type: str | None) -> float:
    if not initiator_type:
        return 0.0
    it = initiator_type.lower()
    if it == "fetch":
        return 1.0
    if it == "xmlhttprequest" or it == "xhr":
        return 0.8
    if it == "script":
        return 0.4
    return 0.2


def _response_size_score(body: str | None) -> float:
    if not body:
        return 0.0
    # log-scaled: 1KB ~ 0.3, 10KB ~ 0.6, 100KB ~ 0.9
    n = len(body)
    return min(1.0, max(0.0, math.log10(max(1, n)) / 5.0))


def _task_overlap_score(task_tokens: set[str], url: str, body: str | None) -> float:
    if not task_tokens:
        return 0.0
    parts = urlsplit(url)
    hay = (parts.path + " " + parts.query).lower()
    body_snip = (body[:4000].lower() if body else "")
    hay_all = hay + " " + body_snip
    hits = 0
    for t in task_tokens:
        if t in hay_all:
            hits += 1
    # saturate quickly: 0 hits = 0.0, 1 hit = 0.4, 2 hits = 0.7, 3+ = 1.0
    if hits <= 0:
        return 0.0
    if hits == 1:
        return 0.4
    if hits == 2:
        return 0.7
    return 1.0


def rank_candidates(
    calls: list[RecordedCall],
    *,
    page_url: str,
    task_text: str,
    k: int = 6,
) -> list[Candidate]:
    task_tokens = _tokenize(task_text)
    page_host = urlsplit(page_url).hostname or ""

    candidates: list[Candidate] = []
    for c in calls:
        parts = urlsplit(c.url)
        host = parts.hostname or ""
        path = parts.path or ""
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)

        reasons: list[str] = []
        score = 0.0

        # content type
        ct_score = _content_type_score(c.content_type)
        score += 2.2 * ct_score
        reasons.append(f"content_type={ct_score:.2f}")

        # status
        if c.status is not None and 200 <= c.status <= 299:
            score += 1.2
            reasons.append("status_2xx")
        else:
            score -= 0.6
            reasons.append("status_non_2xx_or_unknown")

        # response size
        rs = _response_size_score(c.response_body)
        score += 1.1 * rs
        reasons.append(f"response_size={rs:.2f}")

        # initiator
        it = _initiator_score(c.initiator_type)
        score += 0.8 * it
        reasons.append(f"initiator={it:.2f}")

        # query params (often indicates data APIs)
        if query_pairs:
            score += 0.35
            reasons.append("has_query_params")

        # api-ish URL hint
        api_bonus = _api_path_bonus(path)
        score += 0.6 * api_bonus
        if api_bonus > 0:
            reasons.append("api_path_hint")

        # tracker penalty
        if _is_tracker(host, path):
            score -= 2.5
            reasons.append("tracker_penalty")

        # same-host soft bonus
        if host and page_host and (host == page_host):
            score += 0.3
            reasons.append("same_host")

        # task relevance
        overlap = _task_overlap_score(task_tokens, c.url, c.response_body)
        score += 1.6 * overlap
        reasons.append(f"task_overlap={overlap:.2f}")

        candidates.append(Candidate(call=c, score=score, reasons=tuple(reasons)))

    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates[: max(1, k)]
```

How to integrate:

* Convert your existing dicts to `RecordedCall` objects in a tiny adapter (keep compatibility; don’t rewrite recorder immediately).
* In `RecipeAnalyzer.analyze(...)`, call `rank_candidates(...)` and pass only candidates to the LLM prompt.

---

### 4.2 JSON shape fingerprinting

```python
from __future__ import annotations

import hashlib
from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | dict[str, "JSONValue"] | list["JSONValue"]


def _type_tag(v: JSONValue) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    return "obj"


def json_path_types(value: JSONValue, *, max_depth: int = 6) -> set[str]:
    out: set[str] = set()

    def walk(v: JSONValue, path: str, depth: int) -> None:
        out.add(f"{path}:{_type_tag(v)}")
        if depth >= max_depth:
            return

        if isinstance(v, dict):
            for k, child in v.items():
                # keys can be arbitrary; keep them because schema stability depends on them
                walk(child, f"{path}.{k}", depth + 1)
        elif isinstance(v, list):
            # normalize arrays
            out.add(f"{path}[]:list")
            # union shapes of a small sample to avoid O(n)
            for child in v[:3]:
                walk(child, f"{path}[]", depth + 1)

    walk(value, "$", 0)
    return out


def json_fingerprint(value: JSONValue, *, max_depth: int = 6) -> tuple[str, set[str]]:
    paths = json_path_types(value, max_depth=max_depth)
    digest = hashlib.sha256("\n".join(sorted(paths)).encode("utf-8")).hexdigest()
    return digest, paths


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union
```

How to use:

* In “validate/baseline” stage, compute fingerprint and store digest + (optionally) a truncated list of paths for debugging.
* On subsequent runs, compare Jaccard similarity; if it collapses, mark as failing.

Tradeoffs:

* Some endpoints return different shapes depending on query. Keep thresholds configurable and allow “empty result” exceptions.

---

### 4.3 Validation loop (validate-before-save, with retry)

```python
from __future__ import annotations

from dataclasses import dataclass

# You already have Recipe/RecipeRequest types; these are small wrappers.
@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    status: int | None = None
    fingerprint: str | None = None


class RecipeValidator:
    def __init__(self, runner) -> None:
        self._runner = runner  # RecipeRunner-like object

    async def validate(self, recipe, *, page, params: dict[str, str]) -> ValidationResult:
        try:
            # You likely have internal methods; if not, call runner.run(...) and adapt.
            raw = await self._runner.run_raw(recipe=recipe, params=params, page=page)  # implement run_raw to return status/body/parsed
        except Exception as e:  # narrow this in real code (network, parse, SSRF)
            return ValidationResult(ok=False, reason=f"runner_exception:{e.__class__.__name__}")

        if raw.status is None:
            return ValidationResult(ok=False, reason="no_status")
        if not (200 <= raw.status <= 299):
            return ValidationResult(ok=False, reason=f"bad_status:{raw.status}", status=raw.status)

        # Minimal correctness check: parse succeeded for declared response type
        if raw.parsed_ok is False:
            return ValidationResult(ok=False, reason="parse_failed", status=raw.status)

        # Optional: extraction check (don’t require this for v1 success)
        # if recipe.request and recipe.request.extract_path and not raw.extracted:
        #     return ValidationResult(ok=False, reason="extract_empty", status=raw.status)

        return ValidationResult(ok=True, reason="ok", status=raw.status, fingerprint=getattr(raw, "fingerprint", None))
```

Key point: you’ll need a `run_raw` on the runner (or a small wrapper) that returns structured info (`status`, `body`, `parsed_ok`, `fingerprint`). This is worth adding because it makes validation and debugging dramatically easier.

Tradeoffs:

* Adds code paths and test updates. Keep the existing `run(...) -> str` untouched; add `run_raw(...)` as an internal API.

---

### 4.4 Atomic YAML writes + name collision handling (async-friendly)

```python
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import anyio
import yaml


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "recipe"


async def atomic_write_yaml(path: Path, content: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(content, f, sort_keys=False, allow_unicode=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            try:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            except OSError:
                # best-effort cleanup
                pass

    await anyio.to_thread.run_sync(_write)


async def choose_recipe_path(directory: Path, recipe_name: str) -> Path:
    base = _slugify(recipe_name)
    p = directory / f"{base}.yaml"
    if not p.exists():
        return p

    # collision: add short suffix
    for i in range(1, 100):
        candidate = directory / f"{base}-{i}.yaml"
        if not candidate.exists():
            return candidate

    # last resort: random temp-style filename
    fd, tmp_name = tempfile.mkstemp(prefix=f"{base}-", suffix=".yaml", dir=str(directory))
    os.close(fd)
    return Path(tmp_name)
```

Tradeoffs:

* Windows rename semantics differ (but you’re likely on macOS/Linux). `os.replace` is the right move.

---

## Practical “tell it like it is” notes

1. You won’t hit 60%+ purely by prompt tweaking. Candidate filtering + validation is the lever. 
2. If you keep requiring “perfect extraction paths” at creation time, you’ll keep failing. Make extraction optional for v1 success.
3. Parameterization from a single trace will stay brittle. To go beyond “works on easy GET search endpoints”, you’ll eventually need either multi-example diffs or per-site strategies.

---

## Summary of the recommended v1 slice

* Add deterministic ranking to reduce LLM choice to top K.
* Change analyzer prompt: “pick among these candidates; don’t invent”.
* Validate-before-save with immediate execution; retry on failure.
* Treat “endpoint correct + parse correct” as success even if extraction is missing.
* Harden YAML writes and collisions; move mutable stats to SQLite telemetry later.

That set is the highest probability path to 60%+ without ballooning complexity or destabilizing your tool surface.
