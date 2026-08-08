"""Decide whether a model recommendation is admissible.

This runs *before* any patch touches the filesystem. It is the software half of
the trust boundary; :mod:`orchestrator.patcher` is the other half, checking the
diff itself. The checks here concern the recommendation object:

* the response is well-formed (guaranteed already by pydantic, re-asserted here);
* every ``observation_refs`` entry cites a fact the request actually supplied —
  a model that invents a path id is hallucinating and is rejected;
* the ``transformation_type`` is in the allowlist;
* an explicit ``abstain`` is accepted as a valid, non-failing outcome.

The outcome tells the state machine which edge to take.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.schemas.ai import ActionKind, AIOptimizationRequest, AIRecommendation


@dataclass
class ValidationOutcome:
    """Result of validating one recommendation.

    ``outcome`` is one of the decision-box labels in
    :data:`orchestrator.statemachine.TRANSITIONS` for
    ``VALIDATE_RECOMMENDATION``: ``valid``, ``abstained``, ``repairable``,
    ``invalid``, or ``ungrounded``.
    """

    outcome: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.outcome == "valid"


def validate_recommendation(
    recommendation: AIRecommendation,
    request: AIOptimizationRequest,
    already_repaired: bool = False,
) -> ValidationOutcome:
    """Classify a recommendation against the request that produced it."""
    # An abstention is a legitimate answer, not a failure.
    if recommendation.action is ActionKind.ABSTAIN:
        return ValidationOutcome(
            "abstained",
            [recommendation.abstention_reason or "model abstained without stated reason"],
        )

    reasons: list[str] = []

    # A patch action must carry a patch.
    if recommendation.action is ActionKind.PATCH and recommendation.patch is None:
        reasons.append("action is 'patch' but no patch object was supplied")

    # Ground every cited observation in the request. A citation the request never
    # provided is a fabricated fact.
    available_ids = set()
    if request.critical_path is not None:
        available_ids.add(request.critical_path.path_id)
    for ref in recommendation.observation_refs:
        if ref not in available_ids:
            return ValidationOutcome(
                "ungrounded",
                [f"observation_ref '{ref}' was not supplied in the request"],
            )

    # Transformation must be permitted.
    if recommendation.transformation_type not in request.allowed_transformations:
        reasons.append(
            f"transformation '{recommendation.transformation_type}' is not in the "
            f"allowlist {request.allowed_transformations}"
        )

    # Declared change size must respect the budget (the diff itself is re-checked
    # by the patcher, but catching it here saves a filesystem write).
    if recommendation.patch is not None:
        max_lines = request.change_budget.get("max_changed_lines", 10_000)
        if recommendation.patch.changed_line_count > max_lines * 2:
            reasons.append(
                f"declared change is {recommendation.patch.changed_line_count} lines, "
                f"far over the budget of {max_lines}"
            )

    if reasons:
        # A structural problem is repairable once; after that it is invalid.
        return ValidationOutcome("invalid" if already_repaired else "repairable", reasons)

    return ValidationOutcome("valid")
