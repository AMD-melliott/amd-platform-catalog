# PRD: AMD Platform Catalog

**Status:** Draft
**Owner:** Matt Elliott (AMD-melliott)
**Date:** 2026-09-02

## 1. Summary

A versioned, cross-language catalog of AMD GPU and NPU platform facts —
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and known behavioral quirks — aggregated from AMD's own authoritative
public sources and distributed so any tool (Rust, Python, Go, or an AI agent)
can answer "what is this device, and what can it do" without re-deriving the
answer itself.

## 2. Problem statement

Every tool that monitors or manages AMD hardware currently re-solves the same
problem in isolation:

- **gpuflo** hardcodes a single PCI device-ID quirk (Strix Halo, `1002:1586`)
  to correct a misleading KFD heap-type report, with no generalized concept
  of "what architecture/generation is this."
- **rocm-cli** is taking an independent approach to device detection
  (per conversation with its maintainer, Mike Roy).
- Matt has hit this same gap across multiple other AMD-adjacent products.
- `instinct-dash` solved it for exactly two platforms (MI300X, Strix Halo)
  with a hardcoded provider split — not designed to generalize.

None of this is because the underlying data doesn't exist. It's scattered:
AMD/LLVM publish authoritative generation and precision-support tables, but
nothing packages them for direct consumption by monitoring/management tools,
and nothing adds the layer no datasheet can provide — quirks confirmed only
by running on real hardware.

## 3. Goals

- One authoritative, versioned data artifact mapping device identity
  (PCI device ID, gfx/LLVM target) to architecture generation, hardware
  specs, precision/data-type support, and NPU presence.
- Trivially consumable from Rust, Python, and Go with no shared runtime,
  FFI, or subprocess dependency — the catalog is data, not code.
- An accompanying agent skill so an AI coding agent can query the catalog
  directly (e.g. while debugging or extending a monitoring tool) without
  re-deriving platform facts from scratch each time.
- Full source provenance on every catalog entry, so consumers (and
  reviewers) can verify a claim traces back to an authoritative source.
- A small, honest, hand-maintained "quirks" layer for facts that can only
  come from real hardware observation — kept explicitly separate from
  scraped/generated data.

## 4. Non-goals (v1)

- **NPU functional-status / live probing** (`xrt-smi`-style runtime
  telemetry). This catalog covers static presence + generation only.
  Functional monitoring is a backlog item (see §8).
- **Runtime capability negotiation or feature flags for driver/ROCm
  version compatibility** — this catalog describes the hardware, not
  what a given software stack currently supports on it.
- **Becoming the single source of truth for GPU telemetry** — this is a
  static identity/capability catalog, not a monitoring library.
- Reimplementing anything `amdsmi` already exposes at runtime
  (`device_id`, `target_graphics_version`, VRAM/GTT split). The catalog
  complements those raw identity signals with the generation label and
  capability facts that amdsmi does not decode.

## 5. Background: sources evaluated

