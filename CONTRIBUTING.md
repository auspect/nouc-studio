# Contributing to Nouc Studio

Thank you for contributing to **Nouc Studio**! Please follow these engineering principles when submitting changes:

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
- Every output metric must propagate quantitative and epistemic uncertainty (`UncertaintyProfile`, 95% confidence interval, `TrustGrade` A–F, and explicit assumptions/caveats).

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
uv run ruff check src tests
uv run ty check src tests
uv run pytest -v
```
