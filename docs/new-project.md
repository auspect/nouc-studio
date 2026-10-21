# Start a new project with uv and VS Code Copilot

Use a published wheel. You need uv, VS Code and a connected GitHub Copilot
extension. No clone of the Nouc development repository or model API key is
required for this Copilot workflow. Nouc's internal model configuration is a
separate option; an IDE subscription does not supply API credentials to Python.

## Development package from TestPyPI (PowerShell)

Start in the parent directory of the new project. Choose an unused directory name:

```powershell
uv init --bare --python 3.13 my-studio
Set-Location my-studio
uv python pin 3.13

@'

[tool.uv.sources]
nouc-studio = { index = "testpypi" }

[[tool.uv.index]]
name = "testpypi"
url = "https://test.pypi.org/simple/"
explicit = true
'@ | Add-Content pyproject.toml

$noucVersion = (Invoke-RestMethod https://test.pypi.org/pypi/nouc-studio/json).info.version
uv add "nouc-studio[verify]==$noucVersion"
uv run nouc init --agent copilot
code .
```

The named index is explicit: only Nouc comes from TestPyPI, while dependencies
come from PyPI. The chosen Nouc version and dependency hashes are saved in
`uv.lock`. Python 3.13 is an example supported runtime; the pin records the
interpreter choice. Run `uv sync --locked` on later checkouts.

For a release available on PyPI, omit the TestPyPI configuration and use
`uv add "nouc-studio[verify]"` instead. The `verify` extra supplies Ruff, ty and
pytest; they are consumer tools, not installed by writing agent instructions.

## One-shot initialization with uvx

For the PyPI release candidate, an isolated CLI invocation can initialize an
existing project directory without first installing Nouc into that project:

```powershell
uvx --python 3.13 --from "nouc-studio==0.1.0rc1" nouc init --agent copilot
```

The explicit prerelease pin selects the candidate. `uvx` runs in its own
environment and does not add project dependencies or create a project lock.
An application that imports Nouc, Marimo or its other libraries still needs its
own dependencies, for example `uv add "nouc-studio[verify]==0.1.0rc1"`, followed
by `uv run` for builds, tests and execution. Keep the `uv` project workflow above
for reproducible application development. See the official
[uv tool isolation guide](https://docs.astral.sh/uv/guides/tools/).

## Use Copilot

In the chat agent selector choose **Nouc Studio**. If the folder was already open
before initialization, reopen it or reload VS Code to refresh agent discovery.
Then send your ordinary business prompt. Follow any normal workspace trust and
tool permission prompts presented by VS Code.

The agent asks contextual business questions, saves a working brief, and designs
the interface before implementation. The bundled UI/UX skill prioritizes desktop
task flow, readable tables, useful controls and progressive disclosure. It uses
a specialist subagent where the host supports delegation, or an explicit design
review otherwise. It does not require a particular model or invent a tool.

The public `nouc_studio.studio.generator.render_studio_view_html` helper provides
a compact Studio shell with section tabs (or a section selector for many panels).
Related controls and results should be composed into cohesive task panels before
passing them to the shell. This helper is optional when a custom interface better
serves the brief; the multi-view runtime and verification requirements still apply.

Verify actual inputs, edits, navigation and data updates in the running Studio.
A static or generic verification pass alone cannot detect every widget or layout
failure inside a projected view. Desktop checks are the default; mobile checks
are needed only when the requested product calls for them.

## Repeat, upgrade or inspect initialization

```powershell
uv run nouc init --agent copilot --dry-run
uv run nouc init --agent copilot
uv run nouc models
```

`init` writes eight managed resources: `AGENTS.md`, the Copilot instructions and
agent definition, and five `skills/*/SKILL.md` files. Its versioned manifest is
`.nouc-studio/bootstrap.json`. Keep these files in your application's Git history.
An identical rerun does not rewrite them. On an upgrade, unchanged managed files
can be updated; user edits or unrelated existing files cause a conflict before
the initializer writes anything.

Inspect conflicts before choosing `--overwrite`. Explicit replacement backs up
the old content under `.nouc-studio/bootstrap-backups/`, which is locally ignored
by Git. The initializer does not install dependencies, run a build, create a
remote, or modify global IDE settings. Installation and package imports have no
bootstrap side effects.

For developing Nouc itself, the canonical resources remain in this repository.
The installed-wheel initializer intentionally does not fall back to a source
checkout when its bundled assets are missing. Build and test the wheel as
described in [publishing](publishing.md).
