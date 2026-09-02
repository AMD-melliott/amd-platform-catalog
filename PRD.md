# PRD: AMD Platform Catalog

**Status:** Draft
**Owner:** Matt Elliott (AMD-melliott)
**Date:** 2026-09-02

## 1. Summary

A versioned, cross-language catalog of AMD GPU and NPU platform facts —
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and hand-validated hardware notes — aggregated from AMD's own
authoritative public sources and distributed so any tool (Rust, Python, Go, or
an AI agent) can answer "what is this device, and what can it do" without
re-deriving the answer itself.

## 2. Problem statement

Every tool that monitors or manages AMD hardware currently re-solves the same
problem in isolation:

- **gpuflo** hardcodes a single PCI device-ID correction (Strix Halo,
  `1002:1586`) to fix a misleading KFD heap-type report, with no generalized
  concept of "what architecture/generation is this."
- **rocm-cli** is taking an independent approach to device detection
  (per conversation with its maintainer, Mike Roy).
- Matt has hit this same gap across multiple other AMD-adjacent products.
- `instinct-dash` solved it for exactly two platforms (MI300X, Strix Halo)
  with a hardcoded provider split — not designed to generalize.

None of this is because the underlying data doesn't exist. It's scattered:
AMD/LLVM publish authoritative generation and precision-support tables, but
nothing packages them for direct consumption by monitoring/management tools,
and nothing adds the layer no datasheet can provide — notes confirmed only by
running on real hardware.

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
- A small, honest, hand-maintained **notes** layer for facts that can only
  come from real hardware observation — kept explicitly separate from
  scraped/generated data.

## 4. Non-goals (v1)

