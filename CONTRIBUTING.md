# Contributing to Nouc Studio

Use the [public examples](examples/README.md) to reproduce the pipeline and the
[architecture guide](docs/architecture.md) to understand its current boundaries.
Review [public data and artifacts](docs/public-data.md) before staging changes.

Versions come from Git commits and release tags, never from a manually edited
package constant. See [Git versioning and tag-triggered publication](docs/publishing.md)
for development builds, the PyPI Trusted Publisher setup and release checks.

## 1. Zero `pip` Policy
- **Never** use `pip install` in scripts, documentation, or agent prompts.
- Exclusively use **`uv`** (`uv sync`, `uv add`, `uv run`) or **`pixi`** (`pixi run`).
- Standalone Marimo notebooks must declare dependencies using **PEP 723** inline `# /// script` headers.

## 2. Zero Blind Trust in Parametric Knowledge
- Before integrating or modifying calls to rapidly evolving libraries (`marimo`, `marimo-studio`, `polars`, `pointblank`, `pydantic-monty`, `google-genai`, `wigglystuff`), verify symbols empirically:
  ```bash
  uv run nouc ground --module <module_name> --symbol <SymbolName>
  ```
- When needed, query upstream repository documentation via the DeepWiki MCP integration (`--repo owner/repo --question "..."`).

## 3. Graph-First Lineage & Epistemic Humility
- All data sources, transformations, validations, and KPIs must be registered as typed nodes and edges in `LineageGraphEngine` (`rustworkx.PyDiGraph`).
- Every output metric must carry an `UncertaintyProfile`, a `TrustGrade` and
  explicit assumptions/caveats. Label heuristic sensitivity ranges with their
  method; reserve statistical confidence intervals for a justified statistical
  model. Represent unsupported uncertainty as unknown rather than zero.

## 4. Dual-Tier Self-Healing Memory
- Keep the entire `.insights/memory/` directory and the global store untracked.
  Raw episodes may contain business data, local paths or diagnostic snippets.
  Share reviewed, anonymized rules in documentation rather than raw JSONL.
- Whenever you encounter a non-trivial failure (`ruff`, `ty`, `marimo` reactive DAG, `pydantic-monty`, `pointblank`, or `marimo-studio` build/validation) and verify a fix, record it so both the project-local (`.insights/memory/`) and global (`~/.nouc-studio/memory/`) stores learn from it:
  ```bash
  uv run nouc memory record \
    --library "<library>" \
    --error "<error signature>" \
    --fix "<verified fix>" \
    --rule "<actionable prevention rule>"
  ```

## 5. Pre-Commit Verification Gate
Before opening a Pull Request, ensure all checks pass with zero warnings/errors:
```bash
uv run ruff check src tests scripts examples/offline_walkthrough.py examples/ui_contract.py
uv run ty check src tests scripts examples/offline_walkthrough.py examples/ui_contract.py
uv run pytest -v
```

Run changed examples using their documented commands. For UI changes, also
exercise the real Studio at the target and a smaller desktop viewport, following
[studio-experience-design](skills/studio-experience-design/SKILL.md).
