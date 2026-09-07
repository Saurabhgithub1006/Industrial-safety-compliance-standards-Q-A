"""LLM client abstraction. Everything in `generator.py` talks to `LLMClient`, never
to the Anthropic SDK directly -- so tests run the real prompt-building and
citation-validation logic against `FakeLLMClient` with zero network calls and no API
key, and the only thing that changes for real usage is which client gets
constructed. No API key was available while building this phase; this interface is
exactly how that gets handled without blocking the rest of Phase 3 on it.
"""

from __future__ import annotations

import json
from typing import Protocol


class LLMClient(Protocol):
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
    ANTHROPIC_API_KEY in the environment; the `anthropic` package raises its own
    clear error if it's missing, which is left to surface as-is."""

    def __init__(self, model: str = "claude-sonnet-5", max_tokens: int = 4096):
        import anthropic  # imported lazily so tests never need this installed at all

        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": schema_name, "description": f"Emit a {schema_name}.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": schema_name},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == schema_name:
                return block.input
        raise ValueError(f"model response contained no {schema_name!r} tool call: {response.content!r}")


class FakeLLMClient:
    """Deterministic stand-in for tests: returns a pre-programmed response (or the
    next one off a queue) instead of calling out to anything. Also records every
    call it received, so a test can assert on what prompt/schema the generator
    actually sent -- catching prompt-construction bugs without needing a live model
    to notice them."""

    def __init__(self, responses: list[dict] | dict | None = None):
        if isinstance(responses, dict):
            responses = [responses]
        self._responses: list[dict] = list(responses) if responses else []
        self.calls: list[dict] = []

    def queue(self, response: dict) -> None:
        self._responses.append(response)

    def complete_structured(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if not self._responses:
            raise AssertionError("FakeLLMClient has no queued response for this call")
        return self._responses.pop(0)


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
