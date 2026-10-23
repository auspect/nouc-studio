# Git versions and tag-triggered publication

Nouc Studio's version is derived from Git by Hatch VCS / setuptools-scm. There is
no version literal to maintain in `pyproject.toml`, `pixi.toml` or the package.
`nouc_studio.__version__` reads the installed distribution metadata through
`importlib.metadata`. Git and Hatch VCS are build-time requirements only.

## Version rules

- A clean commit tagged `v1.2.3` builds version `1.2.3`. Prerelease tags such as
  `v1.2.3rc1`, `v1.2.3a1` and `v1.2.3b1` are supported too.
- Commits after that tag produce a next-version development snapshot, for example
  `1.2.4.dev3+g<commit>`. The commit distance and hash come from Git.
- Before the first version tag, the SCM tool produces an initial development
  version from the repository history. It does not turn the old source literal
  `0.1.0` into a release. Choose the first release explicitly with a tag.
- A dirty checkout may add a date marker. The publish workflow rejects dirty
  sources, and rejects a wheel whose version differs from the selected tag.
- PyPI publication requires a release tag. TestPyPI also accepts a manually
  requested snapshot of the default branch without a tag. Its public version
  retains the Git-derived development number (for example `1.2.4.dev3`) and
  excludes the index-forbidden `+g...` suffix. The workflow summary retains the
  full source SHA. Ordinary branch pushes never upload to either index.
- Use a complete Git checkout including tags. A raw GitHub source ZIP without Git
  metadata is not the supported build input. Published sdists carry their version
  metadata and can build wheels without Git.

Do not use `uv version --bump` or `SETUPTOOLS_SCM_PRETEND_VERSION` for releases.
For tagless TestPyPI snapshots only, the workflow derives the public development
version from the installed SCM metadata and supplies a distribution-specific
build override. It rejects release and dirty versions; no version is written
into package sources. Rerunning the same snapshot version fails on an index
that already contains it; make a new commit rather than reusing a version.
The tag is the version source. Editable-install metadata is refreshed at install
or build time, not on every import. After changing commits or tags, refresh it:

```powershell
uv sync --locked --reinstall-package nouc-studio
uv run python -c "import nouc_studio; print(nouc_studio.__version__)"
```

## One-time registry and GitHub setup

These settings must be configured by the project owner before the first upload.
The workflow does not create a PyPI project, reserve its name, or change GitHub
repository settings.

1. In GitHub, create environments named **`pypi`** and **`testpypi`**. Permit
   deployments from the default branch for manual runs and release tags matching
   `v*` for automatic runs (selected branches and tags). A tag-triggered job
   deploys from its tag ref, even though it reads the source validator from the
   default branch. Protect the default branch and release tags against rewriting.
   Required environment reviewers pause uploads; omit that rule for fully
   automatic publication.
2. In PyPI, configure a GitHub **Trusted Publisher** (pending publisher for a new
   project, subject to name availability) with these exact values:

   | Field | Production | Test |
   | --- | --- | --- |
   | PyPI project | `nouc-studio` | `nouc-studio` on TestPyPI |
   | Repository owner | `auspect` | `auspect` |
   | Repository | `nouc-studio` | `nouc-studio` |
   | Workflow filename | `publish.yml` | `publish.yml` |
   | Environment | `pypi` | `testpypi` |

3. Configure TestPyPI separately; its accounts, project and publisher are separate
   from PyPI. No `PYPI_TOKEN` secret is needed. The publish-only job receives
   `id-token: write`; it downloads this run's immutable artifacts and executes no
   repository code. The official PyPA action publishes with attestations enabled.

The GitHub repository is `auspect/nouc-studio`. Trusted Publisher registrations
on both PyPI and TestPyPI must use the current repository name `nouc-studio`;
update any registration created before the repository was renamed.

See the official [Trusted Publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [publishing instructions](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Build without publishing

Ordinary push/PR CI builds and inspects distributions on Linux/Python 3.12 in
addition to the test matrix. It never publishes. For downloadable artifacts,
open **Actions → Build and publish Python package → Run workflow**, choose a
branch and leave `target=build`, `tag` empty. A tag can also be built in this mode.

The build uses `uv build --no-sources`: first an sdist, then a wheel from that
sdist. It checks metadata, archive contents and README rendering, then installs
the wheel outside the source checkout and checks its runtime version and CLI.
The workflow summary records the selected source SHA, version and SHA-256 hashes.

Locally, use a dedicated output directory so earlier Studio bundles in `dist/`
are not mistaken for Python distributions:

```powershell
uv build --no-sources --out-dir dist/package
uv run python scripts/release.py inspect dist/package
uv run twine check --strict dist/package/*
```

The wheel contains the Python package, the eleven canonical Copilot/skill
resources consumed by `nouc init`, the complete Apache-2.0 license and original
copyright attribution in `NOTICE`. The sdist adds the canonical bootstrap sources,
tests, release checker, selected documentation, public example scripts and
explicitly listed synthetic fixtures.
Resource allowlists and wheel/sdist byte comparisons prevent accidental omission
or divergent instruction copies. The installed-wheel smoke test initializes a
fresh temporary consumer project twice and verifies the `verify` extra and
idempotence; it does not use a fallback to the source checkout.
Local memory, input-only user folders, generated studios, browser transcripts,
screenshots and caches are excluded from both distributions.

## Publish a release by pushing its tag

After the changes pass CI and are on the default branch, create and push an
annotated tag. The tag remains an explicit owner action; ordinary commits do
not publish:

```powershell
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

Pushing a canonical `vX.Y.Z` tag automatically runs tests, build and metadata
checks, and an isolated installation, then publishes to PyPI with Trusted
Publishing. Prerelease tags such as `v0.1.0rc1` also publish to PyPI as prereleases.
Branch pushes, pull requests and GitHub Release creation do not upload a package.
Creating a tag only locally does not trigger GitHub Actions.

The trigger matches `v[0-9]*`; a stricter validator rejects noncanonical versions
before upload. On tag pushes, the validator is loaded from the default branch,
then verifies that the tag commit matches the push event SHA and is reachable
from the default branch before checking out that exact source commit.

Configure the PyPI Trusted Publisher before pushing the first release tag.
Every valid release tag pushed to this repository requests production
publication. Use manual `target=build` without a tag for a development preview.

The manual workflow remains available for builds, TestPyPI, or a production
retry. Choose the default branch and `target=testpypi`, leaving `tag` empty to
test the current commit before creating any release tag. TestPyPI's own Trusted
Publisher must be configured. An existing tag can also be supplied to TestPyPI;
production retries always require a tag. A valid tag push already triggers production;
a manual TestPyPI upload of that tag is an additional check, not a prerequisite
for the automatic PyPI upload.

The tag must name a commit reachable from the default branch. The workflow
resolves and freezes that commit before building. A duplicate version fails
rather than being silently skipped; published versions are immutable. Make a new
commit/tag for a correction, rather than moving a published tag or reusing its
version. If publishing fails, inspect the job and registry before retrying: a
partial upload may already have made one distribution available.

Implementation references: [Hatch VCS](https://github.com/ofek/hatch-vcs),
[SCM runtime metadata](https://setuptools-scm.readthedocs.io/stable/usage/#at-runtime),
and [uv package builds](https://docs.astral.sh/uv/guides/package/).
