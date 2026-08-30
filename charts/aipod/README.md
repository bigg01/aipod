# aipod Helm chart

Deploys **both** modes of the one `aipod` image:

- `Deployment/<release>-aipod-server` (+ `Service`, optional `Ingress`) — the MCP
  server. `replicas: 1` (per-session state + background tasks live in memory).
- `Deployment/<release>-aipod-agent` (+ `Service`, optional `Ingress`) — the
  pydantic-ai agent. `replicas: 2`, stateless; `AIPOD_MCP_URL` points at the
  server Service by default.
- `ConfigMap/<release>-aipod-config` — governance labels + `AIPOD_MODEL` + the
  computed `AIPOD_MCP_URL`, shared by both via `envFrom`.
- `ServiceAccount/<release>-aipod` (toggle with `serviceAccount.create`).
- `Secret`s for the bearer key and the model-provider key — created from inline
  values, or referenced via `*.existingSecret`.

Both pods run non-root, drop all capabilities, read-only rootfs, `RuntimeDefault`
seccomp, with an `emptyDir` at `/tmp`.

## Install

```bash
# from a checkout of the repo
helm install aipod ./charts/aipod

# server only, with bearer auth and an ingress
helm install aipod ./charts/aipod \
  --set agent.enabled=false \
  --set auth.enabled=true --set auth.apiKey=$(openssl rand -hex 16) \
  --set server.ingress.enabled=true --set server.ingress.host=mcp.example.com

# agent + server, provider key from a Secret you already manage
helm install aipod ./charts/aipod \
  --set model.existingSecret=my-anthropic-secret
```

Render without installing:

```bash
helm template aipod ./charts/aipod --debug
```

## Key values

| Key | Default | Notes |
| --- | --- | --- |
| `image.repository` / `image.tag` | `ghcr.io/bigg01/aipod` / `""` | tag falls back to chart `appVersion` |
| `server.enabled` / `agent.enabled` | `true` / `true` | deploy either half on its own |
| `server.replicas` | `1` | keep at 1 unless behind session affinity |
| `agent.replicas` | `2` | stateless |
| `config.*` | see `values.yaml` | rendered verbatim into the ConfigMap (governance labels) |
| `config.AIPOD_MCP_URL` | `""` | empty ⇒ computed in-cluster Service URL |
| `auth.enabled` | `false` | `true` ⇒ `/mcp` is an OAuth 2.1 protected resource |
| `auth.apiKey` / `auth.existingSecret` | `""` | inline key (chart makes the Secret) or bring your own |
| `model.apiKey` / `model.existingSecret` | `""` | provider key for agent mode; `/ask` is `503` without it |
| `metrics.exporter` | `"prometheus"` | OpenTelemetry metrics for both modes — `prometheus` (default, serves `/metrics`) / `otlp` / `console` / `none` |
| `metrics.otlpEndpoint` | `""` | OTLP/HTTP collector URL (`exporter: otlp`) |
| `metrics.prometheusScrapeAnnotations` | `true` | add `prometheus.io/scrape` pod annotations when `exporter: prometheus` |
| `*.ingress.enabled` | `false` | per-mode Ingress with `className` / `annotations` / `tls` |
| `*.resources` | 50m/128Mi → 500m/256Mi | per-mode requests/limits |

See [`values.yaml`](values.yaml) for the full set (pod annotations, nodeSelector,
tolerations, affinity, security contexts).

## Uninstall

```bash
helm uninstall aipod
```
