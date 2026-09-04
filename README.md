# AMD Platform Catalog

A versioned, cross-language catalog of AMD GPU and NPU platform facts:
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and hand-validated hardware notes. It's aggregated from AMD's own
authoritative public sources, so any tool (Rust, Python, Go, or an AI agent)
can answer "what is this device, and what can it do" without re-deriving the
answer itself.

AMD already publishes this information, spread across ROCm's docs, LLVM's
target tables, and driver source trees. Nothing pulls it together for direct
use, so tools that need it tend to re-derive the same facts one hardcoded
case at a time. This catalog does that work once: mechanically sourced where
possible, with a small hand-maintained notes layer for the handful of facts
only real hardware testing can confirm.

See [`PRD.md`](PRD.md) for the full design: problem statement, data model,
sourcing decisions, and phased implementation plan. This README covers how
to build and use what's here today.

## Using the agent skill

If you're working with an AI coding agent, this is the fastest way in.
`skills/amd-platform-catalog/` follows the
[agentskills.io specification](https://agentskills.io/specification) and is
installable with [vercel-labs/skills](https://github.com/vercel-labs/skills):

```bash
npx skills add AMD-melliott/amd-platform-catalog
```

or read `skills/amd-platform-catalog/SKILL.md` directly. It ships a
dependency-free Python CLI (`scripts/catalog_lookup.py`) over a bundled
catalog snapshot (`assets/catalog.json`, a real copy, not a symlink,
since a tool that installs only this skill's subdirectory wouldn't bring a
symlink's target along). Same lookups, same notes-overlay behavior, same
golden values as the three language bindings below:

```bash
cd skills/amd-platform-catalog
python3 scripts/catalog_lookup.py resolve 74a1   # MI300X, notes overlay applied
python3 scripts/catalog_lookup.py npu 17f0       # NPU4/5/6 share this PCI ID
```

Run `scripts/sync_catalog_snapshot.sh` after regenerating the canonical
catalog to resync the bundled snapshot.

## Language bindings

Rust, Python, and Go each get a thin wrapper that embeds the catalog
directly: no FFI, no subprocess, no network access. All three expose the
same typed lookups and agree on the same golden values (MI300X, Strix Halo).

### Rust binding

```bash
cd bindings/rust
cargo test
```

```rust
use amd_platform_catalog::Catalog;

let catalog = Catalog::embedded();
let mi300x = catalog.gpu_by_device_id("74a1").unwrap();
assert_eq!(mi300x.generation, "CDNA3");

let strix_halo_npus = catalog.npus_by_device_id("17f0");
assert_eq!(strix_halo_npus.len(), 3); // NPU4/5/6 share this PCI ID
```

The catalog JSON is embedded in the crate at compile time via `include_str!`.

### Python binding

```bash
cd bindings/python
uv run pytest
```

```python
from amd_platform_catalog import Catalog

catalog = Catalog.embedded()
mi300x = catalog.gpu_by_device_id("74a1")
assert mi300x.generation == "CDNA3"

strix_halo_npus = catalog.npus_by_device_id("17f0")
assert len(strix_halo_npus) == 3  # NPU4/5/6 share this PCI ID
```

`catalog.json` is a symlink into `catalog/catalog.json` (the actual file
package data reads from), packaged alongside the module.

### Go binding

```bash
cd bindings/go
go test ./...
```

```go
import catalog "github.com/AMD-melliott/amd-platform-catalog/bindings/go"

c := catalog.Embedded()
mi300x := c.GPUByDeviceID("74a1")
// mi300x.Generation == "CDNA3"

strixHaloNPUs := c.NPUsByDeviceID("17f0")
// len(strixHaloNPUs) == 3, NPU4/5/6 share this PCI ID
```

Unlike the Rust and Python bindings, `bindings/go/catalog.json` is a real
committed copy of `catalog/catalog.json`, not a symlink. Go's `//go:embed`
refuses to embed symlinks at all. Run `go generate ./...` in `bindings/go/`
after regenerating the canonical catalog to resync it.

## Repository layout

```
PRD.md                       Full design doc
docs/                        Sphinx docs site (published to GitHub Pages)
.github/workflows/           CI: tests+lint (ci.yml), docs deploy (docs.yml), security (security.yml, codeql.yml)
.github/dependabot.yml        Dependency update PRs for every ecosystem in this repo
catalog/
  catalog.json                The built, versioned catalog artifact
  notes.json                   Hand-maintained notes overlay (PRD §6.5)
  schema/catalog.schema.json  JSON Schema formalizing PRD §6's data model
tools/catalog_build/          Offline ingestion pipeline (Python)
  rst_tables.py                Shared docutils-based RST list-table extractor
  ingest_rocm_gpu_specs.py
  ingest_rocm_precision_support.py
  ingest_libdrm_amdgpu_ids.py
  match_gpu_device_ids.py       Joins amdgpu.ids onto GpuEntry by marketing name
  ingest_llvm_amdgpu_usage.py
  cross_check_llvm.py           Build-time-only validator, never mutates GpuEntry
  ingest_xdna_pciids.py
  build_catalog.py              Orchestrates all of the above -> catalog.json
  validate_schema.py
tools/hardware_validation/    On-hardware probes feeding catalog/notes.json (PRD §6.5) -- not part of CI
tests/                        pytest suite + pinned RST/C fixtures (offline)
bindings/rust/                Thin Rust binding crate (embeds catalog.json)
bindings/python/               Thin Python binding package (embeds catalog.json)
bindings/go/                   Thin Go binding module (embeds a synced copy of catalog.json)
skills/amd-platform-catalog/   Agent skill (agentskills.io spec) -- see its SKILL.md
```

## Building the catalog

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m tools.catalog_build.build_catalog --output catalog/catalog.json
uv run python -m tools.catalog_build.validate_schema catalog/catalog.json
```

By default this fetches all five sources live and prints a warning to
stderr for every known gap (ambiguous/unmatched device IDs, missing
precision data, cross-source generation mismatches, brand-new LLVM targets).
Pass `--fixtures-dir tests/fixtures` to build offline from the pinned
snapshots used by the test suite instead.

## Running the tests

```bash
uv run python -m pytest tests/
```

57 tests. Ingestion round-trips are checked against pinned fixtures for
every source, along with schema-conformance and golden-entry checks (MI300X,
Strix Halo) confirming the resolved catalog entries match hand-verified
values exactly. `test_skill.py` validates `skills/amd-platform-catalog/`
against the agentskills.io spec (frontmatter format, file references,
line-count limit) and exercises its lookup script against the same golden
values.

## Linting and CI

`.github/workflows/ci.yml` runs on every push/PR to `main`: `ruff check`
+ `ruff format --check` + the pytest suites (root and `bindings/python`);
`cargo fmt --check` + `cargo clippy --all-targets -- -D warnings` +
`cargo test` for `bindings/rust`; `gofmt -l` + `go vet` + `go test` for
`bindings/go`. Run the same commands locally before pushing:

```bash
uv run ruff check . && uv run ruff format --check .
(cd bindings/rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings)
(cd bindings/go && gofmt -l . && go vet ./...)
```

`.github/workflows/security.yml` runs a secret scan (gitleaks), a large-file
tripwire, and (on PRs) a dependency-vulnerability review;
`.github/workflows/codeql.yml` runs CodeQL against the Python and Go code.
`.github/dependabot.yml` opens weekly update PRs for every ecosystem in this
repo (`uv`, `cargo`, `gomod`, `github-actions`).

## Documentation site

The Sphinx docs site under `docs/` (theme: furo) is published to GitHub
Pages at <https://amd-melliott.github.io/amd-platform-catalog/>. Pages pull
their content from this README and `PRD.md` via MyST `include` directives
(whole file, or by section for the per-binding/skill pages) rather than
duplicating it, so the docs site and the in-repo docs can't drift apart:

- `docs/overview.md`: this README's opening (what and why)
- `docs/agent-skill.md`: the agent skill
- `docs/bindings/{rust,python,go}.md`: one dedicated page per binding
- `docs/development.md`: repository layout, building, testing, linting/CI
- `docs/PRD.md`: the full PRD, built but deliberately left out of the site
  navigation for now (marked `:orphan:`) while this is still a personal
  project; `PRD.md` itself is unaffected

Build it locally:

```bash
uv sync --group docs
uv run --group docs sphinx-build -b html docs docs/_build/html -W
```

`.github/workflows/docs.yml` builds and deploys it to GitHub Pages on every
push to `main`.

A [rocm-docs-core](https://github.com/ROCm/rocm-docs-core) theme setup
(flavor: `instinct-design`) is preserved on the `rocm-docs-core-theme`
branch to switch back to later.

## License

MIT. See [`LICENSE`](LICENSE).
