# Five-domain Ethernet MAC qualification benchmark

This benchmark wraps the unchanged OpenCores Ethernet MAC imported in
`../ethmac/rtl`. The wrapper adds two independent auxiliary master domains,
one fixed divide-by-two generated clock for every master, observable sequential
work on all generated clocks, and two-flop CDC handshake synchronizers.

The five asynchronous master domains are WB, TX, RX, AUX0 and AUX1. Their five
generated clocks are declared explicitly in `constraints/ethmac5.sdc` and in
the manifest inventory. Clock generation, CDC logic and the wrapper interface
are protected from model edits; only the auxiliary datapath is editable.

The 3328-bit state in each auxiliary domain is calibrated to bring the routed
functional standard-cell count close to 50,000. The count is a hypothesis until
measured by ORFS; filler and tap cells must not be counted as functional cells.

Run from `/home/juneja/nebula`:

```sh
.venv/bin/python -m orchestrator.cli \
  --project benchmarks/ethmac5/nebula.project.yaml baseline --backend real
```

This is a locally constructed qualification benchmark, not an upstream ethmac
configuration. The Ethernet RTL retains its upstream LGPL notices and license.

## Final measured baseline and accepted optimization

The frozen baseline is `20260913T160717Z_baseline`. It measured 51,359 cells in
Nebula standalone synthesis and 57,608 routed standard cells, with 139,496 um^2
cell area, five master plus five generated clock names, zero detailed-route DRC,
and zero antenna violations.

Live Groq run `20260913T164418Z_optimize` proposed a balanced XOR tree for the
editable auxiliary datapath. Candidate `cand_0001_06c207` passed whole-design,
cycle-exact EQY and improved routed setup WNS from -0.430501 ns to -0.335711 ns.
It also reduced setup TNS by 3.4968 ns, standard-cell count by 100, area by 142
um^2, and vectorless estimated power by 0.88%. DRC remained zero. A repeated
proposal independently reproduced the same netlist and physical result.

The tracked result summary, exact accepted patch, hashes and limitations are in
`evidence/`; the accepted RTL deliverable is in `optimized/`. Raw runs remain
Git-ignored and must be exported separately for submission. Setup and hold
slacks are still negative, so this is an accepted measured improvement rather
than a claim of complete timing closure.
