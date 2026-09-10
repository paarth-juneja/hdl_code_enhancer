"""End-to-end smoke test of the mock loop, plus the load-bearing safety checks.

Runs the whole thing in a temporary copy of the project so it leaves no
artifacts behind, then asserts the properties the design depends on:

* all three ASM branches are reachable (accept, QoR regression, formal fail);
* rejected candidates keep their evidence, including the EQY counterexample;
* the history ledger retains every attempt;
* a protected-region patch is refused;
* the clock inventory is checked against the manifest, not just against the
  baseline, so a baseline that lost a clock cannot normalise the loss;
* the manifest lock makes a mutated design non-comparable;
* the ASM has no path from an unproven equivalence result to acceptance.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orchestrator.adapters.base import make_backend
from orchestrator.config import check_clock_inventory, load_project
from orchestrator.llm.client import make_llm_client
from orchestrator.patcher import _Hunk, _apply_hunk, apply_patch
from orchestrator.pipeline import optimize, run_baseline
from orchestrator.schemas.ai import RTLPatch
from orchestrator.statemachine import assert_no_unproven_acceptance

ROOT = Path(__file__).resolve().parents[1]
COPY_ITEMS = ["rtl", "constraints", "tests", "nebula.project.yaml"]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    for item in COPY_ITEMS:
        src = ROOT / item
        dst = tmp_path / item
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copyfile(src, dst)
    return tmp_path


def test_three_branches_and_evidence(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    report = optimize(
        config,
        make_backend("mock"),
        make_llm_client("mock"),
        max_iterations=3,
        printer=lambda *_: None,
    )

    verdicts = {r.index: (r.verdict.value, r.failure_class.value) for r in report.iterations}
    assert verdicts[1] == ("ACCEPTED", "NONE")
    assert verdicts[2] == ("REJECTED", "QOR_REGRESSION")
    assert verdicts[3] == ("REJECTED", "NOT_EQUIVALENT")
    assert report.accepted == ["cand_0001_08c412"]

    request_files = list(sandbox.glob("runs/*/40_ai/request_1.json"))
    assert len(request_files) == 1
    import json
    request = json.loads(request_files[0].read_text())
    assert request["rtl_context"][0]["file"] == "rtl/dsp_core.v"

    # Rejected candidates keep their whole evidence tree.
    candidates = sandbox / "candidates"
    assert len(list(candidates.iterdir())) == 3

    # The formal counterexample is preserved for the non-equivalent candidate.
    vcds = list(sandbox.glob("runs/*/candidates/cand_0003_*/60_eqy/equiv/*.vcd"))
    assert vcds, "EQY counterexample VCD was not retained"


def test_history_retains_every_attempt(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    optimize(config, make_backend("mock"), make_llm_client("mock"),
             max_iterations=3, printer=lambda *_: None)
    import json

    history = json.loads((sandbox / "experiments" / "history.json").read_text())
    assert len(history["iterations"]) == 3
    # The two failures are present, not just the success.
    failure_classes = {it["failure_class"] for it in history["iterations"]}
    assert "QOR_REGRESSION" in failure_classes
    assert "NOT_EQUIVALENT" in failure_classes


def test_completed_baseline_can_be_reused(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    baseline = run_baseline(config, make_backend("mock"), printer=lambda *_: None)

    report = optimize(
        config,
        make_backend("mock"),
        make_llm_client("mock"),
        max_iterations=1,
        baseline_dir=baseline.workspace.root,
        printer=lambda *_: None,
    )

    assert report.baseline_run_id == baseline.workspace.run_id
    optimize_runs = list((sandbox / "runs").glob("*_optimize"))
    assert len(optimize_runs) == 1
    reference = (optimize_runs[0] / "baseline_reference.json").read_text()
    assert baseline.workspace.run_id in reference


def test_protected_region_patch_is_refused(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    # A patch that edits the CDC synchronizer -- a protected file.
    diff = (
        "--- a/rtl/cdc_sync.v\n"
        "+++ b/rtl/cdc_sync.v\n"
        "@@\n"
        "-            req_sync <= req_meta;\n"
        "+            req_sync <= req;\n"  # collapsing a synchronizer stage
    )
    patch = RTLPatch(patch_id="p", recommendation_id="r", base_source_hash="",
                     diff_text=diff)
    result = apply_patch(
        config, patch, "cand_bad",
        sandbox / "candidates" / "cand_bad" / "rtl",
        sandbox / "patch.log",
    )
    assert result.outcome == "protected"
    # No candidate tree may have been written.
    assert not (sandbox / "candidates" / "cand_bad" / "rtl").exists()


def test_unique_hunk_match_tolerates_tabs_changed_to_spaces():
    source = ["reg\t[7:0]\ta,b;", "assign x=a^b;"]
    hunk = _Hunk(
        file="rtl/example.v",
        old_lines=[r"reg\t[7:0] a,b;", "assign x=a^b;"],
        new_lines=["reg [7:0] a,b;", "assign x = a ^ b;"],
    )
    assert _apply_hunk(source, hunk) == [source[0], "assign x = a ^ b;"]


def test_manifest_lock_detects_mutation(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    before = config.settings_hash()
    # Mutating the SDC (a frozen input) must change the settings hash, which is
    # what makes two runs non-comparable.
    sdc = sandbox / "constraints" / "nebula.sdc"
    sdc.write_text(sdc.read_text() + "\n# tampered\n", encoding="utf-8")
    config_after = load_project(sandbox / "nebula.project.yaml")
    assert config_after.settings_hash() != before


def test_clock_inventory_is_anchored_on_the_manifest(sandbox: Path):
    config = load_project(sandbox / "nebula.project.yaml")
    declared = [e.name for e in config.constraints.clock_expectations]
    assert declared, "the fixture must declare clocks for this check to mean anything"

    # The declared set is what a correct STA run produces.
    assert check_clock_inventory(config, declared) == []

    # A clock that failed to be created is caught even though a baseline missing
    # it would otherwise look internally consistent to every candidate.
    assert check_clock_inventory(config, declared[:-1])

    # So is a clock the SDC created but the manifest never declared.
    assert check_clock_inventory(config, declared + ["clk_undeclared"])


def test_asm_has_no_unproven_acceptance():
    # Raises if anyone wires an UNKNOWN/FAIL equivalence result toward ORFS.
    assert_no_unproven_acceptance() is None
