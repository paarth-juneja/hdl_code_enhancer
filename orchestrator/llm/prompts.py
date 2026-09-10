"""Versioned prompt templates.

The prompt is advisory. It tells the model the rules, but it is not the thing
that enforces them — :mod:`orchestrator.patcher` and
:mod:`orchestrator.llm.validator` are. That separation is deliberate: a prompt
can be talked around, a schema check and a protected-path check cannot.

``PROMPT_VERSION`` is recorded on every recommendation so a result can be traced
to the exact instructions that produced it.
"""

from __future__ import annotations

import json

from orchestrator.schemas.ai import AIOptimizationRequest

PROMPT_VERSION = "1.0.0"

SYSTEM_PROMPT = """\
You are a hardware RTL optimization assistant operating inside a tool-grounded
system called Nebula. Your role is strictly bounded.

You MAY:
- Read the single critical timing path and the bounded RTL slice you are given.
- Propose ONE small, equivalence-preserving RTL transformation as a unified diff.
- Decline (action "abstain") when no safe change is available.

You MAY NOT:
- Claim any change succeeded. You never see measurements and never set a verdict.
- Touch clock generation, reset, clock-domain-crossing, or interface logic.
- Change latency, add or remove pipeline stages, or alter cycle behaviour.
- Exceed the stated change budget or edit any file outside the allowlist.

Every change you propose must be provably equivalent to the original under a
cycle-exact relation. If you are not confident a change is cycle-exact, abstain.
A correct abstention is a good outcome; a wrong "improvement" is the worst
outcome, because a downstream formal check will reject it and the iteration is
wasted.

Respond with a single JSON object matching the AIRecommendation schema. Cite the
path you were given in observation_refs. Put predictions in predicted_effects,
never in the rationale as if they were facts.
"""

USER_TEMPLATE = """\
## Exact response identifiers and patch rules
- request_id must be exactly: {request_id}
- observation_refs must contain exactly this raw path ID, without a label or prefix: {path_id}
- A patch must use standard unified-diff text beginning with `--- a/<path>` and
  `+++ b/<path>`. Do not use `*** Begin Patch` or `*** Update File` markers.
- Patch paths and changed_files must exactly match a file path shown in RTL context.

## Timing facts (measured by tools -- treat as ground truth)
{facts}

## Critical path
{path}

## RTL context (the only source you may edit)
{rtl_context}

## Invariants that must hold
{invariants}

## Allowed transformations
{allowed}

## Forbidden changes
{forbidden}

## Change budget
{budget}

## Previous attempts and their MEASURED outcomes
{previous}

Propose one transformation as an AIRecommendation JSON object, or abstain.
"""

REPAIR_TEMPLATE = """\
Your previous response could not be accepted for this reason:

{error}

Return a corrected AIRecommendation JSON object. Do not introduce new design
facts or a different transformation; only fix the structural problem above. If
you cannot produce a valid object, abstain.
"""


def render_user_prompt(request: AIOptimizationRequest) -> str:
    """Fill the user template from a request object."""
    path_text = "none"
    if request.critical_path is not None:
        cp = request.critical_path
        path_text = (
            f"path_id={cp.path_id} slack={cp.slack} depth={cp.logic_depth} "
            f"start={cp.startpoint.get('object')} end={cp.endpoint.get('object')} "
            f"launch={cp.launch_clock} capture={cp.capture_clock} "
            f"relationship={cp.relationship}"
        )

    context_text = "none"
    if request.rtl_context:
        blocks = [
            f"--- {c.file}:{c.line_start}-{c.line_end} ---\n{c.text}"
            for c in request.rtl_context
        ]
        context_text = "\n\n".join(blocks)

    previous_text = "none"
    if request.previous_attempts:
        previous_text = "\n".join(
            f"- {a.transformation_type}: {a.verdict} ({a.failure_class}) "
            f"delta={a.measured_delta}"
            for a in request.previous_attempts
        )

    return USER_TEMPLATE.format(
        request_id=request.request_id,
        path_id=(request.critical_path.path_id if request.critical_path else "none"),
        facts=json.dumps(request.facts, indent=2),
        path=path_text,
        rtl_context=context_text,
        invariants=json.dumps(request.invariants, indent=2),
        allowed=", ".join(request.allowed_transformations),
        forbidden=", ".join(request.forbidden_changes),
        budget=json.dumps(request.change_budget),
        previous=previous_text,
    )
