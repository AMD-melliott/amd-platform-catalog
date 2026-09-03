from dataclasses import replace

from amd_platform_catalog import Catalog, MemoryModel, NoteEntry


def test_embedded_catalog_parses_and_has_entries():
    catalog = Catalog.embedded()
    assert catalog.gpus
    assert catalog.npus


def test_mi300x_golden_lookup():
    catalog = Catalog.embedded()
    entry = catalog.gpu_by_device_id("74a1")
    assert entry is not None
    assert entry.product_name == "MI300X"
    assert entry.generation == "CDNA3"
    assert entry.gfx_target == "gfx942"
    assert entry.memory_model == MemoryModel.DEDICATED
    assert entry.precision_support is not None
    assert entry.precision_support.get("fp8_e4m3_fnuz") is True


def test_device_id_lookup_is_case_insensitive():
    catalog = Catalog.embedded()
    assert catalog.gpu_by_device_id("74A1") is not None
    assert catalog.gpu_by_device_id("74a1") is not None


def test_strix_halo_golden_lookup_has_no_precision_support():
    catalog = Catalog.embedded()
    entry = catalog.gpu_by_device_id("1586")
    assert entry is not None
    assert entry.product_name == "AMD Ryzen AI Max+ PRO 395"
    assert entry.generation == "RDNA3.5"
    assert entry.memory_model == MemoryModel.UNIFIED
    # Real, sourced gap (PRD §6.3 callout): RDNA3.5 has no column in
    # precision-support.rst, so this must stay None, not a guess.
    assert entry.precision_support is None


def test_unknown_device_id_returns_none_not_a_guess():
    catalog = Catalog.embedded()
    assert catalog.gpu_by_device_id("ffff") is None


def test_strix_family_npu_has_three_ambiguous_hw_gens():
    catalog = Catalog.embedded()
    rows = catalog.npus_by_device_id("17f0")
    assert len(rows) == 3
    for row in rows:
        assert row.family == "Strix / Krackan / Strix Halo / Gorgon Point"


def test_npu_lookup_by_device_id_and_revision():
    catalog = Catalog.embedded()
    row = catalog.npu_by_device_id_and_revision("17f0", "10")
    assert row is not None
    assert row.hw_gen == "NPU4"


def test_resolve_gpu_applies_specs_override_from_notes():
    # catalog.json's one real note doesn't target specs.<key> -- construct
    # one to verify the override mechanism generically, per the module
    # docstring's documented scope: only "specs.<key>" targets are supported.
    catalog = Catalog.embedded()
    mi300x = catalog.gpu_by_device_id("74a1")
    assert mi300x is not None
    device_id = mi300x.device_id
    assert device_id is not None
    catalog = replace(
        catalog,
        gpus=[mi300x],
        notes=[
            NoteEntry(
                device_id=device_id,
                field="specs.vram_gib",
                override=999,
                note="synthetic test override",
                validated_on="2026-09-03",
            )
        ],
    )

    resolved = catalog.resolve_gpu(device_id)
    assert resolved is not None
    assert resolved.specs.get("vram_gib") == 999

    # Raw lookup (no overlay) must be unaffected.
    raw = catalog.gpu_by_device_id(device_id)
    assert raw is not None
    assert raw.specs.get("vram_gib") != 999


def test_strix_halo_has_unvalidated_precision_support_note():
    catalog = Catalog.embedded()
    notes = catalog.notes_for_device("1586")
    precision_note = next((n for n in notes if n.field == "precision_support"), None)
    assert precision_note is not None, "Strix Halo should carry a note about unvalidated precision_support"
    assert "hand-validated" in precision_note.note
    assert precision_note.override is None

    # An annotation-only note (no override) must not affect resolve_gpu.
    resolved = catalog.resolve_gpu("1586")
    assert resolved is not None
    assert resolved.precision_support is None


def test_notes_for_device_surfaces_explicitly_even_when_no_override():
    catalog = Catalog.embedded()
    catalog = replace(
        catalog,
        notes=[
            NoteEntry(
                device_id="74a1",
                field="memory_pool",
                override=None,
                note="annotation only, no override",
                validated_on="2026-09-03",
                validated_by="test",
            )
        ],
    )
    notes = catalog.notes_for_device("74a1")
    assert len(notes) == 1
    assert notes[0].note == "annotation only, no override"
