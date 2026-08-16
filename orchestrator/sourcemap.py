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

Mapping happens at two levels, because per-element mapping alone does not work
on real designs. Technology mapping destroys the evidence: measured on gcd only
34 of 220 cells still carry ``src``, and on aes 522 of 9950 -- in both cases the
survivors are registers, never the combinational logic a critical path is made
of. So a path's body is usually unmappable no matter how good the lookup is.
What does survive is the path's endpoints, and ``mapping_status`` gains
``endpoints_only`` to say exactly that rather than dressing it up as partial
success.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.parsers.yosys_json_src import SourceIndex
from orchestrator.schemas.common import write_json
from orchestrator.schemas.timing import CriticalPathRecord, SourceLink

_CONFIDENCE = {"src_attribute": 0.95, "name_heuristic": 0.45, "unmapped": 0.0}


def _link(
    instance: str, index: SourceIndex, rtl_dir: Path
) -> SourceLink | None:
    """Resolve one netlist object to a source link, or None."""
    span = index.lookup(instance)
    if span is None:
        return None
    method = "src_attribute" if index.has_exact(instance) else "name_heuristic"
    return SourceLink(
        file=(rtl_dir / span.file).as_posix(),
        line_start=span.line_start,
        line_end=span.line_end,
        netlist_object=instance,
        confidence=_CONFIDENCE[method],
        method=method,
    )


def map_path(
    path: CriticalPathRecord, index: SourceIndex, rtl_dir: Path
) -> CriticalPathRecord:
    """Return a copy of ``path`` with source links filled in.

    Both the per-element links and the endpoint links are attempted. Elements
    rarely resolve on a real design -- abc discards ``src`` from the mapped
    combinational cells that make up the body of a path -- so the endpoints
    carry the mapping in practice. They are registers, and registers keep their
    attribute, which is why a path that maps nothing in the middle can still be
    stated as "between the register at gcd.v:352 and the one at gcd.v:571".
    """
    mapped_count = 0
    for element in path.elements:
        instance = element.instance or element.pin
        element.source_link = _link(instance, index, rtl_dir)
        if element.source_link is not None:
            mapped_count += 1

    # Endpoint names come from the report header ("Startpoint: _390_ (...)"),
    # and after the autoname pass in adapters/yosys.py they are the same names
    # design.json uses.
    start_obj = path.startpoint.get("object") if path.startpoint else None
    end_obj = path.endpoint.get("object") if path.endpoint else None
    path.startpoint_source = _link(start_obj, index, rtl_dir) if start_obj else None
    path.endpoint_source = _link(end_obj, index, rtl_dir) if end_obj else None
    endpoints_mapped = sum(
        1 for link in (path.startpoint_source, path.endpoint_source) if link
    )

    if mapped_count and mapped_count == len(path.elements):
        path.mapping_status = "fully_mapped"
    elif mapped_count:
        path.mapping_status = "partial"
    elif endpoints_mapped:
        # Honest distinct state: the path is anchored in RTL, but only at its
        # ends. Reporting this as "partial" would overstate what is known.
        path.mapping_status = "endpoints_only"
    else:
        path.mapping_status = "unmapped"
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
    if best is not None:
        return best
    # Nothing on the path body resolved, which is the normal case after
    # technology mapping. Fall back to the endpoint: the register the path
    # writes into is the more useful of the two, since that is where the
    # violation lands.
    return path.endpoint_source or path.startpoint_source


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
                "startpoint_source": (
                    p.startpoint_source.model_dump(mode="json")
                    if p.startpoint_source
                    else None
                ),
                "endpoint_source": (
                    p.endpoint_source.model_dump(mode="json")
                    if p.endpoint_source
                    else None
                ),
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
