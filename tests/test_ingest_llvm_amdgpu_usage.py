from pathlib import Path

from tools.catalog_build.ingest_llvm_amdgpu_usage import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "AMDGPUUsage.rst"


def _by_target():
    return {e.gfx_target: e for e in ingest(FIXTURE.read_text())}


def test_mi300x_and_strix_halo_generations_match_rocm():
    by_target = _by_target()
    assert by_target["gfx942"].generation == "CDNA3"
    assert by_target["gfx1151"].generation == "RDNA3.5"


def test_gfx9_family_disambiguated_per_target_despite_shared_header():
    # All of these share one "GCN GFX9 (Vega)" family header row; only the
    # per-target citations (AMD-GCN-GFX908-CDNA1 etc.) disambiguate them.
    by_target = _by_target()
    assert by_target["gfx900"].generation == "VEGA"
    assert by_target["gfx906"].generation == "VEGA7NM"
    assert by_target["gfx908"].generation == "CDNA1"
    assert by_target["gfx90a"].generation == "CDNA2"
    assert by_target["gfx942"].generation == "CDNA3"


def test_blanket_family_citation_covers_every_member():
    by_target = _by_target()
    for target in ("gfx1100", "gfx1101", "gfx1102"):
        assert by_target[target].generation == "RDNA3"


def test_brand_new_family_without_citation_falls_back_to_parenthetical():
    # GFX13/"RDNA 5" has no citation token yet in today's fixture -- this is
    # exactly the "catch brand-new targets" case this source exists for.
    by_target = _by_target()
    assert by_target["gfx1310"].generation == "RDNA5"


def test_pre_rdna_cdna_targets_have_no_generation():
    by_target = _by_target()
    assert by_target["r600"].generation is None
