#!/usr/bin/env python3
"""Zero-dependency lookup CLI for the AMD Platform Catalog (see ../SKILL.md).

Mirrors the Rust/Python/Go bindings' own method names 1:1 (gpu_by_device_id,
resolve_gpu, gpus_by_gfx_target, gpus_by_generation, npus_by_device_id,
npu_by_device_id_and_revision, notes_for_device) so behavior -- especially
the notes-overlay restriction to "specs.<key>" targets, and case-insensitive
device IDs -- stays identical across all four. Never guesses: an unknown
device_id is reported plainly, not filled in by analogy to a similar one.

Every subcommand prints one JSON value to stdout. Lookups that find nothing
print {"found": false, ...} and exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "assets" / "catalog.json"


def _normalize_hex(device_id: str) -> str:
    return device_id.strip().lower()


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def gpu_by_device_id(catalog: dict[str, Any], device_id: str) -> dict[str, Any] | None:
    needle = _normalize_hex(device_id)
    for gpu in catalog["gpus"]:
        gpu_device_id = gpu.get("device_id")
        if gpu_device_id is not None and _normalize_hex(gpu_device_id) == needle:
            return gpu
    return None


def notes_for_device(catalog: dict[str, Any], device_id: str) -> list[dict[str, Any]]:
    """Every note applicable to a device ID, unfiltered -- never silently
    folded into "the data" (see also resolve_gpu, which applies a subset).
    """
    needle = _normalize_hex(device_id)
    return [n for n in catalog["notes"] if _normalize_hex(n["device_id"]) == needle]


def resolve_gpu(catalog: dict[str, Any], device_id: str) -> dict[str, Any] | None:
    """Looks up a GPU by device ID and applies its notes overlay.

    Only supports overrides whose field is "specs.<key>" -- an open map,
    safe to overwrite by key. Extend this if a real example of a
    top-level-field override ever exists to design against.
    """
    entry = gpu_by_device_id(catalog, device_id)
    if entry is None:
        return None
    resolved = dict(entry)
    resolved["specs"] = dict(entry.get("specs") or {})
    for note in notes_for_device(catalog, device_id):
        override = note.get("override")
        if override is None:
            continue
        field = note["field"]
        if field.startswith("specs."):
            resolved["specs"][field.removeprefix("specs.")] = override
    return resolved


def gpus_by_gfx_target(catalog: dict[str, Any], gfx_target: str) -> list[dict[str, Any]]:
    return [g for g in catalog["gpus"] if g["gfx_target"] == gfx_target]


def gpus_by_generation(catalog: dict[str, Any], generation: str) -> list[dict[str, Any]]:
    return [g for g in catalog["gpus"] if g["generation"] == generation]


def npus_by_device_id(catalog: dict[str, Any], device_id: str) -> list[dict[str, Any]]:
    """All NPU rows for a device ID (may be several -- one device_id can
    bind to multiple (device_id, revision_id) hardware generations).
    """
    needle = _normalize_hex(device_id)
    return [n for n in catalog["npus"] if _normalize_hex(n["device_id"]) == needle]


def npu_by_device_id_and_revision(catalog: dict[str, Any], device_id: str, revision_id: str) -> dict[str, Any] | None:
    needle_device = _normalize_hex(device_id)
    needle_revision = _normalize_hex(revision_id)
    for npu in catalog["npus"]:
        if _normalize_hex(npu["device_id"]) != needle_device:
            continue
        npu_revision = npu.get("revision_id")
        if npu_revision is not None and _normalize_hex(npu_revision) == needle_revision:
            return npu
    return None


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2))


def _not_found(**fields: Any) -> NoReturn:
    _print_json({"found": False, "message": "not yet cataloged", **fields})
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Path to catalog.json (default: bundled snapshot at {DEFAULT_CATALOG})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    gpu_parser = subparsers.add_parser("gpu", help="Raw GPU lookup by device_id, no notes overlay applied")
    gpu_parser.add_argument("device_id")

    resolve_parser = subparsers.add_parser("resolve", help="GPU lookup by device_id with notes overlay applied")
    resolve_parser.add_argument("device_id")

    gpus_parser = subparsers.add_parser("gpus", help="List GPUs sharing a gfx_target or generation")
    gpus_group = gpus_parser.add_mutually_exclusive_group(required=True)
    gpus_group.add_argument("--gfx-target")
    gpus_group.add_argument("--generation")

    npu_parser = subparsers.add_parser("npu", help="NPU lookup by device_id, optionally narrowed by revision_id")
    npu_parser.add_argument("device_id")
    npu_parser.add_argument("--revision")

    notes_parser = subparsers.add_parser("notes", help="Every note for a device_id, unfiltered")
    notes_parser.add_argument("device_id")

    subparsers.add_parser("sources", help="List the catalog's source provenance entries")

    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog)

    if args.command == "gpu":
        entry = gpu_by_device_id(catalog, args.device_id)
        if entry is None:
            _not_found(device_id=args.device_id)
        _print_json({"found": True, **entry})

    elif args.command == "resolve":
        entry = resolve_gpu(catalog, args.device_id)
        if entry is None:
            _not_found(device_id=args.device_id)
        _print_json({"found": True, **entry})

    elif args.command == "gpus":
        if args.gfx_target:
            results = gpus_by_gfx_target(catalog, args.gfx_target)
        else:
            results = gpus_by_generation(catalog, args.generation)
        _print_json({"count": len(results), "gpus": results})

    elif args.command == "npu":
        if args.revision:
            entry = npu_by_device_id_and_revision(catalog, args.device_id, args.revision)
            if entry is None:
                _not_found(device_id=args.device_id, revision_id=args.revision)
            _print_json({"found": True, **entry})
        else:
            results = npus_by_device_id(catalog, args.device_id)
            if not results:
                _not_found(device_id=args.device_id)
            _print_json({"found": True, "count": len(results), "npus": results})

    elif args.command == "notes":
        results = notes_for_device(catalog, args.device_id)
        _print_json({"count": len(results), "notes": results})

    elif args.command == "sources":
        _print_json({"sources": catalog["sources"]})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
