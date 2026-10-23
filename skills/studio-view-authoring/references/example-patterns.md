# Patterns from the official Studio examples

Reviewed on 2026-10-23 against upstream commit
[`37571a3`](https://github.com/marimo-team/marimo-studio/tree/37571a33ea4779a0cec398eb65c9f0a9e4eca862/docs/examples).
These are design patterns to adapt, not a promise that every current upstream
provider runs on Nouc's locked Studio 0.3.0. Ground installed APIs first.

## Select views by the user's task

| Official example | Concrete mechanism | Useful Nouc adaptation |
| --- | --- | --- |
| [Quadratic programs](https://marimo-team.github.io/marimo-studio/examples/quadratic-programs.html) | A common optimization notebook feeds a lesson deck, reading page, geometry lab and typeset report. Native controls choose parameters; a precomputed sweep supports browser exploration. | Pair a concise explanation with an interactive scenario view. Compute and test scenario results in Python; let the view select supported results. |
| [Rio athletes](https://marimo-team.github.io/marimo-studio/examples/athletes.html) | Overview totals use `mo-value`; a native sport filter updates a roster and chart. Mosaic coordinates browser selection over the projected table. A paper uses the same fitted values. | Give an overview and a row explorer the same result contract. Distinguish a local brush selection from a filter that changes audited totals. |
| [Earthquake watch](https://marimo-team.github.io/marimo-studio/examples/earthquakes.html) | An operations map, priority list and summary share filtered membership. Story, briefing and bulletin reuse one `seismic_analysis` result. | Export one result containing the selected rows, totals, thresholds and caveats. Project it into the operations view and the explanatory report so they agree. |
| [Building occupancy](https://marimo-team.github.io/marimo-studio/examples/occupancy.html) | A monitor shares sensor baselines and anomalies with a PDF report and model review. Threshold exploration selects notebook-computed operating points and error evidence. Report prose handles a scope with no occupied readings. | Treat threshold choice as a decision supported by tradeoffs and examples. Include empty-scope prose and denominators, not just a score. |

Do not automatically reproduce the 3D presentation, every report format or every
framework. Select the smallest set that serves the agreed workflow. Nouc's
existing overview/audit/explorer is a starting arrangement; the names alone do
not make an app useful.

## A reusable result contract

For an operations screen, a notebook result might contain:

```python
operations_result = {
    "scope": scope_label,
    "snapshot": snapshot_label,
    "units": {"amount": "USD"},
    "summary": {"count": len(selected_records), "amount": selected_amount},
    "records": selected_records,
    "excluded_count": excluded_count,
    "caveats": current_caveats,
}
```

These names illustrate a contract, not an implemented Nouc API. Decide the
business meaning before filling it. Compute the fields once in Python. Render
the count, records and exclusions from the same filtered population. Add lineage
IDs and uncertainty fields according to the existing epistemic skill.

For a scenario, prefer a native marimo control when Python must recompute an
arbitrary input. A finite precomputed grid is appropriate for a bounded model
review; label its available states and do not interpolate an unsupported answer.
Keep a scenario's audit evidence synchronized with its result.

## Choose delivery deliberately

Default to the local Python server for Nouc's native dependencies and local data.
The upstream gallery often uses **Prepared** exports: its visible interactions
can select precomputed states without running Python. That is not proof that a
new arbitrary input will work in a static export. Browser/Pyodide mode has a
different dependency and data-access boundary.

Map libraries, fonts, CSV feeds, PDF engines and framework assets can require
network access even when no LLM is called. Prepared exports can include records
from states that are not initially selected. Review the entire export before
sharing it; use synthetic or explicitly public data for repository examples.

Read the installed `delivery.md` reference before implementing an export. Test
the actual delivery mode over HTTP, including its controls and empty states.
