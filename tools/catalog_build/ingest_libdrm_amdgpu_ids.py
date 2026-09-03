"""Parse libdrm's ``data/amdgpu.ids`` into raw device_id/revision_id/product_name rows.

This is the candidate source (see PRD §6.3 callout, added 2026-09-02) for
closing GpuEntry's `device_id` gap: no source ingested so far maps a GPU's
marketing product name to a PCI device ID. `amdgpu.ids` does, and it is
AMD-maintained (recent history: commits from Alex Deucher, `amdgpu.` driver
maintainer, "from ROCm <release>") and updated per ROCm release.

This module only parses the file -- it does not attempt the product-name
join onto GpuEntry records. That join is nontrivial (one device_id can map
to several revisions carrying *different* marketing names, e.g. `1586`
alone covers "8060S"/"8050S"/"8040S" variants) and lives in
``match_gpu_device_ids.py`` instead, so parsing and matching can be tested
independently.
"""

from __future__ import annotations

import dataclasses
import re

_DEVICE_ID_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


@dataclasses.dataclass(frozen=True)
class AmdgpuIdRow:
    device_id: str
    revision_id: str
    product_name: str


def ingest(text: str) -> list[AmdgpuIdRow]:
    rows: list[AmdgpuIdRow] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "," not in line:
            # Blanks, the leading comment block, and the bare version line
            # (e.g. "1.0.0") have no comma and are skipped.
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            raise ValueError(f"amdgpu.ids line {lineno}: expected 3 comma-separated fields, got {len(parts)}: {line!r}")
        device_id, revision_id, product_name = parts
        if not _DEVICE_ID_RE.match(device_id):
            raise ValueError(f"amdgpu.ids line {lineno}: device_id {device_id!r} is not 4 hex digits")
        rows.append(
            AmdgpuIdRow(device_id=device_id.lower(), revision_id=revision_id.upper(), product_name=product_name)
        )
    return rows
