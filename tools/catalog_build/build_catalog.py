"""Merge ingested sources into a versioned catalog.json (PRD §7.2/§7.3).

Phase 0/1: gpu-specs.rst and precision-support.rst are ingested per Phase 0;
libdrm's amdgpu.ids populates GpuEntry.device_id where the join resolves
unambiguously (see match_gpu_device_ids.py); LLVM's AMDGPUUsage Processors
table is ingested purely as a build-time cross-check (see cross_check_llvm.py)
-- it never adds/changes GpuEntry fields, only emits warnings for generation
mismatches and gfx_targets not yet in gpu-specs.rst; amd/xdna-driver's own
PCI ID table populates ``npus`` directly (see ingest_xdna_pciids.py -- family
is left unset where the driver source itself provides no marketing name).
The hand-maintained notes overlay is a later PRD phase -- ``notes`` is
emitted as an empty array on purpose, not silently populated.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import sys
import urllib.parse
from pathlib import Path

import requests

from . import (
    cross_check_llvm,
    ingest_libdrm_amdgpu_ids,
    ingest_llvm_amdgpu_usage,
    ingest_rocm_gpu_specs,
    ingest_rocm_precision_support,
    ingest_xdna_pciids,
    match_gpu_device_ids,
)

ROCM_REPO = "ROCm/ROCm"
ROCM_BRANCH = "develop"
GPU_SPECS_PATH = "docs/reference/gpu-specs.rst"
PRECISION_SUPPORT_PATH = "docs/reference/precision-support.rst"

LLVM_REPO = "llvm/llvm-project"
LLVM_BRANCH = "main"
AMDGPU_USAGE_PATH = "llvm/docs/AMDGPUUsage.rst"

LIBDRM_PROJECT = "mesa/libdrm"
LIBDRM_BRANCH = "main"
AMDGPU_IDS_PATH = "data/amdgpu.ids"

XDNA_REPO = "amd/xdna-driver"
XDNA_BRANCH = "main"
XDNA_DIR = "drivers/accel/amdxdna"
XDNA_PCI_DRV_PATH = f"{XDNA_DIR}/amdxdna_pci_drv.c"
XDNA_REGS_FILENAMES = ["npu1_regs.c", "npu3_regs.c", "npu4_regs.c", "npu5_regs.c", "npu6_regs.c"]

# Pre-release: this is the Phase 0/1 spike, not the real PRD v0.1.0 release.
CATALOG_VERSION = "0.0.1"

DEFAULT_OUTPUT = Path("catalog/catalog.json")


@dataclasses.dataclass
class SourceDoc:
    name: str
    url: str
    ref: str
    text: str


def _github_raw_url(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _github_blob_url(repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{repo}/blob/{branch}/{path}"


def _github_latest_commit_sha(repo: str, branch: str, path: str) -> str:
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/commits",
        params={"path": path, "sha": branch, "per_page": 1},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()[0]["sha"]


def _blob_url(path: str) -> str:
    return _github_blob_url(ROCM_REPO, ROCM_BRANCH, path)


def fetch_source(name: str, path: str) -> SourceDoc:
    resp = requests.get(_github_raw_url(ROCM_REPO, ROCM_BRANCH, path), timeout=30)
    resp.raise_for_status()
    ref = _github_latest_commit_sha(ROCM_REPO, ROCM_BRANCH, path)
    return SourceDoc(name=name, url=_blob_url(path), ref=ref, text=resp.text)


def _llvm_blob_url() -> str:
    return _github_blob_url(LLVM_REPO, LLVM_BRANCH, AMDGPU_USAGE_PATH)


def fetch_llvm_amdgpu_usage() -> SourceDoc:
    resp = requests.get(_github_raw_url(LLVM_REPO, LLVM_BRANCH, AMDGPU_USAGE_PATH), timeout=30)
    resp.raise_for_status()
    ref = _github_latest_commit_sha(LLVM_REPO, LLVM_BRANCH, AMDGPU_USAGE_PATH)
    return SourceDoc(name="llvm-amdgpu-usage", url=_llvm_blob_url(), ref=ref, text=resp.text)


def _libdrm_raw_url() -> str:
    return f"https://gitlab.freedesktop.org/{LIBDRM_PROJECT}/-/raw/{LIBDRM_BRANCH}/{AMDGPU_IDS_PATH}"


def _libdrm_blob_url() -> str:
    return f"https://gitlab.freedesktop.org/{LIBDRM_PROJECT}/-/blob/{LIBDRM_BRANCH}/{AMDGPU_IDS_PATH}"


def _libdrm_latest_commit_sha() -> str:
    project_encoded = urllib.parse.quote(LIBDRM_PROJECT, safe="")
    resp = requests.get(
        f"https://gitlab.freedesktop.org/api/v4/projects/{project_encoded}/repository/commits",
        params={"path": AMDGPU_IDS_PATH, "ref_name": LIBDRM_BRANCH, "per_page": 1},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()[0]["id"]


def fetch_libdrm_amdgpu_ids() -> SourceDoc:
    resp = requests.get(_libdrm_raw_url(), timeout=30)
    resp.raise_for_status()
    return SourceDoc(
        name="libdrm-amdgpu-ids", url=_libdrm_blob_url(), ref=_libdrm_latest_commit_sha(), text=resp.text
    )


def load_fixture(name: str, file_path: Path, url: str) -> SourceDoc:
    return SourceDoc(name=name, url=url, ref="fixture", text=file_path.read_text())


@dataclasses.dataclass
class XdnaSource:
    """xdna-driver spans several files (one pci_ids table + several
    per-generation regs.c files with the marketing-name tables) but is one
    logical, singly-provenanced source -- `source_doc` carries the `sources`
    entry, `pci_drv_text`/`regs_texts` are what ingest_xdna_pciids.ingest()
    actually parses."""

    source_doc: SourceDoc
    pci_drv_text: str
    regs_texts: list[str]


def _xdna_blob_url() -> str:
    return _github_blob_url(XDNA_REPO, XDNA_BRANCH, XDNA_DIR)


def fetch_xdna_pciids() -> XdnaSource:
    pci_drv_resp = requests.get(_github_raw_url(XDNA_REPO, XDNA_BRANCH, XDNA_PCI_DRV_PATH), timeout=30)
    pci_drv_resp.raise_for_status()
    regs_texts = []
    for filename in XDNA_REGS_FILENAMES:
        resp = requests.get(_github_raw_url(XDNA_REPO, XDNA_BRANCH, f"{XDNA_DIR}/{filename}"), timeout=30)
        resp.raise_for_status()
        regs_texts.append(resp.text)
    ref_resp = requests.get(f"https://api.github.com/repos/{XDNA_REPO}/commits/{XDNA_BRANCH}", timeout=30)
    ref_resp.raise_for_status()
    source_doc = SourceDoc(name="xdna-driver-npu-pciids", url=_xdna_blob_url(), ref=ref_resp.json()["sha"], text="")
    return XdnaSource(source_doc=source_doc, pci_drv_text=pci_drv_resp.text, regs_texts=regs_texts)


def load_xdna_fixture(fixtures_dir: Path) -> XdnaSource:
    xdna_dir = fixtures_dir / "xdna_driver"
    pci_drv_text = (xdna_dir / "amdxdna_pci_drv.c").read_text()
    regs_texts = [(xdna_dir / filename).read_text() for filename in XDNA_REGS_FILENAMES]
    source_doc = SourceDoc(name="xdna-driver-npu-pciids", url=_xdna_blob_url(), ref="fixture", text="")
    return XdnaSource(source_doc=source_doc, pci_drv_text=pci_drv_text, regs_texts=regs_texts)


# gpu-specs.rst labels MI100's architecture "CDNA" (no digit); every other
# ROCm source (precision-support.rst included) calls it "CDNA1". Per
# product-owner confirmation (2026-09-02), CDNA had no numbered siblings
# until CDNA2 shipped, so these are the same generation -- aliased only for
# generation-keyed lookups/comparisons (precision join, LLVM cross-check).
# The sourced `generation` string on the GpuEntry itself is left untouched.
# Deliberately NOT extended to LLVM's old-chip naming (VEGA/VEGA7NM for
# gfx900/gfx906) -- that's a different naming scheme from a different
# project, not a confirmed alias, so those surface as cross-check warnings
# instead (see PRD).
_GENERATION_ALIASES = {"CDNA": "CDNA1"}


def build_catalog(
    gpu_specs: SourceDoc,
    precision_support: SourceDoc,
    libdrm_amdgpu_ids: SourceDoc,
    llvm_amdgpu_usage: SourceDoc,
    xdna_pciids: XdnaSource,
) -> dict:
    gpu_entries = ingest_rocm_gpu_specs.ingest(gpu_specs.text)
    precision_by_generation = ingest_rocm_precision_support.ingest(precision_support.text)
    amdgpu_id_rows = ingest_libdrm_amdgpu_ids.ingest(libdrm_amdgpu_ids.text)
    llvm_entries = ingest_llvm_amdgpu_usage.ingest(llvm_amdgpu_usage.text)
    npu_id_rows = ingest_xdna_pciids.ingest(xdna_pciids.pci_drv_text, xdna_pciids.regs_texts)

    device_id_report = match_gpu_device_ids.apply_device_ids(gpu_entries, amdgpu_id_rows)
    for product_name in device_id_report.unmatched:
        print(
            f"warning: no device_id match for product {product_name!r} (libdrm amdgpu.ids)",
            file=sys.stderr,
        )
    for product_name, candidates in device_id_report.ambiguous:
        print(
            f"warning: ambiguous device_id match for product {product_name!r}: "
            f"candidates {sorted(candidates)} (libdrm amdgpu.ids)",
            file=sys.stderr,
        )

    for entry in gpu_entries:
        generation = entry.get("generation")
        lookup_generation = _GENERATION_ALIASES.get(generation, generation)
        precision = precision_by_generation.get(lookup_generation)
        if precision:
            entry["precision_support"] = precision
        else:
            print(
                f"warning: no precision_support data for generation "
                f"{entry.get('generation')!r} (product {entry.get('product_name')!r})",
                file=sys.stderr,
            )

    cross_check_report = cross_check_llvm.cross_check(gpu_entries, llvm_entries, _GENERATION_ALIASES)
    for product_name, gfx_target, rocm_generation, llvm_generation in cross_check_report.mismatches:
        print(
            f"warning: generation mismatch for {product_name!r} ({gfx_target}): "
            f"gpu-specs.rst says {rocm_generation!r}, LLVM AMDGPUUsage says {llvm_generation!r}",
            file=sys.stderr,
        )
    for llvm_entry in cross_check_report.new_targets:
        print(
            f"warning: LLVM lists {llvm_entry.gfx_target!r} (generation {llvm_entry.generation!r}) "
            f"which is not yet in gpu-specs.rst",
            file=sys.stderr,
        )

    npu_entries = []
    for row in npu_id_rows:
        entry = {
            "device_id": row.device_id,
            "revision_id": row.revision_id,
            "vendor_id": row.vendor_id,
            "hw_gen": row.hw_gen,
        }
        if row.family is not None:
            entry["family"] = row.family
        npu_entries.append(entry)

    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {"name": gpu_specs.name, "url": gpu_specs.url, "ref": gpu_specs.ref},
            {"name": precision_support.name, "url": precision_support.url, "ref": precision_support.ref},
            {"name": libdrm_amdgpu_ids.name, "url": libdrm_amdgpu_ids.url, "ref": libdrm_amdgpu_ids.ref},
            {"name": llvm_amdgpu_usage.name, "url": llvm_amdgpu_usage.url, "ref": llvm_amdgpu_usage.ref},
            {
                "name": xdna_pciids.source_doc.name,
                "url": xdna_pciids.source_doc.url,
                "ref": xdna_pciids.source_doc.ref,
            },
        ],
        "gpus": gpu_entries,
        "npus": npu_entries,
        "notes": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Read gpu-specs.rst/precision-support.rst/amdgpu.ids/AMDGPUUsage.rst/"
        "xdna_driver/ from this local directory instead of fetching them live "
        "(offline mode).",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if args.fixtures_dir:
        gpu_specs = load_fixture("rocm-gpu-specs", args.fixtures_dir / "gpu-specs.rst", _blob_url(GPU_SPECS_PATH))
        precision_support = load_fixture(
            "rocm-precision-support", args.fixtures_dir / "precision-support.rst", _blob_url(PRECISION_SUPPORT_PATH)
        )
        libdrm_amdgpu_ids = load_fixture(
            "libdrm-amdgpu-ids", args.fixtures_dir / "amdgpu.ids", _libdrm_blob_url()
        )
        llvm_amdgpu_usage = load_fixture(
            "llvm-amdgpu-usage", args.fixtures_dir / "AMDGPUUsage.rst", _llvm_blob_url()
        )
        xdna_pciids = load_xdna_fixture(args.fixtures_dir)
    else:
        gpu_specs = fetch_source("rocm-gpu-specs", GPU_SPECS_PATH)
        precision_support = fetch_source("rocm-precision-support", PRECISION_SUPPORT_PATH)
        libdrm_amdgpu_ids = fetch_libdrm_amdgpu_ids()
        llvm_amdgpu_usage = fetch_llvm_amdgpu_usage()
        xdna_pciids = fetch_xdna_pciids()

    catalog = build_catalog(gpu_specs, precision_support, libdrm_amdgpu_ids, llvm_amdgpu_usage, xdna_pciids)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.output} ({len(catalog['gpus'])} gpu entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
