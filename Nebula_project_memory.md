# Nebula project memory

Last updated: 16 August 2026

Purpose: this is a compact, living record of the decisions and next actions discussed for the Nebula RTL optimization project. Update it whenever the architecture, environment, constraints, or implementation status changes.

## Project objective

Build a tool-grounded RTL optimization system in which Python orchestrates deterministic EDA tools and an LLM proposes constrained RTL changes. The final system must compare the original and candidate RTL under identical settings, formally verify correctness, and accept a candidate only when the measured Quality of Results (QoR) satisfies a declared policy.

The intended trace is:

```text
constraints -> failing timing path -> related RTL -> proposed transformation
            -> candidate RTL -> verification -> measured QoR -> accept/reject
```

## Terminology established

- **QoR** means **Quality of Results**.
- Relevant QoR metrics include timing slack, critical-path delay, maximum frequency, cell count, area, power estimates, congestion, and design violations.
- Power is only credible when the activity assumptions or traces are documented.
- QoR must be measured by EDA tools. The LLM must not invent, estimate, or decide the measured result.

## Agreed tool responsibilities

| Component | Responsibility |
|---|---|
| Python orchestrator | Validate inputs, generate configurations, launch tools, parse reports, manage candidates, enforce timeouts, compare results, and preserve artifacts |
| Yosys | RTL elaboration and logic synthesis; mapped netlist and synthesis statistics |
| OpenSTA | Fast static timing analysis using a netlist, Liberty library, and SDC constraints |
| OpenROAD | Floorplanning, placement, clock-tree synthesis, routing, and physically informed QoR |
| ORFS | Reproducible automation around Yosys, OpenROAD, KLayout, platforms, reports, and metrics |
| EQY | Primary formal equivalence check between original and candidate RTL |
| SymbiYosys | Property checking and supplementary formal verification; not a substitute for a correctly configured equivalence check |
| LLM | Propose a small structured RTL patch and explain its reasoning; it cannot execute commands or declare success |

ORFS itself will not be generated. The Python application will generate or maintain the design-specific inputs used by ORFS, especially `config.mk`, SDC constraints, file lists, and run parameters.

## Intended optimization loop

```text
Validate project inputs
        |
Run and store immutable baseline
        |
Parse paths and QoR into structured records
        |
Provide relevant path/RTL context to the LLM
        |
Generate isolated candidate RTL
        |
Syntax/lint and fast synthesis/STA screening
        |
EQY equivalence check
        |
Full ORFS/OpenROAD run for promising candidates
        |
Compare against baseline using frozen settings
        |
Accept, reject, or try the next bounded candidate
```

## Initial acceptance policy

A candidate should initially be accepted only when all of the following hold:

1. Equivalence status is `PASS`.
2. No clocks or timing constraints disappeared.
3. Timing improves or the required timing violation closes.
4. Area regression stays within a declared limit, tentatively 5%.
5. Latency, interfaces, resets, and cycle-level behavior remain unchanged.
6. The authoritative ORFS/OpenROAD stage completes successfully.
7. Raw logs, parsed metrics, tool versions, configurations, and rejected attempts are retained.

Begin with cycle-exact combinational restructuring and synthesis-friendly RTL refactors. Do not initially allow pipelining, retiming, clock gating, reset changes, or CDC modifications because these require stronger specifications and verification.

## Current machine status

Migrated to a native Linux workstation. Checked on 8 August 2026:

| Software | Status |
|---|---|
| OS | Ubuntu 24.04.3 LTS (native, not WSL) |
| CPU / RAM / disk | 8 cores, 15 GB RAM, ~280 GB free |
| Python | Installed: Python 3.12.3 (project venv at `nebula/.venv`) |
| Git | Installed: Git 2.43.0 |
| Make | Installed: GNU Make 4.3 |
| Docker | Installed and verified (`docker.io`, daemon active, `hello-world` passes); user `juneja` added to `docker` group |

