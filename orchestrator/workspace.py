"""Run directories, content hashing, and the manifest lock.

One :class:`Workspace` owns one ``runs/<run_id>/`` tree. Stage directories are
named with a numeric prefix so that an ``ls`` shows the pipeline in execution
order — which matters more than it sounds when someone is reading a failed run
for the first time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.config import ProjectConfiguration
from orchestrator.schemas.common import (
    run_stamp,
    sha256_text,
    short_hash,
    utc_now,
    write_json,
    write_text,
)

STAGE_DIRS = {
    "validate": "00_validate",
    "synth": "10_synth",
    "sta": "20_sta",
    "parse": "30_parse",
    "map": "35_map",
    "ai": "40_ai",
    "patch": "45_patch",
    "screen": "50_screen",
    "eqy": "60_eqy",
    "orfs": "70_orfs",
    "compare": "80_compare",
}


@dataclass
class Workspace:
    """Filesystem layout for a single run."""

    project: ProjectConfiguration
    run_id: str
    root: Path
    backend: str = "mock"
    _lock: dict[str, str] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def create(
        cls, project: ProjectConfiguration, backend: str = "mock", label: str = "run"
    ) -> "Workspace":
        run_id = f"{run_stamp()}_{label}"
        root = project.project_root / "runs" / run_id
        root.mkdir(parents=True, exist_ok=True)
        workspace = cls(project=project, run_id=run_id, root=root, backend=backend)
        write_json(
            root / "run_manifest.json",
            {
                "run_id": run_id,
                "project_id": project.project_id,
                "backend": backend,
                "created_at": utc_now(),
                "settings_hash": project.settings_hash(),
            },
        )
        return workspace

    # -- directories --------------------------------------------------------

    def stage_dir(self, stage: str, candidate_id: str | None = None) -> Path:
        """Directory for one stage, optionally scoped to a candidate.

        Candidate stages live under ``candidates/<id>/`` inside the run so that a
        rejected candidate's whole evidence tree can be kept without colliding
        with the baseline's.
        """
        name = STAGE_DIRS.get(stage, stage)
        base = self.root if candidate_id in (None, "baseline") else self.root / "candidates" / str(candidate_id)
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def candidate_rtl_dir(self, candidate_id: str) -> Path:
        """Isolated source tree for a candidate. Always a copy, never a link."""
        path = self.project.project_root / "candidates" / candidate_id / "rtl"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        """Path relative to the project root, POSIX-style, for storing in JSON."""
        try:
            return path.resolve().relative_to(self.project.project_root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    # -- manifest lock ------------------------------------------------------

    def write_lock(self) -> dict[str, str]:
        """Hash every frozen input and persist ``manifest.lock.json``.

        Everything downstream records the lock digest it ran under. ``policy.py``
        refuses to compare two runs whose ``settings_hash`` differ, which is what
        makes "identical settings" a checked property rather than a claim.
        """
        hashes = self.project.input_hashes()
        self._lock = {
            "run_id": self.run_id,
            "created_at": utc_now(),
            "settings_hash": self.project.settings_hash(),
            "file_hashes": hashes,
            "rtl_bundle_hash": sha256_text(
                "".join(hashes.get(p, "") for p in self.project.rtl_relpaths())
            ),
        }
        write_json(self.stage_dir("validate") / "manifest.lock.json", self._lock)
        return self._lock

    @property
    def lock(self) -> dict[str, str]:
        if not self._lock:
            self.write_lock()
        return self._lock

    def next_candidate_id(self, index: int, patch_hash: str) -> str:
        """Stable, sortable, and traceable back to the patch that made it."""
        return f"cand_{index:04d}_{short_hash(patch_hash)}"

    # -- artifacts ----------------------------------------------------------

    def save_text(self, stage: str, name: str, text: str, candidate_id: str | None = None) -> Path:
        return write_text(self.stage_dir(stage, candidate_id) / name, text)

    def save_json(self, stage: str, name: str, payload: object, candidate_id: str | None = None) -> Path:
        return write_json(self.stage_dir(stage, candidate_id) / name, payload)
