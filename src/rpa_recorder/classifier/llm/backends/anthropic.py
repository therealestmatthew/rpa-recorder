"""`AnthropicBackend` — `LLMBackend` for the Anthropic Messages API.

Constructs `AsyncAnthropic(max_retries=0)` so our `RetryPolicy` is the only
retry layer. Translates the SDK's content-block list into a flat
`(text, tool_calls)` pair on `LLMResponse`. Returns `usage.input_tokens`
and `usage.output_tokens` straight through — never estimate locally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..protocol import LLMResponse

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic


def _extract_text_and_tools(content: Any) -> tuple[str | None, list[dict[str, Any]]]:
    """Walk an SDK `Message.content` list and split into text + tool_use blocks."""
    text_parts: list[str] = []
    tools: list[dict[str, Any]] = []
    for block in content or []:
        block_type = getattr(block, "type", None)
        if block_type is None and isinstance(block, dict):
            block_type = block.get("type")
        if block_type == "text":
            value = getattr(block, "text", None)
            if value is None and isinstance(block, dict):
                value = block.get("text")
            if value:
                text_parts.append(str(value))
        elif block_type == "tool_use":
            tools.append(
                {
                    "id": getattr(block, "id", None)
                    or (block.get("id") if isinstance(block, dict) else None),
                    "name": getattr(block, "name", None)
                    or (block.get("name") if isinstance(block, dict) else None),
                    "input": getattr(block, "input", None)
                    if not isinstance(block, dict)
                    else block.get("input", {}),
                }
            )
    return ("\n".join(text_parts) if text_parts else None), tools


def _to_jsonable(value: Any) -> Any:
    """Best-effort JSON-safe projection of an SDK response object."""
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError, ValueError:
            pass
    if hasattr(value, "to_dict"):
        try:
            result = value.to_dict()
        except TypeError, ValueError:
            result = None
        if result is not None:
            return result
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class AnthropicBackend:
    """Thin adapter around `AsyncAnthropic.messages.create`."""

    name: str = "anthropic"

    def __init__(self, *, model: str, client: AsyncAnthropic | None = None) -> None:
        self.model = model
        if client is None:
            from anthropic import AsyncAnthropic  # noqa: PLC0415

            client = AsyncAnthropic(max_retries=0)
        self._client = client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "timeout": timeout_s,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = {"type": "any"}
        response = await self._client.messages.create(**kwargs)
        text, tool_calls = _extract_text_and_tools(getattr(response, "content", None))
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage is not None else 0
        out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage is not None else 0
        stop_reason = str(getattr(response, "stop_reason", None) or "")
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
            stop_reason=stop_reason,
            raw=_to_jsonable(response),
        )


__all__ = ["AnthropicBackend"]
