# Ethernet MAC qualification candidate

Source repository: https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts

Imported unchanged from `flow/designs/src/ethmac` at commit
`9768f0f5432c77b215be1ff3ce7a3417f2b27bcd` in the local Git checkout.
Upstream origin: https://opencores.org/projects/ethmac . License notices are
retained in `rtl/LICENSE` and each source file (LGPL 2.1 or later).
The local upstream source directory had no Git modifications at import.

## Qualification

This is a third-party candidate, **not a compliant final competition benchmark**.
It has WB, TX and RX input clocks, clock crossing logic and a programmable MDC
divider. It does not supply five independent masters or a generated clock for
each master. Upstream describes approximately 28K gates; that is not a mapped
standard-cell count. Measure the count using the imported sources and platform.

`constraints/ethmac.sdc` is a new exploratory nangate45 scenario (10 ns WB,
40 ns TX/RX), not the upstream ASAP7 SDC. The upstream SDC treats input clocks
as logically exclusive and uses different units/latencies, so it was not copied
as a signoff constraint. Our scenario treats the input domains as asynchronous.
Runtime MDC divider modes and external MDIO timing require further qualification;
this run must not be presented as complete timing closure or CDC verification.

## Run

From `/home/juneja/nebula`:

```sh
.venv/bin/python -m orchestrator.cli --project benchmarks/ethmac/nebula.project.yaml baseline --backend real
```

This invokes the existing Yosys, OpenSTA and ORFS pipeline. It does not call a
model or claim an optimized result. Results are retained under this benchmark's
ignored `runs/` directory. Only `eth_crc.v` is editable in the exploratory
manifest; clock generation, the bus crossing logic and FIFO are protected.

Other candidate considered: OpenTitan's clock manager
(https://github.com/lowRISC/opentitan/tree/master/hw/ip_templates/clkmgr).
Its generated/gated clock structure alone does not establish five independent
masters or ~50K cells; importing the full SoC would also need a SystemVerilog
and dependency integration beyond this Verilog baseline experiment.
