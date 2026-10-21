"""Exercise a built wheel's real Copilot setup outside the source checkout.

Usage: uv run python scripts/check_bootstrap_install.py dist/package
The wheel is installed with its verify extra into a separate uv environment using
this command's exact Python interpreter. No editable source package is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path


def select_wheel(path: Path) -> Path:
    candidates = list(path.glob("*.whl")) if path.is_dir() else [path]
    if len(candidates) != 1 or not candidates[0].is_file() or candidates[0].suffix != ".whl":
        raise ValueError("Provide exactly one built wheel or its dedicated output directory.")
    return candidates[0].resolve()


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("Expected exactly one wheel METADATA file.")
        metadata = BytesParser().parsebytes(archive.read(names[0]))
    version = metadata["Version"]
    if metadata["Name"] != "nouc-studio" or not isinstance(version, str) or not version:
        raise ValueError("Expected a versioned nouc-studio wheel.")
    return version


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


def installed_check(
    workspace: Path, source_root: Path, expected_version: str, expected_python: str,
) -> None:
    """Runs only in the wheel environment, under python -I, with no source imports."""
    from importlib.metadata import version

    import nouc_studio
    from nouc_studio.bootstrap import COPILOT_FILES, MANIFEST_PATH, load_copilot_resources

    assert not workspace.resolve().is_relative_to(source_root.resolve()), "Smoke cwd is inside the checkout."
    assert nouc_studio.__file__ is not None
    assert not Path(nouc_studio.__file__).resolve().is_relative_to(source_root.resolve()), (
        "The smoke check imported the source checkout instead of the installed wheel."
    )
    assert nouc_studio.__version__ == version("nouc-studio") == expected_version
    assert ".".join(map(str, sys.version_info[:3])) == expected_python
    cli = Path(sys.executable).parent / ("nouc.exe" if os.name == "nt" else "nouc")
    assert cli.is_file(), "The wheel did not install the nouc entry point."
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def invoke(*arguments: str, expected_code: int = 0) -> None:
        result = subprocess.run(
            [str(cli), *arguments], cwd=workspace, env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        assert result.returncode == expected_code, result.stdout + result.stderr

    for module in ("ruff", "ty", "pytest"):
        subprocess.run([sys.executable, "-I", "-m", module, "--version"], check=True, env=environment)
    invoke("--help")
    consumer = workspace / "consumer-project"
    invoke("init", str(consumer), "--agent", "copilot", "--dry-run")
    assert not consumer.exists(), "Dry-run created consumer files."
    invoke("init", str(consumer), "--agent", "copilot")
    before = snapshot(consumer)
    assert set(before) == {*COPILOT_FILES, MANIFEST_PATH}
    assets = load_copilot_resources()
    assert len(assets) == 8
    for name in COPILOT_FILES:
        assert before[name][0] == assets[name], f"Installed setup differs from its bundle: {name}"
    manifest = json.loads((consumer / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert manifest["package_version"] == expected_version
    assert manifest["files"] == {
        name: hashlib.sha256(content).hexdigest() for name, content in assets.items()
    }
    invoke("init", str(consumer), "--agent", "copilot")
    assert snapshot(consumer) == before, "Repeated setup changed contents or modification times."

    user_file = consumer / "AGENTS.md"
    user_file.write_bytes(user_file.read_bytes() + b"\n# Consumer-maintained note\n")
    edited = snapshot(consumer)
    invoke("init", str(consumer), "--agent", "copilot", expected_code=1)
    assert snapshot(consumer) == edited, "Setup overwrote a consumer edit or partially wrote a conflict."
    print(json.dumps({
        "version": expected_version, "python": expected_python, "copilot_files": len(assets),
        "dry_run": "passed", "init": "passed", "idempotence": "passed", "preserves_edits": "passed",
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    if len(sys.argv) > 1 and sys.argv[1] == "--installed-check":
        parser.add_argument("workspace", type=Path)
        parser.add_argument("source_root", type=Path)
        parser.add_argument("expected_version")
        parser.add_argument("expected_python")
        args = parser.parse_args(sys.argv[2:])
        installed_check(args.workspace, args.source_root, args.expected_version, args.expected_python)
        return
    parser.add_argument("wheel", type=Path, help="Wheel path or dedicated distribution output directory.")
    args = parser.parse_args()
    try:
        wheel = select_wheel(args.wheel)
        expected_version = wheel_version(wheel)
        uv = shutil.which("uv")
        if uv is None:
            raise ValueError("uv must be available on PATH.")
        script = Path(__file__).resolve()
        source_root = script.parents[1]
        environment = os.environ.copy()
        for name in (
            "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT", "UV_PROJECT_ENVIRONMENT",
            "UV_NO_SYNC", "UV_FROZEN",
        ):
            environment.pop(name, None)
        with tempfile.TemporaryDirectory(prefix="nouc-bootstrap-smoke-") as temporary:
            workspace = Path(temporary).resolve()
            command = [
                uv, "run", "--isolated", "--no-project", "--no-config", "--directory", str(workspace),
                "--python", sys.executable, "--with", f"{wheel}[verify]", "--",
                "python", "-I", str(script), "--installed-check", str(workspace), str(source_root),
                expected_version, ".".join(map(str, sys.version_info[:3])),
            ]
            subprocess.run(command, check=True, env=environment, cwd=workspace)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Installed bootstrap check failed: {exc}\n")


if __name__ == "__main__":
    main()
