"""Multi-View Marimo Studio Application & Reactive Notebook Generator."""

from __future__ import annotations

import asyncio
import json
import os
from html import escape
from pathlib import Path
from typing import Any

from marimo_studio.authoring import open_workspace
from pydantic import BaseModel, Field

from nouc_studio.graph.engine import LineageGraphEngine
from nouc_studio.graph.models import MetricLineageTrace
from nouc_studio.ingestion.pipeline import IngestionManifest

_STUDIO_VIRTUAL_FILE_BRIDGE = r"""
    <script id="nouc-studio-virtual-files">
      (() => {
        if (typeof window.fetch !== "function") return;
        const base = new URL(document.baseURI);
        // The artifact base and the native runtime share this signed capability.
        // Only ./@file requests below this exact artifact directory need repair.
        const route = base.pathname.match(
          /^(.*\/_marimo-studio\/presentation\/[^/]+)\/[^/]+\/_marimo-studio\/artifacts\/[^/]+\/$/
        );
        if (!route || !["http:", "https:"].includes(base.protocol) ||
            base.username || base.password) return;
        const filePrefix = base.pathname + "@file/";
        const originalFetch = window.fetch.bind(window);
        window.fetch = (input, init) => {
          const isRequest = input instanceof Request;
          let url;
          try {
            url = new URL(isRequest ? input.url : String(input), base);
          } catch {
            return originalFetch(input, init);
          }
          if (url.origin !== base.origin || url.username || url.password ||
              !url.pathname.startsWith(filePrefix) ||
              url.pathname.length === filePrefix.length) {
            return originalFetch(input, init);
          }
          url.pathname = route[1] + "/@file/" + url.pathname.slice(filePrefix.length);
          return originalFetch(isRequest ? new Request(url, input) : url.href, init);
        };
      })();
    </script>
"""


def render_studio_runtime_support() -> str:
    """Return a head script for native virtual-file fetches in signed Studio views.

    Custom HTML shells can include this support without adopting the generic
    layout. It rewrites only this artifact's same-origin ``./@file/`` fetches to
    its signed runtime capability; other requests and navigation are unchanged.
    """
    return _STUDIO_VIRTUAL_FILE_BRIDGE


class StudioViewSummary(BaseModel):
    """Build and validation metadata for a generated marimo-studio view."""

    view_name: str
    root_dir: str
    build_revision: str
    validation_passed: bool
    diagnostics: list[str] = Field(default_factory=list)


class GeneratedStudioBundle(BaseModel):
    """Complete output of the StudioApplicationGenerator."""

    output_dir: str
    notebook_path: str
    lineage_json_path: str
    traces_json_path: str
    views: list[StudioViewSummary] = Field(default_factory=list)
    launch_edit_command: str
    launch_run_command: str


