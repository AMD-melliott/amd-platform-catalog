// Package catalog is a thin Go binding over the AMD Platform Catalog (PRD
// §7.3), mirroring bindings/rust 1:1.
//
// Aggregation happens offline; this package just embeds the pinned
// catalog.json (via go:embed, no subprocess/live fetch), parses it once,
// and exposes typed lookups. When a device isn't in the catalog, lookups
// return nil -- callers should say so plainly and never guess a
// generation/capability by analogy (PRD §7.4's "never synthesize, never
// guess" failure mode applies here too, not just to the agent skill).
//
// Notes overlay scope (documented limitation, same as the Rust binding):
// ResolveGPU applies a NoteEntry.Override onto the returned entry only when
// its Field is "specs.<key>" (an open map, safe to overwrite by key).
// Extend applyGPUOverrides when a real example of a top-level-field
// override exists to design against.
package catalog

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
)

type MemoryModel string

const (
	MemoryModelDedicated MemoryModel = "dedicated"
	MemoryModelUnified   MemoryModel = "unified"
)

type LifecycleStatus string

const (
	LifecycleStatusActive  LifecycleStatus = "active"
	LifecycleStatusEOS     LifecycleStatus = "eos"
	LifecycleStatusUnknown LifecycleStatus = "unknown"
)

type Source struct {
	Name string `json:"name"`
	URL  string `json:"url"`
	Ref  string `json:"ref"`
}

type GPUEntry struct {
	DeviceID         *string         `json:"device_id,omitempty"`
	RevisionID       *string         `json:"revision_id,omitempty"`
	GfxTarget        string          `json:"gfx_target"`
	Generation       string          `json:"generation"`
	ProductName      string          `json:"product_name"`
	GraphicsModel    *string         `json:"graphics_model,omitempty"`
	MemoryModel      MemoryModel     `json:"memory_model"`
	Specs            map[string]any  `json:"specs,omitempty"`
	PrecisionSupport map[string]bool `json:"precision_support,omitempty"`
	LifecycleStatus  LifecycleStatus `json:"lifecycle_status"`
}

type NPUEntry struct {
	DeviceID               string   `json:"device_id"`
	RevisionID             *string  `json:"revision_id,omitempty"`
	VendorID               string   `json:"vendor_id"`
	Family                 *string  `json:"family,omitempty"`
	HwGen                  string   `json:"hw_gen"`
	LLVMTarget             *string  `json:"llvm_target,omitempty"`
	AssociatedGPUDeviceIDs []string `json:"associated_gpu_device_ids,omitempty"`
}

type NoteEntry struct {
	DeviceID    string  `json:"device_id"`
	Field       string  `json:"field"`
	Override    any     `json:"override,omitempty"`
	Note        string  `json:"note"`
	ValidatedOn string  `json:"validated_on"`
	ValidatedBy *string `json:"validated_by,omitempty"`
}

type Catalog struct {
	CatalogVersion string      `json:"catalog_version"`
	GeneratedAt    string      `json:"generated_at"`
	Sources        []Source    `json:"sources"`
	GPUs           []GPUEntry  `json:"gpus"`
	NPUs           []NPUEntry  `json:"npus"`
	Notes          []NoteEntry `json:"notes"`
}

func normalizeHex(id string) string {
	return strings.ToLower(strings.TrimSpace(id))
}

// applyGPUOverrides applies any "specs.<key>" overrides found in notes onto
// entry.Specs. See the package doc comment for why this is the only
// supported override target today.
func applyGPUOverrides(entry *GPUEntry, notes []*NoteEntry) {
	for _, note := range notes {
		if note.Override == nil {
			continue
		}
		if key, ok := strings.CutPrefix(note.Field, "specs."); ok {
			if entry.Specs == nil {
				entry.Specs = map[string]any{}
			}
			entry.Specs[key] = note.Override
		}
	}
}

// catalog.json is a committed copy of ../../catalog/catalog.json, not a
// symlink: go:embed refuses to embed symlinks outright (even ones that
// resolve within the module), so a real copy is the only option here. Run
// `go generate ./...` after regenerating the canonical catalog.json to
// resync this copy.
//
//go:generate cp ../../catalog/catalog.json catalog.json
//go:embed catalog.json
var embeddedCatalogJSON []byte

