"""Classify an EQY run into a :class:`VerificationResult`.

The single rule this parser enforces: ``UNKNOWN`` and ``TIMEOUT`` are distinct
terminal outcomes and neither is ever mapped to ``PASS``. EQY signals its result
both through a marker file in the work directory and through the log; both are
consulted, and a disagreement between them degrades to ``UNKNOWN`` rather than
optimistically picking the better one.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.runner import ProcessResult
from orchestrator.schemas.common import Provenance, Status, sha256_file
from orchestrator.schemas.verification import EquivalenceRelation, VerificationResult

_PASS_TOKENS = ("successfully proved", "designs are equivalent", "equivalence successfully proven")
_FAIL_TOKENS = ("failed to prove", "not equivalent", "found a mismatch", "disproved")
_UNKNOWN_TOKENS = ("unknown", "inconclusive", "gave up", "reached depth limit")


def _status_from_log(text: str) -> Status:
    lowered = text.lower()
    if any(tok in lowered for tok in _FAIL_TOKENS):
        return Status.FAIL
    if any(tok in lowered for tok in _UNKNOWN_TOKENS):
        return Status.UNKNOWN
    if any(tok in lowered for tok in _PASS_TOKENS):
        return Status.PASS
    return Status.UNKNOWN


def _status_from_markers(work_dir: Path) -> Status | None:
    for marker, status in (
        ("FAIL", Status.FAIL),
        ("UNKNOWN", Status.UNKNOWN),
        ("PASS", Status.PASS),
    ):
        if (work_dir / marker).exists():
            return status
    return None


def parse_equivalence(
    eqy_dir: Path,
    candidate_id: str,
    relation: EquivalenceRelation,
    gold_files: list[Path],
    gate_files: list[Path],
    process: ProcessResult | None = None,
) -> VerificationResult:
    """Combine marker file, log text, and process status into one verdict."""
    work_dir = eqy_dir / "equiv"
    log_path = work_dir / "logfile.txt"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""

    limitations: list[str] = []

    # A timeout at the process level overrides everything: the proof did not
    # finish, so no marker it may have left is trustworthy.
    if process is not None and process.status is Status.TIMEOUT:
        status = Status.TIMEOUT
        limitations.append("solver exceeded the configured timeout")
    else:
        marker_status = _status_from_markers(work_dir)
        log_status = _status_from_log(log_text) if log_text else None
        if marker_status is None and log_status is None:
            status = Status.ERROR
            limitations.append("no marker file and no readable log; run did not complete")
        elif marker_status is not None and log_status is not None and marker_status != log_status:
            # Disagreement is never resolved in favour of PASS.
            status = Status.UNKNOWN
            limitations.append(
                f"marker ({marker_status.value}) and log ({log_status.value}) disagree; "
                "treated as UNKNOWN"
            )
        else:
            status = marker_status or log_status or Status.UNKNOWN

    counterexamples = [p.as_posix() for p in work_dir.glob("*.vcd")] if work_dir.exists() else []

    return VerificationResult(
        verification_id=f"{candidate_id}_eqy",
        candidate_id=candidate_id,
        tool="eqy",
        status=status,
        equivalence_relation=relation,
        gold_hash=sha256_file(gold_files[0]) if gold_files and gold_files[0].exists() else "",
        gate_hash=sha256_file(gate_files[0]) if gate_files and gate_files[0].exists() else "",
        failed_partitions=1 if status is Status.FAIL else 0,
        unknown_partitions=1 if status in (Status.UNKNOWN, Status.TIMEOUT) else 0,
        counterexample_artifacts=counterexamples,
        log_artifact=log_path.as_posix() if log_path.exists() else None,
        limitations=limitations,
        provenance=Provenance(
            produced_by="parsers.eqy_status",
            artifact_paths=[log_path.as_posix()] if log_path.exists() else [],
        ),
    )
