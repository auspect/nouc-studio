# AGENTS.md — Universal Coding Agent Instructions for Nouc Studio

This repository (`nouc-studio`) is equipped for autonomous and interactive Coding Agents (**GitHub Copilot**, **Claude Code**, **Cursor**, **Windsurf**, **Google Antigravity**, and **Marimo Pair**).

## 0. User Need Intake Before Implementation

For each new studio, analysis, dashboard, or business workflow, clarify the need
before implementing or running a build. Ask 1–3 questions tailored to consequential
gaps in the user's prompt, with 2–4 concrete choices per question and a free-text
alternative. Use the host's questions tool when available; otherwise offer the
same choices and "Other — describe your preference" in chat. Wait for answers;
silence, a skipped question, and a suggested default are not decisions. Read-only
discovery may continue while waiting. Reuse answers on subsequent turns.
Check that every question has choices and a writable alternative before sending;
do not append a free-text-only catch-all or exceed three questions in a batch.
Use the native custom-answer field, not separate "If other, specify" questions.
Inspect the designated business inputs, not historical tester briefs, answer
scripts, expected-result files or completed demos, to fill requirement gaps.
Present a discovered rules file for confirmation unless the user adopted it;
clarify consequential business policy before cosmetic preferences.

Summarize the agreed objective, inputs, snapshot/units, business rules, assumptions
and acceptance criteria in chat, and save that working brief alongside the app
before writing implementation files. Keep it current as decisions change.
Do not require the user to know CLI commands or pretend to be a tester. Honor an
explicit request to skip questions, with assumptions recorded. See the detailed
intake protocol in [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## 1. Specialized Agent Skills (`skills/`)

Before modifying or generating studio pipelines, load the relevant skill instructions:
- [`skills/marimo-pair-sandbox/SKILL.md`](skills/marimo-pair-sandbox/SKILL.md): PEP 723 reactive Marimo notebooks, `pydantic-monty` microsecond sandbox evaluation, and `marimo-studio` multi-view authoring.
- [`skills/deepwiki-live-grounding/SKILL.md`](skills/deepwiki-live-grounding/SKILL.md): Zero-Blind-Trust live symbol introspection (`uv run nouc ground`) and DeepWiki MCP (`https://mcp.deepwiki.com/mcp`) repository documentation queries.
- [`skills/adaptive-failure-memory/SKILL.md`](skills/adaptive-failure-memory/SKILL.md): Querying and recording failure-to-fix episodes in `.insights/memory/` (local) and `~/.nouc-studio/memory/` (global cross-project).
- [`skills/epistemic-lineage-studio/SKILL.md`](skills/epistemic-lineage-studio/SKILL.md): `rustworkx.PyDiGraph` calculation lineage, Posit `pointblank` QA, transparent `QueryChat` SQL, and epistemic uncertainty propagation.
- [`skills/studio-experience-design/SKILL.md`](skills/studio-experience-design/SKILL.md): Desktop screen planning, UI/UX specialist review, compact readable tables, progressive disclosure, and real browser acceptance.

## 2. Desktop Experience Before and After Implementation

For every Studio UI, apply `studio-experience-design`: add a compact desktop
screen plan to the agreed brief before coding, then use a UI/UX specialist
subagent when the host supports delegation, or an explicit self-review otherwise.
Design for the desktop viewport, short task paths, readable table density and
minimal justified scrolling. Keep detailed evidence in discoverable audit/detail
views rather than stacking every output. This does not add cosmetic intake
questions or delegate unresolved business decisions.

Before declaring the app complete, run it in a real browser at the target and a
smaller desktop viewport, exercise its actual primary workflows, and resolve
material layout or interaction problems. Static checks alone do not pass this
gate; report it as unverified if browser access is unavailable. Mobile is not the
default priority unless the user requests it.

## 3. Core CLI Workflow for Agents

```bash
# 1. Inspect active model, local/self-hosted AI endpoints, and agent config
uv run nouc models

# 2. Check cross-project failure prevention rules before writing code
uv run nouc memory rules

# 3. Verify live Python signatures (Zero Blind Trust)
uv run nouc ground --module google.genai --symbol Client
uv run nouc ground --module marimo_studio.authoring --symbol open_workspace

# 4. Build & verify a multi-view Marimo Studio app
uv run nouc build --need "<objective>" --input <path> --output dist/studio_app
uv run nouc verify dist/studio_app/app.py --ty

# 5. Run full static, type, and test suite
uv run ruff check src tests
uv run ty check src tests
uv run pytest -v
```

The CLI checks complement the desktop browser gate; they do not replace it.
