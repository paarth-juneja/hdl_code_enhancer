"""Load and validate ``nebula.project.yaml`` into a typed configuration.

Paths in the manifest are always relative to the manifest's own directory. They
are resolved against :attr:`ProjectConfiguration.project_root` at use time and
never stored absolute, so the same manifest works unchanged when the project
moves to Linux.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from orchestrator.schemas.common import NebulaRecord, sha256_file, sha256_text


class FileEntry(BaseModel):
    path: str
    language: str = "verilog"
    role: str = "rtl"


class DesignConfig(BaseModel):
    top_module: str
    rtl_dir: str = "rtl"
    file_list: list[FileEntry] = Field(default_factory=list)
    include_dirs: list[str] = Field(default_factory=list)
    defines: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, int | str] = Field(default_factory=dict)


class ClockExpectation(BaseModel):
    name: str
    type: str = "master"
    period_ns: float | None = None
    source: str | None = None
    divide_by: int | None = None


class ConstraintsConfig(BaseModel):
    sdc_file: str
    clock_expectations: list[ClockExpectation] = Field(default_factory=list)
    asynchronous_groups: list[list[str]] = Field(default_factory=list)


class PlatformConfig(BaseModel):
    platform_id: str = "nangate45"
    liberty: str = ""
    lef: list[str] = Field(default_factory=list)
    analysis_corners: list[str] = Field(default_factory=lambda: ["typical"])


class ToolEntry(BaseModel):
    binary: str
    version: str | None = None
    flow_dir: str | None = None


class ToolchainConfig(BaseModel):
    container_digest: str | None = None
    tools: dict[str, ToolEntry] = Field(default_factory=dict)


class Guardrails(BaseModel):
    max_area_regression_pct: float = 5.0
    max_cell_count_regression_pct: float = 5.0
    latency_change_allowed: bool = False
    interface_change_allowed: bool = False
    clocks_must_be_preserved: bool = True


class ObjectiveConfig(BaseModel):
    primary_metric: str = "wns"
    direction: str = "maximize"
    guardrails: Guardrails = Guardrails()
    tie_breakers: list[str] = Field(default_factory=list)


class RunPolicy(BaseModel):
    max_iterations: int = 5
    max_candidates: int = 10
    approval_mode: str = "auto"
    authoritative_stage: str = "orfs"
    timeouts_s: dict[str, int] = Field(default_factory=dict)

    def timeout(self, stage: str, default: int = 900) -> int:
        return self.timeouts_s.get(stage, default)


class ChangeBudget(BaseModel):
    max_changed_lines: int = 40
    max_changed_files: int = 2


class TransformationPolicy(BaseModel):
    allowed: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    change_budget: ChangeBudget = ChangeBudget()


class SecurityConfig(BaseModel):
    model_data_policy: str = "bounded_context_only"
    protected_paths: list[str] = Field(default_factory=list)
    editable_paths: list[str] = Field(default_factory=list)
    redact_patterns: list[str] = Field(default_factory=list)


class EquivalenceConfig(BaseModel):
    relation: str = "cycle_exact"
    gold_top: str = ""
    gate_top: str = ""
    reset_assumption: str = ""
    blackboxes: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    propose_model: str = "claude-opus-5"
    repair_model: str = "claude-opus-5"
    narrate_model: str = "claude-sonnet-5"
    max_output_tokens: int = 4096
    temperature: float = 0.2
    max_repairs_per_iteration: int = 1
    prompt_version: str = "1.0.0"


class ProjectConfiguration(NebulaRecord):
    """The whole manifest, validated.

    ``project_root`` is injected at load time and excluded from hashing, so the
    lock digest does not change when the project is checked out elsewhere.
    """

    project_id: str
    display_name: str = ""
    design: DesignConfig
    constraints: ConstraintsConfig
    platform: PlatformConfig = PlatformConfig()
    toolchain: ToolchainConfig = ToolchainConfig()
    objective: ObjectiveConfig = ObjectiveConfig()
    run_policy: RunPolicy = RunPolicy()
    transformations: TransformationPolicy = TransformationPolicy()
    security: SecurityConfig = SecurityConfig()
    equivalence: EquivalenceConfig = EquivalenceConfig()
    llm: LLMConfig = LLMConfig()

    project_root: Path = Field(default=Path("."), exclude=True)

    # -- path helpers -------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """Resolve a manifest-relative path against the project root."""
        return (self.project_root / relative).resolve()

    def rtl_files(self) -> list[Path]:
        """RTL in declared order. Order matters: Yosys reads them as given."""
        return [self.resolve(entry.path) for entry in self.design.file_list]

    def rtl_relpaths(self) -> list[str]:
        return [entry.path for entry in self.design.file_list]

    def sdc_path(self) -> Path:
        return self.resolve(self.constraints.sdc_file)

    def liberty_path(self) -> Path:
        return self.resolve(self.platform.liberty)

    def tool_binary(self, name: str, default: str | None = None) -> str:
        entry = self.toolchain.tools.get(name)
        if entry is not None:
            return entry.binary
        if default is not None:
            return default
        raise KeyError(f"tool '{name}' is not declared in the toolchain lock")

    def is_protected(self, relpath: str) -> bool:
        """True if a candidate diff is forbidden from touching this file.

        Comparison is on POSIX-normalised strings so a Windows-authored path
        cannot slip past the check on Linux or vice versa.
        """
        normalised = Path(relpath).as_posix()
        return any(
            normalised == Path(p).as_posix() for p in self.security.protected_paths
        )

    def is_editable(self, relpath: str) -> bool:
        normalised = Path(relpath).as_posix()
        if not self.security.editable_paths:
            return not self.is_protected(normalised)
        return any(
            normalised == Path(p).as_posix() for p in self.security.editable_paths
        )

    # -- hashing ------------------------------------------------------------

    def input_hashes(self) -> dict[str, str]:
        """SHA-256 of every input that must be identical across compared runs."""
        hashes: dict[str, str] = {}
        for entry in self.design.file_list:
            path = self.resolve(entry.path)
            if path.exists():
                hashes[entry.path] = sha256_file(path)
        sdc = self.sdc_path()
        if sdc.exists():
            hashes[self.constraints.sdc_file] = sha256_file(sdc)
        lib = self.liberty_path()
        hashes[self.platform.liberty] = (
            sha256_file(lib) if lib.exists() else "MISSING_LIBERTY"
        )
        return hashes

    def settings_hash(self) -> str:
        """Digest of everything except the RTL.

        This is what ``policy.py`` compares between a baseline and a candidate.
        The RTL is expected to differ; nothing else may.
        """
        payload = {
            "top_module": self.design.top_module,
            "defines": self.design.defines,
            "parameters": self.design.parameters,
            "sdc": self.input_hashes().get(self.constraints.sdc_file, ""),
            "liberty": self.input_hashes().get(self.platform.liberty, ""),
            "platform": self.platform.platform_id,
            "corners": self.platform.analysis_corners,
            "toolchain": self.toolchain.model_dump(mode="json"),
        }
        return sha256_text(repr(sorted(payload.items())))


def load_project(manifest_path: Path) -> ProjectConfiguration:
    """Parse ``nebula.project.yaml`` and attach its directory as the root."""
    manifest_path = manifest_path.resolve()
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    raw.pop("schema_version", None)
    config = ProjectConfiguration(**raw)
    config.project_root = manifest_path.parent
    return config


def validate_inputs(config: ProjectConfiguration) -> list[str]:
    """Return a list of problems. Empty list means the project is ingestible."""
    problems: list[str] = []

    if not config.design.file_list:
        problems.append("design.file_list is empty")

    for entry in config.design.file_list:
        path = config.resolve(entry.path)
        if not path.exists():
            problems.append(f"missing RTL file: {entry.path}")
        elif path.stat().st_size == 0:
            problems.append(f"empty RTL file: {entry.path}")

    if not config.sdc_path().exists():
        problems.append(f"missing SDC file: {config.constraints.sdc_file}")

    declared = {e.path for e in config.design.file_list}
    for protected in config.security.protected_paths:
        if protected.startswith("rtl/") and protected not in declared:
            problems.append(
                f"protected path '{protected}' is not in design.file_list; "
                "the patcher cannot guard a file it does not know about"
            )

    overlap = set(config.security.protected_paths) & set(config.security.editable_paths)
    if overlap:
        problems.append(f"paths are both protected and editable: {sorted(overlap)}")

    for name in config.transformations.allowed:
        if name in config.transformations.forbidden:
            problems.append(f"transformation '{name}' is both allowed and forbidden")

    return problems


def check_clock_inventory(
    config: ProjectConfiguration, observed: list[str]
) -> list[str]:
    """Compare the clocks STA actually found against the declared inventory.

    ``constraints.clock_expectations`` is the manifest's statement of which
    clocks this design has. Without checking it, the clock guardrail only
    compares a candidate against a baseline -- so a baseline whose SDC silently
    failed to create a clock would define the missing clock as normal, and every
    candidate would agree with it. Anchoring on the declaration instead is what
    makes "no clocks disappeared" a claim about the design rather than about two
    runs that happen to match.

    Only names are compared. Periods are deliberately not: OpenSTA derives a
    generated clock's period rather than storing it, and reports 0 for
    ``clk_a_div``/``clk_b_div``, so a period comparison would fail on correct
    output. An empty ``clock_expectations`` disables the check.

    Returns a list of problems; empty means the inventory matches.
    """
    declared = {entry.name for entry in config.constraints.clock_expectations}
    if not declared:
        return []

    seen = set(observed)
    problems: list[str] = []

    missing = sorted(declared - seen)
    if missing:
        problems.append(
            f"declared clock(s) absent from STA: {missing}; "
            "the SDC did not create them, so their paths are unconstrained"
        )

    undeclared = sorted(seen - declared)
    if undeclared:
        problems.append(
            f"STA found undeclared clock(s): {undeclared}; "
            "add them to constraints.clock_expectations or remove them from the SDC"
        )

    return problems
