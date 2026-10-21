"""Explicit, conservative project setup using resources shipped in the distribution.

Importing Nouc Studio never installs instructions. Only ``nouc init`` writes them.
The manifest lets later versions update untouched managed files while preserving
the user's edits. Paths are checked without resolving away links or junctions.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata, resources
from pathlib import Path
from uuid import uuid4

SKILL_NAMES = (
    "marimo-pair-sandbox",
    "deepwiki-live-grounding",
    "adaptive-failure-memory",
    "epistemic-lineage-studio",
    "studio-experience-design",
)
COPILOT_FILES = (
    "AGENTS.md",
    ".github/copilot-instructions.md",
    ".github/agents/nouc-studio.agent.md",
    *(f"skills/{name}/SKILL.md" for name in SKILL_NAMES),
)
MANIFEST_PATH = ".nouc-studio/bootstrap.json"
BACKUP_DIRECTORY = ".nouc-studio/bootstrap-backups"


class BootstrapError(Exception):
    """A setup problem that can be presented without a traceback or file contents."""


@dataclass(frozen=True)
class BootstrapFile:
    path: str
    action: str


@dataclass(frozen=True)
class BootstrapResult:
    project_dir: Path
    files: tuple[BootstrapFile, ...]
    dry_run: bool
    backup_dir: Path | None = None


def load_copilot_resources() -> dict[str, bytes]:
    """Read the explicit allowlist from an installed wheel, never the current repo."""
    bundle = resources.files("nouc_studio").joinpath("_bootstrap")
    try:
        return {name: bundle.joinpath(*name.split("/")).read_bytes() for name in COPILOT_FILES}
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise BootstrapError(
            "The installed distribution is missing its Copilot resources. "
            "Install a built nouc-studio wheel, rather than an editable source checkout."
        ) from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked_path(path: Path, *, directory: bool = False) -> None:
    """Reject symlinks and all Windows reparse points, including parent junctions."""
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise BootstrapError(f"Refusing a symbolic link or Windows reparse point: {component}")
        if component != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise BootstrapError(f"Expected a directory: {component}")
        elif not stat.S_ISREG(info.st_mode):
            raise BootstrapError(f"Expected a regular file: {component}")
        elif info.st_nlink > 1:
            raise BootstrapError(f"Refusing a hard-linked destination: {component}")


def _read_existing(path: Path) -> bytes | None:
    _checked_path(path)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _read_manifest(data: bytes | None) -> dict[str, str]:
    if data is None:
        return {}
    try:
        value = json.loads(data)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("agent") != "copilot"
            or not isinstance(value.get("files"), dict)
        ):
            raise ValueError("invalid manifest structure")
        hashes = value["files"]
        if any(
            name not in COPILOT_FILES
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            for name, digest in hashes.items()
        ):
            raise ValueError("invalid managed files")
        return hashes
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise BootstrapError(
            f"Invalid {MANIFEST_PATH}; preserve it and inspect it before running init again."
        ) from exc


def _write_checked(path: Path, data: bytes, expected: bytes | None) -> None:
    """Replace a checked regular file atomically; never clobber a newly created file."""
    _checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _checked_path(path.parent, directory=True)
    if _read_existing(path) != expected:
        raise BootstrapError(f"Destination changed during setup; rerun init: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".nouc-init-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        _checked_path(path)
        if expected is None:
            # link is atomic and fails when a destination appeared since preflight.
            os.link(temporary, path)
        else:
            if _read_existing(path) != expected:
                raise BootstrapError(f"Destination changed during setup; rerun init: {path}")
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_project(
    project_dir: Path,
    *,
    agent: str = "copilot",
    dry_run: bool = False,
    overwrite: bool = False,
) -> BootstrapResult:
    """Install agent instructions, preserving edits and reporting every planned file.

    All conflicts and unsafe destinations are checked before writes. An I/O error
    can leave a partial installation; rerunning init safely completes it. This is
    not a security boundary against a process concurrently replacing directories.
    """
    if agent != "copilot":
        raise BootstrapError("Only --agent copilot is currently supported.")
    root = Path(os.path.abspath(project_dir))
    _checked_path(root, directory=True)
    assets = load_copilot_resources()
    if set(assets) != set(COPILOT_FILES):
        raise BootstrapError("The installed Copilot resource allowlist is incomplete.")
    manifest_file = root / MANIFEST_PATH
    original_manifest = _read_existing(manifest_file)
    previous = _read_manifest(original_manifest)
    existing = {name: _read_existing(root / name) for name in COPILOT_FILES}
    actions: list[BootstrapFile] = []
    conflicts: list[str] = []
    for name, content in assets.items():
        current = existing[name]
        if current == content:
            action = "unchanged"
        elif current is None:
            action = "create"
        elif previous.get(name) == _digest(current):
            action = "update"
        else:
            action = "overwrite" if overwrite else "conflict"
            conflicts.append(name)
        actions.append(BootstrapFile(name, action))
    if conflicts and not overwrite:
        raise BootstrapError(
            "Existing user files differ; no files were written: "
            + ", ".join(conflicts)
            + ". Review them, or rerun with --overwrite to keep backups and replace them."
        )
    manifest = (
        json.dumps(
            {
                "schema_version": 1,
                "agent": agent,
                "package_version": metadata.version("nouc-studio"),
                "files": {name: _digest(data) for name, data in assets.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    actions.append(
        BootstrapFile(
            MANIFEST_PATH,
            "unchanged" if original_manifest == manifest else "update" if original_manifest else "create",
        )
    )
    # Preflight backup paths too, even during dry-run; never create them to inspect.
    replacements = [name for name in assets if existing[name] not in (None, assets[name])]
    backup_dir = None
    if replacements:
        backup_root = root / BACKUP_DIRECTORY
        _checked_path(backup_root, directory=True)
        backup_ignore = _read_existing(backup_root / ".gitignore")
        if backup_ignore not in (None, b"*\n"):
            raise BootstrapError(
                f"Existing backup ignore rules differ: {backup_root / '.gitignore'}. "
                "Inspect them before setup; backups must remain excluded from Git."
            )
        backup_dir = backup_root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    if dry_run:
        return BootstrapResult(root, tuple(actions), True, backup_dir)
    if backup_dir is not None:
        backup_ignore = root / BACKUP_DIRECTORY / ".gitignore"
        if _read_existing(backup_ignore) is None:
            _write_checked(backup_ignore, b"*\n", None)
        for name in replacements:
            data = existing[name]
            assert data is not None
            _write_checked(backup_dir / name, data, None)
        if original_manifest is not None:
            _write_checked(backup_dir / MANIFEST_PATH, original_manifest, None)
    for entry in actions:
        if entry.path != MANIFEST_PATH and entry.action != "unchanged":
            _write_checked(root / entry.path, assets[entry.path], existing[entry.path])
    if original_manifest != manifest:
        _write_checked(manifest_file, manifest, original_manifest)
    return BootstrapResult(root, tuple(actions), False, backup_dir)
