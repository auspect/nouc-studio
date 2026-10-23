---
name: studio-launch-recovery
description: >-
  Launch a Nouc marimo-studio app and diagnose failed builds, stale previews,
  missing projections or Python results that appear only after Run all. Use for
  run/edit/check commands, environment mismatches and browser verification;
  distinguish saved source, built views and live notebook execution.
---

# Launch and recover a Studio

Use the project environment containing both `marimo` and `marimo-studio`:

```bash
uv run nouc studio path/to/app.py
uv run nouc studio path/to/app.py --edit
uv run nouc studio path/to/app.py --check
```

The first command builds **production** views, validates saved projections and
starts `marimo run --no-sandbox` using the same Python. `--edit` builds
**development** views and starts `marimo edit --no-sandbox --watch`. `--check`
builds and executes isolated runtime validation, then exits without a server.
It can execute the notebook once per view, including its file/network work;
use trusted inputs and do not confuse it with a live-session refresh.

`--headless` keeps the server running without opening a browser. Open the local
URL printed by Marimo, including its token, and keep the terminal alive. Stop
with Ctrl+C. Use `--port 2720` if needed. The repository's `pixi run app`,
`pixi run edit` and `pixi run check-app` are shortcuts for the synthetic example;
append a notebook path to select another app. Consumer projects use the CLI
unless they have explicitly added equivalent Pixi tasks.

## Diagnose the failed stage

| Observation | Check and repair |
| --- | --- |
| No notebook or no Studio views | Check the path and `await workspace.status()`. Restore view sources together with the notebook. Discover `view_root`; Studio 0.3 uses `__marimo__/studio/<stem>/`, while newer versions use `studio/<stem>/`. Do not move folders based only on latest docs. |
| “Build failed” but a page is visible | The last successful artifact can remain visible. Read the failed build's source-located diagnostics, fix the source, rebuild the correct profile. A visible older page is not success. |
| Build passes but a projection is missing | Run `--check`; inspect named cells versus exported variables, notebook exceptions and provider diagnostics. Fix Python or the projection target. |
| Preview requests changed cells / Run all | Execute those cells or Run all **in the live notebook**, then use **Retry preview** if Studio still displays its repair panel. A view build and an isolated validation leave that session's Python state unchanged. |
| External Python edits do not appear | Ensure edit mode has `--watch`, inspect the live cell state and run pending cells. Resolve symlinked notebook paths. Restart only when the server/environment needs it. |
| HTTP 409 from an exact preview URL | Rebuild successful current source, obtain a new URL. Exact URLs pin a presentation revision, not merely an artifact hash. |
| Starter/tool unavailable | Inspect installed starter/provider requirements. Vanilla needs no Deno; framework/document providers may need extra tools. Install into the serving environment, then restart. |
| `marimo-studio` CLI crashes before parsing arguments | Capture versions and traceback locally. Nouc's launcher uses the public authoring API and native Marimo command. On the tested 0.3.0 stack this avoids the observed Click `ParamType` import error. Do not patch site-packages. |

## Inspect saved source without a live session

Use `marimo_studio.authoring.open_workspace(Path("app.py"))`. Await `status()`,
then `workspace.view(name).inspect()`. Read `latest_build.diagnostics`, including
code, source path/line, message and hint. The returned `freshness` is about the
development profile in the tested version; do not use it to conclude that a
production build failed. Never delete source folders or edit `.artifacts/` to
make an error disappear.

Read version-matched guidance if the symptom persists:

```bash
uv run python -c "from nouc_studio.verification import load_installed_marimo_studio_skill_reference as read; print(read('gotchas.md')); print(read('verification.md'))"
```

For standalone PEP 723 notebooks, a deliberately configured `--sandbox` workflow
is valid when its metadata declares all dependencies. Do not mix that environment
with Nouc's project launch and assume they share packages. Latest upstream
`--sandbox=pixi` recipes also require compatible Marimo and Pixi versions.

## Verify the actual preview

In a live pairing session, reacquire `marimo_studio.agent.current_workspace()`
for each code execution. Keep the editor browser tab connected. Call
`await view.show()` in its own execution; then obtain
`await view.preview_url(runtime="server")`. Finish the code execution before
browser automation waits for readiness: blocking the kernel can prevent the
page from becoming ready. A saved-file view needs an explicit server URL.

Open the fresh preview URL or enter its iframe. Wait for
`html[data-marimo-studio-state="ready"]` in that document. Change a real control
and assert the dependent text, chart or rows changed. Apply both desktop sizes
from [studio-experience-design](../studio-experience-design/SKILL.md).
If readiness stalls, inspect visible status, console errors and failed requests;
report a harness limitation separately from an application defect.

Keep diagnostics, tokenized URLs and screenshots local. Record only verified,
sanitized remedies through [adaptive-failure-memory](../adaptive-failure-memory/SKILL.md).
The public [upstream troubleshooting guide](https://marimo-team.github.io/marimo-studio/guide/troubleshooting.html)
is a secondary reference; recheck its version before applying a migration.
