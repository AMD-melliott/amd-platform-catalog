"""Empirically probes precision/data-type support on real AMD hardware.

Unlike everything under tools/catalog_build/, this is NOT part of the
offline ingestion pipeline. It must run on a machine with a real AMD
GPU, ROCm, and a ROCm build of PyTorch installed. It exists to help close
PRD §10's "RDNA3.5 missing from precision-support.rst" gap (and any other
generation/product ROCm's own doc hasn't caught up to yet) by producing
real, on-hardware evidence a human can review before hand-authoring a
catalog/notes.json entry (PRD §6.5). This script never writes to
notes.json itself, and its output is not a source of truth on its own.

Tests the same data-type keys used in catalog.json's `precision_support`
object (see tools/catalog_build/ingest_rocm_precision_support.py's
_TYPE_KEY_MAP) so results map directly onto that field.

IMPORTANT CAVEAT: a "not supported" result here means this specific
PyTorch build's operator kernels rejected the op on this GPU. It is NOT
proof the underlying ISA/silicon lacks the capability. ROCm's own
precision-support.rst (what this project's `precision_support` field
mirrors) describes HIP C++ type implementation support, a lower-level
claim than "does today's PyTorch release ship a kernel for this." A
"not supported" verdict here is a real, useful, on-hardware data point,
but treat it as "this framework's operator coverage today", not as a
substitute for that distinction. Say so plainly if you write a note
from this, the same way the catalog itself never overstates a claim.

Usage (from an environment with a ROCm PyTorch install, e.g. a venv
created per https://pytorch.org/get-started/locally/ for ROCm):

    python3 tools/hardware_validation/validate_precision_support.py
    python3 tools/hardware_validation/validate_precision_support.py --output report.json
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import re
import subprocess
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class ProbeSpec:
    catalog_key: str
    torch_dtype_names: tuple[str, ...]  # tried in order; first that exists on this torch build wins
    kind: str  # "int" | "float" | "fp8" | "narrow" (fp4/fp6: existence/creation only, no compute-op test yet)


# Mirrors ingest_rocm_precision_support.py's _TYPE_KEY_MAP values exactly, so
# a result here can be dropped straight into a catalog/notes.json draft
# keyed the same way as `precision_support`.
PROBES: list[ProbeSpec] = [
    ProbeSpec("int8", ("int8",), "int"),
    ProbeSpec("int16", ("int16",), "int"),
    ProbeSpec("int32", ("int32",), "int"),
    ProbeSpec("int64", ("int64",), "int"),
    ProbeSpec("float16", ("float16",), "float"),
    ProbeSpec("bfloat16", ("bfloat16",), "float"),
    ProbeSpec("float32", ("float32",), "float"),
    ProbeSpec("float64", ("float64",), "float"),
    ProbeSpec("fp8_e4m3", ("float8_e4m3fn",), "fp8"),
    ProbeSpec("fp8_e5m2", ("float8_e5m2",), "fp8"),
    ProbeSpec("fp8_e4m3_fnuz", ("float8_e4m3fnuz",), "fp8"),
    ProbeSpec("fp8_e5m2_fnuz", ("float8_e5m2fnuz",), "fp8"),
    ProbeSpec("fp4_e2m1", ("float4_e2m1fn_x2", "float4_e2m1fn"), "narrow"),
    ProbeSpec("fp6_e2m3", ("float6_e2m3fn_x2", "float6_e2m3fn"), "narrow"),
    ProbeSpec("fp6_e3m2", ("float6_e3m2fn_x2", "float6_e3m2fn"), "narrow"),
]


def _detect_pci_device_id(device_index: int) -> str | None:
    """Best-effort only: returns None on anything unexpected rather than
    guessing. Assumes amd-smi's GPU listing order matches torch's device
    index, which holds for a single-GPU box but isn't guaranteed on a
    multi-GPU system.
    """
    try:
        output = subprocess.run(["amd-smi", "list"], capture_output=True, text=True, timeout=10, check=True).stdout
    except Exception:
        return None
    bdfs = re.findall(r"BDF:\s*(\S+)", output)
    if device_index >= len(bdfs):
        return None
    try:
        raw = Path(f"/sys/bus/pci/devices/{bdfs[device_index]}/device").read_text().strip()
    except OSError:
        return None
    return raw.removeprefix("0x").lower()


def _probe_numeric(torch, dtype, kind: str) -> tuple[bool, str]:
    """int/float kinds: create on GPU, elementwise add, and (float only) a
    small matmul, checked against the expected result, not just "did it
    raise".
    """
    try:
        a = torch.arange(1, 17, device="cuda").to(dtype).reshape(4, 4)
        b = a + a
        if b.device.type != "cuda":
            return False, "result left the GPU device"
        if kind == "float":
            extra = a.to(torch.float32) @ a.to(torch.float32)
            extra_ok = bool(torch.isfinite(extra).all())
            extra_desc = "matmul"
        else:
            extra = a.sum()
            extra_ok = int(extra.item()) == 136  # sum(1..16)
            extra_desc = "sum"
        if not extra_ok:
            return False, f"{extra_desc} produced an unexpected/non-finite result"
        expected = a.to(torch.float64) * 2
        if not torch.allclose(b.to(torch.float64), expected, rtol=1e-2, atol=1e-2):
            return False, "elementwise add did not match the expected result"
        return True, f"create + elementwise add + {extra_desc}, all correct"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _probe_fp8(torch, dtype) -> tuple[bool | None, str]:
    """fp8 variants are storage-only types in PyTorch: there's no generic
    elementwise op for them. The realistic vehicle for actually using one is
    torch._scaled_mm (the fused, hardware-accelerated GEMM path), so that's
    what's tested here, not a plain elementwise op.
    """
    try:
        torch.manual_seed(0)
        n = 32
        a = torch.randn(n, n, device="cuda")
        b = torch.randn(n, n, device="cuda")
        a8, b8 = a.to(dtype), b.to(dtype)
    except Exception as e:
        return None, f"tensor creation/cast failed: {type(e).__name__}: {e}"
    scale = torch.tensor(1.0, device="cuda")
    try:
        out = torch._scaled_mm(a8, b8.t().contiguous().t(), scale, scale, out_dtype=torch.float32)
        if not bool(torch.isfinite(out).all()):
            return False, "torch._scaled_mm ran but produced non-finite output"
        return True, "tensor create/cast ok; torch._scaled_mm (accelerated fp8 GEMM) ran and produced a finite result"
    except Exception as e:
        return False, (
            "tensor create/cast ok, but torch._scaled_mm (the accelerated fp8 GEMM path) failed: "
            f"{type(e).__name__}: {e}. This reflects what THIS PyTorch BUILD's kernels support on "
            "this GPU today, not necessarily the ISA/silicon's own native fp8 capability. See the "
            "module docstring's caveat before turning this into a notes.json claim."
        )


def _probe_narrow(torch, dtype_name: str, dtype) -> tuple[bool | None, str]:
    """fp4/fp6 are brand-new, packed (sub-byte) formats with no standardized
    compute-op path across torch builds yet. Only existence + raw creation
    is checked; this is NOT a "supported" claim either way.
    """
    try:
        raw = torch.randint(0, 256, (4, 4), dtype=torch.uint8, device="cuda")
        _ = raw.view(dtype)
        return None, (
            f"torch.{dtype_name} exists and raw tensor creation succeeded, but this probe doesn't "
            "exercise any compute op for it yet (too new/uncommon for a generic check). Treat as "
            "untested, not confirmed supported."
        )
    except Exception as e:
        return False, f"torch.{dtype_name} exists but tensor creation failed: {type(e).__name__}: {e}"


def probe(torch, spec: ProbeSpec) -> dict:
    torch_dtype = None
    torch_dtype_name = None
    for name in spec.torch_dtype_names:
        candidate = getattr(torch, name, None)
        if candidate is not None:
            torch_dtype = candidate
            torch_dtype_name = name
            break

    if torch_dtype is None:
        return {
            "torch_dtype": None,
            "verdict": None,
            "detail": f"none of {spec.torch_dtype_names} exist as a dtype in this torch build ({torch.__version__})",
        }

    assert torch_dtype_name is not None  # set in the same loop iteration as torch_dtype, always together

    if spec.kind in ("int", "float"):
        verdict, detail = _probe_numeric(torch, torch_dtype, spec.kind)
    elif spec.kind == "fp8":
        verdict, detail = _probe_fp8(torch, torch_dtype)
    else:
        verdict, detail = _probe_narrow(torch, torch_dtype_name, torch_dtype)

    return {"torch_dtype": torch_dtype_name, "verdict": verdict, "detail": detail}


def build_report() -> dict:
    try:
        import torch
    except ImportError as e:
        raise SystemExit(
            "torch is not installed in this Python environment. This script needs a ROCm build of "
            "PyTorch (see https://pytorch.org/get-started/locally/, select ROCm), installed "
            "separately from this project's own uv-managed dependencies, which deliberately don't "
            "include it."
        ) from e

    if not torch.cuda.is_available():
        raise SystemExit("No GPU visible to PyTorch (torch.cuda.is_available() is False). Nothing to probe.")

    device_index = 0
    props = torch.cuda.get_device_properties(device_index)

    results = {spec.catalog_key: probe(torch, spec) for spec in PROBES}

    return {
        "probed_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "device": {
            "index": device_index,
            "name": torch.cuda.get_device_name(device_index),
            "gcn_arch_name": getattr(props, "gcnArchName", None),
            "pci_device_id": _detect_pci_device_id(device_index),
        },
        "results": results,
    }


def _print_human_readable(report: dict) -> None:
    device = report["device"]
    print(f"Device:       {device['name']} ({device['gcn_arch_name']})")
    print(f"PCI device_id: {device['pci_device_id'] or 'could not detect, see script docstring'}")
    print(f"PyTorch:      {report['torch_version']} (ROCm/HIP {report['hip_version']})")
    print(f"Probed at:    {report['probed_at']}")
    print()
    verdict_label = {True: "SUPPORTED", False: "NOT SUPPORTED", None: "UNTESTED"}
    for key, result in report["results"].items():
        label = verdict_label[result["verdict"]]
        dtype = result["torch_dtype"] or "-"
        print(f"  {key:<16} {label:<14} (torch.{dtype})")
        print(f"      {result['detail']}")
    print()
    print(
        "This is diagnostic output for a human to review, not an automatic source. See the module\n"
        "docstring's caveat about framework-level vs. ISA-level support before hand-authoring a\n"
        "catalog/notes.json entry (PRD §6.5 / CONTRIBUTING.md). Set real validated_by/validated_on\n"
        "yourself; this script does not write to notes.json."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=None, help="Also write the full JSON report to this path.")
    args = parser.parse_args(argv)

    report = build_report()
    _print_human_readable(report)

    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nwrote {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
