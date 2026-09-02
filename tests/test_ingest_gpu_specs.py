from pathlib import Path

from tools.catalog_build.ingest_rocm_gpu_specs import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "gpu-specs.rst"


def _entries():
    return ingest(FIXTURE.read_text())


def _by_name(entries, name):
    matches = [e for e in entries if e["product_name"] == name]
    assert len(matches) == 1, f"expected exactly one entry named {name!r}, got {len(matches)}"
    return matches[0]


def test_mi300x():
    entry = _by_name(_entries(), "MI300X")
    assert entry["generation"] == "CDNA3"
    assert entry["gfx_target"] == "gfx942"
    assert entry["memory_model"] == "dedicated"
    assert entry["lifecycle_status"] == "unknown"
    assert entry["specs"]["vram_gib"] == 192
    assert entry["specs"]["compute_units"] == "304 (38 per XCD)"
    assert entry["specs"]["gfxip_major_version"] == 9
    assert "graphics_model" not in entry
    assert "device_id" not in entry  # not derivable from this source


def test_strix_halo():
    entry = _by_name(_entries(), "AMD Ryzen AI Max+ PRO 395")
    assert entry["graphics_model"] == "Radeon 8060S"
    assert entry["generation"] == "RDNA3.5"
    assert entry["gfx_target"] == "gfx1151"
    assert entry["memory_model"] == "unified"
    assert entry["specs"]["vram_gib"] == "Dynamic + carveout"
    assert entry["specs"]["compute_units"] == 40
    assert entry["specs"]["wavefront_size"] == "32 or 64"


def test_all_four_product_lines_present():
    entries = _entries()
    # Instinct(15) + Radeon PRO(9) + Radeon(15) + Ryzen APU(5) rows in today's fixture.
    assert len(entries) == 15 + 9 + 15 + 5
    assert {e["memory_model"] for e in entries} == {"dedicated", "unified"}
