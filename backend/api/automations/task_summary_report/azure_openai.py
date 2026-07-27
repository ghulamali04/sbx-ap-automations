from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from azure.identity import (
    DefaultAzureCredential,
    DeviceCodeCredential,
    get_bearer_token_provider,
)
from openai import AzureOpenAI, OpenAI

# These defaults are the Azure Foundry resource and deployment supplied for this
# project. Environment variables can override them without requiring a code change.
DEFAULT_ENDPOINT = "https://gali-1170-resource.services.ai.azure.com/openai/v1/"
DEFAULT_DEPLOYMENT = "Mistral-Large-3"
_FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
_AZURE_OPENAI_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
_LOG = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You summarise financial-advisory task notes for a client-facing report. "
    "Write two or three concise, plain-English sentences explaining what has "
    "happened and where the work currently stands. Weight recent activity most "
    "heavily. Use no heading, preamble, quotes, or markdown."
)


def endpoint() -> str:
    value = os.getenv("AZURE_OPENAI_ENDPOINT", DEFAULT_ENDPOINT).strip()
    return f"{value.rstrip('/')}/"


def deployment_name() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", DEFAULT_DEPLOYMENT).strip()


def api_version() -> str:
    return os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()


def is_configured() -> bool:
    return bool(endpoint() and deployment_name())


@lru_cache(maxsize=1)
def _credential():
    if os.getenv("WEBSITE_HOSTNAME") or os.getenv("IDENTITY_ENDPOINT"):
        return DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return DeviceCodeCredential()


def _uses_foundry_v1() -> bool:
    configured_mode = os.getenv("AZURE_OPENAI_API_MODE", "auto").strip().lower()
    if configured_mode in {"foundry", "foundry_v1"}:
        return True
    if configured_mode in {"azure", "azure_openai"}:
        return False
    value = endpoint().lower()
    return "services.ai.azure.com" in value or "/openai/v1" in value


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Create the correct client for Azure OpenAI or Foundry's OpenAI v1 API."""
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    if _uses_foundry_v1():
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

    client_options = {
        "azure_endpoint": endpoint(),
        "api_version": api_version(),
        "timeout": 30.0,
        "max_retries": 0,
    }
    if api_key:
        client_options["api_key"] = api_key
    else:
        client_options["azure_ad_token_provider"] = get_bearer_token_provider(
            _credential(),
            _AZURE_OPENAI_TOKEN_SCOPE,
        )
    return AzureOpenAI(**client_options)


def _create_completion(messages: list[dict[str, str]], max_tokens: int) -> str:
    completion = _client().chat.completions.create(
        model=deployment_name(),
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    content = completion.choices[0].message.content or ""
    return " ".join(content.split()).strip()


async def test_model() -> str:
    """Send the supervisor-provided test question without blocking FastAPI."""
    return await asyncio.to_thread(
        _create_completion,
        [{"role": "user", "content": "What is the capital of France?"}],
        80,
    )


async def summarize_note(task_name: str, project_name: str, notes: str) -> str | None:
    """Return a one-line summary, or None so a model failure cannot stop the PDF."""
    if not is_configured() or not notes.strip():
        return None

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Task: {task_name}\nProject: {project_name}\nNotes: {notes}",
        },
    ]
    try:
        return await asyncio.to_thread(_create_completion, messages, 80) or None
    except Exception as exc:  # noqa: BLE001 - PDF generation degrades gracefully
        _LOG.warning(
            "Azure OpenAI summary failed for task %r in project %r: %s",
            task_name,
            project_name,
            exc,
        )
        return None