- **NPU functional-status / live probing** (`xrt-smi`-style runtime
  telemetry). This catalog covers static presence + generation only.
  Functional monitoring is a backlog item (see §10).
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
| LLVM `AMDGPUUsage.html` (ingested from its `.rst` source, `llvm/llvm-project` `llvm/docs/AMDGPUUsage.rst`) | **Primary source (implemented 2026-09-02)** | Authoritative gfx-target → product family → generation mapping (RDNA3/3.5/4, CDNA3/4). First to reflect brand-new targets — confirmed live: lists 20 `gfx_target`s (all of RDNA1, plus forward-looking `gfx1250`/`gfx1310` etc.) that `gpu-specs.rst` doesn't have yet. Ingesting the `.rst` source directly (rather than the rendered `.html`) gives a real pinned commit SHA for `ref` instead of only a fetch-date. |
| `ROCm/ROCm` `docs/reference/gpu-specs.rst` | **Primary source** | Product name, graphics model, generation, gfx target, and detailed hardware specs (compute units, cache, VRAM) for Instinct/Radeon PRO/Radeon/Ryzen APU, as versioned RST tables. |
| `ROCm/ROCm` `docs/reference/precision-support.rst` | **Primary source** | Per-generation (CDNA1-4, RDNA2-4) data-type/precision capability matrix (fp8 variants, bf16, tf32, int8, etc.) — genuine "what can it do" data. |
| `ROCm/ROCm` `docs/reference/gpu-arch/index.md` | **Secondary/reference** | Curated links to AMD white papers and ISA reference PDFs per generation. Unstructured; only worth extracting from if a specific fact is missing elsewhere. |
| NPU PCI-ID data — `amd/xdna-driver` (`drivers/accel/amdxdna/amdxdna_pci_drv.c` + per-generation `npuN_regs.c`) | **Primary source (implemented 2026-09-02, superseding the Gentoo wiki mirror)** | NPU presence + driver-generation label (`hw_gen`) via PCI `(device_id, revision_id)`, e.g. `1022:1502` rev `00` (NPU1), `1022:17f0` rev `10`/`11`/`20` (NPU4/5/6, jointly "Strix / Krackan / Strix Halo / Gorgon Point" — the driver itself can't disambiguate further without a live firmware query; see §6.4 callout). The original Gentoo wiki mirror is no longer consulted — going straight to the driver source turned out to have better provenance AND reveal real ambiguities the wiki's simpler mapping had smoothed over. |
| `libdrm` `data/amdgpu.ids` (`gitlab.freedesktop.org/mesa/libdrm`) | **Primary source (candidate) — closes the GPU `device_id` gap identified below** | AMD-maintained (recent commits by Alex Deucher, `alexander.deucher@amd.com`, "from ROCm 7.2") `device_id, revision_id -> marketing product_name` table. Confirmed live (2026-09-02): `1586`/rev `C1` -> "AMD Radeon 8060S Graphics" (matches Strix Halo), `74A1` -> "AMD Instinct MI300X". Versioned (`1.0.0` header), mechanically parseable (simple comma-delimited text), updated per ROCm release — same trust tier as the other primary sources above. See §6.3 and §11 for the join complexity this introduces. |
| amdgpu "IP Discovery" (debugfs) | **Noted, not used** | Most authoritative possible source (driver's own runtime hardware discovery), but root-only, undocumented binary format. Impractical for this catalog. |
| AMD marketing product pages | **Rejected** | No gfx-target/architecture data; marketing TOPS/model-name only. |

## 6. Data model

The catalog is one JSON document with four top-level arrays plus provenance
metadata. Field types below are the target shape; `specs` and
`precision_support` stay intentionally loose objects rather than fixed
schemas, since the source tables' own columns vary by product family (e.g.
the Ryzen APU table reports VRAM as `"Dynamic + carveout"` rather than a
fixed GiB number, and adds a `graphics_model` column the other tables don't
have).

### 6.1 Catalog (root object)

| Field | Type | Required | Description |
|---|---|---|---|
| `catalog_version` | semver string | yes | Version of the catalog data itself, independent of any per-language wrapper package version. |
| `generated_at` | RFC 3339 timestamp | yes | When the ingestion pipeline produced this catalog. |
| `sources` | array of `Source` | yes | Provenance list — every upstream source consulted to build this catalog. |
| `gpus` | array of `GpuEntry` | yes | One entry per known GPU device identity. |
| `npus` | array of `NpuEntry` | yes | One entry per known NPU device identity. |
| `notes` | array of `NoteEntry` | yes | Hand-maintained corrections/observations layered on top of sourced data. |

### 6.2 `Source`

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Short slug identifying the source, e.g. `"rocm-gpu-specs"`. |
| `url` | string (URL) | yes | Canonical URL of the source document or repository. |
| `ref` | string | yes | Commit SHA, tag, or fetch-date pinning exactly what was ingested. |

### 6.3 `GpuEntry`

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | hex string, no `0x` prefix | yes | PCI device ID, e.g. `"1586"`. |
| `revision_id` | hex string | no | PCI revision ID; present only when needed to disambiguate multiple products sharing one `device_id`. |
| `gfx_target` | string | yes | LLVM/gfx target name, e.g. `"gfx1151"`. |
| `generation` | string | yes | Architecture generation label, e.g. `"RDNA3.5"`. |
| `product_name` | string | yes | Marketing product name. |
| `graphics_model` | string | no | Graphics-specific model name where distinct from `product_name` (APUs), e.g. `"Radeon 8060S"`. |
| `memory_model` | enum: `dedicated`, `unified` | yes | High-level memory architecture. |
| `specs` | object (open-ended, sourced verbatim from `gpu-specs.rst` columns) | no | Compute units, VRAM, cache sizes, etc. Shape varies by product family. |
| `precision_support` | object (open-ended booleans keyed by data-type name) | no | Per-type native-support flags sourced from `precision-support.rst`, joined by `generation`. |
| `lifecycle_status` | enum: `active`, `eos`, `unknown` | yes (defaults `unknown`) | Whether AMD has marked this product retired/end-of-service. See open question in §11. |

> **`device_id` sourcing, partially closed (found 2026-09-02, implemented 2026-09-02).** No source evaluated in §5 originally supplied PCI device IDs for GPUs — `gpu-specs.rst` has no such column, unlike the NPU side which always had a PCI-ID source. `libdrm`'s `data/amdgpu.ids` (added to §5) closes this for products it lists: `ingest_libdrm_amdgpu_ids.py` parses the file, and `match_gpu_device_ids.py` joins it onto `GpuEntry` rows by normalized marketing name (stripping the "AMD "/"AMD Instinct "/"AMD Radeon Instinct " prefixes and trailing " Graphics" suffix `amdgpu.ids` adds, and matching against `graphics_model` when present, else `product_name`). Matching is deliberately **exact** after normalization, not substring — gpu-specs.rst's plain "MI300X" is a substring of `amdgpu.ids`' "MI300X HF"/"MI300X VF" variant rows too, so substring matching would silently misattribute a variant SKU's `device_id` to the base part. Against today's two live sources: 34/44 GPU entries resolve unambiguously (including MI300X -> `74a1` and Strix Halo -> `1586`); 3 are genuinely ambiguous (`revision_id` disambiguation not yet implemented — MI250X spans two device_ids, "Radeon 780M" is reused across Phoenix and Hawk Point) and 7 are unmatched (older Instinct cards absent from `amdgpu.ids` entirely, capacity-suffixed names like "MI50 (32GB)" `amdgpu.ids` doesn't distinguish, and brand-new SKUs — RX 9050, R9700S — `amdgpu.ids` hasn't caught up to yet). All left unset with a build-time warning rather than guessed. Remaining work: use `revision_id` to resolve the 3 ambiguous cases (PRD's `revision_id` field exists for exactly this).
>
> **Generation naming inconsistency, also found during Phase 0 (2026-09-02).** `gpu-specs.rst` labels MI100's architecture `"CDNA"` (no digit); `precision-support.rst` and every other source use `"CDNA1"`. Treated as the same generation for the precision-support join, per product-owner judgment (CDNA had no numbered siblings until CDNA2 shipped — the same "no digit until a sequel exists" pattern as unnumbered RDNA before RDNA2). `catalog.json`'s `generation` field still preserves gpu-specs.rst's literal `"CDNA"` string as sourced — only the precision-support lookup applies the alias, so this is a documented normalization, not a silent rewrite of sourced data.

