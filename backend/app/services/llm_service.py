"""Chat-completion service for conversational search.

Sits behind small module-level functions for the same reason as the Ravelry
client and the embedding service: nothing outside this module imports the
provider SDK, so the model can be swapped without touching the search layer.

The client is created lazily and reused — unlike the local ML models it holds
no weights, so there is nothing to preload at startup, and an unconfigured
deployment never constructs one at all.
"""

import json
import logging
import threading
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

Message = dict[str, str]

_client: Any = None
_client_lock = threading.Lock()


class LLMUnavailableError(RuntimeError):
    """The model could not be reached, timed out, or returned unusable output.

    Callers turn this into a 503 — conversational search is additive, so it
    must never take the rest of the API down with it.
    """


def is_configured() -> bool:
    """Whether an API key is present. False means the feature is turned off."""
    return bool(get_settings().openai_api_key)


def get_client() -> Any:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                settings = get_settings()
                if not settings.openai_api_key:
                    raise LLMUnavailableError("OPENAI_API_KEY is not set.")
                from openai import AsyncOpenAI

                logger.info("Creating OpenAI client for model %s.", settings.openai_model)
                _client = AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    timeout=settings.llm_timeout_seconds,
                )
    return _client


async def _complete(
    messages: list[Message],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> str:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await get_client().chat.completions.create(**kwargs)
    except LLMUnavailableError:
        raise
    except Exception as exc:
        logger.warning("LLM request failed (%s).", exc)
        raise LLMUnavailableError("The language model could not be reached.") from exc

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise LLMUnavailableError("The language model returned an empty response.")
    return content


async def complete_text(
    messages: list[Message], *, max_tokens: int = 350, temperature: float = 0.3
) -> str:
    """Prose completion, for the answer step."""
    return await _complete(
        messages, max_tokens=max_tokens, temperature=temperature, json_mode=False
    )


async def complete_json(
    messages: list[Message], *, max_tokens: int = 200, temperature: float = 0.0
) -> dict[str, Any]:
    """JSON-object completion, for structured extraction.

    Temperature 0 by default: extraction should be repeatable so the same
    question produces the same filters (and the same cache key).
    """
    raw = await _complete(
        messages, max_tokens=max_tokens, temperature=temperature, json_mode=True
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError("The language model returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailableError("Expected a JSON object from the language model.")
    return parsed
