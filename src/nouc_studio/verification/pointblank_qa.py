"""Posit Pointblank data quality validation and LineageGraph proof registration."""

from __future__ import annotations

from typing import Any

import pointblank as pb
import polars as pl
from pydantic import BaseModel, Field

from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.graph.models import (
    EdgeKind,
    GraphNode,
    NodeKind,
    TrustGrade,
    UncertaintyProfile,
)


class PointblankValidationReport(BaseModel):
    """Structured summary of a Posit Pointblank validation interrogation on a Polars DataFrame."""

    table_id: str
    all_passed: bool
    step_count: int
    mean_pass_rate: float
    step_pass_rates: dict[int, float] = Field(default_factory=dict)
    failed_steps: list[int] = Field(default_factory=list)
    code_snippet: str


def run_pointblank_validation(
    df: pl.DataFrame,
    *,
    table_id: str,
    graph: LineageGraphEngine | None = None,
    upstream_node_id: str | None = None,
    required_columns: list[str] | None = None,
    non_null_columns: list[str] | None = None,
    positive_columns: list[str] | None = None,
) -> PointblankValidationReport:
    """Execute a Posit Pointblank validation suite on a Polars DataFrame and register proof in the LineageGraph."""
    cols_to_check = required_columns if required_columns is not None else list(df.columns)
    non_null_cols = (
        non_null_columns
        if non_null_columns is not None
        else [c for c in df.columns if df[c].null_count() == 0][:6]
    )

    validator: Any = pb.Validate(data=df, tbl_name=table_id)
    code_lines = [f"pb.Validate(data={table_id}, tbl_name={table_id!r})"]

    if cols_to_check:
        validator = validator.col_exists(columns=cols_to_check)
        code_lines.append(f".col_exists(columns={cols_to_check!r})")

    if non_null_cols and df.height > 0:
        validator = validator.col_vals_not_null(columns=non_null_cols)
        code_lines.append(f".col_vals_not_null(columns={non_null_cols!r})")

    if positive_columns and df.height > 0:
        valid_pos = [c for c in positive_columns if c in df.columns and df[c].dtype.is_numeric()]
        if valid_pos:
            validator = validator.col_vals_ge(columns=valid_pos, value=0)
            code_lines.append(f".col_vals_ge(columns={valid_pos!r}, value=0)")

    code_lines.append(".interrogate()")
    code_str = "".join(code_lines)

    if not cols_to_check and not non_null_cols:
        report = PointblankValidationReport(
            table_id=table_id,
            all_passed=True,
            step_count=0,
            mean_pass_rate=1.0,
            code_snippet=code_str,
        )
    else:
        interrogated = validator.interrogate()
        all_ok = bool(interrogated.all_passed())
        raw_f_passed: dict[int, float] = interrogated.f_passed() or {}
        step_rates = {int(k): round(float(v), 4) for k, v in raw_f_passed.items() if v is not None}
        mean_rate = round(sum(step_rates.values()) / len(step_rates), 4) if step_rates else 1.0
        failed_steps = [step_idx for step_idx, rate in step_rates.items() if rate < 1.0]
        report = PointblankValidationReport(
            table_id=table_id,
            all_passed=all_ok,
            step_count=len(step_rates),
            mean_pass_rate=mean_rate,
            step_pass_rates=step_rates,
            failed_steps=failed_steps,
            code_snippet=code_str,
        )

    if graph is not None:
        check_node_id = f"val_pb_{table_id}"
        caveats = (
            [f"Pointblank steps {report.failed_steps} had row-level failures (mean pass rate={report.mean_pass_rate * 100:.1f}%)."]
            if report.failed_steps
            else []
        )
        graph.add_node(
            GraphNode(
                node_id=check_node_id,
                kind=NodeKind.VALIDATION_CHECK,
                label=f"Pointblank QA: {table_id}",
                description=f"Pointblank interrogated {report.step_count} atomic steps (mean pass rate: {report.mean_pass_rate * 100:.1f}%).",
                code_snippet=report.code_snippet,
                value_preview={"all_passed": report.all_passed, "mean_pass_rate": report.mean_pass_rate},
                unit="ratio",
                uncertainty=UncertaintyProfile(
                    extraction_confidence=1.0,
                    data_completeness=1.0,
                    validation_pass_rate=report.mean_pass_rate,
                    epistemic_uncertainty_pct=round((1.0 - report.mean_pass_rate) * 20.0, 2),
                    caveats=caveats,
                    trust_grade=TrustGrade.A_VERIFIED if report.all_passed else TrustGrade.C_MODERATE,
                ),
            )
        )
        if upstream_node_id and graph.has_node(upstream_node_id):
            graph.add_edge(
                upstream_node_id,
                check_node_id,
                EdgeKind.VALIDATED_BY,
                rationale=f"Validated table '{table_id}' using Posit Pointblank.",
            )

    return report
