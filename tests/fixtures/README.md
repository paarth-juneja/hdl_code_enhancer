# Mock fixtures

These files are **reconstructions** of what Yosys, OpenSTA, EQY, and ORFS
produce. They exist so `--backend mock` can run the whole Nebula loop on a
machine with no EDA tooling — see `orchestrator/adapters/mock.py`.

`@@TOKEN@@` markers are substituted at run time by the mock backend, so a single
template can stand in for the baseline and for each scripted candidate outcome.

## They are not real tool output

Genuine reports differ in whitespace, column order, and wording. The parsers in
`orchestrator/parsers/` are written against these reconstructions and **will need
adjustment** against real output. The intended sequence once a Linux toolchain
exists:

1. Run the truth fixture through the real tools by hand.
2. Overwrite these files with the captured reports.
3. Re-run `--backend mock`; parsers now fail against the real formats.
4. Fix the parsers until they pass.
5. Switch to `--backend real`.

Do step 2 early. Every day the parsers only see these invented fixtures is a day
of accumulating format debt.
