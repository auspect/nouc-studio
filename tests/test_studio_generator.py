"""Rendering regressions for generated notebooks and their Studio projections."""

import importlib.util
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import polars as pl
import pytest

from nouc_studio.studio.generator import (
    _generate_notebook_source,
    _render_studio_view_html,
    render_studio_runtime_support,
)


class _CalloutParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.contents: list[str] = []
        self.tab_labels: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "marimo-callout-output":
            payload = dict(attrs).get("data-html")
            if payload is not None:
                self.contents.append(json.loads(payload))
        elif tag == "marimo-tabs":
            payload = dict(attrs).get("data-tabs")
            if payload is not None:
                self.tab_labels.extend(json.loads(payload))


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.append(dict(attrs))


@pytest.fixture
def rendered_notebook(tmp_path: Path) -> dict[str, Any]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Sorting by filename must not put source-code metadata or textual protocols first.
    pl.DataFrame({"line_start": [1, 2], "line_end": [10, 20], "arguments": [2, 3]}).write_parquet(
        data_dir / "codebase_ast_symbols.parquet"
    )
    pl.DataFrame({"assay": ["A", "B"], "threshold": ["0.5", "1.0"]}).write_parquet(
        data_dir / "a_protocol.parquet"
    )
    pl.DataFrame({"region": ["France", "UK"], "revenue_usd": [125000.0, 84000.0]}).write_parquet(
        data_dir / "z_business_revenue.parquet"
    )
    source = {
        "label": "revenue <forecast>.xlsx",
        "description": "Sales <target> & reconciliation.",
        "coordinates": {"file_path": "evidence/revenue.xlsx", "file_hash_sha256": "a" * 64},
    }
    trace = {
        "metric_node": {
            "node_id": "metric_revenue",
            "label": "Revenue <forecast>",
            "value_preview": 209000.0,
            "unit": "USD",
        },
        "propagated_uncertainty": {
            "trust_grade": "B",
            "confidence_interval_95": [200000.0, 218000.0],
            "assumptions": ["Rates < 2% & region_name is stable.", "No duplicate invoices."],
            "caveats": ["One reconciliation is pending."],
        },
        "upstream_sources": [source, {**source, "label": "invoices.csv"}],
        "transformations": [{"formula_latex": "R = \\sum_i r_i\n\\quad r_i > 0"}],
        "validations": [{"label": "Amounts <limit>"}, {"label": "Positive revenue"}],
        "ordered_steps": [],
    }
    artifacts = {
        "lineage": {"nodes": [], "edges": []},
        "traces": [trace],
        "memory": {"episodes": [], "prevention_rules": ["Check inputs.", "Keep source hashes."]},
    }
    for name, payload in artifacts.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    notebook_path = tmp_path / "app.py"
    notebook_path.write_text(
        _generate_notebook_source(
            app_title="Sales <forecast> & risk",
            user_need="Compare revenue < 250000 & explain assumptions.",
            notebook_path=notebook_path,
            data_dir=data_dir,
            lineage_json_path=tmp_path / "lineage.json",
            traces_json_path=tmp_path / "traces.json",
            memory_rules_path=tmp_path / "memory.json",
        ),
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("_test_generated_studio", notebook_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, definitions = module.app.run()
    return dict(definitions)


def test_multiline_proofs_render_as_markdown(rendered_notebook: dict[str, Any]) -> None:
    parser = _CalloutParser()
    parser.feed(rendered_notebook["lineage_panel"].text)
    assert len(parser.contents) == 4
    for content in parser.contents:
        assert "<h4" in content, content
        assert "<pre" not in content, content
    assert "<marimo-tex" in parser.contents[0]
    assert "Revenue &lt;forecast&gt;" in parser.contents[0]
    assert "<forecast>" not in parser.contents[0]
    assert "invoices.csv" in parser.contents[1]
    assert "revenue &lt;forecast&gt;.xlsx" in parser.contents[1]
    assert "Sales &lt;target&gt; &amp; reconciliation." in parser.contents[1]
    assert "Amounts &lt;limit&gt;" in parser.contents[2]
    assert "Positive revenue" in parser.contents[2]
    assert "No duplicate invoices." in parser.contents[3]
    assert "Rates &lt; 2% &amp; region_name is stable." in parser.contents[3]


def test_business_data_is_selected_for_exploration_and_sql(
    rendered_notebook: dict[str, Any],
) -> None:
    assert rendered_notebook["selected_dataset_dropdown"].value == "z_business_revenue"
    assert "FROM z_business_revenue" in rendered_notebook["query_input"].value
    assert "Visual Cohort Comparison" in rendered_notebook["simulation_view"].text


def test_interpolated_titles_and_labels_remain_text(rendered_notebook: dict[str, Any]) -> None:
    assert "Sales &lt;forecast&gt; &amp; risk" in rendered_notebook["header_block"].text
    assert "Revenue &lt;forecast&gt;" in rendered_notebook["kpi_section"].text
    assert "<forecast>" not in rendered_notebook["header_block"].text


def test_notebook_tab_labels_render_as_text(rendered_notebook: dict[str, Any]) -> None:
    parser = _CalloutParser()
    parser.feed(rendered_notebook["studio_tabs"].text)
    assert len(parser.tab_labels) == 5
    assert "Executive Studio" in parser.tab_labels[0]
    assert all("<ol" not in label for label in parser.tab_labels)


def test_scenario_header_has_one_native_slider_and_no_phantom_widget(
    rendered_notebook: dict[str, Any],
) -> None:
    header = rendered_notebook["header_block"].text
    assert header.count("<marimo-slider") == 1
    assert "anywidget" not in header.lower()
    assert "tangle_shock" not in rendered_notebook
    assert "TangleSlider" not in rendered_notebook
    assert "Drag the slider" in header
    assert "Drag either slider" not in header


def test_uncertainty_ranges_use_honest_labels_without_changing_saved_bounds(
    rendered_notebook: dict[str, Any],
) -> None:
    parser = _CalloutParser()
    parser.feed(rendered_notebook["lineage_panel"].text)
    assert "Heuristic uncertainty range" in parser.contents[0]
    assert "200,000.00" in parser.contents[0]
    assert "218,000.00" in parser.contents[0]
    assert "95%" not in parser.contents[0]
    assert "Heuristic range" in rendered_notebook["kpi_summary_df"].columns
    assert "95%" not in rendered_notebook["kpi_section"].text
    assert rendered_notebook["traces_payload"][0]["propagated_uncertainty"][
        "confidence_interval_95"
    ] == [200000.0, 218000.0]


def test_studio_shell_escapes_text_and_has_no_blanket_verification_badge() -> None:
    html = _render_studio_view_html(
        app_title='Sales <forecast> & "risk"',
        view_title="Business overview",
        view_subtitle="Compare sales < target",
        cell_sections=[("kpi_cards", "Revenue & risk", 'Source "reconciliation"')],
        nav_views=[
            ("main", "Overview & scenarios", "lucide:layout-dashboard"),
            ("audit", "Proofs", "lucide:git-branch"),
        ],
        active_view="main",
    )
    assert "Sales &lt;forecast&gt; &amp; &quot;risk&quot;" in html
    assert 'data-marimo-lens-detail="Source &quot;reconciliation&quot;"' in html
    assert "Verified Reactive View" not in html
    assert '<marimo-cell name="kpi_cards">' in html


@pytest.mark.parametrize("public_root", ["http://localhost:2721/", "http://host/apps/revenue/"])
def test_navigation_uses_native_studio_sibling_routes(public_root: str) -> None:
    views = [("main", "Overview", ""), ("audit", "Proofs", ""), ("ops", "Explorer", "")]
    for current_view, _, _ in views:
        html = _render_studio_view_html(
            app_title="Revenue Studio",
            view_title="Overview",
            view_subtitle="",
            cell_sections=[],
            nav_views=views,
            active_view=current_view,
        )
        parser = _LinkParser()
        parser.feed(html)
        assert len(parser.links) == len(views)
        # The native click handler accepts only self-targeted links to known view paths.
        # This also preserves the server mount prefix instead of loading another shell.
        for link, (destination, _, _) in zip(parser.links, views, strict=True):
            assert link.get("target") in (None, "_self")
            assert link["href"] is not None
            assert urljoin(urljoin(public_root, f"{current_view}/"), link["href"]) == urljoin(
                public_root, f"{destination}/"
            )


def test_embedded_navigation_sends_current_identity_instead_of_loading_nested_shell() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute the generated navigation bridge.")
    html = _render_studio_view_html(
        app_title="Revenue Studio",
        view_title="Overview",
        view_subtitle="",
        cell_sections=[],
        nav_views=[("main", "Overview", ""), ("ops", "Explorer", "")],
        active_view="main",
    )
    match = re.search(r'<script id="nouc-studio-navigation">(.*?)</script>', html, re.DOTALL)
    assert match is not None
    harness = """
import assert from 'node:assert/strict';
const messages = [];
const handlers = {};
const link = { target: '', dataset: { studioView: 'ops' } };
globalThis.Element = class { closest() { return link; } };
globalThis.window = globalThis;
globalThis.parent = { postMessage(message, origin) { messages.push({ message, origin }); } };
globalThis.location = { search: '?region=FR&session_id=s_test01', hash: '#query' };
globalThis.__MARIMO_MOUNT_CONFIG__ = { runtime: 'server', supportUrl: '/_marimo-studio/views/main' };
globalThis.addEventListener = (type, callback) => { handlers[type] = callback; };
globalThis.document = {
  baseURI: 'http://localhost:2721/_marimo-studio/artifacts/current/',
  addEventListener(type, callback) { handlers[type] = callback; }
};
let prevented = 0;
const click = () => ({
  target: new Element(), button: 0,
  preventDefault() { prevented += 1; }
});
"""
    assertions = """
handlers.click(click());
assert.equal(prevented, 1);
assert.deepEqual(messages[0], {
  origin: 'http://localhost:2721',
  message: {
    type: 'marimo-studio:navigate-view', runtime: 'server', lifecycleId: 1,
    view: 'ops', query: '?region=FR&session_id=s_test01', hash: '#query'
  }
});
handlers.message({
  source: parent, origin: 'http://localhost:2721',
  data: { type: 'marimo-studio:switch-view', runtime: 'server', lifecycleId: 7 }
});
handlers.click(click());
assert.equal(messages[1].message.lifecycleId, 7);
handlers.message({
  source: {}, origin: 'http://localhost:2721',
  data: { type: 'marimo-studio:switch-view', runtime: 'server', lifecycleId: 99 }
});
handlers.click(click());
assert.equal(messages[2].message.lifecycleId, 7);
handlers.click({ ...click(), ctrlKey: true });
assert.equal(messages.length, 3);
assert.equal(prevented, 3);
"""
    completed = subprocess.run(
        [node, "--input-type=module"],
        input=harness + match[1] + assertions,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


def test_public_runtime_support_is_reused_once_in_the_generic_shell_head() -> None:
    support = render_studio_runtime_support()
    html = _render_studio_view_html(
        app_title="Widget probe", view_title="Overview", view_subtitle="",
        cell_sections=[], nav_views=[], active_view="overview",
    )
    assert support.count("<script") == support.count("</script>") == 1
    assert 'id="nouc-studio-virtual-files"' in support
    assert "nouc-studio-navigation" not in support
    assert html.count(support) == 1
    assert support in html.split("</head>", maxsplit=1)[0]


@pytest.mark.parametrize("mount_prefix", ["", "/apps/revenue"])
def test_virtual_file_fetch_uses_own_runtime_and_preserves_request_semantics(
    mount_prefix: str,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute the generated virtual-file bridge.")
    html = _render_studio_view_html(
        app_title="Widget probe", view_title="Overview", view_subtitle="",
        cell_sections=[], nav_views=[], active_view="overview",
    )
    match = re.search(r'<script id="nouc-studio-virtual-files">(.*?)</script>', html, re.DOTALL)
    assert match is not None
    assert html.index('id="nouc-studio-virtual-files"') < html.index("</head>")
    capability = f"http://localhost:2725{mount_prefix}/_marimo-studio/presentation/r.opaque.signature"
    base = capability + "/overview/_marimo-studio/artifacts/revision123/"
    harness = f"""
import assert from 'node:assert/strict';
const base = {json.dumps(base)};
const capability = {json.dumps(capability)};
const calls = [];
const result = {{ status: 200 }};
globalThis.window = globalThis;
globalThis.document = {{ baseURI: base }};
globalThis.fetch = function(input, init) {{
  assert.equal(this, window);
  calls.push({{ input, init }});
  return result;
}};
"""
    assertions = r"""
const init = { cache: 'no-store' };
assert.equal(fetch('./@file/42-editor.csv?session_id=s_probe&v=a%2Fb#part', init), result);
assert.equal(calls.at(-1).input, capability + '/@file/42-editor.csv?session_id=s_probe&v=a%2Fb#part');
assert.equal(calls.at(-1).init, init);
const url = new URL('./@file/data.arrow?format=arrow', base);
const originalUrl = url.href;
fetch(url);
assert.equal(calls.at(-1).input, capability + '/@file/data.arrow?format=arrow');
assert.equal(url.href, originalUrl);
const controller = new AbortController();
const request = new Request(base + '@file/data.csv?session_id=s_probe', {
  method: 'POST', body: 'original body', headers: { 'X-Probe': 'kept' },
  credentials: 'include', mode: 'same-origin', redirect: 'error', signal: controller.signal
});
const requestInit = { cache: 'reload', headers: { 'X-Override': 'forwarded' } };
fetch(request, requestInit);
const forwarded = calls.at(-1);
assert.ok(forwarded.input instanceof Request);
assert.equal(forwarded.input.url, capability + '/@file/data.csv?session_id=s_probe');
assert.equal(forwarded.input.method, 'POST');
assert.equal(forwarded.input.headers.get('X-Probe'), 'kept');
assert.equal(await forwarded.input.text(), 'original body');
assert.equal(forwarded.input.credentials, 'include');
assert.equal(forwarded.input.mode, 'same-origin');
assert.equal(forwarded.input.redirect, 'error');
assert.equal(forwarded.init, requestInit);
controller.abort();
assert.equal(forwarded.input.signal.aborted, true);
const untouched = [
  capability + '/@file/already-correct.csv?session_id=s_probe',
  base.replace('r.opaque.signature', 'r.other.signature') + '@file/other-cap.csv',
  base.replace('/overview/', '/audit/') + '@file/other-view.csv',
  base.replace('/revision123/', '/other-revision/') + '@file/other-artifact.csv',
  base + 'subdirectory/@file/not-the-current-directory.csv',
  base.replace('http://localhost:2725', 'https://external.example') + '@file/external.csv',
  base.replace('http://localhost:2725', 'http://user:password@localhost:2725') + '@file/credentials.csv',
  base + 'table.csv?path=/@file/only-in-the-query',
  './@file/', './@files/similar.csv', './api/set-ui-element-value',
  new Request(base.replace('r.opaque.signature', 'r.other.signature') + '@file/request.csv'),
  new URL(base.replace('http://localhost:2725', 'http://localhost:2726') + '@file/other-port.csv')
];
for (const input of untouched) {
  fetch(input, init);
  assert.equal(calls.at(-1).input, input);
  assert.equal(calls.at(-1).init, init);
}
"""
    completed = subprocess.run(
        [node, "--input-type=module"], input=harness + match[1] + assertions,
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "base",
    [
        "http://localhost:2725/overview/",
        "http://localhost:2725/_marimo-studio/artifacts/revision123/",
        "http://localhost:2725/_marimo-studio/presentation/r.signature/overview/",
    ],
)
def test_virtual_file_bridge_does_not_patch_fetch_outside_a_signed_artifact(base: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute the generated virtual-file bridge.")
    html = _render_studio_view_html(
        app_title="Widget probe", view_title="Overview", view_subtitle="",
        cell_sections=[], nav_views=[], active_view="overview",
    )
    match = re.search(r'<script id="nouc-studio-virtual-files">(.*?)</script>', html, re.DOTALL)
    assert match is not None
    harness = f"""
import assert from 'node:assert/strict';
globalThis.window = globalThis;
globalThis.document = {{ baseURI: {json.dumps(base)} }};
const originalFetch = () => {{}};
globalThis.fetch = originalFetch;
"""
    completed = subprocess.run(
        [node, "--input-type=module"],
        input=harness + match[1] + "\nassert.equal(fetch, originalFetch);",
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
