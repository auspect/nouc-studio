"""Reference pricing and margin calculation formulas for AST lineage extraction."""

from __future__ import annotations


def compute_net_margin(revenue: float, operating_cost: float) -> float:
    """Compute net operating margin from revenue and operating cost."""
    if revenue <= 0.0:
        return 0.0
    return (revenue - operating_cost) / revenue


def apply_sensitivity_shock(baseline_value: float, shock_pct: float) -> float:
    """Apply a percentage scenario shock to a baseline KPI value."""
    return baseline_value * (1.0 + (shock_pct / 100.0))
