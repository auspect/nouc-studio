---
name: adaptive-failure-memory
description: >-
  Self-evolving dual-tier memory (Local Project .insights/memory/ + Global Cross-Project
  ~/.nouc-studio/memory/) backed by DuckDB, Rustworkx graphs, and JSONL.
  Mandates querying known failure remedies before coding and recording every verified fix.
---

# Adaptive Failure & Fix Memory Skill

## Core Loop: Never Repeat the Same Mistake Twice

Every agent in `nouc-studio` is connected to a **Dual-Tier Adaptive Memory Store** (`AdaptiveMemoryStore`):
1. **Local Project Memory** (`.insights/memory/`): Tracks project-specific failures, root causes, and verified code patches in `memory.duckdb`, `episodes.jsonl`, and `memory_graph.json` (`rustworkx` DAG).
2. **Global Cross-Project Memory** (`~/.nouc-studio/memory/`): Automatically receives every verified fix so all future projects inherit the accumulated engineering wisdom.

## Mandatory Agent Protocol

### Privacy and Version Control

Keep both raw memory stores local. Ignore the entire `.insights/memory/`
directory in the project's Git rules, including `episodes.jsonl`; an existing
tracked file must be explicitly untracked while preserving its local copy.
Raw errors, snippets and cross-project episodes may contain credentials,
business inputs, prompts or identifying paths. Do not commit, upload or package
them. Never include secrets in a recorded episode. Share only deliberately
reviewed and anonymized prevention rules in ordinary project documentation.
Ignoring or untracking files does not remove their earlier Git history; a
repository-publication review must consider historical copies separately.

### 1. Before Writing Code (Pre-Flight Memory Query)
Always load prevention rules for the target libraries (`marimo`, `marimo-studio`, `polars`, `pydantic-monty`, `pointblank`, `ty`, `ruff`) and inject them into the generation context:

```python
from nouc_studio.config import InsightsConfig
from nouc_studio.memory import AdaptiveMemoryStore

cfg = InsightsConfig()
store = AdaptiveMemoryStore(cfg.local_memory_dir, cfg.global_memory_dir)
rules = store.get_prevention_rules_for_prompt(["marimo", "marimo-studio", "polars"])
```

### 2. When Any Error or Verification Failure Occurs
Query `store.find_similar_failures(error_text, library=...)` to retrieve verified fixes from local or global cross-project history.

### 3. After Resolving an Error and Passing the Verification Gate
Immediately record the `(Failure -> RootCause -> VerifiedFix -> PreventionRule)` episode and promote it to global memory:

```python
store.record_failure_and_fix(
    stage=FailureStage.MARIMO_DAG,
    library="marimo",
    error_type="MultipleDefinitionError",
    error_message=raw_diagnostic,
    failing_code_snippet=old_code,
    root_cause="Variable was assigned in two separate cells.",
    verified_fix_description="Renamed downstream variable and prefixed local helper with `_`.",
    fixed_code_snippet=new_code,
    prevention_rule="Never assign the same global variable name in more than one @app.cell.",
    verified=True,
    promote_to_global=True,
)
```
