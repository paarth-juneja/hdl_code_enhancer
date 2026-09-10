# orchestrator

The Python control layer for Nebula. Deterministic tools measure and decide; a
generative model may only propose a bounded RTL patch. Full file-level dataflow
is in [`../Nebula_file_workflow.md`](../Nebula_file_workflow.md).

## Run it

No EDA tools required — mock mode replays fixtures:

```bash
python -m orchestrator.cli validate
python -m orchestrator.cli optimize --backend mock --llm mock --iterations 3
python -m orchestrator.cli report
```

Install the optional live-model clients inside the virtual environment:

```bash
./.venv/bin/pip install -r requirements-llm.txt
```

For a Groq trial, export the key in the current terminal and run:

```bash
export GROQ_API_KEY="..."
./.venv/bin/python -m orchestrator.cli \
  --project benchmarks/aes/nebula.project.yaml \
  optimize --backend real --llm groq --iterations 1
```

A completed physical baseline can be reused when its project and settings hash
still match. This avoids repeating the long baseline route:

```bash
./.venv/bin/python -m orchestrator.cli \
  --project benchmarks/aes/nebula.project.yaml \
  optimize --backend real --llm groq --iterations 1 \
  --reuse-baseline benchmarks/aes/runs/20260910T184108Z_baseline
```

Use `--llm anthropic --model <model-name>` with `ANTHROPIC_API_KEY` to move to
an Anthropic model later. `--model` also overrides the configured Groq model.
Both providers run the same pipeline against Yosys, OpenSTA, EQY, and ORFS.
Only model execution changes; the generated `synth.ys`, `sta.tcl`, `equiv.eqy`,
and `config.mk` are written by the same code either way.

## Layout

| Module | Role |
|---|---|
| `cli.py` | `validate` / `baseline` / `optimize` / `report` commands |
| `config.py` | `nebula.project.yaml` → typed `ProjectConfiguration` |
| `pipeline.py` | the optimization loop; executes the ASM of the workflow doc §6 |
| `statemachine.py` | the ASM in code — states, transitions, and the no-unproven-acceptance invariant |
| `workspace.py` | run directories, content hashing, the manifest lock |
| `runner.py` | safe subprocess: argv lists only, timeouts, process-tree kill |
| `schemas/` | the versioned data contracts (guide §4.2) |
| `adapters/` | script generators (`yosys`, `opensta`, `eqy`, `orfs`) + `mock` backend |
| `parsers/` | typed views of tool output — the part that needs refitting on Linux |
| `sourcemap.py` | netlist objects → RTL lines, with confidence |
| `llm/` | request builder, prompts, clients (mock, Anthropic, Groq), validator |
| `patcher.py` | the six-check diff gate; writes isolated candidates |
| `policy.py` | the acceptance policy — the only place a verdict is produced |
| `history.py` | append-only ledger; keeps every attempt, detects cycles |

## Where authority lives

`policy.py` is the only module that sets a `Verdict`. The model's entire output
surface is one unified diff, gated twice (by `llm/validator.py` on the
recommendation and `patcher.py` on the diff itself). `UNKNOWN`/`TIMEOUT`
equivalence results have their own exit in `statemachine.py` and never reach an
accepting path — `assert_no_unproven_acceptance()` fails the test suite if that
ever changes.

## Tests

```bash
python -m pytest tests/ -q
```

Covers all three ASM branches end to end, evidence retention, the protected-CDC
guard, manifest-lock non-comparability, and the ASM safety invariant.
