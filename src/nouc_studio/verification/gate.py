"""Unified RLVR Verification Gate (Ruff + Ty + Marimo Reactive DAG + Functional Runtime + Visual Layout + Monty Sandbox + Adaptive Memory)."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path
from textwrap import dedent
from typing import Any

import rustworkx as rx
from pydantic import BaseModel, Field

from nouc_studio.memory.models import FailureEpisode, FailureStage
from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.verification.monty_sandbox import MontyExecutionResult, MontySandboxRunner

COMMAND_TIMEOUT_SECONDS = 300.0


def _assignment_names(target: ast.AST) -> list[str]:
    """Collect public identifiers from a name, starred name, or nested unpacking target."""
    if isinstance(target, ast.Name):
        return [target.id] if not target.id.startswith("_") else []
    if isinstance(target, ast.Starred):
        return _assignment_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _assignment_names(element)]
    return []


class GateCheckResult(BaseModel):
    """Single verification stage result."""

    stage: FailureStage
    passed: bool
    command_or_target: str
    diagnostics: list[str] = Field(default_factory=list)
    matched_memory_remedies: list[FailureEpisode] = Field(default_factory=list)


class VerificationSuiteReport(BaseModel):
    """Aggregated report across all deterministic verification gates."""

    target_path: str
    all_passed: bool
    checks: list[GateCheckResult] = Field(default_factory=list)
    monty_results: list[MontyExecutionResult] = Field(default_factory=list)


def _is_mo_ui_call(expr: ast.AST) -> bool:
    """Return True if `expr` is a call like `mo.ui.dropdown(...)`, `mo.ui.slider(...)`, or `mo.ui.anywidget(...)`."""
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    return bool(
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "mo"
        and func.value.attr == "ui"
    )


def validate_marimo_reactive_dag(notebook_path: Path) -> GateCheckResult:
    """Parse a Marimo notebook `.py` file into a cell AST & reactive variable graph and verify DAG invariants.

    Checks:
    1. Valid Python AST syntax.
    2. Presence of `marimo.App`.
    3. No duplicate global variable definitions across `@app.cell` functions (`MultipleDefinitionError`).
    4. No same-cell `UIElement.value` access (`SameCellUIValueError`).
    5. No unbound cell parameters (`UnboundCellParameterError`).
    6. Acyclic reactive dataflow graph (`rustworkx.is_directed_acyclic_graph`).
    """
    source = notebook_path.read_text(encoding="utf-8")
    diagnostics: list[str] = []

    try:
        tree = ast.parse(source, filename=str(notebook_path))
    except SyntaxError as exc:
        return GateCheckResult(
            stage=FailureStage.MARIMO_DAG,
            passed=False,
            command_or_target=f"marimo_ast_dag({notebook_path.name})",
            diagnostics=[f"SyntaxError at line {exc.lineno}: {exc.msg}"],
        )

    defined_by_cell: dict[str, list[str]] = {}
    referenced_by_cell: dict[str, set[str]] = {}
    variable_owner: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_cell = any(
                (isinstance(dec, ast.Attribute) and dec.attr == "cell")
                or (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "cell")
                for dec in node.decorator_list
            )
            if not is_cell:
                continue

            cell_name = f"{node.name}@L{node.lineno}"
            refs = {arg.arg for arg in node.args.args}
            referenced_by_cell[cell_name] = refs

            defs: list[str] = []
            cell_ui_vars: set[str] = set()

            # Check statements in cell body
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign) and _is_mo_ui_call(stmt.value):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            cell_ui_vars.add(target.id)

            if cell_ui_vars:
                for subnode in ast.walk(node):
                    if (
                        isinstance(subnode, ast.Attribute)
                        and subnode.attr == "value"
                        and isinstance(subnode.value, ast.Name)
                        and subnode.value.id in cell_ui_vars
                    ):
                        diagnostics.append(
                            f"SameCellUIValueError: Cell '{cell_name}' accesses '{subnode.value.id}.value' in the same cell that creates UIElement '{subnode.value.id}'. Move '.value' access to a downstream cell."
                        )

            # In Marimo, a cell's exported definitions are either its return tuple or top-level assigned non-underscore variables
            for stmt in node.body:
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    if isinstance(stmt.value, ast.Tuple):
                        for elt in stmt.value.elts:
                            if isinstance(elt, ast.Name) and not elt.id.startswith("_") and elt.id not in refs:
                                defs.append(elt.id)
                    elif isinstance(stmt.value, ast.Name) and not stmt.value.id.startswith("_") and stmt.value.id not in refs:
                        defs.append(stmt.value.id)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        defs.extend(_assignment_names(target))
                elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                    # `x: int` only annotates; it binds nothing at runtime.
                    defs.extend(_assignment_names(stmt.target))
                elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    for alias in stmt.names:
                        bound = alias.asname or alias.name.split(".")[0]
                        if not bound.startswith("_"):
                            defs.append(bound)

            dedup_defs = list(dict.fromkeys(defs))
            defined_by_cell[cell_name] = dedup_defs

            for var_name in dedup_defs:
                if var_name in variable_owner and variable_owner[var_name] != cell_name:
                    diagnostics.append(
                        f"MultipleDefinitionError: Variable '{var_name}' is defined in both '{variable_owner[var_name]}' and '{cell_name}'."
                    )
                else:
                    variable_owner[var_name] = cell_name

    # Build cell dependency graph in Rustworkx to check for unbound parameters and reactive cycles
    dag: rx.PyDiGraph[str, str] = rx.PyDiGraph()
    cell_idx_map: dict[str, int] = {}
    for cell_name in defined_by_cell:
        cell_idx_map[cell_name] = dag.add_node(cell_name)

    for consumer_cell, refs in referenced_by_cell.items():
        for ref_var in refs:
            producer_cell = variable_owner.get(ref_var)
            if producer_cell is None or producer_cell == consumer_cell:
                diagnostics.append(
                    f"UnboundCellParameterError: Cell '{consumer_cell}' depends on parameter '{ref_var}', which is not exported by any cell in '{notebook_path.name}'."
                )
            else:
                dag.add_edge(cell_idx_map[producer_cell], cell_idx_map[consumer_cell], ref_var)

    if not rx.is_directed_acyclic_graph(dag):
        diagnostics.append("CycleError: Marimo reactive cell graph contains a dependency cycle.")

    return GateCheckResult(
        stage=FailureStage.MARIMO_DAG,
        passed=len(diagnostics) == 0,
        command_or_target=f"marimo_ast_dag({notebook_path.name})",
        diagnostics=diagnostics,
    )


def _execute_marimo_notebook_in_process(notebook_path: Path) -> tuple[list[Any], dict[str, Any], list[str]]:
    """Import and execute `app.run()` on a Marimo notebook file, returning `(outputs, defs, diagnostics)`."""
    diagnostics: list[str] = []
    try:
        spec = importlib.util.spec_from_file_location(f"_nouc_nb_{notebook_path.stem}", notebook_path)
        if spec is None or spec.loader is None:
            return [], {}, [f"ImportError: Unable to load module spec for {notebook_path}"]
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app_obj = getattr(mod, "app", None)
        if app_obj is None:
            return [], {}, [f"RuntimeError: No `app = marimo.App(...)` found in {notebook_path.name}"]
        outputs, defs = app_obj.run()
        out_list = list(outputs) if outputs is not None else []
        defs_dict = dict(defs) if defs is not None else {}

        for idx, out in enumerate(out_list):
            if isinstance(out, BaseException):
                diagnostics.append(f"CellOutputException[cell #{idx}]: {type(out).__name__}: {out}")
            elif out is not None and "Error" in type(out).__name__ and hasattr(out, "msg"):
                diagnostics.append(f"MarimoCellError[cell #{idx}]: {type(out).__name__}: {getattr(out, 'msg', out)}")

        if not defs_dict:
            diagnostics.append(f"EmptyNotebookDefsError: app.run() produced 0 exported definitions in {notebook_path.name}")

        return out_list, defs_dict, diagnostics
    except Exception as exc:
        return [], {}, [f"{type(exc).__name__}: {exc}"]


def _bad_katex_text_commands(text: str) -> list[str]:
    return re.findall(r"\\(?:text|mathrm)\{[^{}]*(?<!\\)_[^{}]*\}", text)


class _RenderedHtmlAudit(HTMLParser):
    """Inspect visible DOM and JSON-backed HTML without interpreting literal code as HTML.

    This is a rendering heuristic, not a browser layout or geometry measurement.
    Marimo embeds callout bodies as HTML-escaped JSON strings in ``data-html``.
    HTMLParser decodes the attribute entities once; json.loads decodes the string.
    Parsing each resulting fragment also handles callouts nested inside callouts.
    """

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    # Installed marimo/_plugins/stateless/callout.py supplies args["html"] to
    # build_stateless_plugin. Ordinary HTML data-* attributes have no JSON contract.
    _JSON_HTML_COMPONENTS = {"marimo-callout-output"}

    def __init__(self, label: str, *, in_card: bool = False, depth: int = 0) -> None:
        super().__init__(convert_charrefs=True)
        self.label = label
        self.in_card = in_card
        self.depth = depth
        self.diagnostics: list[str] = []
        self._stack: list[tuple[str, set[str]]] = []
        self._pre_blocks: list[tuple[int, bool, list[str]]] = []
        self._visible_text: list[str] = []
        self._math_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        ancestors = self._stack + [(tag, classes)]
        in_code = any(name in {"pre", "code", "script", "style"} for name, _ in self._stack)
        in_card = self.in_card or any(
            name == "marimo-callout-output" or any(value == "card" or value.endswith("-card") for value in tokens)
            for name, tokens in ancestors
        )
        if not in_code:
            if tag == "marimo-error" or tag.startswith("marimo-error-"):
                self.diagnostics.append(f"VisualErrorTraceback[{self.label}]: Rendered DOM contains a marimo error element.")
            if "katex-error" in classes:
                self.diagnostics.append(f"VisualKaTeXSyntaxError[{self.label}]: Rendered DOM contains a KaTeX error element.")
            embedded = attributes.get("data-html")
            if embedded is not None and tag in self._JSON_HTML_COMPONENTS:
                try:
                    decoded = json.loads(embedded)
                except (ValueError, TypeError):
                    self.diagnostics.append(f"VisualEmbeddedHtmlError[{self.label}]: data-html is not valid JSON.")
                else:
                    if isinstance(decoded, str):
                        if self.depth >= 16:
                            self.diagnostics.append(f"VisualEmbeddedHtmlError[{self.label}]: Nested data-html exceeds the DOM audit depth limit (16).")
                        else:
                            child = _RenderedHtmlAudit(self.label, in_card=in_card, depth=self.depth + 1)
                            child.feed(decoded)
                            child.close()
                            self.diagnostics.extend(child.finish())
        if tag == "pre":
            # Fenced examples carry codehilite; explicit/guessed source languages
            # also distinguish real Python/SQL/etc. from a misindented prose card.
            intentional_code = any(
                "codehilite" in tokens or any(
                    value.startswith("language-") and value not in {"language-markdown", "language-md", "language-scdoc", "language-text"}
                    for value in tokens
                )
                for _, tokens in ancestors
            )
            self._pre_blocks.append((len(self._stack), in_card and not intentional_code, []))
        elif tag == "code" and classes and self._pre_blocks:
            level, candidate, text = self._pre_blocks[-1]
            if any(value.startswith("language-") for value in classes):
                self._pre_blocks[-1] = (level, False, text)
        if tag not in self._VOID_TAGS:
            self._stack.append((tag, classes))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self._pre_blocks:
            _, candidate, text = self._pre_blocks.pop()
            source = "".join(text)
            # Markdown has already consumed four spaces to create this pre block;
            # template interpolation can leave any additional indentation behind.
            if candidate and re.search(r"(?m)^[ \t]*#{1,6}[ \t]+\S", source):
                # A Python comment/string may itself contain Markdown headings.
                # Preserve executable source examples even without a language hint.
                python_source = False
                with suppress(SyntaxError):
                    python_source = bool(ast.parse(dedent(source)).body)
                if not python_source:
                    self.diagnostics.append(
                        f"VisualMarkdownCodeBlock[{self.label}]: A Markdown heading appears as literal code in a callout/card. Check mixed indentation; use a fenced code block for intentional source examples."
                    )
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        for _, _, text in self._pre_blocks:
            text.append(data)
        if not any(tag in {"pre", "code", "script", "style"} for tag, _ in self._stack):
            self._visible_text.append(data)
            if any(tag == "marimo-tex" or "arithmatex" in classes for tag, classes in self._stack):
                self._math_text.append(data)

    def finish(self) -> list[str]:
        if "Traceback (most recent call last)" in "".join(self._visible_text):
            self.diagnostics.append(f"VisualErrorTraceback[{self.label}]: Rendered text contains an unhandled Python traceback.")
        bad_katex = _bad_katex_text_commands("".join(self._math_text))
        if bad_katex:
            self.diagnostics.append(
                f"VisualKaTeXSyntaxError[{self.label}]: Unescaped underscore inside LaTeX \\text{{...}} or \\mathrm{{...}}: {bad_katex[:2]}"
            )
        return list(dict.fromkeys(self.diagnostics))


class VerificationGate:
    """Executes Ruff, Ty, Marimo DAG, Functional Runtime, Visual Layout, and Monty Sandbox checks with Adaptive Memory."""

    def __init__(
        self,
        memory: AdaptiveMemoryStore,
        cwd: Path | None = None,
        *,
        command_timeout: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self.memory = memory
        self.cwd = cwd or Path.cwd()
        self.command_timeout = command_timeout
        self.monty = MontySandboxRunner()

    def _run_command(self, cmd: list[str]) -> tuple[bool, list[str]]:
        """Run a bounded verification command and collect failure diagnostics."""
        try:
            proc = subprocess.run(
                cmd, cwd=self.cwd, capture_output=True, text=True, check=False,
                timeout=self.command_timeout,
            )
        except subprocess.TimeoutExpired:
            return False, [f"Command timeout after {self.command_timeout:g}s: {' '.join(cmd)}"]
        passed = proc.returncode == 0
        diagnostics = (
            [line for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()]
            if not passed else []
        )
        return passed, diagnostics

    def _attach_remedies(self, result: GateCheckResult, library: str) -> GateCheckResult:
        if result.passed:
            return result
        combined_err = "\n".join(result.diagnostics)
        remedies = self.memory.find_similar_failures(combined_err, library=library, top_k=3)
        return result.model_copy(update={"matched_memory_remedies": remedies})

    def run_ruff_check(self, target: Path) -> GateCheckResult:
        """Run `ruff check` on the target file or directory."""
        cmd = [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "E,F,I,UP,B,SIM",
            "--ignore",
            "E501,B018",
            str(target),
        ]
        passed, diags = self._run_command(cmd)
        res = GateCheckResult(
            stage=FailureStage.RUFF_LINT,
            passed=passed,
            command_or_target=" ".join(cmd),
            diagnostics=diags,
        )
        return self._attach_remedies(res, library="ruff")

    def run_ty_check(self, target: Path) -> GateCheckResult:
        """Run Astral's `ty check` on the target file or directory."""
        cmd = [sys.executable, "-m", "ty", "check", str(target)]
        passed, diags = self._run_command(cmd)
        res = GateCheckResult(
            stage=FailureStage.TY_TYPECHECK,
            passed=passed,
            command_or_target=" ".join(cmd),
            diagnostics=diags,
        )
        return self._attach_remedies(res, library="ty")

    def run_marimo_check(self, notebook_path: Path) -> GateCheckResult:
        """Run AST reactive DAG validation + `marimo check` CLI on a Marimo notebook."""
        dag_res = validate_marimo_reactive_dag(notebook_path)
        if not dag_res.passed:
            return self._attach_remedies(dag_res, library="marimo")

        cmd = [sys.executable, "-m", "marimo", "check", str(notebook_path)]
        passed, diags = self._run_command(cmd)
        res = GateCheckResult(
            stage=FailureStage.MARIMO_DAG,
            passed=passed,
            command_or_target=" ".join(cmd),
            diagnostics=diags,
        )
        return self._attach_remedies(res, library="marimo")

    def run_functional_runtime_check(
        self,
        notebook_path: Path,
        *,
        _precomputed_run: tuple[list[Any], dict[str, Any], list[str]] | None = None,
    ) -> GateCheckResult:
        """Execute `app.run()` on the Marimo notebook to verify functional runtime execution with zero cell errors."""
        _, _, diags = _precomputed_run or _execute_marimo_notebook_in_process(notebook_path)
        res = GateCheckResult(
            stage=FailureStage.RUNTIME_EXECUTION,
            passed=len(diags) == 0,
            command_or_target=f"marimo_app_run({notebook_path.name})",
            diagnostics=diags,
        )
        return self._attach_remedies(res, library="marimo")

    def run_visual_layout_check(
        self,
        notebook_path: Path,
        *,
        _precomputed_run: tuple[list[Any], dict[str, Any], list[str]] | None = None,
    ) -> GateCheckResult:
        """Apply DOM/template heuristics; browser geometry and visual review remain separate checks."""
        outputs, defs, run_diags = _precomputed_run or _execute_marimo_notebook_in_process(notebook_path)
        diags: list[str] = []
        if run_diags:
            diags.extend(f"RuntimePrerequisiteError: {d}" for d in run_diags)
        else:
            # 1. Inspect rendered HTML of all cell outputs & exported visual blocks
            for idx, out in enumerate(outputs):
                if out is not None and hasattr(out, "_mime_"):
                    try:
                        mime_type, html_payload = out._mime_()
                        if isinstance(html_payload, str):
                            html_audit = _RenderedHtmlAudit(f"cell #{idx}")
                            html_audit.feed(html_payload)
                            html_audit.close()
                            diags.extend(html_audit.finish())
                            # Check Mermaid node density so diagrams are visually readable
                            if "marimo-mermaid" in html_payload:
                                node_defs = re.findall(r'\["[^"]+"\]', html_payload)
                                if len(node_defs) > 35:
                                    diags.append(
                                        f"VisualMermaidOvercrowding[cell #{idx}]: Mermaid diagram contains {len(node_defs)} nodes (>35 max legible limit). Scope diagram to a focused subgraph."
                                    )
                    except Exception as exc:
                        diags.append(f"VisualMimeRenderError[cell #{idx}]: {type(exc).__name__}: {exc}")

            # 1b. Also check traces_payload formulas directly for KaTeX underscore errors
            for trace_item in defs.get("traces_payload") or []:
                if isinstance(trace_item, dict):
                    proof_str = str(trace_item.get("natural_language_proof", ""))
                    bad_proof_katex = _bad_katex_text_commands(proof_str)
                    if bad_proof_katex:
                        diags.append(
                            f"VisualKaTeXSyntaxError[trace]: Unescaped underscore in natural_language_proof LaTeX formula: {bad_proof_katex[:2]}"
                        )
                        break

            # 2. Check KPI section horizontal row density if present
            kpi_sec = defs.get("kpi_section")
            if kpi_sec is not None and hasattr(kpi_sec, "_mime_"):
                _, kpi_html = kpi_sec._mime_()
                # Count how many horizontal flex rows vs callouts exist
                callout_count = kpi_html.count("<marimo-callout-output")
                row_count = kpi_html.count("flex-direction: row")
                if callout_count > 4 and row_count <= 1:
                    diags.append(
                        f"VisualHorizontalOverflowError: kpi_section packs {callout_count} KPI callout cards into {row_count} horizontal row(s), causing severe horizontal card squishing."
                    )

            # 3. Check studio multi-view HTML templates if present alongside the notebook
            views_dir = notebook_path.parent / "views"
            if views_dir.is_dir():
                for view_html_path in sorted(views_dir.glob("*/index.html")):
                    html_text = view_html_path.read_text(encoding="utf-8")
                    view_slug = view_html_path.parent.name
                    if "grid-template-columns" not in html_text and "display: grid" not in html_text:
                        diags.append(
                            f"VisualTemplateGridMissing[{view_slug}]: {view_html_path.name} is missing responsive CSS Grid layout rules."
                        )
                    if "<marimo-cell" not in html_text and "<marimo-output" not in html_text:
                        diags.append(
                            f"VisualTemplateBindingsMissing[{view_slug}]: {view_html_path.name} contains no <marimo-cell> or <marimo-output> projections."
                        )

        res = GateCheckResult(
            stage=FailureStage.VISUAL_INSPECTION,
            passed=len(diags) == 0,
            command_or_target=f"visual_dom_audit({notebook_path.name})",
            diagnostics=diags,
        )
        return self._attach_remedies(res, library="marimo-studio")

    def verify_notebook(
        self,
        notebook_path: Path,
        *,
        monty_assertions: list[str] | None = None,
        run_ty: bool = False,
        run_runtime: bool = True,
        run_visual: bool = True,
    ) -> VerificationSuiteReport:
        """Run the full verification gate (AST DAG + Ruff + Functional Runtime + Visual Layout + Monty + optional Ty)."""
        checks: list[GateCheckResult] = [
            self.run_marimo_check(notebook_path),
            self.run_ruff_check(notebook_path),
        ]

        if run_runtime or run_visual:
            precomputed = _execute_marimo_notebook_in_process(notebook_path)
            if run_runtime:
                checks.append(self.run_functional_runtime_check(notebook_path, _precomputed_run=precomputed))
            if run_visual:
                checks.append(self.run_visual_layout_check(notebook_path, _precomputed_run=precomputed))

        if run_ty:
            checks.append(self.run_ty_check(notebook_path))

        monty_results: list[MontyExecutionResult] = []
        if monty_assertions:
            monty_diags: list[str] = []
            for snippet in monty_assertions:
                m_res = self.monty.run_snippet(snippet)
                monty_results.append(m_res)
                if not m_res.succeeded:
                    monty_diags.append(f"{m_res.error_type}: {m_res.error_message}")
            checks.append(
                self._attach_remedies(
                    GateCheckResult(
                        stage=FailureStage.MONTY_SANDBOX,
                        passed=len(monty_diags) == 0,
                        command_or_target="pydantic-monty assertions",
                        diagnostics=monty_diags,
                    ),
                    library="pydantic-monty",
                )
            )

        all_ok = all(c.passed for c in checks)
        return VerificationSuiteReport(
            target_path=str(notebook_path),
            all_passed=all_ok,
            checks=checks,
            monty_results=monty_results,
        )

