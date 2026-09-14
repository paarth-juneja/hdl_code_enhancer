# Nangate45 platform inputs

Real EDA runs require these files:

- `NangateOpenCellLibrary_typical.lib`
- `NangateOpenCellLibrary.tech.lef`
- `NangateOpenCellLibrary.macro.lef`

Their upstream headers restrict direct redistribution, so they are not stored in
this repository. Install the versions that match the selected ORFS image:

```bash
./scripts/bootstrap.sh --with-real-tools
```

The script pulls `${NEBULA_ORFS_IMAGE:-openroad/orfs:latest}`, copies the files
from `/OpenROAD-flow-scripts/flow/platforms/nangate45/`, and leaves them ignored
by Git. Re-run the command whenever the selected image changes.
