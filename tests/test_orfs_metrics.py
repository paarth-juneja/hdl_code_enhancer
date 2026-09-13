from __future__ import annotations

import json

from orchestrator.parsers.orfs_metrics import parse_orfs_metrics


def test_orfs_cell_count_excludes_fill_and_tap_instances(tmp_path):
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "constraints__clocks__count": 5,
                "finish__design__instance__count": 128436,
                "finish__design__instance__count__stdcell": 50725,
                "finish__design__instance__area": 126423,
                "finish__timing__setup__ws": 6.44766,
                "finish__timing__setup__tns": 0,
            }
        ),
        encoding="utf-8",
    )

    qor, timing = parse_orfs_metrics(metadata, "run_test")

    assert qor.cell_count == 50725
    assert timing.wns.value == 6.44766


def test_orfs_cell_count_falls_back_for_legacy_metadata(tmp_path):
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "constraints__clocks__count": 1,
                "finish__design__instance__count": 123,
                "finish__design__instance__area": 456,
                "finish__timing__setup__ws": 0.1,
                "finish__timing__setup__tns": 0,
            }
        ),
        encoding="utf-8",
    )

    qor, _ = parse_orfs_metrics(metadata, "run_legacy")

    assert qor.cell_count == 123
