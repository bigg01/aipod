"""HTTP surface for `aipod agent`: agent card, health, and a simple /ask endpoint."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .. import __version__, telemetry
from ..branding import LOGO_SVG
from .card import agent_card
from .config import mcp_url, model_name
from .runtime import ask

_LANDING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aipod &mdash; agent mode</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ margin:0; padding:3rem 1.25rem; font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
        background:#0b0d12; color:#e7e9ee; }}
 main {{ max-width:720px; margin:0 auto; }}
 .brand {{ display:flex; align-items:center; gap:.7rem; margin-bottom:.25rem; }}
 h1 {{ margin:0; }} .tag {{ color:#8b93a7; }}
 code {{ font-family:ui-monospace,Menlo,monospace; background:#151922; padding:.15rem .4rem; border-radius:6px; }}
 li {{ margin:.3rem 0; }}
 .ver {{ font:600 .8rem/1 ui-monospace,Menlo,monospace; color:#9ecbff; background:#151922;
         border:1px solid #262c3a; border-radius:999px; padding:.25rem .6rem; }}
 footer {{ margin-top:2.5rem; color:#6b7385; font-size:.9rem; }}
 a {{ color:#9ecbff; }}
</style></head><body><main>
<div class="brand">{logo}<h1>aipod &mdash; agent mode</h1><span class="ver">v{version}</span></div>
<p class="tag">A pydantic-ai agent. It calls tools from the aipod MCP server at
<code>{mcp}</code>.</p>
<ul>
  <li><code>GET /.well-known/agent-card.json</code> &mdash; the agent card</li>
  <li><code>GET /health</code> &mdash; readiness / liveness</li>
  <li><code>POST /ask</code> &mdash; accepts <code>{{"prompt": "..."}}</code> or
      <code>{{"input": "..."}}</code>; returns legacy <code>{{"output": "..."}}</code>
      or a Responses-style payload
      {model_note}</li>
</ul>
<footer>Source: <a href="https://github.com/bigg01/aipod">github.com/bigg01/aipod</a></footer>
</main></body></html>
"""


async def _homepage(_request: Request) -> HTMLResponse:
    note = (
        f"(model: <code>{model_name()}</code>)"
        if model_name()
        else "(no <code>AIPOD_MODEL</code> configured &mdash; returns 503)"
    )
    return HTMLResponse(
        _LANDING.format(logo=LOGO_SVG, mcp=mcp_url(), model_note=note, version=__version__)
    )


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "mcpUrl": mcp_url(),
            "model": model_name() or None,
            "ready": model_name() is not None,
        }
    )


async def _agent_card(request: Request) -> JSONResponse:
    return JSONResponse(agent_card(str(request.base_url)))


async def _metrics(_request: Request):  # type: ignore[no-untyped-def]
    return telemetry.prometheus_response()


def _iter_text_parts(content: object) -> Iterable[str]:
    if isinstance(content, str):
        yield content
        return
    if not isinstance(content, list):
        return
    for part in content:
        if isinstance(part, str):
            yield part
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            yield text


def _extract_prompt(body: object) -> tuple[str | None, bool]:
    if not isinstance(body, dict):
        return None, False

    prompt = body.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt, False

    input_value = body.get("input")
    if input_value is None:
        return None, False

    if isinstance(input_value, str) and input_value.strip():
        return input_value, True

    if isinstance(input_value, dict):
        input_value = [input_value]

    if not isinstance(input_value, list):
        return None, True

    chunks: list[str] = []
    for item in input_value:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            chunks.append(text)
        chunks.extend(_iter_text_parts(item.get("content")))

    prompt = "\n".join(part.strip() for part in chunks if part.strip())
    return (prompt if prompt else None), True


def _responses_payload(output_text: str) -> dict[str, object]:
    response_id = f"resp_{uuid4().hex}"
    message_id = f"msg_{uuid4().hex}"
    return {
        "id": response_id,
        "object": "response",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "completed",
        "model": model_name() or "",
        "output": [
            {
                "id": message_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            }
        ],
        "output_text": output_text,
    }


async def _ask(request: Request) -> JSONResponse:
    if model_name() is None:
        return JSONResponse(
            {"error": "no model configured; set AIPOD_MODEL and a provider API key"},
            status_code=503,
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    prompt, responses_shape = _extract_prompt(body)
    if not prompt:
        return JSONResponse(
            {"error": "missing 'prompt' string or non-empty 'input' content"},
            status_code=400,
        )
    output = await ask(prompt)
    if responses_shape:
        return JSONResponse(_responses_payload(output))
    return JSONResponse({"output": output})


def build_app() -> Starlette:
    routes = [
        Route("/", _homepage, methods=["GET"]),
        Route("/health", _health, methods=["GET"]),
        Route("/.well-known/agent-card.json", _agent_card, methods=["GET"]),
        Route("/.well-known/agent.json", _agent_card, methods=["GET"]),
        Route("/ask", _ask, methods=["POST"]),
    ]
    if telemetry.prometheus_enabled():
        routes.append(Route("/metrics", _metrics, methods=["GET"]))
    return Starlette(routes=routes)
