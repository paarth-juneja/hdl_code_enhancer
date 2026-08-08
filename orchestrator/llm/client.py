"""The model client — the one place Nebula talks to a generative model.

Two implementations behind one interface:

* :class:`AnthropicClient` — the real call, using structured output and a single
  bounded repair. Requires the SDK and an API key.
* :class:`MockLLMClient` — returns scripted, schema-valid recommendations so the
  loop runs with no key and no network. Its patches are genuine cycle-exact
  transformations of the truth fixture, so the patcher and formal stages get
  real diffs to work on.

Neither client ever measures anything. Both return an
:class:`~orchestrator.schemas.ai.AIRecommendation`; whether it is any good is
decided later, by the tools.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from orchestrator.llm.prompts import (
    PROMPT_VERSION,
    REPAIR_TEMPLATE,
    SYSTEM_PROMPT,
    render_user_prompt,
)
from orchestrator.schemas.ai import (
    ActionKind,
    AIOptimizationRequest,
    AIRecommendation,
    PredictedEffect,
    RTLPatch,
)


class LLMClient(ABC):
    """A source of :class:`AIRecommendation` objects."""

    model: str = "abstract"

    @abstractmethod
    def propose(self, request: AIOptimizationRequest) -> tuple[AIRecommendation, str]:
        """Return a recommendation and the raw response text for the archive."""

    @abstractmethod
    def repair(
        self, request: AIOptimizationRequest, error: str
    ) -> tuple[AIRecommendation, str]:
        """One bounded retry after a validation failure."""


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------

#: Cycle-exact transformations of rtl/dsp_core.v, one per iteration. Each is a
#: real unified diff that applies to the baseline; the patcher and EQY stages
#: therefore run on genuine input even in mock mode. The final sum wire keeps the
#: name ``s7`` so downstream logic is untouched -- the transformation is local.
_BALANCED_TREE_DIFF = """\
--- a/rtl/dsp_core.v
+++ b/rtl/dsp_core.v
@@
     wire [AW-1:0] s0 = {{4{1'b0}}, a0};
-    wire [AW-1:0] s1 = s0 + {{4{1'b0}}, a1};
-    wire [AW-1:0] s2 = s1 + {{4{1'b0}}, a2};
-    wire [AW-1:0] s3 = s2 + {{4{1'b0}}, a3};
-    wire [AW-1:0] s4 = s3 + {{4{1'b0}}, a4};
-    wire [AW-1:0] s5 = s4 + {{4{1'b0}}, a5};
-    wire [AW-1:0] s6 = s5 + {{4{1'b0}}, a6};
-    wire [AW-1:0] s7 = s6 + {{4{1'b0}}, a7};
+    wire [AW-1:0] p0 = {{4{1'b0}}, a0} + {{4{1'b0}}, a1};
+    wire [AW-1:0] p1 = {{4{1'b0}}, a2} + {{4{1'b0}}, a3};
+    wire [AW-1:0] p2 = {{4{1'b0}}, a4} + {{4{1'b0}}, a5};
+    wire [AW-1:0] p3 = {{4{1'b0}}, a6} + {{4{1'b0}}, a7};
+    wire [AW-1:0] q0 = p0 + p1;
+    wire [AW-1:0] q1 = p2 + p3;
+    wire [AW-1:0] s7 = q0 + q1;
"""

_MUX_FLATTEN_DIFF = """\
--- a/rtl/dsp_core.v
+++ b/rtl/dsp_core.v
@@
     reg [AW-1:0] scaled;
     always @(*) begin
-        if (mode == 3'd0)
-            scaled = s7;
-        else if (mode == 3'd1)
-            scaled = s7 << 1;
-        else if (mode == 3'd2)
-            scaled = s7 << 2;
-        else if (mode == 3'd3)
-            scaled = s7 << 3;
-        else if (mode == 3'd4)
-            scaled = s7 >> 1;
-        else if (mode == 3'd5)
-            scaled = s7 >> 2;
-        else if (mode == 3'd6)
-            scaled = s7 - {{4{1'b0}}, a0};
-        else
-            scaled = {AW{1'b0}};
+        case (mode)
+            3'd0: scaled = s7;
+            3'd1: scaled = s7 << 1;
+            3'd2: scaled = s7 << 2;
+            3'd3: scaled = s7 << 3;
+            3'd4: scaled = s7 >> 1;
+            3'd5: scaled = s7 >> 2;
+            3'd6: scaled = s7 - {{4{1'b0}}, a0};
+            default: scaled = {AW{1'b0}};
+        endcase
     end
"""

# A third, distinct-but-plausible variant so cycle detection has something new
# to hash on the third iteration.
_STRENGTH_REDUCE_DIFF = """\
--- a/rtl/dsp_core.v
+++ b/rtl/dsp_core.v
@@
     wire [AW-1:0] s0 = {{4{1'b0}}, a0};
-    wire [AW-1:0] s1 = s0 + {{4{1'b0}}, a1};
-    wire [AW-1:0] s2 = s1 + {{4{1'b0}}, a2};
-    wire [AW-1:0] s3 = s2 + {{4{1'b0}}, a3};
+    wire [AW-1:0] s1 = s0 + {{4{1'b0}}, a1};
+    wire [AW-1:0] s2 = {{4{1'b0}}, a2} + {{4{1'b0}}, a3};
+    wire [AW-1:0] s3 = s1 + s2;
     wire [AW-1:0] s4 = s3 + {{4{1'b0}}, a4};
     wire [AW-1:0] s5 = s4 + {{4{1'b0}}, a5};
     wire [AW-1:0] s6 = s5 + {{4{1'b0}}, a6};
     wire [AW-1:0] s7 = s6 + {{4{1'b0}}, a7};
"""


@dataclass
class _MockPlan:
    transformation_type: str
    diff_text: str
    hypothesis: str
    rationale: str


_MOCK_PLANS = (
    _MockPlan(
        "balanced_adder_tree",
        _BALANCED_TREE_DIFF,
        "The accumulator sums eight terms in a linear chain (logic depth ~7 adders).",
        "Restructuring as a balanced tree reduces adder depth from 7 to 3 while "
        "computing the identical sum; addition is associative so this is cycle-exact.",
    ),
    _MockPlan(
        "mux_priority_to_parallel",
        _MUX_FLATTEN_DIFF,
        "The scale selector is a priority if/else chain over mutually exclusive modes.",
        "Rewriting as a case statement lets synthesis infer a parallel mux; behaviour "
        "is identical because the conditions were already mutually exclusive.",
    ),
    _MockPlan(
        "common_subexpression_extraction",
        _STRENGTH_REDUCE_DIFF,
        "The first four terms are summed strictly left to right.",
        "Pairing a2+a3 independently shortens the dependency chain; the total is "
        "unchanged.",
    ),
)


@dataclass
class MockLLMClient(LLMClient):
    """Deterministic client for offline runs and demos."""

    model: str = "mock"
    _iteration: int = 0
    plans: tuple[_MockPlan, ...] = field(default_factory=lambda: _MOCK_PLANS)

    def propose(self, request: AIOptimizationRequest) -> tuple[AIRecommendation, str]:
        self._iteration += 1
        plan = self.plans[(request.iteration - 1) % len(self.plans)]
        rec = self._recommendation(request, plan)
        raw = json.dumps(rec.model_dump(mode="json"), indent=2)
        return rec, raw

    def repair(
        self, request: AIOptimizationRequest, error: str
    ) -> tuple[AIRecommendation, str]:
        # The mock never produces malformed output, so a repair simply re-emits
        # the same valid recommendation.
        return self.propose(request)

    def _recommendation(
        self, request: AIOptimizationRequest, plan: _MockPlan
    ) -> AIRecommendation:
        patch = RTLPatch(
            patch_id=f"{request.request_id}_patch",
            recommendation_id=f"rec_{request.iteration:04d}",
            base_source_hash="",  # filled in by the patcher against the real source
            diff_text=plan.diff_text,
            changed_files=["rtl/dsp_core.v"],
            changed_line_count=plan.diff_text.count("\n+") + plan.diff_text.count("\n-"),
            declared_semantic_class="cycle_exact",
        )
        return AIRecommendation(
            recommendation_id=f"rec_{request.iteration:04d}",
            request_id=request.request_id,
            model_record_id=f"mock:{PROMPT_VERSION}",
            transformation_type=plan.transformation_type,
            action=ActionKind.PATCH,
            target={"module": "dsp_core", "file": "rtl/dsp_core.v"},
            observation_refs=[request.critical_path.path_id] if request.critical_path else [],
            hypothesis=plan.hypothesis,
            rationale=plan.rationale,
            predicted_effects=[
                PredictedEffect(metric="wns", direction="improve",
                                confidence_band="medium", basis="logic_depth_reduction"),
                PredictedEffect(metric="cell_area", direction="neutral",
                                confidence_band="low", basis="same_operator_count"),
            ],
            invariants_claimed=["latency_unchanged", "interface_unchanged", "cycle_exact"],
            risks=["Synthesis may already balance this; the change could be a no-op."],
            patch=patch,
            uncertainty=0.35,
        )


# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------


@dataclass
class AnthropicClient(LLMClient):
    """Real model client. Imported lazily so the mock path needs no SDK."""

    model: str = "claude-opus-5"
    max_output_tokens: int = 4096
    temperature: float = 0.2

    def _call(self, system: str, user: str) -> tuple[dict, str]:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - only on real path
            raise RuntimeError(
                "the anthropic SDK is required for --llm anthropic; "
                "install it or run with --llm mock"
            ) from exc

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(block.text for block in message.content if block.type == "text")
        payload = _extract_json(raw)
        return payload, raw

    def propose(self, request: AIOptimizationRequest) -> tuple[AIRecommendation, str]:
        payload, raw = self._call(SYSTEM_PROMPT, render_user_prompt(request))
        rec = _payload_to_recommendation(payload, request)
        return rec, raw

    def repair(
        self, request: AIOptimizationRequest, error: str
    ) -> tuple[AIRecommendation, str]:  # pragma: no cover - real path
        payload, raw = self._call(SYSTEM_PROMPT, REPAIR_TEMPLATE.format(error=error))
        rec = _payload_to_recommendation(payload, request)
        return rec, raw


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start : end + 1])


def _payload_to_recommendation(
    payload: dict, request: AIOptimizationRequest
) -> AIRecommendation:  # pragma: no cover - real path
    payload.setdefault("recommendation_id", f"rec_{request.iteration:04d}")
    payload.setdefault("request_id", request.request_id)
    return AIRecommendation(**payload)


def make_llm_client(name: str, **kwargs) -> LLMClient:
    """Construct a client by name: ``mock`` or ``anthropic``."""
    if name == "mock":
        return MockLLMClient()
    if name == "anthropic":
        return AnthropicClient(
            model=kwargs.get("model", "claude-opus-5"),
            max_output_tokens=kwargs.get("max_output_tokens", 4096),
            temperature=kwargs.get("temperature", 0.2),
        )
    raise ValueError(f"unknown llm client '{name}' (expected 'mock' or 'anthropic')")
