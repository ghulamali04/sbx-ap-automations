from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from azure.identity import (
    DefaultAzureCredential,
    get_bearer_token_provider,
)
from openai import OpenAI

_FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
_LOG = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Summarise only the supplied client-task comments from the past 180 days. "
    "Tell the overall story in chronological context, emphasising the most recent "
    "comments. State the outcome and current status when the comments support "
    "them. Do not infer missing facts or use task metadata, activity, or weighting. "
    "Return two or three concise plain-English sentences without a heading, "
    "preamble, quotation, or markdown."
)


def endpoint() -> str:
    value = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    return f"{value.rstrip('/')}/" if value else ""


def deployment_name() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()


def is_configured() -> bool:
    return bool(endpoint() and deployment_name())


@lru_cache(maxsize=1)
def _credential():
   
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Create the OpenAI client for Azure AI Foundry's OpenAI v1 endpoint."""
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    authentication = api_key or get_bearer_token_provider(
        _credential(),
        _FOUNDRY_TOKEN_SCOPE,
    )
    return OpenAI(
        base_url=endpoint(),
        api_key=authentication,
        timeout=30.0,
        max_retries=0,
    )


def _create_completion(messages: list[dict[str, str]], max_tokens: int) -> str:
    instructions = "\n".join(
        message["content"]
        for message in messages
        if message.get("role") == "system"
    )
    user_input = "\n".join(
        message["content"]
        for message in messages
        if message.get("role") == "user"
    )
    response = _client().responses.create(
        model=deployment_name(),
        instructions=instructions or None,
        input=user_input,
        max_output_tokens=max(256, max_tokens),
        reasoning={
            "effort": os.getenv("AZURE_OPENAI_REASONING_EFFORT", "low").strip()
            or "low"
        },
        text={
            "verbosity": os.getenv("AZURE_OPENAI_TEXT_VERBOSITY", "low").strip()
            or "low"
        },
    )
    content = response.output_text or ""
    return " ".join(content.split()).strip()


async def test_model() -> str:
    """Send the supervisor-provided test question without blocking FastAPI."""
    return await asyncio.to_thread(
        _create_completion,
        [{"role": "user", "content": "What is the capital of France?"}],
        80,
    )


async def summarize_comments(
    task_name: str,
    project_name: str,
    comments: str,
) -> str | None:
    """Summarise filtered 180-day comments without blocking PDF generation."""
    if not is_configured() or not comments.strip():
        return None

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Task comments from the past 180 days:\n{comments}",
        },
    ]
    try:
        return await asyncio.to_thread(_create_completion, messages, 120) or None
    except Exception as exc:  # noqa: BLE001 - PDF generation degrades gracefully
        _LOG.warning(
            "Azure OpenAI summary failed for task %r in project %r: %s",
            task_name,
            project_name,
            exc,
        )
        return None
