# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`aipod` is **one Python package, two modes**, selected by subcommand and sharing one `FROM scratch` container image:

- **`aipod server`** — a *reference* MCP server whose stated purpose is to exercise **every** MCP feature (tools, structured output, static + templated resources, prompts, argument completion, resource subscriptions, progress, logging levels, sampling) behind one endpoint, so client / gateway / runtime authors have a complete thing to test against. Completeness is the point: new MCP capabilities belong here, must stay working, and must be reflected in the contract + docs.
- **`aipod agent`** — a pydantic-ai `Agent` that is an MCP *client* of an `aipod server`.

`src/aipod/__main__.py` is the dispatcher. `--print contract` / `--print agent-card` emit JSON and exit without starting a server.

## Commands

Everything runs through `uv` (see `make help` for the full list):

| Task | Command |
| --- | --- |
| Install deps | `uv sync` |
| Run all tests | `uv run pytest -q` |
| Run one test | `uv run pytest tests/test_server.py::test_tool_inventory` |
| Server (HTTP) | `make server` — `uv run aipod server --transport http --host 127.0.0.1 --port 8000` |
| Server (stdio) | `make server-stdio` |
| Agent | `make agent` (needs `AIPOD_MODEL` + provider key for `/ask`) |
| One-shot agent call | `uv run aipod agent --ask "..."` |
| Regenerate contract | `make contract` → `examples/contract.json` |
| Regenerate agent card | `make card` → `examples/agent-card.json` |
| Exercise via MCP Inspector | `make inspect-cli` / see `docs/testing-mcp.md` (uses `@modelcontextprotocol/inspector@2.4.0` — the v2 line; v0.x / v1 is deprecated) |
| Build container | `make docker` |
| Standalone binary | `make binary` (PyInstaller; needs the `build` dependency group) |
| Render / lint Helm | `make helm-template` / `make helm-lint` |
| Apply Kustomize | `make k8s` |

There is **no linter or formatter configured** (no ruff/black in `pyproject.toml`).

Live instance for manual remote testing: `https://aipod.guggenbuehl.net/` (MCP at `/mcp`).

## Architecture

### Server mode — `src/aipod/server/`

`build_server()` in `build.py` builds **one** `FastMCP` instance and registers everything through a fixed sequence of `_register_*` helpers. To add an MCP feature, register it here.

- **`build.py`** — all tool / resource / prompt / completion registration. `_register_low_level_handlers` reaches into `mcp._mcp_server` for `subscribe` / `unsubscribe` / `setLevel` and monkeypatches `get_capabilities` to advertise `resources.subscribe` (FastMCP hardcodes it to `False` when deriving capabilities). Also calls `telemetry.instrument_fastmcp(mcp)` and registers `/`, `/health`, `/contract.json`, and (when Prometheus) `/metrics`.
- **`sampling_tools.py`** — pydantic-ai `Agent`s for the AI-backed tools (`poet`, `summarize`, `weather_report`, `hero_bio`, `incident_postmortem`). Their model is supplied **by the connected client** via MCP sampling: `sampling_model(ctx)` wraps `ctx.session` in `MCPSamplingModel`, so the server holds no provider credentials.
- **`heroes.py`** / **`sre.py`** — two toy domains (Marvel roster; a small SRE service estate) that give the tools realistic structured-output / stateful / side-effecting shapes. `sre.SREState` is instantiated fresh per `build_server()` call — its incident/deployment state is mutable but never leaks between server instances or test runs. Synthetic metrics/logs are deterministic (sha256-seeded `random.Random`).
- **`auth.py`** — optional bearer-token auth, **open by default**. A key via `--auth-token`, `AIPOD_API_KEY`, or `AIPOD_API_KEYS` turns `/mcp` into an OAuth 2.1 *protected resource*: `StaticTokenVerifier` (implements the `TokenVerifier` protocol) + `AuthSettings`, plus a public `/.well-known/oauth-protected-resource` (RFC 9728). `build_auth()` returns `(None, None)` when no key is set.
- **`contract.py`** — `service_contract()` introspects the **live** server (`mcp.list_tools()` etc.), so the contract can't drift from the code. Two module-level sets, `SAMPLING_TOOLS` and `SIDE_EFFECT_TOOLS`, drive each tool's `requiresSampling` / `sideEffects` / `dataEgress` facets. **Adding a tool means updating those sets** if it uses sampling or mutates state.
- **`data.py`** / **`landing.py`** — shared demo data + `INSTRUCTIONS` / `FEATURES_MD`, and the HTML page served at `/`. These list the tool set by hand — keep them current.

### Agent mode — `src/aipod/agent/`

