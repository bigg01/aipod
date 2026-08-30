"""Bearer-token auth on the Streamable HTTP transport.

Auth is a transport concern, so these drive the real ASGI app with a TestClient
rather than the in-memory session used elsewhere.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from aipod.server import build_server
from aipod.server.auth import StaticTokenVerifier, build_auth, resolve_tokens

pytestmark = pytest.mark.anyio

TOKEN = "test-key-abc123"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_resolve_tokens_precedence(monkeypatch) -> None:
    monkeypatch.delenv("AIPOD_API_KEY", raising=False)
    monkeypatch.delenv("AIPOD_API_KEYS", raising=False)
    assert resolve_tokens() == set()

    monkeypatch.setenv("AIPOD_API_KEYS", "a, b ,c")
    assert resolve_tokens() == {"a", "b", "c"}

    monkeypatch.setenv("AIPOD_API_KEY", "single")
    assert resolve_tokens() == {"single"}

    assert resolve_tokens("explicit") == {"explicit"}  # arg wins over env


async def test_static_verifier_accepts_and_rejects() -> None:
    verifier = StaticTokenVerifier({TOKEN}, ["mcp:invoke"])
    ok = await verifier.verify_token(TOKEN)
    assert ok is not None and ok.scopes == ["mcp:invoke"]
    assert await verifier.verify_token("wrong") is None


def test_build_auth_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AIPOD_API_KEY", raising=False)
    monkeypatch.delenv("AIPOD_API_KEYS", raising=False)
    verifier, settings = build_auth(base_url="http://127.0.0.1:8000")
    assert verifier is None and settings is None


def _client(**kw) -> TestClient:
    app = build_server(host="127.0.0.1", port=8000, **kw).streamable_http_app()
    return TestClient(app)


def test_open_server_has_no_metadata_and_no_challenge() -> None:
    with _client() as c:
        assert c.get("/.well-known/oauth-protected-resource").status_code == 404


def test_protected_resource_metadata_is_public() -> None:
    with _client(auth_token=TOKEN) as c:
        r = c.get("/.well-known/oauth-protected-resource")
        assert r.status_code == 200
        body = r.json()
        assert body["authorization_servers"]
        assert "header" in body["bearer_methods_supported"]


def test_mcp_requires_bearer_token() -> None:
    with _client(auth_token=TOKEN) as c:
        headers = {"Accept": "application/json, text/event-stream"}
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

        r = c.post("/mcp", json=ping, headers=headers)
        assert r.status_code == 401
        assert "resource_metadata=" in r.headers.get("www-authenticate", "")

        r = c.post("/mcp", json=ping, headers={**headers, "Authorization": "Bearer nope"})
        assert r.status_code == 401


def test_valid_token_passes_auth() -> None:
    with _client(auth_token=TOKEN) as c:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        r = c.post(
            "/mcp",
            json=init,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {TOKEN}",
            },
        )
        assert r.status_code != 401  # past the auth layer; handshake itself succeeds
