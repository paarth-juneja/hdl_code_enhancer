# Submission readiness — 14 September 2026

Status: **qualifying benchmark and accepted optimization operational; final
packaging and timing closure remain**.

Source: `Nebula_Content.pdf`, page 2, DIGITAL challenge, “Constraint
Optimization through RTL Enhancement Using Generative AI”. Page 1 lists final
submission on 15 September and presentations on 25 September, without a year.
The brief does not specify upload format, file limits, or a required slide count.

## Official deliverables and evidence

| Required deliverable | Current evidence | Remaining work |
| --- | --- | --- |
| RTL timing analysis framework | Python CLI, Yosys/OpenSTA/ORFS adapters; real five-domain baseline artifacts | Package reproducible installation and exact tool versions |
| GenAI-based RTL optimization engine | Groq/Anthropic clients, bounded requests, patch validation, retained attempts, accepted live Groq candidate | Package a concise demo replay |
| Critical-path and timing-violation analysis | Parsed timing reports and source anchors, including the qualifying `ethmac5` benchmark | Distinguish endpoint mapping from full cone analysis in the report |
| Optimized RTL implementation | Accepted balanced-XOR RTL and exact tracked patch under `benchmarks/ethmac5` | Include it in the final export |
| Timing, frequency, and PPA comparison | Matched routed comparison: +0.09479 ns WNS, +3.4968 ns TNS, -100 cells, -142 um², -0.88% vectorless power | Run an explicit frequency sweep and activity-annotated power if time permits; close setup/hold |
| Formal equivalence verification report | Whole-design cycle-exact EQY PASS for the accepted candidate | Export the raw EQY log with the tracked summary |
| Interactive workflow demo | Runnable CLI and offline mock workflow | Rehearse a judge-facing interactive demonstration with real evidence, run selection, patch, proof and comparison; a web UI is not explicitly required |

## Mandatory benchmark qualification

The official brief requires all of these in the benchmark:

- Five independent asynchronous master clock domains.
- At least one generated clock per master.
- Clock domain crossings.
- Clock-divider logic supporting multiple ratios.
- Approximately 50,000 standard cells.

`benchmarks/ethmac5` satisfies the structural benchmark targets: five
independent master ports, a fixed generated clock for each master, explicit CDC
synchronizers, the original MAC's programmable MDC divider, and a measured
57,608 routed standard cells. Frozen baseline `20260913T160717Z_baseline`
completed with zero route DRC and antenna violations. The corresponding
standalone synthesis count is 51,359; the much larger all-instance total
includes physical filler and tap cells and must not be presented as functional
logic. This is locally constructed qualification RTL around an unchanged
third-party MAC, not an upstream ethmac configuration.

## Submission package to prepare

These are practical packaging recommendations for the seven deliverables, not
additional rules stated by the organisers:

1. Source repository/export: orchestrator, benchmark RTL and SDC, manifests,
   tests, dependencies, tool/image versions and installation instructions.
2. Original and optimized RTL plus the exact diff, clock inventory, CDC/divider
   description, frozen constraints, and benchmark qualification measurements.
3. A concise technical report: method, GenAI role, critical path, measured
   before/after timing/frequency/area/power, failed attempts, and limitations.
4. Evidence bundle: raw reports, parsed JSON, all-input hashes, EQY proof and
   negative control, physical metrics, sanitized model requests/responses.
5. Interactive demo instructions and an offline fallback recording or replay.
6. Presentation slides for the final presentation, if requested by organisers.

Run evidence is currently ignored by Git. A source push does **not** submit the
proofs or measurement logs. Export selected evidence separately, with no `.env`,
API keys, virtual environments, or unrelated private data.

## Priority order

1. Export the completed baseline, accepted candidate, EQY and route evidence.
2. Resolve remaining setup/hold violations before claiming timing closure.
3. Add a frequency sweep and activity-grounded power if schedule permits.
4. Rehearse and package the interactive demo and final report.

## Audit limits and corrections

All tests passed after this audit, including regression coverage that
rejects reuse of a baseline after the RTL changes. Baseline reuse now compares
every declared RTL file against its saved manifest-lock hash as well as settings.
That demonstrates regression
coverage, not completion of the official deliverables.

The earlier two-file EQY demonstration under
`runs/_multi_module_check_20260912/` changed comments only. It confirms file
handling and proof execution; it does not establish a functional multi-module
optimization or timing benefit. Hierarchy context is a lightweight source
scanner, not a complete elaborated timing-cone analysis. Complex generate blocks,
macros and ambiguous instance contexts need further validation.

The previous roadmap completion wording was too broad. The next priority is
official benchmark/result qualification, not additional context features.
