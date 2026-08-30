"""pydantic-ai agents used by the AI-backed tools.

Every agent gets its model at call time from :func:`sampling_model`, which wraps
the live MCP session in a ``MCPSamplingModel``. That means the *client* connected
to this server provides the LLM (via MCP sampling) and the server itself needs no
provider credentials.

To run these against a provider directly instead, pass e.g.
``model="anthropic:claude-haiku-4-5"`` to ``agent.run(...)`` (and set the
matching API key in the environment).
"""

from __future__ import annotations

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.mcp_sampling import MCPSamplingModel


class Summary(BaseModel):
    """Structured result produced by the `summarize` tool."""

    headline: str = Field(description="A single sentence capturing the gist")
    summary: str = Field(description="A short paragraph, 2-4 sentences")
    key_points: list[str] = Field(description="Three to five bullet takeaways")


poet_agent = Agent(
    instructions="You are a playful poet. Reply with a short poem of 4-8 lines that rhymes.",
)

summarizer_agent = Agent(
    output_type=Summary,
    instructions=(
        "Summarise the user's text faithfully and concisely; do not invent facts. "
        "Respond with a JSON object holding `headline`, `summary`, and `key_points` "
        "(a list of 3-5 short strings)."
    ),
)

weather_reporter_agent = Agent(
    instructions=(
        "You are an upbeat TV weather presenter. Given a set of readings, write "
        "2-3 lively sentences describing the forecast for a general audience."
    ),
)

hero_biographer_agent = Agent(
    instructions=(
        "You write concise comic-book character bios. Given a hero's name, teams, "
        "powers, and origin, write 2-3 sentences in an in-universe encyclopaedic "
        "voice. Use only the facts provided; do not invent new ones."
    ),
)

postmortem_agent = Agent(
    instructions=(
        "You are an SRE writing a blameless incident postmortem. Given the facts "
        "of an incident, produce a short write-up with three labelled parts: "
        "Impact, Likely trigger, and Follow-up actions (2-3 bullet points). "
        "Stay factual, avoid blame, and use only the information provided."
    ),
)


def sampling_model(ctx: Context) -> MCPSamplingModel:
    """Build a model that routes LLM calls back through the connected MCP client."""

    return MCPSamplingModel(session=ctx.session)
