"""Optional Microsoft Foundry Invocations runtime (install ``aipod[foundry]``)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import model_name
from .runtime import ask, build_toolset, INSTRUCTIONS

if TYPE_CHECKING:
    from azure.ai.agentserver.invocations import InvocationAgentServerHost

logger = logging.getLogger(__name__)


async def invoke(prompt: str) -> str:
    """Use the configured provider, or Azure's renewable managed identity token."""
    if model_name():
        return await ask(prompt)

    from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
    from openai import AsyncAzureOpenAI
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.azure import AzureProvider

    async with DefaultAzureCredential() as credential:
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        async with AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("OPENAI_API_VERSION", "2024-10-21"),
            azure_ad_token_provider=token_provider,
        ) as client:
            model = OpenAIChatModel(
                os.environ["FOUNDRY_MODEL_NAME"],
                provider=AzureProvider(openai_client=client),
            )
            async with Agent(model, toolsets=[build_toolset()], instructions=INSTRUCTIONS) as agent:
                result = await agent.run(prompt)
                return result.output


def build_host() -> InvocationAgentServerHost:
    """Let Microsoft's adapter own context, probes, transport, and SIGTERM."""
    from azure.ai.agentserver.core import get_request_context
    from azure.ai.agentserver.invocations import InvocationAgentServerHost

    if not model_name() and not (
        os.environ.get("FOUNDRY_MODEL_NAME") and os.environ.get("AZURE_OPENAI_ENDPOINT")
    ):
        raise ValueError("Set AIPOD_MODEL, or FOUNDRY_MODEL_NAME and AZURE_OPENAI_ENDPOINT")

    host = InvocationAgentServerHost()

    @host.invoke_handler
    async def handle(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("prompt"), str)
            or not body["prompt"].strip()
        ):
            return JSONResponse({"error": "missing non-empty 'prompt' string"}, status_code=400)

        context = get_request_context()
        logger.info(
            "Foundry invocation agent=%s version=%s session=%s project=%s",
            os.environ.get("FOUNDRY_AGENT_ID") or os.environ.get("FOUNDRY_AGENT_NAME"),
            os.environ.get("FOUNDRY_AGENT_VERSION"),
            context.session_id or os.environ.get("FOUNDRY_AGENT_SESSION_ID"),
            os.environ.get("FOUNDRY_PROJECT_ENDPOINT"),
        )
        return JSONResponse({"output": await invoke(body["prompt"])})

    return host
