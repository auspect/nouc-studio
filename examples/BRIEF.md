# Public documentation examples

## Objective and scope

Help a contributor run the existing exploratory pipeline, inspect its evidence,
and evaluate a constrained UI contract. This is developer documentation, not a
new business application or an OpenUI integration. Repository prose is English.

Review date: **2026-10-23**. Use the repository's locked environment. Only the
six synthetic rows in `sample_bundle/quarterly_financials.csv` are inputs to the
walkthrough. Do not inspect or reuse user input folders, prior tester answers,
private reports, credentials, or cross-project memory as example material.

## Data and rules

- The six rows form the whole teaching dataset. No reporting date is encoded;
  the filename does not establish a quarter or a current market observation.
- Revenue and operating cost use synthetic USD amounts. `latency_ms` contains
  example measurements. Its mean is descriptive, not a pooled percentile.
- Expected coverage is six rows; revenue totals USD 691,900 and operating cost
  totals USD 252,100. No currency conversion, valuation or forecasting applies.
- Use the existing generic planner. It does not execute the pricing Python file
  or implement policies from the methodology document.
- Force the example's model to `offline`, disable `.env` loading, and allocate
  fresh temporary directories for both memory tiers. Generated artifacts remain
  local under ignored `dist/`. Refuse an existing output directory.

## Acceptance

The walkthrough must produce three Studio views, pass the existing verification
gate including ty, and independently check the three expected figures above.
The UI contract example must reject unknown components, unknown metric IDs and
caller-supplied values. Resolve values, units, grades and caveats from the backend
trace. Run without a model, JavaScript dependency or external service.

Keep executable examples separate from generated artifacts. Review new and
modified public text for secrets, identifying paths and private case details.
Keep package source allowlists narrow. No push or package publication is part of
this work.

## Desktop check scope

The walkthrough generates the existing Studio template without changing its UI.
Its target workflow is overview → select a metric in audit → inspect source and
QA → inspect the table in operations. Use 1440×900 and 1280×800 for browser
acceptance. Keep full evidence in audit/detail views and material warnings beside
the metric. Runtime/static checks alone do not establish browser acceptance.
Record an unverified browser gate if a browser cannot be used. The contract
example emits JSON and does not render a UI.

## Review outcome

The executable and privacy checks passed on 2026-10-23. A UI/UX specialist
checked the rendered overview at both desktop sizes and opened scenario controls
at the larger size. The remaining reactive workflows are unverified; this is
not full UI acceptance. Existing scenario/evidence and confidence-display
limitations are documented in `README.md` and the architecture review.
