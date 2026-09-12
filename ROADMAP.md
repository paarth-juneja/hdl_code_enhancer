# Nebula roadmap

## Completed 12 September 2026: bounded multi-module optimization

Nebula currently sends the model one critical path and one bounded slice from
one RTL file. Although the manifest permits two changed files, the validator
only allows files actually supplied in the request, so today's effective edit
scope is one file. Full-design synthesis and formal checks can reject a broken
cross-module proposal, but the model lacks enough hierarchy context to create a
good one reliably.

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
equivalent across the complete truth-fixture design by EQY (`PASS`, 2 seconds);
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
