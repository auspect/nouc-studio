"""Exercise release boundaries through the same CLI used by tag and manual workflows."""

from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from nouc_studio.bootstrap import COPILOT_FILES

RELEASE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.py"


def git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments], text=True, stderr=subprocess.STDOUT
    ).strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "--initial-branch=main")
    git(repository, "config", "user.name", "Release Guard Test")
    git(repository, "config", "user.email", "release-test@example.invalid")
    git(repository, "config", "commit.gpgsign", "false")
    (repository / "source.txt").write_text("initial source\n", encoding="utf-8")
    git(repository, "add", "source.txt")
    git(repository, "commit", "-m", "Initial source")
    git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repository


def release(*arguments: str) -> subprocess.CompletedProcess[str]:
    # Keep local runs independent of a surrounding CI job's inputs/output paths.
    environment = os.environ.copy()
    for name in (
        "RELEASE_TAG", "PUBLISH_TARGET", "DEFAULT_BRANCH", "GITHUB_REF",
        "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY",
        "GITHUB_EVENT_NAME", "GITHUB_SHA",
        "EXPECTED_TEST_VERSION",
    ):
        environment.pop(name, None)
    return subprocess.run(
        [sys.executable, str(RELEASE_SCRIPT), *arguments],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def select(
    repository: Path, *, tag: str = "", target: str = "build",
    workflow_ref: str = "refs/heads/main",
    event_name: str = "workflow_dispatch", event_sha: str = "",
) -> subprocess.CompletedProcess[str]:
    return release(
        "select", "--repository", str(repository), f"--tag={tag}",
        "--target", target, "--default-branch", "main", "--workflow-ref", workflow_ref,
        "--event-name", event_name, "--event-sha", event_sha,
    )


def test_commit_snapshot_can_build_without_a_release_tag(repository: Path) -> None:
    result = select(repository)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "source_sha": git(repository, "rev-parse", "HEAD"), "release_tag": "",
    }


@pytest.mark.parametrize(("tag", "target"), [("v1.2.3", "pypi"), ("v2.0.0rc1", "testpypi")])
def test_existing_canonical_release_on_default_history_can_publish(
    repository: Path, tag: str, target: str,
) -> None:
    git(repository, "tag", "-a", tag, "-m", "Release candidate")
    tagged_sha = git(repository, "rev-parse", "HEAD")
    (repository / "source.txt").write_text("later source\n", encoding="utf-8")
    git(repository, "commit", "-am", "Continue development after release")
    git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")

    result = select(repository, tag=tag, target=target)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "source_sha": tagged_sha, "release_tag": tag,
    }


def test_commit_snapshot_cannot_publish_to_production(repository: Path) -> None:
    result = select(repository, target="pypi")

    assert result.returncode != 0
    assert "requires an existing release tag" in result.stderr


def test_default_branch_snapshot_can_publish_to_testpypi(repository: Path) -> None:
    result = select(repository, target="testpypi")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_sha"] == git(repository, "rev-parse", "HEAD")


def test_feature_workflow_cannot_publish_snapshot(repository: Path) -> None:
    result = select(repository, target="testpypi", workflow_ref="refs/heads/feature")
    assert result.returncode != 0


def test_unmerged_snapshot_cannot_publish(repository: Path) -> None:
    git(repository, "checkout", "-b", "feature")
    (repository / "source.txt").write_text("unmerged source\n", encoding="utf-8")
    git(repository, "commit", "-am", "Feature")
    result = select(repository, target="testpypi")
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("scm_version", "expected"),
    [("0.1.dev14+gabc1234", "0.1.dev14"), ("1.2.4.dev3+gdef1234", "1.2.4.dev3")],
)
def test_snapshot_version_retains_git_distance_without_local_hash(scm_version: str, expected: str) -> None:
    result = release("test-version", "--scm-version", scm_version)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"test_version": expected}


