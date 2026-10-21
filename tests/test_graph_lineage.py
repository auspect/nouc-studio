"""Unit tests for the Rustworkx Knowledge, AST & Calculation Lineage Graph and Uncertainty Propagation."""

from pathlib import Path

from nouc_studio.graph import (
    EdgeKind,
    GraphNode,
    LineageGraphEngine,
    NodeKind,
    SourceCoordinates,
    TrustGrade,
    UncertaintyProfile,
)


def test_lineage_graph_trace_and_uncertainty_propagation(tmp_path: Path) -> None:
    engine = LineageGraphEngine()

    src_node = GraphNode(
        node_id="src_excel_q4",
        kind=NodeKind.SOURCE_FRAGMENT,
        label="Q4 Financial Workbook [Revenue]",
        description="Raw Q4 revenue sheet",
        coordinates=SourceCoordinates(
            file_path="finance/q4_results.xlsx",
            file_hash_sha256="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
            sheet_name="Revenue",
            cell_range="A1:E120",
        ),
        uncertainty=UncertaintyProfile(
            extraction_confidence=0.98,
            data_completeness=0.95,
            validation_pass_rate=1.0,
            epistemic_uncertainty_pct=1.5,
            caveats=["December regional adjustments pending final audit."],
        ),
    )
    val_node = GraphNode(
        node_id="val_pb_q4",
        kind=NodeKind.VALIDATION_CHECK,
        label="Pointblank QA: q4_revenue",
        description="Checked non-null and positive revenue constraints.",
        code_snippet="pb.Validate(data=q4).col_vals_gt(columns=['net_revenue'], value=0).interrogate()",
        uncertainty=UncertaintyProfile(
            validation_pass_rate=0.99,
            epistemic_uncertainty_pct=0.5,
        ),
    )
    assump_node = GraphNode(
        node_id="assump_fx",
        kind=NodeKind.ASSUMPTION,
        label="Constant FX Rate Assumption",
        description="EUR/USD conversion fixed at 1.08 for Q4 aggregation.",
        uncertainty=UncertaintyProfile(
            epistemic_uncertainty_pct=2.0,
            assumptions=["EUR/USD conversion fixed at 1.08 for Q4 aggregation."],
        ),
    )
    tx_node = GraphNode(
        node_id="tx_net_rev",
        kind=NodeKind.TRANSFORM,
        label="Aggregate Net Revenue",
        description="Sum net revenue across validated rows.",
        code_snippet="q4.filter(pl.col('valid')).select(pl.col('net_revenue').sum())",
        formula_latex=r"R_{\text{net}} = \sum_{i=1}^{N} r_i",
        uncertainty=UncertaintyProfile(epistemic_uncertainty_pct=1.0),
    )
    metric_node = GraphNode(
        node_id="metric_total_rev",
        kind=NodeKind.METRIC,
        label="Total Q4 Net Revenue",
        description="Headline audited Q4 revenue.",
        value_preview=1450000.0,
        unit="EUR",
        uncertainty=UncertaintyProfile(epistemic_uncertainty_pct=1.0),
    )

    for n in (src_node, val_node, assump_node, tx_node, metric_node):
        engine.add_node(n)

    engine.add_edge("src_excel_q4", "val_pb_q4", EdgeKind.VALIDATED_BY)
    engine.add_edge("src_excel_q4", "tx_net_rev", EdgeKind.TRANSFORMED_BY)
    engine.add_edge("val_pb_q4", "tx_net_rev", EdgeKind.VALIDATED_BY)
    engine.add_edge("assump_fx", "tx_net_rev", EdgeKind.CONSTRAINED_BY)
    engine.add_edge("tx_net_rev", "metric_total_rev", EdgeKind.COMPUTES)

    assert engine.is_acyclic()
    assert engine.node_count == 5
    assert engine.edge_count == 5

    trace = engine.trace_metric_lineage("metric_total_rev")
    assert trace.metric_node.value_preview == 1450000.0
    assert len(trace.upstream_sources) == 1
    assert len(trace.validations) == 1
    assert len(trace.assumptions) == 1
    assert trace.propagated_uncertainty.trust_grade in (TrustGrade.A_VERIFIED, TrustGrade.B_HIGH)
    assert trace.propagated_uncertainty.confidence_interval_95 is not None
    low, high = trace.propagated_uncertainty.confidence_interval_95
    assert low < 1450000.0 < high
    assert "A1:E120" in trace.natural_language_proof
    assert "EUR/USD conversion fixed at 1.08" in trace.natural_language_proof

    # Test JSON round-trip and Mermaid rendering
    json_file = tmp_path / "graph.json"
    engine.save_json(json_file)
    reloaded = LineageGraphEngine.load_json(json_file)
    assert reloaded.node_count == 5
    assert "flowchart LR" in reloaded.to_mermaid()
