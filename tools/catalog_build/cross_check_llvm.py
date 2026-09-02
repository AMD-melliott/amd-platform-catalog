"""Cross-check LLVM's AMDGPUUsage Processors table against ingested GpuEntry
records (PRD §8's stated purpose for `ingest_llvm_amdgpu_usage.py`): flag
`gfx_target` <-> `generation` disagreements between the two sources, and
surface LLVM `gfx_target`\\ s ROCm's `gpu-specs.rst` doesn't have yet -- the
actual "catch brand-new targets" reason this source is ingested at all.

Only targets LLVM could resolve to a real generation label participate here
(see ingest_llvm_amdgpu_usage.ProcessorEntry.generation); older pre-RDNA/CDNA
chips are correctly `None` there and would otherwise flood this report with
irrelevant "new target" noise for hardware neither source treats as current.
"""

from __future__ import annotations

import dataclasses

from .ingest_llvm_amdgpu_usage import ProcessorEntry


@dataclasses.dataclass
class CrossCheckReport:
    # (product_name, gfx_target, rocm_generation, llvm_generation)
    mismatches: list[tuple[str, str, str, str]] = dataclasses.field(default_factory=list)
    new_targets: list[ProcessorEntry] = dataclasses.field(default_factory=list)


def cross_check(
    gpu_entries: list[dict],
    llvm_entries: list[ProcessorEntry],
    generation_aliases: dict[str, str],
) -> CrossCheckReport:
    report = CrossCheckReport()
    llvm_by_target = {entry.gfx_target: entry for entry in llvm_entries}
    known_targets = {entry.get("gfx_target") for entry in gpu_entries}

    for entry in gpu_entries:
        gfx_target = entry.get("gfx_target")
        llvm_entry = llvm_by_target.get(gfx_target)
        if llvm_entry is None or llvm_entry.generation is None:
            continue
        rocm_generation = entry.get("generation")
        normalized_rocm = generation_aliases.get(rocm_generation, rocm_generation)
        normalized_llvm = generation_aliases.get(llvm_entry.generation, llvm_entry.generation)
        if normalized_rocm != normalized_llvm:
            report.mismatches.append((entry["product_name"], gfx_target, rocm_generation, llvm_entry.generation))

    for llvm_entry in llvm_entries:
        if llvm_entry.generation is not None and llvm_entry.gfx_target not in known_targets:
            report.new_targets.append(llvm_entry)

    return report
