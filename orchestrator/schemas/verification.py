"""Formal verification records.

The word "formal" carries no information without the relation, the assumptions,
the proof scope, and an honest ``UNKNOWN``. All four are required fields here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from orchestrator.schemas.common import NebulaRecord, Provenance, Status


class EquivalenceRelation(BaseModel):
    """What "equivalent" was actually taken to mean for this proof.

    ``cycle_exact`` is the only relation the initial policy allows. A
    latency-changing transformation needs ``sequential`` with an explicit
    ``latency_mapping``, and until that mapping exists the transformation is
    forbidden rather than approximated.
    """

    kind: str = "cycle_exact"  # cycle_exact | sequential | property_set
    latency_mapping: str | None = None
    reset_assumption: str = ""
    description: str = ""


class VerificationResult(NebulaRecord):
    """Outcome of an EQY (or SymbiYosys) run.

    ``status`` may be ``UNKNOWN`` or ``TIMEOUT``. Neither is convertible to
    ``PASS`` anywhere in this package; ``policy.py`` treats both as "unproven"
    and rejects the candidate.
    """

    verification_id: str
    candidate_id: str
    method: str = "equivalence"
    tool: str = "eqy"
    tool_version: str | None = None
    status: Status = Status.NOT_RUN
    equivalence_relation: EquivalenceRelation = EquivalenceRelation()
    gold_hash: str = ""
    gate_hash: str = ""
    top: str = ""
    clocks_resets: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    blackboxes: list[str] = Field(default_factory=list)
    proof_scope: str = "whole_design"
    engine_strategy: str = ""
    runtime_s: float = 0.0
    peak_memory_mb: float | None = None
    proved_partitions: int = 0
    failed_partitions: int = 0
    unknown_partitions: int = 0
    counterexample_artifacts: list[str] = Field(default_factory=list)
    log_artifact: str | None = None
    limitations: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @property
    def is_proven_equivalent(self) -> bool:
        """True only for an outright PASS with no unknown partitions."""
        return self.status is Status.PASS and self.unknown_partitions == 0
