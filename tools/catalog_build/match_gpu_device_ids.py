"""Join libdrm `amdgpu.ids` rows onto GpuEntry records to populate `device_id`.

Matching strategy (validated by hand against every row in both live sources
on 2026-09-02, see PRD §6.3): normalize each side's marketing name by
stripping AMD's own naming decorations, then require an *exact* match after
normalization. Exact match (not substring/fuzzy) is deliberate -- gpu-specs.rst's
plain "MI300X" is a substring of amdgpu.ids' "AMD Instinct MI300X HF" and
"...MI300X VF" too, so substring matching would silently misattribute a
variant SKU's device_id to the base part. A GpuEntry whose normalized name
doesn't land on exactly one device_id is left without one, with a reason
recorded -- never guessed.

Normalization handles:
- The "AMD " / "AMD Instinct " / "AMD Radeon Instinct " marketing prefixes
  amdgpu.ids uses that gpu-specs.rst's `Name`/`Graphics model` columns omit.
- The trailing " Graphics" suffix amdgpu.ids appends to integrated-graphics
  chip names (matched against `graphics_model`, e.g. "Radeon 8060S").
- amdgpu.ids rows that list multiple marketing names for one device_id/
  revision separated by " / " (e.g. "AMD Instinct MI60 / MI50"), each
  treated as its own alias.

Known, expected residual gaps (not bugs): older Instinct cards absent from
amdgpu.ids entirely (MI6, MI8), capacity-suffixed names amdgpu.ids doesn't
distinguish ("MI50 (32GB)" vs bare "MI50"), and marketing names reused
across genuinely different device_ids ("Radeon 780M" spans Phoenix and
Hawk Point) -- see MatchReport.unmatched / .ambiguous.
"""

from __future__ import annotations

import dataclasses
import re

from .ingest_libdrm_amdgpu_ids import AmdgpuIdRow

_INSTINCT_PREFIX_RE = re.compile(r"^AMD\s+(Radeon\s+)?Instinct\s+", re.IGNORECASE)
_AMD_PREFIX_RE = re.compile(r"^AMD\s+", re.IGNORECASE)
_GRAPHICS_SUFFIX_RE = re.compile(r"\s+Graphics$", re.IGNORECASE)


def normalize_name(name: str) -> str:
    name = name.strip()
    name = _INSTINCT_PREFIX_RE.sub("", name)
    name = _AMD_PREFIX_RE.sub("", name)
    name = _GRAPHICS_SUFFIX_RE.sub("", name)
    return " ".join(name.split()).lower()


def _name_aliases(product_name: str) -> list[str]:
    # e.g. "AMD Instinct MI60 / MI50" names two products for one row.
    return [normalize_name(part) for part in product_name.split(" / ")]


def build_device_id_index(rows: list[AmdgpuIdRow]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for row in rows:
        for alias in _name_aliases(row.product_name):
            index.setdefault(alias, set()).add(row.device_id)
    return index


@dataclasses.dataclass
class MatchReport:
    matched: list[str] = dataclasses.field(default_factory=list)
    ambiguous: list[tuple[str, set[str]]] = dataclasses.field(default_factory=list)
    unmatched: list[str] = dataclasses.field(default_factory=list)


def apply_device_ids(gpu_entries: list[dict], amdgpu_id_rows: list[AmdgpuIdRow]) -> MatchReport:
    """Mutates `gpu_entries` in place, setting `device_id` where exactly one
    candidate is found. Returns a report of what did/didn't resolve."""
    index = build_device_id_index(amdgpu_id_rows)
    report = MatchReport()
    for entry in gpu_entries:
        candidate_name = entry.get("graphics_model") or entry["product_name"]
        device_ids = index.get(normalize_name(candidate_name))
        if not device_ids:
            report.unmatched.append(entry["product_name"])
        elif len(device_ids) > 1:
            report.ambiguous.append((entry["product_name"], device_ids))
        else:
            entry["device_id"] = next(iter(device_ids))
            report.matched.append(entry["product_name"])
    return report
