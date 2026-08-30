"""OpenTelemetry **metrics** for aipod - shared by both modes.

**On by default** with the ``prometheus`` exporter (a local ``/metrics`` scrape
endpoint - no external dependency). Change or disable it with:

* ``AIPOD_METRICS`` = ``prometheus`` | ``otlp`` | ``console`` | ``none``
* ``OTEL_METRICS_EXPORTER`` (standard OTel var; ``none`` disables)
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``
  select ``otlp`` when ``AIPOD_METRICS`` is unset
* ``OTEL_SDK_DISABLED=true`` forces everything off

Exporters:

* ``prometheus`` - a ``/metrics`` scrape endpoint on the mode's HTTP port (default)
* ``otlp``       - periodic OTLP/HTTP push (endpoint from the standard env vars)
* ``console``    - periodic dump to stdout (handy for a quick look)

Instruments (server internals, not just the Python process):

* ``mcp.server.requests``        counter   {mcp.method, outcome} - every MCP
  request the server handles: tools/call, tools/list, resources/read,
  resources/list, resources/templates/list, resources/subscribe,
  resources/unsubscribe, prompts/get, prompts/list, completion/complete,
  logging/setLevel, ping
* ``mcp.server.request.duration`` histogram {mcp.method, outcome}  unit ``s``
* ``mcp.server.tool.calls``       counter   {mcp.tool.name, outcome, mcp.tool.sampling?}
* ``mcp.server.tool.duration``    histogram {…}  unit ``s``
* ``mcp.server.sampling.requests`` counter  - server -> client sampling round-trips
* ``mcp.server.tools`` / ``.resources`` / ``.resource_templates`` / ``.prompts``
  observable gauges - the registered inventory
* ``mcp.server.resource_subscriptions.active`` / ``mcp.server.background_tasks.active``
  observable gauges - live per-connection state
* ``aipod.agent.ask.calls`` / ``aipod.agent.ask.duration``  {outcome}  (agent mode)
"""

from __future__ import annotations

import os
import time
from typing import Any

from . import __version__

try:  # the SDK is a hard dependency, but never let telemetry break a run
    from opentelemetry import metrics as _otel_metrics

    _HAVE_OTEL = True
except Exception:  # pragma: no cover - only when the optional stack is absent
    _HAVE_OTEL = False

_OFF = {"", "0", "off", "none", "no", "false", "disabled"}

# provider + cached instruments; provider is None until setup_metrics() runs
# (or a test installs one), which is also the "metrics are live" signal.
_state: dict[str, Any] = {"provider": None, "instruments": None, "meter_id": None}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def selected_exporter() -> str:
    """Which exporter to use. Defaults to ``prometheus`` (a local ``/metrics``
    endpoint - no external dependency); an OTLP endpoint switches it to ``otlp``."""

    for value in (_env("AIPOD_METRICS"), _env("OTEL_METRICS_EXPORTER")):
        if value in {"otlp", "prometheus", "console"}:
            return value
    if os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    ):
        return "otlp"
    return "prometheus"


def configured() -> bool:
    """True unless metrics are explicitly turned off. Metrics are **on by
    default** (Prometheus ``/metrics``); disable with ``AIPOD_METRICS=none``,
    ``OTEL_METRICS_EXPORTER=none``, or ``OTEL_SDK_DISABLED=true``."""

    if not _HAVE_OTEL:
        return False
    if _env("OTEL_SDK_DISABLED") == "true":
        return False

    aipod = _env("AIPOD_METRICS")
    if aipod in {"otlp", "prometheus", "console"}:
        return True
    if aipod:
        return False  # any other value (none / off / typo) -> off

    otel = _env("OTEL_METRICS_EXPORTER")
    if otel and otel in _OFF:
        return False  # OTEL_METRICS_EXPORTER=none explicitly disables

    return True


def prometheus_enabled() -> bool:
    return configured() and selected_exporter() == "prometheus"


def live() -> bool:
    """True once a MeterProvider is wired up (recording will actually land)."""

    return _HAVE_OTEL and _state["provider"] is not None


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #


def setup_metrics(*, mode: str, service_name: str | None = None) -> None:
    """Build a MeterProvider for the selected exporter. Idempotent; a no-op when
    metrics are not configured."""

    if not configured() or _state["provider"] is not None:
        return

    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource

    exporter = selected_exporter()
    readers = []
    if exporter == "prometheus":
        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        readers.append(PrometheusMetricReader())
    elif exporter == "console":
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )

        readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
    else:  # otlp
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))

    name = service_name or os.environ.get("OTEL_SERVICE_NAME") or f"aipod-{mode}"
    resource = Resource.create(
        {
            "service.name": name,
            "service.version": __version__,
            "aipod.mode": mode,
        }
    )
    provider = MeterProvider(metric_readers=readers, resource=resource)

    # Best-effort global set so any third-party lib sees it too; our own
    # recording goes through _state["provider"] directly and does not depend
    # on this succeeding (OTel refuses a second global set).
    try:
        _otel_metrics.set_meter_provider(provider)
    except Exception:  # pragma: no cover
        pass
    _state["provider"] = provider


