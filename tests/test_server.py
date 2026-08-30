"""End-to-end tests: drive the server with an in-memory MCP client session.

A stub sampling callback stands in for the client's LLM so the pydantic-ai
tools (`poet`, `summarize`, `weather_report`) can be exercised without any
provider credentials.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CreateMessageRequestParams, CreateMessageResult, ErrorData, TextContent

from aipod.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _sampling_callback(
    _context: RequestContext[ClientSession, Any],
    params: CreateMessageRequestParams,
) -> CreateMessageResult | ErrorData:
    """Pretend to be a client LLM. Return JSON when the agent asks for structured output."""

    blob = (params.systemPrompt or "").lower()
    for message in params.messages:
        if isinstance(message.content, TextContent):
            blob += "\n" + message.content.text.lower()

    wants_json = any(marker in blob for marker in ("json", "key_points", "schema"))
    text = (
        json.dumps(
            {
                "headline": "Stub headline",
                "summary": "Stub summary sentence one. Stub summary sentence two.",
                "key_points": ["point one", "point two", "point three"],
            }
        )
        if wants_json
        else "Roses are red, this reply is stubbed, the sampling round-trip worked as hubbed."
    )
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=text),
        model="stub-llm",
    )


@pytest.fixture
async def session():
    async with create_connected_server_and_client_session(
        build_server(),
        sampling_callback=_sampling_callback,
    ) as client:
        yield client


async def test_capabilities(session: ClientSession) -> None:
    result = await session.initialize()
    caps = result.capabilities
    assert caps.tools is not None
    assert caps.resources is not None and caps.resources.subscribe
    assert caps.prompts is not None
    assert caps.logging is not None
    assert caps.completions is not None


async def test_tool_inventory(session: ClientSession) -> None:
    await session.initialize()
    names = {t.name for t in (await session.list_tools()).tools}
    assert {
        "echo",
        "add",
        "get_tiny_image",
        "get_annotated_message",
        "get_structured_weather",
        "get_resource_reference",
        "get_resource_links",
        "trigger_long_running_operation",
        "toggle_simulated_logging",
        "toggle_subscriber_updates",
        "poet",
        "summarize",
        "weather_report",
        "list_heroes",
        "get_hero",
        "find_heroes_by_power",
        "assemble_team",
        "hero_bio",
        "list_services",
        "get_service",
        "check_service_health",
        "error_budget",
        "search_logs",
        "list_incidents",
        "open_incident",
        "update_incident",
        "get_oncall",
        "list_deployments",
        "rollback_deployment",
        "get_runbook",
        "incident_postmortem",
    } <= names


async def test_echo_and_add(session: ClientSession) -> None:
    await session.initialize()
    echo = await session.call_tool("echo", {"message": "hi"})
    assert echo.content[0].text == "Echo: hi"
    added = await session.call_tool("add", {"a": 2, "b": 3})
    assert "is 5" in added.content[0].text


async def test_structured_output_has_schema_and_payload(session: ClientSession) -> None:
    await session.initialize()
    tool = next(t for t in (await session.list_tools()).tools if t.name == "get_structured_weather")
    assert tool.outputSchema is not None
    result = await session.call_tool("get_structured_weather", {"location": "Savognin"})
    assert result.structuredContent["conditions"] == "Snow showers"
    assert result.structuredContent["humidity"] == 84

    # default location is Zurich
    default = await session.call_tool("get_structured_weather", {})
    assert default.structuredContent["location"] == "Zurich"


async def test_image_and_annotations(session: ClientSession) -> None:
    await session.initialize()
    img = await session.call_tool("get_tiny_image", {})
    assert any(block.type == "image" for block in img.content)

    ann = await session.call_tool("get_annotated_message", {"message_type": "error", "include_image": True})
    first = ann.content[0]
    assert first.annotations.priority == 1.0
    assert "assistant" in first.annotations.audience
    assert any(block.type == "image" for block in ann.content)


async def test_resource_reference_and_links(session: ClientSession) -> None:
    await session.initialize()
    ref = await session.call_tool("get_resource_reference", {"resource_id": 7, "kind": "text"})
    assert any(block.type == "resource" for block in ref.content)

    links = await session.call_tool("get_resource_links", {"count": 4})
    resource_links = [b for b in links.content if b.type == "resource_link"]
    assert len(resource_links) == 4


async def test_progress_reporting(session: ClientSession) -> None:
    await session.initialize()
    seen: list[float] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append(progress)

    result = await session.call_tool(
        "trigger_long_running_operation",
        {"steps": 3, "step_seconds": 0.01},
        progress_callback=on_progress,
    )
    assert seen == [1, 2, 3]
    assert "Completed 3 steps" in result.content[0].text


async def test_resources_static_and_templated(session: ClientSession) -> None:
    await session.initialize()
    resources = {str(r.uri) for r in (await session.list_resources()).resources}
    assert "demo://resource/static/instructions.md" in resources

    templates = {t.uriTemplate for t in (await session.list_resource_templates()).resourceTemplates}
    assert "demo://resource/dynamic/text/{resource_id}" in templates

    text = await session.read_resource("demo://resource/dynamic/text/42")  # type: ignore[arg-type]
    assert "Resource 42" in text.contents[0].text

    blob = await session.read_resource("demo://resource/dynamic/blob/9")  # type: ignore[arg-type]
    assert blob.contents[0].blob  # base64 payload present


async def test_prompts(session: ClientSession) -> None:
    await session.initialize()
    names = {p.name for p in (await session.list_prompts()).prompts}
    assert {"simple_prompt", "args_prompt", "completable_prompt", "resource_prompt"} <= names

    args = await session.get_prompt("args_prompt", {"city": "Denver", "state": "CO"})
    assert "Denver, CO" in args.messages[0].content.text

    res = await session.get_prompt("resource_prompt", {"resource_id": "3", "kind": "text"})
    assert any(m.content.type == "resource" for m in res.messages)


async def test_completion(session: ClientSession) -> None:
    await session.initialize()
    from mcp.types import PromptReference

    dept = await session.complete(
        PromptReference(type="ref/prompt", name="completable_prompt"),
        argument={"name": "department", "value": "S"},
    )
    assert set(dept.completion.values) == {"Sales", "Support"}

    member = await session.complete(
        PromptReference(type="ref/prompt", name="completable_prompt"),
        argument={"name": "name", "value": ""},
        context_arguments={"department": "Engineering"},
    )
    assert "Alice" in member.completion.values


async def test_subscription_roundtrip(session: ClientSession) -> None:
    await session.initialize()
    await session.subscribe_resource("demo://resource/dynamic/text/1")  # type: ignore[arg-type]
    started = await session.call_tool("toggle_subscriber_updates", {})
    assert "Started" in started.content[0].text
    stopped = await session.call_tool("toggle_subscriber_updates", {})
    assert "Stopped" in stopped.content[0].text
    await session.unsubscribe_resource("demo://resource/dynamic/text/1")  # type: ignore[arg-type]


async def test_simulated_logging_toggle(session: ClientSession) -> None:
    await session.initialize()
    on = await session.call_tool("toggle_simulated_logging", {})
    assert "Started" in on.content[0].text
    off = await session.call_tool("toggle_simulated_logging", {})
    assert "Stopped" in off.content[0].text


async def test_marvel_hero_tools(session: ClientSession) -> None:
    await session.initialize()

    roster = await session.call_tool("list_heroes", {})
    assert roster.structuredContent["count"] == len(roster.structuredContent["heroes"])
    assert roster.structuredContent["count"] >= 10

    xmen = await session.call_tool("list_heroes", {"team": "x-men"})
    names = {h["codename"] for h in xmen.structuredContent["heroes"]}
    assert "wolverine" in names and "iron-man" not in names

    hero = await session.call_tool("get_hero", {"codename": "Spider-Man"})
    assert hero.structuredContent["name"] == "Peter Parker"

    unknown = await session.call_tool("get_hero", {"codename": "nobody"})
    assert unknown.isError

    fliers = await session.call_tool("find_heroes_by_power", {"power": "flight"})
    assert {"iron-man", "storm"} <= {h["codename"] for h in fliers.structuredContent["heroes"]}

    team = await session.call_tool("assemble_team", {"threat": "a lightning storm over the city", "size": 2})
    assert len(team.structuredContent["members"]) == 2


async def test_hero_resource_template(session: ClientSession) -> None:
    await session.initialize()

    templates = {t.uriTemplate for t in (await session.list_resource_templates()).resourceTemplates}
    assert "hero://roster/{codename}" in templates

    got = await session.read_resource("hero://roster/storm")  # type: ignore[arg-type]
    assert '"name": "Ororo Munroe"' in got.contents[0].text

    from mcp.types import ResourceTemplateReference

    comp = await session.complete(
        ResourceTemplateReference(type="ref/resource", uri="hero://roster/{codename}"),
        argument={"name": "codename", "value": "sp"},
    )
    assert "spider-man" in comp.completion.values


async def test_hero_bio_via_sampling(session: ClientSession) -> None:
    await session.initialize()
    result = await session.call_tool("hero_bio", {"codename": "wolverine"})
    assert "stubbed" in result.content[0].text


# --------------------------------------------------------------------------- #
# IT-application / SRE tools
# --------------------------------------------------------------------------- #


async def test_sre_service_catalogue(session: ClientSession) -> None:
    await session.initialize()

    catalogue = await session.call_tool("list_services", {})
    assert catalogue.structuredContent["count"] == len(catalogue.structuredContent["services"])
    names = {s["name"] for s in catalogue.structuredContent["services"]}
    assert {"checkout-api", "payments-api", "auth-service"} <= names

    tier1 = await session.call_tool("list_services", {"tier": 1})
    assert all(s["tier"] == 1 for s in tier1.structuredContent["services"])

    svc = await session.call_tool("get_service", {"name": "checkout-api"})
    assert svc.structuredContent["team"] == "payments"
    assert "payments-api" in svc.structuredContent["depends_on"]

    assert (await session.call_tool("get_service", {"name": "nope"})).isError

    entry = await session.read_resource("service://catalog/auth-service")  # type: ignore[arg-type]
    assert '"tier": 1' in entry.contents[0].text


async def test_sre_health_and_error_budget(session: ClientSession) -> None:
    await session.initialize()

    degraded = await session.call_tool("check_service_health", {"name": "payments-api"})
    body = degraded.structuredContent
    assert body["status"] in {"degraded", "down"}
    assert "INC-0001" in body["open_incident_ids"]
    assert body["metrics"]["latency_p99_ms"] > 0

    healthy = await session.call_tool("check_service_health", {"name": "checkout-api"})
    assert healthy.structuredContent["status"] == "healthy"

    budget = await session.call_tool("error_budget", {"name": "checkout-api"})
    eb = budget.structuredContent
    assert eb["window_days"] == 30 and eb["budget_minutes"] > 0
    assert "remaining_pct" in eb and "burn_rate" in eb


async def test_sre_incident_lifecycle(session: ClientSession) -> None:
    await session.initialize()

    seeded = await session.call_tool("list_incidents", {})
    assert seeded.structuredContent["count"] >= 2

    opened = await session.call_tool(
        "open_incident",
        {"service": "checkout-api", "severity": "SEV3", "summary": "checkout 500s"},
    )
    inc_id = opened.structuredContent["id"]
    assert inc_id.startswith("INC-") and opened.structuredContent["status"] == "open"

    open_only = await session.call_tool("list_incidents", {"status": "open"})
    assert inc_id in {i["id"] for i in open_only.structuredContent["incidents"]}

    resolved = await session.call_tool(
        "update_incident", {"incident_id": inc_id, "status": "resolved", "note": "cache flag on"}
    )
    assert resolved.structuredContent["status"] == "resolved"
    assert "cache flag on" in resolved.structuredContent["notes"]

    assert (await session.call_tool("update_incident", {"incident_id": "INC-9999", "status": "resolved"})).isError


async def test_sre_deployments_and_oncall(session: ClientSession) -> None:
    await session.initialize()

    deploys = await session.call_tool("list_deployments", {"service": "checkout-api"})
    ids = {d["id"] for d in deploys.structuredContent["deployments"]}
    assert "dep-0001" in ids

    rolled = await session.call_tool("rollback_deployment", {"deployment_id": "dep-0001"})
    assert rolled.structuredContent["status"] == "rolled_back"

    # dep-0005 (auth-service, failed) cannot be rolled back
    assert (await session.call_tool("rollback_deployment", {"deployment_id": "dep-0005"})).isError

    oncall = await session.call_tool("get_oncall", {"team_or_service": "payments-api"})
    assert oncall.structuredContent["team"] == "payments"
    assert oncall.structuredContent["engineer"]
    assert isinstance(oncall.structuredContent["escalation"], list)


async def test_sre_logs_and_runbook(session: ClientSession) -> None:
    await session.initialize()

    logs = await session.call_tool(
        "search_logs", {"service": "checkout-api", "query": "slow query", "limit": 10}
    )
    lc = logs.structuredContent
    assert lc["count"] == len(lc["lines"]) <= 10
    assert all("slow query" in line["message"].lower() for line in lc["lines"])

    # deterministic: same query -> same lines
    again = await session.call_tool(
        "search_logs", {"service": "checkout-api", "query": "slow query", "limit": 10}
    )
    assert again.structuredContent["lines"] == lc["lines"]

    rb = await session.call_tool("get_runbook", {"service": "checkout-api", "symptom": "latency"})
    assert rb.structuredContent["entries"]
    assert "latency" in rb.structuredContent["entries"][0]["symptom"].lower()

    doc = await session.read_resource("runbook://checkout-api")  # type: ignore[arg-type]
    assert doc.contents[0].text.startswith("# checkout-api runbook")


async def test_sre_postmortem_via_sampling(session: ClientSession) -> None:
    await session.initialize()
    result = await session.call_tool("incident_postmortem", {"incident_id": "INC-0001"})
    assert "stubbed" in result.content[0].text


async def test_pydantic_ai_poet_via_sampling(session: ClientSession) -> None:
    await session.initialize()
    result = await session.call_tool("poet", {"theme": "sockets"})
    assert "stubbed" in result.content[0].text


async def test_pydantic_ai_summarize_structured_via_sampling(session: ClientSession) -> None:
    await session.initialize()
    result = await session.call_tool("summarize", {"text": "A long-ish passage that needs summarising."})
    assert result.structuredContent["headline"] == "Stub headline"
    assert len(result.structuredContent["key_points"]) == 3


async def test_service_contract_shape() -> None:
    from aipod.server.contract import service_contract

    contract = await service_contract(build_server(), base_url="http://aipod.example/")
    tool_names = {t["name"] for t in contract["tools"]}
    assert "echo" in tool_names and "weather_report" in tool_names
    sampling_tools = {t["name"] for t in contract["tools"] if t["requiresSampling"]}
    assert sampling_tools == {
        "poet",
        "summarize",
        "weather_report",
        "hero_bio",
        "incident_postmortem",
    }
    assert contract["clientRequirements"]["sampling"]["requiredBy"] == [
        "hero_bio",
        "incident_postmortem",
        "poet",
        "summarize",
        "weather_report",
    ]
    assert contract["security"]["scheme"] == "none"
    assert contract["clientRequirements"]["authentication"]["required"] is False
    template_uris = {t["uriTemplate"] for t in contract["resources"]["templates"]}
    assert "demo://resource/dynamic/text/{resource_id}" in template_uris
    assert "hero://roster/{codename}" in template_uris
    assert "service://catalog/{name}" in template_uris

    gov = contract["governance"]
    assert gov["dataClassification"] == "PUBLIC"
    assert sorted(gov["dataEgress"]["clientModelViaSampling"]) == [
        "hero_bio",
        "incident_postmortem",
        "poet",
        "summarize",
        "weather_report",
    ]
    egress = {t["name"]: t["dataEgress"] for t in contract["tools"]}
    assert egress["summarize"] == "client-model-via-sampling"
    assert egress["echo"] == "none"
    side_effects = {t["name"] for t in contract["tools"] if t["sideEffects"]}
    assert {"toggle_simulated_logging", "open_incident", "rollback_deployment"} <= side_effects
    assert "echo" not in side_effects and "check_service_health" not in side_effects


async def test_governance_env_override(monkeypatch) -> None:
    from aipod.server import contract as contract_mod

    monkeypatch.setenv("AIPOD_DATA_CLASSIFICATION", "CONFIDENTIAL")
    monkeypatch.setenv("AIPOD_REGULATORY_SCOPE", "GDPR, SOC2")
    monkeypatch.setenv("AIPOD_OWNER", "platform-team@example.com")

    gov = contract_mod.governance()
    assert gov["dataClassification"] == "CONFIDENTIAL"
    assert gov["regulatoryScope"] == ["GDPR", "SOC2"]

    contract = await contract_mod.service_contract(build_server())
    assert contract["governance"]["dataClassification"] == "CONFIDENTIAL"
    assert contract["governance"]["owner"] == "platform-team@example.com"
