"""Report parsers — the typed view of what the tools measured.

These are the components most sensitive to real tool output. The fixtures they
run against in mock mode are reconstructions; genuine Yosys/OpenSTA/EQY reports
will differ in spacing and wording, and this directory is where that difference
is absorbed. Keeping parsing isolated from the adapters is what makes the Linux
refit a change to one directory rather than to the whole pipeline.

Every parser follows the same contract: take a path, return a typed record, and
never raise on format drift — attach a ``parser_warnings`` entry and return a
record marked degraded instead, so a report the parser half-understands is
visibly half-understood rather than silently wrong.
"""

from orchestrator.parsers.eqy_status import parse_equivalence
from orchestrator.parsers.opensta_timing import parse_timing
from orchestrator.parsers.orfs_metrics import parse_orfs_metrics
from orchestrator.parsers.yosys_json_src import build_source_index
from orchestrator.parsers.yosys_stat import parse_synth_stat

__all__ = [
    "build_source_index",
    "parse_equivalence",
    "parse_orfs_metrics",
    "parse_synth_stat",
    "parse_timing",
]
