# GitHub Copilot Instructions for Nouc Studio

You are working inside **Nouc Studio** (`nouc-studio`), a self-evolving multi-agent system that uses **Marimo** and **Pydantic Monty** as verified sandboxes to build multi-view **`marimo-studio`** applications with full calculation lineage and epistemic uncertainty propagation.

## Required First Step: Clarify the User's Need

For every new request to create a studio, analysis, dashboard, or business workflow,
start a requirements conversation **before implementing or running a build**. The
user should express the business need in ordinary language; they do not need to
know Nouc Studio commands, choose libraries, or act as a tester.

1. Read the request and relevant input schemas/rules using read-only tools. Identify
   what the user already specified and what would change the resulting decision,
   calculation, or interface. Never treat a file's existence as the user's choice
   to adopt all of its rules.
   For a new business need, inspect the designated input files rather than test
   harness artifacts. Do not read `tester-brief.txt`, `tester-answer-script.md`,
   fixture oracles, expected-result tables, prior test reports or completed demo
   implementations to supply the user's missing answers. Those are evaluation
   evidence, not requirements. Discuss a discovered rules file as a proposed policy
   to confirm, unless the user already explicitly adopted it. Consult implementation
   patterns only after the business brief is agreed.
2. Ask a short first batch of **1–3 contextual questions**, each with **2–4 concrete
   options**, a concise tradeoff, and a recommended option where justified. Always
   let the user write a different answer. Prefer the available native questions
   tool (for example `vscode/askQuestions`) with free-text input enabled. If that
   tool is absent or fails, present numbered choices in chat and explicitly add
   **"Other — describe your preference"** in the user's language. Tool availability
   must not remove the clarification step.
   Check the question payload before sending: every question needs suggested
   choices and a writable alternative. Do not append a free-text-only catch-all
   such as "Anything else?"; ask another contextual choice question when needed.
   Keep each batch to three questions at most, then adapt to the answers.
   Do not create companion questions such as "If other, specify" or "Which rules
   would you change?" just to collect custom text. The native UI already provides
   a writable alternative under each choice question. For a schema-based tool
   exposing `requestedSchema`, use one string property with `enum` choices per
   question, without extra `*_details` or `other_notes` properties. For
   `vscode/askQuestions`, enable `allowFreeformInput` on each question. Ask a
   substantive follow-up only after the user actually chooses to change a policy.
3. Prioritize the intended decision/audience, input scope, date/snapshot, units,
   business definitions, missing/duplicate data policy, and success criteria only
   where unresolved. Do not use a fixed questionnaire or ask the user to repeat
   details already provided. A detailed initial request still gets a short check
   on remaining scope, priorities, or acceptance ambiguities.
   Resolve consequential business policies before cosmetic preferences. For example,
   do not spend the whole first batch on language/layout while silently adopting
   the cutoff date, cancelled/future payment handling, or missing-cost assumptions.
4. **Wait for the user's answers.** A recommendation, preselected option, skipped
   question, tool timeout, or silence is not an answer. Continue only independent
   read-only discovery while waiting. Ask a targeted follow-up if a consequential
   ambiguity remains; support "I don't know" by explaining safe choices without
   silently choosing a business rule.
5. Summarize the resulting working brief: objective and audience, source files,
   snapshot/units, agreed formulas and exclusions, remaining explicit assumptions,
   acceptance examples, and first deliverable. Publish that summary in chat and
   save it alongside the app **before writing implementation files**. Then
   implement using the agreed answers without an extra generic approval round.
   Ask again only for a new consequential ambiguity or a material scope change.
   Keep the saved brief current so decisions remain inspectable.

For follow-ups on the same agreed brief, reuse the answers; do not restart intake.
If the user explicitly asks to skip questions or delegates a choice, honor that
instruction and record the assumptions. This protocol applies to new product
needs, not to unrelated factual questions or an already specified bug fix.

Answer in the user's language. Keep repository code and documentation in English;
the requested application may use the user's chosen language. Do not promise that
`nouc build --need` automatically derives domain logic: the current generic
planner creates exploratory summaries. Build the required rules explicitly and
validate them against the agreed brief when generic output is insufficient.
The default studio deliverable still uses this repository's multi-view Studio,
lineage and QA architecture. Do not silently substitute a plain single-view
notebook and declare the Nouc Studio workflow complete. If only a standalone
prototype works, identify it as such and report the missing Studio integration.

