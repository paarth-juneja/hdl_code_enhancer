"""The generative-AI layer.

This is the only part of Nebula that talks to a model, and its entire output
surface is one bounded unified diff. The request builder decides what the model
may see; the client makes the call; the validator decides whether the response
is admissible. Nothing here can measure a result or set a verdict — those live
in :mod:`orchestrator.policy`, which reads only tool output.
"""

from orchestrator.llm.client import LLMClient, make_llm_client
from orchestrator.llm.request_builder import build_request
from orchestrator.llm.validator import ValidationOutcome, validate_recommendation

__all__ = [
    "LLMClient",
    "ValidationOutcome",
    "build_request",
    "make_llm_client",
    "validate_recommendation",
]
