"""Parse ROCm's ``docs/reference/gpu-specs.rst`` into GpuEntry-shaped dicts.

Per PRD §6.3, only ``product_name``, ``generation``, ``gfx_target``, and
``graphics_model`` (Ryzen APU tab only) are promoted to top-level fields;
every other column stays verbatim in ``specs``, keyed by a slugified column
header, since the source tables' own columns vary by product family.

Two PRD-required GpuEntry fields this source cannot supply:
- ``device_id`` -- gpu-specs.rst has no PCI device-ID column at all. No
  source evaluated in PRD §5 maps product name -> PCI device ID for GPUs
  (only NPUs have a PCI-ID source). Left unset here; needs its own source
  or manual mapping before the schema can require it in practice.
- ``lifecycle_status`` -- defaults to ``"unknown"`` per PRD §6.3.
"""

from __future__ import annotations

import re

from .rst_tables import extract_list_tables

_TOP_LEVEL_FIELDS = {
    "Name": "product_name",
    "Architecture": "generation",
    "LLVM target name": "gfx_target",
    "Graphics model": "graphics_model",
}

_KNOWN_TABS = {
    "AMD Instinct GPUs",
    "AMD Radeon PRO GPUs",
    "AMD Radeon GPUs",
    "AMD Ryzen APUs",
}

_UNIFIED_MEMORY_TABS = {"AMD Ryzen APUs"}


def _slugify(header: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", header.strip()).strip("_").lower()


def _coerce_spec_value(value: str) -> int | float | str:
    # Cells like "304 (38 per XCD)", "Dynamic + carveout", "32 or 64", and
    # "N/A" must stay strings -- only coerce cleanly-numeric cells, per the
    # PRD's explicit call-out that `specs` stays loose rather than typed.
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _row_to_entry(tab_item_title: str, header: list[str], row: list[str]) -> dict:
    entry: dict = {"specs": {}}
    for column, cell in zip(header, row):
        field = _TOP_LEVEL_FIELDS.get(column)
        if field is not None:
            entry[field] = cell
        else:
            entry["specs"][_slugify(column)] = _coerce_spec_value(cell)
    entry["memory_model"] = "unified" if tab_item_title in _UNIFIED_MEMORY_TABS else "dedicated"
    entry["lifecycle_status"] = "unknown"
    return entry


def ingest(rst_text: str) -> list[dict]:
    entries: list[dict] = []
    for table in extract_list_tables(rst_text):
        if table.tab_item_title not in _KNOWN_TABS:
            continue
        for row in table.rows:
            entries.append(_row_to_entry(table.tab_item_title, table.header, row))
    return entries
