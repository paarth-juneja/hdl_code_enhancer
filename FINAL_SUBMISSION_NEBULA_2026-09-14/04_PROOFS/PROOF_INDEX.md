# Proof index

## Formal equivalence

- `formal/eqy_full_log.txt`: complete EQY console proof; final line reports
  `DONE (PASS, rc=0)` and 140 seconds.
- `formal/verification_result.json`: parsed whole-design cycle-exact PASS.
- `formal/equiv.eqy`: proof configuration.
- `formal/PASS`: EQY success marker.

## Physical implementation

- `physical/baseline_metadata.json` and `candidate_metadata.json`: authoritative
  OpenROAD-flow-scripts metrics for timing, power, area, cell count, DRC, and
  antenna checks.
- `physical/*_finish.rpt`: final timing and power reports.
- `physical/*_final_routing.webp`: final routed-layout images.
- `physical/*_worst_path.webp`: worst-path images.
- `physical/*_route_drc.rpt`: empty final DRC reports, corroborated by metadata.
- `physical/*_antennas.txt`: empty final antenna logs, corroborated by metadata.

## Timing and critical-path analysis

- `timing/`: frozen baseline OpenSTA clock/timing reports and parsed JSON.
- `screen/`: candidate standalone screen reports.

## Model and patch provenance

- `ai/`: exact requests, raw responses, and parsed recommendations from all three
  iterations. A credential-pattern scan found no API keys or authorization data.
- `comparison/loop_report.json`: retained accepted and rejected candidates.
- `comparison/ppa_comparison.json`: matched baseline/candidate metrics.
- `comparison/verdict.json`: acceptance decision.

## Software regression

- `tests/pytest_output.txt`: final test run output.
- `tests/environment.txt`: key runtime versions detected for packaging.

## Source identities

- `manifests/baseline_manifest.lock.json`: frozen input hashes.
- `manifests/baseline_run_manifest.json` and `optimize_run_manifest.json`.
- Root `SHA256SUMS.txt`: package-level hashes.

