"""Baseline-versus-candidate comparison and the verdict it carries."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orchestrator.schemas.common import FailureClass, NebulaRecord, Verdict


class ConfigurationEquivalence(BaseModel):
    """Whether the two runs are even allowed to be compared.

    Checked before any metric is read. If ``all_equal`` is false the comparison
    reports ``NON_COMPARABLE`` and the metric table is not interpreted at all —
    a faster number measured under different settings is not a result.
    """

    same_toolchain: bool = False
    same_constraints: bool = False
    same_library: bool = False
    same_corner: bool = False
    differences: list[str] = Field(default_factory=list)

    @property
    def all_equal(self) -> bool:
        return (
            self.same_toolchain
            and self.same_constraints
            and self.same_library
            and self.same_corner
        )


class MetricDelta(BaseModel):
    """One metric, both sides, and the change between them."""

    name: str
    baseline: float | None
    candidate: float | None
    unit: str
    absolute_delta: float | None = None
    relative_delta_pct: float | None = None
    direction: str = "neutral"  # improve | regress | neutral
    source_artifact: str | None = None


class GuardrailResult(BaseModel):
    """One declared guardrail and whether the candidate stayed inside it."""

    name: str
    limit: float | None
    observed: float | None
    passed: bool
    detail: str = ""


class PPAComparison(NebulaRecord):
    """The authoritative comparison record. Only ``policy.py`` constructs one."""

    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    candidate_id: str
    authoritative_stage: str = "orfs"
    configuration_equivalence: ConfigurationEquivalence = ConfigurationEquivalence()
    metrics: list[MetricDelta] = Field(default_factory=list)
    guardrail_results: list[GuardrailResult] = Field(default_factory=list)
    latency_throughput_changes: str = "none"
    equivalence_status: str = "NOT_RUN"
    pareto_status: str = "not_evaluated"
    acceptance_policy_version: str = "1.0.0"
    verdict: Verdict = Verdict.NOT_EVALUATED
    failure_class: FailureClass = FailureClass.NONE
    verdict_reasons: list[str] = Field(default_factory=list)
