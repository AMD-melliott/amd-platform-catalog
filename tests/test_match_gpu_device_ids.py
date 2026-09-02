from tools.catalog_build.ingest_libdrm_amdgpu_ids import AmdgpuIdRow
from tools.catalog_build.match_gpu_device_ids import apply_device_ids, normalize_name


def test_normalize_strips_amd_instinct_prefix():
    assert normalize_name("AMD Instinct MI300X") == "mi300x"


def test_normalize_strips_amd_radeon_instinct_prefix():
    assert normalize_name("AMD Radeon Instinct MI25") == "mi25"


def test_normalize_strips_graphics_suffix():
    assert normalize_name("AMD Radeon 8060S Graphics") == "radeon 8060s"


def test_exact_match_not_substring_match():
    # "MI300X" must not match the "MI300X HF"/"MI300X VF" variant rows.
    rows = [
        AmdgpuIdRow(device_id="74a1", revision_id="00", product_name="AMD Instinct MI300X"),
        AmdgpuIdRow(device_id="74a9", revision_id="00", product_name="AMD Instinct MI300X HF"),
    ]
    entries = [{"product_name": "MI300X", "specs": {}}]
    report = apply_device_ids(entries, rows)
    assert entries[0]["device_id"] == "74a1"
    assert report.matched == ["MI300X"]


def test_ambiguous_name_across_device_ids_left_unset():
    rows = [
        AmdgpuIdRow(device_id="1900", revision_id="91", product_name="AMD Radeon 780M Graphics"),
        AmdgpuIdRow(device_id="15bf", revision_id="c1", product_name="AMD Radeon 780M Graphics"),
    ]
    entries = [{"product_name": "AMD Ryzen 7 7840U", "graphics_model": "Radeon 780M", "specs": {}}]
    report = apply_device_ids(entries, rows)
    assert "device_id" not in entries[0]
    assert report.ambiguous == [("AMD Ryzen 7 7840U", {"1900", "15bf"})]


def test_unmatched_product_left_unset():
    entries = [{"product_name": "MI8", "specs": {}}]
    report = apply_device_ids(entries, [])
    assert "device_id" not in entries[0]
    assert report.unmatched == ["MI8"]


def test_graphics_model_preferred_over_product_name_for_matching():
    rows = [AmdgpuIdRow(device_id="1586", revision_id="c1", product_name="AMD Radeon 8060S Graphics")]
    entries = [
        {"product_name": "AMD Ryzen AI Max+ PRO 395", "graphics_model": "Radeon 8060S", "specs": {}}
    ]
    apply_device_ids(entries, rows)
    assert entries[0]["device_id"] == "1586"


def test_slash_separated_aliases_split():
    rows = [AmdgpuIdRow(device_id="66a1", revision_id="02", product_name="AMD Instinct MI60 / MI50")]
    entries = [{"product_name": "MI60", "specs": {}}, {"product_name": "MI50", "specs": {}}]
    report = apply_device_ids(entries, rows)
    assert entries[0]["device_id"] == "66a1"
    assert entries[1]["device_id"] == "66a1"
    assert set(report.matched) == {"MI60", "MI50"}
