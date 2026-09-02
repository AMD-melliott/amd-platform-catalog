from pathlib import Path

from tools.catalog_build.ingest_xdna_pciids import ingest

FIXTURES = Path(__file__).parent / "fixtures" / "xdna_driver"
REGS_FILES = ["npu1_regs.c", "npu3_regs.c", "npu4_regs.c", "npu5_regs.c", "npu6_regs.c"]


def _rows():
    pci_drv_text = (FIXTURES / "amdxdna_pci_drv.c").read_text()
    regs_texts = [(FIXTURES / f).read_text() for f in REGS_FILES]
    return ingest(pci_drv_text, regs_texts)


def test_total_row_count():
    # 19 (device_id, revision_id) rows in today's fixture.
    assert len(_rows()) == 19


def test_phoenix_hawk_point_has_no_family_from_this_source():
    rows = [r for r in _rows() if r.device_id == "1502"]
    assert len(rows) == 1
    assert rows[0].hw_gen == "NPU1"
    assert rows[0].revision_id == "00"
    assert rows[0].family is None


def test_strix_family_device_id_has_three_ambiguous_hw_gens():
    rows = {r.revision_id: r for r in _rows() if r.device_id == "17f0"}
    assert set(rows) == {"10", "11", "20"}
    for row in rows.values():
        assert row.family == "Strix / Krackan / Strix Halo / Gorgon Point"
    assert rows["10"].hw_gen == "NPU4"
    assert rows["11"].hw_gen == "NPU5"
    assert rows["20"].hw_gen == "NPU6"


def test_npu3_variants_have_distinct_device_ids_same_hw_gen_no_family():
    rows = {r.device_id: r for r in _rows() if r.hw_gen == "NPU3" and r.revision_id == "10"}
    assert set(rows) == {"17f1", "17f2", "17f3"}
    assert all(r.family is None for r in rows.values())


def test_vendor_id_is_amd():
    assert all(r.vendor_id == "1022" for r in _rows())
