"""Dual-tier (Local Project + Global Cross-Project) Adaptive Memory Store using DuckDB, Rustworkx, and JSONL."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import rustworkx as rx

from nouc_studio.memory.models import (
    FailureEpisode,
    FailureStage,
    compute_episode_id,
    normalize_error_signature,
)


def _builtin_seed_episodes() -> list[FailureEpisode]:
    """Return empirically verified baseline failure-to-fix episodes across the SOTA stack."""
    seeds: list[dict[str, Any]] = [
        {
            "stage": FailureStage.MARIMO_DAG,
            "library": "marimo",
            "error_type": "MultipleDefinitionError",
            "error_message": "Variable 'df' is defined in multiple cells.",
            "failing_code_snippet": "# Cell 1: df = pl.read_parquet(...)\n# Cell 2: df = df.filter(...)",
            "root_cause": "Marimo enforces a reactive DAG where every global variable name is defined in at most one cell.",
            "verified_fix_description": "Use distinct semantic variable names across cells (e.g., raw_orders -> filtered_orders -> segment_summary) or prefix cell-local temporaries with an underscore (_tmp).",
            "fixed_code_snippet": "# Cell 1: raw_orders = pl.read_parquet(...)\n# Cell 2: filtered_orders = raw_orders.filter(...)",
            "prevention_rule": "Never redefine the same non-underscore variable across two marimo cells; use distinct domain names or `_` prefix for cell-local variables.",
        },
        {
            "stage": FailureStage.STUDIO_BUILD,
            "library": "marimo-studio",
            "error_type": "RuntimeWarning",
            "error_message": "RuntimeWarning: coroutine 'Workspace.status' was never awaited",
            "failing_code_snippet": "workspace = marimo_studio.agent.current_workspace()\nstatus = workspace.status()",
            "root_cause": "Methods on marimo-studio workspace and view handles (status(), build(), show(), inspect(), read(), write(), preview_url()) are async coroutines.",
            "verified_fix_description": "Always `await` workspace and view operations (e.g. `await workspace.status()`, `await view.build()`).",
            "fixed_code_snippet": "workspace = marimo_studio.agent.current_workspace()\nstatus = await workspace.status()",
            "prevention_rule": "Always `await` async methods (`status`, `build`, `inspect`, `read`, `write`, `show`, `preview_url`) on marimo_studio workspace and view handles.",
        },
        {
            "stage": FailureStage.STUDIO_BUILD,
            "library": "marimo-studio",
            "error_type": "projection-target-not-allowed",
            "error_message": "projection-target-not-allowed after changing mo-value at runtime",
            "failing_code_snippet": '<span id="details" hidden mo-value="default_details"></span>',
            "root_cause": "Dynamic runtime changes to `mo-value` in the browser are blocked unless the host element explicitly declares `data-marimo-allow=\"*\"`.",
            "verified_fix_description": "Add `data-marimo-allow=\"*\"` to any projection host whose `mo-value` selector is updated dynamically in browser JS.",
            "fixed_code_snippet": '<span id="details" hidden mo-value="default_details" data-marimo-allow="*"></span>',
            "prevention_rule": "Include `data-marimo-allow=\"*\"` on any HTML host whose `mo-value` attribute changes at runtime, and keep `mo-value` payloads under 1 MB JSON / 64 MiB Arrow.",
        },
        {
            "stage": FailureStage.MONTY_SANDBOX,
            "library": "pydantic-monty",
            "error_type": "ValueError",
            "error_message": "no signature found for builtin type <class 'dict'> when inspecting ResourceLimits",
            "failing_code_snippet": "inspect.signature(pydantic_monty.ResourceLimits)",
            "root_cause": "`pydantic_monty.ResourceLimits` is a `TypedDict` subclass (runtime `dict`), not a standard class with a custom `__init__` signature.",
            "verified_fix_description": "Inspect `ResourceLimits.__annotations__` for TypedDict schema keys (`max_feed_duration_secs`, `max_turn_duration_secs`, `max_memory`, `max_recursion_depth`).",
            "fixed_code_snippet": "keys = list(pydantic_monty.ResourceLimits.__annotations__.keys())",
            "prevention_rule": "When introspecting TypedDict classes like `pydantic_monty.ResourceLimits`, read `__annotations__` before calling `inspect.signature()`.",
        },
        {
            "stage": FailureStage.RUNTIME_EXECUTION,
            "library": "polars",
            "error_type": "AttributeError",
            "error_message": "'DataFrame' object has no attribute 'groupby'",
            "failing_code_snippet": "df.groupby('category').agg(pl.col('amount').sum())",
            "root_cause": "Polars >=1.0 removed `.groupby()` in favor of `.group_by()`.",
            "verified_fix_description": "Replace `.groupby(...)` with `.group_by(...)` and use expression-based aggregations.",
            "fixed_code_snippet": "df.group_by('category').agg(pl.col('amount').sum())",
            "prevention_rule": "In Polars >=1.0/2.0, always use `.group_by()` (with underscore) instead of `.groupby()`, and `pl.read_excel()` with `fastexcel` engine.",
        },
        {
            "stage": FailureStage.RUNTIME_EXECUTION,
            "library": "duckdb",
            "error_type": "ModuleNotFoundError",
            "error_message": "No module named 'pyarrow' when calling conn.execute(sql).pl() on registered Polars DataFrame",
            "failing_code_snippet": "conn.register('tbl', df); conn.execute(sql).pl()",
            "root_cause": "DuckDB's `.pl()` and Polars registration rely on Arrow zero-copy interchange requiring `pyarrow`, unless `pl.SQLContext` is used as a fallback.",
            "verified_fix_description": "Add `pyarrow` via `uv add pyarrow` and provide a fallback to `pl.SQLContext(tables).execute(sql, eager=True)`.",
            "fixed_code_snippet": "ctx = pl.SQLContext(tables); res_df = ctx.execute(sql, eager=True)",
            "prevention_rule": "Include `pyarrow` in project dependencies when using `duckdb.execute(sql).pl()`, and keep `pl.SQLContext(tables).execute(sql, eager=True)` as a zero-dependency Rust fallback.",
        },
        {
            "stage": FailureStage.STUDIO_BUILD,
            "library": "marimo-studio",
            "error_type": "ViewProjectError",
            "error_message": "artifact-publication-failed: [Errno 2] No such file or directory: '.../__marimo__/studio/<notebook>/<view>/.artifacts/.staging/candidate-<hex>/publication/.marimo-studio-write-<hex>'",
            "failing_code_snippet": "await view.build()  # inside a deeply nested Windows path (>110 chars)",
            "root_cause": "On Windows, marimo-studio's staging path appends ~145 characters (`__marimo__/studio/<nb>/<view>/.artifacts/.staging/candidate-<32hex>/publication/.marimo-studio-write-<32hex>`), exceeding Windows MAX_PATH (260 chars) if the base path or view/notebook names are long.",
            "verified_fix_description": "Use compact notebook names (`app.py`) and concise view slugs (`main`, `audit`, `ops`), and keep workspace output directories under 100 chars on Windows.",
            "fixed_code_snippet": "notebook_path = output_dir / 'app.py'; view = await workspace.create_view('main')",
            "prevention_rule": "On Windows, keep marimo-studio notebook filenames (`app.py`) and view slugs (`main`, `audit`, `ops`) short so `.artifacts/.staging/candidate-...` paths never exceed the 260-char MAX_PATH limit.",
        },
        {
            "stage": FailureStage.RUNTIME_EXECUTION,
            "library": "google-genai / pydantic-ai",
            "error_type": "ImportError",
            "error_message": "Legacy google-gla: prefix, outdated 2025 model names, and missing google-genai dependency in pydantic-ai-slim",
            "failing_code_snippet": "Agent('google-gla:gemini-2.5-pro')  # legacy prefix & outdated parametric model ID",
            "root_cause": "pydantic-ai 2.x migrated from deprecated google-generativeai (google-gla:) to the unified google-genai SDK (from google.genai import Client) and provides current frontier model IDs in pydantic_ai.models.KnownModelName.",
            "verified_fix_description": "Include `google-genai>=1.0.0` and `pydantic-ai-slim[google]>=2.0.0` in pyproject.toml, introspect `pydantic_ai.models.KnownModelName`, and use current frontier models (`google:gemini-3.8-flash`, `google:gemini-4-argon`, `anthropic:claude-sonnet-5-5`, `openai:gpt-6-sol`, `ollama:qwen3-coder:30b`).",
            "fixed_code_snippet": "Agent('google:gemini-3.8-flash')  # or 'google:gemini-4-argon', 'anthropic:claude-sonnet-5-5', 'openai:gpt-6-sol'",
            "prevention_rule": "Never rely on outdated LLM parametric model names or legacy google-gla: prefixes; always introspect `pydantic_ai.models.KnownModelName` and use current frontier IDs (`google:gemini-3.8-flash`, `google:gemini-4-argon`, `anthropic:claude-sonnet-5-5`, `openai:gpt-6-sol`, `ollama:qwen3-coder:30b`).",
        },
        {
            "stage": FailureStage.MARIMO_DAG,
            "library": "marimo",
            "error_type": "SameCellUIValueError",
            "error_message": "RuntimeError: Accessing the value of a UIElement in the cell that created it is not allowed. Fix: move the value access to another cell.",
            "failing_code_snippet": "@app.cell\ndef my_cell(mo):\n    dropdown = mo.ui.dropdown(options=['a', 'b'], value='a')\n    selected = dropdown.value\n    return dropdown, selected",
            "root_cause": "Marimo's reactive execution model binds `.value` updates to downstream cells that take the UIElement as a parameter; reading `widget.value` in the same cell that constructs `widget` raises a RuntimeError at runtime.",
            "verified_fix_description": "Split UI control creation into an upstream `@app.cell` that returns the widget, and read `widget.value` in a downstream `@app.cell` that accepts the widget as a parameter.",
            "fixed_code_snippet": "@app.cell\ndef controls_cell(mo):\n    dropdown = mo.ui.dropdown(options=['a', 'b'], value='a')\n    return (dropdown,)\n\n@app.cell\ndef consumer_cell(dropdown):\n    selected = dropdown.value\n    return (selected,)",
            "prevention_rule": "Never read `widget.value` in the same `@app.cell` that creates `widget = mo.ui.*(...)`; always export `widget` and read `widget.value` in a downstream cell.",
        },
        {
            "stage": FailureStage.RUNTIME_EXECUTION,
            "library": "wigglystuff",
            "error_type": "TypeError",
            "error_message": "Hint.__init__() got an unexpected keyword argument 'text' / AttributeError: 'Hint' object has no attribute 'comm'",
            "failing_code_snippet": "sensitivity_hint = mo.ui.anywidget(Hint(sensitivity_slider, text='Adjust sensitivity'))",
            "root_cause": "`wigglystuff.Hint` signature is `Hint(target: Any, note: Any, *, side: str = 'right', color: str = 'currentColor', gap: float = 3)`. Unlike `TangleSlider` (an `AnyWidget`), `Hint` is a native Marimo display helper (`_mime_()`) that requires `mo.running_in_notebook() == True`.",
            "verified_fix_description": "Wrap `TangleSlider` in `mo.ui.anywidget(...)`, but do NOT wrap `Hint` in `mo.ui.anywidget(...)`; guard `Hint(target, note=...)` with `if mo.running_in_notebook() else mo.md(...)` so both `app.run()` and live notebook runtimes succeed.",
            "fixed_code_snippet": "guided = Hint('Guide', note='Adjust multiplier') if mo.running_in_notebook() else mo.md('Adjust multiplier')",
            "prevention_rule": "In `wigglystuff`, wrap `AnyWidget` subclasses (`TangleSlider`) in `mo.ui.anywidget(...)`, and use `Hint(target, note=...) if mo.running_in_notebook() else mo.md(...)` without `mo.ui.anywidget`.",
        },
        {
            "stage": FailureStage.MARIMO_DAG,
            "library": "marimo",
            "error_type": "UnboundCellParameterError",
            "error_message": "Cell parameter 'header_overview' is not defined by any cell in the notebook (cell function name used instead of exported variable 'header_block').",
            "failing_code_snippet": "@app.cell\ndef header_overview(mo):\n    header_block = mo.md('# Title')\n    return (header_block,)\n\n@app.cell\ndef main_tabs(header_overview):\n    return (header_overview,)",
            "root_cause": "In Marimo, reactive dependencies between `@app.cell` functions are resolved by matching parameter names to exported return variable names, NOT upstream cell function names.",
            "verified_fix_description": "Ensure every parameter of an `@app.cell` function matches an exact variable name returned by an upstream `@app.cell`.",
            "fixed_code_snippet": "@app.cell\ndef main_tabs(header_block):\n    return (header_block,)",
            "prevention_rule": "Every `@app.cell` parameter must match an exported variable name from an upstream cell, never the upstream cell's function name.",
        },
        {
            "stage": FailureStage.VISUAL_INSPECTION,
            "library": "marimo-studio",
            "error_type": "VisualLayoutAndRuntimeError",
            "error_message": "Horizontal overflow from >4 KPI cards in a single mo.hstack and unreadable 100+ node full-workspace Mermaid diagram; static view validation missed cell runtime errors.",
            "failing_code_snippet": "mo.hstack(_all_24_cards, widths='equal'); mo.mermaid(lineage.to_mermaid()); await view.validate(level='static')",
            "root_cause": "Placing all 24 KPI cards in one horizontal row squishes cards to <40px width; rendering the entire workspace lineage graph (>100 nodes) in one Mermaid SVG is unreadable; `level='static'` does not execute cells.",
            "verified_fix_description": "Arrange top 6 hero KPI cards in a 2x3 responsive grid (`mo.hstack` of max 3 cards per row) + a searchable `mo.ui.table` registry, scope Mermaid diagrams to the selected metric's upstream lineage subgraph (<=25 nodes), and enforce `await view.validate(level='runtime')` + `app.run()`.",
            "fixed_code_snippet": "await view.validate(level='runtime', runtime_timeout=60.0)",
            "prevention_rule": "Cap `mo.hstack` card rows at <=3 cards per row, scope Mermaid diagrams to <=30 nodes (metric subgraph), and always run `app.run()` + `await view.validate(level='runtime')` to verify generated apps functionally and visually.",
        },
        {
            "stage": FailureStage.VISUAL_INSPECTION,
            "library": "marimo / katex",
            "error_type": "VisualKaTeXSyntaxError",
            "error_message": "KaTeX parse error: Unescaped underscore '_' inside \\text{expansion_arr_usd} renders formula in red error text.",
            "failing_code_snippet": r"formula_latex = rf'\Sigma_{\text{' + safe_col + r'}} = \sum_{i=1}^{N} x_{i,\text{' + safe_col + r'}}'",
            "root_cause": "In KaTeX / LaTeX, raw underscores `_` inside `\\text{...}` or `\\mathrm{...}` are invalid math-mode subscripts and cause a red KaTeX parse error in the browser.",
            "verified_fix_description": "Sanitize all identifiers inside `\\text{...}` by replacing underscores with spaces (`latex_col = re.sub(r'[^a-zA-Z0-9 ]+', ' ', human_col).strip()`) and render equations in clean `$$...$$` display blocks.",
            "fixed_code_snippet": r"latex_col = safe_col.replace('_', ' '); formula_latex = rf'\Sigma_{\text{' + latex_col + r'}}'",
            "prevention_rule": "Never place raw underscores `_` inside LaTeX `\\text{...}` or `\\mathrm{...}` blocks; replace underscores with spaces and place `$$...$$` display formulas on their own line.",
        },
    ]

    episodes: list[FailureEpisode] = []
    for item in seeds:
        sig = normalize_error_signature(item["error_type"], item["error_message"])
        ep_id = compute_episode_id(item["stage"].value, item["library"], sig)
        episodes.append(
            FailureEpisode(
                episode_id=ep_id,
                project_name="global-seed",
                stage=item["stage"],
                library=item["library"],
                error_type=item["error_type"],
                error_message=item["error_message"],
                normalized_signature=sig,
                failing_code_snippet=item["failing_code_snippet"],
                root_cause=item["root_cause"],
                verified_fix_description=item["verified_fix_description"],
                fixed_code_snippet=item["fixed_code_snippet"],
                prevention_rule=item["prevention_rule"],
                verified=True,
            )
        )
    return episodes


class AdaptiveMemoryStore:
    """Self-evolving dual-tier memory store (Project Local + Global Cross-Project) backed by DuckDB, Rustworkx, and JSONL."""

    def __init__(
        self,
        local_dir: Path,
        global_dir: Path,
        project_name: str = "nouc-studio",
    ) -> None:
        self.local_dir = local_dir
        self.global_dir = global_dir
        self.project_name = project_name

        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.global_dir.mkdir(parents=True, exist_ok=True)

        self.local_jsonl = self.local_dir / "episodes.jsonl"
        self.global_jsonl = self.global_dir / "global_episodes.jsonl"
        self.local_db_path = self.local_dir / "memory.duckdb"
        self.global_db_path = self.global_dir / "global_memory.duckdb"
        self.graph_path = self.local_dir / "memory_graph.json"

        self._graph: rx.PyDiGraph[dict[str, str], str] = rx.PyDiGraph()
        self._node_indices: dict[str, int] = {}

        self._init_storage()
        self._seed_if_empty()
        self._rebuild_in_memory_graph()

    def _init_storage(self) -> None:
        """Initialize DuckDB tables in both local and global memory databases."""
        ddl = """
        CREATE TABLE IF NOT EXISTS failure_episodes (
            episode_id VARCHAR PRIMARY KEY,
            project_name VARCHAR,
            stage VARCHAR,
            library VARCHAR,
            error_type VARCHAR,
            error_message VARCHAR,
            normalized_signature VARCHAR,
            failing_code_snippet VARCHAR,
            root_cause VARCHAR,
            verified_fix_description VARCHAR,
            fixed_code_snippet VARCHAR,
            prevention_rule VARCHAR,
            verified BOOLEAN,
            hit_count INTEGER,
            created_at VARCHAR,
            last_seen_at VARCHAR
        );
        """
        for db_path in (self.local_db_path, self.global_db_path):
            with duckdb.connect(str(db_path)) as conn:
                conn.execute(ddl)

    def _seed_if_empty(self) -> None:
        """Ensure all builtin seed episodes exist in global and local stores."""
        with duckdb.connect(str(self.global_db_path)) as conn:
            existing_global_ids = {
                str(r[0]) for r in conn.execute("SELECT episode_id FROM failure_episodes").fetchall()
            }
        for ep in _builtin_seed_episodes():
            if ep.episode_id not in existing_global_ids:
                self.record_episode(ep, promote_to_global=True)
        self.sync_from_global()

    def _upsert_into_db(self, db_path: Path, jsonl_path: Path, episode: FailureEpisode) -> FailureEpisode:
        """Insert or increment hit_count for an episode in a DuckDB database and append to JSONL."""
        now_iso = datetime.now(UTC).isoformat()
        with duckdb.connect(str(db_path)) as conn:
            existing = conn.execute(
                "SELECT hit_count, created_at FROM failure_episodes WHERE episode_id = ?",
                [episode.episode_id],
            ).fetchone()
            if existing is not None:
                new_hits = int(existing[0]) + 1
                created_at = str(existing[1])
                updated = episode.model_copy(
                    update={"hit_count": new_hits, "created_at": created_at, "last_seen_at": now_iso}
                )
                conn.execute(
                    """
                    UPDATE failure_episodes
                    SET hit_count = ?,
                        last_seen_at = ?,
                        verified_fix_description = ?,
                        fixed_code_snippet = ?,
                        prevention_rule = ?,
                        verified = ?
                    WHERE episode_id = ?
                    """,
                    [
                        updated.hit_count,
                        updated.last_seen_at,
                        updated.verified_fix_description,
                        updated.fixed_code_snippet,
                        updated.prevention_rule,
                        updated.verified,
                        updated.episode_id,
                    ],
                )
            else:
                updated = episode
                conn.execute(
                    """
                    INSERT INTO failure_episodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        updated.episode_id,
                        updated.project_name,
                        updated.stage.value,
                        updated.library,
                        updated.error_type,
                        updated.error_message,
                        updated.normalized_signature,
                        updated.failing_code_snippet,
                        updated.root_cause,
                        updated.verified_fix_description,
                        updated.fixed_code_snippet,
                        updated.prevention_rule,
                        updated.verified,
                        updated.hit_count,
                        updated.created_at,
                        updated.last_seen_at,
                    ],
                )

        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(updated.model_dump(mode="json")) + "\n")
        return updated

    def record_failure_and_fix(
        self,
        *,
        stage: FailureStage,
        library: str,
        error_type: str,
        error_message: str,
        root_cause: str,
        verified_fix_description: str,
        prevention_rule: str,
        failing_code_snippet: str = "",
        fixed_code_snippet: str = "",
        verified: bool = True,
        promote_to_global: bool = True,
    ) -> FailureEpisode:
        """Record a newly encountered failure and its fix locally, and promote to global cross-project memory."""
        sig = normalize_error_signature(error_type, error_message)
        ep_id = compute_episode_id(stage.value, library, sig)
        episode = FailureEpisode(
            episode_id=ep_id,
            project_name=self.project_name,
            stage=stage,
            library=library,
            error_type=error_type,
            error_message=error_message,
            normalized_signature=sig,
            failing_code_snippet=failing_code_snippet,
            root_cause=root_cause,
            verified_fix_description=verified_fix_description,
            fixed_code_snippet=fixed_code_snippet,
            prevention_rule=prevention_rule,
            verified=verified,
        )
        return self.record_episode(episode, promote_to_global=promote_to_global)

    def record_episode(self, episode: FailureEpisode, promote_to_global: bool = True) -> FailureEpisode:
        """Persist a FailureEpisode to local storage and optionally promote to global cross-project storage."""
        updated = self._upsert_into_db(self.local_db_path, self.local_jsonl, episode)
        if promote_to_global and updated.verified:
            self._upsert_into_db(self.global_db_path, self.global_jsonl, updated)
        self._add_episode_to_graph(updated)
        self._save_graph_json()
        return updated

    def sync_from_global(self) -> int:
        """Pull all verified episodes from Global Cross-Project Memory into the Local Project Memory."""
        global_episodes = self._fetch_all_from_db(self.global_db_path)
        local_ids = {ep.episode_id for ep in self._fetch_all_from_db(self.local_db_path)}
        synced = 0
        for ep in global_episodes:
            if ep.episode_id not in local_ids:
                self._upsert_into_db(self.local_db_path, self.local_jsonl, ep)
                synced += 1
        self._rebuild_in_memory_graph()
        return synced

    def _fetch_all_from_db(self, db_path: Path) -> list[FailureEpisode]:
        """Load all FailureEpisodes ordered by hit_count DESC from the specified DuckDB file."""
        with duckdb.connect(str(db_path)) as conn:
            rows = conn.execute(
                """
                SELECT episode_id, project_name, stage, library, error_type, error_message,
                       normalized_signature, failing_code_snippet, root_cause,
                       verified_fix_description, fixed_code_snippet, prevention_rule,
                       verified, hit_count, created_at, last_seen_at
                FROM failure_episodes
                ORDER BY hit_count DESC, last_seen_at DESC
                """
            ).fetchall()
        return [
            FailureEpisode(
                episode_id=r[0],
                project_name=r[1],
                stage=FailureStage(r[2]),
                library=r[3],
                error_type=r[4],
                error_message=r[5],
                normalized_signature=r[6],
                failing_code_snippet=r[7],
                root_cause=r[8],
                verified_fix_description=r[9],
                fixed_code_snippet=r[10],
                prevention_rule=r[11],
                verified=bool(r[12]),
                hit_count=int(r[13]),
                created_at=r[14],
                last_seen_at=r[15],
            )
            for r in rows
        ]

    def list_episodes(self, include_global: bool = True, library: str | None = None) -> list[FailureEpisode]:
        """Return deduplicated episodes across local and (optionally) global memory."""
        by_id: dict[str, FailureEpisode] = {}
        for ep in self._fetch_all_from_db(self.local_db_path):
            by_id[ep.episode_id] = ep
        if include_global:
            for ep in self._fetch_all_from_db(self.global_db_path):
                if ep.episode_id not in by_id:
                    by_id[ep.episode_id] = ep
        results = list(by_id.values())
        if library is not None:
            lib_lower = library.lower().strip()
            results = [e for e in results if e.library.lower() == lib_lower]
        results.sort(key=lambda e: e.hit_count, reverse=True)
        return results

    def find_similar_failures(
        self,
        error_text: str,
        library: str | None = None,
        top_k: int = 5,
    ) -> list[FailureEpisode]:
        """Search both local and global memories for episodes matching an error message or traceback."""
        candidates = self.list_episodes(include_global=True, library=library)
        if not candidates and library is not None:
            candidates = self.list_episodes(include_global=True, library=None)

        query_tokens = {
            tok.lower()
            for tok in error_text.replace(":", " ").replace(".", " ").replace("'", " ").split()
            if len(tok) >= 3
        }
        scored: list[tuple[float, FailureEpisode]] = []
        for ep in candidates:
            haystack = f"{ep.library} {ep.error_type} {ep.normalized_signature} {ep.error_message} {ep.root_cause}".lower()
            overlap = sum(1 for tok in query_tokens if tok in haystack)
            exact_type_bonus = 3.0 if ep.error_type.lower() in error_text.lower() else 0.0
            score = overlap + exact_type_bonus + (0.1 * ep.hit_count)
            if score > 0:
                scored.append((score, ep))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [ep for _, ep in scored[:top_k]]

    def get_prevention_rules_for_prompt(self, libraries: list[str] | None = None) -> list[str]:
        """Return deduplicated, high-priority prevention rules to inject into agent system prompts."""
        episodes = self.list_episodes(include_global=True)
        if libraries:
            lib_set = {lib.lower() for lib in libraries}
            episodes = [e for e in episodes if e.library.lower() in lib_set]
        rules: list[str] = []
        for ep in episodes:
            formatted = f"[{ep.library.upper()} / {ep.stage.value}] {ep.prevention_rule}"
            if formatted not in rules:
                rules.append(formatted)
        return rules

    def _get_or_add_graph_node(self, key: str, kind: str, label: str) -> int:
        if key in self._node_indices:
            return self._node_indices[key]
        idx = self._graph.add_node({"key": key, "kind": kind, "label": label})
        self._node_indices[key] = idx
        return idx

    def _add_episode_to_graph(self, ep: FailureEpisode) -> None:
        lib_idx = self._get_or_add_graph_node(f"lib:{ep.library}", "library", ep.library)
        err_idx = self._get_or_add_graph_node(
            f"err:{ep.episode_id}", "error", f"{ep.error_type}: {ep.normalized_signature[:60]}"
        )
        cause_idx = self._get_or_add_graph_node(
            f"cause:{ep.episode_id}", "root_cause", ep.root_cause[:80]
        )
        fix_idx = self._get_or_add_graph_node(
            f"fix:{ep.episode_id}", "verified_fix", ep.verified_fix_description[:80]
        )
        rule_idx = self._get_or_add_graph_node(
            f"rule:{ep.episode_id}", "prevention_rule", ep.prevention_rule[:80]
        )

        self._graph.add_edge(lib_idx, err_idx, "EXHIBITS_ERROR")
        self._graph.add_edge(err_idx, cause_idx, "CAUSED_BY")
        self._graph.add_edge(cause_idx, fix_idx, "RESOLVED_BY")
        self._graph.add_edge(fix_idx, rule_idx, "CODIFIED_AS")

    def _rebuild_in_memory_graph(self) -> None:
        self._graph = rx.PyDiGraph()
        self._node_indices = {}
        for ep in self.list_episodes(include_global=True):
            self._add_episode_to_graph(ep)
        self._save_graph_json()

    def _save_graph_json(self) -> None:
        nodes = list(self._graph.nodes())
        edges = [
            {
                "source": self._graph[src]["key"],
                "target": self._graph[tgt]["key"],
                "relation": rel,
            }
            for src, tgt, rel in self._graph.weighted_edge_list()
        ]
        self.graph_path.write_text(
            json.dumps({"nodes": nodes, "edges": edges}, indent=2),
            encoding="utf-8",
        )
