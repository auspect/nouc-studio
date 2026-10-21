"""End-to-end integration test for the Multi-Agent Orchestrator and Marimo Studio multi-view generation."""

import shutil
from pathlib import Path

import polars as pl
import pytest

from nouc_studio.agents import MultiAgentOrchestrator
from nouc_studio.config import InsightsConfig
from nouc_studio.verification.gate import _execute_marimo_notebook_in_process


@pytest.mark.parametrize("with_progress", [False, True])
def test_end_to_end_multi_agent_studio_generation(tmp_path: Path, with_progress: bool) -> None:
    inputs_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Excel workbook
    df = pl.DataFrame(
        {
            "product_line": ["CoreCloud", "EdgeAI", "DataFabric", "CoreCloud"],
            "arr_eur": [420000.0, 315000.0, 190000.0, 460000.0],
            "gross_margin_pct": [78.5, 82.0, 71.0, 79.2],
        }
    )
    df.write_excel(inputs_dir / "saas_metrics.xlsx", worksheet="ARR")

    # 2. Markdown specification with embedded table
    (inputs_dir / "product_spec.md").write_text(
        "# Product SLA & Reliability\n"
        "| tier | uptime_pct | max_latency_ms |\n"
        "| --- | --- | --- |\n"
        "| enterprise | 99.99 | 25.0 |\n"
        "| standard | 99.90 | 50.0 |\n",
        encoding="utf-8",
    )

    # 3. Python module
    (inputs_dir / "arr_calculator.py").write_text(
        "def net_arr(gross_arr: float, churn: float) -> float:\n"
        "    return gross_arr - churn\n",
        encoding="utf-8",
    )

    cfg = InsightsConfig(
        project_root=tmp_path,
        local_memory_dir=tmp_path / ".insights" / "memory",
        global_memory_dir=tmp_path / "global_memory",
    )
    orchestrator = MultiAgentOrchestrator(config=cfg)
    steps: list[tuple[str, str]] = []

    def on_step(agent_id: str, role: str) -> None:
        steps.append((agent_id, role))

    report = orchestrator.run_pipeline(
        user_need="Deliver an auditable SaaS ARR & SLA executive studio with calculation lineage and uncertainty intervals.",
        input_paths=[inputs_dir],
        output_dir=output_dir,
        app_title="SaaS ARR & SLA Studio",
        on_step=on_step if with_progress else None,
    )

    assert len(report.agent_telemetry) == 5
    if with_progress:
        assert [agent_id for agent_id, _ in steps] == [
            "1_ingestion_cartographer", "2_epistemic_architect", "3_sandbox_builder",
            "4_auditor_verifier", "5_studio_publisher",
        ] == report.agent_dag_order
        assert steps == [(step.agent_id, step.role) for step in report.agent_telemetry]
    else:
        assert steps == []
    assert report.verification_report.all_passed
    assert len(report.studio_bundle.views) == 3
    assert all(v.validation_passed for v in report.studio_bundle.views)
    assert all(a.passed for a in report.epistemic_audits)
    assert Path(report.studio_bundle.notebook_path).exists()
    assert Path(report.studio_bundle.lineage_json_path).exists()
    assert Path(report.studio_bundle.traces_json_path).exists()

    # Delete the original bundle so missing relative paths cannot pass by
    # accidentally loading data from the generation host.
    relocated_dir = tmp_path / "relocated" / "studio"
    shutil.copytree(output_dir, relocated_dir)
    shutil.rmtree(output_dir)
    relocated_notebook = relocated_dir / "app.py"
    assert str(tmp_path) not in relocated_notebook.read_text(encoding="utf-8")
    _, definitions, diagnostics = _execute_marimo_notebook_in_process(relocated_notebook)
    assert diagnostics == []
    assert definitions["data_directory"] == relocated_dir / "data"
    assert definitions["loaded_tables"]
    assert definitions["traces_payload"]
    assert definitions["lineage_payload"]["nodes"]
    assert definitions["memory_payload"]


def test_realistic_demo_bundles_generation(tmp_path: Path) -> None:
    from nouc_studio.demos import (
        generate_demo_1_saas_ma_bundle,
        generate_demo_2_clinical_biotech_bundle,
        generate_demo_3_ai_infra_finops_bundle,
    )

    d1, need1, title1 = generate_demo_1_saas_ma_bundle(tmp_path)
    d2, need2, title2 = generate_demo_2_clinical_biotech_bundle(tmp_path)
    d3, need3, title3 = generate_demo_3_ai_infra_finops_bundle(tmp_path)

    assert (d1 / "arr_cohorts_2026.xlsx").exists() and need1 and title1
    assert (d2 / "phase2_patient_cohorts.xlsx").exists() and need2 and title2
    assert (d3 / "frontier_llm_routing_2026.xlsx").exists() and need3 and title3