var (
	embeddedCatalog     *Catalog
	embeddedCatalogOnce sync.Once
)

// Embedded returns the catalog embedded in this build of the package,
// parsed once.
//
// Panics if the embedded catalog.json doesn't parse -- this would indicate
// a broken release of this package, not a runtime/input error.
func Embedded() *Catalog {
	embeddedCatalogOnce.Do(func() {
		c, err := FromJSON(embeddedCatalogJSON)
		if err != nil {
			panic(fmt.Sprintf("embedded catalog.json failed to parse; this is a package bug: %v", err))
		}
		embeddedCatalog = c
	})
	return embeddedCatalog
}

// FromJSON parses a catalog from arbitrary JSON bytes (e.g. a newer release
// fetched at runtime rather than the version embedded at build time).
func FromJSON(data []byte) (*Catalog, error) {
	var c Catalog
	if err := json.Unmarshal(data, &c); err != nil {
		return nil, err
	}
	return &c, nil
}

// GPUByDeviceID is a raw lookup by PCI device ID, no notes overlay applied.
// Case-insensitive.
func (c *Catalog) GPUByDeviceID(deviceID string) *GPUEntry {
	needle := normalizeHex(deviceID)
	for i := range c.GPUs {
		g := &c.GPUs[i]
		if g.DeviceID != nil && normalizeHex(*g.DeviceID) == needle {
			return g
		}
	}
	return nil
}

// ResolveGPU looks up a GPU by device ID and applies its notes overlay (PRD
// §7.3). Returns a copy since overrides may modify Specs.
func (c *Catalog) ResolveGPU(deviceID string) *GPUEntry {
	entry := c.GPUByDeviceID(deviceID)
	if entry == nil {
		return nil
	}
	resolved := *entry
	specs := make(map[string]any, len(entry.Specs))
	for k, v := range entry.Specs {
		specs[k] = v
	}
	resolved.Specs = specs
	applyGPUOverrides(&resolved, c.NotesForDevice(deviceID))
	return &resolved
}

func (c *Catalog) GPUsByGfxTarget(gfxTarget string) []*GPUEntry {
	var result []*GPUEntry
	for i := range c.GPUs {
		if c.GPUs[i].GfxTarget == gfxTarget {
			result = append(result, &c.GPUs[i])
		}
	}
	return result
}

func (c *Catalog) GPUsByGeneration(generation string) []*GPUEntry {
	var result []*GPUEntry
	for i := range c.GPUs {
		if c.GPUs[i].Generation == generation {
			result = append(result, &c.GPUs[i])
		}
	}
	return result
}

// NPUsByDeviceID returns all NPU rows for a device ID (may be several --
// see PRD §6.4: one device_id can bind to multiple (device_id, revision_id)
// hardware generations).
func (c *Catalog) NPUsByDeviceID(deviceID string) []*NPUEntry {
	needle := normalizeHex(deviceID)
	var result []*NPUEntry
	for i := range c.NPUs {
		if normalizeHex(c.NPUs[i].DeviceID) == needle {
			result = append(result, &c.NPUs[i])
		}
	}
	return result
}

func (c *Catalog) NPUByDeviceIDAndRevision(deviceID, revisionID string) *NPUEntry {
	needleDevice := normalizeHex(deviceID)
	needleRevision := normalizeHex(revisionID)
	for i := range c.NPUs {
		n := &c.NPUs[i]
		if normalizeHex(n.DeviceID) != needleDevice {
			continue
		}
		if n.RevisionID != nil && normalizeHex(*n.RevisionID) == needleRevision {
			return n
		}
	}
	return nil
}

// NotesForDevice returns every note applicable to a device ID, unfiltered
// -- PRD §7.4 verb 4: notes must be surfaced explicitly, never silently
// folded into "the data" (see also ResolveGPU, which applies a subset of
// these).
func (c *Catalog) NotesForDevice(deviceID string) []*NoteEntry {
	needle := normalizeHex(deviceID)
	var result []*NoteEntry
	for i := range c.Notes {
		if normalizeHex(c.Notes[i].DeviceID) == needle {
			result = append(result, &c.Notes[i])
		}
	}
	return result
}
