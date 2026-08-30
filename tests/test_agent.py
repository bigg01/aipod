"""Unit tests for aipod agent mode. No running server and no API key needed."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from aipod.agent.runtime import build_agent, build_toolset
from aipod.agent.card import agent_card, governance
from aipod.agent.http import build_app


def test_agent_card_shape() -> None:
    card = agent_card("http://agentpod.example/")
    assert card["name"] == "aipod-agent"
    assert card["url"] == "http://agentpod.example/"
    skill_ids = {s["id"] for s in card["skills"]}
    assert {"ask", "poem", "summary", "weather"} == skill_ids

    dep = card["dependencies"][0]
    assert dep["type"] == "mcp-server" and dep["name"] == "aipod-server"
    assert dep["url"].endswith("/mcp")
    assert dep["contract"].endswith("/contract.json")


def test_governance_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPOD_DATA_CLASSIFICATION", "RESTRICTED")
    monkeypatch.setenv("AIPOD_REGULATORY_SCOPE", "GDPR, HIPAA")
    monkeypatch.setenv("AIPOD_OWNER", "ai-platform@example.com")
    monkeypatch.setenv("AIPOD_MODEL", "anthropic:claude-haiku-4-5")

    gov = governance()
    assert gov["dataClassification"] == "RESTRICTED"
    assert gov["regulatoryScope"] == ["GDPR", "HIPAA"]
    assert gov["modelProvider"] == "anthropic"

    card = agent_card("http://agentpod.example/")
    assert card["x-governance"]["dataClassification"] == "RESTRICTED"
    assert card["provider"]["organization"] == "ai-platform@example.com"


def test_contract_url_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPOD_MCP_URL", "https://mcppod.internal/mcp")
    card = agent_card("http://agentpod.example/")
    assert card["dependencies"][0]["contract"] == "https://mcppod.internal/contract.json"


def test_build_agent_has_mcp_toolset() -> None:
    agent = build_agent()  # no model configured -> still constructs
    assert agent is not None
    assert isinstance(build_toolset(), object)


def test_http_routes() -> None:
    client = TestClient(build_app())

    assert client.get("/health").json()["status"] == "ok"

    card = client.get("/.well-known/agent-card.json").json()
    assert card["name"] == "aipod-agent"
    assert client.get("/.well-known/agent.json").status_code == 200
    assert client.get("/").status_code == 200


def test_ask_without_model_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIPOD_MODEL", raising=False)
    client = TestClient(build_app())
    resp = client.post("/ask", json={"prompt": "hi"})
    assert resp.status_code == 503


def test_ask_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPOD_MODEL", "anthropic:claude-haiku-4-5")
    client = TestClient(build_app())
    assert client.post("/ask", json={}).status_code == 400
