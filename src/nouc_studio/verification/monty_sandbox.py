"""Pydantic-Monty Rust Sandbox Runner for microsecond zero-ambient-access code and formula verification."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from pydantic_monty import Monty, MontyError, ResourceLimits


class MontyExecutionResult(BaseModel):
    """Result of executing a code snippet inside Pydantic's Rust-backed Monty sandbox."""

    code: str
    succeeded: bool
    return_value: Any = None
    stdout_lines: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    error_type: str | None = None
    error_message: str | None = None


class MontySandboxRunner:
    """Executes Python calculations and invariants inside Pydantic's Monty Rust sandbox.

    Guarantees zero ambient access to the host filesystem, environment variables, or network,
    with strict memory and duration bounds.
    """

    def __init__(
        self,
        max_duration_secs: float = 2.0,
        max_memory_bytes: int = 64 * 1024 * 1024,
        max_recursion_depth: int = 120,
        type_check: bool = False,
    ) -> None:
        self.max_duration_secs = max_duration_secs
        self.max_memory_bytes = max_memory_bytes
        self.max_recursion_depth = max_recursion_depth
        self.type_check = type_check

    def run_snippet(
        self,
        code: str,
        *,
        inputs: dict[str, Any] | None = None,
        external_lookup: dict[str, Callable[..., Any]] | None = None,
    ) -> MontyExecutionResult:
        """Run a pure Python snippet inside a fresh Monty worker session and return structured metrics."""
        stdout_captured: list[str] = []

        def _on_print(_stream: str, text: str) -> None:
            stdout_captured.append(text)

        limits: ResourceLimits = {
            "max_feed_duration_secs": self.max_duration_secs,
            "max_turn_duration_secs": self.max_duration_secs,
            "max_memory": self.max_memory_bytes,
            "max_recursion_depth": self.max_recursion_depth,
        }

        t0 = time.perf_counter()
        try:
            with Monty() as pool, pool.checkout(limits=limits, type_check=self.type_check) as session:
                val = session.feed_run(
                    code,
                    inputs=inputs or {},
                    external_lookup=external_lookup or {},
                    print_callback=_on_print,
                    skip_type_check=not self.type_check,
                )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return MontyExecutionResult(
                code=code,
                succeeded=True,
                return_value=val,
                stdout_lines=stdout_captured,
                duration_ms=elapsed_ms,
            )
        except MontyError as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return MontyExecutionResult(
                code=code,
                succeeded=False,
                stdout_lines=stdout_captured,
                duration_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return MontyExecutionResult(
                code=code,
                succeeded=False,
                stdout_lines=stdout_captured,
                duration_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
