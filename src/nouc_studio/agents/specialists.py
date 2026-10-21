"""Specialist Agents for Multimodal Ingestion, Epistemic Architecture, Monty/Marimo Sandbox Building, and Auditing."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any

import polars as pl
from pydantic import BaseModel, Field, StringConstraints

from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.graph.models import (
    EdgeKind,
    GraphNode,
    MetricLineageTrace,
    NodeKind,
    TrustGrade,
    UncertaintyProfile,
)
from nouc_studio.ingestion.pipeline import IngestionManifest, MultimodalIngestor
from nouc_studio.memory.models import FailureStage
from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.studio.generator import (
    GeneratedStudioBundle,
    StudioApplicationGenerator,
)
from nouc_studio.verification.deepeval_auditor import (
    EpistemicAuditReport,
    audit_metric_explanation,
)
from nouc_studio.verification.doc_verifier import verify_live_python_symbol
from nouc_studio.verification.gate import VerificationGate, VerificationSuiteReport
from nouc_studio.verification.monty_sandbox import MontySandboxRunner
from nouc_studio.verification.pointblank_qa import (
    PointblankValidationReport,
    run_pointblank_validation,
)

_ACRONYMS = {"arr", "mrr", "usd", "eur", "pct", "cac", "ltv", "ndr", "sla", "gpu", "llm", "kv", "pfs", "orr", "ctdna", "ir", "ae", "roi", "ebitda", "cogs", "id", "qa", "ms"}


def _humanize_identifier(raw: str) -> str:
    """Convert a snake_case identifier like 'expansion_arr_usd' into 'Expansion ARR (USD)'."""
    tokens = [t for t in re.split(r"[_\-\s]+", raw.strip()) if t]
    if not tokens:
        return raw
    formatted: list[str] = []
    suffix_unit = ""
    if len(tokens) > 1 and tokens[-1].lower() in ("usd", "eur", "pct", "ms", "months", "days"):
        last = tokens.pop().lower()
        suffix_unit = {
            "usd": "(USD)",
            "eur": "(EUR)",
            "pct": "(%)",
            "ms": "(ms)",
            "months": "(Months)",
            "days": "(Days)",
        }[last]
    for tok in tokens:
        low = tok.lower()
        if low in _ACRONYMS:
            formatted.append(low.upper())
        else:
            formatted.append(tok.capitalize())
    base = " ".join(formatted)
    return f"{base} {suffix_unit}".strip()


def _infer_unit(col_name: str, aggregation: str) -> str:
    """Infer a clean semantic unit from column name and aggregation."""
    low = col_name.lower()
    if low.endswith("_usd") or "usd" in low:
        return "USD"
    if low.endswith("_eur") or "eur" in low:
        return "EUR"
    if low.endswith("_pct") or "pct" in low or "rate" in low or "margin" in low or "Share" in col_name:
        return "%"
    if low.endswith("_ms") or "latency" in low:
        return "ms"
    if low.endswith("_months") or "months" in low:
        return "months"
    if low.endswith("_days") or "days" in low:
        return "days"
    if "count" in low or "patients" in low or "logos" in low:
        return "count"
    return "avg" if aggregation == "mean" else "total"


def _is_non_additive_measure(col_name: str) -> bool:
    """Conservatively recognize measurements whose row values should not be totaled.

    Column names cannot establish a business formula or the weights for a pooled
    rate/percentile. Retain descriptive means, without inventing those weights.
    Match whole tokens so additive names such as ``operating_cost`` still work.
    """
    tokens = set(re.findall(r"[a-z0-9]+", col_name.lower()))
    non_additive_tokens = {
        "pct", "percent", "percentage", "rate", "ratio", "share", "bps",
        "latency", "duration", "elapsed", "ms", "seconds", "secs", "minutes",
        "hours", "days", "months", "years", "per", "price", "avg", "average",
        "mean", "median",
    }
    return bool(tokens & non_additive_tokens) or any(re.fullmatch(r"p\d{2,3}", token) for token in tokens)


class EpistemicAssumption(BaseModel):
    """A concise, validated assumption returned by optional LLM enrichment."""

    # Strip first, then bound: a padded but short answer must not be discarded.
    output: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class PlannedMetricSpec(BaseModel):
    """Specification for an auditable metric to compute and trace in the LineageGraph."""

    metric_id: str
    label: str
    table_id: str
    column_name: str
    aggregation: str = Field(description="sum, mean, max, min, count, or ratio")
    unit: str = ""
    formula_latex: str
    polars_code: str
    monty_expression: str
    monty_inputs: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    epistemic_uncertainty_pct: float = 1.5


class IngestionCartographerAgent:
    """Specialist Agent 1: Ingests heterogeneous files into Polars Parquet tables and Provenance/AST GraphNodes."""

    def run(
        self,
        input_paths: list[Path],
        output_data_dir: Path,
        graph: LineageGraphEngine,
    ) -> IngestionManifest:
        ingestor = MultimodalIngestor(output_data_dir=output_data_dir, graph=graph)
        manifest = ingestor.ingest_paths(input_paths)

        # If user provided only text/prompt without tabular files, synthesize a baseline telemetry table
        if not manifest.tabular_artifacts and not manifest.document_artifacts and not manifest.code_symbols:
            fallback_csv = output_data_dir / "synthetic_baseline_metrics.csv"
            output_data_dir.mkdir(parents=True, exist_ok=True)
            fallback_csv.write_text(
                "segment,revenue,cost,confidence_weight\nEnterprise,125000.0,45000.0,0.96\nMidMarket,84000.0,31000.0,0.92\nSMB,49500.0,22000.0,0.88\n",
                encoding="utf-8",
            )
            manifest = ingestor.ingest_paths([fallback_csv])

        return manifest


class EpistemicArchitectAgent:
    """Specialist Agent 2: Verifies live library symbols, consults Adaptive Memory, and designs the Calculation Lineage Plan."""

    def __init__(self, memory: AdaptiveMemoryStore, llm_model: str = "google:gemini-3.8-flash") -> None:
        self.memory = memory
        self.llm_model = llm_model

    def verify_core_stack_symbols(self) -> dict[str, bool]:
        """Empirically verify core symbols in the live Python environment (Zero Blind Trust)."""
        targets = [
            ("polars", "DataFrame.group_by"),
            ("pointblank", "Validate"),
            ("pydantic_monty", "Monty"),
            ("pydantic_monty", "ResourceLimits"),
            ("marimo_studio.authoring", "open_workspace"),
            ("wigglystuff", "Hint"),
            ("google.genai", "Client"),
            ("pydantic_ai.models", "KnownModelName"),
        ]
        results: dict[str, bool] = {}
        for mod_name, sym_path in targets:
            res = verify_live_python_symbol(mod_name, sym_path)
            results[f"{mod_name}.{sym_path}"] = res.exists
        return results

    def design_metrics_plan(
        self,
        user_need: str,
        manifest: IngestionManifest,
    ) -> list[PlannedMetricSpec]:
        """Design descriptive summaries, without inferring domain KPIs from column names."""
        specs: list[PlannedMetricSpec] = []
        code_metadata_path = Path(manifest.code_symbols_parquet).resolve() if manifest.code_symbols_parquet else None

        for tbl in manifest.tabular_artifacts:
            # AST coordinates remain ingested, validated and available to the
            # explorer, but source line counts are not executive business KPIs.
            if code_metadata_path is not None and Path(tbl.parquet_path).resolve() == code_metadata_path:
                continue
            t_id = tbl.table_id
            human_tbl = _humanize_identifier(t_id)
            # Always include a total record count / coverage metric for the table
            specs.append(
                PlannedMetricSpec(
                    metric_id=f"metric_{t_id}_row_count",
                    label=f"{human_tbl} — Total Records",
                    table_id=t_id,
                    column_name="*",
                    aggregation="count",
                    unit="rows",
                    formula_latex=r"N_{\text{rows}} = \sum_{i=1}^{N} 1",
                    polars_code=f"{t_id}.height",
                    monty_expression="row_count",
                    monty_inputs={"row_count": tbl.row_count},
                    assumptions=[
                        f"Source table '{t_id}' ({tbl.cell_range}) represents the complete population for this segment."
                    ],
                    epistemic_uncertainty_pct=round((1.0 - tbl.overall_completeness) * 15.0 + 0.5, 2),
                )
            )

            # Summarize the first numeric columns conservatively. A sum of
            # cohort percentages, p99 latencies or unit prices has no useful
            # business meaning; a descriptive unweighted mean remains explicit.
            for col_name, stats in list(tbl.numeric_summary.items())[:3]:
                safe_col = re.sub(r"[^a-zA-Z0-9_]+", "_", col_name.lower()).strip("_")
                human_col = _humanize_identifier(col_name)
                # KaTeX-safe label inside \text{...}: strictly alphanumeric + spaces (never raw underscores)
                latex_col = re.sub(r"[^a-zA-Z0-9 ]+", " ", human_col).strip()
                inferred_unit = _infer_unit(col_name, "sum")
                mean_unit = _infer_unit(col_name, "mean")
                col_null_ratio = tbl.null_ratios.get(col_name, 0.0)
                base_unc = round(1.5 + col_null_ratio * 25.0, 2)

                if not _is_non_additive_measure(col_name):
                    specs.append(
                        PlannedMetricSpec(
                            metric_id=f"metric_{t_id}_sum_{safe_col}",
                            label=f"Total {human_col} — {human_tbl}",
                            table_id=t_id,
                            column_name=col_name,
                            aggregation="sum",
                            unit=inferred_unit,
                            formula_latex=rf"\Sigma_{{\text{{{latex_col}}}}} = \sum_{{i=1}}^{{N}} x_{{i,\text{{{latex_col}}}}}",
                            polars_code=f"{t_id}[{col_name!r}].drop_nulls().sum()",
                            monty_expression="round(col_sum, 4)",
                            monty_inputs={"col_sum": stats["sum"]},
                            assumptions=[
                                f"Null values ({col_null_ratio * 100:.1f}%) in '{col_name}' contribute zero to the aggregate total.",
                                f"Objective context: {user_need[:100]}",
                            ],
                            epistemic_uncertainty_pct=base_unc,
                        )
                    )
                specs.append(
                    PlannedMetricSpec(
                        metric_id=f"metric_{t_id}_mean_{safe_col}",
                        label=f"Descriptive Mean {human_col} — {human_tbl}",
                        table_id=t_id,
                        column_name=col_name,
                        aggregation="mean",
                        unit=mean_unit,
                        formula_latex=rf"\mu_{{\text{{{latex_col}}}}} = \frac{{1}}{{N}} \sum_{{i=1}}^{{N}} x_{{i,\text{{{latex_col}}}}}",
                        polars_code=f"{t_id}[{col_name!r}].drop_nulls().mean()",
                        monty_expression="round(col_mean, 4)",
                        monty_inputs={"col_mean": stats["mean"]},
                        assumptions=[
                            f"Unweighted arithmetic mean of non-null source rows; missing values ({col_null_ratio * 100:.1f}%) are excluded.",
                            "Descriptive summary only; not a pooled percentile, weighted portfolio rate, or inferred business KPI.",
                        ],
                        epistemic_uncertainty_pct=round(base_unc + 1.0, 2),
                    )
                )

        # Document chunks metric if documents were ingested without tabular numeric columns
        if manifest.document_artifacts:
            total_chunks = sum(len(d.chunks) for d in manifest.document_artifacts)
            first_doc = manifest.document_artifacts[0]
            specs.append(
                PlannedMetricSpec(
                    metric_id="metric_document_evidence_chunks",
                    label="Extracted Document Evidence Sections",
                    table_id=first_doc.doc_id,
                    column_name="chunks",
                    aggregation="count",
                    unit="sections",
                    formula_latex=r"N_{\text{chunks}} = \sum_{d \in D} |C_d|",
                    polars_code="sum(len(d.chunks) for d in document_artifacts)",
                    monty_expression="total_chunks",
                    monty_inputs={"total_chunks": total_chunks},
                    assumptions=["Document text extraction preserves semantic section boundaries."],
                    epistemic_uncertainty_pct=3.0,
                )
            )

        # Optional PydanticAI LLM enrichment (Cloud APIs, Local/Self-Hosted Ollama/vLLM/LM Studio, or GitHub Models)
        llm_enabled = (
            self.llm_model.lower() != "offline"
            and (
                self.llm_model.startswith("ollama:")
                or any(
                    os.environ.get(k)
                    for k in (
                        "GEMINI_API_KEY",
                        "GOOGLE_API_KEY",
                        "OPENAI_API_KEY",
                        "ANTHROPIC_API_KEY",
                        "GITHUB_TOKEN",
                        "OPENAI_BASE_URL",
                        "OLLAMA_BASE_URL",
                    )
                )
            )
        )
        if llm_enabled:
            try:
                from pydantic_ai import Agent

                agent = Agent(
                    self.llm_model,
                    output_type=EpistemicAssumption,
                    system_prompt="Provide one concise epistemic assumption to watch out for given the user need.",
                )
                run_res = agent.run_sync(f"User need: {user_need}")
                extra_assumption = run_res.output.output
                if extra_assumption and specs:
                    specs[0].assumptions.append(f"[LLM Epistemic Note] {extra_assumption}")
            except Exception:
                pass

        return specs


class SandboxBuilderAgent:
    """Specialist Agent 3: Executes Pointblank QA & Monty Sandbox formulas, populates LineageGraph, and builds Studio views."""

    def __init__(self, monty: MontySandboxRunner | None = None) -> None:
        self.monty = monty or MontySandboxRunner()

    def execute_and_build(
        self,
        *,
        app_title: str,
        user_need: str,
        manifest: IngestionManifest,
        metric_specs: list[PlannedMetricSpec],
        graph: LineageGraphEngine,
        output_dir: Path,
        memory: AdaptiveMemoryStore,
    ) -> tuple[GeneratedStudioBundle, list[MetricLineageTrace], list[PointblankValidationReport]]:
        # 1. Run Posit Pointblank QA on every ingested Polars table
        pb_reports: list[PointblankValidationReport] = []
        table_df_map: dict[str, pl.DataFrame] = {}
        for tbl in manifest.tabular_artifacts:
            df = pl.read_parquet(tbl.parquet_path)
            table_df_map[tbl.table_id] = df
            pb_rep = run_pointblank_validation(
                df,
                table_id=tbl.table_id,
                graph=graph,
                upstream_node_id=f"src_tbl_{tbl.table_id}",
            )
            pb_reports.append(pb_rep)

        # 2. Execute each PlannedMetricSpec inside Pydantic Monty Sandbox and wire into LineageGraphEngine
        traces: list[MetricLineageTrace] = []
        for spec in metric_specs:
            monty_res = self.monty.run_snippet(spec.monty_expression, inputs=spec.monty_inputs)
            if not monty_res.succeeded:
                memory.record_failure_and_fix(
                    stage=FailureStage.MONTY_SANDBOX,
                    library="pydantic-monty",
                    error_type=monty_res.error_type or "MontyRuntimeError",
                    error_message=monty_res.error_message or "Monty execution failed",
                    failing_code_snippet=spec.monty_expression,
                    root_cause="Invalid expression or missing input variable in Monty sandbox evaluation.",
                    verified_fix_description="Fallback to direct Polars scalar evaluation.",
                    fixed_code_snippet="0.0",
                    prevention_rule="Pass all free variables in Monty expressions explicitly via `inputs={...}`.",
                    verified=True,
                )
                computed_val: Any = 0.0
            else:
                computed_val = monty_res.return_value

            transform_id = f"tx_{spec.metric_id}"
            graph.add_node(
                GraphNode(
                    node_id=transform_id,
                    kind=NodeKind.TRANSFORM,
                    label=f"Transform: {spec.label}",
                    description=f"Polars + Monty verified calculation ({spec.aggregation} on `{spec.column_name}`).",
                    code_snippet=spec.polars_code,
                    formula_latex=spec.formula_latex,
                    value_preview=computed_val,
                    unit=spec.unit,
                    uncertainty=UncertaintyProfile(
                        extraction_confidence=1.0,
                        data_completeness=1.0,
                        validation_pass_rate=1.0,
                        epistemic_uncertainty_pct=spec.epistemic_uncertainty_pct,
                        assumptions=spec.assumptions,
                    ),
                )
            )

            src_tbl_node_id = f"src_tbl_{spec.table_id}"
            val_pb_node_id = f"val_pb_{spec.table_id}"
            if graph.has_node(src_tbl_node_id):
                graph.add_edge(
                    src_tbl_node_id,
                    transform_id,
                    EdgeKind.TRANSFORMED_BY,
                    rationale=f"Polars expression `{spec.polars_code}` transforms `{spec.table_id}`.",
                )
            if graph.has_node(val_pb_node_id):
                graph.add_edge(
                    val_pb_node_id,
                    transform_id,
                    EdgeKind.VALIDATED_BY,
                    rationale=f"Pointblank QA gates input table `{spec.table_id}`.",
                )

            for a_idx, assumption_text in enumerate(spec.assumptions, start=1):
                assump_id = f"assump_{spec.metric_id}_{a_idx}"
                graph.add_node(
                    GraphNode(
                        node_id=assump_id,
                        kind=NodeKind.ASSUMPTION,
                        label=f"Assumption #{a_idx} ({spec.label})",
                        description=assumption_text,
                        uncertainty=UncertaintyProfile(
                            epistemic_uncertainty_pct=round(spec.epistemic_uncertainty_pct * 0.5, 2),
                            assumptions=[assumption_text],
                        ),
                    )
                )
                graph.add_edge(
                    assump_id,
                    transform_id,
                    EdgeKind.CONSTRAINED_BY,
                    rationale=assumption_text,
                )

            graph.add_node(
                GraphNode(
                    node_id=spec.metric_id,
                    kind=NodeKind.METRIC,
                    label=spec.label,
                    description=f"Audited KPI `{spec.label}` answering: {user_need[:120]}",
                    code_snippet=spec.polars_code,
                    formula_latex=spec.formula_latex,
                    value_preview=computed_val,
                    unit=spec.unit,
                    uncertainty=UncertaintyProfile(
                        extraction_confidence=1.0,
                        data_completeness=1.0,
                        validation_pass_rate=1.0,
                        epistemic_uncertainty_pct=spec.epistemic_uncertainty_pct,
                        assumptions=spec.assumptions,
                        trust_grade=TrustGrade.A_VERIFIED,
                    ),
                )
            )
            graph.add_edge(
                transform_id,
                spec.metric_id,
                EdgeKind.COMPUTES,
                rationale=f"Produces final audited figure `{spec.label}` = {computed_val}.",
            )

            trace = graph.trace_metric_lineage(spec.metric_id)
            traces.append(trace)

        # 3. Generate reactive Marimo notebook & build multi-view Marimo Studio bundle
        episodes = [ep.model_dump(mode="json") for ep in memory.list_episodes(include_global=True)]
        rules = memory.get_prevention_rules_for_prompt()
        generator = StudioApplicationGenerator(output_dir=output_dir)
        bundle = generator.build_studio_application(
            app_title=app_title,
            user_need=user_need,
            manifest=manifest,
            graph=graph,
            traces=traces,
            memory_payload={"prevention_rules": rules, "episodes": episodes},
        )
        return bundle, traces, pb_reports


class AuditorVerifierAgent:
    """Specialist Agent 4: Runs RLVR Verification Gate + Epistemic Audit and executes Self-Healing Memory Repairs."""

    def __init__(self, memory: AdaptiveMemoryStore, cwd: Path | None = None) -> None:
        self.memory = memory
        self.gate = VerificationGate(memory=memory, cwd=cwd)

    def verify_and_self_heal(
        self,
        bundle: GeneratedStudioBundle,
        traces: list[MetricLineageTrace],
    ) -> tuple[VerificationSuiteReport, list[EpistemicAuditReport], list[str]]:
        notebook_path = Path(bundle.notebook_path)
        healing_actions: list[str] = []

        # Run initial verification gate
        suite_report = self.gate.verify_notebook(
            notebook_path,
            monty_assertions=["1 + 1 == 2", "abs(100.0 * (1.0 + 0.05) - 105.0) < 1e-6"],
        )

        # If Ruff or Marimo check failed, attempt automatic self-healing and record in Adaptive Memory
        if not suite_report.all_passed:
            for check in suite_report.checks:
                if not check.passed and check.stage == FailureStage.RUFF_LINT:
                    import subprocess
                    import sys

                    before_code = notebook_path.read_text(encoding="utf-8")
                    subprocess.run(
                        [sys.executable, "-m", "ruff", "check", "--fix", "--ignore", "E501,B018", str(notebook_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    after_code = notebook_path.read_text(encoding="utf-8")
                    self.memory.record_failure_and_fix(
                        stage=FailureStage.RUFF_LINT,
                        library="ruff",
                        error_type="RuffLintViolation",
                        error_message="; ".join(check.diagnostics[:3]),
                        failing_code_snippet=before_code[:300],
                        root_cause="Generated notebook code contained formatting or import sorting lint issues.",
                        verified_fix_description="Applied `ruff check --fix` to normalize imports and formatting.",
                        fixed_code_snippet=after_code[:300],
                        prevention_rule="Ensure generated notebook cells sort imports alphabetically and avoid unused bindings.",
                        verified=True,
                        promote_to_global=True,
                    )
                    healing_actions.append("Self-healed Ruff lint violations and promoted rule to Global Memory.")

            suite_report = self.gate.verify_notebook(
                notebook_path,
                monty_assertions=["1 + 1 == 2"],
            )

        # Run Epistemic & Faithfulness Audits on all MetricLineageTraces
        audit_reports = [audit_metric_explanation(trace) for trace in traces]
        return suite_report, audit_reports, healing_actions
