"""Unit tests for Monty Sandbox, Live Symbol Introspection, Pointblank QA, QueryChat, and Marimo DAG Gate."""

import subprocess
from pathlib import Path

import polars as pl
import pytest

from nouc_studio.memory.store import AdaptiveMemoryStore
from nouc_studio.studio import TransparentQueryChatEngine, validate_readonly_sql
from nouc_studio.verification import (
    MontySandboxRunner,
    run_pointblank_validation,
    validate_marimo_reactive_dag,
    verify_live_python_symbol,
)
from nouc_studio.verification.gate import VerificationGate


def test_live_symbol_introspection_and_typed_dict() -> None:
    res_pb = verify_live_python_symbol("pointblank", "Validate")
    assert res_pb.exists
    assert res_pb.signature is not None

    res_td = verify_live_python_symbol("pydantic_monty", "ResourceLimits")
    assert res_td.exists
    assert res_td.kind == "TypedDict"
    assert "max_memory" in res_td.typed_dict_keys

    res_missing = verify_live_python_symbol("polars", "DataFrame.non_existent_method_xyz")
    assert not res_missing.exists


def test_monty_sandbox_runner() -> None:
    runner = MontySandboxRunner()
    res = runner.run_snippet(
        "round((rev - cost) / rev * 100.0, 2)",
        inputs={"rev": 200.0, "cost": 50.0},
    )
    assert res.succeeded
    assert res.return_value == 75.0

    err_res = runner.run_snippet("1 / 0")
    assert not err_res.succeeded
    assert err_res.error_type is not None


def test_pointblank_validation_and_querychat() -> None:
    df = pl.DataFrame(
        {
            "region": ["EU", "US", "APAC"],
            "sales": [150.0, 240.0, 110.0],
        }
    )
    pb_rep = run_pointblank_validation(
        df,
        table_id="regional_sales",
        positive_columns=["sales"],
    )
    assert pb_rep.all_passed
    assert pb_rep.mean_pass_rate == 1.0

    qc = TransparentQueryChatEngine({"regional_sales": df})
    resp, out_df = qc.execute_question("What is the sum of sales by region?")
    assert resp.succeeded
    assert "GROUP BY" in resp.sql_query
    assert out_df.height == 3

    is_safe, _ = validate_readonly_sql("DROP TABLE regional_sales")
    assert not is_safe


def test_marimo_reactive_dag_duplicate_definition_detection(tmp_path: Path) -> None:
    bad_nb = tmp_path / "bad_notebook.py"
    bad_nb.write_text(
        "import marimo\napp = marimo.App()\n"
        "@app.cell\ndef cell_one():\n    shared_metric = 10\n    return (shared_metric,)\n"
        "@app.cell\ndef cell_two():\n    shared_metric = 20\n    return (shared_metric,)\n",
        encoding="utf-8",
    )
    res = validate_marimo_reactive_dag(bad_nb)
    assert not res.passed
    assert any("MultipleDefinitionError" in d for d in res.diagnostics)


def test_marimo_reactive_dag_same_cell_ui_value_and_unbound_param(tmp_path: Path) -> None:
    bad_ui_nb = tmp_path / "bad_ui_notebook.py"
    bad_ui_nb.write_text(
        "import marimo\napp = marimo.App()\n"
        "@app.cell\ndef setup():\n    import marimo as mo\n    return (mo,)\n"
        "@app.cell\ndef bad_ui_cell(mo):\n"
        "    dropdown = mo.ui.dropdown(options=['a', 'b'], value='a')\n"
        "    picked = dropdown.value\n"
        "    return (dropdown, picked)\n"
        "@app.cell\ndef bad_consumer(non_existent_var):\n"
        "    return (non_existent_var,)\n",
        encoding="utf-8",
    )
    res = validate_marimo_reactive_dag(bad_ui_nb)
    assert not res.passed
    assert any("SameCellUIValueError" in d for d in res.diagnostics)
    assert any("UnboundCellParameterError" in d for d in res.diagnostics)


def test_marimo_reactive_dag_annotated_and_nested_unpacking(tmp_path: Path) -> None:
    notebook = tmp_path / "assignments.py"
    source = (
        "import marimo\napp = marimo.App()\n"
        "@app.cell\ndef producer():\n"
        "    annotated: float = 1.0\n"
        "    left, [middle, (right, _local)] = (1, [2, (3, 4)])\n"
        "    [list_left, list_right] = [5, 6]\n"
        "    head, *tail = (7, 8, 9)\n"
        "@app.cell\ndef consumer(annotated, left, middle, right, list_left, list_right, head, tail):\n"
        "    result = annotated + left + middle + right + list_left + list_right + head + tail[0]\n"
    )
    notebook.write_text(source, encoding="utf-8")
    result = validate_marimo_reactive_dag(notebook)
    assert result.passed, result.diagnostics

    notebook.write_text(
        source.replace("def consumer(annotated,", "def consumer(missing,"), encoding="utf-8",
    )
    result = validate_marimo_reactive_dag(notebook)
    assert not result.passed
    assert any("UnboundCellParameterError" in d and "missing" in d for d in result.diagnostics)

    # A bare annotation (`x: int`) binds nothing, so consuming it stays an error.
    notebook.write_text(
        "import marimo\napp = marimo.App()\n"
        "@app.cell\ndef producer():\n"
        "    declared: int\n"
        "@app.cell\ndef consumer(declared):\n"
        "    result = declared + 1\n",
        encoding="utf-8",
    )
    result = validate_marimo_reactive_dag(notebook)
    assert not result.passed
    assert any("UnboundCellParameterError" in d and "declared" in d for d in result.diagnostics)


@pytest.mark.parametrize("check", ["run_ruff_check", "run_ty_check", "run_marimo_check"])
def test_verification_subprocess_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: str,
) -> None:
    memory = AdaptiveMemoryStore(tmp_path / "local", tmp_path / "global")
    gate = VerificationGate(memory, cwd=tmp_path, command_timeout=1.5)
    notebook = tmp_path / "app.py"
    notebook.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")

    def timeout(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 1.5
        assert kwargs["cwd"] == tmp_path
        raise subprocess.TimeoutExpired(cmd, 1.5)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = getattr(gate, check)(notebook)
    assert not result.passed
    assert len(result.diagnostics) == 1
    assert "timeout" in result.diagnostics[0].lower()
    assert "1.5" in result.diagnostics[0]
    assert result.command_or_target in result.diagnostics[0]

