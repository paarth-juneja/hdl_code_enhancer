"""Timing and QoR records — the parsed view of what the tools measured."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orchestrator.schemas.common import NebulaRecord, Provenance, Quantity, Status


class SourceLink(BaseModel):
    """Netlist object resolved back to RTL.

    ``confidence`` and ``method`` are mandatory because synthesis flattens and
    renames: some cells genuinely cannot be traced, and saying so is required.
    A link with ``method="unmapped"`` is a valid, honest result.
    """

    file: str
    line_start: int | None = None
    line_end: int | None = None
    netlist_object: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: str  # src_attribute | name_heuristic | unmapped


class PathElement(BaseModel):
    """One hop along a timing path, in arrival order."""

    order: int
    pin: str
    instance: str | None = None
    cell_type: str | None = None
    incr_delay: float = 0.0
    cumulative_delay: float = 0.0
    source_link: SourceLink | None = None


class CriticalPathRecord(NebulaRecord):
    """One reported timing path with ordered evidence.

    ``raw_report_span`` holds the byte offsets of the text this record was parsed
    from, so a reviewer asking "where did this number come from?" gets a file
    offset rather than an assurance.
    """

    path_id: str
    analysis_id: str
    rank: int
    check_type: str = "setup"
    slack: Quantity
    arrival: Quantity | None = None
    required: Quantity | None = None
    startpoint: dict[str, str] = Field(default_factory=dict)
    endpoint: dict[str, str] = Field(default_factory=dict)
    launch_clock: str | None = None
    capture_clock: str | None = None
    relationship: str = "same_domain"  # same_domain | cross_domain | io
    elements: list[PathElement] = Field(default_factory=list)
    logic_depth: int = 0
    mapping_status: str = "unmapped"
    raw_report_span: tuple[int, int] | None = None


class TimingAnalysisResult(NebulaRecord):
    """Headline timing for one stage and corner.

    ``unconstrained_endpoint_count`` is not optional. Without it, "zero
    violations" and "nothing was constrained" are the same number.
    """

    analysis_id: str
    run_id: str
    stage: str  # synth | screen | orfs
    corner: str
    check_type: str = "setup"
    status: Status = Status.NOT_RUN
    units: dict[str, str] = Field(
        default_factory=lambda: {"time": "ns", "capacitance": "pF", "resistance": "kOhm"}
    )
    clocks: list[str] = Field(default_factory=list)
    generated_clocks: list[str] = Field(default_factory=list)
    asynchronous_groups: list[list[str]] = Field(default_factory=list)
    wns: Quantity = Quantity(value=None, unit="ns")
    tns: Quantity = Quantity(value=None, unit="ns")
    violation_count: int = 0
    unconstrained_endpoint_count: int = 0
    critical_path_ids: list[str] = Field(default_factory=list)
    report_artifact: str | None = None
    parser_version: str = "1.0.0"
    parser_warnings: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None


class QoRRecord(NebulaRecord):
    """Area, cell count, and power for one stage.

    Power stays ``None`` unless ``activity_source`` names where the switching
    activity came from. An unsourced power number is not evidence.
    """

    run_id: str
    stage: str
    cell_count: int | None = None
    cell_area: Quantity = Quantity(value=None, unit="um^2")
    die_area: Quantity = Quantity(value=None, unit="um^2")
    power: Quantity = Quantity(value=None, unit="mW")
    activity_source: str | None = None
    max_frequency: Quantity = Quantity(value=None, unit="MHz")
    provenance: Provenance | None = None
