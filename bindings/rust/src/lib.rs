//! Thin Rust binding over the AMD Platform Catalog (PRD §7.3).
//!
//! Aggregation happens offline; this crate just embeds the pinned
//! `catalog.json` (via `include_str!`, no FFI/subprocess/shared runtime),
//! parses it once, and exposes typed lookups. When a device isn't in the
//! catalog, lookups return `None` -- callers should say so plainly and
//! never guess a generation/capability by analogy (PRD §7.4's "never
//! synthesize, never guess" failure mode applies here too, not just to the
//! agent skill).
//!
//! **Notes overlay scope (documented limitation):** `resolve_gpu` applies a
//! `NoteEntry.override` onto the returned entry only when its `field` is
//! `"specs.<key>"` (an open map, safe to overwrite by key). `catalog.json`
//! has zero notes as of this writing, so there's no real example yet of an
//! override targeting a fixed top-level field (`generation`, `memory_model`,
//! etc.) to design and test that support against -- extend
//! `apply_gpu_overrides` when one exists rather than speculatively covering
//! every field now. `notes_for_device` always returns the raw, unfiltered
//! list regardless, so nothing is ever silently hidden (PRD §7.4 verb 4).

use std::collections::HashMap;
use std::sync::OnceLock;

use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Clone, Deserialize)]
pub struct Catalog {
    pub catalog_version: String,
    pub generated_at: String,
    pub sources: Vec<Source>,
    pub gpus: Vec<GpuEntry>,
    pub npus: Vec<NpuEntry>,
    pub notes: Vec<NoteEntry>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Source {
    pub name: String,
    pub url: String,
    #[serde(rename = "ref")]
    pub git_ref: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryModel {
    Dedicated,
    Unified,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleStatus {
    Active,
    Eos,
    Unknown,
}

#[derive(Debug, Clone, Deserialize)]
pub struct GpuEntry {
    pub device_id: Option<String>,
    pub revision_id: Option<String>,
    pub gfx_target: String,
    pub generation: String,
    pub product_name: String,
    pub graphics_model: Option<String>,
    pub memory_model: MemoryModel,
    #[serde(default)]
    pub specs: HashMap<String, Value>,
    pub precision_support: Option<HashMap<String, bool>>,
    pub lifecycle_status: LifecycleStatus,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NpuEntry {
    pub device_id: String,
    pub revision_id: Option<String>,
    pub vendor_id: String,
    pub family: Option<String>,
    pub hw_gen: String,
    pub llvm_target: Option<String>,
    pub associated_gpu_device_ids: Option<Vec<String>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct NoteEntry {
    pub device_id: String,
    pub field: String,
    #[serde(rename = "override", default)]
    pub override_value: Option<Value>,
    pub note: String,
    pub validated_on: String,
    pub validated_by: Option<String>,
}

fn normalize_hex(id: &str) -> String {
    id.trim().to_ascii_lowercase()
}

/// Applies any `specs.<key>` overrides found in `notes` onto `entry.specs`.
/// See the module-level doc comment for why this is the only supported
/// override target today.
fn apply_gpu_overrides(mut entry: GpuEntry, notes: &[&NoteEntry]) -> GpuEntry {
    for note in notes {
        let Some(value) = &note.override_value else { continue };
        if let Some(key) = note.field.strip_prefix("specs.") {
            entry.specs.insert(key.to_string(), value.clone());
        }
    }
    entry
}

static EMBEDDED_CATALOG_JSON: &str = include_str!("../../../catalog/catalog.json");
static EMBEDDED_CATALOG: OnceLock<Catalog> = OnceLock::new();

impl Catalog {
    /// The catalog embedded in this build of the crate, parsed once.
    ///
    /// # Panics
    /// Panics if the embedded `catalog.json` doesn't parse -- this would
    /// indicate a broken release of this crate, not a runtime/input error.
    pub fn embedded() -> &'static Catalog {
        EMBEDDED_CATALOG.get_or_init(|| {
            serde_json::from_str(EMBEDDED_CATALOG_JSON)
                .expect("embedded catalog.json failed to parse; this is a crate packaging bug")
        })
    }

    /// Parses a catalog from arbitrary JSON text (e.g. a newer release
    /// fetched at runtime rather than the version embedded at compile time).
    pub fn from_json(text: &str) -> serde_json::Result<Catalog> {
        serde_json::from_str(text)
    }

    /// Raw lookup by PCI device ID, no notes overlay applied. Case-insensitive.
    pub fn gpu_by_device_id(&self, device_id: &str) -> Option<&GpuEntry> {
        let device_id = normalize_hex(device_id);
        self.gpus
            .iter()
            .find(|g| g.device_id.as_deref().map(normalize_hex).as_deref() == Some(device_id.as_str()))
    }

    /// Looks up a GPU by device ID and applies its notes overlay (PRD §7.3).
    /// Returns an owned, resolved copy since overrides may modify `specs`.
    pub fn resolve_gpu(&self, device_id: &str) -> Option<GpuEntry> {
        let entry = self.gpu_by_device_id(device_id)?.clone();
        let notes = self.notes_for_device(device_id);
        Some(apply_gpu_overrides(entry, &notes))
    }

    pub fn gpus_by_gfx_target(&self, gfx_target: &str) -> Vec<&GpuEntry> {
        self.gpus.iter().filter(|g| g.gfx_target == gfx_target).collect()
    }

    pub fn gpus_by_generation(&self, generation: &str) -> Vec<&GpuEntry> {
        self.gpus.iter().filter(|g| g.generation == generation).collect()
    }

    /// All NPU rows for a device ID (may be several -- see PRD §6.4: one
    /// device_id can bind to multiple (device_id, revision_id) hardware
    /// generations).
    pub fn npus_by_device_id(&self, device_id: &str) -> Vec<&NpuEntry> {
        let device_id = normalize_hex(device_id);
        self.npus.iter().filter(|n| normalize_hex(&n.device_id) == device_id).collect()
    }

    pub fn npu_by_device_id_and_revision(&self, device_id: &str, revision_id: &str) -> Option<&NpuEntry> {
        let device_id = normalize_hex(device_id);
        let revision_id = normalize_hex(revision_id);
        self.npus.iter().find(|n| {
            normalize_hex(&n.device_id) == device_id
                && n.revision_id.as_deref().map(normalize_hex).as_deref() == Some(revision_id.as_str())
        })
    }

    /// Every note applicable to a device ID, unfiltered -- PRD §7.4 verb 4:
    /// notes must be surfaced explicitly, never silently folded into "the
    /// data" (see also `resolve_gpu`, which applies a subset of these).
    pub fn notes_for_device(&self, device_id: &str) -> Vec<&NoteEntry> {
        let device_id = normalize_hex(device_id);
        self.notes.iter().filter(|n| normalize_hex(&n.device_id) == device_id).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_catalog_parses_and_has_entries() {
        let catalog = Catalog::embedded();
        assert!(!catalog.gpus.is_empty());
        assert!(!catalog.npus.is_empty());
    }

    #[test]
    fn mi300x_golden_lookup() {
        let catalog = Catalog::embedded();
        let entry = catalog.gpu_by_device_id("74a1").expect("MI300X should resolve by device_id");
        assert_eq!(entry.product_name, "MI300X");
        assert_eq!(entry.generation, "CDNA3");
        assert_eq!(entry.gfx_target, "gfx942");
        assert_eq!(entry.memory_model, MemoryModel::Dedicated);
        assert_eq!(
            entry.precision_support.as_ref().and_then(|p| p.get("fp8_e4m3_fnuz")),
            Some(&true)
        );
    }

    #[test]
    fn device_id_lookup_is_case_insensitive() {
        let catalog = Catalog::embedded();
        assert!(catalog.gpu_by_device_id("74A1").is_some());
        assert!(catalog.gpu_by_device_id("74a1").is_some());
    }

    #[test]
    fn strix_halo_golden_lookup_has_no_precision_support() {
        let catalog = Catalog::embedded();
        let entry = catalog.gpu_by_device_id("1586").expect("Strix Halo should resolve by device_id");
        assert_eq!(entry.product_name, "AMD Ryzen AI Max+ PRO 395");
        assert_eq!(entry.generation, "RDNA3.5");
        assert_eq!(entry.memory_model, MemoryModel::Unified);
        // Real, sourced gap (PRD §6.3 callout): RDNA3.5 has no column in
        // precision-support.rst, so this must stay None, not a guess.
        assert!(entry.precision_support.is_none());
    }

    #[test]
    fn unknown_device_id_returns_none_not_a_guess() {
        let catalog = Catalog::embedded();
        assert!(catalog.gpu_by_device_id("ffff").is_none());
    }

    #[test]
    fn strix_family_npu_has_three_ambiguous_hw_gens() {
        let catalog = Catalog::embedded();
        let rows = catalog.npus_by_device_id("17f0");
        assert_eq!(rows.len(), 3);
        for row in &rows {
            assert_eq!(row.family.as_deref(), Some("Strix / Krackan / Strix Halo / Gorgon Point"));
        }
    }

    #[test]
    fn npu_lookup_by_device_id_and_revision() {
        let catalog = Catalog::embedded();
        let row = catalog
            .npu_by_device_id_and_revision("17f0", "10")
            .expect("NPU4 binding should resolve");
        assert_eq!(row.hw_gen, "NPU4");
    }

    #[test]
    fn resolve_gpu_applies_specs_override_from_notes() {
        // catalog.json has zero real notes today (PRD §6.5's notes overlay
        // is a later phase) -- construct one to verify the override
        // mechanism generically, per the module doc comment's documented
        // scope: only "specs.<key>" targets are supported.
        let mut catalog = Catalog::embedded().clone();
        let mi300x = catalog.gpu_by_device_id("74a1").unwrap().clone();
        let device_id = mi300x.device_id.clone().unwrap();
        catalog.gpus = vec![mi300x];
        catalog.notes = vec![NoteEntry {
            device_id: device_id.clone(),
            field: "specs.vram_gib".to_string(),
            override_value: Some(Value::from(999)),
            note: "synthetic test override".to_string(),
            validated_on: "2026-09-02".to_string(),
            validated_by: None,
        }];

        let resolved = catalog.resolve_gpu(&device_id).unwrap();
        assert_eq!(resolved.specs.get("vram_gib"), Some(&Value::from(999)));

        // Raw lookup (no overlay) must be unaffected.
        let raw = catalog.gpu_by_device_id(&device_id).unwrap();
        assert_ne!(raw.specs.get("vram_gib"), Some(&Value::from(999)));
    }

    #[test]
    fn notes_for_device_surfaces_explicitly_even_when_no_override() {
        let mut catalog = Catalog::embedded().clone();
        catalog.notes = vec![NoteEntry {
            device_id: "74a1".to_string(),
            field: "memory_pool".to_string(),
            override_value: None,
            note: "annotation only, no override".to_string(),
            validated_on: "2026-09-02".to_string(),
            validated_by: Some("test".to_string()),
        }];
        let notes = catalog.notes_for_device("74a1");
        assert_eq!(notes.len(), 1);
        assert_eq!(notes[0].note, "annotation only, no override");
    }
}
