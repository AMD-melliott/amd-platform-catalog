---
name: amd-platform-catalog
description: Look up AMD GPU/NPU platform facts -- architecture generation, gfx/LLVM target, hardware specs, precision/data-type support, PCI device IDs, and hand-validated hardware notes -- from a versioned, sourced catalog. Use when asked what an AMD device ID is, what generation/gfx target a GPU is, whether a GPU supports a given precision/data type, whether an NPU exists for a given GPU device ID, or where a catalog fact is sourced from. Never guesses -- says plainly when a device isn't cataloged.
compatibility: Requires Python 3.9+ (standard library only, no dependencies)
metadata:
  bundled_catalog_version: "0.1.0"
  source_repo: "https://github.com/AMD-melliott/amd-platform-catalog"
---

# AMD Platform Catalog

This catalog maps AMD GPU/NPU identity (PCI device ID, gfx/LLVM target) to
architecture generation, hardware specs, precision/data-type support, and
hand-validated notes. Every field traces back to a named, versioned,
authoritative source (ROCm, LLVM, libdrm, or amd/xdna-driver) -- nothing
here is LLM-derived or guessed. When a fact genuinely isn't available from
any source yet, the catalog says so explicitly (a missing field, or a note)
rather than interpolating from a similar device. Follow that same
discipline when using this skill: if a device isn't in the catalog, say so
plainly and suggest filing a catalog entry -- never guess its generation or
capabilities by analogy to hardware that looks similar.

All lookups go through `scripts/catalog_lookup.py`, a dependency-free
Python script that reads the bundled catalog snapshot at
`assets/catalog.json` and prints one JSON value per call. It implements the
same lookups as this project's Rust/Python/Go bindings, including the exact
same notes-overlay behavior, so results agree regardless of which one is
used to answer a question.

## Looking up a device (with notes applied)

```bash
python3 scripts/catalog_lookup.py resolve 74a1
```

Returns the fully resolved GPU entry for device ID `74a1` (MI300X): specs,
generation, gfx target, memory model, precision support, and any
`specs.<key>` overrides from the notes overlay already applied. Device IDs
are case-insensitive. If you need the raw entry *without* the overlay
applied, use `gpu` instead of `resolve`.

If the device isn't cataloged, the script exits 1 and prints
`{"found": false, "message": "not yet cataloged", "device_id": "..."}` --
relay that plainly rather than guessing.

## Finding GPUs by gfx target or generation

```bash
python3 scripts/catalog_lookup.py gpus --gfx-target gfx1151
python3 scripts/catalog_lookup.py gpus --generation RDNA3.5
```

Useful for "what other products share this architecture" questions.

## Checking NPU presence for a device

```bash
python3 scripts/catalog_lookup.py npu 17f0
python3 scripts/catalog_lookup.py npu 17f0 --revision 10
```

One PCI `device_id` can bind to several NPU hardware generations
(distinguished by `revision_id`) -- `17f0` alone returns all 3 (NPU4/5/6,
jointly "Strix / Krackan / Strix Halo / Gorgon Point"; the driver source
itself can't disambiguate further without a live firmware query). Pass
`--revision` to narrow to one.

## Listing notes for a device

```bash
python3 scripts/catalog_lookup.py notes 1586
```

Always returns the raw, unfiltered list of notes for that device --
surfaced explicitly, never silently folded into "the data." A note may or
may not carry an `override` (only `specs.<key>` overrides are ever applied
by `resolve`); an annotation-only note (no `override`) still shows up here
even though it doesn't change what `resolve` returns. Always check this
when a fact seems surprising or safety-relevant -- e.g. device `1586`
(Strix Halo) has no `precision_support` from any source, *and* carries a
note that even a future value there would still be unconfirmed on real
hardware until someone validates it.

## Explaining where a fact comes from

```bash
python3 scripts/catalog_lookup.py sources
```

Lists every source with its name, URL, and pinned ref (commit SHA). Which
source backs which field group:

| Source | Backs |
|---|---|
| `rocm-gpu-specs` | `product_name`, `graphics_model`, `generation`, `gfx_target`, `memory_model`, `specs` |
| `rocm-precision-support` | `precision_support` |
| `libdrm-amdgpu-ids` | `device_id` (joined onto the row above by normalized marketing name) |
| `llvm-amdgpu-usage` | Cross-check only -- never changes a `GpuEntry` field directly |
| `xdna-driver-npu-pciids` | Everything under `npus` |

A hand-authored note (via `notes`) is not sourced from any of the above --
it's a human-confirmed fact or caveat, dated in `validated_on` and
optionally attributed in `validated_by`.

## Freshness

The bundled snapshot at `assets/catalog.json` is `catalog_version
0.1.0`. No GitHub Release has been cut yet for this project, so there is no
pinned release-asset URL to fetch a newer catalog from today -- check
https://github.com/AMD-melliott/amd-platform-catalog/releases once one
exists, or point `--catalog <path>` at a fresher `catalog.json` if you have
one (e.g. a local clone's `catalog/catalog.json`). Don't assume the bundled
snapshot's absence of a fact means the fact doesn't exist upstream -- say
it's not in *this* snapshot, and suggest checking for an update.
