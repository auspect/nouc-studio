"""FinOps token economics and GPU cluster amortization formulas."""

from __future__ import annotations


def compute_blended_cost_per_1m_tokens(total_spend_usd: float, total_tokens_millions: float) -> float:
    """Compute blended effective cost per 1M tokens across cloud and local GPU tiers."""
    if total_tokens_millions <= 0.0:
        return 0.0
    return total_spend_usd / total_tokens_millions


def compute_tokens_per_kilowatt(tokens_per_sec: float, power_draw_kw: float) -> float:
    """Compute energy efficiency in generated tokens per second per kW."""
    if power_draw_kw <= 0.0:
        return 0.0
    return tokens_per_sec / power_draw_kw