### 6.4 `NpuEntry`

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | hex string | yes | PCI device ID under vendor `1022`. |
| `revision_id` | hex string | no | PCI revision ID; present only when needed to disambiguate multiple hardware generations sharing one `device_id`. Added 2026-09-02 (see callout below) — mirrors `GpuEntry.revision_id`. |
| `vendor_id` | hex string | yes | PCI vendor ID (`1022` for AMD's CPU-side functions, where NPUs enumerate). |
| `family` | string | no (was `yes`, relaxed 2026-09-02 — see callout below) | Human family label, e.g. `"Strix/Krackan/Strix Halo"`. |
| `hw_gen` | string | yes | NPU hardware generation label, e.g. `"Gen 5"`. |
| `llvm_target` | string | no | AIE/XDNA LLVM target triple, if known. |
| `associated_gpu_device_ids` | array of hex string | no | Cross-reference to `GpuEntry.device_id` for platforms that ship this NPU alongside a specific GPU. |

> **NPU schema gap, found while ingesting `amd/xdna-driver` directly (2026-09-02).** Its own `amdxdna_ids[]` table (`drivers/accel/amdxdna/amdxdna_pci_drv.c`) shows PCI device_id `0x17f0` bound to **three different `(device_id, revision_id)` driver-generation entries** (NPU4/rev `0x10`, NPU5/rev `0x11`, NPU6/rev `0x20`) — a real disambiguation `NpuEntry` had no field for, so `revision_id` is added, mirroring `GpuEntry`. Worse: **all three of those NPU4/5/6 bindings share the exact same marketing-name table** (`npu4_rev_vbnv_tbl`: Strix, Krackan, Strix Halo, Gorgon Point) — the driver disambiguates the *actual* marketing family only via a live "get device revision" firmware message that reads a silicon fuse (`aie2_message.c`), never from the static PCI revision byte. That's live probing, which this catalog's own non-goals (§4) explicitly exclude — so `family` for any `0x17f0` row is honestly the *whole set* of names the driver associates with it, not a guessed single value. Separately, several device_ids (`0x1502`, and `0x17f1`/`0x17f2`/`0x17f3`/`0x1b0a`/`0x1b0b`/`0x1b0c`'s NPU3/9/10/11 classic/PF/VF variants) have **no marketing-name table in the driver at all** — `family` is left unset for these rather than backfilled with an internal driver string like `"RyzenAI-npu1"` masquerading as a human name, so `family` is now optional. Note this also means PRD §5's original "Phoenix/Hawk Point" claim for `0x1502` is **not corroborated by `amd/xdna-driver` itself** — it must trace to the Gentoo wiki source instead, and should be treated as unverified until a better source is found.

### 6.5 `NoteEntry`

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | hex string | yes | Device this note applies to. |
| `field` | string | yes | Dotted path of the field being overridden or annotated, e.g. `"memory_pool"`. |
| `override` | any | no | Replacement value, when the note corrects a sourced value rather than only annotating it. |
| `note` | string | yes | Human-readable explanation of what was observed and why. |
| `validated_on` | date | yes | Date the observation was last confirmed on real hardware. |
| `validated_by` | string | no | Who or what confirmed it (person, tool, hardware description). |

## 7. Proposed architecture

Three layers, deliberately decoupled:

### 7.1 Ingestion (offline, scheduled — not runtime code)

A script pulls and normalizes the primary sources above into one artifact.
Only the **notes overlay** is hand-maintained; everything else is
mechanically parsed from source (all sources are plain RST/HTML tables with
regular structure — no LLM extraction needed for v1).

### 7.2 The catalog (the actual deliverable)

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
    {"name": "llvm-amdgpu-usage", "url": "https://github.com/llvm/llvm-project/blob/main/llvm/docs/AMDGPUUsage.rst", "ref": "<commit>"}
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
      "precision_support": { "fp8_e4m3": true, "bf16": true, "..." : "..." },
      "lifecycle_status": "active"
    }
  ],
  "npus": [
    { "device_id": "17f0", "vendor_id": "1022", "family": "Strix/Krackan/Strix Halo", "hw_gen": "Gen 5", "llvm_target": "aie2p-none-unknown-elf" }
  ],
  "notes": [
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

### 7.3 Runtime bindings (per language, intentionally thin)

Because aggregation happens offline, each language binding is small: embed
the pinned catalog JSON, look up by `device_id` (+ revision where the
device ID alone is ambiguous), apply the notes overlay, return a typed
struct. No FFI, no subprocess, no shared native runtime.

**Rust (`bindings/rust/`, implemented 2026-09-02).** Embeds `catalog.json`
via `include_str!`, parses once (`OnceLock`), exposes `gpu_by_device_id`,
`gpus_by_gfx_target`, `gpus_by_generation`, `npus_by_device_id` (+revision
variant), `notes_for_device`, and `resolve_gpu` (applies the notes overlay).
The notes-overlay implementation currently only supports overrides whose
`field` is `"specs.<key>"` — `catalog.json` has zero real notes yet, so
there's no concrete example of a top-level-field override to design
against; extend `apply_gpu_overrides` when one exists.

### 7.4 Agent skill architecture

The skill teaches an agent to answer platform-capability questions directly
from the catalog, without re-deriving them or, worse, guessing.

**Distribution.** The skill ships as a standard `SKILL.md` plus a small set
of optional helper scripts, most plausibly in its own directory in this
repo. It carries a bundled snapshot of the catalog for fast, offline lookups,
and documents the pinned GitHub Releases asset URL so an agent working on
something recent can fetch a newer catalog when the bundled one is behind.
The skill's own frontmatter records which `catalog_version` range it was
authored against, so a future breaking schema change can't silently mislead
an agent running an old skill copy against a new catalog (or vice versa).

**Verbs it teaches:**
1. Look up a device by PCI device ID (+ optional revision) → the fully
   resolved entry, with the notes overlay already applied.
2. Look up all products sharing a gfx/LLVM target or generation.
3. Check NPU presence/generation for a given GPU device ID, via
   `associated_gpu_device_ids`.
4. List every note/override for a device — surfaced explicitly, never
   silently folded into "the data."
5. Explain provenance for a given fact — walk back to the `sources` entry
   that backs it.

**Mechanics.** The catalog is small plain JSON, so the skill's instructions
primarily teach direct reads (`Read`, or `jq` via Bash) rather than requiring
a bespoke CLI. A minimal lookup helper script is still worth shipping for the
cross-referencing queries (verbs 2-4), so the agent isn't hand-writing `jq`
filters for the same joins every time — this becomes one of the CLI tools
listed in §8.

**Failure mode.** When a device ID isn't in the catalog, the skill's
instructions must tell the agent to say so plainly ("not yet cataloged") and
suggest filing an entry — never to guess a generation or capability by
analogy. This mirrors the "never synthesize, never guess" ethos that shaped
gpuflo's own data model in the first place.

## 8. Tooling: scripts, tests, and validation

**Ingestion scripts** (one per source, orchestrated by a top-level build
script):
- `ingest_rocm_gpu_specs.py` — parses `gpu-specs.rst` RST list-tables into `GpuEntry` records.
- `ingest_rocm_precision_support.py` — parses `precision-support.rst` into per-generation precision blocks, joined onto `GpuEntry` by `generation`.
- `ingest_llvm_amdgpu_usage.py` — parses the AMDGPUUsage Processors table for `gfx_target` ↔ `generation` cross-check, and to catch brand-new targets before ROCm's spec table catches up (implemented; see `cross_check_llvm.py` below for the actual comparison logic).
- `cross_check_llvm.py` — joins LLVM's per-target generation onto ingested `GpuEntry` records; on today's live sources this found 4 known, expected label differences on pre-CDNA/RDNA Instinct cards (ROCm's `"GCN5.1"`/`"GCN5.0"` vs. LLVM's `"VEGA7NM"`/`"VEGA"` — two different projects' naming for the same old silicon, not aliased away) and 20 `gfx_target`s LLVM already lists that `gpu-specs.rst` doesn't yet — including all of RDNA1 (never added to `gpu-specs.rst` at all) and forward-looking placeholders like `gfx1310`/"RDNA5" and `gfx1250`/`gfx1251` (next-gen APU targets, `*TBA*` product names in LLVM's own doc) — exactly the "catch brand-new targets" case this source exists for. Emits build-time warnings only; never adds or changes `GpuEntry` fields (implemented).
- `ingest_xdna_pciids.py` — builds `NpuEntry` records directly from `amd/xdna-driver` (device_id/revision_id -> hw_gen from `amdxdna_ids[]`, family from the referenced `rev_vbnv_tbl` where one exists) (implemented; see §6.4).
- `ingest_libdrm_amdgpu_ids.py` — parses `libdrm`'s `data/amdgpu.ids` into raw `device_id, revision_id, product_name` rows (implemented; see §6.3).
- `match_gpu_device_ids.py` — joins `amdgpu.ids` rows onto `GpuEntry` records by normalized marketing name to populate `device_id`; never guesses on an ambiguous or unmatched name (implemented; see §6.3).
- `build_catalog.py` — merges all of the above into one versioned `catalog.json`, stamping `generated_at` and `sources`.

**Validation tools:**
- `validate_schema.py` — validates `catalog.json` against a JSON Schema formalizing §6.
- `validate_provenance.py` — asserts every `GpuEntry`/`NpuEntry` field traces to a `sources` entry; fails the build otherwise.
- `validate_cross_source_consistency.py` — flags any `gfx_target` present in one source but missing from another (e.g. LLVM lists a target ROCm's spec table hasn't caught up to, or vice versa).
- `diff_catalog.py` — human-readable diff between two catalog versions; used for release changelogs and for carefully reviewing notes-overlay changes, which are hand-authored and higher-risk than mechanically-parsed fields.

**CLI tools:**
- `catalog-lookup` — lookup-by-device-id, lookup-by-gfx-target, list-npus-for-gpu. Doubles as the tool the agent skill shells out to for cross-referencing queries.
- `catalog-explain` — provenance walk-back for a given field (supports skill verb 5).

**Tests:**
- Golden-entry tests — for each device already validated on real hardware (Strix Halo, MI300X, etc.), assert the resolved entry (after notes overlay) matches expected values exactly. Regression protection against ingestion changes silently altering resolved output.
- Ingestion round-trip tests — fixture copies of upstream RST/HTML snippets, asserting parsed output matches expected structured records without live network access.
- Schema-conformance tests — every shipped catalog release must pass `validate_schema.py` as a CI gate.
- Cross-language binding smoke tests — a minimal Rust/Python/Go test that loads the catalog and performs a known-good lookup, catching packaging/embedding mistakes per language.
- Notes-overlay regression tests — specifically pin the Strix Halo `memory_pool` override (and any future notes) so an ingestion refactor can't accidentally drop a hand-validated correction.

**Automation:**
- A scheduled "source drift" job that re-runs ingestion against upstream HEAD and opens an issue/PR when new devices or changed values are detected. Relevant to, but not a full solution for, the update-cadence open question in §11.

## 9. Success criteria (v1)

- Catalog covers every product row in the current ROCm `gpu-specs.rst`
  (Instinct, Radeon PRO, Radeon, Ryzen APU) plus the known NPU device IDs.
- Every entry traces to a named, versioned source — no un-sourced facts.
- gpuflo's `platform.rs` can be re-pointed at the catalog for generation
  labeling with zero behavior change to its existing device-specific
  corrections (Strix Halo GTT accounting stays correct).
- A second language (Python or Go) consumes the same catalog with a
  comparably small amount of glue code, proving the "thin binding" claim.

## 10. Roadmap / backlog (explicitly out of v1 scope)

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
- ~~Confirm the NPU PCI-ID table against `amd/xdna-driver` source
  directly~~ — done 2026-09-02; see §5/§6.4. Ingestion now reads the driver
  source directly instead of the Gentoo wiki mirror.
- **RDNA3.5 missing from `precision-support.rst`'s generation matrix.**
  Confirmed by inspection during Phase 0 implementation (2026-09-02): no
  RDNA3.5 column exists anywhere in the document, so Strix Halo/Krackan/
  Strix products get no `precision_support` data from this source today.
  Not totally unexpected. May resolve upstream (ROCm adding the column) or
  via hands-on validation — a Strix Halo node is available to confirm
  precision support directly and feed it through the notes layer if
  upstream doesn't add it. Matt is looking into why the column is missing.

## 11. Open questions

- **Retired / deprecated / EOS hardware.** How should the catalog represent
  a product AMD has declared end-of-service? Options range from removing
  the entry entirely, to keeping it forever with a `lifecycle_status` flag
  (the schema in §6.3 reserves this field, defaulting to `"unknown"`, so
  this can be resolved later without a breaking schema change). Removing
  EOS entries loses value for tools still supporting fielded older hardware
  (e.g. MI100); keeping everything forever risks consumers not
  distinguishing "current" from "ancient" without checking the flag. It's
  also unclear how the catalog would learn a device is EOS in the first
  place — ROCm's own compatibility matrix (linked from `gpu-specs.rst`'s
  "see also") already tracks which GPUs each ROCm release still supports,
  which is a plausible signal source worth evaluating once this is
  designed, rather than guessed at now. There's also an interaction with
  the notes layer: does a note ever need its own validity window ("true as
  of catalog version X, before this device went EOS")? Not blocking v1.
- License for the catalog + wrapper packages (leaning MIT to match
  `isa_spec_manager` and general ecosystem convention — not yet decided).
- Update cadence / trigger for re-running ingestion (manual vs. watching
  upstream repos for changes; see the source-drift automation idea in §8).
- Whether `specs`/`precision_support` should be included verbatim per
  product in v1, or deferred to a later phase if the initial cut only
  needs `generation` + `gfx_target` + memory-model notes.
- **GPU `device_id` sourcing — found 2026-09-02, largely closed the same
  day.** `libdrm`'s `data/amdgpu.ids` (added to §5) plus a normalized
  marketing-name join (`match_gpu_device_ids.py`, see §6.3 callout) now
  populates `device_id` for 34/44 GPU entries against today's live sources.
  Remaining: 3 entries are ambiguous by name alone and need `revision_id`
  disambiguation (not yet implemented); 7 are unmatched because
  `amdgpu.ids` doesn't yet list them (older Instinct cards, capacity-suffix
  variants, brand-new SKUs). `device_id` still isn't required in
  `catalog.schema.json` — coverage isn't complete enough to demand it.

## 12. Phased implementation plan

| Phase | Work | Exit criteria |
|---|---|---|
| 0 — Spike | Ingestion script for `gpu-specs.rst` + `precision-support.rst` only; hand-verify Strix Halo and MI300X rows | Parsed output matches known-good values — **done 2026-09-02** |
| 1 — Catalog repo | Full ingestion (add LLVM + NPU sources); first versioned JSON release | `v0.1.0` catalog published with source provenance — **done 2026-09-02** (ingestion complete with real pinned source refs for all 5 sources; `v0.1.0` stamped in `catalog.json`. "Published" here means the artifact + provenance are correct and versioned, not that a GitHub Release/tag has been cut yet — that's a separate, later action.) |
| 2 — Rust wrapper | Thin crate wrapping the catalog; migrate gpuflo's `platform.rs` to consume it | gpuflo depends on catalog; existing tests unchanged — **crate half done 2026-09-02** (`bindings/rust/`: embeds `catalog.json` via `include_str!`, typed lookups by device_id/gfx_target/generation, notes-overlay resolution, 9 passing tests incl. MI300X/Strix Halo goldens). Migrating gpuflo's `platform.rs` itself is **not done** — gpuflo lives in a separate repo this session has no access to; that half needs doing from within gpuflo's own repo. |
| 3 — Python + Go wrappers | Mirror the Rust wrapper | Cross-language parity demonstrated; ready to propose to Mike for rocm-cli |
| 4 — NPU + skill | Verify NPU table against `xdna-driver` source; write the agent skill | Skill usable by an agent with no prior repo context — NPU table verification **done 2026-09-02** (see §5/§6.4); agent skill still outstanding |
