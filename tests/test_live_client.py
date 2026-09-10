"""Live-client request contract without spending API tokens."""
import json
import os
import pytest
from types import SimpleNamespace

from orchestrator.llm.client import AnthropicClient, GroqClient
from orchestrator.llm.validator import validate_recommendation
from orchestrator.schemas.ai import AIOptimizationRequest, AIRecommendation
from orchestrator.schemas.common import Quantity
from orchestrator.schemas.timing import CriticalPathRecord


def test_schema_and_repair_context(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    calls = []
    raw = json.dumps({"recommendation_id": "rec", "request_id": "req",
                      "transformation_type": "none", "action": "abstain"})

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=raw)])

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(
        messages=SimpleNamespace(create=create)))
    request = AIOptimizationRequest(request_id="req", project_id="gcd",
                                    parent_candidate_id="baseline", iteration=1,
                                    facts={"measured_wns": -0.245})
    client = AnthropicClient()
    client.propose(request)
    client.repair(request, "missing explanation")
    assert '"$defs"' in calls[0]["system"]
    assert "temperature" not in calls[0]
    repair = calls[1]["messages"][0]["content"]
    assert "-0.245" in repair
    assert raw in repair
    assert "missing explanation" in repair


def test_missing_key_stops_before_baseline(monkeypatch, capsys):
    import orchestrator.cli as cli
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_load_local_env", lambda: None)
    assert cli.main(["--project", "nonexistent.yaml", "optimize", "--llm", "anthropic"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_groq_json_request_and_repair_context(monkeypatch):
    groq = pytest.importorskip("groq")
    calls = []
    raw = json.dumps({"recommendation_id": "rec", "request_id": "req",
                      "transformation_type": "none", "action": "abstain"})

    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=raw)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(groq, "Groq", lambda **kw: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    request = AIOptimizationRequest(request_id="req", project_id="gcd",
                                    parent_candidate_id="baseline", iteration=1,
                                    facts={"measured_wns": -0.245})
    client = GroqClient()
    client.propose(request)
    client.repair(request, "missing explanation")
    assert calls[0]["model"] == "openai/gpt-oss-120b"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert '"$defs"' in calls[0]["messages"][0]["content"]
    assert "request_id must be exactly: req" in calls[0]["messages"][1]["content"]
    repair = calls[1]["messages"][1]["content"]
    assert "-0.245" in repair
    assert raw in repair
    assert "missing explanation" in repair


def test_missing_groq_key_stops_before_baseline(monkeypatch, capsys):
    import orchestrator.cli as cli
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_load_local_env", lambda: None)
    assert cli.main(["--project", "nonexistent.yaml", "optimize", "--llm", "groq"]) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_local_env_loads_keys_without_overwriting_session(tmp_path, monkeypatch):
    from orchestrator.cli import _load_local_env

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# local credentials\nGROQ_API_KEY=from-file\nANTHROPIC_API_KEY='paid-key'\n"
    )
    monkeypatch.setenv("GROQ_API_KEY", "from-session")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    _load_local_env(env_file)

    assert os.environ["GROQ_API_KEY"] == "from-session"
    assert os.environ["ANTHROPIC_API_KEY"] == "paid-key"


def test_bad_patch_response_gets_one_repair_before_rejection():
    path = CriticalPathRecord(
        path_id="path_0001",
        analysis_id="analysis_1",
        rank=1,
        slack=Quantity(value=-0.1, unit="ns"),
    )
    request = AIOptimizationRequest(
        request_id="req",
        project_id="aes",
        parent_candidate_id="baseline",
        iteration=1,
        critical_path=path,
        allowed_transformations=["common_subexpression_extraction"],
    )
    recommendation = AIRecommendation(
        recommendation_id="rec",
        request_id="req",
        transformation_type="common_subexpression_extraction",
        action="patch",
        observation_refs=["path_id=path_0001"],
        patch=None,
    )

    first = validate_recommendation(recommendation, request)
    second = validate_recommendation(recommendation, request, already_repaired=True)
    assert first.outcome == "repairable"
    assert second.outcome == "ungrounded"
