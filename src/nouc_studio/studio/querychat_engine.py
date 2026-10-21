"""Posit QueryChat-inspired transparent Natural-Language-to-SQL / Polars exploration engine."""

from __future__ import annotations

import re
from typing import Any

import duckdb
import polars as pl
from pydantic import BaseModel, Field

FORBIDDEN_SQL_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|REPLACE|ATTACH|DETACH|COPY|INSTALL|LOAD|CALL|PRAGMA)\b",
    re.IGNORECASE,
)


class QueryChatResponse(BaseModel):
    """Transparent result of a QueryChat natural-language or SQL data exploration query."""

    question: str
    sql_query: str
    polars_equivalent: str
    explanation: str
    row_count: int
    columns: list[str]
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    succeeded: bool = True
    error_message: str | None = None


def validate_readonly_sql(sql: str) -> tuple[bool, str | None]:
    """Ensure a SQL query is strictly read-only (`SELECT` or `WITH ... SELECT`)."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        return False, "Empty SQL query."
    if FORBIDDEN_SQL_KEYWORDS.search(stripped):
        return False, "Query contains forbidden mutating or administrative SQL keywords."
    first_word = stripped.split()[0].upper()
    if first_word not in ("SELECT", "WITH", "SUMMARIZE", "DESCRIBE"):
        return False, f"Only read-only SELECT/WITH queries are allowed (got '{first_word}')."
    return True, None


class TransparentQueryChatEngine:
    """Translates natural language questions into transparent, auditable DuckDB SQL over Polars DataFrames."""

    def __init__(self, tables: dict[str, pl.DataFrame]) -> None:
        self.tables = tables

    def synthesize_sql_from_question(self, question: str, default_table: str | None = None) -> tuple[str, str, str]:
        """Deterministically synthesize a safe SQL query and Polars equivalent from a user question."""
        if not self.tables:
            return "SELECT 1 AS empty", "pl.DataFrame({'empty': [1]})", "No tables registered."

        q_lower = question.lower().strip()
        target_tbl = default_table if (default_table and default_table in self.tables) else next(iter(self.tables.keys()))
        for tbl_name in self.tables:
            if tbl_name.lower() in q_lower:
                target_tbl = tbl_name
                break

        df = self.tables[target_tbl]
        num_cols = [c for c, dt in zip(df.columns, df.dtypes, strict=False) if dt.is_numeric()]
        cat_cols = [c for c, dt in zip(df.columns, df.dtypes, strict=False) if not dt.is_numeric()]

        # If user typed a direct SELECT query, honor it after read-only validation
        if q_lower.startswith("select ") or q_lower.startswith("with "):
            return (
                question.strip(),
                f"duckdb.sql({question.strip()!r}).pl()",
                f"Direct read-only SQL execution against `{target_tbl}`.",
            )

        # Detect aggregation intent ("sum", "total", "average", "mean", "by", "group", "top")
        if any(kw in q_lower for kw in ("sum", "total", "average", "mean", "by ", "group", "par ", "moyenne", "somme")) and num_cols and cat_cols:
            group_col = cat_cols[0]
            for c in cat_cols:
                if c.lower() in q_lower:
                    group_col = c
                    break
            val_col = num_cols[0]
            for c in num_cols:
                if c.lower() in q_lower:
                    val_col = c
                    break
            sql = (
                f'SELECT "{group_col}", '
                f'COUNT(*) AS record_count, '
                f'ROUND(SUM("{val_col}"), 4) AS total_{val_col}, '
                f'ROUND(AVG("{val_col}"), 4) AS avg_{val_col} '
                f'FROM {target_tbl} '
                f'GROUP BY "{group_col}" '
                f'ORDER BY total_{val_col} DESC'
            )
            polars_eq = (
                f"{target_tbl}.group_by({group_col!r}).agg([\n"
                f"    pl.len().alias('record_count'),\n"
                f"    pl.col({val_col!r}).sum().round(4).alias('total_{val_col}'),\n"
                f"    pl.col({val_col!r}).mean().round(4).alias('avg_{val_col}'),\n"
                f"]).sort('total_{val_col}', descending=True)"
            )
            explanation = (
                f"Grouped `{target_tbl}` by `{group_col}` and computed count, sum, and mean of `{val_col}`."
            )
            return sql, polars_eq, explanation

        if any(kw in q_lower for kw in ("top", "highest", "max", "plus grand")) and num_cols:
            sort_col = num_cols[0]
            for c in num_cols:
                if c.lower() in q_lower:
                    sort_col = c
                    break
            sql = f'SELECT * FROM {target_tbl} ORDER BY "{sort_col}" DESC LIMIT 25'
            polars_eq = f"{target_tbl}.sort({sort_col!r}, descending=True).head(25)"
            explanation = f"Selected top 25 records from `{target_tbl}` ordered by `{sort_col}` descending."
            return sql, polars_eq, explanation

        sql = f"SELECT * FROM {target_tbl} LIMIT 50"
        polars_eq = f"{target_tbl}.head(50)"
        explanation = f"Returned first 50 rows of `{target_tbl}` for transparent inspection."
        return sql, polars_eq, explanation

    def execute_question(self, question: str, default_table: str | None = None) -> tuple[QueryChatResponse, pl.DataFrame]:
        """Translate question to SQL, verify read-only safety, execute via DuckDB, and return response + DataFrame."""
        sql, polars_eq, explanation = self.synthesize_sql_from_question(question, default_table=default_table)
        is_safe, err = validate_readonly_sql(sql)
        if not is_safe:
            empty = pl.DataFrame()
            return (
                QueryChatResponse(
                    question=question,
                    sql_query=sql,
                    polars_equivalent=polars_eq,
                    explanation="Blocked by read-only SQL safety gate.",
                    row_count=0,
                    columns=[],
                    succeeded=False,
                    error_message=err,
                ),
                empty,
            )

        try:
            try:
                with duckdb.connect(":memory:") as conn:
                    for tbl_name, tbl_df in self.tables.items():
                        conn.register(tbl_name, tbl_df)
                    res_df = conn.execute(sql).pl()
            except Exception:
                ctx = pl.SQLContext(self.tables)
                res_df = ctx.execute(sql, eager=True)

            referenced = [t for t in self.tables if re.search(rf"\b{re.escape(t)}\b", sql, re.IGNORECASE)]
            return (
                QueryChatResponse(
                    question=question,
                    sql_query=sql,
                    polars_equivalent=polars_eq,
                    explanation=explanation,
                    row_count=res_df.height,
                    columns=list(res_df.columns),
                    preview_rows=res_df.head(20).to_dicts(),
                    referenced_tables=referenced,
                    succeeded=True,
                ),
                res_df,
            )
        except Exception as exc:
            empty = pl.DataFrame()
            return (
                QueryChatResponse(
                    question=question,
                    sql_query=sql,
                    polars_equivalent=polars_eq,
                    explanation="SQL execution failed.",
                    row_count=0,
                    columns=[],
                    succeeded=False,
                    error_message=str(exc),
                ),
                empty,
            )
