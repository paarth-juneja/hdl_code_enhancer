"""The orchestrator ASM, in code.

This module is the executable form of the ASM chart in
``Nebula_file_workflow.md`` section 6. :class:`RunState` is the set of state
boxes; :data:`TRANSITIONS` is the set of decision boxes. Keeping the transition
table declarative means the chart and the implementation can be diffed against
each other rather than drifting apart.

The one invariant worth stating explicitly: there is no transition from an
unproven equivalence result to ``ACCEPTED``. It is absent from the table, and
:func:`assert_no_unproven_acceptance` fails the test suite if anyone adds one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orchestrator.schemas.common import FailureClass


class RunState(str, Enum):
    """State boxes. The orchestrator occupies exactly one at a time."""

    IDLE = "IDLE"
    VALIDATE = "VALIDATE"
    BASELINE_SYNTH = "BASELINE_SYNTH"
    BASELINE_STA = "BASELINE_STA"
    PARSE = "PARSE"
    MAP = "MAP"
    BUILD_REQUEST = "BUILD_REQUEST"
    LLM_PROPOSE = "LLM_PROPOSE"
    LLM_REPAIR = "LLM_REPAIR"
    VALIDATE_RECOMMENDATION = "VALIDATE_RECOMMENDATION"
    APPLY_PATCH = "APPLY_PATCH"
    SCREEN = "SCREEN"
    EQY = "EQY"
    ORFS = "ORFS"
    COMPARE = "COMPARE"
    NEXT_ITERATION = "NEXT_ITERATION"
    DONE = "DONE"
    FAILED = "FAILED"


TERMINAL_STATES = {RunState.DONE, RunState.FAILED}


@dataclass(frozen=True)
class Transition:
    """One edge of the ASM: a decision outcome and what it costs."""

    source: RunState
    outcome: str
    target: RunState
    failure_class: FailureClass = FailureClass.NONE
    preserves_evidence: bool = True
    note: str = ""


#: The decision boxes. Read this table next to section 6 of the workflow doc.
TRANSITIONS: tuple[Transition, ...] = (
    Transition(RunState.IDLE, "start", RunState.VALIDATE),

    Transition(RunState.VALIDATE, "valid", RunState.BASELINE_SYNTH),
    Transition(RunState.VALIDATE, "invalid", RunState.FAILED, FailureClass.INVALID_INPUT),

    Transition(RunState.BASELINE_SYNTH, "ok", RunState.BASELINE_STA),
    Transition(RunState.BASELINE_SYNTH, "failed", RunState.FAILED, FailureClass.SYNTHESIS_FAILED),

    Transition(RunState.BASELINE_STA, "constrained", RunState.PARSE),
    Transition(RunState.BASELINE_STA, "unconstrained", RunState.FAILED, FailureClass.INVALID_CONSTRAINTS),
    Transition(RunState.BASELINE_STA, "failed", RunState.FAILED, FailureClass.INVALID_CONSTRAINTS),

    Transition(RunState.PARSE, "ok", RunState.MAP),
    Transition(RunState.PARSE, "failed", RunState.FAILED, FailureClass.PARSER_FAILED),

    Transition(RunState.MAP, "ok", RunState.BUILD_REQUEST),

    Transition(RunState.BUILD_REQUEST, "ok", RunState.LLM_PROPOSE),

    Transition(RunState.LLM_PROPOSE, "responded", RunState.VALIDATE_RECOMMENDATION),
    Transition(RunState.LLM_PROPOSE, "error", RunState.NEXT_ITERATION, FailureClass.SCHEMA_INVALID),

    Transition(RunState.VALIDATE_RECOMMENDATION, "valid", RunState.APPLY_PATCH),
    Transition(RunState.VALIDATE_RECOMMENDATION, "abstained", RunState.NEXT_ITERATION, FailureClass.ABSTAINED),
    Transition(RunState.VALIDATE_RECOMMENDATION, "repairable", RunState.LLM_REPAIR),
    Transition(RunState.VALIDATE_RECOMMENDATION, "invalid", RunState.NEXT_ITERATION, FailureClass.SCHEMA_INVALID),
    Transition(RunState.VALIDATE_RECOMMENDATION, "ungrounded", RunState.NEXT_ITERATION, FailureClass.UNGROUNDED_CLAIM),

    Transition(RunState.LLM_REPAIR, "responded", RunState.VALIDATE_RECOMMENDATION),
    Transition(RunState.LLM_REPAIR, "error", RunState.NEXT_ITERATION, FailureClass.SCHEMA_INVALID),

    Transition(RunState.APPLY_PATCH, "applied", RunState.SCREEN),
    Transition(RunState.APPLY_PATCH, "rejected", RunState.NEXT_ITERATION, FailureClass.PATCH_REJECTED),
    Transition(RunState.APPLY_PATCH, "protected", RunState.NEXT_ITERATION, FailureClass.PROTECTED_REGION),

    Transition(RunState.SCREEN, "improved", RunState.EQY),
    Transition(RunState.SCREEN, "regressed", RunState.NEXT_ITERATION, FailureClass.QOR_REGRESSION),
    Transition(RunState.SCREEN, "failed", RunState.NEXT_ITERATION, FailureClass.SYNTHESIS_FAILED),

    Transition(RunState.EQY, "pass", RunState.ORFS),
    Transition(RunState.EQY, "fail", RunState.NEXT_ITERATION, FailureClass.NOT_EQUIVALENT,
               note="counterexample VCD retained"),
    # UNKNOWN and TIMEOUT get their own edge and it does not lead to ORFS.
    Transition(RunState.EQY, "unknown", RunState.NEXT_ITERATION, FailureClass.UNPROVEN,
               note="never relabelled as PASS"),

    Transition(RunState.ORFS, "completed", RunState.COMPARE),
    Transition(RunState.ORFS, "failed", RunState.NEXT_ITERATION, FailureClass.PHYSICAL_FAILED),

    Transition(RunState.COMPARE, "accepted", RunState.NEXT_ITERATION),
    Transition(RunState.COMPARE, "guardrail_breach", RunState.NEXT_ITERATION, FailureClass.GUARDRAIL_BREACH),
    Transition(RunState.COMPARE, "non_comparable", RunState.NEXT_ITERATION, FailureClass.NON_COMPARABLE),

    Transition(RunState.NEXT_ITERATION, "continue", RunState.BUILD_REQUEST),
    Transition(RunState.NEXT_ITERATION, "budget_exhausted", RunState.DONE),
    Transition(RunState.NEXT_ITERATION, "cycle_detected", RunState.DONE, FailureClass.CYCLE_DETECTED),
)

_INDEX: dict[tuple[RunState, str], Transition] = {
    (t.source, t.outcome): t for t in TRANSITIONS
}


@dataclass
class StateMachine:
    """Walks the ASM and records the path taken.

    The trace is written into the run manifest, so a reviewer can see the exact
    sequence of states a candidate went through rather than inferring it from
    which directories happen to exist.
    """

    state: RunState = RunState.IDLE
    trace: list[tuple[str, str, str]] = field(default_factory=list)
    last_failure: FailureClass = FailureClass.NONE

    def advance(self, outcome: str) -> RunState:
        """Take the edge labelled ``outcome`` from the current state."""
        key = (self.state, outcome)
        transition = _INDEX.get(key)
        if transition is None:
            valid = sorted(o for (s, o) in _INDEX if s is self.state)
            raise ValueError(
                f"no transition from {self.state.value} on '{outcome}'; "
                f"valid outcomes are {valid}"
            )
        self.trace.append((self.state.value, outcome, transition.target.value))
        self.state = transition.target
        if transition.failure_class is not FailureClass.NONE:
            self.last_failure = transition.failure_class
        return self.state

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_STATES

    def reset_iteration(self) -> None:
        """Clear per-iteration failure state before the next candidate."""
        self.last_failure = FailureClass.NONE


def assert_no_unproven_acceptance() -> None:
    """Structural check: nothing unproven may reach an accepting path.

    Called by the test suite. If someone later adds an edge from an unknown or
    failed equivalence result to ``ORFS`` — the only route to ``COMPARE``, and
    therefore to ``ACCEPTED`` — this raises.
    """
    for transition in TRANSITIONS:
        if transition.source is RunState.EQY and transition.outcome != "pass":
            if transition.target is not RunState.NEXT_ITERATION:
                raise AssertionError(
                    f"equivalence outcome '{transition.outcome}' must return to "
                    f"NEXT_ITERATION, not {transition.target.value}"
                )
