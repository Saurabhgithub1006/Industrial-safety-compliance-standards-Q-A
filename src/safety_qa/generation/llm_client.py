"""LLM client abstraction so generator.py/grounding_judge.py never call an SDK
directly. Tests run against FakeLLMClient with zero network calls and no API key.
See artifacts/changelogs.md CHG-20260907-03 for the design rationale.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Protocol, TypeVar

_T = TypeVar("_T")


def call_with_retry(
    make_request: Callable[[], _T],
    retryable_exceptions: tuple[type[BaseException], ...],
    max_attempts: int = 4,
    base_delay: float = 5.0,
) -> _T:
    """Retry a failed API call with exponential backoff (5s/10s/20s by default).
    Distinct from the schema-validation retry, which handles a malformed response,
    not a failed call. See artifacts/changelogs.md CHG-20260916-10 for why this exists.
    """
    last_error: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return make_request()
        except retryable_exceptions as e:
            last_error = e
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2**attempt))
    raise last_error  # pragma: no cover -- unreachable, loop always returns or raises


class LLMClient(Protocol):
    model: str  # which model produced a call, logged for observability (Phase 7)

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        """Return a dict conforming to schema. Caller validates the schema, not this layer."""
        ...


class AnthropicClient:
    """Real client. Forces structured output via Claude's tool-use mechanism.
    Requires ANTHROPIC_API_KEY, read from .env or the environment.
    """

    def __init__(self, model: str = "claude-sonnet-5", max_tokens: int = 4096):
        import anthropic  # imported lazily so tests never need this installed at all
        from dotenv import load_dotenv

        load_dotenv()  # populates os.environ from .env if one exists; no-op otherwise
        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        import anthropic

        def _make_request():
            return self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                # cache_control breakpoint enables prompt caching for this system prompt.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                tools=[{"name": schema_name, "description": f"Emit a {schema_name}.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": schema_name},
            )

        response = call_with_retry(
            _make_request,
            (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError),
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == schema_name:
                return block.input
        raise ValueError(f"model response contained no {schema_name!r} tool call: {response.content!r}")


class KimiClient:
    """Kimi (Moonshot AI), via their OpenAI-compatible endpoint and function-calling.
    Implements the same LLMClient protocol as AnthropicClient.
    Requires MOONSHOT_API_KEY, read from .env or the environment.
    """

    def __init__(self, model: str = "kimi-k3", max_tokens: int = 4096):
        import os

        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()  # populates os.environ from .env if one exists; no-op otherwise
        api_key = os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            raise ValueError("MOONSHOT_API_KEY is not set (checked process env and .env)")
        self._client = OpenAI(api_key=api_key, base_url="https://api.moonshot.ai/v1")
        self.model = model
        self.max_tokens = max_tokens

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        import openai

        # Moonshot's context caching is automatic; no cache_control needed here.
        def _make_request():
            return self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=[{
                    "type": "function",
                    "function": {"name": schema_name, "description": f"Emit a {schema_name}.", "parameters": schema},
                }],
                # Only tool_choice="auto" works across all Kimi models; see CHG-20260909-05.
                tool_choice="auto",
            )

        response = call_with_retry(
            _make_request,
            (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError),
        )
        message = response.choices[0].message
        if not message.tool_calls:
            raise ValueError(f"model response contained no {schema_name!r} tool call: {message!r}")
        return json.loads(message.tool_calls[0].function.arguments)


class FakeLLMClient:
    """Deterministic stand-in for tests: returns a queued response, records every call."""

    def __init__(self, responses: list[dict] | dict | None = None, model: str = "fake-model"):
        if isinstance(responses, dict):
            responses = [responses]
        self._responses: list[dict] = list(responses) if responses else []
        self.calls: list[dict] = []
        self.model = model

    def queue(self, response: dict) -> None:
        self._responses.append(response)

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if not self._responses:
            raise AssertionError("FakeLLMClient has no queued response for this call")
        return self._responses.pop(0)


# Generator uses the highest-capability tier; judge uses the fast/cheap tier.
_MODEL_BY_PROVIDER_AND_ROLE = {
    "anthropic": {"generator": "claude-sonnet-5", "judge": "claude-haiku-4-5-20251001"},
    "kimi": {"generator": "kimi-k3", "judge": "kimi-k2.6"},
}


def build_client(role: str, provider: str | None = None) -> LLMClient:
    """Build the configured LLMClient for `role` ("generator" or "judge").
    Provider defaults to the LLM_PROVIDER env var, falling back to "kimi".
    """
    import os

    from dotenv import load_dotenv

    load_dotenv()
    provider = (provider or os.environ.get("LLM_PROVIDER") or "kimi").lower()
    if provider not in _MODEL_BY_PROVIDER_AND_ROLE:
        raise ValueError(f"unknown LLM provider {provider!r}; expected one of {list(_MODEL_BY_PROVIDER_AND_ROLE)}")
    model = _MODEL_BY_PROVIDER_AND_ROLE[provider][role]
    if provider == "kimi":
        return KimiClient(model=model)
    return AnthropicClient(model=model)


def parse_json_response(text: str) -> dict:
    """Best-effort JSON extraction for a client that returns raw text, not a tool call."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
