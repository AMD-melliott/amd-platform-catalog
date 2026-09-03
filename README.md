# AMD Platform Catalog

A versioned, cross-language catalog of AMD GPU and NPU platform facts —
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and hand-validated hardware notes — aggregated from AMD's own
authoritative public sources so any tool (Rust, Python, Go, or an AI agent)
can answer "what is this device, and what can it do" without re-deriving the
answer itself.

See [`PRD.md`](PRD.md) for the full design: problem statement, data model,
sourcing decisions, and phased implementation plan. This README covers how
to build and use what's here today.

## Status

Phase 0 and Phase 1 of the PRD's phased plan are done: `catalog.json` is at
`v0.1.0`, built from five sources with real pinned provenance (commit SHAs,
not just fetch dates):

| Source | Feeds |
|---|---|
| ROCm `gpu-specs.rst` | GPU identity, generation, gfx target, hardware specs |
| ROCm `precision-support.rst` | Per-generation data-type support |
| `libdrm`'s `amdgpu.ids` | GPU `device_id` (joined by marketing name) |
| LLVM's `AMDGPUUsage.rst` | Build-time cross-check only — flags gfx_target/generation mismatches and brand-new targets ROCm hasn't caught up to yet |
| `amd/xdna-driver`'s own PCI ID table | NPU identity and hardware generation |

Current catalog: 44 GPU entries, 19 NPU entries, plus a hand-maintained
notes overlay (`catalog/notes.json`) starting with one entry (Strix Halo's
`precision_support` gap). Thin bindings exist for Rust (`bindings/rust/`),
Python (`bindings/python/`), and Go (`bindings/go/`) — all three expose the
same typed lookups and agree on the same golden values (MI300X, Strix Halo).
Migrating `gpuflo`'s `platform.rs` to consume the Rust binding is a separate
task in that other repo. The agent skill (Phase 4) isn't started yet.

**Known, documented gaps** (not oversights — see `PRD.md` for the full
writeup of each): a handful of GPU `device_id`s are ambiguous or unmatched by
`amdgpu.ids`; RDNA3.5 has no column in ROCm's precision-support table; NPU
`family` is unset wherever `amd/xdna-driver` itself can't statically
disambiguate a marketing name from a PCI ID alone.

## Repository layout

```
PRD.md                       Full design doc
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
tests/                        pytest suite + pinned RST/C fixtures (offline)
bindings/rust/                Thin Rust binding crate (embeds catalog.json)
bindings/python/               Thin Python binding package (embeds catalog.json)
bindings/go/                   Thin Go binding module (embeds a synced copy of catalog.json)
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

38 tests: ingestion round-trips against pinned fixtures for every source,
schema-conformance, and golden-entry checks (MI300X, Strix Halo) confirming
the resolved catalog entries match hand-verified values exactly.

## Using the Rust binding

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

No FFI, no subprocess, no shared native runtime — the catalog JSON is
embedded in the crate at compile time via `include_str!`.

## Using the Python binding

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
package data reads from), packaged alongside the module — no live fetch, no
network access.

## Using the Go binding

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
committed copy of `catalog/catalog.json`, not a symlink — Go's `//go:embed`
refuses to embed symlinks at all. Run `go generate ./...` in `bindings/go/`
after regenerating the canonical catalog to resync it.

## License

Not yet decided (see `PRD.md` §11) — leaning MIT.