def _install_provider_for_test(provider: Any) -> None:
    """Point recording at a caller-supplied MeterProvider (tests only)."""

    _state["provider"] = provider
    _state["instruments"] = None
    _state["meter_id"] = None
    _state["observables_meter_id"] = None


def reset() -> None:
    """Forget any provider/instruments (tests only)."""

    _state.update(
        provider=None, instruments=None, meter_id=None, observables_meter_id=None
    )


# --------------------------------------------------------------------------- #
# Instruments + recording
# --------------------------------------------------------------------------- #


def _instruments() -> dict[str, Any] | None:
    provider = _state["provider"]
    if provider is None:
        return None
    meter = provider.get_meter("aipod", __version__)
    if _state["instruments"] is not None and _state["meter_id"] == id(meter):
        return _state["instruments"]
    inst = {
        "req_calls": meter.create_counter(
            "mcp.server.requests",
            unit="{request}",
            description="MCP protocol requests handled, by method (tools/call, "
            "resources/read, prompts/get, completion/complete, ...)",
        ),
        "req_duration": meter.create_histogram(
            "mcp.server.request.duration",
            unit="s",
            description="Wall-clock duration of an MCP protocol request, by method",
        ),
        "tool_calls": meter.create_counter(
            "mcp.server.tool.calls",
            unit="{call}",
            description="MCP tool invocations handled by the server, by tool name",
        ),
        "tool_duration": meter.create_histogram(
            "mcp.server.tool.duration",
            unit="s",
            description="Wall-clock duration of an MCP tool invocation, by tool name",
        ),
        "sampling_requests": meter.create_counter(
            "mcp.server.sampling.requests",
            unit="{request}",
            description="Sampling round-trips the server asked the connected client to run",
        ),
        "ask_calls": meter.create_counter(
            "aipod.agent.ask.calls",
            unit="{call}",
            description="Agent requests run through the pydantic-ai agent",
        ),
        "ask_duration": meter.create_histogram(
            "aipod.agent.ask.duration",
            unit="s",
            description="Wall-clock duration of an agent request",
        ),
    }
    _state["instruments"] = inst
    _state["meter_id"] = id(meter)
    return inst


def record_tool_call(
    tool: str, *, ok: bool, duration_s: float, sampling: bool = False
) -> None:
    inst = _instruments()
    if inst is None:
        return
    attrs: dict[str, Any] = {"mcp.tool.name": tool, "outcome": "ok" if ok else "error"}
    if sampling:
        attrs["mcp.tool.sampling"] = True
    inst["tool_calls"].add(1, attrs)
    inst["tool_duration"].record(max(duration_s, 0.0), attrs)


def record_agent_ask(*, ok: bool, duration_s: float) -> None:
    inst = _instruments()
    if inst is None:
        return
    attrs = {"outcome": "ok" if ok else "error"}
    inst["ask_calls"].add(1, attrs)
    inst["ask_duration"].record(max(duration_s, 0.0), attrs)


def record_request(method: str, *, ok: bool, duration_s: float) -> None:
    inst = _instruments()
    if inst is None:
        return
    attrs = {"mcp.method": method, "outcome": "ok" if ok else "error"}
    inst["req_calls"].add(1, attrs)
    inst["req_duration"].record(max(duration_s, 0.0), attrs)


def record_sampling() -> None:
    inst = _instruments()
    if inst is not None:
        inst["sampling_requests"].add(1)


# --------------------------------------------------------------------------- #
# FastMCP instrumentation
# --------------------------------------------------------------------------- #

# Low-level request class name -> MCP method string.
_METHODS = {
    "PingRequest": "ping",
    "ListToolsRequest": "tools/list",
    "CallToolRequest": "tools/call",
    "ListResourcesRequest": "resources/list",
    "ReadResourceRequest": "resources/read",
    "ListResourceTemplatesRequest": "resources/templates/list",
    "ListPromptsRequest": "prompts/list",
    "GetPromptRequest": "prompts/get",
    "CompleteRequest": "completion/complete",
    "SubscribeRequest": "resources/subscribe",
    "UnsubscribeRequest": "resources/unsubscribe",
    "SetLevelRequest": "logging/setLevel",
}


