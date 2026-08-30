"""HTTP surface for `aipod agent`: agent card, health, and a simple /ask endpoint."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

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
</style></head><body><main>
<div class="brand">{logo}<h1>aipod &mdash; agent mode</h1></div>
<p class="tag">A pydantic-ai agent. It calls tools from the aipod MCP server at
<code>{mcp}</code>.</p>
<ul>
  <li><code>GET /.well-known/agent-card.json</code> &mdash; the agent card</li>
  <li><code>GET /health</code> &mdash; readiness / liveness</li>
  <li><code>POST /ask</code> &mdash; <code>{{"prompt": "..."}}</code> &rarr; <code>{{"output": "..."}}</code>
      {model_note}</li>
</ul>
</main></body></html>
"""


async def _homepage(_request: Request) -> HTMLResponse:
    note = (
        f"(model: <code>{model_name()}</code>)"
        if model_name()
        else "(no <code>AIPOD_MODEL</code> configured &mdash; returns 503)"
    )
    return HTMLResponse(_LANDING.format(logo=LOGO_SVG, mcp=mcp_url(), model_note=note))


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "mcpUrl": mcp_url(),
            "model": model_name() or None,
            "ready": model_name() is not None,
        }
    )


async def _agent_card(request: Request) -> JSONResponse:
    return JSONResponse(agent_card(str(request.base_url)))


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
    prompt = (body or {}).get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse({"error": "missing 'prompt' string"}, status_code=400)
    output = await ask(prompt)
    return JSONResponse({"output": output})


def build_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/", _homepage, methods=["GET"]),
            Route("/health", _health, methods=["GET"]),
            Route("/.well-known/agent-card.json", _agent_card, methods=["GET"]),
            Route("/.well-known/agent.json", _agent_card, methods=["GET"]),
            Route("/ask", _ask, methods=["POST"]),
        ]
    )
