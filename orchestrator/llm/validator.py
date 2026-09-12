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
import re

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

    if recommendation.request_id != request.request_id:
        reasons.append(
            f"request_id must be exactly '{request.request_id}', got "
            f"'{recommendation.request_id}'"
        )

    # A patch action must carry a patch.
    if recommendation.action is ActionKind.PATCH and recommendation.patch is None:
        reasons.append("action is 'patch' but no patch object was supplied")
    elif recommendation.patch is not None:
        diff_files = re.findall(
            r"^\+\+\+ b/(.+)$", recommendation.patch.diff_text, flags=re.MULTILINE
        )
        context_files = {item.file for item in request.rtl_context if item.editable}
        if not diff_files:
            reasons.append(
                "patch.diff_text must contain a standard '+++ b/<path>' unified-diff header"
            )
        elif any(path not in context_files for path in diff_files):
            reasons.append(
                f"patch paths must exactly match an RTL context path {sorted(context_files)}; "
                f"got {diff_files}"
            )
        declared_files = set(recommendation.patch.changed_files)
        if declared_files and declared_files != set(diff_files):
            reasons.append(
                f"patch.changed_files must match its diff paths {diff_files}; "
                f"got {sorted(declared_files)}"
            )
        max_files = request.change_budget.get("max_changed_files", 1)
        if len(set(diff_files)) > max_files:
            reasons.append(
                f"patch changes {len(set(diff_files))} files, over the budget of {max_files}"
            )
        if len(set(diff_files)) > 1 and not _files_connected(
            set(diff_files), request
        ):
            reasons.append(
                "multi-file patch paths must form one connected component in the "
                "complete supplied connection map"
            )

    # Ground every cited observation in the request. A citation the request never
    # provided is a fabricated fact.
    available_ids = set()
    if request.critical_path is not None:
        available_ids.add(request.critical_path.path_id)
    ungrounded: list[str] = []
    for ref in recommendation.observation_refs:
        if ref not in available_ids:
            ungrounded.append(
                f"observation_ref '{ref}' was not supplied in the request; "
                f"use exactly one of {sorted(available_ids)}"
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

    reasons.extend(ungrounded)
    if reasons:
        # A structural problem is repairable once; after that it is invalid.
        if not already_repaired:
            return ValidationOutcome("repairable", reasons)
        return ValidationOutcome("ungrounded" if ungrounded else "invalid", reasons)

    return ValidationOutcome("valid")


def _files_connected(files: set[str], request: AIOptimizationRequest) -> bool:
    """True when complete hierarchy edges connect every proposed patch file."""
    graph: dict[str, set[str]] = {file: set() for file in files}
    for edge in request.connection_map:
        if not edge.complete:
            continue
        if edge.parent_file in files and edge.child_file in files:
            graph[edge.parent_file].add(edge.child_file)
            graph[edge.child_file].add(edge.parent_file)
    if not graph:
        return False
    pending = [next(iter(files))]
    visited: set[str] = set()
    while pending:
        file = pending.pop()
        if file in visited:
            continue
        visited.add(file)
        pending.extend(graph[file] - visited)
    return visited == files
