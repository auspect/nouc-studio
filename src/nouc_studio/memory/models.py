"""Data models for the Dual-Tier (Local + Global Cross-Project) Adaptive Failure/Fix Memory."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FailureStage(StrEnum):
    """Pipeline stage where a failure occurred."""

    INGESTION = "ingestion"
    RUFF_LINT = "ruff_lint"
    TY_TYPECHECK = "ty_typecheck"
    MONTY_SANDBOX = "monty_sandbox"
    MARIMO_DAG = "marimo_dag"
    POINTBLANK_QA = "pointblank_qa"
    STUDIO_BUILD = "studio_build"
    DEEPEVAL_AUDIT = "deepeval_audit"
    RUNTIME_EXECUTION = "runtime_execution"
    VISUAL_INSPECTION = "visual_inspection"


def normalize_error_signature(error_type: str, error_message: str) -> str:
    """Normalize an error message by stripping volatile paths, line numbers, and hex addresses."""
    cleaned = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", error_message)
    cleaned = re.sub(r"line \d+", "line N", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r":[0-9]+:[0-9]+", ":L:C", cleaned)
    cleaned = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "<PATH>", cleaned)
    cleaned = re.sub(r"/[^\s'\"]+/[^\s'\"]+", "<PATH>", cleaned)
    return f"{error_type.strip()}::{cleaned.strip()}"


def compute_episode_id(stage: str, library: str, normalized_signature: str) -> str:
    """Compute a deterministic SHA-256 based episode ID for deduplication across projects."""
    raw = f"{stage}|{library.lower().strip()}|{normalized_signature}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ep_{digest}"


class FailureEpisode(BaseModel):
    """A recorded failure and its verified resolution for adaptive self-healing memory."""

    episode_id: str = Field(description="Deterministic hash ID of (stage, library, signature).")
    project_name: str = Field(default="default", description="Project where the failure occurred.")
    stage: FailureStage = Field(description="Verification or execution stage that caught the failure.")
    library: str = Field(description="Primary library or tool involved (e.g., marimo, polars, marimo-studio, ty).")
    error_type: str = Field(description="Exception class or diagnostic code.")
    error_message: str = Field(description="Raw error output or diagnostic message.")
    normalized_signature: str = Field(description="Path/line-agnostic error signature.")
    failing_code_snippet: str = Field(default="", description="Code or configuration that triggered the failure.")
    root_cause: str = Field(description="Diagnosed root cause of the failure.")
    verified_fix_description: str = Field(description="Actionable description of the fix that resolved the issue.")
    fixed_code_snippet: str = Field(default="", description="Corrected code snippet that passed verification.")
    prevention_rule: str = Field(
        description="Concise rule injected into agent prompts to prevent repeating this error."
    )
    verified: bool = Field(
        default=True,
        description="Whether the fix was empirically verified by passing the verification gate.",
    )
    hit_count: int = Field(default=1, ge=1, description="Number of times this error pattern was encountered.")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_seen_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
