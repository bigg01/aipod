"""OpenTelemetry **metrics** for aipod - shared by both modes.

Off unless asked for. It turns on when any of these is set:

* ``AIPOD_METRICS`` = ``otlp`` | ``prometheus`` | ``console`` (``none`` forces off)
* ``OTEL_METRICS_EXPORTER`` (standard OTel var; anything but ``none``)
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``

``OTEL_SDK_DISABLED=true`` forces it off regardless.

Exporters:

* ``otlp``       - periodic OTLP/HTTP push (endpoint from the standard env vars)
* ``prometheus`` - a ``/metrics`` scrape endpoint on the mode's HTTP port
* ``console``    - periodic dump to stdout (handy for a quick look)

Instruments:

* ``mcp.server.tool.calls``     counter   {mcp.tool.name, outcome, mcp.tool.sampling?}
* ``mcp.server.tool.duration``  histogram {…}  unit ``s``
* ``aipod.agent.ask.calls``     counter   {outcome}
* ``aipod.agent.ask.duration``  histogram {outcome}  unit ``s``
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
    """Which exporter the environment asks for (defaults to ``otlp``)."""

    for value in (_env("AIPOD_METRICS"), _env("OTEL_METRICS_EXPORTER")):
        if value in {"otlp", "prometheus", "console"}:
            return value
    return "otlp"


def configured() -> bool:
    """True when the environment asks for metrics."""

    if not _HAVE_OTEL:
        return False
    if _env("OTEL_SDK_DISABLED") == "true":
        return False

    aipod = _env("AIPOD_METRICS")
    if aipod in {"otlp", "prometheus", "console"}:
        return True
    if aipod and aipod in _OFF:
        return False  # AIPOD_METRICS explicitly disables, endpoint or not
    if aipod:
        return False  # set to something unrecognised -> treat as off

    if _env("OTEL_METRICS_EXPORTER") not in _OFF:
        return True
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


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


def reset() -> None:
    """Forget any provider/instruments (tests only)."""

    _state.update(provider=None, instruments=None, meter_id=None)


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
        "tool_calls": meter.create_counter(
            "mcp.server.tool.calls",
            unit="{call}",
            description="MCP tool invocations handled by the server",
        ),
        "tool_duration": meter.create_histogram(
            "mcp.server.tool.duration",
            unit="s",
            description="Wall-clock duration of an MCP tool invocation",
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


# --------------------------------------------------------------------------- #
# FastMCP instrumentation (wrap the one tool-dispatch chokepoint)
# --------------------------------------------------------------------------- #


def instrument_fastmcp(mcp: Any) -> None:
    """Time and count every tool call by wrapping the tool manager's dispatch."""

    if not configured():
        return
    manager = getattr(mcp, "_tool_manager", None)
    original = getattr(manager, "call_tool", None)
    if original is None or getattr(manager, "_aipod_instrumented", False):
        return

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


# --------------------------------------------------------------------------- #
# Prometheus scrape response (shared by both HTTP surfaces)
# --------------------------------------------------------------------------- #


def prometheus_response() -> Any:
    """A Starlette ``Response`` with the current Prometheus exposition."""

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
