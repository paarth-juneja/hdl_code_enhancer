#!/usr/bin/env python3
"""Check that a fresh Nebula checkout is ready for demo or real mode."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_FILES = (
    "NangateOpenCellLibrary_typical.lib",
    "NangateOpenCellLibrary.tech.lef",
    "NangateOpenCellLibrary.macro.lef",
)
WRAPPERS = ("yosys", "sta", "eqy", "make")


def ok(message: str) -> None:
    print(f"OK   {message}")


def fail(message: str, problems: list[str]) -> None:
    print(f"FAIL {message}")
    problems.append(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="also check Docker EDA tools")
    args = parser.parse_args()
    problems: list[str] = []

    if sys.version_info >= (3, 10):
        ok(f"Python {sys.version.split()[0]}")
    else:
        fail("Python 3.10 or newer is required", problems)

    for module in ("pydantic", "yaml", "pytest"):
        if importlib.util.find_spec(module):
            ok(f"Python module {module}")
        else:
            fail(f"missing Python module {module}", problems)

    for name in WRAPPERS:
        path = ROOT / "tools" / "bin" / name
        if path.is_file() and os.access(path, os.X_OK):
            ok(f"executable wrapper tools/bin/{name}")
        else:
            fail(f"wrapper is missing or not executable: tools/bin/{name}", problems)

    validation = run([sys.executable, "-m", "orchestrator.cli", "validate"])
    if validation.returncode == 0:
        ok("default project validation")
    else:
        fail(f"default project validation: {validation.stdout.strip()}", problems)

    if args.real:
        for name in PLATFORM_FILES:
            path = ROOT / "platform" / "nangate45" / name
            if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                ok(f"installed platform input {name}")
            else:
                fail(
                    f"missing platform input {name}; run ./scripts/bootstrap.sh --with-real-tools",
                    problems,
                )

        if not shutil.which("docker"):
            fail("Docker executable is not installed", problems)
        else:
            docker = run(["docker", "info"])
            if docker.returncode == 0:
                ok("Docker daemon")
                yosys = run([str(ROOT / "tools/bin/yosys"), "-V"])
                if yosys.returncode == 0:
                    ok(f"containerized Yosys: {yosys.stdout.strip().splitlines()[-1]}")
                else:
                    fail(f"containerized Yosys failed: {yosys.stdout.strip()}", problems)
            else:
                fail(f"Docker daemon unavailable: {docker.stdout.strip()}", problems)

    if problems:
        print(f"\nDoctor found {len(problems)} problem(s). See INSTALL.md.")
        return 1
    print("\nNebula checkout is ready" + (" for real EDA runs." if args.real else " for offline demo mode."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
