"""Merge ingested sources into a versioned catalog.json (PRD §7.2/§7.3).

Phase 0/1 spike: gpu-specs.rst and precision-support.rst are ingested per
Phase 0, plus libdrm's amdgpu.ids (Phase 1 continuation) to populate
GpuEntry.device_id where the join resolves unambiguously (see
match_gpu_device_ids.py). LLVM AMDGPUUsage cross-check, NPU PCI-ID
ingestion, and the hand-maintained notes overlay are later PRD phases --
``npus`` and ``notes`` are emitted as empty arrays on purpose, not silently
populated.
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
    ingest_libdrm_amdgpu_ids,
    ingest_rocm_gpu_specs,
    ingest_rocm_precision_support,
    match_gpu_device_ids,
)

ROCM_REPO = "ROCm/ROCm"
ROCM_BRANCH = "develop"
GPU_SPECS_PATH = "docs/reference/gpu-specs.rst"
PRECISION_SUPPORT_PATH = "docs/reference/precision-support.rst"

LIBDRM_PROJECT = "mesa/libdrm"
LIBDRM_BRANCH = "main"
AMDGPU_IDS_PATH = "data/amdgpu.ids"

# Pre-release: this is the Phase 0/1 spike, not the real PRD v0.1.0 release.
CATALOG_VERSION = "0.0.1"

DEFAULT_OUTPUT = Path("catalog/catalog.json")


@dataclasses.dataclass
class SourceDoc:
    name: str
    url: str
    ref: str
    text: str


def _raw_url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{ROCM_REPO}/{ROCM_BRANCH}/{path}"


def _blob_url(path: str) -> str:
    return f"https://github.com/{ROCM_REPO}/blob/{ROCM_BRANCH}/{path}"


def _latest_commit_sha(path: str) -> str:
    resp = requests.get(
        f"https://api.github.com/repos/{ROCM_REPO}/commits",
        params={"path": path, "sha": ROCM_BRANCH, "per_page": 1},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()[0]["sha"]


def fetch_source(name: str, path: str) -> SourceDoc:
    resp = requests.get(_raw_url(path), timeout=30)
    resp.raise_for_status()
    return SourceDoc(name=name, url=_blob_url(path), ref=_latest_commit_sha(path), text=resp.text)


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


# gpu-specs.rst labels MI100's architecture "CDNA" (no digit); every other
# source (precision-support.rst included) calls it "CDNA1". Per product-owner
# confirmation (2026-09-02), CDNA had no numbered siblings until CDNA2
# shipped, so these are the same generation -- aliased only for this lookup.
# The sourced `generation` string on the GpuEntry itself is left untouched.
_PRECISION_LOOKUP_ALIASES = {"CDNA": "CDNA1"}


def build_catalog(gpu_specs: SourceDoc, precision_support: SourceDoc, libdrm_amdgpu_ids: SourceDoc) -> dict:
    gpu_entries = ingest_rocm_gpu_specs.ingest(gpu_specs.text)
    precision_by_generation = ingest_rocm_precision_support.ingest(precision_support.text)
    amdgpu_id_rows = ingest_libdrm_amdgpu_ids.ingest(libdrm_amdgpu_ids.text)

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
        lookup_generation = _PRECISION_LOOKUP_ALIASES.get(generation, generation)
        precision = precision_by_generation.get(lookup_generation)
        if precision:
            entry["precision_support"] = precision
        else:
            print(
                f"warning: no precision_support data for generation "
                f"{entry.get('generation')!r} (product {entry.get('product_name')!r})",
                file=sys.stderr,
            )

    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {"name": gpu_specs.name, "url": gpu_specs.url, "ref": gpu_specs.ref},
            {"name": precision_support.name, "url": precision_support.url, "ref": precision_support.ref},
            {"name": libdrm_amdgpu_ids.name, "url": libdrm_amdgpu_ids.url, "ref": libdrm_amdgpu_ids.ref},
        ],
        "gpus": gpu_entries,
        "npus": [],
        "notes": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="Read gpu-specs.rst/precision-support.rst/amdgpu.ids from this local "
        "directory instead of fetching them live (offline mode).",
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
    else:
        gpu_specs = fetch_source("rocm-gpu-specs", GPU_SPECS_PATH)
        precision_support = fetch_source("rocm-precision-support", PRECISION_SUPPORT_PATH)
        libdrm_amdgpu_ids = fetch_libdrm_amdgpu_ids()

    catalog = build_catalog(gpu_specs, precision_support, libdrm_amdgpu_ids)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.output} ({len(catalog['gpus'])} gpu entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
