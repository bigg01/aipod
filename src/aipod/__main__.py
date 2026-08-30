"""aipod CLI - pick a mode: ``aipod server`` or ``aipod agent``."""

from __future__ import annotations

import argparse
import json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aipod",
        description="One binary, two modes: a reference MCP server, or a pydantic-ai agent that consumes it.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    server = sub.add_parser("server", help="Run as an MCP server (exercises every MCP feature).")
    server.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default="http",
        help="http (Streamable HTTP + landing page, default) or stdio (subprocess clients).",
    )
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument(
        "--auth-token",
        default=None,
        metavar="KEY",
        help="Require 'Authorization: Bearer KEY' on /mcp (also via AIPOD_API_KEY / AIPOD_API_KEYS).",
    )
    server.add_argument(
        "--print",
        dest="print_doc",
        choices=["contract"],
        help="Print the service contract as JSON and exit.",
    )

    agent = sub.add_parser("agent", help="Run as a pydantic-ai agent that consumes an aipod server.")
    agent.add_argument("--host", default="127.0.0.1")
    agent.add_argument("--port", type=int, default=8080)
    agent.add_argument("--ask", metavar="PROMPT", help="Run one request, print the answer, and exit.")
    agent.add_argument("--model", default=None, help="Override AIPOD_MODEL for --ask.")
    agent.add_argument(
        "--print",
        dest="print_doc",
        choices=["agent-card"],
        help="Print the agent card as JSON and exit.",
    )
    return parser


def _run_server(args: argparse.Namespace) -> None:
    from .server.build import build_server

    mcp = build_server(host=args.host, port=args.port, auth_token=args.auth_token)

    if args.print_doc == "contract":
        import anyio

        from .server.contract import service_contract

        base_url = f"http://{args.host}:{args.port}"
        print(
            json.dumps(
                anyio.run(
                    lambda: service_contract(mcp, base_url=base_url, auth_token=args.auth_token)
                ),
                indent=2,
            )
        )
        return

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        from .server.auth import resolve_tokens

        note = " (bearer auth required)" if resolve_tokens(args.auth_token) else ""
        print(f"aipod server on http://{args.host}:{args.port}  (MCP at /mcp){note}")
        mcp.run("streamable-http")


def _run_agent(args: argparse.Namespace) -> None:
    if args.print_doc == "agent-card":
        from .agent.card import agent_card

        print(json.dumps(agent_card(f"http://{args.host}:{args.port}"), indent=2))
        return

    if args.ask is not None:
        import anyio

        from .agent.runtime import ask

        print(anyio.run(lambda: ask(args.ask, model=args.model)))
        return

    import uvicorn

    from .agent.http import build_app

    print(
        f"aipod agent on http://{args.host}:{args.port}  "
        "(agent card at /.well-known/agent-card.json)"
    )
    uvicorn.run(build_app(), host=args.host, port=args.port)


def main() -> None:
    args = _build_parser().parse_args()
    if args.mode == "server":
        _run_server(args)
    else:
        _run_agent(args)


if __name__ == "__main__":
    main()