def instrument_fastmcp(
    mcp: Any,
    *,
    subscriptions: Any = None,
    background_tasks: Any = None,
) -> None:
    """Instrument a FastMCP server's internals: every protocol request (rate,
    latency, errors by method), every tool call by name, and gauges for the
    registered inventory + live subscription / background-task counts."""

    if not configured():
        return

    # 1. Per-tool call/duration/sampling-flag: wrap the tool manager's dispatch
    #    (the low-level CallTool handler captured a bound method at init, so this
    #    is the reassignable chokepoint FastMCP.call_tool actually looks up).
    manager = getattr(mcp, "_tool_manager", None)
    original = getattr(manager, "call_tool", None)
    if original is not None and not getattr(manager, "_aipod_instrumented", False):
        from .server.contract import SAMPLING_TOOLS

        async def call_tool(name: str, arguments: Any, *args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            ok = True
            try:
                return await original(name, arguments, *args, **kwargs)
            except BaseException:
                ok = False
                raise
            finally:
                record_tool_call(
                    name,
                    ok=ok,
                    duration_s=time.perf_counter() - started,
                    sampling=name in SAMPLING_TOOLS,
                )

        manager.call_tool = call_tool  # type: ignore[method-assign]
        manager._aipod_instrumented = True

    # 2. Every MCP request type: wrap the low-level request handlers.
    low = getattr(mcp, "_mcp_server", None)
    handlers = getattr(low, "request_handlers", None)
    if isinstance(handlers, dict) and not getattr(low, "_aipod_instrumented", False):
        for req_type, handler in list(handlers.items()):
            method = _METHODS.get(req_type.__name__, req_type.__name__)
            handlers[req_type] = _timed_request_handler(handler, method)
        low._aipod_instrumented = True

    # 3. Inventory + live-state gauges.
    if not getattr(mcp, "_aipod_observables", False):
        _register_observables(mcp, subscriptions, background_tasks)
        mcp._aipod_observables = True


def _timed_request_handler(handler: Any, method: str) -> Any:
    async def wrapped(req: Any) -> Any:
        started = time.perf_counter()
        ok = True
        try:
            return await handler(req)
        except BaseException:
            ok = False
            raise
        finally:
            record_request(method, ok=ok, duration_s=time.perf_counter() - started)

    return wrapped


def _register_observables(mcp: Any, subscriptions: Any, background_tasks: Any) -> None:
    provider = _state["provider"]
    if provider is None:
        return
    meter = provider.get_meter("aipod", __version__)
    # Observable gauges only need to exist once per meter; re-registering (e.g.
    # a second build_server() in the same process) just warns.
    if _state.get("observables_meter_id") == id(meter):
        return
    _state["observables_meter_id"] = id(meter)

    def _obs(fn: Any) -> Any:
        from opentelemetry.metrics import Observation

        def callback(_options: Any) -> list[Any]:
            try:
                return [Observation(int(fn()))]
            except Exception:  # pragma: no cover - never let a scrape fail
                return []

        return callback

    tm, rm, pm = mcp._tool_manager, mcp._resource_manager, mcp._prompt_manager
    meter.create_observable_gauge(
        "mcp.server.tools", callbacks=[_obs(lambda: len(tm.list_tools()))],
        unit="{tool}", description="Registered MCP tools",
    )
    meter.create_observable_gauge(
        "mcp.server.resources", callbacks=[_obs(lambda: len(rm.list_resources()))],
        unit="{resource}", description="Registered static resources",
    )
    meter.create_observable_gauge(
        "mcp.server.resource_templates", callbacks=[_obs(lambda: len(rm.list_templates()))],
        unit="{template}", description="Registered resource templates",
    )
    meter.create_observable_gauge(
        "mcp.server.prompts", callbacks=[_obs(lambda: len(pm.list_prompts()))],
        unit="{prompt}", description="Registered prompts",
    )
    if subscriptions is not None:
        meter.create_observable_gauge(
            "mcp.server.resource_subscriptions.active",
            callbacks=[_obs(lambda: len(subscriptions))],
            unit="{subscription}", description="Resources currently subscribed",
        )
    if background_tasks is not None:
        meter.create_observable_gauge(
            "mcp.server.background_tasks.active",
            callbacks=[_obs(lambda: len(background_tasks))],
            unit="{task}",
            description="Running background tasks (simulated logging / subscriber updates)",
        )


# --------------------------------------------------------------------------- #
# Prometheus scrape response (shared by both HTTP surfaces)
# --------------------------------------------------------------------------- #


def prometheus_response() -> Any:
    """A Starlette ``Response`` with the current Prometheus exposition."""

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
