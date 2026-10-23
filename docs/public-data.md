# Public data and generated artifacts

Only publish material that was deliberately prepared for public use. A local
file, an ignored directory and a synthetic-looking filename do not establish
permission to publish its contents.

## Use the isolated walkthrough

Run `uv run python examples/offline_walkthrough.py` for the documented public
example. It reads one named synthetic CSV, disables `.env` loading and LLM calls,
and allocates fresh temporary local and global memory directories. It never
imports existing memory episodes. Generated output stays under ignored `dist/`
by default. A custom `--output` directory needs its own Git exclusion.

Keep real inputs in an ignored `private/` directory or outside the checkout.
Do not point a demo at a parent directory containing personal files: directory
ingestion can discover more than the intended source. Do not use user input
folders or historical tester material to create public examples.

## Inspect the complete artifact boundary

| Material | Why it needs review |
| --- | --- |
| `.env`, tokens and provider URLs | Credentials or private infrastructure |
| Local and global failure memory | Prompts, source snippets, errors, business data and paths |
| `adaptive_memory_snapshot.json` | The current builder copies local **and global** episodes here |
| `lineage_graph.json`, `lineage_traces.json` | Source coordinates, values, snippets and assumptions |
| `orchestration_report.json` | User need, input manifest, results and diagnostics |
| Generated `data/`, notebook and Studio metadata | Copied input values, paths and runtime artifacts |
| Browser recordings, screenshots and logs | Rendered data, session URLs or diagnostic details |
| DOCX, PPTX, XLSX, PDF and images | Embedded authorship, comments, hidden content and metadata |

The `.insights/memory/` ignore rule protects the original directory from ordinary
Git additions. It does not remove memory copied into another location. Offline
model mode also does not sanitize artifacts. The current generator has no
general-purpose public-export sanitizer.

## Review before a commit or push

Inspect filenames before opening or staging files. Select intended files
explicitly; avoid bulk staging a workspace with business inputs.

```bash
git status --short
git diff --stat
git diff --cached --name-only
git diff --cached --check
git diff --cached
git ls-files .env .insights/memory private
git check-ignore private/example.csv dist/public-example/app.py
```

The `git ls-files` command should list no private files. Review names, contact
details, identifying paths, credentials and copied client material in the actual
diff. A text scan is only one check: it misses binary metadata and contextual
personal information. Never paste a detected secret into an issue or report.

Ignoring a file does not untrack an existing copy or remove previous commits.
Inspect Git history separately when making an existing repository public. If a
credential was exposed, replace it through its issuer and assess the historical
copies. Coordinate any history rewrite explicitly; this guide does not perform
one or certify the repository's past contents.

## Python distributions

`pyproject.toml` uses explicit source-distribution paths; `scripts/release.py`
restricts which example files may enter an archive. Preserve those allowlists.
Adding a blanket `examples/` or workspace include would broaden the public
artifact boundary to unrelated inputs.

The wheel contains runtime code and bundled agent instructions. The source
distribution also includes selected docs, executable public examples and
synthetic test fixtures. Generated studios, raw memory and private input folders
remain excluded. Archive inspection checks paths and metadata, not the absence
of every possible secret in an otherwise permitted file. Follow the
[publishing guide](publishing.md) for a local package build and inspection.
