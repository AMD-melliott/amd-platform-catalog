"""Parse `amd/xdna-driver`'s own PCI ID table into NpuEntry-shaped records.

Goes straight to the upstream driver source (`drivers/accel/amdxdna/
amdxdna_pci_drv.c`'s `amdxdna_ids[]` table, cross-referenced against each
referenced `amdxdna_dev_info`'s `rev_vbnv_tbl` in the per-generation
`npuN_regs.c` files) rather than the Gentoo wiki mirror PRD originally
proposed -- this closes PRD §10's "confirm against amd/xdna-driver" backlog
item immediately instead of waiting for Phase 4.

**Real finding (2026-09-02, see PRD §6.4 callout):** device_id `0x17f0`
binds to *three* distinct `(device_id, revision_id)` driver-generation
entries (NPU4/rev `0x10`, NPU5/rev `0x11`, NPU6/rev `0x20`), and all three
share the exact same marketing-name table (`npu4_rev_vbnv_tbl`: Strix,
Krackan, Strix Halo, Gorgon Point) -- the driver only disambiguates the
*actual* family via a live "get device revision" firmware message reading a
silicon fuse (`aie2_message.c`), not from the static PCI revision byte
this catalog can read. So `family` here is honestly the *whole set* of
names the driver associates with a `(device_id, revision_id)` pair, never
a guessed single value, and is left unset entirely where the driver
provides no marketing-name table at all (`0x1502`, and the NPU3/9/10/11
classic/PF/VF variants under `0x17f1`/`0x17f2`/`0x17f3`/`0x1b0a`/`0x1b0b`/
`0x1b0c`) -- notably including a case where this means PRD's own original
"Phoenix/Hawk Point" claim for `0x1502` is NOT corroborated by this source.
"""

from __future__ import annotations

import dataclasses
import re

VENDOR_ID = "1022"

_IDS_ARRAY_RE = re.compile(r"amdxdna_ids\[\]\s*=\s*\{(.*?)\n\};", re.DOTALL)
_IDS_ROW_RE = re.compile(r"\{\s*0x([0-9a-fA-F]+)\s*,\s*0x([0-9a-fA-F]+)\s*,\s*&(\w+)\s*\}")

_DEV_INFO_RE = re.compile(r"const struct amdxdna_dev_info (\w+)\s*=\s*\{(.*?)\n\};", re.DOTALL)
_REV_VBNV_FIELD_RE = re.compile(r"\.rev_vbnv_tbl\s*=\s*(\w+)")

_VBNV_TABLE_RE = re.compile(r"const struct amdxdna_rev_vbnv (\w+)\[\]\s*=\s*\{(.*?)\n\};", re.DOTALL)
_VBNV_ROW_RE = re.compile(r'\{\s*AIE2_DEV_REVISION_\w+\s*,\s*"([^"]+)"\s*\}')

_HW_GEN_RE = re.compile(r"dev_(npu\d+)", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class NpuIdRow:
    device_id: str
    revision_id: str
    vendor_id: str
    hw_gen: str
    family: str | None


def _normalize_family_name(raw: str) -> str:
    # "NPU Strix" -> "Strix"; "NPU Krackan 1" -> "Krackan" (the trailing
    # digit/letter is a sub-revision within the family, not a distinct one).
    name = re.sub(r"^NPU\s+", "", raw.strip())
    name = re.sub(r"\s+[0-9A-Za-z]$", "", name)
    return name


def _parse_vbnv_tables(regs_c_texts: list[str]) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for text in regs_c_texts:
        for table_name, body in _VBNV_TABLE_RE.findall(text):
            names: list[str] = []
            for raw_name in _VBNV_ROW_RE.findall(body):
                normalized = _normalize_family_name(raw_name)
                if normalized not in names:
                    names.append(normalized)
            tables[table_name] = names
    return tables


def _parse_dev_info_vbnv_refs(regs_c_texts: list[str]) -> dict[str, str]:
    """dev_info symbol -> rev_vbnv_tbl symbol it references, when present."""
    refs: dict[str, str] = {}
    for text in regs_c_texts:
        for info_name, body in _DEV_INFO_RE.findall(text):
            match = _REV_VBNV_FIELD_RE.search(body)
            if match:
                refs[info_name] = match.group(1)
    return refs


def ingest(pci_drv_c_text: str, regs_c_texts: list[str]) -> list[NpuIdRow]:
    ids_match = _IDS_ARRAY_RE.search(pci_drv_c_text)
    if not ids_match:
        raise ValueError("could not find amdxdna_ids[] table in amdxdna_pci_drv.c")

    vbnv_tables = _parse_vbnv_tables(regs_c_texts)
    vbnv_ref_by_dev_info = _parse_dev_info_vbnv_refs(regs_c_texts)

    rows: list[NpuIdRow] = []
    for device_id, revision_id, info_symbol in _IDS_ROW_RE.findall(ids_match.group(1)):
        hw_gen_match = _HW_GEN_RE.search(info_symbol)
        if not hw_gen_match:
            raise ValueError(f"could not derive hw_gen from dev_info symbol {info_symbol!r}")
        hw_gen = hw_gen_match.group(1).upper()

        family = None
        vbnv_symbol = vbnv_ref_by_dev_info.get(info_symbol)
        if vbnv_symbol:
            names = vbnv_tables.get(vbnv_symbol)
            if names:
                family = " / ".join(names)

        rows.append(
            NpuIdRow(
                device_id=device_id.lower(),
                revision_id=f"{int(revision_id, 16):02x}",
                vendor_id=VENDOR_ID,
                hw_gen=hw_gen,
                family=family,
            )
        )
    return rows
