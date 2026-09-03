package catalog

import (
	"strings"
	"testing"
)

func strPtr(s string) *string { return &s }

func TestEmbeddedCatalogParsesAndHasEntries(t *testing.T) {
	c := Embedded()
	if len(c.GPUs) == 0 {
		t.Fatal("expected GPUs to be populated")
	}
	if len(c.NPUs) == 0 {
		t.Fatal("expected NPUs to be populated")
	}
}

func TestMI300XGoldenLookup(t *testing.T) {
	c := Embedded()
	entry := c.GPUByDeviceID("74a1")
	if entry == nil {
		t.Fatal("MI300X should resolve by device_id")
	}
	if entry.ProductName != "MI300X" {
		t.Errorf("ProductName = %q, want MI300X", entry.ProductName)
	}
	if entry.Generation != "CDNA3" {
		t.Errorf("Generation = %q, want CDNA3", entry.Generation)
	}
	if entry.GfxTarget != "gfx942" {
		t.Errorf("GfxTarget = %q, want gfx942", entry.GfxTarget)
	}
	if entry.MemoryModel != MemoryModelDedicated {
		t.Errorf("MemoryModel = %q, want dedicated", entry.MemoryModel)
	}
	if entry.PrecisionSupport["fp8_e4m3_fnuz"] != true {
		t.Error("expected precision_support[fp8_e4m3_fnuz] to be true")
	}
}

func TestDeviceIDLookupIsCaseInsensitive(t *testing.T) {
	c := Embedded()
	if c.GPUByDeviceID("74A1") == nil {
		t.Error("uppercase lookup should resolve")
	}
	if c.GPUByDeviceID("74a1") == nil {
		t.Error("lowercase lookup should resolve")
	}
}

func TestStrixHaloGoldenLookupHasNoPrecisionSupport(t *testing.T) {
	c := Embedded()
	entry := c.GPUByDeviceID("1586")
	if entry == nil {
		t.Fatal("Strix Halo should resolve by device_id")
	}
	if entry.ProductName != "AMD Ryzen AI Max+ PRO 395" {
		t.Errorf("ProductName = %q", entry.ProductName)
	}
	if entry.Generation != "RDNA3.5" {
		t.Errorf("Generation = %q, want RDNA3.5", entry.Generation)
	}
	if entry.MemoryModel != MemoryModelUnified {
		t.Errorf("MemoryModel = %q, want unified", entry.MemoryModel)
	}
	// Real, sourced gap (PRD §6.3 callout): RDNA3.5 has no column in
	// precision-support.rst, so this must stay nil, not a guess.
	if entry.PrecisionSupport != nil {
		t.Error("expected PrecisionSupport to be nil")
	}
}

func TestUnknownDeviceIDReturnsNilNotAGuess(t *testing.T) {
	c := Embedded()
	if c.GPUByDeviceID("ffff") != nil {
		t.Error("expected nil for unknown device_id")
	}
}

func TestStrixFamilyNPUHasThreeAmbiguousHwGens(t *testing.T) {
	c := Embedded()
	rows := c.NPUsByDeviceID("17f0")
	if len(rows) != 3 {
		t.Fatalf("len(rows) = %d, want 3", len(rows))
	}
	for _, row := range rows {
		if row.Family == nil || *row.Family != "Strix / Krackan / Strix Halo / Gorgon Point" {
			t.Errorf("Family = %v, want Strix / Krackan / Strix Halo / Gorgon Point", row.Family)
		}
	}
}

func TestNPULookupByDeviceIDAndRevision(t *testing.T) {
	c := Embedded()
	row := c.NPUByDeviceIDAndRevision("17f0", "10")
	if row == nil {
		t.Fatal("NPU4 binding should resolve")
	}
	if row.HwGen != "NPU4" {
		t.Errorf("HwGen = %q, want NPU4", row.HwGen)
	}
}

func TestResolveGPUAppliesSpecsOverrideFromNotes(t *testing.T) {
	// catalog.json's one real note doesn't target specs.<key> -- construct
	// one to verify the override mechanism generically, per the package
	// doc comment's documented scope: only "specs.<key>" targets are
	// supported.
	embedded := Embedded()
	mi300x := embedded.GPUByDeviceID("74a1")
	if mi300x == nil {
		t.Fatal("MI300X should resolve by device_id")
	}
	deviceID := *mi300x.DeviceID

	c := &Catalog{
		GPUs: []GPUEntry{*mi300x},
		Notes: []NoteEntry{
			{
				DeviceID:    deviceID,
				Field:       "specs.vram_gib",
				Override:    999,
				Note:        "synthetic test override",
				ValidatedOn: "2026-09-03",
			},
		},
	}

	resolved := c.ResolveGPU(deviceID)
	if resolved == nil {
		t.Fatal("expected resolved GPU entry")
	}
	if v := resolved.Specs["vram_gib"]; v != 999 {
		t.Errorf("Specs[vram_gib] = %v, want 999", v)
	}

	// Raw lookup (no overlay) must be unaffected.
	raw := c.GPUByDeviceID(deviceID)
	if v := raw.Specs["vram_gib"]; v == 999 {
		t.Error("raw lookup should not reflect the override")
	}
}

func TestStrixHaloHasUnvalidatedPrecisionSupportNote(t *testing.T) {
	c := Embedded()
	notes := c.NotesForDevice("1586")
	var precisionNote *NoteEntry
	for _, n := range notes {
		if n.Field == "precision_support" {
			precisionNote = n
			break
		}
	}
	if precisionNote == nil {
		t.Fatal("Strix Halo should carry a note about unvalidated precision_support")
	}
	if !strings.Contains(precisionNote.Note, "hand-validated") {
		t.Errorf("note text = %q, want it to mention hand-validated", precisionNote.Note)
	}
	if precisionNote.Override != nil {
		t.Error("expected annotation-only note to have no override")
	}

	// An annotation-only note (no override) must not affect ResolveGPU.
	resolved := c.ResolveGPU("1586")
	if resolved == nil {
		t.Fatal("expected resolved GPU entry")
	}
	if resolved.PrecisionSupport != nil {
		t.Error("expected PrecisionSupport to remain nil")
	}
}

func TestNotesForDeviceSurfacesExplicitlyEvenWhenNoOverride(t *testing.T) {
	c := &Catalog{
		Notes: []NoteEntry{
			{
				DeviceID:    "74a1",
				Field:       "memory_pool",
				Note:        "annotation only, no override",
				ValidatedOn: "2026-09-03",
				ValidatedBy: strPtr("test"),
			},
		},
	}
	notes := c.NotesForDevice("74a1")
	if len(notes) != 1 {
		t.Fatalf("len(notes) = %d, want 1", len(notes))
	}
	if notes[0].Note != "annotation only, no override" {
		t.Errorf("Note = %q", notes[0].Note)
	}
}
