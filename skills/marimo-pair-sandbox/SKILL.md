---
name: marimo-pair-sandbox
description: >-
  Use Marimo and Pydantic Monty as verified reactive sandboxes for iterative development.
  Enforces zero pip (strictly uv/pixi), PEP 723 script metadata, acyclic cell graphs,
  live session inspection via marimo-pair, and microsecond formula verification via Monty.
---

# Marimo Pair & Monty Sandbox Skill

## Core Mandates (Zero Blind Trust & Zero `pip`)

1. **Strictly No `pip`**: Never invoke `pip` or `pip install`. Always use `uv` (`uv run`, `uv add`, `uv add --script <notebook.py> <pkg>`, `uvx`) or `pixi`.
2. **Never Edit Blindly**:
   - Before calling any library function or class, verify its signature in the live environment via `nouc_studio.verification.verify_live_python_symbol`.
   - Before committing complex calculations to a notebook cell, test the formula invariants in `MontySandboxRunner` (`pydantic-monty`).
3. **Marimo Reactive DAG Rules**:
   - Every non-underscore global variable MUST be defined in at most **one** `@app.cell` function.
   - Use `_` prefixes (e.g., `_row`, `_fig`, `_tmp`) for cell-local temporary variables.
   - Give every `@app.cell` a semantic function name (e.g., `def kpi_summary(...)`) so `marimo-studio` views can project it cleanly via `<marimo-cell name="kpi_summary"></marimo-cell>`.

## Desktop Experience Contract

Before UI code, apply [studio-experience-design](../studio-experience-design/SKILL.md)
and record its compact desktop screen plan in the agreed brief. Use a UI/UX
specialist subagent if the host supports it, otherwise an explicit self-review.
Choose task-oriented controls and compact readable tables; group related cells
into cohesive work panels rather than giving every cell a tall card or its own
tab. Keep long provenance, SQL and logs behind discoverable details, with warning
and exclusion summaries visible. Reuse intake answers; do not add cosmetic questions.

## Live Pairing Workflow (`marimo-pair`)

1. **Start or Attach to a Live Sandboxed Session**:
   ```bash
   uvx --with "marimo-studio[deno]" marimo edit app_notebook.py --sandbox --watch --no-token
   uvx --with marimo-studio marimo pair notebook list
   ```
2. **Execute & Inspect Live State in Code Mode**:
   ```bash
   uvx --with marimo-studio marimo pair execute --url <URL> --file <ABS_PATH> --code-file - <<'PY'
   import marimo_studio
   workspace = marimo_studio.agent.current_workspace()
   print(await workspace.status())
   PY
   ```
3. **Run Deterministic Verification Gate**:
   ```bash
   uv run nouc verify app_notebook.py --ty
   ```
   Check the reported reactive DAG, Ruff, runtime/layout and Ty results. Supply
   meaningful domain invariant checks separately: the CLI's generic Monty smoke
   assertion does not prove the application's calculations.
4. **Pass the Desktop Browser Gate**:
   Launch the actual Studio and follow `studio-experience-design` at the target
   and a smaller desktop viewport. Exercise the real task flows and empty/error
   states, inspect readability and scrolling, and resolve material UX findings.
   Static HTML checks and `app.run()` do not replace this rendered-browser check.
   When browser access is unavailable, identify the gate as unverified.

After editing a notebook or its views, regenerate the Studio artifacts, restart
the serving runtime and open a fresh browser session before acceptance checks.
Signed presentation capabilities are tied to the built artifacts and runtime;
stale sessions can produce misleading fetch or update failures.
For a custom HTML shell, ground
`nouc_studio.studio.generator.render_studio_runtime_support` and include its
returned script in the head to reuse the scoped virtual-file support.
