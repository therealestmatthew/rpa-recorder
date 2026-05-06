"""Response caches: in-memory + Redis-shaped."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rpa_recorder.classifier.llm.cache import InMemoryResponseCache, RedisResponseCache
from rpa_recorder.classifier.llm.protocol import LLMResponse

if TYPE_CHECKING:
    import pytest


def _make_response(text: str = "hi") -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[],
        input_tokens=1,
        output_tokens=2,
        stop_reason="end_turn",
        raw={"id": "abc"},
    )


async def test_in_memory_cache_round_trip() -> None:
    cache = InMemoryResponseCache()
    await cache.set("key", _make_response(), ttl_s=60)
    got = await cache.get("key")
    assert got is not None
    assert got.input_tokens == 1
    assert got.text == "hi"


async def test_in_memory_cache_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = InMemoryResponseCache()
    await cache.set("k", _make_response(), ttl_s=1)
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base + 5.0)
    got = await cache.get("k")
    assert got is None


async def test_in_memory_cache_evicts_when_full() -> None:
    cache = InMemoryResponseCache(max_size=2)
    await cache.set("a", _make_response("a"), ttl_s=60)
    await cache.set("b", _make_response("b"), ttl_s=60)
    await cache.set("c", _make_response("c"), ttl_s=60)
    # `a` should have been evicted as the oldest insertion.
    assert await cache.get("a") is None
    assert await cache.get("b") is not None
    assert await cache.get("c") is not None


async def test_redis_cache_round_trip() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}
            self.ex: dict[str, int] = {}

        async def get(self, key: str) -> str | None:
            return self.store.get(key)

        async def set(self, key: str, value: str, *, ex: int) -> None:
            self.store[key] = value
            self.ex[key] = ex

    fake = FakeRedis()
    cache = RedisResponseCache(fake)
    await cache.set("k", _make_response("redis"), ttl_s=120)
    got = await cache.get("k")
    assert got is not None
    assert got.text == "redis"
    # Verify the key was prefixed and TTL was passed through.
    assert any(k.startswith("llm:resp:") for k in fake.store)
    assert next(iter(fake.ex.values())) == 120


async def test_redis_cache_returns_none_when_missing() -> None:
    class EmptyRedis:
        async def get(self, key: str) -> str | None:
            return None

        async def set(self, key: str, value: str, *, ex: int) -> None: ...

    cache = RedisResponseCache(EmptyRedis())
    assert await cache.get("missing") is None


async def test_redis_cache_decodes_bytes() -> None:
    response = _make_response("decoded")

    class BytesRedis:
        async def get(self, key: str) -> bytes:
            return response.model_dump_json().encode("utf-8")

        async def set(self, key: str, value: str, *, ex: int) -> None: ...

    cache = RedisResponseCache(BytesRedis())
    got = await cache.get("k")
    assert got is not None
    assert got.text == "decoded"


async def test_redis_cache_returns_none_on_malformed_payload() -> None:
    class BadRedis:
        async def get(self, key: str) -> str:
            return "not-json"

        async def set(self, key: str, value: str, *, ex: int) -> None: ...

    cache = RedisResponseCache(BadRedis())
    assert await cache.get("k") is None
