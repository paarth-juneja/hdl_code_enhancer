"""Command-line entry point.

Uses argparse rather than a heavier framework so the loop runs on a bare Python
install with only pydantic and pyyaml present — deliberately, since the first
environment this has to work in is a Windows box with no EDA tooling.

Commands::

    python -m orchestrator.cli validate  [--project nebula.project.yaml]
    python -m orchestrator.cli onboard   --rtl ./rtl [--top my_top]
    python -m orchestrator.cli baseline  [--backend mock|real]
    python -m orchestrator.cli optimize  [--backend ...] [--llm mock|anthropic|groq] [--iterations N]
    python -m orchestrator.cli report    [--project ...]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from orchestrator import __version__
from orchestrator.adapters.base import make_backend
from orchestrator.config import load_project, validate_inputs
from orchestrator.llm.client import make_llm_client
from orchestrator.onboarding import OnboardingError, onboard_project
from orchestrator.pipeline import optimize, run_baseline
from orchestrator.schemas.common import read_json

DEFAULT_MANIFEST = "nebula.project.yaml"
LOCAL_ENV_KEYS = frozenset({"GROQ_API_KEY", "ANTHROPIC_API_KEY"})


def _load_local_env(path: Path | None = None) -> None:
    """Load supported API keys from the ignored repository-level .env file."""
    env_path = path or (Path(__file__).resolve().parents[1] / ".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in LOCAL_ENV_KEYS or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            os.environ[key] = value


def _load(args) -> "object":
    manifest = Path(args.project).resolve()
    if not manifest.exists():
        print(f"error: manifest not found: {manifest}", file=sys.stderr)
        raise SystemExit(2)
    return load_project(manifest)


def cmd_validate(args) -> int:
    config = _load(args)
    problems = validate_inputs(config)
    if problems:
        print(f"INVALID ({len(problems)} problem(s)):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {config.project_id} '{config.display_name}'")
    print(f"  top module      : {config.design.top_module}")
    print(f"  rtl files       : {len(config.design.file_list)}")
    print(f"  protected paths : {config.security.protected_paths}")
    print(f"  settings hash   : {config.settings_hash()[:16]}")
    return 0


def cmd_onboard(args) -> int:
    try:
        result = onboard_project(
            Path(args.rtl),
            top=args.top,
            output_root=Path(args.output_dir) if args.output_dir else None,
            project_id=args.project_id,
            clock_period_ns=args.clock_period_ns,
            force=args.force,
            run_elaboration=args.run_elaboration,
        )
    except OnboardingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"ONBOARDED: {result.top_module}")
    print(f"  RTL files       : {len(result.rtl_files)}")
    print(f"  master clocks   : {result.master_clocks or 'none detected'}")
    print(f"  reset ports     : {result.reset_ports or 'none detected'}")
    print(f"  protected files : {len(result.protected_paths)}")
    print(f"  editable files  : {len(result.editable_paths)}")
    print(f"  elaboration     : {result.elaboration_status}")
    print(f"  manifest        : {result.manifest_path}")
    print(f"  constraints     : {result.sdc_path}")
    print(f"  review report   : {result.report_path}")
    print("\nDraft only: resolve every review item, then run validate and baseline.")
    if args.run_elaboration and result.elaboration_status != "pass":
        print(
            "error: RTL elaboration did not pass; inspect the onboarding report.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_baseline(args) -> int:
    config = _load(args)
    backend = make_backend(args.backend)
    result = run_baseline(config, backend)
    print(f"\nbaseline artifacts under: runs/{result.workspace.run_id}/")
    return 0


def cmd_optimize(args) -> int:
    _load_local_env()
    if args.llm == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: set ANTHROPIC_API_KEY before starting a live run", file=sys.stderr)
        return 2
    if args.llm == "groq" and not os.environ.get("GROQ_API_KEY"):
        print("error: set GROQ_API_KEY before starting a live run", file=sys.stderr)
        return 2
    config = _load(args)
    backend = make_backend(args.backend)
    llm = make_llm_client(
        args.llm,
        model=args.model or config.llm.propose_model,
        max_output_tokens=args.max_output_tokens or config.llm.max_output_tokens,
        temperature=config.llm.temperature,
    )
    report = optimize(
        config,
        backend,
        llm,
        max_iterations=args.iterations,
        baseline_dir=Path(args.reuse_baseline) if args.reuse_baseline else None,
    )

    print("\n=== summary ===")
    for record in report.iterations:
        delta = record.measured_delta.get("wns")
        delta_s = f"  wns delta {delta:+.4f} ns" if isinstance(delta, (int, float)) else ""
        print(f"  iter {record.index}: {record.transformation_type or '-':32} "
              f"{record.verdict.value:14} {record.failure_class.value}{delta_s}")
    print(f"\naccepted candidates: {report.accepted or 'none'}")
    return 0


def cmd_report(args) -> int:
    config = _load(args)
    history_path = config.project_root / "experiments" / "history.json"
    if not history_path.exists():
        print("no experiments/history.json yet; run 'optimize' first", file=sys.stderr)
        return 1
    history = read_json(history_path)
    print(f"experiment {history['experiment_id']}  project {history['project_id']}")
    print(f"stop reason: {history.get('stop_reason')}")
    print(f"accepted:    {history.get('accepted_candidate_ids')}")
    print("\niterations (all attempts retained):")
    for it in history["iterations"]:
        print(f"  {it['index']:>2}  {it.get('transformation_type') or '-':32} "
              f"{it['verdict']:14} {it['failure_class']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Nebula tool-grounded RTL optimization orchestrator.",
    )
    parser.add_argument("--version", action="version", version=f"nebula {__version__}")
    parser.add_argument("--project", default=DEFAULT_MANIFEST,
                        help="path to nebula.project.yaml")

    sub = parser.add_subparsers(dest="command", required=True)

    p_on = sub.add_parser("onboard", help="discover RTL and generate a safe project draft")
    p_on.add_argument("--rtl", required=True, help="directory containing .v/.sv sources")
    p_on.add_argument("--top", help="top module; inferred only when unambiguous")
    p_on.add_argument("--output-dir", help="project output directory; defaults to RTL parent")
    p_on.add_argument("--project-id", help="manifest project identifier")
    p_on.add_argument("--clock-period-ns", type=float, default=10.0,
                      help="draft period applied to detected master clocks")
    p_on.add_argument("--run-elaboration", action="store_true",
                      help="run a bounded Yosys hierarchy/elaboration check")
    p_on.add_argument("--force", action="store_true",
                      help="replace existing generated manifest/SDC/report")
    p_on.set_defaults(func=cmd_onboard)

    p_val = sub.add_parser("validate", help="check the project manifest and inputs")
    p_val.set_defaults(func=cmd_validate)

    p_base = sub.add_parser("baseline", help="run the immutable baseline only")
    p_base.add_argument("--backend", choices=["mock", "real"], default="mock")
    p_base.set_defaults(func=cmd_baseline)

    p_opt = sub.add_parser("optimize", help="run the full optimization loop")
    p_opt.add_argument("--backend", choices=["mock", "real"], default="mock")
    p_opt.add_argument("--llm", choices=["mock", "anthropic", "groq"], default="mock")
    p_opt.add_argument(
        "--model",
        help="override the manifest's model name for the selected provider",
    )
    p_opt.add_argument(
        "--max-output-tokens",
        type=int,
        help="override the manifest's response-token limit for this run",
    )
    p_opt.add_argument("--iterations", type=int, default=None)
    p_opt.add_argument(
        "--reuse-baseline",
        metavar="RUN_DIR",
        help="reuse a completed, settings-matched baseline run",
    )
    p_opt.set_defaults(func=cmd_optimize)

    p_rep = sub.add_parser("report", help="print the experiment ledger")
    p_rep.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
