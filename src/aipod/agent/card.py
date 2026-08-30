"""The agent card - `aipod agent`'s discovery document.

An A2A-style ``AgentCard`` served at ``/.well-known/agent-card.json``. It says
what the agent is, where to reach it, which skills it offers, what it depends on
(an aipod MCP server + its contract), and - in the non-standard ``x-governance``
block - the metadata a registry / router / security review needs to gate it.
"""

from __future__ import annotations

from typing import Any

from .. import __version__
from ..governance import base as _governance_base
from .config import contract_url, mcp_url, model_name

_SKILLS: list[dict[str, Any]] = [
    {
        "id": "ask",
        "name": "Ask",
        "description": "Answer a free-form request, calling aipod-server tools as needed.",
        "tags": ["general", "tool-use", "mcp"],
        "examples": ["Summarise this and then write a poem about the result."],
    },
    {
        "id": "poem",
        "name": "Poem",
        "description": "Write a short rhyming poem (delegates to the server's `poet` tool).",
        "tags": ["text", "creative"],
        "examples": ["Write a poem about autumn rain."],
    },
    {
        "id": "summary",
        "name": "Summary",
        "description": "Summarise a passage into headline / summary / key points (`summarize` tool).",
        "tags": ["summarisation", "structured-output"],
        "examples": ["Summarise the following article: ..."],
    },
    {
        "id": "weather",
        "name": "Weather",
        "description": "Narrative forecast for a demo city (`weather_report` tool).",
        "tags": ["narrative"],
        "examples": ["What's the forecast for Chicago?"],
    },
]


def governance() -> dict[str, Any]:
    """Shared governance labels plus the agent's data-egress facts."""

    gov = _governance_base()
    gov["modelProvider"] = (model_name() or "unset").split(":")[0]
    gov["dataEgress"] = {
        "modelProvider": model_name() or "unset",
        "downstreamServices": [mcp_url()],
        "note": (
            "Prompt content is sent to the configured model provider and to the "
            "aipod MCP server. See that server's /contract.json for its own "
            "egress (its sampling tools call back to this agent's model)."
        ),
    }
    return gov


def agent_card(base_url: str) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    gov = governance()
    return {
        "protocolVersion": "0.3.0",
        "name": "aipod-agent",
        "description": (
            "A pydantic-ai agent that fulfils requests by calling tools from a connected "
            "aipod MCP server."
        ),
        "version": __version__,
        "url": f"{base_url}/",
        "preferredTransport": "HTTP+JSON",
        "additionalInterfaces": [
            {"transport": "HTTP+JSON", "url": f"{base_url}/ask"},
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": _SKILLS,
        "documentationUrl": f"{base_url}/",
        "provider": {"organization": gov["owner"], "url": f"{base_url}/"},
        # What this agent needs at runtime to actually serve its skills.
        "dependencies": [
            {
                "type": "mcp-server",
                "name": "aipod-server",
                "url": mcp_url(),
                "contract": contract_url(),
            }
        ],
        "x-governance": gov,
    }
