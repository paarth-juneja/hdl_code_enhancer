"""Shared test fixtures. Ensures the project root is importable as a package."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.config import load_project  # noqa: E402


@pytest.fixture
def project():
    return load_project(ROOT / "nebula.project.yaml")
