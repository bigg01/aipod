"""The **service contract** - the machine-readable MCP interface `aipod server`
promises.

Derived from the live server so it never drifts: every tool's input/output JSON
Schema, the resource URIs and templates, the prompt arguments, which tools need
the client to support MCP sampling, and a ``governance`` block (data
classification, residency, regulatory scope, egress).

The companion *agent card* - the discovery document - is produced by the other
mode (`aipod agent`). See ``docs/blog/contracts-and-agent-cards.md`` for why
they are separate documents.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import __version__
from ..governance import base as _governance_base
from .auth import auth_summary

MCP_PROTOCOL_VERSION = "2025-06-18"

# Tools whose model is supplied by the connected client via MCP sampling.
# Calling these forwards prompt content to the *client's* model - a data-egress
# boundary that governance reviews care about.
SAMPLING_TOOLS = {"poet", "summarize", "weather_report", "hero_bio", "incident_postmortem"}

# Tools that mutate server-side state rather than being pure reads.
SIDE_EFFECT_TOOLS = {
    "toggle_simulated_logging",
    "toggle_subscriber_updates",
    "trigger_long_running_operation",
    "open_incident",
    "update_incident",
    "rollback_deployment",
}


def governance() -> dict[str, Any]:
    """Shared governance labels plus the server's data-egress facts."""

    gov = _governance_base()
    gov["dataEgress"] = {
        "clientModelViaSampling": sorted(SAMPLING_TOOLS),
        "externalNetworkCalls": [],
        "note": (
            "The sampling tools forward prompt content to the connected client's "
            "model. No other tool makes outbound calls."
        ),
    }
    return gov


async def service_contract(
    mcp: FastMCP, *, base_url: str | None = None, auth_token: str | None = None
) -> dict[str, Any]:
    """Introspect the live server and return its full MCP interface contract."""

    tools = await mcp.list_tools()
    prompts = await mcp.list_prompts()
    resources = await mcp.list_resources()
    templates = await mcp.list_resource_templates()

    transport: dict[str, Any] = {"stdio": True, "streamableHttp": "/mcp"}
    if base_url is not None:
        transport["endpoint"] = f"{base_url.rstrip('/')}/mcp"

    security = auth_summary(auth_token=auth_token, base_url=(base_url or "http://127.0.0.1:8000"))

    return {
        "service": "aipod",
        "mode": "server",
        "version": __version__,
        "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
        "transport": transport,
        "security": security,
        "clientRequirements": {
            "authentication": {
                "required": security["scheme"] != "none",
                "scheme": security["scheme"],
                "note": (
                    "Send Authorization: Bearer <key>. See security.protectedResourceMetadata."
                    if security["scheme"] != "none"
                    else "None. The server accepts unauthenticated requests."
                ),
            },
            "sampling": {
                "required": False,
                "requiredBy": sorted(SAMPLING_TOOLS),
                "note": "Only the pydantic-ai tools need sampling; every other feature works without it.",
            },
        },
        "governance": governance(),
        "tools": [
            {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
                "outputSchema": tool.outputSchema,
                "requiresSampling": tool.name in SAMPLING_TOOLS,
                # Governance facets, per call:
                "sideEffects": tool.name in SIDE_EFFECT_TOOLS,
                "dataEgress": (
                    "client-model-via-sampling" if tool.name in SAMPLING_TOOLS else "none"
                ),
            }
            for tool in tools
        ],
        "resources": {
            "static": [
                {
                    "uri": str(resource.uri),
                    "name": resource.name,
                    "description": resource.description,
                    "mimeType": resource.mimeType,
                }
                for resource in resources
            ],
            "templates": [
                {
                    "uriTemplate": template.uriTemplate,
                    "name": template.name,
                    "description": template.description,
                    "mimeType": template.mimeType,
                }
                for template in templates
            ],
        },
        "prompts": [
            {
                "name": prompt.name,
                "title": prompt.title,
                "description": prompt.description,
                "arguments": [
                    {
                        "name": arg.name,
                        "description": arg.description,
                        "required": arg.required,
                    }
                    for arg in (prompt.arguments or [])
                ],
            }
            for prompt in prompts
        ],
        "capabilities": [
            "tools",
            "resources",
            "resources.subscribe",
            "resources.templates",
            "prompts",
            "completions",
            "logging",
            "progress",
        ],
    }
