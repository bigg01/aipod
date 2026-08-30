"""Optional bearer-token authentication for the Streamable HTTP transport.

`aipod server` runs **open by default** (nothing to configure, every test and
tool works). Provide a key and it turns into an OAuth 2.1 *protected resource*:

* clients must send ``Authorization: Bearer <key>`` on every request to ``/mcp``;
* unauthenticated requests get ``401`` with a ``WWW-Authenticate`` header that
  points at ``/.well-known/oauth-protected-resource`` (RFC 9728);
* that metadata document advertises the authorization server and scopes.

The verifier here checks the token against a **static allow-list** (the keys you
configured) - the simplest thing that satisfies the spec's resource-server half
without standing up an identity provider. To test against a real OAuth 2.1
authorization server instead, set ``AIPOD_AUTH_ISSUER`` to its URL and replace
:class:`StaticTokenVerifier` with a JWT-validating verifier.

Configuration (any one enables auth):

===========================  ==================================================
``--auth-token <key>``       single key, highest precedence
``AIPOD_API_KEY``            single key
``AIPOD_API_KEYS``           comma-separated keys (rotation / per-client)
===========================  ==================================================

``AIPOD_AUTH_SCOPES``  - comma-separated scopes a caller must hold (default: none)
``AIPOD_AUTH_ISSUER``  - authorization-server URL for the metadata doc (default: this server)
``AIPOD_PUBLIC_URL``   - externally reachable base URL, if behind a proxy / ingress
"""

from __future__ import annotations

import os

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

_CLIENT_ID = "aipod-static-key"


def _csv(name: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def resolve_tokens(auth_token: str | None = None) -> set[str]:
    """Collect the configured keys, in precedence order. Empty set -> auth off."""

    if auth_token:
        return {auth_token.strip()}
    single = os.environ.get("AIPOD_API_KEY", "").strip()
    if single:
        return {single}
    return set(_csv("AIPOD_API_KEYS"))


def required_scopes() -> list[str]:
    return _csv("AIPOD_AUTH_SCOPES")


class StaticTokenVerifier(TokenVerifier):
    """Accept a fixed set of opaque tokens; grant them the configured scopes."""

    def __init__(self, tokens: set[str], scopes: list[str]) -> None:
        self._tokens = set(tokens)
        self._scopes = list(scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        if token not in self._tokens:
            return None
        return AccessToken(
            token=token,
            client_id=_CLIENT_ID,
            scopes=self._scopes,
            expires_at=None,
        )


def build_auth(
    *, auth_token: str | None = None, base_url: str
) -> tuple[StaticTokenVerifier | None, AuthSettings | None]:
    """Return ``(token_verifier, auth_settings)`` for FastMCP, or ``(None, None)``."""

    tokens = resolve_tokens(auth_token)
    if not tokens:
        return None, None

    public_url = os.environ.get("AIPOD_PUBLIC_URL", "").strip() or base_url
    issuer = os.environ.get("AIPOD_AUTH_ISSUER", "").strip() or public_url
    scopes = required_scopes()

    settings = AuthSettings(
        issuer_url=issuer,
        resource_server_url=public_url,
        required_scopes=scopes or None,
    )
    return StaticTokenVerifier(tokens, scopes), settings


def auth_summary(*, auth_token: str | None = None, base_url: str) -> dict[str, object]:
    """The ``security`` block for the service contract."""

    tokens = resolve_tokens(auth_token)
    if not tokens:
        return {
            "scheme": "none",
            "note": "Server is open. Set --auth-token / AIPOD_API_KEY(S) to require a bearer token.",
        }

    public_url = os.environ.get("AIPOD_PUBLIC_URL", "").strip() or base_url
    issuer = os.environ.get("AIPOD_AUTH_ISSUER", "").strip() or public_url
    return {
        "scheme": "bearer",
        "type": "oauth2.1-protected-resource",
        "tokenFormat": "opaque static key, presented as an OAuth 2.1 Bearer token",
        "header": "Authorization: Bearer <key>",
        "keyCount": len(tokens),
        "keySources": ["--auth-token", "AIPOD_API_KEY", "AIPOD_API_KEYS"],
        "requiredScopes": required_scopes(),
        "authorizationServers": [issuer],
        "protectedResourceMetadata": f"{public_url.rstrip('/')}/.well-known/oauth-protected-resource",
        "note": (
            "Tokens are checked against a static allow-list. Point AIPOD_AUTH_ISSUER "
            "at a real authorization server and swap in a JWT verifier for full OAuth 2.1."
        ),
    }