def render_studio_view_html(
    *,
    app_title: str,
    view_title: str,
    view_subtitle: str,
    cell_sections: list[tuple[str, str, str]],
    nav_views: list[tuple[str, str, str]],
    active_view: str,
) -> str:
    """Render a compact desktop workspace with one task panel visible at a time."""
    app_title = escape(app_title)
    view_title = escape(view_title)
    view_subtitle = escape(view_subtitle)
    nav_links: list[str] = []
    for v_slug, v_label, v_icon in nav_views:
        is_active = v_slug == active_view
        cls = (
            "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold bg-indigo-600 text-white shadow-sm transition-all"
            if is_active
            else "inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 transition-all"
        )
        # Studio's native router recognizes sibling view URLs and intercepts self navigation.
        href = f"../{v_slug}/"
        nav_links.append(
            f'<a href="{href}" data-studio-view="{v_slug}" class="{cls}">'
            f'<iconify-icon inline icon="{v_icon}" aria-hidden="true"></iconify-icon>'
            f"<span>{escape(v_label)}</span></a>"
        )
    nav_html = "\n            ".join(nav_links)

    section_controls: list[str] = []
    sections_html: list[str] = []
    use_menu = len(cell_sections) > 5
    for index, (cell_name, section_label, section_desc) in enumerate(cell_sections):
        section_label = escape(section_label)
        section_desc = escape(section_desc)
        cell_attribute = escape(cell_name, quote=True)
        lens_source = escape(json.dumps({"path": "index.html", "symbol": cell_name}), quote=True)
        if use_menu:
            section_controls.append(f'<option value="{index}">{section_label}</option>')
        else:
            selected = "true" if index == 0 else "false"
            tab_index = "0" if index == 0 else "-1"
            section_controls.append(
                f'<button type="button" role="tab" id="studio-tab-{index}" '
                f'aria-controls="studio-panel-{index}" aria-selected="{selected}" '
                f'tabindex="{tab_index}" data-section-index="{index}">{section_label}</button>'
            )
        panel_label = (
            f'aria-label="{section_label}"' if use_menu or len(cell_sections) == 1
            else f'aria-labelledby="studio-tab-{index}"'
        )
        panel_role = "region" if use_menu or len(cell_sections) == 1 else "tabpanel"
        sections_html.append(
            f"""        <section
          id="studio-panel-{index}" role="{panel_role}" tabindex="0" {panel_label}
          class="studio-section-container"
          data-marimo-lens-label="{section_label}"
          data-marimo-lens-detail="{section_desc}"
          data-marimo-lens-render-source="{lens_source}"
        >
          <div class="studio-section-header">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900 m-0">{section_label}</h2>
              <p class="text-xs text-slate-500 m-0 mt-1">{section_desc}</p>
            </div>
          </div>
          <marimo-cell name="{cell_attribute}"></marimo-cell>
        </section>"""
        )

    joined_sections = "\n".join(sections_html)
    controls = "\n".join(section_controls)
    if len(cell_sections) <= 1:
        section_navigation = ""
    elif use_menu:
        section_navigation = (
            '<div class="studio-section-navigation"><label for="studio-section-choice">'
            f'{view_title}</label><select id="studio-section-choice">{controls}</select></div>'
        )
    else:
        section_navigation = (
            f'<div class="studio-section-navigation" role="tablist" '
            f'aria-label="{view_title}">{controls}</div>'
        )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{app_title} — {view_title}</title>
{render_studio_runtime_support()}
    <script
      src="https://cdn.jsdelivr.net/npm/@unocss/runtime@66.10.5/uno.global.js"
      integrity="sha384-iX+gEyr2u+Tmd8XxbySu2iimH7dOfTZn9xahADx38mJHYzAI2CJUCo5+PPGOSU2b"
      crossorigin="anonymous"
    ></script>
    <script
      defer
      src="https://cdn.jsdelivr.net/npm/iconify-icon@3.0.3/dist/iconify-icon.min.js"
      integrity="sha384-jypoV+nlFXLykSFUJkpVjPG/eid90inFxyvUI1corcUR778eMGexPBFzNC94eOc+"
      crossorigin="anonymous"
    ></script>
    <style>
      :root {{
        --studio-bg: #f1f5f9;
        --studio-surface: #ffffff;
        --studio-text: #0f172a;
        --studio-accent: #4f46e5;
      }}
      body {{
        margin: 0;
        min-height: 100dvh;
        background: radial-gradient(circle at 15% 0%, #eef2ff 0%, #f8fafc 45%, #f1f5f9 100%);
        color: var(--studio-text);
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      *, *::before, *::after {{ box-sizing: border-box; }}
      #app-shell, .studio-grid, .studio-section-container,
      .studio-section-header, .studio-section-header > *, marimo-cell {{
        min-width: 0;
        max-width: 100%;
      }}
      .studio-section-container {{
        padding: 1rem;
        overflow-wrap: anywhere;
      }}
      marimo-cell {{ display: block; }}
      marimo-cell pre {{ max-width: 100%; overflow-x: auto; }}
      marimo-cell code {{ overflow-wrap: anywhere; white-space: pre-wrap; }}
      marimo-cell img, marimo-cell svg {{ max-width: 100%; }}
      .studio-topbar {{
        position: sticky;
        top: 0;
        z-index: 30;
        backdrop-filter: blur(14px);
        background: rgba(255, 255, 255, 0.88);
        border-bottom: 1px solid rgba(226, 232, 240, 0.9);
      }}
      .studio-topbar > div, #app-shell {{
        width: 100%;
        max-width: 100rem;
        margin-inline: auto;
        padding: 1rem;
      }}
      .studio-topbar > div {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
      }}
      .studio-topbar > div > div {{ min-width: 0; overflow-wrap: anywhere; }}
      .studio-topbar nav {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
      .studio-topbar nav a {{ text-decoration: none; padding: 0.5rem 0.75rem; }}
      .studio-hero-title {{
        font-size: clamp(1.3rem, 1rem + 1.25vw, 1.9rem);
        line-height: 1.2;
      }}
      .studio-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: 0.75rem;
      }}
      .studio-section-container {{
        container-type: inline-size;
        background: var(--studio-surface);
        border: 1px solid #e2e8f0;
        border-radius: 1rem;
      }}
      .studio-section-header {{
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        padding-bottom: 0.5rem;
        margin-bottom: 0.75rem;
        border-bottom: 1px solid #e2e8f0;
        flex: 0 0 auto;
      }}
      .studio-section-navigation {{ display: none; }}
      .studio-tabs-ready {{
        height: 100dvh;
        min-height: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }}
      .studio-tabs-ready .studio-topbar {{ flex: 0 0 auto; }}
      .studio-tabs-ready #app-shell {{
        flex: 1 1 auto;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        padding-block: 0.75rem;
      }}
      .studio-tabs-ready .studio-section-navigation {{
        display: flex;
        align-items: center;
        flex: 0 0 auto;
        gap: 0.25rem;
        flex-wrap: wrap;
      }}
      .studio-section-navigation button, .studio-section-navigation select {{
        font: inherit;
        font-size: 0.875rem;
        color: #334155;
        border: 1px solid transparent;
        border-radius: 0.5rem;
        background: transparent;
        padding: 0.5rem 0.75rem;
        cursor: pointer;
      }}
      .studio-section-navigation button[aria-selected="true"] {{
        background: white;
        color: #4338ca;
        border-color: #c7d2fe;
        font-weight: 600;
      }}
      .studio-section-navigation select {{ background: white; border-color: #cbd5e1; max-width: 100%; }}
      .studio-section-navigation label {{ font-size: 0.875rem; padding-right: 0.5rem; }}
      .studio-section-navigation :focus-visible, .studio-section-container:focus-visible {{
        outline: 2px solid #4f46e5;
        outline-offset: 2px;
      }}
      .studio-tabs-ready .studio-grid {{ flex: 1 1 auto; min-height: 0; }}
      .studio-tabs-ready .studio-section-container {{
        min-height: 0;
        display: flex;
        flex-direction: column;
      }}
      .studio-section-container[hidden] {{ display: none !important; }}
      .studio-tabs-ready marimo-cell {{
        min-height: 0;
        flex: 1 1 auto;
        overflow: auto;
        overscroll-behavior: contain;
      }}
      @media (max-width: 639px) {{
        .studio-topbar {{ position: static; }}
      }}
      @media (min-width: 640px) {{
        .studio-section-header {{
          flex-direction: row;
          align-items: center;
          justify-content: space-between;
        }}
      }}
      @supports (container-type: inline-size) {{
        @media (min-width: 640px) {{
          .studio-section-header {{
            flex-direction: column;
          }}
        }}
        @container (min-width: 520px) {{
          .studio-section-header {{
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
          }}
        }}
      }}
    </style>
  </head>
  <body>
    <header class="studio-topbar">
      <div class="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <div>
          <div class="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-indigo-600">
            <iconify-icon inline icon="lucide:sparkles" aria-hidden="true"></iconify-icon>
            <span>{app_title}</span>
          </div>
          <h1 class="studio-hero-title font-extrabold tracking-tight text-slate-900 mt-0.5 mb-0.5">{view_title}</h1>
          <p class="text-xs sm:text-sm text-slate-600 m-0">{view_subtitle}</p>
        </div>
        <nav class="flex flex-wrap gap-2" aria-label="Studio views">
            {nav_html}
        </nav>
      </div>
    </header>
    <main id="app-shell" class="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {section_navigation}
      <div class="studio-grid">
{joined_sections}
      </div>
    </main>
    <script id="nouc-studio-sections">
      (() => {{
        const panels = [...document.querySelectorAll(".studio-section-container")];
        const tabs = [...document.querySelectorAll("[data-section-index]")];
        const menu = document.querySelector("#studio-section-choice");
        if (!panels.length) return;
        const select = (index, focus = false) => {{
          if (!Number.isInteger(index) || index < 0 || index >= panels.length) return;
          panels.forEach((panel, i) => {{ panel.hidden = i !== index; }});
          tabs.forEach((tab, i) => {{
            tab.setAttribute("aria-selected", String(i === index));
            tab.tabIndex = i === index ? 0 : -1;
          }});
          if (menu) menu.value = String(index);
          if (focus) tabs[index]?.focus();
          window.requestAnimationFrame?.(() => window.dispatchEvent(new Event("resize")));
        }};
        tabs.forEach((tab, index) => {{
          tab.addEventListener("click", () => select(index));
          tab.addEventListener("keydown", (event) => {{
            const next = {{
              ArrowRight: (index + 1) % panels.length,
              ArrowLeft: (index + panels.length - 1) % panels.length,
              Home: 0,
              End: panels.length - 1,
            }}[event.key];
            if (next === undefined) return;
            event.preventDefault();
            select(next, true);
          }});
        }});
        menu?.addEventListener("change", () => select(Number(menu.value)));
        select(0);
        document.body.classList.add("studio-tabs-ready");
      }})();
    </script>
    <script id="nouc-studio-navigation">
      (() => {{
        const mount = window.__MARIMO_MOUNT_CONFIG__;
        if (window.parent === window || !mount?.supportUrl || !mount?.runtime) return;
        const parentOrigin = new URL(mount.supportUrl, document.baseURI).origin;
        let lifecycleId = mount.lifecycleId ?? 1;
        window.addEventListener("message", (event) => {{
          if (event.source !== window.parent || event.origin !== parentOrigin) return;
          const message = event.data;
          if (message?.type === "marimo-studio:switch-view" &&
              message.runtime === mount.runtime &&
              Number.isSafeInteger(message.lifecycleId) && message.lifecycleId > 0) {{
            lifecycleId = message.lifecycleId;
          }}
        }});
        document.addEventListener("click", (event) => {{
          if (event.defaultPrevented || event.button !== 0 || event.altKey ||
              event.ctrlKey || event.metaKey || event.shiftKey ||
              !(event.target instanceof Element)) return;
          const link = event.target.closest("a[data-studio-view]");
          if (!link || (link.target && link.target !== "_self")) return;
          event.preventDefault();
          window.parent.postMessage({{
            type: "marimo-studio:navigate-view",
            runtime: mount.runtime,
            lifecycleId,
            view: link.dataset.studioView,
            query: window.location.search,
            hash: window.location.hash,
          }}, parentOrigin);
        }});
      }})();
    </script>
    <script type="module">
      const observeMarimoValue = (host, {{ onValue, onError = () => {{}} }}) => {{
        const sync = (event) => onValue(event.detail.value);
        const fail = (event) => onError(event.detail);
        host.addEventListener("marimo-value-updated", sync);
        host.addEventListener("marimo-value-error", fail);
        if (host.dataset.marimoError !== undefined) {{
          onError({{
            selector: host.getAttribute("mo-value")?.trim() ?? "",
            code: host.dataset.marimoErrorCode,
            message: host.dataset.marimoError,
            hint: host.dataset.marimoDiagnosticHint,
          }});
        }} else if (host.marimoValue !== undefined) {{
          onValue(host.marimoValue);
        }}
        return () => {{
          host.removeEventListener("marimo-value-updated", sync);
          host.removeEventListener("marimo-value-error", fail);
        }};
      }};
      window.__observeMarimoValue = observeMarimoValue;
      document.querySelector("#app-shell")?.setAttribute("data-ready", "");
    </script>
  </body>
</html>
"""


# Retain compatibility with existing generated projects; new apps use the public helper.
_render_studio_view_html = render_studio_view_html


def _generate_notebook_source(
    *,
    app_title: str,
    user_need: str,
    notebook_path: Path,
    data_dir: Path,
    lineage_json_path: Path,
    traces_json_path: Path,
    memory_rules_path: Path,
) -> str:
    """Generate a self-contained, PEP 723 compliant reactive Marimo notebook with executive visuals & KaTeX proofs."""
    notebook_dir = notebook_path.resolve().parent
    data_posix = Path(os.path.relpath(data_dir.resolve(), notebook_dir)).as_posix()
    lineage_posix = Path(os.path.relpath(lineage_json_path.resolve(), notebook_dir)).as_posix()
    traces_posix = Path(os.path.relpath(traces_json_path.resolve(), notebook_dir)).as_posix()
    rules_posix = Path(os.path.relpath(memory_rules_path.resolve(), notebook_dir)).as_posix()

    return f'''# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo>=0.20.0",
#     "marimo-studio>=0.3.0",
#     "polars>=1.20.0",
#     "duckdb>=1.2.0",
#     "pointblank>=0.10.0",
#     "pyarrow>=26.0.0",
# ]
# ///

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full", app_title={app_title!r})


@app.cell
def imports_and_config():
    import json
    from html import escape
    from pathlib import Path

    import duckdb
    import marimo as mo
    import pointblank as pb
    import polars as pl

    _app_directory = Path(__file__).resolve().parent
    data_directory = _app_directory / {data_posix!r}
    lineage_file = _app_directory / {lineage_posix!r}
    traces_file = _app_directory / {traces_posix!r}
    memory_file = _app_directory / {rules_posix!r}
    user_need_text = {user_need!r}
    app_title_text = {app_title!r}

    def responsive_grid(items, min_width="18rem"):
        _children = "".join(
            f'<div style="min-width:0;max-width:100%;overflow-wrap:anywhere;">{{mo.as_html(_item).text}}</div>'
            for _item in items
        )
        return mo.Html(
            '<style>.nouc-responsive-grid code{{white-space:pre-wrap;overflow-wrap:anywhere;}}'
            '.nouc-responsive-grid pre{{max-width:100%;overflow-x:auto;}}'
            '.nouc-responsive-grid label{{white-space:normal;}}</style>'
            '<div class="nouc-responsive-grid" style="display:grid;grid-template-columns:repeat(auto-fit,'
            f'minmax(min(100%,{{min_width}}),1fr));gap:1.25rem;min-width:0;max-width:100%;">'
            f'{{_children}}</div>'
        )

    def markdown_text(value):
        _text = escape(str(value))
        for _char in (chr(92), "`", "*", "_", "[", "]", "$"):
            _text = _text.replace(_char, chr(92) + _char)
        return _text

    return (
        Path,
        app_title_text,
        data_directory,
        duckdb,
        escape,
        json,
        lineage_file,
        markdown_text,
        memory_file,
        mo,
        pb,
        pl,
        responsive_grid,
        traces_file,
        user_need_text,
    )


@app.cell
def data_loader(data_directory, json, lineage_file, memory_file, pl, traces_file):
    loaded_tables = {{}}
    if data_directory.exists():
        for _pq in sorted(data_directory.glob("*.parquet")):
            loaded_tables[_pq.stem] = pl.read_parquet(_pq)

    lineage_payload = (
        json.loads(lineage_file.read_text(encoding="utf-8"))
        if lineage_file.exists()
        else {{"nodes": [], "edges": []}}
    )
    traces_payload = (
        json.loads(traces_file.read_text(encoding="utf-8"))
        if traces_file.exists()
        else []
    )
    memory_payload = (
        json.loads(memory_file.read_text(encoding="utf-8"))
        if memory_file.exists()
        else {{"prevention_rules": [], "episodes": []}}
    )
    return lineage_payload, loaded_tables, memory_payload, traces_payload


@app.cell
def header_overview(
    app_title_text,
    escape,
    lineage_payload,
    loaded_tables,
    memory_payload,
    mo,
    responsive_grid,
    traces_payload,
    user_need_text,
):
    sensitivity_slider = mo.ui.slider(
        start=-25.0,
        stop=25.0,
        step=1.0,
        value=0.0,
        label="Scenario Shock / Sensitivity Stress (%)",
    )
    confidence_filter = mo.ui.dropdown(
        options=["All Grades (A-F)", "Verified Only (Grade A)", "High Trust (Grades A-B)"],
        value="All Grades (A-F)",
        label="Epistemic Trust Filter",
    )
    guided_slider = mo.md(
        "**Sensitivity guide**\\n\\n"
        "Drag the slider to stress-test the displayed metric values and uncertainty bounds."
    )
    def _dataset_priority(name):
        _df = loaded_tables[name]
        _is_metadata = name.startswith(("doc_", "codebase_")) or name.endswith("_chunks")
        _numeric_count = sum(_dtype.is_numeric() for _dtype in _df.dtypes)
        return (not _is_metadata, _numeric_count > 0, _numeric_count, _df.height)

    _table_names = sorted(loaded_tables, key=_dataset_priority, reverse=True)
    selected_dataset_dropdown = mo.ui.dropdown(
        options=_table_names if _table_names else ["none"],
        value=_table_names[0] if _table_names else "none",
        label="Inspect Ingested Dataset",
    )

    _node_cnt = len(lineage_payload.get("nodes", []))
    _edge_cnt = len(lineage_payload.get("edges", []))
    _rule_cnt = len(memory_payload.get("prevention_rules", []))

    _hero_html = mo.Html(
        f"""
        <div style="box-sizing: border-box; min-width: 0; overflow-wrap: anywhere; background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #312e81 100%); color: #f8fafc; border-radius: 16px; padding: clamp(14px, 3vw, 28px); box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.25); border: 1px solid rgba(99, 102, 241, 0.3);">
          <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 16px;">
            <div style="max-width: 720px; min-width: 0; flex: 1 1 320px;">
              <div style="display: inline-flex; align-items: center; gap: 8px; background: rgba(99, 102, 241, 0.22); border: 1px solid rgba(129, 140, 248, 0.4); color: #c7d2fe; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; padding: 4px 12px; border-radius: 999px; margin-bottom: 10px;">
                <span>Nouc Studio · Multi-View Analytics</span>
              </div>
              <h1 style="margin: 0 0 8px 0; font-size: clamp(1.35rem, 1.1rem + 1vw, 1.85rem); font-weight: 800; color: #ffffff; letter-spacing: -0.02em;">
                {{escape(app_title_text)}}
              </h1>
              <p style="margin: 0; font-size: 14px; line-height: 1.55; color: #cbd5e1;">
                <strong style="color: #e2e8f0;">Objective:</strong> {{escape(user_need_text)}}
              </p>
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 10px;">
              <div style="background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 14px; min-width: 110px;">
                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Polars Tables</div>
                <div style="font-size: 20px; font-weight: 800; color: #ffffff; font-variant-numeric: tabular-nums;">{{len(loaded_tables)}}</div>
              </div>
              <div style="background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 14px; min-width: 110px;">
                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Audited KPIs</div>
                <div style="font-size: 20px; font-weight: 800; color: #34d399; font-variant-numeric: tabular-nums;">{{len(traces_payload)}}</div>
              </div>
              <div style="background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 14px; min-width: 110px;">
                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Lineage DAG</div>
                <div style="font-size: 20px; font-weight: 800; color: #a5b4fc; font-variant-numeric: tabular-nums;">{{_node_cnt}}N / {{_edge_cnt}}E</div>
              </div>
              <div style="background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 10px 14px; min-width: 110px;">
                <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Memory Rules</div>
                <div style="font-size: 20px; font-weight: 800; color: #fcd34d; font-variant-numeric: tabular-nums;">{{_rule_cnt}}</div>
              </div>
            </div>
          </div>
        </div>
        """
    )

    header_block = mo.vstack(
        [
            _hero_html,
            responsive_grid(
                [sensitivity_slider, confidence_filter, guided_slider],
                min_width="15rem",
            ),
        ],
        gap=1.0,
    )
    header_block
    return (
        confidence_filter,
        guided_slider,
        header_block,
        selected_dataset_dropdown,
        sensitivity_slider,
    )


@app.cell
def kpi_cards(
    confidence_filter,
    escape,
    mo,
    pl,
    responsive_grid,
    sensitivity_slider,
    traces_payload,
):
    _total_shock_pct = float(sensitivity_slider.value or 0.0)
    _shock_factor = 1.0 + (_total_shock_pct / 100.0)
    _filter_mode = confidence_filter.value or "All Grades (A-F)"

    def _fmt_metric_number(val, unit_label):
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return f"{{val}} {{unit_label}}".strip()
        num = float(val)
        u_up = (unit_label or "").upper()
        if u_up == "USD":
            return f"${{num:,.0f}}" if abs(num) >= 100 else f"${{num:,.2f}}"
        if u_up == "EUR":
            return f"€{{num:,.0f}}" if abs(num) >= 100 else f"€{{num:,.2f}}"
        if unit_label == "%":
            return f"{{num:,.2f}}%"
        if unit_label in ("rows", "count", "sections"):
            return f"{{int(round(num)):,}} {{unit_label}}"
        if abs(num) >= 1000:
            return f"{{num:,.1f}} {{unit_label}}".strip()
        return f"{{num:,.2f}} {{unit_label}}".strip()

    _cards = []
    _summary_rows = []
    for _trace in traces_payload:
        _m = _trace.get("metric_node", {{}})
        _u = _trace.get("propagated_uncertainty", {{}})
        _grade = _u.get("trust_grade", "A")
        if _filter_mode == "Verified Only (Grade A)" and _grade != "A":
            continue
        if _filter_mode == "High Trust (Grades A-B)" and _grade not in ("A", "B"):
            continue

        _raw_val = _m.get("value_preview", 0)
        _unit = _m.get("unit") or ""
        _ep_pct = float(_u.get("epistemic_uncertainty_pct", 0.0))
        _comp = float(_u.get("data_completeness", 1.0)) * 100.0
        _val_pass = float(_u.get("validation_pass_rate", 1.0)) * 100.0
        _conf_score = float(_u.get("composite_confidence_score", 0.98)) * 100.0

        if isinstance(_raw_val, (int, float)) and not isinstance(_raw_val, bool):
            _stressed = round(float(_raw_val) * _shock_factor, 4)
            _delta = abs(_stressed) * (_ep_pct / 100.0)
            _low_b = _stressed - _delta
            _high_b = _stressed + _delta
            _ci_str = f"[{{_fmt_metric_number(_low_b, _unit)}}, {{_fmt_metric_number(_high_b, _unit)}}]"
            _display_val = _fmt_metric_number(_stressed, _unit)
        else:
            _display_val = f"{{_raw_val}} {{_unit}}".strip()
            _ci_str = "N/A"

        _sources = [s.get("label", "") for s in _trace.get("upstream_sources", [])]
        _src_badge = _sources[0] if _sources else "In-memory"
        _badge_bg = "#ecfdf5" if _grade == "A" else ("#eef2ff" if _grade == "B" else "#fffbeb")
        _badge_fg = "#065f46" if _grade == "A" else ("#3730a3" if _grade == "B" else "#92400e")
        _badge_border = "#a7f3d0" if _grade == "A" else ("#c7d2fe" if _grade == "B" else "#fde68a")
        _bar_width = max(15, min(100, int(round(_conf_score))))

        _card_html = mo.Html(
            f"""
            <div style="box-sizing: border-box; min-width: 0; overflow-wrap: anywhere; container-type: inline-size; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04); display: flex; flex-direction: column; justify-content: space-between; gap: 12px; height: 100%;">
              <div>
                <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 8px;">
                  <div style="font-size: 13px; font-weight: 700; color: #334155; line-height: 1.35;">
                    {{escape(str(_m.get('label', 'Metric')))}}
                  </div>
                  <span style="background: {{_badge_bg}}; color: {{_badge_fg}}; border: 1px solid {{_badge_border}}; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap;">
                    Grade {{_grade}} · {{_conf_score:.0f}}%
                  </span>
                </div>
                <div style="font-size: 26px; font-weight: 800; color: #0f172a; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; margin: 4px 0 10px 0;">
                  {{escape(_display_val)}}
                </div>
                <div style="background: #f8fafc; border: 1px solid #f1f5f9; border-radius: 8px; padding: 8px 10px; font-size: 11.5px; color: #475569;">
                  <div style="display: flex; flex-wrap: wrap; gap: 6px; justify-content: space-between; margin-bottom: 4px;">
                    <span style="min-width:0;"><strong>Heuristic range:</strong> <code style="white-space:normal;overflow-wrap:anywhere;">{{escape(_ci_str)}}</code></span>
                    <span style="color: #6366f1; font-weight: 600;">±{{_ep_pct:.2f}}%</span>
                  </div>
                  <div style="width: 100%; height: 5px; background: #e2e8f0; border-radius: 999px; overflow: hidden;">
                    <div style="width: {{_bar_width}}%; height: 100%; background: linear-gradient(90deg, #4f46e5, #10b981); border-radius: 999px;"></div>
                  </div>
                </div>
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 6px; justify-content: space-between; align-items: center; border-top: 1px solid #f1f5f9; padding-top: 8px; font-size: 11px; color: #64748b;">
                <span>QA Pass: <strong style="color: #059669;">{{_val_pass:.0f}}%</strong> · Complete: <strong>{{_comp:.0f}}%</strong></span>
                <span style="background: #f1f5f9; padding: 2px 7px; border-radius: 6px; font-family: monospace; color: #475569;">{{escape(_src_badge[:24])}}</span>
              </div>
            </div>
            """
        )
        _cards.append(_card_html)
        _summary_rows.append(
            {{
                "Metric": _m.get("label", ""),
                "Stressed Value": _display_val,
                "Heuristic range": _ci_str,
                "Trust Grade": _grade,
                "Uncertainty (±%)": _ep_pct,
                "QA Pass (%)": round(_val_pass, 1),
                "Primary Source": ", ".join(_sources[:2]),
                "Metric ID": _m.get("node_id", ""),
            }}
        )

    # Keep the first screen useful; the complete registry remains one action away.
    _hero_cards = _cards[:3]
    kpi_summary_df = pl.DataFrame(_summary_rows) if _summary_rows else pl.DataFrame()
    kpi_section = mo.vstack(
        [
            mo.md(
                f"### Key metrics · scenario {{_total_shock_pct:+.1f}}%"
            ),
            mo.md("Heuristic uncertainty ranges combine configured assumptions and data-quality penalties."),
            responsive_grid(_hero_cards) if _hero_cards else mo.md("*No metrics match the active trust filter.*"),
            mo.accordion({{
                f"All {{len(_summary_rows)}} metrics · values, sources and quality": mo.ui.table(
                    kpi_summary_df, selection=None, page_size=10, show_column_summaries=False,
                )
            }}),
        ],
        gap=1.25,
    )
    kpi_section
    return kpi_section, kpi_summary_df


@app.cell
def interactive_simulation(
    escape,
    loaded_tables,
    mo,
    pl,
    selected_dataset_dropdown,
    sensitivity_slider,
):
    _active_name = selected_dataset_dropdown.value
    _active_df = loaded_tables.get(_active_name, pl.DataFrame()) if _active_name else pl.DataFrame()

    _total_shock_pct = float(sensitivity_slider.value or 0.0)
    _shock = 1.0 + (_total_shock_pct / 100.0)
    _num_cols = [c for c, dt in zip(_active_df.columns, _active_df.dtypes, strict=False) if dt.is_numeric()]
    _label_col = next(
        (c for c, dt in zip(_active_df.columns, _active_df.dtypes, strict=False) if not dt.is_numeric()),
        _active_df.columns[0] if _active_df.columns else "row",
    )

    if _num_cols and _active_df.height > 0 and _shock != 1.0:
        simulated_df = _active_df.with_columns(
            [(pl.col(c) * _shock).round(4).alias(f"{{c}}_stressed") for c in _num_cols[:3]]
        )
    else:
        simulated_df = _active_df

    # Build a responsive visual SVG distribution & sensitivity comparison chart for the primary numeric column
    _chart_block = mo.md("")
    if _num_cols and _active_df.height > 0:
        _primary_col = _num_cols[0]
        _sample_df = _active_df.head(8)
        _labels = [str(x) for x in _sample_df[_label_col].to_list()]
        _base_vals = [float(x or 0.0) for x in _sample_df[_primary_col].to_list()]
        _stress_vals = [round(v * _shock, 2) for v in _base_vals]
        _max_v = max([abs(v) for v in [*_base_vals, *_stress_vals]] + [1.0])

        _bar_rows_html = []
        for _lbl, _bv, _sv in zip(_labels, _base_vals, _stress_vals, strict=False):
            _bw = max(4.0, min(100.0, (abs(_bv) / _max_v) * 100.0))
            _sw = max(4.0, min(100.0, (abs(_sv) / _max_v) * 100.0))
            _bar_rows_html.append(
                f"""
                <div style="display: grid; grid-template-columns: minmax(0, 1fr); align-items: center; gap: 6px; padding: 10px 0; border-bottom: 1px dashed #e2e8f0;">
                  <div style="font-size: 12px; font-weight: 600; color: #334155; overflow-wrap: anywhere;">{{escape(_lbl)}}</div>
                  <div style="display: flex; flex-direction: column; gap: 4px; min-width: 0;">
                    <div style="height: 8px; width: {{_bw:.1f}}%; background: #94a3b8; border-radius: 999px;" title="Baseline: {{_bv:,.2f}}"></div>
                    <div style="height: 8px; width: {{_sw:.1f}}%; background: linear-gradient(90deg, #4f46e5, #06b6d4); border-radius: 999px;" title="Stressed: {{_sv:,.2f}}"></div>
                  </div>
                  <div style="font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; color: #0f172a; font-weight: 700;">
                    {{_sv:,.2f}} <span style="font-size: 10.5px; color: #64748b; font-weight: 500;">(base {{_bv:,.1f}})</span>
                  </div>
                </div>
                """
            )

        _chart_block = mo.Html(
            f"""
            <div style="box-sizing: border-box; min-width: 0; overflow-wrap: anywhere; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; padding: clamp(12px, 3vw, 22px); box-shadow: 0 2px 6px rgba(15, 23, 42, 0.03);">
              <div style="display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="min-width: 0;">
                  <div style="font-size: 14px; font-weight: 700; color: #0f172a;">Visual Cohort Comparison — <code>{{escape(_primary_col)}}</code> by <code>{{escape(_label_col)}}</code></div>
                  <div style="font-size: 12px; color: #64748b;">Top {{len(_labels)}} records comparing Baseline (slate) vs. Scenario Stress <code>{{_total_shock_pct:+.1f}}%</code> (indigo gradient)</div>
                </div>
                <div style="display: flex; gap: 14px; font-size: 11.5px; font-weight: 600; color: #475569;">
                  <span style="display: inline-flex; align-items: center; gap: 6px;"><span style="width: 10px; height: 10px; background: #94a3b8; border-radius: 3px; display: inline-block;"></span>Baseline</span>
                  <span style="display: inline-flex; align-items: center; gap: 6px;"><span style="width: 10px; height: 10px; background: #4f46e5; border-radius: 3px; display: inline-block;"></span>Stressed ({{_total_shock_pct:+.1f}}%)</span>
                </div>
              </div>
              {{"".join(_bar_rows_html)}}
            </div>
            """
        )

    simulation_view = mo.vstack(
        [
            mo.md("### Interactive Dataset & Sensitivity Explorer"),
            selected_dataset_dropdown,
            _chart_block,
            mo.ui.table(
                simulated_df.head(100),
                label=f"Dataset: {{_active_name}} (Rows={{simulated_df.height}}, Active Shock={{_total_shock_pct:+.1f}}%)",
            ),
        ],
        gap=1.0,
    )
    simulation_view
    return simulated_df, simulation_view


@app.cell
def lineage_selector_controls(mo, traces_payload):
    metric_options_map = {{
        f"{{t['metric_node']['label']}} ({{t['metric_node']['node_id']}})": idx
        for idx, t in enumerate(traces_payload)
    }}
    _first_key = next(iter(metric_options_map.keys()), None)
    lineage_metric_selector = mo.ui.dropdown(
        options=list(metric_options_map.keys()) if metric_options_map else ["No metrics"],
        value=_first_key if _first_key else "No metrics",
        label="Select Audited Metric to Inspect Complete Calculation Proof & Provenance",
        full_width=True,
    )
    return lineage_metric_selector, metric_options_map


@app.cell
def calculation_lineage_view(
    lineage_metric_selector,
    lineage_payload,
    markdown_text,
    metric_options_map,
    mo,
    pl,
    responsive_grid,
    traces_payload,
):
    _selected_idx = metric_options_map.get(lineage_metric_selector.value or "", 0)
    _selected_trace = (
        traces_payload[_selected_idx]
        if traces_payload and _selected_idx < len(traces_payload)
        else None
    )

    # Build a styled, color-coded Mermaid subgraph for the selected metric
    _mermaid_lines = [
        "flowchart LR",
        "    classDef sourceNode fill:#eef2ff,stroke:#4f46e5,color:#1e1b4b,stroke-width:2px;",
        "    classDef transformNode fill:#f5f3ff,stroke:#7c3aed,color:#2e1065,stroke-width:2px;",
        "    classDef validationNode fill:#ecfdf5,stroke:#059669,color:#064e3b,stroke-width:2px;",
        "    classDef assumptionNode fill:#fffbeb,stroke:#d97706,color:#78350f,stroke-width:1.5px,stroke-dasharray: 4 2;",
        "    classDef metricNode fill:#1e1b4b,stroke:#4f46e5,color:#ffffff,stroke-width:3px;",
    ]
    _kind_cls_map = {{
        "source_file": "sourceNode",
        "source_fragment": "sourceNode",
        "studio_view": "sourceNode",
        "transform": "transformNode",
        "marimo_cell": "transformNode",
        "code_ast": "transformNode",
        "validation_check": "validationNode",
        "assumption": "assumptionNode",
        "metric": "metricNode",
    }}
    if _selected_trace:
        _step_ids = set()
        for _s in _selected_trace.get("ordered_steps", []):
            _nid = _s.get("node_id", "")
            _step_ids.add(_nid)
            _raw_lbl = str(_s.get("label", "")).replace('"', "'")
            _short_lbl = _raw_lbl[:42] + ("..." if len(_raw_lbl) > 42 else "")
            _kind = _s.get("kind", "raw_source")
            _grade = (_s.get("uncertainty") or {{}}).get("trust_grade", "A")
            _cls = _kind_cls_map.get(_kind, "sourceNode")
            _mermaid_lines.append(f'    {{_nid}}["{{_short_lbl}} · Grade {{_grade}}"]:::{{_cls}}')
        for _e in lineage_payload.get("edges", []):
            if _e.get("source_id") in _step_ids and _e.get("target_id") in _step_ids:
                _mermaid_lines.append(f'    {{_e["source_id"]}} -->|{{_e["kind"]}}| {{_e["target_id"]}}')
    else:
        for _n in lineage_payload.get("nodes", [])[:15]:
            _lbl = str(_n.get("label", "")).replace('"', "'")
            _mermaid_lines.append(f'    {{_n["node_id"]}}["{{_lbl}}"]:::sourceNode')

    _legend_html = mo.Html(
        """
        <div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 11.5px; font-weight: 600; color: #475569; margin-bottom: 4px;">
          <span style="background: #eef2ff; border: 1.5px solid #4f46e5; color: #1e1b4b; padding: 3px 10px; border-radius: 999px;">1. Raw Source / Table</span>
          <span>→</span>
          <span style="background: #ecfdf5; border: 1.5px solid #059669; color: #064e3b; padding: 3px 10px; border-radius: 999px;">2. Pointblank QA Gate</span>
          <span>→</span>
          <span style="background: #fffbeb; border: 1.5px dashed #d97706; color: #78350f; padding: 3px 10px; border-radius: 999px;">3. Epistemic Assumption</span>
          <span>→</span>
          <span style="background: #f5f3ff; border: 1.5px solid #7c3aed; color: #2e1065; padding: 3px 10px; border-radius: 999px;">4. Polars + Monty Transform</span>
          <span>→</span>
          <span style="background: #1e1b4b; border: 1.5px solid #4f46e5; color: #ffffff; padding: 3px 10px; border-radius: 999px;">5. Audited KPI Metric</span>
        </div>
        """
    )
    _mermaid_diagram = mo.mermaid("\\n".join(_mermaid_lines))

    # Build a structured 2x2 Executive Proof Card Grid with KaTeX-safe math rendering
    if _selected_trace:
        _m_node = _selected_trace.get("metric_node", {{}})
        _u_prof = _selected_trace.get("propagated_uncertainty", {{}})
        _tx_list = _selected_trace.get("transformations", [])
        _src_list = _selected_trace.get("upstream_sources", [])
        _val_list = _selected_trace.get("validations", [])

        _safe_formula = (_tx_list[0].get("formula_latex") if _tx_list else _m_node.get("formula_latex")) or "y = f(x)"
        _polars_expr = (_tx_list[0].get("code_snippet") if _tx_list else _m_node.get("code_snippet")) or "N/A"
        _ci_pair = _u_prof.get("confidence_interval_95")
        _ci_formatted = f"[{{_ci_pair[0]:,.2f}}, {{_ci_pair[1]:,.2f}}]" if _ci_pair else "N/A"

        _formula_card = mo.callout(
            mo.md(
                "#### 1. Mathematical Formula & Sandbox Proof\\n\\n"
                f"**Metric**: **{{markdown_text(_m_node.get('label', ''))}}**  \\n"
                f"**Computed Value**: `{{_m_node.get('value_preview', '')}} {{_m_node.get('unit', '')}}` "
                f"| **Heuristic uncertainty range**: `{{_ci_formatted}}`\\n\\n"
                f"$$\\n{{_safe_formula}}\\n$$\\n\\n"
                f"- **Polars Expression**: `{{_polars_expr}}`\\n"
                "- **Execution Sandbox**: `pydantic-monty` deterministic Rust interpreter."
            ),
            kind="info",
        )

        _prov_bullets = []
        for _s in _src_list:
            _c = _s.get("coordinates") or {{}}
            _fpath = str(_c.get("file_path") or "").replace("\\\\", "/")
            _sheet = f" · sheet=`{{_c['sheet_name']}}`" if _c.get("sheet_name") else ""
            _rng = f" · range=`{{_c['cell_range']}}`" if _c.get("cell_range") else ""
            _sha = str(_c.get("file_hash_sha256") or "")[:12]
            _prov_bullets.append(
                f"- **{{markdown_text(_s.get('label', 'Source'))}}**: `{{_fpath}}`{{_sheet}}{{_rng}} (`sha256:{{_sha}}...`) — {{markdown_text(_s.get('description', ''))}}"
            )
        _prov_md_text = "\\n".join(_prov_bullets) if _prov_bullets else "- *Derived from in-memory parameters.*"

        _provenance_card = mo.callout(
            mo.md(
                "#### 2. Cryptographic Source Provenance\\n\\n"
                "Every upstream file and table coordinate is hashed (`SHA-256`) at ingestion:\\n\\n"
                + _prov_md_text
            ),
            kind="neutral",
        )

        _val_bullets = [
            f"- **{{markdown_text(v.get('label', 'QA'))}}**: Pass rate `{{float((v.get('uncertainty') or {{}}).get('validation_pass_rate', 1.0)) * 100:.1f}}%` — {{markdown_text(v.get('description', ''))}}"
            for v in _val_list
        ]
        _val_md_text = "\\n".join(_val_bullets) if _val_bullets else "- *No row-level validation evidence recorded.*"

        _qa_card = mo.callout(
            mo.md(
                "#### 3. Data Quality & Epistemic Trust Score\\n\\n"
                f"- **Trust Grade**: **Grade {{_u_prof.get('trust_grade', 'A')}}** "
                f"(Composite Confidence: `{{float(_u_prof.get('composite_confidence_score', 1.0)) * 100:.1f}}%`)\\n"
                f"- **Epistemic Uncertainty**: `±{{float(_u_prof.get('epistemic_uncertainty_pct', 0.0)):.2f}}%`\\n"
                + _val_md_text
            ),
            kind="success",
        )

        _assump_bullets = [f"- **Assumption**: {{markdown_text(a)}}" for a in _u_prof.get("assumptions", [])] + [
            f"- **Caveat**: {{markdown_text(c)}}" for c in _u_prof.get("caveats", [])
        ]
        _assump_md_text = "\\n".join(_assump_bullets) if _assump_bullets else "- *No open caveats.*"

        _assumptions_card = mo.callout(
            mo.md(
                "#### 4. Explicit Assumptions & Epistemic Caveats\\n\\n" + _assump_md_text
            ),
            kind="warn",
        )

        _proof_grid = responsive_grid(
            [_formula_card, _provenance_card, _qa_card, _assumptions_card],
            min_width="24rem",
        )
    else:
        _proof_grid = mo.md("*No calculation trace available.*")

    _steps_df = (
        pl.DataFrame(
            [
                {{
                    "Step": idx + 1,
                    "Stage Kind": s.get("kind", ""),
                    "Artifact / Node": s.get("label", ""),
                    "Trust Grade": (s.get("uncertainty") or {{}}).get("trust_grade", "A"),
                    "Polars Code / Formula": s.get("code_snippet") or s.get("formula_latex") or "",
                    "Source File": str((s.get("coordinates") or {{}}).get("file_path") or "").replace("\\\\", "/"),
                    "Coordinates": (s.get("coordinates") or {{}}).get("cell_range")
                    or str(
                        (s.get("coordinates") or {{}}).get("page_number")
                        or (s.get("coordinates") or {{}}).get("line_start")
                        or ""
                    ),
                    "SHA-256 Prefix": ((s.get("coordinates") or {{}}).get("file_hash_sha256") or "")[:12],
                }}
                for idx, s in enumerate(_selected_trace.get("ordered_steps", []))
            ]
        )
        if _selected_trace
        else pl.DataFrame()
    )

    lineage_panel = mo.vstack(
        [
            mo.md("## Complete Calculation Lineage & Mathematical Proof Explorer"),
            mo.md(
                f"Workspace Lineage DAG: `{{len(lineage_payload.get('nodes', []))}}` nodes & `{{len(lineage_payload.get('edges', []))}}` directed edges. "
                "Select any audited metric below to inspect its focused calculation subgraph, KaTeX mathematical formula, and SHA-256 source coordinates."
            ),
            lineage_metric_selector,
            _legend_html,
            _mermaid_diagram.style({{"min-width": "0", "max-width": "100%", "overflow-x": "auto"}}),
            _proof_grid,
            mo.ui.table(_steps_df, label="Step-by-Step Topological Calculation Lineage"),
        ],
        gap=1.25,
    )
    lineage_panel
    return (lineage_panel,)



@app.cell
def pointblank_qa_view(loaded_tables, mo, pb, pl, traces_payload):
    _qa_rows = []
    for _tname, _df in loaded_tables.items():
        _non_null_cols = [c for c in _df.columns if _df[c].null_count() == 0][:5]
        _val = pb.Validate(data=_df, tbl_name=_tname).col_exists(columns=list(_df.columns))
        if _non_null_cols and _df.height > 0:
            _val = _val.col_vals_not_null(columns=_non_null_cols)
        _interrogated = _val.interrogate()
        _rates = _interrogated.f_passed() or {{}}
        _mean_pass = (sum(_rates.values()) / len(_rates)) * 100.0 if _rates else 100.0
        _null_pct = (
            sum(_df[c].null_count() for c in _df.columns) / max(1, _df.height * max(1, _df.width))
        ) * 100.0
        _qa_rows.append(
            {{
                "table_id": _tname,
                "rows": _df.height,
                "columns": _df.width,
                "pointblank_steps": len(_rates),
                "all_checks_passed": bool(_interrogated.all_passed()),
                "mean_pass_rate_pct": round(_mean_pass, 2),
                "missing_cell_pct": round(_null_pct, 2),
            }}
        )

    _assumptions_rows = []
    for _t in traces_payload:
        _m_label = _t.get("metric_node", {{}}).get("label", "")
        _u = _t.get("propagated_uncertainty", {{}})
        for _a in _u.get("assumptions", []):
            _assumptions_rows.append({{"metric": _m_label, "kind": "Assumption", "detail": _a}})
        for _c in _u.get("caveats", []):
            _assumptions_rows.append({{"metric": _m_label, "kind": "Caveat / Uncertainty Driver", "detail": _c}})

    qa_df = pl.DataFrame(_qa_rows) if _qa_rows else pl.DataFrame()
    assumptions_df = pl.DataFrame(_assumptions_rows) if _assumptions_rows else pl.DataFrame()

    qa_panel = mo.vstack(
        [
            mo.md("## Posit Pointblank Data Quality & Epistemic Humility Monitor"),
            mo.ui.table(qa_df, label="Pointblank Automated Data Quality Scorecard"),
            mo.ui.table(assumptions_df, label="Explicit Assumptions & Epistemic Caveats Registry"),
        ],
        gap=1.25,
    )
    qa_panel
    return assumptions_df, qa_df, qa_panel


@app.cell
def querychat_controls(loaded_tables, mo, selected_dataset_dropdown):
    _default_tbl = selected_dataset_dropdown.value or next(iter(loaded_tables.keys()), "dataset")
    query_input = mo.ui.text(
        value=f"SELECT * FROM {{_default_tbl}} LIMIT 25",
        label="QueryChat — Ask in SQL or filter expression (100% Transparent & Read-Only)",
        full_width=True,
    )
    return (query_input,)


@app.cell
def querychat_view(duckdb, loaded_tables, mo, pl, query_input):
    _sql = (query_input.value or "").strip()
    _err_msg = None
    _result_df = pl.DataFrame()
    if _sql:
        _upper = _sql.upper()
        if any(_kw in _upper for _kw in ("DROP ", "DELETE ", "UPDATE ", "INSERT ", "ALTER ", "COPY ")):
            _err_msg = "Blocked by QueryChat read-only security gate."
        else:
            try:
                with duckdb.connect(":memory:") as _conn:
                    for _k, _v in loaded_tables.items():
                        _conn.register(_k, _v)
                    _result_df = _conn.execute(_sql).pl()
            except (duckdb.Error, RuntimeError, ValueError) as _exc:
                try:
                    _ctx = pl.SQLContext(loaded_tables)
                    _result_df = _ctx.execute(_sql, eager=True)
                except Exception:
                    _err_msg = str(_exc)

    querychat_panel = mo.vstack(
        [
            mo.md("## Transparent QueryChat Explorer (Posit Pattern)"),
            mo.md(f"Available tables in DuckDB/Polars memory: {{', '.join(f'`{{k}}`' for k in loaded_tables)}}"),
            query_input,
            mo.md(f"**Executed SQL**:\\n```sql\\n{{_sql}}\\n```"),
            mo.callout(mo.md(f"**Query Error**: `{{_err_msg}}`"), kind="warn")
            if _err_msg
            else mo.ui.table(_result_df, label=f"Query Result ({{_result_df.height}} rows)"),
        ],
        gap=1.0,
    )
    querychat_panel
    return (querychat_panel,)


@app.cell
def adaptive_memory_view(memory_payload, mo, pl):
    _episodes = memory_payload.get("episodes", [])
    _rules = memory_payload.get("prevention_rules", [])
    _ep_df = pl.DataFrame(_episodes) if _episodes else pl.DataFrame()
    _rules_md = "\\n".join(f"- {{r}}" for r in _rules) if _rules else "- *No prevention rules recorded yet.*"

    memory_panel = mo.vstack(
        [
            mo.md("## Self-Evolving Adaptive Memory & Verification Telemetry"),
            mo.md(
                "Tracks every encountered failure and its empirically verified fix across Local (`.insights/memory/`) and Global (`~/.nouc-studio/memory/`) stores."
            ),
            mo.md(f"### Active Cross-Project Prevention Rules\\n{{_rules_md}}"),
            mo.ui.table(_ep_df, label="Recorded Failure-to-Fix Episodes (DuckDB + Rustworkx)"),
        ],
        gap=1.25,
    )
    memory_panel
    return (memory_panel,)


@app.cell
def main_tabs(
    header_block,
    kpi_section,
    lineage_panel,
    memory_panel,
    mo,
    qa_panel,
    querychat_panel,
    simulation_view,
):
    studio_tabs = mo.ui.tabs(
        {{
            "Executive Studio": mo.vstack([header_block, kpi_section, simulation_view], gap=1.5),
            "Calculation Lineage & Proofs": lineage_panel,
            "Pointblank QA & Uncertainty": qa_panel,
            "Transparent QueryChat": querychat_panel,
            "Adaptive Memory & Telemetry": memory_panel,
        }}
    )
    studio_tabs
    return (studio_tabs,)


if __name__ == "__main__":
    app.run()
'''


class StudioApplicationGenerator:
    """Generates a verified Marimo notebook and builds multi-view Marimo Studio applications."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.data_dir = self.output_dir / "data"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def build_studio_application(
        self,
        *,
        app_title: str,
        user_need: str,
        manifest: IngestionManifest,
        graph: LineageGraphEngine,
        traces: list[MetricLineageTrace],
        memory_payload: dict[str, Any],
    ) -> GeneratedStudioBundle:
        """Write the reactive notebook, lineage artifacts, and build + runtime-validate 3 marimo-studio views."""
        import shutil

        lineage_json_path = self.output_dir / "lineage_graph.json"
        traces_json_path = self.output_dir / "lineage_traces.json"
        memory_rules_path = self.output_dir / "adaptive_memory_snapshot.json"
        notebook_path = self.output_dir / "app.py"

        # Ensure idempotency when regenerating app.py in an existing directory
        studio_meta_dir = self.output_dir / "__marimo__" / "studio"
        if studio_meta_dir.exists():
            shutil.rmtree(studio_meta_dir, ignore_errors=True)

        graph.save_json(lineage_json_path)
        traces_json_path.write_text(
            json.dumps([t.model_dump(mode="json") for t in traces], indent=2),
            encoding="utf-8",
        )
        memory_rules_path.write_text(
            json.dumps(memory_payload, indent=2),
            encoding="utf-8",
        )

        notebook_code = _generate_notebook_source(
            app_title=app_title,
            user_need=user_need,
            notebook_path=notebook_path,
            data_dir=self.data_dir,
            lineage_json_path=lineage_json_path,
            traces_json_path=traces_json_path,
            memory_rules_path=memory_rules_path,
        )
        notebook_path.write_text(notebook_code, encoding="utf-8")

        views = asyncio.run(self._author_and_build_views_async(notebook_path, app_title))

        return GeneratedStudioBundle(
            output_dir=str(self.output_dir),
            notebook_path=str(notebook_path),
            lineage_json_path=str(lineage_json_path),
            traces_json_path=str(traces_json_path),
            views=views,
            launch_edit_command=f'uv run marimo edit "{notebook_path}" --watch --no-token',
            launch_run_command=f'uv run marimo run "{notebook_path}"',
        )

    async def _author_and_build_views_async(
        self,
        notebook_path: Path,
        app_title: str,
    ) -> list[StudioViewSummary]:
        """Use `marimo_studio.authoring.open_workspace` to create, author, build, and runtime-validate 3 Studio views."""
        workspace = open_workspace(notebook_path)
        status = await workspace.status()
        existing_names = {v.name for v in status.views}

        nav_views = [
            ("main", "Overview", "lucide:layout-dashboard"),
            ("audit", "Sources & QA", "lucide:git-branch"),
            ("ops", "Data & operations", "lucide:terminal"),
        ]

        view_specs = [
            (
                "main",
                "Overview & scenarios",
                "Review key metrics, adjust scenarios and inspect the underlying data.",
                [
                    ("kpi_cards", "Key metrics", "Values with their sources, quality checks and uncertainty ranges."),
                    ("header_overview", "Scenario controls", "Adjust sensitivity parameters and trust filters."),
                    ("interactive_simulation", "Explore data", "Inspect datasets and scenario effects."),
                ],
            ),
            (
                "audit",
                "Sources & calculation checks",
                "Trace a number to its source and inspect quality checks and assumptions.",
                [
                    ("calculation_lineage_view", "End-to-End Calculation Lineage DAG", "Trace every number back to raw Excel cells, PDF pages, code lines, and formulas."),
                    ("pointblank_qa_view", "Posit Pointblank Data Quality & Epistemic Caveats", "Row-level validation pass rates and explicit assumptions registry."),
                ],
            ),
            (
                "ops",
                "Data & operations",
                "Explore data with visible read-only SQL and inspect recorded failure prevention rules.",
                [
                    ("querychat_view", "Transparent QueryChat Explorer", "Natural language & SQL exploration with exposed executable code."),
                    ("adaptive_memory_view", "Self-Evolving Local & Global Failure Memory", "Verified failure-to-fix episodes and cross-project prevention rules."),
                ],
            ),
        ]

        summaries: list[StudioViewSummary] = []
        for view_name, v_title, v_subtitle, cell_sections in view_specs:
            if view_name in existing_names:
                view = workspace.view(view_name)
            else:
                view = await workspace.create_view(view_name)

            doc = await view.read("index.html")
            html_content = _render_studio_view_html(
                app_title=app_title,
                view_title=v_title,
                view_subtitle=v_subtitle,
                cell_sections=cell_sections,
                nav_views=nav_views,
                active_view=view_name,
            )
            await view.write("index.html", html_content, expected_revision=doc.revision)
            if view_name == "main":
                await view.make_default()

            build_res = await view.build()
            val_res = await view.validate(level="runtime", runtime_timeout=60.0)
            insp = await view.inspect()

            diags = [f"{issue.code}: {issue.message}" for issue in val_res.issues]
            summaries.append(
                StudioViewSummary(
                    view_name=view_name,
                    root_dir=str(insp.root),
                    build_revision=build_res.revision,
                    validation_passed=val_res.ok and len(diags) == 0,
                    diagnostics=diags,
                )
            )

        return summaries

