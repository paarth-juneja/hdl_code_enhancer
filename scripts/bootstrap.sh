#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WITH_LLM=0
WITH_REAL=0
RUN_TESTS=1

usage() {
  echo "Usage: ./scripts/bootstrap.sh [--with-llm] [--with-real-tools] [--skip-tests]"
}

for arg in "$@"; do
  case "$arg" in
    --with-llm) WITH_LLM=1 ;;
    --with-real-tools) WITH_REAL=1 ;;
    --skip-tests) RUN_TESTS=0 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required." >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ "$WITH_LLM" -eq 1 ]]; then
  .venv/bin/python -m pip install -r requirements-llm.txt
  if [[ ! -e .env ]]; then
    cp .env.example .env
    chmod 600 .env
    echo "Created ignored .env; add GROQ_API_KEY or ANTHROPIC_API_KEY before a live run."
  fi
fi

if [[ "$WITH_REAL" -eq 1 ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for --with-real-tools." >&2
    exit 1
  fi
  docker info >/dev/null
  ORFS_IMAGE="${NEBULA_ORFS_IMAGE:-openroad/orfs:latest}"
  docker pull "$ORFS_IMAGE"
  mkdir -p platform/nangate45
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -v "$REPO_ROOT/platform/nangate45:/export" \
    "$ORFS_IMAGE" \
    sh -c 'cp /OpenROAD-flow-scripts/flow/platforms/nangate45/lib/NangateOpenCellLibrary_typical.lib /export/ && cp /OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.tech.lef /export/ && cp /OpenROAD-flow-scripts/flow/platforms/nangate45/lef/NangateOpenCellLibrary.macro.lef /export/'
fi

doctor_args=()
if [[ "$WITH_REAL" -eq 1 ]]; then
  doctor_args+=(--real)
fi
.venv/bin/python scripts/doctor.py "${doctor_args[@]}"

if [[ "$RUN_TESTS" -eq 1 ]]; then
  .venv/bin/python -m pytest -q
fi

.venv/bin/python -m orchestrator.cli optimize --backend mock --llm mock --iterations 1
echo
echo "Nebula is ready. See README.md for real-tool, live-model, and onboarding commands."
