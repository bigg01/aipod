# Examples

| File | What it is | Regenerate / keep in sync |
| --- | --- | --- |
| `contract.json` | service contract served at `GET /contract.json` | `make contract` (`uv run aipod server --print contract`) |
| `agent-card.json` | agent card served at `GET /.well-known/agent-card.json` | `make card` (`uv run aipod agent --print agent-card`) |
| `helm-values.yaml` | a production-ish override for the [`charts/aipod`](../charts/aipod) Helm chart | hand-maintained; mirrors `charts/aipod/values.yaml` |
| `kagent-remotemcpserver.yaml` | registers aipod as a [kagent](https://kagent.dev) `RemoteMCPServer` | hand-maintained; illustrative, not applied by CI |
| `kars-mcpserver.yaml` | registers aipod as an [Azure kars](https://github.com/Azure/kars) `McpServer` | hand-maintained; illustrative, not applied by CI |
| `azure-ai-foundry-mcp-tool.json` | an Azure AI Foundry / Responses-API-shaped `mcp` tool definition pointing at aipod | hand-maintained; illustrative, not applied by CI |

`contract.json` and `agent-card.json` are produced from the code, so they stay in
sync — CI fails if the committed copies drift. Committed copies were generated
with `--host aipod.example --port 80` (and, for the card,
`AIPOD_MCP_URL=http://aipod-server/mcp`).

## The split

- **`contract.json`** is the *interface* document: every tool's input/output JSON
  Schema, resource URIs/templates, prompt arguments, the client `sampling`
  requirement, and per-tool `requiresSampling` / `sideEffects` / `dataEgress`.
  Large, changes with the code, meant to be diffed and tested.
- **`agent-card.json`** is the *discovery* document: identity, transports, a
  short skill list, a `dependencies` link to the server's contract, and an
  `x-governance` block. Small, stable, meant to be crawled / registered.

Both carry the same `AIPOD_*` governance labels. See
[`../docs/blog/contracts-and-agent-cards.md`](../docs/blog/contracts-and-agent-cards.md).

## The `security` block

`contract.json` is generated from an **open** server, so:

```json
"security": { "scheme": "none", "note": "Server is open. Set --auth-token / AIPOD_API_KEY(S) ..." }
```

Start the server with a key (`--auth-token …`, `AIPOD_API_KEY`, or `AIPOD_API_KEYS`)
and the same field becomes:

```json
"security": {
  "scheme": "bearer",
  "type": "oauth2.1-protected-resource",
  "header": "Authorization: Bearer <key>",
  "requiredScopes": ["mcp:invoke"],
  "authorizationServers": ["https://aipod.example"],
  "protectedResourceMetadata": "https://aipod.example/.well-known/oauth-protected-resource"
}
```

and `clientRequirements.authentication.required` flips to `true`. See
[`../docs/testing-mcp.md`](../docs/testing-mcp.md#authentication).

## Deploying

Both modes ship two ways, from the one `ghcr.io/bigg01/aipod` image:

| Method | Path | Command |
| --- | --- | --- |
| Kustomize | [`../k8s`](../k8s) | `kubectl apply -k k8s` |
| Helm | [`../charts/aipod`](../charts/aipod) | `helm install aipod oci://ghcr.io/bigg01/charts/aipod --version 0.1.0 -f helm-values.yaml` |

`helm-values.yaml` here turns on bearer auth (keys from Secrets you manage), sets
the governance labels, and exposes both modes through an ingress with TLS.

## Governance env vars

| Env var | Field |
| --- | --- |
| `AIPOD_OWNER` | `owner` / `provider.organization` |
| `AIPOD_DOMAIN` | `domain` |
| `AIPOD_DATA_CLASSIFICATION` | `dataClassification` (`PUBLIC`…`RESTRICTED`) |
| `AIPOD_DATA_RESIDENCY` | `dataResidency` |
| `AIPOD_REGULATORY_SCOPE` | `regulatoryScope` (CSV) |
| `AIPOD_AUTH_SCHEMES` | `authenticationSchemes` (CSV) |
| `AIPOD_CONTAINS_PII` | `containsPII` |
