"""Thin Python binding over the AMD Platform Catalog (PRD §7.3).

Mirrors the Rust binding (bindings/rust) 1:1: aggregation happens offline,
this package just embeds the pinned catalog.json (as package data, no live
fetch), parses it once, and exposes typed lookups. When a device isn't in
the catalog, lookups return None -- callers should say so plainly and never
guess a generation/capability by analogy (PRD §7.4's "never synthesize,
never guess" failure mode).

Notes overlay scope (documented limitation, same as the Rust binding):
resolve_gpu() applies a NoteEntry.override onto the returned entry only when
its field is "specs.<key>" (an open map, safe to overwrite by key). Extend
_apply_gpu_overrides() when a real example of a top-level-field override
exists to design against.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, replace
from enum import Enum
from importlib import resources
from typing import Any


class MemoryModel(str, Enum):
    DEDICATED = "dedicated"
    UNIFIED = "unified"


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    EOS = "eos"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    ref: str


@dataclass(frozen=True)
class GpuEntry:
    gfx_target: str
    generation: str
    product_name: str
    memory_model: MemoryModel
    lifecycle_status: LifecycleStatus
    device_id: str | None = None
    revision_id: str | None = None
    graphics_model: str | None = None
    specs: dict[str, Any] = field(default_factory=dict)
    precision_support: dict[str, bool] | None = None


@dataclass(frozen=True)
class NpuEntry:
    device_id: str
    vendor_id: str
    hw_gen: str
    revision_id: str | None = None
    family: str | None = None
    llvm_target: str | None = None
    associated_gpu_device_ids: list[str] | None = None


@dataclass(frozen=True)
class NoteEntry:
    device_id: str
    field: str
    note: str
    validated_on: str
    override: Any = None
    validated_by: str | None = None


def _normalize_hex(device_id: str) -> str:
    return device_id.strip().lower()


def _source_from_dict(data: dict[str, Any]) -> Source:
    return Source(name=data["name"], url=data["url"], ref=data["ref"])


def _gpu_from_dict(data: dict[str, Any]) -> GpuEntry:
    return GpuEntry(
        gfx_target=data["gfx_target"],
        generation=data["generation"],
        product_name=data["product_name"],
        memory_model=MemoryModel(data["memory_model"]),
        lifecycle_status=LifecycleStatus(data["lifecycle_status"]),
        device_id=data.get("device_id"),
        revision_id=data.get("revision_id"),
        graphics_model=data.get("graphics_model"),
        specs=dict(data.get("specs") or {}),
        precision_support=data.get("precision_support"),
    )


def _npu_from_dict(data: dict[str, Any]) -> NpuEntry:
    return NpuEntry(
        device_id=data["device_id"],
        vendor_id=data["vendor_id"],
        hw_gen=data["hw_gen"],
        revision_id=data.get("revision_id"),
        family=data.get("family"),
        llvm_target=data.get("llvm_target"),
        associated_gpu_device_ids=data.get("associated_gpu_device_ids"),
    )


def _note_from_dict(data: dict[str, Any]) -> NoteEntry:
    return NoteEntry(
        device_id=data["device_id"],
        field=data["field"],
        note=data["note"],
        validated_on=data["validated_on"],
        override=data.get("override"),
        validated_by=data.get("validated_by"),
    )


def _apply_gpu_overrides(entry: GpuEntry, notes: list[NoteEntry]) -> GpuEntry:
    """Applies any `specs.<key>` overrides found in `notes` onto `entry.specs`.

    See the module-level docstring for why this is the only supported
    override target today.
    """
    specs = dict(entry.specs)
    for note in notes:
        if note.override is None:
            continue
        if note.field.startswith("specs."):
            specs[note.field.removeprefix("specs.")] = note.override
    return replace(entry, specs=specs)


@dataclass(frozen=True)
class Catalog:
    catalog_version: str
    generated_at: str
    sources: list[Source]
    gpus: list[GpuEntry]
    npus: list[NpuEntry]
    notes: list[NoteEntry]

    @classmethod
    def from_json(cls, text: str) -> Catalog:
        """Parses a catalog from arbitrary JSON text (e.g. a newer release
        fetched at runtime rather than the version embedded in this package).
        """
        data = json.loads(text)
        return cls(
            catalog_version=data["catalog_version"],
            generated_at=data["generated_at"],
            sources=[_source_from_dict(s) for s in data["sources"]],
            gpus=[_gpu_from_dict(g) for g in data["gpus"]],
            npus=[_npu_from_dict(n) for n in data["npus"]],
            notes=[_note_from_dict(n) for n in data["notes"]],
        )

    @classmethod
    def embedded(cls) -> Catalog:
        """The catalog embedded in this package, parsed once."""
        global _embedded_catalog
        with _embedded_catalog_lock:
            if _embedded_catalog is None:
                text = resources.files(__package__).joinpath("catalog.json").read_text()
                _embedded_catalog = cls.from_json(text)
            return _embedded_catalog

    def gpu_by_device_id(self, device_id: str) -> GpuEntry | None:
        """Raw lookup by PCI device ID, no notes overlay applied. Case-insensitive."""
        needle = _normalize_hex(device_id)
        for gpu in self.gpus:
            if gpu.device_id is not None and _normalize_hex(gpu.device_id) == needle:
                return gpu
        return None

    def resolve_gpu(self, device_id: str) -> GpuEntry | None:
        """Looks up a GPU by device ID and applies its notes overlay (PRD §7.3)."""
        entry = self.gpu_by_device_id(device_id)
        if entry is None:
            return None
        notes = self.notes_for_device(device_id)
        return _apply_gpu_overrides(entry, notes)

    def gpus_by_gfx_target(self, gfx_target: str) -> list[GpuEntry]:
        return [g for g in self.gpus if g.gfx_target == gfx_target]

    def gpus_by_generation(self, generation: str) -> list[GpuEntry]:
        return [g for g in self.gpus if g.generation == generation]

    def npus_by_device_id(self, device_id: str) -> list[NpuEntry]:
        """All NPU rows for a device ID (may be several -- PRD §6.4: one
        device_id can bind to multiple (device_id, revision_id) hardware
        generations).
        """
        needle = _normalize_hex(device_id)
        return [n for n in self.npus if _normalize_hex(n.device_id) == needle]

    def npu_by_device_id_and_revision(self, device_id: str, revision_id: str) -> NpuEntry | None:
        needle_device = _normalize_hex(device_id)
        needle_revision = _normalize_hex(revision_id)
        for npu in self.npus:
            if _normalize_hex(npu.device_id) != needle_device:
                continue
            if npu.revision_id is not None and _normalize_hex(npu.revision_id) == needle_revision:
                return npu
        return None

    def notes_for_device(self, device_id: str) -> list[NoteEntry]:
        """Every note applicable to a device ID, unfiltered -- PRD §7.4 verb 4:
        notes must be surfaced explicitly, never silently folded into "the
        data" (see also resolve_gpu, which applies a subset of these).
        """
        needle = _normalize_hex(device_id)
        return [n for n in self.notes if _normalize_hex(n.device_id) == needle]


_embedded_catalog: Catalog | None = None
_embedded_catalog_lock = threading.Lock()
