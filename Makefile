# aipod - one binary, two modes

IMAGE      ?= aipod:latest
HOST       ?= 127.0.0.1
SERVER_PORT ?= 8000
AGENT_PORT ?= 8080
AIPOD_MCP_URL ?= http://127.0.0.1:8000/mcp
PROMPT     ?= Write a poem about sockets, then summarise it.

export AIPOD_MCP_URL

.DEFAULT_GOAL := help
INSPECTOR   ?= @modelcontextprotocol/inspector@2.4.0
MCP_URL     ?= http://$(HOST):$(SERVER_PORT)/mcp

.PHONY: help sync test server server-stdio agent ask contract card inspect inspect-cli \
        binary docker docker-server docker-agent k8s k8s-delete clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync: ## Install dependencies with uv
	uv sync

test: ## Run the test suite (server + agent)
	uv run pytest -q

server: ## Run in server mode over Streamable HTTP
	uv run aipod server --transport http --host $(HOST) --port $(SERVER_PORT)

server-stdio: ## Run in server mode over stdio (subprocess clients)
	uv run aipod server --transport stdio

agent: ## Run in agent mode (HTTP: card + /ask)
	uv run aipod agent --host $(HOST) --port $(AGENT_PORT)

ask: ## One-shot agent request (needs AIPOD_MODEL + provider key). PROMPT=... to override
	uv run aipod agent --ask "$(PROMPT)"

contract: ## Regenerate examples/contract.json
	uv run aipod server --print contract --host aipod.example --port 80 > examples/contract.json
	@echo "wrote examples/contract.json"

card: ## Regenerate examples/agent-card.json
	AIPOD_MCP_URL=http://aipod-server/mcp uv run aipod agent --print agent-card --host aipod.example --port 80 > examples/agent-card.json
	@echo "wrote examples/agent-card.json"

inspect: ## Open the MCP Inspector UI (connect it to a running server)
	npx -y $(INSPECTOR)

inspect-cli: ## Scripted protocol check: list tools + call echo via the Inspector CLI
	npx -y $(INSPECTOR) --cli $(MCP_URL) --method tools/list
	npx -y $(INSPECTOR) --cli $(MCP_URL) --method tools/call \
	  --tool-name echo --tool-arg message="hello from make"

binary: ## Build the standalone PyInstaller binary into dist/
	uv run --group build pyinstaller packaging/aipod.spec --noconfirm
	@echo "built dist/aipod"

docker: ## Build the FROM scratch image ($(IMAGE))
	docker build -t $(IMAGE) .

docker-server: docker ## Build then run server mode on :$(SERVER_PORT)
	docker run --rm -p $(SERVER_PORT):8000 $(IMAGE)

docker-agent: docker ## Build then run agent mode on :$(AGENT_PORT)
	docker run --rm -p $(AGENT_PORT):8080 -e AIPOD_MCP_URL=$(AIPOD_MCP_URL) $(IMAGE) agent --host 0.0.0.0 --port 8080

k8s: ## Apply the Kubernetes manifests (both modes)
	kubectl apply -k k8s

k8s-delete: ## Remove the Kubernetes resources
	kubectl delete -k k8s

clean: ## Remove build artefacts
	rm -rf dist build .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