Prior Windows status (4 Aug 2026): Python 3.13.14, Git for Windows 2.53.0, Docker/WSL absent. Superseded by the Linux migration above.

**Project location (changed 16 Aug 2026): `/home/juneja/nebula`, on the root ext4 disk.**
It previously lived on the NTFS volume; see the data-loss incident below. There is no bind
mount and no space in the path any more, so the `/mnt/nv` workaround is retired. Anywhere
below that refers to `/mnt/nv/...` or `/media/juneja/New Volume...` is historical.

Environment notes:
- The project's Python deps (pydantic, pyyaml, pytest) are NOT installed system-wide; they live in `nebula/.venv`. Activate with `. .venv/bin/activate` before running the orchestrator or pytest. `requirements.txt` now exists at the project root.
- The `docker` group is active for `juneja` in new shells; the old `sg docker -c "..."` prefix is no longer needed.
- The embedded terminal in the desktop app mangles `sudo`/password keystrokes; run privileged commands in a native GNOME terminal instead.
- Pre-existing broken dpkg state: `linux-modules-nvidia-580-*` fail to configure (missing `linux-headers-6.17.0-19-generic`). Unrelated to Nebula; makes every apt run print NVIDIA errors at the end. Not yet cleaned up.
- Mock loop confirmed green on Linux: `pytest tests/` = 5 passed (8 Aug 2026).

**CPU / AVX-512 constraint (critical, 8 Aug 2026):** the workstation CPU is an Intel
i7-7700HQ (Kaby Lake) — supports AVX2/FMA/BMI2 but **NOT AVX-512**. The prebuilt
`openroad/orfs:latest` image bundles `kepler-formal` (the in-flow logical-equivalence
checker), which is **compiled with AVX-512** (1547 zmm regs, `vpternlogd`/`kmov*`) and
crashes with SIGILL (`ILL_ILLOPN`) on this CPU — it dies even on `--help`. This aborted
the default ORFS run at the CTS stage ("cts.tcl child killed: illegal instruction").
Diagnosed via strace, not guessed. OpenROAD/Yosys binaries themselves are AVX-512-free
and run fine — only kepler-formal is affected.
- **Workaround:** run ORFS with `LEC_CHECK=0` (gated in `flow/scripts/lec_check.tcl`;
  disables the kepler-formal step). The core synth→place→CTS→route flow does not need it.
  Use `util/docker_shell make LEC_CHECK=0` (or set `LEC_CHECK=0` in the design config).
- Any other AVX-512-compiled EDA binary will hit the same wall; prefer generic/portable
  builds, and if a needed tool is AVX-512-only, build it from source with this CPU's ISA.
- **EQY is bundled in the ORFS image** (`/usr/local/bin/eqy`) — no separate OSS CAD Suite
  needed. **RESOLVED 16 Aug 2026: EQY v0.67 runs fine on this CPU** (exit 0, no SIGILL). It
  is a different tool from kepler-formal and is not AVX-512-blocked.
- **The image ships no external SMT solver** — no bitwuzla, yices, z3 or boolector; only
  `yosys-smtbmc`. So EQY strategies must use `use sat` (Yosys's built-in SAT with temporal
  induction), which needs no external binary. An SMT-based strategy is unrunnable here
  without installing a solver.

**`--backend real` invocation model (chosen 8 Aug 2026):** the orchestrator stays on the
host (in `.venv`); each tool is reached by shelling out to the ORFS Docker image via thin
wrapper scripts in `tools/bin/{yosys,sta,eqy}`. Each wrapper does
`docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v $NEBULA:$NEBULA -v $ORFS:$ORFS -w $PWD openroad/orfs:latest <in-image-binary> "$@"`.
Workspace + ORFS clone are mounted at *identical* host paths so absolute paths baked into
generated `synth.ys`/`sta.tcl` and the PDK `.lib/.lef` resolve unchanged inside the
container. `nebula.project.yaml` toolchain `binary:` fields point at these wrappers
(absolute paths). Zero changes to adapters/runner — the `tool_binary` indirection was
built for exactly this. In-image tool paths: yosys=`/usr/local/bin/yosys`,
sta=`/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta`, eqy=`/usr/local/bin/eqy`.
PDK files symlinked into `platform/nangate45/` from the host ORFS clone.

