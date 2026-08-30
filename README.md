<img src="docs/logo.svg" alt="aipod" width="72" align="left">

# aipod — one binary, two modes

<br clear="left">

**Purpose.** `aipod` is a single program you can start **as an MCP server** or
**as an agent**, chosen by a subcommand:

| Command | Mode | What it is | Publishes |
| --- | --- | --- | --- |
| `aipod server` | **MCP server** | a reference implementation of *every* MCP feature, so client / gateway / runtime authors have one endpoint to test against | a **service contract** (`GET /contract.json`) |
| `aipod agent` | **agent** | a [pydantic-ai](https://ai.pydantic.dev) agent that connects to an `aipod server` over MCP and exposes its tools to a model | an **agent card** (`GET /.well-known/agent-card.json`) |

Built on [`FastMCP`](https://github.com/modelcontextprotocol/python-sdk) (server
mode) and pydantic-ai's MCP client (agent mode). Packaged as a single
`FROM scratch` container; the same image runs either mode.

Repo: <https://github.com/bigg01/aipod>

> Wondering why a *reference* MCP server and agent are worth having around? See
> [`docs/blog/contracts-and-agent-cards.md`](docs/blog/contracts-and-agent-cards.md).

## Server mode — feature surface

| Area | Details |
| --- | --- |
| Tools | `echo`, `add`, `get_tiny_image`, `get_annotated_message`, `get_structured_weather`, `get_resource_reference`, `get_resource_links`, `trigger_long_running_operation`, `toggle_simulated_logging`, `toggle_subscriber_updates` |
| Marvel roster | `list_heroes`, `get_hero`, `find_heroes_by_power`, `assemble_team` — typed `Hero` / `HeroRoster` / `MissionTeam` output over a small fixed dataset |
| SRE / IT-application | `list_services`, `get_service`, `check_service_health`, `error_budget`, `search_logs`, `list_incidents`, `open_incident`, `update_incident`, `list_deployments`, `rollback_deployment`, `get_oncall`, `get_runbook` — a toy service estate with **mutable** incident / deployment state and deterministic synthetic metrics & logs |
| pydantic-ai tools | `poet`, `summarize` (structured output), `weather_report`, `hero_bio`, `incident_postmortem` — model supplied by the *client* via MCP **sampling** (no server-side key) |
| Structured output | `get_structured_weather` / `summarize` / the roster & SRE tools return typed Pydantic models → output schema + `structuredContent` |
| Side effects | `open_incident`, `update_incident`, `rollback_deployment` (+ the `toggle_*` / `trigger_*` demo tools) are flagged `sideEffects: true` in the contract |
| Content blocks | text, image, embedded resource, resource links, priority / audience annotations |
| Resources | static docs + templated `demo://resource/dynamic/{text,blob}/{resource_id}`, `hero://roster/{codename}`, `service://catalog/{name}`, `runbook://{service}` |
| Prompts | `simple_prompt`, `args_prompt`, `completable_prompt`, `resource_prompt` |
| Auth | **open by default**; add a key and `/mcp` becomes an OAuth 2.1 protected resource (bearer token + `/.well-known/oauth-protected-resource`) |
| Metrics | **off by default**; OpenTelemetry per-tool call count + duration, exported via OTLP / Prometheus `/metrics` / console |
| Also | argument completion, resource subscriptions, progress, `logging/setLevel` |

HTTP routes: `GET /` (landing), `GET /health`, `GET|POST /mcp`, `GET /contract.json`,
and — when enabled — `GET /.well-known/oauth-protected-resource` (auth) and
`GET /metrics` (Prometheus).

## Agent mode

```
        HTTP + JSON                    MCP (Streamable HTTP)
client ─────────────▶ aipod agent ────────────────────────▶ aipod server
                      pydantic-ai Agent + model provider    tools / resources / prompts
```

HTTP routes: `GET /`, `GET /health`, `GET /.well-known/agent-card.json`,
`POST /ask` (`{"prompt": "..."}` → `{"output": "..."}`).

Agent mode needs a model — `AIPOD_MODEL` (e.g. `anthropic:claude-haiku-4-5`) plus
the provider key. Without one it still serves the card and `/health`; `/ask`
returns `503`.

## Requirements

- Python ≥ 3.11, [uv](https://docs.astral.sh/uv/)
- Docker + a Kubernetes cluster (optional)

## Run locally

```bash
uv sync

# server mode
uv run aipod server                            # http://127.0.0.1:8000  (MCP at /mcp)
uv run aipod server --transport stdio          # for subprocess clients (Claude Desktop, editors)
uv run aipod server --print contract           # emit the service contract as JSON
uv run aipod server --auth-token s3cret        # require 'Authorization: Bearer s3cret' on /mcp

# agent mode (needs a running server + a model)
export AIPOD_MCP_URL=http://127.0.0.1:8000/mcp
export AIPOD_MODEL=anthropic:claude-haiku-4-5
export ANTHROPIC_API_KEY=...
uv run aipod agent                             # http://127.0.0.1:8080
uv run aipod agent --ask "Write a poem about sockets, then summarise it."
uv run aipod agent --print agent-card          # emit the agent card as JSON
```

### stdio vs. HTTP (server mode)

- **Streamable HTTP** (default) — a long-running network service; clients connect
  to `/mcp`, responses and notifications stream back as SSE. Use for anything
  shared or deployed.
- **stdio** — no network listener. The **client launches `aipod server` as a
  child process** and talks to it over that process's stdin/stdout. "Subprocess
  clients" are desktop / editor MCP hosts (Claude Desktop, Cursor, the VS Code
  MCP extension) that work this way; you never start the server yourself.

## Authentication (optional)

The server runs **open by default**. Give it a key and the Streamable HTTP
`/mcp` route becomes an OAuth 2.1 *protected resource*:

```bash
uv run aipod server --auth-token s3cret          # or: AIPOD_API_KEY=s3cret
export AIPOD_API_KEYS="key-a,key-b"              # multiple keys (rotation / per-client)
```

| Env var | Effect |
| --- | --- |
| `AIPOD_API_KEY` / `AIPOD_API_KEYS` | keys the server accepts (`--auth-token` wins) |
| `AIPOD_AUTH_SCOPES` | CSV of scopes a caller must hold (default: none) |
| `AIPOD_AUTH_ISSUER` | authorization-server URL advertised in metadata (default: this server) |
| `AIPOD_PUBLIC_URL` | externally reachable base URL when behind a proxy / ingress |

With auth on:

- requests to `/mcp` without `Authorization: Bearer <key>` get `401` + a
  `WWW-Authenticate` header pointing at
  `GET /.well-known/oauth-protected-resource` (RFC 9728);
- that metadata document lists the authorization server(s) and scopes;
- `contract.json` → `security` switches from `{"scheme":"none"}` to a `bearer`
  block, and `clientRequirements.authentication.required` becomes `true`.

Tokens are checked against the static key list — the resource-server half of the
spec without an identity provider. For **full OAuth 2.1**, point
`AIPOD_AUTH_ISSUER` at a real authorization server and replace
`StaticTokenVerifier` in `src/aipod/server/auth.py` with a JWT-validating one.

`aipod agent` reaches a protected server by setting `AIPOD_MCP_TOKEN`.

```bash
curl -s http://127.0.0.1:8000/mcp -X POST ... -H 'Authorization: Bearer s3cret'
curl -s http://127.0.0.1:8000/.well-known/oauth-protected-resource | jq
```

Full walkthrough in [`docs/testing-mcp.md`](docs/testing-mcp.md#authentication).

## Observability (OpenTelemetry)

Both modes emit OpenTelemetry **metrics** — off until you ask for an exporter.

| Instrument | Type | Attributes |
| --- | --- | --- |
| `mcp.server.tool.calls` | counter | `mcp.tool.name`, `outcome` (`ok`/`error`), `mcp.tool.sampling` |
| `mcp.server.tool.duration` | histogram (s) | same |
| `aipod.agent.ask.calls` | counter | `outcome` |
| `aipod.agent.ask.duration` | histogram (s) | `outcome` |

Turn it on with `AIPOD_METRICS` (or the standard `OTEL_*` vars):

```bash
# scrape endpoint on the mode's HTTP port
AIPOD_METRICS=prometheus uv run aipod server   # -> GET /metrics
curl -s localhost:8000/metrics | grep mcp_server_tool

# push to an OTLP/HTTP collector
AIPOD_METRICS=otlp OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run aipod agent

# quick look on stdout
AIPOD_METRICS=console uv run aipod server
```

`AIPOD_METRICS` = `otlp` \| `prometheus` \| `console` (`none` / unset = off);
`OTEL_METRICS_EXPORTER` or a bare `OTEL_EXPORTER_OTLP_ENDPOINT` also switch it on;
`OTEL_SDK_DISABLED=true` forces it off. `OTEL_SERVICE_NAME` /
`OTEL_RESOURCE_ATTRIBUTES` set the resource. In k8s: `metrics.exporter` in the
Helm values, or `AIPOD_METRICS` in `k8s/configmap.yaml`.

## Test

```bash
uv run pytest
```

Hermetic — server tests drive an in-memory MCP session with a stubbed sampling
callback; agent tests need no running server and no API key.

### Exercise the server with the MCP Inspector

[`@modelcontextprotocol/inspector`](https://github.com/modelcontextprotocol/inspector)
is the reference MCP client — it speaks the raw protocol, so no model or API key
is needed (except for the sampling-backed tools).

```bash
uv run aipod server                      # start a server (MCP at :8000/mcp)

# interactive UI (http://127.0.0.1:6274)
npx -y @modelcontextprotocol/inspector                          # or: make inspect

# scripted / CI — one request per call (transport auto-detected from /mcp)
npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8000/mcp --method tools/list                 # or: make inspect-cli
npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8000/mcp --method tools/call --tool-name add --tool-arg a=2 --tool-arg b=3
```

Full walkthrough — every feature (structured output, resource templates,
completion, subscriptions, logging, progress, sampling), the `--cli` vs UI split,
stdio via an `mcp.json`, and a CI gate example — in
[`docs/testing-mcp.md`](docs/testing-mcp.md).

## Container (`FROM scratch`)

One image, either mode. PyInstaller bundles the app, **staticx** folds in libc,
the final image is `FROM scratch` (binary + `/tmp` + CA certs + `/etc/passwd`),
~34 MB.

```bash
docker build -t aipod:latest .

docker run --rm -p 8000:8000 aipod:latest                      # server (default CMD)
docker run --rm -p 8080:8080 \
  -e AIPOD_MCP_URL=http://host.docker.internal:8000/mcp \
  -e AIPOD_MODEL=anthropic:claude-haiku-4-5 -e ANTHROPIC_API_KEY=... \
  aipod:latest agent --host 0.0.0.0 --port 8080                 # agent
```

The binary self-extracts into `TMPDIR` (`/tmp`) on start, so the runtime needs a
writable `/tmp` even with a read-only root filesystem.

## Kubernetes

Both modes deploy from the one image, two ways:

### Kustomize — [`k8s/`](k8s/)

`kubectl apply -k k8s`:

- `Deployment/aipod-server` (+ `Service/aipod-server`) — `replicas: 1` (per-session
  state + background tasks live in memory)
- `Deployment/aipod-agent` (+ `Service/aipod-agent`, `Ingress`) — `replicas: 2`,
  stateless; `AIPOD_MCP_URL` points at the server Service
- `ConfigMap/aipod-config` — governance labels + `AIPOD_MODEL`; provider key from a
  Secret you create (`kubectl create secret generic aipod-model --from-literal=ANTHROPIC_API_KEY=...`)
- `Secret/aipod-auth` *(optional)* — `AIPOD_API_KEY` turns on bearer auth for the
  server and is reused by the agent as `AIPOD_MCP_TOKEN`
  (`kubectl create secret generic aipod-auth --from-literal=AIPOD_API_KEY=$(openssl rand -hex 16)`)

### Helm — [`charts/aipod/`](charts/aipod/)

```bash
# from a checkout
helm install aipod ./charts/aipod

# or the published OCI chart
helm install aipod oci://ghcr.io/bigg01/charts/aipod --version 0.1.0 \
  -f examples/helm-values.yaml
```

Same objects, parameterised: `server.enabled` / `agent.enabled`, `*.replicas`,
`*.ingress.*`, `*.resources`, the `config` map, and `auth` / `model` (inline key ⇒
the chart makes the Secret, or point at `*.existingSecret`). Full list in
[`charts/aipod/values.yaml`](charts/aipod/values.yaml);
[`examples/helm-values.yaml`](examples/helm-values.yaml) is a TLS-ingress + bearer-auth
override. `make helm-lint` / `helm-template` / `helm-install`.

Both pods run non-root, no capabilities, read-only rootfs, `RuntimeDefault`
seccomp, with an `emptyDir` at `/tmp`.

## CI / releases

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push / PR:
`pytest` on Python 3.11–3.13, `uv build`, `uv lock --check`, a check that
`examples/` is in sync, `helm lint` + `kubeconform` on the rendered manifests, and
a `FROM scratch` image build with a `/health` + `/contract.json` smoke test.

[`.github/workflows/release.yml`](.github/workflows/release.yml) runs on a
`vX.Y.Z` tag (which must match the `pyproject.toml` version): pushes
`ghcr.io/bigg01/aipod` (semver + `latest` + `sha` tags, SBOM + build provenance),
pushes the Helm chart to `oci://ghcr.io/bigg01/charts`, builds the static
`aipod-linux-x86_64` binary, and cuts a GitHub Release with the binary and chart
attached.

## Governance

Both modes carry the same labels from `AIPOD_*` env vars — a `governance` block in
the server contract, an `x-governance` block (plus a `dependencies` link to the
server's contract) in the agent card:

| Env var | Field |
| --- | --- |
| `AIPOD_OWNER` | `owner` / `provider.organization` |
| `AIPOD_DOMAIN` | `domain` |
| `AIPOD_DATA_CLASSIFICATION` | `dataClassification` (`PUBLIC`…`RESTRICTED`) |
| `AIPOD_DATA_RESIDENCY` | `dataResidency` |
| `AIPOD_REGULATORY_SCOPE` | `regulatoryScope` (CSV) |
| `AIPOD_AUTH_SCHEMES` | `authenticationSchemes` (CSV) |
| `AIPOD_CONTAINS_PII` | `containsPII` |

Per-tool the contract also has `requiresSampling`, `sideEffects`, and `dataEgress`
so a router / gateway can gate calls on data movement and state changes rather
than on tool names.

## Layout

```
src/aipod/
  __main__.py          CLI - `aipod server` | `aipod agent`
  governance.py        shared AIPOD_* governance labels
  telemetry.py         OpenTelemetry metrics (both modes)
  server/
    build.py           every MCP feature on one FastMCP instance
    sampling_tools.py   pydantic-ai tools (model via MCP sampling)
    heroes.py          Marvel roster data + models for the roster tools
    sre.py            IT-application / SRE estate: catalogue, incidents, deploys, metrics
    auth.py            optional bearer-token / OAuth 2.1 protected-resource auth
    contract.py         service contract builder
    data.py, landing.py
  agent/
    runtime.py          pydantic-ai Agent + MCP toolset -> the server
    card.py             agent card builder
    http.py             Starlette app: card, /health, /ask, /metrics
    config.py           AIPOD_MCP_URL, AIPOD_MODEL, ...
packaging/  PyInstaller entry + spec
examples/   generated contract.json + agent-card.json + helm-values.yaml
k8s/        both Deployments, Services, Ingress, ConfigMap, kustomization
charts/aipod/  Helm chart (same objects, parameterised)
.github/workflows/  ci.yml (test + build) + release.yml (image + chart + binary)
docs/       testing-mcp.md (Inspector walkthrough) + blog/ (contracts & agent cards)
tests/      test_server.py + test_agent.py
```
