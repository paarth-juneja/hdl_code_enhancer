# ethmac5 accepted result

This is the tracked summary for real run `20260913T164418Z_optimize`, compared
against immutable baseline `20260913T160717Z_baseline`. Both used the same
Nangate45 library, SDC, tool configuration and physical-flow settings.

## Benchmark qualification

- Five independent master clocks: WB, TX, RX, AUX0 and AUX1.
- Five divide-by-two generated clocks, one sourced from each master.
- Explicit two-flop toggle CDC synchronizers, protected from model edits.
- Fixed divide-by-two logic plus the MAC's programmable MDC divider.
- 51,359 cells in Nebula standalone baseline synthesis and 57,608 routed
  standard cells. Fill and tap cells are excluded from the routed count.
- Zero baseline and candidate detailed-route DRC errors; zero antenna violations.

## Accepted AI change

Groq proposed reassociating a seven-level linear 32-bit XOR reduction into a
three-level balanced tree. Only `rtl/nebula_aux_domain.v` changed. Clock, CDC,
reset, interface and latency behavior were not modified. The exact diff is
`accepted.patch`; the deliverable RTL is `../optimized/nebula_aux_domain.v`.

EQY proved the complete `nebula_ethmac5_top` design cycle-exact under the same
reset sequence (`PASS`, 140 seconds). A second model proposal synthesized to
the same netlist and independently reproduced the accepted physical metrics.

| Routed metric | Baseline | Accepted | Change |
| --- | ---: | ---: | ---: |
| Setup WNS | -0.430501 ns | -0.335711 ns | +0.094790 ns (+22.019%) |
| Setup TNS | -22.1458 ns | -18.6490 ns | +3.4968 ns (+15.790%) |
| Standard cells | 57,608 | 57,508 | -100 (-0.174%) |
| Cell area | 139,496 um^2 | 139,354 um^2 | -142 um^2 (-0.102%) |
| Estimated power | 0.230906 W | 0.228874 W | -0.002032 W (-0.880%) |
| Detailed-route DRC | 0 | 0 | unchanged |

For the 0.45 ns AUX0 target, a WNS-derived effective-period estimate improves
from 0.880501 ns to 0.785711 ns, corresponding to about 1.136 GHz to 1.273 GHz
(+12.1%). This is an estimate under the fixed constraint model, not a separate
frequency-sweep signoff result.

## Limitations

- Setup timing improves but remains negative; this is an optimization result,
  not a claim of full timing closure.
- Candidate hold WNS is -0.00689157 ns and hold TNS is -0.0693946 ns. Hold
  cleanup remains before signoff.
- Power is ORFS vectorless/default-activity estimation. It is useful only as a
  matched comparison, not activity-annotated signoff power.
- Raw run directories are Git-ignored. Preserve them separately when packaging
  submission evidence.

## Reproducibility identities

- Baseline RTL SHA-256: `e65fb297fde081c698f170e79a277c377929b38b8ab55e51d83b305dcc608443`
- Accepted RTL SHA-256: `31c25a0a596d5dc15dd1aa22ddff132954d6734b16b8a7ad3c329f7418a8a0de`
- Baseline synthesized netlist SHA-256: `f68b90b83507c6c83d44e2382487c233d19fcb03ee72c2694e3259f6a86feb6f`
- Accepted synthesized netlist SHA-256: `9e0d8962b27776c3fe0148cbe6ec38df426d95fb09b0e8b85837185308dfc664`
- Frozen SDC SHA-256: `a71d9f1b8d16fa097a69b722ba79dfb981859d97a4728e27e37fb7bd8a175220`
