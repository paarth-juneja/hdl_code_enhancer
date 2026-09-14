# Nebula final submission package

Open this file first. This folder contains the final source snapshot, technical
report, presentation, optimized RTL, and the evidence needed to audit the
claimed improvement.

## Recommended review order

1. `01_REPORT/Nebula_Technical_Report.pdf`
2. `02_PRESENTATION/Nebula_Final_Presentation.pptx`
3. `03_RTL_AND_CONSTRAINTS/accepted.patch`
4. `04_PROOFS/formal/eqy_full_log.txt`
5. `04_PROOFS/physical/baseline_metadata.json` and
   `04_PROOFS/physical/candidate_metadata.json`
6. `04_PROOFS/comparison/ppa_comparison.json`
7. `05_SOURCE/nebula-source-040eb0d.tar.gz`

## Result in one paragraph

Nebula analyzes constrained RTL, maps critical timing endpoints back to source,
asks a bounded GenAI optimizer for an RTL-only patch, rejects unsafe candidates,
proves whole-design cycle-exact equivalence, and compares matched physical-flow
results. On the five-master-clock `ethmac5` qualification benchmark, the accepted
balanced XOR tree improved routed setup WNS from -0.430501 ns to -0.335711 ns,
improved TNS by 3.4968 ns, removed 100 standard cells, reduced cell area by 142
um^2, and reduced matched vectorless power by 0.88%. EQY proved the whole design
equivalent in 140 seconds. Both layouts completed with zero final route DRC and
zero antenna violations.

## Honest limitations

The result improves timing but does not close timing. Candidate setup WNS remains
-0.335711 ns, hold WNS is -0.00689157 ns, and power uses default vectorless
activity. The quoted frequency change is only a WNS-derived estimate, not a
separate frequency sweep. These limits are stated in the report and slides.

## Package map

- `00_SEND_CHECKLIST.md`: exact upload/email checklist and ready-to-send text.
- `01_REPORT/`: technical report in PDF and Markdown.
- `02_PRESENTATION/`: editable PowerPoint deck and PDF export.
- `03_RTL_AND_CONSTRAINTS/`: original/optimized RTL, exact diff, constraints,
  project manifest, and benchmark explanation.
- `04_PROOFS/`: formal, timing, physical, AI, comparison, and test evidence.
- `05_SOURCE/`: clean source archive from Git commit `040eb0d`.
- `06_REFERENCE/`: abstract, project guide, and official challenge brief.
- `SHA256SUMS.txt`: hashes for every packaged file except the checksum file.

## Reproduction

Extract the source archive, install `requirements.txt`, ensure Yosys/OpenSTA/EQY
and OpenROAD-flow-scripts are available, then run from the repository root:

```sh
python -m orchestrator.cli \
  --project benchmarks/ethmac5/nebula.project.yaml baseline --backend real
```

The full physical flow is expensive. For a fast functional regression:

```sh
python -m pytest -q
```

