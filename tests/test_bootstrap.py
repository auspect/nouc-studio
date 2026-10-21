"""Consumer setup preserves existing work and rejects redirected destinations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nouc_studio import bootstrap
from nouc_studio.bootstrap import (
    BACKUP_DIRECTORY,
    COPILOT_FILES,
    MANIFEST_PATH,
    BootstrapError,
    initialize_project,
)
from nouc_studio.cli import app


@pytest.fixture
def assets(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    values = {name: f"# Bundled {name}\n".encode() for name in COPILOT_FILES}
    monkeypatch.setattr(bootstrap, "load_copilot_resources", lambda: values.copy())
    monkeypatch.setattr(bootstrap.metadata, "version", lambda _: "0.1.dev99")
    return values


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def test_new_consumer_receives_only_allowlisted_assets_and_receipt(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    root = tmp_path / "new-project"
    result = initialize_project(root)

    assert result.backup_dir is None
    assert set(snapshot(root)) == {*COPILOT_FILES, MANIFEST_PATH}
    for name, data in assets.items():
        assert (root / name).read_bytes() == data
    manifest = json.loads((root / MANIFEST_PATH).read_text())
    assert manifest["package_version"] == "0.1.dev99"
    assert manifest["files"] == {
        name: hashlib.sha256(data).hexdigest() for name, data in assets.items()
    }


def test_repeated_setup_preserves_bytes_and_mtimes(tmp_path: Path, assets: dict[str, bytes]) -> None:
    initialize_project(tmp_path)
    before = snapshot(tmp_path)

    result = initialize_project(tmp_path)

    assert {entry.action for entry in result.files} == {"unchanged"}
    assert snapshot(tmp_path) == before


def test_dry_run_does_not_even_create_target(tmp_path: Path, assets: dict[str, bytes]) -> None:
    root = tmp_path / "absent" / "new-project"
    result = initialize_project(root, dry_run=True)

    assert result.dry_run
    assert not root.parent.exists()
    assert {entry.action for entry in result.files} == {"create"}


def test_unmanaged_conflict_stops_all_writes(tmp_path: Path, assets: dict[str, bytes]) -> None:
    (tmp_path / "AGENTS.md").write_text("My existing project instructions\n")
    before = snapshot(tmp_path)

    with pytest.raises(BootstrapError, match="no files were written: AGENTS.md"):
        initialize_project(tmp_path)

    assert snapshot(tmp_path) == before


def test_matching_existing_file_is_adopted_without_rewriting(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    existing = tmp_path / "AGENTS.md"
    existing.write_bytes(assets["AGENTS.md"])
    before = existing.stat().st_mtime_ns
    initialize_project(tmp_path)
    assert existing.stat().st_mtime_ns == before


def test_user_modified_managed_file_requires_explicit_overwrite(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    initialize_project(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Personal additions\n")
    before = snapshot(tmp_path)
    with pytest.raises(BootstrapError, match="Existing user files differ"):
        initialize_project(tmp_path)
    assert snapshot(tmp_path) == before


def test_overwrite_keeps_exact_backup_without_printing_its_contents(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    user_text = b"Personal confidential instructions\n"
    (tmp_path / "AGENTS.md").write_bytes(user_text)
    result = initialize_project(tmp_path, overwrite=True)

    assert result.backup_dir is not None
    assert (result.backup_dir / "AGENTS.md").read_bytes() == user_text
    assert (tmp_path / "AGENTS.md").read_bytes() == assets["AGENTS.md"]
    assert (tmp_path / BACKUP_DIRECTORY / ".gitignore").read_bytes() == b"*\n"
    assert "confidential" not in repr(result)


def test_upgrade_updates_only_untouched_managed_file_and_backs_it_up(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    initialize_project(tmp_path)
    old_manifest = (tmp_path / MANIFEST_PATH).read_bytes()
    old = assets["AGENTS.md"]
    assets["AGENTS.md"] = old + b"Updated release instructions\n"

    result = initialize_project(tmp_path)

    assert result.backup_dir is not None
    assert (result.backup_dir / "AGENTS.md").read_bytes() == old
    assert (result.backup_dir / MANIFEST_PATH).read_bytes() == old_manifest
    assert next(entry.action for entry in result.files if entry.path == "AGENTS.md") == "update"


def test_overwrite_dry_run_never_creates_backup(tmp_path: Path, assets: dict[str, bytes]) -> None:
    (tmp_path / "AGENTS.md").write_text("User instructions")
    before = snapshot(tmp_path)
    result = initialize_project(tmp_path, dry_run=True, overwrite=True)
    assert result.backup_dir is not None
    assert not result.backup_dir.parent.exists()
    assert snapshot(tmp_path) == before


def test_custom_backup_ignore_is_preserved_and_blocks_replacement(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    (tmp_path / "AGENTS.md").write_text("User instructions")
    ignore = tmp_path / BACKUP_DIRECTORY / ".gitignore"
    ignore.parent.mkdir(parents=True)
    ignore.write_text("# custom rules\n")
    before = snapshot(tmp_path)
    with pytest.raises(BootstrapError, match="backups must remain excluded"):
        initialize_project(tmp_path, overwrite=True)
    assert snapshot(tmp_path) == before


def test_git_tracks_manifest_but_ignores_overwrite_backups(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    (tmp_path / "AGENTS.md").write_text("User instructions")
    initialize_project(tmp_path, overwrite=True)
    status = subprocess.check_output(
        ["git", "-C", str(tmp_path), "status", "--short", "--untracked-files=all"], text=True,
    )
    assert MANIFEST_PATH in status
    assert "bootstrap-backups" not in status


@pytest.mark.parametrize("manifest", [b"not json", b"[]", b"{}", b'\xff'])
def test_invalid_manifest_is_preserved_even_with_overwrite(
    tmp_path: Path, assets: dict[str, bytes], manifest: bytes,
) -> None:
    destination = tmp_path / MANIFEST_PATH
    destination.parent.mkdir()
    destination.write_bytes(manifest)
    before = snapshot(tmp_path)
    with pytest.raises(BootstrapError, match="Invalid .nouc-studio/bootstrap.json"):
        initialize_project(tmp_path, overwrite=True)
    assert snapshot(tmp_path) == before


def test_manifest_cannot_expand_destination_allowlist(tmp_path: Path, assets: dict[str, bytes]) -> None:
    destination = tmp_path / MANIFEST_PATH
    destination.parent.mkdir()
    destination.write_text(json.dumps({
        "schema_version": 1, "agent": "copilot", "files": {"../outside.txt": "0" * 64},
    }))
    with pytest.raises(BootstrapError, match="Invalid"):
        initialize_project(tmp_path)
    assert not (tmp_path.parent / "outside.txt").exists()


def directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        # Real junctions need no developer-mode symlink privilege on Windows.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("redirect", ["root", "ancestor", "github", "manifest-parent", "backup"])
def test_directory_symlinks_and_windows_junctions_are_rejected(
    tmp_path: Path, assets: dict[str, bytes], redirect: str,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "project"
    if redirect in {"root", "ancestor"}:
        directory_link(root, outside)
        if redirect == "ancestor":
            root = root / "nested"
    else:
        root.mkdir()
        if redirect == "github":
            directory_link(root / ".github", outside)
        elif redirect == "manifest-parent":
            directory_link(root / ".nouc-studio", outside)
        else:
            initialize_project(root)
            (root / "AGENTS.md").write_text("Edited instructions")
            directory_link(root / BACKUP_DIRECTORY, outside)
    with pytest.raises(BootstrapError, match="symbolic link or Windows reparse point"):
        initialize_project(root, overwrite=True)
    assert list(outside.iterdir()) == []


def test_existing_file_hardlink_is_rejected(tmp_path: Path, assets: dict[str, bytes]) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("Do not change me")
    root = tmp_path / "project"
    root.mkdir()
    os.link(outside, root / "AGENTS.md")
    with pytest.raises(BootstrapError, match="hard-linked"):
        initialize_project(root, overwrite=True)
    assert outside.read_text() == "Do not change me"


def test_directory_where_file_should_be_is_rejected(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    (tmp_path / "AGENTS.md").mkdir()
    with pytest.raises(BootstrapError, match="regular file"):
        initialize_project(tmp_path, overwrite=True)
    assert set(tmp_path.iterdir()) == {tmp_path / "AGENTS.md"}


def test_concurrent_destination_creation_is_preserved(
    tmp_path: Path, assets: dict[str, bytes], monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = bootstrap._write_checked

    def concurrent_write(path: Path, data: bytes, expected: bytes | None) -> None:
        if path.name == "AGENTS.md":
            path.write_text("Concurrent user instructions")
        original(path, data, expected)

    monkeypatch.setattr(bootstrap, "_write_checked", concurrent_write)
    with pytest.raises(BootstrapError, match="changed during setup"):
        initialize_project(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == "Concurrent user instructions"


def test_missing_packaged_resource_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.resources, "files", lambda _: tmp_path)
    with pytest.raises(BootstrapError, match="installed distribution is missing"):
        bootstrap.load_copilot_resources()
    assert list(tmp_path.iterdir()) == []


def test_cli_reports_consumer_paths_and_nonzero_conflict(
    tmp_path: Path, assets: dict[str, bytes],
) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(tmp_path), "--agent", "copilot"])
    assert result.exit_code == 0, result.output
    assert "Nouc Studio Copilot agent" in result.output
    assert "<your source paths>" in result.output
    assert "nouc-studio[verify]" in result.output
    (tmp_path / "AGENTS.md").write_text("private text must not be logged")
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 1
    assert "Existing user files differ" in result.output
    assert "private text" not in result.output


def test_unknown_agent_does_not_create_target(tmp_path: Path, assets: dict[str, bytes]) -> None:
    root = tmp_path / "absent"
    result = CliRunner().invoke(app, ["init", str(root), "--agent", "unknown"])
    assert result.exit_code == 1
    assert not root.exists()


def test_distribution_bundles_exact_canonical_resources_in_wheel_and_sdist() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    targets = project["tool"]["hatch"]["build"]["targets"]
    assert targets["wheel"]["force-include"] == {
        name: f"nouc_studio/_bootstrap/{name}" for name in COPILOT_FILES
    }
    assert all(f"/{name}" in targets["sdist"]["include"] for name in COPILOT_FILES)
    assert not any(name in targets["sdist"]["include"] for name in ("/.github", "/skills"))
    assert {"pytest", "ruff", "ty"} == {
        dependency.split(">=")[0] for dependency in project["project"]["optional-dependencies"]["verify"]
    }
