"""Builds the FastMCP instance that implements every MCP feature."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.types import (
    BlobResourceContents,
    CompletionArgument,
    CompletionContext,
    Completion,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    LoggingLevel,
    PromptReference,
    ResourceLink,
    ResourceTemplateReference,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl

from .. import __version__
from .. import telemetry
from . import data
from . import heroes
from . import sampling_tools as agents
from . import sre
from .auth import build_auth
from .landing import LANDING_HTML

# --------------------------------------------------------------------------- #
# Per-connection background state (simulated logging + subscription updates)
# --------------------------------------------------------------------------- #

_bg_tasks: dict[tuple[int, str], asyncio.Task[None]] = {}
_subscriptions: set[str] = set()
_client_log_level: dict[str, str] = {"value": "debug"}

_LEVEL_ORDER = {name: i for i, name in enumerate(data.LOG_LEVELS)}


def _level_enabled(level: str) -> bool:
    return _LEVEL_ORDER.get(level, 0) >= _LEVEL_ORDER.get(_client_log_level["value"], 0)


def _cancel_all_bg() -> None:
    for task in list(_bg_tasks.values()):
        task.cancel()
    _bg_tasks.clear()


# --------------------------------------------------------------------------- #
# Server construction
# --------------------------------------------------------------------------- #


def build_server(
    *, host: str = "127.0.0.1", port: int = 8000, auth_token: str | None = None
) -> FastMCP:
    token_verifier, auth_settings = build_auth(
        auth_token=auth_token, base_url=f"http://{host}:{port}"
    )

    mcp = FastMCP(
        "aipod",
        instructions=data.INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path="/mcp",
        token_verifier=token_verifier,
        auth=auth_settings,
    )

    _register_tools(mcp)
    _register_ai_tools(mcp)
    _register_hero_tools(mcp)
    _register_sre_tools(mcp, sre.SREState())
    _register_resources(mcp)
    _register_prompts(mcp)
    _register_completion(mcp)
    _register_low_level_handlers(mcp)
    _register_http_routes(mcp)
    telemetry.instrument_fastmcp(
        mcp, subscriptions=_subscriptions, background_tasks=_bg_tasks
    )
    return mcp


# --------------------------------------------------------------------------- #
# Plain tools
# --------------------------------------------------------------------------- #


def _register_tools(mcp: FastMCP) -> None:
    @mcp.tool(title="Echo", description="Echo the input message back to the caller.")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    @mcp.tool(title="Add", description="Add two numbers and describe the result.")
    def add(a: float, b: float) -> str:
        return f"The sum of {a} and {b} is {a + b}."

    @mcp.tool(
        title="Get tiny image",
        description="Return text interleaved with an image content block.",
        structured_output=False,
    )
    def get_tiny_image() -> list[ContentBlock]:
        return [
            TextContent(type="text", text="Here is a tiny PNG:"),
            ImageContent(type="image", data=data.MCP_TINY_IMAGE, mimeType="image/png"),
            TextContent(type="text", text="That was the image."),
        ]

    @mcp.tool(
        title="Get annotated message",
        description="Return content blocks carrying priority and audience annotations.",
        structured_output=False,
    )
    def get_annotated_message(
        message_type: Literal["error", "success", "debug"],
        include_image: bool = False,
    ) -> list[ContentBlock]:
        table = {
            "error": ("Error: operation failed", 1.0, ["user", "assistant"]),
            "success": ("Operation completed successfully", 0.7, ["user"]),
            "debug": ("Debug: cache hit ratio 0.95, latency 150ms", 0.3, ["assistant"]),
        }
        text, priority, audience = table[message_type]
        blocks: list[ContentBlock] = [
            TextContent(
                type="text",
                text=text,
                annotations={"priority": priority, "audience": audience},
            )
        ]
        if include_image:
            blocks.append(
                ImageContent(
                    type="image",
                    data=data.MCP_TINY_IMAGE,
                    mimeType="image/png",
                    annotations={"priority": 0.5, "audience": ["user"]},
                )
            )
        return blocks

    @mcp.tool(
        title="Get structured weather",
        description="Return a typed Weather object so the client can validate it against the output schema.",
    )
    def get_structured_weather(location: data.Location = data.DEFAULT_LOCATION) -> data.Weather:
        return data.WEATHER[location]

    @mcp.tool(
        title="Get resource reference",
        description="Return an embedded resource content block for a dynamic resource.",
        structured_output=False,
    )
    def get_resource_reference(resource_id: int = 1, kind: data.ResourceKind = "text") -> list[ContentBlock]:
        uri = data.dynamic_uri(kind, resource_id)
        if kind == "blob":
            resource: TextResourceContents | BlobResourceContents = BlobResourceContents(
                uri=AnyUrl(uri),
                mimeType="application/octet-stream",
                blob=data.blob_body_b64(resource_id),
            )
        else:
            resource = TextResourceContents(
                uri=AnyUrl(uri), mimeType="text/plain", text=data.text_body(resource_id)
            )
        return [
            TextContent(type="text", text=f"Resource reference for #{resource_id}:"),
            EmbeddedResource(type="resource", resource=resource),
            TextContent(type="text", text=f"You can read it again at {uri}"),
        ]

    @mcp.tool(
        title="Get resource links",
        description="Return between 1 and 10 resource_link blocks pointing at dynamic resources.",
        structured_output=False,
    )
    def get_resource_links(count: int = 3) -> list[ContentBlock]:
        count = max(1, min(count, 10))
        blocks: list[ContentBlock] = [
            TextContent(type="text", text=f"Here are {count} resource links:")
        ]
        for i in range(1, count + 1):
            kind: data.ResourceKind = "text" if i % 2 == 0 else "blob"
            blocks.append(
                ResourceLink(
                    type="resource_link",
                    uri=AnyUrl(data.dynamic_uri(kind, i)),
                    name=f"{kind.title()} resource {i}",
                    description=f"A dynamic {kind} resource",
                    mimeType="text/plain" if kind == "text" else "application/octet-stream",
                )
            )
        return blocks

    @mcp.tool(
        title="Trigger long running operation",
        description="Run a fake multi-step job, emitting a progress notification per step.",
    )
    async def trigger_long_running_operation(
        ctx: Context, steps: int = 5, step_seconds: float = 1.0
    ) -> str:
        steps = max(1, min(steps, 20))
        for i in range(1, steps + 1):
            await asyncio.sleep(step_seconds)
            await ctx.report_progress(progress=i, total=steps, message=f"Step {i}/{steps}")
        return f"Completed {steps} steps in ~{steps * step_seconds:.0f}s."

    @mcp.tool(
        title="Toggle simulated logging",
        description="Start or stop a background task that emits a random-level log message every 5s.",
    )
    async def toggle_simulated_logging(ctx: Context) -> str:
        session = ctx.session
        key = (id(session), "logging")
        existing = _bg_tasks.pop(key, None)
        if existing is not None:
            existing.cancel()
            return "Stopped simulated logging."

        async def loop() -> None:
            try:
                while True:
                    level = random.choice(data.LOG_LEVELS)
                    if _level_enabled(level):
                        await session.send_log_message(
                            level=level,  # type: ignore[arg-type]
                            data=f"{level}-level message at {datetime.now():%H:%M:%S}",
                            logger="aipod",
                        )
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass

        _bg_tasks[key] = asyncio.create_task(loop())
        return "Started simulated logging (every 5s, honouring the client's log level)."

    @mcp.tool(
        title="Toggle subscriber updates",
        description="Start or stop a background task that emits resources/updated for every subscribed resource.",
    )
    async def toggle_subscriber_updates(ctx: Context) -> str:
        session = ctx.session
        key = (id(session), "subs")
        existing = _bg_tasks.pop(key, None)
        if existing is not None:
            existing.cancel()
            return "Stopped simulated resource updates."

        async def loop() -> None:
            try:
                while True:
                    targets = _subscriptions or {data.dynamic_uri("text", 1)}
                    for uri in list(targets):
                        await session.send_resource_updated(AnyUrl(uri))
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                pass

        _bg_tasks[key] = asyncio.create_task(loop())
        return "Started simulated resource updates (every 5s for subscribed resources)."


# --------------------------------------------------------------------------- #
# pydantic-ai backed tools (model supplied by the client via MCP sampling)
# --------------------------------------------------------------------------- #


def _register_ai_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Poet (pydantic-ai + sampling)",
        description="A pydantic-ai agent writes a short rhyming poem; the LLM comes from the client via MCP sampling.",
    )
    async def poet(ctx: Context, theme: str) -> str:
        result = await agents.poet_agent.run(
            f"Write a short poem about {theme}.", model=agents.sampling_model(ctx)
        )
        return result.output

    @mcp.tool(
        title="Summarize (pydantic-ai structured output + sampling)",
        description="A pydantic-ai agent returns a structured Summary; the LLM comes from the client via MCP sampling.",
    )
    async def summarize(ctx: Context, text: str) -> agents.Summary:
        result = await agents.summarizer_agent.run(text, model=agents.sampling_model(ctx))
        return result.output

    @mcp.tool(
        title="Weather report (pydantic-ai + sampling)",
        description="A pydantic-ai agent turns the structured readings for a city into a short spoken-style forecast.",
    )
    async def weather_report(ctx: Context, location: data.Location = data.DEFAULT_LOCATION) -> str:
        w = data.WEATHER[location]
        prompt = (
            f"Readings for {location}: {w.temperature} C, {w.conditions}, "
            f"humidity {w.humidity}%. Present the forecast."
        )
        result = await agents.weather_reporter_agent.run(prompt, model=agents.sampling_model(ctx))
        return result.output


# --------------------------------------------------------------------------- #
# Marvel hero roster tools (structured output over a small fixed dataset)
# --------------------------------------------------------------------------- #


def _register_hero_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        title="List heroes",
        description="List the Marvel heroes in the roster, optionally filtered by team.",
    )
    def list_heroes(team: str | None = None) -> heroes.HeroRoster:
        found = heroes.all_heroes(team)
        return heroes.HeroRoster(count=len(found), heroes=found)

    @mcp.tool(
        title="Get hero",
        description="Return the full record for one hero by codename (e.g. 'spider-man').",
    )
    def get_hero(codename: str) -> heroes.Hero:
        return heroes.get(codename)

    @mcp.tool(
        title="Find heroes by power",
        description="Return every hero whose power list matches the given substring (e.g. 'flight').",
    )
    def find_heroes_by_power(power: str) -> heroes.HeroRoster:
        found = heroes.by_power(power)
        return heroes.HeroRoster(count=len(found), heroes=found)

    @mcp.tool(
        title="Assemble team",
        description="Pick the heroes whose powers best fit a described threat (deterministic).",
    )
    def assemble_team(threat: str, size: int = 3) -> heroes.MissionTeam:
        return heroes.assemble_team(threat, size)

    @mcp.tool(
        title="Hero bio (pydantic-ai + sampling)",
        description="A pydantic-ai agent writes a short in-universe bio from the hero's facts; the LLM comes from the client via MCP sampling.",
    )
    async def hero_bio(ctx: Context, codename: str) -> str:
        hero = heroes.get(codename)
        prompt = (
            f"Write a 2-3 sentence in-universe biography of {hero.name} "
            f"(alias {hero.codename}). Teams: {', '.join(hero.teams)}. "
            f"Powers: {', '.join(hero.powers)}. Origin: {hero.origin}"
        )
        result = await agents.hero_biographer_agent.run(prompt, model=agents.sampling_model(ctx))
        return result.output


# --------------------------------------------------------------------------- #
# IT-application / SRE tools (service catalogue, health, incidents, deploys)
# --------------------------------------------------------------------------- #


def _register_sre_tools(mcp: FastMCP, state: sre.SREState) -> None:
    @mcp.tool(
        title="List services",
        description="List the application/service catalogue, optionally filtered by tier or environment.",
    )
    def list_services(tier: int | None = None, environment: str | None = None) -> sre.ServiceList:
        found = sre.list_services(tier, environment)
        return sre.ServiceList(count=len(found), services=found)

    @mcp.tool(
        title="Get service",
        description="Return one service's catalogue entry: tier, team, dependencies, SLOs, repo.",
    )
    def get_service(name: str) -> sre.Service:
        return sre.get_service(name)

    @mcp.tool(
        title="Check service health",
        description="Roll up synthetic metrics, SLOs, and open incidents into a healthy/degraded/down verdict.",
    )
    def check_service_health(name: str) -> sre.HealthReport:
        return state.health(name.strip().lower())

    @mcp.tool(
        title="Error budget",
        description="Compute the remaining SLO error budget and current burn rate for a service.",
    )
    def error_budget(name: str, window_days: int = 30) -> sre.ErrorBudget:
        return state.error_budget(name.strip().lower(), window_days)

    @mcp.tool(
        title="Search logs",
        description="Search a service's (synthetic, deterministic) log stream for a substring, optionally by level.",
    )
    def search_logs(
        service: str, query: str = "", level: str | None = None, limit: int = 20
    ) -> sre.LogSearchResult:
        service = service.strip().lower()
        if service not in sre.SERVICES:
            raise ValueError(f"unknown service {service!r}")
        lines = sre.logs_for(service, query, level, limit)
        return sre.LogSearchResult(service=service, query=query, count=len(lines), lines=lines)

    @mcp.tool(
        title="List incidents",
        description="List incidents, optionally filtered by status, severity, or service.",
    )
    def list_incidents(
        status: str | None = None, severity: str | None = None, service: str | None = None
    ) -> sre.IncidentList:
        found = state.list_incidents(status, severity, service)
        return sre.IncidentList(count=len(found), incidents=found)

    @mcp.tool(
        title="Open incident",
        description="Open a new incident against a service. Mutates server-side state.",
    )
    def open_incident(service: str, severity: sre.Severity, summary: str) -> sre.Incident:
        return state.open_incident(service.strip().lower(), severity, summary)

    @mcp.tool(
        title="Update incident",
        description="Move an incident to a new status (acknowledged/mitigated/resolved) with an optional note. Mutates state.",
    )
    def update_incident(
        incident_id: str, status: sre.IncidentStatus, note: str | None = None
    ) -> sre.Incident:
        return state.update_incident(incident_id, status, note)

    @mcp.tool(
        title="Get on-call",
        description="Who is on call for a team or for the team that owns a service, plus the escalation order.",
    )
    def get_oncall(team_or_service: str) -> sre.OnCall:
        team, engineer = sre.oncall_for(team_or_service)
        return sre.OnCall(team=team, engineer=engineer, escalation=sre.escalation_for(team))

    @mcp.tool(
        title="List deployments",
        description="List recent deployments, optionally filtered by service or status.",
    )
    def list_deployments(service: str | None = None, status: str | None = None) -> sre.DeploymentList:
        found = state.list_deployments(service, status)
        return sre.DeploymentList(count=len(found), deployments=found)

    @mcp.tool(
        title="Roll back deployment",
        description="Roll back a deployment by id (simulated). Mutates server-side state.",
    )
    def rollback_deployment(deployment_id: str) -> sre.Deployment:
        return state.rollback_deployment(deployment_id)

    @mcp.tool(
        title="Get runbook",
        description="Return the runbook entries for a service, optionally narrowed to a symptom.",
    )
    def get_runbook(service: str, symptom: str | None = None) -> sre.Runbook:
        service = service.strip().lower()
        return sre.Runbook(service=service, entries=sre.runbook_for(service, symptom))

    @mcp.tool(
        title="Incident postmortem (pydantic-ai + sampling)",
        description="A pydantic-ai agent drafts a short blameless postmortem from an incident's facts; the LLM comes from the client via MCP sampling.",
    )
    async def incident_postmortem(ctx: Context, incident_id: str) -> str:
        inc = state.incidents.get(incident_id)
        if inc is None:
            raise ValueError(f"unknown incident {incident_id!r}")
        health = state.health(inc.service)
        prompt = (
            f"Incident {inc.id} on {inc.service} ({inc.severity}), status {inc.status}. "
            f"Summary: {inc.summary}. Opened {inc.opened_at}. Notes: {inc.notes or 'none'}. "
            f"Current health: {health.status} because {', '.join(health.reasons)}. "
            "Draft a short blameless postmortem: impact, likely trigger, and 2-3 follow-up actions."
        )
        result = await agents.postmortem_agent.run(prompt, model=agents.sampling_model(ctx))
        return result.output


# --------------------------------------------------------------------------- #
# Resources (static + templated)
# --------------------------------------------------------------------------- #


def _register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        data.STATIC_INSTRUCTIONS_URI,
        name="Server instructions",
        description="Overview of what this server implements.",
        mime_type="text/markdown",
    )
    def instructions_doc() -> str:
        return data.INSTRUCTIONS

    @mcp.resource(
        data.STATIC_FEATURES_URI,
        name="Feature list",
        description="The full list of tools, resources, and prompts.",
        mime_type="text/markdown",
    )
    def features_doc() -> str:
        return data.FEATURES_MD

    @mcp.resource(
        "demo://resource/dynamic/text/{resource_id}",
        name="Dynamic text resource",
        description="A plaintext resource fabricated from a positive-integer {resource_id}.",
        mime_type="text/plain",
    )
    def dynamic_text(resource_id: str) -> str:
        return data.text_body(int(resource_id))

    @mcp.resource(
        "demo://resource/dynamic/blob/{resource_id}",
        name="Dynamic blob resource",
        description="A binary resource fabricated from a positive-integer {resource_id}.",
        mime_type="application/octet-stream",
    )
    def dynamic_blob(resource_id: str) -> bytes:
        return data.blob_body(int(resource_id))

    @mcp.resource(
        "hero://roster/{codename}",
        name="Hero record",
        description="One Marvel hero as JSON, addressed by codename (e.g. hero://roster/storm).",
        mime_type="application/json",
    )
    def hero_record(codename: str) -> str:
        return heroes.get(codename).model_dump_json(indent=2)

    @mcp.resource(
        "service://catalog/{name}",
        name="Service catalogue entry",
        description="One service's catalogue entry as JSON (e.g. service://catalog/checkout-api).",
        mime_type="application/json",
    )
    def service_catalog_entry(name: str) -> str:
        return sre.get_service(name).model_dump_json(indent=2)

    @mcp.resource(
        "runbook://{service}",
        name="Service runbook",
        description="The runbook for a service as Markdown (e.g. runbook://checkout-api).",
        mime_type="text/markdown",
    )
    def service_runbook(service: str) -> str:
        service = service.strip().lower()
        entries = sre.runbook_for(service)
        if not entries:
            return f"# {service} runbook\n\n_No runbook entries recorded._\n"
        lines = [f"# {service} runbook", ""]
        for entry in entries:
            lines.append(f"## {entry.symptom}")
            lines += [f"{i}. {step}" for i, step in enumerate(entry.steps, start=1)]
            lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


def _register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(title="Simple prompt", description="A prompt that takes no arguments.")
    def simple_prompt() -> str:
        return "This is a simple prompt with no arguments."

    @mcp.prompt(
        title="Arguments prompt",
        description="A prompt with a required city and an optional state.",
    )
    def args_prompt(city: str, state: str | None = None) -> str:
        location = f"{city}, {state}" if state else city
        return f"What is the weather like in {location}?"

    @mcp.prompt(
        title="Completable prompt",
        description="Pick a department, then a team member; both arguments offer completions.",
    )
    def completable_prompt(department: str, name: str) -> str:
        return f"Please promote {name} to the head of the {department} team."

    @mcp.prompt(
        title="Resource prompt",
        description="A prompt whose message list embeds a dynamic resource.",
    )
    def resource_prompt(resource_id: str = "1", kind: str = "text") -> list[base.Message]:
        uri = data.dynamic_uri(kind, resource_id)
        if kind == "blob":
            resource: TextResourceContents | BlobResourceContents = BlobResourceContents(
                uri=AnyUrl(uri),
                mimeType="application/octet-stream",
                blob=data.blob_body_b64(int(resource_id)),
            )
        else:
            resource = TextResourceContents(
                uri=AnyUrl(uri), mimeType="text/plain", text=data.text_body(int(resource_id))
            )
        return [
            base.UserMessage(f"Please analyse the {kind} resource with id {resource_id}:"),
            base.UserMessage(content=EmbeddedResource(type="resource", resource=resource)),
        ]


# --------------------------------------------------------------------------- #
# Argument completion (prompts + resource templates)
# --------------------------------------------------------------------------- #


def _prefix_filter(options: list[str], value: str) -> list[str]:
    value = value.lower()
    return [o for o in options if o.lower().startswith(value)]


def _register_completion(mcp: FastMCP) -> None:
    @mcp.completion()
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        if isinstance(ref, PromptReference):
            if ref.name == "completable_prompt" and argument.name == "department":
                return Completion(values=_prefix_filter(list(data.DEPARTMENTS), argument.value))
            if ref.name == "completable_prompt" and argument.name == "name":
                dept = (context.arguments or {}).get("department") if context else None
                members = data.TEAMS.get(dept or "", [])
                return Completion(values=_prefix_filter(members, argument.value))
            if ref.name == "resource_prompt" and argument.name == "kind":
                return Completion(values=_prefix_filter(["text", "blob"], argument.value))
            if ref.name == "args_prompt" and argument.name == "city":
                return Completion(values=_prefix_filter(list(data.WEATHER), argument.value))
        elif isinstance(ref, ResourceTemplateReference):
            if argument.name == "resource_id":
                digits = argument.value or ""
                base_ids = [digits + s for s in "0123456789"] if digits.isdigit() else ["1", "2", "3"]
                return Completion(values=base_ids[:10])
            if argument.name == "codename":
                return Completion(values=_prefix_filter(sorted(heroes.ROSTER), argument.value)[:10])
            if argument.name in ("name", "service"):
                return Completion(values=_prefix_filter(sorted(sre.SERVICES), argument.value)[:10])
        return None


# --------------------------------------------------------------------------- #
# Low-level handlers FastMCP does not wrap: subscribe / unsubscribe / setLevel
# --------------------------------------------------------------------------- #


def _register_low_level_handlers(mcp: FastMCP) -> None:
    low = mcp._mcp_server  # noqa: SLF001 - intentional: FastMCP exposes this for exactly this use

    @low.subscribe_resource()
    async def _subscribe(uri: AnyUrl) -> None:
        _subscriptions.add(str(uri))

    @low.unsubscribe_resource()
    async def _unsubscribe(uri: AnyUrl) -> None:
        _subscriptions.discard(str(uri))

    @low.set_logging_level()
    async def _set_level(level: LoggingLevel) -> None:
        _client_log_level["value"] = level

    # The low-level server hard-codes ``resources.subscribe = False`` when it
    # derives capabilities from handlers, so advertise it explicitly now that a
    # subscribe handler is registered.
    _orig_get_capabilities = low.get_capabilities

    def get_capabilities(notification_options, experimental_capabilities):  # type: ignore[no-untyped-def]
        caps = _orig_get_capabilities(notification_options, experimental_capabilities)
        if caps.resources is not None:
            caps.resources.subscribe = True
        return caps

    low.get_capabilities = get_capabilities  # type: ignore[method-assign]


# --------------------------------------------------------------------------- #
# Extra HTTP routes (only used under streamable-http transport)
# --------------------------------------------------------------------------- #


def _register_http_routes(mcp: FastMCP) -> None:
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, JSONResponse

    from .contract import service_contract

    @mcp.custom_route("/", methods=["GET"])
    async def homepage(_request: Request) -> HTMLResponse:
        return HTMLResponse(LANDING_HTML)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "subscriptions": sorted(_subscriptions),
            }
        )

    if telemetry.prometheus_enabled():

        @mcp.custom_route("/metrics", methods=["GET"])
        async def metrics_route(_request: Request):  # type: ignore[no-untyped-def]
            return telemetry.prometheus_response()

    @mcp.custom_route("/contract.json", methods=["GET"])
    async def contract_route(request: Request) -> JSONResponse:
        return JSONResponse(await service_contract(mcp, base_url=str(request.base_url)))
