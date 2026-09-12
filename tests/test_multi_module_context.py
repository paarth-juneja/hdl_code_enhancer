"""Regression tests for bounded multi-module model context."""

from __future__ import annotations

from pathlib import Path

from orchestrator.config import load_project
from orchestrator.llm.request_builder import build_request
from orchestrator.llm.validator import validate_recommendation
from orchestrator.patcher import apply_patch
from orchestrator.rtl_hierarchy import build_rtl_hierarchy
from orchestrator.schemas.ai import (
    AIOptimizationRequest,
    AIRecommendation,
    ActionKind,
    ModuleConnection,
    PortConnection,
    RTLContextSlice,
    RTLPatch,
)
from orchestrator.schemas.common import Quantity
from orchestrator.schemas.history import OptimizationIterationHistory
from orchestrator.schemas.timing import CriticalPathRecord, SourceLink, TimingAnalysisResult

ROOT = Path(__file__).resolve().parents[1]


def _path(file: str, line: int) -> CriticalPathRecord:
    link = SourceLink(
        file=file,
        line_start=line,
        line_end=line,
        netlist_object="u_dsp/acc_out_reg",
        confidence=0.95,
        method="src_attribute",
    )
    return CriticalPathRecord(
        path_id="path_1",
        analysis_id="analysis_1",
        rank=1,
        slack=Quantity(value=-0.1, unit="ns"),
        endpoint_source=link,
        mapping_status="endpoints_only",
    )


def test_request_selects_critical_module_and_connected_parent():
    config = load_project(ROOT / "nebula.project.yaml")
    path = _path((ROOT / "rtl/dsp_core.v").as_posix(), 48)
    timing = TimingAnalysisResult(
        analysis_id="analysis_1",
        run_id="run_1",
        stage="synth",
        corner="typical",
    )
    request = build_request(
        config,
        timing,
        [path],
        OptimizationIterationHistory(
            experiment_id="exp_1", project_id=config.project_id
        ),
        iteration=1,
    )

    contexts = {item.module: item for item in request.rtl_context}
    assert contexts["dsp_core"].file == "rtl/dsp_core.v"
    assert contexts["dsp_core"].editable is True
    assert contexts["nebula_top"].editable is False
    edge = next(
        item for item in request.connection_map
        if item.parent_module == "nebula_top" and item.child_module == "dsp_core"
    )
    assert edge.complete is True
    assert {port.port for port in edge.ports} >= {"clk", "acc_out", "out_valid"}
    assert next(port for port in edge.ports if port.port == "acc_out").direction == (
        "child_to_parent"
    )


def test_hierarchy_traverses_real_aes_named_instances():
    config = load_project(ROOT / "benchmarks/aes/nebula.project.yaml")
    hierarchy = build_rtl_hierarchy(config)
    edge = next(
        item for item in hierarchy.connections
        if item.parent_module == "aes_key_expand_128"
        and item.instance == "u0"
        and item.child_module == "aes_sbox"
    )
    assert edge.complete is True
    assert {(port.port, port.signal) for port in edge.ports} == {
        ("a", "tmp_w[23:16]"),
        ("d", "subword[31:24]"),
    }


def test_missing_named_port_is_reported_not_guessed(tmp_path: Path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "constraints").mkdir()
    (tmp_path / "rtl/design.v").write_text(
        "module child(input wire a, output wire y); assign y = a; endmodule\n"
        "module top(input wire a, output wire y); child u0(.a(a), .y()); endmodule\n"
    )
    (tmp_path / "constraints/test.sdc").write_text("# test\n")
    (tmp_path / "nebula.project.yaml").write_text(
        "project_id: missing_port\n"
        "design:\n"
        "  top_module: top\n"
        "  file_list:\n"
        "    - path: rtl/design.v\n"
        "constraints:\n"
        "  sdc_file: constraints/test.sdc\n"
        "platform:\n"
        "  liberty: missing.lib\n"
    )
    hierarchy = build_rtl_hierarchy(load_project(tmp_path / "nebula.project.yaml"))
    assert len(hierarchy.connections) == 1
    assert hierarchy.connections[0].complete is False
    assert hierarchy.connections[0].unconnected_ports == ["y"]


