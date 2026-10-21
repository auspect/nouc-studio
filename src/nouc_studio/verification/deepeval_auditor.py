"""Epistemic Faithfulness, Numerical Proof, and Uncertainty Calibration Auditor (DeepEval-compatible)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from nouc_studio.graph.models import MetricLineageTrace, TrustGrade


class EpistemicAuditReport(BaseModel):
    """Audit result verifying that natural-language explanations match calculation lineage & uncertainty."""

    metric_id: str
    passed: bool
    numerical_faithfulness_score: float = Field(ge=0.0, le=1.0)
    provenance_citation_score: float = Field(ge=0.0, le=1.0)
    uncertainty_calibration_score: float = Field(ge=0.0, le=1.0)
    composite_audit_score: float = Field(ge=0.0, le=1.0)
    findings: list[str] = Field(default_factory=list)


def audit_metric_explanation(
    trace: MetricLineageTrace,
    explanation_text: str | None = None,
) -> EpistemicAuditReport:
    """Audit an explanation against a MetricLineageTrace for numerical accuracy, provenance, and uncertainty disclosure."""
    text = explanation_text if explanation_text is not None else trace.natural_language_proof
    findings: list[str] = []

    # 1. Numerical faithfulness check
    expected_val = trace.metric_node.value_preview
    num_score = 1.0
    if isinstance(expected_val, (int, float)) and not isinstance(expected_val, bool):
        formatted_candidates = {
            str(expected_val),
            f"{float(expected_val):.1f}",
            f"{float(expected_val):.2f}",
            f"{float(expected_val):,.2f}",
            f"{float(expected_val):,.0f}",
        }
        if not any(cand in text for cand in formatted_candidates):
            num_score = 0.4
            findings.append(
                f"Metric value '{expected_val}' is not explicitly cited in the explanation text."
            )

    # 2. Provenance citation check
    prov_score = 1.0
    if trace.upstream_sources:
        cited_sources = sum(
            1
            for src in trace.upstream_sources
            if src.label.lower() in text.lower()
            or (src.coordinates and PathLike_basename(src.coordinates.file_path).lower() in text.lower())
        )
        prov_score = round(cited_sources / len(trace.upstream_sources), 4)
        if prov_score < 1.0:
            findings.append(
                f"Only {cited_sources}/{len(trace.upstream_sources)} upstream source artifacts are cited in the proof."
            )

    # 3. Uncertainty & epistemic humility check
    u = trace.propagated_uncertainty
    unc_score = 1.0
    uncertainty_keywords = (
        "uncertainty",
        "confidence",
        "grade",
        "interval",
        "assumption",
        "caveat",
        "±",
        "incertitude",
    )
    has_uncertainty_mention = any(kw in text.lower() for kw in uncertainty_keywords)
    if not has_uncertainty_mention:
        unc_score = 0.3
        findings.append("Explanation lacks explicit uncertainty / confidence grade disclosure.")
    elif u.trust_grade in (TrustGrade.C_MODERATE, TrustGrade.D_LOW, TrustGrade.F_UNTRUSTED) and (u.caveats or u.assumptions):
        # Must mention at least one caveat or assumption when trust grade is C/D/F
        mentioned = any(
            re.sub(r"[^a-z0-9 ]", "", item.lower())[:18] in re.sub(r"[^a-z0-9 ]", "", text.lower())
            for item in [*u.assumptions, *u.caveats]
            if len(item) >= 5
        )
        if not mentioned:
            unc_score = 0.5
            findings.append(
                f"Metric has TrustGrade {u.trust_grade.value} (`±{u.epistemic_uncertainty_pct}%`), but specific caveats/assumptions were omitted."
            )

    composite = round(0.40 * num_score + 0.30 * prov_score + 0.30 * unc_score, 4)
    passed = composite >= 0.75 and num_score >= 0.8

    return EpistemicAuditReport(
        metric_id=trace.metric_node.node_id,
        passed=passed,
        numerical_faithfulness_score=num_score,
        provenance_citation_score=prov_score,
        uncertainty_calibration_score=unc_score,
        composite_audit_score=composite,
        findings=findings,
    )


def PathLike_basename(raw_path: str) -> str:
    """Return final path segment across POSIX and Windows separators."""
    norm = raw_path.replace("\\", "/").rstrip("/")
    return norm.split("/")[-1] if "/" in norm else norm
