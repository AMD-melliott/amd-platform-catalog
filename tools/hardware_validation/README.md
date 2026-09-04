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
