"""The experiment ledger.

Append-only. Rejected and failed iterations are recorded with the same detail as
accepted ones — an experiment that keeps only its successes is not an experiment.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from orchestrator.schemas.common import FailureClass, NebulaRecord, Verdict, utc_now


class IterationRecord(BaseModel):
    """One trip around the optimization loop, successful or not."""

    index: int
    candidate_id: str
    parent_candidate_id: str
    recommendation_id: str | None = None
    patch_id: str | None = None
    patch_hash: str | None = None
    transformation_type: str | None = None
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    comparison_id: str | None = None
    verification_id: str | None = None
    verdict: Verdict = Verdict.NOT_EVALUATED
    failure_class: FailureClass = FailureClass.NONE
    measured_delta: dict[str, float] = Field(default_factory=dict)
    run_dir: str = ""
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None


class Budget(BaseModel):
    max_iterations: int = 5
    max_candidates: int = 10
    consumed_iterations: int = 0
    consumed_candidates: int = 0


class OptimizationIterationHistory(NebulaRecord):
    """Complete history for one experiment.

    ``seen_patch_hashes`` is what stops the loop re-proposing a change it already
    measured. Without it a model that likes one idea will spend the whole budget
    on it.
    """

    experiment_id: str
    project_id: str
    baseline_candidate_id: str = "baseline"
    iterations: list[IterationRecord] = Field(default_factory=list)
    budget: Budget = Budget()
    seen_patch_hashes: list[str] = Field(default_factory=list)
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    stop_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
