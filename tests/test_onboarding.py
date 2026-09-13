from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator.cli import main
from orchestrator.onboarding import OnboardingError, onboard_project


def _write_fixture(root: Path) -> Path:
    rtl = root / "rtl"
    rtl.mkdir()
    (rtl / "datapath.sv").write_text(
        "module datapath(input logic clk, input logic [7:0] a, output logic [7:0] y);\n"
        "always_ff @(posedge clk) y <= a + 1'b1;\nendmodule\n",
        encoding="utf-8",
    )
    (rtl / "cdc_sync.sv").write_text(
        "module cdc_sync(input logic clk, input logic d, output logic q);\n"
        "always_ff @(posedge clk) q <= d;\nendmodule\n",
        encoding="utf-8",
    )
    (rtl / "clock_divider.sv").write_text(
        "module clock_divider(input logic clk_in, output logic clk_out);\n"
        "always_ff @(posedge clk_in) clk_out <= ~clk_out;\nendmodule\n",
        encoding="utf-8",
    )
    (rtl / "chip_top.sv").write_text(
        "module chip_top(input logic clk_a, input logic clk_b, input logic rst_n,\n"
        "input logic [7:0] a, output logic [7:0] y);\n"
        "logic q, slow;\n"
        "datapath u_dp(.clk(clk_a), .a(a), .y(y));\n"
        "cdc_sync u_sync(.clk(clk_b), .d(y[0]), .q(q));\n"
        "clock_divider u_div(.clk_in(clk_a), .clk_out(slow));\n"
        "endmodule\n",
        encoding="utf-8",
    )
    return rtl


def test_onboard_generates_ordered_reviewable_project(tmp_path: Path):
    rtl = _write_fixture(tmp_path)
    result = onboard_project(rtl, clock_period_ns=8.0)

    assert result.top_module == "chip_top"
    assert result.master_clocks == ["clk_a", "clk_b"]
    assert result.reset_ports == ["rst_n"]
    assert "rtl/chip_top.sv" in result.protected_paths
    assert "rtl/cdc_sync.sv" in result.protected_paths
    assert "rtl/clock_divider.sv" in result.protected_paths
    assert result.editable_paths == ["rtl/datapath.sv"]

    manifest = yaml.safe_load(result.manifest_path.read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in manifest["design"]["file_list"]]
    assert paths.index("rtl/datapath.sv") < paths.index("rtl/chip_top.sv")
    assert all(entry["language"] == "systemverilog" for entry in manifest["design"]["file_list"])
    assert manifest["constraints"]["clock_expectations"][0]["period_ns"] == 8.0

    sdc = result.sdc_path.read_text(encoding="utf-8")
    assert "create_clock -name clk_a -period 8" in sdc
    assert "create_clock -name clk_b -period 8" in sdc
    assert "TODO: add create_generated_clock" in sdc
    assert "Required human review" in result.report_path.read_text(encoding="utf-8")


def test_onboard_refuses_ambiguous_top_and_overwrite(tmp_path: Path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "two.v").write_text(
        "module first; endmodule\nmodule second; endmodule\n", encoding="utf-8"
    )
    with pytest.raises(OnboardingError, match="ambiguous"):
        onboard_project(rtl)

    onboard_project(rtl, top="first")
    with pytest.raises(OnboardingError, match="overwrite"):
        onboard_project(rtl, top="first")


def test_onboard_cli(tmp_path: Path, capsys):
    rtl = _write_fixture(tmp_path)
    assert main(["onboard", "--rtl", str(rtl), "--top", "chip_top"]) == 0
    output = capsys.readouterr().out
    assert "ONBOARDED: chip_top" in output
    assert (tmp_path / "nebula.project.yaml").exists()


def test_onboard_expands_vector_clock_ports(tmp_path: Path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text(
        "module top(input logic [4:0] clk_m, input logic rst_n); endmodule\n",
        encoding="utf-8",
    )

    result = onboard_project(rtl)

    assert result.master_clocks == [
        "clk_m[4]", "clk_m[3]", "clk_m[2]", "clk_m[1]", "clk_m[0]",
    ]
    sdc = result.sdc_path.read_text(encoding="utf-8")
    assert "create_clock -name {clk_m[4]}" in sdc
    assert "-group [get_clocks {clk_m[0]}]" in sdc


def test_onboard_cli_fails_when_requested_elaboration_fails(
    tmp_path: Path, monkeypatch, capsys
):
    rtl = _write_fixture(tmp_path)
    monkeypatch.setattr(
        "orchestrator.onboarding._run_elaboration",
        lambda *_args, **_kwargs: ("fail", "synthetic parser error"),
    )

    status = main([
        "onboard", "--rtl", str(rtl), "--top", "chip_top", "--run-elaboration",
    ])

    assert status == 1
    assert "RTL elaboration did not pass" in capsys.readouterr().err


def test_systemverilog_adapters_enable_sv(tmp_path: Path):
    from orchestrator.adapters.eqy import build_eqy_script
    from orchestrator.adapters.yosys import build_synth_script
    from orchestrator.config import load_project

    rtl = _write_fixture(tmp_path)
    result = onboard_project(rtl, top="chip_top")
    config = load_project(result.manifest_path)
    synth = build_synth_script(
        config, config.rtl_files(), tmp_path / "out", tmp_path / "synth.ys"
    )
    assert "read_verilog -sv" in synth

    eqy = build_eqy_script(
        config, config.rtl_files(), config.rtl_files(), tmp_path / "eqy",
        tmp_path / "equiv.eqy",
    )
    assert "read_verilog -sv" in eqy
