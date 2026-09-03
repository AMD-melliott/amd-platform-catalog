---
myst:
    html_meta:
        "description": "A versioned, cross-language catalog of AMD GPU and NPU platform facts"
        "keywords": "AMD, GPU, NPU, ROCm, catalog, gfx target, precision support"
---

# AMD Platform Catalog

A versioned, cross-language catalog of AMD GPU and NPU platform facts:
architecture generation, gfx/LLVM target, hardware specs, precision/data-type
support, and hand-validated hardware notes. It's aggregated from AMD's own
authoritative public sources.

Source: <https://github.com/AMD-melliott/amd-platform-catalog>

```{toctree}
:hidden:
:maxdepth: 2

overview
bindings/rust
bindings/python
bindings/go
agent-skill
```

## Overview

::::{grid} 1 1 2 2
:gutter: 1

:::{grid-item-card} Project
- {doc}`/overview`
:::

:::{grid-item-card} Bindings
- {doc}`/bindings/rust`
- {doc}`/bindings/python`
- {doc}`/bindings/go`
:::

:::{grid-item-card} Agent skill
- {doc}`/agent-skill`
:::

::::
