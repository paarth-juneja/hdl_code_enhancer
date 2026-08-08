"""The acceptance policy — where authority lives.

Only this module produces a :class:`~orchestrator.schemas.common.Verdict`.
Nothing upstream, and least of all the model, can set one. The order of checks
is deliberate and is itself a safety property:

1. **Configuration equivalence first.** If the two runs did not use the same
   toolchain, library, corner, and constraints, no metric is even read — the
   verdict is ``NON_COMPARABLE``. A faster number measured under different
   settings is not evidence of anything.
2. **Formal equivalence.** Only an outright ``PASS`` counts. ``UNKNOWN`` and
   ``TIMEOUT`` are unproven, never accepted.
3. **Clock preservation.** A candidate that dropped a clock changed the timing
   problem and is rejected.
4. **Primary objective.** Timing must improve (or the target violation close).
5. **Guardrails.** Area/cell regressions must stay within the declared limit.
"""

from __future__ import annotations

from orchestrator.config import ProjectConfiguration
from orchestrator.schemas.common import FailureClass, Status, Verdict
from orchestrator.schemas.comparison import (
    ConfigurationEquivalence,
    GuardrailResult,
    MetricDelta,
    PPAComparison,
)
from orchestrator.schemas.timing import QoRRecord, TimingAnalysisResult
from orchestrator.schemas.verification import VerificationResult


def _delta(name: str, baseline: float | None, candidate: float | None,
           unit: str, higher_is_better: bool, artifact: str | None = None) -> MetricDelta:
    absolute = None
    relative = None
    direction = "neutral"
    if baseline is not None and candidate is not None:
        absolute = round(candidate - baseline, 6)
        if baseline != 0:
            relative = round((candidate - baseline) / abs(baseline) * 100.0, 3)
        improved = (candidate > baseline) if higher_is_better else (candidate < baseline)
        if absolute == 0:
            direction = "neutral"
        else:
            direction = "improve" if improved else "regress"
    return MetricDelta(
        name=name, baseline=baseline, candidate=candidate, unit=unit,
        absolute_delta=absolute, relative_delta_pct=relative,
        direction=direction, source_artifact=artifact,
    )


def check_configuration_equivalence(
    baseline_settings_hash: str,
    candidate_settings_hash: str,
    baseline_clocks: list[str],
    candidate_clocks: list[str],
) -> ConfigurationEquivalence:
    """Compare everything that must be identical across the two runs."""
    differences: list[str] = []
    same = baseline_settings_hash == candidate_settings_hash
    if not same:
        differences.append("settings hash differs between baseline and candidate")
    return ConfigurationEquivalence(
        same_toolchain=same,
        same_constraints=same,
        same_library=same,
        same_corner=same,
        differences=differences,
    )