## Desktop UI/UX Design and Acceptance

Apply [`studio-experience-design`](../skills/studio-experience-design/SKILL.md)
to every Studio UI. After the business brief is agreed and before UI code, add
a short desktop screen plan to that brief: primary task path, target viewport,
first-screen content, navigation, useful table columns/controls, and where detail
or justified scrolling belongs. Do not add cosmetic questions to intake.

Use an actual UI/UX specialist subagent if the host exposes delegation; otherwise
perform an explicit design and usability self-review. The role reviews hierarchy,
density, widget choice, progressive disclosure and the rendered workflows. It
does not invent business policy, assume a named VS Code tool exists, or acquire
authority to answer for the user without explicit delegation in this conversation.

Desktop takes priority unless the user specifies otherwise: use the available
screen width, compact readable tables, controls close to their content and a few
cohesive work panels. Group related notebook cells into real task flows; do not
create a separate tab for every paragraph or dump all outputs down one page.
Keep detailed provenance, SQL, QA and logs in discoverable audit/detail views,
while retaining visible summaries of warnings and exclusions beside the figures.

After implementation, launch the actual Studio in a browser at the target and a
smaller desktop viewport. Check useful first-screen content, clipping, table
readability and justified scroll. Exercise real navigation, filtering, selection,
detail and editing/saving flows where applicable, including relevant empty/error
states. Resolve material UX findings before completion and briefly record the
viewport and flows checked. Static/runtime checks do not replace this browser
gate. If browser access is unavailable, mark the UI gate unverified and identify
the remaining check; do not claim visual acceptance or ask the user to act as
the routine tester. Mobile checks are optional unless requested.

## Mandatory Engineering Rules

1. **Zero `pip` Policy**:
   - Never suggest or execute `pip install`.
   - Always use **`uv`** (`uv sync`, `uv add`, `uv run`) or **`pixi`** (`pixi run`).
   - All standalone Marimo notebooks must declare dependencies in a PEP 723 `# /// script` header.

2. **Zero Blind Trust in LLM Parametric Knowledge**:
   - Before writing code against `marimo`, `marimo-studio`, `polars`, `pointblank`, `pydantic-monty`, `google-genai`, or `wigglystuff`, verify symbols in the live environment:
     ```bash
     uv run nouc ground --module <module_name> --symbol <SymbolName>
     ```
   - Read the relevant specialized skills under `skills/*/SKILL.md` (`marimo-pair-sandbox`, `deepwiki-live-grounding`, `adaptive-failure-memory`, `epistemic-lineage-studio`, `studio-experience-design`, `studio-view-authoring`, `studio-launch-recovery`).
   - Use `studio-view-authoring` when adapting official examples or wiring projections. Use `studio-launch-recovery` to run `uv run nouc studio <app.py>` and diagnose build, Python or browser failures. A view build does not execute pending Python cells in the live editor.

3. **Consult & Update Dual-Tier Adaptive Memory**:
   - Before generating or debugging code, inspect active prevention rules:
     ```bash
     uv run nouc memory rules
     ```
   - Whenever you encounter an error (`ruff`, `ty`, `marimo` reactive DAG, `pydantic-monty`, `pointblank`, `marimo-studio`) and verify a fix, record it in local (`.insights/memory/`) and global (`~/.nouc-studio/memory/`) memory:
     ```bash
     uv run nouc memory record --library "<lib>" --error "<err>" --fix "<fix>" --rule "<rule>"
     ```

4. **Graph-First Lineage & Epistemic Humility**:
   - Every ingested source, transformation, Pointblank validation check, and KPI must be registered in `LineageGraphEngine` (`rustworkx.PyDiGraph`).
   - Every output number must carry an `UncertaintyProfile` (uncertainty or sensitivity bounds where supported, `±%` epistemic uncertainty, `TrustGrade` A–F, and explicit assumptions/caveats). Do not label heuristic sensitivity ranges as statistical 95% confidence intervals.

5. **Verification Gate Before Completion**:
   - Run the applicable static, type, sandbox and domain checks before completion:
     ```bash
     uv run nouc verify <app.py> --ty
     uv run ruff check src tests
     uv run ty check src tests
     uv run pytest -v
     ```
   - For UI deliverables, also pass the desktop browser acceptance gate above.
