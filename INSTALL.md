# Installation and first-run guide

## Supported environment

The shortest supported path is Linux or WSL2 with Python 3.10+, Git, and Bash.
macOS can run mock mode directly and real mode through Docker Desktop. Native
Windows shells are not supported; use WSL2.

Real EDA mode additionally needs:

- Docker Engine or Docker Desktop with Linux containers.
- Enough free disk for the ORFS image and generated run data.
- Permission to run `docker` without an interactive password prompt.

Live model mode needs network access and either a Groq or Anthropic API key.

## Automatic setup

```bash
git clone https://github.com/paarth-juneja/hdl_code_enhancer.git
cd hdl_code_enhancer
./scripts/bootstrap.sh
```

Available bootstrap options:

```text
--with-llm         install Groq and Anthropic client packages
--with-real-tools  pull the ORFS image and test Docker wrappers
--skip-tests       skip pytest during setup
--help             show the option summary
```

Options may be combined:

```bash
./scripts/bootstrap.sh --with-llm --with-real-tools
```

The script is safe to run again. It reuses `.venv` and never overwrites `.env`.

## Manual setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/doctor.py
.venv/bin/python -m pytest -q
```

For live model providers:

```bash
.venv/bin/python -m pip install -r requirements-llm.txt
cp .env.example .env
chmod 600 .env
```

For real tools:

```bash
docker pull openroad/orfs:latest
docker info
./scripts/bootstrap.sh --with-real-tools --skip-tests
.venv/bin/python scripts/doctor.py --real
```

## First offline run

```bash
.venv/bin/python -m orchestrator.cli validate
.venv/bin/python -m orchestrator.cli optimize \
  --backend mock --llm mock --iterations 3
.venv/bin/python -m orchestrator.cli report
```

Outputs appear under `runs/`, `candidates/`, and `experiments/`. Git ignores all
three because they are generated artifacts.

## First real run

Start with the small default fixture:

```bash
.venv/bin/python -m orchestrator.cli baseline --backend real
```

A real run creates synthesis, timing, mapping, and physical-flow evidence under
`runs/<timestamp>_baseline/`. Docker mounts the checkout at the same absolute
path inside the container, so generated scripts remain valid regardless of
where the repository was cloned.

The bootstrap also copies the matching Nangate45 liberty and LEF inputs from
the selected image to ignored files under `platform/nangate45/`. Re-run real
bootstrap after changing `NEBULA_ORFS_IMAGE` so tool and platform inputs match.

## Container selection

The wrappers default to `openroad/orfs:latest`. Override it for a tested tag or
digest:

```bash
export NEBULA_ORFS_IMAGE='openroad/orfs:latest'
```

When the wrappers are invoked from a checkout discovered through a symlink, set
the canonical repository path explicitly if needed:

```bash
export NEBULA_REPO_ROOT="$(pwd -P)"
```

## Troubleshooting

### `docker: permission denied`

Confirm `docker info` works for the current user. On Linux, follow Docker's
post-installation guidance or run the shell in an environment with Docker
access. Do not add `sudo` inside Nebula's wrappers.

### `manifest not found`

Run commands from the repository root or pass the manifest explicitly:

```bash
.venv/bin/python -m orchestrator.cli \
  --project /absolute/path/to/nebula.project.yaml validate
```

### Missing API key

Copy `.env.example` to `.env`, fill exactly one supported key, and keep the file
at the repository root. The CLI recognizes `GROQ_API_KEY` and
`ANTHROPIC_API_KEY`.

### Real flow is slow or fills the disk

The five-domain benchmark produces gigabytes of data. Use the default truth
fixture for the first real run. Archive or remove old ignored run directories
only after preserving any evidence you need.

### Onboarding elaboration fails

Open `ONBOARDING_REPORT.md`, fix missing includes, defines, parameters, memories,
or black boxes, then rerun onboarding with `--force --run-elaboration`.

### Reusing a baseline is rejected

Nebula hashes every declared RTL input and compares tool, library, constraint,
and settings identities. Reuse fails intentionally when any relevant input has
changed. Run a new baseline rather than bypassing the check.
