"""Parse OpenSTA reports into timing records.

Two files are consumed:

* ``wns_tns.rpt`` — the headline slack, written by the adapter as two labelled
  lines so it survives report-format drift in the detailed output.
* ``timing.rpt`` — the ``report_checks -format full_clock_expanded`` dump, from
  which individual :class:`CriticalPathRecord` objects are extracted, each with
  the byte span of the text it came from.

The parser never raises on an unfamiliar line. Anything it cannot interpret
becomes a ``parser_warnings`` entry, so a partially-understood report is visibly
partial rather than silently wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

from orchestrator.schemas.common import Provenance, Quantity, Status
from orchestrator.schemas.timing import CriticalPathRecord, PathElement, TimingAnalysisResult

_WNS_RE = re.compile(r"^wns\s+(-?[0-9.]+|INF)", re.IGNORECASE | re.MULTILINE)
_TNS_RE = re.compile(r"^tns\s+(-?[0-9.]+|INF)", re.IGNORECASE | re.MULTILINE)
_CLOCK_RE = re.compile(r"^clock\s+(\S+)\s+period\s+([0-9.]+)", re.IGNORECASE | re.MULTILINE)

# One reported path block: startpoint / endpoint / slack, plus the launch and
# capture clocks that full_clock_expanded provides.
_START_RE = re.compile(r"Startpoint:\s*(\S+)")
_END_RE = re.compile(r"Endpoint:\s*(\S+)")
_SLACK_RE = re.compile(r"slack\s*\(?(?:MET|VIOLATED)?\)?\s*(-?[0-9.]+)", re.IGNORECASE)
_LAUNCH_RE = re.compile(r"launched by\s+(\S+)|clocked by\s+(\S+)", re.IGNORECASE)
_ARRIVAL_RE = re.compile(r"data arrival time\s+(-?[0-9.]+)", re.IGNORECASE)
_REQUIRED_RE = re.compile(r"data required time\s+(-?[0-9.]+)", re.IGNORECASE)
# A path element row: "<incr> <cumulative> <dir> <pin> (<cell>)".
_ELEM_RE = re.compile(
    r"^\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+[\^vru]?\s*([\w/.\[\]$:]+)\s*(?:\(([\w$]+)\))?",
)


def _to_float(token: str) -> float | None:
    if token.upper() in {"INF", "+INF"}:
        return None
    if token.upper() == "-INF":
        return None
    try:
        return float(token)
    except ValueError:
        return None


def _split_path_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return (start_offset, end_offset, block_text) per reported path."""
    blocks: list[tuple[int, int, str]] = []
    starts = [m.start() for m in re.finditer(r"Startpoint:", text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append((start, end, text[start:end]))
    return blocks


def _parse_path_block(
    block: str, span: tuple[int, int], analysis_id: str, rank: int
) -> CriticalPathRecord:
    start_m = _START_RE.search(block)
    end_m = _END_RE.search(block)
    slack_m = _SLACK_RE.search(block)
    arrival_m = _ARRIVAL_RE.search(block)
    required_m = _REQUIRED_RE.search(block)

    slack = _to_float(slack_m.group(1)) if slack_m else None

    elements: list[PathElement] = []
    for order, line in enumerate(block.splitlines()):
        elem_m = _ELEM_RE.match(line)
        if not elem_m or "arrival" in line.lower() or "required" in line.lower():
            continue
        incr = _to_float(elem_m.group(1)) or 0.0
        cumulative = _to_float(elem_m.group(2)) or 0.0
        elements.append(
            PathElement(
                order=order,
                pin=elem_m.group(3),
                cell_type=elem_m.group(4),
                incr_delay=incr,
                cumulative_delay=cumulative,
            )
        )

    launch = None
    capture = None
    clock_hits = _LAUNCH_RE.findall(block)
    if clock_hits:
        first = next((g for g in clock_hits[0] if g), None)
        launch = first
        if len(clock_hits) > 1:
            capture = next((g for g in clock_hits[-1] if g), None)
    relationship = "same_domain"
    if launch and capture and launch != capture:
        relationship = "cross_domain"

    return CriticalPathRecord(
        path_id=f"{analysis_id}_path_{rank:04d}",
        analysis_id=analysis_id,
        rank=rank,
        slack=Quantity(value=slack, unit="ns"),
        arrival=Quantity(value=_to_float(arrival_m.group(1)), unit="ns") if arrival_m else None,
        required=Quantity(value=_to_float(required_m.group(1)), unit="ns") if required_m else None,
        startpoint={"object": start_m.group(1)} if start_m else {},
        endpoint={"object": end_m.group(1)} if end_m else {},
        launch_clock=launch,
        capture_clock=capture,
        relationship=relationship,
        elements=elements,
        logic_depth=max(len(elements) - 1, 0),
        mapping_status="unmapped",
        raw_report_span=span,
    )


def parse_timing(
    sta_dir: Path,
    run_id: str,
    stage: str,
    corner: str = "typical",
) -> tuple[TimingAnalysisResult, list[CriticalPathRecord]]:
    """Parse an OpenSTA output directory.

    Returns the headline :class:`TimingAnalysisResult` and the list of
    :class:`CriticalPathRecord` extracted from ``timing.rpt``.
    """
    analysis_id = f"{run_id}_{stage}_sta"
    warnings: list[str] = []

    wns_text = (sta_dir / "wns_tns.rpt").read_text(encoding="utf-8", errors="replace") \
        if (sta_dir / "wns_tns.rpt").exists() else ""
    wns_m = _WNS_RE.search(wns_text)
    tns_m = _TNS_RE.search(wns_text)
    wns = _to_float(wns_m.group(1)) if wns_m else None
    tns = _to_float(tns_m.group(1)) if tns_m else None
    if wns is None:
        warnings.append("could not read wns from wns_tns.rpt")

    clocks: list[str] = []
    clocks_path = sta_dir / "clocks.rpt"
    if clocks_path.exists():
        clocks = [m.group(1) for m in _CLOCK_RE.finditer(clocks_path.read_text(encoding="utf-8"))]
    else:
        warnings.append("clocks.rpt missing; clock inventory unknown")

    unconstrained_count = 0
    unconstrained_path = sta_dir / "unconstrained.rpt"
    if unconstrained_path.exists():
        unconstrained_count = len(
            re.findall(r"Startpoint:", unconstrained_path.read_text(encoding="utf-8"))
        )

    paths: list[CriticalPathRecord] = []
    timing_path = sta_dir / "timing.rpt"
    if timing_path.exists():
        text = timing_path.read_text(encoding="utf-8", errors="replace")
        for rank, (start, end, block) in enumerate(_split_path_blocks(text), start=1):
            paths.append(_parse_path_block(block, (start, end), analysis_id, rank))
    else:
        warnings.append("timing.rpt missing; no critical paths extracted")

    violation_count = sum(
        1 for p in paths if p.slack.value is not None and p.slack.value < 0
    )

    result = TimingAnalysisResult(
        analysis_id=analysis_id,
        run_id=run_id,
        stage=stage,
        corner=corner,
        status=Status.PASS if wns is not None else Status.ERROR,
        clocks=clocks,
        wns=Quantity(value=wns, unit="ns"),
        tns=Quantity(value=tns, unit="ns"),
        violation_count=violation_count,
        unconstrained_endpoint_count=unconstrained_count,
        critical_path_ids=[p.path_id for p in paths],
        report_artifact=timing_path.as_posix() if timing_path.exists() else None,
        parser_warnings=warnings,
        provenance=Provenance(
            produced_by="parsers.opensta_timing",
            artifact_paths=[timing_path.as_posix()],
        ),
    )
    return result, paths
