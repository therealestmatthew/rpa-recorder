"""Retry policies."""

import pytest

from rpa_recorder.classifier.llm.protocol import LLMBudgetExceeded
from rpa_recorder.classifier.llm.retry import ExponentialBackoffRetry, NoRetry


class _Boom(RuntimeError):  # noqa: N818
    pass


async def test_exponential_backoff_retries_until_success() -> None:
    delays: list[float] = []

    async def fake_sleep(t: float) -> None:
        delays.append(t)

    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _Boom("rate limit")
        return "ok"

    retry = ExponentialBackoffRetry(max_attempts=3, base_delay=1.0, jitter=0.0, sleep=fake_sleep)
    result = await retry.execute(flaky, retryable=(_Boom,))
    assert result == "ok"
    assert attempts["n"] == 3
    assert delays == [1.0, 2.0]


async def test_no_retry_passes_through() -> None:
    attempts = {"n": 0}

    async def fn() -> int:
        attempts["n"] += 1
        raise _Boom("nope")

    with pytest.raises(_Boom):
        await NoRetry().execute(fn, retryable=(_Boom,))
    assert attempts["n"] == 1


async def test_retry_re_raises_after_max_attempts() -> None:
    async def fake_sleep(_: float) -> None:
        return None

    async def always_fails() -> int:
        raise _Boom("perm")

    retry = ExponentialBackoffRetry(max_attempts=2, base_delay=0.0, jitter=0.0, sleep=fake_sleep)
    with pytest.raises(_Boom):
        await retry.execute(always_fails, retryable=(_Boom,))


async def test_retry_does_not_retry_non_retryable() -> None:
    attempts = {"n": 0}

    async def fake_sleep(_: float) -> None:
        attempts["sleep"] = attempts.get("sleep", 0) + 1

    async def boom() -> int:
        attempts["n"] += 1
        raise LLMBudgetExceeded("over cap")

    retry = ExponentialBackoffRetry(max_attempts=3, base_delay=1.0, jitter=0.0, sleep=fake_sleep)
    with pytest.raises(LLMBudgetExceeded):
        # `retryable` only lists `_Boom`, so `LLMBudgetExceeded` isn't caught.
        await retry.execute(boom, retryable=(_Boom,))
    assert attempts["n"] == 1
    assert attempts.get("sleep", 0) == 0


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match=r"max_attempts must be"):
        ExponentialBackoffRetry(max_attempts=0)
