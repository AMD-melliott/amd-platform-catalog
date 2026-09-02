"""Parse ROCm's ``docs/reference/precision-support.rst`` into a per-generation
data-type support matrix, sourced from the "HIP C++ type implementation
support" table -- the one table framed as native/emulated support per
architecture (see the doc's own "Level of support definitions" section),
rather than the separate compute-unit / matrix-core / packed-math breakdowns
further down the same page, which are a finer-grained follow-on not needed
for the PRD §6.3 flat ``precision_support`` shape.

Real, load-bearing gap: RDNA3.5 is not a column anywhere in this document
(confirmed by inspection) -- so devices in that generation (e.g. Strix Halo)
get no ``precision_support`` data from this source. This module surfaces
that by simply not producing an RDNA3.5 key, rather than guessing from a
neighboring generation.
"""

from __future__ import annotations

from .rst_tables import extract_list_tables

GENERATIONS = ["CDNA1", "CDNA2", "CDNA3", "CDNA4", "RDNA2", "RDNA3", "RDNA4"]

# Row labels in the source table are raw HIP C++ type tokens; map them to the
# friendly type names used elsewhere in the same doc's descriptive tables.
# Deliberately explicit (not a generic slugify) so an unrecognized new row
# is visible rather than silently mis-keyed.
_TYPE_KEY_MAP = {
    "int8_t, uint8_t": "int8",
    "int16_t, uint16_t": "int16",
    "int32_t, uint32_t": "int32",
    "int64_t, uint64_t": "int64",
    "__hip_fp4_e2m1": "fp4_e2m1",
    "__hip_fp6_e2m3": "fp6_e2m3",
    "__hip_fp6_e3m2": "fp6_e3m2",
    "__hip_fp8_e4m3_fnuz": "fp8_e4m3_fnuz",
    "__hip_fp8_e5m2_fnuz": "fp8_e5m2_fnuz",
    "__hip_fp8_e4m3": "fp8_e4m3",
    "__hip_fp8_e5m2": "fp8_e5m2",
    "half": "float16",
    "bfloat16": "bfloat16",
    "float": "float32",
    "double": "float64",
}

_SUPPORT_ICON = {"✅": True, "❌": False}


def _find_native_support_table(rst_text: str):
    expected_header = ["HIP C++ Type", *GENERATIONS]
    for table in extract_list_tables(rst_text):
        if table.header == expected_header:
            return table
    raise ValueError(
        "could not find the HIP C++ type implementation-support matrix table "
        f"(expected header {expected_header!r})"
    )


def ingest(rst_text: str) -> dict[str, dict[str, bool]]:
    table = _find_native_support_table(rst_text)
    result: dict[str, dict[str, bool]] = {gen: {} for gen in GENERATIONS}
    for row in table.rows:
        raw_type, *cells = row
        type_key = _TYPE_KEY_MAP.get(raw_type)
        if type_key is None:
            print(f"warning: unrecognized HIP type row {raw_type!r}; using raw token as key")
            type_key = raw_type
        for generation, cell in zip(GENERATIONS, cells):
            support = _SUPPORT_ICON.get(cell)
            if support is None:
                raise ValueError(f"unexpected support icon {cell!r} for {raw_type!r}/{generation}")
            result[generation][type_key] = support
    return result
