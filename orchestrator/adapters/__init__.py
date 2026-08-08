"""Tool adapters.

Each adapter has exactly two jobs: **generate a tool script** and **describe the
invocation**. Neither job depends on whether the tool is actually installed,
which is what makes ``--backend mock`` a drop-in substitution rather than a
branch scattered through the pipeline.

Script generation is never mocked. The ``synth.ys``, ``sta.tcl``, ``equiv.eqy``
and ``config.mk`` written during a mock run are byte-identical to the ones a
real run would write, so the scripts are under test from day one even without a
toolchain.
"""

from orchestrator.adapters.base import (
    Backend,
    RealBackend,
    ToolInvocation,
    make_backend,
)

__all__ = ["Backend", "RealBackend", "ToolInvocation", "make_backend"]
