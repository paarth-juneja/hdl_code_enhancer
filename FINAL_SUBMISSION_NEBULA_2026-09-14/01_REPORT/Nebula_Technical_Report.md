# Nebula

## Constraint optimization through RTL enhancement using Generative AI

Final technical report - 14 September 2026

## Executive summary

Nebula is a verification-gated RTL optimization workflow. It analyzes timing,
maps critical endpoints back to source, supplies bounded context to a Generative
AI model, applies structured RTL patches, runs synthesis and timing screens,
proves cycle-exact whole-design equivalence, and accepts a candidate only after a
matched physical-flow comparison.

The final `ethmac5` demonstration meets the benchmark's structural targets: five
independent asynchronous master clock domains, one generated clock per master,
explicit clock-domain crossings, fixed and programmable divider logic, and
approximately 50,000 standard cells. Its frozen baseline contains 51,359 cells
after standalone synthesis and 57,608 functional standard cells after routing.

The accepted AI proposal replaces a seven-level linear 32-bit XOR reduction with
a balanced three-level tree. EQY proves the complete design cycle-exact. The
matched routed comparison improves setup WNS by 0.094790 ns, improves setup TNS
by 3.4968 ns, removes 100 standard cells, reduces area by 142 um^2, and reduces
vectorless estimated power by 0.88%.

## 1. Problem and design goal

Timing repair at RTL requires more than plausible code generation. A proposed
change must preserve interfaces, resets, clock-domain behavior, transaction
latency, and functional behavior. It must also produce a measured improvement
under the same library, constraints, corner, and physical-flow settings.

Nebula treats the language model as a proposal generator inside a deterministic
verification pipeline. The model cannot edit protected clock, reset, CDC, or
wrapper files. Candidate patches pass schema validation, path and scope checks,
synthesis, static timing, formal equivalence, and post-route comparison before
acceptance.

## 2. System architecture

The command-line orchestrator performs these stages:

1. Validate the project manifest and hash all declared RTL and constraints.
2. Synthesize the complete design with Yosys.
3. Run OpenSTA, parse clocks and violations, and map timing endpoints to RTL.
4. Build bounded hierarchy context around the critical module.
5. Request a structured RTL patch from the configured model provider.
6. Apply the patch in an isolated candidate workspace.
7. Screen the candidate with full-design synthesis and timing analysis.
8. Prove whole-design cycle-exact equivalence with EQY.
9. Run the matched OpenROAD physical flow and compare timing and PPA.
10. Accept or reject using explicit guardrails while retaining every attempt.

The repository also includes automated onboarding. Given an RTL directory, it
discovers sources, infers a top module where unambiguous, orders dependencies,
expands clock vectors, detects likely resets/CDC/dividers, creates conservative
protected/editable boundaries, and emits a draft manifest, SDC, and review list.

## 3. Benchmark qualification

`ethmac5` wraps an unchanged OpenCores Ethernet MAC with two auxiliary domains.
The wrapper exposes five asynchronous masters: WB, TX, RX, AUX0, and AUX1. Each
master produces a declared divide-by-two generated clock. Protected two-flop
toggle synchronizers provide explicit CDC behavior. Fixed divide-by-two blocks
and the MAC's programmable MDC divider satisfy the divider requirement.

The auxiliary state width calibrates the physical design near the requested
size. The frozen baseline reports 51,359 standalone synthesis cells and 57,608
routed functional standard cells. Filler and tap cells are excluded from this
number. The layout completes with zero final detailed-route DRC errors and zero
antenna violations.

This is a locally constructed qualification wrapper around unchanged third-party
MAC RTL, not an upstream ethmac configuration. The upstream licensing notices
remain in the source archive.

## 4. AI-proposed RTL change

The editable source contained a serial XOR reduction:

```verilog
assign response_o = state_q[0] ^ state_q[1] ^ state_q[2] ^ state_q[3] ^
                    state_q[4] ^ state_q[5] ^ state_q[6] ^ state_q[7];
```

The accepted proposal introduces intermediate XOR pairs and a balanced final
reduction. It preserves ports, state, reset behavior, clocks, CDC logic, and
cycle latency. Only `rtl/nebula_aux_domain.v` changes. The package includes both
files and the exact unified diff.

