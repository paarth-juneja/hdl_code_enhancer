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

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.adapters import eqy as eqy_adapter
from orchestrator.adapters import opensta as sta_adapter
from orchestrator.adapters import orfs as orfs_adapter
from orchestrator.adapters import yosys as yosys_adapter
from orchestrator.adapters.base import Backend
from orchestrator.config import (
    ProjectConfiguration,
    check_clock_inventory,
    validate_inputs,
)
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
from orchestrator.schemas.common import Status, Verdict, read_json, write_json
from orchestrator.schemas.history import IterationRecord
from orchestrator.schemas.timing import CriticalPathRecord, QoRRecord, TimingAnalysisResult
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
    reference_run_id: str | None = None


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
    synth_proc = backend.execute(synth_inv)
    if not synth_proc.ok:
        raise RuntimeError(
            f"baseline synthesis failed ({synth_proc.status.value}): "
            f"{synth_proc.stderr_tail or synth_proc.stdout_tail}"
        )

    _stage_backend_hook(backend, "sta", "baseline")
    sta_dir = workspace.stage_dir("sta")
    sta_inv = sta_adapter.sta_invocation(config, synth_dir / "netlist.v", sta_dir)
    sta_proc = backend.execute(sta_inv)
    if not sta_proc.ok:
        raise RuntimeError(
            f"baseline STA failed ({sta_proc.status.value}): "
            f"{sta_proc.stderr_tail or sta_proc.stdout_tail}"
        )

    timing, paths = parse_timing(sta_dir, workspace.run_id, "synth")

    # Anchor the clock inventory on the manifest before anything is measured. A
    # baseline missing a declared clock is not a worse baseline, it is an
    # invalid one: every candidate would be compared against a timing
    # environment that never existed, and the comparison would look clean.
    clock_problems = check_clock_inventory(config, timing.clocks)
    if clock_problems:
        raise ValueError(
            "baseline clock inventory does not match the manifest:\n  "
            + "\n  ".join(clock_problems)
        )

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
    orfs_inv = orfs_adapter.orfs_invocation(config, config.rtl_files(), orfs_dir)
    orfs_proc = backend.execute(orfs_inv)
    if not orfs_proc.ok:
        raise RuntimeError(
            f"baseline ORFS failed ({orfs_proc.status.value}): "
            f"{orfs_proc.stderr_tail or orfs_proc.stdout_tail}"
        )
    orfs_qor, orfs_timing = parse_orfs_metrics(
        orfs_inv.expected_outputs["metadata"], workspace.run_id
    )
    orfs_timing.clocks = timing.clocks
    workspace.save_json("orfs", "orfs_qor.json", orfs_qor)

    printer(f"[baseline] synth wns={timing.wns} cells={qor.cell_count} area={qor.cell_area}")
    printer(f"[baseline] orfs  wns={orfs_timing.wns} area={orfs_qor.cell_area}")
    return BaselineResult(
        workspace=workspace, timing=timing, paths=mapped, qor=qor,
        settings_hash=config.settings_hash(),
        orfs_timing=orfs_timing, orfs_qor=orfs_qor,
        reference_run_id=workspace.run_id,
    )


