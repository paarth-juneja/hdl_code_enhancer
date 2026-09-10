# Nebula roadmap

## Next milestone: bounded multi-module optimization

Nebula currently sends the model one critical path and one bounded slice from
one RTL file. Although the manifest permits two changed files, the validator
only allows files actually supplied in the request, so today's effective edit
scope is one file. Full-design synthesis and formal checks can reject a broken
cross-module proposal, but the model lacks enough hierarchy context to create a
good one reliably.

The next milestone is to build a bounded multi-file context from the critical
timing cone:

1. Map critical-path elements to their producer and consumer RTL modules.
2. Resolve module instantiations, port declarations, and named connections.
3. Select the smallest relevant slices from up to the configured file budget.
4. Include an explicit connection map in `AIOptimizationRequest`.
5. Permit patches only to the supplied files and validate that patch paths match
   the connection map.
6. Elaborate and lint the complete candidate before timing analysis.
7. Run synthesis, timing, and cycle-exact formal equivalence on the complete
   design using the existing gates.

Acceptance requires tests for producer/consumer selection, hierarchy traversal,
two-file patch application, missing port connections, protected modules, and
full-design equivalence.

## Later milestone: latency-changing pipeline insertion

Introducing a register on a module output generally changes both an interface
contract and transaction latency. It must remain outside the cycle-exact mode.
A separate pipeline mode will require an explicitly permitted latency delta,
valid/control propagation across every affected module, a declared input/output
cycle mapping, and latency-aware sequential equivalence. Until those checks
exist, Nebula must abstain from or reject register insertion that changes
observable cycle behavior.