def _multi_file_request(complete: bool = True) -> AIOptimizationRequest:
    return AIOptimizationRequest(
        request_id="req_0001",
        project_id="example",
        parent_candidate_id="baseline",
        iteration=1,
        critical_path=_path("rtl/child.v", 3),
        rtl_context=[
            RTLContextSlice(
                file="rtl/parent.v", line_start=1, line_end=5,
                text="module parent;", module="parent", editable=True,
            ),
            RTLContextSlice(
                file="rtl/child.v", line_start=1, line_end=5,
                text="module child;", module="child", editable=True,
            ),
        ],
        connection_map=[ModuleConnection(
            parent_module="parent",
            parent_file="rtl/parent.v",
            child_module="child",
            child_file="rtl/child.v",
            instance="u_child",
            line=3,
            ports=[PortConnection(
                port="data", signal="data", direction="parent_to_child"
            )],
            complete=complete,
        )],
        allowed_transformations=["common_subexpression_extraction"],
        change_budget={"max_changed_lines": 20, "max_changed_files": 2},
    )


def _multi_file_recommendation() -> AIRecommendation:
    diff = (
        "--- a/rtl/parent.v\n+++ b/rtl/parent.v\n@@\n-old_parent\n+new_parent\n"
        "--- a/rtl/child.v\n+++ b/rtl/child.v\n@@\n-old_child\n+new_child\n"
    )
    return AIRecommendation(
        recommendation_id="rec_0001",
        request_id="req_0001",
        transformation_type="common_subexpression_extraction",
        action=ActionKind.PATCH,
        observation_refs=["path_1"],
        patch=RTLPatch(
            patch_id="patch_1",
            recommendation_id="rec_0001",
            base_source_hash="",
            diff_text=diff,
            changed_files=["rtl/parent.v", "rtl/child.v"],
            changed_line_count=4,
        ),
    )


def test_two_file_patch_requires_complete_connection_map():
    recommendation = _multi_file_recommendation()
    assert validate_recommendation(
        recommendation, _multi_file_request(complete=True)
    ).outcome == "valid"
    rejected = validate_recommendation(
        recommendation, _multi_file_request(complete=False), already_repaired=True
    )
    assert rejected.outcome == "invalid"
    assert any("connected component" in reason for reason in rejected.reasons)


def test_read_only_hierarchy_context_cannot_be_patched():
    request = _multi_file_request()
    request.rtl_context[0].editable = False
    rejected = validate_recommendation(
        _multi_file_recommendation(), request, already_repaired=True
    )
    assert rejected.outcome == "invalid"
    assert any("RTL context path" in reason for reason in rejected.reasons)


def test_connected_two_file_patch_is_materialised_as_complete_candidate(tmp_path: Path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "constraints").mkdir()
    (tmp_path / "rtl/parent.v").write_text(
        "module parent(input wire a, output wire y);\n"
        "  wire mid;\n"
        "  child u_child(.a(a), .y(mid));\n"
        "  assign y = mid;\n"
        "endmodule\n"
    )
    (tmp_path / "rtl/child.v").write_text(
        "module child(input wire a, output wire y);\n"
        "  assign y = a;\n"
        "endmodule\n"
    )
    (tmp_path / "constraints/test.sdc").write_text("# test\n")
    (tmp_path / "nebula.project.yaml").write_text(
        "project_id: two_file\n"
        "design:\n"
        "  top_module: parent\n"
        "  file_list:\n"
        "    - path: rtl/child.v\n"
        "    - path: rtl/parent.v\n"
        "constraints:\n"
        "  sdc_file: constraints/test.sdc\n"
        "platform:\n"
        "  liberty: missing.lib\n"
        "transformations:\n"
        "  change_budget:\n"
        "    max_changed_lines: 10\n"
        "    max_changed_files: 2\n"
        "security:\n"
        "  editable_paths: [rtl/parent.v, rtl/child.v]\n"
    )
    patch = RTLPatch(
        patch_id="patch_two",
        recommendation_id="rec_two",
        base_source_hash="",
        diff_text=(
            "--- a/rtl/parent.v\n+++ b/rtl/parent.v\n@@\n"
            "-  assign y = mid;\n+  assign y = mid | 1'b0;\n"
            "--- a/rtl/child.v\n+++ b/rtl/child.v\n@@\n"
            "-  assign y = a;\n+  assign y = a | 1'b0;\n"
        ),
    )
    candidate = tmp_path / "candidates/cand_two/rtl"
    result = apply_patch(
        load_project(tmp_path / "nebula.project.yaml"),
        patch,
        "cand_two",
        candidate,
        tmp_path / "patch.log",
    )
    assert result.outcome == "applied"
    assert result.changed_files == ["rtl/child.v", "rtl/parent.v"]
    assert "mid | 1'b0" in (candidate / "parent.v").read_text()
    assert "a | 1'b0" in (candidate / "child.v").read_text()
