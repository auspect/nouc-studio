"""Document and image ingestion (PDF, DOCX, PPTX, Markdown, TXT, Images) with page/slide/line provenance."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
from PIL import Image
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
from nouc_studio.ingestion.tabular import (
    TabularArtifact,
    _compute_file_sha256,
    _profile_and_persist_dataframe,
    _sanitize_identifier,
)


class DocumentChunk(BaseModel):
    """A provenance-tracked chunk of text or visual metadata from a document."""

    chunk_id: str
    source_path: str
    page_or_slide: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_title: str = ""
    text: str
    extraction_confidence: float = 0.95


class DocumentArtifact(BaseModel):
    """Ingested representation of a PDF, Office document, Markdown/TXT, or Image file."""

    doc_id: str
    source_path: str
    mime_type: str
    chunks: list[DocumentChunk] = Field(default_factory=list)
    extracted_tables: list[TabularArtifact] = Field(default_factory=list)
    summary_parquet_path: str | None = None


def _extract_markdown_tables(
    md_text: str,
    *,
    base_id: str,
    source_path: Path,
    file_hash: str,
    output_dir: Path,
    graph: LineageGraphEngine,
    file_node_id: str,
) -> list[TabularArtifact]:
    """Detect GitHub-flavored Markdown tables and convert them into provenance-tracked Polars DataFrames."""
    lines = md_text.splitlines()
    tables: list[TabularArtifact] = []
    i = 0
    table_idx = 1
    while i < len(lines) - 1:
        line = lines[i].strip()
        next_line = lines[i + 1].strip()
        if line.startswith("|") and line.endswith("|") and re.match(r"^\|[\s:\-\|]+\|$", next_line):
            headers = [h.strip() for h in line.strip("|").split("|")]
            i += 2
            rows: list[dict[str, str | float | int | None]] = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                row_dict: dict[str, str | float | int | None] = {}
                for col_idx, col_name in enumerate(headers):
                    raw_val = cells[col_idx] if col_idx < len(cells) else ""
                    cleaned_num = raw_val.replace(",", "").replace("$", "").replace("€", "").replace("%", "").strip()
                    val: str | float | int | None = raw_val
                    if cleaned_num == "":
                        val = None
                    else:
                        try:
                            val = int(cleaned_num) if "." not in cleaned_num else float(cleaned_num)
                        except ValueError:
                            val = raw_val
                    row_dict[col_name or f"col_{col_idx}"] = val
                rows.append(row_dict)
                i += 1
            if rows:
                df = pl.DataFrame(rows)
                tbl_id = _sanitize_identifier(f"{base_id}_md_table_{table_idx}")
                tables.append(
                    _profile_and_persist_dataframe(
                        df,
                        table_id=tbl_id,
                        source_path=source_path,
                        file_hash=file_hash,
                        mime_type="text/markdown",
                        output_dir=output_dir,
                        graph=graph,
                        file_node_id=file_node_id,
                        sheet_name=f"md_table_{table_idx}",
                    )
                )
                table_idx += 1
        else:
            i += 1
    return tables


def ingest_document_or_image(
    path: Path,
    output_dir: Path,
    graph: LineageGraphEngine,
) -> DocumentArtifact:
    """Ingest PDF, DOCX, PPTX, Markdown, TXT, or Image files with exact page/slide/line provenance."""
    suffix = path.suffix.lower()
    file_hash = _compute_file_sha256(path)
    doc_id = _sanitize_identifier(path.stem)
    file_node_id = f"file_{doc_id}_{file_hash[:8]}"

    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    mime_type = mime_map.get(suffix, "application/octet-stream")

    graph.add_node(
        GraphNode(
            node_id=file_node_id,
            kind=NodeKind.SOURCE_FILE,
            label=path.name,
            description=f"Document/media source ({suffix})",
            coordinates=SourceCoordinates(
                file_path=str(path),
                file_hash_sha256=file_hash,
                mime_type=mime_type,
            ),
        )
    )

    chunks: list[DocumentChunk] = []
    extracted_tables: list[TabularArtifact] = []

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        for page_idx, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc_id}_p{page_idx}",
                        source_path=str(path),
                        page_or_slide=page_idx,
                        section_title=f"Page {page_idx}",
                        text=text,
                        extraction_confidence=0.92,
                    )
                )
    elif suffix == ".docx":
        import docx

        doc = docx.Document(str(path))
        current_heading = "Document Body"
        para_buffer: list[str] = []
        section_idx = 1
        for para in doc.paragraphs:
            txt = para.text.strip()
            if not txt:
                continue
            if para.style and para.style.name and para.style.name.startswith("Heading"):
                if para_buffer:
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{doc_id}_sec{section_idx}",
                            source_path=str(path),
                            section_title=current_heading,
                            text="\n".join(para_buffer),
                            extraction_confidence=0.98,
                        )
                    )
                    section_idx += 1
                    para_buffer = []
                current_heading = txt
            else:
                para_buffer.append(txt)
        if para_buffer:
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc_id}_sec{section_idx}",
                    source_path=str(path),
                    section_title=current_heading,
                    text="\n".join(para_buffer),
                    extraction_confidence=0.98,
                )
            )
        for tbl_idx, table in enumerate(doc.tables, start=1):
            raw_rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if len(raw_rows) >= 2:
                headers = [h or f"col_{idx}" for idx, h in enumerate(raw_rows[0])]
                records = [dict(zip(headers, r, strict=False)) for r in raw_rows[1:]]
                df = pl.DataFrame(records)
                extracted_tables.append(
                    _profile_and_persist_dataframe(
                        df,
                        table_id=_sanitize_identifier(f"{doc_id}_docx_tbl_{tbl_idx}"),
                        source_path=path,
                        file_hash=file_hash,
                        mime_type=mime_type,
                        output_dir=output_dir,
                        graph=graph,
                        file_node_id=file_node_id,
                        sheet_name=f"docx_table_{tbl_idx}",
                    )
                )
    elif suffix == ".pptx":
        from pptx import Presentation

        prs = Presentation(str(path))
        for slide_idx, slide in enumerate(prs.slides, start=1):
            slide_texts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    txt = shape.text_frame.text.strip()
                    if txt:
                        slide_texts.append(txt)
                if shape.has_table:
                    tbl = shape.table
                    raw_rows = [[c.text.strip() for c in r.cells] for r in tbl.rows]
                    if len(raw_rows) >= 2:
                        headers = [h or f"col_{idx}" for idx, h in enumerate(raw_rows[0])]
                        records = [dict(zip(headers, r, strict=False)) for r in raw_rows[1:]]
                        df = pl.DataFrame(records)
                        extracted_tables.append(
                            _profile_and_persist_dataframe(
                                df,
                                table_id=_sanitize_identifier(f"{doc_id}_slide_{slide_idx}_tbl"),
                                source_path=path,
                                file_hash=file_hash,
                                mime_type=mime_type,
                                output_dir=output_dir,
                                graph=graph,
                                file_node_id=file_node_id,
                                sheet_name=f"slide_{slide_idx}",
                            )
                        )
            if slide_texts:
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc_id}_slide{slide_idx}",
                        source_path=str(path),
                        page_or_slide=slide_idx,
                        section_title=slide_texts[0][:80],
                        text="\n".join(slide_texts),
                        extraction_confidence=0.97,
                    )
                )
    elif suffix in (".md", ".txt"):
        content = path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".md":
            extracted_tables.extend(
                _extract_markdown_tables(
                    content,
                    base_id=doc_id,
                    source_path=path,
                    file_hash=file_hash,
                    output_dir=output_dir,
                    graph=graph,
                    file_node_id=file_node_id,
                )
            )
        lines = content.splitlines()
        current_title = path.name
        start_line = 1
        buf: list[str] = []
        sec_idx = 1
        for line_no, line in enumerate(lines, start=1):
            if line.startswith("#"):
                if buf:
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{doc_id}_s{sec_idx}",
                            source_path=str(path),
                            line_start=start_line,
                            line_end=line_no - 1,
                            section_title=current_title,
                            text="\n".join(buf).strip(),
                            extraction_confidence=1.0,
                        )
                    )
                    sec_idx += 1
                    buf = []
                current_title = line.lstrip("#").strip()
                start_line = line_no
            else:
                buf.append(line)
        if buf and "\n".join(buf).strip():
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc_id}_s{sec_idx}",
                    source_path=str(path),
                    line_start=start_line,
                    line_end=len(lines),
                    section_title=current_title,
                    text="\n".join(buf).strip(),
                    extraction_confidence=1.0,
                )
            )
    elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
        with Image.open(path) as img:
            width, height = img.size
            mode = img.mode
            fmt = img.format or suffix.lstrip(".").upper()
        chunks.append(
            DocumentChunk(
                chunk_id=f"{doc_id}_img",
                source_path=str(path),
                section_title=f"Image {path.name} ({width}x{height} {mode})",
                text=f"Image asset '{path.name}': format={fmt}, dimensions={width}x{height}, color_mode={mode}.",
                extraction_confidence=0.90,
            )
        )

    # Persist document chunks as a Polars Parquet table so Marimo cells can query/search document evidence directly!
    summary_parquet: str | None = None
    if chunks:
        output_dir.mkdir(parents=True, exist_ok=True)
        chunks_df = pl.DataFrame([c.model_dump() for c in chunks])
        pq_path = output_dir / f"doc_{doc_id}_chunks.parquet"
        chunks_df.write_parquet(pq_path)
        summary_parquet = pq_path.as_posix()

        for c in chunks[:20]:  # Register up to 20 granular chunk nodes in the lineage graph
            node_id = f"src_doc_{c.chunk_id}"
            graph.add_node(
                GraphNode(
                    node_id=node_id,
                    kind=NodeKind.SOURCE_FRAGMENT,
                    label=f"{path.name} — {c.section_title[:40]}",
                    description=c.text[:240],
                    coordinates=SourceCoordinates(
                        file_path=str(path),
                        file_hash_sha256=file_hash,
                        mime_type=mime_type,
                        page_number=c.page_or_slide,
                        line_start=c.line_start,
                        line_end=c.line_end,
                        section_title=c.section_title,
                    ),
                    uncertainty=UncertaintyProfile(
                        extraction_confidence=c.extraction_confidence,
                        data_completeness=1.0,
                        validation_pass_rate=1.0,
                        epistemic_uncertainty_pct=round((1.0 - c.extraction_confidence) * 20.0, 2),
                        trust_grade=TrustGrade.A_VERIFIED if c.extraction_confidence >= 0.95 else TrustGrade.B_HIGH,
                    ),
                )
            )
            graph.add_edge(
                file_node_id,
                node_id,
                EdgeKind.EXTRACTED_FROM,
                rationale=f"Extracted section '{c.section_title}' from {path.name}.",
            )

    return DocumentArtifact(
        doc_id=doc_id,
        source_path=str(path),
        mime_type=mime_type,
        chunks=chunks,
        extracted_tables=extracted_tables,
        summary_parquet_path=summary_parquet,
    )
