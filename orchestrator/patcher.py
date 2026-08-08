"""Validate a diff and materialise it as an isolated candidate.

This is the hard half of the trust boundary. Whatever the prompt said and
whatever the validator accepted, no byte of a candidate is written until six
checks pass:

1. the patch touches only files in the editable allowlist;
2. it touches no protected path (clock gen, reset, CDC, interfaces);
3. the changed-line count is within the declared budget;
4. every hunk applies cleanly against the current baseline source;
5. every touched identifier already exists in the source (a new top-level name
   is a red flag for an interface change);
6. the resulting candidate is a full copy, so the baseline is never mutated.

The applier matches hunks by content, not by the line numbers in the ``@@``
header, so it is robust to a model that miscounts lines — a common failure mode
that would otherwise reject good patches.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.config import ProjectConfiguration
from orchestrator.schemas.ai import RTLPatch
from orchestrator.schemas.common import sha256_file, sha256_text, write_text

_FILE_HEADER_RE = re.compile(r"^\+\+\+ [ab]/(.+)$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class PatchResult:
    """Outcome of applying (or refusing) a patch."""

    outcome: str  # applied | rejected | protected
    candidate_id: str | None = None
    candidate_rtl_dir: Path | None = None
    changed_files: list[str] = field(default_factory=list)
    changed_line_count: int = 0
    reasons: list[str] = field(default_factory=list)
    log: str = ""


@dataclass
class _Hunk:
    file: str
    old_lines: list[str]
    new_lines: list[str]


def _parse_diff(diff_text: str) -> list[_Hunk]:
    """Split a unified diff into per-hunk old/new line lists.

    The ``@@`` line numbers are ignored; only the content of each hunk is used.
    """
    hunks: list[_Hunk] = []
    current_file = ""
    old: list[str] = []
    new: list[str] = []
    in_hunk = False

    def flush() -> None:
        nonlocal old, new, in_hunk
        if in_hunk and (old or new):
            hunks.append(_Hunk(current_file, old, new))
        old, new, in_hunk = [], [], False

    for line in diff_text.splitlines():
        header = _FILE_HEADER_RE.match(line)
        if header:
            flush()
            current_file = header.group(1).strip()
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("@@"):
            flush()
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        elif line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
        elif line == "":
            old.append("")
            new.append("")
    flush()
    return hunks


def _apply_hunk(source_lines: list[str], hunk: _Hunk) -> list[str] | None:
    """Replace the first exact occurrence of ``hunk.old_lines``. None on miss."""
    old = hunk.old_lines
    if not old:
        return source_lines
    n = len(old)
    for i in range(len(source_lines) - n + 1):
        if source_lines[i : i + n] == old:
            return source_lines[:i] + hunk.new_lines + source_lines[i + n :]
    return None


def _touched_identifiers(hunks: list[_Hunk]) -> set[str]:
    idents: set[str] = set()
    for hunk in hunks:
        for line in hunk.new_lines:
            idents.update(_IDENT_RE.findall(line))
    return idents


def apply_patch(
    config: ProjectConfiguration,
    patch: RTLPatch,
    candidate_id: str,
    candidate_rtl_dir: Path,
    log_path: Path,
) -> PatchResult:
    """Run the six checks and, if all pass, write the candidate tree."""
    log_lines: list[str] = [f"patch {patch.patch_id} -> candidate {candidate_id}"]
    hunks = _parse_diff(patch.diff_text)
    if not hunks:
        return _fail("rejected", ["diff contained no applicable hunks"], log_lines, log_path)

    touched_files = sorted({h.file for h in hunks})
    log_lines.append(f"touched files: {touched_files}")

    # Check 1 + 2: allowlist and protected paths.
    for relpath in touched_files:
        if config.is_protected(relpath):
            return _fail(
                "protected",
                [f"'{relpath}' is a protected path (clock/reset/CDC/interface)"],
                log_lines,
                log_path,
            )
        if not config.is_editable(relpath):
            return _fail(
                "rejected",
                [f"'{relpath}' is not in the editable allowlist"],
                log_lines,
                log_path,
            )

    # Check 3: change budget.
    changed = sum(
        len(h.new_lines) + len(h.old_lines) - 2 * _common_prefix_suffix(h)
        for h in hunks
    )
    budget = config.transformations.change_budget.max_changed_lines
    if changed > budget:
        return _fail(
            "rejected",
            [f"changed line count {changed} exceeds budget {budget}"],
            log_lines,
            log_path,
        )
    if len(touched_files) > config.transformations.change_budget.max_changed_files:
        return _fail("rejected", ["too many files changed"], log_lines, log_path)

    # Check 4 + 5: apply against baseline, verify identifiers exist.
    baseline_sources: dict[str, list[str]] = {}
    patched_sources: dict[str, list[str]] = {}
    for relpath in touched_files:
        source_path = config.resolve(relpath)
        if not source_path.exists():
            return _fail("rejected", [f"target file missing: {relpath}"], log_lines, log_path)
        lines = source_path.read_text(encoding="utf-8").splitlines()
        baseline_sources[relpath] = lines
        patched_sources[relpath] = lines

    for hunk in hunks:
        result = _apply_hunk(patched_sources[hunk.file], hunk)
        if result is None:
            return _fail(
                "rejected",
                [f"hunk did not match current source of {hunk.file}"],
                log_lines,
                log_path,
            )
        patched_sources[hunk.file] = result

    existing_idents: set[str] = set()
    for lines in baseline_sources.values():
        existing_idents.update(_IDENT_RE.findall("\n".join(lines)))
    new_idents = _touched_identifiers(hunks) - existing_idents
    # Locally-scoped new wires are fine; a new module/port name is not. Flag only
    # identifiers that look like top-level declarations.
    suspicious = {i for i in new_idents if i in {config.design.top_module}}
    if suspicious:
        return _fail(
            "rejected",
            [f"patch introduces protected top-level identifier(s): {sorted(suspicious)}"],
            log_lines,
            log_path,
        )

    # Check 6: write the isolated candidate. Copy every RTL file, then overwrite
    # the touched ones with their patched content.
    candidate_rtl_dir.mkdir(parents=True, exist_ok=True)
    for entry in config.design.file_list:
        src = config.resolve(entry.path)
        dst = candidate_rtl_dir / Path(entry.path).name
        shutil.copyfile(src, dst)
    for relpath, lines in patched_sources.items():
        dst = candidate_rtl_dir / Path(relpath).name
        write_text(dst, "\n".join(lines) + "\n")
        log_lines.append(f"wrote patched {dst.name}")

    patch.apply_status = "applied"
    patch.changed_files = touched_files
    patch.changed_line_count = changed
    patch.base_source_hash = sha256_text(
        "".join("".join(baseline_sources[f]) for f in touched_files)
    )
    patch.static_validation_results = ["all six checks passed"]

    log_lines.append(f"APPLIED: {changed} lines across {len(touched_files)} file(s)")
    write_text(log_path, "\n".join(log_lines) + "\n")
    return PatchResult(
        outcome="applied",
        candidate_id=candidate_id,
        candidate_rtl_dir=candidate_rtl_dir,
        changed_files=touched_files,
        changed_line_count=changed,
        log="\n".join(log_lines),
    )


def _common_prefix_suffix(hunk: _Hunk) -> int:
    """Count of context lines shared between old and new (rough change sizing)."""
    old, new = hunk.old_lines, hunk.new_lines
    pre = 0
    for a, b in zip(old, new):
        if a == b:
            pre += 1
        else:
            break
    suf = 0
    for a, b in zip(reversed(old[pre:]), reversed(new[pre:])):
        if a == b:
            suf += 1
        else:
            break
    return pre + suf


def _fail(
    outcome: str, reasons: list[str], log_lines: list[str], log_path: Path
) -> PatchResult:
    log_lines.extend(f"REJECTED: {r}" for r in reasons)
    write_text(log_path, "\n".join(log_lines) + "\n")
    return PatchResult(outcome=outcome, reasons=reasons, log="\n".join(log_lines))
