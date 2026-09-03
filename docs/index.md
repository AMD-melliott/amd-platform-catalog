# AMD Platform Catalog

A versioned, cross-language catalog of AMD GPU and NPU platform facts —
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and hand-validated hardware notes — aggregated from AMD's own
authoritative public sources.

This site publishes the project's two working documents as-is, so there's
one source of truth instead of a docs site that drifts from the repo:

```{toctree}
:maxdepth: 2

README
PRD
```

- **[README](README.md)** — what's built today: building the catalog,
  running the tests, and using the Rust, Python, and Go bindings plus the
  agent skill.
- **[PRD](PRD.md)** — the full design: problem statement, data model,
  sourcing decisions, architecture, and the phased implementation plan.

Source: <https://github.com/AMD-melliott/amd-platform-catalog>
