"""Audited SaaS M&A valuation and cohort retention formulas."""

from __future__ import annotations


def compute_net_dollar_retention(starting_arr: float, expansion_arr: float, churned_arr: float) -> float:
    """Compute Net Dollar Retention (NDR) ratio from cohort ARR flows."""
    if starting_arr <= 0.0:
        return 0.0
    return ((starting_arr + expansion_arr - churned_arr) / starting_arr) * 100.0


def compute_rule_of_40(arr_growth_pct: float, fcf_margin_pct: float) -> float:
    """Compute SaaS Rule of 40 composite efficiency index."""
    return arr_growth_pct + fcf_margin_pct


def compute_enterprise_value(ending_arr_usd: float, ev_multiple: float, ndr_pct: float) -> float:
    """Compute NDR-adjusted implied Enterprise Value (USD)."""
    ndr_premium = max(0.8, min(1.35, ndr_pct / 110.0))
    return ending_arr_usd * ev_multiple * ndr_premium
