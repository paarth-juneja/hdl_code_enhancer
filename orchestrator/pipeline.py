"""The optimization loop — the ASM of section 6 executed end to end.

``run_baseline`` produces the immutable reference. ``optimize`` then walks the
loop: build a bounded request, ask the model for one patch, validate it, apply
it to an isolated candidate, screen it cheaply, prove equivalence, run the
authoritative physical stage, compare, and record — accepting only when every
gate holds.

Every stage delegates its real work to a module already written: adapters
generate the scripts, the backend executes them, the parsers type the output,
the policy engine decides. This file only sequences them and drives the state
machine so the trace matches the chart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.adapters import eqy as eqy_adapter
from orchestrator.adapters import opensta as sta_adapter
from orchestrator.adapters import orfs as orfs_adapter
from orchestrator.adapters import yosys as yosys_adapter
from orchestrator.adapters.base import Backend
from orchestrator.config import ProjectConfiguration, validate_inputs
from orchestrator.history import HistoryLedger
from orchestrator.llm.client import LLMClient
from orchestrator.llm.request_builder import build_request
from orchestrator.llm.validator import validate_recommendation
from orchestrator.parsers.eqy_status import parse_equivalence
from orchestrator.parsers.opensta_timing import parse_timing
from orchestrator.parsers.orfs_metrics import parse_orfs_metrics
from orchestrator.parsers.yosys_json_src import build_source_index
from orchestrator.parsers.yosys_stat import parse_synth_stat
from orchestrator import policy as policy_engine
from orchestrator.patcher import apply_patch
from orchestrator.schemas.common import Status, Verdict, write_json
from orchestrator.schemas.history import IterationRecord
from orchestrator.schemas.verification import EquivalenceRelation
from orchestrator.sourcemap import build_source_map
from orchestrator.statemachine import RunState, StateMachine
from orchestrator.workspace import Workspace


@dataclass
class BaselineResult:
    """Everything the loop needs to compare candidates against.

    ``timing``/``qor`` are the synthesis-stage view, used for request building and
    the cheap screen gate. ``orfs_timing``/``orfs_qor`` are the post-route view,
    which is what the acceptance policy compares a candidate against — comparing a
    candidate's routed numbers to a baseline's pre-route numbers would be the
    stage-mixing error the methodology forbids.
    """

    workspace: Workspace
    timing: object
    paths: list
    qor: object
    settings_hash: str
    orfs_timing: object = None
    orfs_qor: object = None


@dataclass
class LoopReport:
    """Summary of a full optimize run."""

    baseline_run_id: str
    iterations: list[IterationRecord] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    stop_reason: str = ""


def _stage_backend_hook(backend: Backend, stage: str, candidate_id: str | None) -> None:
    """Let a mock backend know which run it is simulating; real backends ignore."""
    hook = getattr(backend, "on_stage", None)
    if callable(hook):
        hook(stage, candidate_id)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def run_baseline(
    config: ProjectConfiguration, backend: Backend, printer=print
) -> BaselineResult:
    """Synthesise, analyse, parse, and map the immutable baseline."""
    workspace = Workspace.create(config, backend=backend.name, label="baseline")
    workspace.write_lock()
    printer(f"[baseline] run {workspace.run_id}")

    _stage_backend_hook(backend, "synth", "baseline")
    synth_dir = workspace.stage_dir("synth")
    synth_inv = yosys_adapter.synth_invocation(config, config.rtl_files(), synth_dir)
    backend.execute(synth_inv)

    _stage_backend_hook(backend, "sta", "baseline")
    sta_dir = workspace.stage_dir("sta")
    sta_inv = sta_adapter.sta_invocation(config, synth_dir / "netlist.v", sta_dir)
    backend.execute(sta_inv)

    timing, paths = parse_timing(sta_dir, workspace.run_id, "synth")
    qor = parse_synth_stat(synth_dir / "synth_stat.txt", workspace.run_id)
    workspace.save_json("parse", "timing_analysis.json", timing)
    workspace.save_json("parse", "qor.json", qor)

    index = build_source_index(synth_dir / "design.json")
    mapped = build_source_map(paths, index, config.project_root / config.design.rtl_dir,
                              workspace.stage_dir("map") / "source_map.json")
    workspace.save_json("parse", "critical_paths.json",
                        [p.model_dump(mode="json") for p in mapped])

    # Authoritative physical baseline, so candidates are compared post-route to
    # post-route. The mock returns the same baseline numbers regardless of phase.
    _stage_backend_hook(backend, "orfs", "baseline")
    orfs_dir = workspace.stage_dir("orfs")
    backend.execute(orfs_adapter.orfs_invocation(config, config.rtl_files(), orfs_dir))
    orfs_qor, orfs_timing = parse_orfs_metrics(orfs_dir / "metadata-base.json", workspace.run_id)
    orfs_timing.clocks = timing.clocks
    workspace.save_json("orfs", "orfs_qor.json", orfs_qor)

    printer(f"[baseline] synth wns={timing.wns} cells={qor.cell_count} area={qor.cell_area}")
    printer(f"[baseline] orfs  wns={orfs_timing.wns} area={orfs_qor.cell_area}")
    return BaselineResult(
        workspace=workspace, timing=timing, paths=mapped, qor=qor,
        settings_hash=config.settings_hash(),
        orfs_timing=orfs_timing, orfs_qor=orfs_qor,
    )


# ---------------------------------------------------------------------------
# Optimization loop
# ---------------------------------------------------------------------------


def optimize(
    config: ProjectConfiguration,
    backend: Backend,
    llm: LLMClient,
    max_iterations: int | None = None,
    printer=print,
) -> LoopReport:
    """Run the full loop and return a summary."""
    problems = validate_inputs(config)
    if problems:
        raise ValueError("project failed validation:\n  " + "\n  ".join(problems))

    baseline = run_baseline(config, backend, printer)
    iterations = max_iterations or config.run_policy.max_iterations

    ledger = HistoryLedger.create(
        config.project_root, config.project_id,
        experiment_id=f"exp_{baseline.workspace.run_id}",
        max_iterations=iterations,
        max_candidates=config.run_policy.max_candidates,
    )

    report = LoopReport(baseline_run_id=baseline.workspace.run_id)
    machine = StateMachine(state=RunState.BUILD_REQUEST)

    for index in range(1, iterations + 1):
        machine.state = RunState.BUILD_REQUEST
        machine.reset_iteration()
        printer(f"\n[iter {index}] building request")

        record = _run_iteration(
            config, backend, llm, baseline, ledger, machine, index, printer
        )
        report.iterations.append(record)
        ledger.append(record)

        if record.verdict is Verdict.ACCEPTED:
            report.accepted.append(record.candidate_id)

        if not ledger.budget_remaining():
            break

    report.stop_reason = ledger.history.stop_reason or "iteration budget reached"
    ledger.stop(report.stop_reason)
    _write_report(baseline.workspace, report)
    printer(f"\n[done] {report.stop_reason}; accepted={report.accepted}")
    return report


def _run_iteration(
    config: ProjectConfiguration,
    backend: Backend,
    llm: LLMClient,
    baseline: BaselineResult,
    ledger: HistoryLedger,
    machine: StateMachine,
    index: int,
    printer,
) -> IterationRecord:
    """One trip around the ASM. Returns the iteration record whatever happened."""
    ws = baseline.workspace
    record = IterationRecord(
        index=index, candidate_id=f"pending_{index:04d}",
        parent_candidate_id="baseline",
    )

    # -- build request + propose -------------------------------------------
    request = build_request(config, baseline.timing, baseline.paths,
                            ledger.history, index)
    ws.save_json("ai", f"request_{index}.json", request)

    machine.advance("ok")            # BUILD_REQUEST -> LLM_PROPOSE
    recommendation, raw = llm.propose(request)
    ws.save_text("ai", f"response_raw_{index}.json", raw)
    machine.advance("responded")     # LLM_PROPOSE -> VALIDATE_RECOMMENDATION

    # -- validate (with one bounded repair) --------------------------------
    outcome = validate_recommendation(recommendation, request)
    if outcome.outcome == "repairable":
        printer(f"[iter {index}] repairing: {outcome.reasons}")
        machine.advance("repairable")           # -> LLM_REPAIR
        recommendation, raw = llm.repair(request, "; ".join(outcome.reasons))
        ws.save_text("ai", f"response_raw_{index}_repair.json", raw)
        machine.advance("responded")            # -> VALIDATE_RECOMMENDATION
        outcome = validate_recommendation(recommendation, request, already_repaired=True)

    ws.save_json("ai", f"recommendation_{index}.json", recommendation)
    record.recommendation_id = recommendation.recommendation_id
    record.transformation_type = recommendation.transformation_type

    if outcome.outcome != "valid":
        machine.advance(outcome.outcome)        # abstained | invalid | ungrounded
        return _reject(record, machine, ws, index,
                       reason=outcome.outcome, detail=outcome.reasons, printer=printer)

    machine.advance("valid")                    # -> APPLY_PATCH

    # -- cycle detection ---------------------------------------------------
    patch = recommendation.patch
    from orchestrator.history import normalise_patch
    record.patch_hash = normalise_patch(patch.diff_text)
    if ledger.already_seen(patch.diff_text):
        machine.state = RunState.NEXT_ITERATION
        ledger.stop("cycle detected: model repeated a prior patch")
        return _reject(record, machine, ws, index, reason="cycle_detected",
                       detail=["patch already tried"], printer=printer)

    # -- apply patch -------------------------------------------------------
    candidate_id = ws.next_candidate_id(index, record.patch_hash)
    record.candidate_id = candidate_id
    record.patch_id = patch.patch_id
    cand_rtl = ws.candidate_rtl_dir(candidate_id)
    patch_log = ws.stage_dir("patch", candidate_id) / "patch_apply.log"
    result = apply_patch(config, patch, candidate_id, cand_rtl, patch_log)
    ws.save_json("patch", "rtl_patch.json", patch, candidate_id=candidate_id)

    if result.outcome != "applied":
        machine.advance("protected" if result.outcome == "protected" else "rejected")
        return _reject(record, machine, ws, index, reason=result.outcome,
                       detail=result.reasons, printer=printer)

    machine.advance("applied")                  # -> SCREEN
    printer(f"[iter {index}] {candidate_id}: {recommendation.transformation_type} applied")

    candidate_files = sorted(cand_rtl.glob("*.v"))

    # -- screen ------------------------------------------------------------
    _stage_backend_hook(backend, "screen", candidate_id)
    if hasattr(backend, "begin_candidate"):
        backend.begin_candidate(index)
    screen_synth = ws.stage_dir("synth", candidate_id)
    backend.execute(yosys_adapter.synth_invocation(config, candidate_files, screen_synth,
                                                    timeout_s=config.run_policy.timeout("screen")))
    screen_sta = ws.stage_dir("screen", candidate_id)
    backend.execute(sta_adapter.sta_invocation(config, screen_synth / "netlist.v", screen_sta))
    screen_timing, _ = parse_timing(screen_sta, ws.run_id, "screen")
    screen_qor = parse_synth_stat(screen_synth / "synth_stat.txt", ws.run_id, "screen")
    ws.save_json("screen", "screen_qor.json", screen_qor, candidate_id=candidate_id)
    record.stage_statuses["screen"] = screen_timing.status.value

    if not policy_engine.screen_improved(baseline.timing.wns.value, screen_timing.wns.value):
        machine.advance("regressed")
        printer(f"[iter {index}] screen: wns {screen_timing.wns} did not beat "
                f"baseline {baseline.timing.wns}")
        record.measured_delta = _delta_dict(baseline, screen_timing, screen_qor)
        return _reject(record, machine, ws, index, reason="qor_regression",
                       detail=["screen timing regressed"], printer=printer, advanced=True)

    machine.advance("improved")                 # -> EQY

    # -- formal equivalence ------------------------------------------------
    _stage_backend_hook(backend, "eqy", candidate_id)
    eqy_dir = ws.stage_dir("eqy", candidate_id)
    relation = EquivalenceRelation(
        kind=config.equivalence.relation,
        reset_assumption=config.equivalence.reset_assumption,
    )
    eqy_inv = eqy_adapter.eqy_invocation(config, config.rtl_files(), candidate_files, eqy_dir)
    eqy_proc = backend.execute(eqy_inv)
    verification = parse_equivalence(eqy_dir, candidate_id, relation,
                                     config.rtl_files(), candidate_files, eqy_proc)
    ws.save_json("eqy", "verification_result.json", verification, candidate_id=candidate_id)
    record.verification_id = verification.verification_id
    record.stage_statuses["eqy"] = verification.status.value

    if verification.status is not Status.PASS:
        edge = "fail" if verification.status is Status.FAIL else "unknown"
        machine.advance(edge)
        printer(f"[iter {index}] equivalence {verification.status.value} -> rejected")
        record.measured_delta = _delta_dict(baseline, screen_timing, screen_qor)
        return _reject(record, machine, ws, index,
                       reason="not_equivalent" if edge == "fail" else "unproven",
                       detail=verification.limitations, printer=printer, advanced=True)

    machine.advance("pass")                     # -> ORFS

    # -- authoritative physical run ----------------------------------------
    _stage_backend_hook(backend, "orfs", candidate_id)
    orfs_dir = ws.stage_dir("orfs", candidate_id)
    orfs_proc = backend.execute(orfs_adapter.orfs_invocation(config, candidate_files, orfs_dir))
    if orfs_proc.status is not Status.PASS:
        machine.advance("failed")
        return _reject(record, machine, ws, index, reason="physical_failed",
                       detail=[orfs_proc.stderr_tail], printer=printer, advanced=True)
    cand_qor, cand_timing = parse_orfs_metrics(orfs_dir / "metadata-base.json", ws.run_id)
    # Clock inventory is verified by name at STA, where names exist; ORFS metadata
    # only reports a count. Carry the screen-stage clock names into the
    # authoritative timing so the preservation check compares like with like.
    cand_timing.clocks = screen_timing.clocks
    machine.advance("completed")                # -> COMPARE

    # -- compare + decide --------------------------------------------------
    config_equiv = policy_engine.check_configuration_equivalence(
        baseline.settings_hash, config.settings_hash(),
        baseline.timing.clocks, cand_timing.clocks,
    )
    comparison = policy_engine.evaluate(
        config, baseline.workspace.run_id, ws.run_id, candidate_id,
        baseline.orfs_timing, cand_timing, baseline.orfs_qor, cand_qor,
        verification, config_equiv,
    )
    ws.save_json("compare", "ppa_comparison.json", comparison, candidate_id=candidate_id)
    ws.save_json("compare", "verdict.json",
                 {"verdict": comparison.verdict.value,
                  "reasons": comparison.verdict_reasons}, candidate_id=candidate_id)

    record.comparison_id = comparison.comparison_id
    record.verdict = comparison.verdict
    record.failure_class = comparison.failure_class
    record.measured_delta = {m.name: m.absolute_delta for m in comparison.metrics
                             if m.absolute_delta is not None}
    record.run_dir = str(ws.stage_dir("compare", candidate_id).parent)

    edge = {
        Verdict.ACCEPTED: "accepted",
        Verdict.NON_COMPARABLE: "non_comparable",
    }.get(comparison.verdict, "guardrail_breach")
    machine.advance(edge)                        # COMPARE -> NEXT_ITERATION

    printer(f"[iter {index}] VERDICT {comparison.verdict.value}: {comparison.verdict_reasons}")
    return record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delta_dict(baseline: BaselineResult, timing, qor) -> dict[str, float]:
    out: dict[str, float] = {}
    if baseline.timing.wns.value is not None and timing.wns.value is not None:
        out["wns"] = round(timing.wns.value - baseline.timing.wns.value, 6)
    if baseline.qor.cell_area.value is not None and qor.cell_area.value is not None:
        out["cell_area"] = round(qor.cell_area.value - baseline.qor.cell_area.value, 6)
    return out


def _reject(record, machine, ws, index, reason, detail, printer, advanced=False):
    """Finalise a rejected iteration and route back to NEXT_ITERATION."""
    from orchestrator.schemas.common import FailureClass
    record.verdict = Verdict.REJECTED
    record.failure_class = machine.last_failure or FailureClass.NONE
    if not advanced and machine.state is not RunState.NEXT_ITERATION:
        # Ensure we are parked at NEXT_ITERATION for the next loop pass.
        machine.state = RunState.NEXT_ITERATION
    printer(f"[iter {index}] rejected ({reason}): {detail}")
    return record


def _write_report(workspace: Workspace, report: LoopReport) -> None:
    payload = {
        "baseline_run_id": report.baseline_run_id,
        "accepted": report.accepted,
        "stop_reason": report.stop_reason,
        "iterations": [
            {
                "index": r.index,
                "candidate_id": r.candidate_id,
                "transformation": r.transformation_type,
                "verdict": r.verdict.value,
                "failure_class": r.failure_class.value,
                "measured_delta": r.measured_delta,
                "stage_statuses": r.stage_statuses,
            }
            for r in report.iterations
        ],
    }
    write_json(workspace.root / "loop_report.json", payload)