**Space-in-path blocker — SUPERSEDED 16 Aug 2026 by moving to ext4.** History: the project
sat at `/media/juneja/New Volume/...`, whose space breaks EDA tool scripts (yosys
`read_verilog` split the path at the space; make/ORFS cannot handle spaces at all). The fix
was a bind mount exposing the volume at `/mnt/nv`, persisted in `/etc/fstab`. That mount
silently broke: at boot the fstab bind claimed `/media/juneja/New Volume` before udisks
mounted the drive, so udisks fell back to `/media/juneja/New Volume1` (trailing `1`) and
`/mnt/nv` ended up bound to an empty directory on the root disk. The lesson is that a bind
mount racing udisks is not a durable fix. Moving to `/home/juneja/nebula` removes the
problem at the source: no space, no mount, nothing to race.

**NTFS data loss (critical, discovered 16 Aug 2026).** The `ntfs3` driver silently corrupted
six items of the 8 Aug work — file contents replaced with unrelated data, stable across
reads and md5, i.e. on-disk damage rather than a read glitch:
`nebula.project.yaml` (became git's fsmonitor-watchman perl sample),
`orchestrator/parsers/yosys_stat.py` (binary garbage), `tools/bin/yosys` and `tools/bin/sta`
(raw NTFS `INDX` index blocks), `scratch_real_screen.py` (fragments of a JS bundle), and a
zero-byte `.git` object. `constraints/nebula.sdc` was a subtler seventh case: it *reverted*
to its last committed content, silently discarding the SDC portability fixes — it hashed
clean against HEAD, so a "does the working tree match the commit?" check does not detect it.
- Everything was reconstructed on 16 Aug from the generated scripts of the last green run
  (`runs/20260808T124503Z_realscreen`), the surviving `tools/bin/eqy`, and `config.py`'s
  schema, then verified by reproducing the 8 Aug numbers exactly.
- **Root cause of the exposure was not the filesystem but the workflow: the work sat
  uncommitted for a week.** Commit after each green stage. Nothing was recoverable from
  `git`, because nothing had been pushed — `origin` still held only the initial commit.
- Do not reuse the NTFS copy. It still contains a commit made by accident against the
  corrupted files; treat that directory as dead.

**Step 4 progress (8 Aug 2026) — real backend, both screening stages GREEN:**
- synth (yosys) runs for real via wrapper: PASS. `parse_synth_stat` refit to read yosys
  `stat -liberty` table form (`908  1.4E+03 cells`) in addition to the old
  `Number of cells:` form — real baseline parses cell_count=908, area=1401.02 um^2.
- sta (OpenSTA) runs for real: PASS. **WNS = +3.04688 ns, TNS = 0** (design meets timing;
  n_paths=0 is correct — `-slack_max 0.0` lists only violating paths, of which there are none).
- `pytest tests/` still 5-green after all edits.
- Throwaway driver `scratch_real_screen.py` runs just synth+sta via RealBackend (handy for
  re-testing; now gitignored rather than deleted).

**Step 4 complete (16 Aug 2026) — ORFS and EQY both wired and green on real tools.**
Every stage of the loop now runs against genuine tools; nothing is left on the mock path.
- **ORFS** runs through detailed route via `tools/bin/make`. That wrapper deliberately
  differs from the others: it runs against the *image's* `/OpenROAD-flow-scripts/flow`
  rather than `$PWD`, mirroring ORFS's own `util/docker_shell`, because the image ships a
  matched set of flow scripts and tool binaries. The host clone stays mounted only because
  the PDK paths resolve through `platform/nangate45/` symlinks into it.
- `LEC_CHECK = 0` is now baked into the generated `config.mk`. ORFS defaults it to **1**
  whenever kepler-formal is present (`settings.mk`), and it *is* present in the image — so
  the default reproduces the AVX-512 SIGILL at CTS. This must stay set.
- **Adapter bug found and fixed:** `expected_outputs` pointed at `<stage>/metadata-base.json`,
  but ORFS writes `$(WORK_HOME)/reports/$(PLATFORM)/$(DESIGN_NICKNAME)/$(FLOW_VARIANT)/metadata.json`
  (`scripts/variables.mk`). Nothing ever wrote the old path, so the stage would have reported
  success while the parser read a missing file. Both `pipeline.py` call sites and the mock
  now take the path from the invocation's `expected_outputs`.
- Post-route baseline on nangate45: **2260 cells, 1778.21 um^2, WNS +2.91261 ns, TNS 0,
  0 setup violations, 0 DRC errors**, ~53 s wall clock.
- **EQY adapter bugs found and fixed:** the generated `equiv.eqy` was invalid. `depth` is
  not an `[options]` key (EQY accepts only `splitnets` and `insbuf` there) — it belongs in a
  `[strategy]` section. And `use bitwuzla` is not a strategy type at all; the valid set is
  `dummy | sat | sby | imctk`. Both strategies now use `sat`.
- **Formal checkpoints met:** two identical RTL copies proved equivalent (2.4 s); the
  balanced-adder-tree refactor of `dsp_core.v` proved equivalent (7.4 s). Negative control
  also passes: a deliberately broken variant (a7 dropped, a6 doubled) is caught as **FAIL**
  with rc=2, isolated to partition `nebula_top.u_dsp.s7` (1 of 48), counterexample VCD
  retained. A checker that cannot produce FAIL would be worthless, so this control matters
  as much as the PASS.

**Open issues carried forward (16 Aug 2026):**
- `constraints__clocks__count` from ORFS is **2**, but the design has four clocks; ORFS
  appears to count only `create_clock` masters, not generated clocks. `parse_orfs_metrics`
  fabricates names from that count and `pipeline.py` then overwrites them with the STA
  names, so the discrepancy is currently *masked* rather than resolved. Settle this before
  the `clocks_must_be_preserved` guardrail is trusted.
- `parse_orfs_metrics` records `power` while leaving `activity_source=None`, contradicting
  `QoRRecord`'s own docstring ("an unsourced power number is not evidence"). Either drop the
  value or name the activity source.
- `clocks.rpt` reports `period 0.000000` for both generated clocks — OpenSTA derives rather
  than stores a generated clock's period. Cosmetic today, but it feeds the same guardrail.

**SDC portability — RESOLVED, and the key lesson for the real/large design (8 Aug 2026):**
The benchmark SDC was written in **Synopsys DC/PrimeTime dialect**; OpenSTA supports only a
subset, so several commands had to be translated. This WILL recur with the user's large
production RTL/SDC — write SDC in the OpenSTA-supported subset. Fixes applied to
`constraints/nebula.sdc`:
1. Generated clocks anchored on **stable nets** `[get_nets clk_a_div]` / `[get_nets clk_b_div]`
   instead of DC-style register pins `u_div_a/clk_out_reg/Q` (which yosys renames to the
   unstable auto-name `_1750_`). Named nets survive flattening and both synth paths.
2. `remove_from_collection` (Synopsys-only) replaced with a portable `data_inputs {exclude}`
   proc that filters `[all_inputs]` by name. OpenSTA collections are **plain Tcl lists**:
   iterate with `foreach` (NOT `foreach_in_collection`) and read names with `get_full_name`.
3. Non-fatal warning remains: SDC `set_units -capacitance pF` vs library fF (1e-15) — OpenSTA
   converts; left as-is.
Also fixed Nebula's **own** `orchestrator/adapters/opensta.py`: it emitted Synopsys
`redirect FILE { report_checks ... }`, which OpenSTA rejects. Switched to OpenSTA's native
`report_checks ... > FILE` redirection.

Recommended development-machine resources are at least 16 GB RAM, 4 CPU cores, and roughly 50 GB of free storage; 32 GB RAM is preferable for larger physical runs. A GPU is not required for the EDA flow.

## Linux setup checkpoints

### 1. Install and verify the base environment

Install Git, Make, Docker, and Python on Ubuntu. Verify that these commands work before proceeding:

```bash
docker run --rm hello-world
git --version
python3 --version
```

### 2. Run the official ORFS example

```bash
git clone --recursive https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts
cd OpenROAD-flow-scripts/flow
util/docker_shell make LEC_CHECK=0   # LEC_CHECK=0 required on this CPU (no AVX-512; see kepler-formal note above)
```

Success means the default design completes and produces synthesis, timing, physical implementation, and metrics artifacts. Do not begin LLM integration until this checkpoint works.

### 3. Run a project baseline

Define the RTL file list, top module, clocks, generated clocks, SDC constraints, and initial platform. Use `nangate45` for the first smoke test unless the project requirements establish a different platform.

Keep the project outside the ORFS repository and invoke ORFS with an absolute design configuration path:

```bash
cd OpenROAD-flow-scripts/flow
util/docker_shell make DESIGN_CONFIG=/absolute/path/to/nebula/flow/config.mk
```

### 4. Add formal tools

Install a current YosysHQ OSS CAD Suite distribution or another pinned environment containing EQY, SymbiYosys, Yosys, and suitable formal solvers. First prove two identical RTL copies equivalent, then prove one small manual refactor.

## Planned repository layout

```text
nebula/
|-- rtl/                  # Immutable baseline RTL
|-- constraints/          # SDC and related constraints
|-- flow/                 # ORFS config.mk and design-specific flow data
|-- orchestrator/         # Python application
|-- candidates/           # Isolated candidate RTL trees
|-- runs/                 # Per-run logs, netlists, metrics, and manifests
|-- reports/              # Human-readable comparisons and exports
|-- tests/                # Parser, runner, policy, and fixture tests
`-- Nebula_project_memory.md
```

## Python implementation order

1. Project manifest and input validation.
2. Safe process runner with fixed commands, isolated directories, timeouts, and captured output.
3. ORFS baseline adapter.
4. Typed report parsers and a common JSON run record.
5. Candidate copying and patch application.
6. Fast syntax/synthesis/STA screening.
7. EQY adapter and equivalence-result classification (`PASS`, `FAIL`, `UNKNOWN`, `ERROR`).
8. QoR comparison and acceptance policy.
9. SQLite or JSON experiment history, including every failed/rejected attempt.
10. LLM adapter with schema-constrained output.
11. Bounded multi-candidate search.
12. User interface and report export only after the command-line loop is reliable.

Suggested initial Python packages: Pydantic, PyYAML, Typer, Rich, and pytest. Tool execution should use Python's process APIs without allowing the LLM to supply arbitrary commands.

## Proposed common run record

```json
{
  "candidate_id": "baseline",
  "status": "completed",
  "tool_versions": {},
  "timing": {
    "wns_ns": null,
    "tns_ns": null,
    "critical_path_ns": null
  },
  "area": {
    "cell_count": null,
    "cell_area_um2": null
  },
  "power": {
    "estimated_mw": null,
    "activity_source": null
  },
  "equivalence": "NOT_RUN",
  "artifacts": {}
}
```

The schema must also distinguish synthesis failure, missing or unconstrained timing paths, parser failure, formal timeout, equivalence failure, and a genuine QoR regression.

## LLM guardrails

- Provide only the relevant critical path, source context, constraints, allowed transformations, and previous outcomes.
- Require structured output: patch, rationale, predicted trade-off, affected signals, and assumptions.
- Limit patch size and transformation families.
- Never let the model modify the immutable baseline or frozen constraints.
- Never let the model directly execute shell commands.
- Treat every LLM claim as a hypothesis until the tools measure it.
- Preserve rejected candidates and do not cherry-pick only successful attempts.

## ML strategy decision

Do not train a custom RTL-generation model initially. Use an existing LLM for candidate proposals and deterministic rules for scoring and validation. Accumulate structured attempt history first. A later lightweight model can rank candidates or predict which transformations are worth expensive physical runs.

## Immediate next milestone

Status as of 16 August 2026 — steps 1 to 5 are done on real tools:

1. ~~Verify Docker.~~ Done.
2. ~~Run the default ORFS example.~~ Done (needs `LEC_CHECK=0` on this CPU).
3. ~~Run one small project RTL baseline.~~ Done — synth, STA, and full ORFS through route.
4. ~~Parse its headline timing and area metrics into JSON.~~ Done — all four parsers run
   against genuine tool output.
5. ~~Apply one manual cycle-exact refactor.~~ Done — balanced adder tree in `dsp_core.v`,
   proved equivalent, with a broken variant correctly disproved as a control.
6. **Produce an honest before/after comparison — the remaining step.** The refactor has been
   proved equivalent but has *not* yet been pushed through ORFS and compared post-route to
   post-route against the 2260-cell / 1778.21 um^2 / +2.91261 ns baseline. Until that runs,
   there is no measured QoR claim for it, only a correctness claim.

Only after step 6 should the LLM be connected. The whole point of the ordering is that the
model is given a loop that already measures honestly.

## File workflow and orchestrator (frozen 8 August 2026)

The file-level dataflow is now documented in `Nebula_file_workflow.md` and
implemented in `orchestrator/`. The stage → filename contract is fixed:

```text
00_validate manifest.lock.json | 10_synth netlist.v design.json synth_stat.txt
20_sta timing.rpt wns_tns.rpt clocks.rpt unconstrained.rpt | 30_parse *.json
35_map source_map.json | 40_ai request/response/recommendation/patch
45_patch candidates/<id>/rtl/* | 50_screen | 60_eqy verification_result.json
70_orfs metadata-*.json | 80_compare ppa_comparison.json verdict.json
90_history experiments/history.json
```

Key decisions baked in:

- **Backend abstraction with `--backend mock`.** Real adapters generate the true
  `synth.ys`/`sta.tcl`/`equiv.eqy`/`config.mk`; the mock replays fixtures so the
  whole loop runs on Windows today. Switching to Linux is a flag flip plus a
  refit of `orchestrator/parsers/` against genuine tool output — nothing else.
- **GenAI is called at exactly three sites** (propose / repair / narrate). Its
  only output artifact is a bounded unified diff.
- **CLI uses argparse**, not Typer/Rich (kept dependency-light; only pydantic +
  pyyaml required to run).
- **Baseline runs ORFS too**, so candidates are compared post-route to post-route
  (avoids the stage-mixing trap).
- Verified end to end: one command exercises ACCEPTED, QoR-regression, and
  EQY-FAIL branches; `pytest tests/` green.

## Open decisions

- Exact benchmark RTL and top module.
- Authoritative platform/PDK and cell-count definition.
- Complete clock, generated-clock, reset, and CDC inventory.
- Authoritative QoR stage: post-synthesis, placed, or routed.
- Timing-versus-area objective and allowed regression limits.
- LLM provider/model and API budget.
- Formal semantics for memories, X values, resets, black boxes, and any latency-changing transformation.
- Whether the final application is CLI-only, local web UI, or a service with background workers.

## Primary references

- [OpenROAD Flow Scripts repository](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts)
- [ORFS Docker instructions](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/master/docs/user/BuildWithDocker.md)
- [OpenSTA repository and interface documentation](https://github.com/The-OpenROAD-Project/OpenSTA)
- [EQY getting started](https://yosyshq.readthedocs.io/projects/eqy/en/latest/quickstart.html)
- [Local project development guide](./Nebula_project_development_guide.md)

