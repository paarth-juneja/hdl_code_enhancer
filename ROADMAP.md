# Nebula roadmap

## Submission priority

See `SUBMISSION_READINESS.md` for the official requirement audit. The qualifying
five-domain benchmark now measures 57,608 routed standard cells with zero route
DRC. A live Groq candidate is accepted after whole-design EQY and matched
post-route comparison: WNS improved by 0.09479 ns while cell count and area
decreased. Hold cleanup, activity-grounded power and final demo packaging remain.

## Implemented 14 September 2026: automated RTL onboarding

`python -m orchestrator.cli onboard --rtl <directory>` now discovers Verilog and
SystemVerilog sources, infers an unambiguous top, orders files by module
dependencies, expands constant-width clock-vector ports, detects reset/CDC/divider
candidates, and generates a conservative project manifest, draft SDC, and review
report. Top-level, CDC, divider, and reset-related files are protected by default;
other files form the initial editable set. Optional `--run-elaboration` performs a
bounded Yosys hierarchy check and returns a failing process status when it does
not pass. Timing intent that cannot be inferred safely remains an explicit human
review item.

## Implemented 13 September 2026: qualifying benchmark and accepted candidate

`benchmarks/ethmac5` wraps the unchanged imported Ethernet MAC with two auxiliary
asynchronous domains, five fixed generated clocks, observable generated-clock
loads and explicit auxiliary CDC synchronizers. The original MAC supplies the
programmable-ratio clock-divider logic. Frozen run `20260913T160717Z_baseline`
measured 51,359 standalone-synthesis cells and 57,608 final routed standard
cells, with all ten declared clock names detected, 139,496 um^2 cell area, zero
route DRC and zero antenna violations.

Live run `20260913T164418Z_optimize` accepted a model-proposed balanced XOR tree
after complete cycle-exact EQY. Routed WNS improved from -0.430501 ns to
-0.335711 ns, TNS improved by 3.4968 ns, standard cells fell by 100, area fell
by 142 um^2, and DRC remained zero. The accepted RTL and tracked evidence are
under `benchmarks/ethmac5/optimized` and `benchmarks/ethmac5/evidence`.

## Implemented 12 September 2026: initial multi-module context

Previously, requests supplied only one source slice. Requests now include
source-scanned hierarchy context; this remains an initial implementation, not
a demonstrated optimization of a complete timing cone.

Nebula now builds a bounded multi-file context from the critical timing cone:

1. Critical-path source anchors are resolved to their enclosing RTL modules.
2. Module declarations, port directions, instances, and named connections are
   scanned into an explicit hierarchy.
3. The critical module and directly connected neighbours are selected within
   `max_changed_files`; protected/non-editable neighbours are marked read-only.
4. `AIOptimizationRequest.connection_map` carries parent/child modules, instance
   names, port expressions, signal direction, and incomplete-port evidence.
5. Single-file patches remain supported. Multi-file patches are admitted only
   when every file is editable and the complete connection map connects them.
6. The existing synthesis screen elaborates the complete candidate before STA,
   and the existing EQY stage proves the complete design cycle-exact.

Acceptance evidence: 21 tests cover producer/consumer selection, AES hierarchy
traversal, two-file validation/application, missing port connections, read-only
modules, and the full mock pipeline. A real two-file candidate was also proved
equivalent across the complete truth-fixture design by EQY (`PASS`, 2 seconds).
That candidate changed comments only and is a plumbing check, not an optimized
RTL result;
its ignored evidence is under `runs/_multi_module_check_20260912/`.

## Next milestone: live multi-module optimization trial

Use a completed AES baseline and a live model to exercise the new context on a
genuinely connected pair of editable modules. The candidate must pass the same
synthesis, timing, cycle-exact EQY, and post-route ORFS gates; abstention or a
rejection is an honest result. Do not broaden into latency-changing transforms
to manufacture an improvement.

## Later milestone: latency-changing pipeline insertion

Introducing a register on a module output generally changes both an interface
contract and transaction latency. It must remain outside the cycle-exact mode.
A separate pipeline mode will require an explicitly permitted latency delta,
valid/control propagation across every affected module, a declared input/output
cycle mapping, and latency-aware sequential equivalence. Until those checks
exist, Nebula must abstain from or reject register insertion that changes
observable cycle behavior.
