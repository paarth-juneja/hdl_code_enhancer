"""Parse the Yosys ``stat`` report into a :class:`QoRRecord`.

Yosys prints two different shapes depending on whether ``-liberty`` was given,
and the pipeline needs both:

* Without a liberty file, counts appear as labelled lines::

      Number of cells:               908

* With ``-liberty`` — which is what ``synth.ys`` actually emits, because the
  area figures come from the library — the same counts appear as a right-aligned
  table whose label trails the value::

        908  1.4E+03 cells

The table's area column is rounded for display (``1.4E+03``), so it is only a
fallback. The authoritative figure is the ``Chip area for module`` line, which
Yosys prints at full precision.

Per the contract in :mod:`orchestrator.parsers`, format drift never raises: an
unrecognised report yields a record whose values are ``None``, so a number the
parser did not find is visibly absent rather than quietly wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

from orchestrator.schemas.common import Provenance, Quantity
from orchestrator.schemas.timing import QoRRecord

# "Number of cells:   908" — the form emitted without -liberty.
_LABELLED_CELLS = re.compile(r"^\s*Number of cells:\s*(\d+)\s*$", re.MULTILINE)

# "  908  1.4E+03 cells" — the -liberty table. The area column is either a
# number or "-" (printed for rows that have no area, such as wires), and the
# label trails the values. Anchoring on the exact word "cells" is what keeps
# this off the per-cell-type rows below it ("47  50.008  AND2_X1").
_TABLE_CELLS = re.compile(
    r"^\s*(\d+)\s+(-|[\d.eE+-]+)\s+cells\s*$", re.MULTILINE
)

# "Chip area for module '\nebula_top': 1401.022000"
_CHIP_AREA = re.compile(r"^\s*Chip area for module\s+'.*?':\s*([\d.eE+-]+)", re.MULTILINE)


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_synth_stat(
    stat_path: Path, run_id: str, stage: str = "synth"
) -> QoRRecord:
    """Return cell count and area from a Yosys ``stat`` report.

    Args:
        stat_path: the ``synth_stat.txt`` written by ``tee -o ... stat``.
        stage: which stage produced it — ``"synth"`` for the baseline, or
            ``"screen"`` for a candidate's fast re-synthesis.
    """
    try:
        text = stat_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    cell_count: int | None = None
    match = _LABELLED_CELLS.search(text) or _TABLE_CELLS.search(text)
    if match:
        cell_count = int(match.group(1))

    cell_area: float | None = None
    area_match = _CHIP_AREA.search(text)
    if area_match:
        cell_area = _to_float(area_match.group(1))
    else:
        # Fall back to the table's rounded area column rather than reporting
        # nothing, but only when it carries a real number.
        table = _TABLE_CELLS.search(text)
        if table and table.group(2) != "-":
            cell_area = _to_float(table.group(2))

    return QoRRecord(
        run_id=run_id,
        stage=stage,
        cell_count=cell_count,
        cell_area=Quantity(value=cell_area, unit="um^2"),
        # Yosys measures no power. Leaving activity_source unset keeps an
        # unsourced power number out of the record entirely.
        power=Quantity(value=None, unit="mW"),
        activity_source=None,
        provenance=Provenance(
            produced_by="parsers.yosys_stat",
            artifact_paths=[stat_path.as_posix()],
        ),
    )
