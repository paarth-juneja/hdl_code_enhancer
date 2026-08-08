"""Versioned data contracts shared by the backend, the AI layer, and the UI.

Every model here carries ``schema_version``. Changing a field without bumping it
is the fastest way to make two runs silently non-comparable.
"""

from orchestrator.schemas.ai import (
    AIOptimizationRequest,
    AIRecommendation,
    RTLPatch,
)
from orchestrator.schemas.common import (
    FailureClass,
    Provenance,
    Quantity,
    Status,
    Verdict,
)
from orchestrator.schemas.comparison import MetricDelta, PPAComparison
from orchestrator.schemas.history import IterationRecord, OptimizationIterationHistory
from orchestrator.schemas.timing import (
    CriticalPathRecord,
    PathElement,
    QoRRecord,
    SourceLink,
    TimingAnalysisResult,
)
from orchestrator.schemas.verification import EquivalenceRelation, VerificationResult

__all__ = [
    "AIOptimizationRequest",
    "AIRecommendation",
    "CriticalPathRecord",
    "EquivalenceRelation",
    "FailureClass",
    "IterationRecord",
    "MetricDelta",
    "OptimizationIterationHistory",
    "PPAComparison",
    "PathElement",
    "Provenance",
    "QoRRecord",
    "Quantity",
    "RTLPatch",
    "SourceLink",
    "Status",
    "TimingAnalysisResult",
    "Verdict",
    "VerificationResult",
]
