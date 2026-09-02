from pathlib import Path

from tools.catalog_build.ingest_rocm_precision_support import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "precision-support.rst"


def _result():
    return ingest(FIXTURE.read_text())


def test_fp4_only_on_cdna4():
    result = _result()
    assert result["CDNA4"]["fp4_e2m1"] is True
    for generation in ("CDNA1", "CDNA2", "CDNA3", "RDNA2", "RDNA3", "RDNA4"):
        assert result[generation]["fp4_e2m1"] is False


def test_fp8_fnuz_vs_ocp_variants():
    result = _result()
    # CDNA3 only has the FNUZ fp8 variant; RDNA4 only has the OCP variant.
    assert result["CDNA3"]["fp8_e4m3_fnuz"] is True
    assert result["CDNA3"]["fp8_e4m3"] is False
    assert result["RDNA4"]["fp8_e4m3_fnuz"] is False
    assert result["RDNA4"]["fp8_e4m3"] is True


def test_universally_supported_integer_types():
    result = _result()
    for generation in ("CDNA1", "CDNA2", "CDNA3", "CDNA4", "RDNA2", "RDNA3", "RDNA4"):
        assert result[generation]["int8"] is True
        assert result[generation]["int64"] is True


def test_no_rdna35_column():
    # Real upstream gap: RDNA3.5 (Strix Halo) has no column in this table.
    assert "RDNA3.5" not in _result()
