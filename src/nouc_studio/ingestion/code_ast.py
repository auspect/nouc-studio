"""Codebase AST & Symbol Tree Extractor for Python, SQL, Rust, TypeScript, and config files."""

from __future__ import annotations

import ast
import re
from pathlib import Path

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
from nouc_studio.ingestion.tabular import _compute_file_sha256, _sanitize_identifier


class CodeSymbolRecord(BaseModel):
    """A parsed function, class, SQL query, or module symbol extracted from source code."""

    symbol_id: str
    file_path: str
    symbol_name: str
    symbol_kind: str
    line_start: int
    line_end: int
    signature: str
    docstring: str = ""
    calls: list[str] = Field(default_factory=list)
    complexity: int = 1


def _estimate_ast_complexity(node: ast.AST) -> int:
    """Estimate McCabe cyclomatic complexity of a Python AST subtree."""
    branch_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.ExceptHandler,
        ast.With,
        ast.AsyncWith,
        ast.BoolOp,
        ast.IfExp,
        ast.comprehension,
    )
    return 1 + sum(1 for child in ast.walk(node) if isinstance(child, branch_types))


def _extract_python_symbols(path: Path, source_text: str) -> list[CodeSymbolRecord]:
    """Parse Python source into an explicit AST symbol list with call edges and complexity."""
    records: list[CodeSymbolRecord] = []
    stem = _sanitize_identifier(path.stem)
    try:
        tree = ast.parse(source_text, filename=str(path))
    except SyntaxError:
        return records

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            line_start = getattr(node, "lineno", 1)
            line_end = getattr(node, "end_lineno", line_start)
            doc = ast.get_docstring(node) or ""
            calls: list[str] = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    if isinstance(sub.func, ast.Name):
                        calls.append(sub.func.id)
                    elif isinstance(sub.func, ast.Attribute):
                        calls.append(sub.func.attr)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                sig = f"def {node.name}({', '.join(args)})"
            else:
                sig = f"class {node.name}"

            records.append(
                CodeSymbolRecord(
                    symbol_id=f"ast_{stem}_{node.name}_{line_start}",
                    file_path=str(path),
                    symbol_name=node.name,
                    symbol_kind=kind,
                    line_start=line_start,
                    line_end=line_end,
                    signature=sig,
                    docstring=doc[:200],
                    calls=sorted(set(calls)),
                    complexity=_estimate_ast_complexity(node),
                )
            )
    return records


def _extract_generic_symbols(path: Path, source_text: str) -> list[CodeSymbolRecord]:
    """Extract structural symbols from Rust, TypeScript/JS, or SQL files."""
    records: list[CodeSymbolRecord] = []
    stem = _sanitize_identifier(path.stem)
    patterns = [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|function)\s+([a-zA-Z0-9_]+)")),
        ("class_or_struct", re.compile(r"^\s*(?:pub\s+)?(?:class|struct|interface|enum)\s+([a-zA-Z0-9_]+)")),
        ("sql_cte_or_view", re.compile(r"^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)|WITH)\s+([a-zA-Z0-9_.]+)", re.IGNORECASE)),
    ]
    for line_no, line in enumerate(source_text.splitlines(), start=1):
        for kind, pat in patterns:
            m = pat.search(line)
            if m:
                sym_name = m.group(1)
                records.append(
                    CodeSymbolRecord(
                        symbol_id=f"ast_{stem}_{_sanitize_identifier(sym_name)}_{line_no}",
                        file_path=str(path),
                        symbol_name=sym_name,
                        symbol_kind=kind,
                        line_start=line_no,
                        line_end=line_no,
                        signature=line.strip()[:120],
                    )
                )
    return records


def ingest_code_file(
    path: Path,
    graph: LineageGraphEngine,
) -> list[CodeSymbolRecord]:
    """Ingest a source code file into the LineageGraphEngine as explicit CODE_AST nodes."""
    file_hash = _compute_file_sha256(path)
    stem = _sanitize_identifier(path.stem)
    file_node_id = f"file_code_{stem}_{file_hash[:8]}"
    source_text = path.read_text(encoding="utf-8", errors="replace")
    total_lines = len(source_text.splitlines())

    graph.add_node(
        GraphNode(
            node_id=file_node_id,
            kind=NodeKind.SOURCE_FILE,
            label=path.name,
            description=f"Source code file ({path.suffix}, {total_lines} lines)",
            coordinates=SourceCoordinates(
                file_path=str(path),
                file_hash_sha256=file_hash,
                mime_type="text/x-python" if path.suffix == ".py" else "text/plain",
                line_start=1,
                line_end=max(1, total_lines),
            ),
        )
    )

    symbols = (
        _extract_python_symbols(path, source_text)
        if path.suffix.lower() == ".py"
        else _extract_generic_symbols(path, source_text)
    )

    for sym in symbols:
        graph.add_node(
            GraphNode(
                node_id=sym.symbol_id,
                kind=NodeKind.CODE_AST,
                label=f"{sym.symbol_kind}: {sym.symbol_name}",
                description=sym.docstring or f"Defined at {path.name}:{sym.line_start}-{sym.line_end} (complexity={sym.complexity})",
                coordinates=SourceCoordinates(
                    file_path=str(path),
                    file_hash_sha256=file_hash,
                    mime_type="text/x-code",
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    section_title=sym.symbol_name,
                ),
                code_snippet=sym.signature,
                value_preview={"complexity": sym.complexity, "calls": sym.calls},
                uncertainty=UncertaintyProfile(
                    extraction_confidence=1.0,
                    data_completeness=1.0,
                    validation_pass_rate=1.0,
                    trust_grade=TrustGrade.A_VERIFIED,
                ),
            )
        )
        graph.add_edge(
            file_node_id,
            sym.symbol_id,
            EdgeKind.DEFINED_IN,
            rationale=f"AST symbol '{sym.symbol_name}' parsed from {path.name}:{sym.line_start}-{sym.line_end}.",
        )

    return symbols


def persist_code_symbols_table(
    symbols: list[CodeSymbolRecord],
    output_dir: Path,
) -> str | None:
    """Persist all extracted code AST symbols as a Polars Parquet dataset for notebook analytics."""
    if not symbols:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "symbol_id": s.symbol_id,
            "file_path": s.file_path,
            "symbol_name": s.symbol_name,
            "symbol_kind": s.symbol_kind,
            "line_start": s.line_start,
            "line_end": s.line_end,
            "signature": s.signature,
            "docstring": s.docstring,
            "call_count": len(s.calls),
            "complexity": s.complexity,
        }
        for s in symbols
    ]
    df = pl.DataFrame(rows)
    pq_path = output_dir / "codebase_ast_symbols.parquet"
    df.write_parquet(pq_path)
    return pq_path.as_posix()
