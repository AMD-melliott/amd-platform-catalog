# Hardware validation

Scripts here are deliberately separate from `tools/catalog_build/`. That
pipeline is offline: it parses public documents and never touches real
hardware. Scripts in this directory do the opposite: they run *on* a real
AMD GPU/NPU to produce evidence a human can review before hand-authoring a
`catalog/notes.json` entry (PRD §6.5). None of them write to `notes.json`
themselves, and none of them are part of CI (some need packages, like a
ROCm build of PyTorch, that this project's own `uv` dependencies
deliberately don't include).

## `validate_precision_support.py`

Empirically probes which `precision_support` data types (the same keys
`catalog.json` uses: `int8`, `float16`, `bfloat16`, `fp8_e4m3`,
`fp8_e4m3_fnuz`, etc.) actually work on the current GPU via PyTorch. Exists
to help close gaps like PRD §10's "RDNA3.5 missing from
`precision-support.rst`" -- a generation ROCm's own doc hasn't caught up to
yet.

Requires a ROCm build of PyTorch (see
[pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/),
select ROCm) installed in whatever Python environment you run it with --
not this project's own `uv`-managed one.

```bash
python3 tools/hardware_validation/validate_precision_support.py
python3 tools/hardware_validation/validate_precision_support.py --output report.json
```

Read the module docstring before treating a result as settled: a "not
supported" verdict means *this specific PyTorch build's kernels* rejected
the operation on *this* GPU today. It is real, useful, on-hardware
evidence, but it is not automatically the same claim `precision-support.rst`
makes (native HIP C++ type implementation support at the ISA/compiler
level) -- a framework not shipping a kernel yet isn't proof the silicon
can't do it. Say so plainly in any note you write from this, the same way
the catalog itself never overstates a claim.

## `validate_precision_support_hip.cpp` / `.sh`

Tests the same 15 `precision_support` keys, but one level lower than the
PyTorch script: a small HIP C++ program (`.cpp`, built and run by the
`.sh` wrapper) that constructs each type from a `float` *on the GPU*,
converts it back, adds two values, and checks the result -- exercising the
HIP compiler/type system directly, which is exactly what
`precision-support.rst`'s own "HIP C++ Type implementation support"
framing measures, rather than any one ML framework's operator coverage.

Requires `hipcc` (a ROCm/HIP install; not this project's own dependencies)
and a real AMD GPU.

```bash
tools/hardware_validation/validate_precision_support_hip.sh
```

On Strix Halo (gfx1151), this currently shows all 15 types passing the
on-device roundtrip -- including all four fp8 variants and both fp6
variants, which the PyTorch script either couldn't test at all (fp6 has no
matching dtype in most PyTorch builds) or reported as failing (fp8, via
`torch._scaled_mm`'s own "ROCm MI300+ only" gate). The two results aren't
contradictory: HIP's fp8 headers (`amd_hip_fp8.h`) explicitly gate certain
fp8 variants as host-only depending on target architecture, and gfx1151
falls into the "neither gfx942 nor gfx1200-class" bucket where both
variant families stay device-usable -- so the type itself works on this
hardware even though PyTorch's *accelerated GEMM kernel* for it doesn't
exist yet on this architecture. Read both scripts' results together: HIP
says the type is usable on-device; PyTorch says whether today's build has
a fast kernel for it. Neither alone is the full picture.

**Known limitation** (documented in the file): the fp8 host-vs-device
gating is architecture-dependent at *compile* time, and this file assumes
every fp8 variant is device-usable on the target it's compiled for. That
holds for gfx1151 and older/generic targets, but compiling for gfx942
(MI300) or gfx1200/1201-class hardware -- where HIP's own headers make the
*other* fp8 family host-only -- will fail to compile with a specific,
readable error rather than silently mis-reporting. Extend with per-type
preprocessor guards if this needs to run on that class of hardware.

## Other candidates (not yet written)

Suggested here rather than implemented, since each is its own scoped
decision:

- **Device self-identification check.** Read the real PCI `device_id`/
  `revision_id`/`gfx_target` off the machine you're running on (via
  `/sys/class/drm/*/device/{device,revision}` and `rocminfo`) and cross-check
  against what `resolve_gpu()` returns for that ID -- catches a catalog
  entry that's wrong for real hardware, not just internally inconsistent.
  Cheap: no PyTorch needed, just stdlib + the Python binding.
- **Memory-model / heap-type check.** Generalizes the one hand-check
  already backing Strix Halo's `memory_pool` note (KFD heap-type vs. the
  real `amd-smi` GTT/VRAM split) into a reusable script instead of a
  one-off manual observation.
- **NPU presence check.** Confirms the NPU device_id/hw_gen the catalog
  expects for a given platform is actually visible in `lspci`/sysfs on that
  exact machine.
