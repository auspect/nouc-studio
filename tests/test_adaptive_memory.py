"""Unit tests for the Dual-Tier (Local + Global Cross-Project) Adaptive Failure/Fix Memory Store."""

from pathlib import Path

from nouc_studio.config import _default_global_memory_dir
from nouc_studio.memory import AdaptiveMemoryStore, FailureStage


def test_new_installation_uses_nouc_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert _default_global_memory_dir() == tmp_path / ".nouc-studio" / "memory"


def test_rename_preserves_existing_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    legacy = tmp_path / ".prism-studio" / "memory"
    legacy.mkdir(parents=True)
    assert _default_global_memory_dir() == legacy
    current = tmp_path / ".nouc-studio" / "memory"
    current.mkdir(parents=True)
    assert _default_global_memory_dir() == current


def test_adaptive_memory_local_and_global_promotion(tmp_path: Path) -> None:
    local_dir_a = tmp_path / "project_a" / ".insights" / "memory"
    local_dir_b = tmp_path / "project_b" / ".insights" / "memory"
    global_dir = tmp_path / "global_memory"

    store_a = AdaptiveMemoryStore(local_dir=local_dir_a, global_dir=global_dir, project_name="project_a")

    # Seed episodes should be present automatically
    initial_episodes = store_a.list_episodes(include_global=True)
    assert len(initial_episodes) >= 5

    # Record a new project-specific failure and fix in Project A
    ep = store_a.record_failure_and_fix(
        stage=FailureStage.MARIMO_DAG,
        library="marimo",
        error_type="CycleError",
        error_message="Cell 'calc_a' and cell 'calc_b' form a dependency cycle at line 42.",
        failing_code_snippet="def calc_a(b): return b + 1\ndef calc_b(a): return a + 1",
        root_cause="Mutual dependency between two reactive cells.",
        verified_fix_description="Merged coupled state transition into a single cell and exposed read-only projections.",
        fixed_code_snippet="def calc_ab(): a = 1; b = a + 1; return a, b",
        prevention_rule="Never create mutual dependencies (A -> B -> A) across Marimo @app.cell functions.",
        verified=True,
        promote_to_global=True,
    )
    assert ep.hit_count == 1

    # Recording the same error pattern at a different line increments hit_count
    ep2 = store_a.record_failure_and_fix(
        stage=FailureStage.MARIMO_DAG,
        library="marimo",
        error_type="CycleError",
        error_message="Cell 'calc_a' and cell 'calc_b' form a dependency cycle at line 198.",
        root_cause="Mutual dependency between two reactive cells.",
        verified_fix_description="Merged coupled state transition into a single cell.",
        prevention_rule="Never create mutual dependencies (A -> B -> A) across Marimo @app.cell functions.",
        verified=True,
        promote_to_global=True,
    )
    assert ep2.episode_id == ep.episode_id
    assert ep2.hit_count == 2

    # Project B initializes against the same Global Memory and immediately inherits Project A's fix!
    store_b = AdaptiveMemoryStore(local_dir=local_dir_b, global_dir=global_dir, project_name="project_b")
    matches = store_b.find_similar_failures("CycleError: dependency cycle between cells", library="marimo")
    assert any(m.episode_id == ep.episode_id for m in matches)

    rules = store_b.get_prevention_rules_for_prompt(libraries=["marimo"])
    assert any("mutual dependencies" in r for r in rules)
    assert (local_dir_b / "memory_graph.json").exists()
