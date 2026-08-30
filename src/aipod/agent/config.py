"""Environment-driven configuration for `aipod agent`."""

from __future__ import annotations

import os

DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"


def mcp_url() -> str:
    """URL of the aipod MCP server this agent connects to."""

    return os.environ.get("AIPOD_MCP_URL", DEFAULT_MCP_URL)


def contract_url() -> str:
    """Best-effort URL of the server's contract (``/mcp`` -> ``/contract.json``)."""

    url = mcp_url()
    if url.endswith("/mcp"):
        return url[: -len("/mcp")] + "/contract.json"
    return url.rstrip("/") + "/contract.json"


def model_name() -> str | None:
    """pydantic-ai model id, e.g. ``anthropic:claude-haiku-4-5``. ``None`` if unset."""

    return os.environ.get("AIPOD_MODEL") or None


def mcp_token() -> str | None:
    """Bearer token for the MCP server, if it requires auth (``AIPOD_MCP_TOKEN``)."""

    return os.environ.get("AIPOD_MCP_TOKEN") or None
