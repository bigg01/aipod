# Why I built a fake MCP server on purpose

![aipod — one binary, two modes](../banner.svg)

*Notes from a Solution Architect for AI, coming out of SRE and platform
engineering.*

---

## The problem

I design the plumbing that other people's AI agents run on: gateways, routers,
CI checks. That plumbing needs something real to test against.

Testing against production is risky. A quick hand-written stub only covers
the one call you needed last week. Waiting for a "real" server from another
team blocks your work on their schedule.

So I built `aipod`: an MCP server that deliberately implements every MCP
feature, in one place, for testing against.

## What it is

One program, two modes:

- **`aipod server`** — a reference MCP server. Tools, resources, prompts,
  auth, the works. Nothing it does matters for a business — it exists purely
  to be tested against.
- **`aipod agent`** — a small agent that calls `aipod server`, so you have a
  real client to test with too.

## Two documents worth knowing

Every agent and every server should be able to describe itself. `aipod`
publishes both of the documents that do that:

- **Agent card** — a short JSON file at `/.well-known/agent-card.json` that
  says "here's an agent, here's what it can do, here's how to reach it."
  Small and stable, meant for a registry or a router to read.
- **Service contract** — a longer JSON file at `/contract.json` listing every
  tool's exact input and output shape. Meant for generating a typed client,
  validating a call before it's sent, or diffing in CI when something
  changes.

Card answers *which* agent. Contract answers *exactly how to call it*. You
want both, generated from the running code, not hand-written.

## See it run

```bash
podman build -t aipod:latest .
podman run -d --rm -p 18000:8000 aipod:latest
curl -s http://127.0.0.1:18000/health
```

![Building and running aipod with podman](img/container-run.svg)

## Every tool, from a real MCP client

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is the
reference MCP client. Point it at the running container and ask what's there
— no model, no API key needed:

```bash
I="npx -y @modelcontextprotocol/inspector@0.16.8 --cli http://127.0.0.1:18000/mcp"
$I --method tools/list | jq -r '.tools[].name'
```

![The full list of tools the MCP Inspector sees](img/mcp-inspector.svg)

That's the whole surface: plain tools, a toy hero roster, a toy SRE/incident
system, and a few tools that borrow the caller's model via MCP sampling.
Real enough to catch real bugs in a gateway or a client, without touching
anything that matters.

## Use it from Claude Code

`aipod server` is an MCP server, so any MCP client can use it — including
Claude Code's own CLI. Point it at the running container:

```bash
claude mcp add --transport http aipod http://127.0.0.1:18000/mcp
claude mcp get aipod
```

![Registering aipod as an MCP server in the Claude Code CLI](img/claude-code-mcp.svg)

From there, just ask Claude to use one of aipod's tools — `get_hero`,
`check_service_health`, whatever's listed above. Same command works against
a remote agent too: swap the URL for wherever `aipod server` is actually
deployed (the k8s `Service` below, for instance) and nothing else changes.

## The same manifest, on Kubernetes

`aipod` ships the actual Kubernetes files it runs on — a `Deployment`, a
`Service`, a `ConfigMap`. Below, that `ConfigMap` and `Deployment` are started
unmodified with `podman kube play` (runs a Kubernetes manifest directly,
handy for a quick check without a cluster):

```bash
podman kube play k8s/configmap.yaml k8s/server.yaml --publish 18001:8000
podman pod ps
curl -s http://127.0.0.1:18001/contract.json | jq '.governance.owner, .governance.dataClassification'
```

![The k8s manifest running, governance labels flowing into the contract](img/k8s-run.svg)

`owner` and `dataClassification` came from the `ConfigMap`, not the code.
Change the manifest, and the document the server publishes changes with it —
which is what makes it something a reviewer can actually trust.

## Metrics, for free

Testing a gateway or a router is only half the job — you also need to know
whether *your* pipeline can actually see what's happening inside the thing
it's talking to. `aipod` ships OpenTelemetry metrics: per-tool call counts and
durations, off by default, one env var to turn on.

```bash
podman run -d --rm -p 18000:8000 -e AIPOD_METRICS=prometheus aipod:latest
# call a couple of tools, then:
curl -s http://127.0.0.1:18000/metrics | grep tool_calls_total
```

![aipod exposing OpenTelemetry metrics after a couple of tool calls](img/metrics.svg)

`AIPOD_METRICS` also takes `otlp` (push to a collector) or `console` (dump to
stdout) — same instruments either way:
`mcp.server.tool.calls`, `mcp.server.tool.duration`, and the agent-side
`aipod.agent.ask.calls` / `.duration`. Point your existing OTel pipeline at it
before you point it at a real fleet.

## Why it's worth having

A test fixture that only covers what one team happened to need isn't
infrastructure — it's a blind spot with a URL. `aipod` refuses to be partial:
every gateway, router, or CI check run against it has been run against the
whole protocol. Point it at anything that talks MCP, before you point that
thing at something real.
