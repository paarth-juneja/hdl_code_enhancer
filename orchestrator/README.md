# orchestrator

The Python control layer for Nebula. Deterministic tools measure and decide; a
generative model may only propose a bounded RTL patch. Full file-level dataflow
is in [`../Nebula_file_workflow.md`](../Nebula_file_workflow.md).

## Run it

Onboard a new RTL tree first. Nebula infers source order, a unique top module,
obvious clock/reset ports, and conservative protected/editable paths, then emits
a draft manifest, SDC, and review report:

```bash
python -m orchestrator.cli onboard --rtl ./my_design/rtl --top my_top
python -m orchestrator.cli --project ./my_design/nebula.project.yaml validate
```

Use `--run-elaboration` to add a bounded Yosys hierarchy check and `--force`
only when intentionally replacing prior onboarding output. The generated SDC is
explicitly a draft: generated clocks, real periods, I/O delays, exceptions, CDC
intent, and reset/formal assumptions must be reviewed before a baseline run.

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

Store a Groq key once in the repository's ignored `.env` file:

```bash
read -rsp "Paste Groq API key: " key; echo
printf 'GROQ_API_KEY=%s\n' "$key" > .env
unset key
chmod 600 .env
```

Nebula loads this file automatically, so future terminals do not need an
`export`. The `.env` file is ignored by Git; `.env.example` documents the
supported names without containing credentials. Then run:

```bash
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

If a reasoning model exhausts the manifest's response allowance before emitting
its patch, increase only that run's allowance with
`--max-output-tokens 4096`. Provider proposal or repair errors are retained as
run evidence and consume one iteration; they do not terminate the remaining
iteration budget.

Use `--llm anthropic --model <model-name>` with `ANTHROPIC_API_KEY` to move to
an Anthropic model later. `--model` also overrides the configured Groq model.
Both providers run the same pipeline against Yosys, OpenSTA, EQY, and ORFS.
Only model execution changes; the generated `synth.ys`, `sta.tcl`, `equiv.eqy`,
and `config.mk` are written by the same code either way.

## Layout

| Module | Role |
|---|---|
| `cli.py` | `onboard` / `validate` / `baseline` / `optimize` / `report` commands |
| `onboarding.py` | RTL discovery, source ordering, safe draft manifest/SDC/report generation |
| `config.py` | `nebula.project.yaml` → typed `ProjectConfiguration` |
| `pipeline.py` | the optimization loop; executes the ASM of the workflow doc §6 |
| `statemachine.py` | the ASM in code — states, transitions, and the no-unproven-acceptance invariant |
| `workspace.py` | run directories, content hashing, the manifest lock |
| `runner.py` | safe subprocess: argv lists only, timeouts, process-tree kill |
| `schemas/` | the versioned data contracts (guide §4.2) |
| `adapters/` | script generators (`yosys`, `opensta`, `eqy`, `orfs`) + `mock` backend |
| `parsers/` | typed views of tool output — the part that needs refitting on Linux |
| `sourcemap.py` | netlist objects → RTL lines, with confidence |
| `rtl_hierarchy.py` | bounded module/instance/port connection map for multi-file context |
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
