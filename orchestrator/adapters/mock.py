"""Mock backend — replays fixture templates instead of spawning tools.

Purpose: make the entire loop runnable before a Linux EDA environment exists,
so that the orchestrator, the parsers, the policy engine, and all three ASM
branches can be developed and demonstrated on any machine with Python.

What is *not* mocked, deliberately:

* Script generation. ``synth.ys``, ``sta.tcl``, ``equiv.eqy``, and ``config.mk``
  are written by the real adapters in both modes.
* Parsing. The fixtures are report-shaped text, so ``orchestrator/parsers/``
  runs for real. The parsers are the component most likely to need adjustment
  against genuine tool output, and mocking them would hide exactly that risk.

PORTABILITY NOTE — read before trusting a mock result
-----------------------------------------------------
The fixture templates in ``tests/fixtures/`` are a *reconstruction* of Yosys,
OpenSTA, EQY, and ORFS output. Real tools will differ in whitespace, column
headers, and wording. The intended sequence once a Linux toolchain exists:

1. Run the truth fixture through the real tools by hand.
2. Overwrite ``tests/fixtures/`` with the genuine reports.
3. Re-run in mock mode; the parsers will now fail against real formats.
4. Fix the parsers until they pass.
5. Switch to ``--backend real``.

Do step 2 early. Every day the parsers see only invented fixtures is a day of
accumulating format debt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.adapters.base import Backend, ToolInvocation
from orchestrator.runner import ProcessResult
from orchestrator.schemas.common import Status, write_text

DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


@dataclass
class MockOutcome:
    """The measurements one simulated run will report."""

    label: str
    wns: float
    tns: float
    violation_count: int
    cell_count: int
    cell_area: float
    eqy_status: str = "PASS"  # PASS | FAIL | UNKNOWN
    orfs_ok: bool = True


#: Baseline the candidates are compared against.
BASELINE_OUTCOME = MockOutcome(
    label="baseline",
    wns=-0.412,
    tns=-18.740,
    violation_count=47,
    cell_count=1180,
    cell_area=1982.4,
)

#: Scripted candidate outcomes. Chosen so that a single three-iteration run
#: exercises every branch of the ASM that a demo needs to show:
#:   1. accepted            -- timing improves, area holds, equivalence proved
#:   2. QoR regression      -- timing gets worse; rejected before formal runs
#:   3. equivalence failure -- timing improves but the design changed behaviour
DEFAULT_SCENARIO: tuple[MockOutcome, ...] = (
    MockOutcome("improves", wns=-0.186, tns=-6.210, violation_count=18,
                cell_count=1206, cell_area=2013.7, eqy_status="PASS"),
    MockOutcome("regresses", wns=-0.588, tns=-24.910, violation_count=63,
                cell_count=1174, cell_area=1970.2, eqy_status="PASS"),
    MockOutcome("not_equivalent", wns=-0.104, tns=-3.480, violation_count=9,
                cell_count=1225, cell_area=2044.8, eqy_status="FAIL"),
)


@dataclass
class MockBackend(Backend):
    """Deterministic stand-in for the EDA toolchain."""

    name: str = "mock"
    fixture_dir: Path = field(default_factory=lambda: DEFAULT_FIXTURE_DIR)
    scenario: tuple[MockOutcome, ...] = DEFAULT_SCENARIO
    _phase: str = "baseline"
    _candidate_index: int = 0

    # -- backend hook -------------------------------------------------------

    def on_stage(self, stage: str, candidate_id: str | None) -> None:
        """Track which run is being simulated.

        ``RealBackend`` inherits this as a no-op; the pipeline calls it
        unconditionally so no mock-awareness leaks into the pipeline itself.
        """
        if candidate_id in (None, "baseline"):
            self._phase = "baseline"
        else:
            self._phase = "candidate"

    def begin_candidate(self, index: int) -> None:
        """Select which scripted outcome the next candidate run reports."""
        self._candidate_index = index

    @property
    def outcome(self) -> MockOutcome:
        if self._phase == "baseline":
            return BASELINE_OUTCOME
        if not self.scenario:
            return BASELINE_OUTCOME
        return self.scenario[(self._candidate_index - 1) % len(self.scenario)]

    # -- execution ----------------------------------------------------------

    def execute(self, invocation: ToolInvocation) -> ProcessResult:
        started = time.monotonic()
        handler = {
            "yosys": self._run_yosys,
            "opensta": self._run_opensta,
            "eqy": self._run_eqy,
            "orfs": self._run_orfs,
        }.get(invocation.tool)

        if handler is None:
            return self._result(invocation, Status.ERROR, started,
                                note=f"no mock handler for tool '{invocation.tool}'")

        status = handler(invocation)
        return self._result(invocation, status, started)

    # -- per-tool simulation ------------------------------------------------

    def _run_yosys(self, invocation: ToolInvocation) -> Status:
        out = invocation.cwd
        o = self.outcome
        self._render(
            "yosys/synth_stat.txt.tmpl",
            out / "synth_stat.txt",
            {"CELL_COUNT": o.cell_count, "CELL_AREA": f"{o.cell_area:.6f}"},
        )
        self._render("yosys/netlist.v.tmpl", out / "netlist.v", {"LABEL": o.label})
        self._render("yosys/design.json.tmpl", out / "design.json", {})
        write_text(out / "yosys.log",
                   f"[mock] synthesis complete: {o.cell_count} cells, "
                   f"{o.cell_area:.2f} um^2 ({o.label})\n")
        return Status.PASS

    def _run_opensta(self, invocation: ToolInvocation) -> Status:
        out = invocation.cwd
        o = self.outcome
        # Three reported paths, worst first, spaced so ranking is testable.
        self._render(
            "opensta/timing.rpt.tmpl",
            out / "timing.rpt",
            {
                "SLACK_1": f"{o.wns:.4f}",
                "SLACK_2": f"{o.wns + 0.06:.4f}",
                "SLACK_3": f"{o.wns + 0.11:.4f}",
                "ARRIVAL_1": f"{4.0 - o.wns:.4f}",
            },
        )
        self._render(
            "opensta/wns_tns.rpt.tmpl",
            out / "wns_tns.rpt",
            {"WNS": f"{o.wns:.6f}", "TNS": f"{o.tns:.6f}"},
        )
        self._render("opensta/clocks.rpt.tmpl", out / "clocks.rpt", {})
        self._render("opensta/unconstrained.rpt.tmpl", out / "unconstrained.rpt", {})
        return Status.PASS

    def _run_eqy(self, invocation: ToolInvocation) -> Status:
        work = invocation.cwd / "equiv"
        work.mkdir(parents=True, exist_ok=True)
        status = self.outcome.eqy_status

        self._render(
            "eqy/logfile.txt.tmpl",
            work / "logfile.txt",
            {"STATUS_LINE": _EQY_STATUS_LINE[status], "STATUS": status},
        )
        # EQY signals its verdict with a marker file; mirror that exactly so the
        # parser is exercised the same way in both modes.
        for marker in ("PASS", "FAIL", "UNKNOWN"):
            (work / marker).unlink(missing_ok=True)
        write_text(work / status, "")

        if status == "FAIL":
            self._render("eqy/counterexample.vcd.tmpl", work / "counterexample.vcd", {})
        # EQY exits non-zero on a disproof; that is a completed run, not a tool
        # error, and the parser -- not the exit code -- decides the verdict.
        return Status.PASS

    def _run_orfs(self, invocation: ToolInvocation) -> Status:
        # ORFS runs with cwd set to the flow directory, so its artifacts go to
        # log_dir (the run's 70_orfs/), not cwd.
        out = invocation.log_dir
        o = self.outcome
        if not o.orfs_ok:
            write_text(out / "orfs.log", "[mock] flow aborted during detailed routing\n")
            return Status.FAIL

        # Post-route numbers are slightly worse than post-synthesis: wire delay
        # and legalisation are exactly what the screen stage cannot see.
        payload = {
            "constraints__clocks__count": 4,
            "synth__design__instance__count": o.cell_count,
            "finish__design__instance__count": int(o.cell_count * 1.04),
            "finish__design__instance__area": round(o.cell_area * 1.06, 3),
            "finish__timing__setup__ws": round(o.wns - 0.035, 4),
            "finish__timing__setup__tns": round(o.tns - 1.2, 4),
            "finish__timing__drv__setup_violation_count": o.violation_count,
            "finish__power__total": None,
            "flow__status": "ok",
        }
        # Written where the adapter declared it, so the mock and the real flow
        # agree on one path instead of two that have to be kept in step.
        write_text(
            invocation.expected_outputs["metadata"],
            json.dumps(payload, indent=2) + "\n",
        )
        write_text(out / "orfs.log", f"[mock] flow completed ({o.label})\n")
        return Status.PASS

    # -- helpers ------------------------------------------------------------

    def _render(self, fixture: str, destination: Path, values: dict[str, object]) -> None:
        """Substitute ``@@TOKEN@@`` placeholders in a fixture template."""
        source = self.fixture_dir / fixture
        if not source.exists():
            raise FileNotFoundError(
                f"mock fixture missing: {source}\n"
                "Fixtures are required by --backend mock; see tests/fixtures/README.md"
            )
        text = source.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace(f"@@{key}@@", str(value))
        write_text(destination, text)

    def _result(
        self,
        invocation: ToolInvocation,
        status: Status,
        started: float,
        note: str = "",
    ) -> ProcessResult:
        log = invocation.log_dir / f"{invocation.log_name}.stdout.log"
        write_text(log, f"[mock backend] {' '.join(invocation.command)}\n")
        err = invocation.log_dir / f"{invocation.log_name}.stderr.log"
        write_text(err, note)
        return ProcessResult(
            command=invocation.command,
            cwd=str(invocation.cwd),
            exit_code=0 if status is Status.PASS else 1,
            status=status,
            runtime_s=round(time.monotonic() - started, 3),
            stdout_path=str(log),
            stderr_path=str(err),
            notes=["mock"] + ([note] if note else []),
        )


_EQY_STATUS_LINE = {
    "PASS": "Successfully proved designs equivalent",
    "FAIL": "Failed to prove equivalence of partition dsp_core.acc_out",
    "UNKNOWN": "Unable to prove or disprove equivalence (solver returned unknown)",
}
