"""Attach RTL source locations to timing-path elements.

This is the stage that turns "net ``u_dsp/_0421_`` is slow" into "the adder at
``dsp_core.v:41`` is slow" — the only form the model can act on. Every attached
link carries a ``confidence`` and a ``method``:

* ``src_attribute`` (high) — the cell had an exact ``src`` in ``design.json``.
* ``name_heuristic`` (low)  — matched only on the leaf name after synthesis
  renaming, so the line is plausible but not certain.
* ``unmapped``              — no location found; the element is left honest.

The distinction matters: a low-confidence guess presented as a precise line
number is worse than an admitted gap, because it sends the model editing the
wrong code.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.parsers.yosys_json_src import SourceIndex
from orchestrator.schemas.common import write_json
from orchestrator.schemas.timing import CriticalPathRecord, SourceLink

_CONFIDENCE = {"src_attribute": 0.95, "name_heuristic": 0.45, "unmapped": 0.0}


def map_path(
    path: CriticalPathRecord, index: SourceIndex, rtl_dir: Path
) -> CriticalPathRecord:
    """Return a copy of ``path`` with source links filled in per element."""
    mapped_count = 0
    for element in path.elements:
        instance = element.instance or element.pin
        span = index.lookup(instance)
        if span is None:
            element.source_link = None
            continue
        method = "src_attribute" if index.has_exact(instance) else "name_heuristic"
        element.source_link = SourceLink(
            file=(rtl_dir / span.file).as_posix(),
            line_start=span.line_start,
            line_end=span.line_end,
            netlist_object=instance,
            confidence=_CONFIDENCE[method],
            method=method,
        )
        mapped_count += 1

    if mapped_count == 0:
        path.mapping_status = "unmapped"
    elif mapped_count == len(path.elements):
        path.mapping_status = "fully_mapped"
    else:
        path.mapping_status = "partial"
    return path


def dominant_source(path: CriticalPathRecord) -> SourceLink | None:
    """The highest-confidence source link on the path, for request targeting.

    Ties break toward the largest incremental delay — the element most worth
    the model's attention.
    """
    best: SourceLink | None = None
    best_key = (-1.0, -1.0)
    for element in path.elements:
        link = element.source_link
        if link is None:
            continue
        key = (link.confidence, element.incr_delay)
        if key > best_key:
            best_key = key
            best = link
    return best


def build_source_map(
    paths: list[CriticalPathRecord],
    index: SourceIndex,
    rtl_dir: Path,
    out_path: Path,
) -> list[CriticalPathRecord]:
    """Map every path and persist ``source_map.json``."""
    mapped = [map_path(p, index, rtl_dir) for p in paths]
    summary = {
        "index_size": len(index),
        "paths": [
            {
                "path_id": p.path_id,
                "mapping_status": p.mapping_status,
                "dominant_source": (
                    dominant_source(p).model_dump(mode="json")
                    if dominant_source(p)
                    else None
                ),
            }
            for p in mapped
        ],
    }
    write_json(out_path, summary)
    return mapped
