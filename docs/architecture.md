# How Nouc Studio works

Nouc combines a deterministic analysis pipeline with instructions for an external
coding agent. Keep these two paths distinct: the agent can implement an agreed
business workflow; the generic CLI currently constructs exploratory summaries.

This guide describes the source reviewed on **2026-10-23**. The
[OpenUI review](openui-review-2026-10.md) proposes changes separately.

## From files to views

| Stage | Current behavior | Source |
| --- | --- | --- |
| Ingest | Read supported files; persist tables; record hashes, coordinates and code symbols | [ingestion](../src/nouc_studio/ingestion/pipeline.py) |
| Plan | Count rows; summarize the first three numeric columns; avoid totals for recognized non-additive names | [specialists](../src/nouc_studio/agents/specialists.py) |
| Compute | Evaluate planned expressions in Monty; run Pointblank checks; connect sources, assumptions, transforms and metrics | [builder](../src/nouc_studio/agents/specialists.py) |
| Generate | Write a reactive notebook, JSON evidence and three Studio projections | [generator](../src/nouc_studio/studio/generator.py) |
| Verify and report | Check the notebook; attempt Ruff repair; audit explanation text; write an orchestration report | [orchestrator](../src/nouc_studio/agents/orchestrator.py) |

The orchestrator records five sequential stages, with publication represented by
local report writing. It does not deploy a web service. A graph of stages does
not imply concurrent or autonomous model agents.

The optional PydanticAI call produces one short assumption. It does not choose
formulas or turn a methodology document into executable policy. Failures in that
optional call are currently swallowed. The default planner also creates a
synthetic fallback table when no usable artifacts are ingested. Inspect the
manifest before interpreting any generated number as a source observation.

## Data and calculation evidence

The [graph models](../src/nouc_studio/graph/models.py) represent source files and
fragments, code symbols, transformations, checks, assumptions and metrics.
`MetricLineageTrace` collects a metric's ancestors, ordered steps, uncertainty and
explanation. Source coordinates vary with the reader: a sheet range, document
page, code line span or file reference has different precision.

The graph records what the pipeline computed and where inputs came from. It
does not establish that the chosen population, units, aggregation or business
definition is correct. A source hash establishes byte identity, not truth.
An average of cohort rates is descriptive unless the denominator and weighting
policy are supplied. Parsing a Python file for AST symbols does not execute it.

The generated notebook reloads data and evidence from its output directory.
Its `main`, `audit` and `ops` projections share the reactive notebook. The scenario
slider applies generic percentage changes; it is not a domain forecasting model.
It currently scales numeric row-count metrics too, while audit retains the
baseline trace. Main cards omit per-metric caveats and can display a fallback
98% confidence score. Reset the scenario before comparing with saved evidence.
The generated SQL view and the separate
[`TransparentQueryChatEngine`](../src/nouc_studio/studio/querychat_engine.py)
currently have different implementations. The latter synthesizes a few query
patterns from keywords; the generated view accepts SQL directly.

## What verification establishes

| Check | Establishes | Requires a separate check |
| --- | --- | --- |
| Ruff and ty | Selected lint and type rules | Business meaning |
| Marimo DAG and execution | Cell dependencies and runtime behavior | Every user interaction |
| Monty | Supplied expression or assertion executes within its configured limits | Correctness of an untested formula |
| Pointblank | Supplied data checks pass or fail | Policies absent from the check plan |
| Layout checks | Selected properties of generated markup | Actual desktop usability |
| Explanation audit | Heuristic checks for value, source and uncertainty mentions | Independent semantic validation |

`nouc verify` supplies a generic `1 + 1 == 2` Monty assertion. Add meaningful
domain invariants when implementing a business workflow. The module named
`deepeval_auditor` uses local heuristics; its name does not establish that an
external DeepEval evaluation ran. Browser acceptance means exercising the
actual running Studio, not only evaluating notebook cells.

The current build CLI does not convert every failed report into a nonzero exit
status. The [walkthrough](../examples/offline_walkthrough.py) explicitly checks
the report, view validations, explanation audits and expected fixture figures.

## Interpreting uncertainty

[`propagate_uncertainty`](../src/nouc_studio/graph/uncertainty.py) combines configured
relative uncertainty terms and quality penalties. Trust grades use fixed
thresholds. Independence assumptions, correlated ancestors and unknown
uncertainty need domain review; the scores have no established empirical
calibration in this repository.

The generic range is stored in the legacy `confidence_interval_95` field.
Display it as a **heuristic range**, with assumptions and caveats. Do not infer
95% coverage or treat a missing range as zero uncertainty. `A` describes the
current scoring rule, not independent certification of the calculation.

## Execution and privacy boundaries

Marimo's `--sandbox` creates a separate dependency environment from notebook
metadata. It is not, by itself, an operating-system isolation boundary for
untrusted notebook code. Monty constrains snippets evaluated through its own
runner; the rest of the Python pipeline still executes in the host process.
See [Marimo sandbox documentation](https://docs.marimo.io/guides/package_management/sandboxes/).

SQL keyword filtering does not restrict all DuckDB file, network or extension
capabilities. Treat the prototype explorer as a trusted local tool. A shared
service needs a constrained query executor plus process/container isolation,
resource limits and authorization. See
[DuckDB's security model](https://www.duckdb.org/docs/current/operations_manual/securing_duckdb/overview).

The memory stores persist raw diagnostic episodes. The builder serializes both
tiers into generated artifacts. Use isolated memory for public examples and
review exports separately from Git's ignore rules. The
[public-data guide](public-data.md) describes the current boundary and its limits.

Fresh memory stores are populated with bundled seed episodes. Their `verified`
flag is stored metadata, not evidence of a check performed in the current run.
Recheck version-sensitive advice against the installed API and current upstream
documentation. Symbol existence alone does not establish behavior or provider
model availability.

## Extension points

Keep a business metric specification separate from its presentation. Supply
explicit formulas, units, snapshot rules, exclusions and expected outcomes;
connect them to lineage and QA before selecting UI components. Preserve the
source notebook and existing renderer while evaluating alternative interfaces.

The [UI contract example](../examples/ui_contract.py) demonstrates one proposed
boundary: a caller chooses a known metric ID and the backend supplies its value
and evidence. It adds no OpenUI runtime, renderer or production API.