Three live-model iterations were retained. Candidate 1 passed all gates and was
accepted. Candidate 2 passed the early screen but was rejected for a physical
QoR regression. Candidate 3 independently reproduced Candidate 1's netlist and
physical metrics and was also accepted. The final deliverable uses Candidate 1.

## 5. Formal verification

EQY compared the full `nebula_ethmac5_top` hierarchy, not only the edited module.
The equivalence relation is cycle-exact with the same reset sequence. It proved
all partitions and reported `DONE (PASS, rc=0)` after 140 seconds. The full log,
EQY configuration, PASS marker, parsed result, and accepted patch are in the
proof bundle.

The equivalence gate is mandatory in the state machine. Tests also verify that
UNKNOWN or FAIL cannot proceed to physical comparison or acceptance.

## 6. Matched physical results

Baseline run: `20260913T160717Z_baseline`

Candidate run: `20260913T164418Z_optimize`, candidate `cand_0001_06c207`

| Routed metric | Baseline | Candidate | Change |
| --- | ---: | ---: | ---: |
| Setup WNS | -0.430501 ns | -0.335711 ns | +0.094790 ns (+22.019%) |
| Setup TNS | -22.1458 ns | -18.6490 ns | +3.4968 ns (+15.790%) |
| Standard cells | 57,608 | 57,508 | -100 (-0.174%) |
| Cell area | 139,496 um^2 | 139,354 um^2 | -142 um^2 (-0.102%) |
| Estimated power | 0.230906 W | 0.228874 W | -0.002032 W (-0.880%) |
| Final route DRC | 0 | 0 | unchanged |
| Antenna violations | 0 | 0 | unchanged |

The same toolchain, SDC, library, corner, and physical-flow configuration were
used for both runs. Under the fixed 0.45 ns AUX0 constraint, adding the magnitude
of WNS gives an effective-period estimate of 0.880501 ns for the baseline and
0.785711 ns for the candidate, or approximately 1.136 GHz and 1.273 GHz. This
12.1% estimate is explanatory only; it is not a separately measured frequency
sweep.

## 7. Reproducibility and audit trail

The source archive is produced from Git commit `040eb0d`. The proof bundle
contains run manifests, locked input hashes, parsed timing data, full model
requests and responses with no credentials, screen results, the raw EQY log,
ORFS metadata, final timing reports, layout images, and the acceptance verdict.
`SHA256SUMS.txt` covers every distributed file.

Key identities:

- Baseline RTL SHA-256: `e65fb297fde081c698f170e79a277c377929b38b8ab55e51d83b305dcc608443`
- Accepted RTL SHA-256: `31c25a0a596d5dc15dd1aa22ddff132954d6734b16b8a7ad3c329f7418a8a0de`
- Baseline netlist SHA-256: `f68b90b83507c6c83d44e2382487c233d19fcb03ee72c2694e3259f6a86feb6f`
- Accepted netlist SHA-256: `9e0d8962b27776c3fe0148cbe6ec38df426d95fb09b0e8b85837185308dfc664`
- Frozen SDC SHA-256: `a71d9f1b8d16fa097a69b722ba79dfb981859d97a4728e27e37fb7bd8a175220`

## 8. Limitations and next work

The candidate improves setup timing but still has -0.335711 ns setup WNS.
Candidate hold WNS is -0.00689157 ns and hold TNS is -0.0693946 ns. Therefore,
this submission claims a verified optimization, not timing closure.

Power uses ORFS default vectorless activity and supports only a matched relative
comparison. Activity-annotated power and an explicit frequency sweep remain
future signoff work. Hierarchy context comes from a lightweight source scanner,
so complex generate constructs, macros, and ambiguous instance contexts require
additional validation.

## 9. Conclusion

Nebula demonstrates a complete evidence chain from timing analysis to an AI
proposal, guarded patching, cycle-exact formal proof, and matched post-route
measurement. The accepted result improves timing, area, cell count, and estimated
power simultaneously while preserving full-design behavior. The retained failed
attempt and explicit limitations show that acceptance depends on measured proof,
not the model's confidence.

