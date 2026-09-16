"""LLM client abstraction. Everything in `generator.py` talks to `LLMClient`, never
to the Anthropic SDK directly -- so tests run the real prompt-building and
citation-validation logic against `FakeLLMClient` with zero network calls and no API
key, and the only thing that changes for real usage is which client gets
constructed. No API key was available while building this phase; this interface is
exactly how that gets handled without blocking the rest of Phase 3 on it.
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
    """Retry `make_request` (a zero-arg callable performing one real API call) on
    transient failures -- rate limits, server errors, connection drops -- with
    exponential backoff (5s, 10s, 20s between the 4 attempts by default).
    Distinct from the schema-validation retry in generator.py/grounding_judge.py,
    which handles a malformed *response*; this handles the call itself not
    succeeding at all.

    Real gap this closes: an unhandled RateLimitError was observed directly
    during manual testing on this project's Kimi account, which is capped at 3
    requests/minute -- tight enough that a short burst of calls trips it. The
    default backoff schedule is sized to comfortably clear that specific
    constraint (a single retry wait of 5s+ already exceeds the ~20s/request
    budget a 3 RPM cap implies), not tuned to any particular provider's own
    Retry-After header (neither SDK's exception objects were verified to expose
    one in a way worth depending on here)."""
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
    model: str  # exposed so callers can log which model produced a given call (Phase 7 observability)

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        """Return a dict conforming to `schema` (a JSON Schema, e.g. from
        `GeneratedAnswer.model_json_schema()`). Raises on a response that can't be
        parsed as JSON at all; schema *validation* is the caller's job (schema.py's
        Pydantic models), not this layer's."""
        ...


class AnthropicClient:
    """Real client -- forces structured output via Claude's tool-use mechanism
    (per the tech-stack choice in the arch doc: 'structured output enforced with a
    JSON schema, Pydantic model -> tool-use/tool-call schema'). Requires
    ANTHROPIC_API_KEY -- loaded from a `.env` file in the repo root if present
    (never committed; see .gitignore), otherwise read from the environment as-is.
    The `anthropic` package raises its own clear error if the key is missing
    either way, which is left to surface as-is."""

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
                # A content-block system prompt with a cache_control breakpoint,
                # not a plain string -- this is what actually enables Claude's
                # prompt caching. The judge's system prompt (and the generator's)
                # is identical on every call for a given role; without this
                # breakpoint it would be billed and processed as fresh input every
                # single time despite never changing.
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
    """Moonshot AI's Kimi models, via their OpenAI-compatible endpoint
    (https://api.moonshot.ai/v1) using OpenAI-style function-calling for structured
    output -- same role as AnthropicClient, different wire format underneath.
    Implements the same LLMClient protocol, so nothing in generator.py or
    grounding_judge.py needs to know or care which provider is behind it.

    Requires MOONSHOT_API_KEY -- loaded from a `.env` file in the repo root if
    present (never committed; see .gitignore), otherwise read from the environment
    as-is."""

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

        # No caching code needed here, unlike AnthropicClient: Moonshot's context
        # caching is fully automatic for any repeated prefix over 256 tokens, with
        # zero API changes required (confirmed via their docs, not assumed) --
        # putting the system message first in `messages`, which this already does,
        # is the one thing on our side that actually matters for the cache to hit.
        def _make_request():
            return self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                tools=[{
                    "type": "function",
                    "function": {"name": schema_name, "description": f"Emit a {schema_name}.", "parameters": schema},
                }],
                # Verified empirically (not clearly documented): Kimi's thinking-enabled
                # models 400 on a pinned tool_choice ({"type":"function",...}), and
                # kimi-k2.6 additionally rejects tool_choice="required" -- only "auto" is
                # accepted across models. Since exactly one tool is ever offered and the
                # prompt explicitly instructs calling it, "auto" reliably triggers the
                # call in practice; the retry-on-missing-tool-call logic in generator.py
                # / grounding_judge.py is the safety net for the rare case it doesn't.
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
    """Deterministic stand-in for tests: returns a pre-programmed response (or the
    next one off a queue) instead of calling out to anything. Also records every
    call it received, so a test can assert on what prompt/schema the generator
    actually sent -- catching prompt-construction bugs without needing a live model
    to notice them."""

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


# Per the arch doc's model-tiering design (Sec 6.1): the generator needs the
# highest-capability tier (it synthesizes across clauses); a judge is a bounded
# entailment check and can run on a smaller/faster/cheaper tier.
_MODEL_BY_PROVIDER_AND_ROLE = {
    "anthropic": {"generator": "claude-sonnet-5", "judge": "claude-haiku-4-5-20251001"},
    "kimi": {"generator": "kimi-k3", "judge": "kimi-k2.6"},
}


def build_client(role: str, provider: str | None = None) -> LLMClient:
    """Construct the configured real LLMClient for `role` ("generator" or
    "judge"). `provider` defaults to the LLM_PROVIDER env var, falling back to
    "kimi" (the provider this project currently has a real API key for) --
    override with LLM_PROVIDER=anthropic once an Anthropic key is set, or pass
    provider explicitly. Centralized here so every CLI picks the provider and the
    right model tier for its role the same way, instead of each hardcoding one."""
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
    """Best-effort JSON extraction for clients that return raw text instead of a
    structured tool call (kept separate from AnthropicClient so it's independently
    testable, and reusable if a non-tool-use provider is ever added)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
