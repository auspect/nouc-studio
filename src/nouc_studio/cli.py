"""Command-Line Interface (`nouc`) for the Nouc Studio Multi-Agent Marimo Studio System."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nouc_studio.agents.orchestrator import MultiAgentOrchestrator
from nouc_studio.config import InsightsConfig
from nouc_studio.memory.models import FailureStage
from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.verification.doc_verifier import (
    DeepWikiClient,
    load_installed_marimo_studio_skill_reference,
    verify_live_python_symbol,
)
from nouc_studio.verification.gate import VerificationGate

app = typer.Typer(
    name="nouc",
    help="Nouc Studio: Self-evolving multi-agent system using Marimo & Monty sandboxes to build auditable, multi-view Marimo Studio apps.",
    no_args_is_help=True,
)
console = Console()


@app.command("init")
def init_command(
    project_dir: Annotated[
        Path, typer.Argument(help="Project to configure; defaults to the current directory.")
    ] = Path("."),
    agent: Annotated[str, typer.Option("--agent", help="Coding agent: copilot.")] = "copilot",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Inspect planned files without creating directories or files.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace conflicting files, keeping local backups first.")
    ] = False,
) -> None:
    """Install bundled Copilot instructions and skills in a consumer project."""
    from nouc_studio.bootstrap import BootstrapError, initialize_project

    try:
        result = initialize_project(
            project_dir, agent=agent, dry_run=dry_run, overwrite=overwrite,
        )
    except (BootstrapError, OSError, ValueError) as exc:
        console.print(f"Setup stopped: {exc}", markup=False)
        raise typer.Exit(code=1) from exc
    table = Table(title="Copilot setup preview" if dry_run else "Copilot project setup")
    table.add_column("Action")
    table.add_column("Project file")
    for entry in result.files:
        table.add_row(entry.action, entry.path)
    console.print(table)
    if result.backup_dir is not None:
        console.print(f"{'Planned backups' if dry_run else 'Backups'}: {result.backup_dir}", markup=False)
    if not dry_run:
        console.print(f"Project: {result.project_dir}", markup=False)
        console.print(
            "Open this folder in VS Code, select the Nouc Studio Copilot agent, "
            "and describe your application. Reload the VS Code window if the agent is not listed."
        )
        console.print(
            "Consumer checks: uv run ruff check <your source paths>; "
            "uv run ty check <your source paths>; uv run pytest -v. "
            "Install nouc-studio[verify] if these tools are missing.",
            markup=False,
        )


@app.command("build")
def build_command(
    need: Annotated[
        str,
        typer.Option("--need", "-n", help="Expressed user need or analytical objective."),
    ],
    inputs: Annotated[
        list[Path],
        typer.Option("--input", "-i", help="Input files or directories (Excel, PDF, DOCX, PPTX, MD, TXT, Images, Code)."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory for the generated Marimo Studio application."),
    ] = Path("dist/studio_app"),
    title: Annotated[
        str,
        typer.Option("--title", "-t", help="Application title."),
    ] = "Nouc Studio Application",
) -> None:
    """Run the 5-agent DAG pipeline to ingest files, compute lineage + uncertainty, verify in sandboxes, and build a Marimo Studio app."""
    cfg = InsightsConfig()
    orchestrator = MultiAgentOrchestrator(config=cfg)

    console.print(
        Panel.fit(
            f"[bold indigo]Nouc Studio Multi-Agent Pipeline[/bold indigo]\n"
            f"[bold]Objective:[/bold] {need}\n"
            f"[bold]Inputs:[/bold] {[str(p) for p in inputs]}\n"
            f"[bold]Output Directory:[/bold] {output_dir}",
            title="Starting Nouc Studio Build",
        )
    )

    with console.status("Starting agents...") as status:
        report = orchestrator.run_pipeline(
            user_need=need,
            input_paths=inputs,
            output_dir=output_dir,
            app_title=title,
            on_step=lambda agent_id, role: status.update(f"[cyan]{agent_id}[/cyan]: {role}"),
        )

    tel_table = Table(title="Multi-Agent DAG Execution Telemetry")
    tel_table.add_column("Agent ID", style="cyan")
    tel_table.add_column("Role", style="white")
    tel_table.add_column("Status", style="green")
    tel_table.add_column("Duration (ms)", justify="right")
    tel_table.add_column("Summary")
    for step in report.agent_telemetry:
        tel_table.add_row(step.agent_id, step.role, step.status, f"{step.duration_ms:.1f}", step.summary)
    console.print(tel_table)

    kpi_table = Table(title="Audited Metrics, Lineage & Epistemic Uncertainty")
    kpi_table.add_column("Metric ID", style="cyan")
    kpi_table.add_column("Label")
    kpi_table.add_column("Value", justify="right", style="bold")
    kpi_table.add_column("Trust Grade", justify="center")
    kpi_table.add_column("Uncertainty (±%)", justify="right")
    kpi_table.add_column("Heuristic range", justify="right")
    for trace in report.traces:
        u = trace.propagated_uncertainty
        ci_str = f"[{u.confidence_interval_95[0]}, {u.confidence_interval_95[1]}]" if u.confidence_interval_95 else "N/A"
        kpi_table.add_row(
            trace.metric_node.node_id,
            trace.metric_node.label,
            f"{trace.metric_node.value_preview} {trace.metric_node.unit or ''}".strip(),
            u.trust_grade.value,
            f"±{u.epistemic_uncertainty_pct:.2f}%",
            ci_str,
        )
    console.print(kpi_table)

    view_table = Table(title="Generated & Statically Validated Marimo Studio Views")
    view_table.add_column("View Name", style="magenta")
    view_table.add_column("Revision")
    view_table.add_column("Validation Passed", justify="center")
    view_table.add_column("Root Path")
    for v in report.studio_bundle.views:
        view_table.add_row(
            v.view_name,
            v.build_revision[:16],
            "PASS" if v.validation_passed else "FAIL",
            v.root_dir,
        )
    console.print(view_table)

    failures = []
    if not report.verification_report.all_passed:
        failures.append("notebook verification")
    if any(not view.validation_passed for view in report.studio_bundle.views):
        failures.append("Studio view validation")
    if any(not qa.all_passed for qa in report.pointblank_reports):
        failures.append("data QA")
    if any(not audit.passed for audit in report.epistemic_audits):
        failures.append("explanation audit")
    if failures:
        console.print(f"Build verification failed: {', '.join(failures)}.", markup=False)
        console.print(
            f"Inspect {output_dir / 'orchestration_report.json'} and run "
            f'nouc verify "{report.studio_bundle.notebook_path}" --ty.', markup=False,
        )
        raise typer.Exit(code=1)

    console.print(
        Panel.fit(
            f"[bold green]Build checks passed; browser acceptance remains required.[/bold green]\n"
            f"- Notebook: [cyan]{report.studio_bundle.notebook_path}[/cyan]\n"
            f"- Lineage Graph ({report.lineage_node_count} nodes, {report.lineage_edge_count} edges): [cyan]{report.studio_bundle.lineage_json_path}[/cyan]\n"
            f"- Launch Studio Editor: [bold yellow]{report.studio_bundle.launch_edit_command}[/bold yellow]\n"
            f"- Launch Studio App: [bold yellow]{report.studio_bundle.launch_run_command}[/bold yellow]",
            title="Marimo Studio Application",
        )
    )


@app.command("verify")
def verify_command(
    notebook: Annotated[Path, typer.Argument(help="Path to the Marimo notebook (.py) to verify.")],
    run_ty: Annotated[bool, typer.Option("--ty", help="Also run ty typecheck on the notebook.")] = False,
) -> None:
    """Run the RLVR Verification Gate (Marimo Reactive DAG + Ruff + Monty Sandbox + optional Ty) on a notebook."""
    cfg = InsightsConfig()
    memory = AdaptiveMemoryStore(cfg.local_memory_dir, cfg.global_memory_dir)
    gate = VerificationGate(memory=memory, cwd=cfg.project_root)

    report = gate.verify_notebook(
        notebook,
        monty_assertions=["1 + 1 == 2"],
        run_ty=run_ty,
    )
    tbl = Table(title=f"Verification Gate Report: {notebook.name}")
    tbl.add_column("Stage", style="cyan")
    tbl.add_column("Passed")
    tbl.add_column("Diagnostics / Remedies")
    for chk in report.checks:
        status = "[green]PASS[/green]" if chk.passed else "[red]FAIL[/red]"
        detail = "; ".join(chk.diagnostics[:3]) if chk.diagnostics else "Clean"
        if chk.matched_memory_remedies:
            detail += f" | Memory Fix: {chk.matched_memory_remedies[0].verified_fix_description}"
        tbl.add_row(chk.stage.value, status, detail)
    console.print(tbl)
    if not report.all_passed:
        raise typer.Exit(code=1)


@app.command("memory")
def memory_command(
    action: Annotated[
        str,
        typer.Argument(help="Action: 'list', 'rules', 'sync', or 'record'."),
    ] = "list",
    query: Annotated[
        str | None,
        typer.Option("--query", "-q", help="Search error signature or library."),
    ] = None,
    library: Annotated[
        str,
        typer.Option("--library", "-l", help="Library name when recording a failure."),
    ] = "marimo",
    error_message: Annotated[
        str | None,
        typer.Option("--error", "-e", help="Error message when recording a failure."),
    ] = None,
    fix: Annotated[
        str | None,
        typer.Option("--fix", "-f", help="Verified fix description when recording."),
    ] = None,
    rule: Annotated[
        str | None,
        typer.Option("--rule", "-r", help="Prevention rule when recording."),
    ] = None,
) -> None:
    """Inspect, query, sync, or record episodes in the Local + Global Cross-Project Adaptive Memory."""
    cfg = InsightsConfig()
    store = AdaptiveMemoryStore(cfg.local_memory_dir, cfg.global_memory_dir)

    if action == "sync":
        synced = store.sync_from_global()
        console.print(f"[green]Synced {synced} verified episodes from Global Memory ({cfg.global_memory_dir}).[/green]")
        return

    if action == "record":
        if not error_message or not fix or not rule:
            console.print("[red]--error, --fix, and --rule are required for 'record'.[/red]")
            raise typer.Exit(code=1)
        ep = store.record_failure_and_fix(
            stage=FailureStage.RUNTIME_EXECUTION,
            library=library,
            error_type="RecordedError",
            error_message=error_message,
            root_cause=error_message,
            verified_fix_description=fix,
            prevention_rule=rule,
            verified=True,
            promote_to_global=True,
        )
        console.print(f"[green]Recorded & promoted episode {ep.episode_id} to local + global memory.[/green]")
        return

    if action == "rules":
        for r in store.get_prevention_rules_for_prompt():
            console.print(f"• {r}")
        return

    episodes = (
        store.find_similar_failures(query)
        if query
        else store.list_episodes(include_global=True)
    )
    tbl = Table(title=f"Adaptive Failure/Fix Memory ({len(episodes)} episodes)")
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Library", style="magenta")
    tbl.add_column("Stage")
    tbl.add_column("Hits", justify="right")
    tbl.add_column("Error Type")
    tbl.add_column("Prevention Rule")
    for ep in episodes:
        tbl.add_row(
            ep.episode_id,
            ep.library,
            ep.stage.value,
            str(ep.hit_count),
            ep.error_type,
            ep.prevention_rule,
        )
    console.print(tbl)


@app.command("ground")
def ground_command(
    module_name: Annotated[str, typer.Option("--module", "-m", help="Python module to introspect live.")] = "marimo_studio",
    symbol_path: Annotated[str, typer.Option("--symbol", "-s", help="Dot-separated symbol path.")] = "",
    repo: Annotated[str | None, typer.Option("--repo", help="Optional GitHub repo to query via DeepWiki MCP.")] = None,
    question: Annotated[str | None, typer.Option("--question", help="Question for DeepWiki MCP.")] = None,
) -> None:
    """Zero-Blind-Trust live runtime introspection and DeepWiki / agent-plugin documentation lookup."""
    res = verify_live_python_symbol(module_name, symbol_path)
    console.print(Panel.fit(res.model_dump_json(indent=2), title=f"Live Symbol Introspection: {module_name}.{symbol_path}"))

    if module_name == "marimo_studio" and not symbol_path:
        ref = load_installed_marimo_studio_skill_reference("projections.md")
        console.print(Panel.fit(ref[:1000] + "\n...", title="Installed marimo-studio Skill Reference (projections.md)"))

    if repo and question:
        client = DeepWikiClient()
        dw = client.ask_repo_question(repo, question)
        console.print(Panel.fit(str(dw)[:1200], title=f"DeepWiki MCP ({repo})"))


@app.command("models")
def models_command() -> None:
    """Inspect active LLM model, Local/Self-Hosted AI endpoints, API keys, and Coding Agent integration status."""
    import os

    cfg = InsightsConfig()
    status = cfg.apply_llm_environment()

    tbl = Table(title="Nouc Studio Model & Coding Agent Configuration")
    tbl.add_column("Setting / Integration", style="cyan")
    tbl.add_column("Active Value / Status", style="green")
    tbl.add_column("How to Configure (.env or Environment)", style="white")

    tbl.add_row(
        "Active Runtime Mode",
        status["mode"],
        "Auto-detected from INSIGHTS_DEFAULT_LLM_MODEL, INSIGHTS_LLM_BASE_URL, and API keys",
    )
    tbl.add_row(
        "Default Model ID",
        status["model"],
        "INSIGHTS_DEFAULT_LLM_MODEL (e.g. google:gemini-3.8-flash, google:gemini-4-argon, anthropic:claude-sonnet-5-5, openai:gpt-6-sol, ollama:qwen3-coder:30b)",
    )
    tbl.add_row(
        "Custom Base URL",
        status["endpoint"],
        "INSIGHTS_LLM_BASE_URL (e.g. http://localhost:11434/v1 for Ollama, http://localhost:8000/v1 for vLLM)",
    )

    for key_name, provider_desc in [
        ("GEMINI_API_KEY", "Google Gemini Developer API (google-genai)"),
        ("GOOGLE_API_KEY", "Google Gemini / Vertex AI fallback key"),
        ("ANTHROPIC_API_KEY", "Anthropic Claude API"),
        ("OPENAI_API_KEY", "OpenAI or Self-Hosted vLLM / LM Studio / llama.cpp"),
        ("GITHUB_TOKEN", "GitHub Copilot / GitHub Models (https://models.github.ai/inference)"),
    ]:
        present = "[bold green]SET[/bold green]" if os.environ.get(key_name) else "[dim]not set[/dim]"
        tbl.add_row(f"Env: {key_name}", present, provider_desc)

    from nouc_studio.bootstrap import SKILL_NAMES

    for agent_file, desc in [
        (".github/copilot-instructions.md", "GitHub Copilot repository instructions"),
        (".github/agents/nouc-studio.agent.md", "Nouc Studio custom Copilot agent"),
        ("AGENTS.md", "Universal Coding Agent instructions (Copilot, Claude Code, Cursor, Antigravity)"),
        *((f"skills/{name}/SKILL.md", "Specialized Nouc Studio agent skill") for name in SKILL_NAMES),
    ]:
        exists = (cfg.project_root / agent_file).exists()
        tbl.add_row(f"Agent Config: {agent_file}", "[bold green]READY[/bold green]" if exists else "[yellow]MISSING[/yellow]", desc)

    console.print(tbl)


@app.command("demos")
def demos_command(
    demo: Annotated[
        str,
        typer.Option(
            "--demo",
            "-d",
            help="Demo to build & verify: 'all', 'demo_1_saas', 'demo_2_clinical', or 'demo_3_finops'.",
        ),
    ] = "all",
    examples_dir: Annotated[
        Path,
        typer.Option("--examples-dir", help="Directory where multimodal demo inputs are generated."),
    ] = Path("examples"),
    dist_dir: Annotated[
        Path,
        typer.Option("--dist-dir", help="Output directory for generated Marimo Studio applications."),
    ] = Path("dist"),
) -> None:
    """Build and verify the 3 realistic End-to-End multimodal Marimo Studio demos (SaaS M&A, Clinical Biotech, AI Infra FinOps)."""
    from nouc_studio.demos import build_and_verify_all_demos

    summaries = build_and_verify_all_demos(
        examples_root=examples_dir,
        dist_root=dist_dir,
        selected_demo=demo,
    )

    tbl = Table(title="Realistic End-to-End Marimo Studio Demos Summary")
    tbl.add_column("Demo ID", style="cyan")
    tbl.add_column("Domain", style="white")
    tbl.add_column("Files", justify="right")
    tbl.add_column("Polars Tables", justify="right")
    tbl.add_column("AST Symbols", justify="right")
    tbl.add_column("DAG (N/E)", justify="right")
    tbl.add_column("Metrics", justify="right")
    tbl.add_column("Studio Views", justify="center", style="magenta")
    tbl.add_column("RLVR Gate", justify="center")
    tbl.add_column("Notebook Path", style="green")

    for s in summaries:
        gate_str = "[bold green]PASS[/bold green]" if s.verification_passed else "[bold red]FAIL[/bold red]"
        tbl.add_row(
            s.demo_id,
            s.domain,
            str(s.ingested_files_count),
            str(s.tabular_tables_count),
            str(s.ast_symbols_count),
            f"{s.lineage_nodes_count}/{s.lineage_edges_count}",
            str(s.audited_metrics_count),
            ", ".join(s.studio_views),
            gate_str,
            s.notebook_path,
        )

    console.print(tbl)
    if any(not s.verification_passed for s in summaries):
        raise typer.Exit(code=1)


@app.command("studio")
def studio_command(
    notebook: Annotated[
        Path, typer.Argument(help="Studio notebook path (normally app.py).", envvar="NOUC_STUDIO_NOTEBOOK"),
    ] = Path("app.py"),
    edit: Annotated[bool, typer.Option("--edit", help="Open the editor and watch external Python edits.")] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Build and validate by executing notebook Python; do not start a server."),
    ] = False,
    headless: Annotated[bool, typer.Option("--headless", help="Start the server without opening a browser.")] = False,
    port: Annotated[int | None, typer.Option("--port", min=1, max=65535)] = None,
    runtime_timeout: Annotated[
        float, typer.Option("--runtime-timeout", min=1, help="Seconds per runtime validation (--check)."),
    ] = 60.0,
) -> None:
    """Build the required Studio artifacts, then launch Marimo in the project environment."""
    from nouc_studio.studio.launcher import (
        StudioLaunchError,
        prepare_studio,
        studio_server_command,
    )

    notebook = notebook.resolve()
    try:
        asyncio.run(prepare_studio(
            notebook, edit=edit, check_runtime=check, runtime_timeout=runtime_timeout,
            emit=lambda message: console.print(message, markup=False, soft_wrap=True),
        ))
    except StudioLaunchError as exc:
        console.print(f"Studio stopped: {exc}", markup=False, soft_wrap=True)
        raise typer.Exit(code=1) from exc
    if check:
        console.print("Build and isolated Python checks passed. Live browser interaction is a separate check.")
        return
    if edit:
        console.print("Editor: after a Python edit, run changed cells or Run all. Building a view does not run live Python.")
    console.print("Starting Marimo; open the local URL printed below. Stop with Ctrl+C.")
    command = studio_server_command(notebook, edit=edit, headless=headless, port=port)
    result = subprocess.run(command, check=False)
    raise typer.Exit(code=result.returncode)


@app.command("workbench")
def workbench_command(
    headless: Annotated[bool, typer.Option("--headless", help="Run workbench check without opening browser.")] = False,
) -> None:
    """Launch the interactive Meta-Workbench Marimo UI."""
    wb_path = Path(__file__).parent / "studio" / "workbench.py"
    if headless:
        cmd = [sys.executable, "-m", "marimo", "check", str(wb_path)]
    else:
        cmd = [sys.executable, "-m", "marimo", "edit", str(wb_path), "--no-sandbox", "--watch"]
    proc = subprocess.run(cmd, check=False)
    raise typer.Exit(code=proc.returncode)


if __name__ == "__main__":
    app()
