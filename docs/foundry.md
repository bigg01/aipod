# Microsoft Foundry hosted agent

Install `uv sync --extra foundry`, then run `uv run aipod agent --foundry`.
This uses Microsoft's official Invocations adapter: plain HTTP on
`0.0.0.0:8088` (`PORT` overrides the port), `GET /readiness`, platform request
context, and graceful SIGTERM draining. Invalid model configuration prevents
startup. Readiness indicates runtime availability; it does not probe downstream
model credentials or MCP connectivity.

`POST /invocations` accepts `{"prompt":"hello"}` and returns
`{"output":"..."}`. This endpoint is stateless, with no conversation history
or streaming. The existing `aipod agent` and `/ask` behavior remain available
outside Foundry mode.

## Model, context, and tools

Set `FOUNDRY_MODEL_NAME` to your Azure OpenAI deployment name and
`AZURE_OPENAI_ENDPOINT` to its resource endpoint. The Foundry runtime uses
`DefaultAzureCredential` with renewable Entra tokens; grant the agent identity
the model inference role on that resource. `OPENAI_API_VERSION` defaults to
`2024-10-21`. Alternatively set `AIPOD_MODEL` and that provider's credentials
(the Foundry image includes the OpenAI provider; install other provider extras
if needed).

The SDK consumes Foundry's project, agent, version, session, user, and call
context. Project/agent/session identifiers are included in invocation logs;
request context stays scoped to the invocation. No user/session history is stored.
MCP tools use `AIPOD_MCP_URL` and optional `AIPOD_MCP_TOKEN` bearer authentication.
Configure Foundry egress/private networking and DNS so this URL is reachable.
Caller authorization is handled by Foundry; caller tokens are not used as model
or MCP credentials. Model and MCP clients exit their async contexts on completion,
failure, or cancellation; the adapter drains requests on SIGTERM.

## Published image

Release v0.1.7 publishes `ghcr.io/bigg01/aipod:0.1.7-foundry` (Linux AMD64).
The GitHub release records its immutable digest. Copy the image into your ACR
and use the destination registry's digest in the Foundry deployment.

## Build and publish

Use the dedicated Python image; the existing static reference-server image
deliberately excludes model providers and Azure dependencies.

```sh
podman build --platform linux/amd64 -f Dockerfile.foundry \
  -t YOUR_REGISTRY.azurecr.io/aipod:foundry .
podman login YOUR_REGISTRY.azurecr.io
podman push YOUR_REGISTRY.azurecr.io/aipod:foundry
az acr repository show --name YOUR_REGISTRY --image aipod:foundry \
  --query digest -o tsv
```

Deploy `YOUR_REGISTRY.azurecr.io/aipod@sha256:RETURNED_DIGEST`, granting the
platform image-pull identity access to ACR. Configure the deployment protocol
as **Invocations, version 2.0.0**. Change any existing **Responses 2.0.0**
declaration to match; this repository contains no Terraform to update.
The container's default command is `aipod agent --foundry` and requires no
command override. Keep `PYTHONNOUSERSITE=1` enabled and runtime code in `/app`,
separate from Foundry's writable session `HOME`.

Verify with `curl http://localhost:8088/readiness` and
`curl -H 'Content-Type: application/json' -d '{"prompt":"hello"}' http://localhost:8088/invocations`.

Contract: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract
