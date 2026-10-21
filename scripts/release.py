"""Fail-closed source and distribution checks for tag and manual releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import zipfile
from email.parser import BytesParser
from importlib.metadata import version as installed_version
from pathlib import Path, PurePosixPath

RELEASE_TAG = re.compile(
    r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:(?:a|b|rc)(?:0|[1-9]\d*))?"
)
SDIST_EXAMPLE_FIXTURES = {
    "examples/demo_3_ai_infra_finops/frontier_llm_routing_2026.xlsx",
    "examples/demo_2_clinical_biotech/phase2_patient_cohorts.xlsx",
    "examples/sample_bundle/pricing_model.py",
    "examples/sample_bundle/methodology_notes.md",
}
COPILOT_RESOURCE_FILES = (
    "AGENTS.md",
    ".github/copilot-instructions.md",
    ".github/agents/nouc-studio.agent.md",
    "skills/marimo-pair-sandbox/SKILL.md",
    "skills/deepwiki-live-grounding/SKILL.md",
    "skills/adaptive-failure-memory/SKILL.md",
    "skills/epistemic-lineage-studio/SKILL.md",
    "skills/studio-experience-design/SKILL.md",
)
WHEEL_BOOTSTRAP_PREFIX = "nouc_studio/_bootstrap/"
FORBIDDEN_ARCHIVE_PARTS = {
    ".cache", ".uv-cache", ".insights", ".nouc-studio", "apps", "__marimo__", "__pycache__",
}


def forbidden_archive_path(name: str, allowed_github: set[str], *, directory: bool = False) -> bool:
    """Allow only the two canonical GitHub instruction files, never workflow/state trees."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return True
    if FORBIDDEN_ARCHIVE_PARTS.intersection(path.parts) or ".env" in path.parts:
        return True
    if ".github" not in path.parts:
        return False
    allowed = allowed_github
    if directory:
        allowed = {parent.as_posix() for item in allowed_github for parent in PurePosixPath(item).parents}
    return path.as_posix() not in allowed


def git(repository: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()


def select_source(
    repository: Path, tag: str, target: str, default_branch: str, workflow_ref: str,
    event_name: str = "workflow_dispatch", event_sha: str = "",
) -> dict[str, str]:
    publishing = target != "build"
    if target == "pypi" and not tag:
        raise ValueError("Publishing requires an existing release tag; commits produce build artifacts only.")
    if tag and RELEASE_TAG.fullmatch(tag) is None:
        raise ValueError("Use a canonical tag such as v1.2.3 or v1.2.3rc1.")
    if publishing:
        if event_name == "push":
            if target != "pypi" or workflow_ref != f"refs/tags/{tag}" or not event_sha:
                raise ValueError("Automatic publishing requires a matching tag push to PyPI and its commit SHA.")
        elif event_name != "workflow_dispatch" or workflow_ref != f"refs/heads/{default_branch}":
            raise ValueError("Run manual publishing from the default branch workflow, with the tag as an input.")
    if git(repository, "status", "--porcelain"):
        raise ValueError("Release builds require a clean checkout.")
    sha = git(repository, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}" if tag else "HEAD")
    if publishing and event_name == "push" and sha != event_sha:
        raise ValueError("The release tag no longer matches the commit in the push event.")
    if publishing:
        subprocess.run(
            ["git", "-C", str(repository), "merge-base", "--is-ancestor", sha, f"origin/{default_branch}"],
            check=True,
        )
    return {"source_sha": sha, "release_tag": tag}


def test_snapshot_version(scm_version: str) -> str:
    """Keep Git's public dev version while excluding the index-forbidden local hash."""
    if re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:(?:a|b|rc)\d+)?\.dev\d+(?:\+g[0-9a-f]+)?", scm_version) is None:
        raise ValueError("TestPyPI snapshots require a clean Git development version; use a tag for a release.")
    return scm_version.split("+", 1)[0]


