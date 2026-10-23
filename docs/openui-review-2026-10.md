# OpenUI and the next architecture step

**Reviewed: 2026-10-23.** This is an engineering assessment of the checked-out
Nouc implementation and the upstream sources linked below. Proposed changes are
not implemented features. No OpenUI runtime has been installed or benchmarked
inside Nouc for this review.

## Recommendation

Borrow the component catalog, typed proposals and progressive rendering ideas.
Keep Marimo as the working execution and authoring environment while measuring
whether another renderer improves actual tasks. Nouc's useful distinction is a
number connected to its inputs, checks and assumptions. A generated interface
should preserve that evidence boundary.

The next experiment should let a model select approved components and existing
metric IDs. The backend supplies values, units and caveats. Avoid a rewrite of
the notebook, calculations and UI in one step: that would make regressions hard
to attribute. This sequencing is a recommendation based on the current code,
not a performance result.

## Which OpenUI?

| Project | Verified purpose | Fit for Nouc |
| --- | --- | --- |
| [Thesys OpenUI](https://github.com/thesysdev/openui) | Component libraries, generated prompts, a streaming UI language and multiple frontend runtimes | Candidate for a constrained presentation adapter |
| [W&B OpenUI](https://github.com/wandb/openui) | Describe and refine a UI, preview it, and convert HTML to frameworks | Useful authoring/prototyping ideas; not an evidence model |

The Thesys repository's `@openuidev/react-lang` manifest declares **1.0.1** at
commit `c9f93b6e57d05b19b9781846769da530c6741dc4`, dated 2026-10-23. This is a
source snapshot, not a claim about what a package registry will resolve later.
See the [pinned package manifest](https://github.com/thesysdev/openui/blob/c9f93b6e57d05b19b9781846769da530c6741dc4/packages/react-lang/package.json).

OpenUI's current documentation includes reactive state, actions, queries and
mutations. It can serve app surfaces as well as chat. Its own component catalog
defines the capabilities available to generated output. See
[OpenUI Lang](https://www.openui.com/docs/openui-lang).

## Compare the right layers

| Option | What it provides | What Nouc still owns | Assessment |
| --- | --- | --- | --- |
| Existing Marimo Studio | Reactive Python notebook and projected views | Business rules, evidence and task design | Keep as the baseline |
| Thesys OpenUI | Compact streaming language and component rendering | Trusted data binding, authorization, state bridge and evidence UI | Evaluate after defining the contract |
| [json-render](https://json-render.dev/docs) | Typed component/action catalog, JSON specs, bindings and streaming patches | The same calculation and permission boundaries | Useful comparison with familiar JSON tooling |
| [A2UI](https://a2ui.org/) | Declarative UI protocol and native component catalogs | Renderer integration, data policy and business semantics | Consider when multiple clients or agents must interoperate |
| [AG-UI](https://docs.ag-ui.com/introduction) | Events connecting agent state, tools and user interactions | UI representation, calculations and renderer | A transport/state concern; can complement the options above |

At this review date, A2UI identifies **v0.9.1 as current** and **v1.0 as a
candidate**. Pin a protocol version rather than designing against an unspecified
“latest.” Its official [version overview](https://a2ui.org/) and
[renderer roadmap](https://a2ui.org/roadmap/) describe the supported surfaces.

Do not choose an architecture from token counts alone. Thesys publishes a
seven-scenario representation benchmark; its [product page](https://www.openui.com/)
also presents other headline comparisons. These are vendor measurements, with different scopes,
not Nouc end-to-end results. Measure validity, repair attempts, time to a usable
screen and task completion using identical data, component catalogs and models.
See the [benchmark methodology](https://www.openui.com/docs/openui-lang/benchmarks).

## Ideas to adopt

1. **A small, versioned component catalog.** Start with a metric, a table, a
   filter and a trace detail. Define their permitted props and actions from one
   schema; derive both model instructions and validation from it. Use stable
   semantic IDs instead of model-written HTML, SQL or JavaScript.
2. **Backend-owned evidence.** A metric component accepts a metric ID and a
   result revision. Its value, unit, source references, grade and material caveats
   come from the same backend result. An interface proposal cannot overwrite
   them or remove required warnings.
3. **Useful progressive rendering.** Show pending, incomplete, failed and ready
   states explicitly. Keep the previous valid result until a replacement is
   validated. Partial output must never resemble a completed verified figure.
4. **Separate calculation and presentation state.** Record dataset revision,
   scenario parameters, metric selection and UI layout separately. A stale
   response must not overwrite a newer scenario. Retain selection when opening
   and closing a trace.
5. **Observable failures and reversible edits.** Record schema errors and
   rejected proposals locally; show recoverable error states. Bound retries and
   retain the last valid proposal. Review telemetry payloads before any export.

These are proposed Nouc rules. The
[executable contract example](../examples/ui_contract.py) implements only metric
selection, strict shape validation and trace binding. It does not implement the
renderer, result revisions, authorization, streaming or action execution.

## Costs and boundaries of an OpenUI adapter

A frontend adapter needs a bridge to the notebook's reactive state, tested
component mappings, lifecycle handling, asset packaging and another dependency
lock. A separate web client would also need session authorization and a result
API. A browser-bundle or embedded renderer could reduce setup work, but would
still need integration tests with Studio's projected cells and capabilities.
No drop-in Marimo adapter has been demonstrated in this repository.

OpenUI Gateway forwards requests to model providers and corrects generated
output; its documentation states that Gateway and Autofix automatically enable
reliability monitoring. Those services introduce a separate data-flow decision.
Keep the first experiment on synthetic data with explicitly chosen inference
and telemetry settings. Local inference does not by itself establish that every
other component is local. See [Gateway](https://www.openui.com/docs/gateway) and
[monitoring](https://www.openui.com/docs/reliability).

Registered components and schema validation constrain presentation. They do not
prove a business result, authorize a data read or sandbox a tool implementation.
Keep calculation execution, query permissions and publish/export actions on the
backend. Review every newly registered action as an additional capability.

## Challenge the existing implementation first

| Priority | Finding in current code | Proposed change and acceptance condition |
| --- | --- | --- |
| P0 | The [builder](../src/nouc_studio/agents/specialists.py) copies global and local memory into the bundle | Default exports to reviewed rules only; a canary secret in either memory tier must never reach public artifacts |
| P0 | [QueryChat](../src/nouc_studio/studio/querychat_engine.py) and the [generated SQL cell](../src/nouc_studio/studio/generator.py) use different keyword filters | Use one bounded executor with table/function permissions, disabled external access and host isolation; test both paths against local-file reads and multiple statements |
| Resolved in this work | The [build CLI](../src/nouc_studio/cli.py) previously printed “Deliverable Ready” despite failed report fields | Notebook, view, QA and explanation failures now return nonzero; regression tests inject each failed gate. Browser acceptance remains separate. |
| P1 | The [planner](../src/nouc_studio/agents/specialists.py) relies on column order and name heuristics; empty ingestion can create synthetic data | Add explicit metric definitions, units and population rules; require a named demo mode for fallback data; compare against independently calculated fixtures |
| P1 | [Uncertainty](../src/nouc_studio/graph/uncertainty.py) uses configured penalties and quadrature; a legacy field says `confidence_interval_95` | Introduce an explicit method and unknown state; test correlated sources, missing validation and stale dependencies; migrate the serialized field compatibly |
| P1 | [Explanation audits](../src/nouc_studio/verification/deepeval_auditor.py) check textual mentions and heuristic scores | Separate disclosure checks from correctness checks; test wrong values, wrong denominators and unsupported claims against independent expected outcomes |
| P1 | [Scenario cards](../src/nouc_studio/studio/generator.py) scale row counts, omit per-metric caveats and can fall back to a 98% badge; audit keeps baseline values | Bind every displayed scenario value to the same result revision and trace; retain warnings; test count invariance and missing confidence explicitly |
| P1 | [Bundled memory seeds](../src/nouc_studio/memory/store.py) are marked verified at creation and include version-sensitive advice | Attach library versions and verification receipts; revalidate a rule before promoting a fix; distinguish seed guidance from observed failures |
| P1 | The [generator](../src/nouc_studio/studio/generator.py) combines notebook logic, HTML, scripts and styling in a large source template | Extract cohesive templates/components incrementally; retain the same domain fixtures and browser workflows across the change |
| P2 | Five sequential stages are described as multi-agent orchestration; the optional LLM adds one assumption and swallows errors | Name current execution plainly; report enrichment failures; add autonomous planning only if it improves task success over the deterministic baseline |

DuckDB explicitly treats untrusted SQL as executable code and describes
`enable_external_access` and configuration locking as additional safeguards.
Keyword filtering or a database opened read-only is insufficient isolation.
Follow its [security guidance](https://www.duckdb.org/docs/current/operations_manual/securing_duckdb/overview)
when implementing the executor. The public walkthrough uses fixed trusted inputs;
this review does not change the core executor.

## A bounded experiment

Keep one reviewed dataset and backend result fixed. Compare the current Studio
with a catalog-driven Marimo composition, then with an OpenUI adapter only if
the first experiment leaves a concrete task unmet. Include json-render if a
separate frontend is justified.

Use twelve repeatable tasks covering metric selection, filtering, trace lookup,
scenario changes, empty results, failed QA, unknown metrics, stale updates and
malformed proposals. Run each generation task several times and record the
model, prompt/catalog revision, settings, valid first responses, repairs, tokens,
latency and completion outcome. Check 1440×900 and 1280×800, keyboard access and
visible warnings. Do not substitute screenshots for interaction tests.

Stop a candidate if it changes an authoritative value, silently drops a material
warning or grants an unregistered capability. Adopt it only if measured task
completion or maintainability improves enough to pay for the new integration.
All comparisons in this paragraph are an experiment plan, not completed results.
