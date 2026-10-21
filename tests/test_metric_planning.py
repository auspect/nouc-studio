"""Business-facing generic summaries must not invent additive semantics."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from nouc_studio.agents.specialists import EpistemicArchitectAgent, EpistemicAssumption
from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.ingestion.pipeline import MultimodalIngestor
from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.verification.monty_sandbox import MontySandboxRunner

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def architect(tmp_path: Path) -> EpistemicArchitectAgent:
    memory = AdaptiveMemoryStore(tmp_path / "local-memory", tmp_path / "global-memory")
    return EpistemicArchitectAgent(memory, llm_model="offline")


@pytest.mark.parametrize(
    ("source", "additive_column", "expected_total", "descriptive_values", "rows"),
    [
        (
            "demo_3_ai_infra_finops/frontier_llm_routing_2026.xlsx",
            "monthly_requests_k",
            5560.0,
            {"p99_ttft_ms": 285.0, "cost_per_1m_tokens_usd": 1.4567},
            6,
        ),
        (
            "demo_2_clinical_biotech/phase2_patient_cohorts.xlsx",
            "enrolled_patients",
            155.0,
            {"tumor_shrinkage_median_pct": 41.74, "ctdna_molecular_response_pct": 58.075},
            5,
        ),
    ],
)
def test_real_demo_plans_keep_counts_but_never_total_non_additive_measurements(
    tmp_path: Path,
    architect: EpistemicArchitectAgent,
    source: str,
    additive_column: str,
    expected_total: float,
    descriptive_values: dict[str, float],
    rows: int,
) -> None:
    manifest = MultimodalIngestor(tmp_path / "data", LineageGraphEngine()).ingest_paths(
        [EXAMPLES / source]
    )
    specs = architect.design_metrics_plan("Explain the source data honestly.", manifest)
    sandbox = MontySandboxRunner()
    totals = {spec.column_name: spec for spec in specs if spec.aggregation == "sum"}
    assert set(totals) == {additive_column}
    total = totals[additive_column]
    assert sandbox.run_snippet(total.monty_expression, inputs=total.monty_inputs).return_value == expected_total

    coverage = next(spec for spec in specs if spec.aggregation == "count")
    assert coverage.monty_inputs == {"row_count": rows}
    means = {spec.column_name: spec for spec in specs if spec.aggregation == "mean"}
    for column, expected in descriptive_values.items():
        metric = means[column]
        assert metric.label.startswith("Descriptive Mean ")
        assert "Unweighted arithmetic mean of non-null source rows" in metric.assumptions[0]
        result = sandbox.run_snippet(metric.monty_expression, inputs=metric.monty_inputs)
        assert result.succeeded
        assert result.return_value == pytest.approx(expected)


def test_rate_duration_and_unit_price_have_descriptive_means_only(
    tmp_path: Path, architect: EpistemicArchitectAgent,
) -> None:
    source = tmp_path / "operations.csv"
    source.write_text(
        "error_rate,duration_seconds,unit_price_usd\n0.01,10,2.5\n0.03,30,7.5\n",
        encoding="utf-8",
    )
    manifest = MultimodalIngestor(tmp_path / "data", LineageGraphEngine()).ingest_paths([source])

    specs = architect.design_metrics_plan("Review service operations.", manifest)

    assert not any(spec.aggregation == "sum" for spec in specs)
    assert {spec.column_name for spec in specs if spec.aggregation == "mean"} == {
        "error_rate", "duration_seconds", "unit_price_usd",
    }


def test_ast_metadata_stays_ingested_without_executive_metrics(
    tmp_path: Path, architect: EpistemicArchitectAgent,
) -> None:
    source = tmp_path / "codebase_revenue.csv"
    source.write_text("revenue_usd,operating_cost\n100,40\n200,70\n", encoding="utf-8")
    manifest = MultimodalIngestor(tmp_path / "data", LineageGraphEngine()).ingest_paths(
        [source, EXAMPLES / "sample_bundle/pricing_model.py", EXAMPLES / "sample_bundle/methodology_notes.md"]
    )
    assert manifest.code_symbols
    assert manifest.code_symbols_parquet is not None
    assert Path(manifest.code_symbols_parquet).exists()
    assert any(table.table_id == "codebase_ast_symbols" for table in manifest.tabular_artifacts)

    specs = architect.design_metrics_plan("Explain revenue and source coverage.", manifest)

    assert not any(spec.table_id == "codebase_ast_symbols" for spec in specs)
    # Prefixes alone must not hide a legitimate source table, and document
    # coverage remains available alongside primary tabular coverage.
    assert any(spec.metric_id == "metric_codebase_revenue_row_count" for spec in specs)
    assert any(spec.metric_id == "metric_document_evidence_chunks" for spec in specs)
    assert {spec.column_name for spec in specs if spec.aggregation == "sum"} == {
        "revenue_usd", "operating_cost",
    }


@pytest.mark.parametrize("output_kind", ["typed", "padded", "wrong_shape", "too_long"])
def test_llm_assumption_uses_bounded_typed_output(
    tmp_path: Path, architect: EpistemicArchitectAgent,
    monkeypatch: pytest.MonkeyPatch, output_kind: str,
) -> None:
    import pydantic_ai

    source = tmp_path / "sales.csv"
    source.write_text("sales\n100\n200\n", encoding="utf-8")
    manifest = MultimodalIngestor(tmp_path / "data", LineageGraphEngine()).ingest_paths([source])
    baseline = architect.design_metrics_plan("Review sales.", manifest)
    note = "Check source coverage."
    # A valid assumption at the length boundary must be preserved, not sliced.
    note = note + " " + "x" * (200 - len(note) - 1)

    class FakeAgent:
        def __init__(
            self, model: str, *, output_type: type[EpistemicAssumption], system_prompt: str,
        ) -> None:
            assert model == "ollama:test"
            assert output_type is EpistemicAssumption
            assert system_prompt == (
                "Provide one concise epistemic assumption to watch out for given the user need."
            )
            self.output_type = output_type

        def run_sync(self, prompt: str) -> SimpleNamespace:
            assert prompt == "User need: Review sales."
            if output_kind == "wrong_shape":
                return SimpleNamespace(output="Unexpected unstructured text")
            if output_kind == "padded":
                # Whitespace must be stripped before the length bound applies.
                return SimpleNamespace(output=self.output_type(output=f"  {note}  "))
            text = note if output_kind == "typed" else note + "x"
            return SimpleNamespace(output=self.output_type(output=text))

    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    architect.llm_model = "ollama:test"
    specs = architect.design_metrics_plan("Review sales.", manifest)
    if output_kind in {"typed", "padded"}:
        assert specs[0].assumptions == baseline[0].assumptions + [f"[LLM Epistemic Note] {note}"]
    else:
        assert specs == baseline
