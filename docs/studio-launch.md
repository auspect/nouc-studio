# Run, edit and diagnose a Studio

Use `nouc studio` from the project's uv environment. It builds the views for the
selected mode before starting Marimo, and reports the stage that failed.

## Try the repository example with Pixi

From the repository root:

```bash
pixi run example-build
pixi run app
```

The first command creates the synthetic example in `dist/public-example/` and
runs its checks. Run it once: it refuses to overwrite an existing directory.
On later visits, just run `pixi run app`. Marimo prints a local URL and normally
opens the browser. Keep the terminal running; Ctrl+C stops the app.

```bash
pixi run edit
pixi run check-app
pixi run app "path with spaces/app.py" --headless --port 2720
pixi run example-build --output dist/another-example
```

`edit` opens the Python/Studio editor with file watching. `check-app` builds and
executes Python checks without starting a web server. Each task accepts a
different notebook path; an explicit path takes precedence over the example
default. `--headless` starts a server without opening a browser, whereas
`--check` exits after validation.

Pixi supplies the existing workspace tools; these tasks delegate Python package
management to `uv.lock` through `uv run --locked`. They do not use Marimo's
separate Pixi notebook sandbox. The tasks were exercised with Pixi 0.77.0;
newer upstream `--sandbox=pixi` examples require a different supported stack.
First-time environment setup can download packages.

## Without Pixi, or in a consumer project

```bash
uv sync --locked
uv run nouc studio path/to/app.py
uv run nouc studio path/to/app.py --edit
uv run nouc studio path/to/app.py --check
```

In this checkout, create the example with
`uv run python examples/offline_walkthrough.py` and use
`dist/public-example/app.py`. In a consumer project, `nouc studio` with no path
defaults to `app.py`. The optional `NOUC_STUDIO_NOTEBOOK` environment variable
supplies another default; explicit arguments win.

`nouc init` installs the agent skills, including launch guidance. It does not
install this repository's Pixi manifest into a consumer project. To add simple
shortcuts to an existing Pixi project, merge these entries into its tasks:

```toml
[tasks]
app = "uv run --locked nouc studio app.py"
edit = "uv run --locked nouc studio app.py --edit"
check-app = "uv run --locked nouc studio app.py --check"
```

Keep both marimo and marimo-studio installed in that uv project. Nouc launches
the server with the same Python interpreter used to build views and passes
`--no-sandbox`. Copy the notebook, view sources and required data together when
moving an app. A notebook alone does not contain its Studio views.

## What each command proves

| Command | Build profile | Python execution | Result |
| --- | --- | --- | --- |
| `nouc studio app.py` | Production | By the live server when the app connects | Running app |
| `nouc studio app.py --edit` | Development | In the editor session | Editor watching external Python edits |
| `nouc studio app.py --check` | Production | Isolated runtime validation, potentially once per view | Exit status and diagnostics |
| `nouc studio app.py --edit --check` | Development | Isolated runtime validation | Check the preview profile without serving |
| `nouc verify app.py --ty` | Separate notebook gate | Notebook execution and configured checks | Structural/static/type checks |

The launcher checks all discovered views and their saved projection targets.
It stops on a failed build or validation instead of launching the retained older
artifact. Normal launch does not execute an extra isolated Python validation
first; use `--check` explicitly when diagnosing. This check executes notebook
file, network and database operations, so run it on trusted notebooks.
For slow notebooks, increase `--runtime-timeout 120`.

`nouc build` now returns nonzero when notebook verification, view validation,
data QA or explanation audits fail. It preserves the report for diagnosis.
Passing these checks still does not establish domain correctness or desktop UX.

## Preview recovery

There are four separate states: saved Python, saved view source, the built view
artifact and the Python running in a live browser session. Fix the failing stage:

| Symptom | Action |
| --- | --- |
| “Build failed”, yet the old page still displays | Read the build diagnostic, fix the named source and rebuild. Studio retains the last successful artifact. |
| HTML changes appear, but Python values do not | Run changed cells or **Run all** in the connected editor, then **Retry preview** if the repair panel remains. Building or isolated validation does not refresh that live session. |
| A cell or value projection is missing | Run `--check`; compare the named cell / exported variable with the view target and inspect Python exceptions. |
| Outside Python changes are missed | Use `--edit` (includes `--watch`); check pending cells. The launcher resolves the notebook path to avoid symlink watcher surprises. |
| An exact preview URL gives HTTP 409 | Build current source successfully and request a new preview URL. |
| No Studio views are found | Inspect `await workspace.status()` for the actual root. Check that the notebook and view folders use the same Studio version. |
| A provider cannot build | Inspect its required tools in the serving environment. Vanilla needs no Deno; add framework/PDF tools only for the selected supported provider. |
| A check passes but the browser is blank | Inspect the visible Studio state, browser console and failed requests. Use the Python server for native dependencies and local files. |

Agents should use the bundled
[launch recovery skill](../skills/studio-launch-recovery/SKILL.md). It covers
saved versus live workspaces, frame-aware browser checks and source-located
diagnostics. A screenshot of an earlier successful build is insufficient:
change a real control and verify its dependent result.

## Version evidence, checked 2026-10-23

The project environment uses marimo-studio 0.3.0 and marimo 0.25.1. In this
environment the upstream `marimo-studio` CLI fails on import with
`TypeError: type 'ParamType' is not subscriptable`. Nouc's launcher avoids that
entry point by using the public authoring API and native `python -m marimo`.
This is a verified local workaround, not a claim about every upstream release.

The current official documentation describes newer folder conventions and
toolchain requirements. Its [compatibility guide](https://marimo-team.github.io/marimo-studio/reference/compatibility.html)
explains the migration from 0.3. Consult the installed skill references before
applying current website recipes; do not move or delete view folders blindly.
The [upstream troubleshooting guide](https://marimo-team.github.io/marimo-studio/guide/troubleshooting.html)
documents retained artifacts, Python execution and preview revision behavior.

The companion [view-authoring skill](../skills/studio-view-authoring/SKILL.md)
adapts concrete official examples into reusable projection and workflow patterns.
Its [reference](../skills/studio-view-authoring/references/example-patterns.md)
covers interactive explanation, row exploration, operations and model review.

## Validation recorded on 2026-10-23

On Linux / Python 3.14.3, the 223 repository tests, Ruff and ty passed. Focused
tests cover failed rebuilds retaining an older artifact, Python runtime errors,
paths containing spaces, mode selection and CLI exit codes. Pixi's `check-app`
passed. Wheel and sdist inspection, Twine and an isolated installed-wheel
bootstrap check passed with all eleven managed resources.

A UI/UX specialist exercised the running app in Chromium at 1440×900 and
1280×800. A real scenario control changed the visible revenue total from
691,900 to 698,819 for +1%. In an isolated copy, an external Python edit reached
the watched editor; running the pending cells and retrying preview displayed
the new content with Studio ready. These checks establish launch and refresh
behavior, not complete acceptance of the example's analytical workflows.
