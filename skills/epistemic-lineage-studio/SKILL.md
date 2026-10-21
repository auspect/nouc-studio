---
name: epistemic-lineage-studio
description: >-
  Designs and builds multi-view Marimo Studio applications where every number is backed
  by a Rustworkx Calculation Lineage DAG, exact source file coordinates (SHA-256, sheet/cell,
  page/line), Posit Pointblank data quality proofs, QueryChat transparent SQL, and explicit
  epistemic uncertainty metadata (TrustGrade A-F, supported bounds and caveats).
---

# Epistemic Lineage & Multi-View Marimo Studio Skill

## Philosophy: Proof Over Pretty Code

In immature projects, new features, or high-stakes audits, stakeholders cannot trust a number simply because the UI or code looks clean. Every metric in a `nouc-studio` Studio application MUST carry:
1. **Source Provenance**: Exact file path, SHA-256 hash, and physical coordinates (`sheet_name` + `cell_range` for Excel, `page_number` for PDF/PPTX, `line_start`-`line_end` for Markdown/Code).
2. **Transformation Trace**: The exact Polars expression or read-only DuckDB SQL query (`QueryChat` pattern) that computed the number, plus its mathematical LaTeX formula.
3. **Validation Proof**: Posit `pointblank` interrogation pass rate (`col_exists`, `col_vals_not_null`, domain range checks) and `pydantic-monty` invariant checks.
4. **Uncertainty & Epistemic Humility**:
   - Quantitative sensitivity/scenario bounds `[low, high]` where evidence supports
     them, explicitly labelled with their method and scope. Heuristic ranges are
     not statistical 95% confidence intervals; use a confidence level only when
     a justified statistical model establishes it.
   - Relative epistemic uncertainty `±X.X%` where quantifiable. If a bound or
     percentage cannot be established, mark it unknown with the reason; do not
     invent precision or equate missing uncertainty with zero.
   - Discrete `TrustGrade` (`A` through `F`)
   - Explicit list of assumptions and data completeness caveats.

## External Source and Update Integrity

- Bind each business key to the identity actually returned by the source, with
  inspectable supporting evidence. A query parameter or requested URL alone is
  not identity proof. Retain a source receipt and record the value's unit,
  measurement basis, currency, source as-of time and fetch time separately.
- Reconcile only observations that are genuinely comparable at the snapshot of
  the chosen figure, including identity, basis, units and as-of date. An earlier
  agreement or a list of raw source names does not corroborate the current
  figure. Explain any normalization and the observations actually compared.
- Missing or incomparable corroboration must produce a visible uncorroborated
  state, not grade A. Propagate unavailable or stale dependencies, including
  exchange rates, into the derived figure's grade, caveats and exclusions; a
  fresh primary observation does not refresh its dependencies.
- For imports and partial updates, distinguish omitted fields from explicit
  values and explicit clearing. Preserve existing values when a field is
  omitted; clearing requires an explicit supported action.
- Add meaningful adversarial tests for a returned identity mismatch, misaligned
  as-of dates, a stale dependency and a partial mutation. Assert the resulting
  evidence, visible trust state and preserved data, not merely successful
  parsing or a nonempty graph.

## Required Multi-View Studio Architecture

Every generated `marimo-studio` application provides synchronized views over the reactive notebook:
- **`executive`**: High-level interactive KPIs (with TrustGrade and supported uncertainty indicators), relevant scenario controls (`wigglystuff` / `mo.ui`), and key visual insights.
- **`audit_lineage`**: Complete calculation DAG visualization (`Mermaid` + step-by-step trace table) allowing meticulous auditors to inspect every intermediate step from raw files to final figures.
- **`telemetry_memory`**: Pointblank data quality scorecard, transparent `QueryChat` SQL/Polars explorer, and self-healing agent memory & verification logs.

## Evidence Without an Overloaded Desktop

Apply [studio-experience-design](../studio-experience-design/SKILL.md) before UI
code and for final browser acceptance. Let a UI/UX specialist subagent review the
design and rendered workflows when delegation is available; otherwise explicitly
self-review. Desktop is the default target, with useful first-screen content,
compact readable tables and minimal justified scrolling.

The evidence requirements describe available metadata, not a mandate to display
every proof at once. Keep grade, material warnings, missing-data status and
exclusions beside the affected figure. Put full source coordinates, formulas,
SQL, validation detail and memory logs in discoverable audit views or selected
details. Group related cells into coherent task panels, not a new tab per small
output. Scope a lineage graph to the selected metric's ancestors for readability;
keep the full trace accessible. Never hide a material failure inside a collapsed
proof without a visible summary.

Run `uv run nouc verify <app.py> --ty`, meaningful domain checks, and the desktop
browser gate on real workflows. A generic verification report does not establish
that the projected Studio is readable or usable at its actual viewport.
