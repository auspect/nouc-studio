"""Resolve a constrained UI proposal against backend-owned calculation traces.

An architectural example, not OpenUI Lang, an A2UI payload, or a renderer.
Run: uv run python examples/ui_contract.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nouc_studio.graph.models import GraphNode, MetricLineageTrace, NodeKind, UncertaintyProfile


class MetricCardRequest(BaseModel):
    """The proposer may select a metric; it cannot supply its value or evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    component: Literal["metric_card"]
    metric_id: str = Field(min_length=1, max_length=200)


class ViewProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal["nouc-ui-proposal/1"]
    cards: list[MetricCardRequest] = Field(min_length=1, max_length=6)


def resolve_cards(proposal: ViewProposal, traces: list[MetricLineageTrace]) -> list[dict[str, object]]:
    """Bind only traces supplied by the trusted caller; do not fetch or run code."""
    by_id = {trace.metric_node.node_id: trace for trace in traces}
    if len(by_id) != len(traces):
        raise ValueError("Ambiguous backend metric IDs.")
    requested_ids = [card.metric_id for card in proposal.cards]
    if len(set(requested_ids)) != len(requested_ids):
        raise ValueError("Duplicate metric selection.")
    if any(metric_id not in by_id for metric_id in requested_ids):
        raise ValueError("Unknown metric ID.")

    cards: list[dict[str, object]] = []
    for metric_id in requested_ids:
        trace = by_id[metric_id]
        if trace.metric_node.kind != NodeKind.METRIC:
            raise ValueError("The referenced node is not a metric.")
        uncertainty = trace.propagated_uncertainty
        cards.append({
            "component": "metric_card",
            "metric_id": metric_id,
            "label": trace.metric_node.label,
            "value": trace.metric_node.value_preview,
            "unit": trace.metric_node.unit,
            "trust_grade": uncertainty.trust_grade.value,
            "heuristic_range": uncertainty.confidence_interval_95,
            "range_method": "Nouc heuristic; not a statistical confidence interval",
            "assumptions": uncertainty.assumptions,
            "caveats": uncertainty.caveats,
            "trace_metric_id": metric_id,
            "source_count": len(trace.upstream_sources),
            "validation_count": len(trace.validations),
        })
    return cards


def synthetic_trace() -> MetricLineageTrace:
    # An intentionally incomplete trace demonstrates that the UI must retain caveats.
    uncertainty = UncertaintyProfile(
        trust_grade="F",
        validation_pass_rate=0.0,
        assumptions=["Six synthetic records; this is a contract demonstration."],
        caveats=["No source or validation nodes in this standalone fixture. Uncertainty is unknown."],
    )
    return MetricLineageTrace(
        metric_node=GraphNode(
            node_id="synthetic_revenue",
            kind=NodeKind.METRIC,
            label="Synthetic revenue",
            value_preview=691900.0,
            unit="USD",
            uncertainty=uncertainty,
        ),
        propagated_uncertainty=uncertainty,
        natural_language_proof="Hand-calculated fixture only; use the walkthrough for actual source lineage.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=Path, help="Trusted local lineage_traces.json from the walkthrough.")
    parser.add_argument("--proposal", type=Path, help="JSON matching ViewProposal; otherwise selects the first metric.")
    args = parser.parse_args()
    traces = (
        [MetricLineageTrace.model_validate(item) for item in json.loads(args.traces.read_text(encoding="utf-8"))]
        if args.traces else [synthetic_trace()]
    )
    if not traces:
        parser.error("No metric traces available.")
    proposal = ViewProposal.model_validate_json(args.proposal.read_text(encoding="utf-8")) if args.proposal else ViewProposal(
        schema_version="nouc-ui-proposal/1",
        cards=[MetricCardRequest(component="metric_card", metric_id=traces[0].metric_node.node_id)],
    )
    print(json.dumps(resolve_cards(proposal, traces), indent=2))


if __name__ == "__main__":
    main()
