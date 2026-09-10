"""Assemble the bounded request the model is allowed to see.

Three responsibilities, in order of importance:

1. **Bound the context.** The model receives the worst path, a window of source
   around it, the invariants, the transformation allowlist, and a summary of
   what previous attempts measured — never the repository, never whole files,
   never tool commands.
2. **Redact.** Any configured secret pattern is scrubbed before the payload can
   leave the machine.
3. **Feed back measured history.** Previous attempts are summarised as measured
   verdicts, so the model can avoid repeating a change that already failed —
   but its own earlier predictions are excluded, so it cannot reinforce guesses.
"""

from __future__ import annotations

import re
from pathlib import Path

from orchestrator.config import ProjectConfiguration
from orchestrator.schemas.ai import (
    AIOptimizationRequest,
    PreviousAttempt,
    RTLContextSlice,
)
from orchestrator.schemas.history import OptimizationIterationHistory
from orchestrator.schemas.timing import CriticalPathRecord, TimingAnalysisResult
from orchestrator.sourcemap import dominant_source

#: Lines of RTL to include on each side of the targeted region. Eight lines was
#: too narrow for real timing paths: it showed AES state-register assignments
#: while hiding the combinational round logic that feeds them. This remains a
#: bounded slice, but includes enough nearby logic to propose a grounded patch.
CONTEXT_MARGIN = 80


def _redact(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def _slice_source(
    file_path: Path,
    line_start: int,
    line_end: int,
    patterns: list[str],
    display_path: str | None = None,
) -> RTLContextSlice | None:
    if not file_path.exists():
        return None
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo = max(1, line_start - CONTEXT_MARGIN)
    hi = min(len(lines), line_end + CONTEXT_MARGIN)
    body = "\n".join(lines[lo - 1 : hi])
    return RTLContextSlice(
        file=display_path or file_path.name,
        line_start=lo,
        line_end=hi,
        text=_redact(body, patterns),
        role="critical_path_source",
    )


def _previous_attempts(history: OptimizationIterationHistory) -> list[PreviousAttempt]:
    attempts: list[PreviousAttempt] = []
    for record in history.iterations:
        if record.recommendation_id is None:
            continue
        attempts.append(
            PreviousAttempt(
                recommendation_id=record.recommendation_id,
                transformation_type=record.transformation_type or "unknown",
                patch_hash=record.patch_hash,
                verdict=record.verdict.value,
                failure_class=record.failure_class.value,
                measured_delta=record.measured_delta,
            )
        )
    return attempts


def build_request(
    config: ProjectConfiguration,
    timing: TimingAnalysisResult,
    paths: list[CriticalPathRecord],
    history: OptimizationIterationHistory,
    iteration: int,
    parent_candidate_id: str = "baseline",
) -> AIOptimizationRequest:
    """Produce the :class:`AIOptimizationRequest` for one iteration."""
    worst = paths[0] if paths else None

    rtl_context: list[RTLContextSlice] = []
    if worst is not None:
        link = dominant_source(worst)
        if link is not None and link.line_start is not None:
            source_path = config.project_root / link.file
            try:
                display_path = source_path.resolve().relative_to(
                    config.project_root.resolve()
                ).as_posix()
            except ValueError:
                display_path = Path(link.file).as_posix()
            slice_ = _slice_source(
                source_path,
                link.line_start,
                link.line_end or link.line_start,
                config.security.redact_patterns,
                display_path,
            )
            if slice_ is not None:
                rtl_context.append(slice_)

    facts: dict[str, object] = {
        "timing_summary": {
            "wns": {"value": timing.wns.value, "unit": timing.wns.unit},
            "tns": {"value": timing.tns.value, "unit": timing.tns.unit},
            "violating_endpoints": timing.violation_count,
            "unconstrained_endpoints": timing.unconstrained_endpoint_count,
        },
        "clocks": timing.clocks,
    }
    if worst is not None:
        facts["constraint_summary"] = {
            "launch_clock": worst.launch_clock,
            "capture_clock": worst.capture_clock,
            "relationship": worst.relationship,
            "logic_depth": worst.logic_depth,
        }

    return AIOptimizationRequest(
        request_id=f"req_{iteration:04d}",
        project_id=config.project_id,
        parent_candidate_id=parent_candidate_id,
        iteration=iteration,
        facts=facts,
        critical_path=worst,
        rtl_context=rtl_context,
        invariants={
            "interfaces": "unchanged",
            "latency": "unchanged",
            "reset": "unchanged",
            "clock": "unchanged",
            "cdc": "forbidden",
        },
        allowed_transformations=config.transformations.allowed,
        forbidden_changes=config.transformations.forbidden,
        change_budget={
            "max_changed_lines": config.transformations.change_budget.max_changed_lines,
            "max_changed_files": config.transformations.change_budget.max_changed_files,
        },
        previous_attempts=_previous_attempts(history),
    )