@pytest.mark.parametrize("scm_version", ["1.2.3", "1.2.3rc1", "1.2.4.dev3+gabc.d20261017", "invalid"])
def test_snapshot_rejects_releases_and_dirty_versions(scm_version: str) -> None:
    result = release("test-version", "--scm-version", scm_version)
    assert result.returncode != 0


@pytest.mark.parametrize("workflow_ref", ["refs/heads/feature", "refs/tags/v1.2.3"])
def test_publish_must_use_default_branch_workflow(repository: Path, workflow_ref: str) -> None:
    git(repository, "tag", "v1.2.3")

    result = select(repository, tag="v1.2.3", target="pypi", workflow_ref=workflow_ref)

    assert result.returncode != 0
    assert "default branch workflow" in result.stderr


def test_dirty_checkout_cannot_publish(repository: Path) -> None:
    git(repository, "tag", "v1.2.3")
    (repository / "source.txt").write_text("uncommitted source\n", encoding="utf-8")

    result = select(repository, tag="v1.2.3", target="pypi")

    assert result.returncode != 0
    assert "clean checkout" in result.stderr


@pytest.mark.parametrize("tag", ["v1.2.3", "v2.0.0rc1"])
def test_tag_push_publishes_exact_event_commit(repository: Path, tag: str) -> None:
    git(repository, "tag", "-a", tag, "-m", "Release")
    sha = git(repository, "rev-parse", "HEAD")
    result = select(
        repository, tag=tag, target="pypi", workflow_ref=f"refs/tags/{tag}",
        event_name="push", event_sha=sha,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_sha"] == sha


@pytest.mark.parametrize(
    ("workflow_ref", "target", "event_sha"),
    [
        ("refs/heads/main", "pypi", "HEAD"),
        ("refs/tags/v9.9.9", "pypi", "HEAD"),
        ("refs/tags/v1.2.3", "testpypi", "HEAD"),
        ("refs/tags/v1.2.3", "pypi", ""),
        ("refs/tags/v1.2.3", "pypi", "0" * 40),
    ],
)
def test_automatic_publish_rejects_mismatched_event(
    repository: Path, workflow_ref: str, target: str, event_sha: str,
) -> None:
    git(repository, "tag", "v1.2.3")
    sha = git(repository, "rev-parse", "HEAD") if event_sha == "HEAD" else event_sha
    result = select(
        repository, tag="v1.2.3", target=target, workflow_ref=workflow_ref,
        event_name="push", event_sha=sha,
    )
    assert result.returncode != 0
    assert "source_sha" not in result.stdout


def test_automatic_publish_rejects_unmerged_tag(repository: Path) -> None:
    git(repository, "checkout", "-b", "feature")
    (repository / "source.txt").write_text("unmerged source\n", encoding="utf-8")
    git(repository, "commit", "-am", "Feature")
    git(repository, "tag", "v1.2.3")
    result = select(
        repository, tag="v1.2.3", target="pypi", workflow_ref="refs/tags/v1.2.3",
        event_name="push", event_sha=git(repository, "rev-parse", "HEAD"),
    )
    assert result.returncode != 0
    assert "source_sha" not in result.stdout


def test_unmerged_feature_tag_cannot_publish(repository: Path) -> None:
    git(repository, "checkout", "-b", "feature")
    (repository / "source.txt").write_text("unmerged source\n", encoding="utf-8")
    git(repository, "commit", "-am", "Unmerged feature")
    git(repository, "tag", "v1.2.3")

    result = select(repository, tag="v1.2.3", target="pypi")

    assert result.returncode != 0
    assert "source_sha" not in result.stdout


def test_missing_default_remote_reference_fails_closed(repository: Path) -> None:
    git(repository, "tag", "v1.2.3")
    git(repository, "update-ref", "-d", "refs/remotes/origin/main")

    result = select(repository, tag="v1.2.3", target="pypi")

    assert result.returncode != 0
    assert "source_sha" not in result.stdout


@pytest.mark.parametrize(
    "tag",
    [
        "v01.2.3", "v1.02.3", "v1.2.03", "v1.2.3rc01", "1.2.3",
        "v1.2.3+local", "v1.2.3.post1", "v1.2.3;echo injected", "--help",
    ],
)
def test_noncanonical_or_command_shaped_tag_is_rejected(repository: Path, tag: str) -> None:
    result = select(repository, tag=tag, target="pypi")

    assert result.returncode != 0
    assert "canonical tag" in result.stderr


def distributions(
    directory: Path, *, wheel_version: str = "1.2.3", source_version: str | None = None,
    workbench: bool = True, wheel_extra: str | None = None, source_extra: str | None = None,
    missing_wheel_resource: str | None = None, missing_source_resource: str | None = None,
    changed_wheel_resource: str | None = None,
) -> tuple[Path, Path]:
    """Small archives sufficient to exercise metadata/content validation, without a build."""
    source_version = source_version or wheel_version
    wheel_path = directory / f"nouc_studio-{wheel_version}-py3-none-any.whl"
    source_path = directory / f"nouc_studio-{source_version}.tar.gz"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(
            f"nouc_studio-{wheel_version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: nouc-studio\nVersion: {wheel_version}\n\n",
        )
        if workbench:
            wheel.writestr("nouc_studio/studio/workbench.py", "# runtime workbench\n")
        for name in COPILOT_FILES:
            if name != missing_wheel_resource:
                content = f"# Canonical resource: {name}\n"
                if name == changed_wheel_resource:
                    content += "A stale bundled copy.\n"
                wheel.writestr(f"nouc_studio/_bootstrap/{name}", content)
        if wheel_extra:
            wheel.writestr(wheel_extra, "unexpected content\n")
    root = f"nouc_studio-{source_version}"
    source_files = {
        f"{root}/PKG-INFO": (
            f"Metadata-Version: 2.4\nName: nouc-studio\nVersion: {source_version}\n\n"
        ),
        f"{root}/src/nouc_studio/studio/workbench.py": "# runtime workbench\n",
        **{
            f"{root}/{name}": f"# Canonical resource: {name}\n"
            for name in COPILOT_FILES if name != missing_source_resource
        },
    }
    if source_extra:
        source_files[f"{root}/{source_extra}"] = "unexpected content\n"
    with tarfile.open(source_path, "w:gz") as source:
        for name, content in source_files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            source.addfile(info, io.BytesIO(data))
    return wheel_path, source_path


@pytest.mark.parametrize(("version", "tag"), [("1.2.3", "v1.2.3"), ("2.0.0rc1", "v2.0.0rc1"), ("1.2.4.dev2+gabc123", "")])
def test_consistent_artifacts_report_versions_and_real_digests(
    tmp_path: Path, version: str, tag: str,
) -> None:
    wheel, source = distributions(tmp_path, wheel_version=version)

    result = release("inspect", str(tmp_path), f"--tag={tag}")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "version": version, "wheel": wheel.name, "sdist": source.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def test_wheel_and_sdist_must_agree_on_version(tmp_path: Path) -> None:
    distributions(tmp_path, wheel_version="1.2.3", source_version="1.2.4")

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "versions disagree" in result.stderr


@pytest.mark.parametrize("version", ["1.2.4", "1.2.3.dev1", "1.2.3+gabc123"])
def test_tag_cannot_publish_different_development_or_local_version(tmp_path: Path, version: str) -> None:
    distributions(tmp_path, wheel_version=version)

    result = release("inspect", str(tmp_path), "--tag=v1.2.3")

    assert result.returncode != 0
    assert "does not match distribution version" in result.stderr


def test_runtime_workbench_must_be_in_the_wheel(tmp_path: Path) -> None:
    distributions(tmp_path, workbench=False)

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "missing the runtime workbench" in result.stderr


def test_unrelated_files_must_not_enter_wheel(tmp_path: Path) -> None:
    distributions(tmp_path, wheel_extra="apps/unrelated/app.py")

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "outside the package" in result.stderr


@pytest.mark.parametrize(
    "unwanted",
    [
        ".env", ".insights/memory/episodes.jsonl", "apps/demo/app.py", ".cache/build.log",
        ".github/workflows/publish.yml", ".github/unmanaged.md",
        "src/nouc_studio/_bootstrap/.github/workflows/private.yml",
        ".nouc-studio/bootstrap-backups/personal/AGENTS.md",
    ],
)
def test_local_state_and_demos_must_not_enter_sdist(tmp_path: Path, unwanted: str) -> None:
    distributions(tmp_path, source_extra=unwanted)

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "local state, demos or secrets" in result.stderr


@pytest.mark.parametrize(
    "unwanted",
    [
        "nouc_studio/.env", "nouc_studio/.insights/memory/episodes.jsonl",
        "nouc_studio/_bootstrap/.github/workflows/private.yml",
        "nouc_studio/_bootstrap/.github/unmanaged.md",
        "nouc_studio/_bootstrap/.nouc-studio/bootstrap-backups/personal/AGENTS.md",
    ],
)
def test_package_namespace_does_not_allow_local_state_or_unrelated_github_files(
    tmp_path: Path, unwanted: str,
) -> None:
    distributions(tmp_path, wheel_extra=unwanted)
    result = release("inspect", str(tmp_path))
    assert result.returncode != 0
    assert "local state, demos or secrets" in result.stderr


@pytest.mark.parametrize("resource", COPILOT_FILES)
def test_each_copilot_resource_must_be_in_the_wheel(tmp_path: Path, resource: str) -> None:
    distributions(tmp_path, missing_wheel_resource=resource)
    result = release("inspect", str(tmp_path))
    assert result.returncode != 0
    assert "missing a unique Copilot resource" in result.stderr
    assert resource in result.stderr


@pytest.mark.parametrize("resource", COPILOT_FILES)
def test_canonical_resources_must_be_available_to_rebuild_wheel_from_sdist(
    tmp_path: Path, resource: str,
) -> None:
    distributions(tmp_path, missing_source_resource=resource)
    result = release("inspect", str(tmp_path))
    assert result.returncode != 0
    assert "missing a unique canonical Copilot resource" in result.stderr
    assert resource in result.stderr


@pytest.mark.parametrize("resource", COPILOT_FILES)
def test_stale_bundled_instructions_cannot_disagree_with_canonical_sources(
    tmp_path: Path, resource: str,
) -> None:
    distributions(tmp_path, changed_wheel_resource=resource)
    result = release("inspect", str(tmp_path))
    assert result.returncode != 0
    assert "Copilot resources disagree" in result.stderr
    assert resource in result.stderr


def test_release_allowlist_tracks_runtime_and_hatch_packaging(tmp_path: Path) -> None:
    root = RELEASE_SCRIPT.parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    mappings = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert set(mappings) == set(COPILOT_FILES)
    release_module = runpy.run_path(str(RELEASE_SCRIPT))
    assert set(release_module["COPILOT_RESOURCE_FILES"]) == set(COPILOT_FILES)
    distributions(tmp_path)
    result = release("inspect", str(tmp_path))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("extension", ["whl", "tar.gz"])
def test_artifact_directory_cannot_mix_multiple_builds(tmp_path: Path, extension: str) -> None:
    distributions(tmp_path)
    (tmp_path / f"leftover.{extension}").write_bytes(b"old archive")

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "exactly one wheel and one sdist" in result.stderr


def test_incomplete_build_cannot_pass_artifact_validation(tmp_path: Path) -> None:
    _, source = distributions(tmp_path)
    source.unlink()

    result = release("inspect", str(tmp_path))

    assert result.returncode != 0
    assert "exactly one wheel and one sdist" in result.stderr


@pytest.mark.parametrize("wheel_version", ["1.2.4.dev3+gabc1234", "1.2.4.dev4"])
def test_snapshot_distribution_must_match_selected_public_version(tmp_path: Path, wheel_version: str) -> None:
    distributions(tmp_path, wheel_version=wheel_version)
    result = release("inspect", str(tmp_path), "--test-version", "1.2.4.dev3")
    assert result.returncode != 0
    assert "snapshot metadata" in result.stderr
