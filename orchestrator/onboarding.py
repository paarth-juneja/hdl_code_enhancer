"""Conservative onboarding for a new RTL tree.

The optimizer is automatic once a project manifest and constraints are valid.
This module removes most of the mechanical setup while keeping uncertain timing
intent explicit: source discovery and hierarchy are inferred, but clock periods,
generated-clock anchors, CDC intent, and editable/protected boundaries remain
visible review items rather than hidden guesses.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator.rtl_hierarchy import (
    RTLModule,
    _find_instances,
    _module_spans,
)
from orchestrator.runner import run_command
from orchestrator.schemas.common import Status, write_text


RTL_SUFFIXES = {".v": "verilog", ".sv": "systemverilog"}
IGNORED_DIRS = {
    ".git", ".venv", "build", "candidates", "dist", "experiments",
    "node_modules", "runs", "slpp_all",
}
_CLOCK_NAME = re.compile(r"(?:^|_)(?:clk|clock)(?:_|$)|^(?:clk|clock)", re.I)
_RESET_NAME = re.compile(r"(?:^|_)(?:rst|reset)(?:_|$)|^(?:rst|reset)", re.I)
_PROTECTED_NAME = re.compile(r"cdc|synchron|async.*fifo|clock.*div|clk.*div|reset", re.I)
_CONSTANT_RANGE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
_PORT_DIRECTION = re.compile(r"\b(input|output|inout)\b")


class OnboardingError(ValueError):
    """The RTL tree is ambiguous or cannot be onboarded safely."""


@dataclass
class OnboardingResult:
    project_root: Path
    manifest_path: Path
    sdc_path: Path
    report_path: Path
    top_module: str
    rtl_files: list[Path]
    master_clocks: list[str]
    reset_ports: list[str]
    protected_paths: list[str]
    editable_paths: list[str]
    review_items: list[str] = field(default_factory=list)
    elaboration_status: str = "not_requested"


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()


def _discover(rtl_root: Path) -> list[Path]:
    files = [
        path for path in rtl_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in RTL_SUFFIXES
        and not any(part in IGNORED_DIRS for part in path.relative_to(rtl_root).parts)
    ]
    return sorted(files, key=lambda path: path.relative_to(rtl_root).as_posix())


def _scan(files: list[Path], output_root: Path):
    spans: list[tuple[RTLModule, int, int, str]] = []
    duplicate_modules: list[str] = []
    for path in files:
        rel = _relative(path, output_root)
        spans.extend(_module_spans(rel, path.read_text(encoding="utf-8", errors="replace")))

    modules: dict[str, RTLModule] = {}
    for module, *_ in spans:
        if module.name in modules:
            duplicate_modules.append(module.name)
        else:
            modules[module.name] = module

    connections = []
    for module, _start, _end, module_text in spans:
        connections.extend(_find_instances(module, module_text, modules))
    return spans, modules, connections, sorted(set(duplicate_modules))


def _ordered_files(
    files: list[Path],
    output_root: Path,
    modules: dict[str, RTLModule],
    connections,
    top: str,
) -> list[Path]:
    by_rel = {_relative(path, output_root): path for path in files}
    dependencies: dict[str, set[str]] = {rel: set() for rel in by_rel}
    for edge in connections:
        if edge.parent_file != edge.child_file:
            dependencies.setdefault(edge.parent_file, set()).add(edge.child_file)

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(rel: str) -> None:
        if rel in visited:
            return
        if rel in visiting:  # Recursive module/file dependency; Yosys can defer it.
            return
        visiting.add(rel)
        for dependency in sorted(dependencies.get(rel, ())):
            if dependency in by_rel:
                visit(dependency)
        visiting.remove(rel)
        visited.add(rel)
        ordered.append(rel)

    top_file = modules[top].file
    for rel in sorted(by_rel):
        if rel != top_file:
            visit(rel)
    visit(top_file)
    return [by_rel[rel] for rel in ordered]


def _expanded_port_names(name: str, module_text: str) -> list[str]:
    """Expand a constant-width ANSI port such as ``clk_m[4:0]``.

    A vector clock is multiple physical clock inputs, not one clock. Symbolic
    widths remain unexpanded because guessing a parameter value would make the
    generated constraints silently wrong.
    """
    header = module_text[:module_text.find(";")]
    directions = list(_PORT_DIRECTION.finditer(header))
    for index, match in enumerate(directions):
        end = (
            directions[index + 1].start()
            if index + 1 < len(directions)
            else len(header)
        )
        fragment = header[match.end():end]
        name_match = re.search(rf"\b{re.escape(name)}\b", fragment)
        if match.group(1) != "input" or name_match is None:
            continue
        ranges = list(_CONSTANT_RANGE.finditer(fragment[:name_match.start()]))
        if not ranges:
            return [name]
        left, right = (int(value) for value in ranges[-1].groups())
        step = -1 if left > right else 1
        return [f"{name}[{bit}]" for bit in range(left, right + step, step)]
    return [name]


def _clock_and_reset_ports(
    top: RTLModule, module_text: str
) -> tuple[list[str], list[str]]:
    inputs = [name for name, direction in top.ports.items() if direction == "input"]
    clocks = [
        expanded
        for name in sorted(name for name in inputs if _CLOCK_NAME.search(name))
        for expanded in _expanded_port_names(name, module_text)
    ]
    resets = sorted(name for name in inputs if _RESET_NAME.search(name))
    return clocks, resets


def _protected_files(
    files: list[Path], output_root: Path, spans, modules: dict[str, RTLModule], top: str
) -> list[str]:
    protected = {modules[top].file}
    modules_by_file: dict[str, list[str]] = {}
    for module, *_ in spans:
        modules_by_file.setdefault(module.file, []).append(module.name)
    for path in files:
        rel = _relative(path, output_root)
        searchable = " ".join([rel, *modules_by_file.get(rel, [])])
        if _PROTECTED_NAME.search(searchable):
            protected.add(rel)
    return sorted(protected)


def _divider_candidates(spans) -> list[str]:
    candidates = []
    for module, *_ in spans:
        if re.search(r"(?:clock|clk).*div|div.*(?:clock|clk)", module.name, re.I):
            candidates.append(f"{module.name} ({module.file})")
    return sorted(candidates)


def _cdc_candidates(spans) -> list[str]:
    candidates = []
    for module, *_ in spans:
        if re.search(r"cdc|synchron|async.*fifo", module.name, re.I):
            candidates.append(f"{module.name} ({module.file})")
    return sorted(candidates)


def _manifest_payload(
    project_id: str,
    top: str,
    rtl_root: Path,
    output_root: Path,
    ordered: list[Path],
    clocks: list[str],
    period_ns: float,
    protected: list[str],
    editable: list[str],
) -> dict:
    repo_root = Path(__file__).resolve().parents[1]
    platform_root = repo_root / "platform" / "nangate45"
    tools_root = repo_root / "tools" / "bin"
    orfs_flow = Path(os.environ.get("ORFS_FLOW_DIR", "/home/juneja/OpenROAD-flow-scripts/flow"))
    return {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "display_name": f"Onboarded RTL: {top}",
        "design": {
            "top_module": top,
            "rtl_dir": _relative(rtl_root, output_root),
            "file_list": [
                {
                    "path": _relative(path, output_root),
                    "language": RTL_SUFFIXES[path.suffix.lower()],
                }
                for path in ordered
            ],
            "include_dirs": [_relative(rtl_root, output_root)],
            "defines": {},
            "parameters": {},
        },
        "constraints": {
            "sdc_file": "constraints/nebula.sdc",
            "clock_expectations": [
                {"name": name, "type": "master", "period_ns": period_ns}
                for name in clocks
            ],
            "asynchronous_groups": [[name] for name in clocks],
        },
        "platform": {
            "platform_id": "nangate45",
            "liberty": _relative(
                platform_root / "NangateOpenCellLibrary_typical.lib", output_root
            ),
            "lef": [
                _relative(platform_root / "NangateOpenCellLibrary.tech.lef", output_root),
                _relative(platform_root / "NangateOpenCellLibrary.macro.lef", output_root),
            ],
            "analysis_corners": ["typical"],
        },
        "toolchain": {
            "tools": {
                "yosys": {"binary": (tools_root / "yosys").as_posix()},
                "opensta": {"binary": (tools_root / "sta").as_posix()},
                "eqy": {"binary": (tools_root / "eqy").as_posix()},
                "orfs": {
                    "binary": (tools_root / "make").as_posix(),
                    "flow_dir": orfs_flow.as_posix(),
                },
            }
        },
        "objective": {
            "primary_metric": "wns",
            "direction": "maximize",
            "guardrails": {
                "max_area_regression_pct": 5.0,
                "max_cell_count_regression_pct": 5.0,
                "latency_change_allowed": False,
                "interface_change_allowed": False,
                "clocks_must_be_preserved": True,
            },
            "tie_breakers": ["cell_area", "cell_count"],
        },
        "run_policy": {
            "max_iterations": 5,
            "max_candidates": 10,
            "approval_mode": "auto",
            "authoritative_stage": "orfs",
            "timeouts_s": {
                "synth": 1800, "sta": 900, "screen": 1800,
                "eqy": 3600, "orfs": 14400,
            },
        },
        "transformations": {
            "allowed": [
                "balanced_adder_tree", "common_subexpression_extraction",
                "constant_folding", "boolean_reassociation", "mux_factoring",
                "logic_replication",
            ],
            "forbidden": [
                "pipelining", "retiming", "clock_gating", "reset_restructuring",
                "cdc_modification", "interface_change",
            ],
            "change_budget": {"max_changed_lines": 40, "max_changed_files": 2},
        },
        "security": {
            "model_data_policy": "bounded_context_only",
            "protected_paths": protected,
            "editable_paths": editable,
            "redact_patterns": [],
        },
        "equivalence": {
            "relation": "cycle_exact",
            "gold_top": top,
            "gate_top": top,
            "reset_assumption": "reset_sequence_identical",
            "blackboxes": [],
        },
        "llm": {
            "propose_model": "openai/gpt-oss-120b",
            "repair_model": "openai/gpt-oss-120b",
            "narrate_model": "openai/gpt-oss-120b",
            "max_output_tokens": 4096,
            "temperature": 0.2,
            "max_repairs_per_iteration": 1,
            "prompt_version": "1.0.0",
        },
    }


def _sdc_text(clocks: list[str], period_ns: float) -> str:
    lines = [
        "# DRAFT generated by `orchestrator onboard`.",
        "# Review every period and add generated-clock, I/O, exception, and",
        "# uncertainty constraints before treating timing as authoritative.",
        "",
    ]
    for name in clocks:
        clock_name = f"{{{name}}}" if "[" in name else name
        lines.append(
            f"create_clock -name {clock_name} -period {period_ns:g} [get_ports {{{name}}}]"
        )
    if len(clocks) > 1:
        lines.extend(["", "set_clock_groups -asynchronous \\"])
        for index, name in enumerate(clocks):
            suffix = " \\" if index < len(clocks) - 1 else ""
            lines.append(f"  -group [get_clocks {{{name}}}]{suffix}")
    lines.extend([
        "",
        "# TODO: add create_generated_clock commands for every generated clock.",
        "# TODO: add realistic input/output delays and timing exceptions.",
        "",
    ])
    return "\n".join(lines)


def _report_text(
    top: str,
    ordered: list[Path],
    output_root: Path,
    clocks: list[str],
    resets: list[str],
    divider_candidates: list[str],
    cdc_candidates: list[str],
    protected: list[str],
    editable: list[str],
    unused_modules: list[str],
    review_items: list[str],
    elaboration_status: str,
) -> str:
    def bullets(values: list[str]) -> list[str]:
        return [f"- `{value}`" for value in values] or ["- None detected"]

    return "\n".join([
        "# Nebula onboarding report",
        "",
        f"Top module: `{top}`",
        f"Static source count: {len(ordered)}",
        f"Elaboration check: **{elaboration_status}**",
        "",
        "## Dependency-aware source order",
        "",
        *bullets([_relative(path, output_root) for path in ordered]),
        "",
        "## Detected master clock ports",
        "",
        *bullets(clocks),
        "",
        "## Detected reset ports",
        "",
        *bullets(resets),
        "",
        "## Probable divider modules",
        "",
        *bullets(divider_candidates),
        "",
        "## Probable CDC modules",
        "",
        *bullets(cdc_candidates),
        "",
        "## Protected files",
        "",
        *bullets(protected),
        "",
        "## Initially editable files",
        "",
        *bullets(editable),
        "",
        "## Modules not reachable from the selected top",
        "",
        *bullets(unused_modules),
        "",
        "## Required human review",
        "",
        *[f"- {item}" for item in review_items],
        "",
        "Do not run a costly baseline until every review item is resolved.",
        "",
    ])


def _run_elaboration(
    ordered: list[Path], top: str, output_root: Path, yosys_binary: str
) -> tuple[str, str | None]:
    check_dir = output_root / "onboarding" / "elaboration"
    script = check_dir / "elaborate.ys"
    read_lines = [
        f"read_verilog {'-sv ' if path.suffix.lower() == '.sv' else ''}{path.resolve().as_posix()}"
        for path in ordered
    ]
    write_text(script, "\n".join([*read_lines, f"hierarchy -check -top {top}", ""]))
    result = run_command(
        [yosys_binary, "-q", "-s", script.as_posix()],
        cwd=check_dir,
        log_dir=check_dir,
        log_name="elaboration",
        timeout_s=300,
    )
    detail = result.stderr_tail or result.stdout_tail or None
    return result.status.value.lower(), detail


def onboard_project(
    rtl_root: Path,
    *,
    top: str | None = None,
    output_root: Path | None = None,
    project_id: str | None = None,
    clock_period_ns: float = 10.0,
    force: bool = False,
    run_elaboration: bool = False,
) -> OnboardingResult:
    """Discover an RTL tree and write a reviewable Nebula project draft."""
    rtl_root = rtl_root.resolve()
    if not rtl_root.is_dir():
        raise OnboardingError(f"RTL directory not found: {rtl_root}")
    if clock_period_ns <= 0:
        raise OnboardingError("clock period must be positive")

    output_root = (output_root or rtl_root.parent).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "nebula.project.yaml"
    sdc_path = output_root / "constraints" / "nebula.sdc"
    report_path = output_root / "ONBOARDING_REPORT.md"
    existing = [path for path in (manifest_path, sdc_path, report_path) if path.exists()]
    if existing and not force:
        raise OnboardingError(
            "refusing to overwrite existing onboarding output: "
            + ", ".join(path.as_posix() for path in existing)
            + "; pass --force only after reviewing those files"
        )

    files = _discover(rtl_root)
    if not files:
        raise OnboardingError(f"no .v or .sv files found under {rtl_root}")
    spans, modules, connections, duplicates = _scan(files, output_root)
    if not modules:
        raise OnboardingError("no Verilog/SystemVerilog module declarations found")
    if duplicates:
        raise OnboardingError(f"duplicate module declarations: {duplicates}")

    instantiated = {edge.child_module for edge in connections}
    top_candidates = sorted(set(modules) - instantiated)
    if top is None:
        if len(top_candidates) != 1:
            raise OnboardingError(
                "top module is ambiguous; pass --top. Candidates: "
                + ", ".join(top_candidates or sorted(modules))
            )
        top = top_candidates[0]
    if top not in modules:
        raise OnboardingError(f"top module {top!r} was not found")

    ordered = _ordered_files(files, output_root, modules, connections, top)
    top_text = next(
        module_text for module, *_rest, module_text in spans if module.name == top
    )
    clocks, resets = _clock_and_reset_ports(modules[top], top_text)
    protected = _protected_files(files, output_root, spans, modules, top)
    all_rel = [_relative(path, output_root) for path in ordered]
    editable = [rel for rel in all_rel if rel not in protected]
    dividers = _divider_candidates(spans)
    cdcs = _cdc_candidates(spans)

    reachable = {top}
    changed = True
    while changed:
        changed = False
        for edge in connections:
            if edge.parent_module in reachable and edge.child_module not in reachable:
                reachable.add(edge.child_module)
                changed = True
    unused = sorted(set(modules) - reachable)

    review_items = [
        f"Confirm the inferred top module `{top}` and dependency order.",
        f"Replace the draft {clock_period_ns:g} ns period for every master clock.",
        "Declare every generated clock with its actual source, divide ratio, "
        "and stable synthesized anchor.",
        "Confirm asynchronous clock groups and add any synchronous relationships.",
        "Add realistic I/O delays, clock uncertainty, false paths, and multicycle paths.",
        "Review probable CDC/divider files and the protected/editable boundary.",
        "Confirm reset polarity and the cycle-exact formal reset assumption.",
        "Confirm parameters, preprocessor defines, include directories, memories, "
        "and black boxes.",
    ]
    if not clocks:
        review_items.insert(
            0,
            "No top-level clock input was detected; add clocks manually before validation.",
        )
    if not editable:
        review_items.append(
            "No editable datapath file was inferred; choose editable_paths manually."
        )
    if unused:
        review_items.append(
            "Remove unused modules or confirm that conditional compilation makes "
            "them reachable."
        )

    pid = project_id or re.sub(r"[^a-z0-9_]+", "_", top.lower()).strip("_")
    payload = _manifest_payload(
        pid or "onboarded_rtl", top, rtl_root, output_root, ordered, clocks,
        clock_period_ns, protected, editable,
    )
    write_text(manifest_path, yaml.safe_dump(payload, sort_keys=False, width=100))
    write_text(sdc_path, _sdc_text(clocks, clock_period_ns))

    elaboration_status = "not requested"
    if run_elaboration:
        yosys_binary = payload["toolchain"]["tools"]["yosys"]["binary"]
        elaboration_status, detail = _run_elaboration(
            ordered, top, output_root, yosys_binary
        )
        if elaboration_status != Status.PASS.value.lower():
            review_items.insert(
                0, "Yosys elaboration failed; inspect onboarding/elaboration logs."
                + (f" Last output: {detail}" if detail else "")
            )

    write_text(report_path, _report_text(
        top, ordered, output_root, clocks, resets, dividers, cdcs, protected,
        editable, unused, review_items, elaboration_status,
    ))
    return OnboardingResult(
        project_root=output_root,
        manifest_path=manifest_path,
        sdc_path=sdc_path,
        report_path=report_path,
        top_module=top,
        rtl_files=ordered,
        master_clocks=clocks,
        reset_ports=resets,
        protected_paths=protected,
        editable_paths=editable,
        review_items=review_items,
        elaboration_status=elaboration_status,
    )
