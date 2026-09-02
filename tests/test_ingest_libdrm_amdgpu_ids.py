from pathlib import Path

import pytest

from tools.catalog_build.ingest_libdrm_amdgpu_ids import AmdgpuIdRow, ingest

FIXTURE = Path(__file__).parent / "fixtures" / "amdgpu.ids"


def _rows():
    return ingest(FIXTURE.read_text())


def test_strix_halo_device_id_has_multiple_revisions():
    rows = [r for r in _rows() if r.device_id == "1586"]
    assert len(rows) >= 4
    assert AmdgpuIdRow(device_id="1586", revision_id="C1", product_name="AMD Radeon 8060S Graphics") in rows


def test_mi300x_device_id():
    rows = [r for r in _rows() if r.product_name == "AMD Instinct MI300X"]
    assert rows == [AmdgpuIdRow(device_id="74a1", revision_id="00", product_name="AMD Instinct MI300X")]


def test_skips_header_comment_and_version_line():
    rows = _rows()
    assert all(r.device_id.isalnum() and len(r.device_id) == 4 for r in rows)
    # 743 real device rows in today's fixture (749 lines minus comments/blank/version).
    assert len(rows) == 743


def test_rejects_malformed_device_id():
    with pytest.raises(ValueError):
        ingest("ZZZZZ,\t00,\tBogus Card\n")
