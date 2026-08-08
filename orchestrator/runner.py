"""Safe subprocess execution.

Three properties this module exists to guarantee:

1. **Commands are argv lists, never shell strings.** ``shell=True`` appears
   nowhere in this package. A model-supplied string therefore has no path to
   becoming a command, and there is no quoting difference between Windows and
   Linux.
2. **Every run is bounded.** A timeout is required, and expiry kills the whole
   process tree — Yosys and OpenROAD both spawn children that outlive a plain
   ``Popen.kill()``.
3. **Output is always preserved.** stdout and stderr are written to files
   regardless of exit status, because a crashed run's log is the only evidence
   of why it crashed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.schemas.common import Status, write_text


@dataclass
class ProcessResult:
    """Outcome of one tool invocation."""

    command: list[str]
    cwd: str
    exit_code: int | None
    status: Status
    runtime_s: float
    stdout_path: str
    stderr_path: str
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is Status.PASS


def _kill_tree(process: subprocess.Popen) -> None:
    """Terminate a process and its children on either platform.

    ``taskkill /T`` is the only reliable way to reach grandchildren on Windows;
    on POSIX the process group created by ``start_new_session`` does the job.
    """
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            import os
            import signal

            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:  # pragma: no cover - best effort cleanup
        process.kill()


def _tail(text: str, lines: int = 40) -> str:
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def tool_available(binary: str) -> bool:
    """Whether a tool binary is on PATH. Used to fail fast with a clear message."""
    return shutil.which(binary) is not None


def run_command(
    command: list[str],
    cwd: Path,
    log_dir: Path,
    log_name: str,
    timeout_s: int,
    env_allowlist: dict[str, str] | None = None,
) -> ProcessResult:
    """Run one tool and capture everything about the attempt.

    Args:
        command: argv as a list. Never a string; never passed through a shell.
        cwd: working directory, created if absent, isolating the tool's output.
        log_dir: where ``<log_name>.stdout.log`` and ``.stderr.log`` are written.
        log_name: base name for the log pair.
        timeout_s: hard limit. On expiry the process tree is killed and the
            status is ``TIMEOUT``, which is distinct from ``FAIL``.
        env_allowlist: exact environment for the child. ``None`` inherits the
            parent environment.

    Returns:
        A :class:`ProcessResult`. Logs exist on disk whatever happened.
    """
    cwd.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{log_name}.stdout.log"
    stderr_path = log_dir / f"{log_name}.stderr.log"

    if not tool_available(command[0]):
        message = (
            f"tool not found on PATH: {command[0]}\n"
            f"command was: {' '.join(command)}\n"
            "Install the toolchain, or re-run with --backend mock.\n"
        )
        write_text(stderr_path, message)
        write_text(stdout_path, "")
        return ProcessResult(
            command=command,
            cwd=str(cwd),
            exit_code=None,
            status=Status.ERROR,
            runtime_s=0.0,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stderr_tail=message,
            notes=["tool_not_found"],
        )

    popen_kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if env_allowlist is not None:
        popen_kwargs["env"] = env_allowlist
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    started = time.monotonic()
    timed_out = False
    process = subprocess.Popen(command, **popen_kwargs)  # noqa: S603 - argv list, no shell
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process)
        stdout, stderr = process.communicate()
    runtime = time.monotonic() - started

    stdout = stdout or ""
    stderr = stderr or ""
    write_text(stdout_path, stdout)
    write_text(stderr_path, stderr)

    if timed_out:
        status = Status.TIMEOUT
    elif process.returncode == 0:
        status = Status.PASS
    else:
        status = Status.FAIL

    return ProcessResult(
        command=command,
        cwd=str(cwd),
        exit_code=process.returncode,
        status=status,
        runtime_s=round(runtime, 3),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
        timed_out=timed_out,
    )
