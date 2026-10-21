"""Interactive Meta-Workbench Marimo Notebook for driving the Nouc Studio Multi-Agent System."""

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title="Nouc Studio — Meta-Agent Workbench")


@app.cell
def imports():
    from pathlib import Path

    import marimo as mo
    import polars as pl

    from nouc_studio.agents.orchestrator import MultiAgentOrchestrator
    from nouc_studio.config import InsightsConfig
    from nouc_studio.verification.doc_verifier import verify_live_python_symbol
    from nouc_studio.verification.monty_sandbox import MontySandboxRunner

    return (
        InsightsConfig,
        MontySandboxRunner,
        MultiAgentOrchestrator,
        Path,
        mo,
        pl,
        verify_live_python_symbol,
    )


@app.cell
def workbench_controls(mo):
    need_input = mo.ui.text_area(
        value="Build an executive and audit-ready financial & engineering insights studio with full calculation lineage and uncertainty intervals.",
        label="Expressed Need / Objective",
        full_width=True,
    )
    input_path_box = mo.ui.text(
        value="src/nouc_studio",
        label="Input Files or Directory Path (Excel, PDF, DOCX, PPTX, MD, Code...)",
        full_width=True,
    )
    output_dir_box = mo.ui.text(
        value="dist/generated_studio_app",
        label="Target Marimo Studio Output Directory",
        full_width=True,
    )
    app_title_box = mo.ui.text(
        value="Nouc Studio — Executive & Lineage Suite",
        label="Generated Studio Application Title",
        full_width=True,
    )
    run_button = mo.ui.run_button(label="Run Nouc Studio Pipeline & Generate Marimo Studio App")

    controls_panel = mo.vstack(
        [
            mo.md("# Nouc Studio — Multi-Agent Marimo Studio Workbench"),
            mo.md(
                "Transform any expressed need + heterogeneous files into a verified, multi-view **`marimo-studio`** application with full Calculation Lineage, Pointblank QA, Monty Sandbox checks, and Dual-Tier Adaptive Memory."
            ),
            need_input,
            mo.hstack([input_path_box, output_dir_box, app_title_box], widths="equal", gap=1.5),
            run_button,
        ]
    )
    controls_panel
    return (
        app_title_box,
        controls_panel,
        input_path_box,
        need_input,
        output_dir_box,
        run_button,
    )


@app.cell
def pipeline_execution(
    InsightsConfig,
    MultiAgentOrchestrator,
    Path,
    app_title_box,
    input_path_box,
    mo,
    need_input,
    output_dir_box,
    pl,
    run_button,
):
    _cfg = InsightsConfig()
    orchestrator = MultiAgentOrchestrator(config=_cfg)

    if run_button.value:
        _raw_paths = [Path(p.strip()) for p in (input_path_box.value or "").split(",") if p.strip()]
        report = orchestrator.run_pipeline(
            user_need=need_input.value or "Analyze inputs with full lineage",
            input_paths=_raw_paths,
            output_dir=Path(output_dir_box.value or "dist/generated_studio_app"),
            app_title=app_title_box.value or "Insights Studio",
        )
        _tel_df = pl.DataFrame([t.model_dump() for t in report.agent_telemetry])
        _views_df = pl.DataFrame([v.model_dump() for v in report.studio_bundle.views])
        execution_summary = mo.vstack(
            [
                mo.callout(
                    mo.md(
                        f"**Studio Bundle Generated & Verified (`all_passed={report.verification_report.all_passed}`)**  \n"
                        f"- **Generated Notebook**: `{report.studio_bundle.notebook_path}`  \n"
                        f"- **Edit Studio Command**: `{report.studio_bundle.launch_edit_command}`  \n"
                        f"- **Run Studio Command**: `{report.studio_bundle.launch_run_command}`"
                    ),
                    kind="success" if report.verification_report.all_passed else "warn",
                ),
                mo.ui.table(_tel_df, label="Multi-Agent DAG Execution Telemetry"),
                mo.ui.table(_views_df, label="Generated & Validated Marimo Studio Views"),
            ]
        )
    else:
        report = None
        execution_summary = mo.callout(
            mo.md("Click **Run Multi-Agent Pipeline & Generate Marimo Studio App** above to build a target application, or explore the live Monty Sandbox & Adaptive Memory below."),
            kind="info",
        )

    execution_summary
    return execution_summary, orchestrator, report


@app.cell
def inspector_controls(mo):
    monty_code_box = mo.ui.text(
        value="round((125000.0 - 45000.0) / 125000.0 * 100.0, 2)",
        label="Test Formula in Pydantic Monty Rust Sandbox (Zero Ambient Access)",
        full_width=True,
    )
    symbol_box = mo.ui.text(
        value="pointblank:Validate",
        label="Live Runtime Symbol Verifier (module:symbol_path)",
    )
    return monty_code_box, symbol_box


@app.cell
def monty_and_memory_inspector(
    MontySandboxRunner,
    mo,
    monty_code_box,
    orchestrator,
    pl,
    symbol_box,
    verify_live_python_symbol,
):
    _runner = MontySandboxRunner()
    _m_res = _runner.run_snippet(monty_code_box.value or "0")

    _parts = (symbol_box.value or "polars:DataFrame").split(":", 1)
    _mod = _parts[0].strip()
    _sym = _parts[1].strip() if len(_parts) > 1 else ""
    _sym_res = verify_live_python_symbol(_mod, _sym)

    _episodes = [ep.model_dump(mode="json") for ep in orchestrator.memory.list_episodes(include_global=True)]
    _ep_df = pl.DataFrame(_episodes) if _episodes else pl.DataFrame()

    inspector_panel = mo.vstack(
        [
            mo.md("## Live Sandbox, Zero-Blind-Trust Grounding & Adaptive Memory"),
            mo.hstack([monty_code_box, symbol_box], widths="equal", gap=1.5),
            mo.md(
                f"- **Monty Sandbox Result**: `{_m_res.return_value}` (succeeded=`{_m_res.succeeded}`, latency=`{_m_res.duration_ms} ms`)  \n"
                f"- **Live Symbol Verification (`{_mod}.{_sym}`)**: exists=`{_sym_res.exists}`, kind=`{_sym_res.kind}`, signature=`{_sym_res.signature or _sym_res.typed_dict_keys}`"
            ),
            mo.ui.table(_ep_df, label="Local + Global Cross-Project Failure/Fix Memory (DuckDB + Rustworkx)"),
        ]
    )
    inspector_panel
    return (inspector_panel,)


if __name__ == "__main__":
    app.run()

