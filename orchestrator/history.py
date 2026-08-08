"""The experiment ledger — append-only, keeps every attempt.

Rejected and failed iterations are recorded with the same fields as accepted
ones. Two consumers depend on that completeness: the request builder, which
feeds measured failures back to the model so it does not repeat them; and any
honest results table, which must not be able to quietly drop the attempts that
did not work.

``seen_patch_hashes`` is the cycle guard. When the model proposes a change whose
normalised hash has already been tried, the loop stops rather than spending the
remaining budget re-testing the same idea.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.schemas.common import read_json, sha256_text, utc_now, write_json
from orchestrator.schemas.history import (
    IterationRecord,
    OptimizationIterationHistory,
)


def normalise_patch(diff_text: str) -> str:
    """Hash a diff by its added/removed content, ignoring whitespace and headers.

    Two diffs that make the same change with different context lines or line
    numbers collapse to the same hash, so cosmetic variation cannot disguise a
    repeat.
    """
    meaningful = []
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            meaningful.append(line[0] + "".join(line[1:].split()))
    return sha256_text("\n".join(sorted(meaningful)))


class HistoryLedger:
    """Owns ``experiments/history.json`` for one experiment."""

    def __init__(self, path: Path, history: OptimizationIterationHistory):
        self.path = path
        self.history = history

    @classmethod
    def create(
        cls, project_root: Path, project_id: str, experiment_id: str,
        max_iterations: int, max_candidates: int,
    ) -> "HistoryLedger":
        path = project_root / "experiments" / "history.json"
        history = OptimizationIterationHistory(
            experiment_id=experiment_id,
            project_id=project_id,
        )
        history.budget.max_iterations = max_iterations
        history.budget.max_candidates = max_candidates
        ledger = cls(path, history)
        ledger.flush()
        return ledger

    @classmethod
    def load(cls, path: Path) -> "HistoryLedger":
        history = OptimizationIterationHistory(**read_json(path))
        return cls(path, history)

    # -- mutation -----------------------------------------------------------

    def already_seen(self, diff_text: str) -> bool:
        return normalise_patch(diff_text) in self.history.seen_patch_hashes

    def append(self, record: IterationRecord) -> None:
        """Record one iteration and update the derived indexes."""
        record.ended_at = record.ended_at or utc_now()
        self.history.iterations.append(record)
        self.history.budget.consumed_iterations = len(self.history.iterations)
        if record.patch_hash and record.patch_hash not in self.history.seen_patch_hashes:
            self.history.seen_patch_hashes.append(record.patch_hash)
        if record.verdict.value == "ACCEPTED":
            self.history.accepted_candidate_ids.append(record.candidate_id)
            self.history.budget.consumed_candidates += 1
        self.history.updated_at = utc_now()
        self.flush()

    def stop(self, reason: str) -> None:
        self.history.stop_reason = reason
        self.history.updated_at = utc_now()
        self.flush()

    def budget_remaining(self) -> bool:
        return self.history.budget.consumed_iterations < self.history.budget.max_iterations

    def flush(self) -> None:
        write_json(self.path, self.history)
