"""Unit tests for Multimodal Ingestion across Excel (.xlsx), Markdown, DOCX, PPTX, Images, and Code AST."""

from pathlib import Path

import docx
import polars as pl
import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from nouc_studio.graph import LineageGraphEngine, NodeKind
from nouc_studio.graph.models import GraphNode
from nouc_studio.ingestion import MultimodalIngestor
from nouc_studio.ingestion.tabular import _profile_and_persist_dataframe


def test_multimodal_ingestion_all_formats(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    out_data_dir = tmp_path / "data"
    input_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create a real Excel (.xlsx) file using Polars / xlsxwriter
    excel_path = input_dir / "financials.xlsx"
    df_excel = pl.DataFrame(
        {
            "quarter": ["Q1", "Q2", "Q3", "Q4"],
            "revenue": [120000.0, 135000.0, 142000.0, 168000.0],
            "operating_cost": [80000.0, 82000.0, 85000.0, 91000.0],
        }
    )
    df_excel.write_excel(excel_path, worksheet="RegionalRevenue")

    # 2. Create a Markdown file with a section hierarchy and an embedded GFM table
    md_path = input_dir / "architecture_notes.md"
    md_path.write_text(
        "# System Overview\nOur service latency targets are strict.\n\n"
        "| service | p95_ms | error_rate |\n"
        "| --- | --- | --- |\n"
        "| auth | 12.4 | 0.01 |\n"
        "| billing | 28.9 | 0.03 |\n",
        encoding="utf-8",
    )

    # 3. Create a DOCX document with heading, paragraph, and table
    docx_path = input_dir / "audit_memo.docx"
    doc = docx.Document()
    doc.add_heading("Q4 Audit Findings", level=1)
    doc.add_paragraph("All revenue recognition rules were verified against ledger entries.")
    tbl = doc.add_table(rows=2, cols=2)
    tbl.rows[0].cells[0].text = "control_id"
    tbl.rows[0].cells[1].text = "score"
    tbl.rows[1].cells[0].text = "SOX-101"
    tbl.rows[1].cells[1].text = "98.5"
    doc.save(str(docx_path))

    # 4. Create a PPTX presentation with slide text and table
    pptx_path = input_dir / "board_deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "2026 Strategic Targets"
    shape_tbl = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1.5)).table
    shape_tbl.cell(0, 0).text = "kpi"
    shape_tbl.cell(0, 1).text = "target"
    shape_tbl.cell(1, 0).text = "NRR"
    shape_tbl.cell(1, 1).text = "118"
    prs.save(str(pptx_path))

    # 5. Create a PNG image
    img_path = input_dir / "diagram.png"
    img = Image.new("RGB", (120, 80), color=(30, 64, 175))
    img.save(img_path)

    # 6. Create a Python source code file
    py_path = input_dir / "pricing_engine.py"
    py_path.write_text(
        'def compute_margin(revenue: float, cost: float) -> float:\n'
        '    """Compute gross margin ratio."""\n'
        '    if revenue <= 0:\n'
        '        return 0.0\n'
        '    return (revenue - cost) / revenue\n',
        encoding="utf-8",
    )

    graph = LineageGraphEngine()
    ingestor = MultimodalIngestor(output_data_dir=out_data_dir, graph=graph)
    manifest = ingestor.ingest_paths([input_dir])

    assert len(manifest.ingested_files) == 6
    # Excel table + Markdown table + DOCX table + PPTX table + AST symbols table = 5 tabular artifacts
    assert len(manifest.tabular_artifacts) >= 5
    assert len(manifest.document_artifacts) == 4
    assert any(s.symbol_name == "compute_margin" for s in manifest.code_symbols)
    assert graph.is_acyclic()
    assert len(graph.nodes_by_kind(NodeKind.SOURCE_FILE)) == 6
    assert len(graph.nodes_by_kind(NodeKind.CODE_AST)) >= 1


@pytest.mark.parametrize("frame_kind", ["mixed", "empty", "no_columns", "strings"])
def test_vectorized_profile_matches_scalar_statistics(tmp_path: Path, frame_kind: str) -> None:
    frame = pl.DataFrame({
        "ints": [1, None, -3, 7],
        "floats": [1.123456, 2.987654, None, -0.000001],
        "all_null": pl.Series([None] * 4, dtype=pl.Float64),
        "single": [None, 2.0, None, None],
        "strings": ["a", None, "c", "d"],
        "bools": [True, False, None, True],
    })
    if frame_kind == "empty":
        frame = frame.clear()
    elif frame_kind == "no_columns":
        frame = pl.DataFrame()
    elif frame_kind == "strings":
        frame = frame.select("strings", "bools")

    # Reference the previous scalar path to preserve rounding, null handling,
    # float casting and sample standard deviation exactly.
    expected_nulls = {
        col: round(frame[col].null_count() / frame.height, 4) if frame.height else 0.0
        for col in frame.columns
    }
    expected_numeric: dict[str, dict[str, float]] = {}
    for col, dtype in frame.schema.items():
        if dtype.is_numeric() and frame.height > 0:
            series = frame[col].drop_nulls().cast(pl.Float64)
            if series.len() > 0:
                values = {
                    "sum": series.sum(), "mean": series.mean(), "std": series.std(),
                    "min": series.min(), "max": series.max(),
                }
                expected_numeric[col] = {
                    key: round(float(value), 4) if isinstance(value, (int, float)) else 0.0
                    for key, value in values.items()
                }

    graph = LineageGraphEngine()
    graph.add_node(GraphNode(node_id="file_test", kind=NodeKind.SOURCE_FILE, label="test"))
    artifact = _profile_and_persist_dataframe(
        frame, table_id="test", source_path=tmp_path / "source.csv", file_hash="a" * 64,
        mime_type="text/csv", output_dir=tmp_path / "data", graph=graph,
        file_node_id="file_test",
    )
    assert artifact.null_ratios == expected_nulls
    assert artifact.numeric_summary == expected_numeric
    assert artifact.overall_completeness == (
        round(1.0 - sum(expected_nulls.values()) / len(expected_nulls), 4)
        if expected_nulls else 1.0
    )
    assert all(
        type(value) is float
        for stats in artifact.numeric_summary.values() for value in stats.values()
    )
