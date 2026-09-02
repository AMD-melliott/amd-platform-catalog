from tools.catalog_build.cross_check_llvm import cross_check
from tools.catalog_build.ingest_llvm_amdgpu_usage import ProcessorEntry

ALIASES = {"CDNA": "CDNA1"}


def test_matching_generation_produces_no_mismatch():
    gpu_entries = [{"product_name": "MI300X", "gfx_target": "gfx942", "generation": "CDNA3"}]
    llvm_entries = [ProcessorEntry(gfx_target="gfx942", family="GCN GFX9", generation="CDNA3")]
    report = cross_check(gpu_entries, llvm_entries, ALIASES)
    assert report.mismatches == []
    assert report.new_targets == []


def test_aliased_generation_produces_no_mismatch():
    gpu_entries = [{"product_name": "MI100", "gfx_target": "gfx908", "generation": "CDNA"}]
    llvm_entries = [ProcessorEntry(gfx_target="gfx908", family="GCN GFX9", generation="CDNA1")]
    report = cross_check(gpu_entries, llvm_entries, ALIASES)
    assert report.mismatches == []


def test_real_disagreement_reported_as_mismatch():
    gpu_entries = [{"product_name": "MI60", "gfx_target": "gfx906", "generation": "GCN5.1"}]
    llvm_entries = [ProcessorEntry(gfx_target="gfx906", family="GCN GFX9", generation="VEGA7NM")]
    report = cross_check(gpu_entries, llvm_entries, ALIASES)
    assert report.mismatches == [("MI60", "gfx906", "GCN5.1", "VEGA7NM")]


def test_llvm_only_target_with_resolvable_generation_is_new():
    gpu_entries = [{"product_name": "MI300X", "gfx_target": "gfx942", "generation": "CDNA3"}]
    llvm_entries = [
        ProcessorEntry(gfx_target="gfx942", family="GCN GFX9", generation="CDNA3"),
        ProcessorEntry(gfx_target="gfx1310", family="GCN GFX13", generation="RDNA5"),
    ]
    report = cross_check(gpu_entries, llvm_entries, ALIASES)
    assert [t.gfx_target for t in report.new_targets] == ["gfx1310"]


def test_llvm_only_target_with_no_generation_is_not_reported_as_new():
    gpu_entries = []
    llvm_entries = [ProcessorEntry(gfx_target="r600", family="Radeon HD 2000/3000 Series", generation=None)]
    report = cross_check(gpu_entries, llvm_entries, ALIASES)
    assert report.new_targets == []
