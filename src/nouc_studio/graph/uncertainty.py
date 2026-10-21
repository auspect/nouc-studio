"""Quantitative and epistemic uncertainty propagation across the Calculation Lineage Graph."""

from __future__ import annotations

import math

from nouc_studio.graph.models import (
    GraphNode,
    NodeKind,
    TrustGrade,
    UncertaintyProfile,
)


def compute_trust_grade(
    extraction_confidence: float,
    data_completeness: float,
    validation_pass_rate: float,
    epistemic_uncertainty_pct: float,
) -> TrustGrade:
    """Assign a discrete epistemic TrustGrade (A-F) based on quantitative lineage metrics."""
    if validation_pass_rate < 0.5 or extraction_confidence < 0.4:
        return TrustGrade.F_UNTRUSTED

    epistemic_factor = max(0.0, 1.0 - (epistemic_uncertainty_pct / 100.0))
    composite = (
        0.30 * extraction_confidence
        + 0.25 * data_completeness
        + 0.25 * validation_pass_rate
        + 0.20 * epistemic_factor
    )

    if composite >= 0.92 and validation_pass_rate >= 0.98 and epistemic_uncertainty_pct <= 5.0:
        return TrustGrade.A_VERIFIED
    if composite >= 0.80 and validation_pass_rate >= 0.90:
        return TrustGrade.B_HIGH
    if composite >= 0.65:
        return TrustGrade.C_MODERATE
    if composite >= 0.45:
        return TrustGrade.D_LOW
    return TrustGrade.F_UNTRUSTED


def propagate_uncertainty(
    metric_node: GraphNode,
    upstream_nodes: list[GraphNode],
) -> UncertaintyProfile:
    """Propagate uncertainty from all upstream sources, transforms, validations, and assumptions.

    Uses root-sum-square (quadrature) combination for independent relative epistemic uncertainties,
    minimum/geometric aggregation for extraction confidence & completeness, and aggregates all
    explicit assumptions and caveats.
    """
    if not upstream_nodes:
        grade = compute_trust_grade(
            metric_node.uncertainty.extraction_confidence,
            metric_node.uncertainty.data_completeness,
            metric_node.uncertainty.validation_pass_rate,
            metric_node.uncertainty.epistemic_uncertainty_pct,
        )
        return metric_node.uncertainty.model_copy(update={"trust_grade": grade})

    extraction_scores: list[float] = [metric_node.uncertainty.extraction_confidence]
    completeness_scores: list[float] = [metric_node.uncertainty.data_completeness]
    validation_scores: list[float] = []
    epistemic_squares: float = metric_node.uncertainty.epistemic_uncertainty_pct**2
    assumptions: list[str] = list(metric_node.uncertainty.assumptions)
    caveats: list[str] = list(metric_node.uncertainty.caveats)

    for node in upstream_nodes:
        u = node.uncertainty
        if node.kind in (NodeKind.SOURCE_FILE, NodeKind.SOURCE_FRAGMENT):
            extraction_scores.append(u.extraction_confidence)
            completeness_scores.append(u.data_completeness)
        elif node.kind == NodeKind.VALIDATION_CHECK:
            validation_scores.append(u.validation_pass_rate)
        elif node.kind in (NodeKind.TRANSFORM, NodeKind.ASSUMPTION, NodeKind.MARIMO_CELL):
            completeness_scores.append(u.data_completeness)

        epistemic_squares += u.epistemic_uncertainty_pct**2

        for item in u.assumptions:
            if item not in assumptions:
                assumptions.append(item)
        for item in u.caveats:
            if item not in caveats:
                caveats.append(item)
        if node.kind == NodeKind.ASSUMPTION and node.description and node.description not in assumptions:
            assumptions.append(node.description)

    min_extraction = min(extraction_scores) if extraction_scores else 1.0
    avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 1.0
    val_pass_rate = (
        sum(validation_scores) / len(validation_scores)
        if validation_scores
        else metric_node.uncertainty.validation_pass_rate
    )

    # Quadrature sum of epistemic uncertainties + penalty for incomplete data
    incompleteness_penalty_pct = max(0.0, (1.0 - avg_completeness) * 25.0)
    extraction_penalty_pct = max(0.0, (1.0 - min_extraction) * 30.0)
    combined_epistemic_pct = round(
        math.sqrt(epistemic_squares + incompleteness_penalty_pct**2 + extraction_penalty_pct**2),
        2,
    )

    ci_95 = metric_node.uncertainty.confidence_interval_95
    if ci_95 is None and isinstance(metric_node.value_preview, (int, float)) and not isinstance(metric_node.value_preview, bool):
        val = float(metric_node.value_preview)
        delta = abs(val) * (combined_epistemic_pct / 100.0)
        ci_95 = (round(val - delta, 4), round(val + delta, 4))

    grade = compute_trust_grade(
        extraction_confidence=min_extraction,
        data_completeness=avg_completeness,
        validation_pass_rate=val_pass_rate,
        epistemic_uncertainty_pct=combined_epistemic_pct,
    )

    return UncertaintyProfile(
        extraction_confidence=round(min_extraction, 4),
        data_completeness=round(avg_completeness, 4),
        validation_pass_rate=round(val_pass_rate, 4),
        epistemic_uncertainty_pct=combined_epistemic_pct,
        confidence_interval_95=ci_95,
        assumptions=assumptions,
        caveats=caveats,
        trust_grade=grade,
    )
