"""Exercise generated desktop navigation against its actual HTML and JavaScript."""

from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from typing import Any

import pytest

from nouc_studio.studio.generator import render_studio_view_html


class _ShellParser(HTMLParser):
    """Keep the real control/panel tree and inline script without a DOM dependency."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict[str, Any] = {
            "tag": "document", "attrs": {}, "children": [], "text": ""
        }
        self._stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node: dict[str, Any] = {
            "tag": tag,
            "attrs": {key: value or "" for key, value in attrs},
            "children": [],
            "text": "",
        }
        self._stack[-1]["children"].append(node)
        if tag not in {"meta", "link", "img", "input", "br", "hr", "source", "wbr"}:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self._stack[-1]["text"] += data

    def nodes(self, tag: str | None = None) -> list[dict[str, Any]]:
        def visit(node: dict[str, Any]) -> list[dict[str, Any]]:
            found = [node] if tag is None or node["tag"] == tag else []
            for child in node["children"]:
                found.extend(visit(child))
            return found

        return visit(self.root)

    @property
    def script(self) -> str:
        return next(
            node["text"]
            for node in self.nodes("script")
            if node["attrs"].get("id") == "nouc-studio-sections"
        )


def _shell(section_count: int) -> _ShellParser:
    names = ["valid", "unreachable", "invalid"]
    sections = [
        (names[index] if index < len(names) else f"detail_{index}", f"Panel {index}", "Details")
        for index in range(section_count)
    ]
    return _ShellParser(
        render_studio_view_html(
            app_title="Ticket triage",
            view_title="Desktop workspace",
            view_subtitle="Inspect records without losing context.",
            cell_sections=sections,
            nav_views=[("main", "Workspace", "lucide:table")],
            active_view="main",
        )
    )


@pytest.mark.parametrize("count", [0, 1, 3, 6])
def test_no_javascript_keeps_every_projection_present_and_visible(count: int) -> None:
    shell = _shell(count)
    panels = shell.nodes("section")
    cells = shell.nodes("marimo-cell")
    assert len(panels) == len(cells) == count
    assert len({panel["attrs"]["id"] for panel in panels}) == count
    assert all("hidden" not in panel["attrs"] for panel in panels)
    assert all("hidden" not in cell["attrs"] for cell in cells)
    assert all("style" not in panel["attrs"] for panel in panels)
    assert "studio-tabs-ready" not in shell.nodes("body")[0]["attrs"].get("class", "")
    for panel, cell in zip(panels, cells, strict=True):
        assert cell in panel["children"]
        assert cell["attrs"]["name"]


def test_each_tab_controls_its_rendered_projection_and_accessible_panel() -> None:
    shell = _shell(3)
    tabs = [node for node in shell.nodes("button") if node["attrs"].get("role") == "tab"]
    panels = shell.nodes("section")
    assert len(tabs) == len(panels) == 3
    assert len([n for n in shell.nodes() if n["attrs"].get("role") == "tablist"]) == 1
    for tab, panel in zip(tabs, panels, strict=True):
        assert tab["attrs"]["aria-controls"] == panel["attrs"]["id"]
        assert panel["attrs"]["aria-labelledby"] == tab["attrs"]["id"]
        assert panel["attrs"]["role"] == "tabpanel"


@pytest.mark.parametrize("count", [1, 6])
def test_single_panel_and_menu_have_regions_without_orphaned_tab_roles(count: int) -> None:
    shell = _shell(count)
    assert not [node for node in shell.nodes() if node["attrs"].get("role") == "tab"]
    assert all(panel["attrs"]["role"] == "region" for panel in shell.nodes("section"))
    assert all(panel["attrs"]["aria-label"] for panel in shell.nodes("section"))
    if count == 6:
        menu = shell.nodes("select")
        assert len(menu) == 1
        assert shell.nodes("label")[0]["attrs"]["for"] == menu[0]["attrs"]["id"]
        assert [node["attrs"]["value"] for node in shell.nodes("option")] == [
            str(index) for index in range(count)
        ]
    else:
        assert not shell.nodes("select")


@pytest.fixture
def node_path() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to execute the generated browser script")
    return node


_DOM_HARNESS = r"""
import assert from 'node:assert/strict';
class DomNode {
  constructor(raw, parent = null) {
    this.tagName = raw.tag;
    this.attributes = {...raw.attrs};
    this.textContent = raw.text;
    this.parentElement = parent;
    this.listeners = new Map();
    this.children = raw.children.map(child => new DomNode(child, this));
    this.value = this.tagName === 'select' ? this.children[0]?.attributes.value ?? '' : '';
    const classes = new Set((this.attributes.class ?? '').split(/\s+/).filter(Boolean));
    this.classList = {add: name => classes.add(name), contains: name => classes.has(name)};
  }
  get hidden() { return Object.hasOwn(this.attributes, 'hidden'); }
  set hidden(value) {
    if (value) this.attributes.hidden = ''; else delete this.attributes.hidden;
  }
  get tabIndex() { return Number(this.attributes.tabindex ?? -1); }
  set tabIndex(value) { this.attributes.tabindex = String(value); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(type, handler) {
    this.listeners.set(type, [...this.listeners.get(type) ?? [], handler]);
  }
  fire(type, event = {}) {
    for (const handler of this.listeners.get(type) ?? []) handler(event);
  }
  focus() {
    for (let current = this; current; current = current.parentElement) {
      assert.equal(current.hidden, false, 'focus must not enter a hidden panel');
    }
    document.activeElement = this;
  }
  click() { this.focus(); this.fire('click'); }
}
const root = new DomNode(serialized);
const walk = node => [node, ...node.children.flatMap(walk)];
const matches = (node, selector) => {
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  if (selector.startsWith('#')) return node.attributes.id === selector.slice(1);
  if (selector.startsWith('[')) return Object.hasOwn(node.attributes, selector.slice(1, -1));
  return node.tagName === selector;
};
globalThis.document = {
  activeElement: null,
  querySelectorAll: selector => walk(root).filter(node => matches(node, selector)),
  querySelector: selector => walk(root).find(node => matches(node, selector)) ?? null,
  body: walk(root).find(node => node.tagName === 'body'),
};
const resizeEvents = [];
globalThis.window = {
  requestAnimationFrame: callback => { callback(); return 1; },
  dispatchEvent: event => { resizeEvents.push(event.type); return true; },
};
const originalCells = document.querySelectorAll('marimo-cell');
// These existing projection identities stand for healthy and problematic data alike.
const originalNames = originalCells.map(cell => cell.getAttribute('name'));
const panels = document.querySelectorAll('.studio-section-container');
const tabs = document.querySelectorAll('[data-section-index]');
const menu = document.querySelector('#studio-section-choice');
const checkCellsPreserved = () => {
  const currentCells = document.querySelectorAll('marimo-cell');
  assert.equal(currentCells.length, originalCells.length);
  currentCells.forEach((cell, index) => assert.equal(cell, originalCells[index]));
  assert.deepEqual(originalCells.map(cell => cell.getAttribute('name')), originalNames);
};
const checkSelected = index => {
  assert.deepEqual(panels.map(panel => panel.hidden), panels.map((_, i) => i !== index));
  tabs.forEach((tab, i) => {
    assert.equal(tab.getAttribute('aria-selected'), String(i === index));
    assert.equal(tab.tabIndex, i === index ? 0 : -1);
  });
  checkCellsPreserved();
};
"""


def _run_script(node: str, shell: _ShellParser, assertions: str) -> None:
    completed = subprocess.run(
        [node, "--input-type=module"],
        input=(
            f"const serialized = {json.dumps(shell.root)};\n"
            + _DOM_HARNESS
            + shell.script
            + assertions
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_generated_tabs_switch_click_keyboard_focus_and_keep_all_cells(node_path: str) -> None:
    _run_script(
        node_path,
        _shell(3),
        r"""
assert.equal(document.body.classList.contains('studio-tabs-ready'), true);
checkSelected(0);
assert.deepEqual(originalNames, ['valid', 'unreachable', 'invalid']);
tabs.forEach((tab, index) => { tab.click(); checkSelected(index); });
const press = (key, expected, handled = true) => {
  let prevented = false;
  document.activeElement.fire('keydown', {key, preventDefault: () => { prevented = true; }});
  assert.equal(prevented, handled);
  checkSelected(expected);
  assert.equal(document.activeElement, tabs[expected]);
};
press('ArrowRight', 0);
press('ArrowLeft', 2);
press('Home', 0);
press('End', 2);
press('Escape', 2, false);
tabs[1].click();
checkSelected(1);
assert.equal(document.activeElement, tabs[1]);
assert.ok(resizeEvents.length >= 8, 'widgets need a resize after each accepted switch');
assert.ok(resizeEvents.every(type => type === 'resize'));
""",
    )


def test_generated_menu_reaches_every_region_and_rejects_invalid_indices(node_path: str) -> None:
    _run_script(
        node_path,
        _shell(6),
        r"""
assert.equal(tabs.length, 0);
assert.ok(menu);
checkSelected(0);
for (let index = 0; index < panels.length; index++) {
  menu.value = String(index);
  menu.fire('change');
  checkSelected(index);
  assert.equal(menu.value, String(index));
}
const resizeCount = resizeEvents.length;
for (const value of ['invalid', '-1', '6', '1.5', 'NaN', 'Infinity']) {
  menu.value = value;
  menu.fire('change');
  checkSelected(5);
}
assert.equal(resizeEvents.length, resizeCount, 'invalid targets must not trigger a switch');
""",
    )


@pytest.mark.parametrize("count", [0, 1])
def test_script_handles_empty_or_single_region_without_inaccessible_controls(
    node_path: str, count: int
) -> None:
    _run_script(
        node_path,
        _shell(count),
        """
assert.equal(tabs.length, 0);
assert.equal(menu, null);
if (panels.length) {
  checkSelected(0);
  assert.equal(document.body.classList.contains('studio-tabs-ready'), true);
} else {
  assert.equal(document.body.classList.contains('studio-tabs-ready'), false);
}
checkCellsPreserved();
""",
    )