| Source | Verdict | What it gives |
|---|---|---|
| gpuopen ISA XML + `isa_spec_manager` | **Rejected** — wrong layer | Compiler/disassembler-grade instruction encodings. No device, capability, or memory-model data. |
| `amdsmi` (`rocm-systems/projects/amdsmi`) | **Reference, not source** | Already multi-language (C/Python/Go/Rust). Resolves `device_id` → `target_graphics_version` and correct VRAM/GTT split at runtime, confirmed live on Strix Halo. Does not decode a generation label or expose NPU/precision data. |
| LLVM `AMDGPUUsage.html` | **Primary source** | Authoritative gfx-target → product family → generation mapping (RDNA3/3.5/4, CDNA3/4). First to reflect brand-new targets. |
| `ROCm/ROCm` `docs/reference/gpu-specs.rst` | **Primary source** | Product name, graphics model, generation, gfx target, and detailed hardware specs (compute units, cache, VRAM) for Instinct/Radeon PRO/Radeon/Ryzen APU, as versioned RST tables. |
| `ROCm/ROCm` `docs/reference/precision-support.rst` | **Primary source** | Per-generation (CDNA1-4, RDNA2-4) data-type/precision capability matrix (fp8 variants, bf16, tf32, int8, etc.) — genuine "what can it do" data. |
| `ROCm/ROCm` `docs/reference/gpu-arch/index.md` | **Secondary/reference** | Curated links to AMD white papers and ISA reference PDFs per generation. Unstructured; only worth extracting from if a specific fact is missing elsewhere. |
| NPU PCI-ID data (Gentoo wiki `User:Lockal/AMDXDNA`, `amd/xdna-driver`) | **Primary source, needs re-verification against upstream driver source** | NPU presence + generation via PCI ID (vendor `1022`), e.g. `1022:1502` (Phoenix/Hawk Point), `1022:17f0` (Strix/Krackan/Strix Halo family, disambiguated by revision). |
| amdgpu "IP Discovery" (debugfs) | **Noted, not used** | Most authoritative possible source (driver's own runtime hardware discovery), but root-only, undocumented binary format. Impractical for this catalog. |
| AMD marketing product pages | **Rejected** | No gfx-target/architecture data; marketing TOPS/model-name only. |

## 6. Proposed architecture

Three layers, deliberately decoupled:

### 6.1 Ingestion (offline, scheduled — not runtime code)

A script pulls and normalizes the primary sources above into one artifact.
Only the **quirks overlay** is hand-maintained; everything else is
mechanically parsed from source (all sources are plain RST/HTML tables with
regular structure — no LLM extraction needed for v1).

### 6.2 The catalog (the actual deliverable)

A single versioned JSON document (JSON chosen over YAML/TOML: zero extra
dependencies in Rust, Python, or Go, and directly readable by an agent
skill without a parser library).

```jsonc
{
  "catalog_version": "0.1.0",
  "generated_at": "2026-09-02T00:00:00Z",
  "sources": [
    {"name": "rocm-gpu-specs", "url": "https://github.com/ROCm/ROCm/blob/develop/docs/reference/gpu-specs.rst", "ref": "<commit>"},
    {"name": "rocm-precision-support", "url": "...", "ref": "<commit>"},
    {"name": "llvm-amdgpu-usage", "url": "https://llvm.org/docs/AMDGPUUsage.html", "ref": "<fetch-date>"}
  ],
  "gpus": [
    {
      "device_id": "1586",
      "gfx_target": "gfx1151",
      "generation": "RDNA3.5",
      "product_name": "AMD Ryzen AI Max+ PRO 395",
      "graphics_model": "Radeon 8060S",
      "memory_model": "unified",
      "specs": { "compute_units": 40, "vram_gib": null, "..." : "..." },
      "precision_support": { "fp8_e4m3": true, "bf16": true, "..." : "..." }
    }
  ],
  "npus": [
    { "device_id": "17f0", "vendor_id": "1022", "family": "Strix/Krackan/Strix Halo", "hw_gen": "Gen 5", "llvm_target": "aie2p-none-unknown-elf" }
  ],
  "quirks": [
    {
      "device_id": "1586",
      "field": "memory_pool",
      "override": "gtt",
      "note": "KFD heap-type evidence misreports as dedicated (heap type 1); confirmed via amd-smi GTT/VRAM split on real hardware.",
      "validated_on": "2026-09-02"
    }
  ]
}
```

### 6.3 Runtime (per language, intentionally thin)

Because aggregation happens offline, each language binding is small: embed
the pinned catalog JSON, look up by `device_id` (+ revision where the
device ID alone is ambiguous), apply the quirks overlay, return a typed
struct. No FFI, no subprocess, no shared native runtime.

### 6.4 Agent skill

Documents the schema and catalog location; a lookup helper script is
optional since the catalog is small enough for an agent to read directly.

## 7. Success criteria (v1)

- Catalog covers every product row in the current ROCm `gpu-specs.rst`
  (Instinct, Radeon PRO, Radeon, Ryzen APU) plus the known NPU device IDs.
- Every entry traces to a named, versioned source — no un-sourced facts.
- gpuflo's `platform.rs` can be re-pointed at the catalog for generation
  labeling with zero behavior change to its existing quirk resolution
  (Strix Halo GTT accounting stays correct).
- A second language (Python or Go) consumes the same catalog with a
  comparably small amount of glue code, proving the "thin binding" claim.

## 8. Roadmap / backlog (explicitly out of v1 scope)

- **NPU functional-status detection** (probe-based, `xrt-smi`-style
  liveness/health, not just static presence). Tracked as a future item;
  no design work yet.
- **Staleness/deprecation signaling** — TBD. Needs research into how AMD
  announces hardware deprecations before a workable freshness model can be
  designed. Not blocking v1; catalog ships with a `generated_at` timestamp
  and nothing more sophisticated for now.
- **Long-term repo ownership** — starts in `AMD-melliott` personal account.
  Contributing it to the ROCm GitHub org requires open-source governance
  board approval and is explicitly deferred; not a v1 concern.
- Confirm the NPU PCI-ID table against `amd/xdna-driver` source directly
  (today's data is sourced from a community wiki mirror, not upstream
  driver source).

## 9. Open questions

- License for the catalog + wrapper packages (leaning MIT to match
  `isa_spec_manager` and general ecosystem convention — not yet decided).
- Update cadence / trigger for re-running ingestion (manual vs. watching
  upstream repos for changes).
- Whether `specs`/`precision_support` should be included verbatim per
  product in v1, or deferred to a later phase if the initial cut only
  needs `generation` + `gfx_target` + memory-model quirks.

## 10. Phased implementation plan

| Phase | Work | Exit criteria |
|---|---|---|
| 0 — Spike | Ingestion script for `gpu-specs.rst` + `precision-support.rst` only; hand-verify Strix Halo and MI300X rows | Parsed output matches known-good values |
| 1 — Catalog repo | Full ingestion (add LLVM + NPU sources); first versioned JSON release | `v0.1.0` catalog published with source provenance |
| 2 — Rust wrapper | Thin crate wrapping the catalog; migrate gpuflo's `platform.rs` to consume it | gpuflo depends on catalog; existing tests unchanged |
| 3 — Python + Go wrappers | Mirror the Rust wrapper | Cross-language parity demonstrated; ready to propose to Mike for rocm-cli |
| 4 — NPU + skill | Verify NPU table against `xdna-driver` source; write the agent skill | Skill usable by an agent with no prior repo context |
