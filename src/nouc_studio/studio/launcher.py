"""Build Studio views before serving them in the current Python environment."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from marimo_studio.authoring import open_workspace
from marimo_studio.errors import MarimoStudioError


class StudioLaunchError(RuntimeError):
    """A preparation stage failed; the server must not start."""


def _failure_detail(error: MarimoStudioError | OSError) -> str:
    if isinstance(error, MarimoStudioError):
        return f"[{error.code}] {error} {error.public_hint}".strip()
    return str(error)


async def prepare_studio(
    notebook: Path,
    *,
    edit: bool = False,
    check_runtime: bool = False,
    runtime_timeout: float = 60.0,
    emit: Callable[[str], None] = print,
) -> None:
    """Build all views and validate projections; execute Python only when requested."""
    if not notebook.is_file() or notebook.suffix != ".py":
        raise StudioLaunchError(
            f"Notebook not found or not a .py file: {notebook}. "
            "Pass the generated app.py path; build the app first."
        )
    workspace = open_workspace(notebook)
    try:
        status = await workspace.status()
    except (MarimoStudioError, OSError) as exc:
        raise StudioLaunchError(f"Studio discovery failed: {_failure_detail(exc)}") from exc
    if not status.views:
        raise StudioLaunchError(
            f"No Studio views found (state={status.state}) in {status.view_root}. "
            "Restore the view sources alongside the notebook or create a view first. "
            "Check the installed Studio version before moving folders."
        )
    profile: Literal["development", "production"] = "development" if edit else "production"
    emit(f"Studio: {len(status.views)} views; profile={profile}; sources={status.view_root}")
    for overview in status.views:
        view = workspace.view(overview.name)
        emit(f"Build {overview.name} ({profile})")
        try:
            build = await view.build(profile=profile)
        except (MarimoStudioError, OSError) as exc:
            raise StudioLaunchError(
                f"View build failed [{overview.name}, {profile}]: {_failure_detail(exc)}\n"
                "Fix the view source and retry. A previously successful preview may "
                "still be visible; it does not prove this build passed."
            ) from exc
        if build.issues:
            for issue in build.issues:
                emit(f"Build diagnostic [{overview.name}]: {issue}")
        level: Literal["static", "runtime"] = "runtime" if check_runtime else "static"
        emit(f"Validate {overview.name} ({level})")
        try:
            report = await view.validate(level=level, runtime_timeout=runtime_timeout)
        except (MarimoStudioError, OSError) as exc:
            raise StudioLaunchError(
                f"{level.capitalize()} validation failed [{overview.name}]: {_failure_detail(exc)}"
            ) from exc
        for issue in report.issues:
            emit(
                f"{issue.severity} [{overview.name}/{issue.stage}/{issue.code}] "
                f"{issue.message} {issue.advice}"
                + (f" Source: {issue.source}" if issue.source else "")
            )
        if not report.ok:
            raise StudioLaunchError(
                f"{level.capitalize()} validation failed [{overview.name}]. "
                "Fix the reported projection or Python error and retry."
            )


def studio_server_command(
    notebook: Path, *, edit: bool = False, headless: bool = False, port: int | None = None,
) -> list[str]:
    """Keep paths as argv values and reuse the environment that built the views."""
    command = [
        sys.executable, "-m", "marimo", "edit" if edit else "run",
        str(notebook), "--no-sandbox",
    ]
    if edit:
        command.append("--watch")
    if headless:
        command.append("--headless")
    if port is not None:
        command.extend(["--port", str(port)])
    return command
