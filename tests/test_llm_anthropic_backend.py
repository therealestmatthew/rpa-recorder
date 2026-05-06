"""`AnthropicBackend` adapter tests with a mocked SDK client."""

from typing import Any

import pytest

from rpa_recorder.classifier.llm.backends.anthropic import AnthropicBackend


class _FakeBlock:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessage:
    def __init__(
        self, *, content: list[Any], usage: _FakeUsage, stop_reason: str = "end_turn"
    ) -> None:
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {"content": "stub", "stop_reason": self.stop_reason}


class _FakeMessages:
    def __init__(self, response: _FakeMessage) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response: _FakeMessage) -> None:
        self.messages = _FakeMessages(response)


async def test_complete_returns_llm_response_with_tokens() -> None:
    response = _FakeMessage(
        content=[
            _FakeBlock(type="text", text="hi"),
            _FakeBlock(type="tool_use", id="t1", name="classify", input={"intent": "login"}),
        ],
        usage=_FakeUsage(50, 10),
    )
    backend = AnthropicBackend(model="claude-sonnet-4-6", client=_FakeClient(response))  # type: ignore[arg-type]
    result = await backend.complete([{"role": "user", "content": "go"}], max_tokens=200)
    assert result.input_tokens == 50
    assert result.output_tokens == 10
    assert result.text == "hi"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "classify"
    assert result.tool_calls[0]["input"]["intent"] == "login"


async def test_complete_passes_tools_and_tool_choice() -> None:
    response = _FakeMessage(content=[], usage=_FakeUsage(1, 1))
    client = _FakeClient(response)
    backend = AnthropicBackend(model="claude-sonnet-4-6", client=client)  # type: ignore[arg-type]
    tools = [{"name": "classify", "input_schema": {"type": "object"}}]
    await backend.complete(
        [{"role": "user", "content": "x"}],
        max_tokens=100,
        tools=tools,
    )
    call = client.messages.calls[-1]
    assert call["tools"] == tools
    assert call["tool_choice"] == {"type": "any"}
    assert call["max_tokens"] == 100


async def test_complete_passes_timeout() -> None:
    response = _FakeMessage(content=[], usage=_FakeUsage(0, 0))
    client = _FakeClient(response)
    backend = AnthropicBackend(model="claude-sonnet-4-6", client=client)  # type: ignore[arg-type]
    await backend.complete([{"role": "user", "content": "x"}], max_tokens=10, timeout_s=2.5)
    assert client.messages.calls[-1]["timeout"] == 2.5


async def test_complete_propagates_exceptions() -> None:
    class Boom(Exception):  # noqa: N818
        ...

    class FailingMessages:
        async def create(self, **_: Any) -> Any:
            raise Boom("rate limit")

    class FailingClient:
        messages = FailingMessages()

    backend = AnthropicBackend(model="claude-sonnet-4-6", client=FailingClient())  # type: ignore[arg-type]
    with pytest.raises(Boom):
        await backend.complete([{"role": "user", "content": "x"}], max_tokens=10)


async def test_complete_handles_dict_blocks() -> None:
    # Some SDK versions may pass blocks as dicts; both must work.
    response = _FakeMessage(
        content=[
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "t1", "name": "classify", "input": {"intent": "search"}},
        ],
        usage=_FakeUsage(1, 1),
    )
    backend = AnthropicBackend(model="claude-sonnet-4-6", client=_FakeClient(response))  # type: ignore[arg-type]
    result = await backend.complete([{"role": "user", "content": "x"}], max_tokens=10)
    assert result.text == "hello"
    assert result.tool_calls[0]["input"]["intent"] == "search"


def test_default_client_is_constructed_with_no_retries() -> None:
    backend = AnthropicBackend(model="claude-sonnet-4-6")
    # The client object should expose `max_retries` (or similar). The default
    # constructor in the SDK accepts `max_retries=0`; we check the attribute
    # if present but tolerate a SDK that hides it.
    client = backend._client
    max_retries = getattr(client, "max_retries", None)
    if max_retries is not None:
        assert max_retries == 0
