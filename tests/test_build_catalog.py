import json
from pathlib import Path

import jsonschema

from tools.catalog_build.build_catalog import SourceDoc, build_catalog, load_xdna_fixture

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (Path(__file__).parents[1] / "catalog" / "schema" / "catalog.schema.json").read_text()
)


def _fixture_source(name: str, filename: str) -> SourceDoc:
    return SourceDoc(
        name=name,
        url=f"https://example.invalid/{filename}",
        ref="test-fixture",
        text=(FIXTURES / filename).read_text(),
    )


def _built_catalog() -> dict:
    return build_catalog(
        _fixture_source("rocm-gpu-specs", "gpu-specs.rst"),
        _fixture_source("rocm-precision-support", "precision-support.rst"),
        _fixture_source("libdrm-amdgpu-ids", "amdgpu.ids"),
        _fixture_source("llvm-amdgpu-usage", "AMDGPUUsage.rst"),
        load_xdna_fixture(FIXTURES),
    )


def test_catalog_conforms_to_schema():
    jsonschema.Draft202012Validator(SCHEMA).validate(_built_catalog())


def test_golden_entries_after_precision_join():
    catalog = _built_catalog()
    by_name = {g["product_name"]: g for g in catalog["gpus"]}

    mi300x = by_name["MI300X"]
    assert mi300x["generation"] == "CDNA3"
    assert mi300x["precision_support"]["fp8_e4m3_fnuz"] is True
    assert mi300x["precision_support"]["int64"] is True
    assert mi300x["device_id"] == "74a1"

    strix_halo = by_name["AMD Ryzen AI Max+ PRO 395"]
    assert strix_halo["generation"] == "RDNA3.5"
    # Real gap, not a bug: RDNA3.5 has no column in precision-support.rst.
    assert "precision_support" not in strix_halo
    assert strix_halo["device_id"] == "1586"

    mi100 = by_name["MI100"]
    # gpu-specs.rst sources MI100's generation as "CDNA" (no digit); the
    # sourced field stays as-is, but the precision join aliases it to CDNA1.
    assert mi100["generation"] == "CDNA"
    assert mi100["precision_support"]["int64"] is True


def test_notes_default_to_empty_when_none_given():
    catalog = _built_catalog()
    assert catalog["notes"] == []


def test_notes_are_merged_in_verbatim_when_given():
    strix_halo_note = {
        "device_id": "1586",
        "field": "precision_support",
        "note": "not yet hand-validated on real hardware",
        "validated_on": "2026-09-02",
        "validated_by": "matt.elliott@amd.com",
    }
    catalog = build_catalog(
        _fixture_source("rocm-gpu-specs", "gpu-specs.rst"),
        _fixture_source("rocm-precision-support", "precision-support.rst"),
        _fixture_source("libdrm-amdgpu-ids", "amdgpu.ids"),
        _fixture_source("llvm-amdgpu-usage", "AMDGPUUsage.rst"),
        load_xdna_fixture(FIXTURES),
        notes=[strix_halo_note],
    )
    jsonschema.Draft202012Validator(SCHEMA).validate(catalog)
    assert catalog["notes"] == [strix_halo_note]


def test_npu_entries_populated_from_xdna_driver():
    catalog = _built_catalog()
    by_key = {(n["device_id"], n["revision_id"]): n for n in catalog["npus"]}
    assert len(catalog["npus"]) == 19

    strix_halo_npu = by_key[("17f0", "10")]
    assert strix_halo_npu["hw_gen"] == "NPU4"
    assert strix_halo_npu["family"] == "Strix / Krackan / Strix Halo / Gorgon Point"
    assert strix_halo_npu["vendor_id"] == "1022"

    phoenix_npu = by_key[("1502", "00")]
    assert phoenix_npu["hw_gen"] == "NPU1"
    # Real gap, not a bug: xdna-driver has no marketing-name table for 0x1502.
    assert "family" not in phoenix_npu
