"""Turn Yosys ``design.json`` into a netlist-object → source-location index.

Yosys writes ``src`` attributes on cells (and often wires) of the form
``dsp_core.v:41.20-41.55`` — file, then ``line.col-line.col``. This module reads
those attributes and exposes a lookup from a cell instance name to its RTL
location. That index is the raw material :mod:`orchestrator.sourcemap` uses to
attach source links to timing-path elements.

A cell with no ``src`` attribute (constants, tie cells, synthesis-introduced
logic) simply does not appear in the index. The absence is meaningful and is
reported as ``method="unmapped"`` downstream rather than filled in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_SRC_RE = re.compile(r"([^\s:|]+):(\d+)(?:\.(\d+))?(?:-(\d+)(?:\.(\d+))?)?")


@dataclass(frozen=True)
class SourceSpan:
    file: str
    line_start: int
    line_end: int


def _parse_src(attr: str) -> SourceSpan | None:
    """Parse one ``file:line.col-line.col`` token. Yosys may pipe-join several;
    the first with a line number wins."""
    for piece in attr.split("|"):
        match = _SRC_RE.search(piece.strip())
        if match:
            file = match.group(1)
            line_start = int(match.group(2))
            line_end = int(match.group(4)) if match.group(4) else line_start
            return SourceSpan(file=Path(file).name, line_start=line_start, line_end=line_end)
    return None


class SourceIndex:
    """Lookup from netlist object name to RTL source span."""

    def __init__(self, spans: dict[str, SourceSpan]):
        self._spans = spans

    def __len__(self) -> int:
        return len(self._spans)

    def lookup(self, object_name: str) -> SourceSpan | None:
        """Resolve a netlist object, exact match first then a suffix heuristic.

        STA reports a hierarchical pin like ``u_dsp/_0421_``; the JSON keys are
        cell names within a module. When an exact key is absent we fall back to
        the last path segment, and the caller lowers the confidence accordingly.
        """
        if object_name in self._spans:
            return self._spans[object_name]
        leaf = object_name.split("/")[-1]
        return self._spans.get(leaf)

    def has_exact(self, object_name: str) -> bool:
        return object_name in self._spans


def build_source_index(design_json_path: Path) -> SourceIndex:
    """Read ``design.json`` and index every object that carries a ``src``."""
    data = json.loads(design_json_path.read_text(encoding="utf-8"))
    spans: dict[str, SourceSpan] = {}

    for _module_name, module in (data.get("modules") or {}).items():
        for cell_name, cell in (module.get("cells") or {}).items():
            attrs = cell.get("attributes") or {}
            src = attrs.get("src")
            if src:
                span = _parse_src(src)
                if span:
                    spans[cell_name] = span
        for net_name, net in (module.get("netnames") or {}).items():
            attrs = net.get("attributes") or {}
            src = attrs.get("src")
            if src and net_name not in spans:
                span = _parse_src(src)
                if span:
                    spans[net_name] = span

    return SourceIndex(spans)
