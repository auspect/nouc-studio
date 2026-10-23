# Studio launch and agent skills brief

Requested scope: use concrete official marimo-studio examples to help agents
author views, make local launch simple, and diagnose failed builds or previews
that need Python execution. This extends the existing repository workflow;
it introduces no new business analysis or business rules.

Inputs: the source checkout, installed marimo-studio 0.3.0 / marimo 0.25.1,
the synthetic public walkthrough, and official documentation checked on
2026-10-23 at upstream commit `37571a33ea4779a0cec398eb65c9f0a9e4eca862`.
The current upstream documentation describes a newer minor version. Installed
signatures and packaged references govern executable recipes.

Deliverables:

- A single local launch command, with app/edit/check shortcuts in Pixi.
- View builds use the profile required by the selected serving mode. Failures
  identify the stage and prevent launching a retained older artifact as success.
- Runtime checking is explicit because it executes notebook Python. Launch
  keeps the project environment; it does not provision a second sandbox.
- Two bundled agent skills, including a reference with patterns from the
  quadratic-program, athletes, earthquakes and occupancy examples.
- Guidance distinguishing source, build, live Python and browser state.

Desktop acceptance reuses the public example's existing screen plan: open the
overview at 1440×900 and 1280×800, navigate to a control and verify a changed
result. Also check an editor source change and a controlled build failure.
This work changes the launch workflow, not the example's analytical semantics.

Acceptance: focused failure/argument tests, Ruff, ty, repository tests,
installed-wheel bootstrap verification including skill references, Pixi command
checks and browser evidence. Report unavailable checks explicitly. Keep generated
apps, browser evidence and raw memory local; commit or push nothing in this task.

Outcome: 223 tests, Ruff and ty passed; Pixi runtime checks and the installed
wheel's eleven-resource bootstrap passed. Real Chromium checks covered the two
desktop sizes, scenario reactivity and external Python edits followed by live
execution and Retry preview. See [the launch guide](studio-launch.md) for the
commands, version boundary and limits of this acceptance evidence.
