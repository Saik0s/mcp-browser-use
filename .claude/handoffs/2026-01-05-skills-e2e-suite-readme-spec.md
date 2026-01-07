# Readable Summary
Skills E2E Suite + README Full Spec Handoff

<analysis>
- Captured explicit requests and constraints
- Logged key files and architecture touchpoints
- Listed pending tasks and immediate next action
</analysis>

<plan>
# Session Handoff Plan
Slug: skills-e2e-suite-readme-spec
Readable Summary: Skills E2E Suite + README Full Spec Handoff

## 1. Primary Request and Intent
- Build comprehensive skills E2E test suite using the full public Claude browser-use skills list (user provided categories/items) to learn+save a skill for each entry.
- Tests must run real API via MCP server, local-only, “run once” intent (do not run in CI by default).
- LLM: `gemini-3-flash-preview` (provider `google`).
- Auth-required cases: fail by default; allow skip with a flag.
- Save learned skills under `./results/skills`.
- Expand `README.md` into full project spec: architecture, plans, user stories, acceptance criteria, decisions, problems, etc.

## 2. Key Technical Concepts
- MCP server `run_browser_agent` with `learn=True` + `save_skill_as` for skill extraction.
- Skill pipeline: `SkillRecorder` → `SkillAnalyzer` → `SkillStore` (YAML).
- Skills disabled by default; enable via `MCP_SKILLS_ENABLED=true` and set `MCP_SKILLS_DIRECTORY`.
- Strict typing / Pydantic models in tests; no new deps without approval.
- Pytest markers `e2e`, `slow`; gate execution via env (`MCP_SKILLS_E2E=1`).
- Local-only storage path: `./results/skills`.
- Google LLM env: `MCP_LLM_PROVIDER=google`, `MCP_LLM_MODEL_NAME=gemini-3-flash-preview`, `GEMINI_API_KEY=...`.

## 3. Files and Code Sections
### `src/mcp_server_browser_use/server.py`
- **Why important**: learning mode and skill save flow; tests must exercise this.
- **Code snippet**:
```python
# learning mode core flow (abridged)
if learn:
    recorder = SkillRecorder(task=task)
...
if recorder:
    await agent.browser_session.start()
    await recorder.attach(agent.browser_session)
...
if learn and final and save_skill_as:
    recording = recorder.get_recording(result=final)
    analyzer = SkillAnalyzer(llm)
    extracted_skill = await analyzer.analyze(recording)
    if extracted_skill and skill_store:
        extracted_skill.name = save_skill_as
        skill_store.save(extracted_skill)
```

### `src/mcp_server_browser_use/config.py`
- **Why important**: skills feature default-off, env prefix for tests.
- **Code snippet**:
```python
class SkillsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_SKILLS_")
    enabled: bool = Field(default=False)
    directory: str | None = Field(default=None)
    validate_results: bool = Field(default=True)
```

### `src/mcp_server_browser_use/skills/models.py`
- **Why important**: `SkillRequest` / `Skill` model validation for learned skills.

### `tests/test_e2e.py`
- **Why important**: existing E2E style, API key gating patterns.

### `tests/test_skills.py`, `tests/integration_tests/test_skills.py`
- **Why important**: unit + integration expectations for skills models/tools.

### `tests/conftest.py`, `tests/integration_tests/conftest.py`
- **Why important**: pytest markers and skill-enabled MCP client fixture.

### `docs/skills-design.md`
- **Why important**: skills architecture, limitations, phases; must be reflected in README spec.

### `plans/skills-architecture-redesign.md`
- **Why important**: security/correctness issues + acceptance criteria; include in README spec “decisions/problems/roadmap.”

### `plans/feat-fastmcp-background-tasks.md`, `plans/feat-context-logging-progress.md`, `plans/feat-background-service-installation.md`
- **Why important**: planned features + acceptance criteria; fold into README spec.

### `README.md`
- **Why important**: must become full project spec file per user request.

### `skills/browser-use/SKILL.md`
- **Why important**: MCP tool descriptions; align README spec with actual tool surface.

## 4. Problem Solving
- `brainstorming` skill file missing at expected path; proceeded with minimal brainstorming (note for compliance).
- Skills disabled by default; tests must force-enable via env.
- Local-only requirement implies new tests must be gated (no CI by default).

## 5. Pending Tasks
- Create data-driven skills E2E suite:
  - Manifest of all user-provided skill entries (split files to keep <500 LOC).
  - Pydantic `SkillCase` model + loader.
  - Runner that: run `run_browser_agent` (learn+save), verify skill saved, optionally execute skill_name once, collect results.
  - Auth-required cases fail by default; skip only if `MCP_SKILLS_E2E_SKIP_AUTH=1`.
  - Results report saved under `./results/skills`.
- Update `README.md` into full project spec using content from `docs/` + `plans/`.

## 6. Current Work
- No code changes yet for this request.
- Files inspected to map skills pipeline and tests:
  - `server.py` learn/save flow
  - `skills/models.py`, `config.py`
  - existing tests and markers
  - `docs/skills-design.md`, plan docs
- Prior repo state: unrelated changes already in worktree (do not revert): `.mcp.json` deleted, `AGENTS.md` modified, `FASTMCP_PREVENTION_STRATEGIES.md` deleted, `docs/FASTMCP_PREVENTION_STRATEGIES.md` added.

## 7. Optional Next Step
- Start TDD: add failing test for manifest loader + E2E runner (gated by `MCP_SKILLS_E2E=1`), then implement runner + manifest, then update `README.md` spec sections.
</plan>
