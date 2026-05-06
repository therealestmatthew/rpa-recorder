"""Response caches keyed by `sha256(model + prompt.version + signature(...))`.

`InMemoryResponseCache` is the test/local default — bounded TTL dict with
no external dependencies. `RedisResponseCache` accepts any Redis-shaped
async client (`get`, `set` with `ex=`); production wires the real client
in M11.5's worker.

Stored format is the *raw* `LLMResponse` model_dump_json so token counts
and `stop_reason` replay correctly through the parser on cache hit.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from .protocol import LLMResponse

if TYPE_CHECKING:
    from typing import Any


class InMemoryResponseCache:
    """Per-process TTL cache. Not safe for cross-worker sharing.

    Implementation is a small dict + monotonic-time check; we avoid taking
    a `cachetools` dep for one tiny use case. Eviction is lazy (on `get`).
    """

    def __init__(self, *, max_size: int = 10_000) -> None:
        self._max = max_size
        self._store: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> LLMResponse | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return LLMResponse.model_validate_json(payload)

    async def set(self, key: str, response: LLMResponse, ttl_s: int) -> None:
        # Bound size: evict oldest insertion order entry if at cap.
        if len(self._store) >= self._max and key not in self._store:
            oldest = next(iter(self._store))
            self._store.pop(oldest, None)
        self._store[key] = (
            time.monotonic() + ttl_s,
            response.model_dump_json(),
        )


class RedisResponseCache:
    """Redis-backed cache. Accepts any async Redis-shaped client.

    Stores the JSON-serialised `LLMResponse` under `llm:resp:<key>` with
    `EX=ttl_s`. The client itself is opaque — duck-typed against `get` and
    `set(name, value, ex=ttl_s)`.
    """

    _PREFIX = "llm:resp:"

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _full_key(key: str) -> str:
        return f"{RedisResponseCache._PREFIX}{key}"

    async def get(self, key: str) -> LLMResponse | None:
        raw = await self._redis.get(self._full_key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return LLMResponse.model_validate_json(raw)
        except ValueError, json.JSONDecodeError:
            return None

    async def set(self, key: str, response: LLMResponse, ttl_s: int) -> None:
        await self._redis.set(
            self._full_key(key),
            response.model_dump_json(),
            ex=ttl_s,
        )


__all__ = ["InMemoryResponseCache", "RedisResponseCache"]
