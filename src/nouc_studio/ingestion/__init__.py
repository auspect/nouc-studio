"""Multimodal file ingestion (Excel, CSV, Parquet, PDF, DOCX, PPTX, Markdown, TXT, Images, Code)."""

from nouc_studio.ingestion.code_ast import CodeSymbolRecord, ingest_code_file
from nouc_studio.ingestion.documents import (
    DocumentArtifact,
    DocumentChunk,
    ingest_document_or_image,
)
from nouc_studio.ingestion.pipeline import IngestionManifest, MultimodalIngestor
from nouc_studio.ingestion.tabular import TabularArtifact, ingest_tabular_file

__all__ = [
    "CodeSymbolRecord",
    "DocumentArtifact",
    "DocumentChunk",
    "IngestionManifest",
    "MultimodalIngestor",
    "TabularArtifact",
    "ingest_code_file",
    "ingest_document_or_image",
    "ingest_tabular_file",
]
