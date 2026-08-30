"""The pydantic-ai agent (`aipod agent`).

In agent mode, aipod is an MCP *client*: it connects to a running aipod (server
mode) over the Streamable HTTP transport and exposes that server's tools to a
pydantic-ai `Agent`. The model is configured with `AIPOD_MODEL` (and the matching
provider API key); without one the agent can still describe itself but not run.
"""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset

from .config import mcp_token, mcp_url, model_name

INSTRUCTIONS = """\
You are aipod. You fulfil requests by calling tools exposed by a connected aipod
MCP server - poem writing, summarising, weather reports, and a set of
protocol-reference utilities. Prefer the server's tools over answering from
memory, and keep replies short.
"""


def build_toolset() -> MCPToolset:
    """A toolset bound to the configured aipod MCP endpoint.

    If ``AIPOD_MCP_TOKEN`` is set, it is sent as a bearer token so the agent can
    reach a server that requires auth.
    """

    token = mcp_token()
    if token:
        return MCPToolset(mcp_url(), headers={"Authorization": f"Bearer {token}"})
    return MCPToolset(mcp_url())


def build_agent(model: str | None = None) -> Agent:
    """Construct the agent. `model` overrides `AIPOD_MODEL`."""

    model = model or model_name()
    toolset = build_toolset()
    if model is None:
        # No model configured - usable for card / metadata, not for `.run()`.
        return Agent(toolsets=[toolset], instructions=INSTRUCTIONS)
    return Agent(model, toolsets=[toolset], instructions=INSTRUCTIONS)


async def ask(prompt: str, *, model: str | None = None) -> str:
    """Run a single request through the agent and return its text output."""

    agent = build_agent(model)
    async with agent:
        result = await agent.run(prompt)
    return result.output