def inspect_distributions(directory: Path, tag: str = "", test_version: str = "") -> dict[str, str]:
    if tag and RELEASE_TAG.fullmatch(tag) is None:
        raise ValueError("Invalid release tag.")
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one sdist in a dedicated output directory.")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_files = [n for n in names if n.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError("Expected one wheel METADATA file.")
        wheel_metadata = BytesParser().parsebytes(wheel.read(metadata_files[0]))
        if "nouc_studio/studio/workbench.py" not in names:
            raise ValueError("The wheel is missing the runtime workbench.")
        if any(n.split("/")[0] != "nouc_studio" and ".dist-info/" not in n for n in names):
            raise ValueError("The wheel contains files outside the package and its metadata.")
        allowed_github = {
            WHEEL_BOOTSTRAP_PREFIX + name for name in COPILOT_RESOURCE_FILES if name.startswith(".github/")
        }
        if any(
            forbidden_archive_path(item.filename, allowed_github, directory=item.is_dir())
            for item in wheel.infolist()
        ):
            raise ValueError("The wheel contains local state, demos or secrets, or unexpected .github files.")
        wheel_resources: dict[str, bytes] = {}
        for name in COPILOT_RESOURCE_FILES:
            bundled = WHEEL_BOOTSTRAP_PREFIX + name
            if names.count(bundled) != 1:
                raise ValueError(f"The wheel is missing a unique Copilot resource: {name}")
            content = wheel.read(bundled)
            if not content.strip():
                raise ValueError(f"The wheel contains an empty Copilot resource: {name}")
            wheel_resources[name] = content
    with tarfile.open(sources[0], "r:gz") as source:
        members = source.getmembers()
        metadata_files = [m for m in members if len(Path(m.name).parts) == 2 and m.name.endswith("/PKG-INFO")]
        if len(metadata_files) != 1:
            raise ValueError("Expected one top-level sdist PKG-INFO file.")
        stream = source.extractfile(metadata_files[0])
        if stream is None:
            raise ValueError("Cannot read sdist metadata.")
        source_metadata = BytesParser().parsebytes(stream.read())
        allowed_github = {name for name in COPILOT_RESOURCE_FILES if name.startswith(".github/")}
        if any(
            forbidden_archive_path(
                PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix(),
                allowed_github,
                directory=member.isdir(),
            )
            for member in members
        ):
            raise ValueError("The sdist contains local state, demos or secrets, or unexpected .github files.")
        if any(
            m.isfile() and Path(m.name).parts[1:2] == ("examples",)
            and Path(*Path(m.name).parts[1:]).as_posix() not in SDIST_EXAMPLE_FIXTURES
            for m in members
        ):
            raise ValueError("The sdist contains examples other than the four test fixtures.")
        root = PurePosixPath(metadata_files[0].name).parts[0]
        for name in COPILOT_RESOURCE_FILES:
            matches = [member for member in members if member.name == f"{root}/{name}" and member.isfile()]
            if len(matches) != 1:
                raise ValueError(f"The sdist is missing a unique canonical Copilot resource: {name}")
            stream = source.extractfile(matches[0])
            if stream is None:
                raise ValueError(f"Cannot read canonical Copilot resource: {name}")
            if stream.read() != wheel_resources[name]:
                raise ValueError(f"Wheel and sdist Copilot resources disagree: {name}")
    version = str(wheel_metadata["Version"])
    if wheel_metadata["Name"] != "nouc-studio" or source_metadata["Name"] != "nouc-studio":
        raise ValueError("Unexpected distribution name.")
    if not version or version == "None" or source_metadata["Version"] != version:
        raise ValueError("Wheel and sdist versions disagree.")
    if tag and version != tag[1:]:
        raise ValueError(f"Tag {tag} does not match distribution version {version}.")
    if test_version and (tag or version != test_snapshot_version(test_version)):
        raise ValueError("TestPyPI snapshot metadata does not match its Git development version.")
    return {
        "version": version,
        "wheel": wheels[0].name,
        "sdist": sources[0].name,
        "wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(sources[0].read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("--repository", type=Path, default=Path.cwd())
    select.add_argument("--tag", default=os.getenv("RELEASE_TAG", ""))
    select.add_argument("--target", choices=["build", "testpypi", "pypi"], default=os.getenv("PUBLISH_TARGET", "build"))
    select.add_argument("--default-branch", default=os.getenv("DEFAULT_BRANCH", "main"))
    select.add_argument("--workflow-ref", default=os.getenv("GITHUB_REF", ""))
    select.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch"))
    select.add_argument("--event-sha", default=os.getenv("GITHUB_SHA", ""))
    inspect = commands.add_parser("inspect")
    inspect.add_argument("directory", type=Path)
    inspect.add_argument("--tag", default=os.getenv("RELEASE_TAG", ""))
    inspect.add_argument("--test-version", default=os.getenv("EXPECTED_TEST_VERSION", ""))
    snapshot = commands.add_parser("test-version")
    snapshot.add_argument("--scm-version", default=None)
    args = parser.parse_args()
    try:
        if args.command == "select":
            result = select_source(
                args.repository, args.tag, args.target, args.default_branch, args.workflow_ref,
                args.event_name, args.event_sha,
            )
        elif args.command == "test-version":
            result = {"test_version": test_snapshot_version(args.scm_version or installed_version("nouc-studio"))}
        else:
            result = inspect_distributions(args.directory, args.tag, args.test_version)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    if output := os.getenv("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{key}={value}\n" for key, value in result.items())
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write("\n### Release validation\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n")


if __name__ == "__main__":
    main()
