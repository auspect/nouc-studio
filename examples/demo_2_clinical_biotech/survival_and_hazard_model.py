"""Biostatistical efficacy and therapeutic window calculations for Phase II audit."""

from __future__ import annotations


def compute_therapeutic_utility_index(shrinkage_pct: float, grade3_ae_pct: float) -> float:
    """Compute benefit-risk therapeutic utility score balancing response vs Grade 3+ toxicity."""
    return shrinkage_pct - (1.5 * grade3_ae_pct)


def adjust_response_for_assay_cv(observed_pct: float, assay_cv_pct: float) -> tuple[float, float]:
    """Return 95% assay-calibrated sensitivity bounds for molecular response rate."""
    delta = observed_pct * (1.96 * (assay_cv_pct / 100.0))
    return (round(observed_pct - delta, 2), round(observed_pct + delta, 2))
