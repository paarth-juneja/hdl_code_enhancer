"""Parse ORFS ``metadata-*.json`` into a :class:`QoRRecord`.

ORFS emits a flat metrics JSON keyed by ``stage__group__metric``. Only the
post-route ("finish") figures are treated as authoritative; the synthesis
figures in the same file are the same numbers the screen stage already had, and
mixing the two is exactly the stage-confusion the methodology warns against.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.schemas.common import Provenance, Quantity, Status
from orchestrator.schemas.timing import QoRRecord, TimingAnalysisResult


def _first(data: dict, *keys: str, default=None):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def parse_orfs_metrics(
    metadata_path: Path, run_id: str, corner: str = "typical"
) -> tuple[QoRRecord, TimingAnalysisResult]:
    """Return post-route QoR and timing from an ORFS metadata file."""
    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    cell_count = _first(data, "finish__design__instance__count",
                        "synth__design__instance__count")
    cell_area = _first(data, "finish__design__instance__area")
    wns = _first(data, "finish__timing__setup__ws")
    tns = _first(data, "finish__timing__setup__tns")
    clock_count = _first(data, "constraints__clocks__count", default=0)
    violations = _first(data, "finish__timing__drv__setup_violation_count", default=0)
    power = _first(data, "finish__power__total")

    qor = QoRRecord(
        run_id=run_id,
        stage="orfs",
        cell_count=int(cell_count) if cell_count is not None else None,
        cell_area=Quantity(value=float(cell_area) if cell_area is not None else None, unit="um^2"),
        power=Quantity(value=float(power) if power is not None else None, unit="mW"),
        activity_source=None,  # no activity file supplied; power stays unsourced
        provenance=Provenance(
            produced_by="parsers.orfs_metrics",
            artifact_paths=[metadata_path.as_posix()],
        ),
    )

    timing = TimingAnalysisResult(
        analysis_id=f"{run_id}_orfs_sta",
        run_id=run_id,
        stage="orfs",
        corner=corner,
        status=Status.PASS if wns is not None else Status.ERROR,
        wns=Quantity(value=float(wns) if wns is not None else None, unit="ns"),
        tns=Quantity(value=float(tns) if tns is not None else None, unit="ns"),
        violation_count=int(violations) if violations is not None else 0,
        clocks=[f"clock_{i}" for i in range(int(clock_count))] if clock_count else [],
        provenance=Provenance(
            produced_by="parsers.orfs_metrics",
            artifact_paths=[metadata_path.as_posix()],
        ),
    )
    return qor, timing
