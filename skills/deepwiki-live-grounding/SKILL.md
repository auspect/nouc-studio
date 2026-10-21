---
name: deepwiki-live-grounding
description: >-
  Eliminates reliance on stale LLM parametric knowledge by verifying library APIs,
  method signatures, TypedDict schemas, and upstream repository documentation via
  DeepWiki MCP (https://mcp.deepwiki.com/mcp), agent-plugins, and live runtime introspection.
---

# Zero-Blind-Trust Grounding Skill (DeepWiki + Live Introspection)

## Why This Skill Exists

LLMs frequently hallucinate deprecated APIs (e.g., `df.groupby` in Polars >=1.0 instead of `df.group_by`, synchronous calls on `marimo-studio` async view handles, or invalid `inspect.signature` calls on `TypedDict` classes like `pydantic_monty.ResourceLimits`).

**Rule**: Never assume you know a library's API from training weights alone. Always verify!

## Verification Protocol

### Step 1: Live Runtime Introspection (`verify_live_python_symbol`)
Before generating code that imports or calls a third-party symbol, inspect the actual installed package in the active `uv` environment:

```python
from nouc_studio.verification import verify_live_python_symbol

res = verify_live_python_symbol("pointblank", "Validate")
assert res.exists, res.error
print(res.kind, res.signature)
```

### Step 2: Packaged Agent Plugin Instructions (`agent-plugins`)
For libraries shipping native agent plugins (like `marimo-studio`), read their exact version-matched reference directly from the installed environment:

```bash
uvx --with marimo-studio agent-plugins read marimo-studio
```
Or in Python:
```python
from nouc_studio.verification import load_installed_marimo_studio_skill_reference
print(load_installed_marimo_studio_skill_reference("projections.md"))
```

### Step 3: DeepWiki MCP Repository Grounding
When integrating or debugging open-source libraries (`marimo-team/marimo`, `marimo-team/marimo-studio`, `posit-dev/pointblank`, `posit-dev/querychat`, `koaning/wigglystuff`, `pola-rs/polars`, `pydantic/monty`), query the DeepWiki MCP server (`https://mcp.deepwiki.com/mcp`):

```python
from nouc_studio.verification import DeepWikiClient

client = DeepWikiClient()
answer = client.ask_repo_question(
    repo="marimo-team/marimo-studio",
    question="How do I project a named cell and bind mo-value hosts in an HTML view?",
)
```
