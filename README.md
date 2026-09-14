# Nebula

Nebula is a verification-gated RTL optimization workflow. It uses deterministic
EDA tools to find timing problems, gives a Generative AI model a bounded source
context, validates the proposed patch, proves whole-design cycle-exact
equivalence, and accepts a candidate only after a matched physical comparison.

The repository is self-contained for mock/demo mode. Real Yosys, OpenSTA, EQY,
and OpenROAD runs use the ORFS Docker image through portable wrappers. Real-tool
bootstrap copies the required Nangate45 inputs from that image into ignored
local files. No developer-specific filesystem paths or external PDK symlinks
are required.

## Clone and run the demo

Requirements: Git, Bash, and Python 3.10 or newer.

```bash
git clone https://github.com/paarth-juneja/hdl_code_enhancer.git
cd hdl_code_enhancer
./scripts/bootstrap.sh
```

The bootstrap creates `.venv`, installs the Python dependencies, validates the
repository, runs the tests, and executes a short offline optimization demo.
Expected final lines include `33 passed` or more and an accepted mock candidate.

Run the demo again at any time:

```bash
.venv/bin/python -m orchestrator.cli validate
.venv/bin/python -m orchestrator.cli optimize \
  --backend mock --llm mock --iterations 3
.venv/bin/python -m orchestrator.cli report
```

Mock mode needs no API key, Docker image, or EDA installation. It exercises the
same pipeline and policy using checked-in fixtures.

## Run with real EDA tools

Install Docker Engine or Docker Desktop, make sure `docker info` succeeds, then:

```bash
./scripts/bootstrap.sh --with-real-tools
```

This pulls `openroad/orfs:latest`, installs its matching Nangate45 liberty and
LEF files under `platform/nangate45/`, and checks the containerized wrappers.

Run a real baseline on the small truth fixture:

```bash
.venv/bin/python -m orchestrator.cli \
  --project nebula.project.yaml baseline --backend real
```

The five-domain qualification benchmark is much larger and can take a long time
and substantial memory:

```bash
.venv/bin/python -m orchestrator.cli \
  --project benchmarks/ethmac5/nebula.project.yaml baseline --backend real
```

Set a different compatible container without editing the repository:

```bash
export NEBULA_ORFS_IMAGE=openroad/orfs:latest
```

## Run a live model optimization

Install the optional clients:

```bash
./scripts/bootstrap.sh --with-llm --skip-tests
cp .env.example .env
```

Add one key to the ignored `.env` file:

```text
GROQ_API_KEY=your_key_here
# ANTHROPIC_API_KEY=your_key_here
```

Then run one real proposal against a project that already has a real baseline:

```bash
.venv/bin/python -m orchestrator.cli \
  --project benchmarks/ethmac5/nebula.project.yaml \
  optimize --backend real --llm groq --iterations 1
```

Never commit `.env`. Nebula loads only the supported key names and keeps the file
out of Git.

## Onboard your own RTL

Keep the design inside the checkout so Docker can mount it automatically:

```bash
.venv/bin/python -m orchestrator.cli onboard \
  --rtl ./my_design/rtl \
  --top my_top \
  --output-dir ./my_design \
  --run-elaboration
```

Onboarding creates:

- `my_design/nebula.project.yaml`
- `my_design/constraints/nebula.sdc`
- `my_design/ONBOARDING_REPORT.md`

The generated constraints are deliberately a draft. Review every item in the
onboarding report, especially clock periods, generated-clock anchors, clock
groups, I/O delays, CDC intent, resets, and editable/protected paths. Then run:

```bash
.venv/bin/python -m orchestrator.cli \
  --project my_design/nebula.project.yaml validate
```

## Included verified result

The `benchmarks/ethmac5` result uses five independent master clocks, five
generated clocks, explicit CDC synchronizers, fixed and programmable clock
division, and a 57,608-standard-cell routed baseline. The accepted balanced XOR
tree passed whole-design EQY and improved routed setup WNS by 0.094790 ns while
reducing TNS, cell count, area, and matched vectorless power.

Timing improves but does not close: candidate setup WNS remains -0.335711 ns and
hold WNS remains -0.00689157 ns. See
[`benchmarks/ethmac5/evidence/RESULTS.md`](benchmarks/ethmac5/evidence/RESULTS.md)
for exact metrics, hashes, and limitations.

## Repository map

| Path | Purpose |
| --- | --- |
| `orchestrator/` | CLI, state machine, adapters, parsers, model clients, and policy |
| `benchmarks/` | GCD, AES, Ethernet MAC, and five-domain qualification projects |
| `rtl/`, `constraints/` | Small default truth fixture |
| `platform/nangate45/` | Setup notes; real bootstrap installs ignored liberty and LEF inputs |
| `tools/bin/` | Checkout-relative Docker wrappers for the real EDA tools |
| `tests/` | Offline regression suite and tool-output fixtures |
| `FINAL_SUBMISSION_NEBULA_2026-09-14/` | Report, slides, RTL, proof bundle, and frozen source export |

Generated `runs/`, `candidates/`, `experiments/`, `.venv/`, and `.env` content is
ignored by Git.

## Health checks

```bash
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/doctor.py --real
.venv/bin/python -m pytest -q
```

Detailed installation and troubleshooting notes are in [`INSTALL.md`](INSTALL.md).
The pipeline design is documented in
[`orchestrator/README.md`](orchestrator/README.md) and
[`Nebula_file_workflow.md`](Nebula_file_workflow.md).

## License note

The Ethernet MAC benchmark retains its upstream notices. Nangate45 inputs come
from the selected ORFS image and retain their original headers. Review
third-party notices before redistributing derived commercial artifacts.
