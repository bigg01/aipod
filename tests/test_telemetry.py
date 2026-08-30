"""OpenTelemetry metrics: env gating, tool-call instrumentation, /metrics."""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from starlette.testclient import TestClient

from aipod import telemetry
from aipod.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def in_memory(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    """A live MeterProvider backed by an in-memory reader; no real exporter."""

    monkeypatch.setenv("AIPOD_METRICS", "console")  # -> configured() is True
    reader = InMemoryMetricReader()
    telemetry._install_provider_for_test(MeterProvider(metric_readers=[reader]))
    yield reader
    telemetry.reset()


def _points(data: object, name: str) -> list:
    out = []
    for rm in data.resource_metrics:  # type: ignore[attr-defined]
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    out.extend(metric.data.data_points)
    return out


@pytest.mark.parametrize(
    ("env", "expect_configured", "expect_prometheus"),
    [
        ({}, True, True),  # on by default, prometheus
        ({"AIPOD_METRICS": "none"}, False, False),
        ({"AIPOD_METRICS": "off"}, False, False),
        ({"OTEL_METRICS_EXPORTER": "none"}, False, False),
        ({"OTEL_SDK_DISABLED": "true"}, False, False),
        ({"AIPOD_METRICS": "otlp"}, True, False),
        ({"AIPOD_METRICS": "prometheus"}, True, True),
        ({"AIPOD_METRICS": "console"}, True, False),
        ({"OTEL_METRICS_EXPORTER": "otlp"}, True, False),
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}, True, False),
        ({"AIPOD_METRICS": "prometheus", "OTEL_SDK_DISABLED": "true"}, False, False),
        ({"AIPOD_METRICS": "none", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318"}, False, False),
    ],
)
def test_env_gating(
    monkeypatch: pytest.MonkeyPatch,
    env: dict,
    expect_configured: bool,
    expect_prometheus: bool,
) -> None:
    for key in ("AIPOD_METRICS", "OTEL_METRICS_EXPORTER", "OTEL_EXPORTER_OTLP_ENDPOINT",
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_SDK_DISABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert telemetry.configured() is expect_configured
    assert telemetry.prometheus_enabled() is expect_prometheus


def test_no_provider_means_recording_is_a_noop() -> None:
    telemetry.reset()
    telemetry.record_tool_call("echo", ok=True, duration_s=0.01)  # must not raise
    telemetry.record_agent_ask(ok=False, duration_s=0.2)
    assert telemetry.live() is False


async def test_tool_calls_are_counted_and_timed(in_memory: InMemoryMetricReader) -> None:
    async with create_connected_server_and_client_session(build_server()) as client:
        await client.call_tool("echo", {"message": "hi"})
        await client.call_tool("echo", {"message": "again"})
        bad = await client.call_tool("get_hero", {"codename": "nobody"})
        assert bad.isError

    data = in_memory.get_metrics_data()

    calls = {
        (p.attributes["mcp.tool.name"], p.attributes["outcome"]): p.value
        for p in _points(data, "mcp.server.tool.calls")
    }
    assert calls[("echo", "ok")] == 2
    assert calls[("get_hero", "error")] == 1

    durations = _points(data, "mcp.server.tool.duration")
    assert sum(p.count for p in durations) == 3


async def test_sampling_tools_carry_the_sampling_attribute(
    in_memory: InMemoryMetricReader,
) -> None:
    async with create_connected_server_and_client_session(build_server()) as client:
        # no sampling callback wired -> the call errors, but it is still recorded
        await client.call_tool("poet", {"theme": "sockets"})

    points = _points(in_memory.get_metrics_data(), "mcp.server.tool.calls")
    poet = next(p for p in points if p.attributes["mcp.tool.name"] == "poet")
    assert poet.attributes["mcp.tool.sampling"] is True


async def test_requests_counted_by_method(in_memory: InMemoryMetricReader) -> None:
    async with create_connected_server_and_client_session(build_server()) as client:
        await client.list_tools()
        await client.list_resources()
        await client.list_prompts()
        await client.read_resource("demo://resource/dynamic/text/1")  # type: ignore[arg-type]
        try:
            await client.read_resource("hero://roster/nobody")  # type: ignore[arg-type]
        except Exception:
            pass
        await client.get_prompt("simple_prompt")

    by = {
        (p.attributes["mcp.method"], p.attributes["outcome"]): p.value
        for p in _points(in_memory.get_metrics_data(), "mcp.server.requests")
    }
    assert by[("tools/list", "ok")] >= 1
    assert by[("resources/list", "ok")] >= 1
    assert by[("prompts/list", "ok")] >= 1
    assert by[("resources/read", "ok")] >= 1
    assert by[("resources/read", "error")] == 1
    assert by[("prompts/get", "ok")] >= 1


def test_inventory_gauges(in_memory: InMemoryMetricReader) -> None:
    build_server()  # registers the observable gauges on the live meter

    gauges = {
        m: _points(in_memory.get_metrics_data(), m)
        for m in (
            "mcp.server.tools",
            "mcp.server.resources",
            "mcp.server.resource_templates",
            "mcp.server.prompts",
            "mcp.server.background_tasks.active",
        )
    }
    assert gauges["mcp.server.tools"][0].value == 31
    assert gauges["mcp.server.resources"][0].value == 2
    assert gauges["mcp.server.resource_templates"][0].value == 5
    assert gauges["mcp.server.prompts"][0].value == 4
    assert gauges["mcp.server.background_tasks.active"][0].value == 0


def test_agent_ask_metric_records(in_memory: InMemoryMetricReader) -> None:
    telemetry.record_agent_ask(ok=True, duration_s=0.05)
    telemetry.record_agent_ask(ok=False, duration_s=0.15)

    points = {
        p.attributes["outcome"]: p.value
        for p in _points(in_memory.get_metrics_data(), "aipod.agent.ask.calls")
    }
    assert points == {"ok": 1, "error": 1}


def test_prometheus_endpoint_on_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPOD_METRICS", "prometheus")
    from opentelemetry.exporter.prometheus import PrometheusMetricReader

    provider = MeterProvider(metric_readers=[PrometheusMetricReader()])
    telemetry._install_provider_for_test(provider)
    try:
        telemetry.record_tool_call("echo", ok=True, duration_s=0.01)
        app = build_server(host="127.0.0.1", port=8000).streamable_http_app()
        resp = TestClient(app).get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "mcp_server_tool_calls" in resp.text
    finally:
        provider.shutdown()
        telemetry.reset()


def test_metrics_route_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("AIPOD_METRICS", "OTEL_METRICS_EXPORTER", "OTEL_EXPORTER_OTLP_ENDPOINT",
                "OTEL_SDK_DISABLED"):
        monkeypatch.delenv(key, raising=False)
    from opentelemetry.exporter.prometheus import PrometheusMetricReader

    provider = MeterProvider(metric_readers=[PrometheusMetricReader()])
    telemetry._install_provider_for_test(provider)
    try:
        app = build_server(host="127.0.0.1", port=8000).streamable_http_app()
        assert TestClient(app).get("/metrics").status_code == 200
    finally:
        provider.shutdown()
        telemetry.reset()


def test_no_metrics_route_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIPOD_METRICS", "none")
    app = build_server(host="127.0.0.1", port=8000).streamable_http_app()
    assert TestClient(app).get("/metrics").status_code == 404
