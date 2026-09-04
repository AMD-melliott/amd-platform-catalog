"""Parse LLVM's ``AMDGPUUsage.rst`` Processors table.

Purpose (PRD §8): cross-check `gfx_target` <-> `generation` against ROCm's
`gpu-specs.rst`, and catch brand-new `gfx_target`\\ s LLVM lists before
ROCm's own spec tables catch up. This module only parses LLVM's table into
per-processor records; the actual cross-check (comparing against ingested
GpuEntry records) lives in build_catalog.py, mirroring how the precision
join and device_id join are separate from their own single-source parsers.

**Table shape.** The "AMDGPU Processors" table isn't a ``list-table`` --
it's an RST simple table with embedded single-cell "family header" rows
(e.g. ``**GCN GFX11.5 (RDNA 3.5)** [AMD-GCN-GFX11-RDNA3.5]_``) that group
the processor rows beneath them. `rst_tables.extract_list_tables` already
handles this structurally (docutils parses it into the same table/row/entry
tree as a list-table); family-header rows surface as single-cell rows.

**Generation extraction is citation-based, not header-text-based**, because
one family header can cover *several* real generations: the whole "GCN GFX9
(Vega)" group spans gfx900/904 (Vega), gfx906 (Vega 7nm), gfx908 (CDNA1),
gfx90a (CDNA2), and gfx942 (CDNA3) -- distinguishable only via the several
citation tokens trailing that one header (``AMD-GCN-GFX908-CDNA1``, etc.),
each naming which specific `gfx_target` number(s) it covers. Most modern
families (GFX10.3/RDNA2, GFX11/RDNA3, GFX11.5/RDNA3.5, GFX12/RDNA4) instead
carry one blanket citation covering the whole family. Older pre-RDNA/CDNA
families (R600, GFX6-8) either have no generation-bearing citation at all or
none whose parenthetical name matches CDNA/RDNA naming -- `generation` comes
back `None` for those rows, which is correct: they're out of scope for this
catalog (ROCm's `gpu-specs.rst` doesn't cover them under a comparable label
either).

Some very new families (GFX11.7/"RDNA 4m", GFX13/RDNA5) have no citation at
all yet; for those, the header's own parenthetical is used as a fallback
generation label when it matches CDNA/RDNA naming -- exactly the "catch
brand-new targets" case this source exists for.

**Subarch string, for GFXIP stepping (PRD §6.3).** The table's "Target
Triple Architecture" column (the *third* cell, not the mostly-empty
"Alternative Processor" second cell, which holds unrelated codename aliases
like ``carrizo``) gives a subarch string like ``amdgpu11.51`` for
``gfx1151``, where the two characters after the dot are minor version +
stepping concatenated. ``stepping_from_subarch`` extracts just the
stepping character; build_catalog.py merges it onto GpuEntry.specs
(gpu-specs.rst has no stepping column of its own to source it from).
Stepping is usually a decimal digit, but two CDNA2 chips have a letter
(``gfx90a`` -> ``amdgpu9.0a``, ``gfx90c`` -> ``amdgpu9.0c``).
"""

from __future__ import annotations

import dataclasses
import re

from .rst_tables import extract_list_tables

_PROCESSOR_TABLE_NAME = "amdgpu-processor-table"

# A citation token like "AMD-GCN-GFX908-CDNA1" or "AMD-GCN-GFX900-GFX904-VEGA".
_CITATION_TOKEN_RE = re.compile(r"\bAMD-[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\b")
_GFX_SEGMENT_RE = re.compile(r"^GFX([0-9A-Z]+)$")
_PARENTHETICAL_RE = re.compile(r"\(([^)]+)\)")
_MODERN_GENERATION_RE = re.compile(r"^(RDNA|CDNA)\s*([0-9]+(?:\.[0-9]+)?[a-z]?)$", re.IGNORECASE)

# A subarch string like "amdgpu11.51" (gfx1151: minor "5", stepping "1") or
# "amdgpu9.0a" (gfx90a: minor "0", stepping "a"). The two characters after
# the dot are always minor+stepping concatenated; only the last one is the
# stepping. Anything that doesn't match this shape returns no stepping,
# never guessed.
_SUBARCH_RE = re.compile(r"^amdgpu\d+\.([0-9a-z]{2})$", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class ProcessorEntry:
    gfx_target: str
    family: str
    generation: str | None
    subarch: str | None = None


def _parse_citations(header_text: str) -> list[tuple[list[str], str | None]]:
    """Each citation token -> (gfx-number(s) it covers, generation or None)."""
    citations: list[tuple[list[str], str | None]] = []
    for token in _CITATION_TOKEN_RE.findall(header_text):
        segments = token.split("-")[1:]  # drop leading "AMD"
        if segments and segments[0] == "GCN":
            segments = segments[1:]
        gfx_numbers: list[str] = []
        generation_segments: list[str] = []
        for segment in segments:
            match = _GFX_SEGMENT_RE.match(segment)
            if match:
                gfx_numbers.append(match.group(1))
            else:
                generation_segments.append(segment)
        if gfx_numbers:
            generation = "-".join(generation_segments) if generation_segments else None
            citations.append((gfx_numbers, generation))
    return citations


def _parenthetical_generation(header_text: str) -> str | None:
    match = _PARENTHETICAL_RE.search(header_text)
    if not match:
        return None
    modern = _MODERN_GENERATION_RE.match(match.group(1).strip())
    if not modern:
        return None
    return f"{modern.group(1).upper()}{modern.group(2)}"


def _resolve_generation(
    gfx_number: str,
    citations: list[tuple[list[str], str | None]],
    parenthetical_generation: str | None,
) -> str | None:
    best_generation: str | None = None
    best_match_len = -1
    for gfx_numbers, generation in citations:
        for candidate in gfx_numbers:
            if generation is not None and gfx_number.startswith(candidate) and len(candidate) > best_match_len:
                best_generation = generation
                best_match_len = len(candidate)
    return best_generation if best_generation is not None else parenthetical_generation


def stepping_from_subarch(subarch: str) -> str | None:
    """Extracts the GFXIP stepping character from an LLVM subarch string
    (see the module docstring). Returns None for anything that doesn't
    match the expected `amdgpu<major>.<minor><stepping>` shape: this
    catalog never guesses a stepping it can't parse cleanly.
    """
    match = _SUBARCH_RE.match(subarch.strip())
    if not match:
        return None
    return match.group(1)[-1].lower()


def ingest(rst_text: str) -> list[ProcessorEntry]:
    tables = extract_list_tables(rst_text)
    table = next(t for t in tables if _PROCESSOR_TABLE_NAME in t.names)

    entries: list[ProcessorEntry] = []
    family_header = ""
    citations: list[tuple[list[str], str | None]] = []
    paren_generation: str | None = None

    for row in table.rows:
        if len(row) == 1:
            family_header = row[0]
            citations = _parse_citations(family_header)
            paren_generation = _parenthetical_generation(family_header)
            continue

        gfx_target = row[0].strip()
        if not gfx_target:
            continue

        generation = None
        if gfx_target.lower().startswith("gfx"):
            generation = _resolve_generation(gfx_target[3:].upper(), citations, paren_generation)

        # row[1] is "Alternative Processor" (codename aliases like
        # "carrizo"; empty for virtually every modern chip), not what we
        # want. row[2] is "Target Triple Architecture", the subarch string.
        subarch = row[2].strip() if len(row) > 2 else ""

        entries.append(
            ProcessorEntry(
                gfx_target=gfx_target,
                family=family_header,
                generation=generation,
                subarch=subarch or None,
            )
        )

    return entries
