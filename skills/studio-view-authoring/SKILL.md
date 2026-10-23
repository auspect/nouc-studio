---
name: studio-view-authoring
description: >-
  Create or extend marimo-studio views from a shared reactive notebook. Use when
  choosing an overview, explorer, operations screen, briefing or report, wiring
  projections, or adapting official Studio examples. Complements the business
  brief and desktop review; does not replace notebook calculations with UI code.
---

# Author task-oriented Studio views

Start from the agreed business brief and the desktop screen plan required by
[studio-experience-design](../studio-experience-design/SKILL.md). Reuse answers
already given. Consult [concrete example patterns](references/example-patterns.md)
when choosing views; a generic dashboard is not the only useful presentation.

## Ground the installed version

Use the project's environment, not an independently upgraded `uvx` environment:

```bash
uv run nouc ground --module marimo_studio.authoring --symbol open_workspace
uv run python -c "from nouc_studio.verification import load_installed_marimo_studio_skill_reference as read; print(read('projections.md'))"
```

Read the installed skill's setup/provider reference when selecting a starter.
Use `await workspace.status()` to discover the view root and
`await workspace.starters()` to inspect available providers. The October 2026
website describes a newer minor release than Nouc's tested Studio 0.3.0:
never hardcode the website's `studio/<stem>/` location into a 0.3 app.

## Give the notebook a projection contract

Keep ingestion, units, filters, domain calculations, QA, uncertainty and result
selection in Python. Export named results for the views:

| Projection | Use |
| --- | --- |
| `<marimo-cell name="controls"></marimo-cell>` | Display a named cell, including native interactive controls |
| `<marimo-output value="trend_chart"></marimo-output>` | Display a Python object's rich output |
| `<strong mo-value="summary.total"></strong>` | Bind a JSON-compatible field without copying its number into HTML |

Cell names and exported variable names differ. Read the notebook or call
`await workspace.inspect_notebook(include_code=True)` to resolve them. Create
controls in one cell and read their `.value` in downstream cells. A UI filter
must update the relevant metric, evidence and warning together. Browser-only
selection over a notebook-supplied table is useful, but do not silently give it
different business definitions from Python.

For custom renderers, read the installed projections reference, consume updates
and preserve missing-data labels and provenance. Computed projection targets
need a finite declared set or the supported `data-marimo-allow="*"` boundary.

## Build a small working view first

For saved-file authoring, use `open_workspace(Path("app.py"))`; inside a live
marimo-pair execution use `marimo_studio.agent.current_workspace()`. Await
workspace and view operations. Read the view's generated `AGENTS.md` before
editing its source. The following is a small edit pattern, not a whole app:

Preserve the starter's document structure and its `app-shell` host. Replace its
content areas; do not substitute a bare HTML fragment for a provider entry file.

```python
from pathlib import Path
from marimo_studio.authoring import open_workspace

workspace = open_workspace(Path("app.py"))
view = workspace.view("main")  # create through workspace.create_view if absent
document = await view.read("index.html")
# new_html contains projections of existing notebook results.
await view.write("index.html", new_html, expected_revision=document.revision)
await view.build(profile="development")
report = await view.validate(level="static")
assert report.ok, report.issues
```

Use the guarded revision returned by `read`; on conflict, read and reconcile the
other author's change. Edit provider sources, never `.artifacts/`. Start with
Vanilla for simple HTML. Add Deno for providers that require it, or Quarto / Typst
/ Tectonic only when the brief needs the corresponding document format and the
installed Studio version supports it. Verify tool availability in the serving
environment before expanding the view.

## Finish with observable evidence

Apply [studio-launch-recovery](../studio-launch-recovery/SKILL.md) to build, run
and diagnose. Runtime validation executes saved notebook Python in isolation;
it does not update an open editor. After Python edits, execute changed cells
in the live notebook. In a browser, wait for Studio readiness and exercise the
brief's real control → result → evidence flow at both desktop sizes. Record
which interactions passed and which remain unverified.
