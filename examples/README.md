# Run the public examples

These examples teach the existing pipeline and one proposed UI boundary. They
use synthetic data and need no model API key. Run commands from a source
checkout after `uv sync --locked`; these scripts are not installed in the wheel.
The [working brief](BRIEF.md) records scope, units and acceptance conditions.

## 1. Build and verify a Studio

```bash
uv run python examples/offline_walkthrough.py
```

The script reads only `sample_bundle/quarterly_financials.csv`. It disables
`.env` loading, forces the model to `offline` and gives both memory tiers fresh
temporary directories. This prevents existing cross-project episodes from
entering the example. Nouc still seeds those directories with its bundled
engineering rules; their presence is not a record of failures in this run.
The script refuses to overwrite an existing output directory:

```bash
uv run python examples/offline_walkthrough.py --output dist/public-example-rerun
```

The default output is `dist/public-example/`. A successful run checks:

| Figure | Expected result |
| --- | ---: |
| Input rows | 6 |
| Sum of synthetic revenue | 691,900 |
| Sum of synthetic operating cost | 252,100 |

The teaching amounts use USD. The CSV names these columns `revenue` and
`operating_cost`, so the generic planner currently labels their sums as `total`;
it cannot infer USD from the CSV alone. A business implementation must supply
units explicitly. The dataset has no encoded reporting date. Its descriptive
mean latency does not establish a pooled percentile.

The script also checks all three views, the build report, explanation audits and
the notebook verification gate including ty. It exits nonzero if a required
check fails. Its console summary labels browser acceptance as unverified because
the script does not drive a browser.

| Artifact | Purpose |
| --- | --- |
| `app.py` and `__marimo__/studio/` | Reactive notebook and built `main`, `audit`, `ops` projections |
| `data/` | Ingested tables |
| `lineage_graph.json`, `lineage_traces.json` | Source relationships and metric evidence |
| `orchestration_report.json` | Build stages, metrics and checks |
| `example_verification.json` | Additional verification with ty |
| `adaptive_memory_snapshot.json` | Snapshot of the isolated example memory |

Keep these generated artifacts local: they can contain source paths and runtime
metadata even with synthetic inputs. See [public data](../docs/public-data.md).

## Open and exercise the existing views

```bash
uv run nouc studio dist/public-example/app.py
```

Use the URL printed by Marimo. The launcher builds production views and passes
`--no-sandbox` to reuse the locked project
environment. For editing, replace `run` with `edit` and add `--watch`.

At 1440×900, then 1280×800, verify overview navigation, a sensitivity change,
metric selection in audit, visible source/QA details, and a SQL query in operations.
Use the displayed table name for `SELECT * FROM <table> LIMIT 3`. Confirm the
result changes, text remains readable and required warnings stay visible.
The generic gate does not perform these browser checks.

**Existing template limitations:** the generic slider scales every numeric
metric, including row counts, while audit traces retain baseline values. Reset
the slider to zero when comparing displayed figures with the saved evidence.
Main cards do not show each metric's full assumptions/caveats; inspect audit.
Their confidence badge can fall back to 98% when the score is absent from saved
JSON. Treat these as prototype limitations, not calibrated confidence or a
validated business scenario. The contract example below proposes a stricter
evidence boundary; it does not repair the existing template.

## 2. Select a metric without supplying its value

```bash
uv run python examples/ui_contract.py
uv run python examples/ui_contract.py --traces dist/public-example/lineage_traces.json
```

The first command uses an intentionally incomplete synthetic trace, with grade
`F` and an explicit caveat. The second uses the first metric from the walkthrough.
Both print resolved JSON, not a rendered UI.

The proposed request format is deliberately small:

```json
{
  "schema_version": "nouc-ui-proposal/1",
  "cards": [
    {"component": "metric_card", "metric_id": "synthetic_revenue"}
  ]
}
```

Save a proposal locally and pass `--proposal <path>`. Use an actual metric ID
from the selected trace file when passing `--traces`. Unknown components,
unknown/duplicate metric IDs, extra fields and caller-supplied values are rejected.
The backend trace supplies label, value, unit, grade, range and caveats.

This is a Nouc design example inspired by component catalogs, **not OpenUI Lang
or A2UI syntax**. It has no renderer, authentication or action executor. A real
service must select authorized backend traces itself; accepting arbitrary caller
trace files would not establish trustworthy evidence. See the
[dated architecture review](../docs/openui-review-2026-10.md).

## Existing multimodal fixtures

The three domain bundles demonstrate readers for spreadsheets, documents,
images, source code and Parquet. Their filenames, model names and economic or
clinical figures are synthetic teaching material, not current factual sources.
The generic output does not implement retention, survival analysis or FinOps
policy from those files.

To regenerate one bundle, direct generated inputs and output to ignored paths:

```bash
uv run nouc demos --demo demo_3_finops --examples-dir dist/generated-inputs --dist-dir dist/generated-studios
```

That command uses the normal CLI configuration and memory stores. Follow the
[public-data guide](../docs/public-data.md) before sharing its artifacts; the
isolated walkthrough is the recommended starting point for public examples.
The `sample_bundle` methodology and pricing source illustrate document/AST
ingestion. The walkthrough deliberately reads only the CSV.

## Verification recorded on 2026-10-23

Both example commands ran on Linux with Python 3.14.3, Marimo 0.25.1 and
marimo-studio 0.3.0. Expected figures, the verification gate with ty, the full
repository test suite and the additional privacy regression passed. That
regression supplies a synthetic private-memory canary and an invalid caller
`.env`, then checks that the example ignores them. Ruff, ty and Python archive
inspection also passed. The suite reported one upstream google-genai
deprecation warning under Python 3.14.

A UI/UX specialist exercised the running overview in Chromium at 1440×900 and
1280×800. Navigation and a real scenario change were checked: +1% changed the
visible revenue total from 691,900 to 698,819. An external Python edit in an
isolated copy appeared after running pending cells and retrying preview.
See [launch validation](../docs/studio-launch.md#validation-recorded-on-2026-10-23).
**Full business workflow acceptance remains incomplete:** these checks do not
establish audit selection, SQL result correctness or context retention across
every view. No browser recordings or generated app artifacts are published.
