"""Shared demo data, models, and constants used across the server."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Location = Literal["New York", "Chicago", "Los Angeles"]
ResourceKind = Literal["text", "blob"]


class Weather(BaseModel):
    """Structured weather payload returned by the weather tools."""

    location: str = Field(description="City the reading is for")
    temperature: float = Field(description="Temperature in degrees Celsius")
    conditions: str = Field(description="Human readable sky conditions")
    humidity: int = Field(description="Relative humidity as a percentage", ge=0, le=100)


WEATHER: dict[str, Weather] = {
    "New York": Weather(location="New York", temperature=19.0, conditions="Cloudy", humidity=82),
    "Chicago": Weather(location="Chicago", temperature=14.0, conditions="Light rain", humidity=77),
    "Los Angeles": Weather(location="Los Angeles", temperature=27.0, conditions="Sunny", humidity=41),
}

# A 1x1 transparent PNG, base64 encoded. Small enough to inline, real enough to render.
MCP_TINY_IMAGE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

LOG_LEVELS: tuple[str, ...] = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)

DEPARTMENTS: tuple[str, ...] = ("Engineering", "Sales", "Marketing", "Support")

TEAMS: dict[str, list[str]] = {
    "Engineering": ["Alice", "Bjorn", "Chandra"],
    "Sales": ["Dara", "Eli", "Farida"],
    "Marketing": ["Gwen", "Hassan", "Ivy"],
    "Support": ["Jonas", "Keiko", "Lamar"],
}

DYNAMIC_URI = "demo://resource/dynamic/{kind}/{resource_id}"
STATIC_INSTRUCTIONS_URI = "demo://resource/static/instructions.md"
STATIC_FEATURES_URI = "demo://resource/static/features.md"


def dynamic_uri(kind: ResourceKind, resource_id: int | str) -> str:
    return f"demo://resource/dynamic/{kind}/{resource_id}"


def text_body(resource_id: int) -> str:
    stamp = datetime.now().strftime("%H:%M:%S")
    return f"Resource {resource_id}: a plaintext resource generated at {stamp}."


def blob_body(resource_id: int) -> bytes:
    stamp = datetime.now().strftime("%H:%M:%S")
    return f"Resource {resource_id}: a binary blob generated at {stamp}.".encode()


def blob_body_b64(resource_id: int) -> str:
    return base64.b64encode(blob_body(resource_id)).decode()


INSTRUCTIONS = """\
# aipod (server mode) - a reference MCP server that exercises every MCP feature

This server exercises every feature of the Model Context Protocol so client
authors have one endpoint to test against: tools, structured output, resources,
resource templates, prompts, argument completion, resource subscriptions,
progress reporting, and logging.

Three of the tools (`poet`, `summarize`, `weather_report`) are backed by
pydantic-ai agents that obtain their model through **MCP sampling** - they call
back into the connected client's LLM, so the server needs no API keys of its own.
"""

FEATURES_MD = """\
# Features

## Tools
- `echo` - echoes the input message
- `add` - adds two numbers
- `get_tiny_image` - returns text interleaved with an image block
- `get_annotated_message` - content blocks with priority / audience annotations
- `get_structured_weather` - returns a typed `Weather` object (output schema)
- `get_resource_reference` - returns an embedded resource block
- `get_resource_links` - returns resource_link blocks
- `trigger_long_running_operation` - reports incremental progress
- `toggle_simulated_logging` - starts/stops periodic multi-level log messages
- `toggle_subscriber_updates` - starts/stops `resources/updated` notifications
- `poet` - pydantic-ai agent, rhyming poem, model via MCP sampling
- `summarize` - pydantic-ai agent, structured `Summary` output via MCP sampling
- `weather_report` - pydantic-ai agent, narrative forecast via MCP sampling
- `list_heroes` / `get_hero` - Marvel roster, typed `HeroRoster` / `Hero` output
- `find_heroes_by_power` - roster search by power substring
- `assemble_team` - deterministic team pick for a described threat
- `hero_bio` - pydantic-ai agent, in-universe bio via MCP sampling

## SRE / IT-application tools
- `list_services` / `get_service` - service catalogue (tier, team, deps, SLOs)
- `check_service_health` - synthetic metrics + SLO + open incidents -> verdict
- `error_budget` - remaining SLO error budget and burn rate
- `search_logs` - deterministic synthetic log search by substring / level
- `list_incidents` / `open_incident` / `update_incident` - incident register (mutates state)
- `list_deployments` / `rollback_deployment` - deployment history (rollback mutates state)
- `get_oncall` - current on-call engineer + escalation order
- `get_runbook` - runbook entries for a service, optionally by symptom
- `incident_postmortem` - pydantic-ai agent, blameless postmortem via MCP sampling

## Resources
- `demo://resource/dynamic/text/{resource_id}` - templated text resource
- `demo://resource/dynamic/blob/{resource_id}` - templated binary resource
- `hero://roster/{codename}` - one hero as JSON (completion on `codename`)
- `service://catalog/{name}` - one service's catalogue entry as JSON
- `runbook://{service}` - a service's runbook as Markdown
- `demo://resource/static/instructions.md`
- `demo://resource/static/features.md`

## Prompts
- `simple_prompt` - no arguments
- `args_prompt` - required `city`, optional `state`
- `completable_prompt` - `department` then `name`, with argument completion
- `resource_prompt` - embeds a dynamic resource in the message list

## Other
- Argument completion for prompts and the resource templates
- Resource subscribe / unsubscribe + `notifications/resources/updated`
- `logging/setLevel` is honoured by the simulated logger
- Optional bearer-token auth: run with `--auth-token` / `AIPOD_API_KEY` and the
  `/mcp` route becomes an OAuth 2.1 protected resource (`401` +
  `WWW-Authenticate`, `/.well-known/oauth-protected-resource` metadata)
"""