def reuse_baseline(
    config: ProjectConfiguration, run_dir: Path, backend: Backend, printer=print
) -> BaselineResult:
    """Load a completed baseline after verifying it matches this project."""
    run_dir = run_dir.resolve()
    manifest = read_json(run_dir / "run_manifest.json")
    if manifest.get("project_id") != config.project_id:
        raise ValueError(
            f"baseline project is {manifest.get('project_id')!r}, expected {config.project_id!r}"
        )
    if manifest.get("settings_hash") != config.settings_hash():
        raise ValueError("baseline settings hash does not match the current project")

    lock = read_json(run_dir / "00_validate" / "manifest.lock.json")
    recorded_hashes = lock.get("file_hashes", {})
    current_hashes = config.input_hashes()
    mismatched_rtl = [
        path for path in config.rtl_relpaths()
        if path not in recorded_hashes or path not in current_hashes
        or recorded_hashes[path] != current_hashes[path]
    ]
    if mismatched_rtl:
        raise ValueError(
            "baseline RTL does not match the current project: "
            + ", ".join(mismatched_rtl)
        )

    timing = TimingAnalysisResult.model_validate(
        read_json(run_dir / "30_parse" / "timing_analysis.json")
    )
    paths = [
        CriticalPathRecord.model_validate(item)
        for item in read_json(run_dir / "30_parse" / "critical_paths.json")
    ]
    qor = QoRRecord.model_validate(read_json(run_dir / "30_parse" / "qor.json"))
    metadata = list((run_dir / "70_orfs").rglob("metadata.json"))
    if len(metadata) != 1:
        raise ValueError(
            f"expected one ORFS metadata.json in {run_dir}, found {len(metadata)}"
        )
    orfs_qor, orfs_timing = parse_orfs_metrics(metadata[0], manifest["run_id"])
    orfs_timing.clocks = timing.clocks

    workspace = Workspace.create(config, backend=backend.name, label="optimize")
    workspace.write_lock()
    write_json(
        workspace.root / "baseline_reference.json",
        {"baseline_run_id": manifest["run_id"], "baseline_path": run_dir.as_posix()},
    )
    printer(f"[baseline] reusing {manifest['run_id']} (settings hash verified)")
    return BaselineResult(
        workspace=workspace,
        timing=timing,
        paths=paths,
        qor=qor,
        settings_hash=config.settings_hash(),
        orfs_timing=orfs_timing,
        orfs_qor=orfs_qor,
        reference_run_id=manifest["run_id"],
    )


# ---------------------------------------------------------------------------
# Optimization loop
# ---------------------------------------------------------------------------


