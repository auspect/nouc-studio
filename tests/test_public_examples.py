"""Check the public examples' evidence boundary and output protection."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from nouc_studio.memory.models import FailureStage
from nouc_studio.memory.store import AdaptiveMemoryStore

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = runpy.run_path(str(ROOT / "examples" / "ui_contract.py"))


def proposal_payload(metric_id: str = "synthetic_revenue") -> dict[str, object]:
    return {
        "schema_version": "nouc-ui-proposal/1",
        "cards": [{"component": "metric_card", "metric_id": metric_id}],
    }


@pytest.mark.parametrize("field", ["value", "unit", "trust_grade", "caveats", "html", "sql"])
def test_proposer_cannot_supply_evidence_or_executable_content(field: str) -> None:
    payload = {
        "schema_version": "nouc-ui-proposal/1",
        "cards": [{"component": "metric_card", "metric_id": "synthetic_revenue", field: "override"}],
    }
    with pytest.raises(ValidationError):
        CONTRACT["ViewProposal"].model_validate(payload)


def test_unknown_component_and_version_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CONTRACT["ViewProposal"].model_validate({
            "schema_version": "nouc-ui-proposal/1",
            "cards": [{"component": "arbitrary_html", "metric_id": "synthetic_revenue"}],
        })
    with pytest.raises(ValidationError):
        CONTRACT["ViewProposal"].model_validate({**proposal_payload(), "schema_version": "future"})


def test_selected_metric_retains_backend_value_and_missing_evidence_warning() -> None:
    trace = CONTRACT["synthetic_trace"]()
    proposal = CONTRACT["ViewProposal"].model_validate(proposal_payload())
    cards = CONTRACT["resolve_cards"](proposal, [trace])
    assert cards[0]["value"] == 691900.0
    assert cards[0]["unit"] == "USD"
    assert cards[0]["trust_grade"] == "F"
    assert cards[0]["heuristic_range"] is None
    assert "Uncertainty is unknown" in cards[0]["caveats"][0]
    assert cards[0]["source_count"] == cards[0]["validation_count"] == 0
    assert cards[0]["trace_metric_id"] == trace.metric_node.node_id


def test_unknown_or_ambiguous_metric_does_not_fall_back_to_another_value() -> None:
    trace = CONTRACT["synthetic_trace"]()
    proposal = CONTRACT["ViewProposal"].model_validate(proposal_payload("missing"))
    with pytest.raises(ValueError, match="Unknown metric"):
        CONTRACT["resolve_cards"](proposal, [trace])
    proposal = CONTRACT["ViewProposal"].model_validate(proposal_payload())
    with pytest.raises(ValueError, match="Ambiguous backend"):
        CONTRACT["resolve_cards"](proposal, [trace, trace])
    proposal.cards.append(proposal.cards[0])
    with pytest.raises(ValueError, match="Duplicate metric"):
        CONTRACT["resolve_cards"](proposal, [trace])


def test_walkthrough_refuses_existing_directory_without_modifying_it(tmp_path: Path) -> None:
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("existing material", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "offline_walkthrough.py"), "--output", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode != 0
    assert "Output already exists" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "existing material"
    assert list(tmp_path.iterdir()) == [sentinel]


def test_sdist_example_paths_match_the_reviewed_allowlist() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    example_paths = {path.removeprefix("/") for path in included if path.startswith("/examples/")}
    release = runpy.run_path(str(ROOT / "scripts" / "release.py"))
    assert example_paths == release["SDIST_EXAMPLE_FILES"]
    assert all((ROOT / path).is_file() for path in example_paths)
    assert not any("user_inputs" in path or "private" in path for path in example_paths)


def test_walkthrough_excludes_callers_memory_and_dotenv(tmp_path: Path) -> None:
    canary = "SYNTHETIC_PRIVATE_MEMORY_CANARY_FOR_TEST_ONLY"
    local = tmp_path / "caller-local"
    global_dir = tmp_path / "caller-global"
    memory = AdaptiveMemoryStore(local, global_dir)
    memory.record_failure_and_fix(
        stage=FailureStage.RUNTIME_EXECUTION,
        library="synthetic-test",
        error_type="SyntheticError",
        error_message=canary,
        root_cause="Synthetic privacy regression fixture",
        verified_fix_description="Synthetic test record",
        prevention_rule=canary,
    )
    # Loading this .env would fail config validation. The walkthrough must ignore it.
    (tmp_path / ".env").write_text("INSIGHTS_PACKAGE_MANAGER=invalid-test-value\n", encoding="utf-8")
    output = tmp_path / "result"
    env = {
        **os.environ,
        "INSIGHTS_LOCAL_MEMORY_DIR": str(local),
        "INSIGHTS_GLOBAL_MEMORY_DIR": str(global_dir),
        "INSIGHTS_DEFAULT_LLM_MODEL": "invalid-test-model",
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "offline_walkthrough.py"), "--output", str(output)],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert canary not in (output / "adaptive_memory_snapshot.json").read_text(encoding="utf-8")
    assert canary not in (output / "orchestration_report.json").read_text(encoding="utf-8")
    assert canary not in result.stdout
    assert any(episode.error_message == canary for episode in memory.list_episodes())
