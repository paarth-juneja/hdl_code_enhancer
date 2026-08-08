"""Primitives shared by every Nebula record.

Two rules are enforced structurally rather than by convention:

* A bare float is never a measurement. Everything measured is a :class:`Quantity`
  carrying its unit, because "0.4" is meaningless without knowing ns from ps.
* :class:`Status` distinguishes ``UNKNOWN`` and ``TIMEOUT`` from ``FAIL``. There is
  no helper anywhere in this package that collapses them into ``PASS``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class Status(str, Enum):
    """Outcome of any stage or check.

    ``UNKNOWN`` and ``TIMEOUT`` exist so that "the solver could not decide" is
    never recorded as either success or failure.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    NOT_RUN = "NOT_RUN"


class Verdict(str, Enum):
    """Final disposition of a candidate. Only ``policy.py`` may produce one."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NON_COMPARABLE = "NON_COMPARABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_EVALUATED = "NOT_EVALUATED"


class FailureClass(str, Enum):
    """Why an iteration stopped. Recorded even for iterations that succeeded."""

    NONE = "NONE"
    INVALID_INPUT = "INVALID_INPUT"
    SYNTHESIS_FAILED = "SYNTHESIS_FAILED"
    INVALID_CONSTRAINTS = "INVALID_CONSTRAINTS"
    PARSER_FAILED = "PARSER_FAILED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNGROUNDED_CLAIM = "UNGROUNDED_CLAIM"
    ABSTAINED = "ABSTAINED"
    PATCH_REJECTED = "PATCH_REJECTED"
    PROTECTED_REGION = "PROTECTED_REGION"
    QOR_REGRESSION = "QOR_REGRESSION"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"
    UNPROVEN = "UNPROVEN"
    PHYSICAL_FAILED = "PHYSICAL_FAILED"
    GUARDRAIL_BREACH = "GUARDRAIL_BREACH"
    NON_COMPARABLE = "NON_COMPARABLE"
    CYCLE_DETECTED = "CYCLE_DETECTED"


class Quantity(BaseModel):
    """A measured value and its unit. Never store a bare number."""

    value: float | None = None
    unit: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return "n/a" if self.value is None else f"{self.value:g} {self.unit}"


class Provenance(BaseModel):
    """Where a record came from, so any number can be traced to raw output."""

    produced_by: str
    tool_version: str | None = None
    command: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    input_hashes: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: utc_now())
    backend: str = "unknown"


class NebulaRecord(BaseModel):
    """Base class carrying the schema version onto every persisted object."""

    schema_version: str = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Filesystem helpers.
#
# Every write goes through these two functions so that newline="\n" is applied
# in exactly one place. A CRLF sneaking into a generated .mk or .eqy file
# produces failures under make and the Yosys frontends that are tedious to
# diagnose, and Windows would otherwise inject them silently.
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """ISO-8601 UTC timestamp, second resolution, always suffixed with Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stamp() -> str:
    """Compact UTC stamp used to name run directories."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_text(path: Path, text: str) -> Path:
    """Write text with POSIX line endings, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def write_json(path: Path, payload: Any) -> Path:
    """Serialise a pydantic model, dict, or list to JSON on disk."""
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return write_text(path, json.dumps(data, indent=2, sort_keys=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(value: str, length: int = 6) -> str:
    return value[:length]
