"""Backend abstraction: how a described invocation actually gets executed.

An adapter produces a :class:`ToolInvocation` — a script on disk, an argv list, a
working directory, and the set of output files the tool is expected to leave
behind. A :class:`Backend` then executes it. ``RealBackend`` spawns the process;
``MockBackend`` synthesises the declared outputs from fixtures.

Because the split is at *execution* and not at *description*, both backends
exercise the same script generators and the same parsers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.runner import ProcessResult, run_command


@dataclass
class ToolInvocation:
    """A fully described tool run, independent of whether it will really run."""

    tool: str
    command: list[str]
    cwd: Path
    log_dir: Path
    log_name: str
    timeout_s: int
    #: Files the tool is expected to produce. The mock backend uses these as the
    #: list of artifacts it must synthesise; the real backend uses them to detect
    #: a tool that exited zero but wrote nothing.
    expected_outputs: dict[str, Path] = field(default_factory=dict)
    #: Which fixture family the mock should draw from.
    fixture_key: str = ""
    #: Values the mock substitutes into fixture templates for this run.
    mock_params: dict[str, object] = field(default_factory=dict)


class Backend(ABC):
    """Executes tool invocations."""

    name: str = "abstract"

    @abstractmethod
    def execute(self, invocation: ToolInvocation) -> ProcessResult:
        """Run (or simulate) the invocation and leave its outputs on disk."""

    def missing_outputs(self, invocation: ToolInvocation) -> list[str]:
        """Expected outputs that are absent or empty after execution."""
        missing = []
        for label, path in invocation.expected_outputs.items():
            if not path.exists() or path.stat().st_size == 0:
                missing.append(label)
        return missing


class RealBackend(Backend):
    """Spawns the actual tool. Used on Linux with the toolchain installed."""

    name = "real"

    def execute(self, invocation: ToolInvocation) -> ProcessResult:
        result = run_command(
            command=invocation.command,
            cwd=invocation.cwd,
            log_dir=invocation.log_dir,
            log_name=invocation.log_name,
            timeout_s=invocation.timeout_s,
        )
        # A tool that exits zero while producing nothing is a failure, not a
        # success with empty results. Yosys does this when a script silently
        # takes an error path.
        if result.ok:
            missing = self.missing_outputs(invocation)
            if missing:
                result.status = result.status.FAIL
                result.notes.append(f"expected outputs missing: {missing}")
        return result


def make_backend(name: str, **kwargs: object) -> Backend:
    """Construct a backend by name. ``mock`` is imported lazily to keep the
    real path free of any dependency on fixture material."""
    if name == "real":
        return RealBackend()
    if name == "mock":
        from orchestrator.adapters.mock import MockBackend

        return MockBackend(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"unknown backend '{name}' (expected 'real' or 'mock')")
