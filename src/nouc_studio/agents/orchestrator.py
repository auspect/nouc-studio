"""Rustworkx DAG Multi-Agent Orchestrator for building verified Marimo Studio applications."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import rustworkx as rx
from pydantic import BaseModel, Field

from nouc_studio.agents.specialists import (
    AuditorVerifierAgent,
    EpistemicArchitectAgent,
    IngestionCartographerAgent,
    PlannedMetricSpec,
    SandboxBuilderAgent,
)
from nouc_studio.config import InsightsConfig
from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.graph.models import MetricLineageTrace
from nouc_studio.ingestion.pipeline import IngestionManifest
from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.studio.generator import GeneratedStudioBundle
from nouc_studio.verification.deepeval_auditor import EpistemicAuditReport
from nouc_studio.verification.gate import VerificationSuiteReport
from nouc_studio.verification.pointblank_qa import PointblankValidationReport


class AgentStepTelemetry(BaseModel):
    """Execution telemetry for a single node in the Multi-Agent Orchestration DAG."""

    agent_id: str
    role: str
    duration_ms: float
    status: str
    summary: str


class OrchestrationReport(BaseModel):
    """Complete deliverable and verification report from the Multi-Agent Orchestrator."""

    app_title: str
    user_need: str
    agent_dag_order: list[str]
    agent_telemetry: list[AgentStepTelemetry] = Field(default_factory=list)
    verified_symbols: dict[str, bool] = Field(default_factory=dict)
    manifest: IngestionManifest
    planned_metrics: list[PlannedMetricSpec] = Field(default_factory=list)
    pointblank_reports: list[PointblankValidationReport] = Field(default_factory=list)
    traces: list[MetricLineageTrace] = Field(default_factory=list)
    studio_bundle: GeneratedStudioBundle
    verification_report: VerificationSuiteReport
    epistemic_audits: list[EpistemicAuditReport] = Field(default_factory=list)
    self_healing_actions: list[str] = Field(default_factory=list)
    lineage_node_count: int
    lineage_edge_count: int


class MultiAgentOrchestrator:
    """Coordinates the 5 specialist agents along a strict Rustworkx execution DAG with self-healing memory."""

    def __init__(self, config: InsightsConfig | None = None) -> None:
        self.config = config or InsightsConfig()
        self.config.ensure_directories()
        self.llm_runtime_status = self.config.apply_llm_environment()
        self.memory = AdaptiveMemoryStore(
            local_dir=self.config.local_memory_dir,
            global_dir=self.config.global_memory_dir,
            project_name=self.config.project_root.name,
        )
        self._agent_dag: rx.PyDiGraph[str, str] = rx.PyDiGraph(check_cycle=True)
        self._build_agent_dag()

    def _build_agent_dag(self) -> None:
        n_cart = self._agent_dag.add_node("1_ingestion_cartographer")
        n_arch = self._agent_dag.add_node("2_epistemic_architect")
        n_build = self._agent_dag.add_node("3_sandbox_builder")
        n_audit = self._agent_dag.add_node("4_auditor_verifier")
        n_pub = self._agent_dag.add_node("5_studio_publisher")

        self._agent_dag.add_edge(n_cart, n_arch, "manifest_and_provenance_graph")
        self._agent_dag.add_edge(n_arch, n_build, "verified_symbols_and_metric_plan")
        self._agent_dag.add_edge(n_build, n_audit, "notebook_and_lineage_traces")
        self._agent_dag.add_edge(n_audit, n_pub, "verified_studio_bundle")

    def get_agent_execution_order(self) -> list[str]:
        """Return topological execution order of the multi-agent pipeline."""
        return [self._agent_dag[idx] for idx in rx.topological_sort(self._agent_dag)]

    def run_pipeline(
        self,
        *,
        user_need: str,
        input_paths: list[Path],
        output_dir: Path,
        app_title: str = "Nouc Studio Studio",
        on_step: Callable[[str, str], None] | None = None,
    ) -> OrchestrationReport:
        """Execute the end-to-end multi-agent pipeline from raw files + need to a verified Marimo Studio app."""
        output_dir.mkdir(parents=True, exist_ok=True)
        data_dir = output_dir / "data"
        graph = LineageGraphEngine()
        telemetry: list[AgentStepTelemetry] = []

        def notify_step(agent_id: str, role: str) -> None:
            if on_step is not None:
                on_step(agent_id, role)

        # Step 1: IngestionCartographerAgent
        notify_step("1_ingestion_cartographer", "Multimodal Ingestion & Provenance Cartographer")
        t0 = time.perf_counter()
        cartographer = IngestionCartographerAgent()
        manifest = cartographer.run(input_paths=input_paths, output_data_dir=data_dir, graph=graph)
        telemetry.append(
            AgentStepTelemetry(
                agent_id="1_ingestion_cartographer",
                role="Multimodal Ingestion & Provenance Cartographer",
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                status="completed",
                summary=(
                    f"Ingested {len(manifest.ingested_files)} files -> "
                    f"{len(manifest.tabular_artifacts)} Polars tables, "
                    f"{len(manifest.document_artifacts)} docs, "
                    f"{len(manifest.code_symbols)} AST symbols."
                ),
            )
        )

        # Step 2: EpistemicArchitectAgent
        notify_step("2_epistemic_architect", "Zero-Blind-Trust Grounding & Lineage Architect")
        t0 = time.perf_counter()
        architect = EpistemicArchitectAgent(memory=self.memory, llm_model=self.config.default_llm_model)
        verified_symbols = architect.verify_core_stack_symbols()
        planned_metrics = architect.design_metrics_plan(user_need=user_need, manifest=manifest)
        telemetry.append(
            AgentStepTelemetry(
                agent_id="2_epistemic_architect",
                role="Zero-Blind-Trust Grounding & Lineage Architect",
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                status="completed",
                summary=(
                    f"Verified {sum(verified_symbols.values())}/{len(verified_symbols)} live runtime symbols and "
                    f"designed {len(planned_metrics)} auditable KPI lineage specs."
                ),
            )
        )

        # Step 3: SandboxBuilderAgent
        notify_step("3_sandbox_builder", "Monty & Marimo Reactive Sandbox Builder")
        t0 = time.perf_counter()
        builder = SandboxBuilderAgent()
        bundle, traces, pb_reports = builder.execute_and_build(
            app_title=app_title,
            user_need=user_need,
            manifest=manifest,
            metric_specs=planned_metrics,
            graph=graph,
            output_dir=output_dir,
            memory=self.memory,
        )
        telemetry.append(
            AgentStepTelemetry(
                agent_id="3_sandbox_builder",
                role="Monty & Marimo Reactive Sandbox Builder",
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                status="completed",
                summary=(
                    f"Executed {len(planned_metrics)} Monty sandbox formulas, {len(pb_reports)} Pointblank QA plans, "
                    f"and built {len(bundle.views)} Marimo Studio views."
                ),
            )
        )

        # Step 4: AuditorVerifierAgent
        notify_step("4_auditor_verifier", "RLVR Verification Gate & Epistemic Auditor")
        t0 = time.perf_counter()
        auditor = AuditorVerifierAgent(memory=self.memory, cwd=self.config.project_root)
        verification_report, epistemic_audits, healing_actions = auditor.verify_and_self_heal(
            bundle=bundle,
            traces=traces,
        )
        telemetry.append(
            AgentStepTelemetry(
                agent_id="4_auditor_verifier",
                role="RLVR Verification Gate & Epistemic Auditor",
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                status="completed" if verification_report.all_passed else "healed_with_warnings",
                summary=(
                    f"Verification gate passed={verification_report.all_passed}; "
                    f"audited {len(epistemic_audits)} metric proofs."
                ),
            )
        )

        # Step 5: StudioPublisherAgent
        notify_step("5_studio_publisher", "Marimo Studio Multi-View Publisher")
        t0 = time.perf_counter()
        manifest_file = output_dir / "orchestration_report.json"
        telemetry.append(
            AgentStepTelemetry(
                agent_id="5_studio_publisher",
                role="Marimo Studio Multi-View Publisher",
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                status="completed",
                summary=f"Published studio bundle at {output_dir} with views {[v.view_name for v in bundle.views]}.",
            )
        )

        report = OrchestrationReport(
            app_title=app_title,
            user_need=user_need,
            agent_dag_order=self.get_agent_execution_order(),
            agent_telemetry=telemetry,
            verified_symbols=verified_symbols,
            manifest=manifest,
            planned_metrics=planned_metrics,
            pointblank_reports=pb_reports,
            traces=traces,
            studio_bundle=bundle,
            verification_report=verification_report,
            epistemic_audits=epistemic_audits,
            self_healing_actions=healing_actions,
            lineage_node_count=graph.node_count,
            lineage_edge_count=graph.edge_count,
        )
        manifest_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
