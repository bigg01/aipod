# Generated docs

Both files are produced from the code, so they stay in sync.

| File | Produced by | Regenerate | Served at |
| --- | --- | --- | --- |
| `contract.json` | `aipod server` | `uv run aipod server --print contract` | `GET /contract.json` |
| `agent-card.json` | `aipod agent` | `uv run aipod agent --print agent-card` | `GET /.well-known/agent-card.json` |

Committed copies were generated with `--host aipod.example --port 80` (and, for
the card, `AIPOD_MCP_URL=http://aipod-server/mcp`).

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
