"""Unified Multimodal Ingestion Dispatcher (Excel, CSV, Parquet, PDF, DOCX, PPTX, MD, TXT, Images, Code)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.ingestion.code_ast import (
    CodeSymbolRecord,
    ingest_code_file,
    persist_code_symbols_table,
)
from nouc_studio.ingestion.documents import (
    DocumentArtifact,
    ingest_document_or_image,
)
from nouc_studio.ingestion.tabular import (
    TabularArtifact,
    _compute_file_sha256,
    _profile_and_persist_dataframe,
    ingest_tabular_file,
)

TABULAR_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv", ".parquet", ".json", ".ndjson"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".svg"}
CODE_EXTENSIONS = {".py", ".rs", ".sql", ".ts", ".tsx", ".js", ".toml", ".yaml", ".yml"}
IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".insights", ".ruff_cache", ".pytest_cache"}


class IngestionManifest(BaseModel):
    """Complete manifest of all ingested multimodal artifacts and normalized Parquet tables."""

    tabular_artifacts: list[TabularArtifact] = Field(default_factory=list)
    document_artifacts: list[DocumentArtifact] = Field(default_factory=list)
    code_symbols: list[CodeSymbolRecord] = Field(default_factory=list)
    code_symbols_parquet: str | None = None
    ingested_files: list[str] = Field(default_factory=list)


class MultimodalIngestor:
    """Dispatches heterogeneous files into Polars Parquet datasets and Provenance/AST GraphNodes."""

    def __init__(self, output_data_dir: Path, graph: LineageGraphEngine) -> None:
        self.output_data_dir = output_data_dir
        self.graph = graph

    def ingest_paths(self, inputs: list[Path]) -> IngestionManifest:
        """Recursively ingest files and directories into normalized Parquet tables and graph nodes."""
        manifest = IngestionManifest()
        resolved_files: list[Path] = []

        for item in inputs:
            if not item.exists():
                continue
            if item.is_file():
                resolved_files.append(item)
            elif item.is_dir():
                for child in sorted(item.rglob("*")):
                    if child.is_file() and not any(part in IGNORED_DIRS for part in child.parts):
                        resolved_files.append(child)

        for file_path in resolved_files:
            suffix = file_path.suffix.lower()
            if suffix in TABULAR_EXTENSIONS:
                tabs = ingest_tabular_file(file_path, self.output_data_dir, self.graph)
                manifest.tabular_artifacts.extend(tabs)
                manifest.ingested_files.append(str(file_path))
            elif suffix in DOCUMENT_EXTENSIONS:
                doc_art = ingest_document_or_image(file_path, self.output_data_dir, self.graph)
                manifest.document_artifacts.append(doc_art)
                manifest.tabular_artifacts.extend(doc_art.extracted_tables)
                manifest.ingested_files.append(str(file_path))
            elif suffix in CODE_EXTENSIONS:
                syms = ingest_code_file(file_path, self.graph)
                manifest.code_symbols.extend(syms)
                manifest.ingested_files.append(str(file_path))

        if manifest.code_symbols:
            pq_path = persist_code_symbols_table(manifest.code_symbols, self.output_data_dir)
            manifest.code_symbols_parquet = pq_path
            if pq_path is not None:
                import polars as pl

                df = pl.read_parquet(pq_path)
                p = Path(pq_path)
                manifest.tabular_artifacts.append(
                    _profile_and_persist_dataframe(
                        df,
                        table_id="codebase_ast_symbols",
                        source_path=p,
                        file_hash=_compute_file_sha256(p),
                        mime_type="application/vnd.apache.parquet",
                        output_dir=self.output_data_dir,
                        graph=self.graph,
                        file_node_id=self.graph.topological_nodes()[0].node_id,
                    )
                )

        return manifest
