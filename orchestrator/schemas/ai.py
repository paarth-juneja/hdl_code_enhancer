"""The AI contract: what goes to the model, and what it is allowed back.

These three models are the entire surface area of the generative component.
Anything the model produces that does not validate against
:class:`AIRecommendation` is discarded — it never reaches the filesystem as a
candidate.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from orchestrator.schemas.common import NebulaRecord, Quantity
from orchestrator.schemas.timing import CriticalPathRecord


class ActionKind(str, Enum):
    """What the model decided to do.

    ``ABSTAIN`` is a first-class result, not a failure. A model that declines
    when it has no safe proposal is behaving correctly, and the policy engine
    records it without penalty.
    """

    PATCH = "patch"
    ADVISE = "advise"
    ABSTAIN = "abstain"


class RTLContextSlice(BaseModel):
    """A bounded window of source. The model never receives whole files."""

    file: str
    line_start: int
    line_end: int
    text: str
    role: str = "critical_path_source"
    module: str | None = None
    editable: bool = True


class PortConnection(BaseModel):
    """One named child port connected to an expression in its parent module."""

    port: str
    signal: str
    direction: str = "unknown"  # parent_to_child | child_to_parent | inout | unknown


class ModuleConnection(BaseModel):
    """A bounded, source-grounded edge in the RTL instance hierarchy."""

    parent_module: str
    parent_file: str
    child_module: str
    child_file: str
    instance: str
    line: int
    ports: list[PortConnection] = Field(default_factory=list)
    unconnected_ports: list[str] = Field(default_factory=list)
    complete: bool = True


class PreviousAttempt(BaseModel):
    """One earlier iteration, summarised as measured fact.

    Only measured outcomes are fed back. The model's own earlier predictions are
    deliberately excluded so it cannot reinforce its own guesses.
    """

    recommendation_id: str
    transformation_type: str
    patch_hash: str | None = None
    verdict: str
    failure_class: str
    measured_delta: dict[str, float] = Field(default_factory=dict)


class AIOptimizationRequest(NebulaRecord):
    """Everything the model is given. Nothing outside this object is visible to it."""

    request_id: str
    project_id: str
    parent_candidate_id: str
    iteration: int
    facts: dict[str, object] = Field(default_factory=dict)
    critical_path: CriticalPathRecord | None = None
    rtl_context: list[RTLContextSlice] = Field(default_factory=list)
    connection_map: list[ModuleConnection] = Field(default_factory=list)
    invariants: dict[str, str] = Field(default_factory=dict)
    allowed_transformations: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    change_budget: dict[str, int] = Field(default_factory=dict)
    previous_attempts: list[PreviousAttempt] = Field(default_factory=list)
    required_output_schema: str = "AIRecommendation@1.0.0"
    model_data_classification: str = "bounded_context_only"


class PredictedEffect(BaseModel):
    """A prediction, kept in a separate field from anything measured.

    ``basis`` forces the model to name its reasoning, which makes a wrong
    prediction diagnosable rather than merely wrong.
    """

    metric: str
    direction: str  # improve | regress | neutral
    confidence_band: str  # low | medium | high
    basis: str


class RTLPatch(NebulaRecord):
    """A candidate change, replayable against exactly the source it targeted."""

    patch_id: str
    recommendation_id: str
    base_source_hash: str
    format: str = "unified_diff"
    diff_text: str = ""
    changed_files: list[str] = Field(default_factory=list)
    changed_line_count: int = 0
    touched_identifiers: list[str] = Field(default_factory=list)
    declared_semantic_class: str = "cycle_exact"
    latency_delta: int = 0
    interface_delta: bool = False
    clock_reset_cdc_touch_flags: dict[str, bool] = Field(default_factory=dict)
    apply_status: str = "not_attempted"
    static_validation_results: list[str] = Field(default_factory=list)


class AIRecommendation(NebulaRecord):
    """The model's structured output.

    Note the fields that do *not* exist here: there is no status, no verdict, no
    measured metric, and no ``optimization_succeeded``. The schema itself is what
    prevents the model from claiming a result.
    """

    recommendation_id: str
    request_id: str
    model_record_id: str = ""
    transformation_type: str
    action: ActionKind = ActionKind.ABSTAIN
    target: dict[str, object] = Field(default_factory=dict)
    observation_refs: list[str] = Field(default_factory=list)
    hypothesis: str = ""
    rationale: str = ""
    preconditions: list[str] = Field(default_factory=list)
    predicted_effects: list[PredictedEffect] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invariants_claimed: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)
    patch: RTLPatch | None = None
    uncertainty: float = Field(default=1.0, ge=0.0, le=1.0)
    abstention_reason: str | None = None
    schema_validation: str = "not_validated"
    token_usage: dict[str, int] = Field(default_factory=dict)
    estimated_cost: Quantity = Quantity(value=None, unit="USD")
