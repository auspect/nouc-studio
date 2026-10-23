"""Launch gates must reject broken views and preserve the project environment."""

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from marimo_studio.authoring import open_workspace
from typer.testing import CliRunner

from nouc_studio import cli
from nouc_studio.studio import launcher


@pytest.fixture
def studio_notebook(tmp_path: Path) -> Path:
    directory = tmp_path / "app with spaces"
    directory.mkdir()
    notebook = directory / "app.py"
    notebook.write_text('''import marimo
app = marimo.App()

@app.cell
def summary():
    result = 42
    result
    return (result,)

if __name__ == "__main__":
    app.run()
''', encoding="utf-8")

    async def create() -> None:
        view = await open_workspace(notebook).create_view("main")
        document = await view.read("index.html")
        await view.write(
            "index.html", document.content.replace(
                "</main>", '<marimo-cell name="summary"></marimo-cell></main>',
            ),
            expected_revision=document.revision,
        )

    asyncio.run(create())
    return notebook


@pytest.mark.parametrize("edit", [False, True])
def test_cli_builds_selected_profile_and_preserves_argv(
    studio_notebook: Path, monkeypatch: pytest.MonkeyPatch, edit: bool,
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 17))
    monkeypatch.setattr(cli.subprocess, "run", run)
    result = CliRunner().invoke(cli.app, [
        "studio", str(studio_notebook), "--headless", "--port", "2747",
        *(["--edit"] if edit else []),
    ])
    assert result.exit_code == 17, result.output
    assert f"profile={'development' if edit else 'production'}" in result.output
    command = run.call_args.args[0]
    assert command[:5] == [
        sys.executable, "-m", "marimo", "edit" if edit else "run", str(studio_notebook),
    ]
    assert "--no-sandbox" in command
    assert ("--watch" in command) == edit
    assert "--no-token" not in command
    assert command[-3:] == ["--headless", "--port", "2747"]


def test_check_executes_python_without_starting_server(
    studio_notebook: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Mock(side_effect=AssertionError("server must not start"))
    monkeypatch.setattr(cli.subprocess, "run", run)
    result = CliRunner().invoke(cli.app, ["studio", str(studio_notebook), "--check"])
    assert result.exit_code == 0, result.output
    assert "isolated Python checks passed" in result.output
    run.assert_not_called()


async def test_failed_rebuild_keeps_old_artifact_but_blocks_launch(studio_notebook: Path) -> None:
    await launcher.prepare_studio(studio_notebook, edit=True)
    view = open_workspace(studio_notebook).view("main")
    before = await view.inspect()
    document = await view.read("index.html")
    broken = document.content.replace("</head>", '<script src="./missing.js"></script></head>')
    await view.write("index.html", broken, expected_revision=document.revision)
    with pytest.raises(launcher.StudioLaunchError, match="View build failed.*main"):
        await launcher.prepare_studio(studio_notebook, edit=True)
    after = await view.inspect()
    assert before.build is not None and after.build is not None
    assert after.build.revision == before.build.revision
    assert after.latest_build is not None
    assert after.latest_build.phase == "failed"


async def test_runtime_error_is_distinct_from_valid_view_build(studio_notebook: Path) -> None:
    source = studio_notebook.read_text(encoding="utf-8")
    studio_notebook.write_text(source.replace("result = 42", "result = 1 / 0"), encoding="utf-8")
    await launcher.prepare_studio(studio_notebook)  # normal launch does not execute Python twice
    messages: list[str] = []
    with pytest.raises(launcher.StudioLaunchError, match="Runtime validation failed"):
        await launcher.prepare_studio(studio_notebook, check_runtime=True, emit=messages.append)
    assert any("runtime" in message.lower() for message in messages)


@pytest.mark.parametrize("exists", [False, True])
def test_missing_notebook_or_views_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exists: bool,
) -> None:
    notebook = tmp_path / "app.py"
    if exists:
        notebook.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(cli.subprocess, "run", run)
    result = CliRunner().invoke(cli.app, ["studio", str(notebook)])
    assert result.exit_code == 1
    assert ("No Studio views" if exists else "Notebook not found") in result.output
    run.assert_not_called()


def test_explicit_path_overrides_pixi_default(
    studio_notebook: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOUC_STUDIO_NOTEBOOK", "missing.py")
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(cli.subprocess, "run", run)
    result = CliRunner().invoke(cli.app, ["studio", str(studio_notebook)])
    assert result.exit_code == 0, result.output
    assert str(studio_notebook) in run.call_args.args[0]
    monkeypatch.setenv("NOUC_STUDIO_NOTEBOOK", str(studio_notebook))
    result = CliRunner().invoke(cli.app, ["studio"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("failed_stage", ["notebook", "view", "qa", "audit", None])
def test_build_cli_does_not_report_ready_after_failed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_stage: str | None,
) -> None:
    report = SimpleNamespace(
        agent_telemetry=[], traces=[], lineage_node_count=0, lineage_edge_count=0,
        studio_bundle=SimpleNamespace(
            notebook_path=tmp_path / "app.py", lineage_json_path=tmp_path / "lineage.json",
            launch_edit_command="edit", launch_run_command="run",
            views=[SimpleNamespace(view_name="main", build_revision="revision",
                                   validation_passed=failed_stage != "view", root_dir=str(tmp_path))],
        ),
        verification_report=SimpleNamespace(all_passed=failed_stage != "notebook"),
        pointblank_reports=[SimpleNamespace(all_passed=failed_stage != "qa")],
        epistemic_audits=[SimpleNamespace(passed=failed_stage != "audit")],
    )
    orchestrator = Mock()
    orchestrator.run_pipeline.return_value = report
    monkeypatch.setattr(cli, "MultiAgentOrchestrator", lambda **_: orchestrator)
    monkeypatch.setattr(cli, "InsightsConfig", lambda: None)
    result = CliRunner().invoke(cli.app, [
        "build", "--need", "synthetic smoke", "--input", "synthetic.csv", "--output", str(tmp_path),
    ])
    assert result.exit_code == (1 if failed_stage else 0), result.output
    assert ("Build checks passed" in result.output) == (failed_stage is None)
    if failed_stage:
        assert "Build verification failed" in result.output
        assert "orchestration_report.json" in result.output.replace("\n", "")
