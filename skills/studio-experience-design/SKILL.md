---
name: studio-experience-design
description: >-
  Design and review desktop-first Nouc Studio applications, dashboards and business
  workflows before implementation and in a real browser. Use for screen layout,
  compact readable tables, task-oriented controls and progressive disclosure.
---

# Desktop Studio Experience Design

Make the user's recurring task efficient on a desktop screen. Desktop is the
default design target for Nouc Studio; do not let mobile layouts dictate desktop
density, navigation or interaction. Honor an explicitly different user target.
This skill complements the agreed business brief and the required multi-view
Studio architecture; it does not introduce business policies or replace intake.

## UI/UX specialist role

Before UI implementation, assign a UI/UX specialist subagent when the host
actually exposes delegation. Give it the agreed task, relevant input schema,
existing application conventions and target desktop viewport. Ask for a compact
screen plan and the highest-impact usability risks. Keep business calculations
and policy decisions with the implementing agent and user.

The specialist owns information hierarchy, navigation, control choice, table
density, progressive disclosure and browser usability review. It can challenge
a technically correct screen that is cumbersome to use. Resolve its material
findings before completion. Do not invent a VS Code agent/tool or require a
particular provider. Without delegation, perform the same role as an explicit
design and usability self-review. Delegation does not expand authorization.

## Before code: a small desktop screen plan

Reuse intake answers. Ask only about a consequential unresolved workflow or
constraint; do not add a questionnaire about colors, cards or cosmetic layout.
Record the following in a short section of the existing working brief:

- The primary user task and its shortest path; secondary tasks belong behind
  an appropriate tab, row detail, menu or advanced disclosure.
- The desktop viewport, visible first-screen content, navigation and the one
  or two main work areas. Use the actual browser size when available; otherwise
  start at 1440×900 and plan a check at a smaller desktop size such as 1280×800.
- The main table/chart, useful default columns, filters and editing/selection
  controls; explain where longer audit details and justified scrolling live.
- Observable success: for example, find a record, filter it, inspect its source
  and return without losing context. Include relevant empty, error and saved states.

Keep this a reviewable plan, not a separate large design report or new approval
round. Sketch or inspect a simple wireframe when spatial choices are unclear.

## Desktop layout and disclosure

- Use the available desktop width deliberately. Keep the page title, relevant
  context and primary action easy to find; place closely related controls near
  the content they affect. Size panels to the viewport rather than stacking every
  notebook output in one long document.
- Make the primary task useful on the first screen at normal zoom. Scrolling
  is justified for long records, substantial tables or detail; it is not a cure
  for oversized headers, excessive cards, blank space or duplicate summaries.
  Prefer one predictable page scroll or one clearly bounded data region; avoid
  competing nested scrollbars. Do not hide essential controls below tall outputs.
- Choose a few stable navigation destinations. Use tabs for peer views, a side
  panel or selected-row detail for context, and accordions for optional evidence.
  Keep the active record, filters and selection when changing views where useful.
  Group related notebook cells into cohesive task panels; do not make every small
  output or paragraph a separate tab.
- When using Nouc's shell, ground the public
  `nouc_studio.studio.generator.render_studio_view_html` helper first. Compose
  related controls and results into cohesive projected cells: the shell provides
  compact section navigation, not an excuse to split each output into its own
  destination. A custom layout may better serve the agreed task.
- Show essential warnings, missing-data status and exclusion counts next to the
  figure they qualify. Put full provenance, formulas, SQL, QA and logs within a
  discoverable detail action or audit view instead of expanding them all by default.
  A collapsed warning must retain a visible summary.
- Do not force every datum into cards or charts. Use charts when they answer a
  question more efficiently than a table; keep decorative content out of the work area.

## Tables and controls

- Default to compact, readable rows and a useful subset of columns. Keep record
  identifiers visible, align numbers, show units and sensible precision, and make
  sorting/filtering clear. Preserve complete values in accessible row details or
  copy actions when visual truncation is necessary. Do not shrink text to fit.
- Use table height, pagination or virtualization suitable for the actual row
  count. Horizontal scrolling is reasonable for a genuinely wide audit table;
  the main working table should not require it for ordinary tasks. Keep headers
  and row context visible when the chosen component supports it.
- Choose controls by task: searchable selection for long lists, checkboxes or
  toggles for independent binary choices, tabs/segmented controls for a few peer
  modes, numeric/date fields for precise entry, and sliders for meaningful
  continuous exploration. Avoid oversized controls, redundant filters and sliders
  standing in for exact data entry. Verify the installed widget API before use.
- Make active filters and their reset visible. Distinguish no data, no matching
  rows, pending loading and failed loading; offer the action that resolves each.
  Preserve entered work after validation errors. Support keyboard focus and
  labelled actions; do not communicate status through color or hover alone.

## After code: desktop browser acceptance gate

Run the actual Studio application and inspect its rendered views using available
browser tools. Source review, `app.run()`, static HTML checks and a green generic
verification report do not establish usable screen layout.

1. Inspect the planned desktop viewport and a smaller desktop size at normal
   zoom. Check first-screen usefulness, clipped controls, accidental horizontal
   overflow, table readability and justified scroll. Capture the screen for review
   when the available browser tool supports it.
2. Exercise the brief's real primary flow with representative permitted inputs:
   navigation, filtering, record selection/detail, and editing/saving when present.
   Verify that visible content actually changes and context survives the return
   path. Check empty/error states and a realistically sized table as applicable.
3. Have the UI/UX specialist review the rendered evidence and observed flows,
   or perform the explicit self-review fallback. Fix material friction and recheck
   affected flows. Do not ask the user to perform routine testing for the agent.

Record viewport, flows checked and any remaining limitation in a few lines.
When browser access is unavailable, finish the checks that are possible and mark
this gate **unverified**, with the specific remaining check. Do not invent visual
evidence or claim a desktop UX pass. A mobile check is optional unless requested;
it does not replace desktop acceptance.