def evaluate(
    config: ProjectConfiguration,
    baseline_run_id: str,
    candidate_run_id: str,
    candidate_id: str,
    baseline_timing: TimingAnalysisResult,
    candidate_timing: TimingAnalysisResult,
    baseline_qor: QoRRecord,
    candidate_qor: QoRRecord,
    verification: VerificationResult,
    config_equivalence: ConfigurationEquivalence,
) -> PPAComparison:
    """Produce the authoritative comparison and verdict for one candidate."""
    guardrails = config.objective.guardrails
    reasons: list[str] = []

    metrics = [
        _delta("wns", baseline_timing.wns.value, candidate_timing.wns.value,
               "ns", higher_is_better=True,
               artifact=candidate_timing.report_artifact),
        _delta("tns", baseline_timing.tns.value, candidate_timing.tns.value,
               "ns", higher_is_better=True),
        _delta("cell_count", baseline_qor.cell_count, candidate_qor.cell_count,
               "cells", higher_is_better=False),
        _delta("cell_area", baseline_qor.cell_area.value, candidate_qor.cell_area.value,
               "um^2", higher_is_better=False),
    ]

    comparison = PPAComparison(
        comparison_id=f"{candidate_id}_cmp",
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        candidate_id=candidate_id,
        authoritative_stage=config.run_policy.authoritative_stage,
        configuration_equivalence=config_equivalence,
        metrics=metrics,
        equivalence_status=verification.status.value,
    )

    # -- Gate 1: comparability ---------------------------------------------
    if not config_equivalence.all_equal:
        comparison.verdict = Verdict.NON_COMPARABLE
        comparison.failure_class = FailureClass.NON_COMPARABLE
        comparison.verdict_reasons = (
            ["runs are not comparable; no metric interpreted"]
            + config_equivalence.differences
        )
        return comparison

    # -- Gate 2: formal equivalence ----------------------------------------
    if verification.status is not Status.PASS:
        comparison.verdict = Verdict.REJECTED
        if verification.status in (Status.UNKNOWN, Status.TIMEOUT):
            comparison.failure_class = FailureClass.UNPROVEN
            reasons.append(f"equivalence {verification.status.value}: never treated as PASS")
        else:
            comparison.failure_class = FailureClass.NOT_EQUIVALENT
            reasons.append(f"equivalence {verification.status.value}")
        comparison.verdict_reasons = reasons
        return comparison

    # -- Gate 3: clock preservation ----------------------------------------
    if guardrails.clocks_must_be_preserved:
        missing = set(baseline_timing.clocks) - set(candidate_timing.clocks)
        if missing:
            comparison.verdict = Verdict.REJECTED
            comparison.failure_class = FailureClass.GUARDRAIL_BREACH
            comparison.verdict_reasons = [f"clock(s) disappeared: {sorted(missing)}"]
            return comparison

    # -- Gate 4: primary objective -----------------------------------------
    wns_delta = next(m for m in metrics if m.name == "wns")
    timing_improved = wns_delta.direction == "improve"
    target_closed = (
        candidate_timing.wns.value is not None and candidate_timing.wns.value >= 0.0
    )
    if not timing_improved and not target_closed:
        comparison.verdict = Verdict.REJECTED
        comparison.failure_class = FailureClass.QOR_REGRESSION
        comparison.verdict_reasons = [
            f"wns did not improve (delta {wns_delta.absolute_delta} ns)"
        ]
        return comparison

    # -- Gate 5: guardrails ------------------------------------------------
    area_delta = next(m for m in metrics if m.name == "cell_area")
    cell_delta = next(m for m in metrics if m.name == "cell_count")
    guardrail_results = [
        GuardrailResult(
            name="area_regression",
            limit=guardrails.max_area_regression_pct,
            observed=area_delta.relative_delta_pct,
            passed=(area_delta.relative_delta_pct or 0.0) <= guardrails.max_area_regression_pct,
            detail=f"cell_area delta {area_delta.relative_delta_pct}%",
        ),
        GuardrailResult(
            name="cell_count_regression",
            limit=guardrails.max_cell_count_regression_pct,
            observed=cell_delta.relative_delta_pct,
            passed=(cell_delta.relative_delta_pct or 0.0) <= guardrails.max_cell_count_regression_pct,
            detail=f"cell_count delta {cell_delta.relative_delta_pct}%",
        ),
    ]
    comparison.guardrail_results = guardrail_results
    breached = [g for g in guardrail_results if not g.passed]
    if breached:
        comparison.verdict = Verdict.REJECTED
        comparison.failure_class = FailureClass.GUARDRAIL_BREACH
        comparison.verdict_reasons = [f"{g.name}: {g.detail} over limit {g.limit}%" for g in breached]
        return comparison

    # -- Accept ------------------------------------------------------------
    comparison.verdict = Verdict.ACCEPTED
    comparison.failure_class = FailureClass.NONE
    comparison.verdict_reasons = [
        f"equivalence PASS; wns {wns_delta.absolute_delta:+} ns; "
        f"area {area_delta.relative_delta_pct:+}% within {guardrails.max_area_regression_pct}%"
    ]
    return comparison


def screen_improved(
    baseline_wns: float | None, candidate_wns: float | None
) -> bool:
    """Cheap pre-formal gate: is the candidate worth verifying at all?

    A candidate whose post-synthesis slack is worse never consumes the expensive
    formal and physical stages.
    """
    if baseline_wns is None or candidate_wns is None:
        return False
    return candidate_wns > baseline_wns
