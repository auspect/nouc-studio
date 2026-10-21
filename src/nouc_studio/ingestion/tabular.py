"""Rust-native Polars + FastExcel (Calamine) tabular ingestion with cell-range provenance."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import fastexcel
import polars as pl
from pydantic import BaseModel, Field

from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.graph.models import (
    EdgeKind,
    GraphNode,
    NodeKind,
    SourceCoordinates,
    TrustGrade,
    UncertaintyProfile,
)


class TabularArtifact(BaseModel):
    """Metadata and schema summary for an ingested Polars table."""

    table_id: str
    source_path: str
    sheet_name: str | None = None
    parquet_path: str
    row_count: int
    col_count: int
    columns: list[str]
    dtypes: dict[str, str]
    null_ratios: dict[str, float]
    overall_completeness: float
    cell_range: str
    numeric_summary: dict[str, dict[str, float]] = Field(default_factory=dict)


def _col_index_to_excel_letters(n: int) -> str:
    """Convert 1-based column count to Excel column letters (1 -> A, 26 -> Z, 27 -> AA)."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def _sanitize_identifier(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip().lower()).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"tbl_{cleaned}"
    return cleaned


def _compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _profile_and_persist_dataframe(
    df: pl.DataFrame,
    *,
    table_id: str,
    source_path: Path,
    file_hash: str,
    mime_type: str,
    output_dir: Path,
    graph: LineageGraphEngine,
    file_node_id: str,
    sheet_name: str | None = None,
) -> TabularArtifact:
    """Profile a Polars DataFrame, persist it as Parquet, and register provenance nodes in the graph."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_file = output_dir / f"{table_id}.parquet"
    df.write_parquet(parquet_file)

    row_count = df.height
    col_count = df.width
    columns = list(df.columns)
    dtypes = {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes, strict=False)}

    null_counts_frame = df.null_count()
    null_counts = null_counts_frame.row(0, named=True) if columns else {}
    null_ratios = {
        col: round(nulls / row_count, 4) if row_count > 0 else 0.0
        for col, nulls in null_counts.items()
    }

    overall_completeness = (
        round(1.0 - (sum(null_ratios.values()) / len(null_ratios)), 4) if null_ratios else 1.0
    )
    end_col = _col_index_to_excel_letters(max(1, col_count))
    cell_range = f"A1:{end_col}{max(1, row_count + 1)}"

    numeric_summary: dict[str, dict[str, float]] = {}
    numeric_exprs: list[pl.Expr] = []
    for col, dtype in zip(df.columns, df.dtypes, strict=False):
        if dtype.is_numeric() and row_count > null_counts[col]:
            values = pl.col(col).drop_nulls().cast(pl.Float64)
            numeric_exprs.append(
                pl.struct(
                    values.sum().alias("sum"),
                    values.mean().alias("mean"),
                    values.std().alias("std"),
                    values.min().alias("min"),
                    values.max().alias("max"),
                ).alias(col)
            )
    if numeric_exprs:
        summaries = df.select(numeric_exprs).row(0, named=True)
        numeric_summary = {
            col: {
                key: round(float(value), 4) if isinstance(value, (int, float)) else 0.0
                for key, value in stats.items()
            }
            for col, stats in summaries.items()
        }

    coords = SourceCoordinates(
        file_path=str(source_path),
        file_hash_sha256=file_hash,
        mime_type=mime_type,
        sheet_name=sheet_name,
        cell_range=cell_range,
    )
    caveats: list[str] = []
    if overall_completeness < 1.0:
        missing_cols = [c for c, r in null_ratios.items() if r > 0]
        caveats.append(
            f"Table '{table_id}' has missing values in columns {missing_cols} (completeness={overall_completeness * 100:.1f}%)."
        )

    fragment_node = GraphNode(
        node_id=f"src_tbl_{table_id}",
        kind=NodeKind.SOURCE_FRAGMENT,
        label=f"Table {table_id}" + (f" [{sheet_name}]" if sheet_name else ""),
        description=f"Tabular dataset with {row_count} rows and {col_count} columns ({', '.join(columns[:8])}).",
        coordinates=coords,
        code_snippet=f"{table_id} = pl.read_parquet({parquet_file.as_posix()!r})",
        value_preview={"rows": row_count, "cols": col_count, "columns": columns},
        unit="rows",
        uncertainty=UncertaintyProfile(
            extraction_confidence=1.0,
            data_completeness=overall_completeness,
            validation_pass_rate=1.0,
            epistemic_uncertainty_pct=round((1.0 - overall_completeness) * 10.0, 2),
            caveats=caveats,
            trust_grade=TrustGrade.A_VERIFIED if overall_completeness >= 0.95 else TrustGrade.B_HIGH,
        ),
        metadata={"parquet_path": parquet_file.as_posix(), "numeric_summary": numeric_summary},
    )
    graph.add_node(fragment_node)
    graph.add_edge(
        file_node_id,
        fragment_node.node_id,
        EdgeKind.EXTRACTED_FROM,
        rationale=f"Extracted sheet/table '{sheet_name or source_path.name}' ({cell_range}) via Polars/Rust.",
    )

    return TabularArtifact(
        table_id=table_id,
        source_path=str(source_path),
        sheet_name=sheet_name,
        parquet_path=parquet_file.as_posix(),
        row_count=row_count,
        col_count=col_count,
        columns=columns,
        dtypes=dtypes,
        null_ratios=null_ratios,
        overall_completeness=overall_completeness,
        cell_range=cell_range,
        numeric_summary=numeric_summary,
    )


def ingest_tabular_file(
    path: Path,
    output_dir: Path,
    graph: LineageGraphEngine,
) -> list[TabularArtifact]:
    """Ingest Excel (.xlsx/.xls), CSV, TSV, Parquet, or JSON files into Polars DataFrames with provenance."""
    suffix = path.suffix.lower()
    file_hash = _compute_file_sha256(path)
    stem_id = _sanitize_identifier(path.stem)
    file_node_id = f"file_{stem_id}_{file_hash[:8]}"

    mime_map = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".parquet": "application/vnd.apache.parquet",
        ".json": "application/json",
        ".ndjson": "application/x-ndjson",
    }
    mime_type = mime_map.get(suffix, "application/octet-stream")

    graph.add_node(
        GraphNode(
            node_id=file_node_id,
            kind=NodeKind.SOURCE_FILE,
            label=path.name,
            description=f"Raw tabular source file ({suffix})",
            coordinates=SourceCoordinates(
                file_path=str(path),
                file_hash_sha256=file_hash,
                mime_type=mime_type,
            ),
        )
    )

    artifacts: list[TabularArtifact] = []
    if suffix in (".xlsx", ".xls"):
        excel_reader = fastexcel.read_excel(path)
        for sheet_name in excel_reader.sheet_names:
            df = pl.read_excel(path, sheet_name=sheet_name, engine="calamine")
            sheet_id = _sanitize_identifier(f"{stem_id}_{sheet_name}") if len(excel_reader.sheet_names) > 1 else stem_id
            artifacts.append(
                _profile_and_persist_dataframe(
                    df,
                    table_id=sheet_id,
                    source_path=path,
                    file_hash=file_hash,
                    mime_type=mime_type,
                    output_dir=output_dir,
                    graph=graph,
                    file_node_id=file_node_id,
                    sheet_name=sheet_name,
                )
            )
    elif suffix == ".csv":
        df = pl.read_csv(path, try_parse_dates=True)
        artifacts.append(
            _profile_and_persist_dataframe(
                df,
                table_id=stem_id,
                source_path=path,
                file_hash=file_hash,
                mime_type=mime_type,
                output_dir=output_dir,
                graph=graph,
                file_node_id=file_node_id,
            )
        )
    elif suffix == ".tsv":
        df = pl.read_csv(path, separator="\t", try_parse_dates=True)
        artifacts.append(
            _profile_and_persist_dataframe(
                df,
                table_id=stem_id,
                source_path=path,
                file_hash=file_hash,
                mime_type=mime_type,
                output_dir=output_dir,
                graph=graph,
                file_node_id=file_node_id,
            )
        )
    elif suffix == ".parquet":
        df = pl.read_parquet(path)
        artifacts.append(
            _profile_and_persist_dataframe(
                df,
                table_id=stem_id,
                source_path=path,
                file_hash=file_hash,
                mime_type=mime_type,
                output_dir=output_dir,
                graph=graph,
                file_node_id=file_node_id,
            )
        )
    elif suffix == ".json":
        try:
            df = pl.read_json(path)
        except Exception:
            import json as _json

            parsed: Any = _json.loads(path.read_text(encoding="utf-8"))
            rows = parsed if isinstance(parsed, list) else [parsed]
            df = pl.DataFrame(rows)
        artifacts.append(
            _profile_and_persist_dataframe(
                df,
                table_id=stem_id,
                source_path=path,
                file_hash=file_hash,
                mime_type=mime_type,
                output_dir=output_dir,
                graph=graph,
                file_node_id=file_node_id,
            )
        )
    elif suffix == ".ndjson":
        df = pl.read_ndjson(path)
        artifacts.append(
            _profile_and_persist_dataframe(
                df,
                table_id=stem_id,
                source_path=path,
                file_hash=file_hash,
                mime_type=mime_type,
                output_dir=output_dir,
                graph=graph,
                file_node_id=file_node_id,
            )
        )

    return artifacts
