# Testing the `aipod` MCP server

Three ways to exercise `aipod server`, fastest first:

| Level | Tool | Needs | Good for |
| --- | --- | --- | --- |
| Unit / regression | `uv run pytest` | nothing | CI, refactors — hermetic, stubbed sampling |
| Scripted protocol | **MCP Inspector, `--cli`** | Node.js / `npx` | one request per call, CI gates, `jq` pipelines |
| Manual protocol | **MCP Inspector, UI** | Node.js / `npx` | clicking through tools, resources, prompts, sampling, notifications |

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(`@modelcontextprotocol/inspector`) is the reference MCP client. It speaks the
raw protocol, so it shows exactly what a real client sees — no model or API key,
except for the sampling-backed tools (see [Sampling](#sampling)). Examples below
use the current line (**v2**, `2.4.0` at time of writing).

---

## 0. Start a server to test against

```bash
# Streamable HTTP — a real listener; used by every HTTP example below
uv run aipod server --transport http --host 127.0.0.1 --port 8000
#   MCP endpoint: http://127.0.0.1:8000/mcp
```

Non-MCP smoke test of the listener:

```bash
curl -s http://127.0.0.1:8000/health        | jq
curl -s http://127.0.0.1:8000/contract.json | jq '.tools[].name'
```

---

## 1. `pytest` — the hermetic suite

```bash
uv run pytest -q          # or: make test
```

`tests/test_server.py` drives an **in-memory** MCP session
(`mcp.shared.memory.create_connected_server_and_client_session`) with a stubbed
sampling callback, so every feature — tools, structured output, resources,
templates, prompts, completion, subscriptions, logging, progress, and the
contract shape — is covered with no listener and no model. Use it as the
template for your own regression tests.

---

## 2. MCP Inspector — `--cli` (scriptable)

`npx` fetches it; nothing to install. Against an HTTP server the transport is
auto-detected from the `/mcp` suffix.

```bash
I="npx -y @modelcontextprotocol/inspector@2.4.0 --cli http://127.0.0.1:8000/mcp"
```

### Discover

```bash
$I --method tools/list
$I --method resources/list
$I --method resources/templates/list
$I --method prompts/list
```

### Call plain tools

```bash
$I --method tools/call --tool-name echo --tool-arg message="hello aipod"
$I --method tools/call --tool-name add  --tool-arg a=2 --tool-arg b=3
```

### Structured output — `structuredContent` validated against the output schema

```bash
$I --method tools/call --tool-name get_structured_weather --tool-arg location="Los Angeles"
# result carries both `content` (text) and `structuredContent` (typed Weather)
```

### Marvel roster tools (typed output over a fixed dataset)

```bash
$I --method tools/call --tool-name list_heroes
$I --method tools/call --tool-name list_heroes --tool-arg team=X-Men
$I --method tools/call --tool-name get_hero --tool-arg codename=spider-man
$I --method tools/call --tool-name find_heroes_by_power --tool-arg power=flight
$I --method tools/call --tool-name assemble_team \
   --tool-arg threat="a lightning storm over the harbour" --tool-arg size=3
$I --method resources/read --uri "hero://roster/storm"
```

### SRE / IT-application tools

```bash
# catalogue + health
$I --method tools/call --tool-name list_services --tool-arg tier=1
$I --method tools/call --tool-name get_service --tool-arg name=checkout-api
$I --method tools/call --tool-name check_service_health --tool-arg name=payments-api
$I --method tools/call --tool-name error_budget --tool-arg name=checkout-api

# logs (synthetic but deterministic — same query, same lines)
$I --method tools/call --tool-name search_logs \
   --tool-arg service=checkout-api --tool-arg query="slow query" --tool-arg limit=10

# incidents — open_incident / update_incident mutate in-memory state for this server
$I --method tools/call --tool-name list_incidents --tool-arg status=open
$I --method tools/call --tool-name open_incident \
   --tool-arg service=checkout-api --tool-arg severity=SEV3 --tool-arg summary="checkout 500s"
$I --method tools/call --tool-name update_incident \
   --tool-arg incident_id=INC-0003 --tool-arg status=resolved --tool-arg note="cache flag on"

# deployments, on-call, runbooks
$I --method tools/call --tool-name list_deployments --tool-arg service=checkout-api
$I --method tools/call --tool-name rollback_deployment --tool-arg deployment_id=dep-0001
$I --method tools/call --tool-name get_oncall --tool-arg team_or_service=payments-api
$I --method tools/call --tool-name get_runbook --tool-arg service=checkout-api --tool-arg symptom=latency
$I --method resources/read --uri "service://catalog/auth-service"
$I --method resources/read --uri "runbook://checkout-api"
```

> `open_incident`, `update_incident`, and `rollback_deployment` are flagged
> `sideEffects: true` in `contract.json`. State lives in the server process, so
> `--cli` calls (each a fresh connection) see the same store, but restarting the
> server resets it.

### Content blocks — image, annotations, embedded resource, resource links

```bash
$I --method tools/call --tool-name get_tiny_image
$I --method tools/call --tool-name get_annotated_message \
   --tool-arg message_type=error --tool-arg include_image=true
$I --method tools/call --tool-name get_resource_reference \
   --tool-arg resource_id=1 --tool-arg kind=text
$I --method tools/call --tool-name get_resource_links --tool-arg count=3
```

### Read resources — static and templated

```bash
$I --method resources/read --uri "demo://resource/static/features.md"
$I --method resources/read --uri "demo://resource/dynamic/text/7"
$I --method resources/read --uri "demo://resource/dynamic/blob/7"
```

### Prompts

```bash
$I --method prompts/get --prompt-name simple_prompt
$I --method prompts/get --prompt-name args_prompt     --prompt-args city=Chicago
$I --method prompts/get --prompt-name resource_prompt --prompt-args resource_id=2 kind=text
```

### Logging level

```bash
$I --method logging/setLevel --log-level warning
```

### UI-only from here

The `--cli` runner supports `initialize`, `tools/*`, `resources/list|read|templates/list`,
`prompts/list|get`, and `logging/setLevel`. **Argument completion, resource
subscriptions, progress streams, and sampling** are request/notification flows
you watch over time — drive those from the [UI](#3-mcp-inspector--ui-interactive)
or from `pytest`.

### stdio instead of HTTP

The `--cli` runner can't take a launch command whose own flags (`--transport
stdio`) collide with the Inspector's. Point it at a small server config instead —
the same `mcp.json` shape a desktop MCP host uses:

```jsonc
// mcp.json
{ "mcpServers": { "aipod": {
    "command": "uv",
    "args": ["run", "aipod", "server", "--transport", "stdio"]
} } }
```

```bash
npx -y @modelcontextprotocol/inspector@2.4.0 --cli \
  --config mcp.json --server aipod --method tools/list
```

### Use it as a CI gate

```bash
# fail the build if an expected tool disappears or the count drops
$I --method tools/list | jq -e '
  ([.tools[].name] | length) >= 31 and
  ([.tools[].name] | index("check_service_health")) and
  ([.tools[].name] | index("open_incident")) and
  ([.tools[].name] | index("get_hero"))' >/dev/null

# stricter: pin the whole sorted list (regenerate on purpose)
$I --method tools/list | jq -S '[.tools[].name] | sort' > tools.expected.json
```

---

## Authentication

`aipod server` is **open by default**. Start it with a key and `/mcp` turns into
an OAuth 2.1 protected resource — a bearer token on every request, plus RFC 9728
protected-resource metadata.

```bash
uv run aipod server --auth-token s3cret          # or AIPOD_API_KEY / AIPOD_API_KEYS
```

### From `curl`

```bash
# metadata is public
curl -s http://127.0.0.1:8000/.well-known/oauth-protected-resource | jq

# no token → 401 + a WWW-Authenticate challenge that points back at that metadata
curl -si http://127.0.0.1:8000/mcp -X POST \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' | head -n 20

# with the key → request is accepted
curl -s http://127.0.0.1:8000/mcp -X POST \
  -H 'Authorization: Bearer s3cret' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

### From the Inspector

- **`--cli`** — pass the token as a header:

  ```bash
  npx -y @modelcontextprotocol/inspector@2.4.0 --cli \
    http://127.0.0.1:8000/mcp --header "Authorization: Bearer s3cret" --method tools/list
  ```

- **UI** — in the connection pane set **Authentication → Bearer Token** to the
  key, or (against a real authorization server) use the built-in **OAuth 2.1**
  flow, which discovers the endpoints from the protected-resource metadata.

### Scopes

`AIPOD_AUTH_SCOPES="mcp:invoke,mcp:admin"` makes those scopes required. The
static verifier grants every configured key all of them, so a valid key still
passes; the point is to exercise a client's scope handling and to populate
`scopes_supported` in the metadata.

### From `pytest`

`tests/test_auth.py` drives the real ASGI app with a `TestClient`: metadata is
public, missing / wrong tokens get `401` with the `resource_metadata=` hint, and
a valid token clears the auth layer.

### Real OAuth 2.1

The static allow-list is the resource-server half of the spec. For end-to-end
OAuth 2.1, point `AIPOD_AUTH_ISSUER` at an authorization server and swap
`StaticTokenVerifier` (`src/aipod/server/auth.py`) for one that validates the
issuer's JWTs (signature, `aud`, `exp`, scopes).

---

## Metrics (OpenTelemetry)

Off unless asked for. `AIPOD_METRICS` = `prometheus` \| `otlp` \| `console`
(standard `OTEL_*` vars work too; `OTEL_SDK_DISABLED=true` forces off).

```bash
AIPOD_METRICS=prometheus uv run aipod server --transport http --port 8000 &
# call a couple of tools first so the counters exist
npx -y @modelcontextprotocol/inspector@2.4.0 --cli http://127.0.0.1:8000/mcp \
  --method tools/call --tool-name echo --tool-arg message=hi

curl -s http://127.0.0.1:8000/metrics | grep -E 'mcp_server_tool_(calls|duration)'
# mcp_server_tool_calls_total{mcp_tool_name="echo",outcome="ok",...} 1.0
```

Instruments: `mcp.server.tool.calls` / `mcp.server.tool.duration`
(attrs `mcp.tool.name`, `outcome`, `mcp.tool.sampling`) in server mode;
`aipod.agent.ask.calls` / `aipod.agent.ask.duration` in agent mode.
`tests/test_telemetry.py` asserts them with an in-memory reader.

---

## 3. MCP Inspector — UI (interactive)

```bash
npx -y @modelcontextprotocol/inspector@2.4.0
# opens http://127.0.0.1:6274 and prints a pre-authed URL (session token)
```

**Connect to the running HTTP server**

1. Transport type → **Streamable HTTP**
2. URL → `http://127.0.0.1:8000/mcp`
3. **Connect**

**Or let the Inspector spawn a stdio server**

1. Transport type → **STDIO**
2. Command → `uv`   ·   Arguments → `run aipod server --transport stdio`
3. **Connect**

Then work the tabs:

| Tab | Try |
| --- | --- |
| **Tools** | `add`; `get_tiny_image` (renders the PNG); `get_annotated_message` (shows priority / audience) |
| **Resources** | open `features.md`; expand the templates, read `demo://resource/dynamic/text/{id}`; click **Subscribe**, then run `toggle_subscriber_updates` and watch `resources/updated` arrive |
| **Prompts** | fill `args_prompt`; on `completable_prompt` the argument fields autocomplete from the server's completion handler (pick a department, then the name field narrows to that team) |
| **Sampling** | approve the incoming request so `poet` / `summarize` / `weather_report` can return — see below |
| **Notifications** pane | set the log level, run `toggle_simulated_logging`, watch messages filter by level; also shows progress events from `trigger_long_running_operation` |

---

## Sampling

`poet`, `summarize`, and `weather_report` carry no API key. Each asks the
**client** to run the model via the MCP `sampling/createMessage` request, so the
result depends on the client:

- **Inspector UI** — the **Sampling** tab surfaces each request; paste a response
  (or wire a real model) and approve it, and the tool call completes.
  `summarize` expects a JSON object with `headline`, `summary`, `key_points`.
- **Inspector `--cli`** — does not answer sampling requests, so these tools stall.
  Cover them with `pytest` (stubbed callback) or end-to-end through `aipod agent`
  with a real model:

```bash
export AIPOD_MCP_URL=http://127.0.0.1:8000/mcp
export AIPOD_MODEL=anthropic:claude-haiku-4-5
export ANTHROPIC_API_KEY=...
uv run aipod agent --ask "Use the poet tool to write about TCP sockets."
```

---

## Cheat sheet (`--cli`)

| Feature | Method | Example flags |
| --- | --- | --- |
| List / call tool | `tools/list`, `tools/call` | `--tool-name echo --tool-arg message=hi` |
| Structured output | `tools/call` | `--tool-name get_structured_weather --tool-arg location=Chicago` |
| Marvel roster | `tools/call` | `--tool-name get_hero --tool-arg codename=storm` |
| SRE estate | `tools/call` | `--tool-name check_service_health --tool-arg name=payments-api` |
| Read resource | `resources/read` | `--uri "service://catalog/checkout-api"` |
| List templates | `resources/templates/list` | — |
| Get prompt | `prompts/get` | `--prompt-name args_prompt --prompt-args city=Chicago` |
| Set log level | `logging/setLevel` | `--log-level warning` |
| Auth (when enabled) | any | `--header "Authorization: Bearer <key>"` |
| Completion, subscribe, progress, sampling | — | UI only (or `pytest`) |
