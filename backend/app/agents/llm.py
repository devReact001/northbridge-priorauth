"""One helper for every agent that needs structured output from Claude.

A forced tool call returns schema-shaped JSON, and the client is injectable so tests run
without network access or an API key.
"""

import time
from dataclasses import dataclass
from typing import Any, Optional

from ..config import settings


@dataclass
class ToolCall:
    data: dict
    input_tokens: int
    output_tokens: int
    latency_ms: int


def get_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def call_tool(
    *,
    system: str,
    user: str,
    tool: dict,
    client: Optional[Any] = None,
    model: Optional[str] = None,
    max_tokens: int = 3000,
) -> ToolCall:
    client = client or get_client()
    start = time.perf_counter()
    message = client.messages.create(
        model=model or settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user}],
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    block = next((b for b in message.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise ValueError(f"Model did not return a {tool['name']} tool call")
    return ToolCall(
        data=block.input,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        latency_ms=latency_ms,
    )