def optimize(
    config: ProjectConfiguration,
    backend: Backend,
    llm: LLMClient,
    max_iterations: int | None = None,
    baseline_dir: Path | None = None,
    printer=print,
) -> LoopReport:
    """Run the full loop and return a summary."""
    problems = validate_inputs(config)
    if problems:
        raise ValueError("project failed validation:\n  " + "\n  ".join(problems))

    baseline = (
        reuse_baseline(config, baseline_dir, backend, printer)
        if baseline_dir is not None
        else run_baseline(config, backend, printer)
    )
    iterations = max_iterations or config.run_policy.max_iterations

    ledger = HistoryLedger.create(
        config.project_root, config.project_id,
        experiment_id=f"exp_{baseline.workspace.run_id}",
        max_iterations=iterations,
        max_candidates=config.run_policy.max_candidates,
    )

    report = LoopReport(
        baseline_run_id=baseline.reference_run_id or baseline.workspace.run_id
    )
    machine = StateMachine(state=RunState.BUILD_REQUEST)
    seen_netlist_hashes: set[str] = set()

    for index in range(1, iterations + 1):
        machine.state = RunState.BUILD_REQUEST
        machine.reset_iteration()
        printer(f"\n[iter {index}] building request")

        record = _run_iteration(
            config, backend, llm, baseline, ledger, machine, index, printer,
            seen_netlist_hashes,
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
    seen_netlist_hashes: set[str],
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
    try:
        recommendation, raw = llm.propose(request)
    except Exception as exc:
        machine.advance("error")
        detail = [_llm_error_detail(exc)]
        ws.save_text("ai", f"error_{index}.txt", detail[0] + "\n")
        return _reject(
            record, machine, ws, index, reason="llm_proposal_failed",
            detail=detail, printer=printer, advanced=True,
        )
    ws.save_text("ai", f"response_raw_{index}.json", raw)
    machine.advance("responded")     # LLM_PROPOSE -> VALIDATE_RECOMMENDATION

    # -- validate (with one bounded repair) --------------------------------
    outcome = validate_recommendation(recommendation, request)
    record.recommendation_id = recommendation.recommendation_id
    record.transformation_type = recommendation.transformation_type
    if outcome.outcome == "repairable":
        printer(f"[iter {index}] repairing: {outcome.reasons}")
        machine.advance("repairable")           # -> LLM_REPAIR
        try:
            recommendation, raw = llm.repair(request, "; ".join(outcome.reasons))
        except Exception as exc:
            machine.advance("error")
            detail = [_llm_error_detail(exc)]
            ws.save_json("ai", f"recommendation_{index}.json", recommendation)
            ws.save_text("ai", f"error_{index}_repair.txt", detail[0] + "\n")
            return _reject(
                record, machine, ws, index, reason="llm_repair_failed",
                detail=detail, printer=printer, advanced=True,
            )
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

    # Declared order, not alphabetical. The baseline reads the manifest's
    # file_list order and Yosys reads files as given, so globbing here made the
    # candidate differ from the baseline in read order as well as in content --
    # a second variable in a comparison that is supposed to have exactly one.
    # The layout mirrors patcher.py, which writes each file_list entry into the
    # candidate tree under its basename.
    candidate_files = [cand_rtl / Path(rel).name for rel in config.rtl_relpaths()]
    missing = [p.name for p in candidate_files if not p.exists()]
    if missing:
        return _reject(record, machine, ws, index, reason="patch_incomplete",
                       detail=[f"candidate tree is missing declared RTL: {missing}"],
                       printer=printer)

    # -- screen ------------------------------------------------------------
    _stage_backend_hook(backend, "screen", candidate_id)
    if hasattr(backend, "begin_candidate"):
        backend.begin_candidate(index)
    screen_synth = ws.stage_dir("synth", candidate_id)
    synth_proc = backend.execute(
        yosys_adapter.synth_invocation(
            config,
            candidate_files,
            screen_synth,
            timeout_s=config.run_policy.timeout("screen"),
        )
    )
    if synth_proc.status is not Status.PASS:
        machine.advance("failed")
        record.stage_statuses["screen"] = synth_proc.status.value
        return _reject(
            record,
            machine,
            ws,
            index,
            reason="synthesis_failed",
            detail=[synth_proc.stderr_tail],
            printer=printer,
            advanced=True,
        )
    screen_sta = ws.stage_dir("screen", candidate_id)
    backend.execute(sta_adapter.sta_invocation(config, screen_synth / "netlist.v", screen_sta))
    screen_timing, _ = parse_timing(screen_sta, ws.run_id, "screen")
    screen_qor = parse_synth_stat(screen_synth / "synth_stat.txt", ws.run_id, "screen")
    ws.save_json("screen", "screen_qor.json", screen_qor, candidate_id=candidate_id)
    record.stage_statuses["screen"] = screen_timing.status.value

    # Different-looking RTL patches can elaborate to the exact same design
    # (for example, when only a comment or temporary wire name differs).  Do
    # not repeat whole-design EQY and a long physical run for an already-seen
    # synthesized netlist.  This check deliberately happens after STA so the
    # duplicate still retains complete cheap-screen evidence.
    netlist_hash = _sha256_file(screen_synth / "netlist.v")
    if netlist_hash in seen_netlist_hashes:
        machine.advance("regressed")
        record.measured_delta = _delta_dict(baseline, screen_timing, screen_qor)
        return _reject(
            record,
            machine,
            ws,
            index,
            reason="duplicate_netlist",
            detail=[f"synthesized netlist already evaluated: {netlist_hash}"],
            printer=printer,
            advanced=True,
        )
    seen_netlist_hashes.add(netlist_hash)

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
    orfs_inv = orfs_adapter.orfs_invocation(config, candidate_files, orfs_dir)
    orfs_proc = backend.execute(orfs_inv)
    if orfs_proc.status is not Status.PASS:
        machine.advance("failed")
        return _reject(record, machine, ws, index, reason="physical_failed",
                       detail=[orfs_proc.stderr_tail], printer=printer, advanced=True)
    cand_qor, cand_timing = parse_orfs_metrics(
        orfs_inv.expected_outputs["metadata"], ws.run_id
    )
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
        config, baseline.reference_run_id or baseline.workspace.run_id,
        ws.run_id, candidate_id,
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


def _llm_error_detail(exc: Exception) -> str:
    """Bound an external-provider error before saving it as run evidence."""
    message = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {message}"[:4000]


def _sha256_file(path: Path) -> str:
    """Return a stable content identity for a generated artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
