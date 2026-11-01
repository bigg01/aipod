"""Foundry adapter integration without Azure or a model connection."""

import pytest
from starlette.testclient import TestClient

pytest.importorskip("azure.ai.agentserver.invocations")

from aipod.agent.foundry import build_host


def test_foundry_invocation_and_context(monkeypatch):
    from azure.ai.agentserver.core import get_request_context

    monkeypatch.setenv("AIPOD_MODEL", "test")
    monkeypatch.setenv("FOUNDRY_AGENT_SESSION_ID", "session-1")
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    async def fake_invoke(prompt):
        assert prompt == "hello"
        context = get_request_context()
        assert context.session_id == "session-1"
        assert context.call_id == "call-1"
        assert context.user_id == "user-1"
        return "world"

    monkeypatch.setattr("aipod.agent.foundry.invoke", fake_invoke)
    with TestClient(build_host()) as client:
        assert client.get("/readiness").status_code == 200
        response = client.post(
            "/invocations", json={"prompt": "hello"},
            headers={"x-agent-foundry-call-id": "call-1", "x-agent-user-id": "user-1"},
        )
        assert response.status_code == 200
        assert response.json() == {"output": "world"}
        assert response.headers["x-agent-session-id"] == "session-1"
        for body in ({}, [], {"prompt": " "}, {"prompt": 42}):
            assert client.post("/invocations", json=body).status_code == 400
        assert client.post("/invocations", content="{").status_code == 400


def test_foundry_missing_model_fails_before_readiness(monkeypatch):
    monkeypatch.delenv("AIPOD_MODEL", raising=False)
    monkeypatch.delenv("FOUNDRY_MODEL_NAME", raising=False)
    with pytest.raises(ValueError, match="FOUNDRY_MODEL_NAME"):
        build_host()
