"""Pydantic models for Provenance, Code AST, Calculation Lineage, and Uncertainty Graphs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeKind(StrEnum):
    """Types of nodes in the unified Knowledge & Calculation Lineage DAG."""

    SOURCE_FILE = "source_file"
    SOURCE_FRAGMENT = "source_fragment"
    CODE_AST = "code_ast"
    MARIMO_CELL = "marimo_cell"
    TRANSFORM = "transform"
    VALIDATION_CHECK = "validation_check"
    METRIC = "metric"
    ASSUMPTION = "assumption"
    STUDIO_VIEW = "studio_view"


class EdgeKind(StrEnum):
    """Types of directed edges in the unified Knowledge & Calculation Lineage DAG."""

    EXTRACTED_FROM = "extracted_from"
    DEFINED_IN = "defined_in"
    DEPENDS_ON = "depends_on"
    TRANSFORMED_BY = "transformed_by"
    VALIDATED_BY = "validated_by"
    COMPUTES = "computes"
    CONSTRAINED_BY = "constrained_by"
    PROJECTED_INTO = "projected_into"


class TrustGrade(StrEnum):
    """Epistemic trust grade for any computed metric or view."""

    A_VERIFIED = "A"  # Exact calculation, 100% validation pass, high source confidence
    B_HIGH = "B"  # Verified calculation with minor imputation or bounded variance
    C_MODERATE = "C"  # Contains heuristic assumptions or partial source coverage
    D_LOW = "D"  # High epistemic uncertainty or failed non-critical data checks
    F_UNTRUSTED = "F"  # Failed critical validation or unverified code


class SourceCoordinates(BaseModel):
    """Exact physical location of a piece of data inside an ingested input file."""

    file_path: str = Field(description="Relative or absolute path to the source file.")
    file_hash_sha256: str = Field(description="SHA-256 digest of the raw file for auditability.")
    mime_type: str = Field(default="application/octet-stream")
    sheet_name: str | None = Field(default=None, description="Excel/tabular sheet name if applicable.")
    cell_range: str | None = Field(default=None, description="Excel cell range e.g. A1:G142.")
    page_number: int | None = Field(default=None, description="1-based page or slide number for PDF/PPTX.")
    line_start: int | None = Field(default=None, description="1-based start line for code/markdown/txt.")
    line_end: int | None = Field(default=None, description="1-based end line for code/markdown/txt.")
    section_title: str | None = Field(default=None, description="Document heading or AST symbol path.")


class UncertaintyProfile(BaseModel):
    """Quantitative and qualitative uncertainty profile attached to a node or metric."""

    extraction_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in raw data extraction (1.0 for native Parquet/CSV/Excel, <1.0 for OCR/PDF).",
    )
    data_completeness: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of non-null valid records contributing to this node.",
    )
    validation_pass_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of Pointblank / Monty assertions that passed on upstream inputs.",
    )
    epistemic_uncertainty_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated relative uncertainty percentage (+/- %) due to model/formula assumptions.",
    )
    confidence_interval_95: tuple[float, float] | None = Field(
        default=None,
        description="95% confidence or sensitivity interval (lower_bound, upper_bound) for numeric metrics.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions required for this calculation to hold.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Known data limitations, missing segments, or edge cases.",
    )
    trust_grade: TrustGrade = Field(
        default=TrustGrade.A_VERIFIED,
        description="Computed epistemic trust grade (A through F).",
    )

    @property
    def composite_confidence_score(self) -> float:
        """Compute composite confidence in [0.0, 1.0] combining extraction, completeness, QA, and epistemic penalty."""
        epistemic_factor = max(0.0, 1.0 - (self.epistemic_uncertainty_pct / 100.0))
        score = (
            0.30 * self.extraction_confidence
            + 0.25 * self.data_completeness
            + 0.25 * self.validation_pass_rate
            + 0.20 * epistemic_factor
        )
        return round(min(1.0, max(0.0, score)), 4)


class GraphNode(BaseModel):
    """A typed node in the Knowledge, AST & Calculation Lineage Graph."""

    node_id: str = Field(description="Unique deterministic identifier for the node.")
    kind: NodeKind = Field(description="Semantic category of the node.")
    label: str = Field(description="Human-readable title of the node.")
    description: str = Field(default="", description="Detailed explanation of what this node represents.")
    coordinates: SourceCoordinates | None = Field(
        default=None,
        description="Physical source coordinates if this node originates from a file.",
    )
    code_snippet: str | None = Field(
        default=None,
        description="Exact Polars, DuckDB SQL, or Python AST code executing at this node.",
    )
    formula_latex: str | None = Field(
        default=None,
        description="Mathematical representation of the calculation in LaTeX.",
    )
    value_preview: Any = Field(
        default=None,
        description="Computed scalar value, summary dict, or schema preview.",
    )
    unit: str | None = Field(default=None, description="Unit of measurement (e.g., EUR, %, ms, rows).")
    uncertainty: UncertaintyProfile = Field(
        default_factory=UncertaintyProfile,
        description="Uncertainty and trust profile at this node.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class GraphEdge(BaseModel):
    """A directed edge linking two GraphNodes in the lineage DAG."""

    source_id: str
    target_id: str
    kind: EdgeKind
    rationale: str = Field(default="", description="Explanation of how source influences target.")


class MetricLineageTrace(BaseModel):
    """Complete, step-by-step auditable proof trace for a single output metric."""

    metric_node: GraphNode
    upstream_sources: list[GraphNode] = Field(default_factory=list)
    transformations: list[GraphNode] = Field(default_factory=list)
    validations: list[GraphNode] = Field(default_factory=list)
    assumptions: list[GraphNode] = Field(default_factory=list)
    ordered_steps: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    propagated_uncertainty: UncertaintyProfile
    natural_language_proof: str = Field(
        description="Step-by-step human-auditable explanation from raw files to final number."
    )
