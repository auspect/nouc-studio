"""Build the synthetic CSV example with isolated memory and explicit checks.

Run from a checkout: uv run python examples/offline_walkthrough.py
This is a project script; the generated Marimo notebook carries PEP 723 metadata.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from nouc_studio.agents.orchestrator import MultiAgentOrchestrator, OrchestrationReport
from nouc_studio.config import InsightsConfig
from nouc_studio.verification.gate import VerificationGate

ROOT = Path(__file__).resolve().parents[1]


def check_figures(report: OrchestrationReport) -> None:
    """Compare computed figures with hand-calculated expectations for the CSV."""
    expectations = {("*", "count"): 6, ("revenue", "sum"): 691900, ("operating_cost", "sum"): 252100}
    values = {trace.metric_node.node_id: trace.metric_node.value_preview for trace in report.traces}
    for (column, aggregation), expected in expectations.items():
        matches = [
            spec for spec in report.planned_metrics
            if spec.column_name == column and spec.aggregation == aggregation
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one {aggregation} metric for {column}.")
        actual = values[matches[0].metric_id]
        if not isinstance(actual, (int, float)) or not math.isclose(actual, expected, abs_tol=1e-6):
            raise RuntimeError(f"Incorrect {aggregation} for {column}: {actual!r}; expected {expected}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "public-example")
    args = parser.parse_args()
    output = args.output.resolve()
    # Refuse replacement: generated Studio metadata is rebuilt destructively by the core generator.
    if output.exists():
        parser.error("Output already exists. Choose a new directory with --output.")
    output.mkdir(parents=True)

    with TemporaryDirectory(prefix="nouc-public-example-") as scratch:
        memory_root = Path(scratch)
        config = InsightsConfig(
            _env_file=None,
            project_root=ROOT,
            default_llm_model="offline",
            local_memory_dir=memory_root / "local",
            global_memory_dir=memory_root / "global",
        )
        orchestrator = MultiAgentOrchestrator(config)
        report = orchestrator.run_pipeline(
            user_need="Inspect six synthetic records and their exploratory totals and evidence.",
            input_paths=[ROOT / "examples" / "sample_bundle" / "quarterly_financials.csv"],
            output_dir=output,
            app_title="Synthetic data walkthrough",
        )
        check_figures(report)
        if not report.verification_report.all_passed or not all(a.passed for a in report.epistemic_audits):
            raise RuntimeError("Build checks failed. Inspect the local orchestration report.")
        if {view.view_name for view in report.studio_bundle.views} != {"main", "audit", "ops"}:
            raise RuntimeError("Expected all three Studio views.")
        if not all(view.validation_passed for view in report.studio_bundle.views):
            raise RuntimeError("Studio view validation failed.")
        gate = VerificationGate(memory=orchestrator.memory, cwd=ROOT)
        verification = gate.verify_notebook(Path(report.studio_bundle.notebook_path), run_ty=True)
        (output / "example_verification.json").write_text(
            verification.model_dump_json(indent=2), encoding="utf-8",
        )
        if not verification.all_passed:
            raise RuntimeError("Verification failed. Inspect example_verification.json.")

    # No paths, raw source records or memory episodes in this console summary.
    print(json.dumps({
        "input": "six synthetic CSV rows",
        "expected_figures_passed": True,
        "verification_with_ty_passed": True,
        "views": [view.view_name for view in report.studio_bundle.views],
        "browser_acceptance": "unverified by this script",
    }, indent=2))


if __name__ == "__main__":
    main()