- **`runtime.py`** — `build_toolset()` → `MCPToolset(AIPOD_MCP_URL, headers=...)` (bearer header when `AIPOD_MCP_TOKEN` is set); `build_agent()` attaches it to a pydantic-ai `Agent`; `ask()` runs a single request and records an OTel metric. Without `AIPOD_MODEL` the agent still constructs (for card / metadata) but cannot `.run()`.
- **`http.py`** — `build_app()` → Starlette app: `/`, `/health`, `/.well-known/agent-card.json` (+ `/agent.json`), `/ask`, and `/metrics` when Prometheus is enabled. `/ask` returns `503` if no model is configured.
- **`card.py`** — the A2A-style agent card with a non-standard `x-governance` block and a `dependencies` entry linking to the server's `/contract.json`.

### Shared

- **`governance.py`** — `base()` reads `AIPOD_*` env vars (`AIPOD_OWNER`, `AIPOD_DATA_CLASSIFICATION`, `AIPOD_REGULATORY_SCOPE`, …) into the label set that appears in **both** the server contract's `governance` block and the card's `x-governance` block. One image, relabelled per environment.
- **`telemetry.py`** — OpenTelemetry **metrics**, **on by default** with the `prometheus` exporter (serves `GET /metrics`); `AIPOD_METRICS=none` / `OTEL_METRICS_EXPORTER=none` / `OTEL_SDK_DISABLED=true` disable it, `AIPOD_METRICS=otlp|console` or a bare `OTEL_EXPORTER_OTLP_ENDPOINT` switch exporter. `configured()` gates instrumentation; `setup_metrics()` is called from `__main__` on the serving paths only; recording is a no-op until a `MeterProvider` exists. `instrument_fastmcp(mcp, subscriptions=…, background_tasks=…)` (called at the end of `build_server`) wraps `mcp._tool_manager.call_tool` for per-tool metrics **and** every entry in `mcp._mcp_server.request_handlers` for per-MCP-method metrics, and registers observable gauges for the registered inventory + live subscription/background-task counts. `sampling_tools.sampling_model()` calls `record_sampling()`.

## Conventions that bite

- **Generated files must stay in sync.** `examples/contract.json` and `examples/agent-card.json` are produced from the code; CI fails if the committed copies drift. Run `make contract card` after any change to tools, resources, prompts, the governance defaults, or the version. `contract.py` embeds `__version__`, so a version bump alone changes `contract.json`.
- **Version lives in three places** — bump together: `pyproject.toml`, `src/aipod/__init__.py` (`__version__`), and `charts/aipod/Chart.yaml` (`version` **and** `appVersion`). Then `uv lock` and regenerate `examples/`.
- **Kustomize and Helm are kept equivalent.** `k8s/` (raw manifests + kustomization) and `charts/aipod/` (Helm chart) deploy the same two Deployments/Services from the one image — change both.
- **Tests use pure `anyio`, never `pytest-asyncio`** (it deadlocks here). Every async test module has `pytestmark = pytest.mark.anyio` and a local `anyio_backend` fixture returning `"asyncio"`.
  - Server tests drive an **in-memory** MCP client/server via `mcp.shared.memory.create_connected_server_and_client_session(build_server(), sampling_callback=...)` with a stub sampling callback — no network, no API keys.
  - `tests/test_auth.py`, the agent HTTP tests, and the `/metrics` tests use `starlette.testclient.TestClient` against the real ASGI app (auth is a transport concern).
  - Telemetry tests inject a provider with `telemetry._install_provider_for_test(MeterProvider(metric_readers=[InMemoryMetricReader()]))` and call `telemetry.reset()` in teardown.

## Packaging & release

- **`Dockerfile`** builds `dist/aipod` with PyInstaller (`packaging/aipod.spec`, entry `packaging/entry.py`), runs it through **staticx**, and ships the static binary in `FROM scratch`. The spec deliberately **excludes** `pydantic_ai.models.*` / `pydantic_ai.providers.*` except `mcp_sampling` — if you add a server-side model provider, extend `hiddenimports` / `_keep` in the spec.
- **`.github/workflows/ci.yml`** runs on push/PR: pytest on 3.11–3.13, `uv build`, `uv lock --check`, the `examples/` drift check, `helm lint` + `kubeconform`, and a container smoke test.
- **`.github/workflows/release.yml`** runs on a `vX.Y.Z` tag whose number **must equal the `pyproject.toml` version** (a `guard` job enforces it). It pushes `ghcr.io/bigg01/aipod` (multi-tag, SBOM + provenance), pushes the Helm chart to `oci://ghcr.io/bigg01/charts`, builds the static binary, and creates a GitHub Release. To cut a release: bump the version (three files, above), commit, `git tag vX.Y.Z`, `git push origin vX.Y.Z`.
